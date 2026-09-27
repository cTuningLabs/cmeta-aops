"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Terraform, infrastructure as code (https://developer.hashicorp.com/terraform, BUSL-1.1): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "terraform".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'terraform',
 'default_version': '1.16.4',
 'url': 'https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{os}_{arch}.zip',
 'ext': {'*': 'zip'},
 'checksum': {'list': 'https://releases.hashicorp.com/terraform/{version}/terraform_{version}_SHA256SUMS'}}


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
        Download, verify and unpack the pinned terraform release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
