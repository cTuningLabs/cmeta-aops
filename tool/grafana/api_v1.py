"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Grafana (the open-source edition) from its official archive: the whole distribution kept (bin/, conf/, public/ - the
server needs them all), checked against the archive's .sha256. Its folder was grafana-v<version>/ in older releases
and is grafana-<version>/ in newer ones: both are candidates, the archive's own is taken.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {
    'name': 'grafana',
    'url': 'https://dl.grafana.com/oss/release/grafana-{version}.{os}-{arch}.{ext}',
    'ext': {'windows': 'zip', '*': 'tar.gz'},
    'member': ['grafana-{version}/bin/grafana{exe}', 'grafana-v{version}/bin/grafana{exe}'],
    'tree': True,
    'checksum': {'file': '{url}.sha256'},
}


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def install(self, ctx, params, cmd=None, *misc):
        return install_release(self, ctx, params, cmd, SPEC)
