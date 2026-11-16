"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Programs converted from the Collective Knowledge (CK) format, without hooks of their own: template-ck-program
holds the hooks, select-program gives them to a program that inherits it (and to no other), and the dataset
task returns the files of a dataset in its order, the number it stands for, and a file of them by name.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

TEMPLATE_C_CPU = 'template-c-cpu,649899ef3f004e4a'
TEMPLATE_CK = 'template-ck-program,f7fab3bed78041d1'


# The hooks alone, without the engine

@pytest.fixture(scope='module')
def ck():
    """The template's api_v1.py with InitCProgram replaced by an empty class."""
    path = ROOT / 'program' / 'template-ck-program' / 'api_v1.py'
    source = path.read_text(encoding='utf-8').replace(
        'from program_22788f3c30d04e6d.api.cprogram import InitCProgram', 'class InitCProgram: pass')
    namespace = {'__file__': str(path), '__name__': 'template_ck_program_test'}
    exec(compile(source, str(path), 'exec'), namespace)
    return namespace


def hooks(ck):
    hook = ck['CProgram'].__new__(ck['CProgram'])

    def read_file(path):
        with open(path, encoding='utf-8') as f:
            return {'return': 0, 'data': yaml.safe_load(f)}

    hook.cm = SimpleNamespace(error=lambda msg: {'return': 1, 'error': msg},
                              utils=SimpleNamespace(files=SimpleNamespace(read_file=read_file)))
    return hook


def context(compute, uname='linux', local=None, flags_d='-D'):
    _global = {'target': {'compute': compute}, 'host': {'os': {'uname': uname}},
               'compiler-c': {'features': {'flags': {'d': flags_d}}}}
    _local = {'lang': 'c', 'params': {}}
    _local.update(local or {})
    return {'tasks': {'global': _global, 'local': _local}}


def test_compile_defines_and_flags_follow_the_host_the_target_and_the_compiler(ck):
    hook = hooks(ck)

    # GCC or clang on Linux: GNU C89 for the old sources, no WINDOWS; an empty "d" is tolerated
    ctx = context(['cpu'], local={'ck_legacy_c': True, 'params': {'compile': {'flags': ['-O3'], 'd': None}}})
    assert hook.customize2(ctx)['return'] == 0
    compile_ = ctx['tasks']['local']['params']['compile']
    assert compile_['flags'] == ['-O3'] + ck['LEGACY_C_FLAGS']
    assert compile_['d'] == {}

    # MSVC on Windows: WINDOWS for the CK sources, no GNU flags
    ctx = context(['cpu'], 'windows', {'ck_legacy_c': True}, flags_d='/D')
    assert hook.customize2(ctx)['return'] == 0
    compile_ = ctx['tasks']['local']['params']['compile']
    assert compile_['d'] == {'WINDOWS': None} and 'flags' not in compile_

    # An Android build on a Windows host: its C library is not Windows'
    ctx = context(['android-cpu'], 'windows')
    assert hook.customize2(ctx)['return'] == 0
    assert ctx['tasks']['local']['params']['compile']['d'] == {}


def test_polybench_sizes_and_dump(ck):
    hook = hooks(ck)
    ck_d = {'NI': 1024, 'NJ': 1024, 'POLYBENCH_DUMP_ARRAYS': None}

    def compile_d(**compile_):
        ctx = context(['cpu'], local={'ck_size_vars': ['NI', 'NJ'], 'params': {'compile': dict(compile_, d=dict(ck_d))}})
        r = hook.customize2(ctx)
        return r if r['return'] else ctx['tasks']['local']['params']['compile']['d']

    # CK's sizes: the defines stay and the arrays are dumped
    assert compile_d() == ck_d

    # --compile.size: the header's macro in place of CK's sizes, no dump unless --compile.dump asks for it
    assert compile_d(size='small') == {'SMALL_DATASET': None}
    assert compile_d(size='large', dump='yes') == {'POLYBENCH_DUMP_ARRAYS': None, 'LARGE_DATASET': None}
    assert compile_d(dump='no') == {'NI': 1024, 'NJ': 1024}

    r = compile_d(size='huge')
    assert r['return'] == 1 and 'mini' in r['error']


