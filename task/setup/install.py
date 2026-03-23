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
        name: str = None,           # Tool name
        tool_tags: str = None,      # Tool tags
        tool_api_ver: int = None,   # Tool api ver (if has code)
        tool_path: str = None,
        paths: str = None,
        version: str = None,        # Tool required version
        env: dict = {},
        timeout: int = 60,
        tool_read: dict = {},       # Preloaded tool data from read_tool
        task_desc: dict = {},
        install: bool = None,
        build: bool = None,
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
    artifact_au = tool_read['artifact_au']

    ctx_tasks = ctx['tasks']
    nested_call = ctx_tasks.setdefault('nested_call', 0)
    host = ctx_tasks['global']['host']

    uname = host['os']['uname']

    with_version = '' if not version else f' with version "{version}"'
    _with = params.get('with', {})
    if _with:
        if with_version != '': with_version += ' and'
        with_version += f' with params "{_with}"'

    result = {'return': 16, 'error':f'tool {artifact_au}{with_version} was not installed'}

    # Check direct or custom installation
    install_cmd = desc.get('install_cmd', {})
    os_key = uname if (uname == 'windows' or uname in install_cmd) else 'linux'
    install_cmd = install_cmd.get('all') if 'all' in install_cmd else install_cmd.get(os_key)

    has_custom_install = True if hasattr(tool_api_code, 'install') and callable(getattr(tool_api_code, 'install')) else False

    # Check deps (winget, sudo apt / curl on Linux/MacOS)
    install_uses_all = []

    install_uses_task = task_desc.get('install_uses', [])
    if install_uses_task and not desc.get('skip_common_install_uses', False):
        x = install_uses_task.get('all') if 'all' in install_uses_task else install_uses_task.get(os_key)
        if x:
            install_uses_all += x

    install_uses = desc.get('install_uses', [])
    if install_uses:
        x = install_uses.get('all') if 'all' in install_uses else install_uses.get(os_key)
        if x:
            install_uses_all += x

    proceed = False

    if install_cmd or has_custom_install:
        if quiet or install is True or not con:
            proceed = True

        if proceed:   
            print ('')
            print (f'{space}INFO: attempting to install tool "{artifact_au}"{with_version} ...')

        elif con:
            print ('')
            x = input (f'{space}INFO: would you like to install tool "{artifact_au}"{with_version} (Y/n)? ')

            x = x.strip().lower()

            if x not in ['', 'y', 'yes']:
                print (f'{space}      Skipped!')
            else:
                proceed = True
    else:
        return {'return':16, 'error':f'no installation procedure for tool "{artifact_au}"'}


    if not proceed:
        return result

    if install_uses_all:
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


    requires_sudo = desc.get('requires_sudo',{})
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

    install_params.update({
       'control': {
          'con': con,
          'quiet': quiet,
          'verbose': verbose,
       },
       'result': result,
       'timeout': timeout,
    })


    if has_custom_install:
        r = tool_api_code.install(ctx, install_params)
        if self.cm.catch_error(r): return r

        result = r


    elif install_cmd:
        # Add version if supported
        if version:
            install_cmd_version = desc.get('install_cmd_version')
            if install_cmd_version: 
                install_cmd_ver = install_cmd_version['all'] if 'all' in install_cmd_version else install_cmd_version.get(os_key)

                if install_cmd_ver:
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

        if hasattr(tool_api_code, 'customize_install_cmd') and callable(getattr(tool_api_code, 'customize_install_cmd')):
            r = tool_api_code.customize_install_cmd(ctx, install_cmd, install_params, env, timeout)
            if self.cm.catch_error(r): return r

            if 'install_cmd' in r: 
                install_cmd = r['install_cmd']

            if 'timeout' in r:
                timeout = r['timeout']

        # Update from task context
        r = self.cm.utils.common.expand_string(install_cmd, ctx_tasks)
        if self.cm.catch_error(r): return r
        install_cmd = r['string']

        # Run installation
        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': install_cmd,
              'env': env,
              'timeout': timeout,
              'con': con, 
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
