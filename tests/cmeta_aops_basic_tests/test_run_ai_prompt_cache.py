"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

How long the provider keeps the prompt cache of a conversation (--prompt_cache_minutes of run-ai and run-claude): what
a run asks for and where that comes from - the flag, one's own variable, this machine's default on a key, the harness
itself -, how Claude Code is told by its version (the block prompt_cache of run-claude's _desc.yaml), what the records
keep, and the settings of a run in the reference a gateway of one's own is sent. Offline: no harness is started; the
last test runs the task through the engine with a stand-in harness.
"""

import datetime
import io
import json
import os
import pathlib
import uuid

import pytest


# ---------------------------------------------------------------------------------------------- run-claude: by version
def test_claude_code_is_told_the_way_its_version_takes(task_namespace):
    """The setting promptCacheTtl from 2.1.243, a variable for the whole session from 2.1.108, an error before; a
    lifetime Claude Code does not take is never rounded."""
    ns = task_namespace('run-claude')
    request, ways = ns['prompt_cache_request'], ns['prompt_cache_ways']()
    names = {w['name']: w for w in ways}
    assert {'prompt-cache-ttl-setting', 'prompt-caching-1h-variable'} <= set(names)

    # the current way: a key of Claude Code's settings, and the variables that would decide in its place
    r = request(60, '2.1.330')
    assert r['return'] == 0 and r['minutes'] == 60 and r['way'] == 'prompt-cache-ttl-setting'
    assert r['settings'] == {'promptCacheTtl': '1h'} and r['env'] == {}
    assert {'CLAUDE_CODE_PROMPT_CACHE_TTL', 'FORCE_PROMPT_CACHING_5M'} <= set(r['drops'])
    r = request('5', '2.1.243')                                     # a word of the command line, the first version that has it
    assert r['return'] == 0 and r['settings'] == {'promptCacheTtl': '5m'} and r['note'] == ''

    # an older Claude Code: one lifetime for the whole session, through a variable
    r = request(60, '2.1.242')
    assert r['return'] == 0 and r['way'] == 'prompt-caching-1h-variable'
    assert r['settings'] == {} and r['env'] == {'ENABLE_PROMPT_CACHING_1H': '1'}
    assert request(5, '2.1.108')['env'] == {'FORCE_PROMPT_CACHING_5M': '1'}

    # before that it cannot be told: an error that names the first version, nothing set
    r = request(60, '2.1.107')
    assert r['return'] == 1 and '2.1.107' in r['error'] and '2.1.108' in r['error']

    # only the lifetimes the way lists
    r = request(30, '2.1.330')
    assert r['return'] == 1 and '5 or 60' in r['error'] and 'nothing between' in r['error']
    assert request(0, '2.1.330')['return'] == 1 and request(-5, '2.1.330')['return'] == 1
    assert 'number of minutes' in request('an hour', '2.1.330')['error']

    # a version nobody could read, or one cMeta does not compare: the newest way, and the answer says so
    r = request(60, '')
    assert r['return'] == 0 and r['way'] == 'prompt-cache-ttl-setting' and 'not known' in r['note']

    # a task that declares nothing has no way
    assert request(60, '2.1.330', ways=[])['return'] == 1


def test_the_lifetime_joins_the_one_settings_flag_of_a_session(task_namespace):
    """Claude Code reads one --settings: the lifetime goes into the gateway's and run-ai's, and wins over a value the
    flags after "--" gave."""
    ns = task_namespace('run-claude')
    add = ns['prompt_cache_request'](60, '2.1.330')['settings']

    flags, err = ns['_with_settings'](['--settings', json.dumps({'apiKeyHelper': 'h', 'promptCacheTtl': '5m'}), '--add-dir', 'x'], add)
    assert err == ''
    settings = json.loads(flags[flags.index('--settings') + 1])
    assert settings == {'apiKeyHelper': 'h', 'promptCacheTtl': '1h'} and '--add-dir' in flags


def test_the_version_is_the_one_the_program_reports(task_namespace, monkeypatch):
    """Claude Code updates itself in place: the program is asked, once per process; one that cannot be asked has no
    version (the newest way is then taken)."""
    ns = task_namespace('run-claude')
    asked = []

    class Answer:
        stdout = '2.1.330 (Claude Code)\n'

    def run(cmd, **kwargs):
        asked.append(cmd)
        return Answer()

    monkeypatch.setattr(ns['subprocess'], 'run', run)
    monkeypatch.setitem(ns, '_VERSIONS', {})
    version = ns['_program_version']
    assert version('claude-under-test') == '2.1.330' and version('claude-under-test') == '2.1.330'
    assert asked == [['claude-under-test', '--version']]

    def fails(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(ns['subprocess'], 'run', fails)
    assert version('no-such-program') == ''


# ---------------------------------------------------------------------------------------------- run-ai: what a run asks for
class Engine:
    """A stand-in for the engine: the tasks of this repository by their names, and the config artifact task-run-ai."""

    def __init__(self, repo_root, config=None):
        self.repo_root, self.config = repo_root, dict(config or {})

    def access(self, p):
        if p.get('command') == 'find':
            path = self.repo_root / 'task' / str(p.get('arg1')).split(',')[0]
            return {'return': 0, 'artifacts': [{'path': str(path)}] if path.is_dir() else []}
        if p.get('command') == 'read':
            return {'return': 0, 'config_cmeta': dict(self.config)}
        return {'return': 1, 'error': 'unexpected call'}

    def error(self, text):
        return {'return': 1, 'error': text}


def run_ai_task(task_namespace, repo_root, config=None):
    ns = task_namespace('run-ai')
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = Engine(repo_root, config)
    return ns, task


CLAUDE, CODEX = 'run-claude,38be73ffceaa4f67', 'run-codex,ad2fd6be195a4e36'


def test_a_run_asks_for_the_flag_then_this_machines_default_on_a_key(task_namespace, repo_root):
    ns, task = run_ai_task(task_namespace, repo_root)

    def ask(asked=0, on_key=True, harness='claude', ref=CLAUDE, environ=None, config=None, kept=0):
        task.cm.config = dict(config or {})
        return task._prompt_cache(harness, ref, asked, on_key, environ=environ or {}, kept=kept)

    # the flag, on a key or on a login
    assert ask(60)[:1] + ask(60)[2:] == (60, '') and 'the flag --prompt_cache_minutes' in ask(60)[1]
    assert ask('5', on_key=False)[0] == 5

    # no flag, on a key: 60 without a config, the config's value with one, 0 leaves it to the harness
    minutes, where, err = ask()
    assert (minutes, err) == (60, '') and 'the default of a run on a key' in where and 'prompt_cache_minutes' in where
    minutes, where, err = ask(config={'prompt_cache_minutes': 5})
    assert (minutes, err) == (5, '') and 'config task-run-ai prompt_cache_minutes' in where
    minutes, where, err = ask(config={'prompt_cache_minutes': 0})
    assert (minutes, err) == (0, '') and 'the harness decides' in where and 'is 0' in where

    # no flag, on the harness's own login: the harness decides, whatever the config says
    minutes, where, err = ask(on_key=False, config={'prompt_cache_minutes': 5})
    assert (minutes, err) == (0, '') and 'own login' in where

    # one's own variable for it: the harness follows it and nothing is set - unless a flag says otherwise
    own = {'CLAUDE_CODE_PROMPT_CACHE_TTL': '5m'}
    minutes, where, err = ask(environ=own)
    assert (minutes, err) == (0, '') and 'CLAUDE_CODE_PROMPT_CACHE_TTL' in where and 'follows' in where
    assert ask(60, environ=own)[0] == 60
    assert ask(environ={'ENABLE_PROMPT_CACHING_1H': '1'})[0] == 0 and ask(environ={'FORCE_PROMPT_CACHING_5M': '1'})[0] == 0
    assert ask(environ={'CLAUDE_CODE_PROMPT_CACHE_TTL': ''})[0] == 60          # an empty variable decides nothing

    # a continued conversation keeps the lifetime its last run asked for, on a key or not, whatever the config says
    # now; the flag and one's own variable still come first, and a lifetime the harness no longer takes is not kept
    minutes, where, err = ask(kept=5, config={'prompt_cache_minutes': 60})
    assert (minutes, err) == (5, '') and 'the conversation keeps' in where
    assert ask(kept=5, on_key=False)[0] == 5
    assert ask(60, kept=5)[0] == 60 and ask(kept=5, environ=own)[0] == 0
    assert ask(kept=45)[0] == 60 and ask(kept=True)[0] == 60


def test_a_lifetime_the_harness_does_not_take_stops_the_run(task_namespace, repo_root):
    """Never rounded, wherever it came from; a harness whose task declares no way refuses the flag and is left alone
    by this machine's default."""
    ns, task = run_ai_task(task_namespace, repo_root)

    minutes, where, err = task._prompt_cache('claude', CLAUDE, 30, True, environ={})
    assert minutes == 0 and '--prompt_cache_minutes=30' in err and '5 or 60' in err
    assert 'number of minutes' in task._prompt_cache('claude', CLAUDE, 'long', True, environ={})[2]

    task.cm.config = {'prompt_cache_minutes': 45}
    minutes, where, err = task._prompt_cache('claude', CLAUDE, 0, True, environ={})
    assert minutes == 0 and 'the config task-run-ai prompt_cache_minutes=45' in err
    assert task._prompt_cache('claude', CLAUDE, 0, False, environ={})[2] == ''         # not read on a login run
    task.cm.config = {}

    # Codex's task declares no way to tell it
    minutes, where, err = task._prompt_cache('codex', CODEX, 60, True, environ={})
    assert minutes == 0 and 'knows no way' in err and 'codex' in err and 'run-codex' in err
    minutes, where, err = task._prompt_cache('codex', CODEX, 0, True, environ={})
    assert (minutes, err) == (0, '') and 'the harness decides' in where and 'codex' in where

    # what run-ai reads of a harness task's description: the lifetimes of its ways, and its own variables
    declared = task._harness_prompt_cache(CLAUDE)
    assert declared['minutes'] == [5, 60]
    assert {'CLAUDE_CODE_PROMPT_CACHE_TTL', 'FORCE_PROMPT_CACHING_5M', 'ENABLE_PROMPT_CACHING_1H'} == set(declared['variables'])
    assert task._harness_prompt_cache(CODEX) is None


def test_the_next_run_reads_the_lifetime_the_last_one_asked_for(task_namespace):
    """ "probably still warm": by the lifetime the last run asked for when it recorded one, else by the table."""
    ns = task_namespace('run-ai')
    task = ns['CTask'].__new__(ns['CTask'])
    task._harness_cache = ns['harness_declarations']([])         # no task declares it: run-ai's table (claude: 5 min)
    cache_line = task._cache_line

    def conv(minutes_ago, **run):
        at = (datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)).isoformat(timespec='seconds')
        return {'runs': [dict({'harness': 'claude', 'finished': at}, **run)]}

    line = cache_line('claude', conv(20, prompt_cache_minutes=60))
    assert 'still warm' in line and 'asked for 60 min' in line
    line = cache_line('claude', conv(20, prompt_cache_minutes=5))
    assert 'cold' in line and 'asked for 5 min' in line
    line = cache_line('claude', conv(20))                              # an older record: as before
    assert 'cold' in line and 'TTL 5 min' in line
    assert cache_line('claude', None) == ''

    # the lifetime the harness task declares (cache_ttl_minutes of its "harness" block) over the table
    task._harness_cache = ns['harness_declarations']([('run-claude,38be73ffceaa4f67', {'name': 'claude', 'cache_ttl_minutes': 30})])
    line = cache_line('claude', conv(20))
    assert 'still warm' in line and 'TTL 30 min' in line


