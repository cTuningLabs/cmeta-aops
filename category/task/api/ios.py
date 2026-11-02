"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Programs that run on an iPhone or iPad (compute ios-cpu). iOS runs no plain executable: the compiled program goes
into an app bundle under the bundle id of task/target--ios-cpu, signed with the developer's identity and the
development profile that target found or made, installed and launched with devicectl with its console attached;
the files the program writes in the app's Documents folder come back with devicectl. The program's main is the
target's launcher (its src/cmeta_ios_main.c), which enters Documents, removes last run's output files named in
CMETA_IOS_CLEAN and writes the exit code into EXIT_FILE, since devicectl reports none.
"""

import getpass
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import tempfile

EXIT_FILE = 'tmp-cmeta-ios-exit.txt'
MIN_OS = '16.0'

# devicectl with the console attached forwards its stdin to the app: a run started by a script fed on stdin
# (cx host run --script) would hand the rest of that script to the program, so the launch reads nothing
LAUNCH_POSTFIX = ' < /dev/null'

# A probe (a target asking the device what it offers) prints one JSON line after this mark
PROBE_MARK = 'CMETA_PROBE:'


def info_plist(bundle_id, exe, min_os, name):
    """The Info.plist of a bundle that iOS installs and launches: an app of the device family, no launch screen file."""
    return {'CFBundleIdentifier': bundle_id,
            'CFBundleExecutable': exe,
            'CFBundleName': name,
            'CFBundleDisplayName': name,
            'CFBundlePackageType': 'APPL',
            'CFBundleInfoDictionaryVersion': '6.0',
            'CFBundleShortVersionString': '1.0',
            'CFBundleVersion': '1',
            'MinimumOSVersion': str(min_os),
            'CFBundleSupportedPlatforms': ['iPhoneOS'],
            'DTPlatformName': 'iphoneos',
            'UIDeviceFamily': [1, 2],
            'LSRequiresIPhoneOS': True,
            'UILaunchScreen': {}}


def make_bundle(app_dir, exe_path, bundle_id, profile_path, min_os, name = None):
    """
    The app bundle around the executable: Info.plist, the executable, the embedded development profile. A bundle
    of a previous run is replaced. Returns the error text, or None.
    """
    for what, path in (('executable', exe_path), ('profile', profile_path)):
        if not os.path.isfile(path):
            return f'no such {what}: {path}'
    try:
        if os.path.isdir(app_dir):
            shutil.rmtree(app_dir)
        os.makedirs(app_dir)
        exe = os.path.basename(exe_path)
        shutil.copy2(exe_path, os.path.join(app_dir, exe))
        os.chmod(os.path.join(app_dir, exe), 0o755)
        shutil.copy2(profile_path, os.path.join(app_dir, 'embedded.mobileprovision'))
        with open(os.path.join(app_dir, 'Info.plist'), 'wb') as f:
            plistlib.dump(info_plist(bundle_id, exe, min_os, name or exe), f)
        return None
    except (OSError, shutil.Error) as e:
        # Windows' message names no file
        return str(e) + (f' ({e.filename})' if getattr(e, 'filename', None) else '')


def _run(argv, timeout = 60):
    try:
        r = subprocess.run(argv, capture_output = True, text = True, timeout = timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def signing_prefix():
    """
    How codesign reaches the private key of the identity: directly in a session whose login keychain is unlocked
    (the Mac's own terminal); through the user's GUI session (launchctl asuser, with passwordless sudo) in an ssh
    session, which sees the login keychain locked (codesign: errSecInternalComponent). Returns (prefix, error).
    """
    keychain = os.path.expanduser('~/Library/Keychains/login.keychain-db')
    rc, out = _run(['security', 'show-keychain-info', keychain])
    if 'User interaction is not allowed' not in out:
        return '', None
    rc, out = _run(['sudo', '-n', 'true'])
    if rc == 0:
        return f'sudo -n launchctl asuser {os.getuid()} sudo -n -u {getpass.getuser()} ', None
    return None, ('the login keychain is locked in this session, so codesign cannot use the signing identity, and sudo '
                  'asks for a password: run "security unlock-keychain ~/Library/Keychains/login.keychain-db" in this '
                  'session first, or run from the Mac\'s own terminal')


def codesign_cmd(prefix, identity, entitlements, app_dir, q):
    return f'{prefix}codesign --force --sign {q(identity)} --entitlements {q(entitlements)} --timestamp=none {q(app_dir)}'


def install_cmd(devicectl, udid, app_dir, q):
    return f'{devicectl} device install app --device {udid} {q(app_dir)}'


def launch_prefix(devicectl, udid, bundle_id, env = None):
    """The command that runs the program (its arguments follow): launched by bundle id, the console attached until
    it ends, a running instance ended first, the run-time environment as a JSON dictionary."""
    e = f' --environment-variables {shlex.quote(json.dumps(env))}' if env else ''
    return f'{devicectl} device process launch --console --terminate-existing{e} --device {udid} {bundle_id} '


def copy_to_cmd(devicectl, udid, bundle_id, host_file, name, q):
    """An input file into the app's Documents folder (the program's working folder)."""
    return (f'{devicectl} device copy to --device {udid} --domain-type appDataContainer --domain-identifier {bundle_id} '
            f'--source {q(host_file)} --destination Documents/{name}')


def copy_from_cmd(devicectl, udid, bundle_id, name, host_file, q):
    """An output file back from the app's Documents folder."""
    return (f'{devicectl} device copy from --device {udid} --domain-type appDataContainer --domain-identifier {bundle_id} '
            f'--source Documents/{name} --destination {q(host_file)}')


