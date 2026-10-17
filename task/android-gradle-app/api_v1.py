"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from cmeta.utils.files import PathLock
from task_c36be4b9314a45e0.api.ctask import InitCTask


def safe_suffix(value):
    parts = str(value).replace('\\', '/').split('/')
    if any(p in ('.', '..') or ':' in p for p in parts) or str(value).startswith(('/', '\\')):
        raise ValueError('artifact subpaths must be relative, without . or ..')
    return [p for p in parts if p]


def select_device(output, serial=''):
    devices = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] in ('device', 'unauthorized', 'offline', 'recovery', 'sideload'):
            devices[fields[0]] = fields[1]
    if serial:
        if devices.get(serial) != 'device':
            raise ValueError('ADB device %s is %s; unlock it and authorize USB debugging' %
                             (serial, devices.get(serial, 'not connected')))
        return serial
    if len(devices) != 1:
        raise ValueError('select one connected device with --serial=<serial>; ADB reports: ' +
                         (', '.join('%s (%s)' % x for x in devices.items()) or 'no devices'))
    return select_device(output, next(iter(devices)))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_inputs(root):
    """All inputs, including Android XML/resources and Gradle files, without copied outputs.

    The program driver hashes declared files. Signing files are only hashed, never read
    into its JSON records; their paths/digests let a changed signing setup invalidate a build.
    """
    files = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(('.', 'tmp')) and
                         d not in ('build', '__pycache__', 'node_modules') and
                         not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if not name.startswith('.') and not path.is_symlink():
                files.append(path.relative_to(root).as_posix())
    return files


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def access(self, ctx, category, command, **params):
        return self.cm.access(dict(category=self.cmeta['uses_categories'][category],
                                   command=command, ctx=ctx, **params))

    def project(self, ctx, project_cref, project_dir):
        # An explicit directory overrides the recipe's cRef, useful for source snapshots in CI.
        if project_dir:
            path = Path(project_dir).expanduser().resolve()
            return path, str(path)
        reference, _, suffix = project_cref.replace('\\', '/').partition('/')
        category, sep, name = reference.partition('::')
        if not sep or not name:
            raise ValueError('give --project_cref=category::artifact[/subpath] or --project_dir=<directory>')
        r = self.cm.access(dict(category=category, command='find', arg1=name, con=False))
        if self.cm.catch_error(r, fail16=True):
            raise ValueError(r.get('error', 'project artifact was not found'))
        artifacts = r.get('artifacts', [])
        if len(artifacts) != 1:
            raise ValueError('project_cref must resolve to exactly one artifact')
        artifact = artifacts[0]
        base = Path(artifact['path']).resolve()
        path = base.joinpath(*safe_suffix(suffix)).resolve()
        path.relative_to(base)
        parts = artifact['cmeta_ref_parts']
        identity = '%s::%s/%s' % (parts['category_uid'], parts['artifact_uid'], suffix)
        return path, identity

    def workspace(self, ctx, identity, module, variant, create):
        params = dict(project=identity, module=module, variant=variant)
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        name = 'android-gradle-app--' + digest
        r = self.access(ctx, 'cache', 'find', arg1=name, con=False)
        if r.get('return', 1) == 16 or (r.get('return') == 0 and not r.get('artifacts')):
            if not create:
                raise ValueError('no successful build in cMeta cache; run the build action first')
            r = self.access(ctx, 'cache', 'create', arg1=name, tags=['android-gradle-app', 'apk'],
                            meta={'params': params}, con=False)
            if self.cm.catch_error(r, fail16=True):
                raise ValueError(r.get('error', 'could not create build workspace'))
            return Path(r['path'])
        if self.cm.catch_error(r, fail16=True):
            raise ValueError(r.get('error', 'could not find build workspace'))
        artifacts = r.get('artifacts', [])
        if len(artifacts) != 1 or artifacts[0].get('cmeta', {}).get('params') != params:
            raise ValueError('ambiguous or mismatched Android build cache entry: ' + name)
        return Path(artifacts[0]['path'])

    def command(self, ctx, args, cwd=None, env=None, capture=False, timeout=None):
        # cmd is a shell runner. Quote arguments, including SDK package semicolons on POSIX.
        if ctx['tasks']['global']['host']['os']['uname'] == 'windows':
            if any('"' in str(x) or '\n' in str(x) or '\r' in str(x) for x in args):
                raise ValueError('command arguments cannot contain quotes or newlines on Windows')
            cmd = ' '.join('"%s"' % x for x in args)
        else:
            cmd = ' '.join(shlex.quote(str(x)) for x in args)
        return self.access(ctx, 'task', 'run', arg1='cmd,c9ba0a88df394d7f',
                           cmd=cmd, chdir=str(cwd) if cwd else None,
                           env=env or {}, capture_output=capture, timeout=timeout,
                           fail_if_nonzero_return_code=False)

    def run(self, ctx: dict, action: str = 'build', project_cref: str = '', project_dir: str = '',
            module: str = 'app', variant: str = 'debug', package: str = '', activity: str = '',
            serial: str = '', apk: str = '', sdk_root: str = '', sdk_packages: str = '',
            launch: bool = False, timeout: int = 1200, workspace_dir: str = ''):
        """Build with the project's Gradle wrapper, deploy an APK with adb install -r -t,
        or run an installed activity. Build outputs and a successful-build receipt live in
        a deletable cMeta cache entry per source project, module and variant. Deploy never
        uninstalls or clears application data; run does not build or install.

        project_cref: category::artifact[/subpath], resolved in the caller's cMeta home.
        project_dir: optional explicit source directory, overrides project_cref.
        sdk_packages: optional comma-separated sdkmanager package names (licenses must
            already be accepted; use sdkmanager --licenses interactively if needed).
        serial: explicit ADB target, else ANDROID_SERIAL, else the single connected device.
        apk: optional explicit APK for deploy, otherwise the last successful cached build.
        launch: also launch after deploy; run always launches.
        workspace_dir: optional explicit build workspace, used by the program template to
            put APK outputs in the normal program cache. Standalone tasks keep their cache.
        prepare: resolve the source and list build inputs, without setting up SDK/JDK/ADB.
        """
        try:
            if action not in ('prepare', 'build', 'deploy', 'run') or variant not in ('debug', 'release'):
                raise ValueError('action must be prepare/build/deploy/run and variant debug/release')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', module):
                raise ValueError('module must be a simple Gradle application module name')
            if action == 'run' or (action == 'deploy' and launch):
                if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', package):
                    raise ValueError('give the Android application ID with --package=<id>')
                if not re.fullmatch(r'\.?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', activity):
                    raise ValueError('give --activity=<activity class>, for example .MainActivity')
            if action in ('prepare', 'build') or (action == 'deploy' and not apk):
                source, identity = self.project(ctx, project_cref, project_dir)
                if not source.is_dir():
                    raise ValueError('source directory does not exist: ' + str(source))
                if action == 'prepare':
                    return {'return': 0, 'project_dir': str(source), 'source_files': source_inputs(source)}
                if workspace_dir:
                    workspace = Path(workspace_dir).expanduser().resolve()
                    if workspace == Path(workspace.anchor) or workspace == source:
                        raise ValueError('workspace_dir must be a separate build directory below a filesystem root')
                    if action == 'build': workspace.mkdir(parents=True, exist_ok=True)
                else:
                    workspace = self.workspace(ctx, identity, module, variant, action == 'build')
            else:
                source = workspace = None

            if action == 'build':
                lock = PathLock(str(workspace / 'build.lock'), logger=self.logger)
                lock.acquire(timeout=30)
                try:
                    return self.build(ctx, source, workspace, module, variant, sdk_root, sdk_packages, timeout)
                finally:
                    lock.release()

            if action == 'deploy':
                if apk:
                    apk_path = Path(apk).expanduser().resolve()
                else:
                    receipt_path = workspace / 'build.json'
                    if not receipt_path.is_file():
                        raise ValueError('no successful APK build; run the build action first')
                    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                    apk_path = Path(receipt['apk'])
                    apk_path.resolve().relative_to(workspace.resolve())
                    if not apk_path.is_file() or sha256(apk_path) != receipt['sha256']:
                        raise ValueError('cached APK is missing or changed; rebuild it before deploying')
                if not apk_path.is_file() or apk_path.suffix.lower() != '.apk':
                    raise ValueError('APK does not exist: ' + str(apk_path))

            adb = ctx['tasks']['global']['adb']['path']
            r = self.command(ctx, [adb, 'devices', '-l'], capture=True, timeout=30)
            if self.cm.catch_error(r, fail16=True): return r
            if r.get('returncode'):
                return self.cm.error('adb devices failed: ' + (r.get('stderr') or 'unknown error'))
            chosen = select_device(r.get('stdout', ''), serial or os.environ.get('ANDROID_SERIAL', ''))
            prefix = [adb, '-s', chosen]
            if action == 'deploy':
                r = self.command(ctx, prefix + ['install', '-r', '-t', str(apk_path)], capture=True, timeout=timeout)
                if self.cm.catch_error(r, fail16=True): return r
                output = (r.get('stdout') or '') + (r.get('stderr') or '')
                if ctx['control'].get('con'): print(output.strip())
                if r.get('returncode') or 'Success' not in output:
                    return self.cm.error('APK install failed (existing app and data were kept): ' + output.strip())
            if action == 'run' or launch:
                component = package + '/' + activity
                r = self.command(ctx, prefix + ['shell', 'am', 'start', '-W', '-n', component], capture=True, timeout=60)
                if self.cm.catch_error(r, fail16=True): return r
                output = (r.get('stdout') or '') + (r.get('stderr') or '')
                if ctx['control'].get('con'): print(output.strip())
                if r.get('returncode') or re.search(r'(^|\n)\s*(Error|Exception)', output):
                    return self.cm.error('activity launch failed: ' + output.strip())
            return {'return': 0, 'action': action, 'serial': chosen,
                    'apk': str(apk_path) if action == 'deploy' else None}
        except (OSError, ValueError, KeyError, TimeoutError) as exc:
            return self.cm.error(str(exc))

    def build(self, ctx, source, workspace, module, variant, sdk_root, sdk_packages, timeout):
        windows = ctx['tasks']['global']['host']['os']['uname'] == 'windows'
        wrapper = source / ('gradlew.bat' if windows else 'gradlew')
        if not wrapper.is_file() or not (source / 'gradle/wrapper/gradle-wrapper.jar').is_file():
            raise ValueError('source must contain the Gradle wrapper script and jar')
        sdk = ctx['tasks']['global']['google-android-sdk-command-line-tools']
        root = Path(sdk_root or sdk['path_home']).expanduser().resolve()
        if not root.is_dir():
            raise ValueError('Android SDK root does not exist: ' + str(root))
        jdk = ctx['tasks']['global']['openjdk']
        java_home = str(Path(jdk['path_bin']).parent)
        env = {'JAVA_HOME': java_home, 'ANDROID_HOME': str(root), 'ANDROID_SDK_ROOT': str(root)}
        # local.properties is Android Studio's generated machine-local SDK pointer. Keep other entries.
        properties = source / 'local.properties'
        old = properties.read_text(encoding='utf-8') if properties.exists() else ''
        lines = [line for line in old.splitlines() if not re.match(r'^\s*sdk\.dir\s*[=:]', line)]
        lines.append('sdk.dir=' + str(root).replace('\\', '/').replace(':', '\\:'))
        text = '\n'.join(lines) + '\n'
        if text != old:
            properties.write_bytes(text.encode('utf-8'))
        if sdk_packages:
            packages = [x.strip() for x in sdk_packages.split(',') if x.strip()]
            sdk_home = Path(sdk['path']).parent.parent
            classpath = sdk_home / 'lib/sdkmanager-classpath.jar'
            # Google's newer .bat enables delayed expansion, corrupting JDK paths containing !.
            # Use its Java entry point when available; retain the launcher for other layouts.
            java = Path(java_home) / 'bin' / ('java.exe' if windows else 'java')
            manager = [str(java), '-Dcom.android.sdklib.toolsdir=' + str(sdk_home),
                       '-classpath', str(classpath), 'com.android.sdklib.tool.sdkmanager.SdkManagerCli'] \
                      if windows and classpath.is_file() else [sdk['path']]
            r = self.command(ctx, manager + ['--sdk_root=' + str(root)] + packages,
                             source, env, timeout=timeout)
            if self.cm.catch_error(r, fail16=True): return r
            if r.get('returncode'):
                return self.cm.error('sdkmanager failed; accept SDK licenses with sdkmanager --licenses and retry')
        # Move every Gradle module's generated files out of the source tree, including copied old outputs.
        outputs = workspace / 'outputs'
        escaped = json.dumps(str(outputs).replace('\\', '/'))
        init = workspace / 'cmeta-build.gradle'
        init.write_bytes(('gradle.beforeProject { p ->\n'
                         '    def relative = p.path == ":" ? "_root" : p.path.substring(1).replace(":", "/")\n'
                         '    p.layout.buildDirectory.set(new File(%s, relative))\n'
                         '}\n' % escaped).encode('utf-8'))
        receipt = workspace / 'build.json'
        # A failed newer build must never leave a deployable receipt for an older APK.
        if receipt.exists(): receipt.unlink()
        args = [str(wrapper)] if windows else ['sh', str(wrapper)]
        args += ['--no-daemon', '--console=plain', '--stacktrace',
                 '--project-cache-dir', str(workspace / 'gradle-cache'), '--init-script', str(init),
                 ':' + module + ':assemble' + variant.title()]
        r = self.command(ctx, args, source, env, timeout=timeout)
        if self.cm.catch_error(r, fail16=True): return r
        if r.get('returncode'):
            return self.cm.error('Gradle APK build failed; see the Gradle output above')
        output_dir = outputs / module / 'outputs/apk' / variant
        metadata_path = output_dir / 'output-metadata.json'
        if not metadata_path.is_file():
            raise ValueError('Gradle did not produce APK metadata: ' + str(metadata_path))
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        elements = metadata.get('elements', [])
        if len(elements) != 1:
            raise ValueError('this prototype requires one APK; split APK installation is not supported')
        apk = (output_dir / elements[0]['outputFile']).resolve()
        apk.relative_to(workspace.resolve())
        if not apk.is_file():
            raise ValueError('built APK is missing: ' + str(apk))
        info = {'apk': str(apk), 'sha256': sha256(apk), 'project_dir': str(source),
                'module': module, 'variant': variant, 'package': metadata.get('applicationId'),
                'version_name': elements[0].get('versionName'), 'version_code': elements[0].get('versionCode'),
                'java_home': java_home, 'jdk_version': jdk.get('version'), 'sdk_root': str(root)}
        receipt.write_bytes((json.dumps(info, indent=2) + '\n').encode('utf-8'))
        if ctx['control'].get('con'):
            print('APK: ' + str(apk))
            print('Version: %s (%s)' % (info['version_name'], info['version_code']))
        return dict(info, **{'return': 0, 'workspace': str(workspace)})
