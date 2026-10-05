"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-ai task through the task engine, with a harness that calls no model: the project and its !AI folder, the
conversations (continue, --new, --conversation, the hand-over), the context sources (--context, ai_uses, this
machine's mapping in the config artifact task-run-ai), the seed, and the proposals and the guard that keep the
artifacts a project uses read-only for a run. Offline. The artifacts live in the local repository of the suite's
throwaway CMETA_HOME: projects in the category "tmp", the stand-in harness as a task "run-fake<id>" whose "session"
does what a small script says.
"""

import contextlib
import io
import json
import os
import pathlib
import re
import textwrap
import time
import uuid

import pytest

FAKE_HARNESS = '''
import os

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):
    """A stand-in for a coding agent: it keeps the prompt it was given, runs a script, writes an answer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, prompt = '', prompt_file = '', interactive = False, stats = True, output_file = '', stats_file = '',
            skip_output_file = False, yes = False, reproducible = False, resume = '', unparsed = None):
        if os.environ.get('RUN_FAKE_PROMPT'):
            with open(os.environ['RUN_FAKE_PROMPT'], 'w', encoding = 'utf-8') as f:
                f.write(prompt or '')
        if os.environ.get('RUN_FAKE_SCRIPT'):
            with open(os.environ['RUN_FAKE_SCRIPT'], encoding = 'utf-8') as f:
                exec(f.read(), {'os': os})
        if output_file and not interactive:     # like the real run tasks: an interactive session owns the terminal
            with open(output_file, 'w', encoding = 'utf-8') as f:
                f.write('# the stand-in harness\\n\\nan answer\\n')
        return {'return': 0, 'flags': list(unparsed or []), 'cwd': os.getcwd()}
