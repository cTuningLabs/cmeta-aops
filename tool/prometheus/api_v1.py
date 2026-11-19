"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Prometheus from its official release archive: the whole distribution kept (prometheus and promtool side by side -
promtool checks configurations and imports history), checked against the release's sha256sums.txt.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release

SPEC = {
    'name': 'prometheus',
    'url': 'https://github.com/prometheus/prometheus/releases/download/v{version}/prometheus-{version}.{os}-{arch}.{ext}',
    'ext': {'windows': 'zip', '*': 'tar.gz'},
    'member': 'prometheus-{version}.{os}-{arch}/prometheus{exe}',
    'tree': True,
    'checksum': {'list': 'https://github.com/prometheus/prometheus/releases/download/v{version}/sha256sums.txt'},
}


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def install(self, ctx, params, cmd=None, *misc):
        return install_release(self, ctx, params, cmd, SPEC)
