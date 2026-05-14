"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        """

        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        result = {'return':0}

        lang = params.get('lang')

        if not lang:
            return self.cm.error(f'"lang" is not specified in "{__file__}"')

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        _with = params.get('with', {})

        _fast = _with.get('fast', False)
        _fastest = _with.get('fastest', False)
        _static = _with.get('static', False)
        _debug = _with.get('add_debug', False)
        _openmp = _with.get('openmp', False)
        _profile = _with.get('profile', False)
        _env = _with.get('env', {})

        clean_files = params.get('clean_files')
        if clean_files is None:
            clean_files = []
        else:
            clean_files = clean_files.copy()

        compiler_flags = params.get('flags', [])
        if type(compiler_flags) == str:
            compiler_flags = compiler_flags.split(' ')

        compiler_link_flags = params.get('link_flags', [])
        if type(compiler_link_flags) == str:
            compiler_link_flags = compiler_link_flags.split(' ')

        include_paths = params.get('include_paths', [])
        lib_paths = params.get('lib_paths', [])
        dynamic_lib_paths = params.get('dynamic_lib_paths', []) # For run-time
        lib_names = params.get('lib_names', [])

        global_compiler_key = 'compiler-'+lang

        flags = ctx['tasks']['global'][global_compiler_key].get('features', {}).get('flags','')

        # Check profile
        if _profile:
            _debug = True

        # Check static/dynamic and debug/non-debug
        if _static:
            x = flags.get('static_build_debug') if _debug else flags.get('static_build')
        else:
            x = flags.get('dynamic_build_debug') if _debug else flags.get('dynamic_build')

        if x and x not in compiler_flags:
            compiler_flags.append(x)

        if _profile and 'profile' in flags:
            compiler_flags.append(flags['profile'])

        # Check fast/fastest
        if _fast and 'fast' in flags:
           compiler_flags.append(flags['fast'])
        if _fastest and 'fastest' in flags:
           compiler_flags.append(flags['fastest'])

        # Check openmp
        if _openmp:
            openmp_flag = flags.get('openmp')
            if not openmp_flag:
                return self.cm.error(f'openmp requested but flag is not defined in compiler meta in "{__file__}" ({__name__})')
        
            if openmp_flag not in compiler_flags:
                compiler_flags.append(openmp_flag)

        found_dynamic_libs = []
        found_dynamic_lib_paths = []

        # Check libraries
        for k in ctx['tasks']['global']:
            if k.startswith('lib-'):
                features = ctx['tasks']['global'][k].get('features',{})

                if not _static:
                    if 'found_dynamic_libs' in features['paths']:
                        for l in features['paths']['found_dynamic_libs']:
                            if l not in found_dynamic_libs:
                                found_dynamic_libs.append(l)

                    if 'found_dynamic_lib_paths' in features['paths']:
                        for l in features['paths']['found_dynamic_lib_paths']:
                            if l not in found_dynamic_lib_paths:
                                found_dynamic_lib_paths.append(l)

                # Check lib names
                _lib_names= features.get('lib_names', [])
                if _static and 'lib_names_static' in features:
                    _lib_names = features.get('lib_names_static')
                if _lib_names:
                    lib_names += _lib_names

                # Check include paths
                paths = features.get('paths', {})

                skip_include_paths_during_compilation = features.get('skip_include_paths_during_compilation', False)
                skip_lib_paths_during_compilation = features.get('skip_lib_paths_during_compilation', False)

                _include_paths = paths.get('includes')
                if _include_paths and not skip_include_paths_during_compilation:
                    include_paths += _include_paths

                if not skip_lib_paths_during_compilation:
                    # Check libs
                    lib_key = 'libs'

                    k = 'libs'
                    if _static:
                        k += '_static'
                        if k in paths:
                            lib_key = k

                    if _debug:
                        k += '_debug'
                        if k in paths:
                            lib_key = k

                    _lib_paths = paths.get(lib_key, [])

                    if _lib_paths:
                        lib_paths += _lib_paths

        # Process includes paths
        for include_path in include_paths:
            compiler_flags.append(flags['include_path'] + self.cm.q(include_path))

        # Process libs 
        if flags.get('link_sep') and flags['link_sep'] not in compiler_link_flags:
            compiler_link_flags.insert(0, flags['link_sep'])

        # Process libs paths
        if lib_paths:
            for lib_path in lib_paths:
               if os.path.isdir(lib_path):
                   compiler_link_flags.append(flags['lib_path'] + self.cm.q(lib_path))

        # Process libs names
        if lib_names:
            for lib in lib_names:
                _lib = flags.get('lib_prefix2','') + lib + flags.get('lib_postfix','') if not lib.startswith('$') else lib[1:]
                compiler_link_flags.append(flags['lib_prefix'] + self.cm.q(_lib))

        if _profile:
            if flags.get('link_profile'):
                compiler_link_flags.append(flags['link_profile'])

        # Finalize
        result['params'] = _with

        result['flags'] = compiler_flags
        result['flags_str'] = ' '.join(compiler_flags).strip()

        result['link_flags'] = compiler_link_flags
        result['link_flags_str'] = ' '.join(compiler_link_flags).strip()

        if lib_names:
            result['lib_names'] = lib_names
 
        if lib_paths:
            result['lib_paths'] = lib_paths

        if dynamic_lib_paths:
            result['dynamic_lib_paths'] = dynamic_lib_paths

        if found_dynamic_libs:
            result['found_dynamic_libs'] = found_dynamic_libs

        if found_dynamic_lib_paths:
            result['found_dynamic_lib_paths'] = found_dynamic_lib_paths

        if include_paths:
            result['include_paths'] = include_paths

        add_to_local = {
          'global_compiler_key': global_compiler_key,
        }

        # Check target file names
        target_file_name = params.get('target_file_name')
        target_exe = params.get('target_exe')

        target_ext = _global[global_compiler_key]['features']['vars']['file_ext_exe']
        target_ext2 = '' if target_ext is None else target_ext

        if target_file_name and not target_exe:
            target_exe = target_file_name + target_ext2

        if not target_exe:
            target_exe = 'program' + target_ext2

        add_to_local['target_exe'] = target_exe
        result['target_exe'] = target_exe

        target_path = params.get('target_path')
        target_path_exe = None

        target_path_exe = os.path.join(target_path, target_exe) if target_path else os.path.join(os.getcwd(), target_exe)

        add_to_local['target_path_exe'] = target_path_exe
        result['target_path_exe'] = target_path_exe

        result['compile_env'] = _env

        # Check source files
        src_file_names_str = ''

        src_path = params.get('src_path')
        for s in params.get('src_file_names', []):
            if src_file_names_str != '':
                src_file_names_str += ' '

            src_file_names_str += self.cm.q(os.path.join(src_path, s))

        add_to_local['src_file_names_str'] = src_file_names_str
        result['src_file_names_str'] = src_file_names_str

        # Clean target files
        clean_files.append(target_exe)
        if target_exe.endswith('.exe'):
            clean_files.append(target_exe[:-4])
        else:
            clean_files.append(target_exe+'.exe')

        for f in clean_files:
             clean_file = os.path.join(target_path, f) if target_path else os.path.join(os.getcwd(), f)

             if os.path.isfile(clean_file):
                 os.remove(clean_file)

        result['add_to_local'] = add_to_local
 
        return result
