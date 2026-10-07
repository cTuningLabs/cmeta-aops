"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-ai task, its context sources: the --context entries, cRef matching, the `ai_uses` values, this machine's
mapping (config task-run-ai, key local_ai_uses), the seed and the list of harnesses. Offline: the methods are
called on the task's class loaded without the engine (the `task_namespace` fixture).
"""

import pathlib

import pytest

PROJECT = "work,0f1e2d3c4b5a6978::20260101.a work folder, with commas,0123456789abcdef"


@pytest.fixture(scope="module")
def api(task_namespace):
    return task_namespace("run-ai")


@pytest.fixture(scope="module")
def CTask(api):
    return api["CTask"]


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(text, encoding = "utf-8")
    return path


def task_with(CTask, config):
    """A task that reads `config` as its config artifact task-run-ai."""
    t = CTask.__new__(CTask)
    t._run_ai_config = lambda: config
    return t


# ---------------------------------------------------------------------------------------------- --context
def test_context_entries_are_separated_by_semicolons_never_commas(CTask):
    assert CTask._context_items("tool::a;claude:/work/x, y\n project,1234::my-app,abcd ") == [
        "tool::a", "claude:/work/x, y", "project,1234::my-app,abcd"]
    assert CTask._context_items(["tool::a", " ", "tool::b"]) == ["tool::a", "tool::b"]
    assert CTask._context_items("") == [] and CTask._context_items(None) == []


# ---------------------------------------------------------------------------------------------- cRefs
def test_cref_parts_keep_commas_in_an_artifact_alias(CTask):
    assert CTask._cref_parts(PROJECT) == ("work", "0f1e2d3c4b5a6978", "20260101.a work folder, with commas", "0123456789abcdef")
    assert CTask._cref_parts("tool::a, b") == ("tool", "", "a, b", "")


def test_cref_matches_with_or_without_uids(CTask):
    assert CTask._cref_matches("work::20260101.a work folder, with commas", PROJECT)
    assert CTask._cref_matches("work,0f1e2d3c4b5a6978::x,0123456789abcdef", PROJECT)     # the UIDs decide
    assert CTask._cref_matches("WORK::20260101.A Work Folder, With Commas", PROJECT)     # case does not matter
    assert not CTask._cref_matches("note::20260101.a work folder, with commas", PROJECT)
    assert not CTask._cref_matches("work::another", PROJECT)


def test_uses_entries_take_lists_dicts_and_semicolon_strings(CTask):
    assert CTask._uses_entries("a::b;c,1::d,2") == [("a::b", ""), ("c,1::d,2", "")]
    assert CTask._uses_entries(["a::b", {"cref": "c::d", "note": "why"}, {"note": "no cref"}, ""]) == [("a::b", ""), ("c::d", "why")]
    assert CTask._uses_entries({"cref": "c::d"}) == [("c::d", "")]
    assert CTask._uses_entries(None) == []


# ---------------------------------------------------------------------------------------------- this machine's mapping
@pytest.fixture
def project(tmp_path):
    """A project folder inside a repository whose _cmr.yaml names it shared-repo,1111222233334444."""
    put(tmp_path / "repo" / "_cmr.yaml", "artifact: shared-repo,1111222233334444\ncategory: repo,f4f792ab40c7498f\n")
    p = tmp_path / "repo" / "work" / "a work folder"
    p.mkdir(parents = True)
    return str(p)


@pytest.mark.parametrize("key", ["shared-repo,1111222233334444", "shared-repo", "1111222233334444", "Shared-Repo"])
def test_local_mapping_by_repository(CTask, project, key):
    t = task_with(CTask, {"local_ai_uses": {key: "org::Private,aaaabbbbccccdddd;org::Other"}})
    assert t._local_ai_uses(project, PROJECT) == [("org::Private,aaaabbbbccccdddd", "", key), ("org::Other", "", key)]


def test_local_mapping_by_artifact(CTask, project):
    t = task_with(CTask, {"local_ai_uses": {"0123456789abcdef": "org::ByUid", "work::20260101.a work folder, with commas": ["org::ByCref"],
                                            "work::someone else": "org::Never", "other-repo,9999888877776666": "org::Never"}})
    assert sorted(c for c, n, k in t._local_ai_uses(project, PROJECT)) == ["org::ByCref", "org::ByUid"]


def test_local_mapping_key_split_at_dots_by_the_cli_is_joined_back(CTask, project):
    # "cx config set task-run-ai --meta.local_ai_uses.cserver.x.page::p=org::A" stores nested levels
    nested = {"local_ai_uses": {"cserver": {"x": {"page::p": "org::A"}}}}
    cref = "cserver.x.page,0123456789abcdef::p,fedcba9876543210"
    assert task_with(CTask, nested)._local_ai_uses(project, cref) == [("org::A", "", "cserver.x.page::p")]


def test_local_mapping_absent_or_malformed(CTask, project):
    for cfg in ({}, {"local_ai_uses": "not a map"}, {"local_ai_uses": {}}, {"other": 1}):
        assert task_with(CTask, cfg)._local_ai_uses(project, PROJECT) == []


def test_no_repository_means_only_artifact_keys(CTask, tmp_path, monkeypatch):
    # a folder that is in no repository: _repo_meta walks up to the root and finds no _cmr.yaml
    monkeypatch.setattr(CTask, "_repo_meta", staticmethod(lambda path: {}))
    t = task_with(CTask, {"local_ai_uses": {"0123456789abcdef": "org::A", "local": "org::Never"}})
    assert [c for c, n, k in t._local_ai_uses(str(tmp_path), PROJECT)] == ["org::A"]


def test_repo_meta_is_the_first_cmr_walking_up(CTask, project, tmp_path):
    assert CTask._repo_meta(project)["artifact"] == "shared-repo,1111222233334444"
    put(tmp_path / "repo" / "work" / "_cmr.yaml", "artifact: inner,2222333344445555\n")
    assert CTask._repo_meta(project)["artifact"] == "inner,2222333344445555"


# ---------------------------------------------------------------------------------------------- the seed
def test_seed_copies_only_when_applied(api, CTask, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    native = pathlib.Path(api["CONV"].claude_project_dirs(str(project))[0]) / "memory"
    put(native / "MEMORY.md", "- [A](a.md) - a\n")
    put(native / "a.md", "a\n")
    mem = project / "!AI" / "memory"
    t = CTask.__new__(CTask)
    assert t._seed_memory(str(project), str(mem), apply = False) == (2, str(native))     # --dry_run / --no_seed
    assert not mem.exists()
    assert t._seed_memory(str(project), str(mem), apply = True) == (2, str(native))
    assert sorted(p.name for p in mem.iterdir()) == ["MEMORY.md", "a.md"]
    assert t._seed_memory(str(project), str(mem), apply = True) == (0, "")               # not empty any more


def test_seed_ignores_an_index_alone(api, CTask, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    put(pathlib.Path(api["CONV"].claude_project_dirs(str(project))[0]) / "memory" / "MEMORY.md", "moved elsewhere\n")
    assert CTask.__new__(CTask)._seed_memory(str(project), str(project / "!AI" / "memory"), apply = True) == (0, "")


def test_a_project_folder_with_brackets_in_its_name_is_not_a_pattern(api, CTask, tmp_path, monkeypatch):
    """"[" and "]" are wildcards for glob: a folder called "notes [draft]" must still show its memory and skills."""
    project = tmp_path / "notes [draft] (v2)"
    ai = project / "!AI"
    put(ai / "memory" / "MEMORY.md", "- [One](one.md) - the first fact\n")
    put(ai / "memory" / "one.md", "one\n")
    put(ai / "skills" / "deploy" / "SKILL.md", "---\nname: deploy\ndescription: how to deploy\n---\nsteps\n")
    assert "the first fact" in CTask._memory_text(str(ai))
    assert [(name, desc) for name, desc, path in CTask._list_skills(str(ai / "skills"))] == [("deploy", "how to deploy")]
    # an !AI/memory that holds something is never seeded over
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    put(pathlib.Path(api["CONV"].claude_project_dirs(str(project))[0]) / "memory" / "native.md", "n\n")
    assert CTask.__new__(CTask)._seed_memory(str(project), str(ai / "memory"), apply = True) == (0, "")
    # the conversations of such a project are found too
    conv = api["CONV"].new_conversation(str(ai / "log"), "20261005-090000", str(project), "", "t")
    api["CONV"].save_conversation(conv)
    assert [c["id"] for c in api["CONV"].list_conversations(str(ai / "log"))] == ["20261005-090000"]


# ---------------------------------------------------------------------------------------------- harnesses and models
def test_the_known_harnesses(api):
    assert set(api["HARNESSES"]) == {"claude", "codex", "opencode", "openclaw", "antigravity", "agy", "gemini", "hermes"}
    assert api["HARNESSES"]["agy"] == api["HARNESSES"]["antigravity"]
    for h in api["HARNESSES"].values():      # alias,UID on both: rename-safe
        assert h["task"].count(",") == 1 and h["tool"].count(",") == 1


def test_every_harness_has_its_task_and_its_model_list(api, repo_root):
    import yaml

    for name, h in api["HARNESSES"].items():
        task, tool = h["task"].split(",")[0], h["tool"].split(",")[0]
        assert (repo_root / "task" / task / "api_v1.py").is_file(), name
        models = yaml.safe_load((repo_root / "tool" / tool / "_desc_models.yaml").read_text(encoding = "utf-8"))
        assert isinstance(models.get("flags", {}).get("model"), list) and "{{model}}" in " ".join(models["flags"]["model"]), name
        names = [m["name"] for m in models["models"]]
        assert names and len(names) == len(set(names)), name
        # the UIDs in the map are the ones of the artifacts
        for kind, ref in (("task", h["task"]), ("tool", h["tool"])):
            meta = yaml.safe_load((repo_root / kind / ref.split(",")[0] / "_cmeta.yaml").read_text(encoding = "utf-8"))
            assert str(meta["artifact"]).split(",")[-1] == ref.split(",")[1], (name, kind)


def test_model_and_effort_are_split_and_turned_into_flags(CTask):
    t = CTask.__new__(CTask)
    assert CTask._split_model("claude-opus-5-5,high", "")[:2] == ("claude-opus-5-5", "high")
    assert CTask._split_model("claude-opus-5-5", "low")[:2] == ("claude-opus-5-5", "low")
    assert CTask._split_model("m,high", "low")[:2] == ("m", "low")                  # --effort wins
    desc = {"flags": {"model": ["--model", "{{model}}"], "effort": ["-c", "model_reasoning_effort={{effort}}"]}}
    flags, model_t, effort_t = t._native_flags(desc, "gpt-x", "high")
    assert flags == ["--model", "gpt-x", "-c", "model_reasoning_effort=high"]
    # a harness without an effort flag: the effort is not passed on
    flags, model_t, effort_t = t._native_flags({"flags": {"model": ["--model", "{{model}}"]}}, "gemini-x", "high")
    assert flags == ["--model", "gemini-x"]
