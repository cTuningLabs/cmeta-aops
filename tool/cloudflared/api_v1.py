"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cloudflared, the Cloudflare Tunnel client (https://github.com/cloudflare/cloudflared, Apache-2.0):
installed from its pinned upstream release (install ladder tier 1) by the shared helper
category/tool/api/common_release.py.

Upstream writes SHA-256 sums only into the release notes (no checksum file to download), so the
spec pins the digests GitHub computes for each asset (the "digest" of the release API) - the sums
of the very files that are downloaded. Another version is downloaded over HTTPS only; add its
digests here when default_version is bumped:

    gh api repos/cloudflare/cloudflared/releases/tags/<version> --jq '.assets[] | [.name, .digest]'
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {'name': 'cloudflared',
 'url': 'https://github.com/cloudflare/cloudflared/releases/download/{version}/cloudflared-{os}-{arch}{exe}',

 # A bare binary on Linux and Windows; on macOS a .tgz holding the binary "cloudflared"
 # (the asset suffix rides in {exe}; the member names the file inside the archive)
 'exe': {'windows': '.exe', 'darwin': '.tgz', '*': ''},
 'ext': {'darwin': 'tgz'},
 'member': 'cloudflared',

 'unsupported': [['windows', 'arm64']],
 'checksum': {'sha256': {
     '2026.10.0': {
         'cloudflared-linux-amd64': 'd33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db',
         'cloudflared-linux-arm64': 'e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08',
         'cloudflared-darwin-amd64.tgz': '903845b81828c8cb3c5d13d816a2de71c06a3da5785469df8eb0e1b736d92f9f',
         'cloudflared-darwin-arm64.tgz': 'a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70',
         'cloudflared-windows-amd64.exe': '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c'},
     '2026.10.1': {
         'cloudflared-linux-amd64': '3bfc539f45d2620c71debb7a86be0efa737ed5ccbad9eb85c787116900e5c586',
         'cloudflared-linux-arm64': '2c65dfabf616c40efc7545d107d7a57ad5e21377e2964b7e88af19a238074a46',
         'cloudflared-darwin-amd64.tgz': '3b0dbaf378337e9d7fb6cd235a76d1d6a7dee434c2d8edf9281164fb6a3837ab',
         'cloudflared-darwin-arm64.tgz': '647615df99d49cd179ea5e13ef760b9bbfb33630f6ae62f87e33dfadda60adcc',
         'cloudflared-windows-amd64.exe': '4d2490e74082c5d48dbfedaf92576fa5bd1702379ab88eb7faa0cfbe8dc891b6'}}}}


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
        Download, verify and place the pinned cloudflared release for this OS and CPU.
        """
        return install_release(self, ctx, params, cmd, SPEC)
