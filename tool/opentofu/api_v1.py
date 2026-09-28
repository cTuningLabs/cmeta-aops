"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

OpenTofu, open-source infrastructure as code (https://opentofu.org, MPL-2.0): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "tofu".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'tofu',
 'default_version': '1.12.6',
 'url': 'https://github.com/opentofu/opentofu/releases/download/v{version}/tofu_{version}_{os}_{arch}.zip',
 'ext': {'*': 'zip'},
 'checksum': {'list': 'https://github.com/opentofu/opentofu/releases/download/v{version}/tofu_{version}_SHA256SUMS'},
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
        Download, verify and unpack the pinned tofu release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
