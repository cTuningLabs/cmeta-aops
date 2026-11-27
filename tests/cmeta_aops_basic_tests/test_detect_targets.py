"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/detect-targets (2026-11-26): the targets of a machine from the probes the target tasks declare, the choice of
--compute=auto (never a guess between two accelerators), the fingerprint that decides when the cached findings are
detected again. Offline: the probe engine on stand-in files and device folders.
"""

import os
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TASK = ROOT / 'task' / 'detect-targets'


@pytest.fixture(scope = 'module')
def mod():
    src = (TASK / 'api_v1.py').read_text(encoding = 'utf-8')
    line = 'from task_c36be4b9314a45e0.api.ctask import InitCTask'
    assert line in src
    ns = {'__name__': 'detect_targets_under_test', '__file__': str(TASK / 'api_v1.py')}
    exec(compile(src.replace(line, 'class InitCTask: pass'), str(TASK / 'api_v1.py'), 'exec'), ns)
    return ns


HOST = {'system': 'linux', 'kernel': '6.8.0', 'machine': 'x86_64'}


def test_a_file_and_its_version(mod, tmp_path):
    f = tmp_path / 'nvidia' / 'version'
    f.parent.mkdir()
    f.write_text('NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  590.44.01  Release Build\n')
    spec = {'any': [{'glob': str(f), 'version': r'Kernel Module(?:\s+for\s+\S+)?\s+([0-9][0-9.]+)'}]}
    out = mod['probe'](spec, HOST, {})
    assert out['present'] and out['versions'] == {'version': '590.44.01'}
    assert not mod['probe']({'any': [{'glob': str(tmp_path / 'none' / '*')}]}, HOST, {})['present']


def test_an_amd_gpu_in_the_kernels_rocm_interface(mod, tmp_path):
    node = tmp_path / 'nodes' / '1'
    node.mkdir(parents = True)
    (node / 'properties').write_text('simd_count 304\ngfx_target_version 90402\n')
    cpu = tmp_path / 'nodes' / '0'
    cpu.mkdir()
    (cpu / 'properties').write_text('simd_count 0\ngfx_target_version 0\n')
    assert mod['gfx_of_kfd'](str(tmp_path / 'nodes')) == ['gfx942']


def test_windows_devices_by_class_and_vendor(mod):
    cache = {'windows': [{'class': 'Display', 'name': 'NVIDIA RTX', 'vendor': '10DE', 'driver': '32.0.15.9186'},
                         {'class': 'Display', 'name': 'Intel(R) Graphics', 'vendor': '8086', 'driver': '32.0.101.8250'},
                         {'class': 'ComputeAccelerator', 'name': 'Intel(R) NPU', 'vendor': '8086', 'driver': ''}]}
    win = dict(HOST, system = 'windows')
    nv = mod['probe']({'any': [{'pnp': {'class': ['Display'], 'vendor': ['10DE']}}]}, win, cache)
    assert nv['present'] and nv['devices'] == ['NVIDIA RTX'] and nv['versions'] == {'NVIDIA RTX': '32.0.15.9186'}
    npu = mod['probe']({'any': [{'pnp': {'class': ['ComputeAccelerator'], 'vendor': ['8086']}}]}, win, cache)
    assert npu['present'] and npu['devices'] == ['Intel(R) NPU']
    amd = mod['probe']({'any': [{'pnp': {'class': ['ComputeAccelerator'], 'vendor': ['1022']}}]}, win, cache)
    assert not amd['present']


def test_apple_silicon_and_the_cpu(mod):
    mac = {'system': 'darwin', 'kernel': '25.0', 'machine': 'arm64', 'chip': 'Apple M4'}
    assert mod['probe']({'any': [{'machine': ['arm64']}]}, mac, {})['devices'] == ['Apple M4']
    assert not mod['probe']({'any': [{'machine': ['arm64']}]}, HOST, {})['present']
    assert mod['probe']({'any': [{'always': True}]}, HOST, {})['present']


def test_the_choice_of_compute_auto(mod):
    choose = mod['choose']
    # one accelerator kind the program supports: taken
    assert choose(['cpu', 'cuda'], ['cpu', 'cuda', 'rocm']) == ('cuda', ['cuda'])
    # two: no guess - the caller lists them
    assert choose(['cpu', 'cuda', 'xpu'], ['cpu', 'cuda', 'xpu']) == (None, ['cuda', 'xpu'])
    # the program supports none of them: the CPU
    assert choose(['cpu', 'cuda', 'xpu'], ['cpu']) == ('cpu', [])
    # nothing it supports at all
    assert choose(['cpu'], ['cuda']) == (None, [])


def test_the_fingerprint_follows_devices_and_versions(mod):
    probes = {'cuda': {'present': True, 'devices': ['A500'], 'versions': {'version': '580.95.05'}}}
    fp = mod['fingerprint'](HOST, probes)
    assert fp == mod['fingerprint'](HOST, {'cuda': dict(probes['cuda'])})
    newer = {'cuda': {'present': True, 'devices': ['A500'], 'versions': {'version': '590.44.01'}}}
    assert fp != mod['fingerprint'](HOST, newer)
    assert fp != mod['fingerprint'](dict(HOST, kernel = '6.9.0'), probes)
    changes = mod['CTask']._changes(probes, newer)
    assert changes == ['cuda: other driver or runtime versions']
    assert mod['CTask']._changes(probes, {}) == ['cuda is gone']


def test_the_target_tasks_declare_their_probes():
    for target, os_name in (('cpu', 'all'), ('cuda', 'linux'), ('cuda', 'windows'), ('rocm', 'linux'), ('xpu', 'linux'),
                            ('xpu', 'windows'), ('metal', 'darwin'), ('npu-intel', 'linux'), ('npu-amd', 'linux'),
                            ('opencl', 'linux'), ('opencl', 'windows'), ('opencl', 'darwin'), ('vulkan', 'linux'),
                            ('vulkan', 'windows'), ('vulkan', 'darwin'), ('openvino', 'linux'), ('openvino', 'windows'),
                            ('android-cpu', 'all'), ('android-gpu', 'all'), ('android-npu', 'all'), ('android-app', 'all')):
        desc = yaml.safe_load((ROOT / 'task' / ('target--' + target) / '_desc.yaml').read_text(encoding = 'utf-8'))
        assert desc['probe'][os_name]['any'], (target, os_name)


KNOWN_CHECKS = {'all', 'any', 'always', 'machine', 'glob', 'version', 'names', 'kfd_gfx', 'drm_vendor', 'drivers',
                'accel_driver', 'pci', 'pnp', 'pnp_driver_value', 'registry_values', 'cpu_vendor', 'adb_devices', 'script'}


def _checks(items):
    for check in items or []:
        yield check
        for key in ('all', 'any'):
            yield from _checks(check.get(key) if isinstance(check.get(key), list) else [])


def test_every_declared_probe_uses_checks_the_task_knows():
    """A word the probe engine does not read would make a target silently absent."""
    seen = 0
    for desc_file in sorted((ROOT / 'task').glob('target--*/_desc.yaml')):
        desc = yaml.safe_load(desc_file.read_text(encoding = 'utf-8'))
        assert desc.get('auto') in (None, 'portable'), desc_file
        for os_name, spec in (desc.get('probe') or {}).items():
            assert os_name in ('all', 'linux', 'windows', 'darwin'), (desc_file, os_name)
            for check in _checks(spec['any']):
                assert set(check) <= KNOWN_CHECKS, (desc_file, os_name, sorted(set(check) - KNOWN_CHECKS))
                seen += 1
    assert seen > 20


def test_a_gpu_and_the_file_its_driver_installs(mod, tmp_path, monkeypatch):
    """all: every check holds; a manifest without its GPU (a distribution installs every Mesa manifest) is nothing."""
    manifest = tmp_path / 'icd.d' / 'nvidia_icd.json'
    manifest.parent.mkdir()
    manifest.write_text('{}')
    there = {'glob': str(manifest)}
    gone = {'glob': str(tmp_path / 'icd.d' / 'radeon_icd*.json')}

    assert mod['probe']({'any': [{'all': [there, {'always': True}]}]}, HOST, {})['present']
    assert not mod['probe']({'any': [{'all': [there, gone]}]}, HOST, {})['present']
    assert mod['probe']({'any': [{'all': [{'always': True}, {'any': [gone, there]}]}]}, HOST, {})['present']
    assert not mod['probe']({'any': [{'all': []}]}, HOST, {})['present']

    # names: the files found are the devices
    out = mod['probe']({'any': [{'glob': str(tmp_path / 'icd.d' / '*.json'), 'names': True}]}, HOST, {})
    assert out['devices'] == ['nvidia_icd.json']


def test_a_windows_driver_that_names_its_opencl_library(mod):
    """What the Khronos loaders read: the driver key of a present device (Enum names it) holds OpenCLDriverName."""
    keys = {('SYSTEM\\CurrentControlSet\\Enum\\PCI\\VEN_10DE&DEV_1', 'Driver'): '{4d36e968}\\0004',
            ('SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968}\\0004', 'OpenCLDriverName'): 'C:\\drv\\nvopencl64.dll',
            ('SYSTEM\\CurrentControlSet\\Enum\\ROOT\\MON', 'Driver'): '{4d36e968}\\0000',
            ('SOFTWARE\\Khronos\\OpenCL\\Vendors', None): ['D:\\oneAPI\\bin\\intelocl64.dll']}
    cache = {'registry': lambda key, value = None: keys.get((key, value)),
             'windows': [{'class': 'Display', 'name': 'NVIDIA RTX', 'vendor': '10DE', 'driver': '32.0.16.1692', 'id': 'PCI\\VEN_10DE&DEV_1'},
                         {'class': 'Display', 'name': 'Virtual Monitor', 'vendor': '', 'driver': '', 'id': 'ROOT\\MON'},
                         {'class': 'ComputeAccelerator', 'name': 'Intel(R) NPU', 'vendor': '8086', 'driver': '', 'id': 'PCI\\VEN_8086'}]}
    win = dict(HOST, system = 'windows')

    spec = {'any': [{'pnp_driver_value': {'class': ['Display', 'SoftwareComponent'], 'value': 'OpenCLDriverName'}}]}
    out = mod['probe'](spec, win, cache)
    assert out['present'] and out['devices'] == ['NVIDIA RTX'] and out['versions'] == {'NVIDIA RTX': '32.0.16.1692'}

    # no driver of a present device names a Vulkan manifest, and the older list is not there
    spec = {'any': [{'pnp_driver_value': {'class': ['Display'], 'value': 'VulkanDriverName'}},
                    {'registry_values': 'SOFTWARE\\Khronos\\Vulkan\\Drivers'}]}
    assert not mod['probe'](spec, win, cache)['present']

    # the older list of the registry: its values are the drivers
    out = mod['probe']({'any': [{'registry_values': 'SOFTWARE\\Khronos\\OpenCL\\Vendors'}]}, win, cache)
    assert out['present'] and out['devices'] == ['intelocl64.dll']


def test_the_cpu_vendor(mod):
    spec = {'any': [{'cpu_vendor': ['GenuineIntel']}]}
    assert mod['probe'](spec, HOST, {'cpu_vendor': 'GenuineIntel'})['devices'] == ['CPU (GenuineIntel)']
    assert not mod['probe'](spec, HOST, {'cpu_vendor': 'AuthenticAMD'})['present']
    assert not mod['probe'](spec, HOST, {'cpu_vendor': ''})['present']


def test_android_devices_from_the_adb_server(mod):
    """The request host:devices-l on the server's socket, as adb itself sends it; nothing is started."""
    import socket
    import threading

    listing = ('EXAMPLE0SERIAL       device product:example model:Example_Tablet device:example transport_id:3\n'
               '192.168.1.7:5555     offline transport_id:4\n').encode()
    asked = []

    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn:
            n = int(conn.recv(4), 16)
            asked.append(conn.recv(n))
            conn.sendall(b'OKAY' + b'%04x' % len(listing) + listing)

    threading.Thread(target = serve, daemon = True).start()
    port = srv.getsockname()[1]
    devices = mod['adb_devices'](port = port)
    srv.close()

    assert asked == [b'host:devices-l']
    assert devices == [{'serial': 'EXAMPLE0SERIAL', 'state': 'device', 'product': 'example', 'model': 'Example_Tablet',
                        'device': 'example', 'transport_id': '3'},
                       {'serial': '192.168.1.7:5555', 'state': 'offline', 'transport_id': '4'}]

    # only a device that is ready counts; no adb server: no answer, no device
    out = mod['probe']({'any': [{'adb_devices': True}]}, HOST, {'adb': devices})
    assert out['present'] and out['devices'] == ['Example_Tablet (EXAMPLE0SERIAL)']
    assert mod['adb_devices'](port = port) is None
    assert not mod['probe']({'any': [{'adb_devices': True}]}, HOST, {'adb': None})['present']


