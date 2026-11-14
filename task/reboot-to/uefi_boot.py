"""
The boot entries of a UEFI firmware - BootOrder, BootNext, BootCurrent and the Boot#### load options - read, chosen
and changed with the standard library only, for the task reboot-to (api_v1.py):

  Linux    efivarfs: /sys/firmware/efi/efivars/<name>-<vendor GUID>, 4 bytes of attributes, then the value.
           Everyone reads; root writes.
  Windows  GetFirmwareEnvironmentVariableExW / SetFirmwareEnvironmentVariableExW of kernel32, in a process with the
           privilege SeSystemEnvironmentPrivilege enabled - an elevated administrator's, for reading as for writing.

Run on its own, this file is the helper the task starts as root (sudo) or as an administrator (Windows asks: UAC) -
the only part of the task that runs with those rights. It writes one JSON answer: to "-" (the standard output, sudo),
into the empty file the task made for it (Windows: so the file stays the user's), or to a new file:

  python -I uefi_boot.py <answer> read [<entry>]          the entries (<entry>: BootXXXX outside the boot order too)
  python -I uefi_boot.py <answer> once|always <entry>     BootNext, or BootOrder with the entry first
  python -I uefi_boot.py <answer> cancel                  BootNext removed

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import errno
import json
import os
import stat
import struct
import sys
import uuid

EFI_GLOBAL = '8be4df61-93ca-11d2-aa0d-00e098032b8c'      # the vendor GUID of BootOrder, BootNext, Boot####
EFIVARS = '/sys/firmware/efi/efivars'
NV_BS_RT = 7                                               # non-volatile, boot-service and runtime access
ACTIVE = 0x1                                               # LOAD_OPTION_ACTIVE
HIDDEN = 0x8                                               # LOAD_OPTION_HIDDEN
ACTIONS = ('read', 'once', 'always', 'cancel')

# A loader's folder on the EFI system partition (\EFI\<folder>\...) or its file name tells the system it starts
LINUX_FOLDERS = {'ubuntu', 'debian', 'fedora', 'redhat', 'centos', 'rocky', 'almalinux', 'opensuse', 'sles', 'arch',
                 'manjaro', 'pop', 'linuxmint', 'kali', 'gentoo', 'nixos', 'systemd', 'neon', 'elementary', 'zorin'}
LINUX_LOADERS = ('shim', 'grub', 'systemd-boot', 'vmlinuz', 'linux')

# ... except the tools a distribution keeps there: the firmware updater, the MOK manager
TOOLS = ('fwupd', 'mmx64', 'mmaa64', 'mmia32')


###################################################################################################
# The values

def u16(data):
    """A UINT16 value (BootCurrent, BootNext), or None."""
    return struct.unpack_from('<H', data)[0] if data and len(data) >= 2 else None


def u16_list(data):
    """An array of UINT16 (BootOrder)."""
    data = data or b''
    count = len(data) // 2
    return list(struct.unpack('<%dH' % count, data[:count * 2]))


def device_path(data):
    """The nodes (type, subtype, body) of the first device path in data, up to its end node."""
    nodes, i = [], 0
    while i + 4 <= len(data):
        kind, sub = data[i], data[i + 1]
        size = struct.unpack_from('<H', data, i + 2)[0]
        if kind == 0x7F or size < 4 or i + size > len(data):
            break
        nodes.append((kind, sub, data[i + 4:i + size]))
        i += size
    return nodes


def is_tool(path):
    """A loader that starts no system: the firmware updater, the MOK manager."""
    parts = [p for p in path.lower().replace('/', '\\').split('\\') if p]
    return bool(parts) and parts[-1].startswith(TOOLS)


def system_of(path):
    """windows, linux or '' (a tool, a fallback loader, unknown) from a loader's path on the EFI system partition."""
    parts = [p for p in path.lower().replace('/', '\\').split('\\') if p]
    name = parts[-1] if parts else ''
    folder = parts[1] if len(parts) >= 3 and parts[0] == 'efi' else ''

    if is_tool(path):
        return ''
    if folder == 'microsoft' or name == 'bootmgfw.efi':
        return 'windows'
    if folder in LINUX_FOLDERS or name.startswith(LINUX_LOADERS):
        return 'linux'
    return ''


