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

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''
        clean = ctx_tasks['run_control'].get('clean', False)
        update = ctx_tasks['run_control'].get('update', False)

        _global = ctx_tasks['global']

        host = _global['host']
        uname = host['os']['uname']

        result = {'return':0}

        env = params.get('env', {})

        output_files = params.get('output_files')
        if output_files is None:
            output_files = []
        else:
            output_files = output_files.copy()

        target_compute = _global['target']['compute']

        target_path = params.get('target_path')
        if target_path is None:
            target_path = os.getcwd()

        target_exe = params.get('target_exe')
        if target_exe:
            target_path_exe = os.path.join(target_path, target_exe)

        prefix_cmd = params.get('prefix_cmd')
        if prefix_cmd is None:
            prefix_cmd = ''

        postfix_cmd = params.get('postfix_cmd')
        if postfix_cmd is None:
            postfix_cmd = ''

        cmd = params.get('cmd')
        if cmd is None:
            cmd = ''

        cmd_main = params.get('cmd_main')
        if cmd_main is not None and cmd_main != '':
            if cmd != '':
                cmd += ' '
            cmd += cmd_main

        run_time_env = ctx['tasks']['local'].get('run_time_env', {})

        ###########################################################################################
        _android_cpu = True if 'android-cpu' in target_compute else False
        _cuda = True if 'cuda' in target_compute else False

        add_to_local = {}

        _cpu = False
        if 'cpu' in target_compute:
            _cpu = True
        if _android_cpu: 
            _cpu = False

        start_exe_prefix = _global['host']['vars']['start_exe_prefix']

        # May not exist if only run (python)
        setup_compile = ctx['tasks']['local'].get('setup-compile',{})

        _profile = params.get('profile')
        if _profile is None:
            _profile = False

        _profile_python = params.get('profile_python')
        if _profile_python is None:
            _profile_python = False

        if _profile_python and 'python' not in ctx['tasks']['global']:
            return self.cm.error(f'profile_python is requested but python is not found in the global context in "{__file__}"')

        _profile_cuda = params.get('profile_cuda')
        if _profile_cuda is None:
            _profile_cuda = False

        if _profile_cuda:
            if 'cuda' not in ctx['tasks']['global']:
                return self.cm.error(f'profile_cuda is requested but cuda is not found in the global context in "{__file__}"')
            if 'nsys' not in ctx['tasks']['global']:
                return self.cm.error(f'profile_cuda is requested but nsys is not found in the global context in "{__file__}"')

        _profile_cuda_kernels = params.get('profile_cuda_kernels')
        if _profile_cuda_kernels is None:
            _profile_cuda_kernels = False

        if _profile_cuda_kernels:
            if 'cuda' not in ctx['tasks']['global']:
                return self.cm.error(f'profile_cuda_kernels is requested but cuda is not found in the global context in "{__file__}"')
            if 'ncu' not in ctx['tasks']['global']:
                return self.cm.error(f'profile_cuda_kernels is requested but ncu is not found in the global context in "{__file__}"')


        run_flags_after_exe = params.get('run_flags_after_exe')
        if run_flags_after_exe is None:
            run_flags_after_exe = ''

        cmds = []
        run_time_cmds = []

        # Setup CPU
        if _profile_python:
            if run_flags_after_exe != '':
                run_flags_after_exe += ' '
            run_flags_after_exe += '-m cProfile -s cumulative -o tmp-cmeta-python-profile.out'

            output_files.append('tmp-cmeta-python-profile.out')
            output_files.append('tmp-cmeta-python-profile.txt')

        if _cpu or _cuda:
            fdlp = setup_compile.get('found_dynamic_lib_paths')

            if fdlp:
                if uname == 'windows':
                    env_dlib = run_time_env.setdefault('+PATH', [])
                else:
                    env_dlib = run_time_env.setdefault('+LD_LIBRARY_PATH', [])

                for f in reversed(fdlp):
                    if f not in env_dlib:
                        env_dlib.insert(0, f)

            if _profile:
                if uname == 'windows':
                    x = _global['microsoft-windows-adk']['qpath_bin']
                    wpr = self.cm.q(os.path.join(x, 'wpr'))
                    run_time_cmds.append(f'{wpr} -start CPU -filemode')
                    output_files.append('tmp-cmeta-wpr.etl')

                elif uname == 'linux':
                    perf = _global['perf']['qpath']
                    prefix_cmd += f'{perf} record -g -- '
                    output_files.append('perf.data')
                    output_files.append('perf_report.txt')

                elif uname == 'darwin':
                    prefix_cmd += f'xcrun xctrace record --template "Time Profiler" --output tmp-cmeta-xcrun --launch -- '
