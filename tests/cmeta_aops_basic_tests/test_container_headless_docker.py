"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of headless_docker_config (the container category): when Docker Desktop's credential store cannot
be opened in this session (ssh with a key, a service), the docker commands get a copy of the config without the
store and the classic builder, on macOS and on Windows alike; a store that answers, Linux and a DOCKER_CONFIG of
the user's own are left alone. And qualified_image: the registry podman needs in a short image name.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def module():
    path = REPO_ROOT / 'category' / 'container' / 'api' / 'v1.py'
    spec = importlib.util.spec_from_file_location('container_api_v1_headless_under_test', str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def home(tmp_path, monkeypatch):
    docker = tmp_path / '.docker'
    (docker / 'contexts').mkdir(parents=True)
    (docker / 'config.json').write_text(json.dumps({'credsStore': 'desktop', 'currentContext': 'desktop-linux'}))

    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))

    # set first, so that the undo removes what the function sets in os.environ itself
    for name in ('DOCKER_CONFIG', 'DOCKER_BUILDKIT'):
        monkeypatch.setenv(name, '')
        monkeypatch.delenv(name)

    # the temporary config folder stays in the test's own folder
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    return tmp_path


def helper(monkeypatch, module, returncode):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, b'', b'')

    monkeypatch.setattr(module.subprocess, 'run', run)
    return calls


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
def test_unreachable_store_gives_a_config_without_it_and_the_classic_builder(module, home, monkeypatch, platform):
    monkeypatch.setattr(module.sys, 'platform', platform)
    calls = helper(monkeypatch, module, 1)
    monkeypatch.setattr(module.atexit, 'register', lambda *a, **k: None)

    folder = module.headless_docker_config()

    assert folder and os.environ['DOCKER_CONFIG'] == folder
    assert os.environ['DOCKER_BUILDKIT'] == '0'
    cfg = json.loads(pathlib.Path(folder, 'config.json').read_text())
    assert 'credsStore' not in cfg and cfg['currentContext'] == 'desktop-linux'
    assert os.path.isdir(os.path.join(folder, 'contexts'))
    assert calls and calls[0][0] == ('security' if platform == 'darwin' else 'docker-credential-desktop')


def test_a_store_that_answers_is_left_alone(module, home, monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    helper(monkeypatch, module, 0)

    assert module.headless_docker_config() == ''
    assert 'DOCKER_CONFIG' not in os.environ and 'DOCKER_BUILDKIT' not in os.environ


def test_linux_and_a_config_of_ones_own_are_left_alone(module, home, monkeypatch):
    calls = helper(monkeypatch, module, 1)

    monkeypatch.setattr(module.sys, 'platform', 'linux')
    assert module.headless_docker_config() == ''

    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setenv('DOCKER_CONFIG', str(home / 'mine'))
    assert module.headless_docker_config() == ''
    assert not calls and 'DOCKER_BUILDKIT' not in os.environ


@pytest.mark.parametrize('short, full', [
    ('ubuntu:26.04', 'docker.io/library/ubuntu:26.04'),
    ('nvidia/cuda:13.3.1-base-ubuntu26.04', 'docker.io/nvidia/cuda:13.3.1-base-ubuntu26.04'),
    ('public.ecr.aws/amazonlinux/amazonlinux:2023', 'public.ecr.aws/amazonlinux/amazonlinux:2023'),
    ('localhost/cmeta/ubuntu:26.04', 'localhost/cmeta/ubuntu:26.04'),
    ('registry:5000/x/y:1', 'registry:5000/x/y:1'),
    ('docker.io/library/debian:13', 'docker.io/library/debian:13'),
])
def test_podman_gets_the_registry_of_a_short_image_name(module, short, full):
    assert module.qualified_image(short) == full