"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import copy

def build_tool(self,
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
        skip_build_uses: bool = None,
        **params
    ):

    if self.cm.debug:
        self.logger.debug("RUNNING TASK setup build")

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

    os_id = host['os_extra']['id']

    with_version = '' if not version else f' with version "{version}"'
    _with = params.get('with', {})
    if _with:
        if with_version != '': with_version += ' and'
        with_version += f' with params "{_with}"'

    result = {'return': 0}

    has_custom_build = True if hasattr(tool_api_code, 'build') and callable(getattr(tool_api_code, 'build')) else False

    force_custom_build = params.get('custom_build', False)

    if force_custom_build and not has_custom_build:
        return self.cm.error(f'custom build is forced but not available in "{__file__}"')


    # Check deps (winget, sudo apt / curl on Linux/MacOS)
    build_uses_all = []

    build_uses_task = task_desc.get('build_uses', {})
    if build_uses_task and not desc.get('skip_common_build_uses', False):
        os_key = uname if (uname == 'windows' or uname in build_uses_task) else 'linux'
        x = build_uses_task.get('all') if 'all' in build_uses_task else build_uses_task.get(os_key)
        if x:
            build_uses_all += x

    build_uses = desc.get('build_uses', {})
    if build_uses:
        os_key = uname if (uname == 'windows' or uname in build_uses) else 'linux'
        x = build_uses.get('all') if 'all' in build_uses else build_uses.get(os_key)
        if x:
            build_uses_all += x

    proceed = False

    ###############################################################################################
    if build_uses_all or has_custom_build:
        if quiet or build is True or not con:
            proceed = True

        if proceed:   
            print ('')
            print (f'{space}INFO: attempting to build tool "{artifact_print_name}"{with_version} ...')

        elif con:
            print ('')
            x = input (f'{space}INFO: would you like to build tool "{artifact_print_name}"{with_version} (Y/n)? ')

            x = x.strip().lower()

            if x not in ['', 'y', 'yes']:
                print (f'{space}      Skipped!')
            else:
                proceed = True
    else:
        return {'return':16, 'error':f'no building procedure for tool "{artifact_print_name}"'}

    if not proceed:
        return result

    ###############################################################################################
    # Prepare some local vars to be used in deps (build_uses_all)
    _local_update = copy.deepcopy(desc.get('build_local', {}))
    if _local_update:
        self.cm.utils.common.deep_merge(_local, _local_update, append_lists=False)

    target_sub_dir = _local_update.get('target_sub_dir', 'build').replace('{{os_sep}}', os.sep)
    _local_update['target_sub_dir'] = target_sub_dir

    cur_dir = os.getcwd()
    _local['cur_dir'] = cur_dir

    target_path = os.path.join(cur_dir, target_sub_dir)
    _local['target_path'] = target_path

    if con and verbose:
        print ('')
        print (f'{space}INFO: Building in "{target_path}" ...') 


    ###############################################################################################
    build_params = params.copy()

    _control = {
      'con': con,
      'quiet': quiet,
      'verbose': verbose,
      'space': space,
      'clean': task_extra_control['clean'],
      'update': task_extra_control['update'],
      'new': task_extra_control['new'],
    }

    build_params.update({
       'control': _control,
       'result': result,
       'version': version,
       'version_pip': version_pip,
       'version_simple': version_simple,
       'version_major': version_major,
       'env': env,
       'timeout': timeout,
    })

    if hasattr(tool_api_code, 'customize_build') and callable(getattr(tool_api_code, 'customize_build')):
        r = tool_api_code.customize_build(ctx, build_params)
        if self.cm.catch_error(r): return r

        if 'add_to_local' in r:
            self.cm.utils.common.deep_merge(_local, r['add_to_local'], append_lists=False)


    ###############################################################################################
    build_note = desc.get('build_note')

    if build_note:
        if con:
            print ('')
            print (f'{space}{build_note}')

            if not quiet:
                print ('')
                input(f'{space}Press Enter to continue:')

            print ('')

    ###############################################################################################
    if build_uses_all and not skip_build_uses:
        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'use',
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'ctx': ctx,
              'desc': build_uses_all,
              'local': _local,
              'task_artifact_alias': self.artifact_alias,
              'task_artifact_uid': self.artifact_uid,
              'task_artifact_path': self.artifact_path,
             }

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r

    ###############################################################################################
    requires_sudo = desc.get('build_requires_sudo', {})

    os_key = uname if (uname == 'windows' or uname in requires_sudo) else 'linux'
    x = requires_sudo.get('all') if 'all' in requires_sudo else requires_sudo.get(os_key)
    if x:
        # Turn on non-interactive mode unless passwordless sudo
        # You may customize it further via customize_build_cmd
        if con:
            print ('')
            print (f'{space}WARNING: this build requires SUDO ...')

        # It's needed to use bash that checks for sudo (even if in non-interactive mode)...
        timeout = None

        passwordless_sudo = ctx_tasks['global']['host'].get('os_extra', {}).get('passwordless_sudo', False)
    
        if passwordless_sudo:
            if verbose:
                print ('')
                print (f'{space}WARNING: passwordless SUDO detected ...')

    ###############################################################################################

    if has_custom_build:
        r = tool_api_code.build(ctx, build_params)
        if self.cm.catch_error(r): return r

        if r['return']>0 and con:
            err = r['error']
            print ('')
            print (f'{space}WARNING: custom build failed ({err})')

        result = r
        # MAY CONTAIN 'found_path' from install!

    if not result.get('found_paths') and not result.get('found_path'):
        result['found_paths'] = [target_path + os.sep + '**']

    return result

