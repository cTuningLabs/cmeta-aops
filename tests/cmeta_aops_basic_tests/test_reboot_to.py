"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The task reboot-to offline: the firmware's load options read from their bytes (a Windows Boot Manager, an ubuntu, a
network start), the boot entries in the boot order, the words of --os, once / always / cancel on a firmware of this
test, the files of efivarfs, the helper's answer, the command that asks Windows for an administrator - and the task's
course: the list, the menu, the question before a restart, one question of Windows (UAC) when --os names the system.
Nothing here reads or changes the firmware of the machine running the tests, and nothing restarts.
"""

import base64
import json
import os
import struct
import subprocess
import sys
import uuid

import pytest

ESP = '1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d'
OTHER_DISK = '99999999-1111-4222-8333-444455556666'


def node(kind, sub, body=b''):
    return struct.pack('<BBH', kind, sub, 4 + len(body)) + body


def hd(number, guid):
    """A hard drive node of a GPT partition: number, start, size, signature, MBR type 2, signature type 2."""
    return node(4, 1, struct.pack('<IQQ', number, 2048, 532480) + uuid.UUID(guid).bytes_le + bytes([2, 2]))


def file(path):
    return node(4, 4, (path + '\0').encode('utf-16-le'))


def option(description, nodes, attributes=1, optional=b''):
    """An EFI_LOAD_OPTION: attributes, the length of the device path, the description, the path, optional data."""
    path = b''.join(nodes) + node(0x7F, 0xFF)
    return struct.pack('<IH', attributes, len(path)) + (description + '\0').encode('utf-16-le') + path + optional


def u16s(*numbers):
    return struct.pack('<%dH' % len(numbers), *numbers)


class FakeFirmware:
    """A firmware of this test: its variables in a dict; keep=False ignores every write."""

    def __init__(self, variables, keep=True, can_read=True, can_write=True):
        self.vars = dict(variables)
        self.writes = []
        self.keep = keep
        self.can_read, self.can_write = can_read, can_write

    def read(self, name):
        return self.vars.get(name)

    def write(self, name, value):
        self.writes.append((name, value))
        if not self.keep:
            return
        if value is None:
            self.vars.pop(name, None)
        else:
            self.vars[name] = value


def machine(order=(0, 1, 0x10), current=0, following=None, **more):
    v = {'BootOrder': u16s(*order), 'BootCurrent': u16s(current),
         'Boot0000': option('Windows Boot Manager', [hd(1, ESP), file('\\EFI\\Microsoft\\Boot\\bootmgfw.efi')],
                            optional=b'WINDOWS\0'),
         'Boot0001': option('ubuntu', [hd(1, ESP), file('\\EFI\\ubuntu\\shimx64.efi')]),
         'Boot0010': option('PXE IPv4 Intel(R) Ethernet', [node(1, 1, b'\x00\x1f'), node(3, 11, bytes(33)),
                                                           node(3, 12, bytes(23))]),
         'Boot0017': option('Linux-Firmware-Updater', [hd(1, ESP), file('\\EFI\\ubuntu\\fwupdx64.efi')])}
    if following is not None:
        v['BootNext'] = u16s(following)
    v.update(more)
    return FakeFirmware(v)


@pytest.fixture
def ns(task_namespace):
    return task_namespace('reboot-to')


@pytest.fixture
def U(ns):
    return ns['UEFI']


###################################################################################################
# The values

def test_load_options_are_read_from_their_bytes(U):
    fw = machine()
    windows = U.load_option(fw.read('Boot0000'))
    assert windows['description'] == 'Windows Boot Manager' and windows['active'] and not windows['hidden']
    assert windows['file'] == '\\EFI\\Microsoft\\Boot\\bootmgfw.efi' and windows['kind'] == 'loader'
    assert windows['partition'] == ESP and windows['partition_number'] == 1 and windows['system'] == 'windows'

    ubuntu = U.load_option(fw.read('Boot0001'))
    assert ubuntu['system'] == 'linux' and ubuntu['file'] == '\\EFI\\ubuntu\\shimx64.efi'

    network = U.load_option(fw.read('Boot0010'))
    assert network['kind'] == 'network' and network['file'] == '' and network['system'] == ''

    # the firmware updater lives in ubuntu's folder and is not a system
    assert U.load_option(fw.read('Boot0017'))['system'] == ''

    hidden = U.load_option(option('x', [file('\\a.efi')], attributes=0x8))
    assert hidden['hidden'] and not hidden['active']

    assert U.load_option(b'') is None and U.load_option(b'\x01\x00') is None


def test_the_system_of_a_loader(U):
    assert U.system_of('\\EFI\\Microsoft\\Boot\\bootmgfw.efi') == 'windows'
    assert U.system_of('\\EFI\\fedora\\shimx64.efi') == 'linux'
    assert U.system_of('/EFI/systemd/systemd-bootx64.efi') == 'linux'
    assert U.system_of('\\EFI\\ubuntu\\mmx64.efi') == ''
    assert U.system_of('\\EFI\\BOOT\\BOOTX64.EFI') == ''
    assert U.system_of('') == ''


def test_boot_entries_follow_the_boot_order(U):
    data = U.boot_entries(machine(order=(1, 0, 0x10), current=0).read)
    assert [e['name'] for e in data['entries']] == ['Boot0001', 'Boot0000', 'Boot0010']
    assert data['order'] == [1, 0, 0x10] and data['current'] == 0 and data['next'] is None
    first, running = data['entries'][0], data['entries'][1]
    assert first['first'] and not first['current'] and running['current'] and not running['first']

    # BootNext and an entry asked for by its number join the list when they are not in the order
    data = U.boot_entries(machine(following=0x17).read)
    updater = data['entries'][-1]
    assert updater['name'] == 'Boot0017' and updater['next'] and not updater['in_order']
    assert [e['name'] for e in U.boot_entries(machine().read, also=0x17)['entries']][-1] == 'Boot0017'


def test_a_laptop_boot_menu_shows_its_one_system(ns, U):
    """The layout of a real laptop's firmware (2026-11-14): the firmware's device entries (VenMsg), its applications (FvFile,
    outside the boot order) and the firmware updater in the boot order - the list shows the one system."""
    vendor = uuid.UUID('bc7838d2-0f82-4d60-8316-c068ee79d25b').bytes_le
    fw = FakeFirmware({
        'BootOrder': u16s(1, 0x17, 0x1E, 0), 'BootCurrent': u16s(1),
        'Boot0001': option('Ubuntu', [hd(1, ESP), file('\\EFI\\ubuntu\\shimx64.efi')]),
        'Boot0017': option('USB CD', [node(3, 10, vendor + bytes(16))]),
        'Boot001E': option('PCI LAN', [node(3, 10, vendor + bytes(16))]),
        'Boot0000': option('Linux-Firmware-Updater', [hd(1, ESP), file('\\EFI\\ubuntu\\fwupdx64.efi')]),
        'Boot0010': option('Setup', [node(4, 6, bytes(16))], attributes=0)})
    entries = U.boot_entries(fw.read)['entries']
    assert [e['name'] for e in entries] == ['Boot0001', 'Boot0017', 'Boot001E', 'Boot0000']
    assert [e['kind'] for e in entries] == ['loader', 'device', 'device', 'loader'] and entries[3]['tool']
    assert [e['name'] for e in ns['shown'](entries)] == ['Boot0001']
    assert len(ns['shown'](entries, every=True)) == 4
    assert U.hint(entries, entries[0]) == 'Ubuntu' and U.load_option(fw.read('Boot0010'))['kind'] == 'firmware'


###################################################################################################
# The choice

def test_the_words_of_os(U):
    entries = U.boot_entries(machine().read, also=0x17)['entries']

    def names(word):
        return [e['name'] for e in U.select(entries, word)]

    assert names('Boot0001') == names('0001') == names('ubuntu') == names('UBUNTU') == names('linux') == ['Boot0001']
    assert names('windows') == names('Windows Boot Manager') == names('win') == ['Boot0000']
    assert names('pxe') == ['Boot0010']
    assert names('boot0099') == [] and names('nothing') == [] and names('') == []


def test_each_entry_has_a_word_that_names_it_alone(U):
    entries = U.boot_entries(machine().read, also=0x17)['entries']
    words = {e['name']: U.hint(entries, e) for e in entries}
    assert words['Boot0000'] == 'windows' and words['Boot0001'] == 'ubuntu'
    for e in entries:
        assert [h['name'] for h in U.select(entries, words[e['name']].strip('"'))] == [e['name']]


def test_two_systems_of_one_name_are_told_apart_by_their_entry(U):
    fw = machine(order=(0, 1, 2), Boot0002=option('ubuntu', [hd(2, OTHER_DISK), file('\\EFI\\ubuntu\\shimx64.efi')]))
    entries = U.boot_entries(fw.read)['entries']
    hits = U.select(entries, 'ubuntu')
    assert [h['name'] for h in hits] == ['Boot0001', 'Boot0002']
    assert U.hint(entries, entries[1]) == 'Boot0001' and U.hint(entries, entries[0]) == 'windows'
    text = U.not_one('ubuntu', hits)
    assert 'Boot0001 (ubuntu)' in text and 'Boot0002 (ubuntu)' in text and '--os=Boot0002' in text
    assert U.not_one('nothing', []) == 'no boot entry matches "nothing"'


def test_two_entries_of_the_same_loader_are_one_system(ns, U):
    """A dual-boot laptop (2026-11-14): two Windows Boot Manager entries, the same bootmgfw.efi on the same partition - --os=windows
    takes the first in the boot order, the other keeps its BootXXXX."""
    fw = machine(order=(2, 1, 0), Boot0002=option('Windows Boot Manager',
                                                  [hd(1, ESP), file('\\EFI\\Microsoft\\Boot\\bootmgfw.efi')]))
    entries = U.boot_entries(fw.read)['entries']
    assert [e['name'] for e in U.select(entries, 'windows')] == ['Boot0002']
    assert [e['name'] for e in U.select(entries, 'Boot0000')] == ['Boot0000']
    words = {e['name']: U.hint(entries, e) for e in entries}
    assert words == {'Boot0002': 'windows', 'Boot0001': 'ubuntu', 'Boot0000': 'Boot0000'}
    assert U.apply(fw, 'once', 'windows')['entry']['name'] == 'Boot0002'


def test_the_lines_under_the_list(ns, U):
    data = U.boot_entries(machine(order=(0, 1), current=0).read)
    assert ns['summary'](data, True) == [
        'Next restart: Windows Boot Manager (Boot0000), the first in the boot order (no "once" is set).']

    # a once into ubuntu that GRUB turned into Windows: the firmware booted ubuntu's entry, Windows runs
    data = U.boot_entries(machine(order=(0, 1), current=1, following=1).read)
    lines = ns['summary'](data, True)
    assert lines[0] == 'Next restart: ubuntu (Boot0001), once - then the boot order again (Windows Boot Manager (Boot0000) first).'
    assert 'This Windows was booted through ubuntu (Boot0001): its GRUB started Windows' in lines[1]
    assert len(ns['summary'](data, False)) == 1


def test_once_sets_boot_next(U):
    fw = machine()
    r = U.apply(fw, 'once', 'ubuntu')
    assert r['return'] == 0 and r['entry']['name'] == 'Boot0001'
    assert fw.writes == [('BootNext', b'\x01\x00')] and r['after']['next'] == 1 and r['before']['next'] is None


def test_always_puts_the_entry_first_and_takes_back_another_once(U):
    fw = machine(order=(0, 1, 0x10), following=0x17)
    r = U.apply(fw, 'always', 'ubuntu')
    assert r['return'] == 0
    assert fw.writes == [('BootOrder', u16s(1, 0, 0x10)), ('BootNext', None)]
    assert r['after']['order'] == [1, 0, 0x10] and r['after']['next'] is None

    # a once to the same entry stays
    fw = machine(following=1)
    assert U.apply(fw, 'always', 'Boot0001')['return'] == 0 and fw.writes == [('BootOrder', u16s(1, 0, 0x10))]


def test_cancel_removes_boot_next(U):
    fw = machine(following=1)
    r = U.apply(fw, 'cancel')
    assert r['return'] == 0 and fw.writes == [('BootNext', None)] and r['after']['next'] is None
    fw = machine()
    assert U.apply(fw, 'cancel')['return'] == 0 and fw.writes == []


def test_a_word_for_no_entry_or_several_changes_nothing(U):
    fw = machine()
    r = U.apply(fw, 'once', 'nothing')
    assert r['return'] == 1 and 'no boot entry matches' in r['error'] and fw.writes == []
    fw = machine(order=(0, 1, 2), Boot0002=option('ubuntu', [hd(2, OTHER_DISK), file('\\EFI\\ubuntu\\grubx64.efi')]))
    assert U.apply(fw, 'always', 'ubuntu')['return'] == 1 and fw.writes == []


def test_a_change_the_firmware_does_not_keep_is_an_error(U):
    fw = machine()
    fw.keep = False
    r = U.apply(fw, 'once', 'ubuntu')
    assert r['return'] == 1 and 'did not keep' in r['error'] and 'BootNext is none' in r['error']


###################################################################################################
# The firmware's variables

def test_efivarfs_files(U, tmp_path):
    fw = U.LinuxFirmware(str(tmp_path))
    fw.write('BootNext', b'\x01\x00')
    path = tmp_path / ('BootNext-' + U.EFI_GLOBAL)
    assert path.read_bytes() == b'\x07\x00\x00\x00\x01\x00'
    assert fw.read('BootNext') == b'\x01\x00'
    fw.write('BootNext', None)
    assert not path.exists() and fw.read('BootNext') is None
    fw.write('BootNext', None)


def test_efivarfs_errors_are_explained(U):
    import errno
    e = OSError(errno.EACCES, 'Permission denied')
    assert U.linux_error('BootNext', '/x/BootNext-g', e, False) == 'changing BootNext needs root'
    assert 'immutable' in U.linux_error('BootNext', '/x/BootNext-g', OSError(errno.EPERM, 'x'), True)
    assert 'read-only' in U.linux_error('BootOrder', '/x/BootOrder-g', OSError(errno.EROFS, 'x'), True)


def test_a_machine_without_uefi_says_so(U, tmp_path):
    with pytest.raises(RuntimeError, match='did not start through UEFI'):
        U.firmware('linux', efi=str(tmp_path / 'none'))
    (tmp_path / 'efi' / 'efivars').mkdir(parents=True)
    with pytest.raises(RuntimeError, match='efivarfs is not mounted'):
        U.firmware('linux', efi=str(tmp_path / 'efi'))
    (tmp_path / 'efi' / 'efivars' / ('BootOrder-' + U.EFI_GLOBAL)).write_bytes(b'\x07\0\0\0\0\0')
    assert U.firmware('linux', efi=str(tmp_path / 'efi')).root == str(tmp_path / 'efi' / 'efivars')
    with pytest.raises(RuntimeError, match='macOS'):
        U.firmware('darwin')


def test_the_helper_answers_in_json(U, tmp_path, capsys):
    assert U.main(['-', 'read'], fw=machine()) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer['return'] == 0 and [e['name'] for e in answer['entries']][:2] == ['Boot0000', 'Boot0001']

    fw = machine()
    target = tmp_path / 'answer.json'
    assert U.main([str(target), 'once', 'ubuntu'], fw=fw) == 0
    assert json.loads(target.read_text(encoding='utf-8'))['entry']['name'] == 'Boot0001' and fw.vars['BootNext'] == b'\x01\x00'

    assert U.main(['-', 'once', 'nothing'], fw=machine()) == 1
    assert 'no boot entry matches' in json.loads(capsys.readouterr().out)['error']
    assert U.main(['-', 'reboot']) == 2


def test_the_helper_writes_into_the_empty_file_made_for_it(U, tmp_path, capsys):
    """Windows: the task makes the answer file and the administrator's helper writes into it, so the file stays the
    user's (2026-11-14: a file the elevated helper made was out of the unelevated console's reach). A file with
    content or another link is never written."""
    made = tmp_path / 'answer.json'
    made.write_bytes(b'')
    assert U.main([str(made), 'read'], fw=machine()) == 0
    assert json.loads(made.read_text(encoding='utf-8'))['return'] == 0

    assert U.main([str(made), 'read'], fw=machine()) == 1
    assert 'not the empty file of an answer' in capsys.readouterr().err
    assert json.loads(made.read_text(encoding='utf-8'))['return'] == 0

    other = tmp_path / 'other.txt'
    other.write_bytes(b'')
    link = tmp_path / 'linked.json'
    try:
        os.link(str(other), str(link))
    except OSError:
        pytest.skip('no hard links here')
    assert U.main([str(link), 'read'], fw=machine()) == 1 and other.read_bytes() == b''


###################################################################################################
# The task

class StubCM:
    def __init__(self):
        self.calls = []

    def error(self, text):
        return {'return': 1, 'error': text}

    def access(self, request):
        if request.get('category') == 'config':
            return {'return': 16, 'error': 'config "%s" not found' % request.get('arg1')}     # no task-reboot-to here
        self.calls.append(request)
        return {'return': 0, 'command': ['shutdown.exe', '/r', '/t', str(request['delay_seconds'])],
                'delay_seconds': request['delay_seconds'], 'scheduled': not request['dry_run']}


class Stdin:
    def __init__(self, terminal):
        self.terminal = terminal

    def isatty(self):
        return self.terminal


def make_task(ns, monkeypatch, fw, answers=None):
    """The task with a firmware of this test, and the answers typed in a terminal (None: no terminal)."""
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM()
    task.cmeta = {'uses_categories': {'task': 'task,c36be4b9314a45e0'}}
    monkeypatch.setattr(ns['UEFI'], 'firmware', lambda: fw)
    monkeypatch.setattr(sys, 'stdin', Stdin(answers is not None))
    typed = iter(answers or [])
    monkeypatch.setitem(ns, 'ask', lambda question, how='': {'return': 0, 'answer': next(typed)})
    return task


def run(task, **params):
    return task.run({'control': {'con': True, 'quiet': False}}, **params)


def test_no_system_named_and_nobody_to_ask(ns, monkeypatch, capsys):
    fw = machine()
    r = run(make_task(ns, monkeypatch, fw))
    assert r['return'] == 1 and '--os=' in r['error'] and fw.writes == []
    out = capsys.readouterr().out
    assert '--os=windows' in out and '--os=ubuntu' in out and 'PXE' not in out


def test_a_restart_without_a_terminal_needs_yes(ns, monkeypatch):
    fw = machine()
    task = make_task(ns, monkeypatch, fw)
    r = run(task, os='ubuntu')
    assert r['return'] == 1 and '--yes' in r['error'] and fw.writes == [] and task.cm.calls == []

    r = run(task, os='ubuntu', reboot=False)
    assert r['return'] == 0 and fw.vars['BootNext'] == b'\x01\x00' and not r['restarting'] and task.cm.calls == []


def test_yes_sets_the_next_start_and_restarts(ns, monkeypatch):
    fw = machine()
    task = make_task(ns, monkeypatch, fw)
    r = run(task, os='ubuntu', yes=True, delay_seconds='5')
    assert r['return'] == 0 and r['restarting'] and fw.writes == [('BootNext', b'\x01\x00')]
    call = task.cm.calls[-1]
    assert call['arg1'] == ns['REBOOT_TASK'] and call['yes'] is True and call['dry_run'] is False
    assert call['delay_seconds'] == 5


def test_the_menu_then_the_question(ns, monkeypatch, capsys):
    fw = machine()
    task = make_task(ns, monkeypatch, fw, answers=['1', 'y'])
    r = run(task)
    assert r['return'] == 0 and r['entry']['name'] == 'Boot0001' and fw.writes == [('BootNext', b'\x01\x00')]
    assert task.cm.calls and '0)' in capsys.readouterr().out

    fw = machine()
    task = make_task(ns, monkeypatch, fw, answers=[''])
    assert run(task)['return'] == 0 and fw.writes == [] and task.cm.calls == []

    fw = machine()
    task = make_task(ns, monkeypatch, fw, answers=['1', 'n'])
    r = run(task)
    assert r['return'] == 0 and r.get('cancelled') and fw.writes == [] and task.cm.calls == []

    fw = machine()
    assert run(make_task(ns, monkeypatch, fw, answers=['7']))['return'] == 1 and fw.writes == []


def test_several_matches_are_offered_as_a_menu(ns, monkeypatch):
    fw = machine(order=(0, 1, 2), Boot0002=option('ubuntu', [hd(2, OTHER_DISK), file('\\EFI\\ubuntu\\shimx64.efi')]))
    task = make_task(ns, monkeypatch, fw, answers=['1', 'y'])
    r = run(task, os='ubuntu')
    assert r['return'] == 0 and fw.writes == [('BootNext', b'\x02\x00')]

    fw = machine(order=(0, 1, 2), Boot0002=option('ubuntu', [hd(2, OTHER_DISK), file('\\EFI\\ubuntu\\shimx64.efi')]))
    r = run(make_task(ns, monkeypatch, fw), os='ubuntu', yes=True)
    assert r['return'] == 1 and '--os=Boot0002' in r['error'] and fw.writes == []


def test_list_dry_run_always_cancel(ns, monkeypatch, capsys):
    fw = machine()
    task = make_task(ns, monkeypatch, fw)
    r = run(task, list=True)
    assert r['return'] == 0 and len(r['entries']) == 3 and fw.writes == []
    assert 'PXE' in (run(task, list=True, all=True) and capsys.readouterr().out)

    r = run(task, os='ubuntu', dry_run=True)
    assert r['return'] == 0 and r['dry_run'] and fw.writes == [] and task.cm.calls[-1]['dry_run'] is True
    assert 'Would set BootNext = Boot0001' in capsys.readouterr().out

    r = run(task, os='ubuntu', always=True, yes=True)
    assert r['return'] == 0 and fw.writes == [('BootOrder', u16s(1, 0, 0x10))] and r['order'] == [1, 0, 0x10]

    fw = machine(following=1)
    r = run(make_task(ns, monkeypatch, fw), cancel=True)
    assert r['return'] == 0 and fw.writes == [('BootNext', None)] and r['next'] is None
    assert 'taken back' in capsys.readouterr().out


def test_words_checked_before_anything(ns, monkeypatch):
    fw = machine()
    task = make_task(ns, monkeypatch, fw)
    assert run(task, os='ubuntu', yes=True, delay_seconds='5000')['return'] == 1
    assert run(task, os='ubuntu', cancel=True)['return'] == 1
    assert fw.writes == [] and task.cm.calls == []

    empty = FakeFirmware({})
    r = run(make_task(ns, monkeypatch, empty, answers=['0']))
    assert r['return'] == 1 and 'no boot entries' in r['error'] and empty.writes == []


def test_windows_without_an_administrator_asks_windows_once_when_os_names_the_system(ns, monkeypatch):
    fw = machine()
    fw.can_read = fw.can_write = False
    task = make_task(ns, monkeypatch, fw)
    helped = []

    def helper(words):
        helped.append(words)
        return ns['UEFI'].apply(fw, words[0], words[1] if len(words) > 1 else '') if words[0] != 'read' else \
            dict(ns['UEFI'].boot_entries(fw.read), **{'return': 0})

    task._helper = helper
    r = run(task, os='ubuntu', yes=True)
    assert r['return'] == 0 and helped == [['once', 'ubuntu']] and fw.vars['BootNext'] == b'\x01\x00'

    # the list, then the menu's choice: the helper reads, then changes
    helped.clear()
    task = make_task(ns, monkeypatch, fw, answers=['0', 'y'])
    task._helper = helper
    assert run(task)['return'] == 0 and helped == [['read'], ['once', 'Boot0000']]


def test_linux_reads_as_the_user_and_changes_through_the_helper(ns, monkeypatch):
    fw = machine()
    fw.can_write = False
    task = make_task(ns, monkeypatch, fw)
    helped = []
    task._helper = lambda words: helped.append(words) or ns['UEFI'].apply(fw, *words)
    assert run(task, os='ubuntu', reboot=False)['return'] == 0 and helped == [['once', 'Boot0001']]


###################################################################################################
# The helper's rights

def test_the_command_that_asks_windows_for_an_administrator(ns):
    encoded = ns['elevated_command']("C:\\Py thon\\it's\\python.exe", ['-I', 'D:\\a b\\uefi_boot.py', 'C:\\t\\a.json', 'once', 'ubuntu'])
    script = base64.b64decode(encoded).decode('utf-16-le')
    assert "-FilePath 'C:\\Py thon\\it''s\\python.exe'" in script
    assert "-ArgumentList '-I \"D:\\a b\\uefi_boot.py\" C:\\t\\a.json once ubuntu'" in script
    assert '-Verb RunAs -Wait -PassThru -WindowStyle Hidden' in script and script.endswith('exit $p.ExitCode')


def test_the_answer_of_the_helper(ns):
    assert ns['answer_of'](b'noise\n{"return": 0, "x": 1}\n') == {'return': 0, 'x': 1}
    r = ns['answer_of'](b'', 'sudo: a password is required')
    assert r['return'] == 1 and r['error'].endswith('sudo: a password is required')
    assert ns['answer_of'](b'[1]')['return'] == 1


def test_sudo_without_a_question_then_in_the_terminal(ns, monkeypatch):
    task = ns['CTask'].__new__(ns['CTask'])
    task.con, task.terminal = False, False
    monkeypatch.setattr(ns['shutil'], 'which', lambda name: '/usr/bin/sudo')
    calls = []

    def fake_run(words, **kw):
        calls.append(words)
        if words[1] == '-n':
            return subprocess.CompletedProcess(words, 1, b'', b'sudo: a password is required\n')
        return subprocess.CompletedProcess(words, 0, b'{"return": 0, "done": true}\n', None)

    monkeypatch.setattr(ns['subprocess'], 'run', fake_run)
    r = task._helper_sudo('/usr/bin/python3', ['once', 'ubuntu'])
    assert r['return'] == 1 and 'password is required' in r['error']
    assert calls == [['sudo', '-n', '/usr/bin/python3', '-I', ns['HELPER'], '-', 'once', 'ubuntu']]

    task.terminal = True
    assert task._helper_sudo('/usr/bin/python3', ['once', 'ubuntu']) == {'return': 0, 'done': True}
    assert calls[-1] == ['sudo', '/usr/bin/python3', '-I', ns['HELPER'], '-', 'once', 'ubuntu']


def test_the_administrator_helper_answers_in_the_file_the_task_made(ns, monkeypatch, tmp_path):
    task = ns['CTask'].__new__(ns['CTask'])
    task.con = False
    folder = tmp_path / 'answer-folder'
    monkeypatch.setattr(ns['tempfile'], 'mkdtemp', lambda prefix='': (folder.mkdir(), str(folder))[1])
    made = []

    def declined(words, **kw):
        made.append((folder / 'answer.json').read_bytes())
        return subprocess.CompletedProcess(words, 1, b'The operation was canceled by the user.', None)

    monkeypatch.setattr(ns['subprocess'], 'run', declined)
    r = task._helper_windows('python.exe', ['read'])
    assert r['return'] == 1 and 'declined (UAC)?' in r['error'] and 'canceled by the user' in r['error']
    assert made == [b''] and not folder.exists()

    def approved(words, **kw):
        # the helper as the administrator would run it: into the empty file the task made
        assert ns['UEFI'].main([str(folder / 'answer.json'), 'read'], fw=machine()) == 0
        return subprocess.CompletedProcess(words, 0, b'', None)

    monkeypatch.setattr(ns['subprocess'], 'run', approved)
    r = task._helper_windows('python.exe', ['read'])
    assert r['return'] == 0 and r['entries'][0]['name'] == 'Boot0000' and not folder.exists()

    def unreadable(words, **kw):
        os.remove(str(folder / 'answer.json'))
        (folder / 'answer.json').mkdir()
        return subprocess.CompletedProcess(words, 0, b'', None)

    monkeypatch.setattr(ns['subprocess'], 'run', unreadable)
    r = task._helper_windows('python.exe', ['read'])
    assert r['return'] == 1 and 'could not be read' in r['error'] and not folder.exists()


###################################################################################################
# --grub (--via=grub): GRUB's menu, its next_entry and saved default (a dual-boot laptop's Linux, 2026-11-14)

GRUB_CFG = """if [ "${next_entry}" ] ; then
   set default="${next_entry}"
