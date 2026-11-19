"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-prometheus-server - a Prometheus server on this machine (README.md): start (detached, or in the foreground for a
host that keeps it), status (the server and every target), stop. It reads the /metrics of the servers it is given -
the AI gateway server, llama.cpp, vLLM by default - every few seconds and keeps the readings, so Grafana (the task
run-grafana-server) can draw them over time. Its configuration, data, record and log: the state artifact
local:prometheus-server-<port>.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.parse
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask, recorded_process_alive

TASK_CATEGORY = 'task,c36be4b9314a45e0'
STATE_CATEGORY = 'state'
TOOL = 'prometheus,65da170bab9b4492'
SETUP_TASK = 'setup,a2f9b61079ce4333'

DEFAULT_PORT = 9090

# What a start takes when its command line does not say: the keys of this config (in the local repository: this
# machine's), else these; a server kept by its host takes them at its next start.
CONFIG = 'task-run-prometheus-server'
BUILT_IN = {'targets': 'ai-gateway=127.0.0.1:8401,llama-cpp=127.0.0.1:8686,vllm=127.0.0.1:8868',
            'scrape_interval': '10s', 'retention': '365d'}


def listening(host, port, timeout=1.0):
    """Something accepts connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def alive(pid):
    if os.name == 'nt':
        r = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH'], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def http_json(url, timeout=5):
    """GET -> (status, the parsed JSON or the text)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            text = r.read().decode('utf-8', 'replace')
            try:
                return r.status, json.loads(text)
            except ValueError:
                return r.status, text[:200]
    except Exception as e:
        return 0, str(e)


def parse_targets(text):
    """'<name>=<host:port>' or '<name>=<URL>' items (a list, or text separated by commas) -> [{name, scheme, address,
    path}]; an item without a name is named by its address. Raises ValueError on an item it cannot read."""
    items = text if isinstance(text, (list, tuple)) else str(text or '').split(',')
    out, seen = [], set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        name, sep, where = item.partition('=')
        if not sep:
            name, where = '', item
        where = where.strip()
        u = urllib.parse.urlsplit(where if '://' in where else 'http://' + where)
        if not u.hostname or not u.port:
            raise ValueError('a target needs a host and a port: "%s"' % item)
        name = (name.strip() or '%s-%d' % (u.hostname, u.port)).replace(' ', '-')
        if name in seen:
            raise ValueError('two targets are named "%s"' % name)
        seen.add(name)
        host = u.hostname if ':' not in u.hostname else '[%s]' % u.hostname
        out.append({'name': name, 'scheme': u.scheme or 'http', 'address': '%s:%d' % (host, u.port),
                    'path': u.path if u.path not in ('', '/') else '/metrics'})
    return out


def config_text(targets, scrape_interval):
    """prometheus.yml: one job per target, named as the target (JSON is YAML, and needs no YAML writer)."""
    return json.dumps({
        'global': {'scrape_interval': scrape_interval, 'evaluation_interval': scrape_interval},
        'scrape_configs': [{'job_name': t['name'], 'scheme': t['scheme'], 'metrics_path': t['path'],
                            'static_configs': [{'targets': [t['address']]}]} for t in targets],
    }, indent=1) + '\n'


def blocks_min_time(data):
    """The earliest time (Unix seconds) of the blocks in a data folder (their meta.json), or None."""
    found = []
    for name in os.listdir(data) if os.path.isdir(data) else []:
        meta = os.path.join(data, name, 'meta.json')
        if os.path.isfile(meta):
            try:
                with open(meta, encoding='utf-8') as f:
                    found.append(int(json.load(f)['minTime']) / 1000.0)
            except Exception:
                pass
    return min(found) if found else None


