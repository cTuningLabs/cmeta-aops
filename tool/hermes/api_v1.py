"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/hermes: install Hermes Agent with its official installer, downloaded first and then run, and register the
"hermes" command the installer publishes (a shim in ~/.local/bin, or %LOCALAPPDATA%\\hermes\\bin\\hermes.cmd on Windows).

Why a hook and not a plain install_cmd: the installer's last stage ("app products or command publication") builds
the desktop web UI with the Node it brought and fails on it (seen 2026-10-07 on Ubuntu 24.04 and Windows 11 with
release 2026.9.24: "Update follow-up 'build' did not finish: web UI build ... exited 1", "the next launch or
`hermes update` retries it") - and the installer then exits 1 although the CLI is complete and the shim is in place.
A plain install_cmd would take that exit code as a failed install. The hook runs the installer, then looks for the
shim: found, the install is good (the exit code is reported as a warning); not found, it is a failure.
"""

import os
import subprocess

INSTALL_SH = 'https://hermes-agent.nousresearch.com/install.sh'
INSTALL_PS1 = 'https://hermes-agent.nousresearch.com/install.ps1'
# non-interactive (no setup wizard, no gateway questions), without the browser tools and the computer-use driver
# (heavy; "hermes pm install agent-browser" adds them later)
INSTALL_FLAGS_SH = ['--non-interactive', '--skip-browser', '--skip-computer-use']
INSTALL_FLAGS_PS1 = ['-NonInteractive', '-SkipBrowser', '-SkipComputerUse']


def hermes_home(os_env):
    if os_env.get('HERMES_HOME'):
        return os_env['HERMES_HOME']
    if os.name == 'nt' and os_env.get('LOCALAPPDATA'):
        return os.path.join(os_env['LOCALAPPDATA'], 'hermes')
    return os.path.join(os.path.expanduser('~'), '.hermes')


def shim_candidates(uname, os_env):
    """Where the installer publishes the hermes command."""
    if uname == 'windows':
        return [os.path.join(hermes_home(os_env), 'bin', 'hermes.cmd'),
                os.path.join(os_env.get('LOCALAPPDATA', ''), 'hermes', 'bin', 'hermes.cmd')]
    return [os.path.join(os.path.expanduser('~'), '.local', 'bin', 'hermes'),
            os.path.join(hermes_home(os_env), 'bin', 'hermes')]


from tool_c393ba5c6fa14f66.api.ctool import InitCTool


class CTool(InitCTool):
    """Hermes Agent: the official installer, then the shim it publishes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']
        uname = _global['host']['os']['uname']
        os_env = _global['host'].get('os_env') or dict(os.environ)

        c = params.get('control', {})
        con = c.get('con', False)
        verbose = c.get('verbose', False)
        space = '  ' * ctx_tasks.get('nested_call', 0) if verbose else ''

        version_simple = params.get('version_simple')
        if params.get('version') and not version_simple:
            return {'return': 16, 'install_cmd': cmd,
                    'error': 'the hermes installer takes an exact release (--version=2026.9.24, a git tag), not a range'}

        # already published by an earlier installer run (its exit code hid it)? then nothing to do
        for shim in shim_candidates(uname, os_env):
            if os.path.isfile(shim):
                if con:
                    print(f'{space}INFO: Hermes Agent is already installed: {shim}')
                return {'return': 0, 'install_cmd': None, 'found_path': shim}

        directory = 'content'
        os.makedirs(os.path.join(os.getcwd(), directory), exist_ok=True)
        script_name = 'install-hermes.ps1' if uname == 'windows' else 'install-hermes.sh'
        url = INSTALL_PS1 if uname == 'windows' else INSTALL_SH
        script = os.path.join(os.getcwd(), directory, script_name)

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                            'ctx': ctx, 'url': url, 'directory': directory, 'filename': script_name,
                            'env': params.get('env'), 'timeout': params.get('timeout'),
                            'con': con, 'quiet': c.get('quiet', False), 'verbose': verbose})
        if r['return'] > 0 or not os.path.isfile(script):
            return {'return': 16, 'install_cmd': cmd, 'error': f'could not download the Hermes installer from {url}: {r.get("error", "")}'}

        if uname == 'windows':
            run_cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script] + INSTALL_FLAGS_PS1
            if version_simple:
                run_cmd += ['-Branch', 'v' + version_simple]
        else:
            run_cmd = ['bash', script] + INSTALL_FLAGS_SH
            if version_simple:
                run_cmd += ['--branch', 'v' + version_simple]

        if con:
            print('')
            print(f'{space}INFO: running the Hermes installer: {" ".join(run_cmd)}')
            print(f'{space}      (code and state go to {hermes_home(os_env)}; the command to {os.path.dirname(shim_candidates(uname, os_env)[0])})')
            print('')
        try:
            rc = subprocess.call(run_cmd, env=dict(os.environ, **(params.get('env') or {})))
        except Exception as e:
            return {'return': 16, 'install_cmd': cmd, 'error': f'cannot run the Hermes installer: {e}'}
        try:
            os.remove(script)
        except OSError:
            pass

        for shim in shim_candidates(uname, os_env):
            if os.path.isfile(shim):
                if con:
                    if rc != 0:
                        print('')
                        print(f'{space}WARNING: the Hermes installer exited with code {rc} after publishing the command (its last stage builds '
                              f'the desktop web UI and fails on some machines: "hermes update" retries it); the CLI is complete')
                    print(f'{space}INFO: Hermes Agent: {shim}')
                return {'return': 0, 'install_cmd': None, 'found_path': shim}

        return {'return': 16, 'install_cmd': None,
                'error': f'the Hermes installer exited with code {rc} and published no command in {" or ".join(shim_candidates(uname, os_env))}'}
