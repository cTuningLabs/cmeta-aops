"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# Go's architecture for each Android ABI (ro.product.cpu.abi)
GOARCH = {
    'arm64-v8a': {'GOARCH': 'arm64'},
    'armeabi-v7a': {'GOARCH': 'arm', 'GOARM': '7'},
    'x86_64': {'GOARCH': 'amd64'},
    'x86': {'GOARCH': '386'},
}


def android_env(abi):
    """The environment of "go build" for an Android ABI: (env, error)."""
    arch = GOARCH.get(abi)
    if not arch:
        return None, f'no Go architecture for the Android ABI "{abi}"'
    return {'GOOS': 'android', **arch, 'CGO_ENABLED': '0'}, None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The target of the Android device that target--android-cpu selected (also for a cached
        result, so another device gets its own ABI): features.env for "go build" and
        -buildmode=pie, since Android runs position-independent executables only.
        """

        target_android = ctx['tasks']['global'].get('target--android-cpu')
        if not target_android:
            return {'return': 0}

        abi = target_android['features']['ro.product.cpu.abi']

        env, error = android_env(abi)
        if error:
            return self.cm.error(error)

        features = result.setdefault('features', {})
        features['env'] = env
        features['target_arch'] = {
          'abi': abi,
          'goos': env['GOOS'],
          'goarch': env['GOARCH'],
          'flags': '-buildmode=pie',
        }

        return {'return': 0}
