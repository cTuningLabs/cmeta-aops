"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import shutil

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

from . import host
from . import redist

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        nvcc does not run on macOS. (The host compiler, GCC, clang or MSVC, is set up once the
        toolkit is found: _host_compiler, with --with.compiler_extra_tags and
        --with.compiler_extra_match.)
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nvcc api_v1 init")

        uname = ctx['tasks']['global']['host']['os']['uname']

        if uname == 'darwin':
            return self.cm.error(f'tool "nvcc" does not support MacOS')

        return {'return':0}

    ############################################################
    def _gpu(self, ctx, _with):
        """
        What a toolkit must suit, from tool/cuda: the CUDA version of the driver (13.0) and the
        architecture of the oldest GPU (its compute capability x 10: 50). --with.any_driver and
        --with.any_arch leave them out (to build for other machines).
        """

        cuda = ctx['tasks']['global'].get('cuda', {}).get('features', {})

        driver_cuda = str((cuda.get('versions') or {}).get('cuda version') or '')
        if not driver_cuda[:1].isdigit() or _with.get('any_driver'):
            driver_cuda = None

        gpu_arch_min = cuda.get('compute_cap_int_min')
        gpu_arch_min = int(gpu_arch_min) if gpu_arch_min and not _with.get('any_arch') else None

        return driver_cuda, gpu_arch_min

    ############################################################
    def _libs(self, _with):
        """The libraries asked for: --with.cuda_libs=cublas,cufft (or a list)."""

        libs = _with.get('cuda_libs') or []
        if isinstance(libs, str):
            libs = libs.split(',')

        return [x.strip() for x in libs if str(x).strip()]

    ############################################################
    def _host_compiler(self, ctx, result, params):
        """
        The host compiler of nvcc, set up once the toolkit is known: the newest one its
        include/crt/host_config.h accepts. Its limits become the versions of the compiler tools
        (--use.microsoft-visual-studio, msvc, gcc-cpp, clang-cpp.version); a version given with
        --use stays, and a C++ compiler version asked for with --use.compiler-cpp.version is not
        steered into the limits (the toolkit's check below reports it when it is rejected).
        --with.any_host_compiler takes any compiler, with nvcc's -allow-unsupported-compiler. A C++
        compiler set up earlier in the run that the toolkit rejects stops the run with what to change.

        Returns the flags that name the compiler to nvcc (-ccbin).
        """

        _global = ctx['tasks']['global']
        _with = params.get('with', {})

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        uname = _global['host']['os']['uname']
        nvcc_features = result['features']

        any_host_compiler = _with.get('any_host_compiler', False)
        lim = {} if any_host_compiler else host.read_limits(nvcc_features.get('paths', {}).get('home'))
        ranges = host.version_ranges(lim)

        if 'compiler-cpp' not in _global:
            use = ctx['tasks'].setdefault('use', {})
            if not (use.get('compiler-cpp') or {}).get('version'):
                # the compiler tools only: the Visual Studio installation follows the version of msvc
                for key, spec in ranges.items():
                    if key != 'microsoft-visual-studio':
                        use.setdefault(key, {}).setdefault('version', spec)

            compiler_extra_match = dict(_with.get('compiler_extra_match') or {})
            constraints = dict(compiler_extra_match.get('constraints') or {})
            supports_nvcc_os = list(constraints.get('supports_nvcc_os') or [])
            if uname not in supports_nvcc_os:
                supports_nvcc_os.append(uname)
            constraints['supports_nvcc_os'] = supports_nvcc_os
            compiler_extra_match['constraints'] = constraints

            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'compiler,f3925b201c704bde', 'lang': 'cpp',
                                'text': 'INFO: Selecting host compiler for NVCC',
                                'extra_tags': _with.get('compiler_extra_tags'),
                                'extra_match': compiler_extra_match,
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r): return r

        cc = _global.get('compiler-cpp', {})
        name = (cc.get('tool') or {}).get('name')

        why = host.unsupported(name, cc.get('version'), lim)
        if why:
            hint = f" (--use.{name}.version='{ranges[name]}')" if name in ranges else ''
            return self.cm.error(f'nvcc {result.get("version")} does not support the C++ compiler of this run: {why}. '
                                 f'Set up a supported one first{hint}, or pass --use.nvcc.with.any_host_compiler '
                                 f'(nvcc may then fail)')

        flag = f'-ccbin {cc["qpath"]}' if cc.get('qpath') else ''
        if any_host_compiler:
            flag = (flag + ' -allow-unsupported-compiler').strip()

        return {'return':0, 'flag':flag}

    ############################################################
    def customize_tool_cache_artifact(self,
                                      ctx,
                                      result,
                                      params,
                                      cache_tags,
                                      cache_params,
                                      cache_features,
                                      cache_meta,
        ):
        """
        A cache entry per GPU architecture: the toolkit found or installed for one GPU may not build
        for another (CUDA 13 does not build for Maxwell, Pascal and Volta GPUs)
        """

        _, gpu_arch_min = self._gpu(ctx, params.get('with', {}))
        if gpu_arch_min:
            cache_params['gpu_arch_min'] = gpu_arch_min

        return {'return':0}

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nvcc api_v1 check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        uname = ctx['tasks']['global']['host']['os']['uname']
        uarch = ctx['tasks']['global']['host']['os']['uarch']

        new_paths = []

