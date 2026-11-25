"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import importlib.util
import json
import os
import re
import shutil
import copy
import time

from cmeta.utils.names import parse_cmeta_name

from task_c36be4b9314a45e0.api.ctask import InitCTask
from task_c36be4b9314a45e0.api import deadlines
from task_c36be4b9314a45e0.api import build_stamp
from task_c36be4b9314a45e0.api import build_identity
from task_c36be4b9314a45e0.api import provenance


###################################################################################################
# The summary of a run, printed after it (--summary=no keeps it quiet) and kept in the result
# ("summary"): what ran, on which targets with which tools, the input, the command, how long it
# took, what it produced and where, the checks. A program's hooks add to it (customize_summary).

def size_text(n):
    """A size in bytes as text, 1000-based."""
    if not isinstance(n, (int, float)):
        return '?'
    for unit, div in (('GB', 1e9), ('MB', 1e6), ('KB', 1e3)):
        if n >= div:
            return f'{n / div:.1f} {unit}'
    return f'{int(n)} B'


def seconds_text(x):
    return f'{x:.3f} s' if isinstance(x, (int, float)) else '?'


def cpu_name(target_features):
    """The CPU of the target as the target task saw it, with its logical CPUs."""
    cpu = (target_features or {}).get('cpu') or {}
    if not isinstance(cpu, dict):
        return None
    name = cpu.get('model_name') or cpu.get('brand')
    packages = cpu.get('packages')
    if not name and isinstance(packages, list) and packages and isinstance(packages[0], dict):
        name = packages[0].get('Name') or packages[0].get('name')
    name = name or cpu.get('extended_identifier') or cpu.get('arch_normalized')
    count = cpu.get('logical_cpu_count')
    if name and count:
        name = f'{name}, {count} logical CPUs'
    return name


def tools_text(resolved):
    """The tools of the run as text - the compilers first (with their role), then the libraries - each once."""
    shown = set()
    out = []
    for k in sorted(resolved or {}, key = lambda k: (0 if k.startswith('compiler-') else 1 if k.startswith('lib-') else 2, k)):
        v = resolved[k] if isinstance(resolved[k], dict) else {}
        name, version = v.get('name') or k, v.get('version')
        if (name, version) in shown:
            continue
        shown.add((name, version))
        text = f'{name} {version}' if version and version != 'default' else name
        out.append(f'{k}: {text}' if k.startswith('compiler-') else text)
    return ', '.join(out)


def run_summary_of(local, global_ctx, params, result, resolved, error = None, built_now = None, run_skipped = False):
    """
    The summary of a run from its context (local and global), its parameters, its result and the tools of the
    run (provenance.collect_resolved); error: what ended the run.
    """
    local = local if isinstance(local, dict) else {}
    global_ctx = global_ctx if isinstance(global_ctx, dict) else {}
    params = params if isinstance(params, dict) else {}
    result = result if isinstance(result, dict) else {}
    target = global_ctx.get('target') or {}
    host = global_ctx.get('host') or {}
    os_ = host.get('os') or {}
    os_extra = host.get('os_extra') or {}
    run = local.get('run-program') if isinstance(local.get('run-program'), dict) else {}

    rc = run.get('returncode')
    if error:
        status = 'timeout' if run.get('timed_out') or 'timed out' in str(error) else 'failed'
        if rc is None:                               # the cmd task's error names the program's exit code
            m = re.search(r'return code (-?\d+)', str(error))
            rc = int(m.group(1)) if m else None
    elif run_skipped:
        status = 'skipped'
    else:
        status = 'ok'

    selected = local.get('selected-program') or {}
    alias = ((selected.get('artifact') or {}).get('cmeta_ref_parts') or {}).get('artifact_alias') or params.get('name')
    cmd = params.get('cmd')
    if isinstance(cmd, list):
        cmd = ','.join(str(c) for c in cmd)

    # The OS by its distribution (ubuntu 24.04) when the host task knows one, else as Python names it (Windows-11)
    os_name = ' '.join(str(os_extra.get(k)) for k in ('id', 'version') if os_extra.get(k))
    if not os_name or os_name == os_.get('uname'):
        os_name = os_.get('python_platform_terse') or os_name
    hostname = host.get('hostname')
    if isinstance(hostname, dict):
        hostname = hostname.get('hostname')

    summary = {'program': alias, 'cmd': cmd or 'default', 'status': status, 'return_code': rc,
               'error': str(error) if error else None,
               'compute': [str(c) for c in target.get('compute') or []],
               'host': {'uname': os_.get('uname'), 'uarch': os_.get('uarch'), 'hostname': hostname, 'os': os_name or None},
               'cpu': cpu_name(target.get('features')),
               'gpu': [], 'opencl_devices': [],
               'tools': tools_text(resolved),
               'resolved': {k: {'name': v.get('name'), 'version': v.get('version')} for k, v in (resolved or {}).items()
                            if isinstance(v, dict)},
               'input': None, 'command': None, 'run_script': None, 'work_path': None,
               'times': {}, 'outputs': [], 'result_files': {}, 'checks': [], 'build': {}, 'lines': []}

    # The GPUs of a CUDA run (the cuda tool's probe), the OpenCL devices the target saw
    cuda = (global_ctx.get('cuda') or {}).get('features') or {}
    versions = cuda.get('versions') if isinstance(cuda.get('versions'), dict) else {}
    for d in cuda.get('devices') or []:
        if isinstance(d, dict):
            summary['gpu'].append({'name': d.get('name'), 'compute_capability': d.get('compute_cap'),
                                   'driver': d.get('driver_version') or versions.get('driver version'),
                                   'cuda': versions.get('cuda version')})
    opencl = (target.get('features') or {}).get('opencl') or {}
    for d in opencl.get('devices') or []:
        if isinstance(d, dict):
            summary['opencl_devices'].append({'name': d.get('name'), 'platform': d.get('platform'), 'version': d.get('version'),
                                              'driver': d.get('driver_version'), 'type': d.get('type')})

    # The input: the dataset of the run, else the input files
    ds = local.get('dataset')
    if isinstance(ds, dict) and ds.get('path'):
        path = str(ds['path'])
        summary['input'] = {'dataset': ds.get('artifact_au'), 'sub_dataset': ds.get('sub_dataset'), 'desc': ds.get('desc'),
                            'path': path, 'size': os.path.getsize(path) if os.path.isfile(path) else None,
                            'files': [str(f) for f in ds.get('files') or []]}
    elif isinstance(local.get('input_files'), dict) and local['input_files']:
        summary['input'] = {'files': {str(k): str(v) for k, v in local['input_files'].items()}}

    # The command (the program's path shortened to its name when it is in the build folder) and the scripts
    target_path = local.get('target_path')
    work_path = local.get('work_path') or target_path
    cmds = local.get('run_time_cmds')
    command = str(cmds[-1]).strip() if isinstance(cmds, list) and cmds else (cmds.strip() if isinstance(cmds, str) else '')
    if command and target_path:
        for prefix in (os.path.join(target_path, ''), '"' + os.path.join(target_path, '')):
            if command.startswith(prefix):
                command = command[len(prefix):] if not prefix.startswith('"') else '"' + command[len(prefix):]
                break
    summary['command'] = command or None
    ext = (host.get('vars') or {}).get('file_ext_bat') or ('.bat' if os_.get('uname') == 'windows' else '.sh')
    summary['work_path'] = work_path
    if target_path:
        summary['run_script'] = os.path.join(target_path, 'tmp-cmeta-run-program' + ext)

    # Times: the program's own run, the run and the compile with cMeta, a kernel time of a result file
    impact = result.get('_impact') if isinstance(result.get('_impact'), dict) else {}
    times = {'run_seconds': (run.get('_impact') or {}).get('self_time'),
             'run_with_cmeta_seconds': impact.get('self_time_run_with_cmeta'),
             'compile_with_cmeta_seconds': impact.get('self_time_compile_with_cmeta')}
    result_files = local.get('result_files') if isinstance(local.get('result_files'), dict) else {}
    data = local.get('result_files_data') if isinstance(local.get('result_files_data'), dict) else {}
    for key, content in data.items():
        if isinstance(content, dict):
            keys = [k for k in content if str(k).startswith('execution_time') and isinstance(content[k], (int, float))]
            k = next((k for k in keys if str(k).startswith('execution_time_kernel')), keys[0] if keys else None)
            if k is not None:
                times['kernel_seconds'] = content[k]
                times['kernel_source'] = f'{k} of {result_files.get(key, key)}'
                break
    summary['times'] = {k: v for k, v in times.items() if v is not None}
    summary['result_files'] = {str(k): str(v) for k, v in result_files.items()}

    # The outputs and where they are
    names = [str(f) for f in local.get('output_files') or []]
    names += [str(f) for f in result_files.values() if str(f) not in names]
    for name in names:
        p = os.path.join(work_path, name) if work_path else name
        summary['outputs'].append({'name': name, 'path': p, 'size': os.path.getsize(p) if os.path.isfile(p) else None})

    # The checks of the provenance record
    prov = result.get('provenance') if isinstance(result.get('provenance'), dict) else {}
    if prov:
        errors, warnings = prov.get('errors') or 0, prov.get('warnings') or 0
        summary['checks'].append({'what': 'provenance record', 'ok': bool(prov.get('ok', True)) and not errors,
                                  'detail': f'{errors} errors, {warnings} warnings' + (f' - {prov["path"]}' if prov.get('path') else '')})

    # The check of the outputs against the reference (--check_output), when the run made one
    oc = result.get('output_check') if isinstance(result.get('output_check'), dict) else None
    if oc and oc.get('status'):
        status = oc['status']
        files = oc.get('files') or {}
        if status == 'validated':
            same = sum(1 for v in files.values() if v.get('status') == 'ok')
            added = sum(1 for v in files.values() if v.get('status') == 'added')
            check = {'ok': True, 'detail': f'{same} file(s) the same as the reference' +
                                           (f', {added} added to it (the reference had none)' if added else '') + f' ({oc.get("case")})'}
        elif status == 'failed':
            bad = [f'{n} - {v.get("why")}' for n, v in files.items() if v.get('status') != 'ok']
            check = {'ok': False, 'detail': '; '.join(bad) + f' (the reference: {oc.get("case")})'}
        elif status == 'recorded':
            check = {'ok': True, 'detail': f'{sum(1 for v in files.values() if v.get("status") == "recorded")} file(s) recorded as the reference in {oc.get("repo")}: {oc.get("case")}'}
        else:
            check = {'ok': None if status in ('nothing', 'no_reference') else False, 'detail': oc.get('error') or oc.get('note') or status}
        summary['checks'].append({'what': 'reference outputs', **check})

    summary['build'] = {'path': target_path, 'compiled_now': built_now,
                        'script': os.path.join(target_path, 'tmp-cmeta-compile-program' + ext) if target_path else None}

    # The parameters of the request (the program's: --repeat, --compile.size ...), and the calibration of the repeat
    summary['params'] = request_params(params)
    summary['calibration'] = result.get('calibration') if isinstance(result.get('calibration'), dict) else None

    # What the run printed, when the cmd task kept it (a program family that redirects names its files instead)
    for stream in ('stdout', 'stderr'):
        text = run.get(stream)
        if isinstance(text, str) and text.strip():
            summary[stream] = {'source': 'the run', 'text': text}

    # The stats the program collected: its result files (xOpenME's timer ...), as finish-run read them
    summary['stats'] = [{'key': str(k), 'file': str(result_files.get(k, k)), 'data': v} for k, v in data.items()]

    return summary


