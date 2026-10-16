"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline guards for Android APK deployment and relocated Gradle builds.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(relative, base_import, base):
    path = ROOT / relative
    source = path.read_text(encoding='utf-8').replace(base_import, 'class %s: pass' % base)
    namespace = {'__file__': str(path), '__name__': 'android_test'}
    exec(compile(source, str(path), 'exec'), namespace)
    return namespace


@pytest.fixture(scope='module')
def app():
    return load('task/android-gradle-app/api_v1.py',
                'from task_c36be4b9314a45e0.api.ctask import InitCTask', 'InitCTask')


def instance(app):
    task = app['CTask'].__new__(app['CTask'])
    task.cm = SimpleNamespace(error=lambda msg: {'return': 1, 'error': msg},
                              catch_error=lambda r, **kw: r.get('return', 0) != 0)
    task.logger = None
    return task


def test_single_authorized_device_and_explicit_selection(app):
    output = 'List of devices attached\none device product:tablet\n'
    assert app['select_device'](output) == 'one'
    output += 'two device product:phone\n'
    assert app['select_device'](output, 'two') == 'two'
    with pytest.raises(ValueError, match='--serial'):
        app['select_device'](output)


@pytest.mark.parametrize('state', ['unauthorized', 'offline'])
def test_never_select_unavailable_device(app, state):
    with pytest.raises(ValueError, match='authorize USB debugging'):
        app['select_device']('tablet ' + state, 'tablet')


def test_no_device(app):
    with pytest.raises(ValueError, match='no devices'):
        app['select_device']('List of devices attached\n')


def test_shell_arguments_are_quoted_for_sdk_ids_and_paths(app):
    task = instance(app)
    calls = []
    task.access = lambda *args, **kw: calls.append(kw) or {'return': 0}
    posix = {'tasks': {'global': {'host': {'os': {'uname': 'linux'}}}}}
    task.command(posix, ['/some path/sdkmanager', 'platforms;android-35'])
    assert "'platforms;android-35'" in calls[-1]['cmd']
    assert "'/some path/sdkmanager'" in calls[-1]['cmd']
    windows = {'tasks': {'global': {'host': {'os': {'uname': 'windows'}}}}}
    task.command(windows, ['D:/!repos/java.exe', 'platforms;android-35'])
    assert calls[-1]['cmd'] == '"D:/!repos/java.exe" "platforms;android-35"'


@pytest.mark.parametrize('suffix', ['../other', '/outside', 'a/../../b', 'C:/absolute', 'a\\..\\b'])
def test_cref_subpaths_cannot_escape_artifact(app, suffix):
    with pytest.raises(ValueError):
        app['safe_suffix'](suffix)


def test_tampered_apk_cannot_reach_adb(app, tmp_path):
    apk = tmp_path / 'app.apk'
    apk.write_bytes(b'changed')
    (tmp_path / 'build.json').write_text(json.dumps({'apk': str(apk), 'sha256': 'wrong'}))
    task = instance(app)
    task.project = lambda *args: (tmp_path, 'project')
    task.workspace = lambda *args: tmp_path
    task.command = lambda *args, **kwargs: pytest.fail('ADB must not be called for a changed APK')
    r = task.run({'control': {}, 'tasks': {'global': {}}}, action='deploy', project_dir=str(tmp_path))
    assert r['return'] != 0 and 'changed' in r['error']


def test_failed_build_invalidates_previous_receipt_and_uses_separate_outputs(app, tmp_path):
    source, workspace, sdk = (tmp_path / n for n in ('source', 'cache', 'sdk'))
    for p in (source / 'gradle/wrapper', workspace, sdk):
        p.mkdir(parents=True)
    (source / 'gradlew.bat').write_text('wrapper')
    (source / 'gradle/wrapper/gradle-wrapper.jar').write_bytes(b'jar')
    (source / 'local.properties').write_text('other.setting=kept\nsdk.dir=C:/old/location\n')
    receipt = workspace / 'build.json'
    receipt.write_text('{"apk":"old"}')
    task = instance(app)
    commands = []
    def fail(args_ctx, args, *misc, **kw):
        commands.append(args)
        return {'return': 0, 'returncode': 1}
    task.command = fail
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': 'windows'}},
           'openjdk': {'path_bin': str(tmp_path / 'jdk/bin')},
           'google-android-sdk-command-line-tools': {'path_home': str(sdk), 'path': str(sdk / 'sdkmanager.bat')}}}}
    r = task.build(ctx, source, workspace, 'app', 'debug', '', '', 1200)
    assert r['return'] != 0 and not receipt.exists()
    assert '--init-script' in commands[0] and '--project-cache-dir' in commands[0]
    assert 'other.setting=kept' in (source / 'local.properties').read_text()
    assert 'C:/old/location' not in (source / 'local.properties').read_text()
    assert 'p.layout.buildDirectory.set' in (workspace / 'cmeta-build.gradle').read_text()


