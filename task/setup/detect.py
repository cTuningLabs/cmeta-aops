"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import re

def detect_existing_tool(self,
        ctx: dict,                  # cMeta context
        name: str = None,           # Tool name
        tool_tags: str = None,      # Tool tags
        tool_api_ver: int = None,   # Tool api ver (if has code)
        tool_path: str = None,
        paths: str = None,
        version: str = None,        # Tool required version
        env: dict = {},
        timeout: int = 10,
        tool_read: dict = {},       # Preloaded tool data from read_tool
        task_desc: dict = {},
        install: bool = None,
        build: bool = None,
        **params
):

    """
    Detect existing tool

    Returns:
        dict: A cMeta dictionary with the following keys:
            - **return** (int): 0 if success, >0 if error.
            - **error** (str): Error message if `return > 0`.
    """

    if self.cm.debug:
        self.logger.debug("RUNNING TASK setup run")

    _params = {}

    result = {'return': 0}

    con = ctx['control'].get('con', False)
    quiet = ctx['control'].get('quiet', False)
    verbose = ctx['control'].get('verbose', False)

    space = tool_read['space']
    _local = tool_read['local']
    desc = tool_read['desc']
    tool_api_code = tool_read['tool_api_code']
    artifact_au = tool_read['artifact_au']

    ############################################################################
    # PREPARE PATHS TO SEARCH
    ctx_tasks = ctx['tasks']
    host = ctx_tasks['global']['host']

    path = tool_path

    os_env = host['os_env']
    uname = host['os']['uname']
    envs = ctx_tasks['aggregated']['env']

    force_path = True if path or paths else False

    if path:
        if path == '{{sys.executable}}':
            import sys
            path = sys.executable
        elif os.path.isdir(path):
            paths = [path]
            path = None
        elif not os.path.isfile(path):
            return {'return':1, 'error':f'tool "{path}" not found'}

    elif not paths:
        paths = []

        if 'only_paths' in desc:
            all_only_paths = desc['only_paths']

            if 'all' in all_only_paths:
                paths = all_only_paths['all']
            elif uname in all_only_paths:
                paths = all_only_paths[uname]
            elif 'linux' in all_only_paths:
                paths = all_only_paths['linux']

        else:

            x = envs.get('PATH', '').strip()
            if x != '':
                paths = x.split(os.pathsep)
            else:
                x = envs.get('+PATH', [])
                if type(x) == list and len(x)>0:
                    paths = x.copy()
                else:
                    x = str(x).strip()
                    if x != '':
                        paths = x.split(os.pathsep)

            x = os_env.get('PATH', '').strip()
            if x != '':
                paths += x.split(os.pathsep)

            x = os.environ.get('CMETA_TOOL_EXTRA_PATHS', '').strip()
            if x != '':
                paths += x.split(os.pathsep)

            if 'extra_paths' in desc:
                all_extra_paths = desc['extra_paths']

                key = uname if uname in all_extra_paths else 'linux'

                extra_paths = all_extra_paths.get(key)

                if extra_paths:
                    for p in extra_paths:
                        p = p.replace('{{user_home}}', os.path.expanduser("~"))
                        paths.append(p)

        r = self.cm.utils.common.expand_strings_in_dict(paths, ctx_tasks)
        if self.cm.catch_error(r): return r

    ############################################################################
    # Call base find function to find tools
    p = {'category':self.cmeta['uses_categories']['tool'],
         'command':'find_path',
         'desc':desc,
         'con':con,
         'verbose':verbose,
         'quiet':quiet,
         'space':space,
         'path':path,
         'paths':paths,
         'context':ctx_tasks,
    }

    r = self.cm.access(p)
    if self.cm.catch_error(r): return r

    found_paths = r['found_paths']

    if not found_paths:
