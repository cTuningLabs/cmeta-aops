"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re
from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

RELEASES = 'https://github.com/ggml-org/llama.cpp/releases'

# Release assets are named llama-b<N>-bin-<platform>-<backend>-<arch>.<ext> (the CPU builds of
# Linux and macOS have no backend part), CUDA builds come with a cudart bundle:
#   win:    llama-b<N>-bin-win-{cpu,vulkan,sycl,cuda-<ver>,rocm-<ver>,openvino-<ver>}-{x64,arm64}.zip
#           cudart-llama-bin-win-cuda-<ver>-{x64,arm64}.zip
#   ubuntu: llama-b<N>-bin-ubuntu-{x64,arm64,vulkan-*,cuda-<ver>-*,rocm-<ver>-x64,...}.tar.gz
#           cudart-llama-b<N>-bin-ubuntu-cuda-<ver>-{x64,arm64}.tar.gz
#   macos:  llama-b<N>-bin-macos-{arm64,x64}.tar.gz (Metal built in on arm64)
# The CUDA versions change with the build (13.3 -> 13.4, Linux CUDA builds since ~b10xxx), so the
# installer reads the release's real asset list and falls back to these rules only when offline.
FALLBACK_CUDA = {'windows': ['13.4', '13.3', '12.4'], 'linux': ['13.4', '13.3', '12.8']}

# Binaries next to llama-cli that programs use (result keys <name>_path / <name>_qpath)
SIBLINGS = {'completion': 'llama-completion', 'bench': 'llama-bench', 'server': 'llama-server', 'cli': 'llama-cli'}


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except ValueError:
        return ()


def release_assets(build, timeout = 30):
    """
    The asset names of release b<build>, read from the release's expanded-assets page:
    no GitHub API call, so no rate limit. None when the page cannot be read.
    """
    import urllib.request

    url = f'{RELEASES}/expanded_assets/b{build}'
    try:
        request = urllib.request.Request(url, headers = {'User-Agent': 'cmeta-aops'})
        with urllib.request.urlopen(request, timeout = timeout) as response:
            html = response.read().decode('utf-8', 'replace')
    except Exception:
        return None

    names = sorted(set(re.findall(rf'/releases/download/b{build}/([^"?#\s]+)', html)))
    return names or None


