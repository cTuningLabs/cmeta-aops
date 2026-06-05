"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
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

        sudo_installed = ctx['tasks']['global']['host'].get('os_extra', {}).get('sudo', False)
        passwordless_sudo = ctx['tasks']['global']['host'].get('os_extra', {}).get('passwordless_sudo', False)

        # If sudo is not installed, we think that we are likely inside container
        # and can turn on noninteractive mode too
        if passwordless_sudo or not sudo_installed:
            env['NONINTERACTIVE'] = 1

        result['timeout'] = None

        return result

