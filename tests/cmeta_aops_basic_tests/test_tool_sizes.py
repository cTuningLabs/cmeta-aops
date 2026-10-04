"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the disk-size rules of tools (category/tool/api/common_sizes.py, a tool's
_desc_sizes.yaml) and of their use by task/setup: the rule chosen for a request (fuzzy versions, os,
arch, method, with keys, first match, a rule without "if"), the free-space check (a quiet run stops
before installing, an interactive run warns and asks, --skip_size_check, the configured minimum
min_free_gb), the size a finished install records, and the "--sizes" report with its suggestions.
Nothing is downloaded: the fake tool's install writes a file.
"""

import json
import os
import pathlib
import textwrap

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GB = 1024 ** 3


@pytest.fixture(scope = "module")
def sizes():
    path = REPO_ROOT / "category" / "tool" / "api" / "common_sizes.py"
    ns = {"__name__": "common_sizes", "__file__": str(path)}
    exec(compile(path.read_text(encoding = "utf-8"), str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def matchers():
    from cmeta import CMeta
    cm = CMeta()
    return cm.utils.common.matches_query, cm.repos.match_version_func


RULES = yaml.safe_load(textwrap.dedent("""
    sizes:
      - if: {method: install, os: linux, version: '>=22'}
        peak: 15
        kept: 12
      - if: {method: install, os: linux}
        peak: 12
      - if: {method: build, with: {static: true}}
        peak: 80
      - if: {method: build}
        peak: 60
      - if: {compute: cuda}
        peak: 9
      - peak: 4