def has_data(data):
    """Prometheus has written something there: a block, or a segment of its write-ahead log."""
    if blocks_min_time(data) is not None:
        return True
    wal = os.path.join(data, 'wal')
    return os.path.isdir(wal) and any(n.isdigit() and os.path.getsize(os.path.join(wal, n)) > 0 for n in os.listdir(wal))


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def _state(self, ctx, port):
        """The state artifact of the server on this port (local:prometheus-server-<port>): its folder."""
        r = self.cm.access({'category': STATE_CATEGORY, 'command': 'get', 'arg1': 'local:prometheus-server-%d' % port,
                            'ctx': ctx, 'con': False})
        if r.get('return', 1) > 0:
            return r
        return {'return': 0, 'path': r['artifact']['path']}

    def _defaults(self):
        """The defaults of a start: config::task-run-prometheus-server over BUILT_IN (a key empty or absent: built in)."""
        out = dict(BUILT_IN)
        try:
            r = self.cm.access({'category': 'config', 'command': 'read', 'arg1': CONFIG, 'con': False})
            cfg = r.get('config_cmeta') if r.get('return', 1) == 0 else None
        except Exception:
            cfg = None
        for k in BUILT_IN:
            if isinstance(cfg, dict) and cfg.get(k) not in (None, ''):
                out[k] = cfg[k]
        return out

    @staticmethod
    def _write_record(folder, rec):
        with open(os.path.join(folder, 'server.json'), 'w', encoding='utf-8') as f:
            json.dump(rec, f, indent=1)

    @staticmethod
    def _read_record(folder):
        fp = os.path.join(folder, 'server.json')
        if not os.path.isfile(fp):
            return {}
        try:
            with open(fp, encoding='utf-8') as f:
                rec = json.load(f)
            rec['_written'] = os.path.getmtime(fp)      # when the record was written: its process must be of that run
            return rec
        except Exception:
            return {}

    @staticmethod
    def _read_json(fp, default):
        try:
            with open(fp, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default

    def _scraped_since(self, folder, host, port, running):
        """When this Prometheus began to read its targets live (Unix seconds; scraped-since.txt): written at the first
        start of an empty data folder, or found once - before any import - from its blocks and its head. An import
        only ever brings the time before it, so that a series never holds two counters at once."""
        fp = os.path.join(folder, 'scraped-since.txt')
        try:
            with open(fp, encoding='utf-8') as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            pass
        found = []
        b = blocks_min_time(os.path.join(folder, 'data'))
        if b is not None:
            found.append(b)
        if running:
            s, data = http_json('http://%s:%d/api/v1/status/tsdb' % (host, port))
            head = ((data or {}).get('data') or {}).get('headStats') or {} if s == 200 and isinstance(data, dict) else {}
            if int(head.get('numSeries') or 0) > 0 and head.get('minTime'):
                found.append(int(head['minTime']) / 1000.0)
        if not found:
            return None
        since = min(found)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write('%.3f\n' % since)
        return since

    def _status(self, host, port, rec):
        """Running (it answers /-/ready), its targets (up or down, why, when last read), whether it is the recorded process."""
        pid = int(rec.get('pid') or 0)
        up = listening(host, port)
        status, _ = http_json('http://%s:%d/-/ready' % (host, port)) if up else (0, '')
        targets = []
        if status == 200:
            s2, data = http_json('http://%s:%d/api/v1/targets?state=active' % (host, port))
            if s2 == 200 and isinstance(data, dict):
                for t in (data.get('data') or {}).get('activeTargets') or []:
                    targets.append({'job': (t.get('labels') or {}).get('job', ''), 'url': t.get('scrapeUrl', ''),
                                    'health': t.get('health', ''), 'error': t.get('lastError', ''),
                                    'last': t.get('lastScrape', ''), 'seconds': t.get('lastScrapeDuration')})
        pid_alive = recorded_process_alive(pid, rec.get('_written', 0), alive) if pid else False
        return {'running': status == 200, 'listening': up, 'pid': pid, 'pid_alive': pid_alive,
                'ours': bool(pid) and up and pid_alive, 'targets': targets}

    def run(self,
            ctx: dict,
            action: str = 'start',          # start | status | stop | restart | reload | import
            port: int = DEFAULT_PORT,       # 9090 by default (Prometheus' own)
            host: str = '127.0.0.1',        # the address to listen on (another than 127.0.0.1: anyone who reaches it reads every series - Prometheus has no sign-in)
            targets: str = '',              # the servers it reads, <name>=<host:port> or <name>=<URL>, separated by commas (default: the config's, else the AI gateway, llama.cpp and vLLM of this machine)
            scrape_interval: str = '',      # how often it reads every target (default: the config's, else 10s)
            retention: str = '',            # how long it keeps what it read (default: the config's, else 365d)
            timeout: int = 60,              # seconds to wait for it to be ready before "start" gives up
            foreground: bool = False,       # keep the server attached to this console (its log on the screen; Ctrl-C ends it)
            file: str = '',                 # import: OpenMetrics with timestamps (e.g. the AI gateway server's lines, its action to-prometheus)
            since: str = '',                # import: the time its samples start (Unix seconds; for the record of imports)
            until: str = '',                # import: the time they end (Unix seconds; for the record of imports)
            unparsed: list = None,          # extra words for prometheus (everything after "--")
    ):
        """
        A Prometheus server on this machine that reads the /metrics of the AI gateway and the model servers.

            cx task run run-prometheus-server
            cx task run run-prometheus-server --action=status
            cx task run run-prometheus-server --action=stop
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        action = str(action or 'start').strip().lower()
        port = int(port)
        st = self._state(ctx, port)
        if st['return'] > 0:
            return st
        folder = st['path']
        rec = self._read_record(folder)
        status = self._status(host, port, rec)

        status['imports'] = self._read_json(os.path.join(folder, 'imports.json'), [])
        status['scraped_since'] = self._scraped_since(folder, host, port, status['running'])

        if action == 'import':
            return self._import(ctx, folder, host, port, rec, status, file, since, until, con)

        if action == 'status':
            if con:
                if status['running']:
                    print('Prometheus on %s:%d: up (pid %s%s); data: %s' % (host, port, rec.get('pid', '?'),
                          '' if status['pid_alive'] else ' - not the recorded process', rec.get('data', '?')))
                    for t in status['targets']:
                        print('  %-28s %-6s %s%s' % (t['job'], t['health'], t['url'], ('  - ' + t['error']) if t['error'] else ''))
                elif status['listening']:
                    print('something listens on %s:%d but does not answer /-/ready as Prometheus' % (host, port))
                else:
                    print('Prometheus on %s:%d: down' % (host, port))
            return {'return': 0, 'port': port, 'host': host, 'state': folder, 'record': rec, **status}

        if action in ('stop', 'restart'):
            pid = int(rec.get('pid') or 0)
            # only the process the record was written for: after a reboot its number may be any other program's
            if pid and recorded_process_alive(pid, rec.get('_written', 0), alive):
                stop_process(pid)
                for _ in range(100):
                    if not alive(pid):
                        break
                    time.sleep(0.2)
                if con:
                    print('Prometheus on port %d: stopped (pid %d)' % (port, pid))
            elif status['listening'] and con:
                print('port %d is taken by a process this task did not start - not stopped' % port)
            elif con:
                print('Prometheus on port %d: not running' % port)
            try:
                os.remove(os.path.join(folder, 'server.json'))
            except OSError:
                pass
            if action == 'stop':
                return {'return': 0, 'port': port, 'stopped': bool(pid)}
            status = self._status(host, port, {})

        if action == 'reload':
            return self._reload(ctx, folder, host, port, rec, status, targets, scrape_interval, con)

        if action not in ('start', 'restart'):
            return self.cm.error('--action must be start, status, stop, restart, reload or import (got "%s")' % action)

        if status['running']:
            if con:
                print('Prometheus on %s:%d is up already (pid %s)' % (host, port, rec.get('pid', '?')))
            return {'return': 0, 'port': port, 'host': host, 'already': True, 'state': folder, 'record': rec, **status}
        if status['listening']:
            return self.cm.error('port %d is taken by another process; --port=<another> or stop it' % port)

        # what the command line does not say: the config of this machine, else built in
        d = self._defaults()
        try:
            chosen = parse_targets(targets or d['targets'])
        except ValueError as e:
            return self.cm.error(str(e))
        scrape_interval, retention = str(scrape_interval or d['scrape_interval']), str(retention or d['retention'])

        # the tool (installed from its release, checked), and promtool beside it to check the configuration
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': TOOL, 'ctx': ctx,
                            'con': con, 'quiet': quiet})
        if r.get('return', 1) > 0:
            return r
        server = str(r.get('path') or '')
        exe = '.exe' if os.name == 'nt' else ''
        promtool = os.path.join(os.path.dirname(server), 'promtool' + exe)

        cfg = os.path.join(folder, 'prometheus.yml')
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write(config_text(chosen, scrape_interval))
        if os.path.isfile(promtool):
            c = subprocess.run([promtool, 'check', 'config', cfg], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if c.returncode:
                return self.cm.error('promtool finds the configuration %s wrong:\n%s' % (cfg, (c.stdout + c.stderr).strip()[-1500:]))
        data = os.path.join(folder, 'data')
        os.makedirs(data, exist_ok=True)
        if not has_data(data) and not os.path.isfile(os.path.join(folder, 'scraped-since.txt')):
            with open(os.path.join(folder, 'scraped-since.txt'), 'w', encoding='utf-8') as f:
                f.write('%.3f\n' % time.time())

        # 127.0.0.1 only by default; the lifecycle endpoints (/-/reload, /-/quit) for whoever reaches it - this machine
        command = [server, '--config.file=' + cfg, '--storage.tsdb.path=' + data, '--storage.tsdb.retention.time=' + retention,
                   '--web.listen-address=%s:%d' % (host, port), '--web.enable-lifecycle']
        command += [str(u) for u in unparsed] if unparsed else []
        log = os.path.join(folder, 'server.log')
        rec = {'port': port, 'host': host, 'targets': [t['name'] + '=' + t['address'] + (t['path'] if t['path'] != '/metrics' else '') for t in chosen],
               'scrape_interval': scrape_interval, 'retention': retention, 'data': data, 'config': cfg, 'command': command,
               'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
        if con:
            print('')
            print('RUN: %s' % ' '.join(command))
            print('     (log: %s)' % (log if not foreground else 'this console'))
        if foreground:
            # in this console (a host keeps the server so: server: run); its record all the same, gone when it ends
            p = subprocess.Popen(command)
            self._write_record(folder, dict(rec, pid=p.pid, foreground=True, log=''))
            try:
                rc = p.wait()
            except KeyboardInterrupt:
                p.terminate()
                rc = 0
            try:
                os.remove(os.path.join(folder, 'server.json'))
            except OSError:
                pass
            return {'return': 0, 'port': port, 'returncode': rc, 'foreground': True}

        with open(log, 'ab') as out:
            if os.name == 'nt':
                # a hidden console of its own, not none: a program it starts shares it (Grafana starts one per data
                # source plugin) - detached from any console, each of them opened a window of its own (2026-11-19)
                p = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=0x08000000 | 0x00000200)        # CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP
            else:
                p = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        rec = dict(rec, pid=p.pid, log=log)
        self._write_record(folder, rec)

        started = time.monotonic()
        ready = False
        while time.monotonic() - started < int(timeout):
            if p.poll() is not None:
                break
            s, _ = http_json('http://%s:%d/-/ready' % (host, port), timeout=2)
            if s == 200:
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            tail = ''
            try:
                with open(log, 'rb') as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 1500))
                    tail = f.read().decode('utf-8', 'replace')
            except OSError:
                pass
            if p.poll() is not None:
                return self.cm.error('prometheus ended with code %s before it was ready; its log %s ends with:\n%s' % (p.returncode, log, tail))
            return self.cm.error('prometheus was not ready within %d s; its log %s ends with:\n%s' % (int(timeout), log, tail))
        status = self._status(host, port, rec)
        if con:
            print('Prometheus up on http://%s:%d (pid %d) in %.1f s, reading: %s' % (host, port, p.pid, time.monotonic() - started,
                  ', '.join(rec['targets'])))
            print('  stop: cx task run run-prometheus-server --action=stop --port=%d' % port)
        return {'return': 0, 'port': port, 'host': host, 'pid': p.pid, 'state': folder, 'record': rec,
                'seconds': round(time.monotonic() - started, 1), **status}

    def _import(self, ctx, folder, host, port, rec, status, file, since, until, con):
        """
        Samples with timestamps (OpenMetrics) into this Prometheus: promtool makes blocks of them in a folder of the
        state artifact, the server is stopped, the blocks join its data, the server starts again as it ran (one that its
        host keeps is started again by its supervisor). Recorded in imports.json. A time it read live is never imported
        over: the samples must end before scraped_since (the caller asks the status for it).
        """
        if not file or not os.path.isfile(file):
            return self.cm.error('--file=<OpenMetrics with timestamps> is missing or not a file: "%s"' % file)
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': TOOL, 'ctx': ctx,
                            'con': False, 'quiet': True})
        if r.get('return', 1) > 0:
            return r
        exe = '.exe' if os.name == 'nt' else ''
        promtool = os.path.join(os.path.dirname(str(r.get('path') or '')), 'promtool' + exe)
        if not os.path.isfile(promtool):
            return self.cm.error('no promtool beside %s' % r.get('path'))

        tmp = os.path.join(folder, 'import-blocks')
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        c = subprocess.run([promtool, 'tsdb', 'create-blocks-from', 'openmetrics', file, tmp],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if c.returncode:
            return self.cm.error('promtool could not make blocks of %s:\n%s' % (file, (c.stdout + c.stderr).strip()[-1500:]))
        blocks = sorted(n for n in os.listdir(tmp) if os.path.isfile(os.path.join(tmp, n, 'meta.json')))

        was = bool(status['ours'])
        foreground = bool(rec.get('foreground'))
        if was:
            self.run(ctx, action='stop', port=port, host=host)
        data = os.path.join(folder, 'data')
        os.makedirs(data, exist_ok=True)
        for b in blocks:
            os.replace(os.path.join(tmp, b), os.path.join(data, b))
        shutil.rmtree(tmp, ignore_errors=True)

        entry = {'file': file, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'blocks': blocks,
                 'since': float(since) if str(since).strip() else None, 'until': float(until) if str(until).strip() else None}
        imports = self._read_json(os.path.join(folder, 'imports.json'), [])
        imports.append(entry)
        with open(os.path.join(folder, 'imports.json'), 'w', encoding='utf-8') as f:
            json.dump(imports, f, indent=1)
        if con:
            print('Prometheus on port %d: %d block(s) imported from %s' % (port, len(blocks), file))

        if was and not foreground:
            r = self.run(ctx, action='start', port=port, host=host, targets=','.join(rec.get('targets') or []),
                         scrape_interval=str(rec.get('scrape_interval') or ''), retention=str(rec.get('retention') or ''))
            if r.get('return', 1) > 0:
                return r
        elif was and con:
            print('  its host keeps it: its supervisor starts it again')
        return {'return': 0, 'port': port, 'imported': entry, 'restarted': was}

    def _reload(self, ctx, folder, host, port, rec, status, targets, scrape_interval, con):
        """
        The targets and the interval as the config says now (or the command line): prometheus.yml written beside the one
        in use, checked with promtool, put in its place and - while the server runs - read again by it (POST /-/reload:
        no restart, nothing lost). A server that is down takes it at its next start. The retention is a flag of the
        process: a change of it needs a restart.
        """
        d = self._defaults()
        try:
            chosen = parse_targets(targets or d['targets'])
        except ValueError as e:
            return self.cm.error(str(e))
        interval = str(scrape_interval or d['scrape_interval'])
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': TOOL, 'ctx': ctx,
                            'con': False, 'quiet': True})
        if r.get('return', 1) > 0:
            return r
        promtool = os.path.join(os.path.dirname(str(r.get('path') or '')), 'promtool' + ('.exe' if os.name == 'nt' else ''))
        cfg = os.path.join(folder, 'prometheus.yml')
        new = cfg + '.new'
        with open(new, 'w', encoding='utf-8') as f:
            f.write(config_text(chosen, interval))
        if os.path.isfile(promtool):
            c = subprocess.run([promtool, 'check', 'config', new], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if c.returncode:
                os.remove(new)
                return self.cm.error('promtool finds the new configuration wrong - the one in use is kept:\n%s' % (c.stdout + c.stderr).strip()[-1500:])
        os.replace(new, cfg)
        reloaded = False
        if status['running']:
            try:
                req = urllib.request.Request('http://%s:%d/-/reload' % (host, port), data=b'', method='POST')
                with urllib.request.urlopen(req, timeout=20) as resp:
                    reloaded = resp.status == 200
            except Exception as e:
                return self.cm.error('Prometheus on port %d did not read the new configuration again: %s' % (port, e))
            if rec:
                rec = {k: v for k, v in rec.items() if k != '_written'}
                rec['targets'] = [t['name'] + '=' + t['address'] + (t['path'] if t['path'] != '/metrics' else '') for t in chosen]
                rec['scrape_interval'] = interval
                self._write_record(folder, rec)
        if con:
            print('Prometheus on port %d: %d target(s) %s - %s' % (port, len(chosen), 'read again by the running server' if reloaded
                  else 'written for its next start', ', '.join(t['name'] for t in chosen)))
        return {'return': 0, 'port': port, 'reloaded': reloaded, 'config': cfg,
                'targets': [{'name': t['name'], 'address': t['address'], 'path': t['path'], 'scheme': t['scheme']} for t in chosen]}
