"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-llama-cpp-server - a llama.cpp server on this machine (README.md): start (detached: a record and a log in a
state artifact), status, stop. The server speaks the Anthropic Messages API (/v1/messages), chat completions and the
Responses API (/v1/responses) on one port - 8686 by default, since llama.cpp's own 8080 is the busiest port of a
developer's machine - so Claude Code, Codex and OpenCode can all use it through an ai.gateway artifact
(ai.gateway::llama-cpp-local names this task as its provider).
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask, recorded_process_alive

TASK_CATEGORY = 'task,c36be4b9314a45e0'
STATE_CATEGORY = 'state'
TOOL = 'llama-cpp,daa99512448647b7'
SETUP_TASK = 'setup,a2f9b61079ce4333'
MODEL_TASK = 'model,86f0effd07ad454d'

DEFAULT_MODEL = 'hf-Qwen@Qwen3-8B-GGUF'
DEFAULT_PORT = 8686

# What a start takes when its command line does not say: the keys of this config (in the local repository: this
# machine's), else these. A page of the server (or cx config set task-run-llama-cpp-server --meta.<key>=<value>) sets
# them; a server kept by its host (server: run: cxt run-llama-cpp-server --foreground) takes them at its next start.
CONFIG = 'task-run-llama-cpp-server'
BUILT_IN = {'model': DEFAULT_MODEL, 'filename': '', 'compute': 'cuda', 'ctx_size': 32768, 'gpu_layers': 'auto',
            'alias': '', 'parallel': 1, 'models': '', 'models_max': 1}


