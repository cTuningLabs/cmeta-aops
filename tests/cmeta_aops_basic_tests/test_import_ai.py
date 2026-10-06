"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The import-ai task: memories and skills copied into the !AI folder of a project - what is copied, skipped and
replaced, what happens to the index MEMORY.md, the plugin manifest and the import record. Offline: the task runs
through the engine on folders of a temporary directory (the project is the current directory).
"""

import json
import os
import pathlib
import re

import pytest

MEMORY = "---\nname: {name}\ndescription: {description}\nmetadata:\n  type: project\n---\n\n{body}\n"
SKILL = "---\nname: {name}\ndescription: what the skill {name} is for\n---\n\nThe steps.\n"


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(text, encoding = "utf-8")
    return path


def read(path):
    return pathlib.Path(path).read_text(encoding = "utf-8")


@pytest.fixture
def world(cm, tmp_path, monkeypatch):
    """A project folder (the current directory), a source of memories with an index of its own, and two skills."""
    project = tmp_path / "My Project, v2"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    source = tmp_path / "source"
    put(source / "MEMORY.md", "- [The build](build.md) — how the build is started\n")
    put(source / "build.md", MEMORY.format(name = "build", description = "from the front matter", body = "Run make."))
    put(source / "release.md", MEMORY.format(name = "release-steps", description = "the steps of a release", body = "Tag, then push."))
    put(tmp_path / "skills" / "deploy" / "SKILL.md", SKILL.format(name = "deploy"))
    put(tmp_path / "skills" / "deploy" / "files" / "check.sh", "echo ok\n")
    put(tmp_path / "skills" / "review" / "SKILL.md", SKILL.format(name = "review"))

    def run(**params):
        request = {"category": "task", "command": "run", "arg1": "import-ai", "project": ".", "con": False}
        request.update(params)
        return cm.access(request)

    run.project, run.ai, run.source, run.skills, run.tmp = project, project / "!AI", source, tmp_path / "skills", tmp_path
    return run


def test_memories_are_copied_with_their_index_lines_and_a_record(world):
    r = world(memories = str(world.source))
    assert r["return"] == 0, r.get("error")
    assert r["memories"] == {"copied": 2, "replaced": 0, "skipped": 0} and r["index_entries"] == 2 and r["missing"] == []
    assert os.path.normcase(r["project"]) == os.path.normcase(str(world.project)) and r["cref"] == ""
    memory = world.ai / "memory"
    assert sorted(p.name for p in memory.iterdir()) == ["MEMORY.md", "build.md", "release.md"]
    assert read(memory / "build.md") == read(world.source / "build.md")              # never edited
    # the line of the source index when it has one, else one made from the front matter
    assert read(memory / "MEMORY.md") == ("- [The build](build.md) — how the build is started\n"
                                          "- [release-steps](release.md) — the steps of a release\n")
    record = read(r["record"])
    assert pathlib.Path(r["record"]).parent == world.ai / "log" and r["record"].endswith(".import.md")
    assert "| memory | `build.md` |" in record and "copied" in record and str(world.source) in record

    again = world(memories = str(world.source))
    assert again["memories"] == {"copied": 0, "replaced": 0, "skipped": 2}
    assert read(memory / "MEMORY.md").count("\n") == 2


def test_a_hand_kept_index_keeps_its_order_and_its_headings(world):
    index = world.ai / "memory" / "MEMORY.md"
    put(world.ai / "memory" / "zebra.md", MEMORY.format(name = "zebra", description = "z", body = "z"))
    put(world.ai / "memory" / "apple.md", MEMORY.format(name = "apple", description = "a", body = "a"))
    kept = "# What this project knows\n\n- [Zebra first, on purpose](zebra.md) — z\n- [Apple](apple.md) — a\n\nNotes below the list stay too.\n"
    put(index, kept)

    r = world(memories = str(world.source / "release.md"))            # one file, no index next to... the source index has no line for it
    assert r["return"] == 0 and r["memories"]["copied"] == 1 and r["index_entries"] == 3
    assert read(index) == kept + "- [release-steps](release.md) — the steps of a release\n"

    # an entry without a file is not removed, and a file without an entry gets one
    put(world.ai / "memory" / "orphan.md", MEMORY.format(name = "orphan", description = "written by hand", body = "o"))
    (world.ai / "memory" / "apple.md").unlink()
    r = world(memories = str(world.source / "build.md"))
    text = read(index)
    assert text.startswith(kept) and "(apple.md)" in text
    assert text.endswith("- [The build](build.md) — how the build is started\n- [orphan](orphan.md) — written by hand\n")


def test_overwrite_renews_the_entry_where_it_stands(world):
    assert world(memories = str(world.source))["return"] == 0
    index = world.ai / "memory" / "MEMORY.md"
    put(index, "- [release-steps](release.md) — the steps of a release\n# builds\n- [The build](build.md) — how the build is started\n")
    put(world.source / "build.md", MEMORY.format(name = "build", description = "from the front matter", body = "Run make -j."))
    put(world.source / "MEMORY.md", "- [The build](build.md) — started with make -j now\n")
    old = os.path.getmtime(world.ai / "memory" / "build.md") - 100
    os.utime(world.source / "build.md", (old, old))                   # the copy in !AI is the newer file

    r = world(memories = str(world.source))
    assert r["memories"] == {"copied": 0, "replaced": 0, "skipped": 2}
    assert "Run make." in read(world.ai / "memory" / "build.md")
    assert "the copy in !AI is newer" in read(r["record"])

    r = world(memories = str(world.source), overwrite = True)
    assert r["memories"] == {"copied": 0, "replaced": 1, "skipped": 1}
    assert "Run make -j." in read(world.ai / "memory" / "build.md")
    assert read(index) == "- [release-steps](release.md) — the steps of a release\n# builds\n- [The build](build.md) — started with make -j now\n"


def test_a_newer_source_replaces_the_copy(world):
    assert world(memories = str(world.source))["return"] == 0
    put(world.source / "release.md", MEMORY.format(name = "release-steps", description = "the steps of a release", body = "Tag, test, then push."))
    new = os.path.getmtime(world.ai / "memory" / "release.md") + 100
    os.utime(world.source / "release.md", (new, new))
    r = world(memories = str(world.source))
    assert r["memories"] == {"copied": 0, "replaced": 1, "skipped": 1}
    assert "Tag, test, then push." in read(world.ai / "memory" / "release.md")


def test_skills_are_copied_whole_with_a_manifest_and_the_index_is_left_alone(world):
    index = put(world.ai / "memory" / "MEMORY.md", "# kept by hand\n\n- [B](b.md) — second on purpose\n- [A](a.md) — first\n")
    put(world.ai / "memory" / "a.md", "a\n")
    put(world.ai / "memory" / "b.md", "b\n")
    before = index.read_bytes()

    r = world(skills = str(world.skills))                              # a folder of skill folders
    assert r["return"] == 0, r.get("error")
    assert r["skills"] == {"copied": 2, "replaced": 0, "skipped": 0} and r["memories"]["copied"] == 0
    assert (world.ai / "skills" / "deploy" / "files" / "check.sh").is_file() and (world.ai / "skills" / "review" / "SKILL.md").is_file()
    manifest = json.loads(read(world.ai / ".claude-plugin" / "plugin.json"))
    assert manifest["name"] == "my-project-v2" and manifest["version"]
    assert index.read_bytes() == before, "an import of skills only must not rewrite a hand-kept index"

    # a skill that changed at its source: left alone, then replaced on request
    put(world.skills / "deploy" / "SKILL.md", SKILL.format(name = "deploy") + "One more step.\n")
    (world.skills / "deploy" / "files" / "check.sh").unlink()
    r = world(skills = str(world.skills / "deploy"))                   # one skill folder
    assert r["skills"] == {"copied": 0, "replaced": 0, "skipped": 1}
    assert "One more step." not in read(world.ai / "skills" / "deploy" / "SKILL.md")
    r = world(skills = str(world.skills / "deploy"), overwrite = True)
    assert r["skills"] == {"copied": 0, "replaced": 1, "skipped": 0}
    assert "One more step." in read(world.ai / "skills" / "deploy" / "SKILL.md")
    assert not (world.ai / "skills" / "deploy" / "files" / "check.sh").exists(), "a replaced skill is the source's folder, nothing left over"
    assert index.read_bytes() == before


def test_a_skill_that_changed_below_its_top_folder_is_not_identical(world):
    assert world(skills = str(world.skills / "deploy"))["skills"]["copied"] == 1
    put(world.skills / "deploy" / "files" / "check.sh", "echo ok, and more\n")         # only a file in a subfolder changes
    r = world(skills = str(world.skills / "deploy"))
    assert r["skills"] == {"copied": 0, "replaced": 0, "skipped": 1} and "already there and different" in read(r["record"])
    r = world(skills = str(world.skills / "deploy"), overwrite = True)
    assert r["skills"]["replaced"] == 1 and read(world.ai / "skills" / "deploy" / "files" / "check.sh") == "echo ok, and more\n"
    assert world(skills = str(world.skills / "deploy"))["skills"] == {"copied": 0, "replaced": 0, "skipped": 1}     # identical now


def test_the_source_of_each_skill_is_recorded_and_run_ai_sees_a_copy_go_apart(world, task_namespace):
    drift = task_namespace("run-ai")["CTask"]._skill_drift
    skills = world.ai / "skills"
    assert world(skills = str(world.skills))["skills"]["copied"] == 2
    sources = json.loads(read(skills / ".sources.json"))
    assert sorted(sources) == ["deploy", "review"]
    assert os.path.normcase(sources["deploy"]["source"]) == os.path.normcase(str(world.skills / "deploy"))
    assert len(sources["deploy"]["hash"]) == 64 and sources["deploy"]["imported"]
    assert drift(str(skills)) == []

    # the source changes: the copy is older
    put(world.skills / "deploy" / "files" / "check.sh", "echo ok, and more\n")
    assert [(n, c) for n, c, s in drift(str(skills))] == [("deploy", "source")]
    assert world(skills = str(world.skills / "deploy"), overwrite = True)["skills"]["replaced"] == 1
    assert drift(str(skills)) == []
    # the copy changes here: said so, differently; then both
    put(skills / "review" / "SKILL.md", SKILL.format(name = "review") + "A local step.\n")
    assert [(n, c) for n, c, s in drift(str(skills))] == [("review", "copy")]
    put(world.skills / "review" / "SKILL.md", SKILL.format(name = "review") + "Another step.\n")
    assert [(n, c) for n, c, s in drift(str(skills))] == [("review", "both")]
    # a source that is not on this machine says nothing; a cache folder is no change
    import shutil
    shutil.rmtree(str(world.skills / "review"))
    put(skills / "deploy" / "__pycache__" / "x.pyc", "cache")
    assert drift(str(skills)) == []
    assert drift(str(world.tmp / "no-skills-here")) == []


def test_an_index_with_a_byte_order_mark_and_overwrite_of_unchanged_memories(world):
    memory = world.ai / "memory"
    put(memory / "build.md", read(world.source / "build.md"))                        # the same file as the source
    index = memory / "MEMORY.md"
    index.write_bytes("﻿- [Build, as I call it](build.md) — kept by hand\n".encode("utf-8"))
    r = world(memories = str(world.source), overwrite = True)
    assert r["memories"] == {"copied": 1, "replaced": 0, "skipped": 1}
    text = index.read_bytes().decode("utf-8")
    assert text.count("(build.md)") == 1, "the first line of an index with a BOM is an entry like the others"
    assert "Build, as I call it" in text, "--overwrite renews the entries of replaced memories only"
    assert "(release.md)" in text


def test_dry_run_plan_and_several_sources(world):
    plan = put(world.tmp / "plans" / "import-plan.yaml", "memories:\n  - ../source/release.md\nskills:\n  - ../skills/review\n")
    r = world(plan = str(plan), memories = "%s; %s" % (world.source / "build.md", world.tmp / "no-such-file.md"), dry_run = True)
    assert r["return"] == 0 and r["dry_run"] is True and r["record"] == ""
    assert r["memories"]["copied"] == 2 and r["skills"]["copied"] == 1 and r["missing"] == [str(world.tmp / "no-such-file.md")]
    assert not world.ai.exists(), "a dry run creates nothing"

    r = world(plan = str(plan), memories = "%s; %s" % (world.source / "build.md", world.tmp / "no-such-file.md"))
    assert r["return"] == 0 and sorted(p.name for p in (world.ai / "memory").iterdir()) == ["MEMORY.md", "build.md", "release.md"]
    assert (world.ai / "skills" / "review" / "SKILL.md").is_file() and "not found" in read(r["record"])


def test_the_memory_claude_code_keeps_for_a_folder(world, task_namespace):
    work = world.tmp / "some work"
    work.mkdir()
    native = pathlib.Path(task_namespace("import-ai")["CTask"]._claude_memory_dirs(str(work))[0])
    assert native.parent.parent == world.tmp / "claude" / "projects" and native.name == "memory"
    put(native / "MEMORY.md", "- [Note](note.md) — kept by Claude Code\n")
    put(native / "note.md", MEMORY.format(name = "note", description = "d", body = "n"))
    r = world(claude_folder = str(work))
    assert r["return"] == 0 and r["memories"]["copied"] == 1
    assert read(world.ai / "memory" / "MEMORY.md") == "- [Note](note.md) — kept by Claude Code\n"

    r = world(claude_folder = str(world.tmp / "a folder claude never saw"))
    assert r["return"] > 0 and "no native Claude memory" in r["error"]

    # a path whose slug is longer than 200 characters: Claude Code cut it and appended a hash
    deep = world.tmp / ("d" * 120) / ("e" * 90)
    r = world(claude_folder = str(deep))
    assert r["return"] > 0 and "shortened slug" in r["error"]
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(str(deep)))
    native = world.tmp / "claude" / "projects" / (slug[:200] + "-a1b2c3") / "memory"
    try:
        put(native / "deep.md", MEMORY.format(name = "deep", description = "d", body = "n"))
    except OSError:
        pytest.skip("this file system does not take paths this long (Windows without LongPathsEnabled)")
    r = world(claude_folder = str(deep))
    assert r["return"] == 0 and r["memories"]["copied"] == 1 and (world.ai / "memory" / "deep.md").is_file()


def test_errors(world):
    r = world()
    assert r["return"] > 0 and "nothing to import" in r["error"]
    r = world(project = "not-a-cref", memories = str(world.source))
    assert r["return"] > 0 and "category::artifact" in r["error"]
    r = world(plan = str(world.tmp / "missing-plan.yaml"))
    assert r["return"] > 0 and "cannot be read" in r["error"]
