"""The status of an ssh host when this machine refuses Python's own socket (a VPN that lets only chosen programs
out): the host's ssh command answers instead, and only then."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('host_status_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StatusThroughSsh(unittest.TestCase):
    def setUp(self):
        self.cat = module.Category.__new__(module.Category)
        self.cat._host_cache = {}
        self.cat.cm = types.SimpleNamespace(error=lambda error: {'return': 1, 'error': error})
        self.cat._here = lambda h: False
        self.calls = []
        def cmd_run(ctx, h, cmd, **kwargs):
            self.calls.append((cmd, kwargs))
            return {'return': 0, 'cmd': 'ssh vm ' + cmd}
        self.cat._cmd_run = cmd_run
        self.host = {'alias': 'vm', 'type': 'ssh', 'desc': {'access': {'address': '100.64.0.7', 'port': 22}}}

    def status(self, banner, quick=None):
        self.cat._run_quick = lambda cmd, timeout: quick
        with mock.patch.object(module, 'ssh_banner_status', return_value=banner):
            return self.cat._status({}, self.host, cmd_timeout=20)

    def test_a_local_refusal_is_blocked_here_not_down(self):
        with mock.patch.object(module.socket, 'create_connection', side_effect=PermissionError(13, 'forbidden')):
            self.assertEqual(module.ssh_banner_status('100.64.0.7', 22, 1), 'blocked here')
        with mock.patch.object(module.socket, 'create_connection', side_effect=ConnectionRefusedError()):
            self.assertEqual(module.ssh_banner_status('100.64.0.7', 22, 1), 'down')

    def test_blocked_here_asks_the_hosts_own_ssh(self):
        self.assertEqual(self.status('blocked here', {'returncode': 0, 'timeout': False}), 'up')
        self.assertEqual(self.calls, [('exit', {'raw': True})])
        self.assertEqual(self.status('blocked here', {'returncode': 255, 'timeout': False}), 'down (through ssh)')
        self.assertEqual(self.status('blocked here', {'returncode': None, 'timeout': True}), 'timeout (20s, through ssh)')

    def test_no_ssh_when_python_could_check(self):
        for banner in ('up', 'down', 'refused', 'no banner'):
            self.assertEqual(self.status(banner), banner)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
