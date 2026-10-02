"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup pip onnxruntime": the ONNX Runtime package for the target compute. Each build of
ONNX Runtime is its own package on PyPI, and they all install the same "onnxruntime" module, so
a Python environment holds one of them (programs keep one venv per set of targets):

  cuda                     onnxruntime-gpu[cuda,cudnn]  (CUDA 13 and cuDNN 9 from pip; Windows, Linux)
  npu-intel, xpu, openvino onnxruntime-openvino         (Intel CPU, GPU, NPU; Windows, Linux x86_64;
                                                        Python 3.11-3.13)
  rocm                     onnxruntime-migraphx         (AMD GPUs; Linux)
  cpu, metal, others       onnxruntime                  (CPU; CoreML on macOS)

--with.ort_package=<package> picks another one (onnxruntime-directml, onnxruntime-qnn, ...).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# The package for a set of targets, and its extras; the first match wins
PACKAGES = (
    (('cuda',), 'onnxruntime-gpu', ['cuda', 'cudnn']),
    (('npu-intel', 'xpu', 'openvino'), 'onnxruntime-openvino', []),
    (('rocm',), 'onnxruntime-migraphx', []),
)

# Python versions with wheels (onnxruntime-openvino lags behind)
PYTHON_RANGE = {'onnxruntime-openvino': ((3, 11), (3, 14))}
PYTHON_DEFAULT_RANGE = ((3, 11), (3, 15))

# On Windows, onnxruntime-openvino loads the OpenVINO runtime of the openvino package (openvino.dll),
# which must be the release it was built against (its PyPI description names it)
OPENVINO_FOR_ORT = {'1.24': '2025.4.1', '1.23': '2025.3.0', '1.22': '2025.1.0'}
ORT_OPENVINO_DEFAULT = '1.24.1'


def openvino_runtime(ort_version):
    """The openvino release for an onnxruntime-openvino version, or None."""
    return OPENVINO_FOR_ORT.get('.'.join(str(ort_version or ORT_OPENVINO_DEFAULT).split('.')[:2]))


def ort_package(compute, override = None):
    """The ONNX Runtime package and its extras for the targets."""
    if override:
        return override, []
    for targets, package, extras in PACKAGES:
        if any(t in compute for t in targets):
            return package, list(extras)
    return 'onnxruntime', []


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
        Install the ONNX Runtime build for the target compute instead of the CPU package.
        """

        _global = ctx['tasks']['global']
        compute = _global.get('target', {}).get('compute') or ['cpu']

        _with = params.setdefault('with', {})

        package, extras = ort_package(compute, _with.get('ort_package'))
        _with['package'] = package
        if extras and not _with.get('extras'):
            _with['extras'] = extras

        python_version = _global.get('python', {}).get('version', '')
        try:
            py = tuple(int(x) for x in python_version.split('.')[:2])
        except ValueError:
            py = ()
        low, high = PYTHON_RANGE.get(package, PYTHON_DEFAULT_RANGE)
        if py and not (low <= py < high):
            return self.cm.error(f'{package} has wheels for Python {low[0]}.{low[1]}-{high[0]}.{high[1] - 1} '
                                 f'(the selected Python is {python_version}): add '
                                 f'--use.python.version=">={low[0]}.{low[1]},<{high[0]}.{high[1]}"')

        variations = _with.setdefault('variations', {})
        variations['compute'] = sorted(set(variations.get('compute', [])) | set(compute))

        # The OpenVINO release onnxruntime-openvino was built against, in the same pip install (and
        # in the cache identity, so an older setup without it is not reused): on Windows its EP
        # loads openvino.dll from it; everywhere it lists the devices (which GPU is the Intel one)
        note = ''
        if package == 'onnxruntime-openvino':
            version = params.get('version')
            if not version:
                version = ORT_OPENVINO_DEFAULT
                params['version'] = version
            openvino = openvino_runtime(version)
            if not openvino:
                return self.cm.error(f'which openvino release onnxruntime-openvino {version} needs is not known: '
                                     f'add it to OPENVINO_FOR_ORT in {__file__}')
            post_flags = _with.get('post_flags') or ''
            if 'openvino==' not in post_flags:
                _with['post_flags'] = (post_flags + f' openvino=={openvino}').strip()
            variations['openvino'] = openvino
            note = f' with openvino {openvino}'

        if ctx['control'].get('con', False):
            print ('')
            print (f'INFO: ONNX Runtime for {",".join(compute)}: {package}' +
                   (f'[{",".join(extras)}]' if extras else '') + note)

        return {'return': 0}
