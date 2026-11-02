"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The status of a Docker or Podman container host (2026-11-02): a running container is up, a container that exists and
is not running is "stopped" (not "down", which read as the engine being off), a container that does not exist is
"missing", and an engine that does not answer says so. Nothing here runs an engine.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def host_module():
    spec = importlib.util.spec_from_file_location('docker_status_test', ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = 'module')
def host():
    m = host_module()
    cls = next(v for v in vars(m).values() if isinstance(v, type) and hasattr(v, '_status') and hasattr(v, '_engine'))
    h = cls.__new__(cls)
    h._retired = lambda host: False
    h._engine = lambda host: 'docker'
    return h


def container(**state):
    return {'alias': 'c', 'type': 'docker', 'via': None, 'via_list': [], 'desc': {'access': {'container': 'c'}}, 'state': state}


def answer(host, returncode, stdout = '', stderr = ''):
    host._run_quick = staticmethod(lambda cmd, timeout: {'returncode': returncode, 'stdout': stdout, 'stderr': stderr})


def test_running_stopped_and_other_states(host):
    answer(host, 0, 'running\n')
    assert host._status({}, container()) == 'up'
    answer(host, 0, 'exited\n')
    assert host._status({}, container()) == 'stopped'
    answer(host, 0, 'created\n')
    assert host._status({}, container()) == 'stopped'
    answer(host, 0, 'paused\n')
    assert host._status({}, container()) == 'down (paused)'


def test_missing_container_and_engine_down(host):
    answer(host, 1, '', 'Error response from daemon: No such container: c')
    assert host._status({}, container()) == 'missing'
    answer(host, 1, '', 'error during connect: Get "http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.51/containers/c/json": '
                        'open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.')
    assert host._status({}, container()) == 'docker engine down'
    answer(host, 1, '', 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?')
    assert host._status({}, container()) == 'docker engine down'


def test_a_stopped_container_is_not_reachable_for_commands(host):
    """Only a stopped WSL distro counts as reachable (wsl.exe starts it for the next command); a stopped container
    needs cx host up first."""
    h = container()
    h['status'] = 'stopped'
    assert host._usable(h) is False
    h['type'] = 'wsl'
    assert host._usable(h) is True