def test_auto_takes_a_portable_interface_second_and_another_device_never(mod):
    choose = mod['choose']
    how = {'opencl': 'portable', 'vulkan': 'portable', 'openvino': 'portable', 'android-cpu': 'never'}
    here = ['android-cpu', 'cpu', 'cuda', 'opencl', 'openvino', 'vulkan']

    # an accelerator of the machine itself goes first, whatever interfaces lie over it
    assert choose(here, ['cpu', 'cuda', 'vulkan', 'opencl'], how) == ('cuda', ['cuda'])
    # none the program supports: one portable interface is taken, two are listed
    assert choose(here, ['cpu', 'vulkan'], how) == ('vulkan', ['vulkan'])
    assert choose(here, ['cpu', 'vulkan', 'opencl'], how) == (None, ['opencl', 'vulkan'])
    # an attached tablet is never the choice: the CPU of this machine
    assert choose(here, ['cpu', 'android-cpu'], how) == ('cpu', [])
    assert choose(here, ['android-cpu'], how) == (None, [])


def test_a_target_probed_for_the_first_time_is_no_change_of_the_machine(mod):
    old = {'cuda': {'present': True, 'devices': ['A500'], 'versions': {}}}
    new = {'cuda': {'present': True, 'devices': ['A500'], 'versions': {}},
           'vulkan': {'present': True, 'devices': ['A500'], 'versions': {}},
           'android-cpu': {'present': False, 'devices': [], 'versions': {}}}
    assert mod['CTask']._changes(old, new) == ['vulkan appeared']
    assert mod['CTask']._changes(old, dict(old, opencl = {'present': False, 'devices': [], 'versions': {}})) == ['other targets are probed']