# ---------------------------------------------------------------------------------------------- the run reference
def test_the_run_reference_names_what_the_run_was_started_with(task_namespace, ctask_helpers, monkeypatch):
    """After the project, the conversation and the run: the settings, in the order given; nothing for a setting without
    a value or with a key a gateway's line cannot keep; the three first as they always were."""
    reference = task_namespace('run-ai')['run_reference']
    base = 'project=work,0123456789abcdef::my%20work,fedcba9876543210;conversation=20261122-101500;run=20261122-101530'
    project = 'work,0123456789abcdef::my work,fedcba9876543210'

    assert reference(project, '20261122-101500', '20261122-101530') == base
    assert reference(project, '20261122-101500', '20261122-101530', []) == base

    full = reference(project, '20261122-101500', '20261122-101530', [
        ('cache_minutes', 60), ('mode', 'interactive'), ('cmeta', '1.2.3'), ('aops', '4.5.6.1'), ('context', 25431),
        ('model', ''), ('effort', None), ('Bad Key', 'x'), ('a_key_that_is_too_long', 'x'), ('run', 'another'), ('host', 'my host')])
    assert full == base + ';cache_minutes=60;mode=interactive;cmeta=1.2.3;aops=4.5.6.1;context=25431;host=my%20host'

    # a setting the harness decides (no value) is left out, a zero that is a value stays
    assert reference(project, '', 's', [('cache_minutes', ''), ('uses', 0)]) == 'project=work,0123456789abcdef::my%20work,fedcba9876543210;run=s;uses=0'

    # what reads the reference for an agent's generator record takes its three fields as before
    record = ctask_helpers('ai_run_record')['ai_run_record']
    monkeypatch.setenv('CMETA_AI_RUN', full)
    assert record('claude')['ai_run'] == {'project': '0123456789abcdef::fedcba9876543210', 'conversation': '20261122-101500',
                                          'run': '20261122-101530'}


