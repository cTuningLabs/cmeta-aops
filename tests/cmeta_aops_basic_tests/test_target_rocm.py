"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/target--rocm: the GPU family names from the kernel's gfx_target_version, the
families read from a fake kfd topology, and the gfx override exported to the run only on request.
"""

import pathlib
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def mod():
    path = REPO_ROOT / "task" / "target--rocm" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                      "class InitCTask:\n    def __init__(self, *args, **kwargs):\n        pass")
    ns = {"__name__": "target_rocm", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.mark.parametrize("version, name", [
    ("110502", "gfx1152"),      # Radeon 860M (Krackan Point)
    ("90400", "gfx940"),        # MI300A; the MI300X is 9.4.2
    ("90402", "gfx942"),
    ("90a00", None),            # not a number: never written by the kernel
    ("100300", "gfx1030"),
    ("110000", "gfx1100"),
    ("120000", "gfx1200"),
    ("90a", None),
])
def test_gfx_names(mod, version, name):
    if name is None:
        with pytest.raises(ValueError):
            mod["gfx_name"](version)
    else:
        assert mod["gfx_name"](version) == name


def test_gfx_from_a_kfd_topology(mod, tmp_path):
    nodes = tmp_path / "nodes"
    (nodes / "0").mkdir(parents = True)
    (nodes / "0" / "properties").write_text("cpu_cores_count 16\nsimd_count 0\ngfx_target_version 0\n")
    (nodes / "1").mkdir()
    (nodes / "1" / "properties").write_text("cpu_cores_count 0\nsimd_count 16\ngfx_target_version 110502\n")
    (nodes / "2").mkdir()
    (nodes / "2" / "properties").write_text("cpu_cores_count 0\nsimd_count 1216\ngfx_target_version 90402\n")
    assert mod["gfx_from_kfd"](str(nodes)) == ["gfx1152", "gfx942"]
    assert mod["gfx_from_kfd"](str(tmp_path / "missing")) == []


def finish(mod, params, monkeypatch, gfx = None):
    monkeypatch.setitem(mod, "gfx_from_kfd", lambda *a, **k: gfx or [])
    t = mod["CTask"]()
    ctx = {'control': {}, 'tasks': {'global': {'rocm': {'features': {'devices': [{'name': 'AMD Radeon 860M Graphics'}]}}}}}
    r = t.finish_dynamic_result(ctx, {'return': 0, 'features': {}}, params)
    assert r['return'] == 0
    return r['result']


def test_the_devices_get_their_family(mod, monkeypatch):
    result = finish(mod, {}, monkeypatch, gfx = ['gfx1152'])
    assert result['features']['gfx'] == ['gfx1152']
    assert result['features']['devices'][0]['gfx'] == 'gfx1152'
    assert '_aggregate' not in result                         # no override by itself


def test_the_override_only_on_request(mod, monkeypatch):
    result = finish(mod, {'gfx_override': '11.5.0'}, monkeypatch)
    assert result['_aggregate'] == {'env': {'HSA_OVERRIDE_GFX_VERSION': '11.5.0'}}
    assert result['features']['gfx_override'] == '11.5.0'
    result = finish(mod, {'gfx_override': 'none'}, monkeypatch)
    assert '_aggregate' not in result
    result = finish(mod, {'with': {'gfx_override': '11.0.0'}}, monkeypatch)
    assert result['_aggregate']['env']['HSA_OVERRIDE_GFX_VERSION'] == '11.0.0'