def load_option(data):
    """A Boot#### value (EFI_LOAD_OPTION) as a dict, or None when it is too short to be one. kind: loader (a file on
    a disk's partition: a system), network, firmware (an application of the firmware), legacy (BIOS) or device."""
    if not data or len(data) < 8:
        return None
    attributes, size = struct.unpack_from('<IH', data)

    # the description: UCS-2 characters up to a zero one
    end = 6
    while end + 1 < len(data) and data[end:end + 2] != b'\0\0':
        end += 2

    entry = {'description': data[6:end].decode('utf-16-le', 'replace'), 'active': bool(attributes & ACTIVE),
             'hidden': bool(attributes & HIDDEN), 'file': '', 'partition': '', 'partition_number': 0}
    found = set()

    for kind, sub, body in device_path(data[end + 2:end + 2 + size]):
        if kind == 4 and sub == 1 and len(body) >= 38:
            # a hard drive's partition: its number, and its GUID on a GPT disk
            entry['partition_number'] = struct.unpack_from('<I', body)[0]
            if body[37] == 2:
                entry['partition'] = str(uuid.UUID(bytes_le=bytes(body[20:36])))
        elif kind == 4 and sub == 4:
            # a file on it (two nodes are one path)
            part = body.decode('utf-16-le', 'replace').split('\0')[0]
            entry['file'] = entry['file'].rstrip('\\') + '\\' + part.lstrip('\\') if entry['file'] else part
        elif kind == 4 and sub in (6, 7):
            found.add('firmware')
        elif kind == 3 and sub in (11, 12, 13, 24):
            found.add('network')                           # MAC, IPv4, IPv6, URI
        elif kind == 5:
            found.add('legacy')

    entry['kind'] = 'loader' if entry['file'] else next((k for k in ('network', 'firmware', 'legacy') if k in found),
                                                        'device')
    entry['system'] = system_of(entry['file'])
    entry['tool'] = is_tool(entry['file'])
    return entry


def boot_entries(read, also=None):
    """The boot entries from read(name) -> the value of a variable of the global vendor GUID (bytes) or None:
    {'order', 'current', 'next', 'entries'} - the entries of BootOrder in its order, then BootCurrent, BootNext and
    "also" (an entry number) when they are not in it."""
    order = u16_list(read('BootOrder'))
    current, following = u16(read('BootCurrent')), u16(read('BootNext'))

    numbers = []
    for n in order + [current, following, also]:
        if n is not None and n not in numbers:
            numbers.append(n)

    entries = []
    for n in numbers:
        entry = load_option(read('Boot%04X' % n))
        if entry is None:
            continue
        entry.update({'number': n, 'name': 'Boot%04X' % n, 'current': n == current, 'next': n == following,
                      'first': bool(order) and order[0] == n, 'in_order': n in order})
        entries.append(entry)

    return {'order': order, 'current': current, 'next': following, 'entries': entries}


###################################################################################################
# The choice

def number_of(selector):
    """The entry number a word names (Boot0001, or its four hex digits 0001), or None."""
    low = str(selector or '').strip().lower()
    digits = low[4:] if low.startswith('boot') else low
    if len(digits) == 4 and all(c in '0123456789abcdef' for c in digits):
        return int(digits, 16)
    return None


def same_loader(hits):
    """Several entries that start the same loader file on the same partition: one system, entered twice (Windows
    makes a new entry after a firmware update or a repair and the old one stays)."""
    keys = {(h['file'].lower(), h['partition'], h['partition_number']) for h in hits}
    return len(keys) == 1 and bool(hits[0]['file'])