def select_asset(build, uname, uarch, backend, assets = None, cuda_driver = None, cuda_wanted = None, glibc = None):
    """
    The release asset (and its cudart bundle) for this platform and backend.

    backend: cpu | cuda | vulkan | rocm | sycl | openvino | metal
    cuda_driver: the CUDA version the driver supports ("13.3"); cuda_wanted: a forced CUDA
    version (--with.ver). CUDA: the newest build not newer than the driver, else one of the
    driver's major version (CUDA minor-version compatibility), else nothing.

    Returns {'asset', 'cudart', 'cuda', 'note'} or {'error'}.
    """
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(uarch)
    if not arch:
        return {'error': f'llama.cpp publishes no binaries for the CPU architecture "{uarch}"'}

    plat = {'windows': 'win', 'linux': 'ubuntu', 'darwin': 'macos'}.get(uname)
    if not plat:
        return {'error': f'llama.cpp publishes no binaries for "{uname}"'}

    ext = 'zip' if plat == 'win' else 'tar.gz'
    prefix = f'llama-b{build}-bin-{plat}-'

    def has(name):
        return assets is None or name in assets

    if plat == 'macos':
        if backend not in ('cpu', 'metal'):
            return {'error': f'llama.cpp publishes no {backend} binaries for macOS (build it from source)'}
        name = f'{prefix}{arch}.{ext}'
        return {'asset': name} if has(name) else {'error': f'release b{build} has no asset {name}'}

    if backend == 'metal':
        return {'error': 'Metal is available on macOS only'}

    if backend == 'cpu':
        name = f'{prefix}cpu-{arch}.{ext}' if plat == 'win' else f'{prefix}{arch}.{ext}'
        return {'asset': name} if has(name) else {'error': f'release b{build} has no asset {name}'}

    if backend in ('vulkan', 'sycl'):
        # Linux SYCL comes as fp16/fp32 builds
        names = [f'{prefix}{backend}-{arch}.{ext}']
        if backend == 'sycl':
            names += [f'{prefix}sycl-fp16-{arch}.{ext}', f'{prefix}sycl-fp32-{arch}.{ext}']
        for name in names:
            if has(name) and (assets is not None or name == names[0]):
                return {'asset': name}
        return {'error': f'release b{build} has no {backend} build for {plat}/{arch}'}

    if backend == 'cuda' and plat == 'ubuntu' and glibc and _version_tuple(glibc) < (2, 38):
        # The Linux CUDA builds come from Ubuntu 24.04 containers
        return {'error': f'the Linux CUDA binaries need glibc 2.38 or newer (this system has {glibc}): '
                         f'build from source'}

    if backend in ('rocm', 'openvino', 'cuda'):
        pattern = re.compile(rf'^{re.escape(prefix)}{backend}-([\d.]+)-{arch}\.{re.escape(ext)}$')
        if assets is not None:
            versions = sorted({m.group(1) for m in map(pattern.match, assets) if m}, key = _version_tuple, reverse = True)
        elif backend == 'cuda':
            versions = FALLBACK_CUDA['windows' if plat == 'win' else 'linux']
        else:
            versions = []

        if not versions:
            return {'error': f'release b{build} has no {backend} build for {plat}/{arch}'}

        note = None
        if backend != 'cuda':
            ver = versions[0]
        elif cuda_wanted:
            if cuda_wanted not in versions:
                return {'error': f'release b{build} has no CUDA {cuda_wanted} build for {plat}/{arch} '
                                 f'(available: {", ".join(versions)})'}
            ver = cuda_wanted
        else:
            ver = None
            if cuda_driver:
                # A build runs on any driver of its CUDA major version (CUDA minor-version
                # compatibility), and newer builds carry kernels for newer GPUs (the 12.4 build
                # has none for Blackwell): the newest build whose major the driver supports
                drv = _version_tuple(cuda_driver)
                usable = [v for v in versions if _version_tuple(v)[:1] <= drv[:1]]
                if usable:
                    ver = usable[0]
                    if _version_tuple(ver) > drv:
                        note = (f'the driver supports CUDA {cuda_driver}, the CUDA {ver} build runs on it '
                                f'through CUDA minor-version compatibility')
            else:
                ver = versions[0]
                note = 'the driver CUDA version is unknown, using the newest CUDA build'
            if not ver:
                return {'error': f'the driver supports CUDA {cuda_driver}, older than every CUDA build of '
                                 f'release b{build} ({", ".join(versions)}): update the driver or build from source'}

        name = f'{prefix}{backend}-{ver}-{arch}.{ext}'
        result = {'asset': name, backend: ver}
        if note:
            result['note'] = note

        if backend == 'cuda':
            cudart = (f'cudart-llama-bin-win-cuda-{ver}-{arch}.zip' if plat == 'win'
                      else f'cudart-llama-b{build}-bin-ubuntu-cuda-{ver}-{arch}.tar.gz')
            if has(cudart):
                result['cudart'] = cudart

        return result

    return {'error': f'unknown llama.cpp backend "{backend}"'}


# The cMeta targets that select a GPU backend of llama.cpp (backend_from_compute)
GPU_TARGETS = ('cuda', 'vulkan', 'rocm', 'xpu', 'openvino', 'metal')


