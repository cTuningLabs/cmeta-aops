"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform
import shutil

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

        _with = params.get('with')
        if _with is None:
            _with = {}

        _lib = _with.get('lib', False)
        _fast = _with.get('fast', False)
        _fastest = _with.get('fastest', False)
        _static = _with.get('static', False)
        _debug = _with.get('add_debug', False)
        _openmp = _with.get('openmp', False)
        _env = _with.get('env', {})
        _d = _with.get('d', {})
        _install = _with.get('install', False)

        _profile = params.get('profile', False)
        _profile_cuda = params.get('profile_cuda', False)
        _profile_cuda_kernels = params.get('profile_cuda_kernels', False)

        cmds = params.get('cmds', [])
        lib_cmd = ''

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

        flags = ctx['tasks']['global'][global_compiler_key].get('features', {}).get('flags',{})

        # Check profile
        if _profile:
            _debug = True

        # Check static/dynamic and debug/non-debug
        if _lib:
            if _static:
               x = flags.get('lib_static_build_debug') if _debug else flags.get('lib_static_build')
            else:
               x = flags.get('lib_dynamic_build_debug') if _debug else flags.get('lib_dynamic_build')
        else:
           if _static:
               x = flags.get('static_build_debug') if _debug else flags.get('static_build')
           else:
               x = flags.get('dynamic_build_debug') if _debug else flags.get('dynamic_build')

        if x and x not in compiler_flags:
            compiler_flags.append(x)

        if _profile and 'profile' in flags:
            compiler_flags.append(flags['profile'])

        if (_profile_cuda or _profile_cuda_kernels) and 'profile_cuda' in flags:
            compiler_flags.append(flags['profile_cuda'])

        # Check -D
        if _d:
           d_flag = flags.get('d')
           if not d_flag:
               return self.cm.error(f'-D is requested but d flag is not defined in compiler meta in "{__file__}" ({__name__})')
           for k in _d:
               v = _d[k]
               x = f'{d_flag}{k}'
               if v:
                  x += f'={v}'
               compiler_flags.append(x)

        # Check fast/fastest
        if _fast and 'fast' in flags:
           compiler_flags.append(flags['fast'])
        if _fastest and 'fastest' in flags:
           compiler_flags.append(flags['fastest'])

        # Check openmp
        if _openmp:
            openmp_flag = flags.get('openmp')
            link_openmp_flag = flags.get('link_openmp')
            if not openmp_flag and not link_openmp_flag:
                return self.cm.error(f'openmp requested but flag is not defined in compiler meta in "{__file__}" ({__name__})')
        
            if openmp_flag and openmp_flag not in compiler_flags:
                compiler_flags.append(openmp_flag)

            if link_openmp_flag and link_openmp_flag not in compiler_link_flags:
                compiler_link_flags.append(link_openmp_flag)

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

                # Should be here even if static (since libraries may have been compiled as dynamic
                # and not have static libs)
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
            if 'include_path' in flags:
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
                if lib.startswith('$'):
                    x = lib[1:] + flags.get('lib_postfix','')
                else:
                    x = flags.get('lib_prefix2','') + lib + flags.get('lib_postfix','')
                compiler_link_flags.append(flags['lib_prefix'] + self.cm.q(x))

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

        if _lib:
            if _static:
                target_ext = _global[global_compiler_key].get('features', {}).get('vars', {}).get('file_ext_lib')
            else:
                target_ext = _global[global_compiler_key].get('features', {}).get('vars', {}).get('file_ext_dlib')
            target_ext2 = '' if target_ext is None else target_ext
        else:
            target_ext = _global[global_compiler_key].get('features', {}).get('vars', {}).get('file_ext_exe')
            target_ext2 = '' if target_ext is None else target_ext

        if target_file_name and not target_exe:
            target_exe = target_file_name + target_ext2

        if not target_exe:
            target_exe = 'program' + target_ext2

        add_to_local['target_exe'] = target_exe
        result['target_exe'] = target_exe

        target_path = params.get('target_path')
        if not target_path:
            target_path = os.getcwd()

        os.makedirs(target_path, exist_ok=True)

        target_path_exe = os.path.join(target_path, target_exe)

        add_to_local['target_path_exe'] = target_path_exe
        result['target_path_exe'] = target_path_exe

        if _lib:
            exe_file_flag = flags['lib_file']
            x = exe_file_flag + self.cm.q(target_path_exe)

            if not _static and flags.get('lib_file2'):
                target_exe2 = target_file_name + _global[global_compiler_key].get('features', {}).get('vars', {}).get('file_ext_lib2')
                target_path_exe2 = os.path.join(target_path, target_exe2) if target_path else os.path.join(os.getcwd(), target_exe2)

                x += ' ' + flags['lib_file2'] + target_path_exe2

                result['target_exe2'] = target_exe2
                result['target_path_exe2'] = target_path_exe2

            result['target_exe_flag'] = x

        else:
            exe_file_flag = flags.get('exe_file')
            if exe_file_flag and target_path_exe:
                k = 'pre_target_exe_flag' if _with.get('pre_target_exe_flag', False) else 'target_exe_flag'

                result[k] = exe_file_flag + self.cm.q(target_path_exe)

        result['compile_env'] = _env
        add_to_local['compile_env'] = _env

        # Check source files
        src_file_names_str = ''
        obj_file_names_str = ''

        src_path = params.get('src_path')
        for s in params.get('src_file_names', []):
            x = os.path.join(src_path, s)

            if src_file_names_str != '':
                src_file_names_str += ' '

            src_file_names_str += self.cm.q(x)

            if _lib and _static:
                x = os.path.join(target_path, s)

                x = os.path.splitext(x)[0] + _global[global_compiler_key].get('features', {}).get('vars', {}).get('file_ext_obj', '.o')

                if obj_file_names_str != '':
                    obj_file_names_str += ' '

                obj_file_names_str += self.cm.q(x)

        add_to_local['src_file_names_str'] = src_file_names_str
        result['src_file_names_str'] = src_file_names_str

        # Check include if install
        if _install:
            target_path_home = os.path.dirname(target_path)
            target_path_include = os.path.join(target_path_home, 'include')

            # Recursively copy *.h from src_path to target_path/include
            for root, _, files in os.walk(src_path):
                for fname in files:
                    if fname.endswith('.h'):
                        os.makedirs(target_path_include, exist_ok=True)
                        shutil.copy2(os.path.join(root, fname), os.path.join(target_path_include, fname))

