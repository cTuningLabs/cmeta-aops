"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Ansible (ansible-core), agentless automation (https://www.ansible.com, GPL-3.0): installed as the pinned PyPI package
"ansible-core" in its own Python 3.12 environment by the shared helper
category/tool/api/common_pyvenv.py (uv creates the environment in the tool's cache entry).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv

SPEC = {'name': 'ansible',
 'package': 'ansible-core',
 'default_version': '2.21.4',
 'python': '3.12',
 'unsupported_os': {'windows': 'Ansible does not run on Windows as a control node (it needs POSIX-only '
                               'Python modules). Use WSL or a Linux container, where the same "cx tool setup '
                               'ansible" commands work.'}}


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
        Create the tool's environment and install the pinned ansible-core.
        """
        return install_pyvenv(self, ctx, params, cmd, SPEC)
