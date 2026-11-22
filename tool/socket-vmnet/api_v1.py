"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

socket-vmnet: socket_vmnet for Lima / colima on macOS (see _desc.yaml): the release archive of this CPU, its SHA-256
checked against the pinned one, unpacked by root into /opt/socket_vmnet, where Lima wants it (root-owned).
"""

import hashlib
import os
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


RELEASE = 'https://github.com/lima-vm/socket_vmnet/releases/download/v{version}/socket_vmnet-{version}-{arch}.tar.gz'
ARCH = {'arm64': 'arm64', 'amd64': 'x86_64'}
TARGET = '/opt/socket_vmnet/bin/socket_vmnet'


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
        _global = ctx['tasks']['global']
        uname, uarch = _global['host']['os']['uname'], _global['host']['os']['uarch']
        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        if uname != 'darwin' or uarch not in ARCH:
            return self.cm.error(f'socket_vmnet is for macOS (arm64, amd64), not {uname} {uarch}')
        version = params.get('version_simple') or (None if params.get('version') else self.cdesc.get('default_version'))
        sha256 = str(((self.cdesc.get('archives') or {}).get(str(version)) or {}).get(uarch) or '').lower()
        if not version or not sha256:
            return self.cm.error(f'no archive of socket_vmnet {version} for {uarch} is pinned (archives: in its _desc.yaml)')

        name = f'socket_vmnet-{version}-{ARCH[uarch]}.tar.gz'
        content = os.path.join(os.getcwd(), 'content')
        os.makedirs(content, exist_ok = True)
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                            'ctx': ctx, 'url': RELEASE.format(version = version, arch = ARCH[uarch]), 'directory': 'content',
                            'filename': name, 'unzip': False, 'con': con, 'quiet': quiet, 'verbose': verbose,
                            'check_file': os.path.join(content, name)})
        if self.cm.catch_error(r): return r
        archive = os.path.join(content, name)
        h = hashlib.sha256()
        with open(archive, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        if h.hexdigest() != sha256:
            os.remove(archive)
            return self.cm.error(f'socket_vmnet {version}: the SHA-256 of {name} is {h.hexdigest()}, the pinned one {sha256}')

        # as upstream says: root unpacks opt/socket_vmnet of the archive into / (the binary root-owned, not user-writable)
        # - by cMeta's tar
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                            'name': 'tar,788abc644bf24d86', 'con': False, 'quiet': True})
        if self.cm.catch_error(r): return r
        if not r.get('path'):
            return self.cm.error('cMeta\'s tool tar reports no program')
        args = ['sudo', r['path'], '-C', '/', '-xzf', archive, 'opt/socket_vmnet']
        if con:
            print(f'RUN: {" ".join(args)}')
        p = subprocess.run(args, stdin = subprocess.DEVNULL, capture_output = True, text = True)
        if p.returncode != 0 or not os.path.isfile(TARGET):
            return self.cm.error(f'installing socket_vmnet into /opt/socket_vmnet failed: {(p.stderr or p.stdout).strip()[-800:]}')
        os.remove(archive)
        return {'return': 0, 'install_cmd': None, 'found_path': TARGET}
