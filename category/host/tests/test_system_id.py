"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"This machine" by the system_id a probe records (a hash of the OS's own id, stable across renames), the declared
hostname as the fallback: _here, whoami, and the probe script of this OS printing the same hash as Python.
"""

import hashlib
import importlib.util
import os
from pathlib import Path
import platform
import subprocess
import sys
import types
import unittest

spec = importlib.util.spec_from_file_location('host_system_id_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def host(alias, hostname='', system_id='', type='ssh'):
    return {'alias': alias, 'uid': alias + '-uid', 'type': type,
            'desc': {'access': {'hostname': hostname} if hostname else {}, 'machine': 'machine,1::' + alias},
            'state': {'system_id': system_id} if system_id else {}}


class SystemId(unittest.TestCase):
    def setUp(self):
        self.cat = module.Category.__new__(module.Category)
        self.cat._host_cache = {}
        self.old = module._LOCAL_SYSTEM_ID
        module._LOCAL_SYSTEM_ID = module.system_id_of('Local-Machine-Guid')
        self.addCleanup(setattr, module, '_LOCAL_SYSTEM_ID', self.old)
        self.me = platform.node().split('.')[0]

    def test_hash_is_lowercase_sha256_prefix(self):
        expected = hashlib.sha256(b'abc-def').hexdigest()[:16]
        self.assertEqual(module.system_id_of('  ABC-def\n'), expected)
        self.assertEqual(module.system_id_of(''), '')
        self.assertEqual(module.system_id_of(None), '')

    def test_system_id_wins_over_a_changed_hostname(self):
        # the Mac mini: the declared hostname is old, the probe recorded the id
        self.assertTrue(self.cat._here(host('mac', 'Mac-001', module.system_id_of('local-machine-guid'))))

    def test_another_system_id_is_not_here_even_with_the_same_hostname(self):
        self.assertFalse(self.cat._here(host('twin', self.me, module.system_id_of('another'))))

    def test_hostname_when_no_id_was_recorded(self):
        self.assertTrue(self.cat._here(host('old', self.me)))
        self.assertFalse(self.cat._here(host('other', 'not-' + self.me)))

    def test_hostname_when_this_os_has_no_id(self):
        module._LOCAL_SYSTEM_ID = ''
        self.assertTrue(self.cat._here(host('h', self.me, module.system_id_of('x'))))

    def test_only_ssh_hosts_are_here(self):
        self.assertFalse(self.cat._here(host('w', self.me, module.system_id_of('local-machine-guid'), type='wsl')))

    def test_whoami_prefers_the_id_then_the_hostname(self):
        hosts = [host('by-name', self.me), host('by-id', 'renamed', module.system_id_of('LOCAL-machine-guid')),
                 host('a-wsl', self.me, type='wsl')]
        self.cat._select = lambda ctx, *a, **k: {'return': 0, 'hosts': hosts}
        r = self.cat.whoami_({'control': {'con': False}})
        self.assertEqual((r['host'], r['by'], r['uid']), ('by-id', 'system_id', 'by-id-uid'))

        hosts.pop(1)
        r = self.cat.whoami_({'control': {'con': False}})
        self.assertEqual((r['host'], r['by']), ('by-name', 'hostname'))

        hosts.pop(0)
        self.assertEqual(self.cat.whoami_({'control': {'con': False}})['host'], '')


class ProbeScriptAgrees(unittest.TestCase):
    """The probe script of this OS prints the system_id Python computes here (the real id, read twice)."""

    def test_probe_prints_the_local_system_id(self):
        module._LOCAL_SYSTEM_ID = None
        mine = module.local_system_id()
        if not mine:
            self.skipTest('this OS has no machine id (a container?)')

        files = Path(__file__).parents[1] / 'files'
        if sys.platform == 'win32':
            cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(files / 'probe.ps1')]
        else:
            cmd = ['bash', str(files / 'probe.sh')]
        out = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=300).stdout.decode('utf-8', errors='replace')
        lines = [x.strip() for x in out.splitlines() if x.strip().startswith('system_id=')]
        self.assertEqual(lines, ['system_id=' + mine])


if __name__ == '__main__':
    unittest.main()
