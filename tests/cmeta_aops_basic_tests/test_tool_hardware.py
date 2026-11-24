"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the hardware a tool declares (its "hardware" rules, docs/cmeta-aops/tool-hardware.md): which rules
count for a version, what task::target--cpu's inventory says is missing or cannot tell, the processor's name in the
message, flm's rule, and explore-tool-versions' class "not supported here" - neither a limit of "latest" nor a broken
version.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, stubs):
    """A module of the repository with its cMeta imports replaced: stubs are (line, replacement) pairs."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, new in stubs:
        assert line in src, line
        src = src.replace(line, new)
    ns = {"__name__": "under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def install():
    return load("task/setup/install.py", [("from task_c36be4b9314a45e0.api.ctask import ask", "ask = None"),
                                          ("from . import upgrade", "upgrade = None")])


def numeric(v):
    return tuple(int(x) for x in v.split("."))


def at_least(version, spec):
    """A stand-in for the engine's fuzzy version match, for the ">=" rules of these tests."""
    assert spec.startswith(">=")
    return numeric(version) >= numeric(spec[2:])


def inventory(platform, raw, **normalized):
    norm = {"sse2": False, "avx2": False, "avx512f": False}
    norm.update(normalized)
    return {"platform": platform, "features_raw": raw, "features_normalized": norm}


FLM = [{"versions": ">=1.0.13", "cpu_features": ["avx512f"], "why": "AVX-512"}]
LINUX_NO_AVX512 = inventory("linux", ["sse2", "avx2", "fma"], sse2 = True, avx2 = True)
LINUX_AVX512 = inventory("linux", ["sse2", "avx2", "avx512f", "avx512bw"], sse2 = True, avx2 = True, avx512f = True)


def test_a_rule_counts_for_the_versions_it_names(install):
    verdict = install["hardware_verdict"]
    missing, unknown = verdict(FLM, "1.0.13", LINUX_NO_AVX512, at_least)
    assert [f for f, _ in missing] == ["avx512f"] and unknown == []

    # an older version, a machine that has it, an unknown version: nothing refused
    assert verdict(FLM, "1.0.7", LINUX_NO_AVX512, at_least) == ([], [])
    assert verdict(FLM, "1.0.13", LINUX_AVX512, at_least) == ([], [])
    assert verdict(FLM, None, LINUX_NO_AVX512, at_least) == ([], [])

    # a rule without versions counts for every version; one rule as a dict; no rules
    rule = {"cpu_features": ["AVX512F"]}
    assert [f for f, _ in verdict(rule, None, LINUX_NO_AVX512, at_least)[0]] == ["avx512f"]
    assert verdict([], "1.0.13", LINUX_NO_AVX512, at_least) == ([], [])


def test_what_the_inventory_cannot_tell_is_never_refused(install):
    verdict = install["hardware_verdict"]

    # no flags read at all (a container without /proc/cpuinfo, an unknown system): unknown, not missing
    missing, unknown = verdict(FLM, "1.0.13", inventory("linux", []), at_least)
    assert missing == [] and [f for f, _ in unknown] == ["avx512f"]
    assert verdict(FLM, "1.0.13", {}, at_least)[0] == []

    # a name outside the normalized set: Linux and macOS list every flag, Windows answers for its own names only
    rule = [{"cpu_features": ["avx512bw"]}]
    assert verdict(rule, None, LINUX_AVX512, at_least) == ([], [])
    assert [f for f, _ in verdict(rule, None, LINUX_NO_AVX512, at_least)[0]] == ["avx512bw"]
    windows = inventory("windows", ["sse2", "avx2"], sse2 = True, avx2 = True)
    assert verdict(rule, None, windows, at_least)[0] == [] and verdict(rule, None, windows, at_least)[1]

    # a normalized name Windows answers for: its answer counts
    assert [f for f, _ in verdict(FLM, "1.0.13", windows, at_least)[0]] == ["avx512f"]


def test_the_processor_is_named_in_the_message(install):
    name = install["processor_name"]
    assert name({"packages": [{"Name": "Intel(R) Core(TM) Ultra 9 386H"}]}) == "Intel(R) Core(TM) Ultra 9 386H"
    assert name({"cpu_signature": {"model_name": "Intel(R) Core(TM) i7-7700HQ CPU @ 2.80GHz"}}) == \
        "Intel(R) Core(TM) i7-7700HQ CPU @ 2.80GHz"
    assert name({"extended_identifier": "Intel64 Family 6 Model 204"}) == "Intel64 Family 6 Model 204"
    assert name({}) == ""


def test_flm_declares_avx512_for_1_0_13_and_newer():
    desc = yaml.safe_load((REPO_ROOT / "tool" / "flm" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert desc["hardware"] == [{"versions": ">=1.0.13", "cpu_features": ["avx512f"], "why": desc["hardware"][0]["why"]}]
    setup = yaml.safe_load((REPO_ROOT / "task" / "setup" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert setup["cli_params"]["skip_hardware_check"] == "bool"


@pytest.fixture(scope = "module")
def explore():
    return load("task/explore-tool-versions/api_v1.py",
                [("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")])


def test_not_supported_here_is_neither_a_limit_nor_broken(explore):
    error = ('flm 1.0.13 is not supported on this machine: it needs the CPU feature(s) avx512f, which this processor '
             'does not have')
    assert explore["error_class"](error, "setup") == "not supported here"

    def verdict(version, works, uname, error_class = None, error = None):
        return {"schema": 1, "tool": "flm", "version": version, "obtained": version if works else None, "works": works,
                "error_class": error_class, "error": error, "host": {"uname": uname, "hostname": "h"}}

    records = [verdict("1.0.7", True, "linux"), verdict("1.0.13", True, "linux"),
               verdict("1.0.13", False, "linux", "setup", error)]
    proposals = explore["proposals_of"](records, {"flm": {"default_version": "1.0.7"}}, min_os = 1, today = "2026-11-24")
    assert not any(p["change"] == "latest_limits" for p in proposals)
    assert [p["change"] for p in proposals] == ["not supported here"]