'''


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    with io.open(str(path), "w", encoding = "utf-8", newline = "\n") as f:     # the same bytes on every OS
        f.write(text)
    return path


def read(path):
    return pathlib.Path(path).read_text(encoding = "utf-8")


class Lab:
    """The artifacts of one test module: a project, three artifacts with memory, and the stand-in harness."""

    def __init__(self, cm, scratch):
        self.cm, self.scratch = cm, scratch
        self.id = uuid.uuid4().hex[:6]
        self.harness = "fake" + self.id
        self.local = pathlib.Path(str(cm.home_path)) / "repos" / "local"
        self.config_dir = self.local / "config" / "task-run-ai"
        self.project = self.add("tmp", "run-ai-project-" + self.id)
        self.used = self.add("tmp", "run-ai-used-" + self.id)
        self.other = self.add("tmp", "run-ai-other-" + self.id)
        self.empty = self.add("tmp", "run-ai-empty-" + self.id)
        task = self.add("task", "run-" + self.harness)
        put(task / "_desc.yaml", "cache: False\n")
        put(task / "api_v1.py", FAKE_HARNESS)
        for artifact in (self.used, self.other):
            put(artifact / "!AI" / "memory" / "MEMORY.md", "- [One](one.md) - the memory of %s\n" % artifact.name)
            put(artifact / "!AI" / "memory" / "one.md", "one\n")
        put(self.used / "!AI" / "skills" / "s1" / "SKILL.md", "---\nname: s1\ndescription: a skill\n---\nbody\n")
        self.uses()

    def add(self, category, alias):
        r = self.cm.access({"category": category, "command": "add", "arg1": "local:" + alias, "con": False, "quiet": True, "yaml": True})
        assert r["return"] == 0, r.get("error")
        return pathlib.Path(r["path"])

    def cref(self, artifact):
        return "tmp::" + artifact.name

    def uid(self, artifact):
        import yaml
        return str(yaml.safe_load(read(artifact / "_cmeta.yaml"))["artifact"]).split(",")[-1]

    def uses(self, *artifacts):
        """The ai_uses list of the project's _desc.yaml."""
        put(self.project / "_desc.yaml", "ai_uses:" + ("".join("\n- " + self.cref(a) for a in artifacts) if artifacts else " []") + "\n")

    def run(self, **params):
        request = {"category": "task", "command": "run", "arg1": "run-ai", "project": self.cref(self.project),
                   "harness": self.harness, "con": False, "prompt": "x"}
        request.update(params)
        return self.cm.access(request)

    def config(self, data = None):
        """The data of the config artifact task-run-ai (which must exist: `cx config set` created it)."""
        put(self.config_dir / "data.json", json.dumps(data or {}, indent = 2))

    def clean(self):
        """A project as before its first run, and no machine-local setting."""
        import shutil
        shutil.rmtree(self.project / "!AI", ignore_errors = True)
        self.uses()
        if self.config_dir.is_dir():
            self.config()


@pytest.fixture(scope = "module")
def lab(cm, tmp_path_factory):
    return Lab(cm, tmp_path_factory.mktemp("run-ai"))


@pytest.fixture
def fresh(lab, monkeypatch):
    lab.clean()
    monkeypatch.setenv("RUN_FAKE_PROMPT", str(lab.scratch / "prompt.txt"))
    monkeypatch.delenv("RUN_FAKE_SCRIPT", raising = False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(lab.scratch / "claude-config"))
    yield lab
    lab.clean()


def kinds(result):
    return sorted((pathlib.Path(s["root"]).name, s["kind"]) for s in result.get("context") or [])


def session(lab, monkeypatch, script):
    """What the stand-in harness does in its next run."""
    monkeypatch.setenv("RUN_FAKE_SCRIPT", str(put(lab.scratch / "script.py", textwrap.dedent(script))))


# ---------------------------------------------------------------------------------------------- the project and a run
def test_dry_run_shows_everything_and_creates_nothing(fresh):
    r = fresh.run(dry_run = True, prompt = "what is in this folder?")
    assert r["return"] == 0, r.get("error")
    assert r["dry_run"] is True and r["harness"] == fresh.harness and r["task"] == "run-" + fresh.harness
    assert os.path.normcase(r["project"]) == os.path.normcase(str(fresh.project))
    assert r["cref"].startswith("tmp,") and r["cref"].endswith("::%s,%s" % (fresh.project.name, fresh.uid(fresh.project)))
    assert r["conversation_how"] == "new" and r["tokens_estimated"] > 0 and r["token_limit"] == 30000
    assert "what is in this folder?" in r["params"]["prompt"] and "run through cMeta run-ai" in r["params"]["prompt"]
    assert not (fresh.project / "!AI").exists(), "a dry run creates nothing"


def test_a_run_keeps_its_records_in_the_project_and_the_next_one_continues(fresh):
    r1 = fresh.run(prompt = "remember the word heron. Reply with one line only")
    assert r1["return"] == 0, r1.get("error")
    ai = fresh.project / "!AI"
    assert os.path.normcase(r1["ai_root"]) == os.path.normcase(str(ai)) and (ai / "memory").is_dir()
    conversation = r1["conversation"]
    assert re.fullmatch(r"\d{8}-\d{6}(-\d+)?", conversation)
    assert (ai / "log" / (conversation + ".conversation.json")).is_file() and pathlib.Path(r1["transcript"]).is_file()
    record = read(r1["record"])
    assert "| harness | `%s`" % fresh.harness in record and "| return | 0 |" in record and "new" in record
    # the harness worked in the project folder and was told where it is
    prompt = read(fresh.scratch / "prompt.txt")
    assert prompt.endswith("remember the word heron. Reply with one line only") and str(ai).replace("\\", "/") + "/memory/" in prompt
    assert "starts the new conversation " + conversation in prompt

    # the next run continues that conversation: this harness keeps no session of its own, so it is handed the transcript
    r2 = fresh.run(prompt = "which word?")
    assert r2["return"] == 0 and r2["conversation"] == conversation
    prompt = read(fresh.scratch / "prompt.txt")
    assert prompt.startswith("You continue conversation %s of this project" % conversation) and conversation + ".transcript.md" in prompt
    assert "continues the conversation " + conversation in prompt and prompt.endswith("which word?")
    # how the conversation began is not repeated in front of the new request: it would read as an instruction
    assert "Reply with one line only" not in prompt
    data = json.loads(read(ai / "log" / (conversation + ".conversation.json")))
    assert [run["prompt"] for run in data["runs"]] == ["remember the word heron. Reply with one line only", "which word?"]
    assert data["runs"][0]["return"] == 0 and data["runs"][1]["handover"] is True


def test_new_conversations_and_picking_one(fresh):
    first = fresh.run(prompt = "the first thread")["conversation"]
    second = fresh.run(prompt = "another thread", new = True)["conversation"]      # at once: the same second
    third = fresh.run(prompt = "one more", new = True)["conversation"]
    assert len({first, second, third}) == 3, "runs started within one second must not share their records"
    assert fresh.run(prompt = "go on")["conversation"] == third                     # the one started last
    time.sleep(1.1)                                                                 # the times are kept to the second
    assert fresh.run(prompt = "go on")["conversation"] == third                     # the latest activity
    time.sleep(1.1)
    assert fresh.run(prompt = "back", conversation = first)["conversation"] == first

    listing = fresh.run(conversations = True)
    assert listing["return"] == 0
    assert [c["id"] for c in listing["conversations"]] == [first, third, second]     # newest activity first
    assert "the first thread" in listing["text"] and "--conversation=<id>" in listing["text"]

    r = fresh.run(prompt = "x", conversation = "19990101")
    assert r["return"] > 0 and "no conversation" in r["error"]

    before = sorted(p.name for p in (fresh.project / "!AI" / "log").iterdir())
    r = fresh.run(prompt = "not recorded", no_log = True)
    assert r["return"] == 0 and r["conversation"] == "" and r["record"] == ""
    assert sorted(p.name for p in (fresh.project / "!AI" / "log").iterdir()) == before


def test_after_an_interactive_run_the_next_harness_is_handed_the_conversation(fresh):
    """An interactive session leaves no output file: whether there is a conversation to hand over is what the
    transcript exported from the harnesses' stores, which must be saved with the conversation."""
    ai_log = fresh.project / "!AI" / "log"
    sid = "11111111-2222-4333-8444-555555555555"
    claude = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(str(fresh.project)))
    put(claude / (sid + ".jsonl"), json.dumps({"type": "user", "timestamp": "2026-01-01T10:00:00.000Z", "message": {"content": "the word is heron"}}) + "\n"
        + json.dumps({"type": "assistant", "timestamp": "2026-01-01T10:00:05.000Z", "message": {"content": [{"type": "text", "text": "Noted: heron."}]}}) + "\n")
    # a conversation held so far by an interactive claude session (no output file, nothing exported yet)
    put(ai_log / "20260101-100000.conversation.json", json.dumps({
        "id": "20260101-100000", "project": str(fresh.project), "cref": "", "started": "2026-01-01T10:00:00", "updated": "2026-01-01T10:01:00",
        "title": "interactive session 20260101-100000", "runs": [{"stamp": "20260101-100000", "harness": "claude", "mode": "interactive", "session": sid}],
        "sessions": {"claude": {"id": sid, "started": "2026-01-01T10:00:00", "runs": 1}}}))
    try:
        r = fresh.run(prompt = "", interactive = True)           # another interactive session, with the stand-in harness
        assert r["return"] == 0 and r["conversation"] == "20260101-100000", r.get("error")
        assert not list(ai_log.glob("*.%s.output.txt" % fresh.harness))
        data = json.loads(read(ai_log / "20260101-100000.conversation.json"))
        assert data["sessions"]["claude"]["exported"] == 2, "what the transcript exported is saved with the conversation"
        assert "Noted: heron." in read(ai_log / "20260101-100000.transcript.md")

        r = fresh.run(prompt = "which word?")
        prompt = read(fresh.scratch / "prompt.txt")
        assert prompt.startswith("You continue conversation 20260101-100000 of this project"), prompt[:300]
    finally:
        import shutil
        shutil.rmtree(claude, ignore_errors = True)


def test_the_harness_must_exist_and_the_models_are_listed(fresh):
    r = fresh.run(harness = "no-such-harness-" + fresh.id)
    assert r["return"] > 0 and "run-no-such-harness-" in r["error"] and "claude" in r["error"]
    assert not (fresh.project / "!AI").exists(), "refused before anything is written"

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = fresh.cm.access({"category": "task", "command": "run", "arg1": "run-ai", "list_models": True, "con": True})
    assert r["return"] == 0, r.get("error")
    for harness in ("claude", "codex", "opencode", "openclaw", "antigravity", "gemini"):
        assert 'the harness "%s"' % harness in out.getvalue(), harness

    r = fresh.run(harness = "codex", model = "gpt-test,high", dry_run = True)
    assert r["return"] == 0 and r["model"] == "gpt-test" and r["effort"] == "high"
    assert r["model_flags"] == ["--model", "gpt-test", "-c", "model_reasoning_effort=high"]
    assert any("not in _desc_models.yaml" in note for note in r["notes"])              # a warning, never an error
    r = fresh.run(harness = "gemini", model = "gemini-3.1-pro-preview,high", dry_run = True)
    assert r["model_flags"] == ["--model", "gemini-3.1-pro-preview"]
    assert any("no effort flag" in note for note in r["notes"])


# ---------------------------------------------------------------------------------------------- context
def test_context_entries_are_crefs_or_claude_folders_separated_by_semicolons(fresh):
    r = fresh.run(dry_run = True, context = fresh.cref(fresh.used))
    assert r["return"] == 0 and kinds(r) == [(fresh.used.name, "context")]

    full = "tmp,%s::%s,%s" % (r["cref"].split("::")[0].split(",")[1], fresh.used.name, fresh.uid(fresh.used))     # commas inside
    r = fresh.run(dry_run = True, context = "%s; %s" % (full, fresh.cref(fresh.other)))
    assert kinds(r) == [(fresh.other.name, "context"), (fresh.used.name, "context")]

    r = fresh.run(dry_run = True, context = "claude:%s;nonsense;%s;tmp::no-such-artifact" % (fresh.scratch / "no-such-folder", fresh.cref(fresh.empty)))
    assert r["return"] == 0 and r["context"] == []
    skipped = dict(r["context_skipped"])
    assert len(skipped) == 4 and "not a cRef" in skipped["nonsense"] and skipped["tmp::no-such-artifact"] == "not found"
    assert any("no !AI" in why for why in skipped.values()) and any("no native Claude memory" in why for why in skipped.values())


def test_ai_uses_of_the_project_and_its_depth(fresh):
    fresh.uses(fresh.used)
    put(fresh.used / "_desc.yaml", "ai_uses:\n- %s\n" % fresh.cref(fresh.other))
    try:
        r = fresh.run(dry_run = True)
        assert kinds(r) == [(fresh.used.name, "ai_uses")]
        assert r["context"][0]["skills"] and r["context"][0]["has_memory"]
        # the source's index reaches the harness, with the links made absolute
        assert "the memory of " + fresh.used.name in r["params"]["prompt"]
        assert str(fresh.used / "!AI" / "memory" / "one.md").replace("\\", "/") in r["params"]["prompt"]
        r = fresh.run(dry_run = True, context_depth = 2)
        assert kinds(r) == [(fresh.other.name, "ai_uses, depth 2"), (fresh.used.name, "ai_uses")]
        assert fresh.run(dry_run = True, skip_ai_uses = True)["context"] == []
        r = fresh.run(dry_run = True, context_depth = 2, context_limit = 1)
        assert len(r["context"]) == 1 and "over --context_limit=1" in dict(r["context_skipped"]).values()
        r = fresh.run(dry_run = True, context_depth = "2", context_limit = "1")      # as the command line gives them
        assert r["return"] == 0 and len(r["context"]) == 1, r.get("error")
        r = fresh.run(dry_run = True, max_context_tokens = 5)
        assert r["token_limit"] == 5 and r["tokens_estimated"] > 5
        r = fresh.run(max_context_tokens = 5)                           # nobody to ask: the run is refused
        assert r["return"] > 0 and "over the limit" in r["error"] and not (fresh.project / "!AI").exists()
    finally:
        (fresh.used / "_desc.yaml").unlink()


def test_this_machines_mapping_in_the_config_artifact(fresh, task_namespace):
    # reading the mapping never creates the config artifact ("config get" would)
    assert fresh.run(dry_run = True)["context"] == []
    if not fresh.config_dir.is_dir():
        assert not list(fresh.local.rglob("task-run-ai"))

    repository = str(task_namespace("run-ai")["CTask"]._repo_meta(str(fresh.project))["artifact"])
    r = fresh.cm.access({"category": "config", "command": "set", "arg1": "task-run-ai", "con": False,
                         "meta": {"local_ai_uses": {repository: fresh.cref(fresh.used)}}})
    assert r["return"] == 0, r.get("error")
    assert fresh.config_dir.is_dir()

    r = fresh.run(dry_run = True)                                       # every artifact of the repository
    assert kinds(r) == [(fresh.used.name, "ai_uses, machine-local: " + repository)]
    assert r["context"][0]["stage_dir"].endswith("%s--%s" % (fresh.used.name, fresh.uid(fresh.used)))      # guarded like any used artifact
    assert fresh.run(dry_run = True, skip_ai_uses = True)["context"] == []

    fresh.config({"local_ai_uses": {fresh.uid(fresh.project): "%s;%s" % (fresh.cref(fresh.used), fresh.cref(fresh.other))}})
    assert [name for name, kind in kinds(fresh.run(dry_run = True))] == sorted([fresh.used.name, fresh.other.name])

    fresh.config({"local_ai_uses": {fresh.cref(fresh.project): fresh.cref(fresh.other)}})
    assert kinds(fresh.run(dry_run = True)) == [(fresh.other.name, "ai_uses, machine-local: " + fresh.cref(fresh.project))]
    assert fresh.run(dry_run = True, project = fresh.cref(fresh.empty))["context"] == []       # a key of one artifact

    fresh.config({"max_context_tokens": 12345})
    r = fresh.run(dry_run = True)
    assert r["token_limit"] == 12345 and "task-run-ai" in r["token_limit_from"]


def test_the_seed_and_no_seed(fresh):
    native = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(str(fresh.project))) / "memory"
    put(native / "MEMORY.md", "- [N](n.md) - kept by Claude Code\n")
    put(native / "n.md", "n\n")
    try:
        r = fresh.run(harness = "claude", dry_run = True)
        assert r["return"] == 0, r.get("error")
        assert any("would seed 2 memory file(s)" in note for note in r["notes"])
        assert r["settings"]["autoMemoryDirectory"] == str(fresh.project / "!AI" / "memory").replace("\\", "/")
        assert "--session-id" in r["flags"] and "--append-system-prompt-file" in r["flags"]
        r = fresh.run(harness = "claude", dry_run = True, no_seed = True)
        assert any("NOT copied (--no_seed)" in note for note in r["notes"])
        assert not (fresh.project / "!AI").exists()
    finally:
        import shutil
        shutil.rmtree(native.parent)


# ---------------------------------------------------------------------------------------------- proposals and the guard
def test_the_artifacts_a_project_uses_are_read_only_for_a_run(fresh, monkeypatch):
    lab = fresh
    lab.uses(lab.used)
    used_ai, project_ai = lab.used / "!AI", lab.project / "!AI"

    def used_state():
        return {str(p.relative_to(used_ai)).replace(os.sep, "/"): read(p) for p in sorted(used_ai.rglob("*"))
                if p.is_file() and "log" not in p.relative_to(used_ai).parts}

    original = used_state()
    try:
        # the dry run names the staging folder of the used artifact
        r = lab.run(dry_run = True)
        stage = pathlib.Path(r["context"][0]["stage_dir"])
        assert stage.name == "%s--%s" % (lab.used.name, lab.uid(lab.used)) and stage.parent == project_ai / "pending"

        # a session that follows the rule: it stages a proposal, and writes its own memory freely
        session(lab, monkeypatch, '''
            d = r"%s"
            os.makedirs(os.path.join(d, 'memory'), exist_ok = True)
            open(os.path.join(d, 'memory', 'two.md'), 'w', encoding = 'utf-8').write('two\\n')
            open(os.path.join(d, 'memory', 'MEMORY.md.append'), 'w', encoding = 'utf-8').write('- [Two](two.md) - second\\n')
            open(os.path.join(d, '_note.md'), 'w', encoding = 'utf-8').write('a second fact worth keeping\\n')
            os.makedirs(r"%s", exist_ok = True)
            open(os.path.join(r"%s", 'own.md'), 'w', encoding = 'utf-8').write('its own memory\\n')
        ''' % (stage, project_ai / "memory", project_ai / "memory"))
        r = lab.run(prompt = "please note a second fact")
        prompt = read(lab.scratch / "prompt.txt")
        assert "Read-only means" in prompt and str(stage).replace("\\", "/") in prompt and "--apply_pending" in prompt
        assert r["return"] == 0 and r["pending"] == 2 and r["context_changes"] == [] and used_state() == original
        assert (project_ai / "memory" / "own.md").is_file()

        # --pending lists them and changes nothing
        r = lab.run(pending = True)
        assert sorted((p["rel"], p["action"]) for p in r["pending"]) == [("memory/MEMORY.md", "append"), ("memory/two.md", "new")]
        assert "+ - [Two](two.md) - second" in r["text"] and "a second fact worth keeping" in r["text"]
        assert used_state() == original and not r["applied"]

        # --apply_pending with nobody to ask applies nothing; -q applies and leaves the records
        r = lab.run(apply_pending = True)
        assert r["return"] == 0 and not r["applied"] and len(r["left"]) == 2 and used_state() == original and stage.is_dir()
        r = lab.run(apply_pending = True, quiet = True)
        state = used_state()
        assert len(r["applied"]) == 2 and state["memory/two.md"] == "two\n"
        assert state["memory/MEMORY.md"] == original["memory/MEMORY.md"] + "- [Two](two.md) - second\n"
        assert len(list((used_ai / "log").glob("*.applied.json"))) == 1 and list((project_ai / "log").glob("*.apply_pending.md"))
        assert not (project_ai / "pending").exists()
        applied = used_state()

        # a session that edits the used artifact directly: put back, and what it wrote waits as proposals
        rogue = '''
            m = r"%s"
            open(os.path.join(m, 'memory', 'one.md'), 'w', encoding = 'utf-8').write('one, rewritten by the session\\n')
            open(os.path.join(m, 'memory', 'rogue.md'), 'w', encoding = 'utf-8').write('written without asking\\n')
            os.remove(os.path.join(m, 'skills', 's1', 'SKILL.md'))
        ''' % used_ai
        session(lab, monkeypatch, rogue)
        r = lab.run(prompt = "go")
        assert sorted((c["rel"], c["what"]) for c in r["context_changes"]) == [
            ("memory/one.md", "changed"), ("memory/rogue.md", "added"), ("skills/s1/SKILL.md", "deleted")]
        assert r["return"] == 0 and used_state() == applied and r["pending"] == 3
        assert read(stage / "memory" / "one.md") == "one, rewritten by the session\n"
        assert (stage / "memory" / "rogue.md").is_file() and (stage / "skills" / "s1" / "SKILL.md.delete").is_file()
        assert "context guard: 3 direct change(s)" in read(r["record"])

        # the user may still approve them
        r = lab.run(apply_pending = True, yes = True)
        state = used_state()
        assert len(r["applied"]) == 3 and state["memory/one.md"] == "one, rewritten by the session\n"
        assert "memory/rogue.md" in state and "skills/s1/SKILL.md" not in state and not (project_ai / "pending").exists()

        # report: listed and left; off: not looked at; an unknown mode is an error before anything runs
        put(used_ai / "memory" / "one.md", "one\n")
        put(used_ai / "skills" / "s1" / "SKILL.md", "body\n")
        (used_ai / "memory" / "rogue.md").unlink()
        base = used_state()
        time.sleep(0.5)      # the same content the user approved a moment ago, written again: past the clock slack
        r = lab.run(prompt = "go", context_guard = "report")
        assert len(r["context_changes"]) == 3 and all(c["outcome"] == "reported" for c in r["context_changes"])
        assert used_state() != base and not (project_ai / "pending").exists()
        monkeypatch.delenv("RUN_FAKE_SCRIPT")
        r = lab.run(prompt = "go", context_guard = "off")
        assert r["return"] == 0 and r["context_changes"] == [] and r["context_guard"] == "off"
        r = lab.run(prompt = "go", context_guard = "sometimes")
        assert r["return"] > 0 and "context_guard" in r["error"]

        # a project that uses nothing runs as before
        lab.uses()
        r = lab.run(prompt = "go")
        assert r["return"] == 0 and r["context_changes"] == [] and r["pending"] == 0
    finally:
        import shutil
        shutil.rmtree(used_ai)
        for path, text in original.items():
            put(used_ai / path, text)
