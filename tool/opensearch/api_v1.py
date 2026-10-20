"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The official complete OpenSearch distribution, including its bundled JDK and plugins.
"""

from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release, install_windows_search_launcher


SPEC = {
    'name': 'opensearch',
    'url': 'https://artifacts.opensearch.org/releases/bundle/opensearch/{version}/opensearch-{version}-{os}-{arch}.{ext}',
    'os': {'linux': 'linux', 'windows': 'windows'},
    'arch': {'amd64': 'x64', 'arm64': 'arm64'},
    'unsupported': [['windows', 'arm64']],
    'ext': {'windows': 'zip', '*': 'tar.gz'},
    'exe': {'windows': '.bat', '*': ''},
    'member': 'opensearch-{version}/bin/opensearch{exe}',
    'tree': True,
    'checksum': {'file': '{url}.sha512', 'algorithm': 'sha512'},
}


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def install(self, ctx, params, cmd=None, *misc):
        result = install_release(self, ctx, params, cmd, SPEC)
        if not result['return'] and ctx['tasks']['global']['host']['os']['uname'] == 'windows':
            result['found_path'] = install_windows_search_launcher(result['found_path'], 'opensearch')
        return result

    def finish_dynamic_result(self, ctx, result=None, params=None):
        result = result if result is not None else {}
        if not result.get('path'):
            return {'return': 0, 'result': result}
        home = Path(result['path']).resolve().parent.parent
        paths = result.setdefault('features', {}).setdefault('paths', {})
        paths['home'] = str(home) if (home / 'lib').is_dir() and (home / 'config').is_dir() else ''
        paths['qhome'] = self.cm.utils.files.quote_path(paths['home']) if paths['home'] else ''
        return {'return': 0, 'result': result}
