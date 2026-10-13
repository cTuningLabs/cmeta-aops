"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import builtins
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


def test_systemd_ignores_session_inhibitors(reboot_module):
    assert reboot_module.reboot_command("Linux", 0, systemd=True) == (
        ["sudo", "-n", "systemctl", "reboot", "-i"], 0)
    assert reboot_module.reboot_command("Linux", 25, systemd=True, interactive=True) == (
        ["sudo", "systemd-run", "--on-active=25s", "--timer-property=AccuracySec=1s",
         "--property=Type=exec", "systemctl", "reboot", "-i"], 25)


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
    assert preview["command"] == ["shutdown.exe", "/r", "/t", "0"]

    missing_yes = task.run({})
    assert missing_yes["return"] != 0 and missing_yes["scheduled"] is False


def test_interactive_prompt_confirms_or_cancels(reboot_module, monkeypatch):
    monkeypatch.setattr(reboot_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(reboot_module.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    task = object.__new__(reboot_module.CTask)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(reboot_module.subprocess, "run", fake_run)
    monkeypatch.setattr(builtins, "input", lambda question: "no")
    cancelled = task.run({})
    assert cancelled["return"] == 0 and cancelled["cancelled"] is True
    assert not calls

    monkeypatch.setattr(builtins, "input", lambda question: "yes")
    confirmed = task.run({})
    assert confirmed["scheduled"] is True
    assert calls == [["shutdown.exe", "/r", "/t", "0"]]


def test_linux_desktop_prompt_uses_inhibitor_override(reboot_module, monkeypatch):
    monkeypatch.setattr(reboot_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(reboot_module.platform, "node", lambda: "p14s")
    monkeypatch.setattr(reboot_module.os.path, "isdir", lambda path: path == "/run/systemd/system")
    monkeypatch.setattr(reboot_module.shutil, "which", lambda name: name)
    monkeypatch.setattr(reboot_module.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    questions = []
    monkeypatch.setattr(builtins, "input", lambda question: questions.append(question) or "y")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(reboot_module.subprocess, "run", fake_run)
    result = object.__new__(reboot_module.CTask).run({})
    assert result["scheduled"] is True
    assert commands == [["sudo", "systemctl", "reboot", "-i"]]
    assert "inhibitors will be ignored" in questions[0]


def test_false_string_is_not_confirmation(reboot_module, monkeypatch):
    monkeypatch.setattr(reboot_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(reboot_module.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(reboot_module.subprocess, "run", lambda *a, **k: pytest.fail("reboot invoked"))
    task = object.__new__(reboot_module.CTask)
    assert task.run({}, yes="False")["return"] == 1
    assert task.run({}, yes="False", dry_run="True")["scheduled"] is False


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
