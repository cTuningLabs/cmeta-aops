"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

yq, the YAML processor (https://mikefarah.gitbook.io/yq, MIT): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "yq".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'yq',
 'default_version': '4.53.6',
 'url': 'https://github.com/mikefarah/yq/releases/download/v{version}/yq_{os}_{arch}{exe}',
 'checksum': {'yq': 'https://github.com/mikefarah/yq/releases/download/v{version}/checksums',
              'order': 'https://github.com/mikefarah/yq/releases/download/v{version}/checksums_hashes_order'}}


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
        Download, verify and unpack the pinned yq release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
