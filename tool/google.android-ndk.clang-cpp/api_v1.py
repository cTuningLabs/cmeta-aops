"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize_tool_cache_artifact(self,
                                      ctx,
                                      result,
                                      params,
                                      cache_tags,
                                      cache_params,
                                      cache_features,
                                      cache_meta,
        ):

        result = {'return':0}

        return result



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

        for p in paths:
            path = p['path']

            path_bin = os.path.dirname(path)

            features = p.setdefault('features', {})

            files = os.listdir(path_bin)

            vers = features.setdefault('abi-android-versions', {})
            for abi in ['aarch64', 'armv7a', 'i686', 'x86_64']:
                vers[abi] = []
                for f in files:
                    if f.startswith(abi+'-'):
                        j = f.find('-android')
                        if j>0:
                            j1 = f.find('-', j+1)
                            if j1>0:
                                ver = f[j+8:j1].strip()
                                if ver not in vers[abi]:
                                    vers[abi].append(ver)

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

        return _result