def listening(host, port, timeout = 1.0):
    """Something accepts connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout = timeout):
            return True
    except OSError:
        return False


def alive(pid):
    if os.name == 'nt':
        r = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH'], capture_output = True, text = True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output = True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def http_json(url, timeout = 5):
    """GET -> (status, the parsed JSON or the text)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout = timeout) as r:
            text = r.read().decode('utf-8', 'replace')
            try:
                return r.status, json.loads(text)
            except ValueError:
                return r.status, text[:200]
    except Exception as e:
        return 0, str(e)


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def _state(self, ctx, port):
        """The state artifact of the server on this port (local:llama-cpp-server-<port>): its folder."""
        r = self.cm.access({'category': STATE_CATEGORY, 'command': 'get', 'arg1': 'local:llama-cpp-server-%d' % port,
                            'ctx': ctx, 'con': False})
        if r.get('return', 1) > 0:
            return r
        return {'return': 0, 'path': r['artifact']['path']}

    def _defaults(self):
        """The defaults of a start: config::task-run-llama-cpp-server over BUILT_IN (a key empty or absent: built in)."""
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
        with open(os.path.join(folder, 'server.json'), 'w', encoding = 'utf-8') as f:
            json.dump(rec, f, indent = 1)

    @staticmethod
    def _read_record(folder):
        fp = os.path.join(folder, 'server.json')
        if not os.path.isfile(fp):
            return {}
        try:
            with open(fp, encoding = 'utf-8') as f:
                rec = json.load(f)
            rec['_written'] = os.path.getmtime(fp)      # when the record was written: its process must be of that run
            return rec
        except Exception:
            return {}

    def _status(self, host, port, rec):
        """Running (the recorded process alive, or anything answering /health), the models it serves."""
        pid = int(rec.get('pid') or 0)
        up = listening(host, port)
        status, health = http_json('http://%s:%d/health' % (host, port)) if up else (0, '')
        models, loaded = [], []
        if status == 200:
            s2, data = http_json('http://%s:%d/v1/models' % (host, port))
            if s2 == 200 and isinstance(data, dict):
                for m in data.get('data') or []:
                    if not isinstance(m, dict) or not m.get('id'):
                        continue
                    models.append(str(m['id']))
                    # a server of several models (the router) says the state of each: loaded, unloaded, loading ...
                    state = m.get('status')
                    state = state.get('value') if isinstance(state, dict) else state
                    if state == 'loaded':
                        loaded.append(str(m['id']))
        return {'running': status == 200, 'listening': up, 'health': health if status == 200 else '',
                'pid': pid, 'pid_alive': recorded_process_alive(pid, rec.get('_written', 0), alive) if pid else False,
                'models': models, 'loaded': loaded,
                'ours': bool(pid) and up and recorded_process_alive(pid, rec.get('_written', 0), alive)}

    def _stop(self, folder, rec, status, port, con):
        """Stop the server this task started on the port - never another program's - and forget its record."""
        pid = int(rec.get('pid') or 0)
        # only the process the record was written for: after a reboot its number may be any other program's
        if pid and recorded_process_alive(pid, rec.get('_written', 0), alive):
            stop_process(pid)
            for _ in range(50):
                if not alive(pid):
                    break
                time.sleep(0.2)
            if con:
                print('llama.cpp server on port %d: stopped (pid %d)' % (port, pid))
        elif status['listening'] and con:
            print('port %d is taken by a process this task did not start - not stopped' % port)
        elif con:
            print('llama.cpp server on port %d: not running' % port)
        try:
            os.remove(os.path.join(folder, 'server.json'))
        except OSError:
            pass
        return bool(pid)

    @staticmethod
    def _serves(rec, one, many):
        """Does the server of this record serve what is asked for - the one model artifact, or every one of the many
        (those need a server of several models)? A server without a record is not known to serve anything."""
        have = [str(x).split(',')[0] for x in (rec.get('models') or ([rec['model']] if rec.get('model') else []))]
        want = [str(x).split(',')[0] for x in (many or [one])]
        return bool(have) and all(w in have for w in want) and (not many or bool(rec.get('router')))

    def _model_file(self, ctx, model, filename, con, quiet):
        """The GGUF file of a model artifact (the model task gets it): (its path, None) or ('', the error)."""
        mp = {'category': TASK_CATEGORY, 'command': 'run', 'arg1': MODEL_TASK, 'name': model, 'ctx': ctx, 'con': con, 'quiet': quiet}
        if filename:
            # a file of the model artifact, named as its description is (_desc-<file>.yaml: the model task's
            # "filedesc"); a GGUF file of this machine, given by its path, is served as it is (its "filename")
            mp['filename' if os.path.isfile(filename) else 'filedesc'] = filename
        r = self.cm.access(mp)
        if r.get('return', 1) > 0:
            return '', r
        model_path = str(r.get('path') or '')
        if os.path.isdir(model_path):
            ggufs = sorted(f for f in os.listdir(model_path) if f.lower().endswith('.gguf'))
            if not ggufs:
                return '', self.cm.error('no .gguf file in %s' % model_path)
            model_path = os.path.join(model_path, ggufs[0])
        if not os.path.isfile(model_path):
            return '', self.cm.error('the model file is missing: %s' % model_path)
        return model_path, None

    def run(self,
            ctx: dict,
            action: str = 'start',          # start | status | stop | restart
            model: str = '',                # the model artifact (cx model ls), a GGUF one (default: the config's, else Qwen3-8B)
            filename: str = '',             # which file of the model artifact (its _desc-<file>.yaml); the artifact's first by default
            port: int = DEFAULT_PORT,       # 8686 by default (not llama.cpp's 8080: the busiest port of a developer's machine)
            host: str = '127.0.0.1',        # the address to listen on (0.0.0.0 for other machines - then the key is their only protection: none)
            compute: str = '',              # the llama.cpp build: cuda | cpu | metal (the tool is built or installed for it; default: the config's, else cuda)
            ctx_size: int = 0,              # the context window in tokens (default: the config's, else 32768 - Claude Code's first request alone is about 17k: below 24k it fails)
            gpu_layers: str = '',           # layers on the GPU: auto = llama.cpp fits them to the device memory (its --fit), else a number (-ngl); default: the config's, else auto
            alias: str = '',                # the model's name in /v1/models and in the harnesses (default: the config's, else the file's name)
            parallel: int = 0,              # concurrent requests the server takes (default: the config's, else 1)
            models: str = '',               # several model artifacts behind one server, each loaded when a request names it (llama.cpp's router): a;b;c (default: the config's; none - one model)
            models_max: int = 0,            # with --models: how many stay loaded at once - the least recently used is unloaded first (default: the config's, else 1)
            swap: bool = False,             # a start that finds the server up with something else than asked for replaces it (default: it is left as it is, and said)
            timeout: int = 300,             # seconds to wait for the model to load before "start" gives up
            foreground: bool = False,       # keep the server attached to this console (its log on the screen; Ctrl-C ends it)
            unparsed: list = None,          # extra words for llama-server (everything after "--")
            workdir: str = '',              # the folder the detached server stands in (default: its state folder; with words after "--", the current one)
    ):
        """
        A llama.cpp server on this machine, detached, with the Anthropic, chat and Responses wires on one port.

            cx task run run-llama-cpp-server                                   # Qwen3-8B (Q4_K_M) on CUDA, port 8686
            cx task run run-llama-cpp-server --model=hf-ggml-org@gpt-oss-20b-GGUF      # the larger model: the layers that fit on the GPU
            cx task run run-llama-cpp-server --model=<another> --swap                  # replace the model a running server serves
            cx task run run-llama-cpp-server --models="<a>;<b>;<c>" --models_max=2     # several models, loaded on demand, two at once
            cx task run run-llama-cpp-server --action=status
            cx task run run-llama-cpp-server --action=stop
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

        if action == 'status':
            if con:
                if status['running']:
                    print('llama.cpp server on %s:%d: up (pid %s%s), models: %s' % (
                        host, port, rec.get('pid', '?'), '' if status['pid_alive'] else ' - not the recorded process',
                        ', '.join(status['models']) or '?'))
                    if rec.get('router'):
                        print('  several models, %s at once, loaded on demand; loaded now: %s' % (
                            rec.get('models_max', '?'), ', '.join(status['loaded']) or 'none'))
                    print('  model file: %s' % rec.get('model_path', '?'))
                    print('  log: %s' % os.path.join(folder, 'server.log'))
                elif status['listening']:
                    print('something listens on %s:%d but does not answer /health as llama.cpp' % (host, port))
                else:
                    print('llama.cpp server on %s:%d: down' % (host, port))
            return {'return': 0, 'port': port, 'host': host, 'state': folder, 'record': rec, **status}

        if action in ('stop', 'restart'):
            stopped = self._stop(folder, rec, status, port, con)
            if action == 'stop':
                return {'return': 0, 'port': port, 'stopped': stopped}
            status = self._status(host, port, {})

        if action != 'start' and action != 'restart':
            return self.cm.error('--action must be start, status, stop or restart (got "%s")' % action)

        # what the command line does not say: the config of this machine (the server's page sets it), else built in.
        # One model named on the command line is one model served, whatever the config says of several.
        d = self._defaults()
        named = bool(model or str(models or '').strip())
        many = [] if (model and not str(models or '').strip()) else \
            [m.strip() for m in str(models or d['models'] or '').split(';') if m.strip()]
        model, filename, compute = model or d['model'], filename or d['filename'], compute or d['compute']
        gpu_layers, alias = gpu_layers or d['gpu_layers'], alias or d['alias']
        ctx_size, parallel = int(ctx_size or 0) or int(d['ctx_size']), int(parallel or 0) or int(d['parallel'])
        models_max = int(models_max or 0) or int(d['models_max'] or 1)

        if status['running']:
            # up already. When the command line names what to serve and the server serves something else, it is left
            # as it is and that is said - or replaced, with --swap (only a server this task started)
            other = named and not self._serves(rec, model, many)
            asked = '; '.join(many) if many else model
            if other and swap:
                if not status.get('ours'):
                    return self.cm.error('port %d is served by a process this task did not start: it is not replaced '
                                         '(asked for %s)' % (port, asked))
                if con:
                    print('llama.cpp server on %s:%d serves %s; replaced by %s (--swap)' % (
                        host, port, ', '.join(status['models']) or '?', asked))
                self._stop(folder, rec, status, port, False)
                rec, status = {}, self._status(host, port, {})
            else:
                if con:
                    print('llama.cpp server on %s:%d is up already (pid %s), models: %s' % (host, port, rec.get('pid', '?'), ', '.join(status['models'])))
                    if other:
                        print('  it %s %s: add --swap to replace what it serves' % (
                            'does not serve' if rec else 'is not recorded to serve', asked))
                out = {'return': 0, 'port': port, 'host': host, 'already': True, 'state': folder, 'record': rec, **status}
                if other:
                    out.update({'other_model': True, 'requested': asked})
                return out
        if status['listening']:
            return self.cm.error('port %d is taken by another process; --port=<another> or stop it' % port)

        # the tool for this compute (built or installed by the setup task), and the model file
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': TOOL, 'ctx': ctx,
                            'with': {'compute': [compute]}, 'con': con, 'quiet': quiet})
        if r.get('return', 1) > 0:
            return r
        tool_path = str(r.get('path') or '')
        server = os.path.join(os.path.dirname(tool_path), 'llama-server' + ('.exe' if os.name == 'nt' else ''))
        if not os.path.isfile(server):
            return self.cm.error('no llama-server beside %s' % tool_path)

        env, router = None, {}
        if many:
            # several models behind one port: llama-server without a model is a router that starts each model as its
            # own instance when a request names it and unloads the least recently used one beyond --models-max. The
            # models are those asked for and no others: a preset file names them, and llama.cpp's own cache of
            # downloads is pointed at an empty folder, so nothing else is listed.
            names, lines = [], ['version = 1', '', '[*]', 'ctx-size = %d' % int(ctx_size), 'parallel = %d' % int(parallel),
                                'jinja = true']
            if str(gpu_layers).strip().lower() not in ('', 'auto'):
                lines.append('n-gpu-layers = %d' % int(gpu_layers))
            for artifact in many:
                path, err = self._model_file(ctx, artifact, '', con, quiet)
                if err:
                    return err
                one = os.path.splitext(os.path.basename(path))[0]
                if one in names:
                    return self.cm.error('two of --models have a file of the same name (%s): a request could not tell them apart' % one)
                names.append(one)
                lines += ['', '[%s]' % one, 'model = %s' % path.replace('\\', '/')]
            model_path = os.path.join(folder, 'models.ini')
            with open(model_path, 'w', encoding = 'utf-8', newline = '\n') as f:
                f.write('\n'.join(lines) + '\n')
            empty = os.path.join(folder, 'no-other-models')
            os.makedirs(empty, exist_ok = True)
            env = dict(os.environ, LLAMA_CACHE = empty)
            name = ', '.join(names)
            command = [server, '--models-preset', model_path, '--models-max', str(int(models_max)), '--host', host,
                       '--port', str(port), '--metrics']
            router = {'router': True, 'models': many, 'model_names': names, 'models_max': int(models_max)}
            model = '; '.join(many)
        else:
            model_path, err = self._model_file(ctx, model, filename, con, quiet)
            if err:
                return err
            name = alias or os.path.splitext(os.path.basename(model_path))[0]

            # the context is set, so llama.cpp's --fit (on by default in the builds since 2026) never shrinks it; the GPU
            # layers are left to --fit unless a number is given (-ngl): a model larger than the GPU's memory then loads
            # as many layers as fit and keeps the rest on the CPU
            command = [server, '-m', model_path, '--host', host, '--port', str(port), '-c', str(int(ctx_size)),
                       '--jinja', '--alias', name, '-np', str(int(parallel)),
                       '--metrics']             # its numbers at /metrics (Prometheus' format): for its page and any scraper
            if str(gpu_layers).strip().lower() not in ('', 'auto'):
                command += ['-ngl', str(int(gpu_layers))]
        command += [str(u) for u in unparsed] if unparsed else []
        log = os.path.join(folder, 'server.log')
        if con:
            print('')
            print('RUN: %s' % ' '.join(command))
            print('     (log: %s)' % log)
        if foreground:
            # in this console, its log on the screen (a host keeps the server so: server: run); its record all the
            # same, so that the status and the server's page know what runs, and gone when it ends
            p = subprocess.Popen(command, env = env)
            self._write_record(folder, dict({'pid': p.pid, 'port': port, 'host': host, 'model': model, 'model_path': model_path,
                                             'alias': name, 'compute': compute, 'ctx_size': int(ctx_size), 'gpu_layers': str(gpu_layers),
                                             'parallel': int(parallel), 'command': command, 'foreground': True,
                                             'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'log': ''}, **router))
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

        # the folder a detached server stands in (2026-11-21): it outlives the command, so by default its own state folder
        # - the folder of the command (a work item, say) stays free to be moved, renamed or deleted on Windows. Words
        # passed on after "--" may name files by a relative path: with them, where the command was given, as before;
        # --workdir says where in any case
        cwd = workdir or (os.getcwd() if unparsed else folder)
        with open(log, 'ab') as out:
            if os.name == 'nt':
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL, env = env, cwd = cwd,
                                     creationflags = 0x00000008 | 0x00000200)        # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
            else:
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL, env = env, cwd = cwd,
                                     start_new_session = True)
        rec = dict({'pid': p.pid, 'port': port, 'host': host, 'model': model, 'model_path': model_path, 'alias': name,
                    'compute': compute, 'ctx_size': int(ctx_size), 'gpu_layers': str(gpu_layers), 'parallel': int(parallel),
                    'command': command, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'log': log}, **router)
        self._write_record(folder, rec)

        # the model loads: /health answers 503 meanwhile, 200 when ready
        started = time.monotonic()
        ready = False
        while time.monotonic() - started < int(timeout):
            if p.poll() is not None:
                break
            s, _ = http_json('http://%s:%d/health' % (host, port), timeout = 2)
            if s == 200:
                ready = True
                break
            time.sleep(1)
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
                return self.cm.error('llama-server ended with code %s before it was ready; its log %s ends with:\n%s' % (p.returncode, log, tail))
            return self.cm.error('llama-server did not answer /health within %d s (still loading? --timeout=<more>); log %s ends with:\n%s' % (int(timeout), log, tail))
        status = self._status(host, port, rec)
        if con:
            print('llama.cpp server up on http://%s:%d (pid %d) in %.0f s: %s' % (host, port, p.pid, time.monotonic() - started, ', '.join(status['models'])))
            if router:
                print('  several models: each is loaded when a request names it in "model", %d at once' % int(models_max))
            print('  wires: /v1/messages (Anthropic), /v1/chat/completions, /v1/responses; stop: cx task run run-llama-cpp-server --action=stop --port=%d' % port)
        return {'return': 0, 'port': port, 'host': host, 'pid': p.pid, 'state': folder, 'record': rec, 'seconds': round(time.monotonic() - started, 1), **status}
