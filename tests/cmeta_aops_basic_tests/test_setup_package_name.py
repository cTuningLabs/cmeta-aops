"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the package a tool's install commands name (task/setup upgrade.package_name_for): the distribution's
own ID first, then a distribution it is like (ID_LIKE: Rocky Linux is "rhel centos fedora", Amazon Linux "fedora") -
Linux only - then package_name, then the tool's alias. A distribution listed by its own ID, and Ubuntu or Debian with
no entry of their own, get what they got before.
"""

import pathlib
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def upgrade():
    path = REPO_ROOT / 'task' / 'setup' / 'upgrade.py'
    m = types.ModuleType('setup_upgrade_under_test')
    m.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), m.__dict__)
    return m


def host(os_id, id_like='', uname='linux'):
    return {'os': {'uname': uname}, 'os_extra': {'id': os_id, 'id_like': id_like}}


GCC_CPP = {'package_name': 'g++', 'package_name_os_id': {'fedora': 'gcc-c++', 'rhel': 'gcc-c++', 'azurelinux': 'gcc-c++'}}
DOCKER = {'package_name': 'docker.io', 'package_name_os_id': {'fedora': 'docker', 'rhel': 'docker', 'arch': 'docker'}}


@pytest.mark.parametrize('desc, h, expected', [
    (GCC_CPP, host('ubuntu', 'debian'), 'g++'),                       # as before
    (GCC_CPP, host('debian'), 'g++'),                                 # as before
    (GCC_CPP, host('rocky', 'rhel centos fedora'), 'gcc-c++'),        # through ID_LIKE (before: g++, which dnf has not)
    (GCC_CPP, host('amzn', 'fedora'), 'gcc-c++'),
    (GCC_CPP, host('azurelinux', 'azurelinux'), 'gcc-c++'),           # its own ID
    (GCC_CPP, host('fedora'), 'gcc-c++'),
    (DOCKER, host('manjaro', 'arch'), 'docker'),
    (DOCKER, host('ubuntu', 'debian'), 'docker.io'),
    (DOCKER, host('darwin', 'debian', uname='darwin'), 'docker.io'),  # macOS: its compatibility ID_LIKE is not used
    ({}, host('ubuntu', 'debian'), 'the-alias'),
])
def test_the_package_of_a_distribution(upgrade, desc, h, expected):
    assert upgrade.package_name_for(desc, h, 'the-alias') == expected


def test_the_own_id_wins_over_a_like(upgrade):
    desc = {'package_name_os_id': {'rocky': 'own', 'rhel': 'like'}}
    assert upgrade.package_name_for(desc, host('rocky', 'rhel centos fedora'), 'x') == 'own'