#        x = '' if not params else f' with params {params}'
        x = ''
        return self.cm.error(f'failed to find tool "{artifact_au}"{x}', 16)

    ############################################################################
    # Check/update paths via tool code 
    # (for example remove ones that doesn't have some capabilities)

    found_paths_with_versions = {}

    if not force_path and hasattr(tool_api_code, 'update_paths') and callable(getattr(tool_api_code, 'update_paths')):
        r = tool_api_code.update_paths(ctx, found_paths, params)
        if self.cm.catch_error(r): return r

        if 'paths' in r: 
            found_paths = r['paths']

        if 'found_paths_with_versions' in r:
            found_paths_with_versions = r['found_paths_with_versions']

    if hasattr(tool_api_code, 'detect_versions') and callable(getattr(tool_api_code, 'detect_versions')):
        r = tool_api_code.detect_versions(ctx, found_paths, params)
        if self.cm.catch_error(r): return r

        if 'found_paths_with_versions' in r:
            found_paths_with_versions = r['found_paths_with_versions']

    ############################################################################
    # Get versions if not forced by TOOL API CODE in the previous step

    match_version = desc.get('match_version', None)

    if not found_paths_with_versions:

        cmd_call_script = desc.get('cmd_call_script')
        cmd_call = None

        cmd_version = desc.get('cmd_get_version', None)

        if cmd_version and match_version:
            for xpath in found_paths:
                
                path = xpath[1:] if xpath.startswith('!') else xpath

                qpath = self.cm.utils.files.quote_path(path)

                cmd = cmd_version.replace('{{tool_path}}', qpath)

                r = self.cm.utils.common.expand_string(cmd, ctx_tasks)
                if self.cm.catch_error(r): return r
                cmd = r['string']

                cmd_call = None
                if cmd_call_script:
                    cmd_call = host['vars']['call_script'] + ' ' + cmd_call_script.replace('{{tool_path}}', qpath)

                    r = self.cm.utils.common.expand_string(cmd_call, ctx_tasks)
                    if self.cm.catch_error(r): return r
                    cmd_call = r['string']

                    cmd = cmd_call + ' ' + host['vars']['cmd_sep'] + ' ' + cmd

                _con = _verbose = True if self.cm.debug else False

                ii = {'category': self.category_alias + ',' + self.category_uid,
                      'command': 'run',
                      'ctx': ctx,
                      'arg1': 'cmd,c9ba0a88df394d7f',
                      'cmd': cmd,
                      'env': env,
                      'timeout': timeout,
                      'con': _con, 
                      'verbose': _verbose, 
                      'text_cmd': 'RUN:', 
                      'fail_if_nonzero_return_code': False,
                      'capture_output': True,
                }

                # We can capture ENV difference for scripts that initalize tools
                # such as Microsoft Visual Studio or Intel compilers ...

                if cmd_call_script:
                    ii['capture_env'] = True

                rx = self.cm.access(ii)
                if self.cm.debug:
                    print ('='*60)
                    print ('Output of versiond detection:')
                    print ('')
                    self.cm.j(rx)
                    print ('='*60)

                if self.cm.catch_error(rx): return rx

                returncode = rx['returncode']
                if returncode == 0:
                    output = rx['stdout'] + '\n' + rx['stderr']

                    found_paths_with_versions[xpath] = {'output': output, 'cmd_call': cmd_call, 'cmd': cmd}

                if cmd_call_script:
                    found_paths_with_versions[xpath]['env_added'] = rx['env_added']

    if not found_paths_with_versions:
