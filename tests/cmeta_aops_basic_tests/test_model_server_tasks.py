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


def llama_cpp_task(task_namespace, tmp_path, monkeypatch, config=None):
    """The task with stand-ins: (the task, its namespace, what was started, what was stopped, the server's state)."""
    ns = task_namespace('run-llama-cpp-server')
    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = Engine(tmp_path, config)
    started, stopped, server = [], [], {'up': False, 'ours': True}

    class Popen:
        def __init__(self, command, **kw):
            started.append((command, kw))
            server['up'] = True
            self.pid = 4242

        def poll(self):
            return None
    monkeypatch.setattr(ns['subprocess'], 'Popen', Popen)
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)
    monkeypatch.setitem(ns, 'http_json', lambda url, timeout=2: (200, {}))
    monkeypatch.setitem(ns, 'recorded_process_alive', lambda pid, written, alive: True)
    monkeypatch.setitem(ns, 'alive', lambda pid: False)
    monkeypatch.setitem(ns, 'stop_process', lambda pid: (stopped.append(pid), server.update(up=False)))
    task._status = lambda host, port, rec: {'running': server['up'], 'listening': server['up'], 'models': ['served'] if server['up'] else [],
                                            'loaded': [], 'pid_alive': True, 'ours': server['up'] and server['ours']}
    return task, ns, started, stopped, server


def test_llama_cpp_serves_several_models_behind_one_port(task_namespace, tmp_path, monkeypatch):
    task, ns, started, stopped, server = llama_cpp_task(task_namespace, tmp_path, monkeypatch)
    r = task.run({'control': {'con': False}}, action='start', port=8690, models='hf-A@one-GGUF;hf-B@two-GGUF', models_max=2, ctx_size=4096)
    assert r['return'] == 0, r

    # llama-server without a model is the router: a preset file names the models, the limit says how many stay loaded
    cmd, kw = started[0]
    assert '-m' not in cmd and cmd[cmd.index('--models-max') + 1] == '2' and '--metrics' in cmd
    with open(cmd[cmd.index('--models-preset') + 1], encoding='utf-8') as f:
        preset = f.read()
    assert preset.startswith('version = 1') and 'ctx-size = 4096' in preset and 'jinja = true' in preset
    assert '[hf-A-one-GGUF]' in preset and '[hf-B-two-GGUF]' in preset and preset.count('model = ') == 2

    # the models asked for and no others: llama.cpp's own cache of downloads is pointed at an empty folder
    assert os.path.isdir(kw['env']['LLAMA_CACHE']) and not os.listdir(kw['env']['LLAMA_CACHE'])
    rec = json.loads((tmp_path / 'state-llama-cpp-server-8690' / 'server.json').read_text(encoding='utf-8'))
    assert rec['router'] is True and rec['models'] == ['hf-A@one-GGUF', 'hf-B@two-GGUF'] and rec['models_max'] == 2

    # each model is asked of the model task by its own name
    fetched = [p for p in task.cm.calls if str(p.get('arg1')).startswith('model,')]
    assert [p['name'] for p in fetched] == ['hf-A@one-GGUF', 'hf-B@two-GGUF']

    # one of its models asked for again: it serves it already; a model it does not have: said, nothing started
    again = task.run({'control': {'con': False}}, action='start', port=8690, model='hf-B@two-GGUF')
    assert again['already'] and 'other_model' not in again and len(started) == 1
    other = task.run({'control': {'con': False}}, action='start', port=8690, model='hf-C@three-GGUF')
    assert other['already'] and other['other_model'] is True and other['requested'] == 'hf-C@three-GGUF' and len(started) == 1

    # the config may name the several models; one model on the command line is then one model served
    task2, ns2, started2, _, _ = llama_cpp_task(task_namespace, tmp_path, monkeypatch, {'models': 'hf-A@one-GGUF;hf-B@two-GGUF'})
    task2.run({'control': {'con': False}}, action='start', port=8692)
    assert '--models-preset' in started2[0][0] and started2[0][0][started2[0][0].index('--models-max') + 1] == '1'
    task3, ns3, started3, _, _ = llama_cpp_task(task_namespace, tmp_path, monkeypatch, {'models': 'hf-A@one-GGUF;hf-B@two-GGUF'})
    task3.run({'control': {'con': False}}, action='start', port=8693, model='hf-C@three-GGUF')
    assert '-m' in started3[0][0] and '--models-preset' not in started3[0][0] and started3[0][1].get('env') is None