def test_a_target_of_another_repository_probes_with_its_own_code(mod, tmp_path):
    """{script: probe.py}: probe(host) of a file of the target artifact - a private backend needs no change here."""
    target = tmp_path / 'target--acme-npu'
    target.mkdir()
    (target / 'probe.py').write_text(
        "def probe(host):\n"
        "    return {'present': True, 'devices': ['Acme NPU on ' + host['system']], 'versions': {'acme driver': 1.2}}\n",
        encoding = 'utf-8')
    spec = {'any': [{'script': 'probe.py'}]}

    out = mod['probe'](spec, HOST, {}, str(target))
    assert out['present'] and out['devices'] == ['Acme NPU on linux'] and out['versions'] == {'acme driver': '1.2'}
    assert 'error' not in out

    # its answer "not there"; and inside all: with a declared check
    (target / 'probe.py').write_text("def probe(host):\n    return {'present': False}\n", encoding = 'utf-8')
    assert not mod['probe'](spec, HOST, {}, str(target))['present']
    assert not mod['probe']({'any': [{'all': [{'always': True}, {'script': 'probe.py'}]}]}, HOST, {}, str(target))['present']

    # its own failure is its answer: the target is absent and says why - the other targets are still probed
    (target / 'probe.py').write_text("def probe(host):\n    raise RuntimeError('no such bus')\n", encoding = 'utf-8')
    out = mod['probe'](spec, HOST, {}, str(target))
    assert not out['present'] and out['error'] == 'probe.py: no such bus'
    (target / 'probe.py').write_text("def probe(host):\n    return 'yes'\n", encoding = 'utf-8')
    assert 'answered no dictionary' in mod['probe'](spec, HOST, {}, str(target))['error']

    # never a file outside the artifact, and never without the artifact's folder
    assert 'not a file of the target artifact' in mod['probe']({'any': [{'script': '../probe.py'}]}, HOST, {}, str(target))['error']
    assert 'not a file of the target artifact' in mod['probe'](spec, HOST, {})['error']


