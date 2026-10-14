"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import install_release


SPEC = {
    'name': 'docker-compose',
    'url': 'https://github.com/docker/compose/releases/download/v{version}/docker-compose-{os}-{arch}{exe}',
    'os': {'linux': 'linux', 'darwin': 'darwin', 'windows': 'windows'},
    'arch': {'amd64': 'x86_64', 'arm64': 'aarch64'},
    'checksum': {'list': 'https://github.com/docker/compose/releases/download/v{version}/checksums.txt'},
}


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def install(self, ctx, params, cmd=None, *misc):
        return install_release(self, ctx, params, cmd, SPEC)
