"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

AIPerf, benchmarking of generative AI inference servers (https://github.com/ai-dynamo/aiperf, Apache-2.0): installed as the pinned PyPI package
"aiperf" in its own Python 3.12 environment by the shared helper
category/tool/api/common_pyvenv.py (uv creates the environment in the tool's cache entry).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv

SPEC = {'name': 'aiperf', 'package': 'aiperf', 'default_version': '0.13.0', 'python': '3.12'}


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
        Create the tool's environment and install the pinned aiperf.
        """
        return install_pyvenv(self, ctx, params, cmd, SPEC)
