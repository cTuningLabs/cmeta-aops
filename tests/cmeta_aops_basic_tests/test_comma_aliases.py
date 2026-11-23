"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Names whose alias holds commas and spaces (2026-11-23): cMeta splits a name at its LAST comma, and the part after it
is the UID only when it is one (16 hex digits, either case; kept in lower case) - otherwise the whole text is the alias:
"Kim Doe, joined Example Co, 20260922,5ca1ab1e5ca1ab1e" is that alias and that UID. Every place of aops that took the
text before the first comma reads a name that way now (cmeta.utils.names.parse_cmeta_name, or the same rule where a
module stays plain Python); plain aliases and alias,UID read as before. A list whose items may be references reads as
the engine reads a list of ai_uses names. Offline: the modules are loaded without the engine where they can be, with
stand-ins for what they ask of it; the engine's name rule is the real one.
"""

import importlib.util
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import types
import urllib.parse
from types import SimpleNamespace

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

UID = '5ca1ab1e5ca1ab1e'
UPPER = UID.upper()
CAT = '0ddba11c0ddba11c'
OTHER = '0123456789abcdef'
ALIAS = 'Kim Doe, joined Example Co, 20260922'
KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOv2xbm5Yx5tSdyFiK0gYn6kSPW0C3ZoD2b0CtEhKsZm test@example'


def module_of(rel_path, name):
    """A module of the repository loaded from its file (the category modules import cmeta, which the suite has)."""
    spec = importlib.util.spec_from_file_location(name, str(REPO_ROOT / rel_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_of(rel_path, replacements, name, **names):
    """A module's namespace with lines of its source replaced: the imports it cannot make without the engine."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding='utf-8')
    for line, new in replacements.items():
        assert line in src, line
        src = src.replace(line, new)
    ns = {'__name__': name, '__file__': str(path), **names}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return path


def read_yaml(path, **kwargs):
    """utils.files.safe_read_file of the engine for a YAML file."""
    with open(path, encoding='utf-8') as f:
        return {'return': 0, 'data': yaml.safe_load(f) or {}}


# ---------------------------------------------------------------------------------------------- the task category API
@pytest.mark.parametrize('project, expected', [
    (f'work,{CAT}::{ALIAS},{UID}', f'{CAT}::{UID}'),                    # an alias with commas
    (f'work,{CAT.upper()}::{ALIAS},{UPPER}', f'{CAT}::{UID}'),          # UIDs in capitals: kept in lower case
    (f'work , {CAT}::{ALIAS} , {UID}', f'{CAT}::{UID}'),                # spaces around the last comma
    (f'{CAT}::{UID}', f'{CAT}::{UID}'),                                 # UIDs alone
    (f'work,{CAT}::demo:{ALIAS},{UID}', f'{CAT}::{UID}'),                # a repository before the alias
    (f'work,{CAT}::my-work,{UID}', f'{CAT}::{UID}'),                    # as before
    (f'work,{CAT}::Kim,{OTHER}', f'{CAT}::{OTHER}'),                   # an alias ending in ,<16 hex> reads as alias,UID
    (f'work,{CAT}::{ALIAS}', None),                                     # no UID: the project is left out
    (f'work::{ALIAS},{UID}', None),
])
def test_the_run_record_names_the_project_by_its_uids(ctask_helpers, monkeypatch, project, expected):
    record = ctask_helpers('ai_run_record')['ai_run_record']
    monkeypatch.setenv('CMETA_AI_RUN', 'project=' + urllib.parse.quote(project, safe='') + ';run=r1')
    assert record('claude')['ai_run'].get('project') == expected
    monkeypatch.setenv('CMETA_AI_RUN', 'run=r1')
    assert 'project' not in record('claude')['ai_run']


class OnCM:
    """The engine as --on sees it for a host artifact: find the host, run the words there."""

    def __init__(self):
        self.calls = []
        self.utils = SimpleNamespace(files=SimpleNamespace(
            safe_read_yaml_or_json=lambda path: {'return': 0, 'data': {'os': 'ubuntu', 'type': 'ssh'}}))

    def access(self, i):
        self.calls.append(dict(i))
        if i['category'].startswith('host,') and i['command'] == 'find':
            return {'return': 0, 'artifacts': [{'path': '/hosts/' + i['arg1'], 'cmeta_ref_parts': {'artifact_alias': i['arg1']}}]}
        if i['category'].startswith('host,') and i['command'] == 'run':
            return {'return': 0, 'outputs': {i['arg1']: {'returncode': 0, 'stdout': '', 'stderr': ''}}}
        raise AssertionError(f'unexpected call: {i}')

    def error(self, text):
        return {'return': 1, 'error': text}


@pytest.fixture(scope='module')
def task_api():
    return module_of('category/task/api/v2.py', 'task_api_v2_comma_aliases')


@pytest.mark.parametrize('words, screen', [
    ([f'{ALIAS},{UID}'], ALIAS), ([f'demo:{ALIAS},{UPPER}'], ALIAS), ([ALIAS], ALIAS), ([f'{ALIAS} , {UID}'], ALIAS),
    ([UID], UID), ([UPPER], UID), (['run-ai'], 'run-ai'), ([f'run-ai,{OTHER}'], 'run-ai'), ([f'Kim,{OTHER}'], 'Kim'),
    ([], 'cx-task')])
def test_the_default_screen_is_named_by_the_whole_alias(task_api, monkeypatch, words, screen):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    c = task_api.Category.__new__(task_api.Category)
    c.cm = OnCM()
    c.cmeta = {'artifact': 'c36be4b9314a45e0'}
    ctx = {'origin': {'cli': {'cmd': ['task', 'run'] + words + ['--on=lab', '--on_screen']}}}
    r = c._run_on(ctx, {'on_screen': True}, 'lab', True, False, False)
    assert r['return'] == 0 and r['run_on']['screen'] == screen
    assert [i['screen'] for i in c.cm.calls if i['command'] == 'run'] == [screen]


@pytest.fixture(scope='module')
def bi():
    return module_of('category/task/api/build_identity.py', 'build_identity_comma_aliases')


