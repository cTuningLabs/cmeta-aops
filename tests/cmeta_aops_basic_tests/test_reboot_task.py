"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import importlib.util
import pathlib
import subprocess
import sys
import types

import pytest


@pytest.fixture
def reboot_module(monkeypatch):
    # Load the artifact outside cMeta so command selection can be tested safely.
    category = types.ModuleType("task_c36be4b9314a45e0")
    api = types.ModuleType("task_c36be4b9314a45e0.api")
    base = types.ModuleType("task_c36be4b9314a45e0.api.ctask")
    base.InitCTask = type("InitCTask", (), {})
    monkeypatch.setitem(sys.modules, category.__name__, category)
    monkeypatch.setitem(sys.modules, api.__name__, api)
    monkeypatch.setitem(sys.modules, base.__name__, base)

    source = pathlib.Path(__file__).parents[2] / "task" / "reboot" / "api_v1.py"
    spec = importlib.util.spec_from_file_location("reboot_artifact_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "system,delay,root,expected,actual",
    [
        ("Windows", 60, False, ["shutdown.exe", "/r", "/t", "60"], 60),
        ("Linux", 61, False, ["sudo", "-n", "shutdown", "-r", "+2"], 120),
        ("Linux", 0, True, ["shutdown", "-r", "now"], 0),
        ("Darwin", 60, False, ["sudo", "-n", "shutdown", "-r", "+1"], 60),
    ],
)
def test_platform_commands(reboot_module, system, delay, root, expected, actual):
    assert reboot_module.reboot_command(system, delay, root) == (expected, actual)


@pytest.mark.parametrize("system,delay", [("FreeBSD", 60), ("Linux", -1), ("Windows", 3601)])
def test_unsupported_or_invalid_inputs(reboot_module, system, delay):
    with pytest.raises(ValueError):
        reboot_module.reboot_command(system, delay)


def test_preview_and_missing_confirmation_cannot_reboot(reboot_module, monkeypatch):
    monkeypatch.setattr(reboot_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(reboot_module.subprocess, "run", lambda *a, **k: pytest.fail("reboot invoked"))
    task = object.__new__(reboot_module.CTask)

    preview = task.run({}, dry_run=True)
    assert preview["return"] == 0 and preview["scheduled"] is False
    assert preview["command"] == ["shutdown.exe", "/r", "/t", "60"]

    missing_yes = task.run({})
    assert missing_yes["return"] != 0 and missing_yes["scheduled"] is False


def test_confirmed_run_schedules_only_selected_command(reboot_module, monkeypatch):
    monkeypatch.setattr(reboot_module.platform, "system", lambda: "Windows")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(reboot_module.subprocess, "run", fake_run)
    task = object.__new__(reboot_module.CTask)
    result = task.run({}, yes=True, delay_seconds=25)
    assert result["scheduled"] is True and result["return"] == 0
    assert calls == [(["shutdown.exe", "/r", "/t", "25"], {"capture_output": True, "text": True, "errors": "replace", "timeout": 20, "check": False})]
