"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The model server tasks offline, with stand-ins for the engine and docker: run-llama-cpp-server takes what its command
line does not say from config::task-run-llama-cpp-server and starts llama-server with --metrics; run-vllm-server runs
vLLM's container with the GPU, its port published, its cache mounted, its defaults from config::task-run-vllm-server,
a token through the env file only, and stops it by its name.
"""
import json
import os

import pytest


class Engine:
    """cm.access for the tasks: the config, the state artifact, the setup and model tasks, container-run."""

    def __init__(self, tmp_path, config=None):
        self.tmp, self.config, self.calls = tmp_path, config or {}, []

    def access(self, p):
        self.calls.append(p)
        cat, cmd, arg1 = str(p.get('category')), p.get('command'), str(p.get('arg1') or '')
        if cat == 'config' and cmd == 'read':
            return {'return': 0, 'config_cmeta': dict(self.config)}
        if cat == 'state' and cmd == 'get':
            folder = self.tmp / ('state-' + arg1.split(':')[-1])
            folder.mkdir(exist_ok=True)
            return {'return': 0, 'artifact': {'path': str(folder)}}
        if arg1.startswith('setup,'):
            if 'docker' in str(p.get('name')):
                return {'return': 0, 'path': 'docker'}
            tool = self.tmp / 'llama' / 'llama-cli'
            tool.parent.mkdir(exist_ok=True)
            server = tool.parent / ('llama-server' + ('.exe' if os.name == 'nt' else ''))
            server.write_text('')
            return {'return': 0, 'path': str(tool)}
        if arg1.startswith('model,'):
            f = self.tmp / ('%s.gguf' % str(p.get('name')).replace('@', '-'))
            f.write_text('')
            return {'return': 0, 'path': str(f)}
        if arg1.startswith('container-run,'):
            return {'return': 0, 'container_id': 'c0ffee'}
        return {'return': 1, 'error': 'unexpected %s' % p}

    def error(self, text):
        return {'return': 1, 'error': text}


def test_llama_cpp_takes_its_defaults_from_the_config_and_starts_with_metrics(task_namespace, tmp_path, monkeypatch):
    ns = task_namespace('run-llama-cpp-server')
    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = Engine(tmp_path, {'model': 'hf-Qwen@Qwen2.5-0.5B-Instruct-GGUF', 'ctx_size': 8192, 'compute': 'cpu', 'parallel': ''})
    started = []

    class Popen:
        def __init__(self, command, **kw):
            started.append(command)
            self.pid = 4242

        def poll(self):
            return None
    monkeypatch.setattr(ns['subprocess'], 'Popen', Popen)
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)
    monkeypatch.setitem(ns, 'http_json', lambda url, timeout=2: (200, {}))     # /health: the model is in
    task._status = lambda host, port, rec: {'running': bool(started), 'listening': bool(started), 'models': ['m'] if started else [],
                                            'pid_alive': True}
    r = task.run({'control': {'con': False}}, action='start', port=8686)
    assert r['return'] == 0, r
    cmd = started[0]
    assert cmd[cmd.index('-c') + 1] == '8192' and cmd[cmd.index('-np') + 1] == '1' and '--metrics' in cmd
    assert cmd[cmd.index('-m') + 1].endswith('hf-Qwen-Qwen2.5-0.5B-Instruct-GGUF.gguf')
    setup = [p for p in task.cm.calls if str(p.get('arg1')).startswith('setup,')][0]
    assert setup['with'] == {'compute': ['cpu']}
    rec = json.loads((tmp_path / 'state-llama-cpp-server-8686' / 'server.json').read_text(encoding='utf-8'))
    assert rec['ctx_size'] == 8192 and rec['compute'] == 'cpu' and rec['parallel'] == 1

    # a word on the command line wins over the config; nothing in the config: the built-in defaults
    started.clear()
    task.cm = Engine(tmp_path)
    task.run({'control': {'con': False}}, action='start', port=8687, ctx_size=4096)
    assert started[0][started[0].index('-c') + 1] == '4096' and started[0][started[0].index('-m') + 1].endswith('Qwen3-8B-GGUF.gguf')


def test_vllm_runs_its_container_with_the_gpu_and_stops_it_by_its_name(task_namespace, tmp_path, monkeypatch):
    ns = task_namespace('run-vllm-server')
    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = Engine(tmp_path, {'model': 'Qwen/Qwen3-0.6B', 'max_model_len': 4096, 'gpu_memory_utilization': 0.8, 'served_name': ''})
    docker = []
    states = iter([{'running': False, 'container': '', 'health': 0, 'models': []}] + [{'running': True, 'container': 'running', 'health': 200, 'models': ['Qwen/Qwen3-0.6B']}] * 5)
    task._docker = lambda *words, timeout=60: (docker.append(words), (0, ''))[1]
    task._status = lambda name, host, port: next(states)
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)
    monkeypatch.setenv('HF_TOKEN', 'hf_made_up_for_the_test')

    r = task.run({'control': {'con': False}}, action='start', port=8868, timeout=10)
    assert r['return'] == 0 and r['health'] == 200, r
    run = [p for p in task.cm.calls if str(p.get('arg1')).startswith('container-run,')][0]
    assert run['image'] == 'vllm/vllm-openai:v0.31.0' and run['name'] == 'cmeta-vllm-8868' and run['detach'] is True
    flags = run['run_flags']
    assert run['ports'] == ['127.0.0.1:8868:8000'] and flags[flags.index('--gpus') + 1] == 'all' and '--ipc=host' in flags
    assert any(v.endswith('state-vllm-cache:/root/.cache') for v in run['volumes'])
    args = run['cmd']
    assert args[args.index('--model') + 1] == 'Qwen/Qwen3-0.6B' and args[args.index('--max-model-len') + 1] == '4096'
    assert args[args.index('--gpu-memory-utilization') + 1] == '0.8' and '--served-model-name' not in args
    # the token travels in the env file of container-run, never on its command line
    assert run['env_secrets'] == {'HF_TOKEN': 'hf_made_up_for_the_test'} and 'hf_made_up_for_the_test' not in json.dumps(args)
    rec = json.loads((tmp_path / 'state-vllm-server-8868' / 'server.json').read_text(encoding='utf-8'))
    assert rec['container_id'] == 'c0ffee' and rec['max_model_len'] == 4096

    # stop: its container by its name, and its record gone
    task._status = lambda name, host, port: {'running': True, 'container': 'running', 'health': 200, 'models': []}
    r = task.run({'control': {'con': False}}, action='stop', port=8868)
    assert r == {'return': 0, 'port': 8868, 'stopped': True}
    assert ('stop', '-t', '30', 'cmeta-vllm-8868') in docker and ('rm', '-f', 'cmeta-vllm-8868') in docker
    assert not (tmp_path / 'state-vllm-server-8868' / 'server.json').exists()


def test_vllm_says_why_when_its_container_ends_while_it_loads(task_namespace, tmp_path, monkeypatch):
    ns = task_namespace('run-vllm-server')
    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = Engine(tmp_path)
    states = iter([{'running': False, 'container': '', 'health': 0, 'models': []},
                   {'running': False, 'container': 'exited', 'health': 0, 'models': []}])
    task._docker = lambda *words, timeout=60: (0, 'ValueError: not enough GPU memory for the KV cache\n') if words[0] == 'logs' else (0, '')
    task._status = lambda name, host, port: next(states)
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)
    monkeypatch.delenv('HF_TOKEN', raising=False)
    r = task.run({'control': {'con': False}}, action='start', port=8869, timeout=10)
    assert r['return'] == 1 and 'cmeta-vllm-8869 ended (exited)' in r['error'] and 'not enough GPU memory' in r['error']
