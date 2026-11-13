"""What the SSH and cServer columns of a fleet page read from "cx host status" (2026-11-13): the ssh server of an ssh
host - for this machine too, whose own check ("here") says nothing about it - and the address a browser opens for a
declared server ("browse", else its url unless that is the machine itself, else its first public URL's root)."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('host_columns_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Category = module.Category


class SshColumn(unittest.TestCase):
    def host(self, access):
        return {'alias': 'h', 'type': 'ssh', 'desc': {'access': access}}

    def test_another_machine_keeps_its_own_check(self):
        with mock.patch.object(module, 'ssh_banner_status') as banner:
            for status in ('up', 'down', 'refused', 'no banner', 'down (through ssh)'):
                self.assertEqual(Category._ssh_server_status(self.host({'address': 'x', 'port': 2222}), status), status)
            banner.assert_not_called()

    def test_this_machine_asks_its_declared_ssh_server(self):
        with mock.patch.object(module, 'ssh_banner_status', return_value='up') as banner:
            self.assertEqual(Category._ssh_server_status(self.host({'address': 'hub-name', 'port': 2222}), 'here', 3), 'up')
            banner.assert_called_once_with('hub-name', 2222, 3)
        with mock.patch.object(module, 'ssh_banner_status', return_value='down') as banner:
            self.assertEqual(Category._ssh_server_status(self.host({'address': 'hub-name'}), 'here', 3), 'down')
            banner.assert_called_once_with('hub-name', module.DEFAULT_SSH_PORT, 3)

    def test_this_machine_without_an_address_says_so(self):
        with mock.patch.object(module, 'ssh_banner_status') as banner:
            self.assertEqual(Category._ssh_server_status(self.host({'hostname': 'PC'}), 'here'), 'not declared')
            banner.assert_not_called()


class BrowseUrl(unittest.TestCase):
    def test_a_declared_browse_wins(self):
        self.assertEqual(Category._browse_url({'url': 'http://127.0.0.1:8228/', 'browse': 'http://pc:8228/'}), 'http://pc:8228/')

    def test_a_url_other_machines_reach_is_the_address(self):
        self.assertEqual(Category._browse_url({'url': 'http://100.64.1.2:8004/'}), 'http://100.64.1.2:8004/')
        self.assertEqual(Category._browse_url({'url': 'http://pc-name:8004/'}), 'http://pc-name:8004/')

    def test_the_machine_itself_falls_back_to_the_public_root(self):
        self.assertEqual(Category._browse_url({'url': 'http://127.0.0.1:8338/healthz',
                                               'public': ['https://site.example/healthz', 'https://other.example/']}),
                         'https://site.example/')
        self.assertEqual(Category._browse_url({'url': 'http://localhost:8338/', 'public': 'https://site.example/a/b'}),
                         'https://site.example/')

    def test_nothing_to_open(self):
        self.assertEqual(Category._browse_url({'url': 'http://127.0.0.1:8228/'}), '')
        self.assertEqual(Category._browse_url({}), '')


if __name__ == '__main__':
    unittest.main()
