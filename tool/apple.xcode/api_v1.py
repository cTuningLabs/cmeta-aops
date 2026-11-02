"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    Xcode on macOS: the developer directory xcode-select names, its toolchain, the iOS SDK and devicectl - what
    the iPhone target (task/target--ios-cpu) and its compilers (tool/apple.xcode.clang, -cpp) build on.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        """
        if ctx['tasks']['global']['host']['os']['uname'] != 'darwin':
            return self.cm.error(f'apple.xcode works only on macOS (darwin) in "{__file__}"')

        return {'return': 0}

    ############################################################
    def _run(self,
             ctx: dict,
             cmd: str,
             params: dict,
    ):
        """A command through the cmd task (a RUN: line in verbose mode): its return code and stripped stdout."""

        _with = params.get('with', {})

        r = self.cm.access({'category': 'task,c36be4b9314a45e0',
                            'command': 'run',
                            'ctx': ctx,
                            'arg1': 'cmd,c9ba0a88df394d7f',
                            'cmd': cmd,
                            'env': _with.get('env', {}),
                            'timeout': _with.get('timeout'),
                            'con': ctx['control'].get('con', False),
                            'quiet': ctx['control'].get('quiet', False),
                            'verbose': ctx['control'].get('verbose', False),
                            'text_cmd': 'RUN:',
                            'capture_output': True,
                            'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(r): return r

        return {'return': 0, 'returncode': r.get('returncode', 1), 'stdout': (r.get('stdout') or '').strip()}

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The selected Xcode: "xcode-select -p" (or --tool_path: a developer directory, or the xcodebuild in one),
        its version from "xcodebuild -version", the toolchain folder, devicectl and the iOS SDK.
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL apple.xcode api_v1 detect")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        none = {'return': 0, 'parsed_paths_with_versions': []}

        developer_dir = ''
        forced = params.get('tool_path')
        if forced:
            # <developer dir> or <developer dir>/usr/bin/xcodebuild
            developer_dir = forced if os.path.isdir(forced) else os.path.dirname(os.path.dirname(os.path.dirname(forced)))
        else:
            r = self._run(ctx, 'xcode-select -p', params)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0 and r['stdout']:
                developer_dir = r['stdout'].splitlines()[0].strip()

        xcodebuild = os.path.join(developer_dir, 'usr', 'bin', 'xcodebuild')
        if not developer_dir or not os.path.isfile(xcodebuild):
            return none

        r = self._run(ctx, self.cm.q(xcodebuild) + ' -version', params)
        if self.cm.catch_error(r): return r
        m = re.search(r'Xcode\s+([\d.]+)', r['stdout']) if r['returncode'] == 0 else None
        if not m:
            # The Command Line Tools: "xcode-select: error: tool 'xcodebuild' requires Xcode"
            return none
        version = m.group(1)
        b = re.search(r'Build version\s+(\S+)', r['stdout'])

        toolchain_bin = os.path.join(developer_dir, 'Toolchains', 'XcodeDefault.xctoolchain', 'usr', 'bin')
        devicectl = os.path.join(developer_dir, 'usr', 'bin', 'devicectl')

        # The iOS platform may not be installed (Xcode asks at its first launch, or: xcodebuild -downloadPlatform iOS)
        ios_sdk = ''
        ios_sdk_version = ''
        r = self._run(ctx, 'xcrun --sdk iphoneos --show-sdk-path', params)
        if self.cm.catch_error(r): return r
        if r['returncode'] == 0 and os.path.isdir(r['stdout']):
            ios_sdk = r['stdout']
            r = self._run(ctx, 'xcrun --sdk iphoneos --show-sdk-version', params)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0:
                ios_sdk_version = r['stdout']

        if con and verbose:
            print (f'{space}INFO: Xcode {version} found in "{developer_dir}"')
            print (f'{space}INFO: iOS SDK: ' + (f'{ios_sdk_version} in "{ios_sdk}"' if ios_sdk else 'not installed'))

        tool = {'path': xcodebuild,
                'detected_version': version,
                'features': {'paths': {'home': developer_dir,
                                       'bin': os.path.dirname(xcodebuild),
                                       'toolchain_bin': toolchain_bin,
                                       'devicectl': devicectl if os.path.isfile(devicectl) else '',
                                       'ios_sdk': ios_sdk},
                             'build': b.group(1) if b else '',
                             'ios_sdk_version': ios_sdk_version}}

        return {'return': 0, 'parsed_paths_with_versions': [tool]}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The paths other tools and tasks template ({{global.apple-xcode.path_toolchain_bin}}, .ios_sdk_path,
        .path_devicectl), taken from the features so that a cached result carries them too.
        """

        features = result.get('features') or {}
        paths = features.get('paths') or {}

        result['path_home'] = paths.get('home', '')
        result['path_toolchain_bin'] = paths.get('toolchain_bin', '')
        result['path_devicectl'] = paths.get('devicectl', '')
        result['ios_sdk_path'] = paths.get('ios_sdk', '')
        result['ios_sdk_version'] = features.get('ios_sdk_version', '')

        for key in ('path_home', 'path_toolchain_bin', 'path_devicectl', 'ios_sdk_path'):
            result['q' + key] = self.cm.q(result[key]) if result[key] else ''

        return {'return': 0}
