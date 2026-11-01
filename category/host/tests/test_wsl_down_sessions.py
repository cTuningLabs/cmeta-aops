"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host down of a WSL distro someone has a session in (2026-11-01): the stop ends every process of the distro - a
terminal tab included - and Docker Desktop's integration starts the distro again at once, which looked like WSL
failing. The sessions are read from Windows: the wsl.exe processes that target the distro, minus Docker's and
Podman's integration (`wsl.exe -d <distro> sh` and the proxy from com.docker.backend.exe), the management commands,
the inner wsl.exe of a pair and our own process tree. With a session the stop is refused unless --force; without
one, or when Windows cannot say, the distro stops as before. Offline: no process is listed, nothing is run.
"""

import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('host_wsl_down_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

DISTRO = 'ubuntu-26.04-on-usb-x'
OWN = 7000


def proc(pid, ppid, name, cmd=''):
    return {'ProcessId': pid, 'ParentProcessId': ppid, 'Name': name, 'CommandLine': cmd}


# the laptop on 2026-11-01 18:21, as Get-CimInstance showed it (abridged)
PROCESSES = [
    proc(45568, 1, 'com.docker.backend.exe', 'com.docker.backend.exe'),
    proc(32984, 45568, 'wsl.exe', f'C:\\WINDOWS\\System32\\wsl.exe -d {DISTRO} sh'),                 # Docker's keep-alive
    proc(42436, 32984, 'wsl.exe', f'C:\\WINDOWS\\System32\\wsl.exe -d {DISTRO} sh'),
    proc(3460, 45568, 'wsl.exe', f'wsl.exe -d {DISTRO} -u root -e /run/docker-desktop/docker-desktop-user-distro proxy'),
    proc(13376, 45568, 'wsl.exe', 'wsl.exe -d docker-desktop -u root -e wsl-bootstrap run'),
    proc(11584, 36096, 'wslhost.exe', ' --vm-id {e9} --handle 3052'),
    proc(300, 1, 'WindowsTerminal.exe', 'WindowsTerminal.exe'),
    proc(400, 300, 'wsl.exe', f'"C:\\WINDOWS\\system32\\wsl.exe" -d {DISTRO}'),                      # a terminal tab
    proc(401, 400, 'wsl.exe', f'"C:\\WINDOWS\\system32\\wsl.exe" -d {DISTRO}'),                      # its inner wsl.exe
    proc(500, OWN, 'wsl.exe', f'wsl.exe -d {DISTRO} -- true'),                                          # our own probe
    proc(600, 1, 'wsl.exe', 'wsl.exe -l -v'),                                                            # a management command
    proc(601, 1, 'wsl.exe', f'wsl.exe -t {DISTRO}'),
    proc(700, 1, 'cmd.exe', 'cmd.exe'),
    proc(800, 700, 'wsl.exe', 'wsl.exe'),                                                               # the default distro, no -d
    proc(900, 1, 'wsl.exe', 'wsl.exe -d ubuntu-24.04-on-usb-x'),                                        # another distro
    proc(950, 1, 'python.exe', 'python.exe cx host run ...'),
    proc(951, 950, 'wsl.exe', f'wsl.exe --distribution {DISTRO} -- bash -l -s'),                        # another shell's cx host run
]


class WslDown(unittest.TestCase):
    def setUp(self):
        self.cat = module.Category.__new__(module.Category)
        self.cat.logger = None
        self.cat.cm = types.SimpleNamespace(error=lambda error: {'return': 1, 'error': error})
        self.ran = []
        self.sessions = [{'pid': 400, 'parent': 'WindowsTerminal.exe', 'cmd': f'-d {DISTRO}'}]

        def run_local(cmd, capture=False, timeout=None, con=True, verbose=False):
            self.ran.append(cmd)
            return {'returncode': 0, 'stdout': '', 'stderr': ''}

        self.cat._run_local = run_local
        self.cat._declared_command = lambda ctx, h, what, verbose: None
        self.cat._wsl_sessions = lambda distro: list(self.sessions)
        self.host = {'alias': 'pc-wsl', 'type': 'wsl', 'status': 'up', 'desc': {'access': {'distro': DISTRO}}}

    def stops(self):
        return [c for c in self.ran if c.startswith('wsl.exe -t ')]

    def test_the_sessions_are_the_wsl_processes_of_the_distro_minus_integration_management_and_ours(self):
        sessions = module.Category.wsl_sessions_in(PROCESSES, DISTRO, OWN)
        self.assertEqual([(s['pid'], s['parent']) for s in sessions], [(400, 'WindowsTerminal.exe'), (951, 'python.exe')])
        self.assertEqual(sessions[0]['cmd'], f'-d {DISTRO}')
        # the default distro is also addressed by a wsl.exe without -d
        sessions = module.Category.wsl_sessions_in(PROCESSES, DISTRO, OWN, is_default=True)
        self.assertEqual([s['pid'] for s in sessions], [400, 800, 951])
        # Docker's distro alone: only its integration - nothing
        self.assertEqual(module.Category.wsl_sessions_in(PROCESSES, 'docker-desktop', OWN), [])
        self.assertEqual(module.Category.wsl_sessions_in([], DISTRO, OWN), [])
        self.assertEqual(module.Category.wsl_sessions_in([{'ProcessId': 'x'}], DISTRO, OWN), [])

    def test_a_session_in_the_distro_refuses_the_stop_without_force(self):
        r = self.cat._down_one({'control': {}}, self.host, False, False)
        self.assertEqual(r['return'], 1)
        self.assertIn('WindowsTerminal.exe (pid 400: wsl.exe -d ' + DISTRO + ')', r['error'])
        self.assertIn('cx host down pc-wsl --force', r['error'])
        self.assertEqual(self.stops(), [])

    def test_force_stops_it_anyway(self):
        r = self.cat._down_one({'control': {}}, self.host, False, True)
        self.assertEqual(r, {'return': 0, 'result': 'stopped'})
        self.assertEqual(self.stops(), ['wsl.exe -t ' + DISTRO])

    def test_without_a_session_the_distro_stops_as_before(self):
        self.sessions = []
        r = self.cat._down_one({'control': {}}, self.host, False, False)
        self.assertEqual(r, {'return': 0, 'result': 'stopped'})
        self.assertEqual(self.stops(), ['wsl.exe -t ' + DISTRO])

    def test_the_probe_reads_windows_and_answers_nothing_when_it_cannot(self):
        cat = module.Category.__new__(module.Category)
        cat.logger = None
        answers = {'returncode': 0, 'stdout': json.dumps(PROCESSES), 'stderr': ''}
        cat._run_local = lambda cmd, capture=False, timeout=None, con=True, verbose=False: dict(answers)
        if module.os.name != 'nt':
            self.assertEqual(cat._wsl_sessions(DISTRO), [])            # a POSIX controller has no WSL
            return
        # the machine's facts pinned: we are process OWN, and another distro is the default (wsl -l -v, UTF-16)
        listing = types.SimpleNamespace(stdout=('  NAME                   STATE    VERSION\n* ubuntu-24.04-on-usb-x  Stopped  2\n'
                                                f'  {DISTRO}  Running  2\n').encode('utf-16-le'))
        with mock.patch.object(module.os, 'getpid', lambda: OWN), \
             mock.patch.object(module.subprocess, 'run', lambda *a, **k: listing):
            sessions = cat._wsl_sessions(DISTRO)
            self.assertEqual(sorted(s['pid'] for s in sessions), [400, 951])
            answers = {'returncode': 1, 'stdout': '', 'stderr': 'no powershell'}
            self.assertEqual(cat._wsl_sessions(DISTRO), [])
            answers = {'returncode': 0, 'stdout': 'not json', 'stderr': ''}
            self.assertEqual(cat._wsl_sessions(DISTRO), [])
            # the default distro: a wsl.exe without -d is a session in it too
            answers = {'returncode': 0, 'stdout': json.dumps(PROCESSES), 'stderr': ''}
            listing.stdout = listing.stdout.replace('* ubuntu-24.04'.encode('utf-16-le'), '  ubuntu-24.04'.encode('utf-16-le')) \
                                           .replace(f'  {DISTRO}'.encode('utf-16-le'), f'* {DISTRO}'.encode('utf-16-le'))
            self.assertEqual(sorted(s['pid'] for s in cat._wsl_sessions(DISTRO)), [400, 800, 951])

    def test_the_cli_flag_reaches_the_stop(self):
        """down_ hands --force through _up_down to _down_one."""
        seen = []
        self.cat._select = lambda ctx, arg1, tags, machine, type: {'return': 0, 'hosts': [self.host]}
        self.cat._is_explicit = lambda arg1, hosts: True
        self.cat._status_all = lambda ctx, hosts: None
        self.cat.cm.catch_error = lambda r: r.get('return', 0) > 0
        self.cat._down_one = lambda ctx, h, verbose, force=False: seen.append(force) or {'return': 0, 'result': 'stopped'}
        ctx = {'control': {'con': False}}
        self.cat.down_(ctx, 'pc-wsl')
        self.cat.down_(ctx, 'pc-wsl', force=True)
        self.assertEqual(seen, [False, True])


if __name__ == '__main__':
    unittest.main()
