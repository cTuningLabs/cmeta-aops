"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup pip jax": JAX with the plugin of the target compute, from PyPI. jax and jaxlib have
CPU wheels for Linux (x86_64, aarch64), macOS (Apple silicon) and Windows (x86_64); the
accelerators come as PJRT plugins, chosen from the targets:

  cuda   jax[cuda13]       Linux; NVIDIA's CUDA 13 libraries from pip. Needs a CUDA 13 driver
                           and GPUs of compute capability 7.5 (Turing) or newer
         jax[cuda12]       Linux; for the other NVIDIA GPUs and for CUDA 12 drivers
  rocm   jax[rocm7-local]  Linux x86_64, with the system's ROCm 7
  xpu    jax[oneapi]       Linux x86_64, not WSL2; Intel's oneAPI runtime from pip, running on
                           the Intel GPU's Level Zero driver (the xpu target sets up
                           tool/intel-gpu-runtime). An alpha release, validated on the Arc Pro
                           B-series and the Data Center GPU Max: the integrated HD, UHD and Iris
                           GPUs are refused before the install (--with.any_intel_gpu tries them)
  metal  jax-metal 0.1.1   macOS on Apple silicon, with JAX 0.5.0: Apple's last plugin release
                           runs no newer JAX (Python 3.10-3.13)
  cpu    jax               everywhere

