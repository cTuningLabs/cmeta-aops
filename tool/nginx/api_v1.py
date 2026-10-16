"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

tool/nginx, what the declarative _desc.yaml cannot say:

  1. install(): on Windows the official zip of nginx.org (windows_zip of _desc.yaml), unpacked whole into the entry's
     content/ folder - nginx.exe runs with conf/, html/, logs/ and temp/ next to it. Elsewhere the declarative command
     (the distribution's package, Homebrew) runs as if there were no install() here.

  2. post_install(): on Linux with systemd, the service enabled and started after the package (the RPM packages do
     not start it; the Debian one does). Without a passwordless sudo the commands are printed for the user.
"""

import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


def start_services(tool, ctx, params, names):
    """systemctl enable --now <the first unit of names that exists>, through sudo -n; the commands said otherwise."""
    _global = ctx['tasks']['global']
    if _global['host']['os']['uname'] != 'linux' or (params.get('result') or {}).get('failed') or not shutil.which('systemctl'):
        return {'return': 0}
    if not os.path.isdir('/run/systemd/system'):
        return {'return': 0}                       # a container or a system without systemd as init

    c = params.get('control', {})
    con = c.get('con', False)
    space = c.get('space', '')
    for unit in names:
        r = subprocess.run(['systemctl', 'cat', unit], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        if r.returncode != 0:
            continue
        s = '' if hasattr(os, 'geteuid') and os.geteuid() == 0 else 'sudo -n '
        r = subprocess.run((s + f'systemctl enable --now {unit}').split(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if con:
            print ('')
            if r.returncode == 0:
                print (f'{space}cMeta info: the service {unit} is enabled and running (systemctl status {unit})')
            else:
                print (f'{space}cMeta warning: the service {unit} was not started (sudo without a password?): '
                       f'sudo systemctl enable --now {unit}')
        break
    return {'return': 0}


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """Windows: the zip of nginx.org, whole; elsewhere the declarative command."""

        _global = ctx['tasks']['global']
        if _global['host']['os']['uname'] != 'windows':
            return {'return': 0, 'install_cmd': cmd}

        c = params.get('control', {})
        version = str(params.get('version') or self.cdesc['default_version'])
        url = self.cdesc['windows_zip'].format(version = version)
        path = os.path.join(os.getcwd(), 'content', 'nginx.exe')

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                            'ctx': ctx, 'url': url, 'directory': 'content', 'env': params.get('env'),
                            'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False),
                            'unzip': True, 'clean': True, 'clean_after_unzip': True, 'strip_folders': 1,
                            'check_file': path})
        if self.cm.catch_error(r): return r

        # nginx refuses to start without these folders next to it (the zip carries logs/ and temp/ empty, or not at all)
        for d in ('logs', 'temp'):
            os.makedirs(os.path.join(os.getcwd(), 'content', d), exist_ok = True)

        return {'return': 0, 'install_cmd': None, 'found_path': path, 'version': version}

    ############################################################
    def post_install(self, ctx, params):
        """Linux: the service enabled and started (see the module docstring)."""
        return start_services(self, ctx, params, (self.cdesc.get('services') or {}).get('nginx') or ['nginx'])
