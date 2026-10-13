"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import shutil
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask


def reboot_command(system, delay_seconds, is_root=False, systemd=False, interactive=False):
    """Return an argument vector and actual delay without invoking a reboot."""
    try:
        delay = int(delay_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("delay_seconds must be an integer") from exc

    if delay < 0 or delay > 3600:
        raise ValueError("delay_seconds must be between 0 and 3600")

    if system == "Windows":
        return ["shutdown.exe", "/r", "/t", str(delay)], delay

    sudo = [] if is_root else (["sudo"] if interactive else ["sudo", "-n"])

    if system == "Linux" and systemd:
        command = ["systemctl", "reboot", "-i"]
        if delay:
            command = ["systemd-run", "--on-active={}s".format(delay),
                       "--timer-property=AccuracySec=1s", "--property=Type=exec"] + command
        return sudo + command, delay

    if system in ("Linux", "Darwin"):
        minutes = (delay + 59) // 60
        when = "now" if minutes == 0 else "+{}".format(minutes)
        command = ["shutdown", "-r", when]
        return sudo + command, minutes * 60

    raise ValueError("unsupported operating system: {}".format(system))


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self, ctx, yes=False, dry_run=False, delay_seconds=0):
        system = platform.system()
        is_root = system != "Windows" and hasattr(os, "geteuid") and os.geteuid() == 0
        interactive = bool(sys.stdin and sys.stdin.isatty())
        systemd = (system == "Linux" and os.path.isdir("/run/systemd/system")
                   and shutil.which("systemctl") is not None and shutil.which("systemd-run") is not None)
        yes = str(yes).lower() in ("true", "1", "yes", "y", "on")
        dry_run = str(dry_run).lower() in ("true", "1", "yes", "y", "on")
        try:
            command, actual_delay = reboot_command(system, delay_seconds, is_root, systemd, interactive)
        except ValueError as exc:
            return {"return": 1, "error": str(exc)}

        result = {
            "return": 0,
            "system": system,
            "command": command,
            "delay_seconds": actual_delay,
            "scheduled": False,
        }
        if dry_run:
            return result
        if not yes:
            if not interactive:
                result["return"] = 1
                result["error"] = "Run in a terminal to confirm, pass --yes, or use --dry_run to preview."
                return result
            question = "Reboot {} {}?".format(platform.node(), "now" if actual_delay == 0 else "in {} seconds".format(actual_delay))
            if systemd:
                question += " Active session inhibitors will be ignored."
            try:
                answer = input(question + " [y/N] ").strip().lower()
            except (EOFError, OSError, ValueError):
                result["return"] = 1
                result["error"] = "No confirmation received; pass --yes only if you intend to reboot."
                return result
            if answer not in ("y", "yes"):
                result["cancelled"] = True
                return result

        try:
            completed = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                       timeout=120 if interactive else 20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["return"] = 1
            result["error"] = "Could not schedule reboot: {}".format(exc)
            return result

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            result["return"] = 1
            result["error"] = "Reboot command failed: {}".format(detail)
            return result

        result["scheduled"] = True
        return result
