"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the summary that compile-and-run-program prints after a run (run_summary_of, summary_text and
the helpers) and of what template-ck-program adds to it (customize_summary).
"""

import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel, drop, names):
    """A task's or program's code with some import lines dropped and their names given."""
    path = ROOT / rel
    src = path.read_text(encoding = 'utf-8')
    for line in drop:
        assert line in src, line
        src = src.replace(line, '')
    ns = dict(names, __name__ = 'summary_test', __file__ = str(path))
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def carp():
    """compile-and-run-program's code without the task category's imports."""
    stub = SimpleNamespace()
    return load('task/compile-and-run-program/api_v1.py',
                drop = ['from task_c36be4b9314a45e0.api.ctask import InitCTask\n',
                        'from task_c36be4b9314a45e0.api import deadlines\n',
                        'from task_c36be4b9314a45e0.api import build_stamp\n',
                        'from task_c36be4b9314a45e0.api import build_identity\n',
                        'from task_c36be4b9314a45e0.api import provenance\n'],
                names = {'InitCTask': object, 'deadlines': stub, 'build_stamp': stub, 'build_identity': stub, 'provenance': stub})


@pytest.fixture(scope = 'module')
def ck():
    """template-ck-program's hooks without the program category's import."""
    ns = load('program/template-ck-program/api_v1.py',
              drop = ['from program_22788f3c30d04e6d.api.cprogram import InitCProgram\n'],
              names = {'InitCProgram': object})
    hook = ns['CProgram'].__new__(ns['CProgram'])
    hook.cm = SimpleNamespace(error = lambda msg: {'return': 1, 'error': msg})
    return hook


def context(tmp_path, compute = ('cpu',), with_dataset = True, ran = True):
    """A run's local and global context: a build folder with outputs, an input file, the host, the target."""
    work = tmp_path / 'build'
    work.mkdir(exist_ok = True)
    for name, text in (('tmp-output.tmp', 'x' * 1500), ('tmp-output1.tmp', ''), ('tmp-ck-timer.json', '{}')):
        (work / name).write_text(text)
    data = tmp_path / 'in.ppm'
    data.write_bytes(b'P6' * 10)
    local = {'selected-program': {'artifact': {'cmeta_ref_parts': {'artifact_alias': 'prog'}}},
             'output_files': ['tmp-output.tmp', 'tmp-output1.tmp', 'missing.bin'],
             'result_files': {'stats': 'tmp-ck-timer.json'},
             'run_time_cmds': [str(work / 'prog.exe') + ' -x ' + str(data) + ' > tmp-output1.tmp'],
             'target_path': str(work), 'work_path': str(work)}
    if ran:
        local['run-program'] = {'returncode': 0, '_impact': {'self_time': 0.123}, 'stderr': ''}
        local['result_files_data'] = {'stats': {'execution_time': 0.5, 'execution_time_kernel_0': 0.25}}
    if with_dataset:
        local['dataset'] = {'artifact_au': 'ctuning-image-ppm,1234', 'sub_dataset': 'image-ppm-0007', 'desc': 'input 7',
                            'path': str(data), 'files': ['data.ppm']}
    else:
        local['input_files'] = {'data': str(data)}
    global_ctx = {'target': {'compute': list(compute),
                             'features': {'cpu': {'model_name': 'Fake CPU 9000', 'logical_cpu_count': 8}}},
                  'host': {'os': {'uname': 'linux', 'uarch': 'amd64', 'python_platform_terse': 'Linux-6.8'},
                           'os_extra': {'id': 'ubuntu', 'version': '24.04'},
                           'hostname': {'hostname': 'box'}, 'vars': {'file_ext_bat': '.sh'}}}
    if 'cuda' in compute:
        global_ctx['cuda'] = {'features': {'versions': {'driver version': '616.92', 'cuda version': '13.4'},
                                           'devices': [{'name': 'Fake GPU', 'compute_cap': '12.0'}]}}
    return local, global_ctx


