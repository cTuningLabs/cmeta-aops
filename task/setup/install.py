"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

def install_tool(self,
        ctx: dict,                  # cMeta context
        _result: dict,              # Aggregated result for setup
        name: str = None,           # Tool name
        tool_tags: str = None,      # Tool tags
        tool_api_ver: int = None,   # Tool api ver (if has code)
        tool_path: str = None,
        paths: str = None,
        version: str = None,        # Tool required version
        version_pip: str = None,        # Tool required version
        version_simple: str = None,        # Tool required version
        version_major: str = None,        # Tool required version
        env: dict = {},
        timeout: int = None,
        tool_read: dict = {},       # Preloaded tool data from read_tool
        task_desc: dict = {},
        task_extra_control: dict = {},
        install: bool = None,
        build: bool = None,
        skip_install_uses: bool = None,
        **params
    ):

    if self.cm.debug:
        self.logger.debug("RUNNING TASK setup install")

    con = ctx['control'].get('con', False)
    quiet = ctx['control'].get('quiet', False)
    verbose = ctx['control'].get('verbose', False)

    space = tool_read['space']
    _local = tool_read['local']
    desc = tool_read['desc']
    tool_api_code = tool_read['tool_api_code']
    tool_api_code2 = tool_read.get('tool_api_code2')
    artifact_au = tool_read['artifact_au']
    artifact_print_name = tool_read['artifact_print_name']

    ctx_tasks = ctx['tasks']
    nested_call = ctx_tasks.setdefault('nested_call', 0)
    host = ctx_tasks['global']['host']

    uname = host['os']['uname']

    with_version = '' if not version else f' with version "{version}"'
    _with = params.get('with', {})
    if _with:
        if with_version != '': with_version += ' and'
        with_version += f' with params "{_with}"'

    result = {'return': 16, 'error':f'tool {artifact_print_name}{with_version} was not installed'}

    # Check direct or custom installation
    install_cmd_desc = desc.get('install_cmd', {})
    os_key = uname if (uname == 'windows' or uname in install_cmd_desc) else 'linux'
    install_cmd = install_cmd_desc.get('all') if 'all' in install_cmd_desc else install_cmd_desc.get(os_key)

    install_cmd_ver_desc = desc.get('install_cmd_version', {})
    os_key = uname if (uname == 'windows' or uname in install_cmd_ver_desc) else 'linux'
    install_cmd_ver = install_cmd_ver_desc['all'] if 'all' in install_cmd_ver_desc else install_cmd_ver_desc.get(os_key)

    # Check direct or custom installation
    uninstall_cmd_desc = desc.get('uninstall_cmd', {})
    os_key = uname if (uname == 'windows' or uname in uninstall_cmd_desc) else 'linux'
    uninstall_cmd = uninstall_cmd_desc.get('all') if 'all' in uninstall_cmd_desc else uninstall_cmd_desc.get(os_key)

    run_uninstall_cmd = False

    has_custom_install = True if hasattr(tool_api_code, 'install') and callable(getattr(tool_api_code, 'install')) else False

    force_custom_install = params.get('custom_install', False)

    if force_custom_install and not has_custom_install:
        return self.cm.error(f'custom install is forced but not available in "{__file__}"')

    # Check deps (winget, sudo apt / curl on Linux/MacOS)
    install_uses_all = []

    install_uses_task = task_desc.get('install_uses', {})
    if install_uses_task and not desc.get('skip_common_install_uses', False):
        os_key = uname if (uname == 'windows' or uname in install_uses_task) else 'linux'
        x = install_uses_task.get('all') if 'all' in install_uses_task else install_uses_task.get(os_key)
        if x:
            install_uses_all += x

    install_uses = desc.get('install_uses', {})
    if install_uses:
        os_key = uname if (uname == 'windows' or uname in install_uses) else 'linux'
        x = install_uses.get('all') if 'all' in install_uses else install_uses.get(os_key)
        if x:
            install_uses_all += x

    proceed = False

    ###############################################################################################
    if install_cmd or has_custom_install:
        if quiet or install is True or not con:
            proceed = True

        if proceed:   
            print ('')
            print (f'{space}INFO: attempting to install tool "{artifact_print_name}"{with_version} ...')

        elif con:
            print ('')
            x = input (f'{space}INFO: would you like to install tool "{artifact_print_name}"{with_version} (Y/n)? ')

            x = x.strip().lower()

            if x not in ['', 'y', 'yes']:
                print (f'{space}      Skipped!')
            else:
                proceed = True
    else:
        return {'return':16, 'error':f'no installation procedure for tool "{artifact_print_name}"'}

    if not proceed:
        return result

    ###############################################################################################
    install_note = desc.get('install_note')

    if install_note:
        if con:
            print ('')
            print (f'{space}{install_note}')

            if not quiet:
                print ('')
                input(f'{space}Press Enter to continue:')

            print ('')

    ###############################################################################################
    requires_sudo = desc.get('requires_sudo', {})

    if install_uses_all and not skip_install_uses:
        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'use',
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'ctx': ctx,
              'desc': install_uses_all,
              'local': _local,
              'task_artifact_alias': self.artifact_alias,
              'task_artifact_uid': self.artifact_uid,
              'task_artifact_path': self.artifact_path,
             }

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r


    requires_sudo = desc.get('requires_sudo', {})
    os_key = uname if (uname == 'windows' or uname in requires_sudo) else 'linux'
    x = requires_sudo.get('all') if 'all' in requires_sudo else requires_sudo.get(os_key)
    if x:
        # Turn on non-interactive mode unless passwordless sudo
        # You may customize it further via customize_install_cmd
        if con:
            print ('')
            print (f'{space}WARNING: this installation requires SUDO ...')

        # It's needed to use bash that checks for sudo (even if in non-interactive mode)...
        timeout = None

        passwordless_sudo = ctx_tasks['global']['host'].get('os_extra', {}).get('passwordless_sudo', False)
    
        if passwordless_sudo:
            if verbose:
                print ('')
                print (f'{space}WARNING: passwordless SUDO detected ...')


    install_params = params.copy()

    _control = {
      'con': con,
      'quiet': quiet,
      'verbose': verbose,
      'space': space,
      'clean': task_extra_control['clean'],
      'update': task_extra_control['update'],
      'new': task_extra_control['new'],
    }


    install_params.update({
       'control': _control,
       'result': result,
       'version': version,
       'version_pip': version_pip,
       'version_simple': version_simple,
       'version_major': version_major,
       'env': env,
       'timeout': timeout,
    })


    if has_custom_install:
        r = tool_api_code.install(ctx, install_params, install_cmd, uninstall_cmd)
        if self.cm.catch_error(r): return r

        if r['return']>0 and con:
            err = r['error']
            print ('')
            print (f'{space}WARNING: custom installation failed ({err})')

        result = r
        # MAY CONTAIN 'found_path' from install!

        if 'run_uninstall_cmd' in r:
            run_uninstall_cmd = r['run_uninstall_cmd']

        if 'uninstall_cmd' in r:
            uninstall_cmd = r['uninstall_cmd']

        if 'install_cmd' in r:
            # Can alter or skip CMD (if set to None)
            install_cmd = r['install_cmd']

            if install_cmd:
                force_custom_install = False # to be able to proceed with install_cmd if needed ...

    if install_cmd and not force_custom_install:
        # Add version if supported
        if version and install_cmd_ver:
            if '{{pip_version}}' in install_cmd_ver:
                xversion = '=='+version if version and version[0].isdigit() else version
                install_cmd = install_cmd_ver.replace('{{pip_version}}', xversion)

            elif '{{version}}' in install_cmd_ver:
                install_cmd = install_cmd_ver.replace('{{version}}', version)

            elif '{{simple_version}}' in install_cmd_ver or '{{major_version}}' in install_cmd_ver:
                simple_version = True
                for k in ['>', '<', '*', '?']:
                    if k in version:
                        simple_version = False
                        break

                if simple_version:
                    xversion = version
                    if xversion.startswith('=='):
                        xversion = xversion[2:]

                    major_version = xversion
                    j = major_version.find('.')
                    if j>0:
                        major_version = major_version[:j]

                    install_cmd = install_cmd_ver.replace('{{simple_version}}', xversion)
                    install_cmd = install_cmd.replace('{{major_version}}', major_version)

        package_name = desc['package_name'] if 'package_name' in desc else artifact_au

        # Start from possible sub-tool to customize install cmd and params
        if tool_api_code2 and hasattr(tool_api_code2, 'customize_install_cmd2') and callable(getattr(tool_api_code2, 'customize_install_cmd2')):
            r = tool_api_code2.customize_install_cmd2(ctx, install_cmd, install_params, env, timeout, uninstall_cmd)
            if self.cm.catch_error(r): return r

            if 'run_uninstall_cmd' in r:
                run_uninstall_cmd = r['run_uninstall_cmd']

            if 'uninstall_cmd' in r: 
                uninstall_cmd = r['uninstall_cmd']

            if 'install_cmd' in r: 
                install_cmd = r['install_cmd']

            if 'timeout' in r:
                timeout = r['timeout']

            if 'package_name' in r:
                package_name = r['package_name']

        # Then finish updating install cmd and params
        if hasattr(tool_api_code, 'customize_install_cmd') and callable(getattr(tool_api_code, 'customize_install_cmd')):
            r = tool_api_code.customize_install_cmd(ctx, install_cmd, install_params, env, timeout, uninstall_cmd)
            if self.cm.catch_error(r): return r

            if 'run_uninstall_cmd' in r:
                run_uninstall_cmd = r['run_uninstall_cmd']

            if 'uninstall_cmd' in r: 
                uninstall_cmd = r['uninstall_cmd']

            if 'install_cmd' in r: 
                install_cmd = r['install_cmd']

            if 'timeout' in r:
                timeout = r['timeout']

            if 'package_name' in r:
                package_name = r['package_name']

        # Check uninstall
        cmds = []

        if run_uninstall_cmd:
            r = self.cm.utils.common.expand_string(uninstall_cmd, ctx_tasks)
            if self.cm.catch_error(r): return r
            uninstall_cmd = r['string']

            # Update package name if installation is from host ...
            uninstall_cmd = uninstall_cmd.replace('{{name}}', package_name)

            cmds.append(uninstall_cmd)

            result['uninstall_cmd'] = uninstall_cmd

        # Update from task context
        r = self.cm.utils.common.expand_string(install_cmd, ctx_tasks)
        if self.cm.catch_error(r): return r
        install_cmd = r['string']

        # Update package name if installation is from host ...
        install_cmd = install_cmd.replace('{{name}}', package_name)

        cmds.append(install_cmd)

        result['install_cmd'] = install_cmd

        for cmd in cmds:
            # Run installation
            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con, 
                  'quiet': quiet, 
                  'verbose': verbose, 
                  'text_cmd': 'RUN:', 
                  # Important to be able to continue processing detect/install/build
                  'fail_if_nonzero_return_code': False, 
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                result['failed'] = True
            else:
                # Restart tool detection
                result = {'return':0, 'found_paths': None}
    
    if hasattr(tool_api_code, 'post_install') and callable(getattr(tool_api_code, 'post_install')):
        r = tool_api_code.post_install(ctx, install_params)
        if self.cm.catch_error(r): return r

    return result
