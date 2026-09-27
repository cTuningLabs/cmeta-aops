"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Kustomize, template-free Kubernetes configuration (https://kustomize.io, Apache-2.0): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "kustomize".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'kustomize',
 'default_version': '5.8.1',
 'url': 'https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv{version}/kustomize_v{version}_{os}_{arch}.{ext}',
 'ext': {'windows': 'zip', '*': 'tar.gz'},
 'checksum': {'list': 'https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv{version}/checksums.txt'}}


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
        Download, verify and unpack the pinned kustomize release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
