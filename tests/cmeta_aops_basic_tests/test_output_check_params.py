"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The parameters of a run in the reference outputs and in the summary (compile-and-run-program): the key values of the
rules in the key of a case, the request's parameters as facts and as a line, CK's calibration of the kernel's repeat
(the time of a run, one round, the plan), and what the summary says of it.
"""

import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def carp():
    """compile-and-run-program's code without the task category's imports."""
    path = ROOT / 'task' / 'compile-and-run-program' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    for line in ('from task_c36be4b9314a45e0.api.ctask import InitCTask\n', 'from task_c36be4b9314a45e0.api import deadlines\n',
                 'from task_c36be4b9314a45e0.api import build_stamp\n', 'from task_c36be4b9314a45e0.api import build_identity\n',
                 'from task_c36be4b9314a45e0.api import provenance\n'):
        assert line in src, line
        src = src.replace(line, '')
    stub = SimpleNamespace()
    ns = {'InitCTask': object, 'deadlines': stub, 'build_stamp': stub, 'build_identity': stub, 'provenance': stub,
          '__name__': 'output_check_params_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_key_values_are_merged_and_land_in_the_key(carp):
    desc = {'output_check': {'key_values': {'a': 1}, 'invariant_of_repeat': True},
            'updates_cmd': {'encode': {'output_check': {'key_values': {'b': 'two'}}}}}
    assert carp['output_check_rules'](desc, 'encode') == {'key_values': {'a': 1, 'b': 'two'}, 'invariant_of_repeat': True}
    assert carp['output_check_rules'](desc) == {'key_values': {'a': 1}, 'invariant_of_repeat': True}
    key = carp['output_key']({'key_params': ['n'], 'key_values': {'compile.d.NI': '16', 'repeat': 3, 'flag': None}},
                             'p', 'default', {}, {'n': 2})
    assert key['params'] == {'n': 2, 'compile.d.NI': '16', 'repeat': 3, 'flag': None}
    # A reference recorded before the repeat was in the key is another case
    assert not carp['same_key'](key, dict(key, params = {'n': 2, 'compile.d.NI': '16', 'flag': None}))


def test_the_request_params_and_their_line(carp):
    params = {'name': 'p', 'compute': 'cpu', 'repeat': 3, 'check_output': True, 'output_repo': 'x', 'summary': None,
              'calibrate': '10', 'compile': {'size': 'large', 'd': {'NI': '16', 'XOPENME': None}}, 'dataset': None}
    kept = carp['request_params'](params)
    assert kept == {'name': 'p', 'compute': 'cpu', 'repeat': 3, 'compile': {'size': 'large', 'd': {'NI': '16', 'XOPENME': None}}}
    assert carp['params_text'](kept) == 'name=p, compute=cpu, repeat=3, compile.size=large, compile.d.NI=16, compile.d.XOPENME'
    assert carp['params_text']({}) == '' and carp['request_params'](None) == {}


def test_the_time_of_a_run_and_one_round_of_the_calibration(carp):
    seconds = carp['run_seconds_of']
    assert seconds({'result_files_data': {'stats': {'execution_time': 0.25}}, 'run-program': {'_impact': {'self_time': 9}}}) == 0.25
    assert seconds({'result_files_data': {'stats': {'execution_time': 0.0}}, 'run-program': {'_impact': {'self_time': 0.3}}}) == 0.3
    assert seconds({}) is None

    step = carp['calibration_step']

    def plan(repeat = 1, rounds = 0, max_rounds = 10, target = 4.0):
        return {'param': 'repeat', 'target': target, 'max': max_rounds, 'repeat': repeat, 'rounds': rounds, 'history': [],
                'seconds': None, 'done': False, 'success': None, 'why': ''}

    def local(t):
        return {'result_files_data': {'stats': {'execution_time': t}}}

    p = step(plan(), local(0.02))                        # under half a second: tenfold
    assert p['repeat'] == 10 and not p['done'] and p['history'] == [{'repeat': 1, 'seconds': 0.02}] and p['rounds'] == 1
    p = step(plan(repeat = 10), local(3.5))              # near the target: done
    assert p['done'] and p['success'] and p['repeat'] == 10
    p = step(plan(repeat = 10), local(1.0))              # far from it: scaled
    assert p['repeat'] == 40 and not p['done']
    p = step(plan(repeat = 10), local(100.0))            # too long: scaled down, one at least
    assert p['repeat'] == 1 and not p['done']
    p = step(plan(repeat = 1), local(100.0))             # one already: nothing to lower, done
    assert p['done'] and p['success'] and p['repeat'] == 1
    p = step(plan(repeat = 10, rounds = 9), local(1.0))  # the rounds run out
    assert p['done'] and p['success'] is False and 'calibration failed' in p['why'] and p['repeat'] == 10
    p = step(plan(), {})                                 # no time at all
    assert p['done'] and p['success'] is False and 'not known' in p['why']


def test_the_plan_of_a_calibration(carp):
    task = carp['CTask'].__new__(carp['CTask'])
    task.cm = SimpleNamespace(error = lambda msg: {'return': 1, 'error': msg})
    local = {'run_time_env': {'CT_REPEAT_MAIN': '{{local.params.repeat|1}}'}}
    assert task.calibration_plan({}, local)['plan'] is None
    assert task.calibration_plan({'calibrate': 'no'}, local)['plan'] is None
    p = task.calibration_plan({'calibrate': True}, local)['plan']
    assert (p['param'], p['target'], p['max'], p['repeat']) == ('repeat', 4.0, 10, 1)
    p = task.calibration_plan({'calibrate': '12', 'calibrate_max': '3', 'repeat': '7'}, local)['plan']
    assert (p['target'], p['max'], p['repeat']) == (12.0, 3, 7)
    assert 'seconds' in task.calibration_plan({'calibrate': 'soon'}, local)['error']
    assert 'rounds' in task.calibration_plan({'calibrate': True, 'calibrate_max': 'x'}, local)['error']
    assert 'does not repeat its kernel' in task.calibration_plan({'calibrate': True}, {})['error']
    # The program names the parameter that repeats, or its description's environment takes it
    assert task.calibration_plan({'calibrate': True}, {'repeat_param': 'loops'})['plan']['param'] == 'loops'
    desc = {'local_vars': {'run_time_env': {'N': '{{local.params.repeat|1}}'}}}
    assert task.calibration_plan({'calibrate': True}, {}, desc)['plan']['param'] == 'repeat'


def test_the_summary_says_the_params_and_the_calibration(carp):
    text = carp['summary_text']
    summary = {'program': 'p', 'cmd': 'default', 'status': 'ok', 'compute': ['cpu'],
               'params': {'repeat': 400, 'compile': {'n': 8}},
               'calibration': {'param': 'repeat', 'target': 4.0, 'max': 10, 'repeat': 400, 'rounds': 3, 'seconds': 4.4, 'success': True,
                               'history': [{'repeat': 1, 'seconds': 0.01}, {'repeat': 10, 'seconds': 0.11}, {'repeat': 400, 'seconds': 4.4}]}}
    lines = text(summary)
    assert '  params:   repeat=400, compile.n=8' in lines
    assert any(x.startswith('  calibration: repeat 1 -> 400 in 3 rounds: done, the run lasts') for x in lines)
    summary['calibration'].update({'success': False, 'why': 'calibration failed: 10 rounds'})
    assert any('FAILED' in x and 'calibration failed' in x for x in text(summary))
    assert not any(x.startswith('  params:') or x.startswith('  calibration:') for x in text({'program': 'p', 'status': 'ok'}))


def test_ignore_lines_leave_the_device_out_of_a_comparison(carp, tmp_path):
    ignore, why = carp['ignore_patterns']({'ignore_lines': ['^GPU Device ', '^device name is ']})
    assert why is None and len(ignore) == 2
    assert carp['ignore_patterns']({'ignore_lines': ['(unclosed']})[1].startswith('output_check.ignore_lines')
    assert carp['ignore_patterns']({}) == ([], None)

    ref = tmp_path / 'ref.txt'
    run = tmp_path / 'run.txt'
    ref.write_bytes(b'GPU Device 0: "NVIDIA RTX" with compute capability 12.0\n\nNon-Matching CPU-GPU Outputs: 0\n')
    run.write_bytes(b'GPU Device 0: "Apple M4" with compute capability 0.0\n\nNon-Matching CPU-GPU Outputs: 0\n')
    record = carp['output_digests'](str(ref), ignore)
    # Without the patterns the two differ; with them, the same
    assert carp['output_digests'](str(run))['sha256'] != carp['output_digests'](str(ref))['sha256']
    assert carp['compare_output'](str(run), record, None, None, ignore)[0] == 'ok'
    # A real difference stays one
    run.write_bytes(b'GPU Device 0: "Apple M4"\n\nNon-Matching CPU-GPU Outputs: 3\n')
    assert carp['compare_output'](str(run), record, None, None, ignore)[0] == 'differs'
    # The size recorded is the whole file's
    assert record['size'] == len(ref.read_bytes())
    # Numbers within a tolerance, the ignored lines left out of both
    ref.write_bytes(b'device name is A\nvalue 1.0000001\n')
    run.write_bytes(b'device name is B\nvalue 1.0000002\n')
    assert carp['numbers_within'](str(run), str(ref), 1e-6, ignore)[0] is True
    assert carp['numbers_within'](str(run), str(ref), 1e-6)[0] is False


def test_a_case_keeps_its_ignore_lines_and_the_whole_file(carp, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'out.txt').write_bytes(b'GPU Device 0: X\nresult 0\n')
    ignore, _ = carp['ignore_patterns']({'ignore_lines': ['^GPU Device ']})
    case = carp['write_case'](str(tmp_path / 'case'), {'program': 'p'}, {}, ['out.txt', 'never.txt'], str(work),
                              ignore = ignore, ignore_lines = ['^GPU Device '])
    assert case['ignore_lines'] == ['^GPU Device ']
    assert case['files']['never.txt'] is None
    assert (tmp_path / 'case' / 'out.txt').read_bytes() == b'GPU Device 0: X\nresult 0\n'     # kept whole
    import hashlib
    assert case['files']['out.txt']['sha256'] == hashlib.sha256(b'result 0\n').hexdigest()  # digests without it


def test_ignore_lines_merge_from_the_program_and_its_command(carp):
    desc = {'output_check': {'ignore_lines': ['^a']}, 'updates_cmd': {'x': {'output_check': {'ignore_lines': ['^b', '^a']}}}}
    assert carp['output_check_rules'](desc, 'x')['ignore_lines'] == ['^a', '^b']


def test_an_absolute_floor_for_numbers_printed_with_few_decimals(carp, tmp_path):
    ref = tmp_path / 'ref.txt'
    run = tmp_path / 'run.txt'
    # A difference that crosses the rounding of the second decimal: 0.17 against 0.18, and 1.00 against 1.01
    ref.write_text('0.17 1.00 53378910.56\n')
    run.write_text('0.18 1.01 53378910.57\n')
    assert carp['numbers_within'](str(run), str(ref), 1e-6)[0] is False                       # the floor is the tolerance
    ok, why = carp['numbers_within'](str(run), str(ref), 1e-6, None, 0.01)
    assert ok is True and '0.01 absolute' in why
    # A real difference stays one: two steps of the last digit, or a relative one beyond the tolerance
    run.write_text('0.19 1.00 53378910.56\n')
    assert carp['numbers_within'](str(run), str(ref), 1e-6, None, 0.01)[0] is False
    run.write_text('0.17 1.00 53500000.00\n')
    assert carp['numbers_within'](str(run), str(ref), 1e-6, None, 0.01)[0] is False
    # compare_output passes it on
    ref.write_text('0.17\n')
    run.write_text('0.18\n')
    record = carp['output_digests'](str(ref))
    assert carp['compare_output'](str(run), record, str(ref), 1e-6, None, 0.01)[0] == 'ok'
    assert carp['compare_output'](str(run), record, str(ref), 1e-6)[0] == 'differs'
