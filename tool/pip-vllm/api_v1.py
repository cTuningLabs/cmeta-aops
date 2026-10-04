"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup pip vllm": the vLLM wheel for the target compute.

vLLM publishes wheels for Linux (x86_64, aarch64) and macOS (Apple silicon, CPU), none for
Windows (use WSL2 or Docker). PyPI's wheel is the CUDA 13.0 build; the other builds live in
vLLM's per-release indexes https://wheels.vllm.ai/<version>/<variant> and carry a local
version (0.30.0+cu129, 0.30.0+cpu), which pip prefers over PyPI's plain 0.30.0:

  cuda   driver with CUDA 13+: PyPI (CUDA 13.0, torch from PyPI)
         driver with CUDA 12.x: /<version>/cu129 + torch from download.pytorch.org/whl/cu129
  cpu    /<version>/cpu (+ torch +cpu from download.pytorch.org/whl/cpu on Linux);
         Linux wheels need glibc 2.39 (0.30.0), the macOS wheel Python 3.12 and macOS 14
  rocm   /rocm/<version>/rocm723 (Python 3.12)
  xpu    /<version>/xpu + download.pytorch.org/whl/xpu

The per-release index needs the version: without --version the newest vLLM on PyPI is used
(and recorded as the version of this setup).
"""

import json
import os
import platform

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

WHEELS = 'https://wheels.vllm.ai'
TORCH_INDEX = 'https://download.pytorch.org/whl'


def newest_on_pypi(package, timeout = 30):
    import urllib.request
    try:
        with urllib.request.urlopen(f'https://pypi.org/pypi/{package}/json', timeout = timeout) as r:
            return json.loads(r.read().decode('utf-8'))['info']['version']
    except Exception:
        return None


def vllm_indexes(version, compute, uname, cuda_driver = None):
    """(extra index URLs, a note) for this vLLM version, compute and OS - or raise ValueError."""
    if uname == 'windows':
        raise ValueError('vLLM publishes no Windows wheels and does not support Windows natively: '
                         'run it in WSL2 (the same cMeta commands) or in Docker (vllm/vllm-openai)')

    if 'rocm' in compute:
        return [f'{WHEELS}/rocm/{version}/rocm723'], 'the ROCm wheels need Python 3.12'

    if 'xpu' in compute:
        return [f'{WHEELS}/{version}/xpu', f'{TORCH_INDEX}/xpu'], 'the XPU wheels need Python 3.12'

    if 'cuda' in compute and uname == 'linux':
        major = None
        try:
            major = int(str(cuda_driver).split('.')[0]) if cuda_driver else None
        except ValueError:
            major = None
        if major is not None and major < 13:
            return [f'{WHEELS}/{version}/cu129', f'{TORCH_INDEX}/cu129'], \
                   f'the driver supports CUDA {cuda_driver}: the CUDA 12.9 build of vLLM'
        return [], 'the CUDA 13.0 build of vLLM (PyPI; the driver must support CUDA 13)'

    # CPU (Linux, macOS); Metal has no vLLM backend here (vllm-metal is a separate project)
    indexes = [f'{WHEELS}/{version}/cpu']
    if uname == 'linux':
        indexes.append(f'{TORCH_INDEX}/cpu')
    return indexes, 'the CPU build of vLLM'


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
        Add vLLM's wheel index (and torch's) for the target compute to pip's flags.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']

        target = _global.get('target', {})
        compute = target.get('compute') or ['cpu']

        _with = params.setdefault('with', {})

        post_flags = _with.get('post_flags') or ''
        if '--index-url' in post_flags or '--extra-index-url' in post_flags:
            # The user chose the indexes
            return {'return': 0}

        version = params.get('version')
        if version and version[0].isdigit() and not any(c in version for c in '<>=*!~'):
            simple = version
        elif not version:
            simple = newest_on_pypi('vllm')
            if not simple:
                return self.cm.error('cannot read the newest vLLM version from PyPI: pass --version=<x.y.z>')
            params['version'] = simple
        else:
            return self.cm.error(f'the vLLM wheel indexes need an exact version (got "{version}")')

        cuda_driver = target.get('features', {}).get('cuda', {}).get('versions', {}).get('cuda version')

        try:
            indexes, note = vllm_indexes(simple, compute, uname, cuda_driver)
        except ValueError as e:
            return self.cm.error(str(e))

        python_version = _global.get('python', {}).get('version', '')
        try:
            py = tuple(int(x) for x in python_version.split('.')[:2])
        except ValueError:
            py = ()
        if py and not ((3, 10) <= py < (3, 15)):
            return self.cm.error(f'vLLM {simple} supports Python 3.10-3.14 (the selected Python is {python_version}): '
                                 f'add --use.python.version=">=3.10,<3.15" or set up another Python')
        if uname == 'darwin' and not python_version.startswith('3.12'):
            return self.cm.error(f'vLLM publishes its macOS wheel for Python 3.12 only (the selected Python is '
                                 f'{python_version or "unknown"}): add --use.python.version=3.12')
        if python_version == '3.14.1':
            note += '; Python 3.14.1 is excluded by torchvision - use another 3.14.x'

        if ctx['control'].get('con', False):
            print ('')
            print (f'INFO: vLLM {simple}: {note}')

        if indexes:
            flags = ' '.join(f'--extra-index-url {i}' for i in indexes)
            _with['post_flags'] = (post_flags + ' ' + flags).strip()

        variations = _with.setdefault('variations', {})
        variations['compute'] = sorted(set(variations.get('compute', [])) | set(compute))

        return {'return': 0}
