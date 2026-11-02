"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the iPhone targets: the helpers of category/task/api/ios.py (the app bundle, the commands
of codesign, devicectl and the exit check, the signing route, the probe), the device and signing helpers of
task/target--ios-cpu (the device words, the identities, the profiles, the cache filter) and the iOS facts of
the build stamp. Nothing here needs a Mac or a device.
"""

import datetime
import importlib.util
import json
import os
import pathlib
import plistlib
import stat

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel):
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(path.stem + '_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = 'module')
def ios():
    return load('category/task/api/ios.py')


@pytest.fixture(scope = 'module')
def stamp():
    return load('category/task/api/build_stamp.py')


@pytest.fixture(scope = 'module')
def target(task_namespace):
    return task_namespace('target--ios-cpu')


def q(s):
    return f'"{s}"' if ' ' in s else s


# The bundle and the commands

def test_bundle_around_the_executable(ios, tmp_path):
    exe = tmp_path / 'program'
    exe.write_bytes(b'\xcf\xfa\xed\xfe')
    profile = tmp_path / 'dev.mobileprovision'
    profile.write_bytes(b'profile')
    app = tmp_path / 'program.app'
    assert ios.make_bundle(str(app), str(exe), 'org.ctuning.cmeta.runner', str(profile), '16.0') is None
    assert (app / 'embedded.mobileprovision').read_bytes() == b'profile'
    assert (app / 'program').read_bytes() == exe.read_bytes()
    if os.name != 'nt':
        assert (app / 'program').stat().st_mode & stat.S_IXUSR
    with open(app / 'Info.plist', 'rb') as f:
        info = plistlib.load(f)
    assert info['CFBundleIdentifier'] == 'org.ctuning.cmeta.runner'
    assert info['CFBundleExecutable'] == 'program' and info['CFBundleName'] == 'program'
    assert info['MinimumOSVersion'] == '16.0' and info['LSRequiresIPhoneOS'] is True
    assert info['CFBundleSupportedPlatforms'] == ['iPhoneOS'] and info['UILaunchScreen'] == {}

    # a bundle of a previous run is replaced
    (app / 'leftover').write_text('x')
    assert ios.make_bundle(str(app), str(exe), 'org.x', str(profile), '17.0', 'cMeta probe') is None
    assert not (app / 'leftover').exists()
    with open(app / 'Info.plist', 'rb') as f:
        assert plistlib.load(f)['CFBundleDisplayName'] == 'cMeta probe'


def test_bundle_errors_are_returned(ios, tmp_path):
    error = ios.make_bundle(str(tmp_path / 'a.app'), str(tmp_path / 'missing'), 'org.x', str(tmp_path / 'p'), '16.0')
    assert error and 'missing' in error


def test_launch_command(ios):
    prefix = ios.launch_prefix('xcrun devicectl', 'UDID1', 'org.ctuning.cmeta.runner', {'CMETA_TARGETS': 'ios-cpu', 'CMETA_IOS_CLEAN': 'a.json;b.txt'})
    assert prefix.startswith('xcrun devicectl device process launch --console --terminate-existing --environment-variables ')
    assert prefix.endswith(' --device UDID1 org.ctuning.cmeta.runner ')
    env = prefix.split('--environment-variables ', 1)[1].split(' --device')[0]
    assert env.startswith("'") and env.endswith("'")
    assert json.loads(env[1:-1]) == {'CMETA_TARGETS': 'ios-cpu', 'CMETA_IOS_CLEAN': 'a.json;b.txt'}
    assert '--environment-variables' not in ios.launch_prefix('xcrun devicectl', 'U', 'org.x')
    assert ios.LAUNCH_POSTFIX == ' < /dev/null'


def test_copy_sign_install_and_exit_commands(ios):
    assert ios.codesign_cmd('', 'Apple Development: x (ID)', '/e/ent.plist', '/b/p.app', q) == \
        'codesign --force --sign "Apple Development: x (ID)" --entitlements /e/ent.plist --timestamp=none /b/p.app'
    assert ios.codesign_cmd('sudo -n launchctl asuser 501 sudo -n -u me ', 'I', '/e', '/a', q).startswith('sudo -n launchctl asuser 501 sudo -n -u me codesign ')
    assert ios.install_cmd('/x/devicectl', 'U', '/b/p.app', q) == '/x/devicectl device install app --device U /b/p.app'
    assert ios.copy_to_cmd('/x/devicectl', 'U', 'org.x', '/in/data.bin', 'data.bin', q) == \
        '/x/devicectl device copy to --device U --domain-type appDataContainer --domain-identifier org.x --source /in/data.bin --destination Documents/data.bin'
    assert ios.copy_from_cmd('/x/devicectl', 'U', 'org.x', 'out.json', 'out.json', q) == \
        '/x/devicectl device copy from --device U --domain-type appDataContainer --domain-identifier org.x --source Documents/out.json --destination out.json'
    assert ios.exit_check_cmd() == 'grep -qx 0 tmp-cmeta-ios-exit.txt'
    assert ios.EXIT_FILE == 'tmp-cmeta-ios-exit.txt'


# The signing route of the session

def test_signing_prefix_unlocked_keychain(ios, monkeypatch):
    monkeypatch.setattr(ios, '_run', lambda argv, timeout = 60: (0, 'Keychain "login.keychain-db" lock-on-sleep timeout=300s'))
    assert ios.signing_prefix() == ('', None)


def test_signing_prefix_locked_keychain_through_the_gui_session(ios, monkeypatch):
    calls = []

    def run(argv, timeout = 60):
        calls.append(argv)
        if argv[0] == 'security':
            return 36, 'security: SecKeychainCopySettings: User interaction is not allowed.'
        return 0, ''

    monkeypatch.setattr(ios, '_run', run)
    monkeypatch.setattr(ios.os, 'getuid', lambda: 501, raising = False)
    monkeypatch.setattr(ios.getpass, 'getuser', lambda: 'fursin')
    assert ios.signing_prefix() == ('sudo -n launchctl asuser 501 sudo -n -u fursin ', None)
    assert calls[1] == ['sudo', '-n', 'true']


def test_signing_prefix_locked_keychain_without_sudo(ios, monkeypatch):
    monkeypatch.setattr(ios, '_run', lambda argv, timeout = 60: (36, 'User interaction is not allowed.') if argv[0] == 'security' else (1, 'sudo: a password is required'))
    prefix, error = ios.signing_prefix()
    assert prefix is None and 'security unlock-keychain' in error


# The probe: an app built, signed, installed and launched, one JSON line back

class FakeCM:
    def q(self, s):
        return q(s)

    def error(self, text, code = 1):
        return {'return': code, 'error': text}

    def catch_error(self, r, fail16 = False):
        return r.get('return', 0) > 0


class FakeTask:
    cm = FakeCM()
    category_alias = 'task'
    category_uid = 'c36be4b9314a45e0'


def probe_ctx(tmp_path):
    (tmp_path / 'clang').write_text('')
    (tmp_path / 'profile').write_text('')
    (tmp_path / 'probe.m').write_text('int main(void) { return 0; }')
    return {'control': {}, 'tasks': {'nested_call': 0, 'global': {
        'apple-xcode': {'path_toolchain_bin': str(tmp_path), 'ios_sdk_path': str(tmp_path)},
        'target--ios-cpu': {'udid': 'UDID1', 'min_os': '16.0', 'devicectl': '/x/devicectl',
                            'signing': {'profile': str(tmp_path / 'profile'), 'identity': 'Apple Development: me (ID)',
                                        'entitlements': str(tmp_path / 'ent.plist'), 'bundle_id': 'org.ctuning.cmeta.runner'}}}}}


def test_probe_builds_signs_installs_launches_and_parses(ios, tmp_path, monkeypatch):
    ctx = probe_ctx(tmp_path)
    runs = []

    def cmd(task, ctx, cmds, capture = False, timeout = None):
        runs.append(list(cmds))
        out = 'CMETA_PROBE: {"name": "Apple A19 GPU", "apple_family": 10}\n' if 'process launch' in cmds[0] else ''
        return {'return': 0, 'stdout': out, 'stderr': ''}

    monkeypatch.setattr(ios, '_cmd', cmd)
    monkeypatch.setattr(ios, 'signing_prefix', lambda: ('', None))
    bundles = []
    monkeypatch.setattr(ios, 'make_bundle', lambda *a: bundles.append(a) or None)

    r = ios.probe(FakeTask(), ctx, str(tmp_path / 'probe.m'), ['Foundation', 'Metal'], 'cmeta-probe-gpu')
    assert r == {'return': 0, 'probe': {'name': 'Apple A19 GPU', 'apple_family': 10}}

    compile_cmd, sign_install, launch = runs
    assert compile_cmd[0].startswith(q(str(tmp_path / 'clang')) + ' -isysroot ')
    assert '-arch arm64 -miphoneos-version-min=16.0 -fobjc-arc -framework Foundation -framework Metal -o ' in compile_cmd[0]
    assert compile_cmd[0].endswith(q(str(tmp_path / 'probe.m')))
    assert sign_install[0].startswith('codesign --force --sign "Apple Development: me (ID)"')
    assert sign_install[1].startswith('/x/devicectl device install app --device UDID1 ')
    assert launch[0] == '/x/devicectl device process launch --console --terminate-existing --device UDID1 org.ctuning.cmeta.runner  < /dev/null'
    assert bundles and bundles[0][2] == 'org.ctuning.cmeta.runner' and bundles[0][5] == 'cMeta probe'

    # the temporary folder is gone
    assert 'cmeta-ios-probe-' in bundles[0][0] and not os.path.isdir(os.path.dirname(bundles[0][0]))


def test_probe_without_the_line_or_with_an_error(ios, tmp_path, monkeypatch):
    ctx = probe_ctx(tmp_path)
    monkeypatch.setattr(ios, 'signing_prefix', lambda: ('', None))
    monkeypatch.setattr(ios, 'make_bundle', lambda *a: None)

    monkeypatch.setattr(ios, '_cmd', lambda task, ctx, cmds, capture = False, timeout = None: {'return': 0, 'stdout': 'nothing', 'stderr': ''})
    r = ios.probe(FakeTask(), ctx, str(tmp_path / 'probe.m'), ['Foundation'], 'p')
    assert r['return'] > 0 and 'printed no CMETA_PROBE: line' in r['error']

    monkeypatch.setattr(ios, '_cmd', lambda task, ctx, cmds, capture = False, timeout = None: {'return': 0, 'stdout': 'CMETA_PROBE: {"error": "no Metal device"}', 'stderr': ''})
    r = ios.probe(FakeTask(), ctx, str(tmp_path / 'probe.m'), ['Foundation'], 'p')
    assert r['return'] > 0 and 'no Metal device' in r['error']

    # a locked keychain without a way to the key stops before the install
    monkeypatch.setattr(ios, 'signing_prefix', lambda: (None, 'the login keychain is locked'))
    r = ios.probe(FakeTask(), ctx, str(tmp_path / 'probe.m'), ['Foundation'], 'p')
    assert r['return'] > 0 and 'keychain is locked' in r['error']


def test_probe_needs_the_cpu_target_and_xcode(ios, tmp_path):
    ctx = probe_ctx(tmp_path)
    del ctx['tasks']['global']['target--ios-cpu']
    assert 'target--ios-cpu' in ios.probe(FakeTask(), ctx, 'p.m', [], 'p')['error']
    ctx = probe_ctx(tmp_path)
    ctx['tasks']['global']['apple-xcode']['ios_sdk_path'] = ''
    assert 'iOS SDK' in ios.probe(FakeTask(), ctx, 'p.m', [], 'p')['error']


# The device and signing helpers of target--ios-cpu

DEVICE = {'identifier': '38FCDC41-A80B-514F-BBA4-FFABBA534CC2',
          'hardwareProperties': {'udid': '00008150-000C259126E0C01C', 'serialNumber': 'F36537R42J', 'ecid': 3419005073276956,
                                 'marketingName': 'iPhone 17', 'productType': 'iPhone18,3', 'platform': 'iOS'},
          'deviceProperties': {'name': 'iPhone', 'osVersionNumber': '27.0.1'},
          'connectionProperties': {'pairingState': 'paired'}}

IDENTITIES = '''Policy: Code Signing
  Matching identities
  1) 1234567890ABCDEF1234567890ABCDEF12345678 "Apple Development: fursin_g@yahoo.fr (9D2D8TV87S)"
  2) ABCDEF1234567890ABCDEF1234567890ABCDEF12 "Developer ID Application: Someone (TEAM)"
     2 identities found

  Valid identities only
     0 valid identities found
'''


def test_device_words(target):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    for word in ('00008150-000C259126E0C01C', '38fcdc41-a80b-514f-bba4-ffabba534cc2', 'F36537R42J', '3419005073276956',
                 'iphone', 'iPhone 17', 'iphone18,3', 'iPhone18'):
        assert task._matches(DEVICE, word), word
    for word in ('0000815', 'ipad', 'F36537R42', ''):
        assert not task._matches(DEVICE, word), word
    assert task._label(DEVICE) == 'iPhone (iPhone 17, iPhone18,3, iOS 27.0.1, 00008150-000C259126E0C01C)'


def test_identities_are_read_from_both_lists_once(target):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    task.cm = FakeCM()
    task._run = lambda ctx, cmd, timeout = None: {'return': 0, 'returncode': 0, 'stdout': IDENTITIES, 'stderr': ''}
    r = task._identities({})
    assert r['return'] == 0
    assert r['identities'] == [{'hash': '1234567890ABCDEF1234567890ABCDEF12345678', 'name': 'Apple Development: fursin_g@yahoo.fr (9D2D8TV87S)'},
                               {'hash': 'ABCDEF1234567890ABCDEF1234567890ABCDEF12', 'name': 'Developer ID Application: Someone (TEAM)'}]


def test_team_is_the_ou_of_the_certificate(target):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    task.cm = FakeCM()
    task._run = lambda ctx, cmd, timeout = None: {'return': 0, 'returncode': 0, 'stderr': '',
                                                  'stdout': 'subject= /UID=9JNV2882S9/CN=Apple Development: x (9D2D8TV87S)/OU=8422C4F4W6/O=Grigori Fursin/C=US\n'}
    assert task._team({}, 'Apple Development: x (9D2D8TV87S)') == {'return': 0, 'team': '8422C4F4W6'}
    task._run = lambda ctx, cmd, timeout = None: {'return': 0, 'returncode': 0, 'stdout': 'unable to load certificate', 'stderr': ''}
    assert task._team({}, 'nobody')['return'] > 0


def test_the_newest_valid_profile_of_the_device_is_taken(target, tmp_path, monkeypatch):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    monkeypatch.setitem(target, 'PROFILE_DIRS', [str(tmp_path)])
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo = None)
    day = datetime.timedelta(days = 1)
    profiles = {
        'a.mobileprovision': {'Name': 'old', 'CreationDate': now - 5 * day, 'ExpirationDate': now + 2 * day,
                              'Entitlements': {'application-identifier': 'TEAM.org.x'}, 'ProvisionedDevices': ['U1']},
        'b.mobileprovision': {'Name': 'new', 'CreationDate': now - 1 * day, 'ExpirationDate': now + 6 * day,
                              'Entitlements': {'application-identifier': 'TEAM.org.x'}, 'ProvisionedDevices': ['U1', 'U2']},
        'c.mobileprovision': {'Name': 'expired', 'CreationDate': now, 'ExpirationDate': now - day,
                              'Entitlements': {'application-identifier': 'TEAM.org.x'}, 'ProvisionedDevices': ['U1']},
        'd.mobileprovision': {'Name': 'other app', 'CreationDate': now, 'ExpirationDate': now + day,
                              'Entitlements': {'application-identifier': 'TEAM.org.y'}, 'ProvisionedDevices': ['U1']},
        'e.mobileprovision': {'Name': 'other device', 'CreationDate': now, 'ExpirationDate': now + day,
                              'Entitlements': {'application-identifier': 'TEAM.org.x'}, 'ProvisionedDevices': ['U3']},
        'f.txt': {},
    }
    for name in profiles:
        (tmp_path / name).write_text('')
    task._read_profile = lambda ctx, path: profiles.get(os.path.basename(path))
    r = task._find_profile({}, 'TEAM', 'org.x', 'U1')
    assert r['return'] == 0 and r['profile']['data']['Name'] == 'new' and r['profile']['path'] == str(tmp_path / 'b.mobileprovision')
    assert task._find_profile({}, 'TEAM', 'org.x', 'U9')['profile'] is None
    assert task._find_profile({}, 'OTHER', 'org.x', 'U1')['profile'] is None


def test_cached_targets_with_an_expired_or_missing_profile_are_not_reused(target, tmp_path):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo = None)
    profile = tmp_path / 'p.mobileprovision'
    profile.write_text('')

    def entry(name, expires, path):
        d = tmp_path / name
        d.mkdir()
        (d / 'cmeta-task-cached-result.json').write_text(json.dumps({'return': 0, 'signing': {'profile': path, 'profile_expires': expires}}))
        return {'path': str(d)}

    valid = entry('valid', (now + datetime.timedelta(days = 3)).isoformat(), str(profile))
    expired = entry('expired', (now - datetime.timedelta(days = 1)).isoformat(), str(profile))
    gone = entry('gone', (now + datetime.timedelta(days = 3)).isoformat(), str(tmp_path / 'missing.mobileprovision'))
    no_result = {'path': str(tmp_path / 'nothing')}
    r = task.filter_cache_artifacts({'control': {}, 'tasks': {}}, [valid, expired, gone, no_result], ['t'], {})
    assert r == {'return': 0, 'artifacts': [valid, no_result], 'tmp_artifacts': ['t']}


def test_runner_project_is_written_for_the_team_and_bundle(target, tmp_path):
    CTask = target['CTask']
    task = CTask.__new__(CTask)
    proj = task._write_runner_project(str(tmp_path / 'runner'), 'org.ctuning.cmeta.runner', '8422C4F4W6', '16.0')
    pbx = pathlib.Path(proj, 'project.pbxproj').read_text(encoding = 'utf-8')
    assert 'PRODUCT_BUNDLE_IDENTIFIER = "org.ctuning.cmeta.runner";' in pbx
    assert 'DEVELOPMENT_TEAM = 8422C4F4W6;' in pbx and 'IPHONEOS_DEPLOYMENT_TARGET = 16.0;' in pbx
    assert 'CODE_SIGN_STYLE = Automatic;' in pbx and '\t' in pbx
    scheme = pathlib.Path(proj, 'xcshareddata', 'xcschemes', 'CMetaRunner.xcscheme').read_text(encoding = 'utf-8')
    assert scheme.count('container:CMetaRunner.xcodeproj') == 2
    assert (tmp_path / 'runner' / 'CMetaRunner' / 'main.c').read_text(encoding = 'utf-8').startswith('#include <stdio.h>')


def test_launcher_source_renames_nothing_of_its_own():
    src = (REPO_ROOT / 'task' / 'target--ios-cpu' / 'src' / 'cmeta_ios_main.c').read_text(encoding = 'utf-8')
    assert '#undef main' in src and 'int cmeta_program_main(int argc, char **argv);' in src
    assert 'CMETA_IOS_CLEAN' in src and 'tmp-cmeta-ios-exit.txt' in src


# The build stamp and the compile hook

def test_stamp_compares_the_ios_device(stamp):
    s = stamp.make_stamp('p', 'u', ['ios-cpu'], 'darwin', ios = {'udid': 'A'})
    assert s['ios'] == {'udid': 'A'} and s['android'] is None
    assert stamp.differences(s, ios = {'udid': 'A'}) == []
    assert stamp.differences(s, ios = {'udid': 'B'}) == [('ios udid', 'A', 'B')]
    assert stamp.differences(s, ios = None) == []
    old = stamp.make_stamp('p', 'u', ['cpu'], 'darwin')
    assert 'ios' in old and old['ios'] is None
    assert stamp.differences({'version': 1, 'compute': ['cpu']}, ios = {'udid': 'A'}) == []


def test_setup_compile_links_extra_sources_into_executables_only():
    src = (REPO_ROOT / 'task' / 'setup-compile' / 'api_v1.py').read_text(encoding = 'utf-8')
    i = src.index("x = compiler_features.get('target_arch', {}).get('exe_extra_sources')")
    assert src.index("if x and not _lib:", i) < src.index("x = _with.get('flags4')", i)
    assert src.index("x = result.get('src_file_names_str')") < i
    assert "if 'openmp' in flags:" in src and 'has no OpenMP for this target: building without it' in src


def test_apple_compilers_serve_the_ios_targets_only():
    import yaml
    for tool in ('apple.xcode.clang', 'apple.xcode.clang-cpp'):
        meta = yaml.safe_load((REPO_ROOT / 'tool' / tool / '_cmeta.yaml').read_text(encoding = 'utf-8'))
        assert meta['constraints']['supports_compute'] == ['ios-cpu', 'ios-gpu', 'ios-npu']
        assert meta['constraints']['supports_os'] == ['darwin']
        desc = yaml.safe_load((REPO_ROOT / 'tool' / tool / '_desc.yaml').read_text(encoding = 'utf-8'))
        flags = desc['features']['darwin']['flags']
        assert flags['static_build'] == '' and flags['openmp'] == '' and 'openmp' in flags
    for program in ('test-nmm-c-cpu', 'lib-xopenme'):
        meta = json.loads((REPO_ROOT / 'program' / program / '_cmeta.json').read_text(encoding = 'utf-8'))
        assert 'ios-cpu' in meta['constraints']['supported_compute']