RESOLVED = {'compiler-c': {'name': 'gcc', 'version': '14.2'}, 'gcc': {'name': 'gcc', 'version': '14.2'},
            'lib-xopenme': {'name': 'lib-xopenme', 'version': 'default'}, 'cuda': {'name': 'cuda', 'version': '13.4'}}


def test_the_summary_of_a_run_that_worked(carp, tmp_path):
    local, global_ctx = context(tmp_path)
    result = {'_impact': {'self_time_run_with_cmeta': 0.9, 'self_time_compile_with_cmeta': 3.0},
              'provenance': {'ok': True, 'errors': 0, 'warnings': 1, 'path': str(tmp_path / 'build' / 'provenance.json')}}
    s = carp['run_summary_of'](local, global_ctx, {'cmd': 'edges'}, result, RESOLVED, built_now = False)
    assert s['program'] == 'prog' and s['cmd'] == 'edges' and s['status'] == 'ok' and s['return_code'] == 0
    assert s['host'] == {'uname': 'linux', 'uarch': 'amd64', 'hostname': 'box', 'os': 'ubuntu 24.04'}
    assert s['cpu'] == 'Fake CPU 9000, 8 logical CPUs'
    assert s['tools'] == 'compiler-c: gcc 14.2, lib-xopenme, cuda 13.4'
    assert s['input']['dataset'] == 'ctuning-image-ppm,1234' and s['input']['sub_dataset'] == 'image-ppm-0007'
    assert s['input']['size'] == 20 and s['input']['files'] == ['data.ppm']
    assert s['command'].startswith('prog.exe -x ')                    # the build folder's prefix dropped
    assert s['times'] == {'run_seconds': 0.123, 'run_with_cmeta_seconds': 0.9, 'compile_with_cmeta_seconds': 3.0,
                          'kernel_seconds': 0.25, 'kernel_source': 'execution_time_kernel_0 of tmp-ck-timer.json'}
    assert [(o['name'], o['size']) for o in s['outputs']] == \
        [('tmp-output.tmp', 1500), ('tmp-output1.tmp', 0), ('missing.bin', None), ('tmp-ck-timer.json', 2)]
    assert s['build']['compiled_now'] is False and s['build']['path'] == str(tmp_path / 'build')
    assert s['checks'] == [{'what': 'provenance record', 'ok': True,
                            'detail': '0 errors, 1 warnings - ' + str(tmp_path / 'build' / 'provenance.json')}]

    lines = carp['summary_text'](s)
    assert lines[0] == 'cMeta run summary: prog (edges) on cpu: OK, exit 0 in 0.123 s (kernel 0.250 s)'
    assert lines[1] == '  host:     linux amd64 (ubuntu 24.04) box; CPU Fake CPU 9000, 8 logical CPUs'
    assert lines[2] == '  tools:    compiler-c: gcc 14.2, lib-xopenme, cuda 13.4'
    assert lines[3] == '  input:    ctuning-image-ppm,1234/image-ppm-0007 - input 7'
    assert lines[4] == f'            {tmp_path / "in.ppm"} (20 B)'
    assert any('tmp-output.tmp (1.5 KB), tmp-output1.tmp (0 B), missing.bin (not made), tmp-ck-timer.json (2 B)' in l for l in lines)
    assert any(l.startswith('  build:    ') and l.endswith('(reused)') for l in lines)
    assert any(l.startswith('            scripts tmp-cmeta-compile-program.sh, tmp-cmeta-run-program.sh, provenance.json') for l in lines)
    assert any('provenance record: ok - 0 errors, 1 warnings' in l for l in lines)

    # The whole block: a rule, the summary (nothing was printed by the run), a rule, the stats of the result files, a rule
    assert s['stats'] == [{'key': 'stats', 'file': 'tmp-ck-timer.json', 'data': {'execution_time': 0.5, 'execution_time_kernel_0': 0.25}}]
    assert 'stdout' not in s and 'stderr' not in s
    block = carp['summary_block'](s)
    rule = carp['RULE']
    assert block[0] == rule and block[1] == lines[0] and block[-1] == rule and block.count(rule) == 3
    i = block.index('stats of the run: stats (tmp-ck-timer.json)')
    assert block[i + 1:i + 3] == ['  execution_time = 0.5', '  execution_time_kernel_0 = 0.25'] and block[i + 3] == rule

    # What the run printed comes first, standard output then standard error, each apart
    local['run-program']['stdout'] = 'hello\nworld\n'
    local['run-program']['stderr'] = 'warn\n'
    s = carp['run_summary_of'](local, global_ctx, {'cmd': 'edges'}, result, RESOLVED, built_now = False)
    assert s['stdout'] == {'source': 'the run', 'text': 'hello\nworld\n'} and s['stderr'] == {'source': 'the run', 'text': 'warn\n'}
    block = carp['summary_block'](s)
    assert block[:5] == [rule, 'standard output of the run (the run, 2 lines):', '', 'hello', 'world']
    assert block[5:9] == [rule, 'standard error of the run (the run, 1 line):', '', 'warn'] and block[9] == rule
    assert block[10] == lines[0] and block.count(rule) == 5

    # A long output is cut, and the file that holds the whole named
    s['stdout'] = {'source': 'out.txt', 'text': '\n'.join(str(i) for i in range(100)), 'path': '/x/out.txt'}
    section = carp['output_section']('standard output', s['stdout'])
    assert section[0] == 'standard output of the run (out.txt, 100 lines):' and len(section) == 2 + carp['OUTPUT_MAX_LINES'] + 1
    assert section[-1] == f'... {100 - carp["OUTPUT_MAX_LINES"]} more lines in /x/out.txt'
    assert carp['stats_lines']({'a': 1, 'b': {'c': 'x'}}) == ['a = 1', 'b.c = x'] and carp['stats_lines']('two\nlines\n') == ['two', 'lines']


