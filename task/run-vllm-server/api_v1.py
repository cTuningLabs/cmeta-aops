"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-vllm-server - a vLLM server on this machine, in vLLM's own container image (vllm/vllm-openai) with the GPU: start
(detached, or in the foreground for a host that keeps it), status, logs, stop. Its OpenAI wires (/v1/chat/completions,
/v1/responses, /v1/models) answer on 127.0.0.1:<port>, its numbers at /metrics. What a start takes when its command
line does not say comes from config::task-run-vllm-server (README.md).
"""

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CATEGORY = 'task,c36be4b9314a45e0'
SETUP_TASK = 'setup,a2f9b61079ce4333'
CONTAINER_RUN = 'container-run,1eeecb521ba540f2'
DOCKER = 'docker,fd2bb541ed094b7a'
STATE_CATEGORY = 'state'

DEFAULT_PORT = 8868
INNER_PORT = 8000                      # vLLM's own port inside its container
CACHE_ARTIFACT = 'local:vllm-cache'    # mounted as the container's /root/.cache: the models (huggingface/) and vLLM's compile cache

# What a start takes when its command line does not say: the keys of this config (this machine's), else these
CONFIG = 'task-run-vllm-server'
BUILT_IN = {'model': 'Qwen/Qwen3-0.6B', 'image': 'vllm/vllm-openai:v0.34.0', 'max_model_len': 8192,
            'gpu_memory_utilization': 0.0, 'served_name': '', 'max_num_seqs': 0}

# The share of the GPU's memory, when neither the command line nor the config names one: vLLM sizes its KV cache
# itself since 0.34.0 (the "extensible KV cache", gpu_memory_utilization 1.0 by default - its release notes: in most
# cases it is best not to set it), so the task passes nothing then; to an earlier vLLM, or an image whose tag names no
# release, it passes the share it always gave
OWN_CACHE_SINCE = (0, 34)
SHARE_BEFORE = 0.85


def image_release(image):
    """The vLLM release an image's tag names (vllm/vllm-openai:v0.34.0 -> (0, 34, 0); v0.34.0-efa too), or None when
    the tag names none (latest, nightly, a digest)."""
    m = re.search(r':v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-+][^/:]*)?$', str(image or ''))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def image_for_gpu(image, given, gpu_spec, nvidia_repository):
    """
    The image of a start on a GPU of this kind (gpus: in _desc.yaml): an image the command line names stays; else the
    default one - when it is vLLM's NVIDIA image, its release in the repository of this kind of GPU
    (vllm/vllm-openai:v0.34.0 -> vllm/vllm-openai-rocm:v0.34.0); any other default image stays as it is.
    """
    if given:
        return image
    repository, sep, tag = str(image or '').rpartition(':')
    wanted = str((gpu_spec or {}).get('image_repository') or '')
    if sep and '/' not in tag and repository == nvidia_repository and wanted:
        return wanted + ':' + tag
    return image


def cache_volumes(cache, hf_cache = ''):
    """
    The container's caches: the task's own folder as its /root/.cache (vLLM's compiled kernels, and the models it
    downloads), and - with --hf_cache - a folder of Hugging Face models of this machine over its
    /root/.cache/huggingface, so a model downloaded once serves several servers (run-sglang-server takes the same word).
    """
    volumes = ['%s:/root/.cache' % cache]
    if hf_cache:
        volumes.append('%s:/root/.cache/huggingface' % hf_cache)
    return volumes


def model_folder(model):
    """
    A model in a folder of this machine (a model artifact's download, a model one made) instead of a Hugging Face id:
    mounted read-only into the container as /models/<the folder's name>. Returns (what vLLM is given, the volume or '').
    """
    if model and os.path.isdir(model):
        folder = os.path.abspath(model)
        inner = '/models/' + (os.path.basename(folder.rstrip('/\\')) or 'model')
        return inner, '%s:%s:ro' % (folder, inner)
    return model, ''


def http_get(url, timeout = 2.0):
    """GET -> (status or 0, the body's text)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout = timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception:
        return 0, ''


def listening(host, port, timeout = 1.0):
    try:
        with socket.create_connection((host, port), timeout = timeout):
            return True
    except OSError:
        return False


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'start',          # start | status | logs | stop | restart
            model: str = '',                # the model as Hugging Face names it, or a folder of this machine with one (default: the config's, else Qwen/Qwen3-0.6B)
            port: int = DEFAULT_PORT,       # 8868 by default (vLLM's own 8000 stays inside the container)
            host: str = '127.0.0.1',        # the address the port is published on (0.0.0.0 for other machines: there is no key)
            image: str = '',                # vLLM's container image, its release (default: the config's, else vllm/vllm-openai:v0.31.0)
            gpu: str = '',                  # the GPU's kind: nvidia (default) or amd - vLLM's image for it and how it is passed in (gpus: in _desc.yaml)
            max_model_len: int = 0,         # the context window in tokens (default: the config's, else 8192)
            gpu_memory_utilization: float = 0.0,   # the share of the GPU's memory vLLM takes (default: the config's, else by vLLM's release: none from 0.34 - vLLM sizes its cache -, 0.85 before)
            served_name: str = '',          # the model's name in /v1/models (default: the config's, else the model's own)
            max_num_seqs: int = 0,          # requests served at once (default: the config's, else vLLM's own)
            hf_cache: str = '',             # a folder of Hugging Face models to use instead of the task's own (mounted as the container's /root/.cache/huggingface)
            swap: bool = False,             # a start that finds the server up with another model than asked for replaces it (default: it is left as it is, and said)
            lines: int = 60,                # logs: how many of the last lines
            timeout: int = 1200,            # seconds a start waits for the server to answer (a first start downloads the model)
            foreground: bool = False,       # attached to this console (its log on the screen; a host keeps it so)
            unparsed: list = None,          # more words for vLLM (everything after "--")
    ):
        """
        A vLLM server on this machine in vLLM's own container, the GPU passed in.

            cx task run run-vllm-server                               # Qwen3-0.6B, port 8868, detached
            cx task run run-vllm-server --model=Qwen/Qwen3-4B --max_model_len=16384
            cx task run run-vllm-server --model=<another> --swap      # replace the model a running server serves
            cx task run run-vllm-server --model=<another> --port=8869 # a second server: vLLM serves one model each
            cx task run run-vllm-server --model=openai/gpt-oss-120b --hf_cache=/data/hf  # a model downloaded before
            cx task run run-vllm-server --action=status|logs|stop|restart
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        action = str(action or 'start').strip().lower()
        if action not in ('start', 'status', 'logs', 'stop', 'restart'):
            return self.cm.error('--action must be start, status, logs, stop or restart (got "%s")' % action)
        port = int(port)
        name = 'cmeta-vllm-%d' % port

        r = self._artifact('local:vllm-server-%d' % port, 'run-vllm-server: the record of the vLLM server on port %d' % port)
        if r['return'] > 0:
            return r
        folder = r['path']
        rec = self._read_record(folder)

        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': DOCKER, 'ctx': ctx,
                            'con': False, 'quiet': True})
        if r.get('return', 1) > 0:
            return r
        self.docker = str(r.get('path') or 'docker')

        status = self._status(name, host, port)

        if action == 'status':
            if con:
                if status['running']:
                    print('vLLM server on %s:%d: %s (container %s), models: %s' % (
                        host, port, 'up' if status['health'] == 200 else 'starting (no answer at /health yet)',
                        name, ', '.join(status['models']) or '?'))
                elif status['container']:
                    print('vLLM server on %s:%d: down - its container %s is %s' % (host, port, name, status['container']))
                else:
                    print('vLLM server on %s:%d: down' % (host, port))
            return {'return': 0, 'port': port, 'host': host, 'name': name, 'state': folder, 'record': rec, **status}

        if action == 'logs':
            text = self._logs(name, int(lines or 60))
            if con:
                print(text)
            return {'return': 0, 'name': name, 'logs': text}

        if action in ('stop', 'restart'):
            stopped = bool(status['container'])
            if stopped:
                self._docker('stop', '-t', '30', name, timeout = 90)
                self._docker('rm', '-f', name)
            try:
                os.remove(os.path.join(folder, 'server.json'))
            except OSError:
                pass
            if con:
                print('vLLM server on port %d: %s' % (port, 'stopped (container %s)' % name if stopped else 'not running'))
            if action == 'stop':
                return {'return': 0, 'port': port, 'stopped': stopped}
            status = self._status(name, host, port)

        if status['running']:
            # up already. When the command line names a model and the server serves another, it is left as it is and
            # that is said - or replaced, with --swap (vLLM serves one model per server: another one is another port)
            other = bool(model) and str(rec.get('model') or '') != str(model)
            if other and swap:
                if con:
                    print('vLLM server on %s:%d serves %s; replaced by %s (--swap)' % (host, port, rec.get('model') or '?', model))
                self._docker('stop', '-t', '30', name, timeout = 90)
                self._docker('rm', '-f', name)
                try:
                    os.remove(os.path.join(folder, 'server.json'))
                except OSError:
                    pass
                rec, status = {}, self._status(name, host, port)
            else:
                if con:
                    print('vLLM server on %s:%d is up already (container %s), models: %s' % (host, port, name, ', '.join(status['models'])))
                    if other:
                        print('  it %s %s: add --swap to replace it, or --port=<another> for a second server' % (
                            'does not serve' if rec.get('model') else 'is not recorded to serve', model))
                out = {'return': 0, 'port': port, 'host': host, 'already': True, 'state': folder, 'record': rec, **status}
                if other:
                    out.update({'other_model': True, 'requested': model})
                return out
        if status['container']:
            # a container of an earlier start that ended (a crash, a host that kept it and was stopped): its name is ours
            self._docker('rm', '-f', name)
        if listening(host, port):
            return self.cm.error('port %d is taken by another process; --port=<another> or stop it' % port)

        # the GPU's kind: its image and how docker passes it in (data: gpus in _desc.yaml)
        gpus = self._gpus()
        kind = str(gpu or 'nvidia').strip().lower()
        if kind not in gpus:
            return self.cm.error('--gpu is one of %s (got "%s")' % (', '.join(gpus), kind))

        # what the command line does not say: the config of this machine (the server's page sets it), else built in
        d = self._defaults()
        image = image_for_gpu(image or d['image'], bool(image), gpus[kind], str(gpus.get('nvidia', {}).get('image_repository') or ''))
        model, served_name = model or d['model'], served_name or d['served_name']
        max_model_len = int(max_model_len or 0) or int(d['max_model_len'])
        gpu_memory_utilization = float(gpu_memory_utilization or 0) or float(d['gpu_memory_utilization'] or 0)
        release = image_release(image)
        if not gpu_memory_utilization and (release is None or release[:2] < OWN_CACHE_SINCE):
            gpu_memory_utilization = SHARE_BEFORE
        max_num_seqs = int(max_num_seqs or 0) or int(d['max_num_seqs'] or 0)

        r = self._artifact(CACHE_ARTIFACT, 'run-vllm-server: the cache of its containers (/root/.cache): the models, '
                                           'vLLM\'s compiled kernels')
        if r['return'] > 0:
            return r
        cache = r['path']
        if hf_cache:
            hf_cache = os.path.abspath(hf_cache)
            if not os.path.isdir(hf_cache):
                return self.cm.error('--hf_cache names no folder: %s' % hf_cache)

        # a model of a folder of this machine: mounted, named by --served_name (else its folder's name)
        inner, model_volume = model_folder(model)
        if model_volume and not served_name:
            served_name = os.path.basename(inner)

        args = ['--model', inner, '--max-model-len', str(max_model_len)]
        if gpu_memory_utilization:
            args += ['--gpu-memory-utilization', str(gpu_memory_utilization)]
        if served_name:
            args += ['--served-model-name', served_name]
        if max_num_seqs:
            args += ['--max-num-seqs', str(max_num_seqs)]
        args += [str(u) for u in unparsed] if unparsed else []

        secrets = {'HF_TOKEN': os.environ['HF_TOKEN']} if os.environ.get('HF_TOKEN') else {}
        params = {'category': TASK_CATEGORY, 'command': 'run', 'arg1': CONTAINER_RUN, 'ctx': ctx, 'engine': 'docker',
                  'image': image, 'name': name, 'detach': not foreground, 'rm': bool(foreground),
                  'ports': ['%s:%d:%d' % (host, port, INNER_PORT)], 'volumes': cache_volumes(cache, hf_cache) + ([model_volume] if model_volume else []),
                  'run_flags': [str(f) for f in gpus[kind].get('run_flags') or []], 'cmd': args, 'env_secrets': secrets,
                  'labels': {'cmeta.task': 'run-vllm-server', 'cmeta.port': str(port)}, 'con': con, 'quiet': quiet}
        rec = {'name': name, 'port': port, 'host': host, 'image': image, 'gpu': kind, 'model': model, 'served_name': served_name or model,
               'max_model_len': max_model_len, 'gpu_memory_utilization': gpu_memory_utilization,
               'max_num_seqs': max_num_seqs, 'args': args, 'cache': cache, 'hf_cache': hf_cache, 'foreground': bool(foreground),
               'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
        if con:
            print('')
            share = ('%.2f of the GPU\'s memory' % gpu_memory_utilization) if gpu_memory_utilization else 'its KV cache sized by vLLM'
            print('vLLM: %s, %s, context %d, %s - container %s on %s:%d' % (
                image, model, max_model_len, share, name, host, port))

        if foreground:
            # attached: its log on the screen; the container goes when it ends (--rm), and when this run is ended
            # from outside before that, the next start removes it by its name
            self._write_record(folder, rec)
            try:
                r = self.cm.access(params)
            finally:
                self._docker('rm', '-f', name)
                try:
                    os.remove(os.path.join(folder, 'server.json'))
                except OSError:
                    pass
            return {'return': 0, 'port': port, 'foreground': True, 'returncode': r.get('returncode')}

        r = self.cm.access(params)
        if r.get('return', 1) > 0:
            return r
        rec['container_id'] = str(r.get('container_id') or '')[:64]
        self._write_record(folder, rec)

        # it loads: the container runs, /health answers once the model is in the GPU's memory
        started = time.monotonic()
        last = ''
        while time.monotonic() - started < int(timeout):
            status = self._status(name, host, port)
            if status['health'] == 200:
                break
            if not status['running']:
                return self.cm.error('the vLLM container %s ended (%s) - its last lines:\n%s' % (
                    name, status['container'] or 'gone', self._logs(name, 25)))
            if con and not quiet:
                line = self._logs(name, 1).strip()
                if line and line != last:
                    print('  ... %s' % line[:160])
                    last = line
            time.sleep(3)
        else:
            return self.cm.error('the vLLM server did not answer within %d s (cx task run run-vllm-server --action=logs)' % int(timeout))
        if con:
            print('vLLM server on %s:%d: up in %d s, models: %s' % (host, port, time.monotonic() - started, ', '.join(status['models'])))
        return {'return': 0, 'port': port, 'host': host, 'name': name, 'state': folder, 'record': rec, **status}

    ############################################################
    def _docker(self, *words, timeout = 60):
        """docker <words> -> (returncode, its output: stdout and stderr together, as text)."""
        try:
            p = subprocess.run([self.docker] + list(words), stdin = subprocess.DEVNULL, stdout = subprocess.PIPE,
                               stderr = subprocess.STDOUT, timeout = timeout)
            return p.returncode, p.stdout.decode('utf-8', 'replace')
        except (OSError, subprocess.TimeoutExpired) as e:
            return -1, str(e)

    def _status(self, name, host, port):
        """The container (running, exited, ... or '' when there is none), /health and the models it serves."""
        rc, out = self._docker('inspect', '--format', '{{json .State}}', name, timeout = 20)
        state = {}
        if rc == 0:
            try:
                state = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                state = {}
        running = bool(state.get('Running'))
        health, models = 0, []
        if running:
            health, _ = http_get('http://%s:%d/health' % ('127.0.0.1' if host in ('0.0.0.0', '') else host, port))
            if health == 200:
                code, text = http_get('http://%s:%d/v1/models' % ('127.0.0.1' if host in ('0.0.0.0', '') else host, port))
                try:
                    models = [m.get('id') for m in json.loads(text).get('data') or [] if m.get('id')]
                except ValueError:
                    models = []
        docker_error = '' if rc in (0, 1) else out.strip()[:300]
        return {'running': running, 'container': str(state.get('Status') or ''), 'started_at': str(state.get('StartedAt') or ''),
                'exit_code': state.get('ExitCode'), 'health': health, 'models': models, 'docker_error': docker_error}

    def _logs(self, name, lines):
        rc, out = self._docker('logs', '--tail', str(max(1, min(int(lines), 5000))), name, timeout = 30)
        return out if rc == 0 else ''

    def _gpus(self):
        """The kinds of GPU (gpus: in _desc.yaml): from the description the engine read, else from the file beside this
        module (a task object made without the engine, as the tests make it)."""
        desc = getattr(self, 'cdesc', None)
        if not isinstance(desc, dict):
            import yaml
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_desc.yaml'), encoding = 'utf-8') as f:
                desc = yaml.safe_load(f) or {}
        return desc.get('gpus') or {}

    def _defaults(self):
        """The defaults of a start: config::task-run-vllm-server over BUILT_IN (a key empty or absent: built in)."""
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

    def _artifact(self, ref, desc = ''):
        """A state artifact of the local repository (made when missing, as the llama.cpp task's) -> {'return', 'path'}."""
        r = self.cm.access({'category': STATE_CATEGORY, 'command': 'get', 'arg1': ref, 'con': False})
        if r.get('return', 1) > 0:
            return r
        return {'return': 0, 'path': r['artifact']['path']}

    @staticmethod
    def _write_record(folder, rec):
        with open(os.path.join(folder, 'server.json'), 'w', encoding = 'utf-8') as f:
            json.dump(rec, f, indent = 1)

    @staticmethod
    def _read_record(folder):
        try:
            with open(os.path.join(folder, 'server.json'), encoding = 'utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
