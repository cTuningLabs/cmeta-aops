"""
reboot-to - restart this machine into another system of its firmware's boot menu (Windows, Ubuntu, ...), once or
always, on Windows and Linux (README.md):

  cx task run reboot-to                         the systems of the boot menu, numbered: which one? then a restart
  cx task run reboot-to ubuntu                  restart into ubuntu once (the start after it is the usual one)
  cx task run reboot-to windows --always        Windows first in the boot order, then a restart
  cx task run reboot-to --list                  the systems and the word of --os for each (--all: every boot entry)
  cx task run reboot-to ubuntu --reboot=no      only the next start is set; --cancel takes it back
  cx task run reboot-to ubuntu --dry_run        what it would do; nothing changes

The firmware's own variables, read and changed by uefi_boot.py: BootNext for once, BootOrder for always. The firmware
then starts that system's loader itself, as at any start, so BitLocker sees nothing new (never GRUB's chainload of
Windows). Windows lets only an administrator read or change them: from another console Windows asks (UAC). Linux:
everyone reads them, root writes (sudo). The restart is the task reboot's.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import base64
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, ask

REBOOT_TASK = 'reboot,ddf5633344d84171'

# uefi_boot.py: the firmware's variables, standard library only - also run on its own, as root or an administrator
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uefi_boot.py')


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UEFI = _load_module('reboot_to_uefi_boot', HELPER)

# grub_menu.py: GRUB's menu, its next_entry (once) and saved default (always) - --via=grub on Linux
GRUB = _load_module('reboot_to_grub_menu', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'grub_menu.py'))

CONFIG = 'task-reboot-to'     # this machine's settings: via (firmware or grub) - cx config set task-reboot-to --meta.via=grub


###################################################################################################
# What is shown

def shown(entries, every=False):
    """The entries a list shows: the systems (a loader file on a disk, not a tool such as the firmware updater), or
    every entry (--all, or no system)."""
    systems = [e for e in entries if e['kind'] == 'loader' and not e.get('tool')]
    return entries if every or not systems else systems


def notes(entry):
    words = []
    if entry['current']:
        words.append('booted this session')
    if entry['next']:
        words.append('the next restart (once)')
    if entry['first']:
        words.append('first in the boot order')
    if not entry['in_order']:
        words.append('not in the boot order')
    if not entry['active']:
        words.append('inactive')
    if entry['hidden']:
        words.append('hidden')
    return ', '.join(words)


def table(entries, rows):
    """The lines of a list, one per row: n) its name, the word of --os, the entry, its loader (or the kind of entry)
    and where it is, notes."""
    cells = []
    for i, e in enumerate(rows):
        where = e['file'] or e['kind']
        if e.get('device'):
            where += ' on ' + e['device']
        elif e.get('partition'):
            where += ' on partition %d {%s}' % (e['partition_number'], e['partition'][:8])
        cells.append(['%d)' % i, e['description'] or '(no name)', '--os=' + UEFI.hint(entries, e), e['name'], where,
                      notes(e)])
    if not cells:
        return []

    widths = [max(len(c[k]) for c in cells) for k in range(len(cells[0]))]
    return ['  ' + '  '.join(c[k].ljust(widths[k]) for k in range(len(c))).rstrip() for c in cells]


def add_devices(entries, folder='/dev/disk/by-partuuid'):
    """Linux: the device of each entry's partition (nvme0n1p1), from its GPT partition GUID."""
    for e in entries:
        link = os.path.join(folder, e['partition']) if e.get('partition') else ''
        if link and os.path.exists(link):
            e['device'] = os.path.basename(os.path.realpath(link))


def entry_text(entry):
    return '%s (%s)' % (entry['description'] or '(no name)', entry['name'])


def first_text(data):
    """The entry the boot order starts with, in words."""
    first = next((e for e in data['entries'] if e['first']), None)
    return entry_text(first) if first else 'the firmware\'s own choice: no boot order'


def numbered(data, number):
    """An entry by its number, in words."""
    entry = next((e for e in data['entries'] if e['number'] == number), None)
    return entry_text(entry) if entry else 'Boot%04X' % number


