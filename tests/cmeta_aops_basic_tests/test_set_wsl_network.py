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
