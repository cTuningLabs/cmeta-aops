"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

k3d, k3s clusters in Docker (https://k3d.io, MIT): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "k3d".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'k3d',
 'default_version': '5.9.0',
 'url': 'https://github.com/k3d-io/k3d/releases/download/v{version}/k3d-{os}-{arch}{exe}',
 'checksum': {'list': 'https://github.com/k3d-io/k3d/releases/download/v{version}/checksums.txt'},
 'unsupported': [['windows', 'arm64']]}


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
        Download, verify and unpack the pinned k3d release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
