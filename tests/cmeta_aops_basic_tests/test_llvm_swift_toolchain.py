"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/llvm ranks a Swift toolchain's clang (swift.org's LLVM fork: no OpenMP headers or runtime) after
every other clang the detection finds, whatever its version; alone, it is still taken. tool/clang and
tool/clang-cpp follow tool/llvm's choice (only_paths = the LLVM's bin folder).
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def llvm():
    path = REPO_ROOT / "tool" / "llvm" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": "tool_llvm", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


SWIFT_OUTPUT = "clang version 21.0.0 (https://github.com/swiftlang/llvm-project.git 903b9faaae5c)\nTarget: x86_64-unknown-linux-gnu"
LLVM_OUTPUT = "clang version 22.1.7\nTarget: x86_64-unknown-linux-gnu\nThread model: posix"
APPLE_OUTPUT = "Apple clang version 21.0.0 (clang-2100.0.0.0)\nTarget: arm64-apple-darwin27.0.0"


def test_is_swift_toolchain(llvm):
    f = llvm["is_swift_toolchain"]
    assert f("/home/u/.local/share/swiftly/bin/clang", SWIFT_OUTPUT)
    assert f("/home/u/.local/share/swiftly/bin/clang", "")                             # by the path alone
    assert f("C:\\Users\\u\\AppData\\Local\\Programs\\Swift\\Toolchains\\6.3.1+Asserts\\usr\\bin\\clang.exe", "")
    assert f("/Library/Developer/Toolchains/swift-6.2-RELEASE.xctoolchain/usr/bin/clang", "")
    assert f("/opt/llvm/bin/clang", SWIFT_OUTPUT)                                       # by the output alone
    assert not f("/usr/bin/clang", APPLE_OUTPUT)
    assert not f("/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang", APPLE_OUTPUT)
    assert not f("/usr/lib/llvm-18/bin/clang", "Ubuntu clang version 18.1.3 (1ubuntu1)")
    assert not f("C:\\Program Files\\LLVM\\bin\\clang.exe", LLVM_OUTPUT)


def candidate(path, version, swift = False):
    c = {"path": path, "detected_version": version, "path_len": len(path), "features": {}}
    if swift:
        c["features"]["swift_toolchain"] = True
    return c


def sort_key(a):
    """The detection's order among equals: version descending (numeric), then shorter path, then path."""
    v = tuple(-int(x) for x in a["detected_version"].split("."))
    return (v, a["path_len"], a["path"])


def swift(version = "21.0.0"):
    return candidate("/home/u/.local/share/swiftly/bin/clang", version, swift = True)


def llvm22():
    return candidate("/home/u/CMETA/repos/local/cache/task--setup--llvm--x/content/bin/clang", "22.1.7")


def distro():
    return candidate("/usr/lib/llvm-18/bin/clang", "18.1.3")


def test_rank_swift_last(llvm):
    rank = llvm["rank_swift_last"]

    # Others first, in the detection's order (version), marked as priority for the detection's sort;
    # a Swift clang newer than all of them still comes last
    ranked, only_swift = rank([swift("99.0.0"), distro(), llvm22()], sort_key)
    assert [c["detected_version"] for c in ranked] == ["22.1.7", "18.1.3", "99.0.0"]
    assert ranked[0]["priority"] and ranked[1]["priority"] and "priority" not in ranked[2]
    assert not only_swift

    # Only a Swift clang: taken, flagged, no priority mark
    s = swift()
    ranked, only_swift = rank([s], sort_key)
    assert ranked == [s] and only_swift and "priority" not in s

    # No Swift clang: untouched (no priority marks, the detection sorts by version itself)
    d, l = distro(), llvm22()
    ranked, only_swift = rank([d, l], sort_key)
    assert ranked == [d, l] and not only_swift and not any("priority" in c for c in ranked)

    # Nothing to rank
    assert rank([], sort_key) == ([], False)


def test_desc_searches_distro_llvm_folders():
    desc = yaml.safe_load((REPO_ROOT / "tool" / "llvm" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert "/usr/lib/llvm-*/bin" in desc["extra_paths"]["linux"]


def test_clang_tools_follow_llvm():
    clang = yaml.safe_load((REPO_ROOT / "tool" / "clang" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert clang["only_paths"]["all"] == ["{{global.llvm.path_bin}}"]
    src = (REPO_ROOT / "tool" / "clang-cpp" / "api_v1.py").read_text(encoding = "utf-8")
    assert "ctx['tasks']['global']['clang']['path']" in src
