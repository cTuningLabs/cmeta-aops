"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

LUNARG = 'https://sdk.lunarg.com/sdk/download'
LUNARG_VERSION = re.compile(r'^\d+\.\d+\.\d+\.\d+$')

# Characters the LunarG Windows installer (Qt Installer Framework) refuses in --root
UNSUPPORTED_PATH_CHARS = '!'


def sdk_layout(root, uname):
    """glslc, header, include, lib and bin of an SDK root, or None when it is not one."""
    exe = '.exe' if uname == 'windows' else ''
    for bin_dir, inc_dir, lib_dir in (('Bin', 'Include', 'Lib'), ('bin', 'include', 'lib')):
        glslc = os.path.join(root, bin_dir, 'glslc' + exe)
        header = os.path.join(root, inc_dir, 'vulkan', 'vulkan_core.h')
        if os.path.isfile(glslc) and os.path.isfile(header):
            return {'root': root, 'bin': os.path.join(root, bin_dir), 'include': os.path.join(root, inc_dir),
                    'lib': os.path.join(root, lib_dir), 'glslc': glslc, 'header': header}
    return None


def loader_library(layout, uname):
    """
    The loader library to link with: the SDK's own (Windows: Lib/vulkan-1.lib, macOS:
    lib/libvulkan.dylib), else - the LunarG Linux SDK no longer ships the loader - the system's
    libvulkan.so (from libvulkan-dev) or its runtime libvulkan.so.1.
    """
    names = {'windows': ['vulkan-1.lib'], 'darwin': ['libvulkan.dylib', 'libvulkan.1.dylib']}.get(
        uname, ['libvulkan.so', 'libvulkan.so.1'])
    for name in names:
        p = os.path.join(layout['lib'], name)
        if os.path.isfile(p):
            return p
    if uname == 'linux':
        for pattern in ('/usr/lib/*-linux-gnu/libvulkan.so', '/usr/lib64/libvulkan.so', '/usr/lib/libvulkan.so',
                        '/usr/lib/*-linux-gnu/libvulkan.so.1', '/usr/lib64/libvulkan.so.1', '/usr/lib/libvulkan.so.1'):
            found = sorted(glob.glob(pattern))
            if found:
                return found[0]
    if uname == 'darwin':
        for p in ('/opt/homebrew/lib/libvulkan.dylib', '/usr/local/lib/libvulkan.dylib'):
            if os.path.isfile(p):
                return p
    return None


def header_version(header):
    """1.<minor>.<VK_HEADER_VERSION> from vulkan_core.h."""
    try:
        with open(header, encoding = 'utf-8', errors = 'replace') as f:
            text = f.read()
    except OSError:
        return None
    patch = re.search(r'#define\s+VK_HEADER_VERSION\s+(\d+)', text)
    complete = re.search(r'VK_HEADER_VERSION_COMPLETE\s+VK_MAKE_API_VERSION\(\s*0\s*,\s*(\d+)\s*,\s*(\d+)', text)
    if not patch:
        return None
    major, minor = (complete.group(1), complete.group(2)) if complete else ('1', '3')
    return f'{major}.{minor}.{patch.group(1)}'


