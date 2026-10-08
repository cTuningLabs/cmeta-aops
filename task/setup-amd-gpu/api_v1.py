"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import shutil
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

AMD_GPU_VENDOR = '0x1002'       # AMD/ATI graphics
AMD_NPU_DRIVER = 'amdxdna'      # the kernel driver of the Ryzen AI NPUs (drivers/accel/amdxdna)
MEMLOCK_CONF = '/etc/security/limits.d/90-amd-npu-memlock.conf'
UNLIMITED = -1                  # resource.RLIM_INFINITY


def truthy(value):
    """The engine hands CLI booleans over as strings."""
    return value is True or str(value).strip().lower() in ('true', '1', 'yes', 'on')


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def find_devices(sys_root = '/sys', dev_root = '/dev'):
    """
    The AMD compute devices that have a kernel driver and a device node:
    gpus  [{node: /dev/dri/renderD128, pci, device, driver}]  from /sys/class/drm/renderD*
    kfd   /dev/kfd when a GPU is there and the node exists (the interface of ROCm)
    npus  [{node: /dev/accel/accel0, pci, device, revision, fw_version, vbnv}]  from /sys/class/accel
    """
    gpus, npus = [], []
    for d in sorted(glob.glob(os.path.join(sys_root, 'class', 'drm', 'renderD*'))):
        dev = os.path.join(d, 'device')
        if (_read(os.path.join(dev, 'vendor')) or '').lower() != AMD_GPU_VENDOR:
            continue
        gpus.append({'node': os.path.join(dev_root, 'dri', os.path.basename(d)),
                     'pci': os.path.basename(os.path.realpath(dev)),
                     'device': _read(os.path.join(dev, 'device')),
                     'driver': os.path.basename(os.path.realpath(os.path.join(dev, 'driver')))})
    for d in sorted(glob.glob(os.path.join(sys_root, 'class', 'accel', 'accel*'))):
        dev = os.path.join(d, 'device')
        if os.path.basename(os.path.realpath(os.path.join(dev, 'driver'))) != AMD_NPU_DRIVER:
            continue
        npu = {'node': os.path.join(dev_root, 'accel', os.path.basename(d)),
               'pci': os.path.basename(os.path.realpath(dev)),
               'device': _read(os.path.join(dev, 'device')),
               'revision': _read(os.path.join(dev, 'revision'))}
        for key in ('fw_version', 'vbnv'):
            value = _read(os.path.join(dev, key))
            if value:
                npu[key] = value
        npus.append(npu)
    kfd = os.path.join(dev_root, 'kfd')
    return {'gpus': gpus, 'kfd': kfd if gpus and os.path.exists(kfd) else None, 'npus': npus}


def nodes_of(devices, npu = True):
    """The device nodes a compute run opens."""
    nodes = [g['node'] for g in devices['gpus']]
    if devices.get('kfd'):
        nodes.append(devices['kfd'])
    if npu:
        nodes += [n['node'] for n in devices['npus']]
    return nodes


def plan(devices, access, node_groups, user, user_groups, existing_groups, memlock, have_setfacl,
         memlock_conf_exists, pid, npu = True):
    """
    The steps that are missing, in order: (name, command, needs_sudo, kind) - kind is "lasting"
    (holds from the next login on) or "now" (for the running session).

    access              {node: True when the user can open it for reading and writing now}
    node_groups         {node: the group that owns it}
    user_groups         the groups of the user in the group database (what a new login gets)
    existing_groups     the groups the system has
    memlock             (soft, hard) limit of locked memory of this process in bytes, UNLIMITED = -1
    """
    steps = []
    nodes = nodes_of(devices, npu)

    wanted = {node_groups[n] for n in nodes if node_groups.get(n)}
    if devices['gpus'] and 'video' in existing_groups:
        wanted.add('video')
    missing = sorted(g for g in wanted if g not in user_groups and g != 'root')
    if missing:
        steps.append(('groups', f'usermod -aG {",".join(missing)} {user}', True, 'lasting'))

    closed = [n for n in nodes if not access.get(n)]
    if closed and have_setfacl:
        steps.append(('access', f'setfacl -m u:{user}:rw {" ".join(closed)}', True, 'now'))

    if npu and devices['npus'] and tuple(memlock) != (UNLIMITED, UNLIMITED):
        if not memlock_conf_exists:
            text = ('# The AMD NPU runtime (XRT) locks its buffers in memory: no limit for this user (cMeta setup-amd-gpu).\\n'
                    f'{user}  -  memlock  unlimited\\n')
            steps.append(('memlock', f"sh -c \"printf '{text}' > {MEMLOCK_CONF}\"", True, 'lasting'))
        steps.append(('memlock-now', f'prlimit --pid {pid} --memlock=unlimited:unlimited', True, 'now'))
    return steps


