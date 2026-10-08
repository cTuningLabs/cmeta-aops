"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import sha256_of

EULA_URL = 'https://www.amd.com/en/developer/aocc.html'
# AMD's archive of a release: aocc-5-2 for 5.2.0 (the first two numbers of the version)
ARCHIVE = 'https://download.amd.com/developer/eula/aocc/aocc-{major}-{minor}/aocc-compiler-{version}.tar'
# The archives the tool knows the checksum of (measured on 2026-10-08; AMD's download page shows one too)
SHA256 = {
    '5.2.0': 'f98af7e2ae8801dd4ba443520653acb739536a86c2a1caf096310c3cfd554ca0',
}


def truthy(value):
    return value is True or str(value).strip().lower() in ('true', '1', 'yes', 'on', 'accepted')


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """The folders of the installation the compiler belongs to (bin, and its parent with lib and include)."""
        for p in paths:
            features = p.setdefault('features', {})
            fpaths = features.setdefault('paths', {})
            path_bin = os.path.dirname(os.path.realpath(p['path']))
            fpaths['bin'] = path_bin
            fpaths['qbin'] = self.cm.q(path_bin)
            fpaths['home'] = os.path.dirname(path_bin)
            fpaths['qhome'] = self.cm.q(fpaths['home'])
        return {'return': 0, 'paths': paths}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        AMD's archive of the release, once the user has accepted the EULA (--with.accept_eula=yes),
        checked against the sha256 the tool knows, unpacked into the cache entry: bin/clang runs as it is.
        """

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        if uname != 'linux' or uarch != 'amd64':
            return {'return': 16, 'error': f'AMD publishes AOCC for Linux x86_64 only ({uname}/{uarch} here)', 'install_cmd': cmd}

        _with = params.get('with', {}) or {}
        if not truthy(_with.get('accept_eula')):
            return self.cm.error(f'AOCC comes under AMD\'s End User License Agreement ({EULA_URL}): read it there and run again '
                                 f'with --with.accept_eula=yes (in a program: --use.aocc.with.accept_eula=yes)')

        version = params.get('version_simple') or self.cdesc.get('default_version')
        if not version or version.count('.') != 2:
            return {'return': 16, 'error': f'AOCC needs an exact version (5.2.0), not "{params.get("version")}"', 'install_cmd': cmd}
        major, minor = version.split('.')[:2]
        url = ARCHIVE.format(major = major, minor = minor, version = version)
        filename = f'aocc-compiler-{version}.tar'
        directory = 'content'
        archive = os.path.join(os.getcwd(), directory, filename)
        path_to_clang = os.path.join(os.getcwd(), directory, f'aocc-compiler-{version}', 'bin', 'clang')

        if con:
            print('')
            print(f'{space}INFO: AOCC {version} from {url} (the EULA accepted by the user)')
            print(f'{space}INFO: Check file: {path_to_clang}')

        rx = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                             'ctx': ctx, 'url': url, 'directory': directory, 'filename': filename,
                             'env': params.get('env'), 'timeout': params.get('timeout'),
                             'con': con, 'quiet': quiet, 'verbose': verbose,
                             'unzip': False, 'clean': True, 'check_file': archive})
        if self.cm.catch_error(rx): return rx

        expected = SHA256.get(version)
        if expected:
            digest = sha256_of(archive)
            if digest != expected:
                return self.cm.error(f'{filename}: sha256 {digest} is not the known {expected} (the archive changed, or the download is broken)')
        elif con:
            print(f'{space}WARNING: the tool knows no checksum of AOCC {version}: compare the file with the one on {EULA_URL}')

        with tarfile.open(archive) as tar:
            tar.extractall(os.path.join(os.getcwd(), directory), filter = 'data')
        os.remove(archive)

        if not os.path.isfile(path_to_clang):
            return self.cm.error(f'the archive was unpacked but {path_to_clang} is not there')

        return {'return': 0, 'install_cmd': None, 'found_path': path_to_clang, 'version': version}
