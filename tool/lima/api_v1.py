"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

tool/lima: Lima from its release archives (install ladder tier 1) - the whole tree, since limactl looks for
share/lima (guest agents, templates) next to its bin folder and one binary would not run:

    https://github.com/lima-vm/lima/releases/download/v<version>/lima-<version>-<Darwin|Linux>-<arm64|x86_64|aarch64>.tar.gz
    https://github.com/lima-vm/lima/releases/download/v<version>/SHA256SUMS       (the digests of every asset)

The archive is downloaded with the download-file task, its SHA-256 checked against SHA256SUMS (a mismatch is a
failure), and unpacked with the standard library into the cache entry's "content" folder: content/bin/limactl,
content/bin/lima, content/share/lima. Nothing goes on the PATH and nothing into the system.
"""

import hashlib
import os
import stat
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import default_version

RELEASES = 'https://github.com/lima-vm/lima/releases/download'
OS_NAMES = {'darwin': 'Darwin', 'linux': 'Linux'}
ARCH_NAMES = {'darwin': {'arm64': 'arm64', 'amd64': 'x86_64'},
              'linux': {'arm64': 'aarch64', 'amd64': 'x86_64'}}


def asset_name(version, uname, uarch):
    """The archive of a release for this OS and CPU, or None when upstream publishes none."""
    os_name = OS_NAMES.get(uname)
    arch = ARCH_NAMES.get(uname, {}).get(uarch)
    if not os_name or not arch:
        return None
    return f'lima-{version}-{os_name}-{arch}.tar.gz'


def expected_digest(sums_text, asset):
    """The SHA-256 of one asset in a "<sha256>  <asset>" list, or ''."""
    for line in (sums_text or '').splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip('*') == asset:
            return parts[0].strip().lower()
    return ''


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def unpack_tree(archive, dest):
    """Unpack a .tar.gz into dest as it is (bin/, share/ at the top); a single top-level folder, if any, is stripped."""
    with tarfile.open(archive, 'r:*') as t:
        members = t.getmembers()
        tops = {m.name.replace('\\', '/').lstrip('./').split('/', 1)[0] for m in members if m.name.strip('./')}
        strip = len(tops) == 1 and all(m.isdir() or '/' in m.name.lstrip('./') for m in members)

        for member in members:
            rel = member.name.replace('\\', '/').lstrip('./')
            if strip:
                rel = rel.split('/', 1)[1] if '/' in rel else ''
            if not rel or '..' in rel.split('/'):
                continue

            target = os.path.join(dest, *rel.split('/'))
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.issym() or member.islnk():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(member.linkname, target)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with t.extractfile(member) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
                if member.mode & stat.S_IXUSR:
                    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class CTool(InitCTool):
    """Lima from its release archives, verified against SHA256SUMS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        c = params.get('control', {})
        con = c.get('con', False)
        quiet = c.get('quiet', False)
        verbose = c.get('verbose', False)
        space = '  ' * ctx_tasks.get('nested_call', 0) if verbose else ''

        version = params.get('version')
        version_simple = params.get('version_simple')
        if version and not version_simple:
            return {'return': 16, 'install_cmd': cmd, 'error': 'the Lima release download needs an exact version (--version=2.2.1)'}
        version = version_simple or default_version(self)
        if not version:
            return self.cm.error('lima pins no default_version in its _desc.yaml: give --version=<version>')

        asset = asset_name(version, uname, uarch)
        if not asset:
            return {'return': 16, 'install_cmd': cmd, 'error': f'Lima publishes no archive for {uname}/{uarch}'}

        directory = 'content'
        root = os.path.join(os.getcwd(), directory)
        os.makedirs(root, exist_ok=True)
        base = f'{RELEASES}/v{version}'

        def fetch(filename, saved_as):
            return self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                                   'ctx': ctx, 'url': f'{base}/{filename}', 'directory': directory, 'filename': saved_as,
                                   'env': params.get('env'), 'timeout': params.get('timeout'),
                                   'con': con, 'quiet': quiet, 'verbose': verbose, 'unzip': False,
                                   'check_file': os.path.join(root, saved_as)})

        if con:
            print ('')
            print (f'{space}INFO: Lima {version}: {base}/{asset}')

        # The version in the saved name: "--upgrade" reuses the entry, and download-file keeps a file that exists
        sums_name = f'_sums_{version}_SHA256SUMS'
        r = fetch('SHA256SUMS', sums_name)
        sums = os.path.join(root, sums_name)
        if r['return'] > 0 or not os.path.isfile(sums):
            return {'return': 16, 'install_cmd': cmd, 'error': f'could not download {base}/SHA256SUMS: {r.get("error", "")} (is {version} a published version?)'}
        with open(sums, encoding='utf-8', errors='replace') as f:
            expected = expected_digest(f.read(), asset)
        if not expected:
            return {'return': 16, 'install_cmd': cmd, 'error': f'{asset} is not in the SHA256SUMS of Lima {version}'}

        r = fetch(asset, asset)
        archive = os.path.join(root, asset)
        if r['return'] > 0 or not os.path.isfile(archive):
            return {'return': 16, 'install_cmd': cmd, 'error': f'could not download {base}/{asset}: {r.get("error", "")}'}

        actual = sha256_of(archive)
        if actual != expected:
            os.remove(archive)
            return self.cm.error(f'SHA-256 mismatch for {asset}: upstream lists {expected}, the download has {actual}')
        if con:
            print (f'{space}INFO: SHA-256 verified against SHA256SUMS')

        try:
            unpack_tree(archive, root)
        except Exception as e:
            return self.cm.error(f'cannot unpack {asset}: {e}')
        for leftover in (archive, sums):
            try:
                os.remove(leftover)
            except OSError:
                pass

        limactl = os.path.join(root, 'bin', 'limactl')
        if not os.path.isfile(limactl):
            return self.cm.error(f'{asset} unpacked, but {limactl} is not there (the archive layout changed?)')
        if con:
            print (f'{space}INFO: Lima: {limactl} (share/lima next to it)')

        return {'return': 0, 'install_cmd': None, 'found_path': limactl}