def test_a_cuda_run_names_the_gpu_and_a_failed_run_its_error(carp, tmp_path):
    local, global_ctx = context(tmp_path, compute = ('cuda',))
    s = carp['run_summary_of'](local, global_ctx, {}, {}, {}, built_now = True)
    assert s['gpu'] == [{'name': 'Fake GPU', 'compute_capability': '12.0', 'driver': '616.92', 'cuda': '13.4'}]
    lines = carp['summary_text'](s)
    assert '  gpu:      Fake GPU (compute capability 12.0, driver 616.92, CUDA 13.4)' in lines
    assert any(l.endswith('(built now)') for l in lines) and not any(l.startswith('  tools:') for l in lines)

    # A run that failed: the exit code from the error, the input file, the error last; no run-program result
    local, global_ctx = context(tmp_path, with_dataset = False, ran = False)
    s = carp['run_summary_of'](local, global_ctx, {}, {}, {}, error = 'CMD "prog.exe" failed with return code 3')
    assert s['status'] == 'failed' and s['return_code'] == 3 and s['input'] == {'files': {'data': str(tmp_path / 'in.ppm')}}
    lines = carp['summary_text'](s)
    assert lines[0] == 'cMeta run summary: prog (default) on cpu: FAILED, exit 3'
    assert lines[-1] == '  error:    CMD "prog.exe" failed with return code 3'
    assert any(l == f'  input:    data = {tmp_path / "in.ppm"}' for l in lines)
    s = carp['run_summary_of'](local, global_ctx, {}, {}, {}, error = 'CMD "x" timed out after 5 s')
    assert s['status'] == 'timeout' and carp['summary_text'](s)[0].endswith('TIMED OUT')
    s = carp['run_summary_of'](local, global_ctx, {}, {}, {}, run_skipped = True)
    assert s['status'] == 'skipped' and carp['summary_text'](s)[0].endswith('not run (compile only)')

    # A dataset given as a file: its path alone
    local['dataset'] = {'path': str(tmp_path / 'in.ppm')}
    s = carp['run_summary_of'](local, global_ctx, {}, {}, {})
    assert s['input']['dataset'] is None and any(l == f'  input:    {tmp_path / "in.ppm"} (20 B)' for l in carp['summary_text'](s))


