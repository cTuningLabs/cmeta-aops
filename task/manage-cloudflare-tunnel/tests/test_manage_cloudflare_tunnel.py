"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import base64
import importlib.util
import json
import plistlib
from pathlib import Path

import pytest
from cmeta import CMeta


@pytest.fixture(scope = 'module')
def module():
    # The task's runtime imports (task_c36be4b9314a45e0.api.ctask) are registered by the engine
    cm = CMeta()
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'manage-cloudflare-tunnel,dfce798b50954b24', 'info': True, 'con': False})
    assert r['return'] == 0, r
    spec = importlib.util.spec_from_file_location('cloudflare_tunnel_test', Path(__file__).parents[1] / 'api_v1.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def token(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


def test_token_decoded_without_its_secret(module):
    t = token({'a': 'acc123', 't': '6f1c-tunnel', 's': 'c2VjcmV0'})
    info = module.decode_token(t + '\n')
    assert info == {'account': 'acc123', 'tunnel': '6f1c-tunnel'}
    assert module.decode_token(t.rstrip('='))['tunnel'] == '6f1c-tunnel'


@pytest.mark.parametrize('text', ['', 'not base64 !', token({'a': 'x', 't': 'y'}), token(['a']),
                                  base64.b64encode(b'\xff\xfe').decode(), 'abc def'])
def test_bad_tokens_refused(module, text):
    with pytest.raises(ValueError):
        module.decode_token(text)


def test_token_hidden_on_command_lines(module):
    assert module.redact(['cloudflared', 'tunnel', 'run', '--token', 'SECRET']) == ['cloudflared', 'tunnel', 'run', '--token', '<hidden>']
    assert module.redact(['x', '--token=SECRET', '--token-file', '/etc/cloudflared/token']) == \
        ['x', '--token=<hidden>', '--token-file', '/etc/cloudflared/token']


def test_systemctl_show(module):
    text = ('LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n'
            'ExecStart={ path=/usr/bin/cloudflared ; argv[]=/usr/bin/cloudflared --no-autoupdate tunnel run '
            '--token-file /etc/cloudflared/token ; ignore_errors=no ; start_time=[n/a] ; pid=864 ; code=(null) }\n')
    d = module.parse_systemctl_show(text)
    assert d['ActiveState'] == 'active' and d['UnitFileState'] == 'enabled'
    assert d['argv'] == ['/usr/bin/cloudflared', '--no-autoupdate', 'tunnel', 'run', '--token-file', '/etc/cloudflared/token']
    assert module.parse_systemctl_show('LoadState=not-found\nActiveState=inactive\nExecStart=\n')['argv'] == []


def test_launchctl_and_sc(module):
    text = ('system/com.cloudflare.cloudflared = {\n\tactive count = 1\n\tstate = running\n\n\tprogram = /usr/local/bin/cloudflared\n'
            '\targuments = {\n\t\t/usr/local/bin/cloudflared\n\t\t--no-autoupdate\n\t\ttunnel\n\t\trun\n\t\t--token-file\n'
            '\t\t/etc/cloudflared/token\n\t}\n}\n')
    d = module.parse_launchctl_print(text)
    assert d['state'] == 'running' and d['argv'][0] == '/usr/local/bin/cloudflared' and d['argv'][-1] == '/etc/cloudflared/token'
    sc = ('SERVICE_NAME: cloudflared\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : 4  RUNNING\n'
          '        START_TYPE         : 2   AUTO_START\n        BINARY_PATH_NAME   : "C:\\Program Files (x86)\\cloudflared\\cloudflared.exe" tunnel run --token SECRET\n')
    d = module.parse_sc_qc(sc)
    assert d['state'] == 'running' and d['enabled'] == 'auto_start'
    assert 'SECRET' not in ' '.join(module.redact(d['argv']))


def test_ingress_from_the_connector(module):
    # The shape cloudflared 2026.9.3 answers on /config (trimmed)
    config = {'version': 3, 'config': {'ingress': [
        {'hostname': 'cmeta.example.org', 'path': None, 'service': 'http://127.0.0.1:8228', 'originRequest': {}},
        {'hostname': 'ssh.example.org', 'path': '^/x', 'service': 'ssh://localhost:22'},
        {'hostname': '', 'path': None, 'service': 'http_status:404'}]}}
    p = module.parse_ingress(json.dumps(config))
    assert p['version'] == 3 and p['catch_all'] == 'http_status:404'
    assert [r['hostname'] for r in p['routes']] == ['cmeta.example.org', 'ssh.example.org']
    assert p['routes'][1]['path'] == '^/x'
    assert module.parse_ingress({'config': {}})['routes'] == []


@pytest.mark.parametrize('service,addr', [('http://127.0.0.1:8228', ('127.0.0.1', 8228)), ('https://localhost', ('localhost', 443)),
                                          ('http://web', ('web', 80)), ('tcp://[::1]:5432', ('::1', 5432)),
                                          ('ssh://localhost', ('localhost', 22)), ('http_status:404', None),
                                          ('hello_world', None), ('unix:/run/x.sock', None)])
def test_origin_address(module, service, addr):
    assert module.origin_address(service) == addr


def test_public_verdict(module):
    assert module.public_verdict(302, 'https://team.cloudflareaccess.com/cdn-cgi/access/login/x') == 'Cloudflare Access login'
    assert module.public_verdict(200, '') == '200'
    assert module.public_verdict(502, '').startswith('502: Cloudflare cannot reach')
    assert module.public_verdict(None, '') == 'no answer'


def test_last_error_of_the_log(module):
    log = ('Oct 16 15:12:12 host1 cloudflared[67198]: 2026-10-16T15:12:12Z INF Tunnel connection curve preferences: [X25519MLKEM768] connIndex=0\n'
           'Oct 16 15:12:12 host1 cloudflared[67198]: 2026-10-16T15:12:12Z ERR Register tunnel error from server side '
           'error="Failed to get tunnel" connIndex=0 event=0 ip=2606:4700:a8::5\n'
           'Oct 16 15:12:12 host1 cloudflared[67198]: 2026-10-16T15:12:12Z INF Retrying connection in up to 8s connIndex=0\n')
    assert module.last_error(log) == 'Register tunnel error from server side error="Failed to get tunnel"'
    assert module.last_error('2026-10-16T15:12:01Z INF all good\n') == ''


def test_service_files(module):
    unit = module.unit_text('/usr/bin/cloudflared')
    assert 'ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token' in unit
    plist = plistlib.loads(module.plist_bytes('/usr/local/bin/cloudflared'))
    assert plist['Label'] == 'com.cloudflare.cloudflared' and plist['RunAtLoad'] and plist['KeepAlive']
    assert plist['ProgramArguments'] == ['/usr/local/bin/cloudflared', '--no-autoupdate', 'tunnel', 'run', '--token-file', '/etc/cloudflared/token']


def test_install_steps(module):
    # A package binary is run where it is; the cMeta cache copy is copied to /usr/local/bin first
    s = module.action_steps('install', 'linux', binary = '/usr/bin/cloudflared', token_tmp = '/tmp/x/token', service_tmp = '/tmp/x/u')
    cmds = [c for _, c, _, _ in s]
    assert not any('/usr/local/bin/cloudflared' in c for c in cmds)
    assert 'install -m 0600 /tmp/x/token /etc/cloudflared/token' in cmds
    assert cmds[-3:] == ['systemctl daemon-reload', 'systemctl enable cloudflared', 'systemctl restart cloudflared']
    assert all(root for _, _, root, _ in s)

    s = module.action_steps('install', 'darwin', binary = '/home/u/CMETA/repos/local/cache/x y/content/cloudflared',
                            token_tmp = '/tmp/t', service_tmp = '/tmp/p')
    cmds = [c for _, c, _, _ in s]
    assert "install -m 0755 '/home/u/CMETA/repos/local/cache/x y/content/cloudflared' /usr/local/bin/cloudflared" in cmds
    assert cmds[-1] == 'launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist'
    assert [m for _, c, _, m in s if c.startswith('launchctl bootout')] == [True]

    with pytest.raises(ValueError, match = 'Windows|windows'):
        module.action_steps('install', 'windows', binary = 'C:\\x\\cloudflared.exe')


def test_upgrade_restart_uninstall_steps(module):
    cmds = [c for _, c, _, _ in module.action_steps('upgrade', 'linux', binary = '/usr/bin/cloudflared', channel = 'apt')]
    assert cmds == ['apt-get update', 'apt-get install --only-upgrade -y cloudflared', 'systemctl restart cloudflared']
    s = module.action_steps('upgrade', 'darwin', channel = 'brew')
    assert s[0][1] == 'brew upgrade cloudflared' and s[0][2] is False
    cmds = [c for _, c, _, _ in module.action_steps('upgrade', 'linux', channel = 'copy', new_binary = '/c/cloudflared')]
    assert cmds[0] == 'install -m 0755 /c/cloudflared /usr/local/bin/cloudflared'
    with pytest.raises(ValueError, match = 'cannot tell'):
        module.action_steps('upgrade', 'linux', binary = '/opt/x/cloudflared', channel = None)
    assert [c for _, c, _, _ in module.action_steps('restart', 'darwin')] == ['launchctl kickstart -k system/com.cloudflare.cloudflared']
    cmds = [c for _, c, _, _ in module.action_steps('uninstall', 'linux')]
    assert cmds[1] == 'rm -f /etc/systemd/system/cloudflared.service /etc/cloudflared/token'


def test_sudo_prefix(module):
    assert module.with_sudo('systemctl restart cloudflared', interactive = False) == 'sudo -n systemctl restart cloudflared'
    assert module.with_sudo('x', interactive = True) == 'sudo x'
    assert module.with_sudo('x', interactive = False, root = True) == 'x'
    assert module.needs_copy('/home/u/CMETA/cache/cloudflared') and not module.needs_copy('/usr/bin/cloudflared')