#                    prefix_cmd += f'sample '

        if _cuda:
            if _profile_cuda:
                nsys = _global['nsys']['qpath']
                prefix_cmd += f'{nsys} profile --trace=cuda,nvtx --stats=true -o cuda_profile '
                output_files.append('cuda_profile.nsys-rep')
                output_files.append('cuda_profile.sqlite')
            elif _profile_cuda_kernels:
                ncu = _global['ncu']['qpath']
                prefix_cmd += f'{ncu} --set basic --target-processes all -o cuda_profile_kernel '
                output_files.append('cuda_profile_kernel.ncu-rep')
                output_files.append('cuda_profile_kernel.ncu-rep.txt')

        # Setup Android
        if _android_cpu:
            start_exe_prefix = './'

            adb_with_serial = _global['adb']['qpath'] + ' -s ' + _global['target--android-cpu']['serial']
            add_to_local['adb_with_serial'] = adb_with_serial

            adb_tmp_path = '/data/local/tmp'
            add_to_local['adb_tmp_path'] = adb_tmp_path

            adb_tmp_path_lib = '/data/local/tmp/lib'
            add_to_local['adb_tmp_path_lib'] = adb_tmp_path_lib

        if _android_cpu:

            cmds.append(adb_with_serial + f' shell "rm -rf {adb_tmp_path_lib}"')
            cmds.append(adb_with_serial + f' shell "mkdir {adb_tmp_path_lib}"')
            cmds.append(adb_with_serial + f' shell "rm -rf {adb_tmp_path}/{target_exe}"')
            cmds.append(adb_with_serial + f' push "{target_path_exe}" {adb_tmp_path}/{target_exe}')
            cmds.append(adb_with_serial + f' shell chmod 755 {adb_tmp_path}/{target_exe}')

            # Check libs
            fdl = setup_compile.get('found_dynamic_libs')
            if fdl:
                for l in fdl:
                    if os.path.isfile(l):
                        ll = os.path.basename(l)
                        cmds.append(adb_with_serial + f' push "{l}" "{adb_tmp_path_lib}/{ll}"')

            # Check run-time env ...
            run_time_env['LD_LIBRARY_PATH'] = adb_tmp_path_lib

            envs = ''
            for k in run_time_env:
                v = run_time_env[k]
                if v is not None:
                    if envs != '':
                        envs +=' && '
                    envs += f'export {k}="{v}"'

            prefix_cmd = adb_with_serial + f' shell "cd {adb_tmp_path} && {envs} && '

            if _profile:
                prefix_cmd += 'simpleperf record -g -- '
                output_files.append('perf.data')

            postfix_cmd = '"'

        x = start_exe_prefix if target_exe else ''
        cmd = cmd.replace('{run_flags_after_exe}', run_flags_after_exe)
        run_time_cmd = prefix_cmd + x + cmd + postfix_cmd
        run_time_cmds.append(run_time_cmd)

        for f in output_files:
            # First clean on the host (remote device will upload to host)
            output_file = os.path.join(target_path, f) if target_path else os.path.join(os.getcwd(), f)

            if os.path.isfile(output_file):
                if con and verbose:
                    print (f'{space}INFO: Removing "{output_file}"')
                os.remove(output_file)

            if _android_cpu:
                cmds.append(adb_with_serial + f' shell "rm -rf {adb_tmp_path}/{f}"')
                run_time_cmds.append(adb_with_serial + f' pull {adb_tmp_path}/{f} {f}"')


        if _profile:
            if _android_cpu:
                x = os.path.join(_global['simpleperf-android']['qpath'] + ' report -i perf.data --sort symbol --children')
                run_time_cmds.append(x)

            if _cpu or _cuda:
                if uname == 'windows':
                    run_time_cmds.append(f'{wpr} -stop tmp-cmeta-wpr.etl')

#                    FGG: To be improved if needed - currently the profile is not exporting functions
#                    wpae = self.cm.q(os.path.join(x, 'wpaexporter'))
#                    run_time_cmds.append(f'{wpae} -i tmp-cmeta-wpr.etl -profile wpa-profile-cpu-usage.wpaProfile -symbols -outputfolder out')

                elif uname == 'linux':
                    run_time_cmds.append(f'{perf} report -i perf.data --sort symbol --children --stdio > perf_report.txt')

        if _profile_cuda:
            x = f'{nsys} stats --report cuda_gpu_kern_sum cuda_profile.nsys-rep'
            run_time_cmds.append(x)

        if _profile_cuda_kernels:
            x = f'{ncu} --import cuda_profile_kernel.ncu-rep --page details > cuda_profile_kernel.ncu-rep.txt'
            run_time_cmds.append(x)

        if _profile_python:
            python_path = ctx['tasks']['global']['python']['qpath']
            run_time_cmds.append(f'{python_path} -c "import pstats; p=pstats.Stats(\'tmp-cmeta-python-profile.out\'); p.sort_stats(\'cumulative\').print_stats(30)" > tmp-cmeta-python-profile.txt')

        if cmds:
            if con and verbose:
                print ('')
                print (f'{space}INFO: Running extra CMD for Android CPU')

            save_script = os.path.join(target_path, 'tmp-cmeta-prepare-run{{file_ext_bat}}')

            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmds': cmds,
                  'env': env,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
#                  'print_env_keys': ['PATH'],
                  'save_script': save_script,
                  'print_extra_line': True,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmds "{cmds}" failed with return code "{returncode}"'}


        if prefix_cmd:
            add_to_local['run_time_prefix_cmd'] = prefix_cmd
        if postfix_cmd:
            add_to_local['run_time_postfix_cmd'] = postfix_cmd

        add_to_local['start_exe_prefix'] = start_exe_prefix

        # Finish cmds
        add_to_local['run_time_cmds'] = run_time_cmds

        if add_to_local:
            result['add_to_local'] = add_to_local

        return result
