"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the reference outputs (category program.output) that compile-and-run-program records and compares
(--check_output): the rules of a program, the key of a case, the comparison of a file, a case written and found.
"""

import hashlib
import json
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
          '__name__': 'output_check_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_the_rules_of_a_program_and_of_a_command(carp):
    desc = {'output_check': {'files': ['a.out'], 'skip': ['tmp-output2.tmp'], 'tolerance': 0.01},
            'updates_cmd': {'encode': {'output_check': {'skip': ['a.sig'], 'key_params': ['compile.size']}}}}
    assert carp['output_check_rules'](desc) == {'files': ['a.out'], 'skip': ['tmp-output2.tmp'], 'tolerance': 0.01}
    assert carp['output_check_rules'](desc, 'encode') == {'files': ['a.out'], 'skip': ['tmp-output2.tmp', 'a.sig'],
                                                           'tolerance': 0.01, 'key_params': ['compile.size']}
    assert carp['output_check_rules']({}, 'x') == {}

    # The files compared: the rules' files, else the output files minus what the run printed and its times, minus skip
    local = {'output_files': ['tmp-ck-timer.json', 'tmp-output.tmp', 'tmp-output1.tmp', 'tmp-output2.tmp', 'image.bin']}
    assert carp['output_files_of']({}, local) == ['tmp-output.tmp', 'image.bin']
    assert carp['output_files_of']({'skip': ['image.bin']}, local) == ['tmp-output.tmp']
    assert carp['output_files_of']({'files': ['tmp-output1.tmp']}, local) == ['tmp-output1.tmp']


def test_the_key_of_a_case_and_what_makes_two_keys_the_same(carp):
    local = {'dataset': {'artifact_au': 'ctuning-image-ppm,1234', 'sub_dataset': 'image-ppm-0007', 'path': '/x/image-ppm-0007/data.ppm'}}
    params = {'compile': {'size': 'large', 'dump': True}, 'n': 3}
    key = carp['output_key']({'key_params': ['compile.size', 'compile.dump', 'n', 'missing.one']}, 'prog', 'default', local, params)
    assert key == {'program': 'prog', 'cmd': 'default', 'dataset': 'ctuning-image-ppm', 'sub_dataset': 'image-ppm-0007',
                   'dataset_file': 'data.ppm', 'params': {'compile.size': 'large', 'compile.dump': True, 'n': 3, 'missing.one': None}}
    assert carp['output_key']({}, 'prog', None, {}, {}) == {'program': 'prog', 'cmd': 'default', 'dataset': None, 'sub_dataset': None,
                                                           'dataset_file': None, 'params': {}}
    same = carp['same_key']
    assert same(key, json.loads(json.dumps(key)))
    assert same({'program': 'p', 'cmd': 'default', 'params': {'n': 3}}, {'program': 'p', 'cmd': 'default', 'params': {'n': '3'}})   # typed or written
    assert not same(key, dict(key, sub_dataset = 'image-ppm-0008'))
    assert not same(key, dict(key, params = dict(key['params'], n = 4)))


def test_a_file_against_its_reference(carp, tmp_path):
    run = tmp_path / 'run'
    ref = tmp_path / 'ref'
    run.mkdir()
    ref.mkdir()
    compare = carp['compare_output']
    digests = carp['output_digests']

    (ref / 'out.txt').write_bytes(b'a 1.000\nb 2.500\n')
    record = digests(str(ref / 'out.txt'))
    (run / 'out.txt').write_bytes(b'a 1.000\nb 2.500\n')
    assert compare(str(run / 'out.txt'), record, str(ref / 'out.txt'), None) == ('ok', 'the same')
    (run / 'out.txt').write_bytes(b'a 1.000\r\nb 2.500\r\n')                          # Windows line ends
    assert compare(str(run / 'out.txt'), record, None, None) == ('ok', 'the same but for the line ends')
    (run / 'out.txt').write_bytes(b'a 1.000\nb 2.501\n')
    status, why = compare(str(run / 'out.txt'), record, str(ref / 'out.txt'), None)   # no tolerance: differs
    assert status == 'differs' and 'bytes' in why
    status, why = compare(str(run / 'out.txt'), record, str(ref / 'out.txt'), 0.001)  # within the tolerance
    assert status == 'ok' and 'within 0.001' in why
    status, why = compare(str(run / 'out.txt'), record, str(ref / 'out.txt'), 0.0001)
    assert status == 'differs' and 'number 2' in why
    (run / 'out.txt').write_bytes(b'a 1.000\nc 2.500\n')
    assert compare(str(run / 'out.txt'), record, str(ref / 'out.txt'), 0.1) == ('differs', 'the text around the numbers differs')
    status, why = compare(str(run / 'out.txt'), record, None, 0.1)                     # the reference file not kept
    assert status == 'differs' and 'digests alone' in why
    assert compare(str(run / 'none.txt'), record, None, None) == ('missing', 'the run made no such file')
    (ref / 'nan.txt').write_bytes(b'x -nan(ind) y\n')
    (run / 'nan.txt').write_bytes(b'x nan y\n')
    assert compare(str(run / 'nan.txt'), digests(str(ref / 'nan.txt')), None, None) == ('ok', 'the same but for the spelling of NaN')


def test_a_case_written_and_found_by_its_key(carp, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'out.txt').write_bytes(b'result\n')
    (work / 'big.bin').write_bytes(b'\0' * 2000)
    artifact = tmp_path / 'program.output' / 'prog'
    key = {'program': 'prog', 'cmd': 'default', 'dataset': 'ds', 'sub_dataset': 'in-1', 'dataset_file': 'data.txt', 'params': {}}
    case = carp['write_case'](str(artifact / 'abcd'), key, {'date': 'now'}, ['out.txt', 'big.bin', 'gone.txt'], str(work), kept_max = 1000)
    assert case['files']['out.txt']['kept'] is True and (artifact / 'abcd' / 'out.txt').read_bytes() == b'result\n'
    assert case['files']['big.bin']['kept'] is False and not (artifact / 'abcd' / 'big.bin').exists()   # too big: the digests alone
    assert case['files']['gone.txt'] is None
    assert case['files']['out.txt']['sha256'] == hashlib.sha256(b'result\n').hexdigest()
    assert json.loads((artifact / 'abcd' / 'case.json').read_text())['key'] == key

    found = carp['find_case']([str(artifact)], key)
    assert found and found['folder'] == str(artifact / 'abcd') and found['case']['recorded'] == {'date': 'now'}
    assert carp['find_case']([str(artifact)], dict(key, sub_dataset = 'in-2')) is None
    assert carp['find_case']([str(tmp_path / 'nowhere')], key) is None
