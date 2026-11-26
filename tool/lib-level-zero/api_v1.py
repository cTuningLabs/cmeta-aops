"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

lib-level-zero - the SDK of oneAPI Level Zero from Intel's release (the headers and, on Windows, ze_loader.lib),
checked against its SHA-256 and unpacked into install/ of the tool's cache entry (_desc.yaml).
"""

import json
import os
import shutil
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _sha256, default_version
from tool_c393ba5c6fa14f66.api.common_static_lib import download

# Intel's SDK of a release for Windows (a zip: include/level_zero/*.h, lib/ze_loader.lib); Intel publishes a signature
# of it, no digest: the SHA-256 of the releases the tool knows is pinned here (computed 2026-11-26)
SDK = {'url': 'https://github.com/oneapi-src/level-zero/releases/download/v{version}/level-zero-win-sdk-{version}.zip',
       'file': 'level-zero-win-sdk-{version}.zip',
       'sha256': {'1.36.0': 'd1eb590f20f075d3921a5cac4e620d0ab20527bb6e07b168e36354f6126753c5'}}


def unpack(archive, dest):
    """The SDK's files into dest, each inside it (no absolute path, no "..")."""
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            parts = name.replace('\\', '/').split('/')
            if name.startswith(('/', '\\')) or '..' in parts or ':' in parts[0]:
                continue
            target = os.path.join(dest, *parts)
            if name.endswith('/'):
                os.makedirs(target, exist_ok = True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok = True)
            with z.open(name) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)


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
        Intel's SDK of the release (Windows) into the tool's cache entry (install/); elsewhere the distribution's package.
        """
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        c = params.get('control', {})
        con = c.get('con', False)
        _with = params.get('with', {})

        if uname != 'windows':
            return self.cm.error('Intel publishes its Level Zero SDK for Windows: on Linux the distribution\'s development '
                                 'package has it (Ubuntu, Debian: sudo apt install libze-dev)')

        version = params.get('version_simple') or default_version(self)
        if not version:
            return self.cm.error('lib-level-zero pins no default_version in its _desc.yaml: give --version=<x.y.z>')
        sha256 = (_with.get('sha256') or SDK['sha256'].get(version) or '').lower()
        if not sha256:
            return self.cm.error(f'no SHA-256 is pinned for the Level Zero SDK {version}: give --with.sha256=<SHA-256 of '
                                 f'{SDK["file"].format(version = version)}> (pinned: {", ".join(sorted(SDK["sha256"]))})')

        url = SDK['url'].format(version = version)
        filename = SDK['file'].format(version = version)
        if con:
            print(f'INFO: downloading {url} ...')
        r = download(self, ctx, params, url, 'download', filename)
        if r['return'] > 0:
            return self.cm.error(f'could not download {url}: {r.get("error")}')
        digest = _sha256(r['path'])
        if digest != sha256:
            os.remove(r['path'])
            return self.cm.error(f'SHA-256 mismatch for {filename}: expected {sha256}, got {digest}')

        install = os.path.join(os.getcwd(), 'install')
        shutil.rmtree(install, ignore_errors = True)
        os.makedirs(install)
        unpack(r['path'], install)
        header = os.path.join(install, 'include', 'level_zero', 'ze_api.h')
        if not os.path.isfile(header) or not os.path.isfile(os.path.join(install, 'lib', 'ze_loader.lib')):
            return self.cm.error(f'{filename} has no include/level_zero/ze_api.h and lib/ze_loader.lib')
        with open(os.path.join(install, '_source.json'), 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'url': url, 'sha256': sha256}, f, indent = 2)
        os.remove(r['path'])

        return {'return': 0, 'install_cmd': None, 'found_path': header}

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The release, the root (what LEVEL_ZERO_V1_SDK_PATH names), include and lib of an installation
        (install/include/level_zero/ze_api.h).
        """
        found = {}
        for path in paths:
            include = os.path.dirname(os.path.dirname(path))
            install = os.path.dirname(include)
            try:
                with open(os.path.join(install, '_source.json'), encoding = 'utf-8') as f:
                    source = json.load(f)
            except (OSError, ValueError):
                continue
            lib = os.path.join(install, 'lib')
            features = {'paths': {'root': install, 'qroot': self.cm.q(install),
                                  'include': include, 'qinclude': self.cm.q(include), 'includes': [include],
                                  'lib': lib, 'qlib': self.cm.q(lib), 'libs': [lib]},
                        'lib_names': ['ze_loader']}
            found[path] = {'output': source.get('version') or 'default', 'features': features}
        return {'return': 0, 'found_paths_with_versions': found}
