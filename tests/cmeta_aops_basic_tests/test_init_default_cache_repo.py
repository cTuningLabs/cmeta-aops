"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/init: the run-wide cache repo (--use.init.default_cache_repo=<repo>, or the key
default_cache_repo of config::task) reaches the place the task engine reads it,
ctx['tasks']['global']['init']['default_cache_repo'], and leaves the other keys of config::task alone.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def task():
    path = REPO_ROOT / "task" / "init" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "task_init", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


class FakeCM:
    """config::task as the given dict."""

    def __init__(self, config):
        self.config = config

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        assert ii["category"].startswith("config,") and ii["command"] == "get" and ii["arg1"] == "task"
        return {"return": 0, "config_cmeta": dict(self.config)}


def run(task, config = None, **params):
    t = task["CTask"].__new__(task["CTask"])
    t.cm = FakeCM(config or {})
    return t.run({}, **params)


def test_cli_value_is_stored_under_the_key_the_engine_reads(task):
    r = run(task, default_cache_repo = "myrepo")
    assert r["return"] == 0 and r["default_cache_repo"] == "myrepo"
    assert "myrepo" not in r                     # not under a key named after the repo


def test_nothing_given_nothing_set(task):
    r = run(task)
    assert r == {"return": 0}
    assert "default_cache_repo" not in run(task, default_cache_repo = "")
    assert "default_cache_repo" not in run(task, default_cache_repo = None)


def test_config_task_sets_it_and_the_cli_overrides_it(task):
    config = {"default_cache_repo": "from-config", "file_cache": "/cache"}
    assert run(task, config)["default_cache_repo"] == "from-config"
    r = run(task, config, default_cache_repo = "from-cli")
    assert r["default_cache_repo"] == "from-cli" and r["file_cache"] == "/cache"


@pytest.mark.parametrize("repo", ["tool", "hf", "file_cache", "return"])
def test_a_repo_named_like_a_config_key_does_not_replace_it(task, repo):
    config = {"tool": {"check_versions": True}, "hf": {"cache": "/hf"}, "file_cache": "/cache"}
    r = run(task, config, default_cache_repo = repo)
    assert r["return"] == 0 and r["default_cache_repo"] == repo
    assert r["tool"] == {"check_versions": True} and r["hf"] == {"cache": "/hf"} and r["file_cache"] == "/cache"


def test_task_init_returns_it_through_the_engine(cm):
    for ii in ({"default_cache_repo": "cache2"}, {"use": {"init": {"default_cache_repo": "cache2"}}}):
        r = cm.access(dict({"category": "task", "command": "run", "arg1": "init", "con": False, "quiet": True}, **ii))
        assert r["return"] == 0, r.get("error")
        assert r.get("default_cache_repo") == "cache2" and "cache2" not in r


def test_use_init_reaches_the_global_state_of_a_pipeline(cm):
    """`host` uses `init`: after the run the value is where the cache step of every task looks for it."""
    ctx = {}
    r = cm.access({"category": "task", "command": "run", "arg1": "host", "con": False, "quiet": True, "ctx": ctx,
                   "use": {"init": {"default_cache_repo": "cache2"}}})
    assert r["return"] == 0, r.get("error")
    init = ctx["tasks"]["global"]["init"]
    assert init.get("default_cache_repo") == "cache2" and "cache2" not in init

    ctx = {}
    r = cm.access({"category": "task", "command": "run", "arg1": "host", "con": False, "quiet": True, "ctx": ctx})
    assert r["return"] == 0, r.get("error")
    assert "default_cache_repo" not in ctx["tasks"]["global"]["init"]      # nothing asked: the cache stays in "local"


def test_the_file_cache_of_one_run(task):
    """--use.init.file_cache=<folder> names the file cache of one run, over the key of config::task (0.47.0;
    before, init refused the parameter: "unexpected keyword argument 'file_cache'")."""
    assert run(task, file_cache = "/run")["file_cache"] == "/run"
    assert run(task, {"file_cache": "/cfg"})["file_cache"] == "/cfg"
    assert run(task, {"file_cache": "/cfg"}, file_cache = "/run")["file_cache"] == "/run"
    assert "file_cache" not in run(task, file_cache = "")


@pytest.mark.parametrize("key, env", [("version_policy", "CMETA_VERSION_POLICY"),
                                      ("versions_ttl_hours", "CMETA_VERSIONS_TTL_HOURS")])
def test_the_version_keys_flag_over_variable_over_config(task, monkeypatch, key, env):
    monkeypatch.delenv(env, raising = False)
    assert key not in run(task)
    assert run(task, {key: "from-config"})[key] == "from-config"

    monkeypatch.setenv(env, "from-env")
    assert run(task, {key: "from-config"})[key] == "from-env"
    assert run(task, {key: "from-config"}, **{key: "from-flag"})[key] == "from-flag"

    monkeypatch.setenv(env, "")
    assert run(task, {key: "from-config"})[key] == "from-config"


def test_the_run_keys_reach_init_through_the_engine(cm, tmp_path):
    use = {"init": {"file_cache": str(tmp_path), "version_policy": "known", "versions_ttl_hours": "1"}}
    r = cm.access({"category": "task", "command": "run", "arg1": "init", "con": False, "quiet": True, "use": use})
    assert r["return"] == 0, r.get("error")
    assert r["file_cache"] == str(tmp_path) and r["version_policy"] == "known" and r["versions_ttl_hours"] == "1"
