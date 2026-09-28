"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

kwokctl and kwok, Kubernetes without kubelets (https://kwok.sigs.k8s.io, Apache-2.0): installed from its pinned upstream
release (install ladder tier 1) by the shared helper category/tool/api/common_release.py:
the asset for this OS and CPU, its SHA-256 checked where upstream publishes checksums,
the binary unpacked and named "kwokctl".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'kwokctl',
 'default_version': '0.8.0',
 'url': 'https://github.com/kubernetes-sigs/kwok/releases/download/v{version}/kwokctl-{os}-{arch}{exe}',
 'extra': [{'name': 'kwok',
            'url': 'https://github.com/kubernetes-sigs/kwok/releases/download/v{version}/kwok-{os}-{arch}{exe}'}]}


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
        Download, verify and unpack the pinned kwokctl release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
