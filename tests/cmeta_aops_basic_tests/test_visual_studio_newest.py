"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/microsoft.visual-studio with two installations cached: a request that names no exact version
(clang's dependency msvc asks for none; nvcc asks for a range) takes the newest installation instead of
asking "More than 1 cache entry found" - the answer -q gave anyway. An exact version, a vcvars script
(tool_path) or a path keep the engine's own matching. Offline: the hook is called with fake entries.
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def vs_module():
    path = REPO_ROOT / "tool" / "microsoft.visual-studio" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": "tool_visual_studio", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def entry(version, drive = "C", sdk = "10.0.26100.0"):
    year = "18" if version.startswith("19.5") else "2022"
    return {"path": f"{drive}:/cache/vs-{version}-{sdk}",
            "cmeta": {"params": {"name": "microsoft.visual-studio", "version": version,
                                 "tool_path": f"{drive}:\\Program Files\\Microsoft Visual Studio\\{year}\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat",
                                 "use": {"microsoft-sdk": {"version": sdk}}}}}


VS2022 = entry("19.44.35211")
VS2026 = entry("19.50.35726", "D")
VS2026_OTHER_SDK = entry("19.50.35726", "D", "10.0.22621.0")
VS2019 = entry("19.29.30154")


def hook(ns, artifacts, params, tmp = None, ctx = None, **extra):
    tool = object.__new__(ns["CTool"])
    return tool.filter_tool_cache_artifacts(ctx if ctx is not None else {"control": {"con": False}},
                                            artifacts, tmp if tmp is not None else [], params, **extra)


def test_helpers():
    ns = vs_module()
    assert ns["version_numbers"]("19.50.35726") == (19, 50, 35726) and ns["version_numbers"]("19.9") < ns["version_numbers"]("19.50")
    assert ns["version_numbers"]("==19.44") == (19, 44) and ns["version_numbers"]("") == (0,)
    assert ns["is_exact_version"]("19.44") and ns["is_exact_version"]("19.44.35211") and ns["is_exact_version"]("==19.44")
    assert not ns["is_exact_version"]("<19.50") and not ns["is_exact_version"](">=19.10,<19.50") and not ns["is_exact_version"](None)
    assert ns["describe"]("19.50.35726") == "19.50.35726 (2026)" and ns["describe"]("19.44.35211") == "19.44.35211 (2022)"
    assert ns["version_of"](VS2022) == "19.44.35211" and ns["version_of"]({"cmeta": {}}) == ""


def test_no_version_takes_the_newest_installation():
    ns = vs_module()
    r = hook(ns, [VS2022, VS2026, VS2019], {"name": "microsoft.visual-studio"})
    assert r == {"return": 0, "artifacts": [VS2026]}
    # the version compares as numbers: 19.9 would be older than 19.50
    old = entry("19.9.1")
    assert hook(ns, [old, VS2026], {"name": "microsoft.visual-studio"})["artifacts"] == [VS2026]


def test_entries_of_the_newest_version_all_stay():
    ns = vs_module()
    r = hook(ns, [VS2022, VS2026, VS2026_OTHER_SDK], {"name": "microsoft.visual-studio", "version": None})
    assert r["artifacts"] == [VS2026, VS2026_OTHER_SDK]        # one per Windows SDK: the engine's choice


def test_a_range_takes_the_newest_within_it():
    """nvcc's host-compiler limits reach the tool as a range; the engine matched the entries to it already."""
    ns = vs_module()
    r = hook(ns, [VS2022, VS2019], {"name": "microsoft.visual-studio", "version": "<19.50"})
    assert r == {"return": 0, "artifacts": [VS2022]}


def test_explicit_version_script_or_path_keep_the_engine_matching():
    ns = vs_module()
    for params, extra in [({"version": "19.44.35211"}, {}), ({"version": "==19.44"}, {}),
                          ({"tool_path": VS2022["cmeta"]["params"]["tool_path"]}, {}), ({}, {"path": "D:/somewhere"})]:
        assert hook(ns, [VS2022, VS2026], dict(name = "microsoft.visual-studio", **params), **extra) == {"return": 0}


def test_nothing_to_choose_keeps_the_lists():
    ns = vs_module()
    assert hook(ns, [VS2026], {"name": "microsoft.visual-studio"}) == {"return": 0}
    assert hook(ns, [], {"name": "microsoft.visual-studio"}, tmp = [VS2022]) == {"return": 0}
    assert hook(ns, [VS2026, VS2026_OTHER_SDK], {"name": "microsoft.visual-studio"}) == {"return": 0}


def test_tmp_entries_are_left_to_the_engine():
    ns = vs_module()
    r = hook(ns, [VS2022, VS2026], {"name": "microsoft.visual-studio"}, tmp = [VS2019])
    assert r == {"return": 0, "artifacts": [VS2026]} and "tmp_artifacts" not in r


def test_info_line_names_the_choice_and_the_option(capsys):
    ns = vs_module()
    hook(ns, [VS2022, VS2026, VS2019], {"name": "microsoft.visual-studio"}, ctx = {"control": {"con": True}})
    out = capsys.readouterr().out
    assert "INFO: 3 cached Visual Studio installations: taking cl.exe 19.50.35726 (2026)" in out
    assert "19.44.35211 (2022), 19.29.30154 (2019) also would" in out
    assert "--use.microsoft-visual-studio.version=<version> picks another" in out
    hook(ns, [VS2022, VS2019], {"name": "microsoft.visual-studio", "version": "<19.50"}, ctx = {"control": {"con": True}})
    assert "installations within <19.50: taking cl.exe 19.44.35211 (2022)" in capsys.readouterr().out
    hook(ns, [VS2022, VS2026], {"name": "microsoft.visual-studio"}, ctx = {"control": {"con": False}})
    assert capsys.readouterr().out == ""


def test_setup_calls_the_hook_and_msvc_passes_its_version():
    """task/setup asks the tool's filter_tool_cache_artifacts; tool/msvc hands its version to the installation."""
    setup = (REPO_ROOT / "task" / "setup" / "api_v1.py").read_text(encoding = "utf-8")
    assert "'filter_tool_cache_artifacts'" in setup
    msvc = (REPO_ROOT / "tool" / "msvc" / "_desc.yaml").read_text(encoding = "utf-8")
    assert "name: microsoft.visual-studio,b30299aeb2bd4c6e" in msvc and 'version: "{{params.version|$None}}"' in msvc
