"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Offline tests of task/set-wsl-network (2026-11-22): the networking mode in .wslconfig (its other keys kept), the
addresses of the firewall rule read in every spelling Windows lists them, and a change of the rule that is done only
when the rule lets the addresses in afterwards (a declined administrator's prompt changed nothing, yet read as done).
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def task_module():
    """task/set-wsl-network's module with the task category's base class replaced by a plain one."""
    path = REPO_ROOT / 'task' / 'set-wsl-network' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    line = 'from task_c36be4b9314a45e0.api.ctask import InitCTask'
    assert line in src
    src = src.replace(line, 'class InitCTask:\n    def __init__(self, *args, **kwargs):\n        pass')
    ns = {'__name__': 'set_wsl_network_api', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_the_mode_is_set_and_the_other_keys_kept():
    m = task_module()
    text = '[wsl2]\nmemory=8GB\n\n[experimental]\nautoMemoryReclaim=gradual\n'
    new = m['set_mode'](text, 'mirrored')
    assert m['mode_of'](new) == 'mirrored'
    assert 'memory=8GB' in new and 'autoMemoryReclaim=gradual' in new
    assert m['mode_of'](m['set_mode'](new, 'nat')) == 'nat'
    assert m['mode_of'](m['set_mode']('', 'mirrored')) == 'mirrored'


def test_the_rule_addresses_in_every_spelling():
    m = task_module()
    network_of = m['network_of']
    assert network_of('192.168.1.67') == '192.168.1.67/32'
    assert network_of(' 192.168.1.0/24 ') == '192.168.1.0/24'
    assert network_of('192.168.1.0/255.255.255.0') == '192.168.1.0/24'
    assert network_of('not an address') == ''


class FakeCm:
    def error(self, text):
        return {'return': 1, 'error': text}


def run_task(m, tmp_path, monkeypatch, rule_after, code = 0):
    """The task's run with --allow_from, Windows and WSL faked: the elevated script answers code, the rule reads
    rule_after."""
    monkeypatch.setattr(m['os'].path, 'expanduser', lambda p: str(tmp_path))
    t = m['CTask']()
    t.cm = FakeCm()
    t._powershell = lambda script, elevated: (code, 'declined' if code else '')
    t._rule = lambda: rule_after
    t._run = lambda args, timeout = 120: (0, 'mirrored\n')
    return t.run({'control': {'con': False}}, allow_from = '192.168.1.67,192.168.1.141')


def test_a_rule_change_is_checked_afterwards(tmp_path, monkeypatch):
    m = task_module()
    assert run_task(m, tmp_path, monkeypatch, '192.168.1.67,192.168.1.141')['return'] == 0
    r = run_task(m, tmp_path, monkeypatch, '192.168.1.67,192.168.1.76')
    assert r['return'] == 1 and '192.168.1.141/32' in r['error']
    r = run_task(m, tmp_path, monkeypatch, '192.168.1.67', code = 1223)
    assert r['return'] == 1 and '1223' in r['error']


def reaches(m, rules, category = 'Private'):
    """The task's --check with Windows faked: the address on a network of that category, Hyper-V's rules as given."""
    import json
    t = m['CTask']()
    t.cm = FakeCm()
    answer = {'alias': 'Tailscale', 'category': category, 'rules': rules}
    t._powershell = lambda script, elevated: (0, '@@HV@@ ' + json.dumps(answer))
    return t._reaches('100.70.1.2', ['100.70.1.3', '100.70.1.4'])


def test_check_counts_only_rules_for_every_port_from_the_peers_on_this_address():
    m = task_module()
    tailscale = {'name': 'Tailscale-In', 'local': '100.70.1.2', 'remote': 'Any', 'protocol': 'Any', 'ports': 'Any',
                 'profiles': 'Domain, Private'}
    assert reaches(m, [tailscale])[0]
    # another network's profile, another address, one port only, other peers: no
    assert not reaches(m, [tailscale], category = 'Public')[0]
    assert not reaches(m, [dict(tailscale, local = '100.70.1.9')])[0]
    assert not reaches(m, [dict(tailscale, protocol = 'TCP', ports = '22')])[0]
    assert not reaches(m, [dict(tailscale, remote = '100.70.1.3')])[0]
    # cMeta's own rule: any address of this machine, the peers' network
    assert reaches(m, [dict(tailscale, name = 'cMeta', local = 'Any', remote = '100.64.0.0/10', profiles = 'Any')])[0]
    assert not reaches(m, [])[0]