def test_a_build_entry_of_a_program_with_commas_keeps_its_whole_alias(bi, cm):
    cache = 'cache,1ebdcc1cc30c4022'
    alias, uid = 'Kim Doe, joined Example Co, a program', 'fedcba9876543211'

    plain = bi.request_identity({}, {}, ['cpu'])
    r = bi.find_or_create_entry(cm, cache, alias, uid, plain)
    assert r['return'] == 0 and r['created'] and r['alias'] == 'task--program--' + alias
    cuda = bi.request_identity({}, {}, ['cuda'])
    r2 = bi.find_or_create_entry(cm, cache, alias, uid, cuda)
    assert r2['created'] and r2['alias'] == f"task--program--{alias}--{r2['uid']}"

    # what the entries were made as: the same aliases and UIDs as those returned
    for made in (r, r2):
        found = cm.access({'category': cache, 'command': 'find', 'arg1': made['uid'], 'con': False})
        parts = found['artifacts'][0]['cmeta_ref_parts']
        assert (parts['artifact_alias'], parts['artifact_uid']) == (made['alias'], made['uid'])
    entries = bi.find_entries(cm, cache, alias, uid)['entries']
    assert {e['alias'] for e in entries} == {r['alias'], r2['alias']}
    assert bi.find_or_create_entry(cm, cache, alias, uid, plain)['path'] == r['path']      # found again by its request


# ---------------------------------------------------------------------------------------------- host, machine, container, secret
@pytest.fixture(scope='module')
def host_api():
    return module_of('category/host/api/v1.py', 'host_category_comma_aliases')


@pytest.mark.parametrize('ref, alias', [
    (f'host,{CAT}::{ALIAS},{UID}', ALIAS), (f'{ALIAS},{UPPER}', ALIAS), (f'{ALIAS} , {UID}', ALIAS), (ALIAS, ALIAS),
    (UID, UID), (UPPER, UID), (f',{UID}', UID), (f'demo:{ALIAS},{UID}', f'demo:{ALIAS}'), (f'Kim,{OTHER}', 'Kim'),
    (f'machine,{CAT}::my-pc,{OTHER}', 'my-pc'), ('my-pc', 'my-pc'), (f'my-pc,{OTHER}', 'my-pc'),      # as before
    ('', None), (None, None)])
def test_a_host_names_its_parent_and_its_machine_by_the_whole_alias(host_api, ref, alias):
    assert host_api.Category._ref_alias(ref) == alias


def test_a_loaded_host_keeps_the_whole_aliases_of_its_parents_and_machine(host_api, tmp_path):
    h = host_api.Category.__new__(host_api.Category)
    h.cm = SimpleNamespace(utils=SimpleNamespace(files=SimpleNamespace(safe_read_file=read_yaml)))
    h.logger = None
    h._host_cache = {}

    phone = put(tmp_path / 'phone' / '_desc.yaml', yaml.safe_dump({
        'type': 'adb', 'via': [f'host,{CAT}::{ALIAS},{UID}', 'lab-pc'], 'machine': f'machine,{CAT}::Lab PC, rack 2,{OTHER}'})).parent
    loaded = h._load_host({'path': str(phone), 'cmeta_ref_parts': {'artifact_alias': 'phone', 'artifact_uid': OTHER}})
    assert loaded['via_list'] == [ALIAS, 'lab-pc'] and loaded['via'] == ALIAS and loaded['machine'] == 'Lab PC, rack 2'

    instance = put(tmp_path / 'instance' / '_desc.yaml', yaml.safe_dump({'type': 'docker', 'via': f'host,{CAT}::{ALIAS},{UPPER}'})).parent
    loaded = h._load_host({'path': str(instance), 'cmeta_ref_parts': {'artifact_alias': 'instance'}})
    assert loaded['via'] == ALIAS and loaded['via_list'] == [ALIAS] and loaded['machine'] is None


def test_the_uid_at_the_end_of_an_artifact_pattern(host_api):
    cut = lambda text: host_api.UID_SUFFIX.sub('', text)
    assert cut(f'{ALIAS},{UID}') == ALIAS and cut(f'{ALIAS},{UPPER}') == ALIAS and cut(f'{ALIAS} , {UID}') == ALIAS
    assert cut(ALIAS) == ALIAS and cut(UID) == UID and cut('work::2026*') == 'work::2026*'
    assert cut(f'demo.project,{CAT}') == 'demo.project'                                    # as before


@pytest.fixture(scope='module')
def machine_api():
    return module_of('category/machine/api/v1.py', 'machine_category_comma_aliases')


def test_the_hosts_of_a_machine_whose_alias_holds_commas(machine_api, tmp_path):
    refs = {'h1': f'machine,{CAT}::Lab PC, rack 2,{UID}', 'h2': 'Lab PC, rack 2', 'h3': UID, 'h4': UPPER,
            'h5': 'old-pc', 'h6': f'machine::old-pc,{OTHER}', 'h7': f'machine,{CAT}::Lab PC,{OTHER}'}
    hosts = []
    for name, ref in refs.items():
        put(tmp_path / name / '_desc.yaml', yaml.safe_dump({'type': 'ssh', 'machine': ref}))
        hosts.append({'path': str(tmp_path / name), 'cmeta_ref_parts': {'artifact_alias': name}})
    m = machine_api.Category.__new__(machine_api.Category)
    m.cm = SimpleNamespace(access=lambda i: {'return': 0, 'artifacts': hosts},
                           utils=SimpleNamespace(files=SimpleNamespace(safe_read_file=read_yaml)),
                           catch_error=lambda r: r.get('return', 0) > 0, error=lambda text: {'return': 1, 'error': text})
    m.cmeta = {'uses_categories': {'host': 'host,e4e49c251c814f6d'}}
    m.logger = None

    by = m._hosts_by_machine({})['by_machine']
    assert by['Lab PC, rack 2'] == ['h1', 'h2'] and by[UID] == ['h3', 'h4'] and by['Lab PC'] == ['h7']
    assert by['old-pc'] == ['h5', 'h6']                                                   # as before

    machines = [{'alias': 'Lab PC, rack 2', 'uid': UID, 'path': '/m/rack', 'desc': {'owner': 'demo'}},
                {'alias': 'Lab PC', 'uid': CAT, 'path': '/m/lab', 'desc': {}},
                {'alias': 'old-pc', 'uid': OTHER, 'path': '/m/old', 'desc': {}}]
    m._select = lambda ctx, arg1=None, *rest: {'return': 0, 'machines': [x for x in machines if arg1 in (None, x['alias'])]}
    listed = {x['alias']: x['hosts'] for x in m.list_({'control': {'con': False}})['machines']}
    assert listed == {'Lab PC, rack 2': ['h1', 'h2', 'h3', 'h4'], 'Lab PC': ['h7'], 'old-pc': ['h5', 'h6']}
    assert m.show_({'control': {'con': False}}, arg1='Lab PC, rack 2')['machine']['hosts'] == ['h1', 'h2', 'h3', 'h4']


