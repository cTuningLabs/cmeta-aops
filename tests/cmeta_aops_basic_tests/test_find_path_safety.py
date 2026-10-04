"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The tool search never starts a recursive search ("**") from a filesystem root or a pseudo file system
(a distribution's /usr/bin/clang gave tool/llvm the home "/", and tool/lib-openmp's "<home>/**" walked
/proc for ever); tool/llvm takes the folders of the real binary behind a symlink; tool/lib-openmp
searches library folders, not a whole home.
"""

import importlib.util
import os
import pathlib
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def tool_api():
    path = REPO_ROOT / "category" / "tool" / "api" / "v1.py"
    spec = importlib.util.spec_from_file_location("cmeta_aops_tool_api_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_glob_pattern_is_safe(tool_api):
    safe = tool_api.glob_pattern_is_safe
    assert safe("/usr/lib/llvm-*/lib/libomp.so")                       # no recursion: always
    assert safe("/home/me/.linuxbrew/**/libomp.so")
    assert safe("/opt/homebrew/opt/**/libomp.dylib")
    assert safe("C:\\Program Files\\LLVM\\**\\libomp.dll")
    assert safe("/usr/lib/llvm-14/**/libomp.so")
    for pattern in ["//**/libomp.so", "/**/libomp.so", "/**", "C:\\**\\x.dll", "C:/**/x.dll",
                    "/proc/**/x", "/sys/**/x", "/dev/**/x", "/run/**/x", "/*/**/libomp.so"]:
        assert not safe(pattern), pattern


def test_lib_openmp_searches_library_folders_only():
    desc = yaml.safe_load((REPO_ROOT / "tool" / "lib-openmp" / "_desc.yaml").read_text(encoding = "utf-8"))
    for os_name, paths in desc["extra_paths"].items():
        for p in paths:
            assert not ("{{" in p and p.rstrip("/\\").endswith("**")), f"{os_name}: {p} recurses under a templated home"


@pytest.mark.skipif(os.name == "nt", reason = "symlinks need privileges on Windows")
def test_llvm_home_follows_symlinks(tmp_path):
    """/usr/bin/clang -> /usr/lib/llvm-14/bin/clang: the home is /usr/lib/llvm-14, not /."""
    path = REPO_ROOT / "tool" / "llvm" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": "tool_llvm", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    real = tmp_path / "usr" / "lib" / "llvm-14" / "bin"
    real.mkdir(parents = True)
    (real / "clang").write_text("")
    link_dir = tmp_path / "usr" / "bin"
    link_dir.mkdir()
    os.symlink(real / "clang", link_dir / "clang")

    import types
    tool = object.__new__(ns["CTool"])
    tool.cm = types.SimpleNamespace(q = lambda s: f'"{s}"', debug = False)
    r = tool.check_features({"control": {}, "tasks": {"global": {"host": {"os": {"uname": "linux"}}}}},
                            [{"path": str(link_dir / "clang"), "output": "clang version 14.0.6"}], {})
    assert r["return"] == 0
    paths = r["paths"][0]["features"]["paths"]
    assert paths["bin"] == str(real) and paths["home"] == str(tmp_path / "usr" / "lib" / "llvm-14")
