"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            hostname: str = '',     # Linux: the machine's name in the tailnet (default: its hostname)
            operator: str = '',     # Linux: the user who may run "tailscale" without sudo (default: this user)
            timeout: str = '600',   # Linux: seconds to wait for the login in the browser
    ):

        """
        Start the Tailscale service: Linux - tailscaled at every boot (systemd) and, when this machine is not logged
        in yet, "tailscale up" (it prints the login link to open in a browser); macOS - brew services.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK start-tailscale-service run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        path_to_tailscale = ctx['tasks']['global']['tailscale']['qpath']

        if uname == 'linux':
            return self._linux(ctx['tasks']['global']['tailscale'].get('path') or 'tailscale', con, quiet,
                               hostname, operator, timeout)

        if con and not quiet:
            print ('')
            print ('WARNING: make sure that you run start-tailscale-service in the Desktop terminal since it may open browser to log in to tailscale!')
            print ('')
            from task_c36be4b9314a45e0.api.ctask import ask as ask_user
            ask_user('Press Enter to continue: ', optional = True)      # a pause to read the warning: nobody there, no pause

        cmd = 'sudo brew services start tailscale'

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
              'env': env,
              'con': con, 
              'quiet': quiet,
              'verbose': verbose, 
              'quiet': quiet,
              'text_cmd': 'RUN:',
#              'print_env_keys': [], 
              'print_extra_line': True,
              'fail_if_nonzero_return_code': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return rx

    ############################################################
    def _linux(self, tailscale, con, quiet, hostname, operator, timeout):
        """tailscaled enabled and started (systemd), then logged in once: "tailscale up" prints the link to open in a
        browser and waits for it. A machine logged in already only has its service checked."""
        import json
        import socket
        import subprocess

        sudo = [] if os.geteuid() == 0 else (['sudo', '-n'] if quiet else ['sudo'])

        def say(text):
            if con:
                print(text)

        def state():
            p = subprocess.run([tailscale, 'status', '--json'], stdin = subprocess.DEVNULL, stdout = subprocess.PIPE,
                               stderr = subprocess.DEVNULL)
            try:
                return json.loads(p.stdout.decode('utf-8', 'replace'))
            except ValueError:
                return {}

        rc = subprocess.call(sudo + ['systemctl', 'enable', '--now', 'tailscaled'], stdin = subprocess.DEVNULL)
        if rc != 0:
            return {'return': 1, 'error': 'systemctl enable --now tailscaled failed (is the tailscale package installed? '
                                          'cx tool install tailscale)'}

        s = state()
        if s.get('BackendState') != 'Running':
            words = sudo + [tailscale, 'up', '--operator=' + (operator or os.environ.get('USER') or 'root'),
                            '--hostname=' + (hostname or socket.gethostname()), '--timeout=%ss' % int(timeout or 600)]
            say('Tailscale: this machine is not logged in - open the link "tailscale up" prints in a browser, sign in, '
                'and approve the machine: ' + ' '.join(words))
            rc = subprocess.call(words, stdin = subprocess.DEVNULL)
            s = state()
            if rc != 0 or s.get('BackendState') != 'Running':
                return {'return': 1, 'error': f'Tailscale is not logged in (state {s.get("BackendState") or "unknown"}): '
                                              f'run this task again in a terminal and open the link it prints'}

        me = s.get('Self') or {}
        address = (me.get('TailscaleIPs') or [''])[0]
        name = (me.get('DNSName') or '').rstrip('.')
        say(f'Tailscale is up: {name or me.get("HostName", "?")} {address} (tailscaled starts at every boot)')
        return {'return': 0, 'address': address, 'dns_name': name, 'hostname': me.get('HostName')}

