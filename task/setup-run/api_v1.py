"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import re
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask, supported_options, nvidia_counters_for_admins_only, running_as_administrator

from . import android

from task_c36be4b9314a45e0.api import ios

# What "nsys profile --capture-range-end" takes, as its own help writes it: none, stop, stop-shutdown,
# repeat[:N][:mode], repeat-shutdown:N[:mode] - mode one of defer, sync, async
CAPTURE_RANGE_END = re.compile(r'^(none|stop|stop-shutdown|repeat(:\d+)?(:(defer|sync|async))?'
                               r'|repeat-shutdown:\d+(:(defer|sync|async))?)$')

# nsys's own end of a range is stop-shutdown: the session ends with the first range - and with it the program, which
# nsys then ends (--kill is true by default); what a program writes after its range would be lost. "stop" ends the
# recording and lets the program run on
CAPTURE_RANGE_END_DEFAULT = 'stop'


def quoted(word):
    """A word of a command line as a shell takes it whole: in double quotes unless it is plain (a name, a path
    without spaces, an option with its value)."""
    word = str(word)
    return word if re.fullmatch(r'[\w.:@=/+\-]+', word) else '"' + word + '"'


def capture_range(asked, end = None):
    """
    The words of "nsys profile" that record only the part of a run the program marks (--profile_cuda_range):

        cudaProfilerApi              from cudaProfilerStart to cudaProfilerStop (torch.cuda.profiler.start / stop)
        nvtx:<range>[@<domain>]      while that NVTX range is open (<range>@*: in any domain)

    and what the end of the range does (--profile_cuda_range_end, nsys's own words): stop (the default here), repeat or
    repeat:<N> (every range, or the first N), none, stop-shutdown, repeat-shutdown:<N>.

    Returns (words, error): the list of words - empty when no range is asked - or the text of the error.
    """
    asked = str(asked or '').strip()
    end = str(end or '').strip()
    if not asked:
        if end:
            return [], f'profile_cuda_range_end ({end}) says what the end of a range does: it needs --profile_cuda_range'
        return [], ''

    if asked.lower() == 'cudaprofilerapi':
        words = ['--capture-range=cudaProfilerApi']
    elif asked.lower().startswith('nvtx:') and asked[5:].strip():
        # the name goes into a command line: nothing a shell reads as its own
        if re.search(r'["\'`&|;<>$^%!\r\n]', asked[5:]):
            return [], f'profile_cuda_range: the NVTX range "{asked[5:].strip()}" holds a character a shell reads as its own'
        # nsys compares a range's name with registered NVTX strings only, unless the program is told otherwise: a
        # range pushed with a plain string (torch.cuda.nvtx.range_push) started no recording - "No reports were
        # generated" (seen with Nsight Systems 2026.1 on Linux, 2026-11-26)
        words = ['--capture-range=nvtx', '--nvtx-capture=' + asked[5:].strip(),
                 '--env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0']
    else:
        return [], (f'profile_cuda_range: "{asked}" is not a range Nsight Systems can wait for - cudaProfilerApi '
                    '(cudaProfilerStart / Stop in the program) or nvtx:<range>[@<domain>] (an NVTX range)')

    end = end or CAPTURE_RANGE_END_DEFAULT
    if not CAPTURE_RANGE_END.match(end):
        return [], (f'profile_cuda_range_end: "{end}" is not one of nsys\'s words - none, stop, stop-shutdown, '
                    'repeat[:N][:defer|sync|async], repeat-shutdown:N[:defer|sync|async]')
    return words + ['--capture-range-end=' + end], ''


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

        ################################################################################
        target_compute = _global['target']['compute']

        # Every Android target runs on the device that target--android-cpu selected (android-gpu and
        # android-npu set it up too): pushed and run over adb. A program that drives the device
        # from the host itself (run_on_host: True, e.g. one that exports models with the host's
        # Python and then pushes and runs them with adb) runs on the host.
        _android_cpu = (any(c in ('android-cpu', 'android-gpu', 'android-npu') for c in target_compute)
                        and not params.get('run_on_host'))
        _cuda = True if 'cuda' in target_compute else False

        # An OpenCL program's host code runs on this machine, as a CUDA program's does: it finds its
        # dynamic libraries (lib-xopenme, lib-polybench ...) the same way
        _opencl = 'opencl' in target_compute

        # A program for an iPhone or iPad runs inside an app bundle on the device that target--ios-cpu
        # selected (ios-gpu and ios-npu set it up too): signed, installed and launched with devicectl (ios.py)
        _ios = (any(c in ('ios-cpu', 'ios-gpu', 'ios-npu') for c in target_compute)
                and not params.get('run_on_host'))

        _cpu = False
        if 'cpu' in target_compute:
            _cpu = True
        if _android_cpu or _ios:
            _cpu = False

        ################################################################################
        # Duplicated in setup-run if we need to update names without compilation
        # (such as python)
        src_file_names = params.get('run_src_file_names')
        if src_file_names:
            src_file_names_str = ''
            src_file_names_str_with_path = ''
            src_path = ctx['tasks']['local']['src_path']

            for sfn in src_file_names:
                sfn = sfn.replace('//', os.sep)

                if src_file_names_str != '':
                    src_file_names_str += ' '
                src_file_names_str += sfn

                # quoted when it holds a space (a home under "C:\Users\First Last"): the joined list goes into a command line
                sfnp = self.cm.utils.files.quote_path(os.path.join(src_path, sfn))
                if src_file_names_str_with_path != '':
                    src_file_names_str_with_path += ' '
                src_file_names_str_with_path += sfnp

            ctx['tasks']['local']['run_src_file_names_str'] = src_file_names_str
            ctx['tasks']['local']['run_src_file_names_str_with_path'] = src_file_names_str_with_path

        ################################################################################
        target_path = params.get('target_path_bin')
        if target_path is None:
            target_path = params.get('target_path')
            if target_path is None:
                target_path = os.getcwd()

        target_path = target_path.replace('//', os.sep)

        ctx['tasks']['local']['target_path'] = target_path

        target_exe = params.get('target_exe')
        if target_exe:
            target_path_exe = os.path.join(target_path, target_exe)

            ctx['tasks']['local']['target_path_exe'] = target_path_exe

        if _android_cpu:
           target_xpath_exe = f'./{target_exe}'
        elif _ios:
           # the launch command (the prefix) names the app by its bundle id; the arguments follow
           target_xpath_exe = ''
        elif not target_exe:
           target_xpath_exe = ''
        else:
           target_xpath_exe = target_path_exe

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


        ################################################################################
        input_files = params.get('input_files')
        if input_files is None:
            input_files = {}
        else:
            input_files = {k: v.replace("//", os.sep) for k, v in input_files.items()}

        r = self.cm.utils.common.expand_strings_in_dict(input_files, ctx_tasks)
        if self.cm.catch_error(r): return r

        ################################################################################
        output_files = params.get('output_files')
        if output_files is None:
            output_files = []
        else:
            output_files = output_files.copy()

        r = self.cm.utils.common.expand_strings_in_dict(output_files, ctx_tasks)
        if self.cm.catch_error(r): return r

        # Update input files
        for k in input_files:
            v = input_files[k]

            if _android_cpu:
                v = os.path.basename(v)

            kk = f'input_files.{k}'
            cmd = cmd.replace('{'+kk+'}', v)

            kk = f'qinput_files.{k}'
            cmd = cmd.replace('{'+kk+'}', self.cm.q(v))

        run_time_env = ctx['tasks']['local'].get('run_time_env', {})

        r = self.cm.utils.common.expand_strings_in_dict(run_time_env, ctx_tasks)
        if self.cm.catch_error(r): return r

        ###########################################################################################

        add_to_local = {}

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
            # Nsight Compute reads the GPU's performance counters: a driver that keeps them for administrators makes it
            # stop with ERR_NVGPUCTRPERM - said before the run, with the way to allow them (2026-11-25)
            if con and nvidia_counters_for_admins_only() and not running_as_administrator():
                how = ('NVIDIA Control Panel - Desktop: Enable Developer Settings, then Developer: Manage GPU Performance '
                       'Counters: "Allow access to the GPU performance counters to all users" (an administrator)'
                       if os.name == 'nt' else
                       'a line "options nvidia NVreg_RestrictProfilingToAdminUsers=0" in a file of /etc/modprobe.d and '
                       'a reboot (root)')
                print("cMeta warning: Nsight Compute reads the GPU's performance counters, which this NVIDIA driver "
                      'lets administrators only read (ERR_NVGPUCTRPERM): ' + how + ' - or run this as an administrator')


        run_flags_after_exe = params.get('run_flags_after_exe')
        if run_flags_after_exe is None:
            run_flags_after_exe = ''

        cmds = []
        run_time_cmds = []

        # --profile_cuda_range: the words of nsys for the range (none: the whole run is recorded)
        ranged = []

        # Setup CPU
        if _profile_python:
            if run_flags_after_exe != '':
                run_flags_after_exe += ' '
            run_flags_after_exe += '-m cProfile -s cumulative -o tmp-cmeta-python-profile.out'

            output_files.append('tmp-cmeta-python-profile.out')
            output_files.append('tmp-cmeta-python-profile.txt')

        if _cpu or _cuda or _opencl:
            fdlp = setup_compile.get('found_dynamic_lib_paths')
            if not fdlp:
                fdlp = []

            global_keys_with_dynamic_libs = params.get('global_keys_with_dynamic_libs', [])
            for k in global_keys_with_dynamic_libs:
                fdlp2 = _global[k].get('features',{}).get('paths',{}).get('found_dynamic_lib_paths', [])
                if fdlp2:
                    fdlp += fdlp2

            if fdlp:
                if uname == 'windows':
                    env_dlib = run_time_env.setdefault('+PATH', [])
                elif uname == 'darwin':
                    env_dlib = run_time_env.setdefault('+DYLD_LIBRARY_PATH', [])
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
                # A program whose work runs in a process it forks and then executes (a model server's engine) shows no
                # kernel unless nsys follows it between the two - where this nsys has the option (Linux; the Windows
                # nsys has none): asked of its own help
                # and a run again in the same folder replaces the report of before (--force-overwrite), where it can
                nsys_path = _global['nsys'].get('path') or str(nsys).strip('"')
                follow = ''.join(f' {o}=true' for o in supported_options(nsys_path, ['profile', '--help'],
                                                                        ['--trace-fork-before-exec', '--force-overwrite']))

                # only the part of the run the program marks (--profile_cuda_range): asked of this nsys's own help too
                ranged, why = capture_range(params.get('profile_cuda_range'), params.get('profile_cuda_range_end'))
                if why:
                    return self.cm.error(why)
                if ranged:
                    needed = [w.split('=')[0] for w in ranged]
                    missing = [o for o in needed if o not in supported_options(nsys_path, ['profile', '--help'], needed)]
                    if missing:
                        return self.cm.error(f'profile_cuda_range: this Nsight Systems ({_global["nsys"].get("version") or nsys_path}) '
                                             f'has no {", ".join(missing)} - a newer one: --use.nsys.version=latest')
                    follow += ''.join(' ' + quoted(w) for w in ranged)
                    if con:
                        print(f'{space}INFO: Nsight Systems records only {params.get("profile_cuda_range")}'
                              f' ({" ".join(ranged)})')

                # "repeat" gives every range a report of its own, numbered: cuda_profile.<n>.nsys-rep. Those of a run
                # before in this folder go before any profiled run, as its one report does (output_files): the summary
                # of a later run read the reports of the run before otherwise
                folder = target_path or os.getcwd()
                for name in os.listdir(folder) if os.path.isdir(folder) else []:
                    if re.fullmatch(r'cuda_profile\.\d+\.(nsys-rep|sqlite)', name):
                        os.remove(os.path.join(folder, name))
                prefix_cmd += f'{nsys} profile --trace=cuda,nvtx{follow} --stats=true -o cuda_profile '
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

            # Only for a program of its own: without one, "rm -rf /data/local/tmp/" would empty
            # the device's work folder (programs that run a release keep it in a folder below)
            if target_exe:
                cmds.append(adb_with_serial + f' shell "rm -rf {adb_tmp_path}/{target_exe}"')
                cmds.append(adb_with_serial + f' push "{target_path_exe}" {adb_tmp_path}/{target_exe}')
                cmds.append(adb_with_serial + f' shell chmod 755 {adb_tmp_path}/{target_exe}')

            # Folders and large files kept on the device between runs (a llama.cpp release or
            # build, a model): pushed once, and again only when they change
            adb_path = _global['adb']['path']
            serial = _global['target--android-cpu']['serial']
            for device_dir, files in (params.get('android_push_folders') or {}).items():
                ddir = android.device_path(adb_tmp_path, device_dir)
                if con:
                    print (f'{space}INFO: Android folder {ddir} ({len(files)} files) ...')
                pushed, error = android.push_folder(adb_path, serial, list(files), ddir)
                if error:
                    return self.cm.error(f'failed to push to {ddir} on the Android device: {error}')
                if con:
                    print (f'{space}      ' + ('pushed' if pushed else 'already on the device'))
            for device_file, host_file in (params.get('android_push_files') or {}).items():
                dfile = android.device_path(adb_tmp_path, device_file)
                if con:
                    print (f'{space}INFO: Android file {dfile} ...')
                pushed, error = android.push_file(adb_path, serial, host_file, dfile)
                if error:
                    return self.cm.error(f'failed to push {host_file} to {dfile} on the Android device: {error}')
                if con:
                    print (f'{space}      ' + ('pushed' if pushed else 'already on the device'))

            # Process input files
            for k in input_files:
                f = input_files[k]
                ff = os.path.basename(f)

                cmds.append(adb_with_serial + f' push "{f}" {adb_tmp_path}/{ff}')

                input_files[k] = ff

            # Check libs
            fdl = setup_compile.get('found_dynamic_libs')
            if fdl:
                for l in fdl:
                    if os.path.isfile(l):
                        ll = os.path.basename(l)
                        cmds.append(adb_with_serial + f' push "{l}" "{adb_tmp_path_lib}/{ll}"')

            # Check run-time env ... (the folders of a release or build first)
            ld_paths = [android.device_path(adb_tmp_path, p) for p in (params.get('android_ld_library_path') or [])]
            run_time_env['LD_LIBRARY_PATH'] = ':'.join(ld_paths + [adb_tmp_path_lib])

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

        # Setup iOS: the bundle, its signature and its installation before the run; the launch with the console
        if _ios:
            if not target_exe:
                return self.cm.error('a program for the ios-cpu target needs an executable (target_exe) to put into its app bundle')

            target_ios = _global['target--ios-cpu']
            signing = target_ios.get('signing') or {}
            udid = target_ios['udid']
            bundle_id = signing.get('bundle_id') or target_ios.get('bundle_id')
            devicectl = target_ios.get('devicectl') or 'xcrun devicectl'

            app_dir = os.path.join(target_path, target_exe + '.app')
            error = ios.make_bundle(app_dir, target_path_exe, bundle_id, signing['profile'], target_ios.get('min_os') or ios.MIN_OS)
            if error:
                return self.cm.error(f'the app bundle "{app_dir}" could not be made: {error}')
            if con and verbose:
                print (f'{space}INFO: app bundle "{app_dir}" ({bundle_id})')

            prefix, error = ios.signing_prefix()
            if error:
                return self.cm.error(error)

            cmds.append(ios.codesign_cmd(prefix, signing['identity'], signing['entitlements'], app_dir, self.cm.q))
            cmds.append(ios.install_cmd(devicectl, udid, app_dir, self.cm.q))

            # Input files go into the app's Documents folder, the program's working folder
            for k in input_files:
                f = input_files[k]
                ff = os.path.basename(f)
                cmds.append(ios.copy_to_cmd(devicectl, udid, bundle_id, f, ff, self.cm.q))
                input_files[k] = ff

            # The run-time environment travels with the launch; the launcher removes last run's output files
            env_on_device = {k: str(v) for k, v in run_time_env.items() if v is not None and not k.startswith('+')}
            if output_files:
                env_on_device['CMETA_IOS_CLEAN'] = ';'.join(output_files)

            add_to_local['ios_app_dir'] = app_dir
            add_to_local['ios_bundle_id'] = bundle_id

            prefix_cmd = ios.launch_prefix(devicectl, udid, bundle_id, env_on_device)
            postfix_cmd = ios.LAUNCH_POSTFIX

        x = start_exe_prefix if target_exe else ''

        y = x + target_exe if target_exe else ''
        cmd = cmd.replace('{target_exe}', y)

        y = target_xpath_exe if target_xpath_exe else ''
        cmd = cmd.replace('{target_xpath_exe}', y)

        cmd = cmd.replace('{run_flags_after_exe}', run_flags_after_exe)

        if src_file_names:
            cmd = cmd.replace('{run_src_file_names_str_with_path}', src_file_names_str_with_path)

        run_time_cmd = prefix_cmd + cmd + postfix_cmd

        run_time_cmds.append(run_time_cmd)

        for f in output_files:
            # First clean on the host (remote device will upload to host)
            output_file = os.path.join(target_path, f) if target_path else os.path.join(os.getcwd(), f)

            if os.path.isfile(output_file):
                if con and verbose:
                    print (f'{space}INFO: Removing "{output_file}"')
                os.remove(output_file)

            # Files the host makes after the run (llama.cpp's perf.json) are not on the device
            if _android_cpu and f not in (params.get('android_skip_pull') or []):
                x1 = f'{adb_tmp_path}/{f}'
                xx1 = self.cm.qq(x1)
                x2 = f'{f}'
                xx2 = self.cm.qq(x2)
                cmds.append(adb_with_serial + f' shell "rm -rf {xx1}"')
                run_time_cmds.append(adb_with_serial + f' pull {xx1} {xx2}')

            if _ios:
                run_time_cmds.append(ios.copy_from_cmd(devicectl, udid, bundle_id, f, f, self.cm.q))

        # The program's exit code on the device, written by the launcher (devicectl reports none)
        if _ios:
            run_time_cmds.append(ios.copy_from_cmd(devicectl, udid, bundle_id, ios.EXIT_FILE, ios.EXIT_FILE, self.cm.q))
            run_time_cmds.append(ios.exit_check_cmd())

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
            # the export of a run before in this folder is older than this report: nsys refuses it ("Use --force-export
            # =true to update export file") and the step failed on every run after the first (2026-11-25, WSL)
            force = ''.join(f' {o}=true' for o in supported_options(_global['nsys'].get('path') or str(nsys).strip('"'),
                                                                   ['stats', '--help'], ['--force-export']))
            each = f'{nsys} stats{force} --report cuda_gpu_kern_sum'
            if ranged:
                # the summary of every report the run left - one, or one per range with "repeat" - and words when
                # the program never met its range (nsys: "No reports were generated"): nsys_range_reports.py, the
                # same line on every system
                helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nsys_range_reports.py')
                x = f'{quoted(sys.executable)} {quoted(helper)} {quoted(str(params.get("profile_cuda_range")).strip())} {each}'
            else:
                x = f'{each} cuda_profile.nsys-rep'
            run_time_cmds.append(x)

        if _profile_cuda_kernels:
            x = f'{ncu} --import cuda_profile_kernel.ncu-rep --page details > cuda_profile_kernel.ncu-rep.txt'
            run_time_cmds.append(x)

        if _profile_python:
            python_path = ctx['tasks']['global']['python']['qpath']
            run_time_cmds.append(f'{python_path} -c "import pstats; p=pstats.Stats(\'tmp-cmeta-python-profile.out\'); p.sort_stats(\'cumulative\').print_stats(30)" > tmp-cmeta-python-profile.txt')

        if 'setup-dynamic-libs' in ctx['tasks']['local']:
            dynamic_lib_paths = ctx['tasks']['local']['setup-dynamic-libs'].get('found_dynamic_lib_paths')
            if dynamic_lib_paths:
                ctx['tasks']['local']['run_time_env']['+PATH'] = dynamic_lib_paths

        if cmds:
            if con and verbose:
                print ('')
                print (f'{space}INFO: Running extra CMD for the target device')

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