def summary_text(summary):
    """The lines of a summary for the console."""
    s = summary
    status = {'ok': 'OK', 'failed': 'FAILED', 'timeout': 'TIMED OUT', 'skipped': 'not run (compile only)'}.get(s.get('status'), str(s.get('status')))
    times = s.get('times') or {}
    head = f'cMeta run summary: {s.get("program")} ({s.get("cmd")}) on {",".join(s.get("compute") or []) or "?"}: {status}'
    if s.get('return_code') is not None:
        head += f', exit {s["return_code"]}'
    if 'run_seconds' in times:
        head += f' in {seconds_text(times["run_seconds"])}'
    if 'kernel_seconds' in times:
        head += f' (kernel {seconds_text(times["kernel_seconds"])})'
    lines = [head]

    h = s.get('host') or {}
    text = ' '.join(str(h.get(k)) for k in ('uname', 'uarch') if h.get(k))
    if h.get('os'):
        text += f' ({h["os"]})'
    if h.get('hostname'):
        text += f' {h["hostname"]}'
    if s.get('cpu'):
        text += f'; CPU {s["cpu"]}'
    lines.append(f'  host:     {text}')
    for g in s.get('gpu') or []:
        extra = ', '.join(x for x in (f'compute capability {g["compute_capability"]}' if g.get('compute_capability') else '',
                                      f'driver {g["driver"]}' if g.get('driver') else '',
                                      f'CUDA {g["cuda"]}' if g.get('cuda') else '') if x)
        lines.append(f'  gpu:      {g.get("name")}' + (f' ({extra})' if extra else ''))
    if 'opencl' in (s.get('compute') or []) and s.get('opencl_devices'):
        lines.append('  opencl:   ' + '; '.join(f'{d.get("name")} ({d.get("platform")}, {d.get("version")})' for d in s['opencl_devices']))
    if s.get('tools'):
        lines.append(f'  tools:    {s["tools"]}')

    inp = s.get('input') or {}
    if inp.get('dataset'):
        name = inp['dataset'] + (f'/{inp["sub_dataset"]}' if inp.get('sub_dataset') else '')
        lines.append(f'  input:    {name}' + (f' - {inp["desc"]}' if inp.get('desc') else ''))
        lines.append(f'            {inp.get("path")} ({size_text(inp.get("size"))})')
    elif inp.get('path'):
        lines.append(f'  input:    {inp["path"]} ({size_text(inp.get("size"))})')
    elif isinstance(inp.get('files'), dict) and inp['files']:
        lines.append('  input:    ' + ', '.join(f'{k} = {v}' for k, v in inp['files'].items()))
    if s.get('command'):
        lines.append(f'  command:  {s["command"]}')
    if s.get('params'):
        lines.append(f'  params:   {params_text(s["params"])}')
    c = s.get('calibration') or {}
    if c:
        first = (c.get('history') or [{}])[0].get('repeat', c.get('repeat'))
        verdict = 'done' if c.get('success') else 'FAILED'
        text = f'{c.get("param")} {first} -> {c.get("repeat")} in {c.get("rounds")} round{"s" if c.get("rounds") != 1 else ""}: {verdict}'
        if c.get('seconds') is not None:
            text += f', the run lasts {seconds_text(c["seconds"])} for a target of {seconds_text(c.get("target"))}'
        if c.get('why') and not c.get('success'):
            text += f' - {c["why"]}'
        lines.append(f'  calibration: {text}')
    outs = s.get('outputs') or []
    if outs:
        lines.append(f'  outputs:  {s.get("work_path")}')
        lines.append('            ' + ', '.join(f'{o["name"]} ({size_text(o["size"])})' if o.get('size') is not None else f'{o["name"]} (not made)' for o in outs))
    b = s.get('build') or {}
    if b.get('path'):
        how = 'built now' if b.get('compiled_now') else ('reused' if b.get('compiled_now') is False else '')
        text = b['path'] + (f' ({how})' if how else '')
        if 'compile_with_cmeta_seconds' in times and b.get('compiled_now'):
            text += f', compile {seconds_text(times["compile_with_cmeta_seconds"])} with cMeta'
        lines.append(f'  build:    {text}')
        scripts = [os.path.basename(x) for x in (b.get('script'), s.get('run_script')) if x]
        if scripts:
            lines.append(f'            scripts {", ".join(scripts)}' + (', provenance.json' if any(c.get('what') == 'provenance record' for c in s.get('checks') or []) else ''))
    for c in s.get('checks') or []:
        mark = 'ok' if c.get('ok') is True else ('FAILED' if c.get('ok') is False else '?')
        lines.append(f'  check:    {c.get("what")}: {mark}' + (f' - {c["detail"]}' if c.get('detail') else ''))
    for x in s.get('lines') or []:
        lines.append(f'  {x}')
    if s.get('error'):
        lines.append(f'  error:    {s["error"]}')
    return lines


RULE = '=' * 100
OUTPUT_MAX_LINES = 60


def output_section(what, out):
    """The lines of a stream's section: a header, the text (its first OUTPUT_MAX_LINES lines), where the rest is."""
    text = str(out.get('text') or '')
    lines = text.rstrip('\n').splitlines()
    source = out.get('source')
    head = f'{what} of the run' + (f' ({source}, ' if source else ' (') + f'{len(lines)} line{"s" if len(lines) != 1 else ""}):'
    shown = lines[:OUTPUT_MAX_LINES]
    rest = []
    if len(lines) > len(shown):
        rest = [f'... {len(lines) - len(shown)} more lines' + (f' in {out["path"]}' if out.get('path') else '')]
    return [head, ''] + shown + rest


def stats_lines(data):
    """The lines of a result file's data: nested keys joined with a dot, a text as it is."""
    if isinstance(data, dict):
        out = []
        for k, v in data.items():
            if isinstance(v, dict):
                out += [f'{k}.{x}' for x in stats_lines(v)]
            else:
                out.append(f'{k} = {v}')
        return out
    if isinstance(data, list):
        return [str(x) for x in data]
    return str(data).rstrip('\n').splitlines() if data is not None else []


def summary_block(summary):
    """
    The whole block printed after a run, its sections apart by a rule: the standard output when the run kept it,
    the standard error when there is one, the summary, and the stats the program collected (its result files).
    """
    sections = []
    if summary.get('stdout'):
        sections.append(output_section('standard output', summary['stdout']))
    if summary.get('stderr'):
        sections.append(output_section('standard error', summary['stderr']))
    sections.append(summary_text(summary))
    stats = []
    for s in summary.get('stats') or []:
        if stats:
            stats.append('')
        stats.append(f'stats of the run: {s.get("key")} ({s.get("file")})')
        lines = stats_lines(s.get('data'))
        stats += [f'  {x}' for x in lines] if lines else ['  (empty)']
    if stats:
        sections.append(stats)
    block = [RULE]
    for section in sections:
        block += section + [RULE]
    return block


###################################################################################################
# The reference outputs of a program (the category program.output): an artifact per program, a case per command,
# input and parameters - recorded by a run, compared by the next ones (cx program run <program> <target>
# --check_output). A case is a folder named by a UID with case.json: the key of the case, the facts of the
# recording, every output file with its size and digests; the files themselves beside it when small.

OUTPUT_CATEGORY = 'program.output'
OUTPUT_CASE = 'case.json'
OUTPUT_STDIO = ('tmp-output1.tmp', 'tmp-output2.tmp', 'tmp-ck-timer.json')   # what the run printed and its times: not compared unless listed
CHECK_PARAMS = ('check_output', 'output_repo', 'overwrite_output', 'summary', 'calibrate', 'calibrate_max')   # the task's switches, not the program's parameters

# CK's calibration of the kernel's repeat (--calibrate): the run made to last about this many seconds, in at most
# this many rounds (CK: calibration_time 4.0, calibration_max 10)
CALIBRATION_TIME = 4.0
CALIBRATION_MAX = 10


# An absolute path in a recorded fact (a command line, a compile flag): a Windows drive path or a POSIX one, at the start
# of a word, after a quote, an '=' or a flag such as -I - kept as its last part, so that a reference recorded on one
# machine names neither the machine's folders nor its user
ABS_PATH = re.compile(r'(?:^|(?<=[\s"\'=,(\[])|(?<=-[A-Za-z]))(?:[A-Za-z]:[\\/]|/)[^\s"\';|<>]*')
QUOTED_PATH = re.compile(r'(["\'])((?:[A-Za-z]:[\\/]|/)[^"\']*)\1')     # a quoted one may hold spaces


def last_part(path):
    """The last part of a path ("data.txt" of "D:\\work\\data.txt"), the path itself when it has none."""
    return re.split(r'[\\/]', path.rstrip('\\/'))[-1] or path


def path_neutral(value):
    """A recorded fact without the folders of the machine: every absolute path reduced to its last part, in a text or in
    the texts of a list or a dictionary (keys kept)."""
    if isinstance(value, str):
        value = QUOTED_PATH.sub(lambda m: m.group(1) + last_part(m.group(2)) + m.group(1), value)
        return ABS_PATH.sub(lambda m: last_part(m.group(0)), value)
    if isinstance(value, list):
        return [path_neutral(x) for x in value]
    if isinstance(value, dict):
        return {k: path_neutral(v) for k, v in value.items()}
    return value


def recorded_facts(summary, program_alias, program_uid):
    """
    The facts a reference recording keeps (case.json "recorded"): when, the program, the host's system and architecture
    (never its name), the CPU and the GPUs, the targets, the tools, the command line and the parameters without the
    machine's folders, the calibration and the times. A reference is published: it says what it was made with, not
    whose machine made it.
    """
    s = summary if isinstance(summary, dict) else {}
    host = {k: v for k, v in (s.get('host') or {}).items() if k != 'hostname'}
    return {'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'program': f'{program_alias},{program_uid}',
            'host': host, 'cpu': s.get('cpu'), 'gpu': [g.get('name') for g in s.get('gpu') or []],
            'compute': s.get('compute'), 'tools': s.get('tools'), 'command': path_neutral(s.get('command')),
            'params': path_neutral(s.get('params')), 'calibration': s.get('calibration'), 'times': s.get('times')}


def request_params(params):
    """The parameters of the request that belong to the program: all of them but the task's own switches and the empty ones."""
    return {str(k): v for k, v in (params or {}).items() if k not in CHECK_PARAMS and v is not None}


def params_text(params):
    """The parameters on one line: k=v, nested keys dotted (compile.size=large), a valueless define by its name."""
    items = []

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f'{prefix}{k}.', x)
        else:
            items.append(prefix[:-1] + ('' if v is None else f'={v}'))

    walk('', params if isinstance(params, dict) else {})
    return ', '.join(items)