def lunarg_version(root):
    """The LunarG SDK version of a root: C:\\VulkanSDK\\1.4.350.0 or ~/VulkanSDK/1.4.350.0/x86_64."""
    for p in (root, os.path.dirname(root)):
        name = os.path.basename(os.path.normpath(p))
        if LUNARG_VERSION.match(name):
            return name
    return None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _candidate_roots(self, ctx, params):
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        home = os.path.expanduser('~')

        roots = []

        tool_path = params.get('tool_path')
        if tool_path:
            # glslc itself, or an SDK root
            p = os.path.abspath(tool_path)
            if os.path.isfile(p):
                p = os.path.dirname(os.path.dirname(p))
            return [p]

        env = os.environ.get('VULKAN_SDK')
        if env:
            roots.append(env)

        # An SDK this setup installed: in its cache entry (the working directory of setup), or
        # in ~/VulkanSDK when the cache path has characters the LunarG installer rejects
        here = os.path.join(os.getcwd(), 'content')
        roots += [p for p in glob.glob(os.path.join(here, '*', 'x86_64')) + glob.glob(os.path.join(here, '*'))
                  if os.path.isdir(p)]

        def versions_desc(pattern):
            found = [p for p in glob.glob(pattern) if os.path.isdir(p)]
            def key(p):
                v = lunarg_version(p) or '0'
                return [int(x) for x in v.split('.') if x.isdigit()]
            return sorted(found, key = key, reverse = True)

        if uname == 'windows':
            for drive in ('C:', 'D:'):
                roots += versions_desc(drive + r'\VulkanSDK\*')
            roots += versions_desc(os.path.join(home, 'VulkanSDK', '*'))
        elif uname == 'darwin':
            roots += versions_desc(os.path.join(home, 'VulkanSDK', '*', 'macOS'))
            roots += ['/opt/homebrew', '/usr/local']
        else:
            roots += versions_desc(os.path.join(home, 'VulkanSDK', '*', 'x86_64'))
            roots += versions_desc(os.path.join(home, 'VulkanSDK', '*', 'aarch64'))
            roots += ['/usr', '/usr/local', '/home/linuxbrew/.linuxbrew']

        unique = []
        for r in roots:
            r = os.path.normpath(r)
            if r not in unique:
                unique.append(r)
        return unique

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The SDK roots that have glslc and vulkan_core.h; the tool is glslc, its version the
        LunarG SDK version (1.4.350.0) or the headers' (1.4.341). Features: paths.{root,
        include, lib, bin, glslc}, kind (lunarg | system).
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL vulkan-sdk api_v1 detect")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        uname = ctx['tasks']['global']['host']['os']['uname']

        parsed = []

        for root in self._candidate_roots(ctx, params):
            layout = sdk_layout(root, uname)
            if not layout:
                continue

            lunarg = lunarg_version(root)
            version = lunarg or header_version(layout['header'])
            if not version:
                continue

            if con and verbose:
                print (f'{space}INFO: Vulkan SDK {version} at {root}')

            layout = dict(layout, loader_lib = loader_library(layout, uname))

            parsed.append({'path': layout['glslc'],
                           'detected_version': version,
                           'features': {'paths': layout,
                                        'kind': 'lunarg' if lunarg else 'system',
                                        'header_version': header_version(layout['header'])}})

        return {'return': 0, 'parsed_paths_with_versions': parsed}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Export the SDK for the steps that follow (also for results replayed from the cache):
        VULKAN_SDK, its bin on PATH and, for a LunarG SDK on Linux/macOS, its lib on
        LD_LIBRARY_PATH / DYLD_LIBRARY_PATH.
        """

        paths = result.get('features', {}).get('paths', {})
        root = paths.get('root')
        if not root:
            return {'return': 0}

        uname = ctx['tasks']['global']['host']['os']['uname']

        env = {'VULKAN_SDK': root, '+PATH': [paths['bin']]}
        if result.get('features', {}).get('kind') == 'lunarg' and uname != 'windows':
            key = '+DYLD_LIBRARY_PATH' if uname == 'darwin' else '+LD_LIBRARY_PATH'
            env[key] = [paths['lib']]

        _aggregate = result.setdefault('_aggregate', {})
        _aggregate.setdefault('env', {}).update(env)

        return {'return': 0, 'result': result}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The pinned LunarG SDK into this cache entry: the Linux x86_64 tarball, or the Windows
        x64 installer in copy-only mode (no system changes, no administrator rights). Other
        systems, or a failed installer, return 16 with the declarative fallback (Homebrew,
        winget, the distro packages).
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL vulkan-sdk api_v1 install")

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc['default_version'])
        if not version or not LUNARG_VERSION.match(str(version)):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the LunarG SDK install needs an exact version such as {self.cdesc["default_version"]}'}

        if not ((uname == 'linux' and uarch == 'amd64') or (uname == 'windows' and uarch == 'amd64')):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'LunarG publishes no SDK archive for {uname}/{uarch} here: using the fallback'}

        directory = 'content'
        content = os.path.join(os.getcwd(), directory)
        root = os.path.join(content, version, 'x86_64') if uname == 'linux' else os.path.join(content, version)

        if uname == 'windows' and any(c in root for c in UNSUPPORTED_PATH_CHARS):
            # The LunarG installer refuses such paths ("The installation path must not contain !"):
            # install per user, as LunarG's Linux default ~/VulkanSDK/<version> (detect() looks there)
            root = os.path.join(os.path.expanduser('~'), 'VulkanSDK', version)
            if con:
                print ('')
                print (f'{space}INFO: the cMeta cache path has a character the LunarG installer rejects: '
                       f'installing into {root}')

        if uname == 'linux':
            url = f'{LUNARG}/{version}/linux/vulkan_sdk.tar.xz'
            filename = f'vulkansdk-linux-x86_64-{version}.tar.xz'
        else:
            url = f'{LUNARG}/{version}/windows/vulkan_sdk.exe'
            filename = f'vulkansdk-windows-X64-{version}.exe'

        if con:
            print ('')
            print (f'{space}INFO: Vulkan SDK {version}: {url}')

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'filename': filename,
              'env': params.get('env'),
              'timeout': params.get('timeout'),
              'con': con, 'quiet': quiet, 'verbose': verbose,
        }
        if uname == 'linux':
            ii.update({'unzip': True, 'clean_after_unzip': True,
                       'check_file': os.path.join(root, 'bin', 'glslc')})

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r

        if uname == 'windows':
            installer = os.path.join(content, filename)
            # Qt Installer Framework command line; copy_only=1: files only - no environment
            # variables, registry entries or system-wide Vulkan runtime
            run = (f'{self.cm.q(installer)} --root {self.cm.q(root)} --accept-licenses --default-answer '
                   f'--confirm-command install copy_only=1')
            rx = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                 'arg1': 'cmd,c9ba0a88df394d7f', 'cmd': run, 'timeout': 3600,
                                 'con': con, 'quiet': quiet, 'verbose': verbose, 'text_cmd': 'RUN:',
                                 'fail_if_nonzero_return_code': False})
            if self.cm.catch_error(rx): return rx
            if rx.get('returncode', 1) != 0 or not sdk_layout(root, uname):
                return {'return': 16, 'install_cmd': cmd,
                        'error': f'the LunarG installer did not complete (return code {rx.get("returncode")}): '
                                 f'falling back to winget'}
            try:
                os.remove(installer)
            except OSError:
                pass

        layout = sdk_layout(root, uname)
        if not layout:
            return self.cm.error(f'the Vulkan SDK {version} was unpacked but {root} has no glslc and headers')

        return {'return': 0, 'install_cmd': None, 'found_path': layout['glslc']}