def test_the_model_task_forgets_the_earlier_model_of_a_run(task_namespace):
    # two models fetched in one run came back as one file (2026-11-20): the task that fetches keeps one result per run
    # under a fixed key, so the model task forgets the keys its result is read from before it fetches
    keys = task_namespace('model')['memo_keys']
    assert keys('{{global.get-hf-model}}') == ['get-hf-model']
    assert keys('{{ global.a.path|}} and {{global.b|$None}}') == ['a', 'b']
    assert keys('') == [] and keys(None) == [] and keys('{{local.x}} {{params.y}}') == []


def test_llama_cpp_leaves_another_model_unless_swap(task_namespace, tmp_path, monkeypatch):
    task, ns, started, stopped, server = llama_cpp_task(task_namespace, tmp_path, monkeypatch)
    ctx = {'control': {'con': False}}
    assert task.run(ctx, action='start', port=8691, model='hf-A@one-GGUF')['return'] == 0 and len(started) == 1

    # up with A: a start that names B leaves it and says so; A again, or nothing named, is "up already" as before
    r = task.run(ctx, action='start', port=8691, model='hf-B@two-GGUF')
    assert r['return'] == 0 and r['already'] and r['other_model'] is True and r['requested'] == 'hf-B@two-GGUF'
    for same in ({'model': 'hf-A@one-GGUF'}, {}):
        r = task.run(ctx, action='start', port=8691, **same)
        assert r['already'] and 'other_model' not in r
    assert len(started) == 1 and not stopped

    # --swap: the server is stopped and started with B
    r = task.run(ctx, action='start', port=8691, model='hf-B@two-GGUF', swap=True)
    assert r['return'] == 0 and 'already' not in r and stopped == [4242] and len(started) == 2
    assert started[1][0][started[1][0].index('-m') + 1].endswith('hf-B-two-GGUF.gguf')
    rec = json.loads((tmp_path / 'state-llama-cpp-server-8691' / 'server.json').read_text(encoding='utf-8'))
    assert rec['model'] == 'hf-B@two-GGUF' and 'router' not in rec

    # a server this task did not start is never replaced
    server['ours'] = False
    r = task.run(ctx, action='start', port=8691, model='hf-A@one-GGUF', swap=True)
    assert r['return'] > 0 and 'did not start' in r['error'] and len(started) == 2


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
    assert run['image'] == 'vllm/vllm-openai:v0.34.0' and run['name'] == 'cmeta-vllm-8868' and run['detach'] is True
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


