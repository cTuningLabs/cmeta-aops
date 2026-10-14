"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the versions by name of "cx tool setup" (task/setup/upgrade.py): "known" (default_version
of the tool's _desc.yaml) and "latest" (the newest version its channel or upstream offers), the policy of a
request without a version (the request, the run through task/init, the tool's _desc.yaml, else known), the
fallback from one to the other with a warning, the cached lookup in tmp::tool-versions, and --versions.

The helpers are tested on their own; the rest end to end through the task engine on throwaway tools whose
"newest version" and "install command" are Python one-liners - nothing is installed, no network is touched,
and the cache lives in the temporary CMETA_HOME.
"""

import datetime
import importlib.util
import json
import os
import pathlib
import sys

import pytest
import yaml

PYTHON_VERSION = "%d.%d.%d" % sys.version_info[:3]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

PYTHON = sys.executable
LATEST = "99.0.0"


@pytest.fixture(scope="module")
def up():
    """task/setup/upgrade.py loaded on its own: its helpers need no cMeta."""
    spec = importlib.util.spec_from_file_location("setup_upgrade_versions", REPO_ROOT / "task" / "setup" / "upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


###################################################################################################
# The helpers

def test_version_words_and_policies(up):
    assert up.version_word("latest") == "latest" and up.version_word(" Known ") == "known"
    assert up.version_word("1.2.3") is None and up.version_word(None) is None and up.version_word(True) is None
    assert up.policy_of("ASK") == "ask" and up.policy_of("latest") == "latest" and up.policy_of("newest") is None


def test_known_version(up):
    assert up.known_version({"default_version": "4.3.0"}) == "4.3.0"
    assert up.known_version({"default_version": 1.3}) == "1.3"
    assert up.known_version({}) is None and up.known_version({"default_version": ""}) is None


def test_ttl_and_age(up):
    assert up.ttl_hours(None) == 24 and up.ttl_hours("12") == 12.0 and up.ttl_hours("x") == 24 and up.ttl_hours(0) == 0.0
    now = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.timezone.utc)
    assert up.lookup_age_hours({"asked_at": "2026-10-14T10:00:00+00:00"}, now) == 2.0
    assert up.lookup_age_hours({"asked_at": "2026-10-14T10:00:00Z"}, now) == 2.0
    assert up.lookup_age_hours({}, now) is None and up.lookup_age_hours({"asked_at": "yesterday"}, now) is None


def test_pick_version_follows_the_channel(up):
    rl = {"channel_version": "2.53.0", "channel_source": "winget (Git.Git)", "upstream_version": "2.55.0", "upstream_source": "https://x"}
    assert up.pick_version(rl, {"primary": up.CHANNEL_WINGET}) == ("2.53.0", "winget (Git.Git)")
    assert up.pick_version(rl, {"primary": up.CHANNEL_RELEASE}) == ("2.55.0", "https://x")
    assert up.pick_version({"channel_version": "1.0"}, {"primary": up.CHANNEL_RELEASE}) == ("1.0", None)
    assert up.pick_version({}, {"primary": up.CHANNEL_RELEASE}) == (None, None)


###################################################################################################
# End to end, offline: throwaway tools

def fake_tool(cm, name, latest_cmd, install_cmd=None, install_cmd_version=None, extra=None):
    """A tool in the temporary CMETA_HOME's local repo, detected at sys.executable, pinned at this Python's version."""
    r = cm.access({"category": "tool", "command": "add", "arg1": f"local:{name}", "con": False, "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")

    desc = {
        "names": [os.path.basename(PYTHON)],
        "match_version": [{"regex": r"Python (\d+\.\d+\.\d+)", "group": 1}],
        "cmd_get_version": "{{tool_path}} --version",
        "default_version": PYTHON_VERSION,
        "cmd_get_latest_version": latest_cmd,
        "cmd_get_latest_version_regex": r"(\d+\.\d+\.\d+)",
        "install_cmd": {"all": install_cmd or f'"{PYTHON}" -c "print(1)"'},
        "skip_common_install_uses": True,
    }
    if install_cmd_version:
        desc["install_cmd_version"] = {"all": install_cmd_version}
    desc.update(extra or {})
    with open(os.path.join(r["path"], "_desc.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(desc, f)
    return r["path"]


def one_liner(text):
    """A command that prints the text (the newest version of a fake tool), or nothing."""
    if not text:
        return f'"{PYTHON}" -c "pass"'
    chars = " + ".join(f"chr({ord(c)})" for c in text)
    return f'"{PYTHON}" -c "import sys; sys.stdout.write({chars})"'


@pytest.fixture(scope="module")
def tools(cm):
    return {
        "newest": fake_tool(cm, "test-versions-newest", one_liner(LATEST)),
        "silent": fake_tool(cm, "test-versions-silent", one_liner("")),
        "failing": fake_tool(cm, "test-versions-failing", one_liner(LATEST),
                             install_cmd_version=f'"{PYTHON}" -c "import sys; sys.exit(1 if \'{{{{simple_version}}}}\' == \'{LATEST}\' else 0)"'),
        "policy-latest": fake_tool(cm, "test-versions-policy", one_liner(LATEST), extra={"version_policy": "latest"}),
    }


def setup(cm, name, **params):
    ii = {"category": "task", "command": "run", "arg1": "setup", "name": name, "tool_path": PYTHON, "con": False, "quiet": True}
    ii.update(params)
    return cm.access(ii)


def test_known_is_the_pinned_version(cm, tools):
    r = setup(cm, "test-versions-newest", version="known")
    assert r["return"] == 0, r.get("error")
    assert r["version"] == PYTHON_VERSION
    assert r["version_resolved"] == {"word": "known", "version": PYTHON_VERSION}


def test_latest_is_the_newest_and_fails_loudly_when_it_is_not_obtained(cm, tools):
    # The install "succeeds" but delivers this Python, not 99.0.0: a resolved version is a version asked for
    r = setup(cm, "test-versions-newest", version="latest", new=True)
    assert r["return"] > 0 and LATEST in r["error"], r

    # The lookup is cached: tmp::tool-versions/<tool>.json in the test home, and the next request reads it
    r = cm.access({"category": "tmp", "command": "find", "arg1": "local:tool-versions"})
    assert r["return"] == 0 and r["artifacts"], r
    record_path = os.path.join(r["artifacts"][0]["path"], "test-versions-newest.json")
    with open(record_path, encoding="utf-8") as f:
        record = json.load(f)
    assert record["latest"] == LATEST and record["known"] == PYTHON_VERSION and record["source"] == "cmd_get_latest_version"

    # --versions of a tool without cmd_get_versions: nothing to list, the newest and the known ones; the first
    # call completes the cached record (the list), the second is served from it
    r = setup(cm, "test-versions-newest", versions=True)
    assert r["return"] == 0, r.get("error")
    assert r["versions"] == [] and r["latest"] == LATEST and r["known"] == PYTHON_VERSION and r["policy"] == "known"
    r = setup(cm, "test-versions-newest", versions=True)
    assert r["return"] == 0 and r["versions_lookup"]["from_cache"] is True
    r = setup(cm, "test-versions-newest", versions=True, refresh_versions=True)
    assert r["return"] == 0 and r["versions_lookup"]["from_cache"] is False


def test_latest_falls_back_to_known_when_nothing_is_found(cm, tools):
    r = setup(cm, "test-versions-silent", version="latest")
    assert r["return"] == 0, r.get("error")
    assert r["version"] == PYTHON_VERSION
    assert r["version_resolved"] == {"word": "latest", "version": PYTHON_VERSION}


def test_a_failed_install_of_the_latest_falls_back_to_known(cm, tools):
    # The versioned install command fails for 99.0.0 and succeeds for the known version; the entry records the latter
    r = setup(cm, "test-versions-failing", version="latest", new=True)
    assert r["return"] == 0, r.get("error")
    assert r["version"] == PYTHON_VERSION
    assert r["version_fallback"]["from"] == LATEST and r["version_fallback"]["to"] == PYTHON_VERSION
    assert r["_params"]["version"] == PYTHON_VERSION


def test_the_policy_of_a_request_without_a_version(cm, tools):
    # The default: whatever is found (this Python), as before, nothing resolved (a new entry: a request without a
    # version would otherwise replay the entry of the "known" request above, whose result says how it was chosen)
    r = setup(cm, "test-versions-newest", new=True)
    assert r["return"] == 0 and r["version"] == PYTHON_VERSION and "version_resolved" not in r

    # The run's policy (--use.init.version_policy=latest, CMETA_VERSION_POLICY or config::task): the newest
    r = setup(cm, "test-versions-newest", use={"init": {"version_policy": "latest"}}, new=True)
    assert r["return"] > 0 and LATEST in r["error"], r

    # The tool's own policy
    r = setup(cm, "test-versions-policy", new=True)
    assert r["return"] > 0 and LATEST in r["error"], r

    # The request's policy wins over the tool's; "ask" without a terminal (quiet) takes the known one
    r = setup(cm, "test-versions-policy", version_policy="known")
    assert r["return"] == 0 and r["version"] == PYTHON_VERSION
    r = setup(cm, "test-versions-newest", version_policy="ask", new=True)
    assert r["return"] == 0 and r["version"] == PYTHON_VERSION and r["version_resolved"]["word"] == "ask"


def test_a_named_version_is_never_replaced(cm, tools):
    r = setup(cm, "test-versions-failing", version=LATEST, new=True)
    assert r["return"] > 0 and LATEST in r["error"] and "version_fallback" not in r


###################################################################################################
# cx tool check-updates: the pins against the newest versions, a report

def test_update_status(up):
    assert up.update_status("4.53.6", "4.54.1") == ("behind", "minor")
    assert up.update_status("4.53.6", "5.0.0") == ("behind", "major")
    assert up.update_status("4.53.6", "4.53.7") == ("behind", "patch")
    assert up.update_status("1.8", "1.8.1") == ("behind", "patch")
    assert up.update_status("4.3.0", "4.3.0") == ("current", None)
    assert up.update_status("2.49.0.windows.1", "2.49.0") == ("current", None)
    assert up.update_status("5.0.0", "4.9.9") == ("ahead", None)
    assert up.update_status(None, "1.0.0") == ("no pin", None) and up.update_status("", None) == ("no pin", None)
    assert up.update_status("1.0.0", None) == ("unknown", None)


@pytest.fixture(scope="module")
def update_tools(cm, tools):
    """Two more throwaway tools: one whose newest version is its pin, one whose pin is newer than the newest."""
    return {
        "current": fake_tool(cm, "test-versions-current", one_liner(PYTHON_VERSION)),
        "ahead": fake_tool(cm, "test-versions-ahead", one_liner("0.0.1")),
        "no-pin": fake_tool(cm, "test-versions-nopin", one_liner(LATEST), extra={"default_version": None}),
    }


def check_updates(cm, names, **params):
    ii = {"category": "tool", "command": "check_updates", "arg1": ",".join(names), "con": False, "quiet": True}
    ii.update(params)
    return cm.access(ii)


def test_check_updates_reports_each_tool(cm, tools, update_tools):
    names = ["test-versions-newest", "test-versions-current", "test-versions-ahead", "test-versions-nopin",
             "test-versions-silent", "test-versions-no-such-tool"]
    r = check_updates(cm, names, refresh_versions=True)
    assert r["return"] == 0, r.get("error")

    rows = {row["tool"]: row for row in r["tools"]}
    assert [row["tool"] for row in r["tools"]] == names
    assert (rows["test-versions-newest"]["status"], rows["test-versions-newest"]["step"]) == ("behind", "major")
    assert rows["test-versions-newest"]["known"] == PYTHON_VERSION and rows["test-versions-newest"]["latest"] == LATEST
    assert rows["test-versions-current"]["status"] == "current"
    assert rows["test-versions-ahead"]["status"] == "ahead"
    assert rows["test-versions-nopin"]["status"] == "no pin" and rows["test-versions-nopin"]["latest"] == LATEST
    assert rows["test-versions-silent"]["status"] == "unknown" and rows["test-versions-silent"]["latest"] is None
    assert rows["test-versions-no-such-tool"]["status"] == "error" and rows["test-versions-no-such-tool"]["notes"]
    assert r["summary"] == {"behind": 1, "behind_major": 1, "current": 1, "ahead": 1, "no pin": 1, "unknown": 1, "error": 1}

    # A second report reads the cached lookups; nothing was installed
    r = check_updates(cm, ["test-versions-newest"])
    assert r["tools"][0]["from_cache"] is True and r["tools"][0]["latest"] == LATEST


def test_check_updates_saves_the_report(cm, tools, update_tools, tmp_path):
    for name in ("report.json", "report.md"):
        r = check_updates(cm, ["test-versions-newest", "test-versions-current"], output=str(tmp_path / name))
        assert r["return"] == 0, r.get("error")
        assert os.path.isfile(r["output"])

    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert [row["tool"] for row in data["tools"]] == ["test-versions-newest", "test-versions-current"]
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert f"| test-versions-newest | {PYTHON_VERSION} | {LATEST} | behind (major) |" in text
    assert text.index("test-versions-newest") < text.index("test-versions-current")    # what needs a look first


HOOK_API = '''from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def check_params(self, ctx, params, cparams):
        return {'return': 1, 'error': 'an Android target must be selected to install this tool'}
'''


def test_check_updates_reads_a_tool_whose_own_hook_stops_an_install(cm, tools):
    """lib-openssl-android needs an Android target to install: a version check installs nothing, so the tool's
    condition is a note of its row (it stopped the report with an error before)."""
    path = fake_tool(cm, "test-versions-hook", one_liner(LATEST))
    with open(os.path.join(path, "api_v1.py"), "w", encoding="utf-8") as f:
        f.write(HOOK_API)

    r = check_updates(cm, ["test-versions-hook"], refresh_versions=True)
    assert r["return"] == 0, r.get("error")
    row = r["tools"][0]
    assert (row["status"], row["latest"]) == ("behind", LATEST)
    assert "an Android target must be selected" in " ".join(row["notes"])

    # A setup still stops on it
    r = setup(cm, "test-versions-hook")
    assert r["return"] > 0 and "an Android target must be selected" in r["error"]


###################################################################################################
# The limits of "latest" (latest_limits in a tool's _desc.yaml): versions it must not take, with why and since when

def test_latest_limits_and_exclusion(up):
    limit = {"exclude": ">=3.15", "reason": "no cp315 wheels", "since": "2026-10-12"}
    assert up.latest_limits({"latest_limits": limit}) == [limit]
    assert up.latest_limits({"latest_limits": [limit, {"reason": "no exclude"}]}) == [limit]
    assert up.latest_limits({}) == []

    assert up.excluded_by("3.15.0", [limit]) is limit and up.excluded_by("3.16.1", [limit]) is limit
    # PEP 440: a pre-release of 3.15 sorts below 3.15 (and "latest" skips pre-releases); ">=3.15.0a0" takes them too
    assert up.excluded_by("3.15.0rc1", [limit]) is None and up.excluded_by("3.15.0rc1", [{"exclude": ">=3.15.0a0"}]) is not None
    assert up.excluded_by("3.14.8", [limit]) is None and up.excluded_by("not a version", [limit]) is None
    assert up.excluded_by("2.5.3", [{"exclude": "==2.5.*"}]) is not None
    assert up.excluded_by("2.5.3", [{"exclude": "this is not a specifier"}]) is None

    versions = ["3.15.0", "3.15.0rc2", "3.14.8", "3.14.7", "3.13.15"]
    assert up.allowed_latest("3.15.0", versions, [limit]) == ("3.14.8", limit)
    assert up.allowed_latest("3.14.8", versions, [limit]) == ("3.14.8", None)
    assert up.allowed_latest("3.15.0", None, [limit]) == (None, limit)
    assert up.allowed_latest("3.15.0", versions, []) == ("3.15.0", None)
    assert up.limit_text(limit) == "excluded >=3.15: no cp315 wheels (since 2026-10-12)"


def test_the_python_tool_declares_its_limit():
    desc = yaml.safe_load((REPO_ROOT / "tool" / "python" / "_desc.yaml").read_text(encoding="utf-8"))
    assert [(x["exclude"], bool(x["reason"]), bool(x["since"])) for x in desc["latest_limits"]] == [(">=3.15", True, True)]


@pytest.fixture(scope="module")
def limited_tool(cm, tools):
    """A tool whose newest version (99.0.0) is excluded: latest is the newest listed version no limit excludes."""
    listed = f"v1.0.0\nv{PYTHON_VERSION}\nv{LATEST}\n"          # one version per line, as git ls-remote prints them
    return fake_tool(cm, "test-versions-limited", one_liner(LATEST), extra={
        "cmd_get_versions": one_liner(listed), "cmd_get_versions_regex": r"v(\d+\.\d+\.\d+)",
        "latest_limits": [{"exclude": ">=99", "reason": "a throwaway limit", "since": "2026-10-14"}]})


def test_latest_skips_the_versions_a_limit_excludes(cm, limited_tool):
    r = setup(cm, "test-versions-limited", version="latest", new=True, refresh_versions=True)
    assert r["return"] == 0, r.get("error")
    assert r["version_resolved"]["version"] == PYTHON_VERSION and r["version"] == PYTHON_VERSION

    r = setup(cm, "test-versions-limited", versions=True)
    assert r["return"] == 0, r.get("error")
    assert (r["latest"], r["newest"]) == (PYTHON_VERSION, LATEST) and r["limit"]["exclude"] == ">=99"

    r = check_updates(cm, ["test-versions-limited"])
    row = r["tools"][0]
    assert (row["status"], row["latest"], row["newest"]) == ("current", PYTHON_VERSION, LATEST)
    assert row["limit_text"] == "excluded >=99: a throwaway limit (since 2026-10-14)"


def test_a_version_asked_for_by_number_is_taken_despite_a_limit(cm, limited_tool):
    """99.0.0 is excluded from "latest", yet asked for by number it is what the setup tries (and, the throwaway
    tool being this Python, fails loudly) - never replaced by an allowed version."""
    r = setup(cm, "test-versions-limited", version=LATEST, new=True)
    assert r["return"] > 0 and LATEST in r["error"]
    assert "version_resolved" not in r and "version_fallback" not in r


def test_check_updates_installs_no_helper(cm, tools, tmp_path):
    """The version lookup of a tool may need a helper (git for ls-remote, the Android command line tools ...):
    "cx tool check-updates" uses only the helpers on the machine - in a container with Homebrew it began to
    install android-commandlinetools (2026-10-14); --versions may still set one up."""
    marker = tmp_path / "helper-installed"
    helper = fake_tool(cm, "test-versions-helper", one_liner(LATEST), extra={
        "names": ["no-such-helper-binary"],
        "install_cmd": {"all": f'"{PYTHON}" -c "open(r\'{marker}\', \'w\').close()"'}})
    fake_tool(cm, "test-versions-needs-helper", one_liner(LATEST), extra={
        "cmd_get_versions_uses": [{"task": "setup", "name": "test-versions-helper"}]})

    r = check_updates(cm, ["test-versions-needs-helper"], refresh_versions=True)
    assert r["return"] == 0, r.get("error")
    assert r["tools"][0]["latest"] == LATEST, (r["tools"][0]["status"], r["tools"][0]["notes"])
    assert not marker.exists()

    r = setup(cm, "test-versions-needs-helper", versions=True, refresh_versions=True)
    assert marker.exists()
