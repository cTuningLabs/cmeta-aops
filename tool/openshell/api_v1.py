"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

NVIDIA OpenShell (https://github.com/NVIDIA/OpenShell, Apache-2.0): the CLI "openshell" and the gateway
"openshell-gateway" from the pinned release, into the cache entry, each checked against the release's own SHA-256
list (openshell-checksums-sha256.txt, openshell-gateway-checksums-sha256.txt). The two assets spell Linux apart: the
CLI is a static musl binary, the gateway links glibc - so two specs of the shared release helper. The gateway's path
is in the result (features.paths.gateway), next to the CLI.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

RELEASE = 'https://github.com/NVIDIA/OpenShell/releases/download/v{version}/'

CLI = {'name': 'openshell',
       'url': RELEASE + 'openshell-{arch}-{os}.tar.gz',
       'ext': {'*': 'tar.gz'},
       'os': {'linux': 'unknown-linux-musl', 'darwin': 'apple-darwin'},
       'arch': {'amd64': 'x86_64', 'arm64': 'aarch64'},
       'unsupported': [['darwin', 'amd64']],
       'checksum': {'list': RELEASE + 'openshell-checksums-sha256.txt'}}

GATEWAY = dict(CLI, name='openshell-gateway',
               url=RELEASE + 'openshell-gateway-{arch}-{os}.tar.gz',
               os={'linux': 'unknown-linux-gnu', 'darwin': 'apple-darwin'},
               checksum={'list': RELEASE + 'openshell-gateway-checksums-sha256.txt'})


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
        The CLI and the gateway of the pinned (or requested) release for this OS and CPU, both into content/.
        """
        r = install_release(self, ctx, params, cmd, GATEWAY)
        if r['return'] > 0:
            return r
        return install_release(self, ctx, params, cmd, CLI)

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The gateway next to the CLI (features.paths.gateway; '' when an installation has none, a CLI-only copy).
        """
        folder = result.get('path_bin') or os.path.dirname(result.get('path') or '')
        gateway = os.path.join(folder, 'openshell-gateway')
        paths = result.setdefault('features', {}).setdefault('paths', {})
        paths['gateway'] = gateway if os.path.isfile(gateway) else ''
        paths['qgateway'] = self.cm.utils.files.quote_path(paths['gateway']) if paths['gateway'] else ''
        return {'return': 0, 'result': result}
