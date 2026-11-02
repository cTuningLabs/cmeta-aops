"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_clang import init_ios_arch

class CTool(InitCTool):
    """
    Apple clang++ of the Xcode toolchain, as the C++ compiler of the ios-cpu target.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """The archiver next to the compiler (the toolchain's ar), for static libraries."""

        for p in paths:
            path_bin = os.path.dirname(p['path'])
            path_tool_lib = os.path.join(path_bin, 'ar')
            if not os.path.isfile(path_tool_lib):
                return self.cm.error(f'library sub-tool not found in "{path_tool_lib}"')

            features = p.setdefault('features', {})
            features.setdefault('paths', {}).update({'bin': path_bin,
                                                     'tool_lib': path_tool_lib,
                                                     'qtool_lib': self.cm.q(path_tool_lib)})

        return {'return': 0, 'paths': paths}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """The flags of the iPhone target of this run, set again on a cached compiler too."""

        r = init_ios_arch(ctx, result, params)
        if self.cm.catch_error(r): return r

        if r.get('target_arch'):
            result.setdefault('features', {})['target_arch'] = r['target_arch']

        return {'return': 0}
