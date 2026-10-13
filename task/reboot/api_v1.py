"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask


def reboot_command(system, delay_seconds, is_root=False):
    """Return an argument vector and actual delay without invoking a reboot."""
    try:
        delay = int(delay_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("delay_seconds must be an integer") from exc

    if delay < 0 or delay > 3600:
        raise ValueError("delay_seconds must be between 0 and 3600")

    if system == "Windows":
        return ["shutdown.exe", "/r", "/t", str(delay)], delay

    if system in ("Linux", "Darwin"):
        minutes = (delay + 59) // 60
        when = "now" if minutes == 0 else "+{}".format(minutes)
        command = ["shutdown", "-r", when]
        if not is_root:
            command = ["sudo", "-n"] + command
        return command, minutes * 60

    raise ValueError("unsupported operating system: {}".format(system))


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self, ctx, yes=False, dry_run=False, delay_seconds=60):
        system = platform.system()
        is_root = system != "Windows" and hasattr(os, "geteuid") and os.geteuid() == 0
        try:
            command, actual_delay = reboot_command(system, delay_seconds, is_root)
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
            result["return"] = 1
            result["error"] = "Pass --yes to schedule the reboot, or --dry_run to preview it."
            return result

        try:
            completed = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=20, check=False)
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
