"""
lib-openssl-android set up on its own (cx tool setup, explore-tool-versions): its check selects the target android-cpu
itself - which reads the ABI of the connected device - where it said "must be selected" before (2026-11-26). Offline:
a stand-in for cMeta's access.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET_TASK = "target--android-cpu,eb4790d97cf74df9"


@pytest.fixture(scope = "module")
def tool_class():
    path = REPO_ROOT / "tool" / "lib-openssl-android" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "lib_openssl_android_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns["CTool"]


class CM:
    """The task of the target: it stores what it read of the device in the run's context, or fails without one."""

    def __init__(self, device = True):
        self.calls, self.device = [], device

    def access(self, i):
        self.calls.append(i)
        if not self.device:
            return {"return": 1, "error": "no Android device is connected (adb devices)"}
        i["ctx"]["tasks"]["global"]["target--android-cpu"] = {"features": {"ro.product.cpu.abi": "arm64-v8a"}}
        return {"return": 0}

    def error(self, text):
        return {"return": 1, "error": text}


def tool(tool_class, device = True):
    t = object.__new__(tool_class)
    t.cm = CM(device)
    return t


def ctx(**known):
    return {"control": {"con": False}, "tasks": {"global": dict(known), "local": {}}}


def test_a_setup_of_its_own_selects_the_android_target(tool_class):
    t, c = tool(tool_class), ctx()
    assert t.check_params(c, {}, {})["return"] == 0
    assert c["tasks"]["local"]["target_abi"] == "arm64-v8a"
    assert [x["arg1"] for x in t.cm.calls] == [TARGET_TASK]


def test_a_run_for_android_cpu_keeps_its_target(tool_class):
    t, c = tool(tool_class), ctx(**{"target--android-cpu": {"features": {"ro.product.cpu.abi": "armeabi-v7a"}}})
    assert t.check_params(c, {}, {})["return"] == 0 and c["tasks"]["local"]["target_abi"] == "armeabi-v7a"
    assert t.cm.calls == []


def test_no_device_is_the_target_tasks_own_error(tool_class):
    r = tool(tool_class, device = False).check_params(ctx(), {}, {})
    assert r["return"] == 1 and "no Android device" in r["error"]


def test_the_target_task_is_named_by_its_uid():
    meta = yaml.safe_load((REPO_ROOT / "task" / "target--android-cpu" / "_cmeta.yaml").read_text(encoding = "utf-8"))
    assert TARGET_TASK == "target--android-cpu," + meta["artifact"]
