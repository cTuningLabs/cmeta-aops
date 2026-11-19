"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host status probes THIS machine again when the cMeta engine or cmeta-aops installed here is another version than its
saved probe recorded (a sync or an upgrade through cx host re-probes the other hosts, never the machine that runs them).
"""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('host_here_versions_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HereVersions(unittest.TestCase):
    def setUp(self):
        self.cat = module.Category.__new__(module.Category)
        self.cat.path = str(Path(__file__).parents[1])

    def test_the_installed_versions_come_from_the_files(self):
        now = self.cat._installed_versions()
        cmr = (Path(__file__).parents[3] / '_cmr.yaml').read_text(encoding='utf-8')
        self.assertIn('version: ' + now['aops'], cmr)
        self.assertRegex(now.get('cmeta', ''), r'^\d+\.\d+')

    def test_a_stale_probe_is_probed_again_a_current_one_is_not(self):
        self.cat._installed_versions = lambda: {'cmeta': '0.44.1', 'aops': '0.76.0'}
        old = {'alias': 'me', 'state': {'cmeta_version': '0.43.0', 'aops_version': '0.74.0'}}
        new = {'alias': 'me', 'state': {'cmeta_version': '0.44.1', 'aops_version': '0.76.0'}}
        self.assertTrue(self.cat._here_versions_changed(old))
        self.assertFalse(self.cat._here_versions_changed(new))
        self.assertTrue(self.cat._here_versions_changed({'alias': 'me', 'state': {}}))

    def test_nothing_is_probed_on_a_guess(self):
        self.cat._installed_versions = lambda: {}
        self.assertFalse(self.cat._here_versions_changed({'alias': 'me', 'state': {'cmeta_version': '0.1'}}))

    def test_status_probes_only_this_machine_and_only_when_stale(self):
        probed = []
        self.cat._installed_versions = lambda: {'cmeta': '0.44.1', 'aops': '0.76.0'}
        self.cat._refresh_state = lambda ctx, h, con: probed.append(h['alias'])
        hosts = [{'alias': 'here-stale', 'status': 'here', 'state': {'cmeta_version': '0.43.0', 'aops_version': '0.76.0'}},
                 {'alias': 'other-stale', 'status': 'up', 'state': {'cmeta_version': '0.1', 'aops_version': '0.1'}},
                 {'alias': 'here-current', 'status': 'here', 'state': {'cmeta_version': '0.44.1', 'aops_version': '0.76.0'}}]
        for h in hosts:
            if h.get('status') == 'here' and self.cat._here_versions_changed(h):
                self.cat._refresh_state({}, h, False)
        self.assertEqual(probed, ['here-stale'])


if __name__ == '__main__':
    unittest.main()
