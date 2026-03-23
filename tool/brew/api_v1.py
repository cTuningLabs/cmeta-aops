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

        passwordless_sudo = ctx['tasks']['global']['host'].get('os_extra', {}).get('passwordless_sudo', False)

        if passwordless_sudo:
            env['NONINTERACTIVE'] = 1

        result['timeout'] = None

        return result
