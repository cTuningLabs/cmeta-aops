"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Run a small matmul + ReLU model with OpenVINO on each selected device and record what happened
in tmp-cmeta-program-stats.json: the device's properties (name, architecture, driver), the
compile time, the latency over the iterations, and the error against NumPy.

The devices come from the targets: npu-intel -> NPU, xpu -> GPU, cpu -> CPU; with only the
openvino target, every device OpenVINO finds. Each device is named in compile_model, never AUTO,
so a device that fails cannot pass by falling back to the CPU. Exit code 1 when a device is
missing, fails, or gives wrong results.

Environment (set by the program's _desc.yaml from its parameters):
  CMETA_TARGETS              the selected targets
  CMETA_OPENVINO_SIZE        the matrix size n: (batch x n) @ (n x n) (default 1024)
  CMETA_OPENVINO_BATCH       the rows of the input (default 1: a matrix-vector product, which
                             memory bandwidth limits; 256 and more use the compute units)
  CMETA_OPENVINO_ITERATIONS  timed inferences per device (default 200)
  CMETA_OPENVINO_SECONDS     run each device this long instead (3, 30, 60, ...), printing its
                             progress; records the GFLOPS of every second too
  CMETA_OPENVINO_PRECISION   f16 or f32 (INFERENCE_PRECISION_HINT; default: the device's own)
  CMETA_OPENVINO_DEVICES     OpenVINO devices instead of the targets' (NPU,CPU)
"""

import json
import os
import statistics
import sys
import time

DEVICE_OF_TARGET = {'npu-intel': 'NPU', 'xpu': 'GPU', 'cpu': 'CPU'}

PROPERTIES = ('FULL_DEVICE_NAME', 'DEVICE_ARCHITECTURE', 'DEVICE_TYPE', 'OPTIMIZATION_CAPABILITIES',
              'DEVICE_GOPS', 'NPU_DRIVER_VERSION', 'NPU_COMPILER_VERSION', 'NPU_DEVICE_TOTAL_MEM_SIZE',
              'GPU_DEVICE_TOTAL_MEM_SIZE', 'GPU_EXECUTION_UNITS_COUNT')


def plain(value):
    """A property value as JSON: OpenVINO element types by name (f16), dicts and lists inside."""
    if hasattr(value, 'get_type_name'):
        return value.get_type_name()
    if isinstance(value, dict):
        return {str(plain(k)): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float):
        return round(value, 1)
    if isinstance(value, (int, bool)) or value is None:
        return value
    return str(value)


def as_list(value):
    """EXECUTION_DEVICES is a string ("NPU") in some OpenVINO versions and a list in others."""
    if isinstance(value, str):
        return [d.strip() for d in value.split(',') if d.strip()]
    return [str(d) for d in value]


def intel_gpu(core, available):
    """
    The OpenVINO name of the first Intel GPU (GPU, GPU.0, GPU.1, ...), or None: OpenVINO's GPU
    plugin also drives other GPUs through OpenCL (an NVIDIA GPU is GPU.0 when no Intel GPU
    runtime is installed), and the xpu target means the Intel one.
    """
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


def gpu_names(core, available):
    names = []
    for d in available:
        if d.split('.')[0] == 'GPU':
            try:
                names.append(f'{d} ({core.get_property(d, "FULL_DEVICE_NAME")})')
            except Exception:
                names.append(d)
    return names


def device_properties(core, device):
    props = {}
    for p in PROPERTIES:
        try:
            props[p] = plain(core.get_property(device, p))
        except Exception:
            pass
    return props


def timed_run(infer, iterations, seconds, flops, label):
    """
    Time the calls of infer(): `iterations` of them, or as many as fit in `seconds`. A timed run
    also gives the GFLOPS of the calls finished in each second, which shows a device slowing down
    as it heats up, and prints its progress.
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


def main():
    import numpy as np
    import openvino as ov
    try:
        import openvino.opset13 as ops
    except ImportError:
        import openvino.runtime.opset13 as ops

    targets = [t.strip() for t in os.environ.get('CMETA_TARGETS', '').split(',') if t.strip()]
    n = int(os.environ.get('CMETA_OPENVINO_SIZE') or 1024)
    batch = int(os.environ.get('CMETA_OPENVINO_BATCH') or 1)
    iterations = int(os.environ.get('CMETA_OPENVINO_ITERATIONS') or 200)
    seconds = float(os.environ.get('CMETA_OPENVINO_SECONDS') or 0)
    precision = (os.environ.get('CMETA_OPENVINO_PRECISION') or '').strip().lower()
    flops = 2 * batch * n * n

    core = ov.Core()
    available = list(core.available_devices)

    wanted = [d.strip().upper() for d in (os.environ.get('CMETA_OPENVINO_DEVICES') or '').split(',') if d.strip()]
    missing_intel_gpu = False
    if not wanted:
        for t in targets:
            if t not in DEVICE_OF_TARGET:
                continue
            device = DEVICE_OF_TARGET[t]
            if t == 'xpu':
                device = intel_gpu(core, available)
                if not device:
                    missing_intel_gpu = True
                    continue
            if device not in wanted:
                wanted.append(device)
        if not wanted and not missing_intel_gpu:
            wanted = available

    rng = np.random.default_rng(12345)
    x = rng.random((batch, n), dtype = np.float32)
    w = rng.random((n, n), dtype = np.float32) / n
    ref = np.maximum(x @ w, 0)
    scale = float(np.max(np.abs(ref))) or 1.0

    param = ops.parameter([batch, n], np.float32, name = 'x')
    model = ov.Model([ops.relu(ops.matmul(param, ops.constant(w), False, False))], [param], 'matmul-relu')

    stats = {'openvino': ov.get_version(), 'targets': targets, 'size': n, 'batch': batch,
             'iterations': None if seconds else iterations, 'seconds': seconds or None,
             'precision_hint': precision or None, 'available_devices': available, 'devices': {}}

    if missing_intel_gpu:
        gpus = gpu_names(core, available)
        error = ('no Intel GPU: OpenVINO finds ' + (', '.join(gpus) if gpus else 'no GPU') +
                 ' (on Linux the Intel GPU needs its compute runtime - cx tool setup intel-gpu-runtime, which '
                 'target --compute=xpu sets up - and access to /dev/dri: the render group)')
        stats['devices']['GPU (Intel)'] = {'error': error}
        print(f'GPU (Intel): {error}')

    for device in wanted:
        entry = {}
        stats['devices'][device] = entry
        if not any(a == device or a.startswith(device + '.') for a in available):
            entry['error'] = f'{device} is not available: OpenVINO finds {", ".join(available)}'
            print(f'{device}: {entry["error"]}')
            continue
        entry['properties'] = device_properties(core, device)
        config = {'INFERENCE_PRECISION_HINT': precision} if precision in ('f16', 'f32') else {}
        try:
            t = time.perf_counter()
            compiled = core.compile_model(model, device, config)
            entry['compile_ms'] = round((time.perf_counter() - t) * 1000, 1)
            try:
                entry['execution_devices'] = as_list(compiled.get_property('EXECUTION_DEVICES'))
            except Exception:
                pass
            try:
                entry['inference_precision'] = plain(compiled.get_property('INFERENCE_PRECISION_HINT'))
            except Exception:
                pass
            request = compiled.create_infer_request()
            for _ in range(5):
                request.infer({0: x})
            if seconds:
                print(f'{device}: running for {seconds:g} s ...', flush = True)
            times, per_second, elapsed = timed_run(lambda: request.infer({0: x}), iterations, seconds, flops, device)
            out = np.array(request.get_output_tensor(0).data, dtype = np.float32)
            err = float(np.max(np.abs(out - ref)))
            entry['calls'] = len(times)
            entry['latency_us'] = latency_stats(times)
            entry['gflops'] = round(flops / (entry['latency_us']['median'] / 1e6) / 1e9, 2)
            if seconds:
                entry['seconds'] = round(elapsed, 2)
                entry['inferences_per_second'] = round(len(times) / elapsed, 1)
                entry['gflops_sustained'] = round(len(times) * flops / elapsed / 1e9, 2)
                entry['gflops_per_second'] = per_second
            else:
                entry['inferences_per_second'] = round(1e6 / entry['latency_us']['median'], 1)
            entry['max_abs_error'] = err
            entry['max_rel_error'] = err / scale
            ran_there = not entry.get('execution_devices') or \
                any(d == device or d.startswith(device + '.') for d in entry['execution_devices'])
            entry['passed'] = bool(err <= 1e-2 * scale and ran_there)
            if not ran_there:
                entry['error'] = f'ran on {entry["execution_devices"]}, not on {device}'
        except Exception as e:
            entry['error'] = str(e)[:800]

        name = entry.get('properties', {}).get('FULL_DEVICE_NAME', device)
        if entry.get('latency_us'):
            timed = ''
            if entry.get('seconds'):
                ps = entry.get('gflops_per_second') or [entry['gflops_sustained']]
                timed = (f'; {entry["calls"]} calls in {entry["seconds"]} s, {entry["gflops_sustained"]} GFLOPS sustained '
                         f'(per second: {min(ps)}-{max(ps)})')
            print(f'{device} ({name}): compile {entry["compile_ms"]} ms, median {entry["latency_us"]["median"]} us '
                  f'(min {entry["latency_us"]["min"]}, p90 {entry["latency_us"]["p90"]}), {entry["gflops"]} GFLOPS, '
                  f'max error {entry["max_abs_error"]:.2e}{timed} -> {"OK" if entry["passed"] else "FAILED"}')
        else:
            print(f'{device} ({name}): {entry.get("error")}')

    stats['passed'] = bool(stats['devices']) and all(e.get('passed') for e in stats['devices'].values())

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)

    return 0 if stats['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
