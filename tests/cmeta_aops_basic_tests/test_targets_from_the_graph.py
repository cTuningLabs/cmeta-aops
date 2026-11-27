"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Targets by query, not by lists of names in shared code (2026-11-27). A compute target is an artifact,
task::target--<name>, in any repository - a private backend is a target of a private repository - and what it is
stands in its _desc.yaml: support (device_os), instance_overlay, backends, probe. Shared code asks for the targets
(ctask.targets) and reads those facts; a tool's map of targets to its backends is data of the tool, extended by a
target's own `backends`. Offline: the helpers on stand-in answers of the engine, and the descriptions of the
repository's own targets.
"""

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(relative, cut = None, drop = ()):
    """The module-level code of a file of the repository (up to `cut`), without the imports that need the engine."""
    path = ROOT / relative
    src = path.read_text(encoding = 'utf-8')
    if cut:
        src = src[:src.index(cut)]
    for line in drop:
        assert line in src, line
        src = src.replace(line, '')
    ns = {'__name__': 'under_test_' + re.sub(r'\W', '_', relative), '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def ctask():
    return load('category/task/api/ctask.py', cut = '\nclass InitCTask')


def desc_of(target):
    return yaml.safe_load((ROOT / 'task' / ('target--' + target) / '_desc.yaml').read_text(encoding = 'utf-8'))


def own_targets():
    return {p.parent.name[len('target--'):]: yaml.safe_load(p.read_text(encoding = 'utf-8'))
            for p in sorted((ROOT / 'task').glob('target--*/_desc.yaml'))}


class Engine:
    """Answers the one question the helpers ask: find task::target--<pattern> with its _desc loaded."""

    def __init__(self, found):
        self.found = found
        self.asked = []

    def access(self, request):
        self.asked.append(request)
        assert request['category'] == 'task,c36be4b9314a45e0' and request['command'] == 'find' and request['load_files'] == ['_desc']
        pattern = request['arg1']
        names = [n for n in self.found if pattern == 'target--*' or pattern == 'target--' + n]
        return {'return': 0, 'artifacts': [{'cmeta_ref_parts': {'artifact_alias': 'target--' + n},
                                            'loaded_files': {'_desc': {'data': self.found[n]}}} for n in names]}


def test_the_targets_are_asked_of_the_graph(ctask):
    engine = Engine({'cuda': {'support': {'kind': 'gpu'}}, 'acme-npu': {'support': {'kind': 'npu'}, 'backends': {'llama-cpp': 'openvino'}}})
    found = ctask['targets'](engine)
    assert found == engine.found and engine.asked[0]['arg1'] == 'target--*'

    # nothing found, or the engine says no: no target - never a list of names to fall back on
    assert ctask['targets'](Engine({})) == {}

    class Refuses:
        def access(self, request):
            return {'return': 1, 'error': 'no'}
    assert ctask['targets'](Refuses()) == {}


def test_an_android_target_is_one_that_says_so(ctask):
    found = own_targets()
    on_device = ctask['targets_on_device']

    # the repository's own targets: the four Android ones and the three of iOS say their device's OS
    assert sorted(t for t in found if (found[t].get('support') or {}).get('device_os') == 'android') == [
        'android-app', 'android-cpu', 'android-gpu', 'android-npu']
    assert sorted(t for t in found if (found[t].get('support') or {}).get('device_os') == 'ios') == ['ios-cpu', 'ios-gpu', 'ios-npu']

    assert on_device(found, ['android-gpu'], 'android') and on_device(found, ['cpu', 'android-npu'], 'android')
    assert not on_device(found, ['cpu', 'cuda'], 'android') and not on_device(found, ['ios-cpu'], 'android')
    assert not on_device(found, [], 'android') and not on_device({}, ['android-cpu'], 'android')

    # a target of another repository for an Android device needs no change of the shared tasks
    private = dict(found, **{'acme-phone-npu': {'support': {'kind': 'npu', 'device_os': 'android'}}})
    assert on_device(private, ['acme-phone-npu'], 'android')


def test_an_instance_gets_the_overlay_of_the_target_that_asks_for_it(ctask):
    found = own_targets()
    compute = ctask['instance_compute']

    # as before these facts moved from the code to the targets: cuda and rocm in a container, cuda alone under WSL
    assert compute(found, 'cuda', 'docker') == 'cuda' and compute(found, 'rocm', 'podman') == 'rocm'
    assert compute(found, 'cuda', 'wsl') == 'cuda' and compute(found, 'rocm', 'wsl') == 'cpu'
    for other in ('cpu', 'vulkan', 'opencl', 'xpu', 'npu-intel', 'metal', '', None):
        assert compute(found, other, 'docker') == 'cpu', other

    # a list, or the text of a command line: the first target of the request that asks for an overlay
    assert compute(found, ['cpu', 'cuda'], 'docker') == 'cuda' and compute(found, 'vulkan, cuda', 'docker') == 'cuda'
    assert sorted(t for t in found if found[t].get('instance_overlay')) == ['cuda', 'rocm']

    # a private backend says the same in its own description
    private = dict(found, **{'acme-npu': {'instance_overlay': ['docker']}})
    assert compute(private, 'acme-npu', 'docker') == 'acme-npu' and compute(private, 'acme-npu', 'podman') == 'cpu'


def test_the_nvidia_toolkit_is_asked_for_by_the_overlays_run_flags():
    docker = load('task/get-host--docker/api_v1.py', cut = '\nclass CTask',
                  drop = ['from task_c36be4b9314a45e0.api.ctask import InitCTask, changed_mounts, write_signatures'])
    flags, asks = docker['overlay_run_flags'], docker['asks_nvidia_gpus']

    ubuntu = yaml.safe_load((ROOT / 'container' / 'ubuntu' / '_desc.yaml').read_text(encoding = 'utf-8'))
    cuda = ubuntu['compute']['cuda']
    assert asks(flags(cuda, 'docker')) and asks(flags(cuda, 'podman'))

    # whatever the overlay is called; an overlay that passes device files asks for no NVIDIA runtime
    assert asks(flags({'run_flags': ['--gpus=all']}, 'docker'))
    assert not asks(flags({'run_flags': ['--device=/dev/kfd', '--device=/dev/dri']}, 'docker'))
    assert not asks(flags(None, 'docker')) and flags({'run_flags': {'docker': ['-x']}}, 'podman') == []


def test_a_tools_backends_are_data_and_a_target_may_name_its_own():
    ctool = load('category/tool/api/ctool.py')
    desc = yaml.safe_load((ROOT / 'tool' / 'llama-cpp' / '_desc.yaml').read_text(encoding = 'utf-8'))

    # every target the tool lists is a target of the repository
    assert set(desc['target_backends']) <= set(own_targets())

    tool = ctool['InitCTool'].__new__(ctool['InitCTool'])
    tool.cdesc = desc
    tool.cm = Engine({'acme-npu': {'backends': {'llama-cpp': 'openvino', 'another-tool': 'x'}}, 'plain': {}})

    # the tool's own list, in its order; a listed target is not asked for
    table = tool.target_backends(['cpu', 'cuda'])
    assert list(table.items()) == list(desc['target_backends'].items()) and [r['arg1'] for r in tool.cm.asked] == ['target--cpu']

    # a target of another repository names its backend for this tool (by the tool's storage key)
    table = tool.target_backends(['acme-npu', 'plain', 'unknown'])
    assert table['acme-npu'] == 'openvino' and 'plain' not in table and 'unknown' not in table

    llama = load('tool/llama-cpp/api_v1.py', cut = '\nclass CTool', drop = ['from tool_c393ba5c6fa14f66.api.ctool import InitCTool'])
    assert llama['backend_from_compute'](['acme-npu'], 'linux', table) == 'openvino'
    assert llama['backends_of'](['acme-npu', 'npu-intel'], table) == ['openvino']
    assert llama['backends_of'](['acme-npu', 'cuda'], table) == ['openvino', 'cuda']


def test_shared_code_holds_no_list_of_target_names():
    """The places that named targets (2026-11-27): each asks the target artifacts now."""
    def text(relative):
        return (ROOT / relative).read_text(encoding = 'utf-8')

    assert "('cuda', 'rocm')" not in text('category/task/api/v2.py')
    assert "== 'cuda' else 'cpu'" not in text('category/task/api/v2.py')
    assert "compute == 'cuda'" not in text('task/get-host--docker/api_v1.py')
    for task in ('compile-and-run-program', 'setup-run'):
        assert "'android-cpu', 'android-gpu', 'android-npu'" not in text('task/%s/api_v1.py' % task), task
    assert 'TARGET_BACKENDS' not in text('tool/llama-cpp/api_v1.py')
