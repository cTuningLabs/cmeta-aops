"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Helm, the package manager for Kubernetes (https://helm.sh, Apache-2.0): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "helm".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'helm',
 'default_version': '4.3.0',
 'url': 'https://get.helm.sh/helm-v{version}-{os}-{arch}.{ext}',
 'ext': {'windows': 'zip', '*': 'tar.gz'},
 'member': '{os}-{arch}/helm{exe}',
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
        Download, verify and unpack the pinned helm release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
