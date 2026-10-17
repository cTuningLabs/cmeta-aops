"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/openshell, task/run-openshell-gateway and tool/nemoclaw (2026-10-17): the release assets of each
OS and CPU, the gateway's configuration text (plaintext on loopback, the JWT keys of generate-certs, the driver only
when asked), the reading of the CLI's gateway list, the Docker Desktop hint, NemoClaw's launcher and Node check.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel, fakes):
    """A module of the tree with its cMeta imports replaced by stand-ins (sys.modules restored after the import)."""
    saved = {name: sys.modules.get(name) for name in fakes}
    for name, attrs in fakes.items():
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    try:
        path = REPO_ROOT / rel
        spec = importlib.util.spec_from_file_location('m_' + path.parent.name.replace('-', '_'), str(path))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return m


class Base:
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(scope='module')
def openshell():
    return load('tool/openshell/api_v1.py', {'tool_c393ba5c6fa14f66': {}, 'tool_c393ba5c6fa14f66.api': {},
                                             'tool_c393ba5c6fa14f66.api.ctool': {'InitCTool': Base},
                                             'tool_c393ba5c6fa14f66.api.common_release': {'install_release': None}})


@pytest.fixture(scope='module')
def gateway():
    return load('task/run-openshell-gateway/api_v1.py', {'task_c36be4b9314a45e0': {}, 'task_c36be4b9314a45e0.api': {},
                                                         'task_c36be4b9314a45e0.api.ctask': {'InitCTask': Base}})


@pytest.fixture(scope='module')
def nemoclaw():
    return load('tool/nemoclaw/api_v1.py', {'tool_c393ba5c6fa14f66': {}, 'tool_c393ba5c6fa14f66.api': {},
                                            'tool_c393ba5c6fa14f66.api.ctool': {'InitCTool': Base}})


def asset(spec, uname, uarch, version='0.1.4'):
    os_name, arch = spec['os'].get(uname), spec['arch'].get(uarch)
    if os_name is None or [uname, uarch] in spec['unsupported']:
        return None
    return spec['url'].format(version=version, os=os_name, arch=arch)


def test_the_release_assets(openshell):
    base = 'https://github.com/NVIDIA/OpenShell/releases/download/v0.1.4/'
    assert asset(openshell.CLI, 'linux', 'amd64') == base + 'openshell-x86_64-unknown-linux-musl.tar.gz'
    assert asset(openshell.GATEWAY, 'linux', 'arm64') == base + 'openshell-gateway-aarch64-unknown-linux-gnu.tar.gz'
    assert asset(openshell.CLI, 'darwin', 'arm64') == base + 'openshell-aarch64-apple-darwin.tar.gz'
    assert asset(openshell.GATEWAY, 'darwin', 'arm64') == base + 'openshell-gateway-aarch64-apple-darwin.tar.gz'
    assert asset(openshell.CLI, 'darwin', 'amd64') is None and asset(openshell.CLI, 'windows', 'amd64') is None
    assert openshell.CLI['checksum']['list'].endswith('/openshell-checksums-sha256.txt')
    assert openshell.GATEWAY['checksum']['list'].endswith('/openshell-gateway-checksums-sha256.txt')


def test_the_gateway_configuration(gateway):
    text = gateway.gateway_toml('cmeta', 17691, '', '/home/u/.local/state/openshell/cmeta-cmeta/pki/jwt')
    assert 'bind_address = "127.0.0.1:17691"' in text and 'disable_tls = true' in text
    assert 'allow_unauthenticated_users = true' in text and 'compute_driver' not in text
    assert 'signing_key_path = "/home/u/.local/state/openshell/cmeta-cmeta/pki/jwt/signing.pem"' in text
    assert 'compute_driver = "podman"' in gateway.gateway_toml('cmeta', 1, 'podman', '/k')
    if sys.version_info >= (3, 11):
        import tomllib
        data = tomllib.loads(gateway.gateway_toml('x', 17000, 'docker', 'C:\\Users\\u\\jwt'))
        assert data['openshell']['version'] == 2 and data['openshell']['gateway']['compute_driver'] == 'docker'
        assert data['openshell']['gateway']['gateway_jwt']['kid_path'] == 'C:/Users/u/jwt/kid'
        assert data['openshell']['gateway']['gateway_jwt']['gateway_id'] == 'cmeta-x'


def test_the_gateway_list_and_the_hint(gateway):
    listing = '[{"name": "cmeta", "endpoint": "http://127.0.0.1:17691"}, {"name": "other", "endpoint": "https://x"}]'
    assert gateway.registered(listing, 'cmeta') == 'http://127.0.0.1:17691'
    assert gateway.registered('{"gateways": [{"name": "cmeta", "url": "http://127.0.0.1:1"}]}', 'cmeta') == 'http://127.0.0.1:1'
    assert gateway.registered(listing, 'nope') is None and gateway.registered('not json', 'cmeta') is None
    assert gateway.supervisor_unreachable('Error: Startup configuration fetch failed after 5 attempts')
    assert not gateway.supervisor_unreachable('cmeta-openshell-ok')
    assert 'Enable host networking' in gateway.DESKTOP_HINT
    assert gateway.podman_major('podman version 5.7.0') == 5 and gateway.podman_major('podman version 4.9.3') == 4
    assert gateway.podman_major('') == 0


def test_the_nemoclaw_launcher_and_node(nemoclaw):
    text = nemoclaw.launcher_text('/c/node/bin/node', "/c/x's/bin/nemoclaw.js", '/c/os/openshell')
    assert text.startswith('#!/bin/sh\n')
    assert ': "${NEMOCLAW_OPENSHELL_BIN:=/c/os/openshell}"' in text and 'export NEMOCLAW_OPENSHELL_BIN' in text
    assert text.rstrip().endswith("""exec '/c/node/bin/node' '/c/x'"'"'s/bin/nemoclaw.js' "$@\"""")
    assert 'NEMOCLAW_OPENSHELL_BIN' not in nemoclaw.launcher_text('/n/node', '/s/nemoclaw.js')
    assert nemoclaw.node_ok('v24.21.0') and nemoclaw.node_ok('v22.19.0')
    assert not nemoclaw.node_ok('v22.18.1') and not nemoclaw.node_ok('')