def test_sdk_package_ids_keep_their_semicolons_and_bypass_windows_launcher(app, tmp_path):
    source, workspace, sdk = (tmp_path / n for n in ('source', 'cache', 'sdk'))
    for p in (source / 'gradle/wrapper', workspace, sdk / 'cmdline-tools/latest/lib'):
        p.mkdir(parents=True)
    (source / 'gradlew.bat').write_text('wrapper')
    (source / 'gradle/wrapper/gradle-wrapper.jar').write_bytes(b'jar')
    (sdk / 'cmdline-tools/latest/lib/sdkmanager-classpath.jar').write_bytes(b'jar')
    task = instance(app)
    commands = []
    def fail(args_ctx, args, *misc, **kw):
        commands.append(args)
        return {'return': 0, 'returncode': 1}
    task.command = fail
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': 'windows'}},
           'openjdk': {'path_bin': str(tmp_path / 'jdk/bin')},
           'google-android-sdk-command-line-tools': {'path_home': str(sdk),
               'path': str(sdk / 'cmdline-tools/latest/bin/sdkmanager.bat')}}}}
    r = task.build(ctx, source, workspace, 'app', 'debug', '', 'platforms;android-35,build-tools;35.0.0', 1200)
    assert r['return'] != 0
    assert commands[0][-2:] == ['platforms;android-35', 'build-tools;35.0.0']
    assert commands[0][0].endswith('java.exe')
    assert 'com.android.sdklib.tool.sdkmanager.SdkManagerCli' in commands[0]