Windows has no GPU plugin: CUDA runs in WSL2. --with.jax_extras=<extras> picks other extras
(cuda12-local, cuda13-local: the system's CUDA; tpu).
"""

import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# CUDA 13 builds for compute capability 7.5 and newer only
CUDA13_MIN_ARCH = 75

# Apple's last jax-metal, the newest JAX it runs (0.5.1 and later fail to compile), and the
# Python versions of that JAX
METAL_PLUGIN = 'jax-metal==0.1.1'
METAL_JAX = '0.5.0'
METAL_PYTHON = ((3, 10), (3, 14))

# The integrated Intel GPUs up to Xe-LP (Gen9 HD and UHD Graphics, Gen11 Iris Plus, Gen12 Iris Xe
# and UHD), on which JAX's oneAPI plugin does not compute (tested: Iris Xe of Raptor Lake, HD
# Graphics 630). Newer integrated GPUs are named "Arc".
OLD_INTEL_IGPU = re.compile(r'\b(HD Graphics|UHD Graphics|Iris)\b', re.I)


def old_intel_gpus(names):
    """The Intel GPUs when all of them are integrated GPUs up to Xe-LP, else []."""
    intel = [n for n in names if 'intel' in n.lower()]
    old = [n for n in intel if OLD_INTEL_IGPU.search(n)]
    return old if intel and len(old) == len(intel) else []


def jax_plugin(compute, uname, uarch, driver_cuda = None, gpu_arch_min = None, extras = None,
               intel_gpus = (), wsl = False, any_intel_gpu = False):
    """
    The jax extras and the extra packages for the targets on this host: (extras, packages, error).
    driver_cuda is the driver's CUDA version (13.0), gpu_arch_min the compute capability of the
    oldest GPU x 10 (50), intel_gpus the names of the GPUs that the xpu target found.
    """
    if extras:
        if isinstance(extras, str):
            extras = extras.split(',')
        return [x.strip() for x in extras if x.strip()], [], None

    linux_x86 = uname == 'linux' and uarch == 'amd64'

    if 'cuda' in compute:
        if uname != 'linux':
            where = ': run it in WSL2' if uname == 'windows' else ''
            return None, [], f'JAX has CUDA plugins for Linux only{where}'
        driver = str(driver_cuda or '')
        major = int(driver.split('.')[0]) if driver[:1].isdigit() else None
        if major is not None and major < 12:
            return None, [], f'JAX needs an NVIDIA driver for CUDA 12 or newer; this one supports CUDA {driver}'
        if (major is None or major >= 13) and (gpu_arch_min is None or gpu_arch_min >= CUDA13_MIN_ARCH):
            return ['cuda13'], [], None
        return ['cuda12'], [], None

    if 'rocm' in compute:
        if not linux_x86:
            return None, [], 'JAX has a ROCm plugin for Linux x86_64 only'
        return ['rocm7-local'], [], None

    if 'xpu' in compute:
        if not linux_x86 or wsl:
            return None, [], 'JAX has an Intel GPU plugin (jax-oneapi-plugin) for Linux x86_64 only, not WSL2'
        old = [] if any_intel_gpu else old_intel_gpus(intel_gpus)
        if old:
            return None, [], (f'JAX\'s Intel GPU plugin (an alpha release, validated on the Arc Pro B-series and the '
                              f'Data Center GPU Max) does not compute on {"; ".join(old)}: '
                              f'add --with.any_intel_gpu to try anyway')
        return ['oneapi'], [], None

    if 'metal' in compute:
        if uname != 'darwin' or uarch != 'arm64':
            return None, [], 'jax-metal needs macOS on Apple silicon'
        return [], [METAL_PLUGIN], None

    return [], [], None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params2(self,
                      ctx: dict,
                      params: dict,
                      cparams: dict,
    ):
        """
        Install the jax extras (its PJRT plugin) of the target compute; for metal, jax-metal with
        the JAX it runs. The plugin is in the cache identity, so a CPU install is not reused for a
        GPU.
        """

        _global = ctx['tasks']['global']
        host = _global['host']['os']
        target = _global.get('target', {})
        compute = target.get('compute') or ['cpu']

        _with = params.setdefault('with', {})

        cuda = _global.get('cuda', {}).get('features') or target.get('features', {}).get('cuda') or {}
        driver_cuda = (cuda.get('versions') or {}).get('cuda version')
        gpu_arch_min = cuda.get('compute_cap_int_min')

        xpu = _global.get('target--xpu', {}).get('features') or target.get('features', {}).get('xpu') or {}
        intel_gpus = [d.get('name', '') for d in xpu.get('devices', [])]

        extras, packages, error = jax_plugin(compute, host['uname'], host.get('uarch'), driver_cuda,
                                             int(gpu_arch_min) if gpu_arch_min else None,
                                             _with.get('jax_extras'), intel_gpus,
                                             wsl = os.path.exists('/dev/dxg'),
                                             any_intel_gpu = bool(_with.get('any_intel_gpu')))
        if error:
            return self.cm.error(f'{error} (targets {",".join(compute)})')

        if extras and not _with.get('extras'):
            _with['extras'] = extras

        variations = _with.setdefault('variations', {})
        variations['compute'] = sorted(set(variations.get('compute', [])) | set(compute))
        variations['jax_plugin'] = ','.join(_with.get('extras') or []) + ','.join(packages)

        note = ''
        if packages:
            # jax-metal in the same pip install, with the newest JAX it runs (jax pins its jaxlib)
            if not params.get('version'):
                params['version'] = METAL_JAX

                python_version = _global.get('python', {}).get('version', '')
                try:
                    py = tuple(int(x) for x in python_version.split('.')[:2])
                except ValueError:
                    py = ()
                low, high = METAL_PYTHON
                if py and not (low <= py < high):
                    return self.cm.error(f'JAX {METAL_JAX} (for jax-metal) has wheels for Python {low[0]}.{low[1]}-'
                                         f'{high[0]}.{high[1] - 1} (the selected Python is {python_version}): add '
                                         f'--use.python.version=">={low[0]}.{low[1]},<{high[0]}.{high[1]}"')

            post_flags = _with.get('post_flags') or ''
            for p in packages:
                if p.split('==')[0] not in post_flags:
                    post_flags = (post_flags + ' ' + p).strip()
            _with['post_flags'] = post_flags
            note = f' with {" ".join(packages)}'

        if ctx['control'].get('con', False):
            print ('')
            print (f'INFO: JAX for {",".join(compute)}: jax' +
                   (f'[{",".join(_with["extras"])}]' if _with.get('extras') else '') +
                   (f' {params["version"]}' if params.get('version') else '') + note)

        return {'return': 0}
