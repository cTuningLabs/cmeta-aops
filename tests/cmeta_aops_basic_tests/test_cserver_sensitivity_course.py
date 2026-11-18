"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The course page cserver.cmeta.sensitivity (Sensitivity and access - cMeta for organisations, 2026-11-18): it renders its
eight lessons on any engine; its live lesson (?native_action=scope) asks the engine, inside the request, what the scope
the host passed means for the repositories - a member sees the repositories they read and never the names of the
others, an administrator of the host (misc.sensitivity_admin) every one; without a scope only the server's own browser,
a browser past its password or an administrator get the list; an engine without the labels (before cMeta 0.44) gets a
sentence, never an error. In a throwaway cMeta home with this repository plugged and one repository per label.
"""

import os
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / 'category' / 'cserver.cmeta.sensitivity'

URLS = {'url': 'http://127.0.0.1:8004/cmeta.sensitivity?', 'url_files': 'http://127.0.0.1:8004/cmeta.sensitivity/',
        'url_server': 'http://127.0.0.1:8004/'}

# the repositories of the test home: alias -> the label of its _cmr.yaml (None: no label)
REPOS = {'pub-repo': None, 'gen-repo': 'general', 'conf-repo': 'confidential', 'hc-repo': 'highly-confidential',
         'mine-repo': 'personal'}


def _engine_has_scope():
    try:
        from cmeta.repos import Repos
    except Exception:
        return False
    return callable(getattr(Repos, 'scope_table', None))


needs_scope = pytest.mark.skipif(not _engine_has_scope(), reason='the engine has no sensitivity scope (cMeta 0.44 or newer)')


@pytest.fixture(scope='module')
def cm(tmp_path_factory):
    from cmeta import CMeta

    home = tmp_path_factory.mktemp('sensitivity-course-home')
    saved = {k: os.environ.get(k) for k in ('CMETA_HOME', 'CMETA_HOME2', 'CMETA_VERBOSE', 'CMETA_DEBUG')}
    for k in ('CMETA_HOME2', 'CMETA_VERBOSE', 'CMETA_DEBUG'):
        os.environ.pop(k, None)
    os.environ['CMETA_HOME'] = str(home)
    try:
        c = CMeta(home = str(home))
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(REPO_ROOT), 'con': False})
        assert r['return'] == 0, r
        for alias, label in REPOS.items():
            request = {'category': 'repo', 'command': 'create', 'arg1': alias, 'con': False}
            if label:
                request['meta'] = {'sensitivity': label}
            r = c.access(request)
            assert r['return'] == 0, r
        yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def page(cm, misc = None, scope = None, **query):
    r = cm.access(dict({'category': 'cserver.cmeta.sensitivity', 'command': 'web', 'con': False, 'urls': dict(URLS),
                        'query': query, 'misc': dict(misc or {})}, **(scope or {})))
    assert r['return'] == 0, r
    return r


def live(cm, misc = None, scope = None):
    out = page(cm, misc, scope, native_action = 'scope')['json']
    assert 'error' not in out, out
    return out


def aliases(out):
    return sorted(r['alias'] for r in out['rows'])


def clean(cm):
    repos = cm.repos
    return getattr(repos, 'clearance', None) is None and not getattr(repos, 'hidden_repos', ()) and \
        not getattr(repos, 'write_scoped', False)


# ---------------------------------------------------------------------------------------------------------- the page

def test_the_page_renders_its_eight_lessons(cm):
    meta = page(cm)['html_meta']
    body = meta['html']
    assert meta['page_title'] == 'Sensitivity and access'
    assert body.count('class="cms-lesson"') == 8
    for title in ('Why labels', 'Labelling', 'The scope of a call', 'People and records', 'Writes under a scope',
                  'What you can see', 'Organising repositories', 'Check'):
        assert 'data-title="%s"' % title in body, title
    assert '%%' not in body                                                   # every placeholder filled
    assert '"lesson": 1' in body and '"lessons": 8' in body and '"hosted": false' in body and '"dark_mode": false' in body
    # the assets come from the host's url_files, with their time against a stale browser copy
    head = meta['page_extra_style']
    assert re.search(r'cmeta\.sensitivity/css/sensitivity\.css\?v=\d+', head) and re.search(r'js/sensitivity\.js\?v=\d+', head)
    # the labels and the questions of files/sensitivity.yaml are in the page
    assert '"highly-confidential"' in body and '"quiz"' in body


def test_the_lesson_the_theme_and_the_host(cm):
    assert '"lesson": 6' in page(cm, lesson = '6')['html_meta']['html']
    assert '"lesson": 8' in page(cm, lesson = '99')['html_meta']['html']           # clamped
    assert '"lesson": 1' in page(cm, lesson = 'x')['html_meta']['html']
    body = page(cm, misc = {'ctuning_server': True, 'theme': 'dark'})['html_meta']['html']
    assert '"hosted": true' in body and '"dark_mode": true' in body             # the cPlatform's shell and its theme
    assert '"dark_mode": true' in page(cm, dark = '1')['html_meta']['html']


def test_an_unknown_action_answers_with_an_error(cm):
    out = page(cm, native_action = 'nothing')['json']
    assert 'unknown native_action' in out['error']


# ---------------------------------------------------------------------------------------------------------- lesson 6

@needs_scope
def test_a_member_sees_only_the_repositories_they_read(cm):
    out = live(cm, scope = {'clearance': 'general'})
    assert out['supported'] and out['scoped'] and out['clearance'] == 'general' and not out['admin']
    shown = aliases(out)
    assert 'pub-repo' in shown and 'gen-repo' in shown and 'internal' in shown and 'ctuninglabs@cmeta-aops' in shown
    # the names of the repositories above the clearance never reach the page - nor the machine's own repository
    for hidden in ('conf-repo', 'hc-repo', 'mine-repo', 'local'):
        assert hidden not in shown, hidden
    assert all(r['read'] for r in out['rows']) and out['read'] == len(out['rows'])
    assert all('path' not in r for r in out['rows'])                        # no folder of the server
    assert clean(cm)

    # a grant by name: listed, and why
    out = live(cm, scope = {'clearance': 'general', 'allow_repos': 'conf-repo'})
    row = {r['alias']: r for r in out['rows']}['conf-repo']
    assert row['read'] and row['why'] == 'granted' and row['sensitivity'] == 'confidential' and 'granted' in row['why_text']

    # repositories hidden by name alone (the sites before the labels): scoped, no clearance
    out = live(cm, scope = {'hide_repos': 'gen-repo'})
    assert out['scoped'] and out['clearance'] is None and 'gen-repo' not in aliases(out) and 'conf-repo' in aliases(out)
    assert all(r['why'] == 'open' and r['why_text'].startswith('not hidden from you') for r in out['rows'])


@needs_scope
def test_an_administrator_sees_every_repository_and_why(cm):
    out = live(cm, misc = {'sensitivity_admin': True}, scope = {'clearance': 'general'})
    assert out['admin'] and out['all']
    rows = {r['alias']: r for r in out['rows']}
    assert set(REPOS) | {'local', 'internal', 'ctuninglabs@cmeta-aops'} <= set(rows)
    assert (rows['conf-repo']['read'], rows['conf-repo']['why']) == (False, 'label')
    assert (rows['mine-repo']['sensitivity'], rows['mine-repo']['read']) == ('personal', False)
    assert (rows['local']['from'], rows['local']['read']) == ('local', False) and 'this machine' in rows['local']['from_text']
    assert (rows['pub-repo']['from'], rows['pub-repo']['sensitivity']) == ('default', 'public')
    assert out['read'] == sum(1 for r in out['rows'] if r['read']) < len(out['rows'])

    # the owner's clearance reads everything
    out = live(cm, scope = {'clearance': 'personal'})
    assert all(r['read'] for r in out['rows']) and 'mine-repo' in aliases(out) and 'local' in aliases(out)


@needs_scope
def test_the_write_scope_shows_where_the_reader_writes(cm):
    out = live(cm, scope = {'clearance': 'general', 'write_repos': 'gen-repo'})
    assert out['write_scoped'] and out['write'] == 1
    rows = {r['alias']: r for r in out['rows']}
    assert rows['gen-repo']['write'] and not rows['pub-repo']['write']
    # a write scope alone (no clearance): every repository read, writes into one
    out = live(cm, scope = {'write_repos': 'none'})
    assert out['scoped'] and out['write_scoped'] and out['write'] == 0 and out['clearance'] is None
    assert clean(cm)


@needs_scope
def test_without_a_scope_the_list_is_for_the_machine_and_its_administrators(cm):
    # a host that passes no scope (a public site before the labels): nothing named to a visitor
    out = live(cm)
    assert out['supported'] and not out['scoped'] and not out['listed'] and out['rows'] == []
    # the engine's cserver: a browser on its own machine, or one past its password; a host's administrator
    for misc in ({'client_local': True}, {'password_gate': True}, {'sensitivity_admin': True}):
        out = live(cm, misc = misc)
        assert out['listed'] and not out['scoped'], misc
        names = aliases(out)
        assert 'conf-repo' in names and 'mine-repo' in names and 'local' in names, misc
        assert all(r['read'] and r['write'] and r['why'] == 'open' and r['why_text'].startswith('no scope')
                   for r in out['rows']), misc


def test_an_engine_before_the_labels_gets_a_sentence(cm, monkeypatch):
    import cmeta.repos
    if callable(getattr(cmeta.repos.Repos, 'scope_table', None)):
        monkeypatch.delattr(cmeta.repos.Repos, 'scope_table')
    out = page(cm, native_action = 'scope')['json']
    assert out['supported'] is False and 'older than 0.44' in out['message'] and 'error' not in out
    # the course itself renders as ever
    assert page(cm)['html_meta']['html'].count('class="cms-lesson"') == 8


# ---------------------------------------------------------------------------------------------------------- the words

def test_the_labels_follow_the_engine_and_the_check_is_answerable():
    data = yaml.safe_load((PAGE / 'files' / 'sensitivity.yaml').read_text(encoding = 'utf-8'))
    ids = [l['id'] for l in data['labels']]
    try:
        from cmeta.repos import SENSITIVITY_LEVELS, sensitivity_rank
    except ImportError:
        pytest.skip('the engine has no sensitivity labels (cMeta 0.44 or newer)')
    assert ids == list(SENSITIVITY_LEVELS) + ['personal']
    for rank, label in enumerate(data['labels']):
        for word in label.get('synonyms') or []:
            assert sensitivity_rank(word) == rank, word
        assert label['light'] and label['dark']
    assert len(data['quiz']) >= 5
    for q in data['quiz']:
        assert q['q'] and q['why'] and len(q['options']) >= 2 and 0 <= q['answer'] < len(q['options']), q


def test_the_page_carries_no_copyright_line():
    """New public code carries its authors and the Apache pointer, never a copyright line."""
    assert 'copyright:' not in (PAGE / '_cmeta.yaml').read_text(encoding = 'utf-8')
    for path in PAGE.rglob('*'):
        if path.is_file() and path.suffix in ('.py', '.html', '.css', '.js', '.yaml'):
            text = path.read_text(encoding = 'utf-8')
            assert 'Copyright (C)' not in text and 'copyright:' not in text, path