def select(entries, selector):
    """The entries a word of --os names, by the first rule that finds any: BootXXXX (or its four hex digits), the
    description itself, windows / linux, part of the description - ignoring case. One entry, several, or none;
    entries of the same loader count as one, the first in the boot order."""
    low = str(selector or '').strip().lower()
    if not low:
        return []

    number = number_of(low)
    if number is not None:
        hits = [e for e in entries if e['number'] == number]
        if hits or low.startswith('boot'):
            return hits

    rules = (lambda e: e['description'].lower() == low,
             lambda e: e['system'] == low,
             lambda e: low in e['description'].lower())
    for rule in rules:
        hits = [e for e in entries if rule(e)]
        if len(hits) > 1 and same_loader(hits):
            return hits[:1]
        if hits:
            return hits
    return []


def hint(entries, entry):
    """The word of --os that names this entry alone: its one-word description, its system, its quoted
    description, or its BootXXXX."""
    description = entry['description']
    words = []
    if description and ' ' not in description:
        words.append(description)
    if entry['system']:
        words.append(entry['system'])
    if description and ' ' in description:
        words.append('"%s"' % description)

    for word in words:
        hits = select(entries, word.strip('"'))
        if len(hits) == 1 and hits[0]['number'] == entry['number']:
            return word
    return entry['name']


def not_one(selector, hits):
    """Why a word of --os names no entry, or several."""
    if not hits:
        return 'no boot entry matches "%s"' % selector
    named = ', '.join('%s (%s)' % (h['name'], h['description']) for h in hits)
    return '"%s" matches %d boot entries: %s - name one by its entry, --os=%s' % (selector, len(hits), named,
                                                                                    hits[-1]['name'])


def apply(fw, action, selector=''):
    """once: BootNext = the entry. always: BootOrder with the entry first - and a BootNext to another entry removed,
    or that one would start next. cancel: BootNext removed. Then the variables are read again, to check.
    fw: read(name) -> bytes or None, write(name, bytes, or None to remove). A dict: before, after, entry."""
    before = boot_entries(fw.read, also=number_of(selector))

    if action == 'cancel':
        if before['next'] is not None:
            fw.write('BootNext', None)
        after = boot_entries(fw.read)
        if after['next'] is not None:
            return {'return': 1, 'error': 'BootNext is still set after its removal', 'before': before, 'after': after}
        return {'return': 0, 'action': action, 'before': before, 'after': after}

    hits = select(before['entries'], selector)
    if len(hits) != 1:
        return {'return': 1, 'error': not_one(selector, hits), 'before': before}
    entry = hits[0]
    number = entry['number']

    if action == 'once':
        fw.write('BootNext', struct.pack('<H', number))
    else:
        order = [number] + [n for n in before['order'] if n != number]
        fw.write('BootOrder', struct.pack('<%dH' % len(order), *order))
        if before['next'] not in (None, number):
            fw.write('BootNext', None)

    after = boot_entries(fw.read, also=number)
    if action == 'once':
        kept = after['next'] == number
    else:
        kept = after['order'][:1] == [number] and after['next'] in (None, number)
    if not kept:
        return {'return': 1, 'before': before, 'after': after,
                'error': 'the firmware did not keep the change: read again, BootNext is %s and BootOrder %s' % (
                    'none' if after['next'] is None else 'Boot%04X' % after['next'],
                    ','.join('%04X' % n for n in after['order']) or 'empty')}

    return {'return': 0, 'action': action, 'entry': entry, 'before': before, 'after': after}


###################################################################################################
# The firmware's variables

