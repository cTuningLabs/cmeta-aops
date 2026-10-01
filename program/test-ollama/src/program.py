"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Start a private Ollama server, pull a model, generate once through the REST API and record
Ollama's timings in tmp-cmeta-program-stats.json. Standard library only.

Environment (from the program's _desc.yaml): CMETA_OLLAMA (the binary), CMETA_OLLAMA_MODEL,
CMETA_OLLAMA_MAX_TOKENS, CMETA_OLLAMA_PORT, CMETA_OLLAMA_MODELS (models folder, optional),
CMETA_TARGETS (cpu -> the model stays on the CPU; vulkan -> OLLAMA_VULKAN=1).
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request


def start_server(cmd, env, log):
    """ollama serve in its own process group, so stop_server() can end its runners too."""
    if os.name == 'nt':
        return subprocess.Popen(cmd, env = env, stdout = log, stderr = subprocess.STDOUT,
                                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(cmd, env = env, stdout = log, stderr = subprocess.STDOUT, start_new_session = True)


def stop_server(server):
    """
    Stop ollama serve and the model runners (llama-server) it started. On Windows terminating
    ollama.exe alone leaves each runner running, holding its RAM and VRAM, so the whole process
    tree goes; elsewhere the process group gets SIGTERM, then SIGKILL.
    """
    if server.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(server.pid)],
                       stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL)
    else:
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        server.wait(timeout = 30)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            server.kill()
        else:
            os.killpg(server.pid, signal.SIGKILL)
        server.wait(timeout = 30)


def api(base, path, payload = None, timeout = 600):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(base + path, data = data,
                                 headers = {'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(req, timeout = timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    ollama = os.environ.get('CMETA_OLLAMA') or 'ollama'
    model = os.environ.get('CMETA_OLLAMA_MODEL') or 'qwen2.5:0.5b'
    max_tokens = int(os.environ.get('CMETA_OLLAMA_MAX_TOKENS') or 64)
    port = int(os.environ.get('CMETA_OLLAMA_PORT') or 11435)
    targets = os.environ.get('CMETA_TARGETS', '')

    env = dict(os.environ)
    env['OLLAMA_HOST'] = f'127.0.0.1:{port}'
    if os.environ.get('CMETA_OLLAMA_MODELS'):
        env['OLLAMA_MODELS'] = os.environ['CMETA_OLLAMA_MODELS']
    if 'vulkan' in targets:
        env['OLLAMA_VULKAN'] = '1'

    base = f'http://127.0.0.1:{port}'
    log = open('ollama-serve.log', 'w', encoding = 'utf-8')
    server = start_server([ollama, 'serve'], env, log)

    stats = {'model': model, 'targets': targets, 'port': port}
    rc = 0
    try:
        for _ in range(120):
            try:
                stats['ollama'] = api(base, '/api/version', timeout = 2).get('version')
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError(f'ollama serve exited with {server.returncode} (see ollama-serve.log)')
                time.sleep(0.5)
        else:
            raise RuntimeError('ollama serve did not answer within 60 s (see ollama-serve.log)')

        print('Ollama', stats['ollama'], '| model', model, '| targets', targets)

        t0 = time.perf_counter()
        api(base, '/api/pull', {'model': model, 'stream': False}, timeout = 3600)
        stats['pull_s'] = round(time.perf_counter() - t0, 2)

        options = {'seed': 12345, 'temperature': 0, 'num_predict': max_tokens}
        if targets.split(',') == ['cpu']:
            options['num_gpu'] = 0

        # Warm-up: the first request also pays for loading the model and initializing the GPU
        api(base, '/api/generate', {'model': model, 'stream': False, 'prompt': 'Hi',
                                    'options': dict(options, num_predict = 1)})

        r = api(base, '/api/generate', {'model': model, 'stream': False, 'options': options,
                                        'prompt': 'How does a computer work? Answer in two sentences.'})

        ns = 1e9
        stats.update({
            'response': r.get('response', ''),
            'load_s': round(r.get('load_duration', 0) / ns, 3),
            'prompt_tokens': r.get('prompt_eval_count'),
            'prompt_tokens_per_second': round(r['prompt_eval_count'] / (r['prompt_eval_duration'] / ns), 2)
                                        if r.get('prompt_eval_duration') else None,
            'generated_tokens': r.get('eval_count'),
            'generation_tokens_per_second': round(r['eval_count'] / (r['eval_duration'] / ns), 2)
                                            if r.get('eval_duration') else None,
            'total_s': round(r.get('total_duration', 0) / ns, 3),
        })

        # Where the model sits: size_vram > 0 means (partly) on a GPU
        for m in api(base, '/api/ps').get('models', []):
            if m.get('name', '').startswith(model.split(':')[0]):
                stats['size_mib'] = m.get('size', 0) // 2**20
                stats['size_vram_mib'] = m.get('size_vram', 0) // 2**20

        print(stats['response'])
    except Exception as e:
        stats['error'] = f'{type(e).__name__}: {e}'
        print('ERROR:', stats['error'], file = sys.stderr)
        rc = 1
    finally:
        stop_server(server)
        log.close()

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)
    print(json.dumps({k: v for k, v in stats.items() if k != 'response'}))
    return rc


if __name__ == '__main__':
    sys.exit(main())
