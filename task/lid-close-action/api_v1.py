"""
lid-close-action - what closing a laptop's lid does: nothing (a machine reached from elsewhere keeps running), or
its sleep, hibernation or shutdown again (README.md):

  cx task run lid-close-action                        status: what closing the lid does now, on AC and on battery
  cx task run lid-close-action disable                closing the lid does nothing while on AC power
  cx task run lid-close-action disable --power=both   ... on battery too
  cx task run lid-close-action enable                 what it did before the disable, again (else --to: sleep)

Windows: the lid action of the active power plan (powercfg LIDACTION). disable keeps the values it replaces in
log::local:lid-close-action and enable puts them back. Linux: systemd-logind, through a drop-in file of this task
(/etc/systemd/logind.conf.d/50-cmeta-lid-close-action.conf, written with sudo), which logind is asked to read
again - never restarted (a restart may end the graphical session); enable removes the file, and the system's own
settings apply again. macOS: pmset disablesleep (sudo) - macOS has no lid action of its own: it keeps the whole
machine from sleeping, on every power source.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import re
import shutil
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

LOG_ARTIFACT = 'lid-close-action'
POWERS = ('ac', 'battery', 'both')

# Windows: the values of LIDACTION (powercfg), and the names this task uses for them
WIN_ACTIONS = {0: 'nothing', 1: 'sleep', 2: 'hibernate', 3: 'shut down'}
WIN_VALUES = {'nothing': 0, 'sleep': 1, 'hibernate': 2, 'shutdown': 3, 'shut down': 3}

# Linux: the values of logind's HandleLidSwitch*, in the same words
LOGIND_ACTIONS = {'ignore': 'nothing', 'suspend': 'sleep', 'hibernate': 'hibernate', 'poweroff': 'shut down',
                  'hybrid-sleep': 'hybrid sleep', 'suspend-then-hibernate': 'sleep, then hibernate', 'lock': 'lock',
                  'halt': 'halt', 'kexec': 'kexec', 'reboot': 'reboot'}
LOGIND_VALUES = {'nothing': 'ignore', 'sleep': 'suspend', 'hibernate': 'hibernate', 'shutdown': 'poweroff',
                 'shut down': 'poweroff'}
DROPIN = '/etc/systemd/logind.conf.d/50-cmeta-lid-close-action.conf'


def parse_powercfg(text):
    """(AC, DC) values of one setting from "powercfg /qh <scheme> <subgroup> <setting>": the last two hex values of
    the output (its words change with the language of Windows, its numbers do not), or (None, None)."""
    found = re.findall(r':\s*(0x[0-9a-fA-F]+)\s*$', text or '', re.M)
    if len(found) < 2:
        return None, None
    return int(found[-2], 16), int(found[-1], 16)


def logind_effective(props):
    """What closing the lid does on AC and on battery from the values logind holds: HandleLidSwitchExternalPower
    empty means "as on battery" (HandleLidSwitch)."""
    battery = props.get('HandleLidSwitch') or 'suspend'
    ac = props.get('HandleLidSwitchExternalPower') or battery
    return {'ac': ac, 'battery': battery}


def logind_dropin(power, effective):
    """The drop-in that makes closing the lid do nothing on the power sources asked. Battery alone: HandleLidSwitch is
    what AC follows when its own value is empty, so AC's present action is written out to stay as it is."""
    lines = ['# cmeta-aops lid-close-action: closing the lid does nothing (%s).' % ('on AC power' if power == 'ac' else
             'on battery' if power == 'battery' else 'on AC power and on battery'),
             '# "cx task run lid-close-action enable" removes this file; the settings of the system apply again.',
             '[Login]']
    if power in ('ac', 'both'):
        lines.append('HandleLidSwitchExternalPower=ignore')
    if power in ('battery', 'both'):
        lines.append('HandleLidSwitch=ignore')
        if power == 'battery':
            lines.append('HandleLidSwitchExternalPower=%s' % effective['ac'])
    return '\n'.join(lines) + '\n'


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'status',     # status, disable (closing the lid does nothing), enable (what it did before)
            power: str = 'ac',          # ac, battery or both: the power sources disable and enable change
            to: str = '',               # enable on Windows with nothing recorded: sleep (default), hibernate, shutdown
    ):
        """
        What closing the lid does: status (the default), disable (nothing), enable (what it did before the disable).
        """
        self.con = ctx['control'].get('con', False)
        action = str(action or 'status').lower()
        if action not in ('status', 'enable', 'disable'):
            return self.cm.error(f'unknown action "{action}": use status, disable or enable')
        power = str(power or 'ac').lower()
        if power not in POWERS:
            return self.cm.error('--power takes ac, battery or both')
        to = str(to or '').lower()
        if to and to not in WIN_VALUES:
            return self.cm.error('--to takes sleep, hibernate, shutdown or nothing')

        if os.name == 'nt':
            return self._windows(action, power, to)
        if sys.platform == 'darwin':
            return self._macos(action, power, to)
        return self._linux(action, power)

    ############################################################
    def _say(self, text):
        if self.con:
            print(text)

    def _run(self, words, input_text=None):
        """(return code, output) of a command."""
        try:
            p = subprocess.run(words, input=input_text.encode('utf-8') if input_text is not None else None,
                               stdin=None if input_text is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as e:
            return 127, str(e)
        return p.returncode, p.stdout.decode('utf-8', 'replace')

    def _folder(self):
        """The log artifact (local repository) that keeps what disable replaced, made on first use."""
        cat = self.cmeta['uses_categories']['log']
        ref = f'local:{LOG_ARTIFACT}'
        r = self.cm.access({'category': cat, 'command': 'find', 'arg1': ref, 'con': False})
        if r['return'] == 0 and r.get('artifacts'):
            return {'return': 0, 'path': r['artifacts'][0]['path']}
        r = self.cm.access({'category': cat, 'command': 'create', 'arg1': ref, 'yaml': True, 'con': False,
                            'tags': ['lid-close-action', 'cmeta-aops'],
                            'meta': {'desc': 'What the task lid-close-action replaced (previous.json): put back by '
                                             'its enable'}})
        if r['return'] > 0:
            return r
        return {'return': 0, 'path': r['path']}

    def _sides(self, power):
        return ['ac', 'battery'] if power == 'both' else [power]

    def _report(self, now, extra=''):
        self._say('closing the lid: on AC power - %s; on battery - %s%s' % (now['ac'], now['battery'], extra))

    ############################################################
    # Windows: powercfg

    def _win_read(self):
        code, out = self._run(['powercfg', '/qh', 'SCHEME_CURRENT', 'SUB_BUTTONS', 'LIDACTION'])
        ac, dc = parse_powercfg(out) if code == 0 else (None, None)
        if ac is None:
            return None
        return {'ac': ac, 'battery': dc}

    def _win_write(self, values):
        """values: {'ac': n, 'battery': n}. powercfg as this user first; when Windows refuses, the same commands as an
        administrator (Windows asks: UAC)."""
        words = []
        for side, value in values.items():
            words.append(['powercfg', '/setacvalueindex' if side == 'ac' else '/setdcvalueindex', 'SCHEME_CURRENT',
                          'SUB_BUTTONS', 'LIDACTION', str(int(value))])
        words.append(['powercfg', '/setactive', 'SCHEME_CURRENT'])
        failed = [w for w in words if self._run(w)[0] != 0]
        if not failed:
            return {'return': 0}
        self._say('Windows refused the change to this console: it asks for an administrator')
        line = ' & '.join(' '.join(w) for w in words)
        ps = ("Start-Process cmd.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
              "'/d /c " + line.replace("'", "''") + "'")
        code, out = self._run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps])
        if code != 0:
            return self.cm.error('powercfg as an administrator failed or was declined: ' + out.strip()[-300:])
        return {'return': 0}

    def _windows(self, action, power, to):
        now = self._win_read()
        if now is None:
            return self.cm.error('powercfg did not tell the lid action of the active power plan (a machine without '
                                 'a lid, or a plan without the setting)')
        named = {k: WIN_ACTIONS.get(v, 'value %d' % v) for k, v in now.items()}
        r = self._folder()
        if r['return'] > 0:
            return r
        record = os.path.join(r['path'], 'previous.json')
        try:
            with open(record, encoding='utf-8') as f:
                previous = json.load(f)
        except (OSError, ValueError):
            previous = {}

        if action == 'status':
            kept = ', '.join('%s %s' % ('on AC' if k == 'ac' else 'on battery', WIN_ACTIONS.get(v, v))
                             for k, v in previous.items())
            self._report(named, ('\n  disable kept, for enable: ' + kept) if kept else '')
            return {'return': 0, 'system': 'windows', 'ac': named['ac'], 'battery': named['battery'], 'kept': previous}

        sides = self._sides(power)
        if action == 'disable':
            # what is replaced is kept for enable - never "nothing" over an action kept before
            for s in sides:
                if now[s] != 0 and s not in previous:
                    previous[s] = now[s]
            r = self._win_write({s: 0 for s in sides})
            if r['return'] > 0:
                return r
            with open(record, 'w', encoding='utf-8') as f:
                json.dump(previous, f, indent=1)
        else:
            values = {s: previous.get(s, WIN_VALUES[to] if to else 1) for s in sides}
            r = self._win_write(values)
            if r['return'] > 0:
                return r
            for s in sides:
                previous.pop(s, None)
            if previous:
                with open(record, 'w', encoding='utf-8') as f:
                    json.dump(previous, f, indent=1)
            elif os.path.isfile(record):
                os.remove(record)

        after = self._win_read() or now
        named = {k: WIN_ACTIONS.get(v, 'value %d' % v) for k, v in after.items()}
        self._report(named)
        return {'return': 0, 'system': 'windows', 'ac': named['ac'], 'battery': named['battery']}

    ############################################################
    # Linux: systemd-logind

    def _logind_props(self):
        props = {}
        for p in ('HandleLidSwitch', 'HandleLidSwitchExternalPower', 'HandleLidSwitchDocked'):
            code, out = self._run(['busctl', 'get-property', 'org.freedesktop.login1', '/org/freedesktop/login1',
                                   'org.freedesktop.login1.Manager', p])
            m = re.match(r'\s*s\s+"(.*)"\s*$', out) if code == 0 else None
            if m:
                props[p] = m.group(1)
        return props

    def _sudo(self, words, input_text=None):
        """A command as root: itself when this process is root, else through sudo without a question (-n); in a
        terminal, sudo may ask for the password."""
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            return self._run(words, input_text)
        code, out = self._run(['sudo', '-n'] + words, input_text)
        if code != 0 and 'password' in out.lower() and sys.stdin.isatty() and input_text is None:
            code, out = subprocess.call(['sudo'] + words), ''
        return code, out

    def _linux(self, action, power):
        if not shutil.which('busctl'):
            return self.cm.error('no systemd here (busctl): this task changes the lid action through systemd-logind')
        props = self._logind_props()
        if not props:
            return self.cm.error('systemd-logind did not answer (busctl get-property org.freedesktop.login1 ...)')
        eff = logind_effective(props)
        named = {k: LOGIND_ACTIONS.get(v, v) for k, v in eff.items()}
        ours = os.path.isfile(DROPIN)

        if action == 'status':
            code, out = self._run(['systemd-inhibit', '--list', '--no-pager'])
            holders = [l.strip() for l in out.splitlines() if 'handle-lid-switch' in l] if code == 0 else []
            extra = ('\n  set by this task: ' + DROPIN) if ours else ''
            if holders:
                extra += '\n  programs holding the lid switch (they decide while they run): ' + '; '.join(h[:100] for h in holders)
            self._report(named, extra)
            return {'return': 0, 'system': 'linux', 'ac': named['ac'], 'battery': named['battery'], 'dropin': ours}

        if action == 'disable':
            text = logind_dropin(power, eff)
            code, out = self._sudo(['mkdir', '-p', os.path.dirname(DROPIN)])
            if code == 0:
                code, out = self._sudo(['tee', DROPIN], text)
            if code != 0:
                return self.cm.error('writing %s needs root: %s - run it in a terminal where sudo may ask, or as root'
                                     % (DROPIN, out.strip()[-200:]))
        else:
            if not ours:
                self._say('this task set nothing here (no %s): the settings of the system apply' % DROPIN)
            else:
                code, out = self._sudo(['rm', '-f', DROPIN])
                if code != 0:
                    return self.cm.error('removing %s needs root: %s' % (DROPIN, out.strip()[-200:]))

        # logind reads its configuration again when it can; a restart is never done here (it may end the session)
        code, out = self._run(['systemctl', 'show', 'systemd-logind', '-p', 'CanReload', '--value'])
        if out.strip() == 'yes':
            code, out = self._sudo(['systemctl', 'reload', 'systemd-logind'])
            if code != 0:
                return self.cm.error('systemctl reload systemd-logind failed: ' + out.strip()[-200:])
        else:
            self._say('this systemd-logind cannot read its configuration again while it runs: the change applies '
                      'after the next restart of the machine (this task never restarts logind - that may end the '
                      'graphical session)')
        eff = logind_effective(self._logind_props())
        named = {k: LOGIND_ACTIONS.get(v, v) for k, v in eff.items()}
        self._report(named)
        return {'return': 0, 'system': 'linux', 'ac': named['ac'], 'battery': named['battery']}

    ############################################################
    # macOS: pmset

    def _macos(self, action, power, to=''):
        """pmset disablesleep governs all the sleep of the machine, not only the lid's: disable keeps the value it
        replaces and enable puts back only what this task changed (2026-11-13: an enable without that record turned
        off a disablesleep another task had set on a test Mac) - or 0 when --to=sleep asks for it."""
        code, out = self._run(['pmset', '-g'])
        disabled = bool(re.search(r'^\s*SleepDisabled\s+1\s*$', out, re.M))
        word = 'nothing (the machine never sleeps)' if disabled else 'sleep'
        if action == 'status':
            self._report({'ac': word, 'battery': word}, '\n  (macOS: pmset disablesleep, for every power source)')
            return {'return': 0, 'system': 'macos', 'ac': word, 'battery': word}
        if power != 'both':
            self._say('macOS has no lid action of its own: pmset disablesleep applies on every power source')
        r = self._folder()
        if r['return'] > 0:
            return r
        record = os.path.join(r['path'], 'previous.json')
        try:
            with open(record, encoding='utf-8') as f:
                previous = json.load(f)
        except (OSError, ValueError):
            previous = {}
        if action == 'disable':
            previous.setdefault('macos_disablesleep', 1 if disabled else 0)
            value = '1'
        elif 'macos_disablesleep' in previous:
            value = str(previous.pop('macos_disablesleep'))
        elif to == 'sleep':
            value = '0'
        else:
            self._say('this task did not change pmset disablesleep here (it is %s): left as it is - '
                      '--to=sleep sets it to 0' % ('1' if disabled else '0'))
            return self._macos('status', power)
        code, out = self._sudo(['pmset', '-a', 'disablesleep', value])
        if code != 0:
            return self.cm.error('pmset needs root: ' + out.strip()[-200:])
        if previous:
            with open(record, 'w', encoding='utf-8') as f:
                json.dump(previous, f, indent=1)
        elif os.path.isfile(record):
            os.remove(record)
        return self._macos('status', power)