#        compute_cap_int_min = ctx['tasks']['global']['cuda']['features']['compute_cap_int_min']
#        compute_cap_int_max = ctx['tasks']['global']['cuda']['features']['compute_cap_int_max']

        for p in paths:
            detected_version = p['detected_version']

            # Parsing standard output
            features = p.setdefault('features', {})

            path_nvcc = p['path']
            path_bin = os.path.dirname(path_nvcc)

            # Check supported arch
            cmd = self.cm.q(path_nvcc) + ' --list-gpu-arch --list-gpu-code'

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:', 
                  'capture_output': True,
                  # Important to be able to continue processing detect/install/build
                  'fail_if_nonzero_return_code': False, 
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']                                            

            if returncode>0:
                # If can't detect capabilities - skip
                continue

            else:
                farch = []
                fcode = []

                for s in rx['stdout'].strip().splitlines():
                    ss = s.split(',')
                    if len(ss) == 2:
                        sa = ss[0]
                        sc = ss[1]

                        if sa.startswith('arch=compute_'):
                            farch.append(int((sa[13:])))
                            if sc.startswith('code=sm_'):
                                fcode.append(int(sc[8:]))

                features['supported_arch'] = farch
                features['supported_arch_min'] = min(farch)
                features['supported_arch_max'] = max(farch)

                features['supported_code'] = fcode
                features['supported_code_min'] = min(fcode)
                features['supported_code_max'] = max(fcode)

                # A toolkit whose programs cannot run here (CUDA 13 on a Maxwell GPU, or with a driver
                # for CUDA 12) is of no use: skip it, so that a suitable one is found or installed
                # (--with.any_arch and --with.any_driver keep it, to build for other machines)
                driver_cuda, gpu_arch_min = self._gpu(ctx, _with)
                why = None
                if gpu_arch_min and features['supported_arch_min'] > gpu_arch_min:
                    why = f'it builds for sm_{features["supported_arch_min"]} and newer, the GPU is sm_{gpu_arch_min}'
                elif driver_cuda and redist.key(detected_version)[:1] > redist.key(driver_cuda)[:1]:
                    why = f'the driver runs CUDA {driver_cuda}'
                if why:
                    if con:
                        print ('')
                        print (f'INFO: skipping nvcc {detected_version} ({path_nvcc}): {why}')
                    continue