class LinuxFirmware:
    """efivarfs: everyone reads (the kernel limits how often a user may), root writes - a variable whole, in one
    write of its attributes and its value."""

    def __init__(self, root=EFIVARS):
        self.root = root
        self.can_read = True
        self.can_write = hasattr(os, 'geteuid') and os.geteuid() == 0

    def path(self, name):
        return os.path.join(self.root, '%s-%s' % (name, EFI_GLOBAL))

    def read(self, name):
        try:
            with open(self.path(name), 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return None
        return data[4:]

    def write(self, name, value):
        path = self.path(name)
        try:
            if value is None:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                return
            data = struct.pack('<I', NV_BS_RT) + value
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)
            try:
                if os.write(fd, data) != len(data):
                    raise OSError(errno.EIO, 'a short write')
            finally:
                os.close(fd)
        except OSError as e:
            raise RuntimeError(linux_error(name, path, e, self.can_write))


def linux_error(name, path, e, root):
    """What a failed write of efivarfs means."""
    if e.errno in (errno.EACCES, errno.EPERM) and not root:
        return 'changing %s needs root' % name
    if e.errno == errno.EPERM:
        return 'the kernel keeps %s immutable (sudo chattr -i %s)' % (name, path)
    if e.errno == errno.EROFS:
        return 'efivarfs is mounted read-only (sudo mount -o remount,rw %s)' % os.path.dirname(path)
    if e.errno == errno.ENOSPC:
        return 'the firmware has no room left for %s (its variable store is full)' % name
    return 'writing %s: %s' % (name, e.strerror or e)


class WindowsFirmware:
    """kernel32's firmware variables. Windows lets a process read or change them only with the privilege
    SeSystemEnvironmentPrivilege enabled; an elevated administrator's token holds it, any other does not."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetFirmwareEnvironmentVariableExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k32.GetFirmwareEnvironmentVariableExW.restype = wintypes.DWORD
        k32.SetFirmwareEnvironmentVariableExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                                           wintypes.DWORD, wintypes.DWORD]
        k32.SetFirmwareEnvironmentVariableExW.restype = wintypes.BOOL
        self.k32 = k32
        self.guid = '{%s}' % EFI_GLOBAL.upper()

        self.can_read = self.can_write = enable_privilege(ctypes, wintypes, k32)

    def read(self, name):
        ctypes = self.ctypes
        size = 4096
        while True:
            buf = ctypes.create_string_buffer(size)
            attributes = ctypes.c_ulong(0)
            n = self.k32.GetFirmwareEnvironmentVariableExW(name, self.guid, buf, size, ctypes.byref(attributes))
            code = 0 if n else ctypes.get_last_error()
            if n or code == 0:
                return buf.raw[:n]
            if code == 203:                                # ERROR_ENVVAR_NOT_FOUND
                return None
            if code == 122 and size < 1 << 20:             # ERROR_INSUFFICIENT_BUFFER
                size *= 16
                continue
            raise RuntimeError(windows_error(name, code, ctypes))

    def write(self, name, value):
        ctypes = self.ctypes
        if value is None:
            ok = self.k32.SetFirmwareEnvironmentVariableExW(name, self.guid, None, 0, NV_BS_RT)
            if not ok and ctypes.get_last_error() == 203:
                return
        else:
            buf = ctypes.create_string_buffer(value, len(value))
            ok = self.k32.SetFirmwareEnvironmentVariableExW(name, self.guid, buf, len(value), NV_BS_RT)
        if not ok:
            raise RuntimeError(windows_error(name, ctypes.get_last_error(), ctypes))


def windows_error(name, code, ctypes):
    """What a failed call for a firmware variable means."""
    if code == 1:
        return 'Windows did not start through UEFI here: a legacy BIOS start has no firmware boot entries to choose'
    if code == 1314:
        return ('Windows lets only an administrator read or change the firmware\'s boot entries (a console started '
                'with "Run as administrator")')
    return '%s: %s (Windows error %d)' % (name, ctypes.FormatError(code).strip(), code)


def enable_privilege(ctypes, wintypes, k32):
    """SeSystemEnvironmentPrivilege enabled in this process's token: True for an elevated administrator."""
    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)

    class LUID(ctypes.Structure):
        _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [('Luid', LUID), ('Attributes', wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [('PrivilegeCount', wintypes.DWORD), ('Privileges', LUID_AND_ATTRIBUTES * 1)]

    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
                                               wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]

    # TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(k32.GetCurrentProcess(), 0x0028, ctypes.byref(token)):
        return False

    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, 'SeSystemEnvironmentPrivilege', ctypes.byref(luid)):
            return False

        # SE_PRIVILEGE_ENABLED; ERROR_NOT_ALL_ASSIGNED (1300) afterwards: the token does not hold the privilege
        wanted = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, 0x2)))
        ctypes.set_last_error(0)
        if not advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(wanted), 0, None, None):
            return False
        return ctypes.get_last_error() == 0
    finally:
        k32.CloseHandle(token)


