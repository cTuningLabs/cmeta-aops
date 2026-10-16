"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def detect_versions(self, ctx, paths, params=None):
        """Use the installed SDK package's revision when every candidate has one.

        Some Windows sdkmanager launchers mishandle ! in JAVA_HOME and print a
        Java diagnostic even for --version. Never record that diagnostic as a version.
        Legacy layouts without source.properties keep command-based detection.
        """
        versions = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            properties = os.path.join(os.path.dirname(os.path.dirname(path)), 'source.properties')
            try:
                with open(properties, encoding='utf-8') as stream:
                    text = stream.read()
            except OSError:
                return {'return': 0}
            match = re.search(r'(?m)^Pkg\.Revision\s*=\s*(\d+(?:\.\d+)*)\s*$', text)
            if not match:
                return {'return': 0}
            versions[candidate] = {'output': match.group(1)}
        return {'return': 0, 'found_paths_with_versions': versions}

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

        path_home = os.path.dirname(os.path.dirname(os.path.dirname(path_bin)))
        qpath_home = self.cm.utils.files.quote_path(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        if _with.get('add_env', True):
            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['ANDROID_HOME'] = path_home # Legacy
            _aggregate_env['ANDROID_SDK_ROOT'] = path_home # New

            _result['result'] = result

        return _result

