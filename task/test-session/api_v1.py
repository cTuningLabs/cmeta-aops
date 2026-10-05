"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Test sessions: one dated place per test, build or benchmark, so tests leave no folders in
random places and their history stays when the sandbox goes (see _desc.yaml for the commands).
All sessions live in two cMeta artifacts of the local repository (--repo, --artifact), in a
folder per day and a subfolder per session, so a session adds no index entry; the session id
<YYYYMMDD>/<HHMM>.<type> is that path:

    log::cmeta-aops-test-sessions/<YYYYMMDD>/<HHMM>.<type>/   the record (kept): session.md,
                                                               session.json, attachments/
    tmp::cmeta-aops-test-sessions/<YYYYMMDD>/<HHMM>.<type>/   the sandbox (deletable)

A record holds the host, cMeta and the repositories (branch, commit, uncommitted changes), the
agent with its model, reasoning effort and session, the command, the notes, the results and the
costs: wall time, sandbox size, and the agent's tokens and cost when they are given.
"""

import datetime
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

ARTIFACT = 'cmeta-aops-test-sessions'  # the log artifact (records) and the tmp artifact (sandboxes)
TAG = 'test-session'
SESSION_ENV = 'CMETA_TEST_SESSION'     # the session of a shell: "cx program run" attaches its provenance record there and runs strict
OLD_PREFIX = 'cmeta-tests-'            # the folders before 0.42.0: <CMETA_HOME>/{tmp,log}/cmeta-tests-<YYYYMMDD>/
MAX_KEEP_MIB = 1024                    # finish removes a larger sandbox (--keep keeps it)
MAX_ATTACH_MIB = 20                    # a larger file is not copied into the log


def now():
    return datetime.datetime.now().astimezone()


def parse_time(text):
    try:
        return datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def name_of(session_id):
    """The session id, which is its path below the two artifacts: 20261002/1338.ubuntu-npu-xpu
    (also from 20261002-1338.ubuntu-npu-xpu and test-session.20261002-1338.ubuntu-npu-xpu), or None."""
    text = str(session_id or '').strip().replace('\\', '/')
    if text.startswith('test-session.'):
        text = text[len('test-session.'):]
    m = re.fullmatch(r'(\d{8})[/-](\d{4}\.[\w.-]+)', text)
    return f'{m.group(1)}/{m.group(2)}' if m else None


def tag_of(text):
    """A type or a host name as a short key: lowercase letters, digits, '.', '_' and '-'."""
    return re.sub(r'[^a-z0-9._-]+', '-', str(text or '').lower()).strip('-.')


def export_line(session_id, shell = None):
    """
    The line that makes a session the shell's current one (CMETA_TEST_SESSION), in the syntax of
    bash (the default off Windows), cmd (the default on Windows) or powershell.
    """
    shell = str(shell or ('cmd' if os.name == 'nt' else 'bash')).strip().lower()
    if shell in ('cmd', 'bat', 'batch'):
        return f'set {SESSION_ENV}={session_id}'
    if shell in ('powershell', 'pwsh', 'ps', 'ps1'):
        return f'$env:{SESSION_ENV} = "{session_id}"'
    return f'export {SESSION_ENV}={session_id}'


def stamp(t, date = True):
    """2026-10-02 10:59:12 UTC+02:00 (the offset keeps logs from several machines comparable)."""
    if t is None:
        return ''
    offset = t.utcoffset()
    zone = ''
    if offset is not None:
        minutes = int(offset.total_seconds() // 60)
        zone = ' UTC{}{:02d}:{:02d}'.format('+' if minutes >= 0 else '-', abs(minutes) // 60, abs(minutes) % 60)
    return t.strftime('%Y-%m-%d %H:%M:%S' if date else '%H:%M:%S') + zone


def duration_text(seconds):
    if seconds is None:
        return ''
    seconds = int(round(seconds))
    if seconds < 60:
        return f'{seconds} s'
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f'{h} h {m} min' if h else f'{m} min {s} s'


def size_text(mib):
    if mib is None:
        return ''
    return f'{mib / 1024:.1f} GiB' if mib >= 1024 else f'{mib} MiB'


def bytes_text(size):
    return f'{size} B' if size < 1024 else f'{size / 1024:.1f} KiB' if size < 2**20 else size_text(round(size / 2**20, 1))


def changed_text(n):
    return f", {n} changed file{'s' if n != 1 else ''}" if n else ''


def folder_mib(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return round(total / 2**20, 1)


def ram_gib():
    """The machine's RAM in GiB, or None."""
    try:
        if hasattr(os, 'sysconf') and 'SC_PHYS_PAGES' in os.sysconf_names:
            return round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30, 1)
    except (ValueError, OSError):
        pass
    try:
        if sys.platform == 'darwin':
            return round(int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'])) / 2**30, 1)
        if os.name == 'nt':
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('sullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 2**30, 1)
    except Exception:
        pass
    return None


def git(path, *args):
    try:
        r = subprocess.run(['git', '-C', path] + list(args), capture_output = True, text = True, timeout = 20)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def git_info(path):
    """The branch, the commit and the number of changed tracked files of the repository at path."""
    info = {}
    commit = git(path, 'rev-parse', '--short', 'HEAD')
    if commit:
        info['branch'] = git(path, 'rev-parse', '--abbrev-ref', 'HEAD')
        info['commit'] = commit
        changes = git(path, 'status', '--porcelain', '--untracked-files=no')
        info['changed_files'] = len(changes.splitlines()) if changes else 0
    return info


def repo_root(path):
    """The cMeta repository (the folder with _cmr.yaml or _cmr.json) that holds path."""
    path = os.path.abspath(path)
    while True:
        if os.path.isfile(os.path.join(path, '_cmr.yaml')) or os.path.isfile(os.path.join(path, '_cmr.json')):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def describe_repo(path):
    return dict({'name': os.path.basename(path.rstrip('\\/')), 'path': path}, **git_info(path))


def cmeta_info(home):
    info = {'home': home}
    try:
        import cmeta
        info['version'] = getattr(cmeta, '__version__', None)
        package = os.path.dirname(os.path.abspath(cmeta.__file__))
        info['path'] = package
        # Only an engine checkout (the package at <git root>/cmeta), not a pip install that
        # happens to sit in some other repository
        top = git(package, 'rev-parse', '--show-toplevel')
        if top and os.path.normcase(os.path.normpath(os.path.join(top, 'cmeta'))) == os.path.normcase(package):
            info.update(git_info(top))
    except Exception:
        pass
    return info


def agent_info(params):
    """The agent at work: CMETA_GENERATOR (what cMeta stamps on artifacts), the agent's own
    variables (the Claude Code session, whose transcript holds the token use), then the flags."""
    agent = {}
    try:
        agent = json.loads(os.environ.get('CMETA_GENERATOR', '') or '{}')
    except ValueError:
        pass
    if not isinstance(agent, dict):
        agent = {}
    agent.pop('method', None)
    agent.pop('by', None)
    if os.environ.get('CLAUDE_CODE_SESSION_ID'):
        agent.setdefault('agent', 'Claude Code')
        agent['session'] = os.environ['CLAUDE_CODE_SESSION_ID']
        if os.environ.get('CLAUDE_EFFORT'):
            agent.setdefault('effort', os.environ['CLAUDE_EFFORT'])
    for key in ('agent', 'model', 'effort', 'session'):
        if params.get(key) not in (None, '', True):
            agent[key] = str(params[key])
    return agent


USAGE_KEYS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
PRICE_KEYS = {'input_tokens': 'input', 'output_tokens': 'output',
              'cache_creation_input_tokens': 'cache_write', 'cache_read_input_tokens': 'cache_read'}


def claude_usage(session, since, until, projects = None):
    """The tokens a Claude Code session (with its subagents) used between two times, from its
    transcripts under ~/.claude/projects, by model; None without transcripts. Each request is
    logged once per content block with the same usage, so requests count once."""
    if not projects:
        projects = os.path.join(os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude'),
                                'projects')
    files = glob.glob(os.path.join(projects, '*', session + '.jsonl')) + \
            glob.glob(os.path.join(projects, '*', session, 'subagents', '*.jsonl'))
    if not files:
        return None
    requests = {}
    for path in files:
        try:
            with open(path, encoding = 'utf-8', errors = 'replace') as f:
                for line in f:
                    if '"usage"' not in line or '"assistant"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    message = d.get('message') if isinstance(d.get('message'), dict) else {}
                    usage = message.get('usage')
                    t = parse_time(str(d.get('timestamp', '')).replace('Z', '+00:00'))
                    if d.get('type') != 'assistant' or not isinstance(usage, dict) or not t or t < since or t > until:
                        continue
                    requests[d.get('requestId') or message.get('id') or d.get('uuid')] = (message.get('model'), usage)
        except OSError:
            continue
    by_model = {}
    for model, usage in requests.values():
        counts = by_model.setdefault(model or 'unknown', dict({'requests': 0}, **{k: 0 for k in USAGE_KEYS}))
        counts['requests'] += 1
        for k in USAGE_KEYS:
            counts[k] += int(usage.get(k) or 0)
    total = dict({'requests': 0}, **{k: 0 for k in USAGE_KEYS})
    for counts in by_model.values():
        for k in total:
            total[k] += counts[k]
    total['by_model'] = by_model
    return total


def usage_cost(usage, prices):
    """The cost in USD from configured prices per million tokens (test_session.prices.<model>:
    input, output, cache_write, cache_read); None unless every model used has prices."""
    if not usage or not usage.get('by_model') or not isinstance(prices, dict):
        return None
    cost = 0.0
    for model, counts in usage['by_model'].items():
        price = prices.get(model)
        if not isinstance(price, dict):
            return None
        for k, p in PRICE_KEYS.items():
            cost += counts.get(k, 0) * float(price.get(p) or 0) / 1e6
    return round(cost, 2)


def tokens_text(n):
    return f'{n / 1e6:.1f}M' if n >= 10**6 else f'{n:,}'


def value(v):
    """CLI values come as strings: keep numbers as numbers in the record."""
    if isinstance(v, str):
        for convert in (int, float):
            try:
                return convert(v)
            except ValueError:
                pass
    return v


def render_md(rec):
    """The human-readable log (session.md), rebuilt from the record each time it changes."""
    started = parse_time(rec.get('started'))
    finished = parse_time(rec.get('finished'))
    host = rec.get('host') or {}
    agent = rec.get('agent') or {}
    cmeta = rec.get('cmeta') or {}
    costs = rec.get('costs') or {}

    lines = [f"# {rec['id']}: {rec.get('title') or rec.get('type')}", '']
    lines.append(f"- **Status:** {rec.get('status')}")
    lines.append(f"- **Started:** {stamp(started)}")
    if finished:
        lines.append(f"- **Finished:** {stamp(finished)} (after {duration_text(costs.get('wall_time_s'))})")
    ram = f", {host['ram_gib']} GiB RAM" if host.get('ram_gib') else ''
    lines.append(f"- **Host:** {host.get('name')}: {host.get('os')} {host.get('release')}, {host.get('arch')}, "
                 f"{host.get('cpus')} CPUs{ram}, Python {host.get('python')}")
    if agent:
        lines.append('- **Agent:** ' + ', '.join(f'{k} {v}' for k, v in agent.items() if v not in (None, '')))
    engine = f"cMeta {cmeta.get('version')}"
    if cmeta.get('commit'):
        engine += f" ({cmeta.get('branch')} @ {cmeta['commit']}{changed_text(cmeta.get('changed_files'))})"
    lines.append(f"- **Engine:** {engine}, home `{cmeta.get('home')}`")
    for repo in rec.get('repositories') or []:
        where = f" {repo.get('branch')} @ {repo.get('commit')}" if repo.get('commit') else ''
        lines.append(f"- **Repository:** {repo.get('name')}{where}{changed_text(repo.get('changed_files'))}")
    if rec.get('command'):
        lines.append(f"- **Command:** `{rec['command']}`")
    if rec.get('artifacts'):
        lines.append(f"- **cMeta:** `log::{rec['artifacts'].get('log')}` and `tmp::{rec['artifacts'].get('tmp')}`, "
                     f"subfolder `{rec['id']}`")
    sandbox = f"- **Sandbox:** `{rec.get('sandbox')}`"
    if rec.get('sandbox_removed'):
        sandbox += f" (removed, {size_text(costs.get('sandbox_mib'))})" if costs.get('sandbox_mib') is not None else ' (removed)'
    elif costs.get('sandbox_mib') is not None:
        sandbox += f" ({size_text(costs['sandbox_mib'])}, kept)"
    lines += [sandbox, '']

    if rec.get('summary'):
        lines += ['## Summary', '', rec['summary'], '']

    if rec.get('results'):
        lines += ['## Results', '', '| Key | Value |', '|---|---|']
        for k, v in rec['results'].items():
            lines.append(f'| {k} | {json.dumps(v) if isinstance(v, (dict, list)) else v} |')
        lines.append('')

    if rec.get('notes'):
        lines += ['## Notes', '']
        for n in rec['notes']:
            lines.append(f"- {stamp(parse_time(n.get('time')), date = False)[:8]} {n.get('text', '')}")
        lines.append('')

    items = []
    if costs.get('wall_time_s') is not None:
        items.append(f"Wall time: {duration_text(costs['wall_time_s'])}")
    if costs.get('sandbox_mib') is not None:
        items.append(f"Sandbox: {size_text(costs['sandbox_mib'])}" + (' (removed)' if rec.get('sandbox_removed') else ''))
    usage = costs.get('agent_usage')
    if usage:
        models = ', '.join(usage.get('by_model', {}))
        items.append(f"Agent: {usage['requests']} requests; {tokens_text(usage['output_tokens'])} output, "
                     f"{tokens_text(usage['input_tokens'])} input, {tokens_text(usage['cache_creation_input_tokens'])} "
                     f"cache-write and {tokens_text(usage['cache_read_input_tokens'])} cache-read tokens"
                     + (f' ({models})' if models else ''))
    if costs.get('agent_tokens') not in (None, ''):
        tokens = costs['agent_tokens']
        items.append(f"Agent tokens (reported): {tokens:,}" if isinstance(tokens, int) else f"Agent tokens (reported): {tokens}")
    if costs.get('agent_cost_usd') not in (None, ''):
        items.append(f"Agent cost (reported): ${costs['agent_cost_usd']}")
    if costs.get('agent_cost_usd_estimate') is not None:
        items.append(f"Agent cost (configured prices): ${costs['agent_cost_usd_estimate']}")
    for k, v in costs.items():
        if k not in ('wall_time_s', 'sandbox_mib', 'agent_usage', 'agent_tokens', 'agent_cost_usd',
                     'agent_cost_usd_estimate') and v not in (None, ''):
            items.append(f"{k}: {v}")
    if items:
        lines += ['## Costs', ''] + [f'- {x}' for x in items] + ['']

    if rec.get('attachments'):
        lines += ['## Attachments', '']
        for a in rec['attachments']:
            lines.append(f"- [{a['name']}](attachments/{a['name']}) ({bytes_text(a.get('bytes', 0))})")
        lines.append('')

    return '\n'.join(lines)


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            **params,
    ):
        """
        Start, annotate, finish, list, prune or migrate test sessions (see _desc.yaml).

        Args (as --flags):
            start (bool): start a session (--type, --title, --cmd: the command under test,
                --repos=<path>[,<path>], --agent, --model, --effort, --session).
            note (str): add a note to the session --id (also with --finish).
            results (dict): --results.<key>=<value> adds results (also --results_file=<json>).
            costs (dict): --costs.<key>=<value> adds costs; --tokens and --cost_usd are shortcuts.
            attach (str): files to copy into the log: <file>[,<file>], globs allowed
                (--attach_as=<name> stores a single file under that name).
            finish (bool): finish the session --id (--status, default passed; --summary;
                --keep, or --max_keep_mib: a larger sandbox is removed, default 1024 MiB).
                With a Claude Code session, the tokens it used meanwhile come from its
                transcripts (--skip_usage: not), the cost with test_session.prices.<model>.
            list (bool): list the sessions (--date=YYYYMMDD, --type, --status, --host); the
                default action.
            prune (bool): remove the sandboxes of finished sessions older than --days (0)
                (--id: only that one; --all: also those finished with --keep).
            migrate (bool): move the sessions kept as folders before 0.42.0
                (<CMETA_HOME>/log/cmeta-tests-*, <CMETA_HOME>/tmp/cmeta-tests-*, or under --from)
                into the artifacts; --remove_old then removes those folders.
            repo (str): the repository of the two artifacts (default local, or the config
                test_session.repo); artifact (str): their name (default cmeta-aops-test-sessions,
                or test_session.artifact).
            print (str): sandbox, log, id, json or export - print only that, on the last line
                (export: the line that makes the session the shell's current one, in the
                syntax of --shell=bash|cmd|powershell; "cx program run" then attaches its
                provenance record to the session and runs with --provenance=strict).

        Returns:
            dict: return, id, sandbox, log, record (sessions for --list, pruned for --prune,
                migrated for --migrate).
        """

        con = ctx['control'].get('con', False)

        # Defaults from the configuration: cx config set task --meta.test_session.max_keep_mib=4096
        r = self.cm.access({'category': self.cmeta['uses_categories']['config'], 'command': 'get', 'arg1': 'task'})
        if self.cm.catch_error(r): return r
        cfg = r.get('config_cmeta', {}).get('test_session', {})

        self.cfg = cfg
        self.repo = str(params.get('repo') or cfg.get('repo') or 'local')
        self.artifact = str(params.get('artifact') or cfg.get('artifact') or ARTIFACT)
        self.con = con and not params.get('print')

        # The two artifacts that hold the sessions: the records and the sandboxes
        self.base = {}
        for key in ('log', 'tmp'):
            r = self._artifact(self.cmeta['uses_categories'][key])
            if r['return'] > 0:
                return r
            self.base[key] = r['path']

        if params.get('start'):
            r = self._start(params)
        elif params.get('finish'):
            r = self._finish(params)
        elif params.get('prune'):
            return self._prune(params, con)
        elif params.get('migrate'):
            return self._migrate(params, con)
        elif params.get('id') and not params.get('list'):
            r = self._update(params)
        else:
            return self._list(params, con)

        if r['return'] > 0:
            return r

        what = params.get('print')
        if con and what in ('sandbox', 'log', 'id'):
            print (r[what])
        elif con and what == 'json':
            print (json.dumps(r['record'], indent = 2))
        elif con and what == 'export':
            print (export_line(r['id'], params.get('shell')))

        return r

    ############################################################
    def _artifact(self, category):
        """The path of the artifact (in self.repo) that holds the sessions, made on first use."""
        ref = f'{self.repo}:{self.artifact}'
        r = self.cm.access({'category': category, 'command': 'find', 'arg1': ref})
        if r['return'] == 0 and r.get('artifacts'):
            return {'return': 0, 'path': r['artifacts'][0]['path']}
        if r['return'] > 0 and r['return'] != 16:
            return r
        what = 'records' if category.startswith('log') else 'sandboxes'
        r = self.cm.access({'category': category, 'command': 'create', 'arg1': ref, 'yaml': True,
                            'tags': [TAG, 'cmeta-aops'],
                            'meta': {'desc': f'The {what} of the test sessions of the cmeta-aops task test-session: '
                                             'a folder per day and a subfolder per session, '
                                             '<YYYYMMDD>/<HHMM>.<type>.'}})
        if r['return'] > 0:
            return r
        return {'return': 0, 'path': r['path']}

    def _dirs(self, session_id):
        date, _, name = session_id.partition('/')
        return os.path.join(self.base['log'], date, name), os.path.join(self.base['tmp'], date, name)

    def _files(self, rec):
        log_dir = self._dirs(rec['id'])[0]
        return {'dir': log_dir, 'json': os.path.join(log_dir, 'session.json'),
                'md': os.path.join(log_dir, 'session.md'), 'attachments': os.path.join(log_dir, 'attachments')}

    def _save(self, rec):
        f = self._files(rec)
        os.makedirs(f['dir'], exist_ok = True)
        with open(f['json'], 'w', encoding = 'utf-8') as out:
            json.dump(rec, out, indent = 2)
        with open(f['md'], 'w', encoding = 'utf-8') as out:
            out.write(render_md(rec))

    def _load(self, session_id):
        name = name_of(session_id)
        if not name:
            return None, self.cm.error(f'test-session: "{session_id}" is not a session id (YYYYMMDD/HHMM.type)')
        path = os.path.join(self._dirs(name)[0], 'session.json')
        if not os.path.isfile(path):
            return None, self.cm.error(f'test-session: no session "{name}" in {self.base["log"]}')
        with open(path, encoding = 'utf-8') as f:
            rec = json.load(f)
        rec['id'] = name
        rec['sandbox'] = self._dirs(name)[1]
        return rec, None

    def _result(self, rec):
        return {'return': 0, 'id': rec['id'], 'sandbox': rec['sandbox'], 'log': self._files(rec)['md'], 'record': rec}

    ############################################################
    def _add(self, rec, params):
        """What --note, --results, --results_file, --costs, --tokens, --cost_usd and --attach add."""
        if params.get('note') not in (None, '', True):
            rec.setdefault('notes', []).append({'time': now().isoformat(timespec = 'seconds'), 'text': str(params['note'])})

        results = rec.setdefault('results', {})
        if params.get('results_file'):
            try:
                with open(params['results_file'], encoding = 'utf-8') as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                return self.cm.error(f'test-session: can\'t read results from {params["results_file"]}: {e}')
            if not isinstance(data, dict):
                return self.cm.error(f'test-session: {params["results_file"]} must hold a JSON object')
            results.update(data)
        if isinstance(params.get('results'), dict):
            results.update({k: value(v) for k, v in params['results'].items()})

        costs = rec.setdefault('costs', {})
        if isinstance(params.get('costs'), dict):
            costs.update({k: value(v) for k, v in params['costs'].items()})
        for key, param in (('agent_tokens', 'tokens'), ('agent_cost_usd', 'cost_usd')):
            if params.get(param) not in (None, '', True):
                costs[key] = value(params[param])

        attach = params.get('attach')
        if attach not in (None, '', True):
            items = attach if isinstance(attach, list) else str(attach).split(',')
            folder = self._files(rec)['attachments']
            max_mib = float(params.get('attach_max_mib') or MAX_ATTACH_MIB)
            # --attach_as=<name>: the name of a single attached file in the log (the records of several
            # program runs are all called provenance.json)
            as_name = str(params.get('attach_as') or '').strip()
            for item in items:
                files = sorted(glob.glob(os.path.expanduser(item.strip()))) or [item.strip()]
                for path in files:
                    if not os.path.isfile(path):
                        return self.cm.error(f'test-session: no file to attach: {path}')
                    size = os.path.getsize(path)
                    if size > max_mib * 2**20:
                        rec.setdefault('notes', []).append({'time': now().isoformat(timespec = 'seconds'),
                            'text': f'not attached ({size_text(round(size / 2**20, 1))} > {max_mib} MiB): {path}'})
                        continue
                    os.makedirs(folder, exist_ok = True)
                    name = os.path.basename(as_name) if as_name and len(items) == 1 and len(files) == 1 else os.path.basename(path)
                    shutil.copy2(path, os.path.join(folder, name))
                    attachments = [a for a in rec.setdefault('attachments', []) if a['name'] != name]
                    attachments.append({'name': name, 'bytes': size, 'from': os.path.abspath(path)})
                    rec['attachments'] = attachments
        return {'return': 0}

    ############################################################
    def _start(self, params):
        kind = tag_of(params.get('type') or 'test') or 'test'
        t = now()
        stem = f"{t.strftime('%Y%m%d/%H%M')}.{kind}"
        name, n = stem, 2
        while any(os.path.exists(d) for d in self._dirs(name)):
            name = f'{stem}-{n}'
            n += 1

        repos = []
        here = repo_root(__file__)
        extra = params.get('repos') or []
        if isinstance(extra, str):
            extra = extra.split(',')
        extra = [os.path.abspath(os.path.expanduser(p.strip())) for p in extra if p.strip()]
        for path in extra:
            if not os.path.isdir(path):
                return self.cm.error(f'test-session: no repository at {path}')
        for path in ([here] if here else []) + extra:
            if path not in [x['path'] for x in repos]:
                repos.append(describe_repo(path))

        log_dir, sandbox = self._dirs(name)
        os.makedirs(sandbox, exist_ok = True)
        rec = {
            'id': name,
            'type': kind,
            'title': params.get('title') or '',
            'status': 'running',
            'started': t.isoformat(timespec = 'seconds'),
            'host': {'name': platform.node(), 'os': platform.system(), 'release': platform.release(),
                     'arch': platform.machine(), 'cpus': os.cpu_count(), 'ram_gib': ram_gib(),
                     'python': platform.python_version()},
            'cmeta': cmeta_info(str(self.cm.home_path)),
            'repositories': repos,
            'agent': agent_info(params),
            'command': params.get('cmd') or '',
            'artifacts': {'log': f'{self.repo}:{self.artifact}', 'tmp': f'{self.repo}:{self.artifact}'},
            'sandbox': sandbox,
            'notes': [],
            'results': {},
            'costs': {},
        }
        r = self._add(rec, params)
        if r['return'] > 0:
            return r
        self._save(rec)

        if self.con:
            print ('')
            print (f'Test session {name} started')
            print (f'  sandbox: {sandbox}')
            print (f'  log:     {self._files(rec)["md"]}')
            print (f'  shell:   {export_line(name, params.get("shell"))}')
            print ('           (then every "cx program run" attaches its provenance record here and runs --provenance=strict)')
        return self._result(rec)

    ############################################################
    def _update(self, params):
        rec, err = self._load(params.get('id'))
        if err:
            return err
        r = self._add(rec, params)
        if r['return'] > 0:
            return r
        self._save(rec)
        return self._result(rec)

    ############################################################
    def _remove_sandbox(self, rec):
        if os.path.isdir(rec['sandbox']):
            rec.setdefault('costs', {})['sandbox_mib'] = folder_mib(rec['sandbox'])
            shutil.rmtree(rec['sandbox'], ignore_errors = True)
        rec['sandbox_removed'] = True

    def _finish(self, params):
        rec, err = self._load(params.get('id'))
        if err:
            return err
        r = self._add(rec, params)
        if r['return'] > 0:
            return r

        t = now()
        started = parse_time(rec.get('started'))
        rec['finished'] = t.isoformat(timespec = 'seconds')
        rec['status'] = params.get('status') or 'passed'
        if params.get('summary'):
            rec['summary'] = params['summary']
        costs = rec.setdefault('costs', {})
        if started:
            costs['wall_time_s'] = round((t - started).total_seconds())

        # The agent's token use while the session was open (all its work in that time), when
        # its transcripts are on this machine; the cost too with configured prices
        session = (rec.get('agent') or {}).get('session')
        if session and started and not params.get('skip_usage'):
            usage = claude_usage(session, started, t)
            if usage is not None:
                costs['agent_usage'] = usage
                # A session started with the harness's default model records no model: take the
                # one that did most of the work (subagents may run a smaller one)
                models = {m: c for m, c in (usage.get('by_model') or {}).items()
                          if m and m != 'unknown' and not m.startswith('<')}
                if models and not rec['agent'].get('model'):
                    rec['agent']['model'] = max(models, key = lambda m: models[m]['output_tokens'])
                    rec['agent']['model_from'] = 'transcript'
                cost = usage_cost(usage, self.cfg.get('prices'))
                if cost is not None:
                    costs['agent_cost_usd_estimate'] = cost

        # The sandbox goes when it is large (builds, downloads) unless --keep; the log stays
        if params.get('keep'):
            rec['keep_sandbox'] = True
        if os.path.isdir(rec['sandbox']):
            costs['sandbox_mib'] = folder_mib(rec['sandbox'])
            max_keep = float(params.get('max_keep_mib') or self.cfg.get('max_keep_mib') or MAX_KEEP_MIB)
            if not rec.get('keep_sandbox') and costs['sandbox_mib'] > max_keep:
                self._remove_sandbox(rec)

        self._save(rec)
        if self.con:
            print ('')
            line = f"Test session {rec['id']} {rec['status']} after {duration_text(costs.get('wall_time_s'))}"
            if 'sandbox_mib' in costs:
                line += f"; sandbox {size_text(costs['sandbox_mib'])} " + ('removed' if rec.get('sandbox_removed') else 'kept')
            print (line)
            print (f"  log: {self._files(rec)['md']}")
        return self._result(rec)

    ############################################################
    def _sessions(self, date = None, kind = None, status = None, host = None):
        """The records, read from the folders of the log artifact (no index entry per session)."""
        sessions = []
        base = self.base['log']
        for day in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not re.fullmatch(r'\d{8}', day) or (date and day != str(date)) or not os.path.isdir(os.path.join(base, day)):
                continue
            for name in sorted(os.listdir(os.path.join(base, day))):
                session_id = name_of(f'{day}/{name}')
                if not session_id:
                    continue
                try:
                    with open(os.path.join(base, day, name, 'session.json'), encoding = 'utf-8') as f:
                        rec = json.load(f)
                except (OSError, ValueError):
                    continue
                rec['id'] = session_id
                rec['sandbox'] = self._dirs(session_id)[1]
                if kind and rec.get('type') != tag_of(kind):
                    continue
                if status and str(rec.get('status')).lower() != str(status).lower():
                    continue
                if host and tag_of((rec.get('host') or {}).get('name')) != tag_of(host):
                    continue
                sessions.append(rec)
        return sessions

    def _list(self, params, con):
        sessions = self._sessions(params.get('date'), params.get('type'), params.get('status'), params.get('host'))
        if con:
            print ('')
            if not sessions:
                print (f'No test sessions in {self.base["log"]}')
            for rec in sessions:
                costs = rec.get('costs', {})
                sandbox = ('removed' if rec.get('sandbox_removed') else
                           size_text(costs['sandbox_mib']) if 'sandbox_mib' in costs else
                           'in use' if os.path.isdir(rec['sandbox']) else 'gone')
                agent = rec.get('agent') or {}
                model = '/'.join(str(agent[k]) for k in ('model', 'effort') if agent.get(k))
                print (f"{rec['id']:36} {rec.get('status', ''):8} {duration_text(costs.get('wall_time_s')):>12}  "
                       f"{sandbox:>10}  {model:24} {rec.get('title', '')}")
        return {'return': 0, 'sessions': sessions}

    ############################################################
    def _prune(self, params, con):
        days = float(params.get('days') or 0)
        limit = now() - datetime.timedelta(days = days)
        only = name_of(params.get('id')) if params.get('id') else None
        pruned = []
        for rec in self._sessions():
            if only and rec['id'] != only:
                continue
            finished = parse_time(rec.get('finished'))
            if rec.get('status') == 'running' or not finished or finished > limit:
                continue
            if rec.get('keep_sandbox') and not params.get('all'):
                continue
            if not os.path.isdir(rec['sandbox']):
                continue
            self._remove_sandbox(rec)
            self._save(rec)
            pruned.append(rec['id'])
            if con:
                print (f"Removed the sandbox of {rec['id']} ({size_text(rec['costs'].get('sandbox_mib'))})")
        if con:
            print (f'Removed {len(pruned)} sandbox(es); the records stay in {self.base["log"]}')
        return {'return': 0, 'pruned': pruned}

    ############################################################
    def _migrate(self, params, con):
        """The sessions kept as folders before 0.42.0 -> subfolders of the two artifacts."""
        root = os.path.normpath(os.path.abspath(os.path.expanduser(str(params.get('from') or self.cm.home_path))))
        old_log, old_tmp = os.path.join(root, 'log'), os.path.join(root, 'tmp')
        migrated, skipped = [], []
        days = sorted(d for d in os.listdir(old_log) if d.startswith(OLD_PREFIX)) if os.path.isdir(old_log) else []
        for day in days:
            folder = os.path.join(old_log, day)
            for file in sorted(n for n in os.listdir(folder) if n.endswith('.json')):
                json_path = os.path.join(folder, file)
                old_sandbox = os.path.join(old_tmp, day, file[:-5])
                old_files = os.path.join(folder, file[:-5])
                try:
                    with open(json_path, encoding = 'utf-8') as f:
                        rec = json.load(f)
                except (OSError, ValueError):
                    skipped.append(json_path)
                    continue
                name = name_of(rec.get('id'))
                if not name:
                    skipped.append(json_path)
                    continue
                log_dir, sandbox = self._dirs(name)
                if os.path.exists(log_dir):
                    # Moved before: --remove_old still removes what is left of the old folders
                    skipped.append(name)
                    if params.get('remove_old'):
                        for path in (json_path, json_path[:-5] + '.md'):
                            if os.path.isfile(path):
                                os.remove(path)
                        for path in (old_files, old_sandbox):
                            if os.path.isdir(path) and not os.listdir(path):
                                os.rmdir(path)
                    continue

                rec['migrated_from'] = {'id': rec.get('id'), 'log': json_path, 'sandbox': rec.get('sandbox') or old_sandbox}
                rec['id'] = name
                rec['artifacts'] = {'log': f'{self.repo}:{self.artifact}', 'tmp': f'{self.repo}:{self.artifact}'}
                rec['sandbox'] = sandbox
                os.makedirs(log_dir, exist_ok = True)
                os.makedirs(os.path.dirname(sandbox), exist_ok = True)
                if os.path.isdir(old_sandbox):
                    shutil.move(old_sandbox, sandbox)
                    rec.pop('sandbox_removed', None)
                else:
                    rec['sandbox_removed'] = True
                if os.path.isdir(old_files):
                    shutil.move(old_files, self._files(rec)['attachments'])
                self._save(rec)
                migrated.append(name)
                if con:
                    print (f"{rec['migrated_from']['id']} -> {log_dir}")

                if params.get('remove_old'):
                    for path in (json_path, json_path[:-5] + '.md'):
                        if os.path.isfile(path):
                            os.remove(path)

        if params.get('remove_old'):
            for base in (old_log, old_tmp):
                for day in (sorted(os.listdir(base)) if os.path.isdir(base) else []):
                    path = os.path.join(base, day)
                    if day.startswith(OLD_PREFIX) and os.path.isdir(path) and not os.listdir(path):
                        os.rmdir(path)
                if os.path.isdir(base) and not os.listdir(base):
                    os.rmdir(base)

        if con:
            print ('')
            print (f'Migrated {len(migrated)} session(s), skipped {len(skipped)}' +
                   ('' if params.get('remove_old') else '; add --remove_old to remove the old folders'))
        return {'return': 0, 'migrated': migrated, 'skipped': skipped}
