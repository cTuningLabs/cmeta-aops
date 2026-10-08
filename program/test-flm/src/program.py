"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Start a private FastFlowLM server on the AMD NPU, pull a model, generate once through its Ollama-style
API and record its timings in tmp-cmeta-program-stats.json. Standard library only.

Environment (from the program's _desc.yaml): CMETA_FLM (the flm command), CMETA_FLM_MODEL,
CMETA_FLM_MAX_TOKENS, CMETA_FLM_PORT, CMETA_FLM_PMODE, CMETA_FLM_MODELS (the models folder; else
CMETA_FLM_CACHE/models, else FastFlowLM's default ~/.config/flm/models).
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request


def start_server(cmd, env, log):
    """flm serve in its own process group, so stop_server() can end what it started too."""
    if os.name == 'nt':
        return subprocess.Popen(cmd, env = env, stdout = log, stderr = subprocess.STDOUT,
                                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(cmd, env = env, stdout = log, stderr = subprocess.STDOUT, start_new_session = True)


def stop_server(server):
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
    flm = os.environ.get('CMETA_FLM') or 'flm'
    model = os.environ.get('CMETA_FLM_MODEL') or 'qwen3:0.6b'
    max_tokens = int(os.environ.get('CMETA_FLM_MAX_TOKENS') or 128)
    port = int(os.environ.get('CMETA_FLM_PORT') or 52701)
    pmode = os.environ.get('CMETA_FLM_PMODE') or 'performance'
    targets = os.environ.get('CMETA_TARGETS', '')

    env = dict(os.environ)
    env['FLM_DISABLE_UPDATE_CHECK'] = '1'
    models = os.environ.get('CMETA_FLM_MODELS') or (os.path.join(os.environ['CMETA_FLM_CACHE'], 'models') if os.environ.get('CMETA_FLM_CACHE') else '')
    if models:
        os.makedirs(models, exist_ok = True)
        env['FLM_MODEL_PATH'] = models

    base = f'http://127.0.0.1:{port}'
    stats = {'model': model, 'targets': targets, 'port': port, 'pmode': pmode}
    rc = 0
    log = open('flm-serve.log', 'w', encoding = 'utf-8')
    server = None
    try:
        r = subprocess.run([flm, 'version'], env = env, capture_output = True, text = True, timeout = 60)
        stats['flm'] = (r.stdout or '').strip().replace('FLM v', '')

        # The model first (the server would download it too, but then the load time holds the download)
        t0 = time.perf_counter()
        r = subprocess.run([flm, 'pull', model, '--quiet'], env = env, stdout = log, stderr = subprocess.STDOUT, timeout = 3600)
        if r.returncode != 0:
            raise RuntimeError(f'flm pull {model} failed with {r.returncode} (see flm-serve.log)')
        stats['pull_s'] = round(time.perf_counter() - t0, 2)

        server = start_server([flm, 'serve', model, '--port', str(port), '--pmode', pmode], env, log)
        for _ in range(240):
            try:
                api(base, '/api/version', timeout = 2)
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError(f'flm serve exited with {server.returncode} (see flm-serve.log)')
                time.sleep(0.5)
        else:
            raise RuntimeError('flm serve did not answer within 120 s (see flm-serve.log)')

        print('FastFlowLM', stats.get('flm'), '| model', model, '| targets', targets, '| pmode', pmode)

        options = {'seed': 12345, 'temperature': 0, 'num_predict': max_tokens}
        # Warm-up: the first request also loads the model onto the NPU
        t0 = time.perf_counter()
        api(base, '/api/generate', {'model': model, 'stream': False, 'prompt': 'Hi', 'options': dict(options, num_predict = 1)})
        stats['first_request_s'] = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        r = api(base, '/api/generate', {'model': model, 'stream': False, 'options': options,
                                        'prompt': 'How does a computer work? Answer in two sentences.'})
        wall = time.perf_counter() - t0

        ns = 1e9
        stats.update({
            'response': r.get('response', ''),
            'prompt_tokens': r.get('prompt_eval_count'),
            'prompt_tokens_per_second': round(r['prompt_eval_count'] / (r['prompt_eval_duration'] / ns), 2)
                                        if r.get('prompt_eval_duration') else None,
            'generated_tokens': r.get('eval_count'),
            'generation_tokens_per_second': round(r['eval_count'] / (r['eval_duration'] / ns), 2)
                                            if r.get('eval_duration') else None,
            'request_s': round(wall, 3),
        })
        print(stats['response'])
    except Exception as e:
        stats['error'] = f'{type(e).__name__}: {e}'
        print('ERROR:', stats['error'], file = sys.stderr)
        rc = 1
    finally:
        if server is not None:
            stop_server(server)
        log.close()

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)
    print(json.dumps({k: v for k, v in stats.items() if k != 'response'}))
    return rc


if __name__ == '__main__':
    sys.exit(main())