def run_seconds_of(local):
    """The time a run took: execution_time of a result file (xOpenME's timer, when it is not zero), else the run's wall time."""
    data = local.get('result_files_data') if isinstance(local.get('result_files_data'), dict) else {}
    for content in data.values():
        if isinstance(content, dict) and isinstance(content.get('execution_time'), (int, float)) and content['execution_time'] > 0:
            return float(content['execution_time'])
    run = local.get('run-program') if isinstance(local.get('run-program'), dict) else {}
    seconds = (run.get('_impact') or {}).get('self_time')
    return float(seconds) if isinstance(seconds, (int, float)) else None


def calibration_step(plan, local):
    """
    One round of CK's calibration after a run: the run's time against the target. Under half a second the repeat
    grows tenfold; within 0.8 and 1.4 of the target (target / time) it is done; else the repeat is scaled by
    target / time (one at least); a repeat that does not change is done too; past the rounds allowed, failed.
    """
    seconds = run_seconds_of(local)
    plan['rounds'] += 1
    plan['history'].append({'repeat': plan['repeat'], 'seconds': seconds})
    plan['seconds'] = seconds
    repeat, target = plan['repeat'], plan['target']
    if seconds is None:
        plan.update({'done': True, 'success': False, 'why': 'the time of the run is not known (no execution_time in a result file, no run time)'})
        return plan
    if seconds < 0.5:
        new = repeat * 10
    elif 0.8 < target / seconds < 1.4:
        plan.update({'done': True, 'success': True})
        return plan
    else:
        new = max(1, int(repeat * target / seconds))
    new = int(new)
    if new == repeat:
        plan.update({'done': True, 'success': True})
    elif plan['rounds'] >= plan['max']:
        plan.update({'done': True, 'success': False,
                     'why': f'calibration failed: {plan["rounds"]} rounds (--calibrate_max) and the run lasts {seconds_text(seconds)} '
                            f'with {plan["param"]} = {repeat}, for a target of {seconds_text(target)}'})
    else:
        plan['next'] = new
        plan['repeat'] = new
    return plan
