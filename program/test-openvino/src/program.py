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


def device_properties(core, device):
    props = {}
    for p in PROPERTIES:
        try:
            props[p] = plain(core.get_property(device, p))
        except Exception:
            pass
    return props


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
    precision = (os.environ.get('CMETA_OPENVINO_PRECISION') or '').strip().lower()

    core = ov.Core()
    available = list(core.available_devices)

    wanted = [d.strip().upper() for d in (os.environ.get('CMETA_OPENVINO_DEVICES') or '').split(',') if d.strip()]
    if not wanted:
        wanted = [DEVICE_OF_TARGET[t] for t in targets if t in DEVICE_OF_TARGET] or available

    rng = np.random.default_rng(12345)
    x = rng.random((batch, n), dtype = np.float32)
    w = rng.random((n, n), dtype = np.float32) / n
    ref = np.maximum(x @ w, 0)
    scale = float(np.max(np.abs(ref))) or 1.0

    param = ops.parameter([batch, n], np.float32, name = 'x')
    model = ov.Model([ops.relu(ops.matmul(param, ops.constant(w), False, False))], [param], 'matmul-relu')

    stats = {'openvino': ov.get_version(), 'targets': targets, 'size': n, 'batch': batch, 'iterations': iterations,
             'precision_hint': precision or None, 'available_devices': available, 'devices': {}}

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
            times = []
            for _ in range(iterations):
                t = time.perf_counter()
                request.infer({0: x})
                times.append(time.perf_counter() - t)
            out = np.array(request.get_output_tensor(0).data, dtype = np.float32)
            err = float(np.max(np.abs(out - ref)))
            entry['latency_us'] = latency_stats(times)
            entry['inferences_per_second'] = round(1e6 / entry['latency_us']['median'], 1)
            entry['gflops'] = round(2 * batch * n * n / (entry['latency_us']['median'] / 1e6) / 1e9, 2)
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
            print(f'{device} ({name}): compile {entry["compile_ms"]} ms, median {entry["latency_us"]["median"]} us '
                  f'(min {entry["latency_us"]["min"]}, p90 {entry["latency_us"]["p90"]}), {entry["gflops"]} GFLOPS, '
                  f'max error {entry["max_abs_error"]:.2e} -> {"OK" if entry["passed"] else "FAILED"}')
        else:
            print(f'{device} ({name}): {entry.get("error")}')

    stats['passed'] = bool(stats['devices']) and all(e.get('passed') for e in stats['devices'].values())

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)

    return 0 if stats['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