def test_a_pci_device_by_its_ids(mod, tmp_path):
    # the kernel's list of devices: a folder per device with its vendor and device ids (the driver is a link there)
    for slot, vendor, device in (('slot-a', '0xFFF0', '0x0001'), ('slot-b', '0x8086', '0xa7a0')):
        dev = tmp_path / 'devices' / slot
        dev.mkdir(parents = True)
        (dev / 'vendor').write_text(vendor + '\n')
        (dev / 'device').write_text(device + '\n')
    assert mod['pci_devices'](str(tmp_path / 'devices')) == [{'vendor': '0xfff0', 'device': '0x0001', 'driver': ''},
                                                              {'vendor': '0x8086', 'device': '0xa7a0', 'driver': ''}]

    cache = {'pci': [{'vendor': '0xfff0', 'device': '0x0001', 'driver': 'acme'},
                     {'vendor': '0x8086', 'device': '0xa7a0', 'driver': ''}]}
    out = mod['probe']({'any': [{'pci': {'vendor': ['0xFFF0']}}]}, HOST, cache)
    assert out['present'] and out['devices'] == ['0xfff0:0x0001 (acme)']
    assert not mod['probe']({'any': [{'pci': {'vendor': ['0xfff0'], 'device': ['0x0002']}}]}, HOST, cache)['present']
    assert not mod['probe']({'any': [{'pci': {'vendor': ['0xfff0'], 'drivers': ['other']}}]}, HOST, cache)['present']
    assert mod['probe']({'any': [{'pci': {'vendor': ['0x8086'], 'device': ['0xa7a0']}}]}, HOST, cache)['devices'] == ['0x8086:0xa7a0 (no driver)']