#        x = '' if not params else f' with params "{params}"'
        x = ''
        return self.cm.error(f'failed to find tool "{artifact_au}"{x}', 16)

    if self.cm.debug:
        print ('')
        print ('Found paths with versions:')
        self.cm.j(found_paths_with_versions)
        print ('')

    ############################################################################
    # Parse versions

    parsed_paths_with_versions = []

    for path in found_paths_with_versions:
        x = found_paths_with_versions[path]
        output = x['output']

        detected = False
        detected_version = None

        for match in match_version:
            match_regex = match['regex']
            match_group = match['group']

            matches = re.search(match_regex, output, re.IGNORECASE | re.MULTILINE)

            if self.cm.debug:
                print ('')
                print (f'Attempt to find version in {path}:')
                print ('')
                print ('Output:')
                print ('')
                print (output)
                print ('')
                print (matches)

            if matches:
                detected_version = matches.group(match_group)
                detected = True
                break

        if detected:
            x['detected_version'] = detected_version
            if path.startswith('!'):
                x['priority'] = True
                path = path[1:]
            x['path'] = path
            parsed_paths_with_versions.append(x)

    if not parsed_paths_with_versions:
        return self.cm.error(f'failed to find tool "{artifact_au}" with parsed version', 16)

    if self.cm.debug:
        print ('')
        print ('Parsed paths with versions:')
        self.cm.j(parsed_paths_with_versions)
        print ('')


    ############################################################################
    # Filter versions
    matched_paths_with_versions = [] 

    if not version:
        matched_paths_with_versions = parsed_paths_with_versions

    else:
        for x in parsed_paths_with_versions:
            path = x['path']
            detected_version = x['detected_version']

            if self.cm.debug:
                print ('')
                print (f'Comparing versions for "{path}": "{detected_version}" vs "{version}"')

            r = self.cm.packages.match_version(version, detected_version)

            if self.cm.debug:
                print (r)

            if r['return']==0 and r['matched']:
                matched_paths_with_versions.append(x)

    if not matched_paths_with_versions:
        return self.cm.error(f'failed to find tool "{artifact_au}" with matched version', 16)

    if hasattr(tool_api_code, 'check_features') and callable(getattr(tool_api_code, 'check_features')):
        r = tool_api_code.check_features(ctx, matched_paths_with_versions, params)
        if self.cm.catch_error(r): return r

        if 'paths' in r: 
            matched_paths_with_versions = r['paths']


    ############################################################################
    # Sort version

    if len(matched_paths_with_versions) == 1:
        selection = 0
        sorted_matched_paths_with_versions = matched_paths_with_versions

    else:
        # Need priority key to move some paths above 
        # (that were marked by ! - such as current python interpreter)
        sort_keys = ['priority', '@detected_version-', 'path']

        # Do not sort priority ones but move them out
        priority_matched_paths_with_versions = []
        normal_matched_paths_with_versions = []

        for a in matched_paths_with_versions:
            if a.get('priority', False):
                priority_matched_paths_with_versions.append(a)
            else:
                normal_matched_paths_with_versions.append(a)     

        sorted_normal_matched_paths_with_versions = sorted(
            normal_matched_paths_with_versions,
            key=lambda a: self.cm.utils.common.build_sort_key(a, sort_keys)
        )

        sorted_matched_paths_with_versions = priority_matched_paths_with_versions + sorted_normal_matched_paths_with_versions

        if not sorted_matched_paths_with_versions:
            return self.cm.error(f'failed to find tool "{artifact_au}" with matched version', 16)

        # Finish selection
        selection = 0

        if con:
            num = 0

            print ('')
            print (f'{space}Detected "{name}":')
            print ('')

            for x in sorted_matched_paths_with_versions:
                path = x['path']
                detected_version = x['detected_version']

                print (f'{space}{num}) {path} (Detected version {detected_version})')

                num += 1

            if quiet:
                print ('')
                print (f'{space}Quietly selected: 0')

                selection = 0

            else:
                print ('')
                x = input(f'{space}Make your selection, press Enter for 0, or select -1 to install/build tool (if supported): ').strip()
 
                selection = 0 if x == '' else int(x)

                if selection < -1 or selection >= num:
                    return self.cm.error('selection out of range')

                if selection == -1:
                    return self.cm.error(f'user forced to install or build tool "{artifact_au}"', 16)


    ############################################################################
    # Finalize selection

    tool = sorted_matched_paths_with_versions[selection]

    path = tool['path']
    detected_version = tool['detected_version']
    cmd_call = tool.get('cmd_call')

    if 'features' in tool:
        result['features'] = tool['features']

    result['path'] = path
    result['filename'] = os.path.basename(path)

    # Extended CMD for the tool (for example pip needs "python -m pip")
    if 'cmd' in desc:
        cmd = desc['cmd']
    else:
        cmd = self.cm.utils.files.quote_path(result['path'])

    r = self.cm.utils.common.expand_string(cmd, ctx_tasks)
    if self.cm.catch_error(r): return r

    result['cmd'] = r['string']

    if cmd_call:
        result['cmd_call_script'] = cmd_call

        cmd = cmd_call + ' ' + host['vars']['cmd_sep'] + ' ' + cmd

        env_added = tool['env_added']
        for key in self.cdesc['add_env_path_keys']:
            if key in list(env_added.keys()):
                env_added['+'+key] = env_added.pop(key).split(os.pathsep)
        result['_aggregate'] = {'env': env_added}

    r = self.cm.utils.common.expand_string(cmd, ctx_tasks)
    if self.cm.catch_error(r): return r

    result['cmd_call'] = r['string']

    cmd_filename = result['filename']
    if 'cmd_filename' in desc:
        r = self.cm.utils.common.expand_string(desc['cmd_filename'], ctx_tasks)
        if self.cm.catch_error(r): return r
        cmd_filename = r['string']
    result['cmd_filename'] = cmd_filename

    result['qpath'] = self.cm.utils.files.quote_path(path)
    result['version'] = detected_version

    path_bin = os.path.dirname(path)
    result['path_bin'] = path_bin
    result['qpath_bin'] = self.cm.utils.files.quote_path(result['path_bin'])

    path_bin_norm = os.path.abspath(os.path.normpath(path_bin))
    x = os_env.get('PATH', '').strip()
    if x != '':
        env_paths = x.split(os.pathsep)

        for p in env_paths:
            if os.path.abspath(os.path.normpath(p)) == path_bin_norm:
                result['path_bin_in_env'] = True
                break


    if version:
        result['requested_version'] = version

    _params['version'] = detected_version

    result['_update_params'] = _params    

    ############################################################################
    # Customize final selection

    if hasattr(tool_api_code, 'post_detect') and callable(getattr(tool_api_code, 'post_detect')):
        r = tool_api_code.post_detect(ctx, result, params)
        if self.cm.catch_error(r): return r

    if con and verbose:
        print ('')
        print (f'{space}Selected tool "{path}" with version "{detected_version}"')
     
    return result
