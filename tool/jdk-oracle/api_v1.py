"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup jdk-oracle": Oracle JDK, downloaded and checked (category/tool/api/common_jdk.py).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_jdk import jdk_init, install_jdk, jdk_finish

VENDOR = 'oracle'


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        The major version (--with.feature, default 25) is part of the cache identity.
        """
        return jdk_init(self, params)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The vendor's JDK into the cache entry.
        """
        return install_jdk(self, ctx, params, VENDOR)

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The vendor and the JDK home as features; --with.add_env exports JAVA_HOME and PATH.
        """
        return jdk_finish(result, params, VENDOR)