@pytest.fixture(scope='module')
def container_api():
    return module_of('category/container/api/v1.py', 'container_category_comma_aliases')


@pytest.mark.parametrize('artifact, alias', [
    (f'{ALIAS},{UID}', ALIAS), (f'{ALIAS},{UPPER}', ALIAS), (f'{ALIAS} , {UID}', ALIAS),
    (f'ctuninglabs@cmeta-aops,{OTHER}', 'ctuninglabs@cmeta-aops'),                       # as before
    (ALIAS, 'the-folder'), (UID, 'the-folder'), ('', 'the-folder')])                      # no alias,UID: the folder's name, as before
def test_a_repository_given_to_a_container_keeps_its_whole_alias(container_api, tmp_path, artifact, alias):
    folder = tmp_path / 'the-folder'
    folder.mkdir()
    c = container_api.Category.__new__(container_api.Category)
    c.cm = SimpleNamespace(access=lambda i: {'return': 0, 'artifacts': [{'path': str(folder), 'meta': {'artifact': artifact}}]})
    assert c._repo_path('the repository') == {'return': 0, 'path': str(folder), 'alias': alias}


def test_a_repository_copied_into_an_image_is_one_word_for_copy_and_run(container_api):
    bake = container_api.Category._bake_lines
    assert bake('cmeta', '/home/cmeta', 'ctuninglabs@cmeta-aops') == [                    # as before
        'COPY --chown=cmeta repos/ctuninglabs@cmeta-aops.tar.gz /tmp/repo.tar.gz',
        'RUN mkdir -p /home/cmeta/repos/ctuninglabs@cmeta-aops && tar -xzf /tmp/repo.tar.gz -C '
        '/home/cmeta/repos/ctuninglabs@cmeta-aops && rm -f /tmp/repo.tar.gz']
    for alias in (ALIAS, "O'Brien, laptop", 'Data, A & B', 'data,b'):
        copy, run = bake('cmeta', '/home/cmeta', alias)
        source = copy[len('COPY --chown=cmeta '):]
        assert (json.loads(source) if source.startswith('[') else source.split()) == [f'repos/{alias}.tar.gz', '/tmp/repo.tar.gz']
        words = shlex.split(run[len('RUN '):])
        assert words[:3] == ['mkdir', '-p', f'/home/cmeta/repos/{alias}'] and words[words.index('-C') + 1] == f'/home/cmeta/repos/{alias}'


def test_two_spellings_of_one_place_compare_equal():
    secret = module_of('category/secret/api/v1.py', 'secret_category_comma_aliases')
    want = ('demo.project', ALIAS.lower(), 'memory/a.md')
    for ref in (f'demo.project,{CAT}::{ALIAS},{UID}/memory/a.md', f'demo.project,{CAT.upper()}::{ALIAS},{UPPER}/memory/a.md',
                f'demo.project::{ALIAS}/memory/a.md/', f'demo.project , {CAT}::{ALIAS} , {UID}\\memory\\a.md'):
        assert secret._ref_key(ref) == want, ref
    assert secret._ref_key('demo.project::cMeta/!AI') == ('demo.project', 'cmeta', '!AI')          # as before
    assert secret._ref_key(f'demo.project::Kim,{OTHER}') == ('demo.project', 'kim', '')          # ,<16 hex> reads as a UID
    assert secret._ref_key('') == ('', '', '')


# ---------------------------------------------------------------------------------------------- programs and tools
@pytest.fixture(scope='module')
def carp():
    lines = ['from task_c36be4b9314a45e0.api.ctask import InitCTask\n', 'from task_c36be4b9314a45e0.api import deadlines\n',
             'from task_c36be4b9314a45e0.api import build_stamp\n', 'from task_c36be4b9314a45e0.api import build_identity\n',
             'from task_c36be4b9314a45e0.api import provenance\n']
    stub = SimpleNamespace()
    return source_of('task/compile-and-run-program/api_v1.py', {line: '' for line in lines}, 'carp_comma_aliases',
                     InitCTask=object, deadlines=stub, build_stamp=stub, build_identity=stub, provenance=stub)


def test_the_output_check_keeps_two_datasets_apart(carp):
    # artifact_au as the engine's select_artifact gives it: the alias, else the UID - never alias,UID
    dataset = lambda au: carp['output_key']({}, 'prog', None, {'dataset': {'artifact_au': au}}, {})['dataset']
    assert dataset('images, set A') == 'images, set A' and dataset(ALIAS) == ALIAS and dataset(UID) == UID
    assert dataset('ctuning-image-ppm') == 'ctuning-image-ppm' and dataset('') is None
    a = carp['output_key']({}, 'prog', None, {'dataset': {'artifact_au': 'images, set A', 'path': '/d/a/data.pgm'}}, {})
    b = carp['output_key']({}, 'prog', None, {'dataset': {'artifact_au': 'images, set B', 'path': '/d/b/data.pgm'}}, {})
    assert not carp['same_key'](a, b)