# Moved to dynamic since depends on the devices ...
#                # Prepare common gencode flags based on my device capabilities and NVCC capabilities
#                xarch = compute_cap_int_min if compute_cap_int_min < features['supported_arch_max'] else features['supported_arch_max']
#                xcode = compute_cap_int_min if compute_cap_int_min < features['supported_code_max'] else features['supported_code_max']
#
#                features['flags'] = {'gencode_auto': f'-gencode arch=compute_{xarch},code=sm_{xcode}'}

            # Finish checking various features

            _paths = {
               'bin': path_bin,
               'bins': [path_bin],
               'libs': [],
               'includes': [],
               'cmakes': [],
            }

            path_home = os.path.dirname(path_bin)
            _paths['home'] = path_home


            path_include = os.path.join(path_home, 'include')
            if os.path.isdir(path_include):
                _paths['include'] = path_include
                _paths['includes'].append(path_include)

            if uname == 'windows' and uarch == 'amd64':
                path_dll = os.path.join(path_bin, 'x64')
                if os.path.isdir(path_dll):
                    _paths['bins'].append(path_dll)

                path_lib = os.path.join(path_home, 'lib', 'x64')
                if os.path.isdir(path_lib):
                    _paths['lib'] = path_lib
                    _paths['libs'].append(path_lib)

                path_cmake = os.path.join(path_home, 'lib', 'cmake')
                if os.path.isdir(path_cmake):
                    _paths['cmake'] = path_cmake
                    _paths['cmakes'].append(path_cmake)
            elif uname == 'linux':

                path_lib = None 
                for x in ['lib64', 'lib']:
                     path_lib = os.path.join(path_home, x)
                     if os.path.isdir(path_lib):
                         break

                if path_lib:
                    _paths['lib'] = path_lib
                    _paths['libs'].append(path_lib)

            path_nvvm = os.path.join(path_home, 'nvvm')
            if os.path.isdir(path_nvvm):
                _paths['nvvm'] = path_nvvm

            path_nvvm_bin = os.path.join(path_nvvm, 'bin')
            if os.path.isdir(path_nvvm_bin):
                _paths['nvvm_bin'] = path_nvvm_bin
                _paths['bins'].append(path_nvvm_bin)

            path_nvvm_include = os.path.join(path_nvvm, 'include')
            if os.path.isdir(path_nvvm_include):
                _paths['nvvm_include'] = path_nvvm_include
                _paths['includes'].append(path_nvvm_include)

            if uname == 'windows' and uarch == 'amd64':
                nvvm_path_lib = os.path.join(path_nvvm, 'lib', 'x64')
                if os.path.isdir(nvvm_path_lib):
                    _paths['nvvm_path_lib'] = nvvm_path_lib
                    _paths['libs'].append(nvvm_path_lib)
            elif uname == 'linux':
                nvvm_path_lib = os.path.join(path_nvvm, 'lib64')
                if os.path.isdir(nvvm_path_lib):
                    _paths['nvvm_path_lib'] = nvvm_path_lib
                    _paths['libs'].append(nvvm_path_lib)

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            # Check versions
            file_versions = os.path.join(path_home, 'version.json')
            if os.path.isfile(file_versions):
                r = self.cm.utils.files.read_file(file_versions)
                if self.cm.catch_error(r): return r

                features_versions = features.setdefault('versions', {})
                features_versions.update(r['data'])

            # Check major version and some flags
            detected_version_major = None
            j = detected_version.find('.')
            if j>0:
                detected_version_major = int(detected_version[:j])
                features['version_major'] = detected_version_major

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _with = params.get('with',{})

        _result = {'return':0}

        update_result = False

        nvcc_features = result['features']

        uname = ctx['tasks']['global']['host']['os']['uname']

        # The host compiler, once the toolkit is known (not for the version check of a cache entry)
        if not params.get('version_check', False):
            r = self._host_compiler(ctx, result, params)
            if self.cm.catch_error(r): return r

            flags = nvcc_features.setdefault('flags', {})
            if flags.get('host_compiler') != r['flag']:
                flags['host_compiler'] = r['flag']
                update_result = True

        if _with.get('add_env', False):
            update_result = True

            features_paths = nvcc_features['paths']

            cuda_home = features_paths['home']
            cuda_bin = features_paths['bin']

            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['CUDA_HOME'] = cuda_home
            _aggregate_env['CUDA_PATH'] = cuda_home

            _path = _aggregate_env.setdefault('+PATH', [])
            if cuda_bin not in _path:
                _path.insert(0, cuda_bin)

        if _with.get('arch_flags', False):
            update_result = True

            supported_arch_min = nvcc_features['supported_arch_min']
            supported_arch_max = nvcc_features['supported_arch_max']

            gpu_compute_cap = ctx['tasks']['global']['cuda']['features']['compute_cap_int_min']

            supported_arch = nvcc_features.get('supported_arch') or \
                [a for a in (supported_arch_min, gpu_compute_cap, supported_arch_max) if supported_arch_min <= a <= supported_arch_max]

            if gpu_compute_cap < supported_arch_min:
                # The code would not run on this GPU
                return self.cm.error(f'nvcc {result.get("version")} builds for sm_{supported_arch_min} and newer, '
                                     f'but the GPU is sm_{gpu_compute_cap}: use an older CUDA toolkit '
                                     f'(--use.nvcc.version=<major.minor>; cx tool setup nvcc installs it without root)')

            # The GPU's own code, or, for a GPU the toolkit does not know (newer than it), the PTX of
            # the newest architecture before it, which the driver compiles for the GPU
            cuda_compute_arch = max(a for a in supported_arch if a <= gpu_compute_cap)
            code = f'sm_{cuda_compute_arch}' if cuda_compute_arch == gpu_compute_cap else f'compute_{cuda_compute_arch}'
            flag = f'-gencode arch=compute_{cuda_compute_arch},code={code}'

            target_arch = nvcc_features.setdefault('target_arch', {})
            target_arch_flags = target_arch.get('flags', '')

            # (once: a result reused in the same run has it already)
            target_arch['compute_cap'] = cuda_compute_arch
            if flag.split(' ', 1)[1] not in [x.strip() for x in target_arch_flags.split('-gencode')]:
                target_arch['flags'] = (target_arch_flags + ' ' if target_arch_flags else '') + flag

        # Update dynamic_build depending on the major version
        version_major = nvcc_features.get('version_major')
        dynamic_build_flag = nvcc_features['flags']['dynamic_build']

        x = 'shared'
        if uname == 'windows' and version_major >=13:
            x = 'hybrid'
        nvcc_features['flags']['dynamic_build'] = dynamic_build_flag.replace('{cudart_shared}', x)

        # The libraries a program asks for (--with.cuda_libs, or lib-cuda's lib_names), added to a
        # toolkit made from NVIDIA's archives when it lacks them (once: they stay in its cache entry)
        libs = self._libs(_with)
        if libs:
            r = self._add_libraries(ctx, nvcc_features.get('paths', {}).get('home'), libs, params)
            if self.cm.catch_error(r): return r

        if update_result:
            _result['result'] = result

        return _result

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        A CUDA toolkit from NVIDIA's redistributable archives (redist.py), without root: the release
        whose nvcc is --version (12.9.86, 12.9, 12, >=12.4,<12.7), else the newest, whose programs
        run on this driver and GPU. nvcc, the runtime and the headers, plus the libraries of
        --with.cuda_libs (cublas,cufft,...): each archive is checked against the sha256 of NVIDIA's
        list and unpacked into this cache entry (content/<release>/).
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        _with = params.get('with', {})

        platform = redist.platform_of(uname, uarch)
        if not platform:
            return self.cm.error(f'NVIDIA publishes no CUDA toolkit archives for {uname}/{uarch}')

        driver_cuda, gpu_arch_min = self._gpu(ctx, _with)
        wanted = params.get('version')

        manifests = {}
        def nvcc_of(release):
            if release not in manifests:
                manifests[release] = redist.manifest(release)
            return redist.nvcc_version(manifests[release])

        def matches(spec, version):
            return self.cm.packages.match_version(spec, version).get('matched', False)

        try:
            release, message = redist.choose(redist.releases(), wanted, matches, driver_cuda, gpu_arch_min, nvcc_of)
            if release:
                nvcc_of(release)
        except (OSError, ValueError) as e:
            return self.cm.error(f'cannot read the list of CUDA releases at {redist.BASE}: {e}')

        if not release:
            return self.cm.error(f'no CUDA toolkit to install: {message}')

        if message and con:
            print ('')
            print (f'{space}WARNING: {message}')

        m = manifests[release]
        archives = redist.components(m, platform, list(redist.COMPILER) + redist.lib_components(self._libs(_with)))
        if 'cuda_nvcc' not in [a[0] for a in archives]:
            return self.cm.error(f'CUDA {release} has no nvcc for {platform}')

        if con:
            size = sum(a[3] for a in archives) / 2**20
            print ('')
            print (f'{space}INFO: CUDA toolkit {release} (nvcc {redist.nvcc_version(m)}) for {platform} '
                   f'(the driver runs CUDA {driver_cuda or "?"}, the GPU is sm_{gpu_arch_min or "?"}): '
                   f'{", ".join(a[0] for a in archives)} ({size:.0f} MiB) from {redist.BASE}')

        root = os.path.join(os.getcwd(), 'content', release)

        r = self._unpack(ctx, root, release, platform, m, archives, params)
        if self.cm.catch_error(r): return r

        nvcc = os.path.join(root, 'bin', 'nvcc' + ('.exe' if uname == 'windows' else ''))
        if not os.path.isfile(nvcc):
            return self.cm.error(f'the CUDA toolkit {release} was unpacked but has no {nvcc}')

        return {'return':0, 'install_cmd':None, 'found_path':nvcc}

    ############################################################
    def _unpack(self, ctx, root, release, platform, m, archives, params):
        """
        Download the archives of a toolkit's components into its cache entry, check their sha256,
        unpack them into the toolkit and record them (the marker file and version.json).
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        # root is <cache entry>/content/<release>
        work = os.path.dirname(os.path.dirname(root))
        downloads = os.path.join(work, 'downloads')

        marker_file = os.path.join(root, redist.MARKER)
        marker = {'release': release, 'platform': platform, 'base': redist.BASE,
                  'nvcc': redist.nvcc_version(m), 'components': {}}
        if os.path.isfile(marker_file):
            with open(marker_file, encoding = 'utf-8') as f:
                marker = json.load(f)

        cur_dir = os.getcwd()
        try:
            for name, relative_path, sha, _ in archives:
                filename = relative_path.rsplit('/', 1)[-1]

                r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                    'arg1': 'download-file,03fed13e2e0447cf', 'chdir': work,
                                    'url': f'{redist.BASE}/{relative_path}', 'directory': 'downloads',
                                    'filename': filename, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                    'con': con, 'quiet': quiet, 'verbose': verbose})
                if self.cm.catch_error(r): return r

                archive = os.path.join(downloads, filename)
                digest = redist.sha256_of(archive)
                if sha and digest != sha:
                    return self.cm.error(f'{filename}: sha256 {digest} is not the {sha} of NVIDIA\'s list')

                try:
                    redist.unpack_into(archive, root)
                except (OSError, ValueError) as e:
                    return self.cm.error(f'cannot unpack {filename} into {root}: {e}')
                os.remove(archive)

                marker['components'][name] = {'version': (m.get(name) or {}).get('version'),
                                              'archive': relative_path, 'sha256': digest}
        finally:
            os.chdir(cur_dir)

        redist.link_targets(root, platform)

        with open(marker_file, 'w', encoding = 'utf-8') as f:
            json.dump(marker, f, indent = 2)

        unpacked = [n for n in marker['components'] if marker['components'][n]]
        with open(os.path.join(root, 'version.json'), 'w', encoding = 'utf-8') as f:
            json.dump(redist.version_json(m, release, unpacked), f, indent = 3)

        shutil.rmtree(downloads, ignore_errors = True)

        return {'return':0}

    ############################################################
    def _add_libraries(self, ctx, root, libs, params):
        """
        Add the components of libraries (cublas, cufft, ...) that a toolkit made from NVIDIA's
        archives lacks; a toolkit from NVIDIA's installer or a distribution is left as it is.
        """

        marker_file = os.path.join(root, redist.MARKER) if root else ''
        if not os.path.isfile(marker_file):
            return {'return':0}

        with open(marker_file, encoding = 'utf-8') as f:
            marker = json.load(f)

        missing = [n for n in redist.lib_components(libs) if n not in marker.get('components', {})]
        if not missing:
            return {'return':0}

        release, platform = marker['release'], marker['platform']

        try:
            m = redist.manifest(release)
        except (OSError, ValueError) as e:
            return self.cm.error(f'cannot read the CUDA {release} manifest at {redist.BASE}: {e}')

        archives = redist.components(m, platform, missing)

        # what NVIDIA does not publish for this platform is not asked for again
        absent = [n for n in missing if n not in [a[0] for a in archives]]
        if absent:
            marker.setdefault('components', {}).update({n: None for n in absent})
            with open(marker_file, 'w', encoding = 'utf-8') as f:
                json.dump(marker, f, indent = 2)

        if not archives:
            return {'return':0}

        names = ', '.join(a[0] for a in archives)
        size = sum(a[3] for a in archives) / 2**20
        con = ctx['control'].get('con', False)
        text = f'{names} ({size:.0f} MiB) from {redist.BASE} to the CUDA toolkit {release} in {root}'

        # A large download is the user's call, unless -q or --install says yes
        if con and not ctx['control'].get('quiet', False) and params.get('install') is not True:
            print ('')
            from task_c36be4b9314a45e0.api.ctask import ask as ask_user
            r = ask_user(f'INFO: add {text} (Y/n)? ', how = '-q (--quiet) or --install to add them without asking')
            if r['return'] > 0: return r
            x = r['answer'].strip().lower()
            if x not in ['', 'y', 'yes']:
                return self.cm.error(f'{names} not added to the CUDA toolkit {release} (the programs that link '
                                     f'{", ".join(libs)} need it)')
        elif con:
            print ('')
            print (f'INFO: adding {text}')

        return self._unpack(ctx, root, release, platform, m, archives, params)