def summary(data, on_windows):
    """The lines under a list: what the next restart starts, and a Windows that a Linux entry's GRUB started (a dual-boot laptop,
    2026-11-14: a once into Ubuntu ended in Windows - GRUB's default was Windows)."""
    if data['next'] is not None:
        lines = ['Next restart: %s, once - then the boot order again (%s first).' % (numbered(data, data['next']),
                                                                                  first_text(data))]
    else:
        lines = ['Next restart: %s, the first in the boot order (no "once" is set).' % first_text(data)]

    current = next((e for e in data['entries'] if e['current']), None)
    if on_windows and current and current['system'] == 'linux':
        lines.append('This Windows was booted through %s: its GRUB started Windows, as its default or chosen in its '
                     'menu. A once into %s ends in Windows while GRUB\'s default is Windows (README: GRUB).' % (
                         entry_text(current), current['description']))
    return lines


###################################################################################################
# The helper's rights

def elevated_command(program, arguments):
    """The -EncodedCommand of PowerShell that starts the program as an administrator (Windows asks: UAC), hidden,
    waits for it and exits with its exit code."""
    script = ("$p = Start-Process -FilePath '%s' -ArgumentList '%s' -Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
              "exit $p.ExitCode" % (program.replace("'", "''"), subprocess.list2cmdline(arguments).replace("'", "''")))
    return base64.b64encode(script.encode('utf-16-le')).decode('ascii')


