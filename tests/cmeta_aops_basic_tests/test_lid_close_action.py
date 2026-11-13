"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The task lid-close-action offline: powercfg's output read whatever the language of Windows, logind's settings and the
drop-in written for each power source, what disable keeps and enable puts back on Windows (never "nothing" kept over
an action), and on macOS an enable that changes only what this task's disable changed. Nothing here changes a power
setting of the machine running the tests.
"""

import json
import os

import pytest

EN = """Power Setting GUID: 5ca83367-6e45-459f-a27b-476b1d01c936  (Lid close action)
      Possible Setting Index: 000
      Possible Setting Friendly Name: Do nothing
      Possible Setting Index: 001
      Possible Setting Friendly Name: Sleep
    Current AC Power Setting Index: 0x00000002
    Current DC Power Setting Index: 0x00000001
"""
FR = """GUID du paramètre d'alimentation : 5ca83367-6e45-459f-a27b-476b1d01c936  (Action de fermeture du capot)
      Index de paramètre possible : 000
    Index actuel du paramètre d'alimentation sur secteur : 0x00000000
    Index actuel du paramètre d'alimentation sur batterie : 0x00000003
"""


@pytest.fixture
def ns(task_namespace):
    return task_namespace('lid-close-action')


class StubCM:
    def error(self, text):
        return {'return': 1, 'error': text}


def make_task(ns, tmp_path):
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM()
    task.con = False
    task.cmeta = {'uses_categories': {'log': 'log', 'task': 'task'}}
    task._folder = lambda: {'return': 0, 'path': str(tmp_path)}
    return task


def test_powercfg_is_read_by_its_numbers_in_any_language(ns):
    assert ns['parse_powercfg'](EN) == (2, 1)
    assert ns['parse_powercfg'](FR) == (0, 3)
    assert ns['parse_powercfg']('') == (None, None)


def test_logind_on_ac_follows_the_battery_when_empty(ns):
    eff = ns['logind_effective']
    assert eff({'HandleLidSwitch': 'suspend', 'HandleLidSwitchExternalPower': ''}) == {'ac': 'suspend', 'battery': 'suspend'}
    assert eff({'HandleLidSwitch': 'hibernate', 'HandleLidSwitchExternalPower': 'ignore'}) == {'ac': 'ignore', 'battery': 'hibernate'}
    assert eff({}) == {'ac': 'suspend', 'battery': 'suspend'}


def test_the_drop_in_for_each_power_source(ns):
    eff = {'ac': 'suspend', 'battery': 'suspend'}
    ac = ns['logind_dropin']('ac', eff)
    assert '[Login]' in ac and 'HandleLidSwitchExternalPower=ignore' in ac and 'HandleLidSwitch=ignore' not in ac
    both = ns['logind_dropin']('both', eff)
    assert 'HandleLidSwitchExternalPower=ignore' in both and 'HandleLidSwitch=ignore' in both
    # the battery alone: AC follows HandleLidSwitch when its own value is empty - its action is written out to stay
    battery = ns['logind_dropin']('battery', eff)
    assert 'HandleLidSwitch=ignore' in battery and 'HandleLidSwitchExternalPower=suspend' in battery


def test_windows_disable_keeps_what_it_replaces_and_enable_puts_it_back(ns, tmp_path):
    task = make_task(ns, tmp_path)
    now = {'ac': 2, 'battery': 2}
    writes = []
    task._win_read = lambda: dict(now)

    def write(values):
        writes.append(dict(values))
        now.update(values)
        return {'return': 0}
    task._win_write = write
    record = os.path.join(str(tmp_path), 'previous.json')

    assert task._windows('disable', 'ac', '')['ac'] == 'nothing'
    assert writes[-1] == {'ac': 0} and json.load(open(record)) == {'ac': 2}
    task._windows('disable', 'ac', '')                      # again: "nothing" is never kept over hibernate
    assert json.load(open(record)) == {'ac': 2}
    r = task._windows('enable', 'ac', '')
    assert writes[-1] == {'ac': 2} and r['ac'] == 'hibernate' and not os.path.exists(record)

    task._windows('disable', 'both', '')
    assert writes[-1] == {'ac': 0, 'battery': 0} and json.load(open(record)) == {'ac': 2, 'battery': 2}
    task._windows('enable', 'battery', '')                  # the battery back; AC's kept value stays for later
    assert writes[-1] == {'battery': 2} and json.load(open(record)) == {'ac': 2}
    task._windows('enable', 'ac', '')
    assert not os.path.exists(record)


def test_windows_enable_with_nothing_kept_sets_to(ns, tmp_path):
    task = make_task(ns, tmp_path)
    writes = []
    task._win_read = lambda: {'ac': 0, 'battery': 0}
    task._win_write = lambda values: writes.append(dict(values)) or {'return': 0}
    task._windows('enable', 'ac', '')
    task._windows('enable', 'both', 'hibernate')
    assert writes == [{'ac': 1}, {'ac': 2, 'battery': 2}]


def test_macos_enable_changes_only_what_disable_changed(ns, tmp_path):
    # 2026-11-13: an enable without a record turned off a disablesleep another task had set on a test Mac
    task = make_task(ns, tmp_path)
    state = {'value': '1'}
    task._run = lambda words, input_text=None: (0, ' SleepDisabled\t\t%s\n' % state['value'])
    calls = []

    def sudo(words, input_text=None):
        calls.append(words)
        state['value'] = words[-1]
        return 0, ''
    task._sudo = sudo

    task._macos('enable', 'ac')                             # not this task's 1: left as it is
    assert calls == [] and state['value'] == '1'
    task._macos('disable', 'ac')
    task._macos('enable', 'ac')
    assert calls == [['pmset', '-a', 'disablesleep', '1'], ['pmset', '-a', 'disablesleep', '1']] and state['value'] == '1'

    state['value'] = '0'
    task._macos('disable', 'both')
    assert state['value'] == '1'
    task._macos('enable', 'both')
    assert state['value'] == '0' and not os.path.exists(os.path.join(str(tmp_path), 'previous.json'))
    task._macos('enable', 'both', 'sleep')                  # asked for: 0 even with nothing kept
    assert calls[-1] == ['pmset', '-a', 'disablesleep', '0']


def test_the_command_line_is_checked(ns, tmp_path):
    task = make_task(ns, tmp_path)
    ctx = {'control': {'con': False}}
    assert 'unknown action' in task.run(ctx, action='close')['error']
    assert '--power takes' in task.run(ctx, action='disable', power='mains')['error']
    assert '--to takes' in task.run(ctx, action='enable', to='coffee')['error']
