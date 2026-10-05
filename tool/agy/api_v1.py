"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/agy - Antigravity CLI (https://antigravity.google/docs/cli), the Google sibling of the "claude", "codex" and
"opencode" tools of cmeta-aops.

Tier 1: download the release archive from GitHub (https://github.com/google-antigravity/antigravity-cli/releases):
"agy_cli_<os>_<arch>.zip" on Windows, ".tar.gz" on Linux and macOS. Each archive holds one file, "antigravity" or
"antigravity.exe" (checked with 1.2.16), which is renamed to "agy" so that the detection ("names:" in _desc.yaml) and
the official command name agree. Google's own installers download the same binary from a GCS bucket (per-platform
manifests with a sha512 at https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/
<os>_<arch>.json) and then run "agy install", which edits the shell profile and PATH; cMeta skips that step and keeps
the binary in its cache. Whatever this hook cannot handle returns 16, so that "setup" falls back to the declarative
install_cmd of _desc.yaml (winget on Windows, the official install script elsewhere).

The binary updates itself unless AGY_CLI_DISABLE_AUTO_UPDATE=true is set; the "run-agy" task sets it, so that the
version cMeta installed stays the version that runs.
"""

import glob
import os
import stat

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

GITHUB_REPO = 'https://github.com/google-antigravity/antigravity-cli'

# (OS, arch as task "host" reports them) -> the release asset
ASSETS = {
    ('windows', 'amd64'): 'agy_cli_windows_x64.zip',
    ('windows', 'arm64'): 'agy_cli_windows_arm64.zip',
    ('linux', 'amd64'): 'agy_cli_linux_x64.tar.gz',
    ('linux', 'arm64'): 'agy_cli_linux_arm64.tar.gz',
    ('darwin', 'amd64'): 'agy_cli_mac_x64.tar.gz',
    ('darwin', 'arm64'): 'agy_cli_mac_arm64.tar.gz',
}
# Alpine and the other musl distributions
MUSL_ASSETS = {'amd64': 'agy_cli_linux_x64_musl.tar.gz', 'arm64': 'agy_cli_linux_arm64_musl.tar.gz'}

ARCHIVE_MEMBER = 'antigravity'      # the one file inside the archive
TOOL_NAME = 'agy'                   # the official command name


def _is_musl(os_info):
    os_id = str(os_info.get('os_id') or os_info.get('id') or '').lower()
    if 'alpine' in os_id:
        return True
    try:
        return len(glob.glob('/lib/ld-musl-*.so.1')) > 0
    except Exception:
        return False


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
        Download the Antigravity CLI release archive from GitHub (curl, no package manager, no profile change),
        unpack its single file and register it as "agy".
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL agy api_v1 install")

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        os_info = _global['host']['os']
        uname = os_info['uname']                          # windows | linux | darwin
        uarch = os_info['uarch']                          # amd64 | arm64
        exe = _global['host']['vars']['file_ext_exe']     # ".exe" on Windows else ""

        version = params.get('version')
        version_simple = params.get('version_simple')

        # A version range ("<2.0") cannot be turned into a release URL
        if version and not version_simple:
            return {
                'return': 16,
                'error': f'custom install for "agy" needs an exact version in "{__file__}"',
                'install_cmd': cmd,
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        asset = ASSETS.get((uname, uarch))
        if asset and uname == 'linux' and _is_musl(os_info):
            asset = MUSL_ASSETS.get(uarch, asset)

        if not asset:
            return {
                'return': 16,
                'error': f'Google publishes no Antigravity CLI build for {uname}/{uarch}',
                'install_cmd': cmd,
            }

        # Without an explicit version take GitHub's "latest release" redirect
        if version_simple:
            url = f'{GITHUB_REPO}/releases/download/{version_simple}/{asset}'
        else:
            url = f'{GITHUB_REPO}/releases/latest/download/{asset}'

        directory = 'content'

        path_to_member = os.path.join(os.getcwd(), directory, ARCHIVE_MEMBER + exe)
        path_to_tool = os.path.join(os.getcwd(), directory, TOOL_NAME + exe)

        if con:
            print ('')
            print (f'{space}INFO: Current path: {os.getcwd()}')
            print (f'{space}INFO: Antigravity CLI download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_member}')
            print ('')

        ###########################################################################################
        # Download and unpack the archive

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'filename': asset,
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 0,
              'check_file': path_to_member,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)

        if rx['return'] > 0:
            # Upstream moved the asset, this version has none, no network, ...
            # -> let "setup" try the declarative install instead of failing
            if con:
                print ('')
                print (f'{space}WARNING: could not download {url}: {rx.get("error","")}')
                print (f'{space}         falling back to the declarative install command')

            return {'return': 16,
                    'error': f'could not download the Antigravity CLI from {url}',
                    'install_cmd': cmd}

        ###########################################################################################
        # The file in the archive is "antigravity"; the command is "agy"

        try:
            if os.path.isfile(path_to_member):
                os.replace(path_to_member, path_to_tool)
            elif not os.path.isfile(path_to_tool):
                # the layout changed: take the one binary that is there
                root = os.path.join(os.getcwd(), directory)
                found = [f for f in glob.glob(os.path.join(root, '**', '*'), recursive=True)
                         if os.path.isfile(f) and os.path.basename(f).lower().startswith(('antigravity', 'agy', 'cli_'))]
                if not found:
                    raise FileNotFoundError(f'no binary in {root} after unpacking {asset}')
                os.replace(found[0], path_to_tool)

            if uname != 'windows':
                os.chmod(path_to_tool, os.stat(path_to_tool).st_mode
                         | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception as e:
            return {'return': 16,
                    'error': f'cannot prepare the agy binary {path_to_tool}: {e}',
                    'install_cmd': cmd}

        if con:
            print ('')
            print (f'{space}INFO: Antigravity CLI: {path_to_tool}')

        return {
            'return': 0,
            'install_cmd': None,        # tell setup NOT to run a shell install
            'found_path': path_to_tool,
        }