def test_run_takes_the_dataset_files_in_order_and_its_number(ck, tmp_path):
    hook = hooks(ck)
    files = tmp_path / 'dataset' / 'files'
    files.mkdir(parents=True)
    for name in ('a.txt', 'b.txt', 'c.txt'):
        (files / name).write_text(name)

    def more_files(dataset):
        ctx = context(['cpu'], local={'ck_dataset_more_files': True, 'dataset': dataset})
        assert hook.customize_ck_run(ctx)['return'] == 0
        return ctx['tasks']['local']['input_files']

    # The order of the dataset task's result, else of the dataset's _desc.yaml, else by name
    assert more_files({'path': str(files / 'b.txt'), 'files': ['b.txt', 'c.txt', 'a.txt']}) == \
        {'data1': str(files / 'c.txt'), 'data2': str(files / 'a.txt')}
    assert more_files({'path': str(files / 'a.txt')}) == \
        {'data1': str(files / 'b.txt'), 'data2': str(files / 'c.txt')}
    (tmp_path / 'dataset' / '_desc.yaml').write_text('files: [c.txt, b.txt, a.txt]\n')
    assert more_files({'path': str(files / 'c.txt')}) == \
        {'data1': str(files / 'b.txt'), 'data2': str(files / 'a.txt')}

    # A number for the command line: the dataset's, else the content of its file, else an error
    def number(dataset):
        ctx = context(['cpu'], local={'ck_number_from_dataset': True, 'dataset': dataset})
        r = hook.customize_ck_run(ctx)
        return r if r['return'] else ctx['tasks']['local']['ck_number']

    assert number({'number': ' 42 '}) == '42'
    (tmp_path / 'n.txt').write_text('17\n')
    assert number({'path': str(tmp_path / 'n.txt')}) == '17'
    assert number({})['return'] == 1


def test_run_redirects_and_outputs_follow_the_target(ck):
    hook = hooks(ck)
    local = {'ck_redirect_stdio': True, 'ck_dump_file': 'tmp-ck-output-dump.txt', 'output_files': ['tmp-ck-timer.json']}

    ctx = context(['cpu'], local=dict(local))
    assert hook.customize_ck_run(ctx)['return'] == 0
    _local = ctx['tasks']['local']
    assert _local['ck_redirects'] == '> tmp-output1.tmp 2> tmp-output2.tmp'
    assert _local['output_files'] == ['tmp-ck-timer.json', 'tmp-ck-output-dump.txt', 'tmp-output1.tmp', 'tmp-output2.tmp']

    # An iPhone app has no redirection; --compile.size without --compile.dump writes no dump
    ctx = context(['ios-cpu'], local=dict(local, params={'compile': {'size': 'small'}}))
    assert hook.customize_ck_run(ctx)['return'] == 0
    _local = ctx['tasks']['local']
    assert _local['ck_redirects'] == '' and _local['output_files'] == ['tmp-ck-timer.json']


def test_run_files_are_copied_on_the_host_and_pushed_to_a_device(ck, tmp_path):
    hook = hooks(ck)
    program = tmp_path / 'program'
    (program / 'src').mkdir(parents=True)
    (program / 'src' / 'pubring.pkr').write_text('keys')
    work = tmp_path / 'work'

    def run_files(compute, names, work_path):
        ctx = context(compute, local={'ck_run_files': names, 'work_path': str(work_path),
                                      'selected-program': {'path': str(program)}})
        r = hook.customize_ck_run(ctx)
        return r, ctx['tasks']['local'].get('input_files')

    r, _ = run_files(['cpu'], ['pubring.pkr'], work)
    assert r['return'] == 0 and (work / 'pubring.pkr').read_text() == 'keys'

    r, input_files = run_files(['android-cpu'], ['pubring.pkr'], tmp_path / 'not-made')
    assert r['return'] == 0 and input_files == {'ck-pubring.pkr': str(program / 'src' / 'pubring.pkr')}
    assert not (tmp_path / 'not-made').exists()

    r, _ = run_files(['cpu'], ['missing'], work)
    assert r['return'] == 1


