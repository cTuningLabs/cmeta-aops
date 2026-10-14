"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import base64
import getpass
import json
import os
import platform
import shlex
import shutil
import sys
import uuid

from task_c36be4b9314a45e0.api.ctask import InitCTask


def switch(value):
    """CLI switches can be native booleans or strings, including --feature- ."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    word = str(value).lower()
    if word in ('true', '1', 'yes', 'on'):
        return True
    if word in ('false', '0', 'no', 'off', ''):
        return False
    raise ValueError('Expected yes/no or true/false, got {!r}'.format(value))


def selection(desc, profile, overrides):
    if profile not in desc['profiles']:
        raise ValueError('Unknown profile: ' + profile)
    return {name: name in desc['profiles'][profile] if value is None else switch(value)
            for name, value in overrides.items()}


def ask_yes(question, default=False):
    while True:
        answer = input('cMeta info: ' + question + (' [Y/n] ' if default else ' [y/N] ')).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes', 'n', 'no'):
            return answer in ('y', 'yes')
        print('cMeta info: Please answer yes or no.')


def powershell_command(script, config):
    """Only encoded data crosses cmd.exe; values cannot become shell syntax."""
    data = base64.b64encode(json.dumps(config).encode('utf-8')).decode('ascii')
    source = "& '{}' -Data '{}'".format(str(script).replace("'", "''"), data)
    encoded = base64.b64encode(source.encode('utf-16-le')).decode('ascii')
    exe = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                       'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    return '"{}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {}'.format(exe, encoded)


def validate_unlock(options):
    for name in ('volume_guid', 'persistent_id', 'protector_id'):
        if not options.get(name):
            raise ValueError('boot_unlock requires --' + name)
        options[name] = str(uuid.UUID(str(options[name]).strip('{}')))
    drive = str(options.get('drive', '')).rstrip('\\/').upper()
    if len(drive) != 2 or not drive[0].isalpha() or drive[1] != ':':
        raise ValueError('boot_unlock requires --drive=D: (the expected data-volume letter)')
    if drive == os.environ.get('SystemDrive', 'C:').upper():
        raise ValueError('boot_unlock must target a data volume, not the OS volume')
    options['drive'] = drive


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def _command(self, command, timeout=60):
        result = self.cm.utils.sys.run(command, capture_output=True, con=False, timeout=timeout,
                                       fail_on_error=False, logger=self.logger)
        if result.get('return', 0) or result.get('returncode', -1):
            raise RuntimeError((result.get('stderr') or result.get('stdout') or
                                result.get('error') or 'Command failed').strip())
        return (result.get('stdout') or '').strip()

    def _windows(self, config, timeout=60):
        command = powershell_command(os.path.join(self.module_path, 'scripts', 'windows.ps1'), config)
        output = self._command(command, timeout)
        # PowerShell's native tools may print informational lines before our JSON marker.
        return json.loads(output.split('CMETA_RESULT=', 1)[1])

    def _unix_inventory(self, system):
        state = {'ssh': {}, 'tailscale': {}, 'keep_awake': {}}
        commands = {'Linux': ['systemctl', 'show', '--property=LoadState,ActiveState,UnitFileState'],
                    'Darwin': ['launchctl', 'print', 'system/com.openssh.sshd']}
        for name in ('ssh', 'tailscale', 'keep_awake'):
            if system == 'Linux':
                units = (self.cdesc['linux']['ssh_services'] if name == 'ssh' else
                         [self.cdesc['linux']['tailscale_service']] if name == 'tailscale' else
                         ['sleep.target', 'suspend.target', 'hibernate.target', 'hybrid-sleep.target'])
                state[name] = {'units': {}}
                for unit in units:
                    try:
                        text = self._command(shlex.join(commands['Linux'] + [unit]), 15)
                        state[name]['units'][unit] = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
                    except RuntimeError as exc:
                        state[name]['units'][unit] = {'error': str(exc)}
            else:
                command = (commands['Darwin'] if name == 'ssh' else
                           ['brew', 'services', 'info', 'tailscale', '--json'] if name == 'tailscale' else
                           ['pmset', '-g', 'custom'])
                try:
                    state[name]['output'] = self._command(shlex.join(command), 15)
                except RuntimeError as exc:
                    state[name]['error'] = str(exc)
        return state

    def _unix_plan(self, system, chosen, state):
        commands = []
        if system == 'Linux':
            if chosen['ssh']:
                units = state['ssh'].get('units', {})
                unit = next((u for u in self.cdesc['linux']['ssh_services']
                             if units.get(u, {}).get('LoadState') == 'loaded'), None)
                if not unit:
                    raise ValueError('Install the distro OpenSSH server first; no loaded ssh/sshd unit was found.')
                commands.append(['systemctl', 'enable', '--now', unit])
            if chosen['tailscale']:
                unit = self.cdesc['linux']['tailscale_service']
                if state['tailscale'].get('units', {}).get(unit, {}).get('LoadState') != 'loaded':
                    raise ValueError('Install Tailscale first; no tailscaled system unit was found.')
                commands.append(['systemctl', 'enable', '--now', unit])
            if chosen['keep_awake']:
                commands.append(['systemctl', 'mask', 'sleep.target', 'suspend.target',
                                 'hibernate.target', 'hybrid-sleep.target'])
        else:
            if chosen['ssh']:
                commands.append(['/usr/sbin/systemsetup', '-setremotelogin', 'on'])
            if chosen['tailscale']:
                if not shutil.which('brew'):
                    raise ValueError('macOS service setup requires an installed Homebrew tailscale formula; GUI clients differ.')
                commands.append([shutil.which('brew'), 'services', 'start', 'tailscale'])
            if chosen['keep_awake']:
                commands.append(['/usr/bin/pmset', '-c', 'sleep', '0'])
        return commands

    def run(self, ctx, profile=None, ssh=None, tailscale=None, keep_awake=None, boot_unlock=None,
            check=False, dry_run=False, apply=False, port=None, sshd_source='', keys='',
            remote_address=None, volume_guid='', persistent_id='', protector_id='',
            drive='', report=''):
        """Select optional services interactively, or use -q with explicit switches.

        A terminal run asks for each feature, then asks to apply the displayed plan.
        --check and --dry_run never prompt or change services. Non-terminal runs inspect only
        unless -q --apply is explicit. False means leave a feature alone, never uninstall it.
        Profiles slurm/kubernetes/aks/mpi/managed select no services; they do not install a scheduler/runtime.
        Windows boot_unlock needs an already protected OS volume and an existing external key.
        --report writes safe observed metadata for later registration on the controller.
        """
        result = {'return': 0, 'schema_version': 1, 'applied': False, 'actions': []}
        try:
            if report and os.path.exists(os.path.abspath(os.path.expanduser(str(report)))):
                raise ValueError('Report already exists; select a new report filename.')
            system = platform.system()
            if system not in ('Windows', 'Linux', 'Darwin'):
                raise ValueError('Unsupported OS: ' + system)
            quiet = bool(ctx['control'].get('quiet', False))
            profile = self.cdesc['default_profile'] if profile is None else profile
            checking, preview, applying = switch(check), switch(dry_run), switch(apply)
            if checking and applying:
                raise ValueError('--check and --apply cannot be combined')
            interactive = not quiet and not checking and not preview and bool(sys.stdin and sys.stdin.isatty())
            chosen = selection(self.cdesc, profile, dict(ssh=ssh, tailscale=tailscale,
                                keep_awake=keep_awake, boot_unlock=boot_unlock))
            options = dict(volume_guid=volume_guid, persistent_id=persistent_id, protector_id=protector_id,
                           drive=drive, port=int(self.cdesc['new_ssh']['port'] if port is None else port),
                           sshd_source=str(sshd_source), keys=str(keys),
                           remote_address=str(self.cdesc['new_ssh']['remote_address'] if remote_address is None else remote_address))
            if not 1 <= options['port'] <= 65535:
                raise ValueError('port must be between 1 and 65535')
            import ipaddress
            ipaddress.ip_network(options['remote_address'], strict=False)
            if interactive:
                print('cMeta info: Setup affects this machine. SSH is needed only for direct SSH access.')
                print('cMeta info: Slurm/Kubernetes workers may use their existing cluster access instead.')
                for name, explanation in self.cdesc['features'].items():
                    if name == 'boot_unlock' and system != 'Windows':
                        continue
                    print('cMeta info: ' + explanation)
                    chosen[name] = ask_yes('Configure ' + name + '?', chosen[name])
                if system == 'Windows' and chosen['boot_unlock']:
                    for name in ('volume_guid', 'persistent_id', 'protector_id', 'drive'):
                        if not options[name]:
                            options[name] = input('cMeta info: {} (identity only, never a key/password): '.format(name)).strip()
            if chosen['boot_unlock']:
                if system != 'Windows':
                    raise ValueError('boot_unlock is supported only on Windows')
                validate_unlock(options)
            config = dict(settings=self.cdesc['windows'], options=options, selected=chosen,
                          action='check', home=str(self.cm.home_path),
                          helper=os.path.join(self.module_path, 'scripts', 'unlock-data.ps1'))
            state = self._windows(config) if system == 'Windows' else self._unix_inventory(system)
            print('cMeta info: {} / {}; active cMeta home: {}'.format(platform.node(), system, config['home']))
            if system == 'Windows':
                print('cMeta info: Current services: ' + json.dumps(state['services']))
                print('cMeta info: Tailscale: ' + json.dumps(state.get('tailscale', {})))
            if interactive and system == 'Windows' and chosen['ssh']:
                current = state['services'][self.cdesc['windows']['ssh_service']]
                print('cMeta info: SSH service: ' + json.dumps(current))
                if current['state'] == 'missing':
                    if not options['keys']:
                        options['keys'] = input('cMeta info: Public-key file for Windows administrator login: ').strip()
                    answer = input('cMeta info: New SSH port [{}]: '.format(options['port'])).strip()
                    if answer:
                        options['port'] = int(answer)
                        if not 1 <= options['port'] <= 65535:
                            raise ValueError('port must be between 1 and 65535')
                    answer = input('cMeta info: Firewall source CIDR [{}]: '.format(options['remote_address'])).strip()
                    if answer:
                        ipaddress.ip_network(answer, strict=False)
                        options['remote_address'] = answer
            commands = ([] if system == 'Windows' or checking else self._unix_plan(system, chosen, state))
            result.update(system=system, hostname=platform.node(), user=getpass.getuser(), profile=profile,
                          selected=chosen, before=state, configuration=options, home=config['home'],
                          architecture=platform.machine(), logical_cpus=os.cpu_count())
            for name in chosen:
                print('cMeta info: {}: {}. {}'.format(name, 'configure' if chosen[name] else 'leave alone',
                                                      self.cdesc['features'][name]))
            if system == 'Windows' and chosen['ssh']:
                print('cMeta info: Existing SSH config/keys/ports remain. New SSH: key-only, port {}, firewall source {}.'.format(
                      options['port'], options['remote_address']))
                print('cMeta info: New SSH uses the cMeta openssh-server tool on the OS drive; --sshd_source can relocate an existing portable installation for next boot.')
            result['plan'] = (['Configure ' + name for name, enabled in chosen.items() if enabled]
                              if system == 'Windows' else [shlex.join(c) for c in commands])
            result['registration'] = {'automatic': False, 'controller_step': 'cx host add <private-repo>:<alias> --yaml',
                                      'profile': profile, 'scheduler_node': profile in ('slurm', 'kubernetes', 'aks')}
            if interactive and not checking and not preview:
                applying = ask_yes('Apply this plan now?', False)
            elif applying and not quiet and not preview:
                raise ValueError('Non-terminal apply needs -q; otherwise run in a terminal for the setup questions.')
            if applying and not checking and not preview and any(chosen.values()):
                if system == 'Windows':
                    import ctypes
                    if not ctypes.windll.shell32.IsUserAnAdmin():
                        raise ValueError('Apply requires an elevated Windows terminal; run the selected command as administrator.')
                    if chosen['ssh'] and state['services'][self.cdesc['windows']['ssh_service']]['state'] == 'missing' and not options['sshd_source']:
                        if not os.path.isfile(options['keys']):
                            raise ValueError('A new Windows SSH service requires --keys=<public-key file>.')
                        dependency = self.cm.access({'category': self.category_alias + ',' + self.category_uid,
                            'command': 'run', 'arg1': 'setup,a2f9b61079ce4333', 'ctx': ctx,
                            'name': self.cdesc['windows']['openssh_tool'], 'quiet': quiet,
                            'con': ctx['control'].get('con', False)})
                        if dependency.get('return', 0):
                            return dependency
                        tool = ctx['tasks']['global']['openssh-server']
                        options['sshd_source'] = os.path.dirname(tool['path'])
                    config['action'] = 'apply'
                    result['after'] = self._windows(config, 600)
                    result['actions'] = list(result['plan'])
                else:
                    sudo = [] if os.geteuid() == 0 else ['sudo'] if interactive else ['sudo', '-n']
                    for command in commands:
                        self._command(shlex.join(sudo + command), 120)
                        result['actions'].append(shlex.join(command))
                    result['after'] = self._unix_inventory(system)
                result['applied'] = True
            if not applying or checking or preview:
                print('cMeta info: Inspection/preview only. Use a terminal, or -q --apply with selected features, to configure.')
            if report:
                path = os.path.abspath(os.path.expanduser(str(report)))
                # Never replace a previous report silently or export key contents.
                with open(path, 'x', encoding='utf-8') as stream:
                    json.dump(result, stream, indent=2)
                    stream.write('\n')
                result['report'] = path
            return result
        except (ValueError, RuntimeError, OSError, EOFError, IndexError) as exc:
            result.update({'return': 1, 'error': str(exc)})
            return result
