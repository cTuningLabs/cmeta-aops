"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Wireless discovery must follow the selected hardware identity and never substitute a phone.
"""

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def instance(namespace):
    task = namespace['CTask'].__new__(namespace['CTask'])
    task.cm = SimpleNamespace(error=lambda message: {'return': 1, 'error': message},
                              catch_error=lambda r, **kw: r.get('return', 0) != 0, debug=False)
    return task


def context():
    return {'control': {'quiet': True}, 'tasks': {'local': {}, 'aggregated': {}, 'nested_call': 0,
            'global': {'adb': {'path': '/adb', 'qpath': '/adb'}, 'host': {'os': {'uname': 'linux'}}}}}


@pytest.mark.parametrize('address', ['10.0.0.1:0', '10.0.0.1:65536', '10.0.0.1:notaport',
                                    '10.0.0.1:123;echo', '10.0.0.1:123&echo', 'x\ny:123', ''])
def test_invalid_endpoints_cannot_reach_the_shell(task_namespace, address):
    with pytest.raises(ValueError):
        task_namespace('keep-adb-connection-alive')['endpoint'](address)


def test_legacy_default_port_and_ipv6(task_namespace):
    endpoint = task_namespace('keep-adb-connection-alive')['endpoint']
    assert endpoint('192.0.2.1') == '192.0.2.1:5555'
    assert endpoint('[2001:db8::1]:43291') == '[2001:db8::1]:43291'


def test_discovery_never_uses_the_pairing_port(task_namespace):
    parse = task_namespace('keep-adb-connection-alive')['mdns_services']
    assert parse('adb-WATCH-guid _adb-tls-pairing._tcp 192.0.2.1:12345\n'
                 'adb-WATCH-guid _adb-tls-connect._tcp. 192.0.2.1:54321\n') == [
                    {'name': 'adb-WATCH-guid', 'endpoint': '192.0.2.1:54321'}]


def test_reconnect_follows_changed_port_and_preserves_identity(task_namespace):
    task = instance(task_namespace('keep-adb-connection-alive'))
    calls, saved = [], []
    def command(ctx, args, **kw):
        calls.append(args)
        if args == ['devices']: out = 'List of devices attached\nPHONE device\n'
        elif args == ['mdns', 'services']:
            out = ('adb-WATCH-guid _adb-tls-pairing._tcp 192.0.2.1:11111\n'
                   'adb-WATCH-guid _adb-tls-connect._tcp 192.0.2.1:54321\n'
                   'adb-PHONE-guid _adb-tls-connect._tcp 192.0.2.2:44444\n')
        elif args[0] == 'connect': out = 'connected to ' + args[1]
        else:
            out = ('WATCH\nWatch model\nSamsung\nfeature:android.hardware.type.watch\n'
                   if args[1] == '192.0.2.1:54321' else 'PHONE\nPhone\nGoogle\n')
        return {'return': 0, 'returncode': 0, 'stdout': out}
    task.command = command
    task.remember = lambda root, receipt: saved.append(receipt)
    r = task.connect_once(context(), '/host', {'required_features': ['android.hardware.type.watch']},
                          {'device_serial': 'WATCH', 'endpoint': '192.0.2.1:22222'}, None, '', 15)
    assert r['device_serial'] == 'WATCH' and r['serial'] == '192.0.2.1:54321'
    assert ['connect', '192.0.2.1:54321'] in calls
    assert ['connect', '192.0.2.1:11111'] not in calls
    assert len(saved) == 1


@pytest.mark.parametrize('expected,required,response', [
    ('WATCH', [], 'OTHER\nOther watch\nSamsung\nfeature:android.hardware.type.watch\n'),
    ('', ['android.hardware.type.watch'], 'PHONE\nPixel\nGoogle\nfeature:android.hardware.telephony\n'),
])
def test_identity_or_watch_feature_mismatch_fails(task_namespace, expected, required, response):
    task = instance(task_namespace('keep-adb-connection-alive'))
    task.command = lambda *a, **k: {'return': 0, 'returncode': 0, 'stdout': response}
    with pytest.raises(ValueError):
        task.identity(context(), '192.0.2.1:12345', expected, required, 15)


def test_first_use_cannot_guess_a_connected_phone(task_namespace):
    task = instance(task_namespace('keep-adb-connection-alive'))
    task.command = lambda ctx, args, **k: {'return': 0, 'returncode': 0,
        'stdout': 'PHONE device\n' if args == ['devices'] else 'adb-PHONE-guid _adb-tls-connect._tcp 192.0.2.2:44444\n'}
    with pytest.raises(ValueError, match='no watch endpoint configured'):
        task.connect_once(context(), None, {}, {}, None, '', 15)


def test_pairing_quiet_mode_does_not_make_up_a_pin(task_namespace):
    task = instance(task_namespace('keep-adb-connection-alive'))
    task.host_config = lambda host: (None, {}, {})
    task.command = lambda *a, **k: pytest.fail('pairing command must not run without a terminal')
    r = task.run(context(), pair=True, once=True, pairing_endpoint='192.0.2.1:12345')
    assert r['return'] != 0 and 'terminal' in r['error']


def test_connect_can_observe_an_existing_declared_usb_host(task_namespace):
    task = instance(task_namespace('keep-adb-connection-alive'))
    task.host_config = lambda host: (None, {'serial': 'USB'}, {})
    calls = []
    task.connect_once = lambda *args: calls.append(args) or {'serial': 'USB', 'device_serial': 'USB'}
    r = task.run(context(), host='phone', once=True)
    assert r['return'] == 0 and r['serial'] == 'USB'
    assert calls[0][-2] == 'USB'


def test_legacy_loop_retries_and_ctrl_c_stops_without_a_server_reset(task_namespace, monkeypatch):
    ns = task_namespace('keep-adb-connection-alive')
    task = instance(ns)
    task.host_config = lambda host: (None, {}, {})
    calls = []
    def connect(*args):
        calls.append(args)
        raise ValueError('temporarily offline')
    task.connect_once = connect
    def stop(seconds): raise KeyboardInterrupt()
    monkeypatch.setattr(ns['time'], 'sleep', stop)
    assert task.run(context(), ip='192.0.2.1:12345')['stopped']
    assert len(calls) == 1


def host_module():
    spec = importlib.util.spec_from_file_location('wireless_host_test', ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('wireless', [True, False])
def test_observed_transport_applies_only_to_opted_in_hosts(wireless):
    module = host_module()
    category = module.Category.__new__(module.Category)
    category._host_cache = {}
    desc = {'type': 'adb', 'access': {'serial': 'USB'}}
    if wireless: desc['access']['wireless'] = {'auto_connect': True}
    category._read_yaml = lambda path: ({'adb_connection': {'serial': '192.0.2.1:55555'}}
                                       if path.endswith('state.yaml') else desc)
    h = category._load_host({'path': '/host', 'cmeta_ref_parts': {'artifact_alias': 'watch'}})
    assert h['desc']['access']['serial'] == ('192.0.2.1:55555' if wireless else 'USB')


def test_host_connect_reuses_existing_task_without_forcing_a_repository():
    module = host_module()
    category = module.Category.__new__(module.Category)
    category._host_cache = {}
    category.cmeta = {'uses_categories': {'task': 'task,uid'},
                      'uses_artifacts': {'task::keep-adb-connection-alive': 'keep-adb-connection-alive,uid'}}
    category._get_host = lambda *a: {'return': 0, 'host': {'alias': 'watch', 'uid': '123', 'type': 'adb'}}
    calls = []
    category.cm = SimpleNamespace(catch_error=lambda r: bool(r.get('return')),
        access=lambda p: calls.append(p) or {'return': 0, 'serial': '192.0.2.1:55555'})
    assert category.connect_({}, 'watch')['return'] == 0
    assert calls[0]['host'] == 'watch,123' and calls[0]['once'] is True
    assert category.connect_({}, 'watch', keepalive=True)['return'] == 0
    assert calls[1]['once'] is False


def test_host_run_reconnects_and_uses_the_new_transport():
    module = host_module()
    category = module.Category.__new__(module.Category)
    calls = []
    category.cm = SimpleNamespace(catch_error=lambda r: bool(r.get('return')))
    category.connect_ = lambda ctx, name: calls.append(name) or {'return': 0, 'serial': '192.0.2.1:54321'}
    category._adb_cmd = lambda parent, args: 'adb ' + args
    h = {'type': 'adb', 'alias': 'watch', 'uid': '123', 'via': None, 'via_list': [],
         'desc': {'access': {'shell': 'none', 'serial': '192.0.2.1:11111',
                             'wireless': {'auto_connect': True}}}}
    r = category._cmd_run({}, h, 'echo ready', raw=True)
    assert r['return'] == 0 and calls == ['watch,123']
    assert '-s 192.0.2.1:54321 shell' in r['cmd']
    assert '11111' not in r['cmd']


def test_host_selection_accepts_a_program_context_with_loaded_modules():
    module = host_module()
    category = module.Category.__new__(module.Category)
    category._host_cache = {}
    ctx = {'category': 'host,uid', 'command': 'connect', 'control': {},
           'tasks': {'local': {'api_module': ModuleType('program_api')}}}
    def access(p):
        assert p['ctx'] is ctx
        assert p['base'] is True and p['category'] == 'host,uid'
        return {'return': 0, 'artifacts': []}
    category.cm = SimpleNamespace(access=access)
    assert category._select(ctx, 'watch') == {'return': 0, 'hosts': []}


def test_probe_preserves_the_latest_wireless_identity(tmp_path):
    module = host_module()
    category = module.Category.__new__(module.Category)
    category.path = str(ROOT / 'category/host')
    category.logger = None
    observed = {'serial': '192.0.2.1:54321', 'device_serial': 'WATCH'}
    category._read_yaml = lambda path: {'adb_connection': observed}
    category._cmd_stdin = lambda *a: {'return': 0, 'cmd': 'probe'}
    category._run_local = lambda *a, **k: {'returncode': 0, 'stdout': 'hostname=watch\nos=Android\n'}
    writes = []
    files = SimpleNamespace(safe_write_file=lambda path, data, **k: writes.append(data) or {'return': 0})
    category.cm = SimpleNamespace(utils=SimpleNamespace(files=files))
    h = {'type': 'adb', 'path': str(tmp_path), 'desc': {'access': {'shell': 'none',
         'wireless': {'auto_connect': True}}}, 'state': {}}
    r = category._probe_one({}, h, 10, False)
    assert r['return'] == 0 and writes[0]['adb_connection'] == observed


def test_android_cpu_target_connects_the_selected_fleet_host_first(task_namespace):
    task = instance(task_namespace('target--android-cpu'))
    task.cmeta = {'uses_categories': {'host': 'host,uid'}}
    task.category_alias, task.category_uid = 'task', 'uid'
    calls = []
    def access(p):
        calls.append(p)
        if p['category'] == 'host,uid': return {'return': 0, 'serial': '192.0.2.1:55555'}
        return {'return': 0, 'returncode': 0, 'stdout': 'PHONE\tdevice\n192.0.2.1:55555\tdevice\n'}
    task.cm.access = access
    ctx = context()
    assert task.init(ctx, {'device_host': 'watch'})['return'] == 0
    assert calls[0]['command'] == 'connect'
    assert ctx['tasks']['local']['adb_serial'] == '192.0.2.1:55555'
