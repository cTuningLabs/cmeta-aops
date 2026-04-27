"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            api_level: str = None,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK test-clang-cpp run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        ctx_tasks_control = ctx['tasks']['run_control']

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        compiler = ctx['tasks']['global']['android-ndk-clang']
        compiler_path = compiler['path']
        compiler_qpath = compiler['qpath']

        adb_qpath = ctx['tasks']['global']['adb']['qpath']

        os.chdir(task_path)

        if not os.path.isdir('tmp'):
            os.makedirs('tmp')

        target_android = ctx['tasks']['global']['target-android-cpu']
        target_adb_device_serial_number = target_android['features']['adb_device_serial_number']


        abi = target_android['features']['ro.product.cpu.abi']

        clang_target = None
        clang_abi = None
        clang_abi_extra = ''

        if abi == 'arm64-v8a':
            clang_abi = 'aarch64'
            clang_abi_extra = ''
        elif abi == 'armeabi-v7a':
            clang_abi = 'armv7a'
            clang_abi_extra = 'eabi'

        if not clang_abi:
            return self.cm.error(f'could\'t create clang_android_target for Android abi "{abi}" in "{__file__}" ({__name__})')

        clang_target = f'{clang_abi}-linux-android{clang_abi_extra}'

        if not api_level:
            api_level = target_android['features']['ro.build.version.sdk']

        api_levels_from_clang = compiler['features']['abi-android-versions'][clang_abi]
        max_api_level_from_clang = max(api_levels_from_clang, key=int)

        if con:
            print ('')
            print (f'Requested Android API level: {api_level}')
        
        if int(api_level) > int(max_api_level_from_clang):
            api_level = int(max_api_level_from_clang)

            if con:
                print (f'Selected available Clang Android API level: {api_level}')

        clang_target += str(api_level)

        if con:
            print (f'Clang target: {clang_target}')


        sn = '-s ' + target_adb_device_serial_number

        cmds = [
          f'{compiler_qpath} --target={clang_target} -O2 -v -o tmp/test src/test.c',
          f'{adb_qpath} {sn} push tmp/test /data/local/tmp/test',
          f'{adb_qpath} {sn} shell chmod 755 /data/local/tmp/test',
          f'{adb_qpath} {sn} shell /data/local/tmp/test',
        ]

        for icmd in range(0, len(cmds)):
            cmd = cmds[icmd]

            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
#                  'print_env_keys': ['PATH'], 
                  'print_extra_line': True,
                  'save_script': f'tmp/save-script-{icmd}' + '{{file_ext_bat}}',
                  'storage_key': f'test-android-clang-compile-and-run-cmd-{icmd}',
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}


        print ('='*80)
        print (f'CLANG PATH: {compiler_path}')
        print ('='*80)

        return result
