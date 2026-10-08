"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import tarfile
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import sha256_of

RELEASES = 'https://github.com/ROCm/FastFlowLM/releases/download/v{version}/{asset}'

# The release assets per platform, with the sha256 GitHub publishes for them (the digest of the asset)
ASSETS = {
    ('1.0.7', 'linux', 'amd64'): ('fastflowlm_1.0.7_linux.tar.gz', 'e5a0725284a845178b6e1136fc99efd6cd6cba0dcd55fc319ab7edfeb04b8433'),
    ('1.0.7', 'windows', 'amd64'): ('fastflowlm_1.0.7_windows_amd64.zip', '0377e501afe3595d491cde1ff91923f225240053437d6e55b47c6e86fadc54d8'),
}


def asset_for(version, uname, uarch):
    """The release asset and its sha256 for this platform, (None, None) when the tool knows none."""
    return ASSETS.get((version, uname, uarch), (None, None))


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
        """
        What "flm validate --json" says on Linux (the NPU, its columns and firmware, the kernel driver, the
        memory-lock limit, ready or not), as features; nothing when the command is not there yet.
        """
        for p in paths:
            features = p.setdefault('features', {})
            path_bin = os.path.dirname(os.path.realpath(p['path']))
            features.setdefault('paths', {})['bin'] = path_bin
            if ctx['tasks']['global']['host']['os']['uname'] != 'linux':
                continue
            env = dict(os.environ)
            env['FLM_DISABLE_UPDATE_CHECK'] = '1'
            r = self.cm.utils.sys.run(f'{self.cm.q(p["path"])} validate --json', capture_output = True, fail_on_error = False,
                                      env = env, timeout = 60, logger = self.logger)
            text = (r.get('stdout') or '').strip()
            start = text.find('{')
            if start >= 0:
                try:
                    features['npu'] = json.loads(text[start:])
                except ValueError:
                    pass
        return {'return': 0, 'paths': paths}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """The pinned release archive from GitHub, checked against its sha256, unpacked into the cache entry."""

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']
        exe = _global['host']['vars']['file_ext_exe']

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        version = params.get('version_simple') or self.cdesc.get('default_version')
        asset, sha = asset_for(version, uname, uarch)
        if not asset:
            known = ', '.join(sorted({v for v, _, _ in ASSETS}))
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'FastFlowLM {version} for {uname}/{uarch}: the tool knows the releases {known} for Linux x86_64 and Windows x64 only'}

        url = RELEASES.format(version = version, asset = asset)
        directory = 'content'
        archive = os.path.join(os.getcwd(), directory, asset)
        path_to_flm = os.path.join(os.getcwd(), directory, 'flm' + exe)

        if con:
            print('')
            print(f'{space}INFO: FastFlowLM {version}: {url}')
            print(f'{space}INFO: Check file: {path_to_flm}')

        rx = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                             'ctx': ctx, 'url': url, 'directory': directory, 'filename': asset,
                             'env': params.get('env'), 'timeout': params.get('timeout'),
                             'con': con, 'quiet': quiet, 'verbose': verbose,
                             'unzip': False, 'clean': True, 'check_file': archive})
        if self.cm.catch_error(rx): return rx

        digest = sha256_of(archive)
        if digest != sha:
            return self.cm.error(f'{asset}: sha256 {digest} is not the published {sha}')

        dest = os.path.join(os.getcwd(), directory)
        if asset.endswith('.zip'):
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        else:
            with tarfile.open(archive) as tar:
                tar.extractall(dest, filter = 'data')
        os.remove(archive)

        if not os.path.isfile(path_to_flm):
            # the Windows zip may hold a folder
            for root, dirs, files in os.walk(dest):
                if 'flm' + exe in files:
                    path_to_flm = os.path.join(root, 'flm' + exe)
                    break
        if not os.path.isfile(path_to_flm):
            return self.cm.error(f'{asset} was unpacked but has no flm{exe}')
        if uname != 'windows':
            os.chmod(path_to_flm, 0o755)

        return {'return': 0, 'install_cmd': None, 'found_path': path_to_flm, 'version': version}