def exit_check_cmd():
    """The program's exit code, written by the launcher and copied back: the run fails as the program did (a plain
    command, no shell construct: the saved run script must say the same in any shell)."""
    return f'grep -qx 0 {EXIT_FILE}'


def _cmd(task, ctx, cmds, capture = False, timeout = None):
    """Commands through the cmd task of the run (RUN: lines in verbose mode); an error names the first that failed."""
    r = task.cm.access({'category': task.category_alias + ',' + task.category_uid,
                        'command': 'run',
                        'ctx': ctx,
                        'arg1': 'cmd,c9ba0a88df394d7f',
                        'cmds': list(cmds),
                        'timeout': timeout,
                        'con': ctx['control'].get('con', False),
                        'quiet': ctx['control'].get('quiet', False),
                        'verbose': ctx['control'].get('verbose', False),
                        'text_cmd': 'RUN:',
                        'print_extra_line': False,
                        'capture_output': capture,
                        'fail_if_nonzero_return_code': False})
    if task.cm.catch_error(r): return r
    if r.get('returncode', 1) > 0:
        tail = ((r.get('stdout') or '') + '\n' + (r.get('stderr') or '')).strip()[-1500:]
        return task.cm.error(f'command failed with return code {r.get("returncode")}: {cmds[0][:200]}' + (f'\n{tail}' if tail else ''))
    return {'return': 0, 'stdout': r.get('stdout') or '', 'stderr': r.get('stderr') or ''}


def probe(task, ctx, source, frameworks, name, min_os = None, timeout = 300):
    """
    A small Objective-C program built for the device, run there and asked one JSON line (after PROBE_MARK): how
    a target task (the GPU, the Neural Engine) learns what the device offers, since iOS has no shell to ask. The
    device, the signing identity and the profile come from target--ios-cpu in the global context, the compiler
    and the SDK from tool/apple.xcode; the app replaces the one under the bundle id and is built in a temporary
    folder removed afterwards. Returns {'return': 0, 'probe': <the dict>} or an error.
    """
    _global = ctx['tasks']['global']
    cpu = _global.get('target--ios-cpu') or {}
    xcode = _global.get('apple-xcode') or {}
    signing = cpu.get('signing') or {}
    if not cpu or not signing.get('profile'):
        return task.cm.error('the probe needs target--ios-cpu (the device and its signing) in this run')

    clang = os.path.join(xcode.get('path_toolchain_bin') or '', 'clang')
    sdk = xcode.get('ios_sdk_path') or ''
    if not sdk or not os.path.isfile(clang):
        return task.cm.error('the probe needs Xcode with the iOS SDK (cx tool setup apple.xcode)')

    udid = cpu['udid']
    bundle_id = signing['bundle_id']
    devicectl = cpu.get('devicectl') or 'xcrun devicectl'
    min_os = str(min_os or cpu.get('min_os') or MIN_OS)
    q = task.cm.q

    folder = tempfile.mkdtemp(prefix = 'cmeta-ios-probe-')
    try:
        exe = os.path.join(folder, name)
        fw = ' '.join(f'-framework {f}' for f in frameworks)
        r = _cmd(task, ctx, [f'{q(clang)} -isysroot {q(sdk)} -arch arm64 -miphoneos-version-min={min_os} -fobjc-arc '
                             f'{fw} -o {q(exe)} {q(source)}'], capture = True, timeout = timeout)
        if r['return'] > 0: return r

        app_dir = os.path.join(folder, name + '.app')
        error = make_bundle(app_dir, exe, bundle_id, signing['profile'], min_os, 'cMeta probe')
        if error:
            return task.cm.error(f'the probe bundle could not be made: {error}')

        prefix, error = signing_prefix()
        if error:
            return task.cm.error(error)

        r = _cmd(task, ctx, [codesign_cmd(prefix, signing['identity'], signing['entitlements'], app_dir, q),
                             install_cmd(devicectl, udid, app_dir, q)], capture = True, timeout = timeout)
        if r['return'] > 0: return r

        r = _cmd(task, ctx, [launch_prefix(devicectl, udid, bundle_id) + LAUNCH_POSTFIX], capture = True, timeout = timeout)
        if r['return'] > 0: return r

        line = next((l for l in (r['stdout'] + '\n' + r['stderr']).splitlines() if PROBE_MARK in l), None)
        if not line:
            return task.cm.error(f'the probe "{name}" printed no {PROBE_MARK} line: ' + (r['stdout'] + r['stderr']).strip()[-800:])
        try:
            data = json.loads(line.split(PROBE_MARK, 1)[1].strip())
        except ValueError as e:
            return task.cm.error(f'the probe "{name}" printed no JSON: {e}: {line[:300]}')
        if isinstance(data, dict) and data.get('error'):
            return task.cm.error(f'the probe "{name}" failed on the device: {data["error"]}')
        return {'return': 0, 'probe': data}
    finally:
        shutil.rmtree(folder, ignore_errors = True)
