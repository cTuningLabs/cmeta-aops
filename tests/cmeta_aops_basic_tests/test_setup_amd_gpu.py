"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/setup-amd-gpu (a Linux machine made ready for its AMD GPU and NPU): the devices
found in a fake /sys, and the plan of missing steps for a fresh account, a desktop login, a ready
machine, a machine without setfacl, and with the NPU left out.
"""

import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
UNLIMITED = (-1, -1)
DEFAULT_LIMIT = (8388608, 8388608)


@pytest.fixture(scope = "module")
def mod():
    path = REPO_ROOT / "task" / "setup-amd-gpu" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "setup_amd_gpu", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def fake_sys(root, gpu_vendor = '0x1002', npu_driver = 'amdxdna'):
    """A /sys with one render node and one accel node, as on a Ryzen AI laptop."""
    if os.name == 'nt':
        pytest.skip('PCI addresses have colons, which a Windows file name cannot have')
    pci = root / 'devices' / 'pci0000:00'
    gpu, npu = pci / '0000:c2:00.0', pci / '0000:c3:00.1'
    for dev, files in ((gpu, {'vendor': gpu_vendor, 'device': '0x1114'}),
                       (npu, {'vendor': '0x1022', 'device': '0x17f0', 'revision': '0x20', 'fw_version': '1.1.2.64', 'vbnv': 'RyzenAI-npu6'})):
        dev.mkdir(parents = True)
        for name, text in files.items():
            (dev / name).write_text(text + '\n')
    drivers = root / 'bus' / 'pci' / 'drivers'
    for name in ('amdgpu', npu_driver):
        (drivers / name).mkdir(parents = True)
    try:
        os.symlink(drivers / 'amdgpu', gpu / 'driver')
        os.symlink(drivers / npu_driver, npu / 'driver')
        (root / 'class' / 'drm' / 'renderD128').mkdir(parents = True)
        os.symlink(gpu, root / 'class' / 'drm' / 'renderD128' / 'device')
        (root / 'class' / 'accel' / 'accel0').mkdir(parents = True)
        os.symlink(npu, root / 'class' / 'accel' / 'accel0' / 'device')
    except OSError:
        pytest.skip('symbolic links are not available here')


def test_devices_from_sysfs(mod, tmp_path):
    fake_sys(tmp_path / 'sys')
    (tmp_path / 'dev').mkdir()
    (tmp_path / 'dev' / 'kfd').write_text('')
    d = mod["find_devices"](str(tmp_path / 'sys'), str(tmp_path / 'dev'))
    assert [g['node'] for g in d['gpus']] == [os.path.join(str(tmp_path / 'dev'), 'dri', 'renderD128')]
    assert d['gpus'][0]['pci'] == '0000:c2:00.0' and d['gpus'][0]['driver'] == 'amdgpu' and d['gpus'][0]['device'] == '0x1114'
    assert d['kfd'] == os.path.join(str(tmp_path / 'dev'), 'kfd')
    assert d['npus'][0]['node'] == os.path.join(str(tmp_path / 'dev'), 'accel', 'accel0')
    assert d['npus'][0]['fw_version'] == '1.1.2.64' and d['npus'][0]['vbnv'] == 'RyzenAI-npu6' and d['npus'][0]['revision'] == '0x20'
    assert len(mod["nodes_of"](d)) == 3 and len(mod["nodes_of"](d, npu = False)) == 2


def test_other_vendors_are_not_taken(mod, tmp_path):
    fake_sys(tmp_path / 'sys', gpu_vendor = '0x10de', npu_driver = 'intel_vpu')
    d = mod["find_devices"](str(tmp_path / 'sys'), str(tmp_path / 'dev'))
    assert d == {'gpus': [], 'kfd': None, 'npus': []}


DEVICES = {'gpus': [{'node': '/dev/dri/renderD128'}], 'kfd': '/dev/kfd', 'npus': [{'node': '/dev/accel/accel0'}]}
NODES = ['/dev/dri/renderD128', '/dev/kfd', '/dev/accel/accel0']
GROUPS = {n: 'render' for n in NODES}
SYSTEM_GROUPS = {'render', 'video', 'users', 'sudo'}


def plan(mod, access, user_groups, memlock, setfacl = True, conf = False, npu = True, devices = DEVICES):
    return mod["plan"](devices, {n: access for n in NODES} if isinstance(access, bool) else access, GROUPS, 'fursin',
                       set(user_groups), SYSTEM_GROUPS, memlock, setfacl, conf, 4242, npu = npu)


def test_a_fresh_account_over_ssh(mod):
    steps = plan(mod, False, {'users', 'sudo'}, DEFAULT_LIMIT)
    assert [(s[0], s[3]) for s in steps] == [('groups', 'lasting'), ('access', 'now'), ('memlock', 'lasting'), ('memlock-now', 'now')]
    assert steps[0][1] == 'usermod -aG render,video fursin'
    assert steps[1][1] == 'setfacl -m u:fursin:rw /dev/dri/renderD128 /dev/kfd /dev/accel/accel0'
    assert '90-amd-npu-memlock.conf' in steps[2][1] and 'fursin  -  memlock  unlimited' in steps[2][1]
    assert steps[3][1] == 'prlimit --pid 4242 --memlock=unlimited:unlimited'
    assert all(s[2] for s in steps)                                 # every step needs root


def test_a_desktop_login_has_the_nodes_but_not_the_groups(mod):
    # The seat's ACL opens the nodes for the logged-in user: only the lasting part is missing
    steps = plan(mod, True, {'users'}, DEFAULT_LIMIT, conf = True)
    assert [s[0] for s in steps] == ['groups', 'memlock-now']


def test_a_ready_machine_needs_nothing(mod):
    assert plan(mod, True, {'users', 'render', 'video'}, UNLIMITED) == []


def test_groups_in_place_but_an_old_login(mod):
    # The user was added to the groups, this login is older: only the ACL for now
    steps = plan(mod, False, {'render', 'video'}, UNLIMITED)
    assert [s[0] for s in steps] == ['access']


def test_without_setfacl_only_the_lasting_steps(mod):
    steps = plan(mod, False, {'users'}, UNLIMITED, setfacl = False)
    assert [s[0] for s in steps] == ['groups']


def test_the_npu_left_out(mod):
    steps = plan(mod, False, {'users'}, DEFAULT_LIMIT, npu = False)
    assert [s[0] for s in steps] == ['groups', 'access']
    assert '/dev/accel/accel0' not in steps[1][1]


def test_an_npu_alone_asks_for_render_only(mod):
    devices = {'gpus': [], 'kfd': None, 'npus': [{'node': '/dev/accel/accel0'}]}
    steps = plan(mod, False, {'users'}, DEFAULT_LIMIT, devices = devices)
    assert steps[0][1] == 'usermod -aG render fursin'               # "video" is for the GPU


def test_sudo_never_waits_at_a_hidden_prompt(mod):
    assert mod["with_sudo"]('usermod -aG render x', True, False) == 'sudo -n usermod -aG render x'
    assert mod["with_sudo"]('usermod -aG render x', True, True) == 'sudo usermod -aG render x'
    assert mod["with_sudo"]('true', False, False) == 'true'
