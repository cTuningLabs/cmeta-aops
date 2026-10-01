"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared by the programs that run llama.cpp (llama-cpp, build-llama-cpp):

    from program_22788f3c30d04e6d.api.common_llama_cpp import finish_llama_run, completion_binary

The run writes the generated text to output.txt and llama.cpp's log (stderr) to llama.log.
finish_llama_run() removes the end-of-generation marker from output.txt and records the
timings llama.cpp prints (common_perf_print) in perf.json, which the programs return as
result['perf']: prompt and generation tokens per second, load and total time.
"""

import json
import os
import re

# "...: prompt eval time =      36.04 ms /    18 tokens (    2.00 ms per token,   499.42 tokens per second)"
_PERF = re.compile(r'(?P<key>load|prompt eval|eval|sampling|total) time\s*=\s*(?P<ms>[\d.]+)\s*ms'
                   r'(?:\s*/\s*(?P<n>\d+)\s*(?P<unit>tokens|runs))?'
                   r'(?:.*?(?P<tps>[\d.]+)\s*tokens per second)?')

# Devices llama.cpp offloads to: "using device CUDA0 (NVIDIA ...)" (newer builds) or "ggml_cuda_init: found 1 CUDA devices"
_DEVICE = re.compile(r'using device (\S+) \(([^)]*)\)')

END_MARKERS = ('[end of text]',)


def parse_llama_log(text):
    """The timings and devices of a llama-completion / llama-cli run from its log."""
    perf = {}
    for line in text.splitlines():
        if 'time =' not in line:
            continue
        m = _PERF.search(line)
        if not m:
            continue
        key = m.group('key').replace(' ', '_')
        entry = {'ms': float(m.group('ms'))}
        if m.group('n'):
            entry[m.group('unit')] = int(m.group('n'))
        if m.group('tps'):
            entry['tokens_per_second'] = float(m.group('tps'))
        perf[key] = entry

    devices = []
    for m in _DEVICE.finditer(text):
        d = {'name': m.group(1), 'description': m.group(2)}
        if d not in devices:
            devices.append(d)

    result = {}
    if perf:
        result['timings'] = perf
        if 'prompt_eval' in perf and 'tokens_per_second' in perf['prompt_eval']:
            result['prompt_tokens_per_second'] = perf['prompt_eval']['tokens_per_second']
        if 'eval' in perf and 'tokens_per_second' in perf['eval']:
            result['generation_tokens_per_second'] = perf['eval']['tokens_per_second']
    if devices:
        result['devices'] = devices

    build = re.search(r'build\s*[:=]\s*b?(\d+)', text)
    if build:
        result['build'] = int(build.group(1))

    # "system_info: n_threads = 16 (n_threads_batch = 16) / 16 | CUDA : ARCHS = 750,...,1210 | ... | CPU : AVX2 = 1 | ..."
    m = re.search(r'system_info:\s*(.+)', text)
    if m:
        info = m.group(1).strip().rstrip('|').strip()
        result['system_info'] = info
        threads = re.search(r'n_threads\s*=\s*(\d+)', info)
        if threads:
            result['threads'] = int(threads.group(1))
        archs = re.search(r'ARCHS\s*=\s*([\d,]+)', info)
        if archs:
            result['cuda_archs'] = [int(a) for a in archs.group(1).split(',') if a]

    return result


def finish_llama_run(program, ctx, desc = {}, **misc):
    """The program's internal_func after the run: clean output.txt, write perf.json."""
    _local = ctx['tasks']['local']
    work_path = _local.get('work_path')
    if not work_path or not os.path.isdir(work_path):
        work_path = os.getcwd()

    output = os.path.join(work_path, 'output.txt')
    if os.path.isfile(output):
        with open(output, encoding = 'utf-8', errors = 'replace') as f:
            text = f.read()
        cleaned = text.rstrip()
        for marker in END_MARKERS:
            if cleaned.endswith(marker):
                cleaned = cleaned[:-len(marker)].rstrip()
        if cleaned != text:
            with open(output, 'w', encoding = 'utf-8') as f:
                f.write(cleaned + '\n')

    log = os.path.join(work_path, 'llama.log')
    perf = {}
    if os.path.isfile(log):
        with open(log, encoding = 'utf-8', errors = 'replace') as f:
            perf = parse_llama_log(f.read())

    with open(os.path.join(work_path, 'perf.json'), 'w', encoding = 'utf-8') as f:
        json.dump(perf, f, indent = 2)

    return {'return': 0}


def optional_access(cm, ctx, ii):
    """
    Run a sub-task whose failure is acceptable (an optional dependency). A failed task returns
    without restoring the caller's context (local, params, control), which would break every
    step that follows, so it is saved and restored here.
    """
    tasks = ctx['tasks']
    saved = {k: tasks.get(k) for k in ('local', 'params', 'cparams')}
    saved_control = dict(ctx['control'])
    try:
        return cm.access(ii)
    finally:
        for k, v in saved.items():
            if v is not None:
                tasks[k] = v
        ctx['control'].clear()
        ctx['control'].update(saved_control)


def completion_binary(path_to_git_repo, target_path_bin, exe_ext):
    """
    The binary a source build should run for a one-shot completion: llama-completion when the
    checkout has it (the late-2025 llama-cli rework), else llama-cli (older checkouts).
    """
    if path_to_git_repo and os.path.isdir(os.path.join(path_to_git_repo, 'tools', 'completion')):
        return 'llama-completion' + exe_ext
    return 'llama-cli' + exe_ext
