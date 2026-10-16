"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

tool/nvidia-container-toolkit, what the declarative _desc.yaml cannot say:

  1. customize_install_cmd(): on Linux, NVIDIA's package repository and its signing key first (the stable channel of
     nvidia.github.io/libnvidia-container), then the four packages of the version asked for (the default_version of
     _desc.yaml), each pinned - apt on Debian and Ubuntu, dnf / yum / zypper on the RPM distributions. Another OS is
     refused with the help text (Docker Desktop on Windows passes the GPU through WSL2 by itself).

  2. post_install(): the engines configured for the GPU - docker gets the "nvidia" runtime and is restarted, podman
     reads the CDI file of the GPUs. Without a passwordless sudo the commands are printed for the user (a quiet run
     never asks for a password).

  configured(engine): whether an engine is configured (get-host--docker asks it before a CUDA instance on Linux).
"""

import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

CDI_FILES = ('/etc/cdi/nvidia.yaml', '/var/run/cdi/nvidia.yaml', '/run/cdi/nvidia.yaml')


def _output(args, timeout=20):
    """The stdout of a short local command as text, '' when it cannot run (bytes decoded, never text=True)."""
    try:
        r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.decode('utf-8', errors='replace') if r.returncode == 0 else ''


def configured(engine):
    """
    Whether this Linux machine's engine can give a container the NVIDIA GPU: docker lists the "nvidia" runtime
    (nvidia-ctk runtime configure), podman finds a CDI file of the GPUs (nvidia-ctk cdi generate).
    """
    if engine == 'podman':
        return any(os.path.isfile(p) for p in CDI_FILES)
    return 'nvidia' in _output(['docker', 'info', '--format', '{{json .Runtimes}}'])


def _sudo():
    return '' if hasattr(os, 'geteuid') and os.geteuid() == 0 else 'sudo '


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize_install_cmd(self, ctx, install_cmd, params, env=None, timeout=None, uninstall_cmd=None):
        """The repository, the key and the pinned packages (see the module docstring)."""

        host = ctx['tasks']['global']['host']
        if host['os']['uname'] != 'linux':
            return self.cm.error('the NVIDIA Container Toolkit is for Linux engines (Docker Engine, podman); '
                                 'Docker Desktop on Windows passes the GPU itself')

        version = str(params.get('version') or self.cdesc['default_version']).strip()
        repo = self.cdesc['repository']
        packages = self.cdesc['packages']
        manager = str((host.get('os_extra') or {}).get('package_manager') or '')
        s = _sudo()

        if manager in ('apt', 'apt-get'):
            lines = [
                f"curl -fsSL {repo['key']} | {s}gpg --dearmor --yes -o {repo['keyring']}",
                f"curl -fsSL {repo['deb_list']} | sed 's#deb https://#deb [signed-by={repo['keyring']}] https://#g' "
                f"| {s}tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null",
                f'{s}apt-get update -q',
                f'{s}apt-get install -y -q ' + ' '.join(f'{p}={version}-1' for p in packages),
            ]
        elif manager in ('dnf', 'yum', 'tdnf'):
            lines = [
                f"curl -fsSL {repo['rpm_repo']} | {s}tee /etc/yum.repos.d/nvidia-container-toolkit.repo >/dev/null",
                f'{s}{manager} install -y ' + ' '.join(f'{p}-{version}-1' for p in packages),
            ]
        elif manager == 'zypper':
            lines = [
                f"{s}zypper --non-interactive --gpg-auto-import-keys ar {repo['rpm_repo']}",
                f'{s}zypper --non-interactive --gpg-auto-import-keys install ' + ' '.join(f'{p}={version}-1' for p in packages),
            ]
        else:
            return self.cm.error(f'no install route for the package manager "{manager or "unknown"}": '
                                 'see https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html')

        return {'return': 0, 'install_cmd': ' && '.join(lines)}

    ############################################################
    def post_install(self,
                     ctx: dict,
                     params: dict,
    ):
        """
        After the packages: docker and podman configured for the GPU (see the module docstring).
        """

        _global = ctx['tasks']['global']
        if _global['host']['os']['uname'] != 'linux' or (params.get('result') or {}).get('failed'):
            return {'return': 0}

        c = params.get('control', {})
        con = c.get('con', False)
        space = c.get('space', '')
        s = _sudo()

        todo = []
        for engine, cmds in (self.cdesc.get('configure') or {}).items():
            if not shutil.which(engine) or configured(engine):
                continue
            todo.append((engine, [s + x for x in cmds]))

        failed = []
        for engine, cmds in todo:
            # passwordless sudo only: a quiet run never waits for a password
            cmd = ' && '.join(x.replace('sudo ', 'sudo -n ', 1) if x.startswith('sudo ') else x for x in cmds)
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'cmd,c9ba0a88df394d7f', 'cmd': cmd, 'env': params.get('env'),
                                'con': con, 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False),
                                'text_cmd': 'RUN:', 'fail_if_nonzero_return_code': False})
            if self.cm.catch_error(r): return r
            if r.get('returncode', 1) != 0 or not configured(engine):
                failed.append((engine, cmds))
            elif con:
                print (f'{space}cMeta info: {engine} is configured for the NVIDIA GPU')

        if failed and con:
            print (f'{space}cMeta warning: not configured (sudo without a password?) - run it yourself:')
            for engine, cmds in failed:
                for x in cmds:
                    print (f'{space}               {x}')

        return {'return': 0}