#            x = 'lib' if _lib else 'bin'
#            target_path_exe_install = os.path.join(target_path, x)
#            os.makedirs(target_path_exe_install, exist_ok=True)

            x = '_cmeta_info.json'
            cmeta_info_file = os.path.join(src_path, x)
            if os.path.isfile(cmeta_info_file):
                shutil.copy2(cmeta_info_file, os.path.join(target_path, x))

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

        # Assemble main cmd
        cmd = _global['compiler']['qpath']

        x = _global['compiler']['features'].get('flags', {}).get('force_build')
        if x:
            cmd += ' ' + x

        x = result.get('pre_target_exe_flag')
        if x:
            cmd += ' ' + x

        x = _global['compiler']['features'].get('target_arch', {}).get('flags')
        if x:
            cmd += ' ' + x

        x = _with.get('flags')
        if x:
            cmd += ' ' + x

        x = result.get('flags_str')
        if x:
            cmd += ' ' + x

        x = _with.get('flags2')
        if x:
            cmd += ' ' + x

        x = _global['compiler']['features'].get('flags', {}).get('catch_errors')
        if x:
            cmd += ' ' + x

        x = _with.get('flags3')
        if x:
            cmd += ' ' + x

        x = result.get('src_file_names_str')
        if x:
            cmd += ' ' + x

        x = _with.get('flags4')
        if x:
            cmd += ' ' + x


        if _lib and _static:
            path_tool_lib = _global['compiler']['features'].get('paths', {}).get('tool_lib')
            if not path_tool_lib:
                return self.cm.error(f'"tool_lib" is not specified in compiler.features.paths in "{__file__}"')

            static_lib1 = flags.get('static_lib1')
            static_lib2 = flags.get('static_lib2')

            lib_cmd = self.cm.q(path_tool_lib) + ' '
            if static_lib1:
                lib_cmd += static_lib1 + ' '
            if static_lib2:
                lib_cmd += static_lib2
            lib_cmd += f'{target_path_exe} {obj_file_names_str}'

        else:
            x = result.get('link_flags_str')
            if x:
                cmd += ' ' + x

            x = _with.get('lflags')
            if x:
                cmd += ' ' + x

            x = result.get('target_exe_flag')
            if x:
                cmd += ' ' + x

            x = _with.get('lflags2')
            if x:
                cmd += ' ' + x

        cmds.append(cmd)

        if lib_cmd:
            cmds.append(lib_cmd)

#        if _install:
#            src = self.cm.q(os.path.normpath(os.path.join(target_path, target_file_name + '*')))
#            dst = self.cm.q(os.path.normpath(target_path_exe_install))
#
#            if platform.system() == 'Windows':
#                install_cmd = f'move /Y {src} {dst}'
#            else:
#                install_cmd = f'mv -f {src} {dst}'
#
#            cmds.append(install_cmd)

        add_to_local['compile_cmds'] = cmds

        result['add_to_local'] = add_to_local
 
        return result