def test_windows_is_asked_for_the_device_classes_the_probes_name(mod):
    checks = [{'pnp': {'class': ['Display'], 'vendor': ['10DE']}},
              {'all': [{'pnp_driver_value': {'class': ['Display', 'SoftwareComponent'], 'value': 'OpenCLDriverName'}},
                       {'any': [{'pnp': {'class': ['System'], 'vendor': ['FFF0']}}]}]},
              {'glob': '/x'}]
    assert mod['classes_of'](checks) == {'Display', 'SoftwareComponent', 'System'}

    # no class named: Windows is not asked at all; a name that is no class name never reaches the command line
    assert mod['windows_devices']([]) == [] and mod['windows_devices'](["x'; Remove-Item y"]) == []

    # a target that names another class is matched like the others
    cache = {'windows': [{'class': 'System', 'name': 'Acme Accelerator', 'vendor': 'FFF0', 'driver': '', 'id': 'PCI\\VEN_FFF0'}]}
    out = mod['probe']({'any': [{'pnp': {'class': ['System'], 'vendor': ['fff0']}}]}, dict(HOST, system = 'windows'), cache)
    assert out['present'] and out['devices'] == ['Acme Accelerator']


def test_the_findings_are_kept_per_set_of_targets_probed():
    """A call that sees fewer repositories has its own findings: the name of its file is of the targets it probed."""
    src = (TASK / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "'targets-' + hashlib.sha256(','.join(sorted(probes)).encode('utf-8')).hexdigest()[:12] + '.json'" in src
    assert "'targets.json'" not in src

