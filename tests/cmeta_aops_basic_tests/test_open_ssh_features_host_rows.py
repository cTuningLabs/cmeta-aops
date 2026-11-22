"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Offline tests of two extensions of 2026-11-22: tool/open-ssh reports the programs beside the ssh it found
(features.paths: ssh-keygen, scp ... - what a task takes instead of a program looked for by name), and every row of
cx host ls / status says where a host runs (via), a container's engine and the template an instance was made from
(what the hosts page folds the instances under their machine with).
"""

import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def open_ssh_tool():
    """tool/open-ssh's CTool with the tool category's base class replaced by a plain one."""
    path = REPO_ROOT / 'tool' / 'open-ssh' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    line = 'from tool_c393ba5c6fa14f66.api.ctool import InitCTool'
    assert line in src
    src = src.replace(line, 'class InitCTool:\n    def __init__(self, *args, **kwargs):\n        pass')
    ns = {'__name__': 'open_ssh_api', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns['CTool']()


def ctx(uname):
    return {'tasks': {'global': {'host': {'os': {'uname': uname}}}}}


def test_open_ssh_reports_the_programs_beside_ssh(tmp_path):
    tool = open_ssh_tool()
    for name in ('ssh', 'ssh-keygen', 'scp', 'ssh-keyscan'):
        (tmp_path / name).write_text('')
    paths = [{'path': str(tmp_path / 'ssh')}]
    r = tool.check_features(ctx('linux'), paths, {})
    found = r['paths'][0]['features']['paths']
    assert found['bin'] == str(tmp_path)
    assert found['ssh-keygen'] == str(tmp_path / 'ssh-keygen')
    assert found['scp'] == str(tmp_path / 'scp')
    assert found['ssh-keyscan'] == str(tmp_path / 'ssh-keyscan')
    # a program the build does not ship is not reported (never a guess)
    assert 'ssh-agent' not in found and 'sftp' not in found


def test_open_ssh_on_windows_takes_the_exe_files(tmp_path):
    tool = open_ssh_tool()
    for name in ('ssh.exe', 'ssh-keygen.exe', 'ssh-keygen'):
        (tmp_path / name).write_text('')
    paths = [{'path': str(tmp_path / 'ssh.exe')}]
    found = tool.check_features(ctx('windows'), paths, {})['paths'][0]['features']['paths']
    assert found['ssh-keygen'] == str(tmp_path / 'ssh-keygen.exe')


def host_category():
    path = REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'
    spec = importlib.util.spec_from_file_location('host_rows_category', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Category.__new__(module.Category)


def test_the_engine_word_of_a_container_host():
    """A container of this machine runs the engine its tool finds (quoted; detected only - skip_install); a container
    another machine carries keeps the engine's name (that machine's shell finds it); a tool that finds nothing leaves
    the name (2026-11-22)."""
    import types
    cat = host_category()
    g = type(cat)._engine_word.__globals__
    asked = []

    def access(request):
        asked.append(request)
        return {'return': 0, 'path': r'C:\Program Files\Docker\docker.exe'} if request['arg1'].startswith('docker,') else {'return': 16}

    cat.cm = types.SimpleNamespace(access=access, q=lambda p: '"' + p + '"')
    cat._get_host = lambda ctx, alias: {'return': 0, 'host': {'alias': alias}}
    cat._here = lambda h: h['alias'] == 'laptop'
    g['ENGINE_EXE'].clear()
    here = {'alias': 'node-1', 'via': 'laptop', 'desc': {'access': {'engine': 'docker'}}}
    away = {'alias': 'node-2', 'via': 'mac', 'desc': {'access': {'engine': 'docker'}}}
    pod = {'alias': 'node-3', 'desc': {'access': {'engine': 'podman'}}}
    assert cat._engine_word({}, here) == r'"C:\Program Files\Docker\docker.exe"'
    assert asked and asked[0]['skip_install'] is True
    assert cat._engine_word({}, away) == 'docker'
    assert cat._engine_word({}, pod) == 'podman'
    g['ENGINE_EXE'].clear()


def test_host_rows_say_where_a_host_runs():
    cat = host_category()
    instance = {'alias': 'slurm-demo-1', 'type': 'docker', 'machine': 'laptop', 'via': 'laptop-win',
                'desc': {'access': {'container': 'slurm-demo-1', 'engine': 'docker'},
                         'made_from': {'template': 'slurm-node', 'engine': 'docker'}},
                'state': {}, 'cmeta': {'tags': ['made-by-cmeta']}}
    row = cat._row(instance, False)
    assert row['made'] is True
    assert row['via'] == 'laptop-win'
    assert row['engine'] == 'docker'
    assert row['template'] == 'slurm-node'

    declared = {'alias': 'lab-ubuntu', 'type': 'ssh', 'machine': 'lab', 'desc': {'access': {'address': '192.0.2.7'}},
                'state': {}, 'cmeta': {}}
    row = cat._row(declared, False)
    assert row['made'] is False and row['via'] == ''
    assert 'engine' not in row and 'template' not in row
