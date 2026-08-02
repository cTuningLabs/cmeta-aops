"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str = None,
                              params: dict = {},
                              env: dict = {},
                              timeout: int = None,
                              *misc: dict,
    ):
        """
        """

        result = {'return':0}

        os_id_like = ctx['tasks']['global']['host'].get('os_extra', {}).get('id_like', '')

        package_name = None

        if os_id_like == 'debian':
            package_name = 'xz-utils'
        elif 'fedora' in os_id_like: # can be 'rhel centos fedora' besides 'fedora'
            package_name = 'xz'

        if package_name:
            result['package_name'] = package_name

        return result