def test_sizes_tools_and_cpu_names(carp):
    assert [carp['size_text'](x) for x in (0, 999, 1000, 2500000, 3e9, None)] == ['0 B', '999 B', '1.0 KB', '2.5 MB', '3.0 GB', '?']
    assert carp['tools_text']({'msvc': {'name': 'msvc', 'version': '19'}, 'compiler-c': {'name': 'msvc', 'version': '19'},
                               'compiler-cuda': {'name': 'nvcc', 'version': '13'}, 'lib-cuda': {'name': 'lib-cuda', 'version': '13.4'}}) \
        == 'compiler-c: msvc 19, compiler-cuda: nvcc 13, lib-cuda 13.4'
    assert carp['tools_text']({}) == ''
    assert carp['cpu_name']({'cpu': {'packages': [{'Name': 'Intel X'}], 'logical_cpu_count': 16}}) == 'Intel X, 16 logical CPUs'
    assert carp['cpu_name']({'cpu': {'extended_identifier': 'Family 6'}}) == 'Family 6'
    assert carp['cpu_name']({}) is None


def test_the_ck_template_adds_the_cpu_check_the_opencl_device_and_the_size(ck, tmp_path):
    work = tmp_path / 'run'
    work.mkdir()
    (work / 'tmp-output1.tmp').write_text('GPU Device 0\n\nNon-Matching CPU-GPU Outputs Beyond Error Threshold of 0.05 Percent: 3\n')
    (work / 'tmp-output2.tmp').write_text('line 1\nline 2\n')
    ctx = {'tasks': {'local': {'work_path': str(work), 'ck_cpu_check': True, 'ck_size_vars': ['NI'],
                               'params': {'compile': {'size': 'large'}},
                               'ck_redirects': '> tmp-output1.tmp 2> tmp-output2.tmp',
                               'ck_opencl': {'platform': 0, 'device': 1, 'name': 'Fake GPU'}},
                     'global': {'opencl': {'features': {'devices': [
                         {'name': 'Other'},
                         {'name': 'Fake GPU', 'platform': 'Fake Platform', 'version': 'OpenCL 3.0', 'driver_version': '1.2'}]}}}}}
    summary = {'status': 'failed', 'work_path': str(work), 'checks': [], 'lines': []}
    assert ck.customize_summary(ctx, summary) == {'return': 0}
    assert summary['checks'] == [{'what': "GPU results against the CPU's (beyond 0.05 %)", 'ok': False, 'detail': '3 values differ'}]
    assert summary['lines'] == ['defines:  LARGE_DATASET',
                                'opencl:   platform 0, device 1: Fake GPU (Fake Platform, OpenCL 3.0, driver 1.2)',
                                'polybench: size large, arrays not dumped']
    # What the program printed, from CK's files
    assert summary['stdout']['source'] == 'tmp-output1.tmp' and summary['stdout']['text'].startswith('GPU Device 0')
    assert summary['stderr'] == {'source': 'tmp-output2.tmp', 'text': 'line 1\nline 2\n', 'path': str(work / 'tmp-output2.tmp')}

    # A run that worked without the comparison in its output: said so; no redirects: nothing taken from the files
    (work / 'tmp-output1.tmp').write_text('nothing\n')
    ctx['tasks']['local'] = {'work_path': str(work), 'ck_cpu_check': True}
    summary = {'status': 'ok', 'work_path': str(work), 'checks': [], 'lines': []}
    ck.customize_summary(ctx, summary)
    assert summary['checks'][0]['ok'] is None and 'stdout' not in summary and 'stderr' not in summary

    # A program without the check, redirecting: the output only
    ctx['tasks']['local'] = {'work_path': str(work), 'ck_redirects': '> tmp-output1.tmp 2> tmp-output2.tmp'}
    summary = {'status': 'ok', 'work_path': str(work), 'checks': [], 'lines': []}
    ck.customize_summary(ctx, summary)
    assert summary['checks'] == [] and summary['lines'] == [] and summary['stdout']['text'] == 'nothing\n'
