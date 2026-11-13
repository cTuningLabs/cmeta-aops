"""Read account allowances; no model calls and no dependency on a cserver app.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cmeta.utils.files import PathLock
from task_c36be4b9314a45e0.api.ctask import InitCTask

HARNESSES = ('codex', 'claude', 'opencode', 'vibe', 'gemini', 'antigravity', 'openclaw', 'hermes')
CLAUDE_URL = 'https://api.anthropic.com/api/oauth/usage'
OPENAI_URL = 'https://chatgpt.com/backend-api/wham/usage'
PAGES = {'claude': 'https://claude.ai/settings/usage', 'openai': 'https://chatgpt.com/codex/settings/usage',
         'vibe': 'https://admin.mistral.ai/usage', 'opencode': 'https://opencode.ai/docs/providers/',
         'gemini': 'https://geminicli.com/docs/resources/quota-and-pricing/',
         'antigravity': 'https://antigravity.google/docs/plans',
         'openclaw': 'https://docs.openclaw.ai/concepts/usage-tracking',
         'hermes': 'https://hermes-agent.nousresearch.com/docs/'}


def read_json(path):
    if not path.is_file():
        return {}
    if path.stat().st_size > 1_048_576:
        raise ValueError('Oversized status file')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    return data if isinstance(data, dict) else {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def window(used, minutes, reset=None, label=''):
    if not number(used) or used < 0 or used > 100:
        return None
    out = {'usedPercent': used, 'windowDurationMins': minutes}
    if isinstance(reset, str):
        try:
            stamp = datetime.fromisoformat(reset.replace('Z', '+00:00'))
            reset = stamp.timestamp() if stamp.tzinfo else None
        except ValueError:
            reset = None
    if number(reset) and reset > 0:
        out['resetsAt'] = reset
    if label:
        out['label'] = label
    return out


def credits(raw):
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if k in ('hasCredits', 'unlimited', 'balance') and
            (v is None or isinstance(v, bool) or number(v) or isinstance(v, str) and len(v) <= 80)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward an authorization header to another host.


class StatusError(Exception):
    def __init__(self, reason, message, retry=30):
        self.reason, self.message, self.retry = reason, message, retry


def get_usage(url, token, account_id=''):
    # URLs come only from these two fixed adapters, never from a web request/config.
    assert url in (CLAUDE_URL, OPENAI_URL)
    headers = {'Authorization': 'Bearer ' + token, 'User-Agent': 'cmeta-ai-account-status/1.0'}
    if url == CLAUDE_URL:
        headers['anthropic-beta'] = 'oauth-2025-04-20'
    if account_id:
        headers['ChatGPT-Account-Id'] = account_id
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=10) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError('Oversized provider response')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Invalid provider response')
        return value
    except HTTPError as exc:
        exc.close()
        if exc.code == 401:
            raise StatusError('login_expired', 'The server login expired. Run this harness once to refresh its login, then check again.', 30) from None
        if exc.code == 403:
            raise StatusError('scope_required', 'This login cannot read account usage. A full personal login with profile access is needed; an inference-only setup token is insufficient.', 120) from None
        if exc.code == 429:
            try:
                delay = max(120, min(3600, int(exc.headers.get('retry-after', 300))))
            except (TypeError, ValueError):
                delay = 300
            raise StatusError('rate_limited', 'The provider temporarily rate-limited quota checks. The next check will retry automatically after the cooldown.', delay) from None
        raise StatusError('provider_error', 'The provider could not return account usage (HTTP %s).' % exc.code) from None
    except (OSError, URLError, ValueError):
        raise StatusError('provider_unreachable', 'Account usage could not be read from the provider. AI requests can still be tried.') from None


def claude_usage(token, plan=''):
    raw = get_usage(CLAUDE_URL, token)
    windows = []
    for key, minutes, label in (('five_hour', 300, '5h'), ('seven_day', 10080, '7d'),
                                ('seven_day_sonnet', 10080, '7d Sonnet'), ('seven_day_opus', 10080, '7d Opus'),
                                ('seven_day_oauth_apps', 10080, '7d OAuth apps'), ('seven_day_cowork', 10080, '7d Cowork')):
        value = raw.get(key)
        if isinstance(value, dict):
            parsed = window(value.get('utilization'), minutes, value.get('resets_at'), label)
            if parsed:
                windows.append(parsed)
    return {'available': bool(windows), 'account': {'type': 'Claude personal login', 'planType': plan},
            'windows': windows, 'source': 'claude-oauth-usage',
            'message': '' if windows else 'Claude did not report active quota windows for this account.'}


def openai_usage(token, account_id=''):
    raw = get_usage(OPENAI_URL, token, account_id)
    rates = raw.get('rate_limit') or {}
    windows = []
    for key in ('primary_window', 'secondary_window'):
        value = rates.get(key)
        if isinstance(value, dict):
            seconds = value.get('limit_window_seconds')
            parsed = window(value.get('used_percent'), seconds / 60 if number(seconds) and seconds > 0 else None, value.get('reset_at'))
            if parsed:
                windows.append(parsed)
    plan = raw.get('plan_type')
    return {'available': bool(windows), 'account': {'type': 'OpenCode OpenAI login', 'planType': plan[:80] if isinstance(plan, str) else ''},
            'windows': windows, 'credits': credits(raw.get('credits')), 'source': 'openai-usage',
            'message': '' if windows else 'OpenAI did not report subscription quota windows for this OpenCode login.'}


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def _codex(self, folder):
        executable = shutil.which('codex')
        if not executable:
            setup = self.cm.access(dict(category=self.cmeta['uses_categories']['task'], command='run',
                arg1='setup,a2f9b61079ce4333', name='codex,cdbf5f6e6882460f', skip_install=True,
                cache=False, store_global=False, quiet=True, con=False))
            executable = setup.get('path') if not setup.get('return') else None
        if not executable:
            raise StatusError('not_installed', 'Codex is not installed on this server.')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        proc = subprocess.Popen([executable, 'app-server', '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=folder,
            env=dict(os.environ, CODEX_SQLITE_HOME=str(folder / 'state')), **options)
        messages = queue.Queue()
        def reader():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass
            messages.put({'eof': True})
        threading.Thread(target=reader, daemon=True).start()
        deadline = time.monotonic() + 18
        def send(value):
            proc.stdin.write((json.dumps(value) + '\n').encode('utf-8'))
            proc.stdin.flush()
        def receive(identifier):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                item = messages.get(timeout=remaining)
                if not isinstance(item, dict):
                    continue
                if item.get('eof') or item.get('id') == identifier and item.get('error'):
                    raise ValueError('Account status unavailable')
                if item.get('id') == identifier:
                    return item.get('result') or {}
        try:
            send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'cmeta_ai_status', 'version': '1.0'}}})
            receive(1)
            send({'method': 'initialized', 'params': {}})
            send({'id': 2, 'method': 'account/read', 'params': {'refreshToken': False}})
            account = receive(2).get('account') or {}
            send({'id': 3, 'method': 'account/rateLimits/read'})
            limits = receive(3)
            shown = {k: v for k, v in account.items() if k in ('type', 'email', 'planType') and isinstance(v, str) and len(v) <= 254}
            rates = limits.get('rateLimits') or {}
            windows = [window(w.get('usedPercent'), w.get('windowDurationMins'), w.get('resetsAt'))
                       for w in (rates.get('primary'), rates.get('secondary')) if isinstance(w, dict)]
            windows = [w for w in windows if w]
            return {'available': bool(account), 'account': shown, 'windows': windows,
                    'credits': credits(rates.get('credits') or limits.get('credits')), 'source': 'codex-app-server',
                    'message': '' if windows else 'Codex did not report subscription quota windows for this login.'}
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            proc.stdin.close()
            proc.stdout.close()

    def _openclaw(self, folder, provider):
        executable = shutil.which('openclaw')
        if not executable:
            setup = self.cm.access(dict(category=self.cmeta['uses_categories']['task'], command='run',
                arg1='setup,a2f9b61079ce4333', name='openclaw,1776c76162b14545', skip_install=True,
                cache=False, store_global=False, quiet=True, con=False))
            executable = setup.get('path') if not setup.get('return') else None
        if not executable:
            raise StatusError('not_installed', 'OpenClaw is not installed on this server. Its status --usage command can report provider quota when configured.')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        try:
            result = subprocess.run([executable, 'status', '--usage', '--json'], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, cwd=folder, **options)
        except subprocess.TimeoutExpired:
            raise StatusError('status_timeout', 'OpenClaw usage check timed out. Check openclaw status --usage on this server; AI requests can still be tried.', 120) from None
        # The CLI status contains unrelated settings; none are returned or cached.
        if result.returncode or len(result.stdout) > 1_048_576:
            raise StatusError('provider_unreachable', 'OpenClaw could not read provider usage. Check openclaw status --usage on this server.')
        raw = json.loads(result.stdout)
        summaries = (raw.get('usage') or {}).get('providers') or []
        selected = [p for p in summaries if isinstance(p, dict) and p.get('provider') == provider]
        if len(selected) != 1 or selected[0].get('error'):
            raise StatusError('provider_required', 'OpenClaw did not return an unambiguous quota for the selected provider. Check its account/profile in openclaw status --usage.')
        raw = selected[0]
        windows = []
        for value in raw.get('windows') or []:
            if not isinstance(value, dict):
                continue
            label = value.get('label')
            label = label[:80] if isinstance(label, str) else 'Quota'
            reset = value.get('resetAt')
            # OpenClaw's JavaScript timestamps use milliseconds.
            reset = reset / 1000 if number(reset) and reset > 100_000_000_000 else reset
            parsed = window(value.get('usedPercent'), None, reset, label)
            if parsed:
                windows.append(parsed)
        shown = {'type': 'OpenClaw ' + provider}
        for source, target in (('accountEmail', 'email'), ('plan', 'planType')):
            if isinstance(raw.get(source), str) and len(raw[source]) <= 254:
                shown[target] = raw[source]
        return {'available': bool(windows), 'account': shown, 'windows': windows, 'source': 'openclaw-status',
                'message': '' if windows else 'OpenClaw did not report quota windows for this provider.'}

    def _selection(self, harness, model):
        """Read only this harness's credentials; never substitute another harness's account."""
        if harness == 'claude':
            token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
            data = {}
            if not token:
                data = read_json(Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / '.credentials.json').get('claudeAiOauth') or {}
                token = data.get('accessToken')
            if not isinstance(token, str) or not token:
                raise StatusError('login_required', 'No readable Claude personal login on this server. API keys do not expose the Claude subscription allowance; use Claude Usage for that account.', 30)
            plan = data.get('subscriptionType')
            return token, lambda folder: claude_usage(token, plan[:80] if isinstance(plan, str) else ''), PAGES['claude']
        if harness == 'opencode':
            provider = model.split('/', 1)[0] if '/' in model else ''
            if provider not in ('openai', 'anthropic'):
                raise StatusError('provider_required', 'OpenCode quota belongs to its selected provider. Select an openai/… or anthropic/… model with OAuth login for automatic quota; other providers report usage in their own dashboard.', 120)
            path = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode/auth.json'
            data = read_json(path).get(provider) or {}
            if not isinstance(data, dict) or data.get('type') != 'oauth' or not isinstance(data.get('access'), str):
                raise StatusError('provider_login_required', 'No readable OpenCode %s OAuth login. API keys, plugins and newer credential stores need their provider usage page; another harness login is never substituted.' % provider, 120)
            token = data['access']
            if provider == 'anthropic':
                return token, lambda folder: claude_usage(token), PAGES['claude']
            account_id = data.get('accountId')
            account_id = account_id if isinstance(account_id, str) and len(account_id) <= 200 else ''
            return token + account_id, lambda folder: openai_usage(token, account_id), PAGES['openai']
        if harness == 'codex':
            return os.environ.get('CODEX_HOME', str(Path.home() / '.codex')), self._codex, PAGES['openai']
        if harness == 'openclaw':
            provider = model.split('/', 1)[0] if '/' in model else ''
            if not provider:
                raise StatusError('provider_required', 'Select an explicit provider/model to read its OpenClaw quota. The default provider is not guessed.')
            return os.environ.get('OPENCLAW_STATE_DIR', str(Path.home() / '.openclaw')), lambda folder: self._openclaw(folder, provider), PAGES['openclaw']
        messages = {
            'vibe': 'Vibe allowance is managed by Mistral. This adapter does not have a reliable read-only quota interface for the installed Vibe login; open Mistral Usage. Per-run tokens and cost remain available when reported.',
            'gemini': 'Gemini quota depends on Google login, Code Assist licence, API key or Vertex project. Automatic account quota is not connected here; use Gemini /stats or the quota page for the same account/project.',
            'antigravity': 'Antigravity model allowances are shown in its account/model quota view. No independent read-only quota adapter is connected here.',
            'hermes': 'Hermes uses several providers. Its per-run token/cost statistics are not a remaining subscription allowance; check the selected provider account.',
        }
        raise StatusError('not_supported', messages.get(harness, 'Automatic quota reporting is not configured for this harness.'), 120)

    def run(self, ctx: dict, harness: str = 'codex', gateway: str = 'login', model: str = '', client_script: bool = False):
        """Return safe normalized account/windows/credits, or the optional shared browser component."""
        if client_script:
            return {'return': 0, 'script': (Path(__file__).parent / 'files/js/account-status.js').read_text(encoding='utf-8')}
        if not all(isinstance(v, str) and len(v) <= 300 for v in (harness, gateway, model)):
            return {'return': 1, 'error': 'Harness, gateway and model must be short text values.'}
        harness = {'agy': 'antigravity', 'claude-code': 'claude'}.get(harness, harness)
        base = {'return': 0, 'harness': harness, 'available': False, 'windows': [], 'credits': None,
                'checked_at': time.time(), 'usage_url': PAGES.get(harness, '')}
        if gateway not in ('', 'login'):
            return dict(base, reason='gateway', message='A gateway is selected. Quota belongs to that gateway/provider; the server personal-login allowance does not apply.')
        try:
            identity, fetch, page = self._selection(harness, model)
            base['usage_url'] = page
            root = self.cm.access(dict(category=self.cmeta['uses_categories']['log'], command='get', arg1='local:ai-account-status', yaml=True, quiet=True, con=False))
            if root.get('return'):
                raise StatusError('storage_unavailable', 'The local account-status cache could not be opened.')
            folder = Path(root['artifact']['path'])
            key = hashlib.sha256((harness + '\0' + model.split('/')[0] + '\0' + identity).encode()).hexdigest()
            path = folder / (key + '.json')
            lock = PathLock(str(path) + '.lock')
            lock.acquire(timeout=25)
            try:
                try:
                    saved = read_json(path)
                except (OSError, ValueError):
                    saved = {}
                now = time.time()
                if saved.get('next_check', 0) > now and isinstance(saved.get('result'), dict):
                    return dict(base, **saved['result'], cached=True)
                try:
                    result = dict(fetch(folder), checked_at=now)
                    delay = 120
                except StatusError as exc:
                    result = {'available': False, 'windows': [], 'message': exc.message, 'reason': exc.reason, 'checked_at': now}
                    delay = exc.retry
                    old = saved.get('result', {})
                    if old.get('available') and now - old.get('checked_at', 0) < 900:
                        result.update(account=old.get('account', {}), windows=old.get('windows', []), credits=old.get('credits'), checked_at=old['checked_at'], stale=True)
                payload = {'next_check': now + delay, 'result': result}
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
                os.replace(temporary, path)
                return dict(base, **result, cached=False)
            finally:
                lock.release()
        except StatusError as exc:
            return dict(base, reason=exc.reason, message=exc.message)
        except (OSError, ValueError, TypeError, TimeoutError, queue.Empty, subprocess.SubprocessError):
            return dict(base, reason='unavailable', message='Account quota could not be read on this server. AI requests can still be tried.')
