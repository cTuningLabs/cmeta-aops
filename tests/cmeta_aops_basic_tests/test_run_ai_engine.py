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
import threading
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
        return {'return': 0, 'flags': list(unparsed or []), 'cwd': os.getcwd(), 'output': 'an answer\\n'}
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
    assert not list((fresh.project / "!AI" / "log").glob("*.lock")), "the stamp reservations are released"

    before = sorted(p.name for p in (fresh.project / "!AI" / "log").iterdir())
    r = fresh.run(prompt = "not recorded", no_log = True)
    assert r["return"] == 0 and r["conversation"] == "" and r["record"] == ""
    assert sorted(p.name for p in (fresh.project / "!AI" / "log").iterdir()) == before


def test_openclaw_is_told_where_the_project_is_and_its_terminal_ui_gets_its_own_flags(fresh):
    # a one-prompt turn: "openclaw agent" takes the session id and the model
    r = fresh.run(dry_run = True, harness = "openclaw", model = "claude-cli/claude-sonnet-4-6,low", prompt = "read notes.txt")
    assert r["return"] == 0, r.get("error")
    flags = r["flags"]
    assert flags[flags.index("--session-id") + 1] == r["new_session"] and flags[flags.index("--model") + 1] == "claude-cli/claude-sonnet-4-6"
    assert flags[flags.index("--thinking") + 1] == "low"
    prompt = r["params"]["prompt"]
    # OpenClaw works in a workspace of its own: the orientation names the project folder; the request follows the mark
    assert "The project folder is %s" % str(fresh.project).replace("\\", "/") in prompt
    assert prompt.endswith("\n<!-- run-ai: the request of this run follows -->\nread notes.txt")
    # its terminal UI takes the session's key and no --model
    r = fresh.run(dry_run = True, harness = "openclaw", model = "claude-cli/claude-sonnet-4-6,low", interactive = True, prompt = "hi")
    assert r["return"] == 0, r.get("error")
    flags = r["flags"]
    assert flags[flags.index("--session") + 1] == "agent:main:explicit:" + r["new_session"]
    assert "--model" not in flags and "--session-id" not in flags and flags[flags.index("--thinking") + 1] == "low"
    assert any('"/model claude-cli/claude-sonnet-4-6"' in n for n in r["notes"])
    # other harnesses are not told about a workspace
    r = fresh.run(dry_run = True, prompt = "hi")
    assert "The project folder is" not in r["params"]["prompt"]


def test_summarize_writes_a_summary_that_the_next_hand_over_points_to(fresh):
    r = fresh.run(summarize = True)
    assert r["return"] > 0 and "no conversation" in r["error"]
    first = fresh.run(prompt = "remember the word heron")
    conversation, log = first["conversation"], fresh.project / "!AI" / "log"
    before = json.loads(read(log / (conversation + ".conversation.json")))

    r = fresh.run(summarize = True)
    assert r["return"] == 0, r.get("error")
    assert r["conversation"] == conversation and r["inline"] and r["runs"] == 1
    summary = read(r["summary"])
    assert pathlib.Path(r["summary"]).name == conversation + ".summary.md" and summary.rstrip().endswith("an answer")
    assert "run-ai --summarize" in summary and "as of run 1" in summary
    # the harness was given the transcript itself, and the conversation was not continued (nor moved up the list)
    prompt = read(fresh.scratch / "prompt.txt")
    assert prompt.startswith("Summarize conversation " + conversation) and "<transcript>" in prompt and "remember the word heron" in prompt
    after = json.loads(read(log / (conversation + ".conversation.json")))
    assert after["runs"] == before["runs"] and after["updated"] == before["updated"] and after["summary"]["runs"] == 1

    # this harness keeps no session: the next run is handed the summary first, then the transcript
    fresh.run(prompt = "which word?")
    prompt = read(fresh.scratch / "prompt.txt")
    assert "read its summary " in prompt and conversation + ".summary.md" in prompt and conversation + ".transcript.md" in prompt
    assert fresh.run(summarize = True, conversation = "19990101")["return"] > 0


