"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

tool/docker, two things the declarative _desc.yaml cannot say:

  1. install(): on macOS and Windows the Docker CLIENT from Docker's static release archives (install ladder tier 1),
     for a machine whose daemon runs elsewhere - colima or Docker Desktop on a Mac, an engine reached through a docker
     context or DOCKER_HOST. On Linux the distribution's package (engine + client) stays the route declared in
     _desc.yaml: install() steps aside there (return code 16, the declarative command untouched).

         https://download.docker.com/mac/static/stable/<aarch64|x86_64>/docker-<version>.tgz   (docker/docker inside)
         https://download.docker.com/win/static/stable/x86_64/docker-<version>.zip             (docker/docker.exe)

     Docker publishes no checksums for these archives: HTTPS only.

  2. post_install(): on Linux, after the package is in, the user goes into the "docker" group, so the socket works
     without sudo (the package creates the group but adds nobody). A new login applies it, which is said once.
     Nothing is done as root, for a user already in the group, or when the group does not exist; without a
     passwordless sudo the command is printed for the user instead (a quiet run never asks for a password).
"""

import os
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'docker',
        'url': 'https://download.docker.com/{os}/static/stable/{arch}/docker-{version}.{ext}',
        'os': {'darwin': 'mac', 'windows': 'win'},          # Linux: the package route of _desc.yaml
        'arch': {'arm64': 'aarch64', 'amd64': 'x86_64'},
        'ext': {'windows': 'zip', '*': 'tgz'},
        'member': 'docker/docker{exe}',
        'unsupported': [['windows', 'arm64']]}

GROUP = 'docker'


def _output(args):
    """The stdout of a short local command as text, '' when it cannot run (bytes decoded, never text=True)."""
    try:
        r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.decode('utf-8', errors='replace') if r.returncode == 0 else ''


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        macOS and Windows: the static Docker client of the pinned version. Linux: hands back the declarative
        package command (the engine and the client come together from the distribution).
        """

        # Linux: nothing to download - the declarative command (the package) runs as if there were no install() here
        if ctx['tasks']['global']['host']['os']['uname'] == 'linux':
            return {'return': 0, 'install_cmd': cmd}

        return install_release(self, ctx, params, cmd, SPEC)

    ############################################################
    def post_install(self,
                     ctx: dict,
                     params: dict,
    ):
        """
        Linux, after the package install: the user into the "docker" group (see the module docstring).
        """

        _global = ctx['tasks']['global']
        if _global['host']['os']['uname'] != 'linux' or (params.get('result') or {}).get('failed'):
            return {'return': 0}

        c = params.get('control', {})
        con = c.get('con', False)
        quiet = c.get('quiet', False)
        verbose = c.get('verbose', False)
        space = c.get('space', '')

        user = os.environ.get('USER') or os.environ.get('LOGNAME') or ''
        if not user or user == 'root':
            return {'return': 0}

        # The group must exist (the package makes it) and the user must not be in it yet
        if not _output(['getent', 'group', GROUP]).strip():
            return {'return': 0}
        if GROUP in _output(['id', '-nG', user]).split():
            return {'return': 0}

        cmd = f'sudo -n usermod -aG {GROUP} {user}'

        r = self.cm.access({'category': 'task,c36be4b9314a45e0',
                            'command': 'run',
                            'ctx': ctx,
                            'arg1': 'cmd,c9ba0a88df394d7f',
                            'cmd': cmd,
                            'env': params.get('env'),
                            'con': con,
                            'quiet': quiet,
                            'verbose': verbose,
                            'text_cmd': 'RUN:',
                            'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(r): return r

        if con:
            print ('')
            if r.get('returncode', 1) == 0:
                print (f'{space}cMeta info: {user} is now in the "{GROUP}" group: log in again (or run "newgrp {GROUP}") before using docker without sudo')
            else:
                print (f'{space}cMeta warning: could not add {user} to the "{GROUP}" group (sudo without a password?). Run it yourself, then log in again:')
                print (f'{space}               sudo usermod -aG {GROUP} {user}')

        return {'return': 0}