# select-program and the dataset task, through the engine

def make_program(cm, name, desc, api=None):
    r = cm.access({'category': 'program', 'command': 'create', 'arg1': name,
                   'meta': {'constraints': {'supported_compute': ['cpu']}}, 'con': False})
    assert r['return'] == 0, r.get('error')
    root = Path(r['path'])
    (root / '_desc.yaml').write_text(yaml.safe_dump(desc))
    if api:
        (root / 'api_v1.py').write_text(api)
    return root


def select(cm, name):
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'select-program', 'name': name,
                   'compute': 'cpu', 'con': False, 'quiet': True})
    assert r['return'] == 0, r.get('error')
    return r['add_to_local']['selected-program']


def test_a_program_without_hooks_takes_those_of_the_template_it_inherits(cm):
    make_program(cm, 'test-ck-template-user', {'inherits': [TEMPLATE_C_CPU, TEMPLATE_CK]})
    selected = select(cm, 'test-ck-template-user')
    assert hasattr(selected['api_code'], 'customize_ck_run')
    assert selected['api_from'].startswith('template-ck-program')


def test_hooks_of_its_own_are_kept_and_template_c_cpu_alone_gives_none(cm):
    own = ('from program_22788f3c30d04e6d.api.cprogram import InitCProgram\n'
           'class CProgram(InitCProgram):\n'
           '    def __init__(self, *args, **kwargs):\n'
           '        super().__init__(*args, module_file_path=__file__, **kwargs)\n'
           '    def customize_own(self, ctx, **misc):\n'
           '        return {"return": 0}\n')
    make_program(cm, 'test-ck-template-own-hooks', {'inherits': [TEMPLATE_C_CPU, TEMPLATE_CK]}, own)
    selected = select(cm, 'test-ck-template-own-hooks')
    assert hasattr(selected['api_code'], 'customize_own')
    assert not hasattr(selected['api_code'], 'customize_ck_run')
    assert 'api_from' not in selected

    make_program(cm, 'test-ck-template-c-cpu-only', {'inherits': [TEMPLATE_C_CPU]})
    selected = select(cm, 'test-ck-template-c-cpu-only')
    assert selected['api_code'] is None and 'api_from' not in selected


def make_dataset(cm, name, files, desc=None):
    r = cm.access({'category': 'dataset', 'command': 'create', 'arg1': name, 'con': False})
    assert r['return'] == 0, r.get('error')
    root = Path(r['path'])
    (root / 'files').mkdir()
    for f in files:
        (root / 'files' / f).write_text(f)
    if desc is not None:
        (root / '_desc.yaml').write_text(yaml.safe_dump(desc))
    return root


def dataset(cm, name, **params):
    r = cm.access(dict({'category': 'task', 'command': 'run', 'arg1': 'dataset', 'name': name,
                        'con': False, 'quiet': True}, **params))
    assert r['return'] == 0, r.get('error')
    return r


def test_dataset_files_in_their_order_its_number_and_a_file_by_name(cm):
    root = make_dataset(cm, 'test-ck-dataset-files', ['a.txt', 'b.txt', 'c.txt'],
                        {'files': ['c.txt', 'a.txt'], 'number': 7})
    r = dataset(cm, 'test-ck-dataset-files')
    assert r['files'] == ['c.txt', 'a.txt', 'b.txt']
    assert os.path.samefile(r['path'], root / 'files' / 'c.txt')
    assert os.path.samefile(r['path_files'], root / 'files')
    assert r['number'] == '7'
    assert r['artifact_au'].startswith('test-ck-dataset-files')

    r = dataset(cm, 'test-ck-dataset-files', filename='b.txt')
    assert os.path.samefile(r['path'], root / 'files' / 'b.txt')


def test_a_dataset_without_a_description_is_as_before(cm):
    root = make_dataset(cm, 'test-ck-dataset-plain', ['z.txt', 'y.txt'])
    r = dataset(cm, 'test-ck-dataset-plain')
    assert os.path.samefile(r['path'], root / 'files' / 'y.txt')
    assert r['files'] == ['y.txt', 'z.txt'] and 'number' not in r
