"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup android-d8": D8, Android's dexer (see _desc.yaml). Without an Android SDK, the
pinned r8 release jar (it contains D8) is downloaded from Google's Maven into the cache and
checked against the SHA-256 that Google publishes next to it.
"""

import hashlib
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

GOOGLE_MAVEN = 'https://dl.google.com/android/maven2/com/android/tools/r8/{version}/r8-{version}.jar'


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


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
        Download the r8 jar of the pinned (or requested) release into content/r8.jar and check
        it against Google's SHA-256.
        """

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc['default_version'])
        if not version or not re.match(r'^\d+\.\d+\.\d+$', str(version)):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the r8 download needs an exact version such as {self.cdesc["default_version"]}'}

        url = GOOGLE_MAVEN.format(version = version)
        if con:
            print ('')
            print (f'{space}INFO: D8 {version}: {url}')

        content = os.path.join(os.getcwd(), 'content')
        paths = {}
        for name, u in (('r8.jar', url), (f'r8-{version}.jar.sha256', url + '.sha256')):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'url': u, 'directory': 'content',
                                'filename': name, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose,
                                'check_file': os.path.join(content, name)})
            if self.cm.catch_error(r): return r
            paths[name] = os.path.join(content, name)

        with open(paths[f'r8-{version}.jar.sha256'], encoding = 'utf-8', errors = 'replace') as f:
            words = f.read().split()
        published = words[0].lower() if words else ''
        got = sha256_of(paths['r8.jar'])
        if got != published:
            os.remove(paths['r8.jar'])
            return self.cm.error(f'r8-{version}.jar: SHA-256 {got} is not the published {published or "(none)"}')
        if con:
            print (f'{space}INFO: SHA-256 verified ({got[:16]}...)')

        return {'return': 0, 'install_cmd': None, 'found_path': paths['r8.jar']}