OUTPUT_KEPT_MAX = 10 * 1000 * 1000             # a reference file is kept beside case.json up to this size; bigger: its digests alone
NAN_WORDS = re.compile(rb'-?(?:nan\(ind\)|nan|1\.#IND|1\.#QNAN)', re.I)
NUMBER = re.compile(r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?')


def output_check_rules(desc, cmd = None):
    """
    The rules of a program's output check - "output_check" of its description, the command's own entry
    (updates_cmd.<cmd>.output_check) on top: files (the outputs compared; default: the run's output files minus
    what it printed and its times), key_params (the parameters that tell the cases apart, dotted), tolerance (of
    the numbers in a text file: relative, with an absolute floor of the same value), skip (files never compared),
    artifact (the program whose references these are, when shared), key_values (values of the key given as they
    are, by a hook mostly: {name: value}), invariant_of_repeat (the output does not depend on the kernel's repeat).
    """
    rules = {}
    for block in (desc.get('output_check'), ((desc.get('updates_cmd') or {}).get(cmd) or {}).get('output_check') if cmd else None):
        if isinstance(block, dict):
            for k, v in block.items():
                if k in ('files', 'key_params', 'skip', 'ignore_lines') and isinstance(v, list) and isinstance(rules.get(k), list):
                    rules[k] = rules[k] + [x for x in v if x not in rules[k]]
                elif k == 'key_values' and isinstance(v, dict) and isinstance(rules.get(k), dict):
                    rules[k] = {**rules[k], **v}
                else:
                    rules[k] = v
    return rules


def output_files_of(rules, local):
    """The output files a check compares: the rules' files, else the run's output files minus the stdio captures and the times; minus skip."""
    files = rules.get('files') if isinstance(rules.get('files'), list) else [f for f in (local.get('output_files') or []) if str(f) not in OUTPUT_STDIO]
    skip = {str(s) for s in rules.get('skip') or []}
    return [str(f) for f in files if str(f) not in skip]


def output_key(rules, program, cmd, local, params):
    """The key of a case: the program, the command, the dataset, its sub-dataset and file, the parameters that matter."""
    dataset = local.get('dataset') if isinstance(local.get('dataset'), dict) else {}
    alias = str(dataset.get('artifact_au') or '') or None        # the dataset's alias (commas and all), else its UID
    key = {'program': program, 'cmd': cmd or 'default', 'dataset': alias,
           'sub_dataset': dataset.get('sub_dataset') or None,
           'dataset_file': os.path.basename(str(dataset['path'])) if dataset.get('path') else None,
           'params': {}}
    for name in rules.get('key_params') or []:
        value = params
        for part in str(name).split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        key['params'][str(name)] = value if value is None or isinstance(value, (bool, int, float)) else str(value)
    for name, value in (rules.get('key_values') or {}).items():
        key['params'][str(name)] = value if value is None or isinstance(value, (bool, int, float)) else str(value)
    return key


def same_key(a, b):
    """Two keys of cases the same: every field as text (a number written or typed), the parameters as a whole."""
    def norm(k):
        k = k if isinstance(k, dict) else {}
        out = {f: (None if k.get(f) is None else str(k.get(f))) for f in ('program', 'cmd', 'dataset', 'sub_dataset', 'dataset_file')}
        out['params'] = {str(n): (None if v is None else str(v)) for n, v in (k.get('params') or {}).items()}
        return out
    return norm(a) == norm(b)


def ignore_patterns(rules):
    """
    The lines of the outputs left out of a comparison (output_check.ignore_lines: regular expressions, a line that
    matches one is dropped - the device a GPU program names, a path, a time): the compiled patterns, or an error.
    """
    out = []
    for p in (rules.get('ignore_lines') or []) if isinstance(rules, dict) else []:
        try:
            out.append(re.compile(str(p).encode('utf-8')))
        except re.error as e:
            return None, f'output_check.ignore_lines: "{p}" is not a regular expression ({e})'
    return out, None


def without_ignored(data, ignore):
    """The bytes of a text file without the lines that match one of the patterns (a binary file - with NUL - as it is)."""
    if not ignore or b'\0' in data:
        return data
    return b''.join(line for line in data.splitlines(keepends = True) if not any(p.search(line) for p in ignore))


def output_digests(path, ignore = None):
    """
    {size, sha256, sha256_lf (Windows line ends read as \\n), sha256_nan (every NaN spelled nan; text files)} of a
    file; with ignore (compiled patterns), the digests are of its text without the lines that match one of them.
    """
    import hashlib
    with open(path, 'rb') as f:
        data = f.read()
    size = len(data)
    data = without_ignored(data, ignore)
    lf = data.replace(b'\r\n', b'\n')
    out = {'size': size, 'sha256': hashlib.sha256(data).hexdigest(), 'sha256_lf': hashlib.sha256(lf).hexdigest()}
    if b'\0' not in data:
        out['sha256_nan'] = hashlib.sha256(NAN_WORDS.sub(b'nan', lf)).hexdigest()
    return out


def numbers_within(path, reference, tolerance, ignore = None, tolerance_abs = None):
    """
    Two text files the same but for their numbers, every number within tolerance of the reference's: relative, with
    an absolute floor - tolerance_abs, else the tolerance itself (a number printed with 2 decimals moves by 0.01 when
    a tiny difference crosses its rounding: tolerance_abs 0.01 lets that through). (True, note) or (False, why). With
    ignore, the lines that match one of the patterns are left out of both.
    """
    floor = tolerance if tolerance_abs is None else float(tolerance_abs)
    try:
        with open(path, 'rb') as f:
            a = without_ignored(f.read(), ignore).decode('utf-8', errors = 'replace').replace('\r\n', '\n')
        with open(reference, 'rb') as f:
            b = without_ignored(f.read(), ignore).decode('utf-8', errors = 'replace').replace('\r\n', '\n')
    except OSError as e:
        return False, str(e)
    if NUMBER.sub('#', a) != NUMBER.sub('#', b):
        return False, 'the text around the numbers differs'
    na, nb = NUMBER.findall(a), NUMBER.findall(b)
    if len(na) != len(nb):
        return False, f'{len(na)} numbers, the reference {len(nb)}'
    worst = 0.0
    for n, (x, y) in enumerate(zip(na, nb), 1):
        try:
            x, y = float(x), float(y)
        except ValueError:
            if x != y:
                return False, f'number {n}: {x} vs {y}'
            continue
        if x != y:
            diff = abs(x - y) / max(1.0, abs(y))
            worst = max(worst, diff)
            # within the relative tolerance, or the absolute floor (a hair above it: 1.01 - 1.00 is 0.010000000000000009)
            if abs(x - y) > max(tolerance * abs(y), floor) * (1 + 1e-9) + 1e-12:
                limit = f'{tolerance:g}' + (f' or {floor:g} absolute' if floor != tolerance else '')
                return False, f'number {n}: {x} vs {y} ({diff:.3g} beyond {limit})'
    limit = f'{tolerance:g}' + (f' (or {floor:g} absolute)' if floor != tolerance else '')
    return True, f'{len(nb)} numbers within {limit}' + (f', the worst {worst:.3g}' if worst else ', all equal')


def compare_output(path, record, reference_path, tolerance, ignore = None, tolerance_abs = None):
    """
    One output of a run against its reference: ('ok' | 'differs' | 'missing', why); with ignore, without the lines that
    match; the numbers of a text file within tolerance (relative) or tolerance_abs (absolute) when a tolerance is given.
    """
    if not os.path.isfile(path):
        return 'missing', 'the run made no such file'
    d = output_digests(path, ignore)
    if d['sha256'] == record.get('sha256'):
        return 'ok', 'the same' + (' (the lines of ignore_lines left out)' if ignore else '')
    if record.get('sha256_lf') and d['sha256_lf'] == record['sha256_lf']:
        return 'ok', 'the same but for the line ends'
    if record.get('sha256_nan') and d.get('sha256_nan') == record['sha256_nan']:
        return 'ok', 'the same but for the spelling of NaN'
    if reference_path and os.path.isfile(reference_path) and isinstance(tolerance, (int, float)) and tolerance >= 0:
        ok, why = numbers_within(path, reference_path, float(tolerance), ignore, tolerance_abs)
        return ('ok' if ok else 'differs'), why
    why = f'{d["size"]} bytes against {record.get("size")} of the reference'
    if not (reference_path and os.path.isfile(reference_path)):
        why += ' (the reference file was not kept: the digests alone)'
    return 'differs', why


def read_case(folder):
    try:
        with open(os.path.join(folder, OUTPUT_CASE), encoding = 'utf-8') as f:
            case = json.load(f)
        return case if isinstance(case, dict) else None
    except (OSError, ValueError):
        return None


def find_case(artifact_paths, key):
    """The case of this key in the artifacts' folders (the first found): {'artifact', 'folder', 'case'} or None."""
    for path in artifact_paths:
        for name in sorted(os.listdir(path)) if os.path.isdir(path) else []:
            folder = os.path.join(path, name)
            case = read_case(folder) if os.path.isdir(folder) else None
            if case and same_key(case.get('key'), key):
                return {'artifact': path, 'folder': folder, 'case': case}
    return None


def write_case(folder, key, facts, files, work_path, kept_max = OUTPUT_KEPT_MAX, ignore = None, ignore_lines = None):
    """
    A case recorded: case.json and the output files kept beside it (up to kept_max bytes each); with ignore, the
    digests are of the files without the lines that match (the files are kept whole), and case.json names the
    patterns (ignore_lines).
    """
    os.makedirs(folder, exist_ok = True)
    case = {'key': key, 'recorded': facts, 'files': {}}
    if ignore_lines:
        case['ignore_lines'] = [str(p) for p in ignore_lines]
    for name in files:
        src = os.path.join(work_path, name)
        if not os.path.isfile(src):
            case['files'][name] = None
            continue
        d = output_digests(src, ignore)
        d['kept'] = d['size'] <= kept_max
        if d['kept']:
            dst = os.path.join(folder, name)
            os.makedirs(os.path.dirname(dst), exist_ok = True)
            shutil.copyfile(src, dst)
        case['files'][name] = d
    with open(os.path.join(folder, OUTPUT_CASE), 'w', encoding = 'utf-8', newline = '\n') as f:
        json.dump(case, f, indent = 1, sort_keys = True)
        f.write('\n')
    return case


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    @staticmethod
    def dataset_steps_take_the_programs_params(steps):
        """
        The dataset steps of a run (task: dataset,...) take the program's --dataset and --dataset_file when they do
        not name their own "name" and "filename": every program answers to them, as the ones converted from CK do.
        """
        for step in steps if isinstance(steps, list) else []:
            # the task's alias: an alias may hold commas, only a UID after the last one is cut
            task = (parse_cmeta_name(str(step.get('task') or '')).get('name') or {}) if isinstance(step, dict) else {}
            if task.get('alias') == 'dataset':
                step.setdefault('name', '{{params.dataset|$None}}')
                step.setdefault('filename', '{{params.dataset_file|$None}}')

    ############################################################
    def calibration_plan(self, params, local, desc = None):
        """
        The plan of CK's calibration asked for with --calibrate: nothing (None) without it; else the target in seconds
        (--calibrate alone: CALIBRATION_TIME, as CK; --calibrate=<seconds>), the rounds allowed (--calibrate_max,
        CALIBRATION_MAX), the parameter that repeats the kernel (repeat_param of the program's local_vars, else
        "repeat" when its run_time_env takes {{local.params.repeat}} - CK's CT_REPEAT_MAIN) and the repeat to start
        from (the --repeat given, else 1). A program that does not repeat its kernel is refused.
        """
        asked = params.get('calibrate')
        if asked in (None, False) or str(asked).strip().lower() in ('', 'no', 'false', 'off', 'none', '0'):
            return {'return': 0, 'plan': None}
        if asked is True or str(asked).strip().lower() in ('yes', 'true', 'on', 'auto'):
            target = CALIBRATION_TIME
        else:
            try:
                target = float(asked)
            except (TypeError, ValueError):
                target = 0
            if target <= 0:
                return self.cm.error(f'--calibrate takes the seconds a run should last (--calibrate=10), or nothing for {CALIBRATION_TIME:g} as CK did: "{asked}"')
        try:
            max_rounds = int(params.get('calibrate_max') or CALIBRATION_MAX)
        except (TypeError, ValueError):
            max_rounds = 0
        if max_rounds < 1:
            return self.cm.error(f'--calibrate_max takes a number of rounds: "{params.get("calibrate_max")}"')

        param = str(local.get('repeat_param') or '').strip()
        if not param:
            envs = [local.get('run_time_env'), ((desc or {}).get('local_vars') or {}).get('run_time_env')]
            if any(isinstance(e, dict) and any('params.repeat' in str(v) for v in e.values()) for e in envs):
                param = 'repeat'
        if not param:
            return self.cm.error('this program does not repeat its kernel (no repeat_param in its local_vars, no {{local.params.repeat}} '
                                 'in its run_time_env): --calibrate has nothing to change')

        start = params.get(param)
        try:
            repeat = int(start) if start not in (None, '') else 1
        except (TypeError, ValueError):
            return self.cm.error(f'--{param} takes a whole number to start the calibration from: "{start}"')
        return {'return': 0, 'plan': {'param': param, 'target': target, 'max': max_rounds, 'repeat': max(1, repeat),
                                      'rounds': 0, 'history': [], 'seconds': None, 'done': False, 'success': None, 'why': ''}}

    ############################################################
    def output_check(self, ctx, params, desc, program_alias, program_uid, result, local, resolved):
        """
        The outputs of this run against the program's reference outputs (category program.output), or recorded as
        the reference: --check_output (auto: compared when a reference exists, recorded when none), =validate (an
        error without a reference), =record (--overwrite_output records over an existing case), =no. --output_repo
        names the repository a recording goes into (local by default, as CK did: a shared repository only when
        asked). Returns the check: status (validated, failed, recorded, no_reference, nothing, error), the case,
        the files with their verdicts.
        """

        mode = params.get('check_output')
        mode = 'auto' if mode in (True, '', 'yes', 'true', 'on', 'auto') else str(mode or 'no').strip().lower()
        if mode in ('no', 'false', 'off', 'none'):
            return None
        if mode not in ('auto', 'validate', 'record'):
            return {'status': 'error', 'error': f'--check_output takes auto, validate, record or no: "{mode}"'}

        cmd = params.get('cmd')
        if isinstance(cmd, list):
            cmd = ','.join(str(c) for c in cmd)
        cmd = cmd or 'default'

        rules = output_check_rules(desc, cmd)
        api_code = (local.get('selected-program') or {}).get('api_code')
        if hasattr(api_code, 'customize_output_check') and callable(getattr(api_code, 'customize_output_check')):
            r = api_code.customize_output_check(ctx, rules)
            if isinstance(r, dict) and r.get('return', 0) > 0:
                return {'status': 'error', 'error': f'the program\'s output_check hook failed: {r.get("error")}'}

        alias = str(rules.get('artifact') or program_alias)          # the program whose references these are
        key = output_key(rules, alias, cmd, local, params)
        files = output_files_of(rules, local)
        work_path = local.get('work_path') or local.get('target_path') or os.getcwd()
        out = {'status': 'nothing', 'mode': mode, 'artifact': alias, 'key': key, 'files': {}}
        if not files:
            out['note'] = 'no output file to check (output_files of the program, or output_check.files)'
            return out

        # The lines left out of every comparison (output_check.ignore_lines)
        ignore, why = ignore_patterns(rules)
        if why:
            return {'status': 'error', 'error': why}

        # The reference: the first case of this key in the artifacts of that name, in any repository
        r = self.cm.access({'category': OUTPUT_CATEGORY, 'command': 'find', 'arg1': alias, 'con': False})
        paths = [a['path'] for a in r.get('artifacts', [])] if r.get('return', 1) == 0 else []
        found = find_case(paths, key)

        if found and mode == 'record' and not params.get('overwrite_output'):
            return {'status': 'error', 'error': f'a reference of this case exists ({found["folder"]}): --overwrite_output records over it, '
                                                '--check_output compares with it', 'case': found['folder']}

        if found and mode != 'record':
            tolerance = rules.get('tolerance')
            ok = True
            records = found['case'].setdefault('files', {})
            changed = False
            for name in files:
                record = records.get(name)
                run_file = os.path.join(work_path, name)
                if not record:
                    # The reference has no such file (the program's outputs grew): added to it, as CK did
                    if os.path.isfile(run_file):
                        d = output_digests(run_file, ignore)
                        d['kept'] = d['size'] <= OUTPUT_KEPT_MAX
                        if d['kept']:
                            shutil.copyfile(run_file, os.path.join(found['folder'], name))
                        records[name] = d
                        changed = True
                        out['files'][name] = {'status': 'added', 'why': 'the reference had no such file: added to it'}
                    else:
                        # Neither the reference nor the run made it: the same
                        out['files'][name] = {'status': 'ok', 'why': 'not made, as in the reference'}
                    continue
                status, why = compare_output(run_file, record, os.path.join(found['folder'], name) if record.get('kept') else None,
                                             tolerance, ignore, rules.get('tolerance_abs'))
                out['files'][name] = {'status': status, 'why': why}
                ok = ok and status == 'ok'
            if changed:
                with open(os.path.join(found['folder'], OUTPUT_CASE), 'w', encoding = 'utf-8', newline = '\n') as f:
                    json.dump(found['case'], f, indent = 1, sort_keys = True)
                    f.write('\n')
            out.update({'status': 'validated' if ok else 'failed', 'case': found['folder'], 'recorded': found['case'].get('recorded')})
            return out

        if mode == 'validate':
            out['status'] = 'no_reference'
            out['note'] = f'no reference of this case in {OUTPUT_CATEGORY}::{alias}: record one with --check_output (or =record)'
            return out

        # A recording: the artifact of the program in --output_repo (made when it is not there), a new case in it
        repo = str(params.get('output_repo') or 'local')
        r = self.cm.access({'category': 'repo', 'command': 'find', 'arg1': repo, 'con': False})
        repo_paths = [a['path'] for a in r.get('artifacts', [])] if r.get('return', 1) == 0 else []
        if not repo_paths:
            return {'status': 'error', 'error': f'no repository "{repo}" to record the reference into (--output_repo)'}
        repo_root = os.path.normcase(os.path.abspath(repo_paths[0]))

        def inside(p):
            return os.path.normcase(os.path.abspath(p)).startswith(repo_root + os.sep)

        # The artifact of this program in the output repository; (re)made when it is not there or lost its identity
        # file (a folder left without _cmeta.yaml, so no machine can find it - an artifact of a manual deletion or
        # a stale index): "add" writes _cmeta.yaml even when the folder already holds cases
        target = next((p for p in paths if inside(p)), None)
        if not target or not os.path.isfile(os.path.join(target, '_cmeta.yaml')):
            tags = ['program.output'] + [str(t) for t in ((local.get('selected-program') or {}).get('artifact') or {}).get('cmeta', {}).get('tags', []) if str(t) not in ('program.output',)]
            r = self.cm.access({'category': OUTPUT_CATEGORY, 'command': 'add', 'arg1': f'{repo}:{alias}', 'yaml': True,
                                'tags': ','.join(tags), 'quiet': True, 'con': False})
            if r.get('return', 1) > 0:
                return {'status': 'error', 'error': f'the artifact {OUTPUT_CATEGORY}::{alias} could not be made in {repo}: {r.get("error")}'}
            r = self.cm.access({'category': OUTPUT_CATEGORY, 'command': 'find', 'arg1': alias, 'con': False})
            target = next((a['path'] for a in r.get('artifacts', []) if inside(a['path'])), None) if r.get('return', 1) == 0 else None
            if not target:
                return {'status': 'error', 'error': f'the artifact {OUTPUT_CATEGORY}::{alias} was made but not found in {repo}'}
            # What the artifact is: the program it holds the references of
            meta_path = os.path.join(target, '_cmeta.yaml')
            rm = self.cm.utils.files.read_file(meta_path)
            if rm.get('return', 1) == 0 and isinstance(rm.get('data'), dict):
                meta = rm['data']
                meta.pop('copyright', None)
                meta['program'] = f'{program_alias},{program_uid}'
                meta['desc'] = f'The reference outputs of the program {program_alias}: a case per command, input and parameters (case.json), recorded by cx program run --check_output.'
                self.cm.utils.files.safe_write_file(meta_path, meta)

        if found:                                    # --check_output=record --overwrite_output
            shutil.rmtree(found['folder'], ignore_errors = True)

        s = run_summary_of(local, ctx['tasks'].get('global'), params, result, resolved)
        facts = recorded_facts(s, program_alias, program_uid)
        uid = self.cm.utils.names.generate_cmeta_uid()
        folder = os.path.join(target, uid)
        case = write_case(folder, key, facts, files, work_path, ignore = ignore, ignore_lines = rules.get('ignore_lines'))
        out['files'] = {n: ({'status': 'recorded', 'why': f'{v["size"]} bytes' + ('' if v.get('kept') else ', the digests alone (too big to keep)')} if v else
                            {'status': 'missing', 'why': 'the run made no such file'}) for n, v in case['files'].items()}
        out.update({'status': 'recorded', 'case': folder, 'repo': repo, 'recorded': facts})
        return out

    ############################################################
    def run_summary(self, ctx, params, result, error = None, built_now = None, run_skipped = False, local = None):
        """
        The summary of this run, with what the program's hooks add (customize_summary); printed when asked.
        local: the run's local context when the context no longer holds it (a step that failed leaves its own).
        """

        con = ctx['control'].get('con', False)
        ctx_tasks = ctx['tasks']
        if isinstance(local, dict):
            ctx_tasks['local'] = local
        local = ctx_tasks.get('local') or {}

        try:
            resolved = provenance.collect_resolved(ctx_tasks.get('global') or {})
        except Exception as e:                           # the summary never spoils a run
            resolved = {}

        summary = run_summary_of(local, ctx_tasks.get('global'), params, result, resolved,
                                 error = error, built_now = built_now, run_skipped = run_skipped)

        api_code = (local.get('selected-program') or {}).get('api_code')
        if hasattr(api_code, 'customize_summary') and callable(getattr(api_code, 'customize_summary')):
            try:
                r = api_code.customize_summary(ctx, summary)
                if isinstance(r, dict) and r.get('return', 0) > 0 and con:
                    print (f'cMeta warning: the program\'s summary hook failed: {r.get("error")}')
            except Exception as e:
                if con:
                    print (f'cMeta warning: the program\'s summary hook failed: {type(e).__name__}: {e}')

        wanted = params.get('summary')
        if con and (wanted is None or provenance.is_true(wanted)):
            print ('')
            for line in summary_block(summary):
                print (line)
            print ('')

        return summary



    ############################################################
    def common_sizes(self):
        """
        The size rules and the disk measures of the tool category (category/tool/api/common_sizes.py),
        shared with task/setup. Its package, tool_<uid>.api, exists once the engine has loaded the tool
        category in this process (any tool setup does that); before that, the module is loaded from
        the category's folder, found through uses_categories. None when the category is not plugged.
        """
        try:
            from tool_c393ba5c6fa14f66.api import common_sizes
            return common_sizes
        except ImportError:
            pass
        category = self.cmeta.get('uses_categories', {}).get('tool', 'tool,c393ba5c6fa14f66')
        r = self.cm.access({'category': 'category', 'command': 'find', 'arg1': category})
        artifacts = r.get('artifacts') if r.get('return', 1) == 0 else None
        if not artifacts:
            return None
        path = os.path.join(artifacts[0]['path'], 'api', 'common_sizes.py')
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location('cmeta_aops_common_sizes', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    ############################################################
    def build_facts(self,
                    ctx: dict,
                    params: dict,
                    compute: list,
                    compiler_key: str = None,
                    compiler_from: dict = None,
    ):
        """
        What a build is made for, as the stamp of the build folder records it: the targets, the host,
        the compiler (from the global context under compiler_key, when resolved), the compile
        parameters that change the output, the Android or iOS device.
        """
        _global = ctx['tasks']['global']
        compiler = None
        if compiler_key:
            compiler = build_stamp.compiler_identity((compiler_from or _global).get(compiler_key))
        android_target = _global.get('target--android-cpu') or {}
        android = {'serial': android_target.get('serial'),
                   'abi': (android_target.get('features') or {}).get('ro.product.cpu.abi')} if android_target else None
        ios_target = _global.get('target--ios-cpu') or {}
        ios = {'udid': ios_target.get('udid')} if ios_target else None
        return {'compute': list(compute or []), 'host': _global['host']['os']['uname'], 'compiler': compiler,
                'compile_params': params.get('compile') or {}, 'android': android, 'ios': ios}

    ############################################################
    def requested_compiler(self,
                           ctx: dict,
                           compiler_key: str,
    ):
        """The compiler a run asks for through --use (--use.compiler-c.name=gcc), as the stamp records
        one, or None: on a reused build the compiler is not resolved, only what the user asked."""
        use = ctx['tasks'].get('use') or {}
        asked = use.get(compiler_key) or use.get('compiler') or {}
        identity = {'name': asked.get('name'), 'version': asked.get('version')}
        return identity if any(identity.values()) else None

    ############################################################
    def refuse_stale_build(self,
                           ctx: dict,
                           target_path: str,
                           facts: dict,
    ):
        """
        The guard of the build folder: when its stamp differs from this run (targets, host, compiler,
        compile parameters, Android device), the folder is neither reused nor rebuilt in place. A
        folder configured for one target or compiler was silently reused for another before: on
        macOS a host build of llama.cpp was pushed to an Android device, since CMake kept its cache.
        --recompile (explicit) and --clean (the folder is wiped first) go on. Returns the error, or
        {'return': 0, 'stamp': <the stamp or None>}.
        """
        stamp = build_stamp.read_stamp(target_path)
        if not stamp:
            return {'return': 0, 'stamp': None}
        diffs = build_stamp.differences(stamp, **facts)
        if diffs:
            return self.cm.error(build_stamp.refusal_message(target_path, stamp, diffs))
        return {'return': 0, 'stamp': stamp}

    ############################################################
    def write_build_stamp(self,
                          ctx: dict,
                          target_path: str,
                          artifact_alias: str,
                          artifact_uid: str,
                          facts: dict,
    ):
        """Records what the build in the folder is made for (after a compile, or for a folder made
        before the stamps existed), with the digests of the sources it was built from; a folder that
        cannot be written is left alone."""
        stamp = build_stamp.make_stamp(artifact_alias, artifact_uid, facts['compute'], facts['host'],
                                       compiler = facts.get('compiler'), compile_params = facts.get('compile_params'),
                                       android = facts.get('android'), sources = self.source_digests(ctx),
                                       ios = facts.get('ios'))
        error = build_stamp.write_stamp(target_path, stamp)
        if error and ctx['control'].get('con', False) and ctx['control'].get('verbose', False):
            print (f'WARNING: the build stamp of "{target_path}" was not written: {error}')
        return stamp

    ############################################################
    def source_digests(self,
                       ctx: dict,
    ):
        """The digests of the program's sources (the declared files and the code under its source
        folder), as the stamp records them and as a reused build is checked against: a changed source
        recompiles (since 0.43.3 - before, an edited program silently ran its old binary)."""
        local = ctx['tasks']['local']
        return build_stamp.source_digests(local.get('src_path'), local.get('src_file_names_list'))

    ############################################################
    def check_program_disk_space(self,
                                 ctx: dict,
                                 params: dict,
                                 program_path: str,
                                 program_name: str,
                                 target_path: str,
                                 compute: list,
    ):
        """
        Before the compile phase: the rule of the program's _desc_sizes.yaml for this run (OS, CPU,
        method build, the targets, the compile parameters as "with", --version) gives the space the
        build needs (peak); the configured minimum of free space (cx config set task
        --meta.min_free_gb=<GB>) applies to every program. The folder checked is the build folder's
        volume (target_path). Below that: a quiet run stops before compiling, else a warning and the
        question whether to go on. --skip_size_check skips it. No file and no minimum: no check.
        """
        if params.get('skip_size_check', False):
            return {'return': 0}

        sizes = self.common_sizes()
        if sizes is None:
            return {'return': 0}

        ctx_tasks = ctx['tasks']
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx_tasks.get('nested_call', 0) if verbose else ''

        rules = sizes.load_sizes(program_path)

        floor = ctx_tasks.get('global', {}).get('init', {}).get('min_free_gb')
        try:
            floor = float(floor) if floor not in (None, '', False) else None
        except (TypeError, ValueError):
            return self.cm.error(f'the configured minimum of free space "min_free_gb" is not a number: {floor}')

        if not rules and floor is None:
            return {'return': 0}

        host = ctx_tasks['global']['host']['os']
        compile_params = build_stamp.normalize_compile(params.get('compile'))
        facts = sizes.request_facts(version = params.get('version') or None, os_name = host['uname'],
                                    arch = host.get('uarch'), method = 'build', compute = list(compute or []),
                                    with_ = compile_params or None)
        rule = sizes.select_rule(rules, facts, self.cm.utils.common.matches_query,
                                 match_version_func = self.cm.repos.match_version_func)
        needed = rule.get('peak') if rule else None

        ok, free, required = sizes.check_space(needed, target_path, floor_gb = floor)
        if ok:
            if verbose and con and required is not None:
                print (f'{space}INFO: disk space for the build: {free:.1f} GB free in {target_path}, about {required:g} GB needed')
            return {'return': 0}

        rule_based = needed is not None and needed >= (floor or 0)
        what = f'{program_name} (build, {host["uname"]}' + (f', {",".join(compute)}' if compute else '') + ')'
        need = (f'needs about {required:g} GB during the build' if rule_based
                else f'needs at least {required:g} GB free (the configured minimum)')
        message = (f'{what} {need}; {free:.1f} GB are free in {target_path}. Free space, give '
                   f'--target_tmp=<name> or --target_path=<folder on another disk>, or --skip_size_check.')

        if quiet or not con:
            return self.cm.error(message)

        print ('')
        print (f'{space}WARNING: {message}')
        from task_c36be4b9314a45e0.api.ctask import ask as ask_user
        r = ask_user(f'{space}Continue anyway (y/N)? ', how = '--skip_size_check to go on without this check')
        if r['return'] > 0: return r
        x = r['answer'].strip().lower()
        if x not in ['y', 'yes']:
            return self.cm.error(f'build of "{program_name}" cancelled: not enough disk space')

        return {'return': 0}

    ############################################################
    def write_provenance(self,
                         ctx: dict,
                         params: dict,
                         mode: str,
                         request_params: dict,
                         request_use: dict,
                         target_path: str,
                         target_tmp: str,
                         artifact_alias: str,
                         artifact_uid: str,
                         compute: list,
                         run_skipped: bool = False,
    ):
        """
        After a run: provenance.json in the build folder (category/task/api/provenance.py) - the
        request, the resolved tools, the binary's dependencies (or what the loader logged with
        --provenance=loaded), the checks. Returns {'return': 0, 'provenance': {path, ok, errors,
        warnings}}; a problem building or writing the record is a WARNING and leaves the run's
        result as it is; with mode `strict`, a failed error-level check fails the run (99).
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        try:
            static_effective = provenance.is_true((params.get('compile') or {}).get('static'))
            entry = ctx['tasks']['local'].get('build_entry')
            record = provenance.build_record(
                mode, {'alias': artifact_alias, 'uid': artifact_uid}, target_tmp, target_path, compute,
                ctx['tasks']['global'], ctx['tasks']['local'], request_params, request_use, static_effective,
                result_data = ctx['tasks']['local'].get('result_files_data'),
                match_version = lambda spec, version: self.cm.packages.match_version(spec, version).get('matched'),
                run_skipped = run_skipped, entry = entry)
            error = provenance.write_record(target_path, record)
            if error:
                raise OSError(error)
        except Exception as e:
            if con:
                print ('')
                print (f'{space}WARNING: provenance record not written: {e}')
            return {'return': 0, 'provenance': {'path': None, 'ok': None, 'error': str(e)}}

        summary = provenance.summary(record)
        summary['path'] = os.path.join(target_path, provenance.RECORD_FILE)

        # The resolved toolchain goes into the build entry's params (cx cache find reads it)
        if entry:
            try:
                r = build_identity.update_entry(self.cm, self.cmeta['uses_categories']['cache'], entry, record.get('resolved'))
                if r['return'] > 0:
                    raise RuntimeError(r.get('error') or f'return code {r["return"]}')
            except Exception as e:
                if con and verbose:
                    print (f'{space}WARNING: the build entry was not updated with the resolved toolchain: {e}')

        failed = provenance.failed_lines(record)
        if con and failed:
            print ('')
            for level, text in failed:
                print (f'{space}PROVENANCE' + (' (warning)' if level == 'warning' else '') + f': {text}')
            if verbose:
                print (f'{space}  (the record: {summary["path"]})')

        # In a test session (CMETA_TEST_SESSION, which "cx task run test-session --start" prints for the
        # shell) the record joins the session's attachments with a note; a problem there is a warning
        session = os.environ.get(provenance.SESSION_ENV, '').strip()
        if session:
            try:
                r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'test-session,33b25e8340de4d8e',
                                    'id': session, 'attach': summary['path'], 'attach_as': provenance.session_attachment_name(record),
                                    'note': provenance.session_note(record), 'con': False, 'quiet': True})
                if r['return'] > 0:
                    raise RuntimeError(r.get('error') or f'return code {r["return"]}')
                summary['session'] = session
            except Exception as e:
                if con:
                    print ('')
                    print (f'{space}WARNING: provenance record not attached to test session {session}: {e}')

        if mode == 'strict' and not record.get('ok', True):
            errors = [text for level, text in failed if level == 'error']
            return self.cm.error(f'PROVENANCE: {len(errors)} check(s) failed: ' + '; '.join(errors), 99)

        return {'return': 0, 'provenance': summary}

    ############################################################
    def run(self,
            ctx: dict,
            **params,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK compile-and-run-program run")

        ###########################################################################################
        # Get program and desc (uses compute as constraints)
        selected_program = ctx['tasks']['local']['selected-program']
        selected_program_api_code = selected_program.get('api_code')

        artifact = selected_program['artifact']
        path = artifact['path']

        cmeta_ref_parts = artifact['cmeta_ref_parts']

        artifact_alias = cmeta_ref_parts.get('artifact_alias')
        artifact_uid = cmeta_ref_parts['artifact_uid']

        desc = copy.deepcopy(selected_program['loaded_files']['_desc'].get('data', {})) # May change during context merge

        program_api_code = selected_program.get('api_code')

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        host = _global['host']
        uname = host['os']['uname']

        ###########################################################################################
        params = copy.deepcopy(params)

        # The request as given, before the program's defaults are merged in: what the provenance
        # record of the run calls "requested" (the program's `use` defaults join ctx use below)
        request_params = copy.deepcopy(params)
        request_use = copy.deepcopy(ctx['tasks'].get('use') or {})

        if 'params' in desc:
            params_desc = copy.deepcopy(desc['params'])
            self.cm.utils.common.deep_merge(params_desc, params, append_lists=False)
            params = params_desc

        params_os = desc.get('params_os')
        if params_os:
            v = None
            if 'all' in params_os:
                v = params_os['all']
            elif uname in params_os:
                v = params_os[uname]
            elif uname != 'windows' and 'linux' in params_os:
                v = params_os['linux']
            if v:
                params_os_desc = copy.deepcopy(v)
                self.cm.utils.common.deep_merge(params_os_desc, params, append_lists=False)
                params = params_os_desc

        r = self.cm.utils.common.expand_strings_in_dict(params, ctx_tasks)
        if self.cm.catch_error(r): return r

        _use = desc.get('use')
        if _use:
            ctx_use = ctx['tasks'].setdefault('use', {})
            self.cm.utils.common.deep_merge(ctx_use, copy.deepcopy(_use), append_lists=True)

        ###########################################################################################
        # Check if customization
        if hasattr(program_api_code, 'customize_pre') and callable(getattr(program_api_code, 'customize_pre')):
            r = program_api_code.customize_pre(ctx, params)
            if self.cm.catch_error(r): return r

        ###########################################################################################
        name = params.get('name')
        program_tags = params.get('program_tags')
        program_api_ver = params.get('program_api_ver')
        skip_compile = params.get('skip_compile')
        recompile = params.get('recompile')
        skip_run = params.get('skip_run')
        target_path = params.get('target_path')
        work_path = params.get('work_path')
        here = params.get('here')
        run = params.get('run')
        env = params.get('env', {})
        unparsed = params.get('unparsed')

        # --provenance=on|off|loaded|strict: the record of the run (category/task/api/provenance.py)
        try:
            provenance_mode = provenance.mode_of(params.get('provenance'))
        except ValueError as e:
            return self.cm.error(str(e))

        ###########################################################################################
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks_control = ctx['tasks']['run_control']
        clean = ctx_tasks_control.get('clean', False)

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        ###########################################################################################
        # Init vars
        local_vars = desc.get('local_vars')
        if local_vars:
#            r = self.cm.utils.common.expand_strings_in_dict(local_vars, ctx_tasks)
#            if self.cm.catch_error(r): return r

            self.cm.utils.common.deep_merge(ctx['tasks']['local'], local_vars, append_lists=False)

        selected_compute = _global.get('target',{}).get('compute', [])

        ###########################################################################################
        # The folder of the build and the run under the program's cache entry (or the current
        # directory for programs that run in '{pwd}'): --target_tmp, else the configured default,
        # else tmp. "auto" gives every set of targets its own folder (tmp-cuda, tmp-cpu-cuda),
        # so builds for different targets stay side by side for comparisons on one machine.
        r = self.cm.access({
          'category':self.cmeta['uses_categories']['config'],
          'command':'get',
          'arg1':'task',
        })
        if self.cm.catch_error(r): return r

        cfg = r['config_cmeta']

        target_tmp = params.get('target_tmp') or cfg.get('compile_and_run_program', {}).get('target_tmp') or 'tmp'
        if target_tmp == 'auto':
            # The target task has not run yet: the targets as given (the template's default is cpu)
            requested = params.get('compute') or 'cpu'
            if isinstance(requested, str):
                requested = requested.split(',')
            requested = [str(c).strip().lower() for c in requested if str(c).strip()] if isinstance(requested, list) else []
            target_tmp = 'tmp-' + '-'.join(requested) if requested else 'tmp'

        if not target_path:
            target_path = ctx_tasks['local'].get('target_path')
            if not target_path:
                x = target_tmp

                skip_cache = cfg.get('compile_and_run_program',{}).get('skip_cache', False)

                if skip_cache:
                    target_path = os.path.join(path, x)
                else:
                    # The build entry of this request (category/task/api/build_identity.py): the explicit
                    # choices of the request and the resolved targets name it, so two requests that
                    # differ build side by side and the same request comes back to its own entry
                    identity = build_identity.request_identity(request_params, request_use, selected_compute)
                    r = build_identity.find_or_create_entry(self.cm, self.cmeta['uses_categories']['cache'],
                                                            artifact_alias, artifact_uid, identity)
                    if self.cm.catch_error(r): return r

                    ctx_tasks['local']['build_entry'] = {'path': r['path'], 'alias': r['alias'], 'uid': r['uid'],
                                                         'request': identity, 'request_digest': build_identity.digest(identity)}
                    if con and verbose and (r.get('created') or r.get('adopted')):
                        what = 'New build entry' if r.get('created') else 'Build entry adopted'
                        print (f'{space}{what} for this request ({build_identity.describe(identity)}): {r["path"]}')

                    target_path = os.path.join(r['path'], x)

        target_path = target_path.replace('//', os.sep)

        ctx_tasks['local']['target_path'] = target_path

        if here:
            work_path = os.getcwd()

        if not work_path:
            work_path = ctx_tasks['local'].get('work_path')
            if not work_path:
                work_path = target_path

        if work_path.strip().lower() == '{pwd}':
            work_path = cur_dir

            work_path = os.path.join(work_path, target_tmp)

            work_path = work_path.replace('//', os.sep)

        ctx_tasks['local']['work_path'] = work_path

        os.makedirs(work_path, exist_ok=True)

        ###########################################################################################
        if 'run_time_env' not in ctx_tasks['local']:
            ctx_tasks['local']['run_time_env'] = env 
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['run_time_env'], env, append_lists=True)

        if 'params' not in ctx_tasks['local']:
            ctx_tasks['local']['params'] = params
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['params'], params, append_lists=True)

        ###########################################################################################
        # Extra possible update dependig on run cmd
        


#        ###########################################################################################
#        # Check if customization
#        if hasattr(program_api_code, 'customize') and callable(getattr(program_api_code, 'customize')):
#            r = program_api_code.customize(ctx, params)
#            if self.cm.catch_error(r): return r

        ###########################################################################################
        # Prepare some paths

        path_repro_all = os.path.join(target_path, '_repro_ctx_all.json')
        path_repro_compile = os.path.join(target_path, '_repro_ctx_compile.json')
        path_repro_run = os.path.join(target_path, '_repro_ctx_run.json')

        ###########################################################################################
        # Check if target is supported - it's already checked via cmeta.constraints.supported_compute
        # when selecting program
#        supported_compute = artifact['cmeta'].get('constraints', {}).get('supported_compute')

        ###########################################################################################
        # Clean (restart) (clean flag is used by "task" category)

        if clean and os.path.isdir(target_path):
            if con and verbose:
                print ('')
                print (f'{space}CLEANING ...')

            shutil.rmtree(target_path)

        if not os.path.isdir(target_path):
            os.makedirs(target_path)

        ###########################################################################################
        # All
        all_desc = desc.get('all', {})
        all_uses = all_desc.get('uses', {})

        if all_uses:
            if con and verbose:
                print ('')
                print (f'{space}PREPARING ...')

            p = {'category': self.category_alias + ',' + self.category_uid,
                 'command': 'use',
                 'con': con,
                 'quiet': quiet,
                 'verbose': verbose,
                 'ctx': ctx,
                 'desc': all_uses,
                 'local': ctx['tasks']['local'], # Reuse local from this task (selected-program)
                 'task_artifact_alias': self.artifact_alias,
                 'task_artifact_uid': self.artifact_uid,
                 'task_artifact_path': self.artifact_path,
                 'self_desc': desc,
                 'uparams': params,
                }

            r = self.cm.access(p)

            rx = self.cm.utils.files.write_file(path_repro_all, {'ctx':ctx, 'result':r}, safe_dump = True)
            if self.cm.catch_error(rx): return rx

            if self.cm.catch_error(r): return r


#        ###########################################################################################
#        # Prepare src path
#        # Check if customization2 after uses_pre (compute, etc)
#        if hasattr(program_api_code, 'customize1') and callable(getattr(program_api_code, 'customize1')):
#            r = program_api_code.customize1(ctx, params=params, desc=desc)
#            if self.cm.catch_error(r): return r

        src_path = params.get('src_path')
        if not src_path:
            src_dir = ctx['tasks']['local'].get('src_dir')
            if src_dir:
                src_path = os.path.join(path, src_dir)
            else:
                src_path = path

        ctx['tasks']['local']['src_path'] = src_path

        # Duplicated in setup-run if we need to update names without compilation
        # (such as python)
        src_file_names = local_vars.get('src_file_names')
        if src_file_names:
            src_file_names_str = ''
            src_file_names_str_with_path = ''
            for sfn in src_file_names:
                sfn = sfn.replace('//', os.sep)

                if src_file_names_str != '':
                    src_file_names_str += ' '
                src_file_names_str += sfn

                # quoted when it holds a space (a home under "C:\Users\First Last"): the joined list goes into a command line
                sfnp = self.cm.utils.files.quote_path(os.path.join(src_path, sfn))
                if src_file_names_str_with_path != '':
                    src_file_names_str_with_path += ' '
                src_file_names_str_with_path += sfnp

            ctx['tasks']['local']['src_file_names_str'] = src_file_names_str
            ctx['tasks']['local']['src_file_names_str_with_path'] = src_file_names_str_with_path
            ctx['tasks']['local']['src_file_names_list'] = list(src_file_names)

        ###########################################################################################
        # The target task of the 'all' pipeline has resolved the targets only now: read before
        # (above), selected_compute was empty, so a change of --compute never triggered a
        # recompile, and the cached context of the other target (its build, its run flags) was
        # reused - a --compute=metal run after a --compute=cpu build ran on the CPU
        selected_compute = ctx_tasks['global'].get('target', {}).get('compute', []) or selected_compute

        ###########################################################################################
        # Compile

        compile_desc = desc.get('compile', {})

        _compiled_state = {}
        _compile_params = None

        compile_target_compute = None

        ctx_setup_compile = None

        build_disk_gb = None

        if not recompile:
            r = self.cm.utils.files.read_file(path_repro_compile)
            if r['return']>0:
                recompile = True
            else:
                _compiled_state = r['data']

                if _compiled_state.get('result', {}).get('return') != 0:
                    recompile = True

                _compiled_state_global = _compiled_state.get('ctx', {}).get('tasks', {}).get('global')
                _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local')

                if _compiled_state_global:
                    compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])

                if _compiled_state_local:
                    ctx_setup_compile = _compiled_state_local.get('setup-compile')

        built_now = False                        # for the summary: compiled in this run, or reused

        if not compile_desc.get('skip', False) and not skip_compile:
            if con and verbose:
                print ('')
                print (f'{space}COMPILING ...')

            # another run of this program in the same cache entry (two pods of a job on one node share its home)
            # may remove it between a check and the removal: a file already gone is fine (2026-11-23)
            try:
                os.remove(path_repro_run)
            except FileNotFoundError:
                pass

            _compiled = False

            if not recompile:
                # Check if compute didn't change (in either direction: cpu,cuda -> cuda changes the
                # build as much as cuda -> cpu,cuda):
                if _compiled_state_global:
                    compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])
                    if compile_target_compute and set(selected_compute) != set(compile_target_compute):
                        recompile = True

                    if not recompile and any(c in ('android-cpu', 'android-gpu', 'android-npu') for c in compile_target_compute):
                        compile_target_adb_serial = _compiled_state_global.get('target--android-cpu',{}).get('serial')
                        target_adb_serial = ctx_tasks['global'].get('target--android-cpu',{}).get('serial')
                        if compile_target_adb_serial != target_adb_serial:
                            recompile = True

                    if not recompile and 'ios-cpu' in compile_target_compute:
                        if _compiled_state_global.get('target--ios-cpu',{}).get('udid') != ctx_tasks['global'].get('target--ios-cpu',{}).get('udid'):
                            recompile = True

                    if not recompile:
                        compile_uname = _compiled_state_global['host']['os']['uname']

                        # Can happen in Docker or WSL with shared host disk
                        if compile_uname != uname:
                            recompile = True

                    if not recompile:
                        target_path_exe = _compiled_state_local.get('target_path_exe')
                        if target_path_exe and not os.path.isfile(target_path_exe):
                            recompile = True

                    # The stamp of the build folder: a build for other targets, another compiler
                    # (asked for with --use) or other compile parameters is not reused
                    if not recompile:
                        _compiler_key = (_compiled_state_local or {}).get('global_compiler_key')
                        _facts = self.build_facts(ctx, params, selected_compute)
                        _facts['compiler'] = self.requested_compiler(ctx, _compiler_key) if _compiler_key else None
                        r = self.refuse_stale_build(ctx, target_path, _facts)
                        if self.cm.catch_error(r): return r
                        if r['stamp'] is None and _compiled_state_global:
                            # A folder made before the stamps, which this run reuses: stamped with this
                            # run's targets and compile parameters (the saved origin parameters lack the
                            # program's defaults) and the compiler the saved state resolved
                            _facts['compiler'] = build_stamp.compiler_identity(_compiled_state_global.get(_compiler_key)) if _compiler_key else None
                            self.write_build_stamp(ctx, target_path, artifact_alias, artifact_uid, _facts)
                        elif r['stamp'] is not None:
                            # The sources the build was made from: an edited program is rebuilt, not run
                            # as it was (a stamp without digests, from before 0.43.3, compares nothing)
                            changed = build_stamp.sources_changed(r['stamp'], self.source_digests(ctx))
                            if changed:
                                recompile = True
                                if con:
                                    shown = ', '.join(changed[:5]) + (f', +{len(changed) - 5} more' if len(changed) > 5 else '')
                                    print ('')
                                    print (f'{space}INFO: the program\'s sources changed since this build ({shown}): recompiling')

                if not recompile:
                    if _compiled_state_global:
                        if con and verbose:
                            print ('')
                            print (f'{space}REUSING EXISTING GLOBAL COMPILE CONTEXT ...')

                        self.cm.utils.common.deep_merge(ctx['tasks']['global'], _compiled_state_global, append_lists=False)

                        # The snapshot holds every tool's features of the compile day; an entry re-detected
                        # since ("cx tool setup <tool> --update": a model added to lib-litert-android) may
                        # carry keys the snapshot lacks - completed from the entry's current result, while
                        # what the snapshot has keeps its value (the record of what the build used)
                        _completed = build_identity.complete_restored_tools(ctx['tasks']['global'])
                        if _completed and con and verbose:
                            print (f'{space}INFO: tool features completed from the current cache entries: ' +
                                   ', '.join(f'{k} ({", ".join(v)})' for k, v in _completed.items()))

                    _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local')
                    if _compiled_state_local:
                        if con and verbose:
                            print (f'{space}REUSING EXISTING LOCAL COMPILE CONTEXT ...')

                        # The cached local carries the parameters of the request that made the build - its
                        # --check_output, --repeat, --calibrate ... - which are not this run's: the live parameters
                        # stay, with the compile parameters of the build (its defines and flags as customized)
                        # over their compile section alone
                        _live_params = copy.deepcopy(ctx['tasks']['local'].get('params') or {})
                        _built_compile = copy.deepcopy((_compiled_state_local.get('params') or {}).get('compile') or {})

                        self.cm.utils.common.deep_merge(ctx['tasks']['local'], _compiled_state_local, append_lists=False)

                        _local_params = ctx['tasks']['local'].get('params')
                        if isinstance(_local_params, dict):
                            _local_params.clear()
                            _local_params.update(_live_params)
                            if _built_compile:
                                if not isinstance(_local_params.get('compile'), dict):
                                    _local_params['compile'] = {}
                                self.cm.utils.common.deep_merge(_local_params['compile'], _built_compile, append_lists=False)
                            if _local_params is not params:
                                for k in list(params):
                                    if k not in _local_params:
                                        del params[k]
                                params.update({k: v for k, v in _local_params.items()})

                        # However, take original selected-program from the beginning of this task
                        # since it has initialized code that is not serializable!
                        ctx['tasks']['local']['selected-program']['api_code'] = selected_program_api_code

                    _compiled_state_aggregated = _compiled_state.get('ctx', {}).get('tasks', {}).get('aggregated')
                    if _compiled_state_aggregated:
                        if con and verbose:
                            print (f'{space}REUSING EXISTING AGGREGATED COMPILE CONTEXT ...')

                        self.cm.utils.common.deep_merge(ctx['tasks']['aggregated'], _compiled_state_aggregated, append_lists=False)

                    _compile_params = _compiled_state.get('ctx', {}).get('origin', {}).get('params', {}).get('compile', {})
                    if _compile_params:
                        if con and verbose:
                            print (f'{space}REUSING EXISTING COMPILE PARAMS ...')

                        self.cm.utils.common.deep_merge(ctx['origin']['params'], {'compile':_compile_params}, append_lists=True)
                        self.cm.utils.common.deep_merge(ctx['tasks']['params'], {'compile':_compile_params}, append_lists=False)

                    if _compiled_state.get('result', {}).get('return') == 0:
                        _compiled = True
                        build_disk_gb = _compiled_state.get('result', {}).get('_impact', {}).get('disk_gb')

            if recompile or not _compiled:
                if os.path.isfile(path_repro_compile):
                    os.remove(path_repro_compile)

                ###########################################################################################
                compile_uses = compile_desc.get('uses')
                if compile_uses:
                    built_now = True
                    self_time_compile_with_cmeta = time.monotonic()

                    # The stamp of the build folder: a rebuild that this run implies (the targets
                    # changed, the binary is gone) does not go into a folder built for other targets,
                    # another compiler or other compile parameters; an explicit --recompile does
                    if not params.get('recompile'):
                        r = self.refuse_stale_build(ctx, target_path, self.build_facts(ctx, params, selected_compute))
                        if self.cm.catch_error(r): return r

                    # The compile parameters as this run requested them, kept for the stamp: a program's hooks
                    # may adjust them on the way (static libraries on an iPhone), and the next run compares its
                    # request with the stamp before those hooks run
                    _requested_compile = copy.deepcopy(params.get('compile') or {})

                    # The free space of the build folder's volume against the program's _desc_sizes.yaml
                    r = self.check_program_disk_space(ctx, params, path, artifact_alias or artifact_uid, target_path, selected_compute)
                    if self.cm.catch_error(r): return r

                    # For setup-compile, which resolves the compiler inside the pipeline: the folder to
                    # compare the compiler with, and whether a rebuild was asked for (--recompile).
                    # A stack, as a lib built on the way runs its own compile-and-run-program
                    ctx['tasks'].setdefault('build_stamps', []).append({'target_path': target_path, 'rebuild': bool(params.get('recompile'))})

                    # --compile_timeout: a deadline for the whole compile phase, the builds that tools
                    # run inside it included (task/cmd caps every command by the time left); closed
                    # before the state is saved, so it never reaches the repro file or the run phase
                    compile_deadline = deadlines.open_deadline(ctx, 'compile', params.get('compile_timeout'), '--compile_timeout')

                    p = {'category': self.category_alias + ',' + self.category_uid,
                         'command': 'use',
                         'con': con,
                         'quiet': quiet,
                         'verbose': verbose,
                         'ctx': ctx,
                         'desc': compile_uses,
                         'local': ctx['tasks']['local'], # Reuse local from this task (selected-program)
                         'task_artifact_alias': self.artifact_alias,
                         'task_artifact_uid': self.artifact_uid,
                         'task_artifact_path': self.artifact_path,
                         'self_desc': desc,
                         'uparams': params,
                        }

#                    if _compile_params:
#                        p['uparams'] = {'compile':_compile_params}

                    try:
                        r = self.cm.access(p)
                    finally:
                        deadlines.close_deadline(ctx, compile_deadline)
                        if ctx['tasks'].get('build_stamps'):
                            ctx['tasks']['build_stamps'].pop()
                            if not ctx['tasks']['build_stamps']:
                                del ctx['tasks']['build_stamps']

                    _impact = r.setdefault('_impact', {})
                    _impact['self_time_compile'] = ctx['tasks']['local'].get('compile-program', {}).get('_impact',{}).get('self_time')
                    _impact['self_time_compile_with_cmeta'] = time.monotonic() - self_time_compile_with_cmeta

                    sizes = self.common_sizes() if r.get('return') == 0 else None
                    if sizes is not None:
                        # What the build took on disk, for the rules of _desc_sizes.yaml
                        _impact['disk_gb'] = round(sizes.folder_gb(target_path), 6)
                        _impact['disk_os'] = uname
                        _impact['disk_arch'] = host['os'].get('uarch')
                        _impact['disk_compute'] = list(selected_compute or [])
                        build_disk_gb = _impact['disk_gb']

                    rx = self.cm.utils.files.write_file(path_repro_compile, {'ctx':ctx, 'result':r}, safe_dump = True)
                    if self.cm.catch_error(rx): return rx

                    if self.cm.catch_error(r): return r

                    # The stamp: what this folder's build is made for (the compiler is resolved now)
                    _compiler_key = ctx['tasks']['local'].get('global_compiler_key')
                    _facts = self.build_facts(ctx, params, selected_compute, compiler_key = _compiler_key)
                    _facts['compile_params'] = _requested_compile
                    self.write_build_stamp(ctx, target_path, artifact_alias, artifact_uid, _facts)

#                ###########################################################################################
#                # Check if customization2 after uses_pre (compute, etc)
#                if hasattr(program_api_code, 'customize2') and callable(getattr(program_api_code, 'customize2')):
#                    r = program_api_code.customize2(ctx, params)
#                    if self.cm.catch_error(r): return r

                ctx_setup_compile = ctx['tasks']['local'].get('setup-compile')

                # Check target program
                target_path_exe = ctx['tasks']['local'].get('target_path_exe')
                if target_path_exe and not os.path.isfile(target_path_exe):
                    return self.cm.error(f'Target file "{target_path_exe}" was not created in "{__file__}"')

        ###########################################################################################
        # Run

        run_desc = desc.get('run', {})

#        if ctx_setup_compile:
#            ctx['tasks']['local']['setup-compile'] = ctx_setup_compile
#
#            for k in ['target_path_exe', 'target_exe']:
#                if k in ctx_setup_compile and k not in ctx_tasks['local']:
#                    ctx['tasks']['local'][k] = ctx_setup_compile[k]
#
#        if 'setup-dynamic-libs' in ctx['tasks']['local']:
#            dynamic_lib_paths = ctx['tasks']['local']['setup-dynamic-libs'].get('found_dynamic_lib_paths')
#            if dynamic_lib_paths:
#                ctx['tasks']['local']['run_time_env']['+PATH'] = dynamic_lib_paths


        # The times of this task on the monotonic clock: the wall clock can be set while a program runs
        self_time_run_with_cmeta = time.monotonic()
        if not run_desc.get('skip', False) and not skip_run:
            if con and verbose:
                print ('')
                print (f'{space}RUNNING ...')

            # another run of this program in the same cache entry (two pods of a job on one node share its home)
            # may remove it between a check and the removal: a file already gone is fine (2026-11-23)
            try:
                os.remove(path_repro_run)
            except FileNotFoundError:
                pass

            # --provenance=loaded: the dynamic loader logs what the run's processes load (a file per
            # process in the build folder); nothing is added to the environment in the other modes
            if provenance_mode == 'loaded' and uname in ('linux', 'darwin') \
                    and not any(str(c).startswith(('android', 'ios')) for c in selected_compute):
                provenance.clear_loader_logs(target_path)
                if uname == 'darwin':
                    # macOS strips DYLD_* from the environment of the system shell that runs the
                    # command: the variables go into the command line, through setup-run's prefix
                    ctx_tasks.setdefault('use', {}).setdefault('setup-run', {})['prefix_cmd'] = \
                        provenance.loader_prefix(uname, target_path)
                else:
                    ctx_tasks['local'].setdefault('run_time_env', {}).update(provenance.loader_env(uname, target_path))

            if unparsed:
                x = ''
                for u in unparsed:
                    x += ' ' + self.cm.q(u)
                ctx['tasks']['local']['unparsed'] = x.strip()

            run_uses = run_desc.get('uses')
            if run_uses:
                # Every dataset step takes --dataset and --dataset_file of the program unless it names its own
                self.dataset_steps_take_the_programs_params(run_uses)

                run_local = ctx['tasks']['local']    # the run's context: a step that fails leaves its own behind

                # --calibrate: the kernel's repeat raised until the run lasts about the target, as CK did - the
                # run's steps again with the next repeat, until the plan says it is done
                r = self.calibration_plan(params, run_local, desc)
                if self.cm.catch_error(r): return r
                calibration = r['plan']

                # The entries of the run's environment that take the repeat ({{local.params.repeat}}): a step expands
                # them in place, so they are expanded again at every round
                env_templates = {}
                if calibration:
                    for k, v in (((desc.get('local_vars') or {}).get('run_time_env')) or {}).items():
                        if f'params.{calibration["param"]}' in str(v):
                            env_templates[str(k)] = v

                while True:
                    if calibration:
                        params[calibration['param']] = calibration['repeat']
                        if isinstance(run_local.get('params'), dict) and run_local['params'] is not params:
                            run_local['params'][calibration['param']] = calibration['repeat']
                        if env_templates:
                            fresh = copy.deepcopy(env_templates)
                            rx = self.cm.utils.common.expand_strings_in_dict(fresh, ctx_tasks)
                            if self.cm.catch_error(rx): return rx
                            if not isinstance(run_local.get('run_time_env'), dict):
                                run_local['run_time_env'] = {}
                            run_local['run_time_env'].update(fresh)
                        if con:
                            print ('')
                            print (f'{space}### Calibration round {calibration["rounds"] + 1} of {calibration["max"]}: '
                                   f'{calibration["param"]} = {calibration["repeat"]}')

                    p = {'category': self.category_alias + ',' + self.category_uid,
                         'command': 'use',
                         'con': con,
                         'quiet': quiet,
                         'verbose': verbose,
                         'ctx': ctx,
                         'desc': run_uses,
                         'local': run_local,              # Reuse local from this task (selected-program)
                         'task_artifact_alias': self.artifact_alias,
                         'task_artifact_uid': self.artifact_uid,
                         'task_artifact_path': self.artifact_path,
                         'self_desc': desc,
                         'uparams': params,
                        }

                    r = self.cm.access(p)

                    rx = self.cm.utils.files.write_file(path_repro_run, {'ctx':ctx, 'result':r}, safe_dump = True)
                    if self.cm.catch_error(rx): return rx

                    if self.cm.catch_error(r):
                        # The summary of a run that failed - what ran, where, what it left - before the error
                        if calibration:
                            result['calibration'] = calibration
                        self.run_summary(ctx, params, result, error = r.get('error'), built_now = built_now, local = run_local)
                        return r

                    if not calibration:
                        break

                    calibration_step(calibration, ctx['tasks']['local'])
                    if con and not calibration['done']:
                        last = calibration['history'][-1]
                        print ('')
                        print (f'{space}### Calibration: the run lasted {seconds_text(last["seconds"])} with {calibration["param"]} = '
                               f'{last["repeat"]}; next {calibration["param"]} = {calibration["repeat"]} (target {seconds_text(calibration["target"])})')
                    if calibration['done']:
                        result['calibration'] = {k: v for k, v in calibration.items() if k not in ('done', 'next')}
                        break

            # Check result files
            result_files_data = ctx['tasks']['local'].get('result_files_data')

            if result_files_data:
                result.update(result_files_data)

        ###########################################################################################
        # The provenance record of this run: provenance.json in the build folder. Passive by
        # default (nothing of the run changes); a problem writing it is a warning; only
        # --provenance=strict fails the run, on a failed error-level check
        if provenance_mode != 'off':
            r = self.write_provenance(ctx, params, provenance_mode, request_params, request_use,
                                      target_path, target_tmp, artifact_alias, artifact_uid, selected_compute,
                                      run_skipped = bool(run_desc.get('skip', False) or skip_run))
            if self.cm.catch_error(r): return r
            result['provenance'] = r['provenance']

        self_time_compile = ctx_tasks['local'].get('compile-program', {}).get('_impact', {}).get('self_time')

        result['_impact'] = {'self_time_compile_with_cmeta': self_time_compile,
                             'self_time_run_with_cmeta': time.monotonic() - self_time_run_with_cmeta}
        if build_disk_gb is not None:
            result['_impact']['disk_gb'] = build_disk_gb

        # The outputs against the program's reference outputs, or recorded as the reference (--check_output)
        output_check = None
        if params.get('check_output') not in (None, False, 'no', 'false', 'off') and not (run_desc.get('skip', False) or skip_run):
            try:
                resolved = provenance.collect_resolved(ctx_tasks.get('global') or {})
            except Exception:
                resolved = {}
            output_check = self.output_check(ctx, params, desc, artifact_alias or artifact_uid, artifact_uid, result,
                                             ctx_tasks['local'], resolved)
            if output_check:
                result['output_check'] = output_check

        # The summary of the run: printed (--summary=no: not), and in the result
        result['summary'] = self.run_summary(ctx, params, result, built_now = built_now,
                                             run_skipped = bool(run_desc.get('skip', False) or skip_run))

        if output_check and output_check.get('status') in ('failed', 'error', 'no_reference'):
            status = output_check['status']
            if status == 'failed':
                bad = ', '.join(f'{n} ({v.get("why")})' for n, v in (output_check.get('files') or {}).items() if v.get('status') != 'ok')
                return self.cm.error(f'the outputs of {artifact_alias or artifact_uid} differ from the reference {output_check.get("case")}: {bad}')
            return self.cm.error(output_check.get('error') or output_check.get('note') or 'the output check failed')

        # A calibration that did not settle is a failed run, as it was for CK (the outputs of the last round stay)
        calibration = result.get('calibration') if isinstance(result.get('calibration'), dict) else None
        if calibration and calibration.get('success') is False:
            return self.cm.error(f'{artifact_alias or artifact_uid}: {calibration.get("why") or "the calibration failed"}')

        return result