def test_only_the_task_dataset_takes_the_programs_dataset_params(carp):
    names = ['dataset', f'dataset,{UID}', f'dataset,{UPPER}', f'dataset , {UID}',
             'dataset, legacy', f'dataset, legacy,{UID}', UID, 'other', 'repo:dataset', '']
    steps = [{'task': n} for n in names] + ['not a step']
    carp['CTask'].dataset_steps_take_the_programs_params(steps)
    took = {s['task'] for s in steps if isinstance(s, dict) and s.get('name') == '{{params.dataset|$None}}'}
    assert took == {'dataset', f'dataset,{UID}', f'dataset,{UPPER}', f'dataset , {UID}'}


class Anything:
    """A stand-in for the modules of the setup task: any function, doing nothing."""
    CACHE_CATEGORY = 'cache,1ebdcc1cc30c4022'

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def test_the_sizes_of_a_tool_are_found_by_its_whole_alias(monkeypatch, tmp_path):
    imports = {'from task_c36be4b9314a45e0.api.ctask import InitCTask, ask': 'InitCTask = object; ask = None'}
    imports.update({f'from . import {m}\n': '' for m in ('build', 'common', 'detect', 'install', 'upgrade')})
    setup = source_of('task/setup/api_v1.py', imports, 'setup_comma_aliases',
                      build=Anything(), common=Anything(), detect=Anything(), install=Anything(), upgrade=Anything())

    sizes = types.ModuleType('tool_c393ba5c6fa14f66.api.common_sizes')
    sizes.records_from_cache = lambda entries: [{'entry': e} for e in entries]
    sizes.load_sizes = lambda path: []
    sizes.suggest_rules = lambda records: {}
    api = types.ModuleType('tool_c393ba5c6fa14f66.api')
    api.common_sizes = sizes
    monkeypatch.setitem(sys.modules, 'tool_c393ba5c6fa14f66', types.ModuleType('tool_c393ba5c6fa14f66'))
    monkeypatch.setitem(sys.modules, 'tool_c393ba5c6fa14f66.api', api)
    monkeypatch.setitem(sys.modules, 'tool_c393ba5c6fa14f66.api.common_sizes', sizes)

    t = setup['CTask'].__new__(setup['CTask'])
    t.category_uid, t.artifact_uid = 'c36be4b9314a45e0', 'a2f9b61079ce4333'
    # the cache entries of a tool carry params.name = its artifact_au (task setup, init): its alias, else its UID
    stored = {ALIAS: '/cache/a', 'python': '/cache/b', UID: '/cache/c'}

    def access(i):
        path = stored.get(i['match']['params']['name'])
        return {'return': 0, 'artifacts': [{'path': path}]} if path else {'return': 16}

    t.cm = SimpleNamespace(access=access)
    for au in stored:
        r = t.report_sizes({'control': {'con': False}}, {}, {'artifact_au': au, 'artifact_path': str(tmp_path)})
        assert r['return'] == 0 and r['records'] == [{'entry': stored[au]}], au


def test_an_upgrade_names_the_tools_it_is_set_up_through_by_their_whole_aliases(capsys):
    path = REPO_ROOT / 'task' / 'setup' / 'upgrade.py'
    up = types.ModuleType('setup_upgrade_comma_aliases')
    up.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), up.__dict__)
    uses = [{'task': 'setup,a2f9b61079ce4333', 'name': f'{ALIAS},{UID}'}, {'task': 'setup', 'name': f'python,{UPPER}'},
            {'task': 'setup', 'name': UID}, {'task': 'download-file', 'name': 'not-a-tool'}]
    old = {'path': '/opt/tool', 'version': '1.0'}
    out = up.upgrade_tool(SimpleNamespace(), {'control': {'con': True}}, old,
                          tool_read={'desc': {'uses': uses}, 'artifact_print_name': 'my-tool', 'space': ''},
                          _upgrade_channels={'primary': up.CHANNEL_NONE, 'upgrade_cmd': None})
    assert out['last_upgrade']['skipped'] == 'no upgrade procedure'
    assert f'it is set up through {ALIAS}, python, {UID}: upgrade that tool instead' in capsys.readouterr().out


def test_a_running_llama_server_serves_the_model_named_by_its_whole_alias(task_namespace):
    serves = task_namespace('run-llama-cpp-server')['CTask']._serves
    rec = {'model': f'{ALIAS}, Q4,{UID}'}
    assert serves(rec, f'{ALIAS}, Q4', []) and serves(rec, f'{ALIAS}, Q4,{UPPER}', []) and serves(rec, f'{ALIAS}, Q4 , {UID}', [])
    assert not serves(rec, f'{ALIAS}, Q8', []) and not serves(rec, ALIAS, [])
    assert serves({'model': 'hf-Qwen@Qwen3-8B-GGUF'}, f'hf-Qwen@Qwen3-8B-GGUF,{OTHER}', [])       # as before
    assert serves({'model': UID}, UPPER, [])
    router = {'models': [f'{ALIAS}, Q4,{UID}', 'small,' + OTHER], 'router': True}
    assert serves(router, None, [f'{ALIAS}, Q4', 'small']) and not serves(router, None, [f'{ALIAS}, Q8', 'small'])
    assert not serves({}, ALIAS, [])


# ---------------------------------------------------------------------------------------------- hosts and sync
def test_sync_names_a_host_by_its_whole_alias(task_namespace):
    label = task_namespace('sync')['host_label']
    assert label(f'host,{CAT}::{ALIAS},{UID}') == ALIAS and label(f'host::{ALIAS}') == ALIAS
    assert label(f'{ALIAS},{UPPER}') == ALIAS and label(f'host::{ALIAS} , {UID}') == ALIAS
    assert label(f'host::my-vm,{OTHER}') == 'my-vm' and label('my-vm') == 'my-vm'                    # as before
    assert label(UID) == UID and label(f'host::{UPPER}') == UID and label(None) == 'None'