def test_vllm_gets_the_share_of_the_gpu_its_release_needs(task_namespace, tmp_path, monkeypatch):
    # vLLM 0.34 sizes its KV cache itself ("best not to set gpu_memory_utilization"): no share is passed to it unless
    # the command line or the config names one; an earlier release, or a tag that names none, gets 0.85 as before
    ns = task_namespace('run-vllm-server')
    assert ns['image_release']('vllm/vllm-openai:v0.34.0') == (0, 34, 0)
    assert ns['image_release']('vllm/vllm-openai:v0.34.0-efa') == (0, 34, 0)
    assert ns['image_release']('vllm/vllm-openai:latest') is None
    assert ns['image_release']('vllm/vllm-openai@sha256:0123') is None
    cls = ns['CTask']
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)

    def started_with(config, **words):
        task = cls.__new__(cls)
        task.cm = Engine(tmp_path, config)
        states = iter([{'running': False, 'container': '', 'health': 0, 'models': []}] + [{'running': True, 'container': 'running', 'health': 200, 'models': ['m']}] * 5)
        task._docker = lambda *w, timeout=60: (0, '')
        task._status = lambda name, host, port: next(states)
        r = task.run({'control': {'con': False}}, action='start', port=8868, timeout=10, **words)
        assert r['return'] == 0, r
        run = [p for p in task.cm.calls if str(p.get('arg1')).startswith('container-run,')][0]
        args = run['cmd']
        return run['image'], (args[args.index('--gpu-memory-utilization') + 1] if '--gpu-memory-utilization' in args else None)

    assert started_with({}) == ('vllm/vllm-openai:v0.34.0', None)
    assert started_with({}, image='vllm/vllm-openai:v0.31.0') == ('vllm/vllm-openai:v0.31.0', '0.85')
    assert started_with({}, image='vllm/vllm-openai:latest') == ('vllm/vllm-openai:latest', '0.85')
    assert started_with({'gpu_memory_utilization': 0.6}) == ('vllm/vllm-openai:v0.34.0', '0.6')
    assert started_with({}, gpu_memory_utilization=0.5) == ('vllm/vllm-openai:v0.34.0', '0.5')


def test_vllm_leaves_another_model_unless_swap(task_namespace, tmp_path, monkeypatch):
    ns = task_namespace('run-vllm-server')
    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = Engine(tmp_path)
    docker, server = [], {'up': False}

    def run_docker(*words, timeout=60):
        docker.append(words)
        if words[0] == 'stop':
            server['up'] = False
        return 0, ''
    task._docker = run_docker
    task._status = lambda name, host, port: ({'running': True, 'container': 'running', 'health': 200, 'models': ['served']} if server['up'] else
                                             {'running': False, 'container': '', 'health': 0, 'models': []})
    monkeypatch.setitem(ns, 'listening', lambda host, port, timeout=1.0: False)
    monkeypatch.delenv('HF_TOKEN', raising=False)
    ctx = {'control': {'con': False}}

    def starts():
        return [p for p in task.cm.calls if str(p.get('arg1')).startswith('container-run,')]

    # the first start: the stand-in container is up once container-run was asked for it
    real_access = task.cm.access
    task.cm.access = lambda p: (server.update(up=True) if str(p.get('arg1')).startswith('container-run,') else None, real_access(p))[1]
    assert task.run(ctx, action='start', port=8870, model='Qwen/Qwen3-0.6B', timeout=10)['return'] == 0 and len(starts()) == 1

    # up with one model: a start that names another leaves it and says so; the same one, or none named, as before
    r = task.run(ctx, action='start', port=8870, model='Qwen/Qwen3-4B', timeout=10)
    assert r['already'] and r['other_model'] is True and r['requested'] == 'Qwen/Qwen3-4B' and len(starts()) == 1
    for same in ({'model': 'Qwen/Qwen3-0.6B'}, {}):
        r = task.run(ctx, action='start', port=8870, timeout=10, **same)
        assert r['already'] and 'other_model' not in r
    assert not [w for w in docker if w[0] == 'stop']

    # --swap: its container is stopped and removed, and a new one started with the other model
    r = task.run(ctx, action='start', port=8870, model='Qwen/Qwen3-4B', swap=True, timeout=10)
    assert r['return'] == 0 and 'already' not in r, r
    assert ('stop', '-t', '30', 'cmeta-vllm-8870') in docker and len(starts()) == 2
    args = starts()[1]['cmd']
    assert args[args.index('--model') + 1] == 'Qwen/Qwen3-4B'
    rec = json.loads((tmp_path / 'state-vllm-server-8870' / 'server.json').read_text(encoding='utf-8'))
    assert rec['model'] == 'Qwen/Qwen3-4B'


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
