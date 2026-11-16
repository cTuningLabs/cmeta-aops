"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The parameters of a CK program's build in the key of its reference outputs and in its summary (template-ck-program):
--compile.n (square arrays), --compile.precision, the defines applied once or twice (a reused build brings them back
applied), what is refused, the key values customize_output_check gives (the defines, the kernel's repeat), the
defines line of the summary.
"""

import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def ck():
    """The template's hooks without the program category's import."""
    path = ROOT / 'program' / 'template-ck-program' / 'api_v1.py'
    source = path.read_text(encoding = 'utf-8').replace(
        'from program_22788f3c30d04e6d.api.cprogram import InitCProgram', 'class InitCProgram: pass')
    ns = {'__file__': str(path), '__name__': 'template_ck_program_params_test'}
    exec(compile(source, str(path), 'exec'), ns)
    hook = ns['CProgram'].__new__(ns['CProgram'])
    hook.cm = SimpleNamespace(error = lambda msg: {'return': 1, 'error': msg})
    return hook


CK_DEFINES = {'DATA_TYPE': 'double', 'NI': '16', 'NJ': '16', 'NK': '16', 'POLYBENCH_DUMP_ARRAYS': 'YES', 'XOPENME': None}


def context(compile_params, local = None):
    """A PolyBench program with CK's defines, the compile parameters given, and CK's repeat in its environment."""
    _local = {'lang': 'c', 'ck_size_vars': ['NI', 'NJ', 'NK'],
              'params': {'compile': dict(compile_params, d = dict(CK_DEFINES))},
              'run_time_env': {'CT_REPEAT_MAIN': '{{local.params.repeat|1}}'}}
    _local.update(local or {})
    return {'tasks': {'global': {'target': {'compute': ['cpu']}, 'host': {'os': {'uname': 'linux'}},
                                 'compiler-c': {'features': {'flags': {'d': '-D'}}}},
                      'local': _local}}


def test_n_makes_every_size_the_same_and_precision_sets_the_type(ck):
    ctx = context({'n': 64, 'precision': 'float'})
    assert ck.customize2(ctx) == {'return': 0}
    d = ctx['tasks']['local']['params']['compile']['d']
    assert d['NI'] == d['NJ'] == d['NK'] == '64' and d['DATA_TYPE'] == 'float'
    assert 'POLYBENCH_DUMP_ARRAYS' not in d                       # no dump with an N, unless asked
    ctx = context({'n': '8', 'dump': 'yes'})
    assert ck.customize2(ctx) == {'return': 0}
    assert ctx['tasks']['local']['params']['compile']['d']['POLYBENCH_DUMP_ARRAYS'] == 'YES'


def test_the_defines_are_the_same_applied_twice_as_a_reused_build_brings_them_back(ck):
    ctx = context({'size': 'large', 'precision': 'float'})
    assert ck.customize2(ctx) == {'return': 0}
    once = dict(ctx['tasks']['local']['params']['compile']['d'])
    assert ck.customize2(ctx) == {'return': 0}
    assert ctx['tasks']['local']['params']['compile']['d'] == once
    assert 'LARGE_DATASET' in once and 'NI' not in once and once['DATA_TYPE'] == 'float' and 'POLYBENCH_DUMP_ARRAYS' not in once


def test_what_is_refused_and_what_is_left_alone(ck):
    assert 'one of them' in ck.customize2(context({'n': 32, 'size': 'small'}))['error']
    assert 'positive whole number' in ck.customize2(context({'n': 'big'}))['error']
    assert 'float, double' in ck.customize2(context({'precision': 'half'}))['error']
    no_type = context({'precision': 'float'}, local = {'params': {'compile': {'precision': 'float', 'd': {'NI': '16'}}}})
    assert 'no DATA_TYPE' in ck.customize2(no_type)['error']
    no_sizes = context({'n': 4}, local = {'ck_size_vars': None})
    assert '--compile.n does not apply' in ck.customize2(no_sizes)['error']
    # A cBench program given --compile.size: nothing to size, nothing changed (as before)
    plain = context({'size': 'large'}, local = {'ck_size_vars': None, 'params': {'compile': {'size': 'large', 'd': {'XOPENME': None}}}})
    assert ck.customize2(plain) == {'return': 0}
    assert plain['tasks']['local']['params']['compile']['d'] == {'XOPENME': None}


def test_the_key_of_a_case_holds_the_defines_and_the_repeat(ck):
    ctx = context({'n': 32, 'precision': 'float'})
    ctx['tasks']['local']['params']['repeat'] = '5'
    rules = {}
    assert ck.customize_output_check(ctx, rules) == {'return': 0}
    assert rules['key_params'] == ['compile.size', 'compile.dump']
    assert rules['key_values'] == {'compile.d.DATA_TYPE': 'float', 'compile.d.NI': '32', 'compile.d.NJ': '32',
                                   'compile.d.NK': '32', 'repeat': 5}

    # CK's sizes and no repeat given (1); XOPENME and WINDOWS never in the key; a valueless define as ''; values given kept
    ctx = context({})
    ctx['tasks']['local']['params']['compile']['d'].update({'WINDOWS': None, 'CK_CPU_CHECK': None})
    rules = {'key_values': {'given': 'kept'}}
    assert ck.customize_output_check(ctx, rules) == {'return': 0}
    assert rules['key_values'] == {'given': 'kept', 'compile.d.DATA_TYPE': 'double', 'compile.d.NI': '16', 'compile.d.NJ': '16',
                                   'compile.d.NK': '16', 'compile.d.POLYBENCH_DUMP_ARRAYS': 'YES', 'compile.d.CK_CPU_CHECK': '',
                                   'repeat': 1}

    # An output the same whatever the repeat, or a program that does not repeat: no repeat in the key
    rules = {'invariant_of_repeat': True}
    ck.customize_output_check(ctx, rules)
    assert 'repeat' not in rules['key_values']
    rules = {}
    ck.customize_output_check(context({}, local = {'run_time_env': {}}), rules)
    assert 'repeat' not in rules['key_values']

    # A cBench program: no define in the key, the repeat alone
    rules = {}
    ck.customize_output_check(context({}, local = {'ck_size_vars': None, 'params': {'compile': {'d': {'XOPENME': None}}}}), rules)
    assert rules['key_values'] == {'repeat': 1} and 'key_params' not in rules

    # A wrong parameter is an error of the hook
    assert 'one of them' in ck.customize_output_check(context({'n': 2, 'size': 'mini'}), {})['error']


def test_polybench_gets_a_floating_point_tolerance_that_a_program_can_override(ck):
    # A PolyBench program (ck_size_vars): a default relative tolerance for its floating-point dump
    rules = {}
    ck.customize_output_check(context({}), rules)
    assert rules['tolerance'] == 1e-6
    # The program's own output_check.tolerance is kept
    rules = {'tolerance': 1e-9}
    ck.customize_output_check(context({}), rules)
    assert rules['tolerance'] == 1e-9
    # A cBench program (no sizes): no tolerance added
    rules = {}
    ck.customize_output_check(context({}, local={'ck_size_vars': None, 'params': {'compile': {'d': {'XOPENME': None}}}}), rules)
    assert 'tolerance' not in rules


def test_the_summary_names_the_defines(ck, tmp_path):
    ctx = context({'n': 8})
    ctx['tasks']['local']['work_path'] = str(tmp_path)
    summary = {'status': 'ok', 'work_path': str(tmp_path), 'checks': [], 'lines': []}
    assert ck.customize_summary(ctx, summary) == {'return': 0}
    assert summary['lines'] == ['defines:  DATA_TYPE=double, NI=8, NJ=8, NK=8',
                                'polybench: size every dimension 8 (--compile.n), arrays not dumped']
    # A cBench program: no defines line
    summary = {'status': 'ok', 'work_path': str(tmp_path), 'checks': [], 'lines': []}
    ck.customize_summary(context({}, local = {'ck_size_vars': None, 'params': {'compile': {'d': {'XOPENME': None}}}, 'work_path': str(tmp_path)}), summary)
    assert summary['lines'] == []


def test_the_dump_file_is_compared_only_when_the_arrays_are_dumped(ck):
    local = {'ck_dump_file': 'tmp-ck-output-dump.txt'}
    rules = {'files': ['tmp-ck-output-dump.txt', 'tmp-output2.tmp']}
    ck.customize_output_check(context({}, local = local), rules)                  # CK's sizes: dumped
    assert rules['files'] == ['tmp-ck-output-dump.txt', 'tmp-output2.tmp']
    rules = {'files': ['tmp-ck-output-dump.txt', 'tmp-output2.tmp']}
    ck.customize_output_check(context({'n': 8}, local = local), rules)            # an N: not dumped
    assert rules['files'] == ['tmp-output2.tmp']
    rules = {'files': ['tmp-ck-output-dump.txt', 'tmp-output2.tmp']}
    ck.customize_output_check(context({'n': 8, 'dump': 'yes'}, local = local), rules)   # asked for
    assert rules['files'] == ['tmp-ck-output-dump.txt', 'tmp-output2.tmp']


def test_the_run_parameters_of_the_environment_are_in_the_key(ck, tmp_path):
    import yaml
    program = tmp_path / 'shared-codelet-adaptive-filter'
    program.mkdir()
    (program / '_desc.yaml').write_text(yaml.safe_dump({'local_vars': {'run_time_env': {
        'CMETA_TARGETS': '{{global.target.cmeta_targets}}',
        'CT_REPEAT_MAIN': '{{local.params.repeat|1}}',
        'CT_TIME': '{{local.params.time|day}}'}}}))

    def read_file(path):
        with open(path, encoding = 'utf-8') as f:
            return {'return': 0, 'data': yaml.safe_load(f)}

    hook = ck.__class__.__new__(ck.__class__)
    hook.cm = SimpleNamespace(error = lambda msg: {'return': 1, 'error': msg},
                              utils = SimpleNamespace(files = SimpleNamespace(read_file = read_file)))
    base = {'ck_size_vars': None, 'selected-program': {'path': str(program)},
            'params': {'compile': {'d': {'XOPENME': None}}},
            'run_time_env': {'CT_REPEAT_MAIN': '1', 'CT_TIME': 'day'}}
    rules = {}
    hook.customize_output_check(context({}, local = base), rules)
    assert rules['key_values'] == {'repeat': 1, 'time': 'day'}                     # the default, the repeat apart
    ctx = context({}, local = base)
    ctx['tasks']['local']['params']['time'] = 'night'
    rules = {}
    hook.customize_output_check(ctx, rules)
    assert rules['key_values']['time'] == 'night'
    # No folder to read: nothing added (the template's hooks never fail on it)
    rules = {}
    hook.customize_output_check(context({}, local = dict(base, **{'selected-program': {}})), rules)
    assert 'time' not in rules['key_values']
