"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

test-on-hosts: cx commands run on several hosts at once, each in a throwaway cMeta home with a repository's tree
plugged in (the tree as it is here, released or not), detached from the ssh session; then how they go, their
results collected here, their folders removed. The fleet rounds of the self-tests as one cx task, through cx host
only (push -q, run --script, pull -q) - never hand-written ssh or scp.
"""

import datetime
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tarfile

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The hosts of a round when --hosts is not given: the key "hosts" of the config artifact task-test-on-hosts
# (cx config set task-test-on-hosts --meta.hosts=a,b,c - the test machines of a fleet, never production ones),
# else this machine
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'
CONFIG_ALIAS = 'task-test-on-hosts'
HERE = 'here'
TREE_REPO = 'ctuninglabs@cmeta-aops'
REMOTE_BASE = 'cmeta-tests'          # under the host's login home: every remote test lives there
ROUND_FILE = 'round.json'            # the round as launched (its hosts, instances, refs that failed), in its local folder
SKIP = {'.git', '__pycache__', '.pytest_cache'}
SESSION_ENV = 'CMETA_TEST_SESSION'


def tar_tree(tree, out):
    """The tree as a tarball, without .git and the caches of Python and pytest."""
    def keep(info):
        return None if set(info.name.replace('\\', '/').split('/')) & SKIP else info

    with tarfile.open(out, 'w:gz') as tar:
        tar.add(tree, arcname = os.path.basename(os.path.normpath(tree)), filter = keep)


def sh_quote(text):
    """A word for bash, in single quotes."""
    return "'" + str(text).replace("'", "'\"'\"'") + "'"


def default_hosts(cm):
    """The hosts of a round without --hosts: the key "hosts" of the config artifact task-test-on-hosts, else here."""
    r = cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': CONFIG_ALIAS, 'con': False})
    hosts = (r.get('config_cmeta') or {}).get('hosts') if r.get('return', 1) == 0 else None
    if isinstance(hosts, list):
        hosts = ','.join(str(h) for h in hosts)
    return str(hosts).strip() if hosts else HERE


class CTask(InitCTask):
    """
    cx commands on several hosts at once, each in a throwaway cMeta home.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)
        self.instances = {}
        self.failed_refs = {}

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'launch',       # launch, peek, collect or remove
            cmds: str = None,             # launch: the commands, separated by ";" - the words after "cx", or "!<shell line>"
            hosts: str = None,            # host aliases separated by "," ("here": this machine; "docker:ubuntu", "podman", "wsl:debian" = an instance of that template here); default: the test hosts
            tree: str = None,             # launch: the repository folder to test (default: the clone of ctuninglabs@cmeta-aops)
            id: str = None,               # the name of the round (default at launch: the time; then required)
            files: str = None,            # collect: only these files of a host's work folder ("*.jsonl,steps.txt")
            to: str = None,               # collect: the folder the results go into (default: <round folder>/collected)
    ):
        """
        launch: the tree packed once, pushed with runner.py to ~/cmeta-tests/<id>/ of each host (cx host push -q)
        and started there detached (nohup python3 runner.py, through cx host run --script); "here" runs the same
        runner on this machine, detached, with the tree as it is. peek: each host's state (running or done) and
        its steps. collect: the work folder of each host into <to>/<host> (cx host pull -q). remove: the hosts'
        folders of the round. The round's local folder is in the sandbox of the shell's test session
        (CMETA_TEST_SESSION), else in the current directory: test-on-hosts-<id>.
        """

        con = ctx['control'].get('con', False)

        if action not in ('launch', 'peek', 'collect', 'remove'):
            return self.cm.error(f'test-on-hosts: unknown action "{action}" (launch, peek, collect, remove)')
        if action != 'launch' and not id:
            return self.cm.error(f'test-on-hosts --action={action}: name the round (--id=<round>, printed at its launch)')

        rid = id or datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        local = self.local_folder(rid)
        remote = f'{REMOTE_BASE}/test-on-hosts-{rid}'

        # peek, collect and remove without --hosts: the hosts the launch resolved (round.json), so that a ref of an
        # instance is not made again and a ref that failed at the launch is not tried again
        saved = {}
        if action != 'launch' and not hosts:
            try:
                with open(os.path.join(local, ROUND_FILE), encoding = 'utf-8') as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
        if saved.get('hosts'):
            host_list = list(saved['hosts'])
            self.instances = saved.get('instances') or {}
        else:
            host_list = [h.strip() for h in str(hosts or default_hosts(self.cm)).split(',') if h.strip()]

            # A host ref of the run-on-any-host design (docker[:template], podman[:template], wsl[:template]) is the
            # instance of that template on this machine, made on first use: the round runs inside it, with the tree
            # already mounted there when it is the repository the instance carries. At a launch, a ref that cannot be
            # made (an image that does not build) is said and left out: the rest of a matrix runs
            r = self.resolve_refs(con, host_list, tolerant = action == 'launch')
            if r['return'] > 0: return r
            host_list = r['hosts']
            self.instances = r['instances']
            self.failed_refs = r.get('failed') or {}
            if not host_list:
                return self.cm.error('test-on-hosts: no host to run on' + (f' - every ref failed: {self.failed_refs}' if self.failed_refs else ''))

        if action == 'launch':
            return self.launch(con, rid, local, remote, host_list, cmds, tree)

        if action == 'peek':
            return self.peek(con, rid, local, remote, host_list)

        if action == 'collect':
            return self.collect(con, rid, local, remote, host_list, files, to)

        return self.remove(con, rid, local, remote, host_list)

    ############################################################
    def launch(self, con, rid, local, remote, host_list, cmds, tree):
        commands = [c.strip() for c in str(cmds or '').split(';') if c.strip()]
        if not commands:
            return self.cm.error('test-on-hosts: nothing to run (--cmds="task run explore-tool-versions yq;...")')

        if not tree:
            r = self.cm.access({'category': 'repo', 'command': 'find', 'arg1': TREE_REPO, 'con': False})
            if self.cm.catch_error(r): return r
            tree = r['artifacts'][0]['path']
        tree = os.path.abspath(tree)
        if not os.path.isdir(tree):
            return self.cm.error(f'test-on-hosts: the tree "{tree}" is not a folder')

        os.makedirs(local, exist_ok = True)
        runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runner.py')
        remote_hosts = [h for h in host_list if h != HERE]

        if con:
            print ('')
            print (f'cMeta info: round {rid}: {len(commands)} command{"s" if len(commands) != 1 else ""} on '
                   f'{", ".join(host_list)}, the tree {tree}')

        started = {}

        def launcher_for(tree_arg, wsl = False):
            """
            launch.sh: the runner started detached, with the tree as a tarball or as a folder inside. Through
            ssh "nohup ... &" survives the session; inside a WSL distribution only a new session does (setsid -f):
            a process in the launching session's group is gone with wsl.exe (seen 2026-10-16).
            """
            path = os.path.join(local, ('launch-wsl.sh' if wsl else 'launch.sh') if tree_arg == 'tree.tar.gz' else
                                ('launch-wsl-mounted.sh' if wsl else 'launch-mounted.sh'))
            words = f'python3 "$ROOT/runner.py" "$ROOT" {sh_quote(tree_arg)} ' + ' '.join(sh_quote(c) for c in commands)
            with open(path, 'w', encoding = 'utf-8', newline = '\n') as f:
                f.write('#!/bin/bash\n'
                        f'# test-on-hosts round {rid}: the runner started detached from the launching session\n\n'
                        f'ROOT="$HOME/{remote}"\n'
                        'cd "$ROOT" || exit 1\n')
                if wsl:
                    f.write(f'setsid -f {words} > "$ROOT/run.out" 2>&1 < /dev/null\n'
                            'echo "started on $(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null) (a new session)"\n')
                else:
                    f.write(f'nohup {words} > "$ROOT/run.out" 2>&1 < /dev/null &\n'
                            'echo "started on $(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null): pid $!"\n')
            return path

        # The tree once, for every remote host that does not carry it already
        tarball = os.path.join(local, 'tree.tar.gz')
        if any(not self.instances.get(h, {}).get('tree_inside') for h in remote_hosts):
            tar_tree(tree, tarball)

        for h in remote_hosts:
            inside = self.instances.get(h, {}).get('tree_inside') if os.path.normcase(os.path.normpath(tree)) == \
                     os.path.normcase(os.path.normpath(self.instances.get(h, {}).get('tree_local') or '')) else ''
            files = [runner] if inside else [tarball, runner]
            for path in files:
                r = self.host('push', arg1 = h, arg2 = path, to = f'{remote}/{os.path.basename(path)}')
                if r['return'] > 0:
                    started[h] = f'push failed: {r.get("error")}'
                    break
            else:
                r = self.host('run', arg1 = h, script = launcher_for(inside or 'tree.tar.gz', wsl = self.instances.get(h, {}).get('engine') == 'wsl'),
                              capture = True)
                out = (r.get('outputs') or {}).get(h, {}).get('stdout', '')
                started[h] = out.strip().splitlines()[-1] if r['return'] == 0 and out.strip() else f'start failed: {r.get("error")}'
                if inside:
                    started[h] += f' (the tree mounted at {inside})'

            if con:
                print (f'  {h}: {started[h]}')

        # This machine: the same runner, detached, with the tree as it is
        if HERE in host_list:
            root = os.path.join(local, HERE)
            os.makedirs(root, exist_ok = True)
            flags = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' \
                    else {'start_new_session': True}
            with open(os.path.join(root, 'run.out'), 'w') as out:
                p = subprocess.Popen([sys.executable, runner, root, tree] + commands, stdout = out, stderr = subprocess.STDOUT,
                                     stdin = subprocess.DEVNULL, cwd = root, **flags)
            started[HERE] = f'started here: pid {p.pid}'
            if con:
                print (f'  {HERE}: {started[HERE]}')

        # The round as launched, for peek / collect / remove without --hosts
        record = {'id': rid, 'hosts': host_list, 'instances': self.instances, 'failed_refs': self.failed_refs,
                  'commands': commands, 'tree': tree, 'started': started,
                  'launched': datetime.datetime.now().astimezone().isoformat(timespec = 'seconds')}
        with open(os.path.join(local, ROUND_FILE), 'w', encoding = 'utf-8') as f:
            json.dump(record, f, indent = 2)

        if con:
            for ref, why in self.failed_refs.items():
                print (f'  {ref}: NOT made - {why}')
            print ('')
            print (f'cMeta info: then: cx task run test-on-hosts --action=peek --id={rid}')

        return {'return': 0, 'id': rid, 'local': local, 'remote': remote, 'started': started, 'failed_refs': self.failed_refs}

    ############################################################
    def peek(self, con, rid, local, remote, host_list):
        script = os.path.join(local, 'peek.sh')
        os.makedirs(local, exist_ok = True)
        with open(script, 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write('#!/bin/bash\n'
                    f'ROOT="$HOME/{remote}"\n'
                    'cat "$ROOT/DONE" 2>/dev/null || echo running\n'
                    'cat "$ROOT/work/steps.txt" 2>/dev/null\n'
                    'true\n')

        states = {}
        for h in host_list:
            if h == HERE:
                root = os.path.join(local, HERE)
                text = ''
                for name in ('DONE', os.path.join('work', 'steps.txt')):
                    path = os.path.join(root, name)
                    if os.path.isfile(path):
                        with open(path, encoding = 'utf-8', errors = 'replace') as f:
                            text += f.read()
                    elif name == 'DONE':
                        text += 'running\n'
            else:
                r = self.host('run', arg1 = h, script = script, capture = True)
                text = (r.get('outputs') or {}).get(h, {}).get('stdout', '') if r['return'] == 0 else f'unreachable: {r.get("error")}\n'

            lines = [l for l in text.splitlines() if l.strip()]
            states[h] = {'done': bool(lines) and lines[0].startswith('done'), 'lines': lines}
            if con:
                print ('')
                print (f'=== {h}')
                for line in lines:
                    print (f'  {line}')

        done = all(s['done'] for s in states.values())
        if con:
            print ('')
            print (f'cMeta info: round {rid}: ' + ('done everywhere' if done else 'still running somewhere'))

        return {'return': 0, 'id': rid, 'done': done, 'hosts': states}

    ############################################################
    def collect(self, con, rid, local, remote, host_list, files, to):
        target = os.path.abspath(to or os.path.join(local, 'collected'))
        patterns = [p.strip() for p in str(files or '').split(',') if p.strip()]
        collected = {}

        for h in host_list:
            dest = os.path.join(target, h)
            if h == HERE:
                work = os.path.join(local, HERE, 'work')
                count = 0
                for folder, _, names in os.walk(work):
                    for name in names:
                        if patterns and not any(fnmatch.fnmatch(name, p) for p in patterns):
                            continue
                        rel = os.path.relpath(os.path.join(folder, name), work)
                        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok = True)
                        shutil.copy2(os.path.join(folder, name), os.path.join(dest, rel))
                        count += 1
                collected[h] = f'{count} files'
            else:
                r = self.host('pull', arg1 = h, arg2 = f'{remote}/work', to = dest, files = ','.join(patterns) or None)
                collected[h] = 'ok' if r['return'] == 0 else f'failed: {r.get("error")}'

            if con:
                print (f'  {h}: {collected[h]} -> {dest}')

        return {'return': 0, 'id': rid, 'to': target, 'hosts': collected}

    ############################################################
    def remove(self, con, rid, local, remote, host_list):
        removed = {}
        for h in host_list:
            if h == HERE:
                root = os.path.join(local, HERE)
                shutil.rmtree(root, ignore_errors = True)
                removed[h] = not os.path.exists(root)
            else:
                r = self.host('run', arg1 = h, arg2 = f'rm -rf ~/{remote}', capture = True)
                removed[h] = r['return'] == 0

            if con:
                print (f'  {h}: ' + ('removed' if removed[h] else 'NOT removed'))

        return {'return': 0, 'id': rid, 'removed': removed}

    ############################################################
    def resolve_refs(self, con, host_list, tolerant = False):
        """
        The host list with every ref of a template instance (docker[:template], podman[:template], wsl[:template],
        and the --on_* words after it: "docker:debian --on_template.os_version=13") replaced by the instance's
        alias, made or found through get-host--docker / get-host--wsl; for each instance, where the tree repository
        (ctuninglabs@cmeta-aops) is mounted inside, so that a round runs on it without a push. Tolerant (a launch): a
        ref that cannot be made goes into 'failed' with its error, the others go on.
        """
        hosts, instances, failed = [], {}, {}
        for ref in host_list:
            words = ref.split()
            head = words[0]
            engine, _, template = head.partition(':')
            if engine not in ('docker', 'podman', 'wsl'):
                hosts.append(ref)
                continue
            options = {}
            for w in words[1:]:
                if w.startswith('--on_') and '=' in w:
                    k, _, v = w[5:].partition('=')
                    if k.startswith('template.'):
                        options.setdefault('template', {})[k[9:]] = v
                    else:
                        options[k] = v
            task = 'get-host--wsl' if engine == 'wsl' else 'get-host--docker'
            ii = {'category': 'task', 'command': 'run', 'arg1': task, 'name': template or 'ubuntu',
                  'template': options.get('template') or {}, 'instance': options.get('instance', ''),
                  'repos': options.get('repos', ''), 'con': con, 'quiet': True}
            if engine != 'wsl':
                ii['engine'] = engine
                ii['arch'] = options.get('arch', '')
                ii['compute'] = options.get('compute', 'cpu')
            r = self.cm.access(ii)
            if r['return'] > 0:
                if not tolerant:
                    return r
                failed[ref] = str(r.get('error', ''))[-300:]
                if con:
                    print (f'  {ref}: NOT made - {failed[ref]}')
                continue
            alias = r['host']
            hosts.append(alias)
            # the tree repository inside the instance, from its host artifact
            rh = self.cm.access({'category': 'host', 'command': 'find', 'arg1': alias, 'con': False})
            mounts = []
            if rh['return'] == 0 and rh.get('artifacts'):
                rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(rh['artifacts'][0]['path'], '_desc'))
                mounts = ((rd.get('data') or {}).get('mounts') or []) if rd['return'] == 0 else []
            inst = {'ref': ref, 'engine': engine}
            for m in mounts:
                if m.get('repo') == TREE_REPO and m.get('kind') != 'data':
                    inst['tree_inside'] = m.get('inside')
                    inst['tree_local'] = m.get('path')
            instances[alias] = inst
            if con:
                print (f'  {ref} -> {alias}' + (f' (the tree mounted at {inst["tree_inside"]})' if inst.get('tree_inside') else ''))
        return {'return': 0, 'hosts': hosts, 'instances': instances, 'failed': failed}

    ############################################################
    def host(self, command, **params):
        """cx host <command> ... -q: no question (rclone is set up again when the cache was cleaned)."""
        p = {'category': 'host', 'command': command, 'con': False, 'quiet': True}
        p.update({k: v for k, v in params.items() if v is not None})
        return self.cm.access(p)

    ############################################################
    def local_folder(self, rid):
        """test-on-hosts-<id> in the sandbox of the shell's test session, else in the current directory."""
        session = os.environ.get(SESSION_ENV, '').strip()
        if session:
            r = self.cm.access({'category': 'task', 'command': 'run', 'arg1': 'test-session', 'id': session,
                                'print': 'sandbox', 'con': False, 'quiet': True})
            if r['return'] == 0 and r.get('sandbox'):
                return os.path.join(r['sandbox'], f'test-on-hosts-{rid}')
        return os.path.join(os.getcwd(), f'test-on-hosts-{rid}')
