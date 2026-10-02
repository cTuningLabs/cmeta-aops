"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Ray, the framework for distributed Python, training and serving (https://www.ray.io,
Apache-2.0): installed as the pinned PyPI package "ray[default]" (with the cluster CLI and the
dashboard) in its own Python environment by the shared helper
category/tool/api/common_pyvenv.py. Every node of a Ray cluster needs the same Ray and the same
Python down to the patch release (3.12.3 and 3.12.14 refuse to join): the Python is pinned
exactly, so uv installs the same build everywhere instead of using a system Python.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv

SPEC = {'name': 'ray',
        'package': 'ray[default]',
        'default_version': '2.59.0',
        'python': '3.12.14'}


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
        Create the tool's environment and install the pinned ray[default].
        """
        return install_pyvenv(self, ctx, params, cmd, SPEC)
