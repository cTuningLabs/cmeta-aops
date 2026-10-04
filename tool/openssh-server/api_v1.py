"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup openssh-server": the OpenSSH server (sshd). On Windows the portable Win32-OpenSSH
release (the zip of Microsoft's GitHub releases: x64, ARM64) is downloaded into the cache and
checked against its pinned SHA-256, with the programs next to sshd.exe that it starts
(sshd-session, sshd-auth) and ssh-keygen. Elsewhere the system sshd is detected (/usr/sbin), and
on Linux the openssh-server package is installed otherwise (_desc.yaml).
"""

import os
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

RELEASE = '10.0.0.0p2-Preview'
URL = 'https://github.com/PowerShell/Win32-OpenSSH/releases/download/{release}/{asset}'
# The release's SHA-256 digests (GitHub's release API)
ASSETS = {
    'amd64': ('OpenSSH-Win64.zip', '23f50f3458c4c5d0b12217c6a5ddfde0137210a30fa870e98b29827f7b43aba5'),
    'arm64': ('OpenSSH-ARM64.zip', '698c6aec31c1dd0fb996206e8741f4531a97355686b5431ef347d531b07fcd42'),
}


def find_sshd(root):
    """sshd.exe of the unpacked release, or None."""
    for d, dirs, files in os.walk(root):
        if 'sshd.exe' in files:
            return os.path.join(d, 'sshd.exe')
    return None


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
        Windows: the portable Win32-OpenSSH release; elsewhere the declarative install (16).
        """
        host = ctx['tasks']['global']['host']['os']
        if host['uname'] != 'windows':
            return {'return': 16, 'install_cmd': cmd, 'error': 'the OpenSSH server comes from the system here'}
        asset = ASSETS.get(str(host.get('uarch')).lower())
        if not asset:
            return self.cm.error(f'no Win32-OpenSSH release for the {host.get("uarch")} CPU')
        name, sha256 = asset

        r = _download(self, ctx, params, URL.format(release = RELEASE, asset = name), 'download', name)
        if r['return'] > 0:
            return r
        digest = _sha256(r['path'])
        if digest != sha256:
            os.remove(r['path'])
            return self.cm.error(f'SHA-256 mismatch for {name}: expected {sha256}, got {digest}')
        content = os.path.join(os.getcwd(), 'content')
        with zipfile.ZipFile(r['path']) as z:
            z.extractall(content)
        os.remove(r['path'])

        sshd = find_sshd(content)
        if not sshd:
            return self.cm.error(f'no sshd.exe in {name}')
        return {'return': 0, 'install_cmd': None, 'found_path': sshd}