def answer_of(out, said=''):
    """The helper's JSON answer (its last line), or an error with what sudo or PowerShell said."""
    lines = out.decode('utf-8', 'replace').strip().splitlines() if out else []
    try:
        answer = json.loads(lines[-1])
    except (ValueError, IndexError):
        answer = None
    if isinstance(answer, dict) and 'return' in answer:
        return answer

    said = ' '.join(said.split())[-300:]
    return {'return': 1, 'error': 'no answer from the helper that reads and changes the boot entries' +
                                  (': ' + said if said else '')}


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            os: str = '',               # the system to start: ubuntu, windows, BootXXXX (--list shows them); none: a menu
            always: bool = False,       # first in the boot order, for every start (by default: the next start only)
            list: bool = False,         # list the systems and the word of --os for each; nothing else
            all: bool = False,          # every boot entry (network, USB, the firmware's own), not only the systems
            cancel: bool = False,       # take back a "once" set before (BootNext); nothing else
            reboot: bool = True,        # restart now; --reboot=no only sets the next start or the boot order
            yes: bool = False,          # restart without asking (a run without a terminal needs it)
            dry_run: bool = False,      # what it would do; nothing changes
            delay_seconds=0,            # restart after so many seconds (0 - 3600, as the task reboot)
            grub: bool = False,         # Linux: choose in GRUB's menu (= --via=grub)
            via: str = '',              # firmware (its boot entries) or grub (Linux: GRUB's menu); default: config task-reboot-to, else firmware
            grub_timeout: str = '',     # --via=grub: GRUB's menu shown for so many seconds at every boot (0: hidden)
    ):
        """
        Restart into another system (Windows, Ubuntu, ...): once - the default - or --always. Through the firmware's
        boot entries, or on Linux through GRUB's menu (--via=grub). Without --os, the systems are listed and one is
        asked for.
        """
        # os, list and all are the words of the command line here: the module os and the built-ins work in the
        # methods below, never in this one
        control = ctx['control']
        self.con = control.get('con', False)
        self.quiet = control.get('quiet', False)
        try:
            self.terminal = bool(self.con and not self.quiet and sys.stdin is not None and sys.stdin.isatty())
        except (ValueError, OSError):
            self.terminal = False

        try:
            delay = int(delay_seconds)
        except (TypeError, ValueError):
            delay = -1
        if not 0 <= delay <= 3600:
            return self.cm.error('--delay_seconds takes a whole number of seconds, 0 - 3600')

        selector = '' if os is True else str(os or '').strip()
        mode = 'cancel' if cancel else 'always' if always else 'once'
        if cancel and (selector or always):
            return self.cm.error('--cancel takes back a "once" and does nothing else: no --os, no --always')

        via = 'grub' if grub else (str(via or '').strip().lower() or self._configured_via())
        if via not in ('firmware', 'grub'):
            return self.cm.error(f'--via takes firmware or grub, not "{via}"')
        timeout = str(grub_timeout or '').strip()
        if timeout and (not timeout.isdigit() or int(timeout) > 600):
            return self.cm.error('--grub_timeout takes a whole number of seconds, 0 - 600')
        if via == 'grub':
            return self._grub(selector, mode, bool(list), bool(all), bool(reboot), bool(yes), bool(dry_run), delay,
                              timeout)
        if timeout:
            return self.cm.error('--grub_timeout goes with --via=grub')

        return self._reboot_to(selector, mode, bool(list), bool(all), bool(reboot), bool(yes), bool(dry_run), delay)

    ############################################################
    def _say(self, text=''):
        if self.con:
            print(text)

    def _reboot_to(self, selector, mode, listing, every, reboot, yes, dry_run, delay):
        host = platform.node()
        try:
            fw = UEFI.firmware()
        except Exception as e:
            return self.cm.error(str(e))

        if mode == 'cancel':
            return self._cancel(fw, dry_run)

        # Windows, a console that is not an administrator's, a system named: Windows asks once (UAC), for the helper
        # that reads, chooses and writes - the question to restart comes before it
        if not fw.can_read and selector and not listing and not dry_run:
            r = self._confirm(mode, '"%s"' % selector, host, reboot, yes)
            if r['return'] > 0 or r.get('stop'):
                return r
            return self._finish(self._change(fw, mode, selector), mode, host, reboot, delay, every)

        r = self._read(fw, selector)
        if r['return'] > 0:
            return r
        data = r
        if not data['entries']:
            return self.cm.error('the firmware lists no boot entries (no BootOrder, or entries it cannot read)')
        add_devices(data['entries'])
        rows = shown(data['entries'], every)

        if listing:
            self._show(data, rows)
            self._say('Restart into one: cx task run reboot-to --os=<its word> (once; --always: every start)')
            return self._result(data)

        entry = None
        if selector:
            hits = UEFI.select(data['entries'], selector)
            if len(hits) == 1:
                entry = hits[0]
            elif not hits or not self.terminal:
                self._show(data, rows)
                return self.cm.error(UEFI.not_one(selector, hits))
            else:
                # several: the menu offers them
                self._say(UEFI.not_one(selector, hits))
                self._say()
                rows = hits
        elif not self.terminal:
            self._show(data, rows)
            return self.cm.error('name the system to start: --os=<its word in the list above>')

        if entry is None:
            r = self._menu(data, rows, mode)
            if r['return'] > 0 or r.get('entry') is None:
                return r
            entry = r['entry']

        if dry_run:
            return self._dry_run(data, entry, mode, host, reboot, delay)

        r = self._confirm(mode, entry_text(entry), host, reboot, yes)
        if r['return'] > 0 or r.get('stop'):
            return r
        return self._finish(self._change(fw, mode, entry['name']), mode, host, reboot, delay, every)

    def _show(self, data, rows):
        if not self.con:
            return
        if len(rows) == len(data['entries']):
            print('The boot entries of this machine\'s firmware, in its boot order:')
        else:
            print('The systems this machine\'s firmware starts, in its boot order (--all: every boot entry):')
        print('')
        for line in table(data['entries'], rows):
            print(line)
        print('')
        for line in summary(data, os.name == 'nt'):
            print(line)
        print('')

    def _menu(self, data, rows, mode):
        self._show(data, rows)
        question = 'Restart into which one%s? Its number, 0-%d (Enter: none): ' % (
            ', always' if mode == 'always' else '', len(rows) - 1)
        r = ask(question, how='--os=<a word of the list> to name it in advance')
        if r['return'] > 0:
            return r

        answer = r['answer'].strip()
        if not answer:
            self._say('Nothing chosen: nothing changed.')
            return {'return': 0, 'entry': None}
        if not answer.isdigit() or int(answer) >= len(rows):
            return self.cm.error('"%s" is not a number of the list (0-%d): nothing changed' % (answer, len(rows) - 1))
        return {'return': 0, 'entry': rows[int(answer)]}

    def _confirm(self, mode, what, host, reboot, yes):
        """The question before a restart: none with --yes, or without a restart (--reboot=no)."""
        if not reboot or yes:
            return {'return': 0}
        if not self.terminal:
            return self.cm.error('a restart without a question needs --yes (or --reboot=no: the next start is set, '
                                 'nothing restarts)')

        if mode == 'once':
            question = 'Restart %s into %s, once? [y/N] ' % (host, what)
        else:
            question = 'Put %s first in the boot order of %s and restart into it? [y/N] ' % (what, host)
        r = ask(question, how='--yes to restart without a question')
        if r['return'] > 0:
            return r
        if r['answer'].strip().lower() not in ('y', 'yes'):
            self._say('Not restarted: nothing changed.')
            return {'return': 0, 'stop': True, 'cancelled': True}
        return {'return': 0}

    def _result(self, data, **more):
        result = {'return': 0, 'entries': data['entries'], 'order': data['order'], 'current': data['current'],
                  'next': data['next']}
        result.update(more)
        return result

    ############################################################
    def _read(self, fw, selector=''):
        """The boot entries: in this process when it may read them, else through the helper (Windows: UAC; an
        efivarfs whose files root alone reads: sudo)."""
        if fw.can_read:
            try:
                return dict(UEFI.boot_entries(fw.read, also=UEFI.number_of(selector)), **{'return': 0})
            except PermissionError:
                pass
            except Exception as e:
                return self.cm.error(str(e))

        r = self._helper(['read'] + ([selector] if selector else []))
        return r if r['return'] == 0 else self.cm.error(r.get('error') or 'the boot entries were not read')

    def _change(self, fw, mode, selector):
        """once, always or cancel: in this process when it may write (root, an administrator), else through the
        helper. The helper's answer: before, after, entry."""
        if fw.can_write:
            try:
                return UEFI.apply(fw, mode, selector)
            except Exception as e:
                return {'return': 1, 'error': str(e)}
        return self._helper([mode] + ([selector] if selector else []))

    def _helper(self, words):
        """uefi_boot.py as root (sudo) or as an administrator (Windows asks: UAC), and its JSON answer."""
        python = sys.executable or 'python3'
        if os.name == 'nt':
            return self._helper_windows(python, words)
        return self._helper_sudo(python, words)

    def _helper_sudo(self, python, words):
        if not shutil.which('sudo'):
            return {'return': 1, 'error': 'root changes the firmware\'s boot entries, and there is no sudo here: '
                                          'run the task as root'}

        # sudo without a question first; in a terminal sudo may ask for the password - the answer still comes on the
        # standard output, sudo's question and its words go to the terminal
        line = [python, '-I', HELPER, '-'] + words
        p = subprocess.run(['sudo', '-n'] + line, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        said = p.stderr.decode('utf-8', 'replace')
        if not p.stdout.strip() and self.terminal:
            self._say('sudo: root changes the firmware\'s boot entries')
            p = subprocess.run(['sudo'] + line, stdout=subprocess.PIPE)
            said = ''
        return answer_of(p.stdout, said)

    def _helper_windows(self, python, words):
        """An administrator's process gives back no output: the helper writes its answer into a file. The task makes
        that file, empty, in a folder of its own (private to this user) - so the file stays this user's and readable
        here; a file the elevated helper made would belong to the Administrators group, which an unelevated console
        may not read (2026-11-14: Permission denied)."""
        folder = tempfile.mkdtemp(prefix='cmeta-reboot-to-')
        answer = os.path.join(folder, 'answer.json')
        try:
            open(answer, 'xb').close()
            self._say('Windows asks for an administrator (UAC): only an administrator reads or changes the '
                      'firmware\'s boot entries.')
            p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                elevated_command(python, ['-I', HELPER, answer] + words)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            said = p.stdout.decode('utf-8', 'replace')
            try:
                with open(answer, 'rb') as f:
                    text = f.read()
            except OSError as e:
                return answer_of(b'', 'its answer could not be read (%s) %s' % (e, said))
            if not text.strip():
                return answer_of(b'', 'declined (UAC)? ' + said)
            return answer_of(text)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    ############################################################
    def _cancel(self, fw, dry_run):
        if dry_run:
            self._say('Would remove BootNext (a "once" set before): the next start follows the boot order.')
            return {'return': 0, 'dry_run': True}

        r = self._change(fw, 'cancel', '')
        if r['return'] > 0:
            return self.cm.error(r.get('error') or 'BootNext was not removed')

        before, after = r['before'], r['after']
        if before['next'] is None:
            self._say('No "once" was set: the next start follows the boot order (%s first).' % first_text(after))
        else:
            self._say('The "once" into %s is taken back: the next start follows the boot order (%s first).' % (
                numbered(before, before['next']), first_text(after)))
        return self._result(after)

    def _dry_run(self, data, entry, mode, host, reboot, delay):
        number = entry['number']
        if mode == 'once':
            self._say('Would set BootNext = %s: %s starts next, once.' % (entry['name'], entry_text(entry)))
        else:
            order = [number] + [n for n in data['order'] if n != number]
            self._say('Would set BootOrder = %s: %s first.' % (','.join('%04X' % n for n in order), entry_text(entry)))
            if data['next'] not in (None, number):
                self._say('Would remove BootNext (%s): it would start next otherwise.' % numbered(data, data['next']))

        command = None
        if reboot:
            r = self._restart(delay, dry_run=True)
            command = r.get('command') if r['return'] == 0 else None
            self._say('Would restart %s%s%s.' % (host, ' in %d seconds' % delay if delay else '',
                                                 ': ' + ' '.join(command) if command else ''))
        return self._result(data, dry_run=True, entry=entry, mode=mode, command=command)

    def _finish(self, r, mode, host, reboot, delay, every):
        """After the change: what the firmware starts now, then the restart."""
        if r['return'] > 0:
            if r.get('before'):
                self._show(r['before'], shown(r['before']['entries'], every))
            return self.cm.error(r.get('error') or 'the boot entries were not changed')

        entry, before, after = r['entry'], r['before'], r['after']
        if mode == 'once':
            self._say('The next start of %s: %s, once - the one after it follows the boot order again (%s first).' % (
                host, entry_text(entry), first_text(after)))
        else:
            self._say('The boot order of %s starts with %s now: every start goes there.' % (host, entry_text(entry)))
            if before['next'] not in (None, entry['number']):
                self._say('The "once" into %s is taken back: it would have started next.' % numbered(before,
                                                                                                    before['next']))
        result = self._result(after, entry=entry, mode=mode, restarting=False)

        if not reboot:
            self._say('Not restarted (--reboot=no): the next restart starts it%s.' % (
                ' - --cancel takes it back' if mode == 'once' else ''))
            return result

        rr = self._restart(delay)
        if rr['return'] > 0:
            return self.cm.error('the boot entry is set, but the restart failed: %s - restart by hand%s' % (
                rr.get('error'), ', or take it back with --cancel' if mode == 'once' else ''))
        self._say('Restarting %s%s.' % (host, ' in %d seconds' % delay if delay else ' now'))
        result.update({'restarting': True, 'command': rr.get('command')})
        return result

    def _restart(self, delay, dry_run=False):
        """The task reboot, without its question: this task asked."""
        return self.cm.access({'category': self.cmeta['uses_categories']['task'], 'command': 'run',
                               'arg1': REBOOT_TASK, 'yes': True, 'dry_run': dry_run, 'delay_seconds': delay,
                               'con': False, 'quiet': True})

    ############################################################
    # --via=grub (Linux): GRUB's menu chooses - its next_entry once, its saved default always

    def _configured_via(self):
        """This machine's choice (config task-reboot-to, key via), else the firmware."""
        r = self.cm.access({'category': 'config', 'command': 'read', 'arg1': CONFIG, 'con': False})
        value = str(((r.get('config_cmeta') or {}) if r.get('return', 1) == 0 else {}).get('via') or '').strip().lower()
        return value or 'firmware'

    def _root(self, words, input_text=None):
        """(return code, output) of a command as root: sudo -n in a quiet run, else sudo (it may ask in a terminal)."""
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            sudo = []
        else:
            sudo = ['sudo', '-n'] if (self.quiet or not self.terminal) else ['sudo']
        try:
            p = subprocess.run(sudo + words, input=input_text.encode('utf-8') if input_text is not None else None,
                               stdin=None if input_text is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as e:
            return 127, str(e)
        return p.returncode, p.stdout.decode('utf-8', 'replace')

    def _grub_state(self):
        """GRUB's menu, its environment (next_entry, saved_entry), /etc/default/grub - and the firmware's entry of the
        loader that starts GRUB, with whether the firmware starts it next."""
        cfg = GRUB.cfg_path()
        if not cfg:
            return self.cm.error('no grub.cfg here (/boot/grub/grub.cfg): this Linux does not start through GRUB')

        def text(path):
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    return f.read()
            except OSError:
                return ''

        state = {'cfg': cfg, 'envfile': GRUB.env_path(cfg), 'entries': GRUB.menu(text(cfg)),
                 'env': GRUB.env(text(GRUB.env_path(cfg))), 'defaults': text(GRUB.DEFAULTS), 'firmware': None}
        state['default'] = GRUB.grub_default(state['defaults'])
        state['style'] = GRUB.setting(state['defaults'], 'GRUB_TIMEOUT_STYLE', 'menu')
        state['timeout'] = GRUB.setting(state['defaults'], 'GRUB_TIMEOUT', '5')

        # the firmware entry that starts GRUB: the one running now when it is a Linux loader, else the first one
        try:
            fw = UEFI.firmware()
            data = dict(UEFI.boot_entries(fw.read), **{'return': 0}) if fw.can_read else None
        except Exception:
            fw, data = None, None
        if data:
            loaders = [e for e in data['entries'] if e['system'] == 'linux' and not e.get('tool')]
            loader = next((e for e in loaders if e['current']), loaders[0] if loaders else None)
            starts = loader and ((data['next'] == loader['number']) or
                                 (data['next'] is None and data['order'][:1] == [loader['number']]))
            state['firmware'] = {'fw': fw, 'data': data, 'loader': loader, 'starts_grub': bool(starts)}
        return dict(state, **{'return': 0})

    def _grub_now(self, s):
        """(the entry GRUB starts by default, the one it starts next once or None)."""
        entries = s['entries']
        if s['default'] == 'saved':
            default = GRUB.named(entries, s['env'].get('saved_entry') or '0')
        else:
            default = GRUB.named(entries, s['default'])
        return default, GRUB.named(entries, s['env'].get('next_entry'))

    def _grub_show(self, s, rows):
        if not self.con:
            return
        default, following = self._grub_now(s)
        cells = []
        for i, e in enumerate(rows):
            note = []
            if default is e:
                note.append('GRUB\'s default')
            if following is e:
                note.append('the next boot (once)')
            word = next((w for w in ([e['title']] if ' ' not in e['title'] else []) + [e['system'], e['id']]
                         if w and GRUB.select(s['entries'], w)[:1] == [e]), e['id'])
            cells.append(['%d)' % i, (e['submenu'] + ' > ' if e['submenu'] else '') + e['title'],
                          '--os=' + word, ', '.join(note)])
        print('GRUB\'s menu (%s):' % s['cfg'])
        print('')
        widths = [max(len(c[k]) for c in cells) for k in range(4)] if cells else []
        for c in cells:
            print('  ' + '  '.join(c[k].ljust(widths[k]) for k in range(4)).rstrip())
        print('')
        print('GRUB starts: %s%s' % (
            (following['title'] + ' once, then ') if following else '',
            (default['title'] if default else 'entry ' + s['default']) +
            (' (its default, GRUB_DEFAULT=%s)' % s['default'])))
        if s['style'] == 'hidden' or s['timeout'] == '0':
            print('Its menu at boot: hidden (Esc shows it) - --grub_timeout=5 shows it 5 s at every boot')
        else:
            print('Its menu at boot: %s s, then the default' % s['timeout'])
        fw = s.get('firmware')
        if fw and fw['loader']:
            print('The firmware starts GRUB next (%s): %s' % (entry_text(fw['loader']),
                                                             'yes' if fw['starts_grub'] else 'NO - this task sets it'))
        print('')

    def _grub(self, selector, mode, listing, every, reboot, yes, dry_run, delay, timeout):
        if not sys.platform.startswith('linux'):
            return self.cm.error('--via=grub chooses in GRUB\'s menu from the Linux side (its files are on the Linux '
                                 'partition): from here, --via=firmware')
        s = self._grub_state()
        if s['return'] > 0:
            return s
        rows = GRUB.shown(s['entries'], every)
        host = platform.node()

        if listing:
            self._grub_show(s, rows)
            self._say('Choose: cxt reboot-to --grub --os=<its word> (once; --always: GRUB\'s default)')
            return {'return': 0, 'via': 'grub', 'entries': s['entries'], 'default': s['default'],
                    'next_entry': s['env'].get('next_entry')}

        if mode == 'cancel':
            if not s['env'].get('next_entry'):
                self._say('No "once" was set in GRUB: the next boot starts its default.')
                return {'return': 0, 'via': 'grub'}
            if dry_run:
                self._say('Would unset GRUB\'s next_entry (%s).' % s['env']['next_entry'])
                return {'return': 0, 'via': 'grub', 'dry_run': True}
            code, out = self._root(['grub-editenv', s['envfile'], 'unset', 'next_entry'])
            if code != 0:
                return self.cm.error('grub-editenv unset next_entry failed: ' + out.strip()[-300:])
            self._say('The "once" in GRUB is taken back: the next boot starts its default.')
            return {'return': 0, 'via': 'grub'}

        # the entry: a word of --os, else the menu (only the GRUB timeout is changed when it alone is asked)
        entry = None
        if selector:
            hits = GRUB.select(s['entries'], selector)
            if len(hits) == 1 or (hits and not self.terminal and len({h['id'] for h in hits}) == 1):
                entry = hits[0]
            elif not hits or not self.terminal:
                self._grub_show(s, rows)
                return self.cm.error('no GRUB entry matches "%s"' % selector if not hits else
                                     '"%s" matches %d GRUB entries - name one by its id' % (selector, len(hits)))
            else:
                rows = hits
        elif timeout:
            pass
        elif not self.terminal:
            self._grub_show(s, rows)
            return self.cm.error('name the system to start: --os=<its word in the list above>')

        if entry is None and not (timeout and not selector):
            self._grub_show(s, rows)
            from task_c36be4b9314a45e0.api.ctask import ask
            r = ask('Restart into which one%s? Its number, 0-%d (Enter: none): ' % (
                ', always' if mode == 'always' else '', len(rows) - 1), how='--os=<a word of the list>')
            if r['return'] > 0:
                return r
            answer = r['answer'].strip()
            if not answer:
                self._say('Nothing chosen: nothing changed.')
                return {'return': 0, 'via': 'grub'}
            if not answer.isdigit() or int(answer) >= len(rows):
                return self.cm.error('"%s" is not a number of the list: nothing changed' % answer)
            entry = rows[int(answer)]

        # what changes: /etc/default/grub (the saved default, the menu's time) + update-grub; GRUB's environment
        values = {}
        if entry is not None and mode == 'always' and s['default'] != 'saved':
            values['GRUB_DEFAULT'] = 'saved'
        if timeout:
            values.update({'GRUB_TIMEOUT_STYLE': 'menu' if int(timeout) > 0 else 'hidden', 'GRUB_TIMEOUT': timeout})
        new_defaults, changed = GRUB.set_keys(s['defaults'], values) if values else (s['defaults'], False)
        steps = []
        if changed:
            steps.append(('/etc/default/grub: ' + ', '.join(f'{k}={v}' for k, v in values.items()) + ', then update-grub',
                          None))
        if entry is not None:
            ref = GRUB.entry_ref(entry)
            steps.append(('grub-reboot %s' % ref if mode == 'once' else 'grub-set-default %s' % ref,
                          ['grub-reboot', ref] if mode == 'once' else ['grub-set-default', ref]))
        fw = s.get('firmware')
        need_fw = bool(entry is not None and fw and fw['loader'] and not fw['starts_grub'])
        if need_fw:
            steps.append(('the firmware: %s %s, so that GRUB runs' % (
                'BootNext =' if mode == 'once' else 'first in BootOrder:', entry_text(fw['loader'])), None))

        if dry_run:
            for text, _ in steps:
                self._say('Would: ' + text)
            if entry is not None and reboot:
                self._say('Would restart %s%s.' % (host, ' in %d seconds' % delay if delay else ''))
            return {'return': 0, 'via': 'grub', 'dry_run': True, 'steps': [t for t, _ in steps]}

        if entry is not None:
            what = '%s (GRUB)' % entry['title']
            r = self._confirm(mode, what, host, reboot, yes)
            if r['return'] > 0 or r.get('stop'):
                return r

        # 1. /etc/default/grub, kept first beside it, then update-grub
        if changed:
            backup = GRUB.DEFAULTS + '.cmeta-reboot-to-' + time.strftime('%Y%m%d-%H%M%S')
            code, out = self._root(['cp', '-p', GRUB.DEFAULTS, backup])
            if code == 0:
                code, out = self._root(['tee', GRUB.DEFAULTS], new_defaults)
            if code != 0:
                return self.cm.error('writing %s failed: %s' % (GRUB.DEFAULTS, out.strip()[-300:]))
            code, out = self._root(['update-grub'])
            if code != 0:
                self._root(['cp', '-p', backup, GRUB.DEFAULTS])
                return self.cm.error('update-grub failed (%s put back): %s' % (GRUB.DEFAULTS, out.strip()[-300:]))
            self._say('%s: %s (the old one: %s); grub.cfg made again' % (
                GRUB.DEFAULTS, ', '.join(f'{k}={v}' for k, v in values.items()), backup))

        if entry is None:
            return {'return': 0, 'via': 'grub', 'grub_timeout': timeout}

        # 2. GRUB's choice, read back
        code, out = self._root(steps[-2 if need_fw else -1][1])
        if code != 0:
            return self.cm.error('%s failed: %s' % (' '.join(steps[-2 if need_fw else -1][1]), out.strip()[-300:]))
        s2 = self._grub_state()
        default, following = self._grub_now(s2)
        def same(a, b):
            return bool(a and b) and (a['id'], a['title']) == (b['id'], b['title'])

        if (mode == 'once' and not same(following, entry)) or \
                (mode == 'always' and (s2['default'] != 'saved' or not same(default, entry))):
            return self.cm.error('GRUB did not keep the choice (next_entry %s, saved_entry %s, GRUB_DEFAULT=%s)' % (
                s2['env'].get('next_entry'), s2['env'].get('saved_entry'), s2['default']))

        # 3. the firmware starts GRUB
        if need_fw:
            r = self._change(fw['fw'], mode, fw['loader']['name'])
            if r['return'] > 0:
                return self.cm.error('GRUB is set, but the firmware does not start GRUB next: %s' % r.get('error'))

        if mode == 'once':
            self._say('The next boot of %s: %s (GRUB, once) - then GRUB\'s default again.' % (host, entry['title']))
        else:
            self._say('GRUB\'s default on %s is %s now: every boot starts it (its menu lets you choose).' % (
                host, entry['title']))
        result = {'return': 0, 'via': 'grub', 'entry': entry, 'mode': mode, 'restarting': False}
        if not reboot:
            self._say('Not restarted (--reboot=no).')
            return result
        rr = self._restart(delay)
        if rr['return'] > 0:
            return self.cm.error('GRUB is set, but the restart failed: %s - restart by hand' % rr.get('error'))
        self._say('Restarting %s%s.' % (host, ' in %d seconds' % delay if delay else ' now'))
        result.update({'restarting': True, 'command': rr.get('command')})
        return result
