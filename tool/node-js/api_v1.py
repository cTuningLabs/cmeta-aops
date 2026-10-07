"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/node-js: install Node.js from the official release archives (install ladder tier 1) - the whole tree, since npm
and npx are scripts under lib/node_modules/npm next to the node binary, not one file to pick out:

    https://nodejs.org/dist/v<version>/node-v<version>-<os>-<arch>.<tar.gz|zip>
    https://nodejs.org/dist/v<version>/SHASUMS256.txt                 (the digests of every asset of the release)

The archive is downloaded with the download-file task, its SHA-256 checked against the SHASUMS256.txt of the release
(a mismatch is a failure), and it is unpacked with the standard library, its top folder stripped, into the cache
entry's "content" folder: content/bin/node (Linux, macOS) or content/node.exe (Windows), with npm and npx beside it.
Nothing goes on the PATH and nothing into the system. When the version is not given, the default below is used -
the current LTS when the file was written; "cx tool setup node-js --versions" lists what nodejs.org publishes.
"""

import hashlib
import os
import stat
import tarfile
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

TOOL_NAME = 'node'
DEFAULT_VERSION = '24.21.0'        # LTS "Krypton" on 2026-10-07 (the current release line was 26.11.0)
DIST = 'https://nodejs.org/dist'
OS_NAMES = {'linux': 'linux', 'darwin': 'darwin', 'windows': 'win'}
ARCH_NAMES = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}


def asset_name(version, uname, uarch):
    """The archive of a release for this OS and CPU, or None when nodejs.org publishes none."""
    os_name, arch = OS_NAMES.get(uname), ARCH_NAMES.get(uarch)
    if not os_name or not arch:
        return None
    ext = 'zip' if uname == 'windows' else 'tar.gz'
    return f'node-v{version}-{os_name}-{arch}.{ext}'


def expected_digest(sums_text, asset):
    """The SHA-256 of one asset in a "<sha256>  <asset>" list, or ''."""
    for line in (sums_text or '').splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].strip() == asset:
            return parts[0].strip().lower()
    return ''


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def unpack_stripped(archive, dest):
    """Unpack a .tar.gz or .zip into dest without its single top-level folder."""
    def strip(name):
        parts = name.replace('\\', '/').split('/', 1)
        return parts[1] if len(parts) == 2 else ''

    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                rel = strip(info.filename)
                if not rel or rel.endswith('/'):
                    continue
                target = os.path.join(dest, *rel.split('/'))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
    else:
        with tarfile.open(archive, 'r:*') as t:
            for member in t.getmembers():
                rel = strip(member.name)
                if not rel:
                    continue
                target = os.path.join(dest, *rel.split('/'))
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                elif member.issym() or member.islnk():
                    # bin/npm and bin/npx are symlinks into lib/node_modules/npm: kept as links where the OS makes
                    # them (Linux, macOS); on Windows - or without the privilege - the target file is copied instead
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    link = member.linkname
                    source = os.path.normpath(os.path.join(os.path.dirname(target), link))
                    made = False
                    if os.name != 'nt':
                        try:
                            if os.path.lexists(target):
                                os.remove(target)
                            os.symlink(link, target)
                            made = True
                        except (OSError, NotImplementedError):
                            made = False
                    if not made and os.path.isfile(source):
                        with open(source, 'rb') as src, open(target, 'wb') as dst:
                            dst.write(src.read())
                        os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                elif member.isfile():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with t.extractfile(member) as src, open(target, 'wb') as dst:
                        dst.write(src.read())
                    if member.mode & stat.S_IXUSR:
                        os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class CTool(InitCTool):
    """Node.js from the official release archives, verified against SHASUMS256.txt."""

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
            return {'return': 16, 'install_cmd': cmd, 'error': 'the Node.js release download needs an exact version (--version=24.21.0)'}
        version = version_simple or DEFAULT_VERSION

        asset = asset_name(version, uname, uarch)
        if not asset:
            return {'return': 16, 'install_cmd': cmd, 'error': f'nodejs.org publishes no archive for {uname}/{uarch}'}

        directory = 'content'
        root = os.path.join(os.getcwd(), directory)
        os.makedirs(root, exist_ok=True)
        base = f'{DIST}/v{version}'

        def fetch(filename):
            return self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                                   'ctx': ctx, 'url': f'{base}/{filename}', 'directory': directory, 'filename': filename,
                                   'env': params.get('env'), 'timeout': params.get('timeout'),
                                   'con': con, 'quiet': quiet, 'verbose': verbose})

        if con:
            print('')
            print(f'{space}INFO: Node.js {version}: {base}/{asset}')

        r = fetch('SHASUMS256.txt')
        sums = os.path.join(root, 'SHASUMS256.txt')
        if r['return'] > 0 or not os.path.isfile(sums):
            return {'return': 16, 'install_cmd': cmd, 'error': f'could not download {base}/SHASUMS256.txt: {r.get("error", "")} (is {version} a published version?)'}
        with open(sums, encoding='utf-8', errors='replace') as f:
            expected = expected_digest(f.read(), asset)
        if not expected:
            return {'return': 16, 'install_cmd': cmd, 'error': f'{asset} is not in the SHASUMS256.txt of Node.js {version}'}

        r = fetch(asset)
        archive = os.path.join(root, asset)
        if r['return'] > 0 or not os.path.isfile(archive):
            return {'return': 16, 'install_cmd': cmd, 'error': f'could not download {base}/{asset}: {r.get("error", "")}'}

        actual = sha256_of(archive)
        if actual != expected:
            os.remove(archive)
            return {'return': 1, 'error': f'SHA-256 mismatch for {asset}: nodejs.org lists {expected}, the download has {actual}'}
        if con:
            print(f'{space}INFO: SHA-256 verified against SHASUMS256.txt')

        try:
            unpack_stripped(archive, root)
        except Exception as e:
            return {'return': 1, 'error': f'cannot unpack {asset}: {e}'}
        for leftover in (archive, sums):
            try:
                os.remove(leftover)
            except OSError:
                pass

        node = os.path.join(root, 'node.exe') if uname == 'windows' else os.path.join(root, 'bin', 'node')
        if not os.path.isfile(node):
            return {'return': 1, 'error': f'{asset} unpacked, but {node} is not there (the archive layout changed?)'}
        if uname != 'windows':
            for name in ('node', 'npm', 'npx', 'corepack'):
                fp = os.path.join(root, 'bin', name)
                if os.path.lexists(fp) and not os.path.islink(fp):
                    os.chmod(fp, os.stat(fp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if con:
            print(f'{space}INFO: Node.js: {node} (npm and npx next to it)')
        return {'return': 0, 'install_cmd': None, 'found_path': node}
