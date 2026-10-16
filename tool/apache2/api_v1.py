"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

tool/apache2, what the declarative _desc.yaml cannot say:

  post_install(): on Linux with systemd, the service enabled and started after the package - apache2 on Debian and
  Ubuntu (its package starts it already), httpd on the RPM distributions (theirs do not). Without a passwordless sudo
  the command is printed for the user. In a container (no systemd as init) nothing is done.
"""

import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def post_install(self, ctx, params):
        """Linux: the first of the service names that systemd knows, enabled and started (see the module docstring)."""

        _global = ctx['tasks']['global']
        if _global['host']['os']['uname'] != 'linux' or (params.get('result') or {}).get('failed') or not shutil.which('systemctl'):
            return {'return': 0}
        if not os.path.isdir('/run/systemd/system'):
            return {'return': 0}

        c = params.get('control', {})
        con = c.get('con', False)
        space = c.get('space', '')
        for unit in (self.cdesc.get('services') or {}).get('apache2') or ['apache2', 'httpd']:
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
                    print (f'{space}cMeta warning: the service {unit} was not started (sudo without a password? port 80 taken?): '
                           f'sudo systemctl enable --now {unit}')
            break
        return {'return': 0}