def with_sudo(cmd, needs_sudo, interactive):
    """sudo in front of a system command: "-n" (never a hidden prompt) unless the run is interactive."""
    if not needs_sudo:
        return cmd
    return ('sudo ' if interactive else 'sudo -n ') + cmd


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            check: bool = False,        # Only report what is there and what is missing
            dry_run: bool = False,      # Print the commands, run nothing
            npu: bool = True,           # Also the AMD NPU: its node and the memory-lock limit (--npu- skips it)
            user: str = None,           # Another user than the one who runs this
            timeout: int = None,
            env: dict = None,
    ):

        """
        Make a Linux machine ready to compute on its AMD GPU and NPU: the user's access to the device
        nodes and the memory-lock limit of the NPU runtime.

            cx task run setup-amd-gpu
            cx task run setup-amd-gpu --check
            cx task run setup-amd-gpu --dry_run

        Returns: devices {gpus, kfd, npus}, access {node: bool} (after the run), steps [{name, cmd, kind,
        returncode}], changed, ready (every node can be opened and, with an NPU, memory can be locked),
        relogin (True when only a new login makes it ready), and return 1 when a step failed.
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        check, dry_run, npu = truthy(check), truthy(dry_run), truthy(npu)

        uname = ctx['tasks']['global']['host']['os']['uname']
        result = {'return': 0, 'devices': {'gpus': [], 'kfd': None, 'npus': []}, 'access': {}, 'steps': [],
                  'changed': False, 'ready': False, 'relogin': False}
        if uname != 'linux':
            result['skipped'] = ('the AMD graphics driver brings everything on Windows' if uname == 'windows'
                                 else 'AMD GPU and NPU compute needs Linux or Windows')
            if con and verbose:
                print(f'setup-amd-gpu: nothing to do on {uname}: {result["skipped"]}')
            return result

        import grp
        import pwd
        import resource

        if not user:
            user = pwd.getpwuid(os.getuid()).pw_name
        root = os.geteuid() == 0
        interactive = (not quiet) and sys.stdin.isatty()

        devices = find_devices()
        result['devices'] = devices
        nodes = nodes_of(devices, npu)
        if not nodes:
            if con:
                print('setup-amd-gpu: no AMD GPU or NPU with a kernel driver here (amdgpu: /sys/class/drm/renderD*, amdxdna: /sys/class/accel)')
            return result

        def look():
            return {n: os.access(n, os.R_OK | os.W_OK) for n in nodes}

        def memlock_ok():
            return not (npu and devices['npus']) or resource.getrlimit(resource.RLIMIT_MEMLOCK) == (UNLIMITED, UNLIMITED)

        access = look()
        node_groups = {}
        for n in nodes:
            try:
                node_groups[n] = grp.getgrgid(os.stat(n).st_gid).gr_name
            except (OSError, KeyError):
                pass
        try:
            pw = pwd.getpwnam(user)
            user_groups = {grp.getgrgid(g).gr_name for g in os.getgrouplist(user, pw.pw_gid)}
        except KeyError:
            return self.cm.error(f'user "{user}" is not known on this machine')

        steps = [] if root else plan(devices, access, node_groups, user, user_groups, {g.gr_name for g in grp.getgrall()},
                                     resource.getrlimit(resource.RLIMIT_MEMLOCK), shutil.which('setfacl') is not None,
                                     os.path.isfile(MEMLOCK_CONF), os.getpid(), npu = npu)

        if con:
            what = [f'GPU {g["pci"]} ({g["driver"]})' for g in devices['gpus']] + [f'NPU {n["pci"]} ({n.get("vbnv") or AMD_NPU_DRIVER})' for n in devices['npus']]
            print(f'setup-amd-gpu: {", ".join(what)}; user {user}')
            for n in nodes:
                print(f'  {n:24} group {node_groups.get(n, "?"):8} {"open" if access[n] else "NO ACCESS"}')
            if npu and devices['npus']:
                print(f'  locked memory            {"unlimited" if memlock_ok() else "limited: the NPU runtime needs it unlimited"}')

        if check or dry_run or not steps:
            result['steps'] = [{'name': n, 'cmd': with_sudo(c, s, interactive), 'kind': k, 'returncode': None} for n, c, s, k in steps]
            result['access'] = access
            result['ready'] = all(access.values()) and memlock_ok()
            if con:
                if steps:
                    print('setup-amd-gpu: missing' + (' (nothing was changed):' if check or dry_run else ':'))
                    for s in result['steps']:
                        print(f'  {s["name"]:12} {s["cmd"]}   # {s["kind"]}')
                else:
                    print('setup-amd-gpu: ready, nothing to do')
            return result

        failed = []
        for name, cmd, needs_sudo, kind in steps:
            line = with_sudo(cmd, needs_sudo, interactive)
            if con:
                print(f'=== setup-amd-gpu: {name}: {line}')
                sys.stdout.flush()
            rr = self.cm.utils.sys.run(line, capture_output = not con, con = con, verbose = verbose, print_cmd = False,
                                       fail_on_error = False, timeout = timeout, env = env, logger = self.logger)
            rc = rr.get('returncode', 0)
            result['steps'].append({'name': name, 'cmd': line, 'kind': kind, 'returncode': rc})
            if rc != 0:
                failed.append(name)
            else:
                result['changed'] = True

        result['access'] = look()
        result['ready'] = all(result['access'].values()) and memlock_ok()
        # The groups are in place but this session cannot use them yet, and the ACL could not help
        result['relogin'] = (not result['ready']) and not any(f in ('groups', 'memlock') for f in failed)

        if failed:
            lines = '\n'.join('  ' + s['cmd'].replace('sudo -n ', 'sudo ') for s in result['steps'] if s['returncode'] != 0)
            hint = ('sudo needs a password here: run these in a terminal, then run again' if not interactive
                    else 'these commands failed')
            return self.cm.error(f'setup-amd-gpu could not finish ({", ".join(failed)}): {hint}:\n{lines}')
        if con:
            if result['ready']:
                print('setup-amd-gpu: ready' + (' (the groups hold from the next login; this session got the devices through an ACL)'
                                                if any(s['name'] == 'groups' for s in result['steps']) else ''))
            else:
                print('setup-amd-gpu: set up, but this session cannot use it yet - log in again (the new groups and limits apply to new logins)')
        return result
