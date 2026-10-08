"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of program/build-pytorchvision: the vision checkout paired with the torch of the Python
(the release tag, main for a development torch, the requested one first) and the environment that ties
the build to that torch (BUILD_VERSION, PYTORCH_VERSION, FORCE_CUDA, the GPU architectures).
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, imports = {}, inject = {}):
    """The module's namespace, with its cMeta imports replaced and names injected."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.parent.name, "__file__": str(path)}
    ns.update(inject)
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def mod():
    return load("program/build-pytorchvision/api_v1.py",
                {"from program_22788f3c30d04e6d.api.cprogram import InitCProgram": "class InitCProgram: pass",
                 "from program_22788f3c30d04e6d.api import common_build": "common_build = None"})


@pytest.mark.parametrize("torch, release", [
    ("2.14.1", "0.29.1"), ("2.14.1+cu130", "0.29.1"), ("2.13.0+rocm10.1.0", "0.28.0"), ("2.7.1", "0.22.1"),
    ("1.13.1", "0.14.1"), ("2.14", "0.29.0"), ("3.0.0", None), ("", None), (None, None),
])
def test_release_pairing(mod, torch, release):
    assert mod["torchvision_release_for_torch"](torch) == release


def test_checkout_for_a_release_torch(mod):
    assert mod["torchvision_checkout_for"]("2.14.1") == ("v0.29.1", "torchvision 0.29.1 pairs with torch 2.14.1")
    assert mod["torchvision_checkout_for"]("2.14.1+cu130")[0] == "v0.29.1"
    assert mod["torchvision_checkout_for"]("2.13.0+rocm10.1.0")[0] == "v0.28.0"


def test_checkout_for_a_development_torch_is_main(mod):
    checkout, reason = mod["torchvision_checkout_for"]("2.15.0a0+git1234abc")
    assert checkout == "main" and "development" in reason
    assert mod["torchvision_checkout_for"]("2.15.0.dev20261001+cu130")[0] == "main"


def test_the_requested_checkout_wins(mod):
    assert mod["torchvision_checkout_for"]("2.14.1", "v0.28.0") == ("v0.28.0", "requested")
    assert mod["torchvision_checkout_for"]("2.15.0a0+git1", "release/0.30") == ("release/0.30", "requested")


def test_unknown_pair_is_main(mod):
    assert mod["torchvision_checkout_for"]("3.0.0")[0] == "main"


def test_pair_env(mod):
    env = mod["pair_env"]("v0.29.1", "2.14.1", ["cuda"], {"8.6", "7.5"})
    assert env == {"BUILD_VERSION": "0.29.1", "PYTORCH_VERSION": "2.14.1", "FORCE_CUDA": "1", "TORCH_CUDA_ARCH_LIST": "7.5;8.6"}
    # a ROCm torch: the GPU ops, no CUDA architectures, the torch version without its local tag
    assert mod["pair_env"]("v0.28.0", "2.13.0+rocm10.1.0", ["rocm"]) == {"BUILD_VERSION": "0.28.0", "PYTORCH_VERSION": "2.13.0", "FORCE_CUDA": "1"}
    # main with a development torch: no package version, no torch pin, CPU only
    assert mod["pair_env"]("main", "2.15.0a0+git1", ["cpu"]) == {"PYTORCH_VERSION": "2.15.0a0"}
    assert mod["pair_env"](None, None, ["cpu"]) == {}


def test_the_torch_probe_survives_the_shell(mod, monkeypatch):
    # python -c "<probe>": a double quote inside would end the argument (seen as NameError: name 'version')
    probe = mod["TORCH_PROBE"]
    assert '"' not in probe
    import contextlib, io, json, sys, types
    fake = types.ModuleType("torch")
    fake.__version__, fake.__file__ = "2.14.1", "x"
    fake.version = types.SimpleNamespace(cuda = "13.3")
    monkeypatch.setitem(sys.modules, "torch", fake)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(probe, {})
    assert json.loads(out.getvalue().strip()) == {"version": "2.14.1", "cuda": "13.3", "hip": None, "file": "x"}


def test_the_tool_mirrors_pytorch():
    """tool/pytorchvision: detected as torchvision in the Python, built by build-pytorchvision with the pairing passed on."""
    desc = yaml.safe_load((REPO_ROOT / "tool" / "pytorchvision" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert desc["storage_key"] == "pytorchvision" and desc["name"] == "torchvision"
    assert "import torchvision" in desc["cmd_get_version"]
    # found as the package's __init__.py under the Python's home (the generic search wants a file name), after the python step
    assert all(n.endswith("site-packages/torchvision/__init__.py") for n in desc["names"]) and len(desc["names"]) == 2
    # extra_paths is a dict by OS (linux also serves macOS; task/setup/detect.py)
    assert "{{global.python.path_home|}}" in desc["extra_paths"]["linux"] and "{{global.python.path_home|}}" in desc["extra_paths"]["windows"]
    assert any(u.get("name", "").startswith("python,") for u in desc["uses"])
    torch_desc = yaml.safe_load((REPO_ROOT / "tool" / "pytorch" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert all(n.endswith("site-packages/torch/__init__.py") for n in torch_desc["names"]) and len(torch_desc["names"]) == 2
    assert "{{global.python.path_home|}}" in torch_desc["extra_paths"]["linux"] and "{{global.python.path_home|}}" in torch_desc["extra_paths"]["windows"]
    assert any(u.get("name", "").startswith("python,") for u in torch_desc["uses"])
    assert torch_desc["default_version"] == "2.14.1"
    assert "pytorch/vision" in desc["cmd_get_versions"]
    build = desc["build_uses"]["all"][0]
    assert build["name"].startswith("build-pytorchvision,")
    assert build["checkout"] == "{{local.checkout|$None}}" and build["torch"] == "{{params.with.torch|$None}}"
    assert build["skip_run"] is True
    assert set(desc["cache_meta_const"]["params"]["with"]) == {"compute", "torch", "ver"}
    tool = load("tool/pytorchvision/api_v1.py", {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"})
    assert tool["site_packages_of"]("/v/lib/python3.14/site-packages/torchvision/__init__.py") == "/v/lib/python3.14/site-packages"
    assert tool["site_packages_of"]("/v/lib/libtorchvision.so") is None
    t = tool["CTool"].__new__(tool["CTool"])
    assert t.customize_build({}, {"version": "0.29.1"}) == {"return": 0, "add_to_local": {"checkout": "v0.29.1"}}
    assert t.customize_build({}, {}) == {"return": 0}
    # after the build the detection looks in the Python of the run, not in the entry's build folder
    ctx = {"tasks": {"global": {"python": {"path_home": "/v/.venv", "path_bin": "/v/.venv/bin"}}}}
    assert t.build(ctx, {}) == {"return": 0, "found_paths": ["/v/.venv", "/v/.venv/bin"]}
    assert t.build({"tasks": {"global": {}}}, {}) == {"return": 0, "found_paths": []}
    pytorch = load("tool/pytorch/api_v1.py", {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"})
    p = pytorch["CTool"].__new__(pytorch["CTool"])
    assert p.build(ctx, {}) == {"return": 0, "found_paths": ["/v/.venv", "/v/.venv/bin"]}


def test_the_description_pairs_before_the_clone():
    desc = yaml.safe_load((REPO_ROOT / "program" / "build-pytorchvision" / "_desc.yaml").read_text(encoding = "utf-8"))
    steps = desc["updates"]["compile"]["uses"][0]["append"]
    names = [s.get("internal_func") or s.get("name") or s.get("task") for s in steps]
    pair = names.index("customize_torch_pair")
    clone = next(i for i, s in enumerate(steps) if s.get("task", "").startswith("clone-git-to-cache"))
    assert pair < clone
    assert steps[clone]["checkout"] == "{{local.checkout|$None}}"
    # --torch=pip brings PyTorch's wheel before the pairing
    torch_step = next(s for s in steps if s.get("with", {}).get("package") == "torch")
    assert "pip" in torch_step["if"] and steps.index(torch_step) < pair
