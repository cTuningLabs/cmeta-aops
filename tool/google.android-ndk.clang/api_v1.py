"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_clang import init_arch, detect_api_levels

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL cuda google.android-ndk.clang check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        r = detect_api_levels(paths)
        if self.cm.catch_error(r): return r

        uname = ctx['tasks']['global']['host']['os']['uname']
        file_ext_exe = '.exe' if uname == 'windows' else ''

        for p in paths:
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            path_tool_lib = os.path.join(path_bin, f'llvm-ar{file_ext_exe}')
            if not os.path.isfile(path_tool_lib):
                return self.cm.error(f'library sub-tool not found in "{path_tool_lib}"')

            _paths = {
               'bin': path_bin,
               'tool_lib': path_tool_lib,
               'qtool_lib': self.cm.q(path_tool_lib),
            }

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

        return {'return':0, 'paths':paths}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _result = {'return':0}

        _with = params.get('with',{})

        path_bin = result['path_bin']

        path_home = path_bin
        qpath_home = self.cm.utils.files.quote_path(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        path_root = os.path.dirname(path_home)
        result['path_root'] = path_root
        result['qpath_root'] = self.cm.q(path_root)

        r = init_arch(ctx, result, params)
        if self.cm.catch_error(r): return r

        target_arch = r.get('target_arch')
        if target_arch:
            features = result.setdefault('features', {})
            features['target_arch'] = target_arch

        return _result

