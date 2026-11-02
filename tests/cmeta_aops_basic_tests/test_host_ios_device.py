"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A host of type ios (an iPhone or iPad on a Mac's USB, 2026-11-02): what the host category reads from the Mac's
"xcrun devicectl list devices" for its status (the table) and its probe (the JSON), and that it runs no command.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def host_module():
    spec = importlib.util.spec_from_file_location('ios_host_test', ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TABLE = '''Name     Hostname   Identifier                         State                Model                    Reality
------   --------   --------------------------------   ------------------   ----------------------   --------
iPhone              00008150-000C259126E0C01C (UDID)   connected (no DDI)   iPhone 17 (iPhone18,3)   physical
iPad     ipad.lan   00008103-001A2B3C4D5E6F70 (UDID)   available (paired)   iPad Pro (iPad16,3)      physical
'''

DEVICES = [{'identifier': '38FCDC41-A80B-514F-BBA4-FFABBA534CC2',
            'hardwareProperties': {'udid': '00008150-000C259126E0C01C', 'marketingName': 'iPhone 17', 'productType': 'iPhone18,3',
                                   'cpuType': {'name': 'arm64e'}, 'internalStorageCapacity': 256000000000, 'platform': 'iOS'},
            'deviceProperties': {'name': 'iPhone', 'osVersionNumber': '27.0.1', 'osBuildUpdate': '24A446', 'developerModeStatus': 'enabled'},
            'connectionProperties': {'pairingState': 'paired'}}]


def test_the_state_column_of_the_device():
    m = host_module()
    assert m.devicectl_state_of(TABLE, '00008150-000C259126E0C01C') == 'connected (no DDI)'
    assert m.devicectl_state_of(TABLE, '00008103-001a2b3c4d5e6f70') == 'available (paired)'      # an empty Hostname cell or not
    assert m.devicectl_state_of(TABLE, '00008150-FFFFFFFFFFFFFFFF') is None
    assert m.devicectl_state_of(TABLE, '') is None
    assert m.devicectl_state_of('', '00008150-000C259126E0C01C') is None


def test_what_the_probe_records():
    m = host_module()
    state = m.ios_state_of(DEVICES, '00008150-000C259126E0C01C')
    assert state == {'hostname': 'iPhone', 'os': 'iOS 27.0.1 (iPhone 17, iPhone18,3)', 'arch': 'arm64', 'cpu': 'arm64e',
                     'model': 'iPhone18,3', 'marketing_name': 'iPhone 17', 'os_build': '24A446', 'developer_mode': 'enabled',
                     'pairing': 'paired', 'identifier': '38FCDC41-A80B-514F-BBA4-FFABBA534CC2', 'storage': '256 GB'}
    assert m.ios_state_of(DEVICES, 'other') is None
    assert m.ios_state_of([], '00008150-000C259126E0C01C') is None


def test_ios_is_a_type_and_the_address_names_the_mac():
    m = host_module()
    assert 'ios' in m.TYPES
    CHost = m.CHost if hasattr(m, 'CHost') else None
    if CHost is None:
        # the category class under whatever name: the one with _address_text
        CHost = next(v for v in vars(m).values() if isinstance(v, type) and hasattr(v, '_address_text'))
    host = CHost.__new__(CHost)
    h = {'alias': 'fgg-iphone-17-ios', 'type': 'ios', 'via': 'fgg-mac-mini-macos', 'via_list': ['fgg-mac-mini-macos'],
         'desc': {'access': {'udid': '00008150-000C259126E0C01C'}}}
    assert host._address_text(h) == 'ios 00008150-000C259126E0C01C via fgg-mac-mini-macos'
    assert 'xcrun devicectl list devices' in m.DEVICECTL_LIST and '--json-output' in m.DEVICECTL_LIST_JSON