def test_the_hosts_of_a_round_keep_a_list_whole(task_namespace):
    ns = task_namespace('test-on-hosts')
    config = {'hosts': [f'{ALIAS},{UID}', ' docker:debian ', '', 'here']}
    cm = SimpleNamespace(access=lambda i: {'return': 0, 'config_cmeta': config})
    assert ns['default_hosts'](cm) == [f'{ALIAS},{UID}', 'docker:debian', 'here']
    assert ns['host_refs'](None, cm) == [f'{ALIAS},{UID}', 'docker:debian', 'here']
    assert ns['host_refs']([f'{ALIAS},{UID}', 'my-pc'], cm) == [f'{ALIAS},{UID}', 'my-pc']       # --hosts,=...: a list
    assert ns['host_refs']('my-pc, docker:ubuntu', cm) == ['my-pc', 'docker:ubuntu']                # a text: commas, as before
    config['hosts'] = 'lab-1,lab-2'
    assert ns['default_hosts'](cm) == 'lab-1,lab-2' and ns['host_refs']('', cm) == ['lab-1', 'lab-2']
    config['hosts'] = []
    assert ns['default_hosts'](cm) == 'here' and ns['host_refs'](None, cm) == ['here']
    config.pop('hosts')
    assert ns['host_refs'](None, cm) == ['here']


def test_an_artifact_mount_names_its_category_with_or_without_a_uid(task_namespace, tmp_path):
    CTask = task_namespace('get-host--docker')['CTask']
    t = CTask.__new__(CTask)
    asked = []

    def access(i):
        asked.append(i)
        folder = tmp_path / 'artifacts' / str(len(asked))
        folder.mkdir(parents=True, exist_ok=True)
        return {'return': 0, 'artifact': {'path': str(folder), 'cmeta': {'artifact': UID}}}

    t.cm = SimpleNamespace(access=access)
    for cref, category, arg1 in [(f'state,{UPPER}::x', 'state,a1ed1ed7ca7043b6', 'x'),
                                 (f'result,{CAT}::{ALIAS}', 'result,6567e4df4d04488a', ALIAS),
                                 (f'state , {UID}::x/sub', 'state,a1ed1ed7ca7043b6', 'x'),
                                 ('cache::x', 'cache,1ebdcc1cc30c4022', 'x')]:                      # as before
        mounts = t._artifact_mounts({'m': cref}, '/home/cmeta')
        assert [m['cref'] for m in mounts] == [cref] and (asked[-1]['category'], asked[-1]['arg1']) == (category, arg1)
    for cref in ('result, other::x', f'{CAT}::x', '::x'):
        with pytest.raises(ValueError):
            t._artifact_mounts({'m': cref}, '/home/cmeta')


# ---------------------------------------------------------------------------------------------- projects and websites
def test_a_project_definition_names_its_category_with_or_without_a_uid(task_namespace, tmp_path):
    CTask = task_namespace('manage-cmeta-project')['CTask']
    t = CTask.__new__(CTask)
    asked = []
    t.cmeta = {'uses_categories': {'website': 'website,1111222233334444', 'task': 'task,c36be4b9314a45e0'}}
    t.cm = SimpleNamespace(access=lambda i: asked.append(i) or {'return': 1, 'error': 'stop here'},
                           catch_error=lambda r, fail16=False: r.get('return', 0) > 0,
                           error=lambda text: {'return': 1, 'error': text})
    for definition, category, arg1 in [(f'website,{CAT}::{ALIAS}', 'website,1111222233334444', ALIAS),
                                       (f'task,{UPPER}::{ALIAS},{UID}', 'task,c36be4b9314a45e0', f'{ALIAS},{UID}'),
                                       ('website::my-site', 'website,1111222233334444', 'my-site'),
                                       ('my-site', 'website,1111222233334444', 'my-site')]:
        asked.clear()
        r = t.run({}, project_home=str(tmp_path), definition=definition)
        assert r == {'return': 1, 'error': 'stop here'} and [(a['category'], a['arg1']) for a in asked] == [(category, arg1)]
    for definition in ('website, other::x', f'{CAT}::x'):
        r = t.run({}, project_home=str(tmp_path), definition=definition)
        assert r['return'] == 1 and 'website or task' in r['error']


@pytest.fixture(scope='module')
def runtime():
    return module_of('task/manage-cmeta-project/runtime.py', 'project_runtime_comma_aliases')


def test_the_project_runtime_reads_categories_and_names_whole(runtime, tmp_path):
    name = runtime.name_alias
    assert name(f'{ALIAS},{UID}') == ALIAS and name(f'{ALIAS} , {UPPER}') == ALIAS and name(ALIAS) == ALIAS
    assert name(UPPER) == UID and name('state') == 'state' and name(f'my-repo,{OTHER}') == 'my-repo'

    categories = {'state': 'state,a1ed1ed7ca7043b6', 'website': 'website,1111222233334444', 'task': 'task,c36be4b9314a45e0'}
    state = tmp_path / 'state'
    state.mkdir()
    cm = SimpleNamespace(access=lambda i: {'return': 0, 'artifact': {'path': str(state)}})
    for ref in ('state::local:website-x', f'state,{UPPER}::local:website-x', f'state , {UID}::x'):
        assert runtime.instance_state(cm, categories, {'state': ref}) == state.resolve()
    for ref in ('state, other::x', f'{UID}::x', 'result::x', 'state::a/b'):
        with pytest.raises(ValueError):
            runtime.instance_state(cm, categories, {'state': ref})

    asked = []
    cm = SimpleNamespace(access=lambda i: asked.append(i) or {'return': 0, 'artifacts': [{'path': 'p'}]})
    runtime.find(cm, categories, f'website,{UPPER}::{ALIAS}')
    runtime.find(cm, categories, f'{ALIAS},{UID}')                       # the default category
    assert [(a['category'], a['arg1']) for a in asked] == [('website,1111222233334444', ALIAS), ('task,c36be4b9314a45e0', f'{ALIAS},{UID}')]
    with pytest.raises(KeyError):
        runtime.find(cm, categories, 'website, other::x')


