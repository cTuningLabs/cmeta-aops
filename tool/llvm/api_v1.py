"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re
import shutil
import urllib.error
import urllib.request

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

LLVM_RELEASES = 'https://github.com/llvm/llvm-project/releases/download/llvmorg-{version}/{filename}'
LLVM_TAGS_REPO = 'https://github.com/llvm/llvm-project'

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

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        new_paths = []

        for p in paths:
            features = p.setdefault('features', {})
            paths = features.setdefault('paths', {})

            path = p['path']

            path_bin = os.path.dirname(path)
            path_home = os.path.dirname(path_bin)

            paths['bin'] = path_bin
            paths['qbin'] = self.cm.q(path_bin)

            paths['home'] = path_home
            paths['qhome'] = self.cm.q(path_home)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}


    ############################################################
    def _resolve_release(self,
                         ctx: dict,
                         prefix: str,
                         filename_template: str,
    ):
        """
        Newest published LLVM release whose version starts with `prefix` ("22" -> "22.1.8", "22.1" -> "22.1.8").

        The versions come from the upstream tags (git ls-remote, the same source as cmd_get_versions);
        release candidates (22.1.0-rc1) and "22-init" tags are skipped. Newest first, the release whose
        prebuilt asset for this platform answers on GitHub is taken - a release tagged minutes ago may have
        no assets yet, and then the previous one is the right answer.

        Args:
            ctx (dict): The cMeta context (the git tool set up earlier is reused when present).
            prefix (str): Partial version, "22" or "22.1".
            filename_template (str): Asset file name with "{version}" in place of the version.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **version** (str): The resolved release, e.g. "22.1.8".
                - **filename** (str): The asset file name for that release.
                - **prefix** (str): The prefix that was resolved.
                - **candidates** (list): All matching releases, newest first.
        """

        _global = ctx['tasks']['global']

        git = (_global.get('git') or {}).get('qpath')
        if not git:
            git_path = shutil.which('git')
            git = self.cm.q(git_path) if git_path else None
        if not git:
            return {'return': 1,
                    'error': f'git is needed to list the LLVM releases for the partial version "{prefix}"; '
                             f'install git or pass an exact version (cx tool setup llvm --versions lists them)'}

        r = self.cm.utils.sys.run(f'{git} ls-remote --tags {LLVM_TAGS_REPO}', capture_output=True)
        if r['return'] > 0: return r
        if r['returncode'] != 0:
            return {'return': 1, 'error': f'listing the LLVM releases failed: {r.get("stderr", "").strip()}'}

        releases = set()
        for line in r['stdout'].splitlines():
            match = re.search(r'refs/tags/llvmorg-(\d+\.\d+\.\d+)$', line.strip())
            if match:
                releases.add(match.group(1))

        candidates = sorted((v for v in releases if v.startswith(prefix + '.')),
                            key=lambda v: [int(x) for x in v.split('.')], reverse=True)
        if not candidates:
            return {'return': 1,
                    'error': f'no published LLVM release matches version "{prefix}" '
                             f'(cx tool setup llvm --versions lists the available ones)'}

        for v in candidates[:5]:
            filename = filename_template.format(version=v)
            if self._asset_exists(LLVM_RELEASES.format(version=v, filename=filename)):
                return {'return': 0, 'version': v, 'filename': filename, 'prefix': prefix, 'candidates': candidates}

        return {'return': 1,
                'error': f'the newest LLVM releases matching "{prefix}" ({", ".join(candidates[:5])}) publish no '
                         f'prebuilt "{filename_template}" asset; pass an exact version'}

    ############################################################
    def _asset_exists(self,
                      url: str,
    ):
        """
        True when GitHub answers the release asset URL with a redirect (the asset exists) or any 2xx/3xx;
        False on HTTP 404. A network problem counts as True so that an offline check never hides a release
        that does exist - the download step reports the real error then.
        """

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        request = urllib.request.Request(url, method='HEAD')
        try:
            with opener.open(request, timeout=20) as response:
                return 200 <= response.status < 400
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            return 200 <= e.code < 400 or e.code >= 500
        except Exception:
            return True

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL llvm api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')
        version_major = params.get('version_major')

        if not version:
            version = self.cdesc['default_version']
            version_simple = version
            version_major = version_simple[:2]

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for LLVM can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        url = None
        filename = None

        if uname == 'windows':
            if uarch == 'amd64':
                uarch2 = 'x86_64'
                filename = f'clang+llvm-{version_simple}-{uarch2}-pc-windows-msvc.tar.xz'
        elif uname == 'linux':
            if uarch == 'amd64':
                uarch2 = 'X64'
                filename = f'LLVM-{version_simple}-Linux-{uarch2}.tar.xz'
        elif uname == 'darwin':
            if uarch == 'arm64':
                uarch2 = 'ARM64'
                filename = f'LLVM-{version_simple}-macOS-{uarch2}.tar.xz'

        if not filename:
            return {
                'return': 16, 
                'error': f'custom install for LLVM could not create download URL',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        # A partial version ("22", "22.1") is not a release tag: llvmorg-22/LLVM-22-Linux-X64.tar.xz does
        # not exist (HTTP 404). Resolve it to the newest published release that starts with it and whose
        # prebuilt asset for this platform is there (a freshly tagged release may not have assets yet).
        if version_simple.count('.') < 2:
            r = self._resolve_release(ctx, version_simple, filename_template=filename.replace(version_simple, '{version}'))
            if self.cm.catch_error(r): return r
            if con:
                print ('')
                print (f'{space}INFO: LLVM version "{version_simple}" resolved to the newest published release {r["version"]}')
            version_simple = r['version']
            version = version_simple
            filename = r['filename']

        url = LLVM_RELEASES.format(version=version_simple, filename=filename)

        directory = 'content'
        path_to_clang = os.path.join(os.getcwd(), directory, 'bin', 'clang' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: LLVM download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_clang}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_clang,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_clang, 
          'version': version,
        }


