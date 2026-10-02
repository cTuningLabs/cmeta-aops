"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

flatc, the FlatBuffers schema compiler (https://github.com/google/flatbuffers, Apache-2.0):
installed from its pinned GitHub release (install ladder tier 1) by the shared helper
category/tool/api/common_release.py. The release has one zip per platform: Windows x64, Linux
x86_64, macOS arm64 and x86_64; the SHA-256 digests of the default release (which GitHub lists
in its API only) are pinned below. Elsewhere (Linux aarch64, Windows arm64), setup falls back
to the declarative install_cmd of _desc.yaml.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

RELEASES = 'https://github.com/google/flatbuffers/releases/download/v{version}/'

# The release asset of each platform
ASSETS = {('windows', 'amd64'): 'Windows.flatc.binary.zip',
          ('linux', 'amd64'): 'Linux.flatc.binary.g++-13.zip',
          ('darwin', 'arm64'): 'Mac.flatc.binary.zip',
          ('darwin', 'amd64'): 'MacIntel.flatc.binary.zip'}

SPEC = {'name': 'flatc',
        'default_version': '25.12.19',
        'ext': {'*': 'zip'},
        'checksum': {'sha256': {'25.12.19': {
            'Windows.flatc.binary.zip': 'fff9445c9db907227bc64b54cc98743084c4949282aa4e576cff6a955724ddc8',
            'Linux.flatc.binary.g++-13.zip': '9f87066dc5dfa7fe02090b55bab5f3e55df03e32c9b0cdf229004ade7d091039',
            'Mac.flatc.binary.zip': '9340a5f9900b95e34ccadcb06bceec91180cc8b83098d5e966ed6d8d590cbba2',
            'MacIntel.flatc.binary.zip': 'b1b0c5bd2b4a19282d461e5ba725f41399af23ef42f4277605b75148996f2f4b'}}}}


def asset_for(uname, uarch):
    """The release asset for this OS and CPU, or None."""
    return ASSETS.get((uname, uarch))


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
        Download, verify and unpack the pinned flatc release for this OS and CPU; elsewhere,
        return 16 so setup falls back to the package manager.
        """

        host = ctx['tasks']['global']['host']['os']
        asset = asset_for(host['uname'], host['uarch'])
        if not asset:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'flatc publishes no release binary for {host["uname"]}/{host["uarch"]}'}

        return install_release(self, ctx, params, cmd, dict(SPEC, url = RELEASES + asset))