def firmware(system=None, efi='/sys/firmware/efi'):
    """The variables of this machine's firmware, or an error that says why there are none to choose. system:
    windows, linux, or another sys.platform (this machine's by default)."""
    if system is None:
        system = 'windows' if os.name == 'nt' else 'linux' if sys.platform.startswith('linux') else sys.platform

    if system == 'windows':
        return WindowsFirmware()

    if system == 'linux':
        efivars = os.path.join(efi, 'efivars')
        if not os.path.isdir(efi):
            raise RuntimeError('this Linux did not start through UEFI (no %s): a legacy BIOS start, WSL or a '
                               'container has no firmware boot entries to choose' % efi)
        if not os.path.isdir(efivars) or not os.listdir(efivars):
            raise RuntimeError('efivarfs is not mounted (sudo mount -t efivarfs efivarfs %s)' % efivars)
        return LinuxFirmware(efivars)

    raise RuntimeError('%s: this task chooses the boot entries of Windows and Linux machines (macOS: System '
                       'Settings, General, Startup Disk)' % system)


###################################################################################################
# The helper, as root or as an administrator

def main(argv, fw=None):
    """python -I uefi_boot.py <answer file or -> read|once|always|cancel [<entry>]: 0 when done, 1 when not."""
    if len(argv) < 2 or argv[1] not in ACTIONS:
        sys.stderr.write('usage: python -I uefi_boot.py <answer file or -> %s [<entry>]\n' % '|'.join(ACTIONS))
        return 2
    target, action = argv[0], argv[1]
    selector = argv[2] if len(argv) > 2 else ''

    try:
        fw = fw or firmware()
        if action == 'read':
            answer = dict(boot_entries(fw.read, also=number_of(selector)), **{'return': 0})
        else:
            answer = apply(fw, action, selector)
    except Exception as e:
        # whatever fails is the answer: the task reads it and says it
        answer = {'return': 1, 'error': str(e) or e.__class__.__name__}

    try:
        write_answer(target, json.dumps(answer))
    except (OSError, ValueError) as e:
        sys.stderr.write('uefi_boot.py: no answer written to %s: %s\n' % (target, e))
        return 1

    return 0 if answer.get('return') == 0 else 1


def write_answer(target, text):
    """The answer: to the standard output (-); into the empty file the task made for it, written in place - so it stays
    the file of the user who started the task: on Windows a file an administrator's process makes belongs to the
    Administrators group, which that user's unelevated console may not read (the Permission denied of 2026-11-14);
    or into a new file. Never into a file with content or with other links: this may run as an administrator."""
    if target == '-':
        sys.stdout.write(text + '\n')
        return

    data = text.encode('utf-8')
    if os.path.lexists(target):
        st = os.lstat(target)
        if not stat.S_ISREG(st.st_mode) or st.st_size or st.st_nlink > 1:
            raise ValueError('it is not the empty file of an answer')
        with open(target, 'r+b') as f:
            f.write(data)
            f.truncate()
        return

    with open(target, 'xb') as f:
        f.write(data)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