def backend_from_compute(compute, uname):
    """The llama.cpp backend for a cMeta compute list (accelerators first; CPU is in every build)."""
    for c, backend in (('cuda', 'cuda'), ('vulkan', 'vulkan'), ('rocm', 'rocm'), ('xpu', 'sycl'),
                       ('openvino', 'openvino'), ('metal', 'metal')):
        if c in compute:
            return backend
    return 'metal' if uname == 'darwin' else 'cpu'


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """

        name = self.cdesc['name']

        # FGG: extension depends on target / compiler and not just on host
        # For example Android on Windows will have .so and not .dll ...

        _with = params.setdefault('with', {})

#        if 'static' not in _with:
#            _with['static'] = False
#
#        if 'debug_info' not in _with:
#            _with['debug_info'] = False

        compute = _with.get('compute')
        if not compute:
            compute = ctx['tasks']['global'].get('target',{}).get('compute')
        if not compute:
            compute = ['cpu']

        if type(compute) == str:
            compute = compute.split(',')

        _with['compute'] = compute
        ctx['tasks']['local']['compute'] = compute

        if 'android-cpu' in compute:
            name += ''
        else:
            if 'compiler-c' in ctx['tasks']['global']:
                name += ctx['tasks']['global']['compiler-c']['features']['vars']['file_ext_exe']
            else:
                name += ctx['tasks']['global']['host']['vars']['file_ext_exe']

        ctx['tasks']['local']['tool_name'] = name

        # Check if Android
        k = 'target--android-cpu'
        target_abi = _with.get('android_abi')
        if not target_abi:
            if k in ctx['tasks']['global']:
                target_abi = ctx['tasks']['global'][k]['features']['ro.product.cpu.abi']

        ctx['tasks']['local']['target_abi'] = target_abi

        return {'return': 0}

    ############################################################
    def customize_build(self,
                        ctx,
                        misc
    ):
        """
        """

        result = {'return':0}

        # Without --version, build the pinned build (as the prebuilt install does) rather than
        # whatever the cached clone of the repository holds
        version = misc.get('version') or self.cdesc.get('default_version')

        if version:
            checkout = f'b{version}'

            result['add_to_local'] = {'checkout': checkout}

        return result


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """
        # We need to update paths and dynamic libs here from compilation context
        # before llama-cpp is called to detect version since it may miss dynamic libs

        _static = params.get('with',{}).get('static', False)

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        _with = params.get('with', {})
        _static = _with.get('static', False)
        _debug_info = _with.get('debug_info', False)

        target_compute = ctx['tasks']['local']['compute']

        _android_cpu = True if 'android-cpu' in target_compute else False
        _cuda = True if 'cuda' in target_compute else False

        _cpu = False
        if 'cpu' in target_compute:
            _cpu = True
        if _android_cpu: 
            _cpu = False

        found_paths_info = {}

        result = {'return':0}

        for path in paths:
#            Actually, even if compiled as static, it may pick up and link dynamically compiled libs from cMeta!
#            if not _static:
            # Attempt to load cMeta compilation context
            # (if was compiled via cMeta)

            path_bin = os.path.dirname(path)
            path_root = os.path.dirname(path_bin)
            path_repro_compile = os.path.join(path_root, '_repro_ctx_compile.json')

            if os.path.isfile(path_repro_compile):
                r = self.cm.utils.files.read_file(path_repro_compile)
                if r['return'] == 0:
                    _compiled_state = r['data']
                    if _compiled_state.get('result', {}).get('return') == 0:
                        _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local', {})
                        if _compiled_state_local:
                            sdl = _compiled_state_local.get('setup-dynamic-libs', {})
                            fdlp = sdl.get('found_dynamic_lib_paths')
                            if fdlp:
                                found_paths_info[path] = {'features': {'paths':{'found_dynamic_lib_paths': fdlp}, 'with': _with}}

        if found_paths_info:
            result['found_paths_info'] = found_paths_info

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Add the binaries next to llama-cli - also to results replayed from the cache:
        result['completion_path'/'completion_qpath'] (llama-completion, the one-shot
        text completion since the late-2025 llama-cli rework; llama-cli itself in older
        builds), 'bench_*' (llama-bench), 'server_*' (llama-server).
        """

        path = result.get('path')
        if not path:
            return {'return': 0}

        path_bin = os.path.dirname(path)
        ext = os.path.splitext(path)[1]

        for key, exe in SIBLINGS.items():
            p = os.path.join(path_bin, exe + ext)
            if not os.path.isfile(p):
                if key != 'completion':
                    continue
                # Builds before the llama-cli rework: llama-cli is the completion tool
                p = path
            result[f'{key}_path'] = p
            result[f'{key}_qpath'] = self.cm.q(p)

        return {'return': 0, 'result': result}

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
            self.logger.debug("RUNNING TOOL llama-cpp api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        _with = params.setdefault('with', {})

        target = ctx['tasks']['global'].get('target', {})

        compute = _with.get('compute')
        if not compute:
            compute = target.get('compute')
        if not compute:
            compute = ['cpu']
        if type(compute) == str:
            compute = compute.split(',')

        # A release build has one GPU backend (and the CPU one): taking the first of two GPU
        # targets would run a different experiment than the one asked for
        gpu_targets = [c for c in compute if c in GPU_TARGETS]
        if len(gpu_targets) > 1 and not _with.get('backend'):
            return self.cm.error(f'llama.cpp releases have one GPU backend per build, not '
                                 f'{" + ".join(gpu_targets)}: build one with all of them '
                                 f'(cx program run build-llama-cpp --compute={",".join(compute)}) '
                                 f'or run one target at a time')

        backend = _with.get('backend') or backend_from_compute(compute, uname)

        # Forces the CUDA version of the build (--with.ver=12.4)
        ver = _with.get('ver')
        if not ver and backend == 'cuda':
            ver = target.get('features', {}).get('cuda', {}).get('ver')

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = str(self.cdesc['default_version'])
            version_simple = version

        if not version_simple or not str(version_simple).isdigit():
            return {
                'return': 16,
                'error': f'custom install for llama.cpp needs an exact build number such as {self.cdesc["default_version"]} '
                         f'(cx tool setup llama-cpp --versions lists them) in "{__file__}"',
                'install_cmd': cmd,
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        # The CUDA version the driver supports ("CUDA UMD version" since driver 610): from the
        # target (a program run with --compute=cuda), else detect the driver here (tool/cuda)
        cuda_driver = target.get('features', {}).get('cuda', {}).get('versions', {}).get('cuda version')
        if backend == 'cuda' and not cuda_driver and not ver:
            if 'cuda' not in _global:
                # A failed sub-task does not restore the caller's context: keep a copy
                tasks = ctx['tasks']
                saved = {k: tasks.get(k) for k in ('local', 'params', 'cparams')}
                saved_control = dict(ctx['control'])
                try:
                    rc = self.cm.access({'category': 'task,c36be4b9314a45e0',
                                         'command': 'run',
                                         'arg1': 'setup,a2f9b61079ce4333',
                                         'name': 'cuda,805716c4f32d42cf',
                                         'ctx': ctx,
                                         'skip_install': True,
                                         'skip_build': True,
                                         'con': con, 'quiet': quiet, 'verbose': verbose})
                finally:
                    for k, v in saved.items():
                        if v is not None:
                            tasks[k] = v
                    ctx['control'].clear()
                    ctx['control'].update(saved_control)
                if rc['return'] > 0 and con:
                    print ('')
                    print (f'{space}WARNING: no NVIDIA driver detected ({rc.get("error")})')
            cuda_driver = _global.get('cuda', {}).get('features', {}).get('versions', {}).get('cuda version')

        assets = release_assets(version_simple)
        if assets is None and con:
            print ('')
            print (f'{space}WARNING: could not list the assets of release b{version_simple}; using the naming rules')

        glibc = None
        if uname == 'linux':
            import platform
            lib, glibc_version = platform.libc_ver()
            if lib == 'glibc':
                glibc = glibc_version

        sel = select_asset(version_simple, uname, uarch, backend, assets = assets,
                           cuda_driver = cuda_driver, cuda_wanted = ver, glibc = glibc)
        if 'error' in sel:
            return {
                'return': 16,
                'error': f'llama.cpp prebuilt binaries: {sel["error"]} - compute={compute}, backend={backend}, '
                         f'{uname}/{uarch}',
                'install_cmd': cmd,
            }

        if sel.get('note') and con:
            print ('')
            print (f'{space}INFO: {sel["note"]}')

        filename = sel['asset']
        filename2 = sel.get('cudart')
        strip_folders = 1 if uname != 'windows' else None

        url = f'{RELEASES}/download/b{version_simple}/{filename}'

        directory = 'content'
        name = self.cdesc.get('name', 'llama-cli')
        path_to_llama = os.path.join(os.getcwd(), directory, name + _global['host']['vars']['file_ext_exe'])

        if filename2:
            url2 = f'{RELEASES}/download/b{version_simple}/{filename2}'

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: llama.cpp download URL: {url}')
            if filename2:
                print (f'{space}INFO: CUDA runtime bundle: {url2}')
            print (f'{space}INFO: Check file: {path_to_llama}')

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
              'check_file': path_to_llama,
              'make_check_file_executable': True,
        }

        if strip_folders:
            ii['strip_folders'] = strip_folders

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        ###########################################################################################
        # The CUDA runtime (cudart, cuBLAS) next to the binaries

        if filename2:

            ii['url'] = url2
            del(ii['clean'])
            del(ii['check_file'])
            del(ii['make_check_file_executable'])

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

        result = {
          'return': 0,
          'install_cmd': None,
          'found_path': path_to_llama,
          'version': version,
        }

        _update_params = {'with': {'backend': backend}}
        if sel.get('cuda'):
            _update_params['with']['cuda_build'] = sel['cuda']
        result['_update_params'] = _update_params

        return result


