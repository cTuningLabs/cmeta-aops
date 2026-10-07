"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

hyperfine, the command-line benchmarking tool (https://github.com/sharkdp/hyperfine, MIT / Apache-2.0):
installed from its pinned upstream release (install ladder tier 1) by the shared helper
category/tool/api/common_release.py: the asset for this OS and CPU, the binary unpacked and
named "hyperfine". Upstream publishes no checksums for its release assets (HTTPS only).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'hyperfine',
 'default_version': '1.21.0',
 'url': 'https://github.com/sharkdp/hyperfine/releases/download/v{version}/hyperfine-v{version}-{arch}-{os}.{ext}',
 'os': {'linux': 'unknown-linux-gnu', 'windows': 'pc-windows-msvc', 'darwin': 'apple-darwin'},
 'arch': {'amd64': 'x86_64', 'arm64': 'aarch64'},
 'ext': {'windows': 'zip', '*': 'tar.gz'}}


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
        Download and unpack the pinned hyperfine release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
