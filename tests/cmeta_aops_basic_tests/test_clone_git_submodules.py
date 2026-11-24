"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/clone-git's submodules (2026-11-24), with small repositories made here and git itself:
- the plan: --submodules_not_recursive fetches the named submodules without their own, the others with everything
  under them; a name that is no submodule is refused;
- the git folders a clone's submodules need, nested ones included, as Git lays them out;
- Windows: a git folder over Git's limit (220 characters) is said with the folder, the excess and the way out.
"""

import os
import shutil
import subprocess

import pytest

GIT = shutil.which('git')
pytestmark = pytest.mark.skipif(not GIT, reason = 'git is not on the PATH')

ID = ['-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', '-c', 'protocol.file.allow=always',
      '-c', 'core.longpaths=true', '-c', 'init.defaultBranch=main']


def git(*words, cwd = None):
    p = subprocess.run([GIT] + ID + list(words), cwd = cwd, stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                       stdin = subprocess.DEVNULL)
    assert p.returncode == 0, (words, p.stdout.decode('utf-8', 'replace'))
    return p.stdout.decode('utf-8', 'replace')


@pytest.fixture(scope = 'module')
def task(task_namespace):
    return task_namespace('clone-git')


@pytest.fixture(scope = 'module')
def sources(tmp_path_factory):
    """top -> used (-> used/inner), unused (-> unused/deep -> unused/deep/deeper), plain: a superproject with a
    submodule a build uses, one it does not (two levels under it) and one without submodules."""
    src = tmp_path_factory.mktemp('src')

    def repo(name, subs = ()):
        d = src / name
        d.mkdir()
        git('init', '-q', cwd = d)
        (d / 'LICENSE').write_text(name)
        for path, other in subs:
            git('submodule', 'add', '-q', str(src / other), path, cwd = d)
        git('add', '-A', cwd = d)
        git('commit', '-q', '-m', name, cwd = d)
        return d

    repo('deeper')
    repo('deep', [('3rdparty/deeper', 'deeper')])
    repo('unused', [('third_party/deep', 'deep')])
    repo('inner')
    repo('used', [('external/inner', 'inner')])
    repo('plain')
    return repo('top', [('third_party/used', 'used'), ('third_party/unused', 'unused'), ('third_party/plain', 'plain')])


class Runner:
    """What the task asks of cMeta here: a shell command run, an error, a quoted path."""

    class utils:
        class sys:
            @staticmethod
            def run(cmd, **kw):
                env = dict(os.environ, GIT_CONFIG_COUNT = '2', GIT_CONFIG_KEY_0 = 'protocol.file.allow', GIT_CONFIG_VALUE_0 = 'always',
                           GIT_CONFIG_KEY_1 = 'core.longpaths', GIT_CONFIG_VALUE_1 = 'true')
                p = subprocess.run(cmd, shell = True, env = env, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL)
                return {'return': 0, 'returncode': p.returncode, 'stdout': p.stdout.decode('utf-8', 'replace')}

    @staticmethod
    def error(text):
        return {'return': 1, 'error': text}

    @staticmethod
    def q(path):
        return f'"{path}"'


def under(task, repo, not_recursive, depth = ''):
    t = task['CTask'].__new__(task['CTask'])
    t.cm = Runner()
    return t._submodules_under(f'"{GIT}"', GIT, str(repo), not_recursive, depth, None, None, False, False, '', False)


def test_named_submodules_stay_without_their_own_and_the_others_get_everything(task, sources, tmp_path):
    clone = tmp_path / 'c'
    git('clone', '-q', str(sources), str(clone))
    git('submodule', 'update', '--init', cwd = clone)                       # the clone's own submodules, as the task does first
    assert not (clone / 'third_party' / 'used' / 'external' / 'inner' / 'LICENSE').exists()

    r = under(task, clone, ['third_party/unused'])
    assert r['return'] == 0, r
    assert (clone / 'third_party' / 'used' / 'external' / 'inner' / 'LICENSE').is_file()          # used: with what is under it
    assert (clone / 'third_party' / 'unused' / 'LICENSE').is_file()                               # unused: its folder is there
    assert not (clone / 'third_party' / 'unused' / 'third_party' / 'deep' / 'LICENSE').exists()   # ... what is under it is not
    assert (clone / 'third_party' / 'plain' / 'LICENSE').is_file()
    # the git folders: none of the unused submodule's own
    assert not (clone / '.git' / 'modules' / 'third_party' / 'unused' / 'modules').exists()


def files(task, repo, wanted, not_recursive, depth = ''):
    t = task['CTask'].__new__(task['CTask'])
    t.cm = Runner()
    return t._submodule_files(f'"{GIT}"', GIT, str(repo), wanted, not_recursive, depth, None, None, False, False, '', False)


def test_a_file_the_build_names_brings_the_nested_submodule_that_holds_it_and_no_other(task, sources, tmp_path):
    clone = tmp_path / 'c'
    git('clone', '-q', str(sources), str(clone))
    git('submodule', 'update', '--init', cwd = clone)
    assert under(task, clone, ['third_party/unused', 'third_party/used'])['return'] == 0
    unused = clone / 'third_party' / 'unused'
    assert not (unused / 'third_party' / 'deep' / 'LICENSE').exists()

    # a file one level down: that nested submodule, not what is under it; the other named submodule is not touched
    r = files(task, clone, ['third_party/unused/third_party/deep/LICENSE', 'LICENSE', 'third_party/plain/LICENSE',
                            'third_party/unused/LICENSE'], ['third_party/unused', 'third_party/used'])
    assert r['return'] == 0 and r['fetched'] == ['third_party/unused/third_party/deep'], r
    assert (unused / 'third_party' / 'deep' / 'LICENSE').is_file()
    assert not (unused / 'third_party' / 'deep' / '3rdparty' / 'deeper' / 'LICENSE').exists()
    assert not (clone / 'third_party' / 'used' / 'external' / 'inner' / 'LICENSE').exists()

    # a file two levels down, as a pattern: the ones on the way are there already, the last one is fetched; asked
    # again, nothing is fetched
    wanted = ['third_party/unused/third_party/deep/3rdparty/deeper/LICENSE*']
    r = files(task, clone, wanted, ['third_party/unused'])
    assert r['return'] == 0 and r['fetched'] == ['third_party/unused/third_party/deep/3rdparty/deeper'], r
    assert (unused / 'third_party' / 'deep' / '3rdparty' / 'deeper' / 'LICENSE').is_file()
    assert files(task, clone, wanted, ['third_party/unused'])['fetched'] == []


def test_the_part_of_a_pattern_before_its_first_wildcard(task):
    prefix = task['literal_prefix']
    assert prefix('a/b/LICENSE') == 'a/b/LICENSE' and prefix('a/b/*.txt') == 'a/b' and prefix('a/*/c') == 'a'
    assert prefix('*') == '' and prefix('/a/b/') == 'a/b' and prefix('a' + chr(92) + 'b') == 'a/b'


def test_a_command_goes_into_a_folder_of_another_drive_too(task, task_namespace):
    # cmd.exe's "cd <path>" stays on the current drive: every command of the task that enters a folder uses CD
    assert task['CD'] == ('cd /d' if os.name == 'nt' else 'cd')
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(here, 'task', 'clone-git', 'api_v1.py'), encoding = 'utf-8') as f:
        src = f.read()
    assert "f'cd " not in src and 'f"cd ' not in src and src.count("f'{CD} ") >= 8


@pytest.mark.skipif(os.name != 'nt', reason = 'the drives of Windows')
def test_cd_d_enters_a_folder_of_another_drive(tmp_path):
    # the fact itself, with cmd.exe: from a folder of one drive, "cd" to another drive's folder stays; "cd /d" enters
    here = str(tmp_path)
    others = [d + ':' + chr(92) for d in 'CDEFGXYZ' if os.path.isdir(d + ':' + chr(92)) and d.upper() != here[0].upper()]
    if not others:
        pytest.skip('this machine has one drive')
    other = others[0]
    plain = subprocess.run(f'cd {other} && cd', shell = True, cwd = here, stdout = subprocess.PIPE, stdin = subprocess.DEVNULL)
    with_d = subprocess.run(f'cd /d {other} && cd', shell = True, cwd = here, stdout = subprocess.PIPE, stdin = subprocess.DEVNULL)
    assert plain.stdout.decode('utf-8', 'replace').strip().upper().startswith(here[0].upper() + ':')
    assert with_d.stdout.decode('utf-8', 'replace').strip().upper() == other.upper()


def test_a_name_that_is_no_submodule_is_refused(task, sources, tmp_path):
    clone = tmp_path / 'c'
    git('clone', '-q', str(sources), str(clone))
    git('submodule', 'update', '--init', cwd = clone)
    r = under(task, clone, ['third_party/unusedd'])
    assert r['return'] > 0 and 'third_party/unusedd' in r['error'] and 'third_party/unused' in r['error']


def test_the_git_folders_of_submodules_as_git_lays_them_out(task, sources, tmp_path):
    clone = tmp_path / 'c'
    git('clone', '-q', '--recursive', str(sources), str(clone))
    dirs = task['submodule_git_dirs'](GIT, str(clone))
    rel = {os.path.relpath(d, clone).replace('\\', '/'): s for d, s in dirs}
    assert rel == {'.git/modules/third_party/used': 'third_party/used',
                   '.git/modules/third_party/used/modules/external/inner': 'third_party/used/external/inner',
                   '.git/modules/third_party/unused': 'third_party/unused',
                   '.git/modules/third_party/unused/modules/third_party/deep': 'third_party/unused/third_party/deep',
                   '.git/modules/third_party/unused/modules/third_party/deep/modules/3rdparty/deeper': 'third_party/unused/third_party/deep/3rdparty/deeper',
                   '.git/modules/third_party/plain': 'third_party/plain'}
    assert all(os.path.isdir(d) for d, _ in dirs)                    # they are where Git put them
    assert len(dirs[0][0]) == max(len(d) for d, _ in dirs)           # the longest first


def test_a_git_folder_over_gits_limit_on_windows_is_said_with_the_way_out(task, sources, tmp_path, monkeypatch):
    clone = tmp_path / 'c'
    git('clone', '-q', '--recursive', str(sources), str(clone))
    problem = task['windows_git_dir_problem']
    assert problem(GIT, str(clone)) == '' or len(str(clone)) > 150         # a short folder: no problem

    longest = max(len(d) for d, _ in task['submodule_git_dirs'](GIT, str(clone)))
    monkeypatch.setitem(task, 'WINDOWS_GIT_DIR_LIMIT', longest - 7)        # as if the clone were 7 characters too deep
    text = problem(GIT, str(clone))
    assert f'longer than {longest - 7} characters' in text and '7 characters too deep' in text
    assert 'third_party/unused/third_party/deep/3rdparty/deeper' in text  # the longest one is named
    assert '2 submodules' in text or '1 submodule ' in text or 'submodule' in text
    assert 'file_cache' in text and str(clone) in text
    assert task['WINDOWS_GIT_DIR_LIMIT'] == longest - 7


def test_the_limit_is_what_git_for_windows_refuses(task):
    # measured with Git for Windows 2.53: a git folder of 220 characters works, 221 is refused ('$GIT_DIR' too big)
    assert task['WINDOWS_GIT_DIR_LIMIT'] == 220


def test_the_submodule_words_reach_clone_git_from_clone_git_to_cache(task_namespace, tmp_path):
    ns = task_namespace('clone-git-to-cache')

    class CM:
        debug = False
        calls = []

        def catch_error(self, r, fail16 = False):
            return r['return'] > 0

        def access(self, ii):
            self.calls.append(ii)
            return {'return': 0, 'path_to_git_repo': '/cache/src'}

    t = ns['CTask'].__new__(ns['CTask'])
    t.cm = CM()
    t.category_alias, t.category_uid = 'task', 'c36be4b9314a45e0'
    ctx = {'control': {'con': False, 'quiet': True, 'verbose': False},
           'tasks': {'nested_call': 0, 'global': {}, 'cparams': {}, 'run_control': {'cur_dir': str(tmp_path), 'work_dir': str(tmp_path)}}}
    r = t.run(ctx, name = 'src-x', url = 'https://github.com/org/x', checkout = 'main', update_submodules = True,
              submodules_depth = 1, submodules_not_recursive = ['third_party/unused'],
              submodules_files = ['third_party/unused/third_party/deep/LICENSE'])
    assert r['return'] == 0
    call = t.cm.calls[0]
    assert call['submodules_depth'] == 1 and call['submodules_not_recursive'] == ['third_party/unused']
    assert call['submodules_files'] == ['third_party/unused/third_party/deep/LICENSE']
