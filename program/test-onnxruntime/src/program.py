"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Run a matmul + ReLU ONNX model with ONNX Runtime on the execution provider of each selected
target and record what happened in tmp-cmeta-program-stats.json: the provider and its options,
the session creation time, the latency over the iterations (or the seconds), and the error
against NumPy.

Targets and providers: cpu -> CPU, cuda -> CUDA, npu-intel -> OpenVINO (NPU), xpu -> OpenVINO
(GPU), openvino alone -> OpenVINO (CPU), metal -> CoreML, rocm -> MIGraphX. Each provider is
named alone, with the CPU fallback of the session disabled, so a provider that cannot run the
model fails instead of running on the CPU. Exit code 1 when a provider is missing, fails, or
computes wrong results.

Environment (set by the program's _desc.yaml from its parameters):
  CMETA_TARGETS          the selected targets
  CMETA_ORT_SIZE         the matrix size n: (batch x n) @ (n x n) (default 1024)
  CMETA_ORT_BATCH        the rows of the input (default 1: a matrix-vector product)
  CMETA_ORT_ITERATIONS   timed inferences per provider (default 200)
  CMETA_ORT_SECONDS      run each provider this long instead, printing its progress
  CMETA_ORT_PROVIDERS    providers instead of the targets' (CUDAExecutionProvider,CPUExecutionProvider)
"""

import json
import os
import statistics
import sys
import time

PROVIDER_OF_TARGET = {
    'cpu': ('CPUExecutionProvider', {}),
    'cuda': ('CUDAExecutionProvider', {}),
    'npu-intel': ('OpenVINOExecutionProvider', {'device_type': 'NPU'}),
    'xpu': ('OpenVINOExecutionProvider', {'device_type': 'GPU'}),
    'openvino': ('OpenVINOExecutionProvider', {'device_type': 'CPU'}),
    'metal': ('CoreMLExecutionProvider', {}),
    'rocm': ('MIGraphXExecutionProvider', {}),
}


def providers_for(targets):
    """The (provider, options) to run, one per target; openvino next to npu-intel or xpu only
    names the stack."""
    runs = []
    for t in targets:
        if t == 'openvino' and ('npu-intel' in targets or 'xpu' in targets):
            continue
        if t in PROVIDER_OF_TARGET and PROVIDER_OF_TARGET[t] not in runs:
            runs.append(PROVIDER_OF_TARGET[t])
    return runs


def intel_gpu(core, available):
    """The OpenVINO name of the first Intel GPU (OpenVINO's GPU plugin also drives other GPUs)."""
    for d in available:
        if d.split('.')[0] != 'GPU':
            continue
        try:
            name = str(core.get_property(d, 'FULL_DEVICE_NAME'))
        except Exception:
            name = ''
        if 'intel' in name.lower():
            return d
    return None


def timed_run(infer, iterations, seconds, flops, label):
    """
    Time the calls of infer(): `iterations` of them, or as many as fit in `seconds` (printing
    progress, and the GFLOPS of the calls finished in each second).
    """
    times, per_second = [], []
    start = time.perf_counter()
    mark, in_second = start + 1.0, 0
    every = 1 if seconds <= 10 else 5
    while True:
        t = time.perf_counter()
        infer()
        now = time.perf_counter()
        times.append(now - t)
        if not seconds:
            if len(times) >= iterations:
                break
            continue
        in_second += 1
        while now >= mark:
            per_second.append(round(in_second * flops / 1e9, 2))
            in_second = 0
            mark += 1.0
            if len(per_second) % every == 0:
                print(f'  {label}: {len(per_second)} s, {len(times)} calls, {per_second[-1]} GFLOPS', flush = True)
        if now - start >= seconds:
            break
    return times, per_second, time.perf_counter() - start


def latency_stats(seconds):
    us = sorted(s * 1e6 for s in seconds)
    return {'min': round(us[0], 1), 'median': round(statistics.median(us), 1),
            'p90': round(us[min(len(us) - 1, int(0.9 * len(us)))], 1), 'max': round(us[-1], 1),
            'mean': round(statistics.mean(us), 1)}


def make_model(w, batch, n):
    """(batch x n) @ w (n x n), then ReLU, as ONNX bytes."""
    from onnx import TensorProto, helper, numpy_helper
    x = helper.make_tensor_value_info('x', TensorProto.FLOAT, [batch, n])
    y = helper.make_tensor_value_info('y', TensorProto.FLOAT, [batch, n])
    graph = helper.make_graph([helper.make_node('MatMul', ['x', 'w'], ['m']), helper.make_node('Relu', ['m'], ['y'])],
                              'matmul-relu', [x], [y], initializer = [numpy_helper.from_array(w, name = 'w')])
    model = helper.make_model(graph, opset_imports = [helper.make_opsetid('', 17)])
    model.ir_version = 9    # older runtimes (onnxruntime-openvino) read IR 9
    return model.SerializeToString()


def main():
    import numpy as np
    import onnxruntime as ort

    targets = [t.strip() for t in os.environ.get('CMETA_TARGETS', '').split(',') if t.strip()]
    n = int(os.environ.get('CMETA_ORT_SIZE') or 1024)
    batch = int(os.environ.get('CMETA_ORT_BATCH') or 1)
    iterations = int(os.environ.get('CMETA_ORT_ITERATIONS') or 200)
    seconds = float(os.environ.get('CMETA_ORT_SECONDS') or 0)
    flops = 2 * batch * n * n

    explicit = [p.strip() for p in (os.environ.get('CMETA_ORT_PROVIDERS') or '').split(',') if p.strip()]
    runs = [(p, {}) for p in explicit] if explicit else providers_for(targets) or [('CPUExecutionProvider', {})]

    # Windows: the OpenVINO EP loads openvino.dll from the openvino package
    if any(p == 'OpenVINOExecutionProvider' for p, _ in runs) and sys.platform == 'win32':
        try:
            from onnxruntime.tools import add_openvino_win_libs
            add_openvino_win_libs.add_openvino_libs_to_path()
        except (ImportError, SystemExit, OSError) as e:
            print(f'WARNING: the OpenVINO libraries were not added to the DLL path: {e}')

    # CUDA and cuDNN from the nvidia-* pip packages (onnxruntime-gpu[cuda,cudnn])
    if any(p == 'CUDAExecutionProvider' for p, _ in runs) and hasattr(ort, 'preload_dlls'):
        try:
            ort.preload_dlls()
        except Exception as e:
            print(f'WARNING: onnxruntime.preload_dlls() failed: {e}')

    available = ort.get_available_providers()

    # xpu: the Intel GPU among OpenVINO's GPUs, which OpenVINO lists (an NVIDIA GPU is GPU.0 when
    # no Intel GPU runtime is installed)
    xpu_check, missing_intel_gpu = None, None
    if 'xpu' in targets and not explicit:
        try:
            import openvino as ov
            core = ov.Core()
            ov_devices = list(core.available_devices)
            gpu = intel_gpu(core, ov_devices)
            if gpu:
                runs = [(p, dict(o, device_type = gpu)) if p == 'OpenVINOExecutionProvider' and o.get('device_type') == 'GPU'
                        else (p, o) for p, o in runs]
                xpu_check = f'the Intel GPU is OpenVINO {gpu}'
            else:
                names = [f'{d} ({core.get_property(d, "FULL_DEVICE_NAME")})' for d in ov_devices if d.split('.')[0] == 'GPU']
                missing_intel_gpu = ('no Intel GPU: OpenVINO finds ' + (', '.join(names) or 'no GPU') +
                                     ' (on Linux the Intel GPU needs intel-opencl-icd and access to /dev/dri)')
                runs = [(p, o) for p, o in runs if not (p == 'OpenVINOExecutionProvider' and o.get('device_type') == 'GPU')]
        except ImportError:
            xpu_check = 'not verified: the openvino package is not installed to list the GPUs'

    rng = np.random.default_rng(12345)
    x = rng.random((batch, n), dtype = np.float32)
    w = rng.random((n, n), dtype = np.float32) / n
    ref = np.maximum(x @ w, 0)
    scale = float(np.max(np.abs(ref))) or 1.0
    model = make_model(w, batch, n)

    stats = {'onnxruntime': ort.__version__, 'device': ort.get_device(), 'targets': targets, 'size': n,
             'batch': batch, 'iterations': None if seconds else iterations, 'seconds': seconds or None,
             'available_providers': available, 'xpu_check': xpu_check, 'providers': {}}

    if missing_intel_gpu:
        stats['providers']['OpenVINO:GPU (Intel)'] = {'error': missing_intel_gpu}
        print(f'OpenVINO:GPU (Intel): {missing_intel_gpu}')

    for provider, options in runs:
        label = provider.replace('ExecutionProvider', '') + (f':{options["device_type"]}' if 'device_type' in options else '')
        entry = {'provider': provider, 'options': options}
        stats['providers'][label] = entry
        if provider not in available:
            entry['error'] = f'{provider} is not available: this ONNX Runtime has {", ".join(available)}'
            print(f'{label}: {entry["error"]}')
            continue
        try:
            so = ort.SessionOptions()
            if provider != 'CPUExecutionProvider':
                so.add_session_config_entry('session.disable_cpu_ep_fallback', '1')
            t = time.perf_counter()
            session = ort.InferenceSession(model, sess_options = so, providers = [(provider, options)])
            entry['session_ms'] = round((time.perf_counter() - t) * 1000, 1)
            entry['session_providers'] = session.get_providers()
            for _ in range(5):
                session.run(None, {'x': x})
            if seconds:
                print(f'{label}: running for {seconds:g} s ...', flush = True)
            times, per_second, elapsed = timed_run(lambda: session.run(None, {'x': x}), iterations, seconds, flops, label)
            out = session.run(None, {'x': x})[0]
            err = float(np.max(np.abs(out - ref)))
            entry['calls'] = len(times)
            entry['latency_us'] = latency_stats(times)
            entry['gflops'] = round(flops / (entry['latency_us']['median'] / 1e6) / 1e9, 2)
            if seconds:
                entry['seconds'] = round(elapsed, 2)
                entry['gflops_sustained'] = round(len(times) * flops / elapsed / 1e9, 2)
                entry['gflops_per_second'] = per_second
            entry['max_abs_error'] = err
            entry['max_rel_error'] = err / scale
            ran_there = entry['session_providers'][:1] == [provider]
            entry['passed'] = bool(err <= 1e-2 * scale and ran_there)
            if not ran_there:
                entry['error'] = f'the session runs on {entry["session_providers"]}, not on {provider}'
        except Exception as e:
            entry['error'] = str(e)[:800]

        if entry.get('latency_us'):
            timed = ''
            if entry.get('seconds'):
                ps = entry.get('gflops_per_second') or [entry['gflops_sustained']]
                timed = (f'; {entry["calls"]} calls in {entry["seconds"]} s, {entry["gflops_sustained"]} GFLOPS sustained '
                         f'(per second: {min(ps)}-{max(ps)})')
            print(f'{label}: session {entry["session_ms"]} ms, median {entry["latency_us"]["median"]} us '
                  f'(min {entry["latency_us"]["min"]}, p90 {entry["latency_us"]["p90"]}), {entry["gflops"]} GFLOPS, '
                  f'max error {entry["max_abs_error"]:.2e}{timed} -> {"OK" if entry["passed"] else "FAILED"}')
        else:
            print(f'{label}: {entry.get("error")}')

    stats['passed'] = bool(stats['providers']) and all(e.get('passed') for e in stats['providers'].values())

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)

    return 0 if stats['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
