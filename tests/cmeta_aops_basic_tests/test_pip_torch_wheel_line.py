"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the wheel line (CUDA cu130, ROCm rocm7.2) that tool/pip takes for torch and the packages
built against it (torchvision, torchaudio, ...) when the request names none: the torch that is already in
the Python of the request decides - its packages come from its index, and a request for torch itself that the
installed torch satisfies keeps it. Until 0.45.0 the newest line of the machine was taken whatever was
installed: a quiet run replaced torch 2.14.1+cu130 by 2.14.1+cu132 and gave a cu130 torch a cu132 torchvision.
A line that is named (with.ver, an index, the target's) is taken as before, whatever is installed.
"""

import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CU = 'https://download.pytorch.org/whl/cu'
ROCM = 'https://download.pytorch.org/whl/rocm'


@pytest.fixture(scope = 'module')
def pip():
    path = REPO_ROOT / 'tool' / 'pip' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                     'class InitCTool: pass')
    ns = {'__name__': 'tool_pip', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


class Engine:
    """The engine as tool/pip uses it here: the real version matching, a Python whose torch is `installed`."""

    def __init__(self, cm, installed):
        self.utils = types.SimpleNamespace(common = cm.utils.common, sys = types.SimpleNamespace(run = self.run))
        self.repos = cm.repos
        self.installed = installed
        self.asked = []

    def q(self, path):
        return '"' + path + '"'

    def run(self, cmd, **kw):
        self.asked.append(cmd)
        if self.installed is None:
            return {'return': 0, 'returncode': 1, 'stdout': '', 'stderr': 'importlib.metadata.PackageNotFoundError: torch'}
        return {'return': 0, 'returncode': 0, 'stdout': self.installed + '\n', 'stderr': ''}

    def error(self, text, code = 1):
        return {'return': code, 'error': text}


def setup(pip, cm, installed, package = 'torch', version = None, compute = 'cuda', machine = '13.3', python = True,
          con = False, target_ver = None, **with_):
    """_common_compute_init for a request; returns (the compute variations, post_flags, what was asked of the Python)."""
    tool = pip['CTool'].__new__(pip['CTool'])
    tool.cm = Engine(cm, installed)
    tool.logger = None
    features = {'cuda': {'versions': {'cuda version': machine}},
                'rocm': {'rocm_version': machine, 'gfx': ['gfx942']}}[compute]
    if target_ver:
        features['ver'] = target_ver
    ctx = {'control': {'con': con},
           'tasks': {'global': {'target': {'compute': [compute, 'cpu'], 'features': {compute: features}}}}}
    if python:
        ctx['tasks']['global']['python'] = {'path': sys.executable}
    params = {'with': dict({'package': package}, **with_)}
    if version:
        params['version'] = version
    r = tool._common_compute_init(ctx, params, skip_extras = True)
    assert r['return'] == 0, r.get('error')
    return params['with']['variations']['compute'], params['with'].get('post_flags', ''), tool.cm.asked


###################################################################################################

@pytest.mark.parametrize('version, kind, line', [
    ('2.14.1+cu130', 'cu', '130'),
    ('2.11.0+cu128', 'cu', '128'),
    ('2.5.1+cu118', 'cu', '118'),
    ('2.14.1+rocm7.2', 'rocm', '7.2'),
    ('2.14.0+rocm10.1.0', 'rocm', None),        # AMD's build: another source, not a line of PyTorch's index
    ('2.14.1+cpu', 'cu', None),
    ('2.14.1', 'cu', None),
    ('2.14.0a0+git0d62256', 'cu', None),        # a source build
    ('2.14.1+cu130', 'rocm', None),
    ('2.14.1+rocm7.2', 'cu', None),
    ('', 'cu', None),
    (None, 'cu', None),
])
def test_wheel_line(pip, version, kind, line):
    assert pip['wheel_line'](version, kind) == line


def test_no_torch_installed_takes_the_line_of_the_machine(pip, cm):
    variations, flags, asked = setup(pip, cm, None)
    assert variations == ['cuda', 'cu132', 'cpu'] and flags == f'--index-url {CU}132'
    assert len(asked) == 1 and 'importlib.metadata' in asked[0] and sys.executable in asked[0]


def test_an_installed_torch_keeps_its_line(pip, cm):
    """The incident: torch 2.14.1+cu130 in the venv, a request that names neither a version nor a line."""
    variations, flags, _ = setup(pip, cm, '2.14.1+cu130')
    assert variations == ['cuda', 'cu130', 'cpu'] and flags == f'--index-url {CU}130'


@pytest.mark.parametrize('version', ['2.14.1', '==2.14.1', '>=2.13', '>=2.14.1'])
def test_a_request_for_the_installed_version_keeps_its_line(pip, cm, version):
    variations, flags, _ = setup(pip, cm, '2.14.1+cu130', version = version)
    assert variations == ['cuda', 'cu130', 'cpu'] and flags == f'--index-url {CU}130'


@pytest.mark.parametrize('version', ['2.13.0', '==2.11.0', '<2.14', '>=2.15'])
def test_a_request_for_another_torch_takes_the_line_of_the_machine(pip, cm, version):
    """Replacing the torch is what was asked: as before (the older line may not even carry that version)."""
    variations, flags, _ = setup(pip, cm, '2.14.1+cu130', version = version)
    assert variations == ['cuda', 'cu132', 'cpu'] and flags == f'--index-url {CU}132'


@pytest.mark.parametrize('package, version', [('torchvision', None), ('torchvision', '0.29.1'), ('torchaudio', None),
                                              ('torchaudio', '2.13.0'), ('flash-attn', None)])
def test_packages_built_against_torch_follow_its_line(pip, cm, package, version):
    """torchvision for a cu130 torch comes from the cu130 index, whatever version of it is asked."""
    variations, flags, _ = setup(pip, cm, '2.14.1+cu130', package = package, version = version)
    assert variations == ['cuda', 'cu130', 'cpu'] and flags == f'--index-url {CU}130'


@pytest.mark.parametrize('installed', ['2.14.1+cpu', '2.14.1', '2.14.0a0+git0d62256', '2.14.0+rocm10.1.0'])
def test_a_torch_without_a_cuda_line_has_no_say(pip, cm, installed):
    """A CPU wheel or a source build on a CUDA target: the line of the machine, as before."""
    for package in ('torch', 'torchvision'):
        variations, flags, _ = setup(pip, cm, installed, package = package)
        assert variations == ['cuda', 'cu132', 'cpu'] and flags == f'--index-url {CU}132'


def test_a_named_line_is_taken_whatever_is_installed(pip, cm):
    variations, flags, asked = setup(pip, cm, '2.14.1+cu130', ver = '12.8')
    assert variations == ['cuda', 'cu128', 'cpu'] and flags == f'--index-url {CU}128'
    assert asked == []                                           # nothing to ask the Python


def test_a_named_index_is_taken_whatever_is_installed(pip, cm):
    variations, flags, asked = setup(pip, cm, '2.14.1+cu130', post_flags = '--index-url https://example.org/whl/cu126')
    assert variations == ['cuda', 'cpu'] and flags == '--index-url https://example.org/whl/cu126'
    assert asked == []


def test_the_line_of_the_target_is_taken_whatever_is_installed(pip, cm):
    variations, flags, asked = setup(pip, cm, '2.14.1+cu130', target_ver = '12.6')
    assert variations == ['cuda', 'cu126', 'cpu'] and flags == f'--index-url {CU}126'
    assert asked == []


def test_an_installed_line_the_machine_would_not_pick(pip, cm):
    """A machine older than every line of the list: no index before, the installed torch's now."""
    variations, flags, _ = setup(pip, cm, None, machine = '11.0')
    assert variations == ['cuda', 'cpu'] and flags == ''
    variations, flags, _ = setup(pip, cm, '2.5.1+cu118', machine = '11.0')
    assert variations == ['cuda', 'cu118', 'cpu'] and flags == f'--index-url {CU}118'


def test_other_flags_of_the_request_are_kept(pip, cm):
    variations, flags, _ = setup(pip, cm, '2.14.1+cu130', package = 'torchvision', post_flags = '--no-deps')
    assert flags == f'--no-deps --index-url {CU}130'


def test_no_python_yet(pip, cm):
    variations, flags, asked = setup(pip, cm, '2.14.1+cu130', python = False)
    assert variations == ['cuda', 'cu132', 'cpu'] and asked == []


def test_it_says_so_when_the_line_is_not_the_one_of_the_machine(pip, cm, capsys):
    setup(pip, cm, '2.14.1+cu130', package = 'torchvision', con = True)
    out = capsys.readouterr().out
    assert 'torch 2.14.1+cu130 is in this Python' in out and 'cu130' in out and '--use.pip-torchvision.with.ver=' in out
    setup(pip, cm, '2.14.1+cu132', package = 'torchvision', con = True)       # the line the machine picks anyway
    assert capsys.readouterr().out == ''
    setup(pip, cm, '2.14.1+cu130', package = 'torchvision', con = False)
    assert capsys.readouterr().out == ''


###################################################################################################
# ROCm, PyTorch's own index

def test_rocm_no_torch_installed(pip, cm):
    variations, flags, _ = setup(pip, cm, None, compute = 'rocm', machine = '10.1')
    assert variations == ['rocm', 'rocm7.2', 'cpu'] and flags == f'--index-url {ROCM}7.2'


def test_rocm_an_installed_torch_keeps_its_line(pip, cm):
    for package in ('torch', 'torchvision'):
        variations, flags, _ = setup(pip, cm, '2.13.0+rocm7.1', package = package, compute = 'rocm', machine = '10.1')
        assert variations == ['rocm', 'rocm7.1', 'cpu'] and flags == f'--index-url {ROCM}7.1'


def test_rocm_another_torch_version_takes_the_line_of_the_machine(pip, cm):
    variations, flags, _ = setup(pip, cm, '2.13.0+rocm7.1', version = '2.14.1', compute = 'rocm', machine = '10.1')
    assert variations == ['rocm', 'rocm7.2', 'cpu'] and flags == f'--index-url {ROCM}7.2'


def test_rocm_a_build_of_amd_has_no_say_here(pip, cm):
    """torch from AMD's index (+rocm10.1.0) is another source (with.rocm_source): as before."""
    variations, flags, _ = setup(pip, cm, '2.14.0+rocm10.1.0', compute = 'rocm', machine = '10.1')
    assert variations == ['rocm', 'rocm7.2', 'cpu'] and flags == f'--index-url {ROCM}7.2'


def test_rocm_a_named_line(pip, cm):
    variations, flags, asked = setup(pip, cm, '2.13.0+rocm7.1', compute = 'rocm', machine = '10.1', ver = '7.0')
    assert variations == ['rocm', 'rocm7.0', 'cpu'] and flags == f'--index-url {ROCM}7.0' and asked == []
