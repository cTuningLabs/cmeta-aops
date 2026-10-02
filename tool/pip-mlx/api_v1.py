"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup pip mlx": Apple's MLX array framework with the backend of the target compute,
from PyPI:

  metal, cpu on macOS (Apple silicon)   mlx              (Metal; mlx-metal comes with it)
  cuda                                  mlx[cuda13]      Linux; a CUDA 13 driver and GPUs of
                                                         compute capability 7.5 (Turing) or newer
                                        mlx[cuda12]      Linux; the other NVIDIA GPUs and drivers
  cpu elsewhere                         mlx[cpu]         Linux (x86_64, aarch64) and Windows (where
                                                         mlx-cpu is named too: the extra is Linux-only)

--with.mlx_extras=<extras> picks the extras instead.
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

CUDA13_MIN_ARCH = 75


def mlx_extras(compute, uname, uarch, driver_cuda = None, gpu_arch_min = None, extras = None):
    """The mlx extras for the targets on this host: (extras, error)."""
    if extras:
        if isinstance(extras, str):
            extras = extras.split(',')
        return [x.strip() for x in extras if x.strip()], None

    if 'cuda' in compute:
        if uname != 'linux':
            return None, 'MLX has a CUDA backend for Linux only'
        driver = str(driver_cuda or '')
        major = int(driver.split('.')[0]) if driver[:1].isdigit() else None
        if major is not None and major < 12:
            return None, f'MLX needs an NVIDIA driver for CUDA 12 or newer; this one supports CUDA {driver}'
        if (major is None or major >= 13) and (gpu_arch_min is None or gpu_arch_min >= CUDA13_MIN_ARCH):
            return ['cuda13'], None
        return ['cuda12'], None

    if uname == 'darwin':
        if uarch != 'arm64':
            return None, 'MLX runs on Apple silicon Macs only'
        return [], None                     # Metal and the CPU in the macOS wheel

    if 'metal' in compute:
        return None, 'the metal target needs macOS on Apple silicon'

    return ['cpu'], None


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
        Install the mlx extras (its backend) of the target compute; they are part of the cache
        identity, so a CPU install is not reused for CUDA.
        """
        _global = ctx['tasks']['global']
        host = _global['host']['os']
        target = _global.get('target', {})
        compute = target.get('compute') or ['cpu']
        _with = params.setdefault('with', {})

        cuda = _global.get('cuda', {}).get('features') or target.get('features', {}).get('cuda') or {}
        arch = cuda.get('compute_cap_int_min')
        extras, error = mlx_extras(compute, host['uname'], host.get('uarch'), (cuda.get('versions') or {}).get('cuda version'),
                                   int(arch) if arch else None, _with.get('mlx_extras'))
        if error:
            return self.cm.error(f'{error} (targets {",".join(compute)})')
        if extras and not _with.get('extras'):
            _with['extras'] = extras

        # mlx 0.32's "cpu" extra is declared for Linux only, although mlx-cpu has Windows wheels:
        # name the backend package itself there, or mlx installs without one ("DLL load failed")
        if host['uname'] == 'windows' and 'cpu' in (_with.get('extras') or []):
            version = params.get('version')
            backend = 'mlx-cpu' + ('==' + version if version and version[:1].isdigit() else '')
            post_flags = _with.get('post_flags') or ''
            if 'mlx-cpu' not in post_flags:
                _with['post_flags'] = (post_flags + ' ' + backend).strip()

        variations = _with.setdefault('variations', {})
        variations['compute'] = sorted(set(variations.get('compute', [])) | set(compute))
        variations['mlx_backend'] = ','.join(_with.get('extras') or []) or 'metal'

        if ctx['control'].get('con', False):
            print ('')
            print (f'INFO: MLX for {",".join(compute)}: mlx' + (f'[{",".join(_with["extras"])}]' if _with.get('extras') else ''))
        return {'return': 0}
