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
