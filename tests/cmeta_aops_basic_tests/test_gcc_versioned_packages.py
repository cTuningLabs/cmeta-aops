"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

An older gcc on Debian or Ubuntu (nvcc limits the host compiler: CUDA 11.8 takes gcc < 12): the tools gcc and
gcc-cpp install the newest gcc-<major> / g++-<major> package of the distribution in the version asked for
(category/tool/api/common_deb.py apt_versioned_package), not the system's gcc of another version.
"""

import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# What "apt-cache policy gcc-30 ... gcc-4" prints on Ubuntu 26.04 (abridged: the packages it knows)
POLICY = """gcc-15:
  Installed: 15.2.0-16ubuntu1
  Candidate: 15.2.0-16ubuntu1
  Version table:
 *** 15.2.0-16ubuntu1 500
        500 http://archive.ubuntu.com/ubuntu resolute/main amd64 Packages
gcc-14:
  Installed: (none)
  Candidate: 14.3.0-14ubuntu1
gcc-13:
  Installed: (none)
  Candidate: 13.4.0-10ubuntu1
gcc-12:
  Installed: (none)
  Candidate: 12.5.0-9ubuntu1
gcc-11:
  Installed: (none)
  Candidate: 11.5.0-11ubuntu2
gcc-10:
  Installed: (none)
  Candidate: (none)
"""


def load(rel, drop = (), names = None):
    path = ROOT / rel
    src = path.read_text(encoding = 'utf-8')
    for line in drop:
        assert line in src, line
        src = src.replace(line, '')
    ns = dict(names or {}, __name__ = 'gcc_test', __file__ = str(path))
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def deb():
    return load('category/tool/api/common_deb.py')


def with_apt(deb, output, which = '/usr/bin/apt-cache'):
    """common_deb with apt-cache answering output (and the commands it was asked)."""
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode = 0, stdout = output, stderr = '')

    deb['shutil'] = SimpleNamespace(which = lambda name: which)
    deb['subprocess'] = SimpleNamespace(run = run, DEVNULL = None, SubprocessError = Exception)
    return calls


def test_the_newest_package_in_the_range_or_with_the_prefix(deb, cm):
    tool = SimpleNamespace(cm = cm)
    calls = with_apt(deb, POLICY)
    pick = deb['apt_versioned_package']

    assert pick(tool, '<12', 'gcc-{major}') == 'gcc-11'
    assert calls[0][:2] == ['apt-cache', 'policy'] and 'gcc-30' in calls[0] and 'gcc-4' in calls[0]
    assert pick(tool, '<14', 'gcc-{major}') == 'gcc-13'
    assert pick(tool, '<15', 'gcc-{major}') == 'gcc-14'
    assert pick(tool, '>=12,<14', 'gcc-{major}') == 'gcc-13'
    assert pick(tool, '11', 'gcc-{major}') == 'gcc-11'
    assert pick(tool, '==12.5', 'gcc-{major}') == 'gcc-12'
    assert pick(tool, '<10', 'gcc-{major}') is None          # gcc-10 has no candidate, nothing older is known
    assert pick(tool, '', 'gcc-{major}') is None


def test_no_apt_no_package(deb, cm):
    with_apt(deb, POLICY, which = None)
    assert deb['apt_versioned_package'](SimpleNamespace(cm = cm), '<12', 'gcc-{major}') is None


def test_the_upstream_part_of_a_debian_version(deb):
    up = deb['apt_upstream_version']
    assert up('4:11.5.0-1ubuntu1~24.04.1') == '11.5.0'
    assert up('14.3.0-14ubuntu1') == '14.3.0'
    assert up('12.4.0+dfsg') == '12.4.0'


@pytest.mark.parametrize('rel, pattern', [('tool/gcc/api_v1.py', 'gcc-{major}'), ('tool/gcc-cpp/api_v1.py', 'g++-{major}')])
def test_the_gcc_tools_install_the_versioned_package(rel, pattern):
    asked = []

    def pick(tool, version, pat):
        asked.append((version, pat))
        return pat.format(major = 11) if version == '<12' else None

    ns = load(rel, ['from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                    'from tool_c393ba5c6fa14f66.api.common_deb import apt_versioned_package'],
              {'InitCTool': object, 'apt_versioned_package': pick})
    t = ns['CTool'].__new__(ns['CTool'])

    assert t.customize_install_cmd({}, 'apt install -y {{name}}', {'version': '<12'}) == \
        {'return': 0, 'package_name': pattern.format(major = 11)}
    assert t.customize_install_cmd({}, 'apt install -y {{name}}', {}) == {'return': 0}
    assert asked == [('<12', pattern), (None, pattern)]
