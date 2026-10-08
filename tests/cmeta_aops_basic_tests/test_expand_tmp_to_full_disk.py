"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/expand-tmp-to-full-disk (/tmp moved from a tmpfs to the disk): the mount of /tmp
read from /proc/mounts, the tmpfs lines of /etc/fstab, and the plan for systemd's unit, an fstab entry,
a /tmp on its own partition and a /tmp on the root filesystem.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

UBUNTU_MOUNTS = """\
/dev/sda2 / ext4 rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid,nodev,size=1510788k,mode=755,inode64 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev,size=7553924k,nr_inodes=1048576,inode64,usrquota 0 0
/dev/sda1 /boot/efi vfat rw,relatime 0 0
"""


@pytest.fixture(scope = "module")
def mod():
    path = REPO_ROOT / "task" / "expand-tmp-to-full-disk" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "expand_tmp", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_the_mount_of_tmp(mod):
    m = mod["tmp_mount"](UBUNTU_MOUNTS)
    assert m['fstype'] == 'tmpfs' and m['source'] == 'tmpfs' and 'usrquota' in m['options'] and 'size=7553924k' in m['options']
    assert mod["tmp_mount"]("/dev/sda2 / ext4 rw 0 0\n") is None                     # a folder of the root filesystem
    assert mod["tmp_mount"]("/dev/sdb1 /tmp ext4 rw,relatime 0 0\n")['fstype'] == 'ext4'   # its own partition
    # the last mount on /tmp counts (mounts stack)
    stacked = "tmpfs /tmp tmpfs rw 0 0\n/dev/sdb1 /tmp ext4 rw 0 0\n"
    assert mod["tmp_mount"](stacked)['fstype'] == 'ext4'


def test_the_tmpfs_lines_of_fstab(mod):
    fstab = "# /etc/fstab\nUUID=1 / ext4 defaults 0 1\n#tmpfs /tmp tmpfs defaults 0 0\ntmpfs  /tmp  tmpfs  defaults,size=2G  0  0\ntmpfs /dev/shm tmpfs defaults 0 0\n"
    assert mod["fstab_tmpfs_lines"](fstab) == [4]
    assert mod["fstab_tmpfs_lines"]("UUID=1 / ext4 defaults 0 1\n") == []


def test_the_plan_for_systemd_unit(mod):
    m = mod["tmp_mount"](UBUNTU_MOUNTS)
    steps = mod["plan"](m, unit_active = True, fstab_lines = [])
    assert [(s[0], s[1], s[3]) for s in steps] == [('mask', 'systemctl mask tmp.mount', 'lasting'), ('unmount', 'systemctl stop tmp.mount', 'now')]
    assert all(s[2] for s in steps)


def test_the_plan_for_an_fstab_entry(mod):
    m = mod["tmp_mount"](UBUNTU_MOUNTS)
    steps = mod["plan"](m, unit_active = False, fstab_lines = [4])
    assert [s[0] for s in steps] == ['fstab', 'unmount']
    assert steps[0][1] == "sed -i.cmeta-backup '4s/^/#/' /etc/fstab" and steps[1][1] == 'umount /tmp'


def test_nothing_when_tmp_is_on_a_disk(mod):
    assert mod["plan"](None, unit_active = False, fstab_lines = []) == []
    assert mod["plan"]({'source': '/dev/sdb1', 'fstype': 'ext4', 'options': []}, unit_active = False, fstab_lines = []) == []


def test_sudo_never_waits_at_a_hidden_prompt(mod):
    assert mod["with_sudo"]('umount /tmp', True, False) == 'sudo -n umount /tmp'
    assert mod["with_sudo"]('umount /tmp', True, True) == 'sudo umount /tmp'
    assert mod["with_sudo"]('umount /tmp', False, True) == 'umount /tmp'