# ---------------------------------------------------------------------------------------------- through the engine
FAKE_HARNESS = '''
import json
import os

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):
    """A stand-in for a coding agent: it writes down what it was given."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, prompt = '', prompt_file = '', interactive = False, stats = True, output_file = '', stats_file = '',
            skip_output_file = False, yes = False, reproducible = False, resume = '', prompt_cache_minutes = 0, unparsed = None):
        with open(os.environ['RUN_FAKE_SEEN'], 'w', encoding = 'utf-8') as f:
            json.dump({'prompt_cache_minutes': prompt_cache_minutes, 'reference': os.environ.get('CMETA_AI_RUN', '')}, f)
        return {'return': 0, 'output': 'an answer\\n'}
'''

# a harness that can be told (its lifetimes are 5 and 60), and one whose task declares nothing
DECLARES = 'cache: False\nprompt_cache:\n  ways:\n    - name: test-way\n      minutes: {5: {}, 60: {}}\n      drops: [FAKE_PROMPT_CACHE_TTL]\n'
SILENT = 'cache: False\n'


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(str(path), 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return path


@pytest.fixture(scope='module')
def lab(cm, tmp_path_factory):
    tag = uuid.uuid4().hex[:6]

    def add(category, alias):
        r = cm.access({'category': category, 'command': 'add', 'arg1': 'local:' + alias, 'con': False, 'quiet': True, 'yaml': True})
        assert r['return'] == 0, r.get('error')
        return pathlib.Path(r['path'])

    project = add('tmp', 'prompt-cache-project-' + tag)
    put(project / '_desc.yaml', 'ai_uses: []\n')
    for harness, desc in (('told' + tag, DECLARES), ('silent' + tag, SILENT)):
        task = add('task', 'run-' + harness)
        put(task / '_desc.yaml', desc)
        put(task / 'api_v1.py', FAKE_HARNESS)

    class Lab:
        scratch = tmp_path_factory.mktemp('prompt-cache')
        seen = scratch / 'seen.json'

        def run(self, harness='told', **params):
            if self.seen.exists():
                self.seen.unlink()
            request = {'category': 'task', 'command': 'run', 'arg1': 'run-ai', 'project': 'tmp::' + project.name,
                       'harness': harness + tag, 'con': False, 'prompt': 'x'}
            request.update(params)
            return cm.access(request)

    lab = Lab()
    lab.project = project
    return lab


def test_a_run_through_the_engine_hands_the_lifetime_to_the_harness_and_records_it(lab, monkeypatch, repo_root):
    import shutil

    import yaml
    monkeypatch.setenv('RUN_FAKE_SEEN', str(lab.seen))
    monkeypatch.delenv('FAKE_PROMPT_CACHE_TTL', raising=False)
    ai = lab.project / '!AI'
    shutil.rmtree(ai, ignore_errors=True)

    # a lifetime the harness does not take: stopped before anything is written
    r = lab.run(prompt_cache_minutes=30)
    assert r['return'] > 0 and '5 or 60' in r['error'] and not ai.exists() and not lab.seen.exists()

    # a harness that cannot be told refuses the flag, and runs as before without it
    r = lab.run(harness='silent', prompt_cache_minutes=60)
    assert r['return'] > 0 and 'knows no way' in r['error'] and not ai.exists()

    # a dry run says what would be asked, and where that came from
    r = lab.run(prompt_cache_minutes=60, dry_run=True)
    assert r['return'] == 0 and r['prompt_cache_minutes'] == 60 and 'the flag' in r['prompt_cache_from']
    assert r['params']['prompt_cache_minutes'] == 60 and not ai.exists()

    # a run on the harness's own login without the flag: the harness is given nothing
    r = lab.run()
    assert r['return'] == 0, r.get('error')
    assert r['prompt_cache_minutes'] == 0 and 'own login' in r['prompt_cache_from']
    seen = json.loads(lab.seen.read_text(encoding='utf-8'))
    assert seen['prompt_cache_minutes'] == 0 and ';cache_minutes=' not in seen['reference'] and ';mode=prompt' in seen['reference']
    runs = [json.loads(p.read_text(encoding='utf-8'))['runs'] for p in (ai / 'log').glob('*.conversation.json')]
    assert len(runs) == 1 and 'prompt_cache_minutes' not in runs[0][-1]

    # with the flag: the harness gets it, and the records and the reference keep it
    r = lab.run(prompt_cache_minutes=5)
    assert r['return'] == 0, r.get('error')
    assert r['prompt_cache_minutes'] == 5 and 'the flag --prompt_cache_minutes' in r['prompt_cache_from']
    seen = json.loads(lab.seen.read_text(encoding='utf-8'))
    assert seen['prompt_cache_minutes'] == 5
    fields = dict(part.split('=', 1) for part in seen['reference'].split(';'))
    aops = str(yaml.safe_load((repo_root / '_cmr.yaml').read_text(encoding='utf-8'))['version'])
    assert fields['cache_minutes'] == '5' and fields['mode'] == 'prompt' and fields['aops'] == aops and fields['cmeta']
    assert int(fields['context']) > 0 and fields['write'] and fields['resumed'] in ('yes', 'no', 'handover')
    assert list(fields)[:8] == ['project', 'conversation', 'run', 'cache_minutes', 'mode', 'cmeta', 'aops', 'context']
    conversation = json.loads(sorted((ai / 'log').glob('*.conversation.json'))[-1].read_text(encoding='utf-8'))
    assert conversation['runs'][-1]['prompt_cache_minutes'] == 5
    record = pathlib.Path(r['record']).read_text(encoding='utf-8')
    assert '| prompt cache | 5 min - the flag --prompt_cache_minutes |' in record

    # the conversation goes on with the lifetime its last run asked for
    r = lab.run(dry_run=True)
    assert r['prompt_cache_minutes'] == 5 and 'the conversation keeps' in r['prompt_cache_from']
    r = lab.run(dry_run=True, new=True)
    assert r['prompt_cache_minutes'] == 0 and 'own login' in r['prompt_cache_from']

    # one's own variable for the harness decides when no flag does
    monkeypatch.setenv('FAKE_PROMPT_CACHE_TTL', '1h')
    r = lab.run(dry_run=True)
    assert r['prompt_cache_minutes'] == 0 and 'FAKE_PROMPT_CACHE_TTL' in r['prompt_cache_from']
    shutil.rmtree(ai, ignore_errors=True)
