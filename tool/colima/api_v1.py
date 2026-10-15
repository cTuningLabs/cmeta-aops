"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

colima (https://github.com/abiosoft/colima, MIT): installed from its pinned upstream release (install ladder tier 1)
by the shared helper category/tool/api/common_release.py - the one binary for this OS and CPU, its SHA-256 checked
against the .sha256sum file published next to it, named "colima". The VM layer (limactl) is tool/lima.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'colima',
        'url': 'https://github.com/abiosoft/colima/releases/download/v{version}/colima-{os}-{arch}',
        'os': {'darwin': 'Darwin', 'linux': 'Linux'},
        'arch': {'arm64': 'arm64', 'amd64': 'x86_64'},
        'checksum': {'file': '{url}.sha256sum'}}


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Download, verify and place the pinned colima release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
