"""Read account allowances; no model calls and no dependency on a cserver app.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""
import base64
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

import yaml

from cmeta.utils.common import compare_versions
from cmeta.utils.files import PathLock
from task_c36be4b9314a45e0.api.ctask import InitCTask, drop_provider_variables

HARNESSES = ('codex', 'claude', 'opencode', 'vibe', 'gemini', 'antigravity', 'openclaw', 'hermes')
CLAUDE_URL = 'https://api.anthropic.com/api/oauth/usage'
CLAUDE_PROFILE_URL = 'https://api.anthropic.com/api/oauth/profile'
OPENAI_URL = 'https://chatgpt.com/backend-api/wham/usage'
PAGES = {'claude': 'https://claude.ai/settings/usage', 'openai': 'https://chatgpt.com/codex/settings/usage',
         'vibe': 'https://admin.mistral.ai/usage', 'opencode': 'https://opencode.ai/docs/providers/',
         'gemini': 'https://geminicli.com/docs/resources/quota-and-pricing/',
         'antigravity': 'https://antigravity.google/docs/plans',
         'openclaw': 'https://docs.openclaw.ai/concepts/usage-tracking',
         'hermes': 'https://hermes-agent.nousresearch.com/docs/'}

# As run-ai: a machine's general default gateway (config run_ai_gateway) is for these harnesses; others run on their
# login. A gateway that passes the harness's own login on (ai.gateway auth.header "login") serves only LOGIN_HARNESSES.
GATEWAY_HARNESSES = ('claude', 'codex', 'opencode')
LOGIN_HARNESSES = ('claude', 'codex')
SET_AI_GATEWAY = 'set-ai-gateway,e10aa0a00edd4a2c'
GATEWAY_CATEGORY = 'ai.gateway,ae1ae632e0ec4f75'
SETUP_TASK = 'setup,a2f9b61079ce4333'

# A harness's version comes from cMeta's tool detection, which starts the program (seconds): it is asked again when
# the program's file changed, else after this many seconds; a harness that was not found is looked for again then.
VERSION_RECHECK = 3600


def harness_ways():
    """The `harnesses` of this task's _desc.yaml: per harness, the cMeta tool that finds it and the ways its account
    is read, the newest first. A harness that changes gets a way ADDED there (and its reader in _selection); the
    ways that exist stay, for the machines that still run an older harness."""
    with open(Path(__file__).parent / '_desc.yaml', encoding='utf-8') as f:
        declared = (yaml.safe_load(f) or {}).get('harnesses')
    return declared if isinstance(declared, dict) else {}


def choose_way(ways, version):
    """The way an account is read for a harness's version -> (the way, a note for the reader). `ways`: the harness's
    entries of _desc.yaml, the newest first; the first whose `since` is not above the version is taken (no `since`:
    every version). A version that is not known (the harness is not found on this machine) or that the engine does
    not compare takes the newest way, and the note says so. A version below every `since`: (None, why) - the account
    is not read, the run is not stopped."""
    if not ways:
        return None, ''
    if not version:
        return ways[0], 'The version of this harness is not known on this machine: the newest way of reading its account is used.'
    for way in ways:
        since = str(way.get('since') or '')
        if not since:
            return way, ''
        r = compare_versions(str(version), since)
        if r.get('return'):
            return ways[0], 'The version of this harness (%s) is not one cMeta compares: the newest way of reading its account is used.' % str(version)[:40]
        if r['comparison'] in ('>', '='):
            return way, ''
    return None, ('This harness is version %s; its account can be read from version %s on. AI requests can still be tried.' %
                  (str(version)[:40], str(ways[-1].get('since'))[:40]))


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
    def __init__(self, reason, message, retry=30, account=None):
        self.reason, self.message, self.retry = reason, message, retry
        self.account = account or {}


def get_usage(url, token, account_id=''):
    # Fixed provider endpoints only; never a URL supplied by a web request/config.
    assert url in (CLAUDE_URL, CLAUDE_PROFILE_URL, OPENAI_URL)
    headers = {'Authorization': 'Bearer ' + token, 'User-Agent': 'cmeta-ai-account-status/1.0'}
    if url in (CLAUDE_URL, CLAUDE_PROFILE_URL):
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
        try:
            exc.close()  # Its response body; Python 3.9/3.10 cannot close an error made without one (fp=None).
        except Exception:
            pass
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


def display_text(value):
    """Bounded display text, never a credential or an arbitrary provider response."""
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= 254 and not any(ord(c) < 32 for c in value) else ''


def api_status():
    return {'available': False, 'account': {'authType': 'api', 'type': 'API'}, 'windows': [],
            'reason': 'api', 'message': 'API usage: subscription quota does not apply. Check the provider or gateway billing page.'}


def claude_usage(token, plan='', include_identity=True):
    account = {'type': 'Claude personal login', 'planType': plan, 'authType': 'login'}
    if include_identity:
        try:
            # The local oauthAccount cache can belong to a previous login. Ask the
            # profile endpoint with exactly the bearer used for this quota request.
            profile = get_usage(CLAUDE_PROFILE_URL, token).get('account') or {}
            profile = profile if isinstance(profile, dict) else {}
            for key in ('email', 'display_name'):
                value = display_text(profile.get(key))
                if value:
                    account['email' if key == 'email' else 'username'] = value
        except StatusError:
            pass  # Profile scope/failure must not break an otherwise valid quota.
    try:
        raw = get_usage(CLAUDE_URL, token)
    except StatusError as exc:
        exc.account = account
        raise
    windows = []
    for key, minutes, label in (('five_hour', 300, '5h'), ('seven_day', 10080, '7d'),
                                ('seven_day_sonnet', 10080, '7d Sonnet'), ('seven_day_opus', 10080, '7d Opus'),
                                ('seven_day_oauth_apps', 10080, '7d OAuth apps'), ('seven_day_cowork', 10080, '7d Cowork')):
        value = raw.get(key)
        if isinstance(value, dict):
            parsed = window(value.get('utilization'), minutes, value.get('resets_at'), label)
            if parsed:
                windows.append(parsed)
    return {'available': bool(windows), 'account': account,
            'windows': windows, 'source': 'claude-oauth-usage',
            'message': '' if windows else 'Claude did not report active quota windows for this account.'}


def openai_usage(token, account_id='', include_identity=True):
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
    account = {'type': 'OpenCode OpenAI login', 'authType': 'login', 'planType': plan[:80] if isinstance(plan, str) else ''}
    if include_identity:
        # Display-only claim from the same access token just accepted by OpenAI.
        # Never use it for authentication or fall back to Codex's separate login.
        try:
            part = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))) if len(part) < 16384 else {}
            profile = claims.get('https://api.openai.com/profile') or {}
            email = display_text(profile.get('email') or claims.get('email'))
            if email:
                account['email'] = email
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
    return {'available': bool(windows), 'account': account,
            'windows': windows, 'credits': credits(raw.get('credits')), 'source': 'openai-usage',
            'message': '' if windows else 'OpenAI did not report subscription quota windows for this OpenCode login.'}


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def _harness_version(self, harness, tool, folder, now):
        """The installed harness's version and program as cMeta's own tool detection gives them (the setup task of
        its tool artifact; nothing is installed) -> (version or '', program or ''). Kept per harness in the folder
        harness/ of the task's log artifact (no credential is in it: the tool, the program's path, its file's
        identity, the version); asked again when the program's file changed, or after VERSION_RECHECK."""
        record = folder / 'harness' / (harness + '.json')
        try:
            saved = json.loads(record.read_text(encoding='utf-8')) if record.is_file() and record.stat().st_size <= 65536 else {}
        except (OSError, ValueError):
            saved = {}
        saved = saved if isinstance(saved, dict) else {}
        if saved.get('tool') == tool and number(saved.get('next_check')) and saved['next_check'] > now:
            program = saved.get('path') if isinstance(saved.get('path'), str) else ''
            if not program:
                return '', ''
            try:
                stat = os.stat(program)
                if saved.get('file') == [os.path.realpath(program), stat.st_mtime_ns, stat.st_size]:
                    return (saved['version'] if isinstance(saved.get('version'), str) else ''), program
            except OSError:
                pass
        found = self.cm.access(dict(category=self.cmeta['uses_categories']['task'], command='run', arg1=SETUP_TASK,
            name=tool, skip_install=True, cache=False, store_global=False, quiet=True, con=False))
        program = found.get('path') if not found.get('return') and isinstance(found.get('path'), str) else ''
        version = found.get('version') if program and isinstance(found.get('version'), str) and len(found['version']) <= 80 else ''
        saved = {'tool': tool, 'path': program, 'version': version, 'next_check': now + VERSION_RECHECK}
        if program:
            try:
                stat = os.stat(program)
                saved['file'] = [os.path.realpath(program), stat.st_mtime_ns, stat.st_size]
            except OSError:
                saved['file'] = None
        record.parent.mkdir(exist_ok=True)
        temporary = record.with_suffix('.%d.tmp' % os.getpid())
        temporary.write_text(json.dumps(saved, allow_nan=False), encoding='utf-8')
        os.replace(temporary, record)
        return version, program

    def _codex(self, folder, executable=''):
        executable = executable or shutil.which('codex')
        if not executable:
            setup = self.cm.access(dict(category=self.cmeta['uses_categories']['task'], command='run',
                arg1='setup,a2f9b61079ce4333', name='codex,cdbf5f6e6882460f', skip_install=True,
                cache=False, store_global=False, quiet=True, con=False))
            executable = setup.get('path') if not setup.get('return') else None
        if not executable:
            raise StatusError('not_installed', 'Codex is not installed on this server.')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        env = dict(os.environ, CODEX_SQLITE_HOME=str(folder / 'state'))
        drop_provider_variables('codex', login=True, env=env)
        proc = subprocess.Popen([executable, 'app-server', '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=folder,
            env=env, **options)
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
            shown = {k: display_text(v) for k, v in account.items() if k in ('type', 'email', 'planType') and display_text(v)}
            if account.get('type') in ('apiKey', 'api_key'):
                return dict(api_status(), source='codex-app-server')
            if not account:
                raise StatusError('login_required', 'Codex has no active account on this server.')
            shown['authType'] = 'login'
            try:
                send({'id': 3, 'method': 'account/rateLimits/read'})
                limits = receive(3)
            except (OSError, ValueError, TimeoutError, queue.Empty):
                raise StatusError('quota_unavailable', 'Codex account is connected, but its quota could not be read.', account=shown) from None
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

    def _openclaw(self, folder, provider, executable=''):
        executable = executable or shutil.which('openclaw')
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
        if shown.get('email'):
            shown['authType'] = 'login'
        elif raw.get('authType') in ('api', 'apiKey', 'api_key'):
            shown['authType'] = 'api'
        return {'available': bool(windows), 'account': shown, 'windows': windows, 'source': 'openclaw-status',
                'message': '' if windows else 'OpenClaw did not report quota windows for this provider.'}

    def _selection(self, harness, model, include_identity=True, way='', executable=''):
        """Read only this harness's credentials; never substitute another harness's account. `way`: the name of the
        way chosen for the harness's version ('' = the newest one declared for the harness); `executable`: the
        harness's program as cMeta found it, for the ways that start it."""
        if not way:
            declared = (harness_ways().get(harness) or {}).get('ways') or []
            way = str(declared[0].get('name') or '') if declared else ''
        if way == 'claude-oauth-usage':
            token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
            data = {}
            if not token:
                data = read_json(Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / '.credentials.json').get('claudeAiOauth') or {}
                token = data.get('accessToken')
            if not isinstance(token, str) or not token:
                raise StatusError('login_required', 'No readable Claude personal login on this server. API keys do not expose the Claude subscription allowance; use Claude Usage for that account.', 30)
            plan = data.get('subscriptionType')
            return token, lambda folder: claude_usage(token, plan[:80] if isinstance(plan, str) else '', include_identity=include_identity), PAGES['claude']
        if way == 'opencode-auth-file':
            provider = model.split('/', 1)[0] if '/' in model else ''
            if not provider:
                raise StatusError('provider_required', 'OpenCode quota belongs to its selected provider. Select an openai/… or anthropic/… model with OAuth login for automatic quota; other providers report usage in their own dashboard.', 120)
            path = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode/auth.json'
            data = read_json(path).get(provider) or {}
            if isinstance(data, dict) and data.get('type') == 'api' and isinstance(data.get('key'), str) and data['key']:
                return data['key'], lambda folder: api_status(), PAGES.get(provider, PAGES['opencode'])
            if not isinstance(data, dict) or data.get('type') != 'oauth' or not isinstance(data.get('access'), str):
                raise StatusError('provider_login_required', 'No readable OpenCode %s OAuth login. API keys, plugins and newer credential stores need their provider usage page; another harness login is never substituted.' % provider, 120)
            token = data['access']
            if provider == 'anthropic':
                return token, lambda folder: claude_usage(token, include_identity=include_identity), PAGES['claude']
            if provider != 'openai':
                raise StatusError('not_supported', 'The selected OpenCode OAuth provider has no connected account-status adapter.', 120)
            account_id = data.get('accountId')
            account_id = account_id if isinstance(account_id, str) and len(account_id) <= 200 else ''
            return token + account_id, lambda folder: openai_usage(token, account_id, include_identity=include_identity), PAGES['openai']
        if way == 'codex-app-server':
            home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
            # A login switch in the same CODEX_HOME must invalidate the quota cache.
            fingerprint = hashlib.sha256()
            for name in ('auth.json', 'config.toml'):
                path = home / name
                if path.is_file() and path.stat().st_size <= 1_048_576:
                    fingerprint.update(path.read_bytes())
            return str(home) + fingerprint.hexdigest(), lambda folder: self._codex(folder, executable), PAGES['openai']
        if way == 'openclaw-status':
            provider = model.split('/', 1)[0] if '/' in model else ''
            if not provider:
                raise StatusError('provider_required', 'Select an explicit provider/model to read its OpenClaw quota. The default provider is not guessed.')
            return os.environ.get('OPENCLAW_STATE_DIR', str(Path.home() / '.openclaw')), lambda folder: self._openclaw(folder, provider, executable), PAGES['openclaw']
        if way:
            raise StatusError('not_supported', 'This copy of the task has no reader for the way "%s" of its _desc.yaml.' % way[:60], 120)
        messages = {
            'vibe': 'Vibe allowance is managed by Mistral. This adapter does not have a reliable read-only quota interface for the installed Vibe login; open Mistral Usage. Per-run tokens and cost remain available when reported.',
            'gemini': 'Gemini quota depends on Google login, Code Assist licence, API key or Vertex project. Automatic account quota is not connected here; use Gemini /stats or the quota page for the same account/project.',
            'antigravity': 'Antigravity model allowances are shown in its account/model quota view. No independent read-only quota adapter is connected here.',
            'hermes': 'Hermes uses several providers. Its per-run token/cost statistics are not a remaining subscription allowance; check the selected provider account.',
        }
        raise StatusError('not_supported', messages.get(harness, 'Automatic quota reporting is not configured for this harness.'), 120)

    def _machine_gateway(self, harness):
        """The gateway a run-ai run without a gateway flag takes on this machine (set-ai-gateway's choice, the general
        default only for GATEWAY_HARNESSES) -> (alias or 'login', how). No gateways here (a trimmed copy): login."""
        r = self.cm.access(dict(category=self.cmeta['uses_categories']['task'], command='run', arg1=SET_AI_GATEWAY,
            harness=harness, connect=False, quiet=True, con=False))
        if r.get('return') == 16:
            return 'login', 'no AI gateways on this machine'
        if r.get('return'):
            raise StatusError('gateway_unavailable', "This machine's default AI gateway could not be read: %s" % display_text(str(r.get('error', ''))[:250]), 30)
        if r['gateway'] != 'login' and r.get('general') and harness not in GATEWAY_HARNESSES:
            return 'login', 'its own login: %s takes no gateway' % harness
        return r['gateway'], r.get('how', '')

    def _gateway_route(self, harness, gateway):
        """What a gateway means for the account: None = an account of its own (a key, a local server), or
        {'own_login': True} = it passes this harness's own login on, whose allowance is then the one used."""
        r = self.cm.access(dict(category=GATEWAY_CATEGORY, command='list', arg1=gateway, quiet=True, con=False))
        rows = (r.get('gateways') or []) if not r.get('return') else []
        row = rows[0] if len(rows) == 1 else None
        if row is None:
            return None, 'The AI gateway %s is not on this machine: a run with it stops before it starts.' % gateway
        if str(row.get('auth') or '').split(' ')[0] == 'login':
            if harness in LOGIN_HARNESSES:
                return {'own_login': True}, ''
            return None, 'The AI gateway %s passes a login on for %s only.' % (gateway, ' and '.join(LOGIN_HARNESSES))
        if str(row.get('auth') or 'none') == 'none':
            return None, 'Through the AI gateway %s, without a key: no account allowance applies.' % gateway
        return None, 'Through the AI gateway %s with its key: its billing applies, not a subscription quota.' % gateway

    def _display(self, out, show_identity):
        out = dict(out, identity_visible=show_identity)
        account = dict(out.get('account') or {})
        if show_identity:
            label = display_text(account.get('email')) or display_text(account.get('username'))
            kind = account.get('authType', 'unknown')
            out['identity'] = {'kind': kind, 'label': 'API' if kind == 'api' else label or ('Login identity unavailable' if kind == 'login' else 'Account unknown')}
        else:
            account.pop('email', None)
            account.pop('username', None)
            out.pop('identity', None)
        out['account'] = account
        return out

    def run(self, ctx: dict, harness: str = 'codex', gateway: str = 'login', model: str = '', client_script: bool = False, show_identity: bool = None,
            machine_default: bool = False):
        """Return safe normalized account/windows/credits, or the optional shared browser component.
        gateway: login (the harness's own login), or an ai.gateway alias - one that passes the login on (local-login)
        reads that login. machine_default: an empty gateway is the one a run-ai run without a gateway flag takes here."""
        if client_script:
            return {'return': 0, 'script': (Path(__file__).parent / 'files/js/account-status.js').read_text(encoding='utf-8')}
        if not all(isinstance(v, str) and len(v) <= 300 for v in (harness, gateway, model)):
            return {'return': 1, 'error': 'Harness, gateway and model must be short text values.'}
        if show_identity is None:
            config = self.cm.access(dict(category=self.cmeta['uses_categories']['config'], command='get',
                arg1='task-ai-account-status', quiet=True, con=False))
            if config.get('return'):
                return {'return': 1, 'error': 'The account-status display configuration could not be read.'}
            # /settings and many cMeta configs use textual yes/no values. Keep
            # explicit task arguments strict, but accept the config convention.
            # (The config's value has its own name: show_identity is a bool parameter.)
            configured = config.get('config_cmeta', {}).get('show_identity', True)
            if isinstance(configured, str):
                text = configured.strip().lower()
                if text in ('yes', 'true', 'on', '1'):
                    configured = True
                elif text in ('no', 'false', 'off', '0'):
                    configured = False
            show_identity = configured
        if not isinstance(show_identity, bool):
            return {'return': 1, 'error': 'show_identity must be true or false.'}
        harness = {'agy': 'antigravity', 'claude-code': 'claude'}.get(harness, harness)
        base = {'return': 0, 'harness': harness, 'available': False, 'windows': [], 'credits': None,
                'checked_at': time.time(), 'usage_url': PAGES.get(harness, '')}
        if not isinstance(machine_default, bool):
            return {'return': 1, 'error': 'machine_default must be true or false.'}
        gateway = gateway.strip()
        try:
            if not gateway and machine_default:
                gateway, how = self._machine_gateway(harness)
                base['gateway_how'] = how
        except StatusError as exc:
            return self._display(dict(base, reason=exc.reason, message=exc.message), show_identity)
        base['gateway'] = gateway or 'login'
        if gateway not in ('', 'login'):
            route, note = self._gateway_route(harness, gateway)
            if not route:
                return self._display(dict(base, **dict(api_status(), reason='gateway', message=note)), show_identity)
            base.update(route)
        try:
            root = self.cm.access(dict(category=self.cmeta['uses_categories']['log'], command='get', arg1='local:ai-account-status', yaml=True, quiet=True, con=False))
            if root.get('return'):
                raise StatusError('storage_unavailable', 'The local account-status cache could not be opened.')
            folder = Path(root['artifact']['path'])
            # The way this harness's account is read follows its version, as cMeta's tool detection gives it
            declared = harness_ways().get(harness) or {}
            way, executable = '', ''
            if declared.get('ways'):
                version, executable = self._harness_version(harness, str(declared.get('tool') or harness), folder, base['checked_at'])
                chosen, note = choose_way(declared['ways'], version)
                base['harness_version'] = version
                if chosen is None:
                    raise StatusError('harness_version', note, 120)
                way = str(chosen.get('name') or '')
                base['mechanism'] = way
                if note:
                    base['mechanism_note'] = note
            identity, fetch, page = self._selection(harness, model, include_identity=show_identity, way=way, executable=executable)
            base['usage_url'] = page
            key = hashlib.sha256(('v2\0' + str(show_identity) + '\0' + harness + '\0' + model.split('/')[0] + '\0' + identity).encode()).hexdigest()
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
                    return self._display(dict(base, **saved['result'], cached=True), show_identity)
                try:
                    result = dict(fetch(folder), checked_at=now)
                    delay = 120
                except StatusError as exc:
                    result = {'available': False, 'windows': [], 'message': exc.message, 'reason': exc.reason, 'checked_at': now}
                    if exc.account:
                        result['account'] = exc.account
                    delay = exc.retry
                    old = saved.get('result', {})
                    if old.get('available') and now - old.get('checked_at', 0) < 900:
                        result.update(account=result.get('account') or old.get('account', {}), windows=old.get('windows', []), credits=old.get('credits'), checked_at=old['checked_at'], stale=True)
                if not show_identity and result.get('account'):
                    result = self._display(result, False)
                payload = {'next_check': now + delay, 'result': result}
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
                os.replace(temporary, path)
                return self._display(dict(base, **result, cached=False), show_identity)
            finally:
                lock.release()
        except StatusError as exc:
            return self._display(dict(base, reason=exc.reason, message=exc.message, account=exc.account), show_identity)
        except (OSError, ValueError, TypeError, TimeoutError, queue.Empty, subprocess.SubprocessError):
            return self._display(dict(base, reason='unavailable', message='Account quota could not be read on this server. AI requests can still be tried.'), show_identity)
