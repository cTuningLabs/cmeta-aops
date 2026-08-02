"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

###################################################################################################
def init_arch(
        ctx: dict,
        result: dict = {},
        params: dict = {},
):
    """
    """

    con = ctx['control'].get('con', False)
    quiet = ctx['control'].get('quiet', False)
    verbose = ctx['control'].get('verbose', False)

    _result = {'return':0}

    # Check arch specific flags
    target_android = ctx['tasks']['global'].get('target--android-cpu')
    if target_android:
        abi = target_android['features']['ro.product.cpu.abi']

        clang_target = None
        clang_abi = None
        clang_abi_extra = ''

        if abi == 'arm64-v8a':
            clang_abi = 'aarch64'
            clang_abi_extra = ''
        elif abi == 'armeabi-v7a':
            clang_abi = 'armv7a'
            clang_abi_extra = 'eabi'

        if not clang_abi:
            return self.cm.error(f'could\'t create clang_android_target for Android abi "{abi}" in "{__file__}" ({__name__})')

        clang_target = f'{clang_abi}-linux-android{clang_abi_extra}'

        api_level = params.get('api_level')
        if not api_level:
            api_level = target_android['features']['ro.build.version.sdk']

        api_levels_from_clang = result['features']['abi-android-versions'][clang_abi]
        max_api_level_from_clang = max(api_levels_from_clang, key=int)

        if con:
            print ('')
            print (f'Requested Android API level: {api_level}')
        
        if int(api_level) > int(max_api_level_from_clang):
            api_level = int(max_api_level_from_clang)

            if con:
                print (f'Selected available Clang Android API level: {api_level}')

        clang_target += str(api_level)

        if con:
            print (f'Clang target: {clang_target}')

        _result['target_arch'] = {
          'abi': abi, 
          'clang_abi': clang_abi, 
          'clang_abi_extra': clang_abi_extra,
          'clang_target': clang_target,
          'api_level': api_level,
          'flags': '-target ' + clang_target,
        }

    return _result

###################################################################################################
def detect_api_levels(
        paths,
):
    """
    """

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
                            if ver.startswith('eabi'):
                                ver = ver[4:]
                            if ver not in vers[abi]:
                                vers[abi].append(ver)

    return {'return':0}

