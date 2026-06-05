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
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        """

        result = {'return':0}

        r = self.cm.check_params(params, [
                'package', 
                'os', 
                'os_id', 
                'fail_if_wrong_host_os',
                'sudo',
                'version',
                'flags',
            ], __name__)
        if self.cm.catch_error(r): return r

        package = params.get('package')
        if not package:
            return self.cm.error(f'package is not defined in "{__file__}"')

        target_os = params.get('os')
        if target_os:
            if type(target_os) == str:
                target_os = target_os.split(',')

        target_os_id = params.get('os_id')
        if target_os_id:
            if type(target_os_id) == str:
                target_os_id = target_os_id.split(',')

        uname = ctx['tasks']['global']['host']['os']['uname']
        os_id = ctx['tasks']['global']['host']['os_extra']['id']

        fail_if_wrong_host_os = params.get('fail_if_wrong_host_os', False)

        if target_os and uname not in target_os:
            if fail_if_wrong_host_os:
                return self.cm.error(f'host OS "{uname}" is not supported for sys-tool "{package}" "{__file__}"')
            else:
                return {'return':0, 'skip_run': True}

        if target_os_id and os_id not in target_os_id:
            if fail_if_wrong_host_os:
                return self.cm.error(f'host OS ID "{os_id}" is not supported for sys-tool "{package}" "{__file__}"')
            else:
                return {'return':0, 'skip_run': True}

        sudo = params.get('sudo', False)
        version = params.get('version')
        flags = params.get('flags')

        _local = ctx['tasks']['local']

        key = 'install_cmd'
        if sudo:
            key += '_sudo'
        if version:
            key += '_version'

        cmd = ctx['tasks']['global']['host']['os_extra'][key]

        cmd = cmd.replace('{{name}}', package)
        if version:
            cmd = cmd.replace('{{version}}', version)

        if flags:
            cmd += ' ' + flags

        _local['cmd'] = cmd

        result['cmd'] = cmd
        result['host_os'] = uname
        result['host_os_id'] = os_id

        return result

