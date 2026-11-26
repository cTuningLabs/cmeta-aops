"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/oneapi's install (Intel Deep Learning Essentials): the release a request means, the table of
releases, the commands handed to Intel's installer on each system, what an install folder holds, and the licence
that is the user's to accept.
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / 'tool' / 'oneapi'


@pytest.fixture(scope = 'module')
def tool():
    """The module-level code of the hook file, up to its class (which needs cMeta)."""
    path = TOOL / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    head = src[:src.index('\nclass CTool')]
    for line in ('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                 'from tool_c393ba5c6fa14f66.api.common_deb import sha256_of'):
        assert line in head
        head = head.replace(line, '')
    # Intel's installer helpers, shared with the other tools that install Intel's tools (common_intel.py)
    start = head.index('from tool_c393ba5c6fa14f66.api.common_intel import')
    head = head[:start] + head[head.index(')', start) + 1:]
    ns = {'__name__': 'oneapi_helpers', '__file__': str(path)}
    shared = REPO_ROOT / 'category' / 'tool' / 'api' / 'common_intel.py'
    exec(compile(shared.read_text(encoding = 'utf-8'), str(shared), 'exec'), ns)
    exec(compile(head, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def desc():
    with open(TOOL / '_desc.yaml', encoding = 'utf-8') as f:
        return yaml.safe_load(f)


def matches(spec, version):
    """The engine's version match, enough of it for these tests: ranges with commas, a plain version as a prefix."""
    def key(v):
        return tuple(int(p) for p in str(v).split('.') if p.isdigit())
    for part in str(spec).split(','):
        part = part.strip()
        for op in ('>=', '<=', '==', '>', '<'):
            if part.startswith(op):
                want, have = key(part[len(op):]), key(version)
                n = max(len(want), len(have))
                want, have = want + (0,) * (n - len(want)), have + (0,) * (n - len(have))
                if not {'>=': have >= want, '<=': have <= want, '==': have == want, '>': have > want, '<': have < want}[op]:
                    return False
                break
        else:
            if key(version)[:len(key(part))] != key(part):
                return False
    return True


TABLE = {
    '2026.2.0': {'linux': {'url': 'u-262-l'}, 'windows': {'url': 'u-262-w'}},
    '2026.1.3': {'linux': {'url': 'u-2613-l', 'compiler': '2026.1.1'}, 'windows': {'url': 'u-2613-w'}},
    '2026.1.2': {'linux': {'url': 'u-2612-l'}, 'windows': {'url': 'u-2612-w'}},
    '2025.3.3': {'linux': {'url': 'u-2533-l'}},
}


@pytest.mark.parametrize('system, asked, default, release', [
    ('linux', '', '2026.1', '2026.1.3'),              # nothing asked: the default line, its newest release
    ('linux', '2026.1', '2026.1', '2026.1.3'),        # a line: its newest release, not the older one of the line
    ('linux', '2026.2', '2026.1', '2026.2.0'),
    ('linux', '>=2026.0', '2026.1', '2026.2.0'),      # a range: the newest release whose line is inside
    ('linux', '>=2026.0,<2026.2', '2026.1', '2026.1.3'),
    ('linux', 'latest', '2026.1', '2026.2.0'),
    ('linux', '2026.1.1', '2026.1', '2026.1.3'),      # the compiler's version, where the table knows it
    ('linux', '2025.3', '2026.1', '2025.3.3'),
    ('windows', '2026.1', '2026.1', '2026.1.3'),
    ('windows', '', '', '2026.2.0'),                  # no default: the newest
])
def test_a_request_names_a_line_of_oneapi_or_a_compiler_version(tool, system, asked, default, release):
    name, entry, why = tool['release_for'](TABLE, system, asked, default, matches)
    assert (name, why) == (release, None)
    assert entry is TABLE[release][system]


@pytest.mark.parametrize('system, asked, words', [
    ('linux', '2026.1.3', ['2026.1.3', 'known lines: 2026.2, 2026.1, 2025.3', 'compiler']),   # the package's number
    ('linux', '2024.2', ['2024.2']),
    ('windows', '2025.3', ['2025.3', 'windows']),      # known for another system only: never another release instead
    ('windows', '2026.1.1', ['2026.1.1']),             # a compiler version read on Linux says nothing about Windows
    ('darwin', '', ['darwin']),
])
def test_a_request_the_table_cannot_answer_is_said(tool, system, asked, words):
    name, entry, why = tool['release_for'](TABLE, system, asked, '2026.1', matches)
    assert name is None and entry is None
    for word in words:
        assert word in why


def test_the_table_of_releases_is_whole(tool, desc):
    releases = desc['releases']
    assert len(releases) >= 5
    for name, systems in releases.items():
        assert re.fullmatch(r'\d{4}\.\d+\.\d+', str(name))
        assert set(systems) == {'linux', 'windows'}, name
        for system, entry in systems.items():
            ext = {'linux': 'sh', 'windows': 'exe'}[system]
            assert str(entry['build']).startswith(str(name) + '.'), (name, system)
            assert re.fullmatch(r'https://registrationcenter-download\.intel\.com/akdlm/IRC_NAS/[0-9a-f-]{36}/'
                                r'intel-deep-learning-essentials-' + re.escape(str(entry['build'])) + r'_offline\.' + ext,
                                entry['url']), (name, system)
            assert isinstance(entry['size'], int) and entry['size'] > 500_000_000
            assert re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])

    # the default is a line of the table on both systems
    for system in ('linux', 'windows'):
        name, _, why = tool['release_for'](releases, system, '', desc['default_version'], matches)
        assert why is None and tool['line_of'](name) == str(desc['default_version'])


def test_an_install_folder_gets_an_instance_of_its_own(tool, tmp_path):
    a, b = tool['instance_of'](str(tmp_path / 'a')), tool['instance_of'](str(tmp_path / 'b'))
    assert a != b and a == tool['instance_of'](str(tmp_path / 'a'))
    assert re.fullmatch(r'cmeta-[0-9a-f]{12}', a)


def test_linux_installs_without_root_into_the_folder_it_is_given(tool):
    cmd = tool['linux_command']('/c/downloads/x_offline.sh', '/c/content', '/c/extract', '/c/log', 'cmeta-0123456789ab', '/c/pkgs')
    assert not re.search(r'\bsudo\b', cmd)
    head, tail = cmd.split(' -a ')                      # before -a: the unpacking; after it: Intel's installer
    assert head == 'sh "/c/downloads/x_offline.sh" -f "/c/extract" -r yes'
    for word in ('--silent', '--eula accept', '--install-dir "/c/content"', '--instance cmeta-0123456789ab',
                 '--intel-sw-improvement-program-consent decline', '--log-dir "/c/log"', '--download-cache "/c/pkgs"'):
        assert word in tail, word


def test_windows_waits_for_the_installer_and_drops_the_file_only_after_a_good_install(tool, desc):
    cmd = tool['windows_command']('C:/c/downloads/x_offline.exe', 'C:/c/log')
    run, after = cmd.split(' && ')
    assert run.startswith('start "" /wait "C:/c/downloads/x_offline.exe" -s -a ')
    for word in ('--silent', '--eula accept', '--intel-sw-improvement-program-consent decline', '--log-dir "C:/c/log"'):
        assert word in run, word
    assert '--install-dir' not in run                   # where Intel installs: beside the oneAPI a machine has
    assert after == 'del /q "C:/c/downloads/x_offline.exe"'

    # --with.install_dir: the folder the user names, with its spaces
    run, after = tool['windows_command']('C:/c/downloads/x_offline.exe', 'C:/c/log', 'D:/Program Files (x86)/Intel/oneAPI').split(' && ')
    assert '--install-dir "D:/Program Files (x86)/Intel/oneAPI" ' in run and run.startswith('start "" /wait ')
    assert after == 'del /q "C:/c/downloads/x_offline.exe"'
    assert 'NEED_VS' not in run                          # Intel's default: the integration with Visual Studio

    # --with.vs_integration=no: every Visual Studio version Intel's installer knows, unset; still silent
    run = tool['windows_command']('C:/c/x.exe', 'C:/c/log', vs_integration = False).split(' && ')[0]
    for year in ('2017', '2019', '2022', '2026'):
        assert f'-p=NEED_VS{year}_INTEGRATION=0 ' in run
    assert ' -s -a --silent --eula accept ' in run

    # --with.gui=yes: Intel's wizard, no switch of the silent mode; the file still goes after a good install
    assert tool['windows_command']('C:/c/x.exe', 'C:/c/log', 'D:/x', gui = True) == 'start "" /wait "C:/c/x.exe" && del /q "C:/c/x.exe"'

    # the installer asks for administrator rights: a quiet run from a plain process prints the command instead
    assert desc['requires_sudo'] == {'windows': True}


def test_intels_installers_take_only_the_components_asked(tool):
    # common_intel.py, the helpers every tool that installs one of Intel's tools shares (a tool of a plugged repository
    # installs VTune alone from the oneAPI Toolkit's online installer): Intel's own colon-separated list, or nothing
    w = tool['windows_command']('C:/c/i.exe', 'C:/c/log', vs_integration = False, components = ['intel.oneapi.win.vtune'])
    assert '--components intel.oneapi.win.vtune ' in w and '-p=NEED_VS2026_INTEGRATION=0' in w
    linux = tool['linux_command']('/c/i.sh', '/c/content', '/c/x', '/c/log', 'cmeta-0', '/c/p', ['intel.a', 'intel.b'])
    assert '--components intel.a:intel.b ' in linux
    assert '--components' not in tool['windows_command']('C:/c/i.exe', 'C:/c/log')
    assert '--components' not in tool['linux_command']('/c/i.sh', '/c/content', '/c/x', '/c/log', 'cmeta-0', '/c/p')
    assert '--components' not in tool['windows_command']('C:/c/i.exe', 'C:/c/log', gui = True, components = ['x'])   # the wizard asks


def test_the_environment_scripts_of_an_install_folder(tool, tmp_path):
    for rel in ('2026.1/oneapi-vars.sh', 'common/2026.0/oneapi-vars.sh', 'latest/oneapi-vars.sh', 'compiler/2026.1/env/vars.sh',
                'setvars.sh', '2026.1/oneapi-vars.bat'):
        path = tmp_path / rel
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text('')
    assert tool['vars_scripts'](str(tmp_path), 'linux') == [str(tmp_path / '2026.1' / 'oneapi-vars.sh')]
    assert tool['vars_scripts'](str(tmp_path), 'windows') == [str(tmp_path / '2026.1' / 'oneapi-vars.bat')]
    assert tool['vars_scripts'](str(tmp_path / 'nothing-here'), 'linux') == []


def test_the_commands_that_remove_an_instance_come_from_the_installers_list(tool):
    text = '''ID                                                Version     Installed Name
========================================================================================================
intel.oneapi.lin.deep-learning-essentials.product 2026.1.3+10 true      Intel Deep Learning Essentials
intel.oneapi.lin.other.product                    2026.1.0+1  false     Something not installed
'''
    cmds = tool['removal_commands']('/h/intel/oneapi/installer/installer', text, 'cmeta-0123456789ab')
    assert cmds == ['"/h/intel/oneapi/installer/installer" --silent --action remove '
                    '--product-id intel.oneapi.lin.deep-learning-essentials.product --product-ver "2026.1.3+10" '
                    '--instance cmeta-0123456789ab --eula accept']
    assert tool['removal_commands']('/x', 'Installer failed with error ...', 'i') == []


def test_the_licence_is_the_users_to_accept_before_anything_is_downloaded(tool, desc):
    src = (TOOL / 'api_v1.py').read_text(encoding = 'utf-8')
    body = src[src.index('    def install(self,'):]
    assert body.index("truthy(_with.get('accept_eula'))") < body.index("'arg1': 'download-file,03fed13e2e0447cf'")
    assert '--with.accept_eula=yes' in body and '--use.oneapi.with.accept_eula=yes' in body
    assert tool['EULA_URL'].startswith('https://www.intel.com/') and tool['EULA_URL'] in desc['install_help_text']
    for value, yes in (('yes', True), (True, True), ('accepted', True), ('', False), (None, False), ('no', False)):
        assert tool['truthy'](value) is yes


def test_intels_folders_are_searched_on_linux_too(desc):
    assert '/opt/intel/oneapi/*' in desc['extra_paths']['linux']
    assert any(p.endswith('/intel/oneapi/*') and 'HOME' in p for p in desc['extra_paths']['linux'])


def test_what_an_environment_script_adds_to_a_list_of_paths_is_added_not_put_in_its_place():
    # oneapi-vars.sh sets LD_LIBRARY_PATH and OCL_ICD_FILENAMES: as plain values they dropped the libraries and the ICD
    # that the Intel GPU runtime of the same run had added, and SYCL saw the CPU only
    with open(REPO_ROOT / 'task' / 'setup' / '_desc.yaml', encoding = 'utf-8') as f:
        keys = set(yaml.safe_load(f)['add_env_path_keys'])
    for key in ('PATH', 'LD_LIBRARY_PATH', 'LIBRARY_PATH', 'CPATH', 'PKG_CONFIG_PATH', 'CMAKE_PREFIX_PATH', 'OCL_ICD_FILENAMES',
                'INCLUDE', 'LIB', 'LIBPATH'):
        assert key in keys, key

    # the keys are applied where a tool's environment script was called: "+KEY" lists of the aggregated environment
    src = (REPO_ROOT / 'task' / 'setup' / 'detect.py').read_text(encoding = 'utf-8')
    assert "for key in self.cdesc['add_env_path_keys']:" in src
    assert "env_added['+'+key] = env_added.pop(key).split(os.pathsep)" in src


def test_the_whole_hook_file_compiles():
    # the fixture runs the module's head only: a broken line in the class (a quote lost on the way) would pass it
    path = TOOL / 'api_v1.py'
    compile(path.read_text(encoding = 'utf-8'), str(path), 'exec')
    path = REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py'
    compile(path.read_text(encoding = 'utf-8'), str(path), 'exec')