"""))["sizes"]


def select(sizes, matchers, **facts):
    f = sizes["request_facts"](version = facts.get("version"), os_name = facts.get("os"), arch = facts.get("arch"),
                               method = facts.get("method"), compute = facts.get("compute"), with_ = facts.get("with_"))
    return sizes["select_rule"](RULES, f, matchers[0], match_version_func = matchers[1])


def test_select_rule(sizes, matchers):
    assert select(sizes, matchers, version = "22.1.7", os = "linux", method = "install")["peak"] == 15
    assert select(sizes, matchers, version = "21.1.0", os = "linux", method = "install")["peak"] == 12
    assert select(sizes, matchers, version = "22.1.7", os = "windows", method = "install")["peak"] == 4   # no linux rule
    assert select(sizes, matchers, os = "linux", method = "install")["peak"] == 12                       # no version: skips '>=22'
    assert select(sizes, matchers, method = "build", with_ = {"static": True})["peak"] == 80
    assert select(sizes, matchers, method = "build", with_ = {"static": False})["peak"] == 60
    assert select(sizes, matchers, method = "install", compute = ["cpu", "cuda"])["peak"] == 9           # scalar in a list
    assert select(sizes, matchers, method = "install", compute = "cuda")["peak"] == 9
    assert select(sizes, matchers, method = "install", os = "darwin")["peak"] == 4                      # the default rule
    assert sizes["select_rule"]([], {"method": "install"}, matchers[0]) is None


def test_load_sizes(sizes, tmp_path):
    assert sizes["load_sizes"](str(tmp_path)) == []
    (tmp_path / "_desc_sizes.yaml").write_text("sizes:\n  - peak: 2\n", encoding = "utf-8")
    assert sizes["load_sizes"](str(tmp_path)) == [{"peak": 2}]
    assert sizes["load_sizes"](str(REPO_ROOT / "tool" / "llvm"))[0]["if"]["method"] == "install"


def test_check_space_and_message(sizes, tmp_path):
    check = sizes["check_space"]
    assert check(None, str(tmp_path)) == (True, None, None)                      # no rule, no floor
    assert check(10, str(tmp_path), free = 50) == (True, 50, 10)
    assert check(10, str(tmp_path), free = 6.5) == (False, 6.5, 10)
    assert check(None, str(tmp_path), floor_gb = 5, free = 2) == (False, 2, 5)   # the floor alone
    assert check(3, str(tmp_path), floor_gb = 5, free = 4) == (False, 4, 5)      # the larger of the two
    assert sizes["free_gb"](str(tmp_path / "not" / "yet" / "made")) > 0            # the nearest existing parent
    m = sizes["shortage_message"]("LLVM", "22.1.7", "install", "linux", 13, 6.5, "/home/x/CMETA", True)
    assert m.startswith("LLVM 22.1.7 (install, linux) needs about 13 GB during the setup; 6.5 GB are free in /home/x/CMETA.")
    assert "--skip_size_check" in m and "--path=" in m
    assert "configured minimum" in sizes["shortage_message"]("x", None, "build", "windows", 5, 1, "D:/c", False)


def test_folder_gb_and_rounding(sizes, tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 1000)
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b").write_bytes(b"y" * 24)
    assert abs(sizes["folder_gb"](str(tmp_path)) - 1024 / GB) < 1e-12
    assert sizes["round_up_gb"](0.3) == 0.4 and sizes["round_up_gb"](4.1) == 5.0 and sizes["round_up_gb"](11.6) == 14
    assert sizes["round_up_gb"](10, margin = 0) == 10


def test_records_and_suggestions(sizes, tmp_path):
    def entry(name, version, kept, peak = None, method = "install", os_name = "linux", arch = "amd64"):
        e = tmp_path / name
        e.mkdir()
        (e / "_cmeta.json").write_text(json.dumps({"params": {"name": "llvm", "version": version, "with": {}}}))
        impact = {"self_time": 1, "disk_gb": kept, "disk_method": method, "disk_os": os_name, "disk_arch": arch}
        if peak:
            impact["peak_gb"] = peak
        (e / "cmeta-task-cached-result.json").write_text(json.dumps({"return": 0, "_impact": impact}))
        return str(e)
    entries = [entry("e1", "22.1.7", 11.3, 12.9), entry("e2", "21.1.0", 9.0), entry("e3", "22.1.1", 3.1, method = "install", os_name = "windows")]
    e4 = tmp_path / "e4"                                   # a detected tool: no size recorded
    e4.mkdir()
    (e4 / "_cmeta.json").write_text(json.dumps({"params": {"name": "llvm", "version": "20.0.0"}}))
    (e4 / "cmeta-task-cached-result.json").write_text(json.dumps({"return": 0, "_impact": {"self_time": 1}}))
    records = sizes["records_from_cache"](entries + [str(e4)])
    assert [r["entry"] for r in records] == ["e1", "e2", "e3"]
    rules = sizes["suggest_rules"](records)
    assert rules[0] == {"if": {"method": "install", "os": "linux", "arch": "amd64", "version": ">=22,<23"}, "peak": 16, "kept": 14}
    assert rules[1]["if"]["version"] == ">=21,<22" and rules[1]["peak"] == 11 and rules[1]["kept"] == 11
    assert rules[-1] == {"peak": 16}                        # the default rule: the largest peak
    text = sizes["rules_to_yaml"](rules)
    assert yaml.safe_load(text)["sizes"] == [
        {"if": {"method": "install", "os": "linux", "arch": "amd64", "version": ">=22,<23"}, "peak": 16, "kept": 14},
        {"if": {"method": "install", "os": "linux", "arch": "amd64", "version": ">=21,<22"}, "peak": 11, "kept": 11},
        {"if": {"method": "install", "os": "windows", "arch": "amd64", "version": ">=22,<23"}, "peak": 4, "kept": 4},
        {"peak": 16}]


# Through task/setup, with a fake tool whose install writes a file (no download)

FAKE = "zz-sizes-fake"


@pytest.fixture(scope = "module")
def fake_tool(cm):
    """A tool in the temporary CMETA_HOME's local repo: a custom install that writes a file (no download),
    and a _desc_sizes.yaml whose install rule needs far more space than any disk has."""
    r = cm.access({"category": "tool", "command": "add", "arg1": f"local:{FAKE}", "con": False, "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")
    tool = pathlib.Path(r["path"])
    (tool / "_desc.yaml").write_text(textwrap.dedent(f"""
        skip_detect: True
        skip_common_install_uses: True
        names: ['{FAKE}']
        match_version:
          - regex: '([0-9.]+)'
            group: 1
        cmd_get_version: 'echo 1.0'
        """), encoding = "utf-8")
    (tool / "api_v1.py").write_text(textwrap.dedent("""
        import os
        from tool_c393ba5c6fa14f66.api.ctool import InitCTool

        class CTool(InitCTool):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, module_file_path = __file__, **kwargs)

            def install(self, ctx, params, cmd = None, *misc):
                os.makedirs('content', exist_ok = True)
                path = os.path.join(os.getcwd(), 'content', 'zz-sizes-fake')
                with open(path, 'wb') as f:
                    f.write(b'0' * 4096)
                return {'return': 0, 'install_cmd': None, 'found_path': path, 'peak_gb': 0.001}
        """), encoding = "utf-8")
    (tool / "_desc_sizes.yaml").write_text(SIZES_FAKE, encoding = "utf-8")
    return tool


SIZES_FAKE = "sizes:\n  - if: {method: install}\n    peak: 100000\n  - peak: 1\n"


def setup(cm, **params):
    p = {"category": "task", "command": "run", "arg1": "setup", "name": FAKE, "con": False, "quiet": True}
    p.update(params)
    return cm.access(p)


def test_quiet_run_stops_before_installing(cm, fake_tool):
    r = setup(cm)
    assert r["return"] > 0
    assert "needs about 100000 GB during the setup" in r["error"] and "--skip_size_check" in r["error"]
    assert not list((pathlib.Path(os.environ["CMETA_HOME"]) / "repos" / "local" / "cache").glob(f"task--setup--{FAKE}--*/content"))


def test_interactive_run_asks(cm, fake_tool, monkeypatch, capsys):
    answers = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda prompt = "": next(answers))
    r = setup(cm, con = True, quiet = False)
    assert r["return"] > 0 and "cancelled" in r["error"]
    assert "WARNING:" in capsys.readouterr().out


def test_skip_check_installs_and_records_the_size(cm, fake_tool):
    r = setup(cm, skip_size_check = True)
    assert r["return"] == 0, r.get("error")
    impact = r["_impact"]
    assert impact["disk_method"] == "install" and impact["disk_os"] and impact["disk_gb"] > 0
    assert impact["peak_gb"] >= impact["disk_gb"]
    # the cache entry's result carries it, and the next plain request reuses the entry without a check
    cache = pathlib.Path(os.environ["CMETA_HOME"]) / "repos" / "local" / "cache"
    results = list(cache.glob(f"task--setup--{FAKE}--*/cmeta-task-cached-result.json"))
    assert results and json.loads(results[0].read_text())["_impact"]["disk_gb"] == impact["disk_gb"]
    assert setup(cm)["return"] == 0


def test_sizes_report(cm, fake_tool, capsys):
    assert setup(cm, skip_size_check = True)["return"] == 0      # one installed entry with its record
    r = setup(cm, sizes = True, con = True)
    assert r["return"] == 0, r.get("error")
    assert len(r["records"]) == 1 and r["records"][0]["method"] == "install"
    assert len(r["rules"]) == 2 and r["suggested"][-1] == {"peak": r["suggested"][0]["peak"]}
    out = capsys.readouterr().out
    assert "Suggested _desc_sizes.yaml" in out and "sizes:" in out


def test_floor_from_config(cm, fake_tool):
    """cx config set task --meta.min_free_gb=<GB>: every install checks for that much free space."""
    r = cm.access({"category": "config", "command": "set", "arg1": "task", "meta": {"min_free_gb": 100000}})
    assert r["return"] == 0, r.get("error")
    try:
        (fake_tool / "_desc_sizes.yaml").unlink()
        r = setup(cm, update = True)
        assert r["return"] > 0 and "configured minimum" in r["error"]
    finally:
        cm.access({"category": "config", "command": "set", "arg1": "task", "meta": {"min_free_gb": None}})
        (fake_tool / "_desc_sizes.yaml").write_text("sizes:\n  - if: {method: install}\n    peak: 100000\n  - peak: 1\n", encoding = "utf-8")
