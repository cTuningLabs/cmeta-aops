"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shutil
import subprocess
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

RELEASES = 'https://github.com/ollama/ollama/releases/download'


def release_asset(uname, uarch, variant = None):
    """The portable release asset for this platform, or None."""
    arch = {'amd64': 'amd64', 'x86_64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(uarch)
    if uname == 'darwin':
        return 'ollama-darwin.tgz'
    if not arch:
        return None
    suffix = f'-{variant}' if variant else ''
    if uname == 'windows':
        return f'ollama-windows-{arch}{suffix}.zip'
    if uname == 'linux':
        return f'ollama-linux-{arch}{suffix}.tar.zst'
    return None


def extract_tar_zst(archive, dest, zstd = None):
    """
    Unpack a .tar.zst: Python's own zstd (3.14+), else the zstandard module, else the zstd CLI.
    Returns None on success or an error message.
    """
    os.makedirs(dest, exist_ok = True)
    try:
        from compression import zstd as _zstd  # noqa: F401  (Python 3.14+)
        with tarfile.open(archive, 'r:zst') as t:
            t.extractall(dest, filter = 'data')
        return None
    except ImportError:
        pass
    try:
        import zstandard
        with open(archive, 'rb') as f, zstandard.ZstdDecompressor().stream_reader(f) as r:
            with tarfile.open(fileobj = r, mode = 'r|') as t:
                t.extractall(dest)
        return None
    except ImportError:
        pass
    zstd = zstd or shutil.which('zstd')
    if not zstd:
        return 'no zstd to unpack the archive (cx tool setup zstd)'
    p1 = subprocess.Popen([zstd, '-dc', archive], stdout = subprocess.PIPE)
    try:
        with tarfile.open(fileobj = p1.stdout, mode = 'r|') as t:
            t.extractall(dest)
    finally:
        p1.stdout.close()
        rc = p1.wait()
    return None if rc == 0 else f'zstd failed with return code {rc}'


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
        The pinned portable release into this cache entry (see _desc.yaml); 16 with the
        declarative install (winget, Homebrew, the official script) when it cannot apply.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple')
        if not version:
            if params.get('version'):
                return {'return': 16, 'install_cmd': cmd,
                        'error': f'the Ollama release download needs an exact version (got "{params.get("version")}")'}
            version = self.cdesc['default_version']

        variant = params.get('with', {}).get('variant')
        asset = release_asset(uname, uarch, variant)
        if not asset:
            return {'return': 16, 'install_cmd': cmd, 'error': f'Ollama publishes no portable build for {uname}/{uarch}'}

        url = f'{RELEASES}/v{version}/{asset}'
        content = os.path.join(os.getcwd(), 'content')
        exe = _global['host']['vars']['file_ext_exe']

        if con:
            print ('')
            print (f'{space}INFO: Ollama {version}: {url}')

        ii = {'category': 'task,c36be4b9314a45e0', 'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf', 'ctx': ctx,
              'url': url, 'directory': 'content',
              'env': params.get('env'), 'timeout': params.get('timeout'),
              'con': con, 'quiet': quiet, 'verbose': verbose}

        if asset.endswith('.tar.zst'):
            # download-file unpacks zip/tar.gz/tar.xz only
            r = self.cm.access(ii)
            if r['return'] > 0:
                return r
            archive = os.path.join(content, asset)
            zstd = _global.get('zstd', {}).get('path') or shutil.which('zstd')
            if not zstd:
                try:
                    from compression import zstd as _zstd  # noqa: F401  (Python 3.14+ unpacks it alone)
                except ImportError:
                    # Only now: the zstd CLI (a failed sub-task must not break the caller's context)
                    tasks = ctx['tasks']
                    saved = {k: tasks.get(k) for k in ('local', 'params', 'cparams')}
                    saved_control = dict(ctx['control'])
                    try:
                        self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run',
                                        'arg1': 'setup,a2f9b61079ce4333', 'name': 'zstd,e70d016f472d462e',
                                        'ctx': ctx, 'con': con, 'quiet': True, 'verbose': verbose})
                    finally:
                        for k, v in saved.items():
                            if v is not None:
                                tasks[k] = v
                        ctx['control'].clear()
                        ctx['control'].update(saved_control)
                    zstd = _global.get('zstd', {}).get('path')
            err = extract_tar_zst(archive, content, zstd)
            if err:
                return {'return': 16, 'install_cmd': cmd, 'error': err}
            os.remove(archive)
            path = os.path.join(content, 'bin', 'ollama')
        else:
            path = os.path.join(content, 'ollama' + exe)
            ii.update({'unzip': True, 'clean': True, 'clean_after_unzip': True, 'check_file': path,
                       'make_check_file_executable': True})
            r = self.cm.access(ii)
            if r['return'] > 0:
                return r

        if not os.path.isfile(path):
            return self.cm.error(f'{asset} was unpacked but has no {path}')
        if uname != 'windows':
            os.chmod(path, os.stat(path).st_mode | 0o111)

        return {'return': 0, 'install_cmd': None, 'found_path': path}