def test_sdk_package_revision_and_legacy_fallback(tmp_path):
    sdk = load('tool/google.android-sdk.command-line-tools/api_v1.py',
               'from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'InitCTool')
    tool = sdk['CTool'].__new__(sdk['CTool'])
    binary = tmp_path / 'cmdline-tools/latest/bin/sdkmanager.bat'
    binary.parent.mkdir(parents=True)
    properties = binary.parent.parent / 'source.properties'
    properties.write_text('Pkg.Revision=20.0\n')
    assert tool.detect_versions({}, [str(binary)])['found_paths_with_versions'][str(binary)]['output'] == '20.0'
    properties.unlink()
    assert 'found_paths_with_versions' not in tool.detect_versions({}, [str(binary)])
    desc = yaml.safe_load((ROOT / 'tool/google.android-sdk.command-line-tools/_desc.yaml').read_text())
    import re
    pattern = desc['match_version'][0]['regex']
    assert re.search(pattern, '20.0\n')
    assert not re.search(pattern, 'Java version 17 or higher is required.\n')


def test_android_source_inputs_include_resources_and_gradle_but_skip_copied_outputs(app, tmp_path):
    for relative in ('app/src/main/AndroidManifest.xml', 'app/src/main/res/values/strings.xml',
                     'app/src/main/res/drawable/icon.png', 'app/build.gradle.kts',
                     'gradle/wrapper/gradle-wrapper.properties', 'keystore.properties',
                     'app/build/old.apk', '.gradle/copied-state', '.idea/workspace.xml'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'input')
    files = app['source_inputs'](tmp_path)
    assert 'app/src/main/res/values/strings.xml' in files
    assert 'app/src/main/res/drawable/icon.png' in files
    assert 'app/build.gradle.kts' in files
    assert 'gradle/wrapper/gradle-wrapper.properties' in files
    assert 'app/build/old.apk' not in files
    assert '.gradle/copied-state' not in files
    assert '.idea/workspace.xml' not in files


def test_prepare_does_not_create_workspace_or_contact_device(app, tmp_path):
    task = instance(app)
    (tmp_path / 'AndroidManifest.xml').write_text('<manifest/>')
    task.workspace = lambda *args: pytest.fail('prepare must not create a build cache')
    task.command = lambda *args, **kw: pytest.fail('prepare must not contact a device')
    r = task.run({'control': {}, 'tasks': {'global': {}}}, action='prepare', project_dir=str(tmp_path))
    assert r['return'] == 0 and r['source_files'] == ['AndroidManifest.xml']


def test_program_hooks_publish_resolved_sources_and_apk_without_absolute_recipe_paths(tmp_path):
    ns = load('category/program/api/common_android_gradle.py',
              'from .cprogram import InitCProgram', 'InitCProgram')
    hook = ns['InitAndroidGradleProgram'].__new__(ns['InitAndroidGradleProgram'])
    calls = []
    def access(params):
        calls.append(params)
        return {'return': 0, 'project_dir': str(tmp_path), 'source_files': ['AndroidManifest.xml']}
    hook.cm = SimpleNamespace(access=access, catch_error=lambda r, **kw: r['return'] != 0)
    local = {'android_project_cref': 'project::example/src',
             'selected-program': {'artifact': {'cmeta': {'uses_categories': {'task': 'task,cat-uid'},
                 'uses_artifacts': {'task::android-gradle-app': 'android-gradle-app,task-uid'}}}}}
    ctx = {'tasks': {'local': local}}
    desc = {'local_vars': {'src_file_names': []}}
    assert hook.customize_android_project(ctx, desc, {})['return'] == 0
    assert calls[0]['category'] == 'task,cat-uid' and calls[0]['action'] == 'prepare'
    assert local['src_dir'] == str(tmp_path)
    assert desc['local_vars']['src_file_names'] == ['AndroidManifest.xml']
    local['android-gradle-build'] = {'apk': str(tmp_path / 'app.apk'), 'sha256': 'digest'}
    assert hook.finish_android_compile(ctx)['return'] == 0
    assert local['target_path_exe'] == str(tmp_path / 'app.apk')


def test_android_app_target_needs_no_device_or_sdk(cm):
    ctx = {}
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'target',
                   'compute': 'android-app', 'ctx': ctx, 'con': False, 'quiet': True})
    assert r['return'] == 0, r.get('error')
    assert r['compute'] == ['android-app']
    global_ctx = ctx['tasks']['global']
    assert 'target--android-app' in global_ctx
    assert 'adb' not in global_ctx and 'openjdk' not in global_ctx
    assert 'google-android-sdk-command-line-tools' not in global_ctx


def test_program_template_inheritance_and_launch_variant(cm):
    r = cm.access({'category': 'program', 'command': 'create', 'arg1': 'test-android-app-template',
                   'meta': {'constraints': {'supported_compute': ['android-app']},
                            'uses_categories': {'task': 'task,c36be4b9314a45e0'},
                            'uses_artifacts': {'task::android-gradle-app': 'android-gradle-app,175185dd757f45e1'}},
                   'con': False})
    assert r['return'] == 0, r.get('error')
    root = Path(r['path'])
    (root / '_desc.yaml').write_text('inherits: ["template-android-gradle-app,7c64f1611d5c4353"]\n')
    (root / 'api_v1.py').write_text(
        'from program_22788f3c30d04e6d.api.common_android_gradle import InitAndroidGradleProgram\n'
        'class CProgram(InitAndroidGradleProgram):\n'
        '    def __init__(self, *args, **kwargs):\n'
        '        super().__init__(*args, module_file_path=__file__, **kwargs)\n')
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'select-program',
                   'name': 'test-android-app-template', 'compute': 'android-app', 'cmd': 'launch',
                   'con': False, 'quiet': True})
    assert r['return'] == 0, r.get('error')
    desc = r['add_to_local']['selected-program']['loaded_files']['_desc']['data']
    assert desc['params']['compute'] == 'android-app'
    assert desc['compile']['skip'] is True
    assert desc['run']['uses'][0]['action'] == 'run'
