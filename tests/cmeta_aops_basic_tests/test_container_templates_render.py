"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Every base template of the container category renders offline (no engine is called): its FROM image, the install
line of its package manager (fedora: dnf, opensuse: zypper - both added 2026-10-17), the user with sudo; a version
and another FROM given as template keys reach the Containerfile; podman gets a full image name. The images
themselves are built in the matrix rounds on the fleet.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

BASES = [
    ('ubuntu', 'ubuntu:26.04', 'apt-get install -y'),
    ('debian', 'debian:12', 'apt-get install -y'),
    ('fedora', 'fedora:44', 'dnf -y install'),
    ('rockylinux', 'rockylinux/rockylinux:9', 'dnf -y install'),
    ('amazonlinux', 'public.ecr.aws/amazonlinux/amazonlinux:2023', 'dnf -y install'),
    ('azurelinux', 'mcr.microsoft.com/azurelinux/base/core:3.0', 'tdnf -y install'),
    ('opensuse', 'opensuse/leap:16.0', 'zypper --non-interactive install'),
]


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))

    c = CMeta(home=str(tmp_path / 'home'))
    r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(REPO_ROOT), 'con': False})
    assert r['return'] == 0, r
    return c


def render(cm, out, template, engine='docker', **keys):
    r = cm.access({'category': 'container', 'command': 'render', 'arg1': template, 'engine': engine, 'out': str(out),
                   'template': keys, 'con': False})
    assert r['return'] == 0, r
    return (out / template / 'Containerfile').read_text(encoding='utf-8')


@pytest.mark.parametrize('template, image, install', BASES)
def test_a_base_template_renders(cm, tmp_path, template, image, install):
    text = render(cm, tmp_path / 'out', template)

    assert f'FROM {image}\n' in text
    assert f'RUN {install}' in text or f'&& {install}' in text
    assert 'useradd' in text and 'NOPASSWD:ALL' in text and 'USER cmeta' in text


def test_template_keys_reach_the_containerfile(cm, tmp_path):
    text = render(cm, tmp_path / 'leap', 'opensuse', os_version='15.6')
    assert 'FROM opensuse/leap:15.6\n' in text

    text = render(cm, tmp_path / 'tw', 'opensuse', os_version='tumbleweed', **{'from': 'opensuse/tumbleweed'})
    assert 'FROM opensuse/tumbleweed\n' in text

    text = render(cm, tmp_path / 'f42', 'fedora', os_version='42')
    assert 'FROM fedora:42\n' in text


def test_podman_gets_full_image_names(cm, tmp_path):
    assert 'FROM docker.io/library/fedora:44\n' in render(cm, tmp_path / 'p1', 'fedora', engine='podman')
    assert 'FROM docker.io/opensuse/leap:16.0\n' in render(cm, tmp_path / 'p2', 'opensuse', engine='podman')