def test_a_skill_copy_older_than_its_source_is_warned_about(fresh, task_namespace):
    tree_hash = task_namespace("run-ai")["CTask"]._tree_hash
    copy = put(fresh.project / "!AI" / "skills" / "deploy" / "SKILL.md", "---\nname: deploy\ndescription: d\n---\nold steps\n").parent
    source = put(fresh.scratch / "skill-source" / "deploy" / "SKILL.md", "---\nname: deploy\ndescription: d\n---\nnew steps\n").parent
    put(copy.parent / ".sources.json", json.dumps({"deploy": {"source": str(source), "imported": "2026-01-01T10:00:00", "hash": tree_hash(str(copy))}}))
    r = fresh.run(dry_run = True)
    warning = [n for n in r["notes"] if "deploy" in n and "WARNING" in n]
    assert len(warning) == 1 and "older than the one it was imported from" in warning[0] and "--overwrite" in warning[0]


def test_runs_started_at_once_reserve_distinct_stamps(tmp_path, task_namespace):
    # two terminals, or a script, start runs of one project within the same second: each reserves its stamp with an
    # exclusive file, so none shares another's records even when they all look before any of them has written
    CTask = task_namespace("run-ai")["CTask"]
    log = tmp_path / "!AI" / "log"
    gate = threading.Barrier(8)
    got = []

    def start():
        gate.wait()
        got.append(CTask._new_stamp(str(log), True))

    workers = [threading.Thread(target = start) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    stamps = [s for s, lock in got]
    assert len(set(stamps)) == 8 and all(pathlib.Path(lock).is_file() for s, lock in got)
    for s, lock in got:
        CTask._release_stamp(lock)
    assert not list(log.glob("*.lock"))

    # a lock left by a run that died long ago is cleared; a fresh one keeps its stamp taken
    put(log / "20000101-000000.lock", "")
    os.utime(str(log / "20000101-000000.lock"), (1, 1))
    stamp, lock = CTask._new_stamp(str(log), True)
    assert not (log / "20000101-000000.lock").exists() and pathlib.Path(lock).name == stamp + ".lock"
    again, lock2 = CTask._new_stamp(str(log), True)
    assert again != stamp
    assert CTask._new_stamp(str(log), False)[1] == ""          # no reservation: nothing written
    for one in (lock, lock2):
        CTask._release_stamp(one)
    assert not list(log.iterdir())


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

        # --trim_context: the sources are left out from the last (the deeper level first) until the estimate fits
        both = fresh.run(dry_run = True, context_depth = 2)
        one = fresh.run(dry_run = True)
        assert both["tokens_estimated"] > one["tokens_estimated"]
        r = fresh.run(dry_run = True, context_depth = 2, max_context_tokens = one["tokens_estimated"], trim_context = True)
        assert kinds(r) == [(fresh.used.name, "ai_uses")] and r["tokens_estimated"] <= one["tokens_estimated"]
        assert "left out to fit the token limit (--trim_context)" in dict(r["context_skipped"]).values()
        assert any("left out " + fresh.cref(fresh.other) in n or fresh.other.name in n for n in r["notes"] if "--trim_context" in n)
        r = fresh.run(dry_run = True, context_depth = 2, max_context_tokens = both["tokens_estimated"], trim_context = True)
        assert len(r["context"]) == 2 and not any("--trim_context" in n for n in r["notes"])      # it fits: nothing left out
        r = fresh.run(context_depth = 2, max_context_tokens = 5, trim_context = "true")           # even without sources too much
        assert r["return"] > 0 and "over the limit" in r["error"]
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

    # trim_context in the config: every run of this machine leaves sources out to fit the limit
    fresh.config({"local_ai_uses": {fresh.cref(fresh.project): fresh.cref(fresh.other)}, "max_context_tokens": 5, "trim_context": True})
    r = fresh.run(dry_run = True)
    assert r["context"] == [] and any("--trim_context" in n and fresh.other.name in n for n in r["notes"])


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


def test_the_write_mode_comes_from_the_flags_then_the_config_and_reaches_each_harness(fresh):
    lab = fresh
    lab.uses(lab.used)
    # the default: the harness asks, the used artifacts take proposals (and the user is asked about a direct change)
    r = lab.run(dry_run = True)
    assert (r["write"], r["write_from"], r["context_guard"]) == ("ask", "default", "ask") and "yes" not in r["params"]
    assert "Read-only means" in r["params"]["prompt"] and not any(n.startswith("write:") for n in r["notes"])
    # --yes is what it has always been: no questions, proposals for the used artifacts
    r = lab.run(dry_run = True, yes = True)
    assert (r["write"], r["write_from"], r["context_guard"]) == ("project", "--yes", "restore") and r["params"]["yes"] is True
    assert "Read-only means" in r["params"]["prompt"]
    # -w = --write=all: the used artifacts may be changed directly; the harness is told so
    for flags in ({"w": True}, {"write": "all"}, {"write": True}, {"write": "true"}):
        r = lab.run(dry_run = True, harness = "claude", **flags)
        assert (r["write"], r["context_guard"]) == ("all", "keep") and r["params"]["yes"] is True, flags
    r = lab.run(dry_run = True, w = True)                       # the stand-in harness gets the text in its prompt
    assert r["write_from"] == "-w" and "write access to those artifacts (--write=all)" in r["params"]["prompt"]
    assert "Read-only means" not in r["params"]["prompt"] and "a change to it is proposed under" not in r["params"]["prompt"]
    assert "yes" not in r["params"] and any("has no switch for its questions" in n for n in r["notes"])      # a harness run-ai does not know
    assert lab.run(dry_run = True, w = True, yes = True)["params"]["yes"] is True
    # an explicit guard wins over the mode's
    r = lab.run(dry_run = True, w = True, context_guard = "restore")
    assert (r["write"], r["context_guard"]) == ("all", "restore") and "Read-only means" in r["params"]["prompt"]

    # --write=none: each harness in its own read-only mode, --yes left out
    expected = {"claude": ["--permission-mode", "plan"], "codex": ["-c", 'sandbox_mode="read-only"'], "opencode": ["--agent", "plan"],
                "antigravity": ["--mode", "plan"], "gemini": ["--approval-mode", "plan"]}
    for harness, flags in expected.items():
        r = lab.run(dry_run = True, harness = harness, write = "none", yes = True)
        assert r["return"] == 0, r.get("error")
        k = r["flags"].index(flags[0])
        assert r["flags"][k:k + 2] == flags and "yes" not in r["params"] and r["context_guard"] == "restore", harness
        assert any(n.startswith("write: none") and "--yes is left out" in n for n in r["notes"])
    r = lab.run(dry_run = True, harness = "claude", write = "read-only", unparsed = ["--permission-mode", "acceptEdits"])
    assert r["flags"].count("--permission-mode") == 1 and any('the flags after "--" decide' in n for n in r["notes"])
    r = lab.run(dry_run = True, harness = "openclaw", write = "none")
    assert any("no read-only mode that run-ai knows" in n for n in r["notes"])
    assert "This run is read-only (--write=none)" in r["params"]["prompt"]
    assert "Read-only means" not in r["params"]["prompt"], "a read-only run stages no proposal either"
    r = lab.run(dry_run = True, write = "sometimes")
    assert r["return"] > 0 and "--write must be one of" in r["error"]

    # this machine's default is the config; a flag wins over it
    r = lab.cm.access({"category": "config", "command": "set", "arg1": "task-run-ai", "con": False, "meta": {"write": "all"}})
    assert r["return"] == 0, r.get("error")
    try:
        r = lab.run(dry_run = True)
        assert (r["write"], r["context_guard"]) == ("all", "keep") and "config task-run-ai" in r["write_from"]
        r = lab.run(dry_run = True, write = "ask")
        assert (r["write"], r["write_from"], r["context_guard"]) == ("ask", "--write=ask", "ask")
        assert lab.run(dry_run = True, write = "none")["write"] == "none"
        lab.config({"write": "now and then"})
        r = lab.run(dry_run = True)
        assert r["return"] > 0 and 'the key "write" of the config task-run-ai' in r["error"]
    finally:
        lab.config()


def test_write_all_keeps_a_direct_change_records_it_and_saves_the_version_before(fresh, monkeypatch):
    lab = fresh
    lab.uses(lab.used)
    used_ai, project_ai = lab.used / "!AI", lab.project / "!AI"
    original = {p: read(p) for p in used_ai.rglob("*") if p.is_file()}
    try:
        session(lab, monkeypatch, '''
            m = r"%s"
            open(os.path.join(m, 'memory', 'one.md'), 'w', encoding = 'utf-8').write('one, improved by the session\\n')
            open(os.path.join(m, 'memory', 'three.md'), 'w', encoding = 'utf-8').write('a new fact\\n')
            os.remove(os.path.join(m, 'skills', 's1', 'SKILL.md'))
        ''' % used_ai)
        r = lab.run(prompt = "tidy the shared memory", w = True)
        assert r["return"] == 0 and (r["write"], r["context_guard"]) == ("all", "keep") and r["pending"] == 0
        # the changes stay ...
        assert read(used_ai / "memory" / "one.md") == "one, improved by the session\n" and (used_ai / "memory" / "three.md").is_file()
        assert not (used_ai / "skills" / "s1" / "SKILL.md").exists() and not (project_ai / "pending").exists()
        changes = {c["rel"]: c for c in r["context_changes"]}
        assert sorted(changes) == ["memory/one.md", "memory/three.md", "skills/s1/SKILL.md"]
        assert all(c["outcome"].startswith("kept") for c in changes.values())
        # ... the versions before the run are in the project's log (nothing for a new file) ...
        stamp = pathlib.Path(r["record"]).name.split(".")[0]
        before = project_ai / "log" / (stamp + ".before") / ("%s--%s" % (lab.used.name, lab.uid(lab.used)))
        assert read(before / "memory" / "one.md") == "one\n" and (before / "skills" / "s1" / "SKILL.md").is_file()
        assert not (before / "memory" / "three.md").exists() and changes["memory/three.md"]["before"] == ""
        assert pathlib.Path(changes["memory/one.md"]["before"]) == before / "memory" / "one.md"
        # ... and the artifact has its own record of what was changed, from which project
        applied = [json.loads(read(p)) for p in (used_ai / "log").glob("*.applied.json")]
        assert len(applied) == 1 and sorted(a["rel"] for a in applied[0]["applied"]) == sorted(changes)
        record = read(r["record"])
        assert "| write | `all` (-w); context guard `keep` |" in record and "as --write=all allows" in record
    finally:
        import shutil
        shutil.rmtree(used_ai)
        for path, text in original.items():
            put(path, text)


def test_apply_pending_asks_for_all_changes_or_one_by_one(fresh, monkeypatch):
    lab = fresh
    lab.uses(lab.used)
    used_ai = lab.used / "!AI"
    original = {p: read(p) for p in used_ai.rglob("*") if p.is_file()}
    stage = pathlib.Path(lab.run(dry_run = True)["context"][0]["stage_dir"])
    try:
        put(stage / "memory" / "two.md", "two\n")
        put(stage / "memory" / "three.md", "three\n")
        # a terminal, and a user who answers "each", then yes to the first change and no to the second
        answers = iter(["e", "n", "y"])
        monkeypatch.setattr("builtins.input", lambda prompt = "": next(answers))
        monkeypatch.setattr("sys.stdin", type("Terminal", (), {"isatty": lambda self: True})())
        with contextlib.redirect_stdout(io.StringIO()):
            r = lab.run(apply_pending = True, con = True)
        assert r["return"] == 0, r.get("error")
        assert [a["rel"] for a in r["applied"]] == ["memory/two.md"] and [x["rel"] for x in r["left"]] == ["memory/three.md"]
        assert read(used_ai / "memory" / "two.md") == "two\n" and not (used_ai / "memory" / "three.md").exists()
        assert (stage / "memory" / "three.md").is_file() and not (stage / "memory" / "two.md").exists()
        # "yes" takes the rest at once; nothing left, the staging folder goes
        answers = iter(["y"])
        with contextlib.redirect_stdout(io.StringIO()):
            r = lab.run(apply_pending = True, con = True)
        assert [a["rel"] for a in r["applied"]] == ["memory/three.md"] and r["left"] == [] and not stage.exists()
    finally:
        import shutil
        shutil.rmtree(used_ai)
        for path, text in original.items():
            put(path, text)
