"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

sccache, the shared compilation cache from Mozilla (https://github.com/mozilla/sccache, Apache-2.0):
installed from its pinned upstream release (install ladder tier 1) by the shared helper
category/tool/api/common_release.py: the asset for this OS and CPU (the static musl build on Linux),
its SHA-256 checked against the per-asset ".sha256" file upstream publishes, the binary unpacked
and named "sccache".
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'sccache',
 'default_version': '0.18.0',
 'url': 'https://github.com/mozilla/sccache/releases/download/v{version}/sccache-v{version}-{arch}-{os}.{ext}',
 'os': {'linux': 'unknown-linux-musl', 'windows': 'pc-windows-msvc', 'darwin': 'apple-darwin'},
 'arch': {'amd64': 'x86_64', 'arm64': 'aarch64'},
 'ext': {'windows': 'zip', '*': 'tar.gz'},
 'checksum': {'file': '{url}.sha256'}}


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
        Download, verify and unpack the pinned sccache release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