def test_bootstrap_puts_a_repository_in_the_folder_of_its_whole_alias(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'register', lambda cm, root: [])
    source = tmp_path / 'source'
    put(source / '_cmr.yaml', f'artifact: "{ALIAS},{UID}"\n')
    root = tmp_path / 'project'
    profile = {'repositories': [{'name': f'{ALIAS},{UID}', 'source': str(source)},
                                {'name': f'plain-repo,{OTHER}', 'source': str(source)},      # as before
                                {'name': UPPER, 'source': str(source)}]}
    runtime.bootstrap(SimpleNamespace(repos=SimpleNamespace(init=lambda: {'return': 0})), {'root': str(root), 'profile': profile})
    assert {p.name for p in (root / 'repos').iterdir()} == {ALIAS, 'plain-repo', UID}
    assert (root / 'repos' / ALIAS / '_cmr.yaml').is_file()


@pytest.fixture(scope='module')
def scripts():
    return module_of('task/manage-cmeta-project/scripts.py', 'project_scripts_comma_aliases')


SYNCS = [f'host,{CAT}::{ALIAS},{UID}', f'{ALIAS} data,{UID}', 'host::my-vm', f'plain-sync,{OTHER}', f'R&D (100%) data,{OTHER}']
CALLS = [['cx', 'host', 'sync', f'{ALIAS},{UID}', '-q'],
         ['cxt', 'sync', f'{ALIAS} data,{UID}', '--require-initialized', '--live', '-q'],
         ['cx', 'host', 'sync', 'my-vm', '-q'],
         ['cxt', 'sync', f'plain-sync,{OTHER}', '--require-initialized', '--live', '-q'],
         ['cxt', 'sync', f'R&D (100%) data,{OTHER}', '--require-initialized', '--live', '-q']]


def test_the_steps_of_the_sync_scripts(scripts):
    step = scripts._step
    assert step(f'host,{CAT}::{ALIAS},{UID}') == ('host', f'{ALIAS},{UID}') and step(f'sync,{UPPER}::{ALIAS}') == ('sync', ALIAS)
    assert step('host:: my-vm ') == ('host', 'my-vm')
    assert step('host::my-vm') == ('host', 'my-vm') and step(f'bisync-x,{OTHER}') == ('sync', f'bisync-x,{OTHER}')     # as before
    assert step('host, other::x') == ('sync', 'host, other::x') and step(f'{CAT}::x') == ('sync', f'{CAT}::x')


def test_the_sync_scripts_write_a_name_with_commas_and_spaces_as_one_word(scripts):
    files = scripts.sync_files({'name': "Kim's site", 'syncs': SYNCS})
    sh, bat = files['___sync_all.sh'].splitlines(), files['___sync_all.bat'].splitlines()

    # plain names: the lines as before
    assert '    cx host sync my-vm $host_flags' in sh and "echo '[3/5] cx host sync my-vm'" in sh
    assert '    call cx host sync my-vm %HOST_Q% %HOST_DRY%' in bat and 'echo [3/5] cx host sync my-vm' in bat
    assert f'cxt sync plain-sync,{OTHER} --require-initialized --live "$@"' in sh
    assert f'call cxt sync plain-sync,{OTHER} --require-initialized --live %*' in bat

    # the others: one word for each shell, the label of a step by the whole alias
    host = [line for line in sh if line.strip().startswith('cx host sync') and 'Kim' in line]
    assert [shlex.split(line) for line in host] == [['cx', 'host', 'sync', f'{ALIAS},{UID}', '$host_flags']]
    assert f'    call cx host sync "{ALIAS},{UID}" %HOST_Q% %HOST_DRY%' in bat
    assert ['echo', f'[2/5] {ALIAS} data'] in [shlex.split(line) for line in sh if line.startswith('echo')]
    assert f'echo [2/5] {ALIAS} data' in bat and 'echo [5/5] R^&D (100%%) data' in bat
    assert f'call cxt sync "R&D (100%%%%) data,{OTHER}" --require-initialized --live %*' in bat
    assert ['echo', "Kim's site synchronized."] in [shlex.split(line) for line in sh if line.startswith('echo')]

    with pytest.raises(ValueError):
        scripts.sync_files({'syncs': [f'a^b,{OTHER}']})          # call doubles a caret even in quotes


