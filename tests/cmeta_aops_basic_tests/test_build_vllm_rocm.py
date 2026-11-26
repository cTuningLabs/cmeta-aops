"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the ROCm build of program/build-vllm (2026-11-26, the way that built vLLM 0.34.0 on an MI300X): it
starts from vLLM's own ROCm wheel of the release (its torch, triton and aiter for one ROCm), adds the development files
of that ROCm, and installs vLLM's build requirements of AMD's distribution without what the wheel brought.
"""

import os
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def mod():
    path = REPO_ROOT / "program" / "build-vllm" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    for line, replacement in {"from program_22788f3c30d04e6d.api.cprogram import InitCProgram": "class InitCProgram: pass",
                              "from program_22788f3c30d04e6d.api.common_build import default_max_jobs": "default_max_jobs = None"}.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": "build_vllm_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.mark.parametrize("checkout, release", [
    ("v0.34.0", "0.34.0"), ("v0.10.1.post1", "0.10.1.post1"), (" v0.30.0 ", "0.30.0"),
    ("main", None), ("8adadd7b", None), ("0.34.0", None), ("", None), (None, None)])
def test_the_release_of_a_checkout(mod, checkout, release):
    assert mod["release_of_checkout"](checkout) == release


def test_the_package_a_line_names(mod):
    name = mod["package_name"]
    assert name("Jinja2>=3.1.6") == "jinja2"
    assert name("setuptools_scm>=8") == "setuptools-scm"
    assert name("torch==2.12.0+rocm7.14.0") == "torch"
    assert name("cmake>=3.26.1,<4  # a remark") == "cmake"
    assert name("# Common dependencies") is None
    assert name("-r ../common.txt") is None
    assert name("--extra-index-url https://repo.amd.com/rocm/whl-multi-arch/") is None
    assert name("") is None


def test_the_build_requirements_over_the_wheel(mod, tmp_path):
    # vLLM 0.34.0's requirements/build/rock.txt, shortened
    rock = ["# Common dependencies", "-r ../common.txt", "--extra-index-url https://repo.amd.com/rocm/whl-multi-arch/",
            "torch==2.12.0+rocm7.14.0", "torchvision==0.27.0+rocm7.14.0", "triton==3.7.1+git0263a6a6.rocm7.14.0",
            "cmake>=3.26.1,<4", "setuptools>=78.1.1,<80.0.0", "setuptools-scm>=8", "wheel", "jinja2>=3.1.6",
            "amdsmi==7.0.2"]
    base = str(tmp_path / "requirements" / "build")
    # what vLLM's ROCm wheel brought into the venv: its torch stack, amdsmi, setuptools
    installed = {"torch", "torchvision", "triton", "amdsmi", "setuptools"}
    out = mod["requirements_over_wheel"](rock, installed, base)
    assert out == ["-r " + os.path.normpath(os.path.join(base, "../common.txt")),
                   "cmake>=3.26.1,<4", "setuptools-scm>=8", "wheel", "jinja2>=3.1.6"]


def test_the_description_builds_rocm_over_the_wheel():
    with open(REPO_ROOT / "program" / "build-vllm" / "_desc.yaml", encoding = "utf-8") as f:
        desc = yaml.safe_load(f)
    steps = desc["updates"]["compile"]["uses"][0]["append"]
    rocm = '"rocm" in {{global.target.compute|$[]}}'

    # the Python of vLLM's ROCm wheels (3.12), the others' range elsewhere
    pythons = [s for s in steps if str(s.get("name", "")).startswith("python,")]
    assert any(s.get("if") == rocm and "3.12" in s["version"] for s in pythons)
    assert any(s.get("if") == '"rocm" not in {{global.target.compute|$[]}}' for s in pythons)

    # the wheel of the release, then the ROCm development files over it - before the build
    # (a pip-* tool is set up as "setup pip" with its package: setup refuses "setup pip-vllm")
    names = [(s.get("with") or {}).get("package") or s.get("name") or s.get("internal_func") or s.get("storage_key") for s in steps]
    wheel = names.index("vllm")
    assert steps[wheel]["name"] == "pip"
    assert steps[wheel]["if"] == rocm and steps[wheel]["version"] == "{{local.vllm_release}}"
    over = names.index("customize_vllm_rocm")
    assert steps[over]["if"] == rocm
    assert names.index("customize_vllm") < wheel < over < names.index("compile-program")
