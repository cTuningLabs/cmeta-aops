"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/paperclip and task/run-paperclip, the parts that need no network and no Node.js: the launchers (cMeta's Node,
telemetry off unless the caller says otherwise), the reading of "node --version", the server's environment (its
data root and instance, a login when it is reachable from elsewhere, no telemetry, no browser), the command of a
start (onboard the first time, run afterwards) and the reading of /api/health.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel, base, stub):
    path = REPO_ROOT / rel
    src = path.read_text(encoding='utf-8').replace(base, stub)
    ns = {'__name__': 'paperclip_under_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope='module')
def tool():
    return load('tool/paperclip/api_v1.py', 'from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'class InitCTool: pass')


@pytest.fixture(scope='module')
def task():
    return load('task/run-paperclip/api_v1.py', 'from task_c36be4b9314a45e0.api.ctask import InitCTask', 'class InitCTask: pass')


def test_the_launchers_run_the_cli_with_cmetas_node_and_no_telemetry(tool):
    text = tool['launcher_posix']("/c/node it's/bin/node", '/c/p/node_modules/paperclipai/dist/index.js')
    assert text.startswith('#!/bin/sh\n')
    assert ': "${PAPERCLIP_TELEMETRY_DISABLED:=1}"' in text and 'export PAPERCLIP_TELEMETRY_DISABLED' in text
    assert "PATH='/c/node it'\"'\"'s/bin':\"$PATH\"; export PATH" in text
    assert text.rstrip().endswith("exec '/c/node it'\"'\"'s/bin/node' '/c/p/node_modules/paperclipai/dist/index.js' \"$@\"")

    cmd = tool['launcher_cmd']('D:\\!R\\node\\node.exe', 'D:\\!R\\c\\index.js')
    assert 'if not defined PAPERCLIP_TELEMETRY_DISABLED set "PAPERCLIP_TELEMETRY_DISABLED=1"' in cmd
    assert '"D:\\!R\\node\\node.exe" "D:\\!R\\c\\index.js" %*' in cmd and '\r\n' in cmd


def test_the_node_version_is_read_and_compared(tool):
    assert tool['node_version']('v24.21.0\n') == (24, 21, 0)
    assert tool['node_version']('v22.19.0') < tool['MIN_NODE'] <= tool['node_version']('v24.11.0')
    assert tool['node_version']('not a node') is None
    assert tool['node_version'](tool['NODE_FALLBACK']) >= tool['MIN_NODE'], 'the fallback must be new enough'


def test_the_server_environment_follows_the_bind(task):
    env = task['server_env']({'PATH': '/bin'}, '/h/state/paperclip', 'default', 3100, 'loopback')
    assert env['PAPERCLIP_HOME'] == '/h/state/paperclip' and env['PAPERCLIP_INSTANCE_ID'] == 'default' and env['PORT'] == '3100'
    assert env['PAPERCLIP_BIND'] == 'loopback' and 'PAPERCLIP_DEPLOYMENT_MODE' not in env
    assert env['PAPERCLIP_TELEMETRY_DISABLED'] == '1' and env['DO_NOT_TRACK'] == '1' and env['PAPERCLIP_NO_BROWSER'] == '1'
    assert env['PATH'] == '/bin'

    # reachable from elsewhere: a login
    env = task['server_env']({}, '/h', 'dev', 3200, 'tailnet')
    assert env['PAPERCLIP_BIND'] == 'tailnet' and env['PAPERCLIP_DEPLOYMENT_MODE'] == 'authenticated' and env['PORT'] == '3200'


def test_a_start_onboards_the_first_time_and_runs_afterwards(task, tmp_path):
    home = tmp_path / 'paperclip'
    assert task['start_args']('/c/paperclipai', str(home), 'default', 'loopback') == ['/c/paperclipai', 'onboard', '--yes']
    assert task['start_args']('/c/paperclipai', str(home), 'dev', 'lan') == ['/c/paperclipai', 'onboard', '--yes', '--bind', 'lan']

    config = home / 'instances' / 'default' / 'config.json'
    config.parent.mkdir(parents=True)
    config.write_text('{}', encoding='utf-8')
    assert task['start_args']('/c/paperclipai', str(home), 'default', 'lan') == ['/c/paperclipai', 'run']
    assert task['start_args']('/c/paperclipai', str(home), 'dev', 'loopback')[1] == 'onboard'      # another instance


def test_the_health_answer(task):
    assert task['health_ok']('{"status": "ok"}') and task['health_ok']('{"status":"healthy","db":"up"}')
    assert not task['health_ok']('{"status": "degraded"}')
    assert task['health_ok']('OK') and not task['health_ok']('')
    assert task['health_ok']('{"version": "2026.1012.0"}'), 'a JSON answer without a status is a server that answers'


def test_the_default_data_root_is_apart_from_paperclips_own(task, monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    assert task['default_home']() == str(tmp_path / 'state' / 'paperclip')
    monkeypatch.delenv('XDG_STATE_HOME')
    assert task['default_home']().replace('\\', '/').endswith('/.local/state/paperclip')
