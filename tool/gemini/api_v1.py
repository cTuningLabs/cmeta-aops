"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import stat

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# The only release asset that works on every OS. Google publishes no standalone
# Linux/Windows binary - the other assets are unsigned macOS builds.
BUNDLE_ASSET = 'gemini-cli-bundle.zip'

# Entry point inside the bundle ("#!/usr/bin/env node" + ESM imports)
BUNDLE_ENTRY = 'gemini.js'

GITHUB_REPO = 'https://github.com/google-gemini/gemini-cli'

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
        Download the Gemini CLI bundle straight from GitHub releases (curl, no
        package manager) and wrap it in a launcher.

        The bundle is a self-contained JavaScript program, so the "binary" we
        register is a two-line launcher that runs it with the Node.js found by
        the "setup" task (see install_uses in _desc.yaml). Anything that cannot
        be handled here returns 16 so that "setup" falls back to the declarative
        "npm install -g @google/gemini-cli".
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL gemini api_v1 install")

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        uname = _global['host']['os']['uname']            # windows | linux | darwin
        exe = _global['host']['vars']['file_ext_exe']     # ".exe" on Windows else ""

        version = params.get('version')
        version_simple = params.get('version_simple')

        # A version range ("<1.0") cannot be turned into a release URL
        if version and not version_simple:
            return {
                'return': 16,
                'error': f'custom install for "gemini" needs an exact version in "{__file__}"',
                'install_cmd': cmd,
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        # Node.js runs the bundle - "setup" has already resolved it via install_uses
        node_path = _global.get('node-js', {}).get('path', '')

        if not node_path:
            return {
                'return': 16,
                'error': 'the "node-js" tool was not set up, so the Gemini CLI bundle cannot be run',
                'install_cmd': cmd,
            }

        # Without an explicit version take GitHub's "latest release" redirect -
        # that keeps a fresh install fresh without pinning a version in the meta
        if version_simple:
            url = f'{GITHUB_REPO}/releases/download/v{version_simple}/{BUNDLE_ASSET}'
        else:
            url = f'{GITHUB_REPO}/releases/latest/download/{BUNDLE_ASSET}'

        directory = 'content'

        path_to_bundle = os.path.join(os.getcwd(), directory, BUNDLE_ENTRY)

        # Windows needs a .cmd - a bare extensionless file is not executable there
        launcher_name = 'gemini.cmd' if uname == 'windows' else 'gemini' + exe
        path_to_tool = os.path.join(os.getcwd(), directory, launcher_name)

        if con:
            print ('')
            print (f'{space}INFO: Current path: {os.getcwd()}')
            print (f'{space}INFO: Gemini CLI download URL: {url}')
            print (f'{space}INFO: Node.js: {node_path}')
            print (f'{space}INFO: Check file: {path_to_bundle}')
            print ('')

        ###########################################################################################
        # Download and unpack the bundle

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'filename': BUNDLE_ASSET,
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 0,
              'check_file': path_to_bundle,
        }

        rx = self.cm.access(ii)

        if rx['return'] > 0:
            # Upstream moved the asset, this version has no bundle, no network, ...
            # -> let "setup" try the declarative npm install instead of failing
            if con:
                print ('')
                print (f'{space}WARNING: could not download {url}: {rx.get("error","")}')
                print (f'{space}         falling back to the declarative install command')

            return {'return': 16,
                    'error': f'could not download the Gemini CLI bundle from {url}',
                    'install_cmd': cmd}

        ###########################################################################################
        # Write the launcher next to the bundle.
        # The absolute Node.js path is baked in so that the launcher also works
        # when it is called outside cMeta (i.e. straight from PATH).

        if uname == 'windows':
            text = ('@echo off\r\n'
                    f'"{node_path}" "%~dp0{BUNDLE_ENTRY}" %*\r\n')
        else:
            text = ('#!/bin/sh\n'
                    f'exec "{node_path}" "$(dirname "$0")/{BUNDLE_ENTRY}" "$@"\n')

        try:
            with open(path_to_tool, 'w', encoding='utf-8', newline='') as f:
                f.write(text)

            if uname != 'windows':
                os.chmod(path_to_tool, os.stat(path_to_tool).st_mode
                         | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception as e:
            return {'return': 16,
                    'error': f'cannot write the gemini launcher {path_to_tool}: {e}',
                    'install_cmd': cmd}

        if con:
            print ('')
            print (f'{space}INFO: Launcher: {path_to_tool}')

        return {
            'return': 0,
            'install_cmd': None,        # tell setup NOT to run a shell install
            'found_path': path_to_tool,
        }
