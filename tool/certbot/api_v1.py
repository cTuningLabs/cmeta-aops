"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def install(self, ctx, params, cmd=None, *misc):
        simple = params.get('version_simple')
        constraint = ('==' + simple) if simple else params.get('version')
        if not constraint:
            constraint = '==' + self.cdesc['default_version']
        spec = {'name': 'certbot', 'package': 'certbot', 'python': '3.12',
                'extra': ['certbot-apache' + constraint],
                'unsupported_os': {'windows': 'Certbot/Apache automation requires Linux or macOS; select the web host'}}
        return install_pyvenv(self, ctx, params, cmd, spec)