def calls_of(log):
    """The command lines the stand-ins of cx and cxt were called with: [program, arguments ...] each."""
    text = log.read_text(encoding='utf-8') if log.exists() else ''
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.mark.skipif(not shutil.which('sh'), reason='no POSIX shell here')
def test_the_generated_sh_passes_each_name_whole(scripts, tmp_path):
    script = put(tmp_path / '___sync_all.sh', scripts.sync_files({'name': 'site', 'syncs': SYNCS})['___sync_all.sh'])
    log = tmp_path / 'calls.log'
    for tool in ('cx', 'cxt'):
        # each call as one JSON line, written by the shell itself (printf %s keeps every byte of an argument)
        put(tmp_path / 'bin' / tool, '#!/bin/sh\n{ printf \'["%s"\' "' + tool + '"; for a in "$@"; do printf \', "%s"\' "$a"; done; '
                                     'printf \']\\n\'; } >> "$CALLS_LOG"\n').chmod(0o755)
    env = dict(os.environ, CALLS_LOG=str(log).replace('\\', '/'),
               PATH=str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run(['sh', str(script).replace('\\', '/'), '-q'], env=env, cwd=str(tmp_path), capture_output=True,
                       text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(calls_of(log)) == sorted(CALLS)


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe is a Windows shell')
def test_the_generated_bat_passes_each_name_whole(scripts, tmp_path):
    script = tmp_path / '___sync_all.bat'
    script.write_bytes(scripts.sync_files({'name': 'site', 'syncs': SYNCS})['___sync_all.bat'].replace('\n', '\r\n').encode('utf-8'))
    log = tmp_path / 'calls.log'
    for tool in ('cx', 'cxt'):
        # a program's arguments as a program reads them (CommandLineToArgv), not as cmd.exe shows them
        (tmp_path / 'bin').mkdir(exist_ok=True)
        (tmp_path / 'bin' / (tool + '.bat')).write_bytes((
            '@"%CALLS_PYTHON%" -c "import sys,json,os; open(os.environ[\'CALLS_LOG\'],\'a\',encoding=\'utf-8\')'
            '.write(json.dumps([\'' + tool + '\']+sys.argv[1:])+chr(10))" %*\r\n').encode('utf-8'))
    env = dict(os.environ, CALLS_LOG=str(log), CALLS_PYTHON=sys.executable,
               PATH=str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run(['cmd', '/c', str(script), '-q'], env=env, cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=120, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(calls_of(log)) == sorted(CALLS)


@pytest.fixture(scope='module')
def website():
    return source_of('task/run-website/api_v1.py', {'    from task_c36be4b9314a45e0.api.ctask import InitCTask': '    InitCTask = object'},
                     'run_website_comma_aliases')


def test_a_website_reference_names_its_category_with_or_without_a_uid(website, tmp_path):
    alias = website['category_alias']
    assert alias(f'state,{UPPER}') == 'state' and alias(f'result , {UID}') == 'result' and alias('task') == 'task'
    assert alias('result, other') == 'result, other' and alias(UID) == '' and alias('') == ''

    t = website['CTask'].__new__(website['CTask'])
    asked = []
    t.cmeta = {'uses_categories': {'task': 'task,c36be4b9314a45e0', 'website': 'website,1111222233334444',
                                   'state': 'state,a1ed1ed7ca7043b6', 'result': 'result,6567e4df4d04488a'}}
    t.cm = SimpleNamespace(access=lambda i: asked.append(i) or {'return': 0, 'artifacts': [{'path': str(tmp_path)}]},
                           catch_error=lambda r, fail16=False: r.get('return', 0) > 0,
                           utils=SimpleNamespace(files=SimpleNamespace(
                               safe_read_yaml_or_json=lambda path: {'return': 0, 'data': {'deployment': {'name': 'site'}}})),
                           error=lambda text: {'return': 1, 'error': text})
    assert t.find(f'website,{UPPER}::{ALIAS}')[0] == 'website' and asked[-1]['arg1'] == ALIAS
    assert t.find('my-task')[0] == 'task'                                                 # as before
    for cref in ('website, other::x', f'{CAT}::x'):
        with pytest.raises(ValueError):
            t.find(cref)
    for state in ('state::local:website-x', f'state,{UPPER}::local:website-x', f'state , {UID}::x'):
        assert t.run({}, website='my-task', action='plan', state_cref=state) == {'return': 0}
    r = t.run({}, website='my-task', action='plan', state_cref='state, other::x')
    assert r['return'] == 1 and 'state-cref' in r['error']


# ---------------------------------------------------------------------------------------------- AI sessions
@pytest.fixture(scope='module')
def run_ai(task_namespace):
    return task_namespace('run-ai')['CTask']


@pytest.mark.parametrize('cref, parts', [
    (f'work,{CAT}::{ALIAS},{UID}', ('work', CAT, ALIAS.lower(), UID)),
    (f'Work,{CAT.upper()}::{ALIAS},{UPPER}', ('work', CAT, ALIAS.lower(), UID)),
    (f'work , {CAT}::{ALIAS} , {UID}', ('work', CAT, ALIAS.lower(), UID)),
    (f'work::{ALIAS}', ('work', '', ALIAS.lower(), '')),
    (f'{CAT}::{UID}', ('', CAT, '', UID)),
    (f'work::demo:{ALIAS},{UID}', ('work', '', 'demo:' + ALIAS.lower(), UID)),
    (f'work::Kim,{OTHER}', ('work', '', 'kim', OTHER)),
    ('tool::a, b', ('tool', '', 'a, b', '')),                                            # as before
    ('', ('', '', '', ''))])
def test_run_ai_reads_both_halves_of_a_cref_at_their_last_comma(run_ai, cref, parts):
    assert run_ai._cref_parts(cref) == parts


def test_a_mapping_key_matches_a_project_by_its_alias_or_its_uid(run_ai):
    project = f'work,{CAT}::{ALIAS},{UID}'
    for key in (f'work::{ALIAS}', f'WORK::{ALIAS.upper()}', f'work,{CAT.upper()}::x,{UPPER}', f'{CAT}::{UID}',
                f'work::{UID}', f'{CAT}::{ALIAS}'):
        assert run_ai._cref_matches(key, project), key
    for key in ('work::Kim Doe', f'note::{ALIAS}', f'{OTHER}::{UID}'):
        assert not run_ai._cref_matches(key, project), key


@pytest.mark.parametrize('cref, alias', [
    (f'work,{CAT}::{ALIAS},{UID}', ALIAS), (f'work::{ALIAS},{UPPER}', ALIAS), (f'work::{ALIAS} , {UID}', ALIAS),
    (f'work::{ALIAS}', ALIAS), (f'work::{UID}', UID), (f'work::my-work,{OTHER}', 'my-work'), ('', 'folder')])
def test_a_session_is_named_by_the_whole_alias(run_ai, cref, alias):
    assert run_ai._alias_of(cref, os.path.join('x', 'folder')) == alias


@pytest.mark.parametrize('key, found', [('My, repo', True), (UID, True), (UPPER, True), (f'my, repo,{UID}', True),
                                        ('my', False), (f' repo,{UID}', False), ('repo', False)])
def test_this_machines_mapping_finds_a_repository_whose_alias_holds_commas(run_ai, tmp_path, key, found):
    put(tmp_path / 'repo' / '_cmr.yaml', f'artifact: "My, repo,{UID}"\ncategory: repo,f4f792ab40c7498f\n')
    project = tmp_path / 'repo' / 'work' / 'x'
    project.mkdir(parents=True)
    t = run_ai.__new__(run_ai)
    t._run_ai_config = lambda: {'local_ai_uses': {key: 'org::A'}}
    assert t._local_ai_uses(str(project), f'work,{CAT}::x,{OTHER}') == ([('org::A', '', key)] if found else [])


@pytest.mark.parametrize('label, key', [
    (f'demo.person,{CAT}::{ALIAS},{UID}', 'Kim-Doe-joined-Example-Co-20260922--' + UID),
    (f'demo.person,{CAT}::{ALIAS},{UPPER}', 'Kim-Doe-joined-Example-Co-20260922--' + UID),
    (f'demo.person,{CAT}::{ALIAS}', 'Kim-Doe-joined-Example-Co-20260922'),            # no UID: the date is part of the alias
    (f'demo.person,{CAT}::{ALIAS},', 'Kim-Doe-joined-Example-Co-20260922'),           # run-ai's label of an artifact without one
    (f'demo.project,{CAT}::cMeta,{OTHER}', 'cMeta--' + OTHER),                          # as before
    (f'demo.project::{UID}', UID),
    ('no cref', 'folder')])
def test_the_staging_folder_of_a_used_artifact(label, key):
    pending = module_of('task/run-ai/pending.py', 'run_ai_pending_comma_aliases')
    assert pending.stage_key(label, os.path.join('x', 'folder')) == key


@pytest.mark.parametrize('artifact, added', [(f'{ALIAS},{UID}', [ALIAS]), (f'{ALIAS} , {UPPER}', [ALIAS]),
                                             (f'ctuninglabs@cmeta-aops,{OTHER}', ['ctuninglabs@cmeta-aops']),     # as before
                                             (UID, [UID]), ('', [])])
def test_run_claude_adds_the_repository_it_lives_in_by_its_whole_alias(task_namespace, tmp_path, artifact, added):
    from cmeta.utils import names

    put(tmp_path / 'repo' / '_cmr.yaml', yaml.safe_dump({'artifact': artifact}))
    task = tmp_path / 'repo' / 'task' / 'run-claude'
    task.mkdir(parents=True)
    CTask = task_namespace('run-claude')['CTask']
    t = CTask.__new__(CTask)
    t.path = str(task)
    t.cm = SimpleNamespace(utils=SimpleNamespace(names=names), access=lambda i: {'return': 0, 'config_cmeta': {}})
    assert t._default_add_repos() == added


def test_import_ai_names_the_plugin_by_the_whole_alias(task_namespace, tmp_path):
    ns = task_namespace('import-ai')
    put(tmp_path / 'skills' / 'deploy' / 'SKILL.md', '---\nname: deploy\ndescription: what deploy is for\n---\n\nThe steps.\n')
    for n, (cref, name) in enumerate([(f'work,{CAT}::{ALIAS} , {UPPER}', 'kim-doe-joined-example-co-20260922'),
                                      (f'work,{CAT}::{ALIAS},{UID}', 'kim-doe-joined-example-co-20260922'),
                                      (f'work,{CAT}::my-work,{OTHER}', 'my-work')]):                      # as before
        project = tmp_path / f'project-{n}'
        project.mkdir()
        t = ns['CTask'].__new__(ns['CTask'])
        t._resolve_project = lambda p, project=project, cref=cref: (str(project), cref)
        assert t.run({'control': {'con': False}}, project='x', skills=str(tmp_path / 'skills'))['return'] == 0
        manifest = project / ns['AI_DIR'] / ns['PLUGIN_DIR'] / ns['PLUGIN_FILE']
        assert json.loads(manifest.read_text(encoding='utf-8'))['name'] == name


# ---------------------------------------------------------------------------------------------- lists of names: run-openssh --keys
def test_keys_read_a_reference_whole(task_namespace):
    split = task_namespace('run-openssh')['split_names']
    # commas, as before - a reference among files too
    assert split('a.pub,b.pub') == ['a.pub', 'b.pub'] and split(' a.pub , b.pub ,') == ['a.pub', 'b.pub']
    assert split('secret::me, ' + KEY) == ['secret::me', KEY]

    # ";" when the text holds one: each part is one item, a reference keeps its commas (one alone: a ";" after it)
    assert split(f'secret::{ALIAS},{UID};') == [f'secret::{ALIAS},{UID}']
    assert split(f'secret,{CAT}::{ALIAS},{UPPER}/id.pub; laptop.pub; desktop.pub') == [
        f'secret,{CAT}::{ALIAS},{UPPER}/id.pub', 'laptop.pub', 'desktop.pub']
    assert split('secret::me; ' + KEY) == ['secret::me', KEY]

    # a list as it is, and nothing
    assert split(['a, b.pub', f'secret::{ALIAS}']) == ['a, b.pub', f'secret::{ALIAS}']
    assert split('') == [] and split(None) == [] and split(' ; ;') == []


def test_keys_resolve_a_secret_named_with_commas(task_namespace, tmp_path):
    ns = task_namespace('run-openssh')
    pub = put(tmp_path / 'id.pub', KEY + '\n')
    asked = []

    def resolve(ref):
        asked.append(ref)
        return (str(pub), None) if ref == f'secret::{ALIAS},{UID}' else (None, f'"{ref}" cannot be resolved')

    for keys in (f'secret::{ALIAS},{UID};', [f'secret::{ALIAS},{UID}']):      # ";" after it, or a list
        asked.clear()
        assert ns['read_keys'](keys, resolve=resolve) == ([KEY], None)
        assert asked == [f'secret::{ALIAS},{UID}']

    secret = tmp_path / 'secret'
    put(secret / 'id.pub', KEY + '\n')
    t = ns['CTask'].__new__(ns['CTask'])
    t.cmeta = {'uses_categories': {'secret': 'secret,9d63451ea1f14010', 'host': 'host,e4e49c251c814f6d'}}
    t.cm = SimpleNamespace(access=lambda i: asked.append(i) or {'return': 0, 'artifacts': [{'path': str(secret)}]},
                           utils=SimpleNamespace(files=SimpleNamespace(
                               safe_read_yaml_or_json=lambda path: {'return': 0, 'data': {'ssh': {'public_key': 'id.pub'}}})))
    for ref in (f'secret::{ALIAS},{UID}', f'secret,9d63451ea1f14010::{ALIAS},{UID}', f'secret,{UPPER}::{ALIAS}'):
        asked.clear()
        assert t._public_key_of(ref) == (os.path.join(str(secret), 'id.pub'), None)
        assert [(a['category'], a['command'], a['arg1']) for a in asked] == [('secret,9d63451ea1f14010', 'find', ref.split('::', 1)[1])]
