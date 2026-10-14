"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Selection, non-interactive mutation boundaries, OS plans, and actual Windows boot-helper
execution against fake volumes. No services, firewall, real disks or real keys are changed.
"""

import base64
import ctypes
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup_host(task_namespace, repo_root):
    ns = task_namespace('setup-cmeta-host')
    import yaml
    desc = yaml.safe_load((repo_root / 'task/setup-cmeta-host/_desc.yaml').read_text())
    task = ns['CTask'].__new__(ns['CTask'])
    task.cdesc = desc
    task.module_path = str(repo_root / 'task/setup-cmeta-host')
    task.cm = type('CM', (), {'home_path': Path('existing-home')})()
    return ns, task


def test_profiles_and_false_strings(setup_host):
    ns, task = setup_host
    overrides = dict(ssh=None, tailscale=None, keep_awake=None, boot_unlock=None)
    assert ns['selection'](task.cdesc, 'fleet', overrides)['ssh']
    for profile in ('managed', 'slurm', 'kubernetes', 'aks', 'mpi'):
        assert not any(ns['selection'](task.cdesc, profile, overrides).values())
    chosen = ns['selection'](task.cdesc, 'fleet', dict(overrides, ssh='false', tailscale=False))
    assert not any(chosen.values())
    assert ns['selection'](task.cdesc, 'slurm', dict(overrides, ssh=True))['ssh']
    with pytest.raises(ValueError):
        ns['switch']('maybe')


def test_no_apply_in_quiet_check_or_preview(setup_host, monkeypatch):
    ns, task = setup_host
    calls = []
    monkeypatch.setattr(ns['platform'], 'system', lambda: 'Windows')
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)), raising=False)
    def windows(config, timeout=60):
        calls.append(config['action'])
        return {'services': {'sshd': {'state': 'Running'}, 'Tailscale': {'state': 'missing'}}}
    task._windows = windows
    ctx = {'control': {'quiet': True}}
    for options in ({}, {'check': True}, {'dry_run': True, 'apply': True}, {'profile': 'aks', 'apply': True}):
        assert task.run(ctx, **options)['return'] == 0
    assert calls == ['check'] * 4
    task.run(ctx, apply=True, tailscale=False)
    assert calls[-2:] == ['check', 'apply']
    assert task.run(ctx, check=True, apply=True)['return'] != 0


def test_new_windows_ssh_reuses_tool_only_after_apply(setup_host, monkeypatch, tmp_path):
    ns, task = setup_host
    monkeypatch.setattr(ns['platform'], 'system', lambda: 'Windows')
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)), raising=False)
    ctx = {'control': {'quiet': True}, 'tasks': {'global': {}}}
    public_key = tmp_path / 'test.pub'
    public_key.write_text('FAKE TEST PUBLIC KEY')
    task.category_alias, task.category_uid = 'task', 'c36be4b9314a45e0'
    calls = []
    def access(params):
        calls.append(params['name'])
        ctx['tasks']['global']['openssh-server'] = {'path': str(tmp_path / 'package/sshd.exe')}
        return {'return': 0}
    task.cm.access = access
    task._windows = lambda config, timeout=60: {'services': {'sshd': {'state': 'missing'}}}
    result = task.run(ctx, apply=True, profile='ssh', keys=str(public_key), dry_run=True)
    assert result['return'] == 0 and not calls
    result = task.run(ctx, apply=True, profile='ssh', keys=str(public_key))
    assert result['return'] == 0 and result['applied']
    assert calls == [task.cdesc['windows']['openssh_tool']]
    assert result['configuration']['sshd_source'] == str(tmp_path / 'package')


def test_existing_report_fails_before_apply(setup_host, tmp_path):
    _, task = setup_host
    report = tmp_path / 'report.json'
    report.write_text('existing')
    result = task.run({'control': {'quiet': True}}, apply=True, report=str(report))
    assert result['return'] != 0 and 'already exists' in result['error']
    assert report.read_text() == 'existing'


def test_nonterminal_apply_needs_quiet(setup_host, monkeypatch):
    ns, task = setup_host
    monkeypatch.setattr(ns['platform'], 'system', lambda: 'Windows')
    monkeypatch.setattr(ns['sys'], 'stdin', type('Input', (), {'isatty': lambda self: False})())
    calls = []
    task._windows = lambda config, timeout=60: calls.append(config['action']) or {'services': {}}
    result = task.run({'control': {}}, apply=True)
    assert result['return'] != 0 and '-q' in result['error']
    assert calls == ['check']


def test_interactive_decline_and_service_selection(setup_host, monkeypatch):
    ns, task = setup_host
    monkeypatch.setattr(ns['platform'], 'system', lambda: 'Windows')
    monkeypatch.setattr(ns['sys'], 'stdin', type('Input', (), {'isatty': lambda self: True})())
    # ssh no, tailscale yes, power no, unlock no, apply no.
    answers = iter(['n', 'y', 'n', 'n', 'n'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    calls = []
    task._windows = lambda config, timeout=60: calls.append(config['action']) or {'services': {}}
    result = task.run({'control': {}})
    assert result['return'] == 0 and not result['applied']
    assert result['selected'] == dict(ssh=False, tailscale=True, keep_awake=False, boot_unlock=False)
    assert calls == ['check']


def test_unlock_identity_validation(setup_host):
    ns, task = setup_host
    options = dict(volume_guid='11111111-1111-1111-1111-111111111111',
                   persistent_id='22222222-2222-2222-2222-222222222222',
                   protector_id='33333333-3333-3333-3333-333333333333', drive='D:')
    ns['validate_unlock'](options)
    with pytest.raises(ValueError):
        ns['validate_unlock'](dict(options, drive=os.environ.get('SystemDrive', 'C:')))
    with pytest.raises(ValueError):
        ns['validate_unlock'](dict(options, volume_guid='wrong'))
    with pytest.raises(ValueError):
        ns['validate_unlock'](dict(options, protector_id=''))


def test_encoded_powershell_values_are_data(setup_host):
    ns, _ = setup_host
    config = {'keys': 'a" & echo hacked | whoami', 'home': 'C:\\unicode-\u00e9'}
    command = ns['powershell_command']("C:/a'b/windows.ps1", config)
    assert 'echo hacked' not in command
    source = base64.b64decode(command.split()[-1]).decode('utf-16-le')
    assert "C:/a''b/windows.ps1" in source
    encoded_config = source.split("-Data '")[1].rstrip("'")
    assert json.loads(base64.b64decode(encoded_config)) == config


def test_unix_uses_native_services_without_cluster_requirement(setup_host):
    _, task = setup_host
    state = {'ssh': {'units': {'ssh.service': {'LoadState': 'loaded'}}},
             'tailscale': {'units': {'tailscaled.service': {'LoadState': 'loaded'}}}}
    selected = dict(ssh=True, tailscale=True, keep_awake=True, boot_unlock=False)
    commands = task._unix_plan('Linux', selected, state)
    assert commands[:2] == [['systemctl', 'enable', '--now', 'ssh.service'],
                           ['systemctl', 'enable', '--now', 'tailscaled.service']]
    assert commands[-1][1] == 'mask'
    assert task._unix_plan('Linux', dict.fromkeys(selected, False), {}) == []
    with pytest.raises(ValueError, match='OpenSSH'):
        task._unix_plan('Linux', selected, {'ssh': {}})


@pytest.mark.skipif(os.name != 'nt', reason='Runs Windows PowerShell with mocked volume APIs')
@pytest.mark.parametrize('protection,letter,locked,expected', [(1, 'D:', 1, True), (1, 'D:', 0, True),
                                                             (0, 'D:', 1, False), (1, 'E:', 1, False)])
def test_real_boot_helper_fails_closed_and_unlocks_exact_volume(setup_host, tmp_path, protection, letter, locked, expected):
    _, task = setup_host
    helper = tmp_path / 'unlock-data.ps1'
    helper.write_bytes((Path(task.module_path) / 'scripts/unlock-data.ps1').read_bytes())
    key = tmp_path / 'fake-test-key.BEK'
    key.write_text('FAKE TEST DATA, NOT A REAL KEY')
    config = dict(device='test-device', persistent_id='test-id', drive='D:', os_drive='C:',
                  key_file=str(key), home=str(tmp_path))
    (tmp_path / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    # These functions replace only the native volume APIs in this child PowerShell process.
    source = r'''
$global:cmetaTestLock = __LOCK__
function Get-CimInstance {
    param($Namespace, $ClassName, $Filter)
    if ($ClassName -eq 'Win32_OperatingSystem') { return @{LastBootUpTime=(Get-Date)} }
    return @{DeviceID='test-device'; PersistentVolumeID='test-id'; DriveLetter='__LETTER__'}
}
function Invoke-CimMethod {
    param($InputObject, $MethodName)
    if ($MethodName -eq 'GetProtectionStatus') { return @{ReturnValue=0; ProtectionStatus=__PROTECTION__} }
    return @{ReturnValue=0; LockStatus=$global:cmetaTestLock}
}
function Unlock-BitLocker {
    param($MountPoint, $RecoveryKeyPath)
    if ($MountPoint -ne 'D:' -or $RecoveryKeyPath -ne '__KEY__') { throw 'Wrong unlock target/key' }
    $global:cmetaTestLock=0
    [IO.File]::WriteAllText('__MARKER__', 'called')
}
& '__HELPER__'
'''
    replacements = {'LOCK': str(locked), 'LETTER': letter, 'PROTECTION': str(protection),
                    'KEY': str(key), 'MARKER': str(tmp_path / 'unlock-called'), 'HELPER': str(helper)}
    for name, value in replacements.items():
        source = source.replace('__' + name + '__', value.replace("'", "''"))
    script = tmp_path / 'mock-volume.ps1'
    script.write_text(source, encoding='utf-8')
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                'Bypass', '-File', str(script)], capture_output=True, timeout=25)
    result = json.loads((tmp_path / 'last-run.json').read_text(encoding='utf-8-sig'))
    assert result['unlocked'] is expected
    assert (completed.returncode == 0) is expected
    assert (tmp_path / 'unlock-called').exists() is (expected and bool(locked))