else
   set default="0"
fi
menuentry 'Ubuntu' --class ubuntu --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-simple-8bd9' {
	linux	/boot/vmlinuz-7.0.0-43-generic root=UUID=8bd9 ro quiet splash
}
submenu 'Advanced options for Ubuntu' $menuentry_id_option 'gnulinux-advanced-8bd9' {
	menuentry 'Ubuntu, with Linux 7.0.0-43-generic' --class ubuntu --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-7.0.0-43-generic-advanced-8bd9' {
		linux	/boot/vmlinuz-7.0.0-43-generic root=UUID=8bd9 ro quiet splash
	}
}
if [ "$grub_platform" = "efi" ]; then
	menuentry "Memory test (mt86+x64)" --class memtest $menuentry_id_option "memtest86+" {
		linux	/boot/mt86+x64.efi
	}
fi
menuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows --class os $menuentry_id_option 'osprober-efi-A070-BC84' {
	chainloader /efi/Microsoft/Boot/bootmgfw.efi
}
fwsetup --is-supported
if [ "$?" = 0 ]; then
		menuentry 'UEFI Firmware Settings' $menuentry_id_option 'uefi-firmware' {
			fwsetup
		}
fi
"""


@pytest.fixture
def G(ns):
    return ns['GRUB']


def test_grub_menu_is_read_with_its_ids_and_submenus(G):
    entries = G.menu(GRUB_CFG)
    assert [(e['title'], e['id'], e['system'], e['submenu']) for e in entries] == [
        ('Ubuntu', 'gnulinux-simple-8bd9', 'linux', ''),
        ('Ubuntu, with Linux 7.0.0-43-generic', 'gnulinux-7.0.0-43-generic-advanced-8bd9', 'linux',
         'Advanced options for Ubuntu'),
        ('Memory test (mt86+x64)', 'memtest86+', '', ''),
        ('Windows Boot Manager (on /dev/nvme0n1p1)', 'osprober-efi-A070-BC84', 'windows', ''),
        ('UEFI Firmware Settings', 'uefi-firmware', '', '')]
    assert [e['title'] for e in G.shown(entries)] == ['Ubuntu', 'Windows Boot Manager (on /dev/nvme0n1p1)']
    assert len(G.shown(entries, every = True)) == 5


def test_grub_words_and_references(G):
    entries = G.menu(GRUB_CFG)
    pick = lambda word: [e['id'] for e in G.select(entries, word)]
    assert pick('windows') == pick('Windows') == pick('osprober-efi-A070-BC84') == ['osprober-efi-A070-BC84']
    # the top-level Ubuntu before its advanced kernels
    assert pick('ubuntu') == ['gnulinux-simple-8bd9'] and pick('linux')[0] == 'gnulinux-simple-8bd9'
    assert pick('7.0.0-43') == ['gnulinux-7.0.0-43-generic-advanced-8bd9'] and pick('nothing') == []
    assert G.entry_ref(entries[3]) == 'osprober-efi-A070-BC84'
    assert G.entry_ref(dict(entries[1], id = '')) == 'Advanced options for Ubuntu>Ubuntu, with Linux 7.0.0-43-generic'
    assert G.named(entries, 'osprober-efi-A070-BC84')['system'] == 'windows'
    assert G.named(entries, 'Advanced options for Ubuntu>Ubuntu, with Linux 7.0.0-43-generic')['submenu']
    assert G.named(entries, '0')['title'] == 'Ubuntu' and G.named(entries, '') is None


def test_grub_environment_and_defaults(G):
    envblock = ('# GRUB Environment Block\n# WARNING: Do not edit this file by tools other than grub-editenv!!!\n'
                'saved_entry=gnulinux-simple-8bd9\nnext_entry=osprober-efi-A070-BC84\n' + '#' * 600)
    assert G.env(envblock) == {'saved_entry': 'gnulinux-simple-8bd9', 'next_entry': 'osprober-efi-A070-BC84'}
    defaults = 'GRUB_DEFAULT=0\nGRUB_TIMEOUT_STYLE=hidden\nGRUB_TIMEOUT=3\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
    assert G.grub_default(defaults) == '0' and G.grub_default('GRUB_DEFAULT="saved"\n') == 'saved'
    assert G.grub_default('') == '0' and G.setting(defaults, 'GRUB_TIMEOUT_STYLE') == 'hidden'
    text, changed = G.set_keys(defaults, {'GRUB_DEFAULT': 'saved', 'GRUB_TIMEOUT_STYLE': 'menu', 'GRUB_TIMEOUT': '5'})
    assert changed and text == ('GRUB_DEFAULT=saved\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=5\n'
                                'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
    assert G.set_keys(text, {'GRUB_DEFAULT': 'saved'}) == (text, False)
    # a missing key is added, a second line that sets it commented out
    text, _ = G.set_keys('GRUB_TIMEOUT=3\nGRUB_TIMEOUT=10\n', {'GRUB_TIMEOUT': '5', 'GRUB_DEFAULT': 'saved'})
    assert text.splitlines() == ['GRUB_TIMEOUT=5', '# GRUB_TIMEOUT=10   # cmeta reboot-to: set above', 'GRUB_DEFAULT=saved']


def test_grub_words_checked_and_windows_refused(ns, monkeypatch):
    task = make_task(ns, monkeypatch, machine())
    assert run(task, os='windows', grub=True, grub_timeout='abc')['return'] == 1
    assert run(task, os='windows', via='bios')['return'] == 1
    monkeypatch.setattr(task, '_configured_via', lambda: 'firmware')
    r = run(task, os='ubuntu', grub_timeout='5', reboot=False)
    assert r['return'] == 1 and '--via=grub' in r['error']
    monkeypatch.setattr(ns['sys'], 'platform', 'win32')
    r = run(task, os='windows', grub=True, reboot=False)
    assert r['return'] == 1 and 'Linux side' in r['error']
