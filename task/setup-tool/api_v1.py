"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
License: Proprietary - contact the author for licensing information.
"""

import os
import re

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     state: dict,
                     params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup-tool check_params")

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)

        state_tasks = state['tasks']
        nested_call = state_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call

        name = params.get('name')
        tool_tags = params.get('tool_tags')
        tool_api_ver = params.get('tool_api_ver')

        ###########################################################################################
        # SELECT TOOL ARTIFACT

        # Call base find function to find an artifact with a website
        p = {'category':self.cmeta['uses_categories']['utils'],
             'command':'select_artifact',
             'select_category':self.cmeta['uses_categories']['tool'],
             'select_artifact':name,
             'select_tags':tool_tags,
             'con':con,
             'quiet':quiet,
             'space':space,
             'load_files':['desc'],
             'print_extra_line': True,
        }

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        artifact_au = r['artifact_au']

        desc = r['loaded_files']['desc'].get('data', {})

        result = {'return':0}

        if 'uses' in desc:
            result['uses'] = desc['uses']

        # Update params
        params['name'] = artifact_au

        return result


    ############################################################
    def customize_cache_artifact(self,
                                 state,
                                 cache_alias_template,
                                 cache_alias_extra,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup-tool customize_cache_artifact")

        result = {'return':0}

        name = params.get('name')

        if cache_alias_extra is None: 
            cache_alias_extra = ''

        cache_alias_extra += f'{name}'

        result['cache_alias_extra'] = cache_alias_extra

        return result


    ############################################################
    def run(self,
            state: dict,                # cMeta state
            name: str = None,           # Tool name
            tool_tags: str = None,      # Tool tags
            tool_api_ver: int = None,   # Tool api ver (if has code)
            tool_path: str = None,
            paths: str = None,
            version: str = None,        # Tool required version
            env: dict = {},
            timeout: int = 10,
            install: bool = False,      # Force tool install
            build: bool = False,        # Force tool build
            skip_install: bool = False, # Skip install if not detected
    ):

        """
        Setup a tool

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup-tool run")

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)

        state_tasks = state['tasks']
        nested_call = state_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call

        _params = {}

        _global = state['tasks']['global']
        _aggregated = state['tasks']['aggregated']
        _local = {}

        uname = _global['host']['os']['uname']

        context = {'global':_global, 'local':_local}

        result = {'return': 0}

        path = tool_path

        ###########################################################################################
        # SELECT TOOL ARTIFACT

        # Call base find function to find an artifact with a website
        p = {'category':self.cmeta['uses_categories']['utils'],
             'command':'select_artifact',
             'select_category':self.cmeta['uses_categories']['tool'],
             'select_artifact':name,
             'select_tags':tool_tags,
             'con':con,
             'quiet':quiet,
             'load_files':['desc'],
             'space':space,
             'load_api': True,
             'load_api_ver': tool_api_ver,
             'load_api_class': 'CTool',
        }

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        artifact = r['artifact']
        cmeta = artifact['cmeta']
        desc = r['loaded_files']['desc'].get('data', {})

        tool_path = artifact['path']
        tool_api_code = r['api_code']

        artifact_au = r['artifact_au']

        ###########################################################################################
        # CHECK IF FAIL ON NON WINDOWS
        if desc.get('win_only', False) and os.name != 'nt':
            return {'return':1, 'error': f'the tool "{artifact_au}" can run only on Windows'}

        ###########################################################################################
        # CHECK DEPENDENCIES
        uses = desc.get('uses', [])

        if uses:
            task_artifact_alias = self.artifact_alias
            task_artifact_uid = self.artifact_uid
            task_category_alias = self.category_alias
            task_category_uid = self.category_uid

            ii = {'category': task_category_alias + ',' + task_category_uid,
                  'command': 'use',
                  'con': con,
                  'quiet': quiet,
                  'verbose': verbose,
                  'state': state,
                  'desc': uses,
                  'nested_call': nested_call,
                  'local': _local,
                  'task_artifact_alias': task_artifact_alias,
                  'task_artifact_uid': task_artifact_uid,
                 }
            r = self.cm.access(ii)
            if r['return']>0: return self.cm._error2(r, self.cm)



        ############################################################################
        # PREPARE PATHS TO SEARCH

        os_env = _global['host']['os_env']
        envs = _aggregated['env']

        if path:
            if path == '{{sys.executable}}':
                import sys
                path = sys.executable
            elif os.path.isdir(path):
                paths = [path]
                path = None
            elif not os.path.isfile(path):
                return {'return':1, 'error':f'tool "{path}" not found'}

        else:
            paths = []

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

            extra_paths = all_extra_paths[key]

            paths += extra_paths


        ############################################################################
        # Run detection and then installation

        if install or build:
            detection = False
            installation = True
        else:
            detection = True
            installation = False

        skip_search = False
        found_paths = []

        while detection or installation:
            if installation:
                detection = False
                installation = False

                failed = False
                r = None

                if not skip_install and tool_api_code is not None:

                    failed = True

                    install_params = {'con': con,
                                      'quiet': quiet,
                                      'verbose': verbose,
                                      'version': version,
                                      'env': env,
                                      'timeout': timeout,
                    }

                    if build and hasattr(tool_api_code, 'build') and callable(getattr(tool_api_code, 'build')):
                        r = tool_api_code.build(state, install_params)
                    elif hasattr(tool_api_code, 'install') and callable(getattr(tool_api_code, 'install')):
                        r = tool_api_code.install(state, install_params)

                    if r:
                        if r['return']>0: return self.cm._error2(r, self.cm)

                        if not r.get('failed', False):
                            failed = False

                        found_paths = r.get('found_paths')

                        if found_paths:
                            skip_search = True
                        else:
                            found_paths = None

                if not r or failed:
                    if con:
                        helper = desc.get('install_help', {})

                        key = uname if uname in helper else 'linux'

                        helper_text = helper.get(key)

                        if helper_text:
                            print ('')
                            print ('='*80)
                            print (helper_text)
                            print ('='*80)

                    x = f' with version "{version}"' if version else ''
                    err = f'failed to find tool "{artifact_au}"{x}'
                    return self.cm._error(err, 1, None, self.cm.fail_on_error)


            ############################################################################
            # Call base find function to find an artifact with a website
            if not skip_search:
                p = {'category':self.cmeta['uses_categories']['tool'],
                     'command':'find_path',
                     'desc':desc,
                     'con':con,
                     'verbose':verbose,
                     'quiet':quiet,
                     'space':space,
                     'path':path,
                     'paths':paths,
                     'context':context,
                }
                r = self.cm.access(p)
                if r['return']>0: 
                    return self.cm._error2(r, self.cm)

                found_paths = r['found_paths']

            if not found_paths:
                if detection:
                    detection = False
                    installation = True
                    continue

                err = f'failed to find tool "{artifact_au}"'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

            ############################################################################
            # Get versions

            cmd_call_script = desc.get('cmd_call_script', False)
            cmd_call = None

            cmd_version = desc.get('cmd_get_version', None)

            match_version = desc.get('match_version', None)

            found_paths_with_versions = {}

            if cmd_version and match_version:
                for path in found_paths:
                    cmd = cmd_version.replace('{{exe_path}}', f'"{path}"')

                    cmd_call = None
                    if cmd_call_script:

                        cmd_call = _global['host']['vars']['call_script'] + ' ' + \
                                   self.cm.utils.files.cpath(path)# + ' '

                        cmd = cmd_call + _global['host']['vars']['cmd_sep'] + ' ' + cmd

                    _con = _verbose = True if self.cm.debug else False

                    ii = {'category': self.category_alias + ',' + self.category_uid,
                          'command': 'run',
                          'state': state,
                          'arg1': 'cmd,c9ba0a88df394d7f',
                          'cmd': cmd,
                          'env': env,
                          'timeout': timeout,
                          'con': _con, 
                          'verbose': _verbose, 
                          'text_cmd': 'RUN:', 
                          'capture_output': True,
                    }

                    if cmd_call_script:
                        ii['capture_env'] = True

                    rx = self.cm.access(ii)
                    if rx['return'] == 0: 
                        returncode = rx['returncode']
                        if returncode == 0:
                            output = rx['stdout'] + '\n' + rx['stderr']

                            found_paths_with_versions[path] = {'output': output, 'cmd_call': cmd_call, 'cmd': cmd}

                        if cmd_call_script:
                            found_paths_with_versions[path]['env_added'] = rx['env_added']

            if not found_paths_with_versions:
                if detection:
                    detection = False
                    installation = True
                    continue

                err = f'failed to find tool "{artifact_au}" with version'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)


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

                    matches = re.search(match_regex, output, re.IGNORECASE)

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
                    x['path'] = path
                    parsed_paths_with_versions.append(x)

            if not parsed_paths_with_versions:
                if detection:
                    detection = False
                    installation = True
                    continue

                err = f'failed to find tool "{artifact_au}" with parsed version'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)


            ############################################################################
            # Filter versions
            # TBD: check via tool code!
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
                if detection:
                    detection = False
                    installation = True
                    continue

                err = f'failed to find tool "{artifact_au}" with matched version'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

            if detection:
                detection = False
                installation = True
            else:
                installation = False

            if matched_paths_with_versions:
                break


        ############################################################################
        # Select tool

        if len(matched_paths_with_versions) == 1:
            selection = 0
            sorted_matched_paths_with_versions = matched_paths_with_versions

        else:
            sort_keys = ['@detected_version-', 'path']

            sorted_matched_paths_with_versions = sorted(
                matched_paths_with_versions,
                key=lambda a: self.cm.utils.common.build_sort_key(a, sort_keys)
            )

            selection = 0

            if con:
                num = 0

                print ('')
                print (f'{space}Detected {name}:')
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
                    x = input(f'{space}Make your selection or press Enter for 0: ').strip()
     
                    selection = 0 if x == '' else int(x)

                    if selection < 0 or selection >= num:
                        err = 'selection out of range'
                        return self.cm._error(err, 1, None, self.cm.fail_on_error)


        ############################################################################
        # Finalize selection

        tool = sorted_matched_paths_with_versions[selection]

        path = tool['path']
        detected_version = tool['detected_version']
        cmd_call = tool.get('cmd_call')

        result['path'] = path
        result['version'] = detected_version

        if cmd_call:
            result['cmd_call_script'] = cmd_call
            env_added = tool['env_added']
            for key in ['PATH', 'EXTERNAL_INCLUDE', '"INCLUDE', 'LIB', 'LIBPATH', 'WindowsLibPath']:
                if key in env_added:
                    env_added['+'+key] = env_added.pop(key).split(os.pathsep)
            result['_aggregate'] = {'env': env_added}

        if version:
            result['requested_version'] = version

        _params['version'] = detected_version

        result['_update_params'] = _params    

        if con and verbose:
            print ('')
            print (f'{space}Selected tool "{path}" with version "{detected_version}"')
         
        return result
