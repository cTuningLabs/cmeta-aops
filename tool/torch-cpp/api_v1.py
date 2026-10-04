"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_libtorch import found_paths_with_versions, add_path_features


class CTool(InitCTool):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        _with = params.setdefault('with', {})

        compute = _with.get('compute')
        if not compute:
            compute = ctx['tasks']['global'].get('target', {}).get('compute')
        if not compute:
            compute = ['cpu']
        if isinstance(compute, str):
            compute = compute.split(',')

        _with['compute'] = compute
        ctx['tasks']['local']['compute'] = compute
        ctx['tasks']['local']['target_abi'] = None

        # --with.build: source (the default, program/build-torch-cpp) or prebuilt (PyTorch's
        # archives through tool/torch-cpp-prebuilt, set up by "uses" in _desc.yaml)
        build = str(_with.get('build') or '').strip().lower()
        if build in ('', 'source'):
            # Without the key the cache identity of the source builds stays as it was
            _with.pop('build', None)
        elif build == 'prebuilt':
            if str(_with.get('static')).strip().lower() in ('true', 'yes', '1', 'on'):
                return self.cm.error('PyTorch\'s prebuilt LibTorch has shared libraries only: '
                                     '--with.static needs a source build (without --with.build=prebuilt)')
            _with['build'] = 'prebuilt'
            # tool/torch-cpp-prebuilt caches the archive under its own name; this setup is not cached,
            # since a cache entry with "build: prebuilt" would also match the requests without
            # --with.build (an entry matches every request whose parameters it contains)
            cparams['cache'] = False
            # Detect the prebuilt library (force_tool_path in _desc.yaml); never fall back to a build
            params['skip_detect'] = False
            params['skip_install'] = True
            params['skip_build'] = True
        else:
            return self.cm.error(f'unknown --with.build={build}: use source (the default) or prebuilt')

        return {'return': 0}


    ############################################################
    def customize_build(self,
                        ctx: dict,
                        misc: dict,
    ):
        result = {'return': 0}

        version = misc.get('version')
        if version:
            # PyTorch git tags are v2.7.1, v2.12.0, etc.
            result['add_to_local'] = {'checkout': f'v{version}'}

        return result


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict = {},
    ):
        """
        Expose the libtorch prefix, include dir and lib dir (the lib dir also for the run-time
        library path), from the cmake --install output of program/build-torch-cpp or from the
        archive of tool/torch-cpp-prebuilt.

        path = {prefix}/lib/torch.dll   (Windows)
             = {prefix}/lib/libtorch.so (Linux)
             = {prefix}/lib/libtorch.dylib (macOS)
        """
        paths = add_path_features(self, paths)

        # How this libtorch was made: "source" (a local build) or "prebuilt" (PyTorch's archive,
        # built with MSVC on Windows)
        build = 'prebuilt' if params.get('with', {}).get('build') == 'prebuilt' else 'source'

        for p in paths:
            p['features']['build'] = build
            path_features = p['features']['paths']
            path_features['found_dynamic_lib_paths'] = [path_features['lib']]

        return {'return': 0, 'paths': paths}


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: list,
                        params: dict = {},
    ):
        """
        The version of each found libtorch, from its headers (include/torch/.../version.h).
        """
        found = found_paths_with_versions(paths, params.get('with', {}))

        result = {'return': 0}
        if found:
            result['found_paths_with_versions'] = found
        return result
