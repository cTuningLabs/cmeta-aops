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

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CATEGORY = 'task,c36be4b9314a45e0'
STATE_CATEGORY = 'state'
TOOL = 'llama-cpp,daa99512448647b7'
SETUP_TASK = 'setup,a2f9b61079ce4333'
MODEL_TASK = 'model,86f0effd07ad454d'

DEFAULT_MODEL = 'hf-Qwen@Qwen3-8B-GGUF'
DEFAULT_PORT = 8686


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

    @staticmethod
    def _read_record(folder):
        fp = os.path.join(folder, 'server.json')
        if not os.path.isfile(fp):
            return {}
        try:
            with open(fp, encoding = 'utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _status(self, host, port, rec):
        """Running (the recorded process alive, or anything answering /health), the models it serves."""
        pid = int(rec.get('pid') or 0)
        up = listening(host, port)
        status, health = http_json('http://%s:%d/health' % (host, port)) if up else (0, '')
        models = []
        if status == 200:
            s2, data = http_json('http://%s:%d/v1/models' % (host, port))
            if s2 == 200 and isinstance(data, dict):
                models = [str(m.get('id')) for m in data.get('data') or [] if isinstance(m, dict) and m.get('id')]
        return {'running': status == 200, 'listening': up, 'health': health if status == 200 else '',
                'pid': pid, 'pid_alive': alive(pid) if pid else False, 'models': models,
                'ours': bool(pid) and alive(pid) and up}

    def run(self,
            ctx: dict,
            action: str = 'start',          # start | status | stop | restart
            model: str = DEFAULT_MODEL,     # the model artifact (cx model ls), a GGUF one
            filename: str = '',             # which file of the model artifact (its _desc-<file>.yaml); the artifact's first by default
            port: int = DEFAULT_PORT,       # 8686 by default (not llama.cpp's 8080: the busiest port of a developer's machine)
            host: str = '127.0.0.1',        # the address to listen on (0.0.0.0 for other machines - then the key is their only protection: none)
            compute: str = 'cuda',          # the llama.cpp build: cuda | cpu | metal (the tool is built or installed for it)
            ctx_size: int = 32768,          # the context window in tokens (Claude Code's first request alone is about 17k: below 24k it fails)
            gpu_layers: str = 'auto',       # layers on the GPU: auto = llama.cpp fits them to the device memory (its --fit), else a number (-ngl)
            alias: str = '',                # the model's name in /v1/models and in the harnesses (the file's name by default)
            parallel: int = 1,              # concurrent requests the server takes
            timeout: int = 300,             # seconds to wait for the model to load before "start" gives up
            foreground: bool = False,       # keep the server attached to this console (its log on the screen; Ctrl-C ends it)
            unparsed: list = None,          # extra words for llama-server (everything after "--")
    ):
        """
        A llama.cpp server on this machine, detached, with the Anthropic, chat and Responses wires on one port.

            cx task run run-llama-cpp-server                                   # Qwen3-8B (Q4_K_M) on CUDA, port 8686
            cx task run run-llama-cpp-server --model=hf-ggml-org@gpt-oss-20b-GGUF      # the larger model: the layers that fit on the GPU
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
                    print('  model file: %s' % rec.get('model_path', '?'))
                    print('  log: %s' % os.path.join(folder, 'server.log'))
                elif status['listening']:
                    print('something listens on %s:%d but does not answer /health as llama.cpp' % (host, port))
                else:
                    print('llama.cpp server on %s:%d: down' % (host, port))
            return {'return': 0, 'port': port, 'host': host, 'state': folder, 'record': rec, **status}

        if action in ('stop', 'restart'):
            pid = int(rec.get('pid') or 0)
            if pid and alive(pid):
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
            if action == 'stop':
                return {'return': 0, 'port': port, 'stopped': bool(pid)}
            status = self._status(host, port, {})

        if action != 'start' and action != 'restart':
            return self.cm.error('--action must be start, status, stop or restart (got "%s")' % action)

        if status['running']:
            if con:
                print('llama.cpp server on %s:%d is up already (pid %s), models: %s' % (host, port, rec.get('pid', '?'), ', '.join(status['models'])))
            return {'return': 0, 'port': port, 'host': host, 'already': True, 'state': folder, 'record': rec, **status}
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
        mp = {'category': TASK_CATEGORY, 'command': 'run', 'arg1': MODEL_TASK, 'name': model, 'ctx': ctx, 'con': con, 'quiet': quiet}
        if filename:
            mp['filename'] = filename
        r = self.cm.access(mp)
        if r.get('return', 1) > 0:
            return r
        model_path = str(r.get('path') or '')
        if os.path.isdir(model_path):
            ggufs = sorted(f for f in os.listdir(model_path) if f.lower().endswith('.gguf'))
            if not ggufs:
                return self.cm.error('no .gguf file in %s' % model_path)
            model_path = os.path.join(model_path, ggufs[0])
        if not os.path.isfile(model_path):
            return self.cm.error('the model file is missing: %s' % model_path)
        name = alias or os.path.splitext(os.path.basename(model_path))[0]

        # the context is set, so llama.cpp's --fit (on by default in the builds since 2026) never shrinks it; the GPU
        # layers are left to --fit unless a number is given (-ngl): a model larger than the GPU's memory then loads
        # as many layers as fit and keeps the rest on the CPU
        command = [server, '-m', model_path, '--host', host, '--port', str(port), '-c', str(int(ctx_size)),
                   '--jinja', '--alias', name, '-np', str(int(parallel))]
        if str(gpu_layers).strip().lower() not in ('', 'auto'):
            command += ['-ngl', str(int(gpu_layers))]
        command += [str(u) for u in unparsed] if unparsed else []
        log = os.path.join(folder, 'server.log')
        if con:
            print('')
            print('RUN: %s' % ' '.join(command))
            print('     (log: %s)' % log)
        if foreground:
            try:
                rc = subprocess.call(command)
            except KeyboardInterrupt:
                rc = 0
            return {'return': 0, 'port': port, 'returncode': rc, 'foreground': True}

        with open(log, 'ab') as out:
            if os.name == 'nt':
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL,
                                     creationflags = 0x00000008 | 0x00000200)        # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
            else:
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL,
                                     start_new_session = True)
        rec = {'pid': p.pid, 'port': port, 'host': host, 'model': model, 'model_path': model_path, 'alias': name,
               'compute': compute, 'command': command, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'log': log}
        with open(os.path.join(folder, 'server.json'), 'w', encoding = 'utf-8') as f:
            json.dump(rec, f, indent = 1)

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
            print('  wires: /v1/messages (Anthropic), /v1/chat/completions, /v1/responses; stop: cx task run run-llama-cpp-server --action=stop --port=%d' % port)
        return {'return': 0, 'port': port, 'host': host, 'pid': p.pid, 'state': folder, 'record': rec, 'seconds': round(time.monotonic() - started, 1), **status}
