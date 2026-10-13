"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/sync-system-clock: the parsers of the time tools' outputs (w32tm, sc, timedatectl, chronyc, sntp), the
commands it plans per OS (Windows elevated, Linux with sudo, WSL2's hwclock, macOS's sntp; --check plans no
fix), the reading of the measurements - all offline - and one real `--check` on this machine, which changes
nothing and may find no time server (then the offset is None and the run still succeeds).
"""

import pytest


@pytest.fixture(scope = "module")
def clock(task_namespace):
    return task_namespace("sync-system-clock")


W32TM = """Tracking time.windows.com [51.145.123.29:123].
Collecting 3 samples.
The current time is 2026-10-12 20:51:01.
20:51:01, +06.1180236s
20:51:03, +06.1189528s
20:51:05, error: 0x800705B4
"""

SC_RUNNING = """
SERVICE_NAME: w32time
        TYPE               : 20  WIN32_SHARE_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
"""

SC_STOPPED = "SERVICE_NAME: w32time\n        STATE              : 1  STOPPED\n"

TIMEDATECTL_SHOW = "Timezone=Europe/Paris\nLocalRTC=no\nCanNTP=yes\nNTP=yes\nNTPSynchronized=yes\nTimeUSec=Mon 2026-10-12 20:50:53 CEST\n"

TIMESYNC_STATUS = """       Server: 91.189.91.157 (ntp.ubuntu.com)
Poll interval: 1min 4s (min: 32s; max 34min 8s)
         Leap: normal
      Version: 4
      Stratum: 2
    Reference: 11FD227B
    Precision: 1us (-24)
Root distance: 15.342ms (max: 5s)
       Offset: -3.301s
        Delay: 20.615ms
"""

CHRONYC = """Reference ID    : 0A0A0A0A (ntp.example.org)
Stratum         : 3
Ref time (UTC)  : Mon Oct 12 18:50:00 2026
System time     : 0.000123456 seconds slow of NTP time
Last offset     : -0.000045678 seconds
RMS offset      : 0.000123456 seconds
"""

SNTP = "+0.012345 +/- 0.001234 time.apple.com 17.253.2.253\n"


def test_the_parsers(clock):
    offsets, errors = clock["parse_w32tm_stripchart"](W32TM)
    assert offsets == [6.1180236, 6.1189528] and len(errors) == 1 and "0x800705B4" in errors[0]
    assert clock["parse_w32tm_stripchart"]("nothing")[0] == []

    assert clock["parse_sc_query"](SC_RUNNING) == "running"
    assert clock["parse_sc_query"](SC_STOPPED) == "stopped"
    assert clock["parse_sc_query"]("") == "unknown"

    d = clock["parse_timedatectl"](TIMEDATECTL_SHOW)
    assert d["ntp"] == "yes" and d["ntpsynchronized"] == "yes" and d["timezone"] == "Europe/Paris"
    d = clock["parse_timedatectl"]("               Local time: Mon 2026-10-12 20:50:53 CEST\n              NTP service: active\n")
    assert d["ntp_service"] == "active"

    assert clock["parse_offset_line"](TIMESYNC_STATUS, "offset") == pytest.approx(-3.301)
    assert clock["parse_offset_line"]("Offset: +1.234ms\n", "offset") == pytest.approx(0.001234)
    assert clock["parse_offset_line"](CHRONYC, "system time") == pytest.approx(-0.000123456)
    assert clock["parse_offset_line"]("System time : 2.5 seconds fast of NTP time", "system time") == pytest.approx(2.5)
    assert clock["parse_offset_line"]("no such line", "offset") is None

    assert clock["parse_sntp"](SNTP) == pytest.approx(0.012345)
    assert clock["parse_sntp"]("sntp: no response") is None


def test_the_plan_per_os(clock):
    plan = clock["plan"]

    p = plan("windows")
    assert p["service"] == "w32time" and p["server"] == "time.windows.com"
    assert [parser for cmd, parser in p["measure"]] == ["w32tm", "sc"]
    assert p["measure"][0][0] == "w32tm /stripchart /computer:time.windows.com /samples:3 /dataonly"
    fix = p["fix"][0][1]
    assert "Set-Service -Name w32time -StartupType Automatic" in fix and "Start-Service -Name w32time" in fix
    assert "w32tm /resync /rediscover" in fix and "-Verb RunAs" in fix and p["fix"][0][2] is False
    assert plan("windows", server = "pool.ntp.org", samples = 5)["measure"][0][0].endswith("/computer:pool.ntp.org /samples:5 /dataonly")

    p = plan("darwin")
    assert p["measure"] == [("sntp time.apple.com", "sntp")]
    assert [(c, s) for n, c, s in p["fix"]] == [("sntp -sS time.apple.com", True), ("systemsetup -setusingnetworktime on", True)]

    p = plan("linux", has = lambda name: name in ("timedatectl",))
    assert p["service"] == "systemd-timesyncd"
    assert [parser for cmd, parser in p["measure"]] == ["timesync", "timedatectl"]
    assert [(c, s) for n, c, s in p["fix"]] == [("timedatectl set-ntp true", True), ("systemctl restart systemd-timesyncd", True)]

    p = plan("linux", has = lambda name: name in ("timedatectl", "chronyc"))
    assert p["service"] == "chrony" and p["measure"][0] == ("chronyc tracking", "chronyc")
    assert [c for n, c, s in p["fix"]] == ["timedatectl set-ntp true", "chronyc makestep"]

    p = plan("wsl2", has = lambda name: name in ("timedatectl",))
    assert [(c, s) for n, c, s in p["fix"]] == [("hwclock -s", True)]

    # a machine without the tools: nothing to measure with (the run says so)
    assert plan("linux", has = lambda name: False)["measure"] == []


def test_reading_the_measurements_and_sudo(clock):
    read, with_sudo = clock["read_measurements"], clock["with_sudo"]

    offset, source, state = read({"w32tm": W32TM, "sc": SC_STOPPED})
    assert offset == pytest.approx((6.1180236 + 6.1189528) / 2) and "2 sample" in source and state["state"] == "stopped"

    offset, source, state = read({"w32tm": "20:51:05, error: 0x800705B4\n", "sc": SC_RUNNING})
    assert offset is None and "0x800705B4" in source and state["state"] == "running"

    offset, source, state = read({"timesync": TIMESYNC_STATUS, "timedatectl": TIMEDATECTL_SHOW})
    assert offset == pytest.approx(-3.301) and state["state"] == "running" and state["synchronized"] == "yes"

    offset, source, state = read({"chronyc": CHRONYC, "timedatectl": "NTP=no\nNTPSynchronized=no\n"})
    assert offset == pytest.approx(-0.000123456) and state["state"] == "stopped"

    assert with_sudo("hwclock -s", True, False) == "sudo -n hwclock -s"
    assert with_sudo("hwclock -s", True, True) == "sudo hwclock -s"
    assert with_sudo("sc query w32time", False, False) == "sc query w32time"


def test_check_on_this_machine_changes_nothing(cm):
    r = cm.access({"category": "task", "command": "run", "arg1": "sync-system-clock", "check": True, "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert r["os"] in ("windows", "linux", "wsl2", "darwin")
    assert r["offset_seconds"] is None or isinstance(r["offset_seconds"], float)
    assert r["actions"] == [] and r["fixed"] is None
    assert isinstance(r["ok"], bool) and r["service"]["name"]
