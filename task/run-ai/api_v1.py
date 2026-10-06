"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-ai - one front door to the coding-agent harnesses cMeta runs (Claude Code, Codex, OpenCode, OpenClaw, Antigravity
CLI, Gemini CLI, ...), with the agent's memory, skills, logs and conversations kept INSIDE the cMeta artifact it works on, in a
folder named !AI, so that a project carries its own AI knowledge wherever it goes - and so that "cxt run-ai" picks up
where the last run stopped, with any harness and any model.

    cxt run-ai [--harness=claude|codex|opencode|openclaw|antigravity|gemini] [--project=<cref>] [-i] [prompt] [-- <harness flags>]
    cxt run-ai                                             # continue the latest conversation of the project, interactively
    cxt run-ai "one prompt"                                # one more turn of that conversation, then exit
    cxt run-ai --new "..."                                 # start a new conversation (the memory and skills stay)
    cxt run-ai --conversation=20261004-18 "..."            # continue a given conversation (id or prefix)
    cxt run-ai --conversations                             # list the conversations of the project
    cxt run-ai --summarize                                 # a summary of the latest conversation (claude: haiku), read first at a hand-over
    cxt run-ai --harness=codex --model=gpt-6.1-sol,high    # the same conversation, now with codex: the transcript is handed over
    cxt run-ai --harness=codex --list_models               # the models and efforts of a harness, every combination ready to copy
    cxt run-ai --list_models                               # the same for every harness, compact
    cxt run-ai --dry_run                                   # the project, its !AI, the conversation and the command - nothing runs
    cxt run-ai -w "..."                                    # no questions, write anywhere - also the used artifacts' memory (--write=all)
    cxt run-ai --pending                                  # the changes staged for the artifacts this project uses (ai_uses)
    cxt run-ai --apply_pending                             # show each of them and apply it on your word

The harness (--harness; the old name --agent is still accepted) is the CLI that runs the model: claude, codex,
opencode, openclaw, antigravity (also agy), gemini, or any <x> for which a task run-<x> exists.

The model and the effort (--model, --effort) are given in the harness's own names and turned into its flags from the
tool's _desc_models.yaml (tool/<harness>/_desc_models.yaml: the models, the efforts, the flags, a description and the
price per model, "disabled: true" for retired ones kept for reproducibility). An unknown or retired name is passed
through with a warning: the list may be behind the vendor, and the harness decides.

The project, in this order:
    --project=<cref>     category::artifact (alias or alias,UID on either side); the agent works in its folder
    (nothing given)      the cMeta artifact the current directory is in (any folder inside it; the detection behind
                         "cx . <command>"); the agent then works in the artifact's root folder
    (none detected)      the current directory itself
    --project=.          the current directory itself, no detection

The !AI folder of the project (created on the first run):
    !AI/memory/                        the agent's persistent memory: MEMORY.md (the index) + one file per memory
    !AI/skills/<name>/SKILL.md         the project's skills (claude loads them as a plugin: !AI/.claude-plugin/plugin.json;
                                       the other harnesses get the list in the prompt and read the SKILL.md files)
    !AI/log/<stamp>.<harness>.run.md   how this run was made: harness, task, project, model, conversation, flags, result
    !AI/log/<stamp>.<harness>.output.txt / .stats.json      the agent's output and its token use and cost
    !AI/log/<id>.conversation.json     a conversation: its runs and, per harness, the native session it continues
    !AI/log/<id>.transcript.md         the whole conversation, re-exported from the harnesses' own stores after every run
    !AI/log/<id>.summary.md            its summary, on request (--summarize)

Conversations (conversations.py): a run continues the conversation with the latest run unless --new or
--conversation=<id> says otherwise. The harness that holds a native session for it resumes it natively (claude
--resume <id>, codex resume <id> / codex exec resume <id>, agy --conversation <id>, opencode --session <id>, openclaw
--session-id <id>, gemini --resume <id>); another harness - or a harness whose session is gone - starts a new native
session and is handed the transcript in the prompt. So one can quit at any time and come back with another model or another harness. No
resume scripts are needed: run-ai is the way back.

How each harness is pointed at !AI - the tool's own settings, no API keys:
    claude     --settings {"autoMemoryDirectory": "<project>/!AI/memory"}  (read AND written);
               --plugin-dir <project>/!AI for the skills; --add-dir and --append-system-prompt-file for the context
    opencode   OPENCODE_CONFIG_CONTENT = {"instructions": [!AI/MEMORY.md, !AI/memory/*.md, the context file]}  (read only)
    codex      the !AI index, the skills and the context are prepended to the prompt (read only); its SQLite state
               (threads, history, memories) lives in <project>/!AI/codex (CODEX_SQLITE_HOME; --codex_state=home: CODEX_HOME)
    antigravity (agy)  as codex; context folders are mounted with --add-dir  (read only; agy has conversations, no memory)
    gemini     as codex; context folders join the workspace with --include-directories  (read only). Gemini CLI serves
               Code Assist Standard/Enterprise licences and API keys; personal Google accounts use antigravity

The first run of a project with an empty !AI/memory copies the memory Claude Code keeps for that folder
(~/.claude/projects/<slug>/memory) into it, so nothing is lost; --no_seed starts with an empty memory instead.

Context: the memory and skills of other artifacts, read-only - in this order: --context (";"-separated: cRefs, or
claude:<folder> for the memory Claude Code keeps for a folder), the project's own `ai_uses` list (_desc.yaml), the
`ai_uses` default of its repository (_cmr.yaml), and this machine's mapping: the config artifact "task-run-ai" of the
local repository, key "local_ai_uses" = {<repository alias,UID | alias | UID, or an artifact cRef | UID>: "<cref>[;<cref>...]"}
(cx config set task-run-ai --meta.local_ai_uses.<repository alias,UID>=<cref>) - for repositories that are shared and
must not name a private artifact themselves. --skip_ai_uses skips the last three; --context_depth follows them further.

The memory and skills of the artifacts a project uses (its `ai_uses`, --context) are read-only for a run, and changed
only on the user's word (pending.py) - by run-ai itself, so the same for every harness, platform and
permission mode: a session that wants to change one stages the new version under the project's own
!AI/pending/<alias>--<UID>/ (memory/<name>.md, <file>.append, <file>.delete, _note.md); "cxt run-ai --pending" lists
what is staged and "cxt run-ai --apply_pending" shows each difference and applies it after a question (-q or --yes:
without one). After every run the used artifacts' memory/ and skills/ are compared with a snapshot taken before it:
for a direct change the user is asked whether to keep it (--context_guard=ask, the default); if not - or with nobody
to ask: -q, --yes, no terminal - it is turned into such a proposal and the file is put back ("restore" does that
without asking, "report" only reports, "keep" keeps and records it, "off" does not look).

What a run may write is one switch: --write=ask|project|all|none, -w for "all", and the key "write" of the config
"task-run-ai" as this machine's default (cx config set task-run-ai --meta.write=all); a flag wins over the config.
    ask      (the default) the harness asks before it edits or runs a command; the used artifacts take proposals
    project  the harness asks nothing (what --yes does); the used artifacts still take proposals only
    all      the same, and the memory and skills of the used artifacts may be changed directly - run-ai lists the
             changes, records them in the artifact and keeps the versions before the run in !AI/log/<stamp>.before/
    none     read-only: the harness runs in its plan / read-only mode (claude, codex, opencode, agy, gemini)

Everything else - the prompt, --prompt_file, -i, --yes, --stats, --reproducible, --add_repos (claude) and the
flags after "--" - goes to run-<harness> unchanged. The task engine changes into the project folder for the
sub-task (its "path" control parameter), so the agent also finds the project's own CLAUDE.md / AGENTS.md.
"""

import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time

import yaml

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CATEGORY = 'task,c36be4b9314a45e0'
TOOL_CATEGORY = 'tool,c393ba5c6fa14f66'
MODELS_FILE = '_desc_models.yaml'

# The harnesses, the tasks that run them and the tools that hold their model lists (alias,UID: rename-safe).
# Any other --harness=<x> tries the task run-<x> and the tool <x>.
HARNESSES = {
    'claude':      {'task': 'run-claude,38be73ffceaa4f67',   'tool': 'claude,383841b240c74e88'},
    'codex':       {'task': 'run-codex,ad2fd6be195a4e36',    'tool': 'codex,cdbf5f6e6882460f'},
    'opencode':    {'task': 'run-opencode,7f1b96c011fb436f', 'tool': 'opencode,7777071804e84fb5'},
    'openclaw':    {'task': 'run-openclaw,91724507fb354b79', 'tool': 'openclaw,1776c76162b14545'},
    'antigravity': {'task': 'run-agy,fe910b4a9c88448f',      'tool': 'agy,433f36c666ce47f1'},       # Antigravity CLI ("agy"), Google's successor of Gemini CLI for personal accounts
    'agy':         {'task': 'run-agy,fe910b4a9c88448f',      'tool': 'agy,433f36c666ce47f1'},       # the same, by the command name
    'gemini':      {'task': 'run-gemini,af663bab27bb4725',   'tool': 'gemini,40a20e8dca604ece'},    # Gemini CLI: Code Assist Standard/Enterprise licences and API keys
}

AI_DIR = '!AI'
MEMORY_DIR = 'memory'
SKILLS_DIR = 'skills'
LOG_DIR = 'log'
STAMP_LOCK = '.lock'        # <stamp>.lock in !AI/log: the stamp of a run that is starting (see _new_stamp)
SKILL_SOURCES_FILE = '.sources.json'    # !AI/skills/.sources.json: where import-ai copied each skill from (see _skill_drift)
INDEX_FILE = 'MEMORY.md'
PLUGIN_DIR = '.claude-plugin'
PLUGIN_FILE = 'plugin.json'

# Where the context comes from: the `ai_uses` list of the project's _desc - the artifacts whose memory and skills this
# project's AI sessions read, in the spirit of `uses` in tasks: one list, one direction, one meaning. `connections` stay
# the undirected links of the knowledge graph and are not used for memory. The list is followed transitively to
# --context_depth (1 by default: the list is what you get). An entry is a cRef string ("category,UID::artifact,UID") or
# a dict with "cref" (and an optional "note"). The same list in a repository's _cmr.yaml is the default of all its
# artifacts; the machine-local mapping (below) adds entries on one machine only.
AI_USES_KEY = 'ai_uses'

# The config artifact of this task (cx config ...: in the local repository, so on this machine only; named after the
# task because config artifacts are global): "local_ai_uses" maps a repository or an artifact to the cRefs its sessions
# read here, "max_context_tokens" is the limit of the context estimate
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'
CONFIG_ARTIFACT = 'task-run-ai'
LOCAL_AI_USES_KEY = 'local_ai_uses'
CONFIG_TOKENS_KEY = 'max_context_tokens'
CONFIG_TRIM_KEY = 'trim_context'        # true: --trim_context on every run of this machine
SUMMARY_CLAUDE_MODEL = 'haiku'          # --summarize with claude and no --model: Claude Code's alias of its current Haiku
SUMMARY_INLINE_CHARS = 120000           # a longer transcript is read by the agent from its file instead of in the prompt

# The context estimate before a run: chars / TOKEN_CHARS (within about 25% for English and Markdown), compared with
# --max_context_tokens, else the config key above (or the older key below in the config "default"), else the default;
# over it the run fails under -q / --yes / no terminal, and asks otherwise. The harness's own counters are recorded
# after the run, next to the estimate.
TOKEN_CHARS = 4
DEFAULT_MAX_CONTEXT_TOKENS = 30000
CONFIG_MAX_TOKENS_KEY = 'run_ai_max_context_tokens'
# How long a harness keeps a prompt cached, so that "last turn N minutes ago" can say whether the context is probably
# still warm (Claude: 5 minutes by default, 60 with extended caching; OpenAI's prompt cache for Codex: typically 5 to
# 10 minutes, up to an hour off-peak - 10 taken; the others when known)
CACHE_TTL_MINUTES = {'claude': 5, 'codex': 10}


def _truthy(value):
    """A flag or a config value as it arrives (True, "true", "1", "yes", "on"; a missing value is False)."""
    return value is True or str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _glob(directory, *pattern):
    """glob.glob in a directory whose own name is taken as it is: a folder called "notes [draft]" is not a pattern."""
    return glob.glob(os.path.join(glob.escape(directory), *pattern))


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONV = _load_module('run_ai_conversations', 'conversations.py')
PEND = _load_module('run_ai_pending', 'pending.py')

# What a run does about direct changes in the memory and skills of the artifacts it uses (pending.py)
GUARD_MODES = ('ask', 'restore', 'report', 'keep', 'off')

# What a run may write - one switch (--write=<mode>, -w = all; the config key "write" is this machine's default; a
# flag wins over the config) over the two things that decide it: the harness's own approvals and sandbox, and the
# guard of the artifacts the project uses.
#   ask      the harness's own default: it asks before it edits or runs a command (a one-prompt run has nobody to
#            ask, so it mostly cannot write); the used artifacts take proposals only
#   project  the harness asks nothing and may write (what --yes does); the used artifacts take proposals only
#   all      the same, and the memory and skills of the used artifacts may be changed directly: kept, recorded in
#            the artifact, the versions before the run saved in the project's !AI/log
#   none     read-only: the harness runs in its plan / read-only mode and is told to change nothing
WRITE_MODES = ('ask', 'project', 'all', 'none')
CONFIG_WRITE_KEY = 'write'
WRITE_GUARD = {'ask': 'ask', 'project': 'restore', 'all': 'keep', 'none': 'restore'}    # unless --context_guard says otherwise
WRITE_WORDS = {'all': ('all', 'true', 'yes', 'on', '1', 'everywhere', 'full'), 'project': ('project',), 'ask': ('ask', 'default'),
               'none': ('none', 'no', 'false', 'off', '0', 'read-only', 'readonly', 'read_only', 'ro')}
# The flags that put a harness into its read-only mode (--write=none), from each CLI's own help; a harness that is
# not listed (OpenClaw, any run-<x>) has no such switch run-ai knows and is only told to change nothing. Codex takes
# the setting as a config override because "codex exec resume" has no --sandbox.
READ_ONLY_FLAGS = {
    'claude': ['--permission-mode', 'plan'],
    'codex': ['-c', 'sandbox_mode="read-only"'],
    'opencode': ['--agent', 'plan'],
    'agy': ['--mode', 'plan'],
    'gemini': ['--approval-mode', 'plan'],
}
# The harness tasks that take "yes" (their own flags that stop the questions and lift the sandbox); run-openclaw has
# none - OpenClaw follows its own settings. A task run-<x> that is not listed gets it only from --yes itself.
YES_HARNESSES = ('claude', 'codex', 'opencode', 'agy', 'gemini')

# The harness tasks that take "long_prompt_file": where they write a prompt too long for a command line argument (an
# interactive session preloads its first prompt that way; opencode and openclaw have no stdin mode at all) and ask the
# agent to read it first. run-ai names that file in !AI/log; a task run-<x> that is not listed is not given it.
LONG_PROMPT_HARNESSES = ('claude', 'codex', 'opencode', 'openclaw', 'agy', 'gemini')


class CTask(InitCTask):
    """run-ai: run a coding agent on a cMeta artifact, with its memory, skills and conversations in the artifact's !AI folder."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    # ------------------------------------------------------------------ the project
    def _resolve_project(self, project, con, space):
        """-> (path, cref or '', how) or an error dict."""
        if project == '.':
            cwd = os.path.normpath(os.getcwd())
            return cwd, '', 'the current directory (--project=.)'
        if project:
            if '::' not in project:
                return self.cm.error('--project must be a cRef "category::artifact" (alias or alias,UID), e.g. '
                                     '--project="project::my-app"')
            cat, art = [x.strip() for x in project.split('::', 1)]
            r = self.cm.access({'category': cat, 'command': 'find', 'arg1': art, 'con': False})
            if r.get('return', 1) > 0:
                return self.cm.error('--project: %s' % r.get('error', 'not found'))
            arts = r.get('artifacts') or []
            if len(arts) != 1:
                return self.cm.error('--project "%s" resolves to %d artifacts%s' % (
                    project, len(arts), (': ' + ', '.join(a.get('path', '') for a in arts)) if arts else ''))
            a = arts[0]
            p = a.get('cmeta_ref_parts') or {}
            cref = '%s,%s::%s,%s' % (p.get('category_alias', cat), p.get('category_uid', ''),
                                     p.get('artifact_alias', art), p.get('artifact_uid', ''))
            return os.path.normpath(a['path']), cref, '--project'

        # no --project: the artifact around the current directory (the "cx . <command>" detection), else the cwd
        cwd = os.path.normpath(os.getcwd())
        r = self.cm.utils.common.detect_cid_in_the_current_directory(self.cm)
        if r.get('return', 1) == 0 and (r.get('artifact_alias') or r.get('artifact_uid')):
            cat = r.get('category_obj') or r.get('category_alias')
            art = r.get('artifact_name') or r.get('artifact_alias') or r.get('artifact_uid')
            rr = self.cm.access({'category': cat, 'command': 'find', 'arg1': art, 'con': False})
            for a in (rr.get('artifacts') or []) if rr.get('return', 1) == 0 else []:
                ap = os.path.normpath(os.path.abspath(a['path']))
                if self.cm.utils.files.is_path_within(ap, cwd):
                    p = a.get('cmeta_ref_parts') or {}
                    cref = '%s,%s::%s,%s' % (p.get('category_alias', ''), p.get('category_uid', ''),
                                             p.get('artifact_alias', ''), p.get('artifact_uid', ''))
                    return ap, cref, 'detected from the current directory'
        return cwd, '', 'the current directory (no cMeta artifact detected)'

    @staticmethod
    def _alias_of(cref, project_path):
        """A short name of the project for session names and plugin names."""
        if cref and '::' in cref:
            # the artifact part of the cRef without its UID; an alias may contain commas itself
            alias = re.sub(r',[0-9a-f]{16}$', '', cref.split('::', 1)[1]).strip()
        else:
            alias = os.path.basename(os.path.normpath(project_path))
        return alias or 'project'

    @staticmethod
    def _new_stamp(log_dir, reserve):
        """The stamp that names the records of a run and, for a new conversation, the conversation: YYYYMMDD-HHMMSS,
        then -2, -3, ... when taken. Two runs of one project started within the same second (a script, two terminals)
        must not share it, so a run that writes records reserves it (reserve=True) by creating <stamp>.lock
        exclusively - one atomic step, which looking for the files first is not - and releases the lock once its run
        record holds the stamp. A lock left by a run that died is harmless (no later run takes a past second) and the
        next run clears it. -> (stamp, lock file or '')."""
        base = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        if reserve:
            for old in _glob(log_dir, '*' + STAMP_LOCK):
                try:
                    if time.time() - os.path.getmtime(old) > 600:
                        os.remove(old)
                except OSError:
                    pass
        n = 1
        while True:
            stamp = base if n == 1 else '%s-%d' % (base, n)
            n += 1
            if _glob(log_dir, stamp + '.*'):
                continue
            if not reserve:
                return stamp, ''
            lock = os.path.join(log_dir, stamp + STAMP_LOCK)
            try:
                os.makedirs(log_dir, exist_ok=True)
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                continue
            except OSError:
                return stamp, ''        # a log folder that cannot be written: the run says so when it writes there
            return stamp, lock

    @staticmethod
    def _release_stamp(lock, made=()):
        """Removes the lock of _new_stamp and, for a run that stops before writing anything, the folders the
        reservation created (made: the deepest first), when they are still empty."""
        if lock:
            try:
                os.remove(lock)
            except OSError:
                pass
        for d in made:
            try:
                os.rmdir(d)
            except OSError:
                pass

    # ------------------------------------------------------------------ the memory index
    @staticmethod
    def _memory_text(ai_root, limit=12000):
        """What a read-only harness (codex, agy, gemini, ...) is told about the project's memory: the index, else the
        list of memory files. Empty when there is nothing yet."""
        mem = os.path.join(ai_root, MEMORY_DIR)
        index = os.path.join(mem, INDEX_FILE)
        if os.path.isfile(index):
            with open(index, encoding='utf-8', errors='replace') as f:
                text = f.read().strip()
            if text:
                return ('Project memory (the index of %s/%s/%s of this cMeta artifact; read a file for the details):\n%s\n'
                        % (AI_DIR, MEMORY_DIR, INDEX_FILE, text[:limit]))
        files = sorted(os.path.basename(x) for x in _glob(mem, '*.md') if not x.endswith(INDEX_FILE))
        if files:
            return 'Project memory files in %s/%s/ of this cMeta artifact: %s\n' % (AI_DIR, MEMORY_DIR, ', '.join(files))
        return ''

    # ------------------------------------------------------------------ skills
    @staticmethod
    def _tree_hash(root):
        """A sha256 of a folder's files (their paths and contents, caches left out) - the same as import-ai's."""
        files = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x != '__pycache__']
            files += [os.path.join(d, n) for n in names if not n.endswith('.pyc')]
        h = hashlib.sha256()
        for fp in sorted(files, key=lambda x: os.path.relpath(x, root).replace('\\', '/')):
            h.update(os.path.relpath(fp, root).replace('\\', '/').encode('utf-8') + b'\0')
            with open(fp, 'rb') as f:
                h.update(f.read())
            h.update(b'\0')
        return h.hexdigest()

    @classmethod
    def _skill_drift(cls, skills_dir):
        """The copies in !AI/skills that went apart from the skill import-ai copied them from (its record
        !AI/skills/.sources.json), when that source is on this machine -> [(name, which changed since the import:
        'source', 'copy' or 'both', the source folder)]."""
        try:
            with open(os.path.join(skills_dir, SKILL_SOURCES_FILE), encoding='utf-8-sig') as f:
                sources = json.load(f)
        except (OSError, ValueError):
            return []
        out = []
        for name, rec in sorted(sources.items() if isinstance(sources, dict) else []):
            copy, src = os.path.join(skills_dir, name), str((rec or {}).get('source') or '')
            if not (src and os.path.isdir(copy) and os.path.isdir(src)):
                continue
            try:
                h_copy, h_src = cls._tree_hash(copy), cls._tree_hash(src)
            except OSError:
                continue
            if h_copy == h_src:
                continue
            out.append((name, 'source' if h_copy == rec.get('hash') else ('copy' if h_src == rec.get('hash') else 'both'), src))
        return out

    @staticmethod
    def _list_skills(skills_dir):
        """[(name, description, path of SKILL.md)] from <skills_dir>/<name>/SKILL.md (name and description from the
        front matter, else the folder name)."""
        out = []
        for fp in sorted(_glob(skills_dir, '*', 'SKILL.md')):
            name, desc = os.path.basename(os.path.dirname(fp)), ''
            try:
                with open(fp, encoding='utf-8-sig', errors='replace') as f:
                    head = f.read(4000)
                m = re.match(r'^---\s*\n(.*?)\n---', head, re.S)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    if isinstance(fm, dict):
                        name = str(fm.get('name') or name)
                        desc = ' '.join(str(fm.get('description') or '').split())
            except Exception:
                pass
            out.append((name, desc, fp))
        return out

    @staticmethod
    def _plugin_name(alias):
        name = re.sub(r'[^A-Za-z0-9]+', '-', alias).strip('-').lower()
        return name or 'project'

    def _ensure_plugin(self, ai_root, alias, cref, apply):
        """!AI/.claude-plugin/plugin.json, so that claude loads !AI/skills with --plugin-dir !AI. -> (path, created)."""
        fp = os.path.join(ai_root, PLUGIN_DIR, PLUGIN_FILE)
        if os.path.isfile(fp):
            return fp, False
        if apply:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'name': self._plugin_name(alias), 'version': '0.1.0',
                           'description': 'The skills of the cMeta artifact %s (its %s/%s folder), written by run-ai' % (cref or alias, AI_DIR, SKILLS_DIR)},
                          f, indent=1)
                f.write('\n')
        return fp, True

    @staticmethod
    def _skills_text(label, skills):
        lines = ['## Skills of %s (read the SKILL.md of a skill before using it)' % label]
        for name, desc, fp in skills:
            lines.append('- %s: %s(%s)' % (name, (desc + ' ') if desc else '', fp.replace('\\', '/')))
        return '\n'.join(lines) + '\n'

    # ------------------------------------------------------------------ claude: the native memory, the settings
    def _seed_memory(self, project_path, mem_dir, apply):
        """The first run of a project (model A): when !AI/memory holds no memory yet and Claude's native folder for
        this path does, the native files are copied in, so nothing the user had is lost; the native folder is left as
        it is. -> (files copied, native dir)."""
        if _glob(mem_dir, '*.md'):
            return 0, ''
        for native in [os.path.join(d, MEMORY_DIR) for d in CONV.claude_project_dirs(project_path)]:
            files = sorted(_glob(native, '*.md'))
            # a folder that holds only the index (a pointer left behind when the memories moved elsewhere) has
            # nothing to seed
            if files and all(os.path.basename(f) == INDEX_FILE for f in files):
                files = []
            if files:
                if apply:
                    os.makedirs(mem_dir, exist_ok=True)
                    for f in files:
                        shutil.copy2(f, os.path.join(mem_dir, os.path.basename(f)))
                return len(files), native
        return 0, ''

    @staticmethod
    def _user_settings(extra):
        """A --settings <file-or-json> the user passed after "--": taken out of the flags and parsed, so that it can be
        merged with run-ai's own settings. -> (dict or None, the flags without it, warning or '')."""
        out, user, warn = [], None, ''
        k = 0
        while k < len(extra):
            x = extra[k]
            if x == '--settings' or x.startswith('--settings='):
                val = x.split('=', 1)[1] if '=' in x else (extra[k + 1] if k + 1 < len(extra) else '')
                k += 1 if '=' in x else 2
                try:
                    if os.path.isfile(val):
                        with open(val, encoding='utf-8') as f:
                            user = json.load(f)
                    else:
                        user = json.loads(val)
                except Exception as e:
                    warn = ('WARNING: the --settings passed after "--" could not be read (%s): it goes to claude as it is, '
                            'and run-ai adds no setting of its own (no memory in !AI)' % e)
                    out += [x] if '=' in x else [x, val]
                continue
            out.append(x)
            k += 1
        return user, out, warn

    @staticmethod
    def _claude_settings(mem_posix, user):
        """The settings of one run: the memory folder over what the user passed with --settings."""
        settings = dict(user or {})
        settings['autoMemoryDirectory'] = mem_posix
        return settings

    # ------------------------------------------------------------------ context: other artifacts' memory and skills, read-only
    def _find_artifact(self, cref):
        """'category::artifact' (alias or alias,UID on either side) -> (path, cref with UIDs), or (None, why)."""
        if '::' not in cref:
            return None, 'not a cRef (category::artifact)'
        cat, art = [x.strip() for x in cref.split('::', 1)]
        r = self.cm.access({'category': cat, 'command': 'find', 'arg1': art, 'con': False})
        arts = (r.get('artifacts') or []) if r.get('return', 1) == 0 else []
        if len(arts) != 1:
            return None, 'not found' if not arts else '%d artifacts match' % len(arts)
        a = arts[0]
        p = a.get('cmeta_ref_parts') or {}
        return os.path.normpath(a['path']), '%s,%s::%s,%s' % (p.get('category_alias', cat), p.get('category_uid', ''),
                                                               p.get('artifact_alias', art), p.get('artifact_uid', ''))

    @staticmethod
    def _read_desc(path):
        """The _desc.yaml or _desc.json of an artifact folder, or {}."""
        for fn in ('_desc.yaml', '_desc.json'):
            fp = os.path.join(path, fn)
            if os.path.isfile(fp):
                try:
                    with open(fp, encoding='utf-8') as f:
                        d = yaml.safe_load(f) if fn.endswith('.yaml') else json.load(f)
                except Exception:
                    return {}
                return d if isinstance(d, dict) else {}
        return {}

    def _desc_connections(self, project_path):
        """The connections of the project, from its _desc.yaml or _desc.json (the knowledge graph's own links)."""
        return [str(x) for x in (self._read_desc(project_path).get('connections') or []) if x]

    @staticmethod
    def _uses_entries(value):
        """An `ai_uses`-style value -> [(cref, note)]: a list of cRef strings or {cref, note} dicts, or one string with
        cRefs separated by ";" (what "cx config set ... --meta.<key>=<a>;<b>" gives: cRefs contain commas)."""
        if isinstance(value, (str, dict)):
            value = [value]
        out = []
        for e in value or []:
            if isinstance(e, dict):
                if e.get('cref'):
                    out.append((str(e['cref']).strip(), str(e.get('note') or '')))
            elif e:
                out += [(x.strip(), '') for x in re.split(r'[;\n]', str(e)) if x.strip()]
        return out

    def _ai_uses(self, path):
        """The `ai_uses` list of an artifact's _desc -> [(cref, note)]; an entry is a cRef string or {cref, note}."""
        return self._uses_entries(self._read_desc(path).get(AI_USES_KEY))

    @staticmethod
    def _repo_meta(project_path):
        """The _cmr.yaml / _cmr.json of the repository the project lives in (the first one found walking up from the
        project folder) -> dict, or {}."""
        d = os.path.normpath(project_path)
        while True:
            for fn in ('_cmr.yaml', '_cmr.json'):
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    try:
                        with open(fp, encoding='utf-8') as f:
                            meta = yaml.safe_load(f) if fn.endswith('.yaml') else json.load(f)
                    except Exception:
                        return {}
                    return meta if isinstance(meta, dict) else {}
            parent = os.path.dirname(d)
            if parent == d:
                return {}
            d = parent

    def _repo_ai_uses(self, project_path):
        """The repository-wide default: an `ai_uses` list in the _cmr.yaml / _cmr.json of the repository the project
        lives in -> [(cref, note)]. Every artifact of that repository then reads those artifacts' memory and skills
        without a list of its own (all the work folders of a private repository read their organisation, say)."""
        return self._uses_entries(self._repo_meta(project_path).get(AI_USES_KEY))

    def _run_ai_config(self):
        """The data of the config artifact task-run-ai, read without creating it ("config get" would) -> dict."""
        try:
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': CONFIG_ARTIFACT, 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _cref_parts(c):
        """'category[,UID]::artifact[,UID]' -> (category alias, category UID, artifact alias, artifact UID), lower case;
        an artifact alias may contain commas, so its UID is the part after the last one when it looks like a UID."""
        cat, _, art = str(c).partition('::')
        ca, _, cu = cat.partition(',')
        aa, au = art, ''
        if ',' in art and re.fullmatch(r'[0-9a-f]{16}', art.rsplit(',', 1)[1].strip()):
            aa, au = art.rsplit(',', 1)
        return ca.strip().lower(), cu.strip().lower(), aa.strip().lower(), au.strip().lower()

    @classmethod
    def _cref_matches(cls, key, cref):
        """Does a cRef key (UIDs optional on either side) name the artifact `cref`?"""
        k, c = cls._cref_parts(key), cls._cref_parts(cref)
        same_cat = (k[1] and k[1] == c[1]) or (k[0] and k[0] == c[0])
        same_art = (k[3] and k[3] == c[3]) or (k[2] and k[2] == c[2])
        return bool(same_cat and same_art)

    def _local_ai_uses(self, project_path, cref):
        """This machine's mapping: the key local_ai_uses of the config artifact task-run-ai, {<key>: <cref>[;<cref>] or
        a list}, where <key> is the project's repository (alias,UID; alias; UID) or the project itself (its cRef, UIDs
        optional; or its UID). The CLI splits a key at its dots ("--meta.local_ai_uses.<key>=..."), so nested levels
        are joined back with dots. -> [(cref, note, key)]."""
        mapping = self._run_ai_config().get(LOCAL_AI_USES_KEY)
        if not isinstance(mapping, dict) or not mapping:
            return []
        flat = {}

        def walk(d, prefix):
            for k, v in d.items():
                key = '%s.%s' % (prefix, k) if prefix else str(k)
                if isinstance(v, dict) and 'cref' not in v:
                    walk(v, key)
                else:
                    flat[key] = v
        walk(mapping, '')
        repo = str(self._repo_meta(project_path).get('artifact') or '').strip()
        r_alias, _, r_uid = repo.partition(',')
        repo_keys = {x.strip().lower() for x in (repo, r_alias, r_uid) if x.strip()}
        art_uid = self._cref_parts(cref)[3] if cref else ''
        out = []
        for key, value in flat.items():
            k = key.strip().lower()
            if k in repo_keys or (art_uid and k == art_uid) or ('::' in k and cref and self._cref_matches(k, cref)):
                out += [(c, n, key) for c, n in self._uses_entries(value)]
        return out

    @staticmethod
    def _context_items(context):
        """--context -> its entries: separated by ";" (or new lines) - never by ",", which cRefs and folder names
        contain; a list (--context,=...) is taken as it is."""
        items = context if isinstance(context, (list, tuple)) else re.split(r'[;\n]', str(context or ''))
        return [str(x).strip() for x in items if str(x).strip()]

    def _context_sources(self, project_path, context, depth, limit, skip_ai_uses=False, project_cref=''):
        """--context entries (a cRef, or claude:<folder> for the memory Claude Code keeps for a folder), then the
        project's `ai_uses` - its own list, the default of its repository's _cmr.yaml, this machine's mapping (config
        task-run-ai, local_ai_uses) - followed transitively to `depth` (what they use, what those use ...). Kept: the
        ones that hold memory or skills; the others are listed as skipped, with the reason.
        -> (sources, skipped: [(label, why)])."""
        try:
            limit = int(limit)              # a string when it comes from the command line
        except (TypeError, ValueError):
            limit = 20
        wanted = []
        for item in self._context_items(context):
            if item.lower().startswith('claude:'):
                wanted.append((item, 'claude', item.split(':', 1)[1].strip(), 0))
            else:
                wanted.append((item, 'context', item, 1))
        if not skip_ai_uses:
            wanted += [(c, 'ai_uses', c, 1) for c, note in self._ai_uses(project_path)]
            wanted += [(c, 'ai_uses, repository default', c, 1) for c, note in self._repo_ai_uses(project_path)]
            wanted += [(c, 'ai_uses, machine-local: %s' % key, c, 1) for c, note, key in self._local_ai_uses(project_path, project_cref)]
        sources, skipped, seen = [], [], {os.path.normcase(os.path.normpath(project_path))}
        k = 0
        while k < len(wanted):
            label, kind, spec, level = wanted[k]
            k += 1
            skills, plugin = [], ''
            if kind == 'claude':
                dirs = [os.path.join(d, MEMORY_DIR) for d in CONV.claude_project_dirs(spec)]
                dirs = [d for d in dirs if _glob(d, '*.md')]
                if not dirs:
                    skipped.append((label, 'no native Claude memory for that folder'))
                    continue
                root = mem = dirs[0]
            else:
                path, info = self._find_artifact(spec)
                if not path:
                    skipped.append((label, info))
                    continue
                if os.path.normcase(path) in seen:
                    continue        # the project itself, or a source already taken
                root, label = path, info
                mem = os.path.join(path, AI_DIR, MEMORY_DIR)
                skills = self._list_skills(os.path.join(path, AI_DIR, SKILLS_DIR))
                if skills and os.path.isfile(os.path.join(path, AI_DIR, PLUGIN_DIR, PLUGIN_FILE)):
                    plugin = os.path.join(path, AI_DIR)
                if (kind == 'context' or kind.startswith('ai_uses')) and level < depth:
                    # what this source uses comes next, one level deeper (its own list, its repository's default and
                    # this machine's mapping)
                    wanted += [(c, 'ai_uses', c, level + 1) for c, note in self._ai_uses(path) + self._repo_ai_uses(path)]
                    wanted += [(c, 'ai_uses', c, level + 1) for c, note, key in self._local_ai_uses(path, info)]
                if not _glob(mem, '*.md') and not skills:
                    skipped.append((label, 'no %s/%s or %s/%s there yet' % (AI_DIR, MEMORY_DIR, AI_DIR, SKILLS_DIR)))
                    continue
            if os.path.normcase(root) in seen:
                continue
            seen.add(os.path.normcase(root))
            if len(sources) >= limit:
                skipped.append((label, 'over --context_limit=%d' % limit))
                continue
            sources.append({'label': label, 'kind': kind if not kind.startswith('ai_uses') or level == 1 else ('%s, depth %d' % (kind, level)),
                            'root': root, 'memory_dir': mem, 'has_memory': bool(_glob(mem, '*.md')),
                            'skills': skills, 'plugin': plugin})
        return sources, skipped

    # ------------------------------------------------------------------ used artifacts: proposals and the guard (pending.py)
    @staticmethod
    def _stage_sources(sources, ai_root):
        """Give every used artifact its staging folder under the project's !AI/pending (kept in the source dict for
        the context text) -> [{label, key, ai}] for pending.py. A folder's native Claude memory (--context=claude:...)
        is no artifact: it gets none."""
        guarded, taken = [], set()
        for s in sources:
            if s['kind'] == 'claude':
                continue
            key = PEND.stage_key(s['label'], s['root'])
            n = 2
            while key in taken:                     # two artifacts with one alias and no UID
                key, n = '%s-%d' % (PEND.stage_key(s['label'], s['root']), n), n + 1
            taken.add(key)
            s['stage_dir'] = os.path.join(ai_root, PEND.PENDING_DIR, key)
            guarded.append({'label': s['label'], 'key': key, 'ai': os.path.join(s['root'], AI_DIR)})
        return guarded

    @staticmethod
    def _ask(question):
        """The user's answer to a question on the terminal, lower case ('' when there is none or on Ctrl+C)."""
        try:
            return input(question).strip().lower()
        except (Exception, KeyboardInterrupt):
            return ''

    def _pending(self, ai_root, log_dir, project, guarded, apply, no_question, con, space, stamp):
        """--pending / --apply_pending: the changes staged under the project's !AI/pending for the artifacts it uses.
        Listing shows every difference; applying asks once per artifact - all its changes, or one question per change
        ("e") - (no question with -q or --yes; without a terminal and without them nothing is applied) and leaves a
        record in the artifact's !AI/log."""
        pending_root = os.path.join(ai_root, PEND.PENDING_DIR)
        targets, unknown = PEND.staged(pending_root, guarded)
        text = []

        def say(line=''):
            text.append(line)
            if con:
                print(space + line)

        say('')
        say('RUN-AI: changes staged for the artifacts this project uses (%s)' % pending_root)
        if not targets and not unknown:
            say('  none')
        listed, applied, left = [], [], []
        terminal = bool(getattr(sys.stdin, 'isatty', lambda: False)())
        for t in targets:
            say('')
            say('  %s' % t['label'])
            say('    in %s' % t['ai'])
            for line in t['note'].splitlines()[:12]:
                say('    note: %s' % line)
            for item in t['items']:
                say('    %-7s %s' % ((item['action'] or 'refused').upper(), item['rel']))
                for line in PEND.diff(item):
                    say('    ' + line)
                listed.append({'label': t['label'], 'rel': item['rel'], 'action': item['action'] or 'refused', 'problem': item['problem']})
            if not apply:
                continue
            todo = [i for i in t['items'] if not i['problem'] and i['action'] != 'same']
            for item in t['items']:
                if not item['problem'] and item['action'] == 'same':
                    PEND.clear(item, t['dir'])              # the artifact has it already
            if todo:
                if no_question:
                    chosen = todo
                elif not (con and terminal):
                    chosen = []
                    say('    not applied: there is nobody to ask (-q or --yes applies without a question)')
                else:
                    # all of an artifact's changes at once, or one question per change
                    answer = self._ask('%s    Apply %d change(s) to %s? [y]es, all / [e]ach, one by one / [N]o ' % (space, len(todo), t['label']))
                    if answer in ('e', 'each'):
                        chosen = [i for i in todo if self._ask('%s      %s %s? [y/N] ' % (space, i['action'].upper(), i['rel'])) in ('y', 'yes')]
                    else:
                        chosen = todo if answer in ('y', 'yes') else []
                kept = [i for i in todo if i not in chosen]
                if kept:
                    left += [{'label': t['label'], 'rel': i['rel'], 'action': i['action']} for i in kept]
                    say('    left staged: %s' % ('all' if not chosen else ', '.join(i['rel'] for i in kept)))
                if not chosen:
                    PEND.finish_target(t['dir'], pending_root)
                    continue
                records = []
                for item in chosen:
                    try:
                        r = PEND.apply(item)
                    except OSError as e:
                        say('    FAILED  %s: %s' % (item['rel'], e))
                        left.append({'label': t['label'], 'rel': item['rel'], 'action': item['action']})
                        continue
                    if r:
                        records.append(r)
                        PEND.clear(item, t['dir'])
                if records:
                    fp = PEND.record_applied(t['ai'], stamp, project, records)
                    say('    applied %d change(s); the record: %s' % (len(records), fp))
                    applied += [dict(r, label=t['label']) for r in records]
            PEND.finish_target(t['dir'], pending_root)
        for key in unknown:
            say('  %s: no artifact this project uses has that name - left alone' % key)
        todo_n = sum(1 for x in listed if x['action'] not in ('same', 'refused'))
        if not apply and todo_n:
            say('')
            say('  "cxt run-ai --apply_pending" shows them again and applies them on your word')
        if applied and log_dir:
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, '%s.apply_pending.md' % stamp), 'w', encoding='utf-8', newline='\n') as f:
                f.write('# run-ai %s - changes applied to used artifacts on the user\'s word\n\n' % stamp)
                f.write(''.join('- %s: %s `%s`\n' % (a['label'], a['action'], a['rel']) for a in applied))
        return {'return': 0, 'pending': listed, 'applied': applied, 'left': left, 'unknown': unknown, 'text': '\n'.join(text) + '\n'}

    # ------------------------------------------------------------------ the context estimate
    @staticmethod
    def _estimate(parts):
        """[(label, text, note)] -> [(label, tokens, note)], total; tokens = chars / TOKEN_CHARS, rounded up."""
        rows, total = [], 0
        for label, text, note in parts:
            n = -(-len(text or '') // TOKEN_CHARS)
            if n or label == 'prompt':
                rows.append((label, n, note))
            total += n
        return rows, total

    def _token_limit(self, max_context_tokens):
        """--max_context_tokens, else the config task-run-ai (max_context_tokens), else the older key of the config
        "default" (run_ai_max_context_tokens), else the default -> (limit, where it came from)."""
        if max_context_tokens:
            return int(max_context_tokens), '--max_context_tokens'
        try:
            n = self._run_ai_config().get(CONFIG_TOKENS_KEY)
            if n:
                return int(n), 'config %s %s' % (CONFIG_ARTIFACT, CONFIG_TOKENS_KEY)
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': 'default', 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
            if isinstance(cfg, dict) and cfg.get(CONFIG_MAX_TOKENS_KEY):
                return int(cfg[CONFIG_MAX_TOKENS_KEY]), 'config default %s' % CONFIG_MAX_TOKENS_KEY
        except Exception:
            pass
        return DEFAULT_MAX_CONTEXT_TOKENS, 'default (cx config set %s --meta.%s=<n> changes it)' % (CONFIG_ARTIFACT, CONFIG_TOKENS_KEY)

    @staticmethod
    def _cache_line(harness, conv):
        """"last turn N min ago" and, for a harness with a known prompt-cache TTL, whether the context is probably warm."""
        runs = (conv or {}).get('runs') or []
        last = (runs[-1].get('finished') or runs[-1].get('started')) if runs else ''
        if not last:
            return ''
        try:
            minutes = (datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds() / 60.0
        except Exception:
            return ''
        ttl = CACHE_TTL_MINUTES.get(CONV.harness_key(harness))
        text = 'last turn %s ago' % ('%.0f min' % minutes if minutes < 120 else '%.1f h' % (minutes / 60))
        if ttl:
            text += '; the harness\'s prompt cache is probably %s (TTL %d min%s)' % (
                'still warm' if minutes <= ttl else 'cold', ttl, ', 60 with extended caching' if CONV.harness_key(harness) == 'claude' else '')
        return text

    @staticmethod
    def _render_context(sources, skills_too, writable=False):
        """One Markdown text: per source its memory index, the links turned into absolute paths so that a memory can
        be read from the project (the agent is given access to those folders); the skills of the sources whose plugin
        is not loaded natively (skills_too: all sources). writable: this run may change them directly (--write=all)."""
        lines = ["# Context from other cMeta artifacts (%s). This project's own memory is in %s/%s/." % (
            'this run may change their memory and skills directly' if writable else 'read-only', AI_DIR, MEMORY_DIR), '']
        for s in sources:
            lines += ['## %s' % s['label']]
            if s.get('stage_dir') and not writable:
                lines += ['read-only; a change to it is proposed under: %s/' % s['stage_dir'].replace('\\', '/')]
            if s['has_memory']:
                lines += ['memory folder: %s' % s['memory_dir'].replace('\\', '/'), '']
                index = os.path.join(s['memory_dir'], INDEX_FILE)
                if os.path.isfile(index):
                    with open(index, encoding='utf-8', errors='replace') as f:
                        for line in f.read().splitlines():
                            lines.append(re.sub(r'\]\(([^)/\\:]+\.md)\)',
                                                lambda m, d=s['memory_dir']: '](%s)' % os.path.join(d, m.group(1)).replace('\\', '/'), line))
                else:
                    lines += ['- %s' % fp.replace('\\', '/') for fp in sorted(_glob(s['memory_dir'], '*.md'))]
                lines.append('')
            if s['skills'] and (skills_too or not s['plugin']):
                lines += ['skills (read the SKILL.md of a skill before using it):']
                lines += ['- %s: %s(%s)' % (n, (d + ' ') if d else '', fp.replace('\\', '/')) for n, d, fp in s['skills']]
                lines.append('')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _orientation(ai_root, conv, conv_how, log_dir, own_skills, sources=(), guard='ask', own_workspace='', write='ask'):
        """What every harness is told first: where this project keeps its memory, skills and conversations, and which
        conversation this run is - so that "what was our last conversation?" is answered from !AI/log and not from the
        harness's own history (~/.claude/projects, CODEX_HOME, ...) - and how a change to a used artifact is proposed
        (guard "keep": that it may be made directly). own_workspace: the harness works in a folder of its own, not in
        the project (OpenClaw), and is told where the project is. write "none": the run is read-only."""
        posix = ai_root.replace('\\', '/')
        lines = ['# This project is run through cMeta run-ai']
        if write == 'none':
            lines.append('- This run is read-only (--write=none): change no file - not in the project, not in its %s folder, nowhere '
                         'else - and run no command that changes anything. Answer from what you read, and say what you would change.' % AI_DIR)
        if own_workspace:
            lines.append('- The project folder is %s. You work in a workspace of your own (%s), not in it: read and write the '
                         'files of the project by their absolute paths in that folder, and keep nothing of the project in your '
                         'workspace.' % (os.path.dirname(posix), own_workspace))
        lines.append('- Its memory is %s/%s/ (MEMORY.md is the index)%s.' % (
            posix, MEMORY_DIR, ('; its skills are in %s/%s/' % (posix, SKILLS_DIR)) if own_skills else ''))
        if sources:
            lines.append('- It also reads%s the memory and skills of the artifacts it uses (its `%s`: the list of its _desc, '
                         'its repository\'s default, this machine\'s mapping; and --context; their indexes follow below): %s.' % (
                             ' - and in this run may change -' if guard == 'keep' else ', read-only,',
                             AI_USES_KEY, '; '.join(s['label'] for s in sources)))
            if guard == 'keep':
                lines.append('- This run has write access to those artifacts (--write=all): change their memory and skills where they '
                             'are, when it serves the request. Keep the format of the files (a memory is one fact in a Markdown file '
                             'with its front matter; a skill is a folder with a SKILL.md) and keep each %s index in step with its '
                             'files. run-ai lists what changed after the run, records it in the artifact\'s %s/%s and keeps the '
                             'versions before the run.' % (INDEX_FILE, AI_DIR, LOG_DIR))
            elif write == 'none':
                pass        # a read-only run stages no proposal either: it says what it would change
            elif any(s.get('stage_dir') for s in sources):
                lines.append('- Read-only means: never create, edit or delete a file in those artifacts, with any tool. To change their '
                             'memory or skills, write the new version under this project\'s own %s/%s/<the folder named for that '
                             'artifact below>/, with the path the file has under the artifact\'s %s: memory/<name>.md or '
                             'skills/<skill>/SKILL.md (the whole file, new or replacing), <file>.append (lines to add to an existing '
                             'file, e.g. memory/%s.append), an empty <file>.delete (remove that file), and _note.md (why). Then tell '
                             'the user to run "cxt run-ai --apply_pending": run-ai shows each difference and applies it on their word.%s' % (
                                 posix, PEND.PENDING_DIR, AI_DIR, INDEX_FILE,
                                 {'ask': ' A direct change is shown to the user after the run and, unless they keep it, undone and turned into such a proposal.',
                                  'restore': ' A direct change is undone after the run and turned into such a proposal.',
                                  'report': ' A direct change is reported to the user after the run.'}.get(guard, '')))
        if conv is None:
            lines.append('- No conversation is recorded for this run (--no_log).')
        else:
            runs = conv.get('runs') or []
            lines.append('- run-ai records every conversation with this project in %s/%s/<id>.conversation.json and its transcript in '
                         '<id>.transcript.md. This run %s conversation %s%s.' % (
                             posix, LOG_DIR, 'starts the new' if conv_how == 'new' else 'continues the',
                             conv['id'], (' (started %s, %d run(s) before this one)' % (
                                 (conv.get('started') or '')[:16], len(runs))) if conv_how != 'new' else ''))
            # a title is the first words of a conversation's first request: it is quoted to tell conversations apart,
            # and must not read as a request of this run (the title of the current conversation is left out: the
            # harness has that conversation, or is handed its transcript)
            others = [c for c in CONV.list_conversations(log_dir) if c['id'] != conv['id']][:6]
            if others:
                lines.append('- Other conversations with this project, newest first. The quoted words are how each one began - they '
                             'tell the conversations apart and are not requests of this run; the transcript has the details:')
                for c in others:
                    last = (c.get('runs') or [{}])[-1]
                    lines.append('  - %s: "%s" - %d run(s), last %s -> %s/%s/%s.transcript.md' % (
                        c['id'], c.get('title') or '', len(c.get('runs') or []), (last.get('finished') or last.get('started') or '')[:16], posix, LOG_DIR, c['id']))
            else:
                lines.append('- There is no earlier conversation recorded for this project: this one is the first.')
            lines.append('- A question about a previous conversation is answered from those transcripts, never from the harness\'s own '
                         'session history (~/.claude/projects, CODEX_HOME, ...), which is not the record of this project.')
        lines.append('- Everything learnt or made for this project stays in its %s folder, never in the user\'s home: a new memory is a '
                     'Markdown file in %s/%s/ with a line added to MEMORY.md (Claude Code does this by itself there); a new skill is '
                     '%s/%s/<name>/SKILL.md (loaded on the next run), not ~/.claude/skills or .claude/skills.' % (
                         AI_DIR, posix, MEMORY_DIR, posix, SKILLS_DIR))
        return '\n'.join(lines) + '\n\n'

    @staticmethod
    def _pull_flag(extra, name):
        """Take --name <value> or --name=<value> out of the flags -> (value or None, the flags without it)."""
        out, value, k = [], None, 0
        while k < len(extra):
            x = extra[k]
            if x == name and k + 1 < len(extra):
                value, k = extra[k + 1], k + 2
                continue
            if x.startswith(name + '='):
                value, k = x.split('=', 1)[1], k + 1
                continue
            out.append(x)
            k += 1
        return value, out

    # ------------------------------------------------------------------ the harness, its tool and its model list
    @staticmethod
    def _harness_refs(harness):
        """-> (the task that runs the harness, the tool that holds its model list); alias,UID for the known ones."""
        h = HARNESSES.get(harness)
        return (h['task'], h['tool']) if h else ('run-' + harness, harness)

    def _artifact_path(self, category, ref):
        """The folder of one artifact, or ''."""
        r = self.cm.access({'category': category, 'command': 'find', 'arg1': ref, 'con': False})
        arts = (r.get('artifacts') or []) if r.get('return', 1) == 0 else []
        return os.path.normpath(arts[0]['path']) if len(arts) == 1 else ''

    def _load_models(self, harness):
        """The _desc_models.yaml of the harness's tool -> (dict or None, its path or '', why not)."""
        tool_ref = self._harness_refs(harness)[1]
        path = self._artifact_path(TOOL_CATEGORY, tool_ref)
        if not path:
            return None, '', 'no tool artifact "%s" for the harness "%s"' % (tool_ref, harness)
        fp = os.path.join(path, MODELS_FILE)
        if not os.path.isfile(fp):
            return None, fp, 'no %s in %s' % (MODELS_FILE, path)
        try:
            with open(fp, encoding='utf-8') as f:
                d = yaml.safe_load(f) or {}
        except Exception as e:
            return None, fp, '%s cannot be read: %s' % (fp, e)
        if not isinstance(d, dict):
            return None, fp, '%s is not a mapping' % fp
        return d, fp, ''

    @staticmethod
    def _split_model(model, effort):
        """--model=<model>[,<effort>] and --effort -> (model, effort, note). An explicit --effort wins."""
        if isinstance(model, (list, tuple)):
            model = ','.join(str(x) for x in model)
        model, effort, note = str(model or '').strip(), str(effort or '').strip(), ''
        if ',' in model:
            model, e = [x.strip() for x in model.rsplit(',', 1)]
            if effort and e and e != effort:
                note = 'two efforts given ("%s" in --model, "%s" in --effort): --effort wins' % (e, effort)
            effort = effort or e
        return model, effort, note

    @staticmethod
    def _effort_names(models):
        return [str(e.get('name', '')) if isinstance(e, dict) else str(e) for e in ((models or {}).get('efforts') or [])]

    @staticmethod
    def _model_entry(models, name):
        for m in (models or {}).get('models') or []:
            if isinstance(m, dict) and name in [str(m.get('name', ''))] + [str(a) for a in (m.get('aliases') or [])]:
                return m
        return None

    @staticmethod
    def _template(value, default):
        """A flag template from _desc_models.yaml ("flags: model: ['--model', '{{model}}']"; a string is split on
        spaces) -> a list of tokens, or None when there is none and no default."""
        if value is None:
            return default
        if isinstance(value, str):
            return value.split()
        return [str(x) for x in value]

    def _check_model(self, models, model, effort, today):
        """Warnings about a model and an effort against the list - never an error: the list may be behind the vendor,
        and the harness decides."""
        notes = []
        if not models:
            return notes
        entry = self._model_entry(models, model) if model else None
        if model:
            if entry is None:
                notes.append('model "%s" is not in %s (updated %s): passed through as it is' % (
                    model, MODELS_FILE, models.get('updated', '?')))
            else:
                if entry.get('disabled'):
                    notes.append('model "%s" is retired in %s%s: the harness may refuse it' % (
                        model, MODELS_FILE, (' (%s)' % entry['note']) if entry.get('note') else ''))
                elif entry.get('until') and str(entry['until']) < today:
                    notes.append('model "%s" was announced to go away on %s: the harness may refuse it' % (model, entry['until']))
                if entry.get('unverified'):
                    notes.append('model "%s": the name is not yet confirmed with the harness itself%s' % (
                        model, (' (%s)' % models['list_cmd']) if models.get('list_cmd') else ''))
        if effort:
            if self._template((models.get('flags') or {}).get('effort'), None) is None:
                notes.append('the harness takes no effort flag: --effort=%s is dropped' % effort)
            else:
                allowed = entry.get('efforts') if (entry is not None and entry.get('efforts') is not None) else self._effort_names(models)
                allowed = [str(x) for x in allowed]
                if effort not in allowed:
                    notes.append('effort "%s" is not listed for %s (listed: %s): passed through as it is' % (
                        effort, ('model "%s"' % model) if entry is not None else 'this harness', ', '.join(allowed) or 'none'))
        return notes

    def _native_flags(self, models, model, effort):
        """The harness's own flags for a model and an effort, from "flags:" of its _desc_models.yaml. Without a list
        the defaults are --model and --effort; a list without an effort flag means the harness has none.
        -> (flags, model template, effort template)."""
        flags = (models or {}).get('flags') or {}
        model_t = self._template(flags.get('model'), ['--model', '{{model}}'])
        effort_t = self._template(flags.get('effort'), None if models else ['--effort', '{{effort}}'])
        out = []
        if model and model_t:
            out += [t.replace('{{model}}', model) for t in model_t]
        if effort and effort_t:
            out += [t.replace('{{effort}}', effort) for t in effort_t]
        return out, model_t, effort_t

    def _list_models(self, harness, con):
        """--list_models: the models and efforts of one harness, with every --model=<model>,<effort> ready to copy;
        without a harness, a compact list for every known one."""
        names = [harness] if harness else [h for h in HARNESSES if h != 'agy']
        compact = not harness
        lines = []
        for h in names:
            task_ref, tool_ref = self._harness_refs(h)
            models, fp, why = self._load_models(h)
            if models is None:
                lines += ['RUN-AI: harness "%s" (task %s): %s' % (h, task_ref, why), '']
                continue
            flags = models.get('flags') or {}
            model_t = ' '.join(self._template(flags.get('model'), ['--model', '{{model}}']))
            effort_t = ' '.join(self._template(flags.get('effort'), None) or [])
            efforts = [e if isinstance(e, dict) else {'name': str(e)} for e in (models.get('efforts') or [])]
            entries = [m for m in (models.get('models') or []) if isinstance(m, dict)]
            active = [m for m in entries if not m.get('disabled')]
            retired = [m for m in entries if m.get('disabled')]
            lines.append('RUN-AI: models of the harness "%s" (task %s, tool %s)' % (h, task_ref, tool_ref))
            lines.append('  list:    %s (updated %s%s)' % (fp, models.get('updated', '?'),
                                                           ('; checked with %s' % models['checked_with']) if models.get('checked_with') else ''))
            if models.get('list_cmd'):
                lines.append('  the harness itself: %s' % models['list_cmd'])
            lines.append('  flags:   %s%s' % (model_t, ('; ' + effort_t) if effort_t else '; no effort flag'))
            if efforts:
                lines.append('  efforts: ' + ', '.join(('%s (%s)' % (e.get('name'), e['desc'])) if e.get('desc') else str(e.get('name')) for e in efforts))
            lines.append('')
            for m in active:
                tags = [t for t, on in (('default', m.get('default')), ('legacy', m.get('legacy')), ('free', m.get('free')),
                                        ('unverified name', m.get('unverified')), ('until %s' % m.get('until'), m.get('until'))) if on]
                head = '  %s%s' % (m.get('name'), (' [%s]' % ', '.join(tags)) if tags else '')
                if m.get('aliases'):
                    head += '   also: %s' % ', '.join(str(a) for a in m['aliases'])
                lines.append(head)
                if compact:
                    continue
                if m.get('desc'):
                    lines.append('      %s' % m['desc'])
                facts = []
                for key, label in (('context', 'context'), ('max_output', 'max output'), ('default_effort', 'default effort'),
                                   ('plans', 'plans'), ('auth', 'auth'), ('retirement', 'retirement')):
                    if m.get(key):
                        facts.append('%s %s' % (label, m[key]))
                price = m.get('price_usd_per_mtok')
                if isinstance(price, dict):
                    facts.append('API price USD/MTok: in %s, out %s' % (price.get('input'), price.get('output')))
                if facts:
                    lines.append('      ' + '; '.join(facts))
                if m.get('note'):
                    lines.append('      note: %s' % m['note'])
                m_efforts = [str(x) for x in m['efforts']] if m.get('efforts') is not None else [str(e.get('name')) for e in efforts]
                lines.append('      cxt run-ai --harness=%s --model=%s' % (h, m.get('name')))
                if effort_t:
                    for e in m_efforts:
                        lines.append('      cxt run-ai --harness=%s --model=%s,%s' % (h, m.get('name'), e))
                lines.append('')
            if compact:
                lines.append('')
            if retired:
                lines.append('  retired (kept for reproducibility; run-ai warns, the harness decides):')
                for m in retired:
                    lines.append('      %s%s' % (m.get('name'), ('  - ' + str(m['note'])) if m.get('note') else ''))
                lines.append('')
        text = '\n'.join(lines).rstrip() + '\n'
        if con:
            print('')
            print(text)
        return {'return': 0, 'list_models': True, 'harness': harness, 'text': text}

    # ------------------------------------------------------------------ conversations
    def _list_conversations(self, log_dir, project_path, con):
        convs = CONV.list_conversations(log_dir)
        lines = ['RUN-AI: conversations of %s (%s)' % (project_path, log_dir)]
        if not convs:
            lines.append('  none yet - the next run starts the first one')
        for c in convs:
            lines.append('  ' + CONV.describe(c))
            for h, s in (c.get('sessions') or {}).items():
                lines.append('      %s session %s (%d run(s), started %s)' % (h, s.get('id') or '?', s.get('runs', 0), (s.get('started') or '?')[:16]))
            lines.append('      files: %s, %s' % (os.path.basename(c['_path']), os.path.basename(CONV.transcript_path(c))))
        lines.append('')
        lines.append('  cxt run-ai                      continues the first one listed (the latest activity)')
        lines.append('  cxt run-ai --conversation=<id>  continues that one;  cxt run-ai --new  starts another')
        text = '\n'.join(lines) + '\n'
        if con:
            print('')
            print(text)
        return {'return': 0, 'conversations': [{k: v for k, v in c.items() if not k.startswith('_')} for c in convs], 'text': text}

    @staticmethod
    def _recover_sessions(conv, project_path):
        """A run that crashed before its native session was discovered left "session: ''": try again from its start time."""
        notes = []
        for r in conv.get('runs') or []:
            if r.get('session') or CONV.chooses_id(r.get('harness', '')):
                continue
            try:
                t0 = datetime.datetime.fromisoformat(r.get('started')).timestamp()
            except Exception:
                continue
            sid = CONV.discover_session(r.get('harness', ''), project_path, t0)
            if sid:
                r['session'] = sid
                hk = CONV.harness_key(r['harness'])
                s = conv.setdefault('sessions', {}).setdefault(hk, {'id': sid, 'started': r.get('started'), 'runs': 0})
                if not s.get('id'):
                    s['id'] = sid
                notes.append('session of the run %s recovered: %s %s' % (r.get('stamp'), hk, sid))
        return notes

    # ------------------------------------------------------------------ what a run may write
    def _write_mode(self, write, w, yes):
        """--write=<mode> or -w (all), else --yes (project: what it has always meant), else the key "write" of the
        config task-run-ai (this machine's default), else "ask" -> (mode, where it came from, error)."""
        def mode_of(value):
            word = 'all' if value is True else str(value).strip().lower()
            return next((mode for mode, words in WRITE_WORDS.items() if word in words), '')

        if _truthy(w):
            return 'all', '-w', ''
        if write not in ('', None, False):
            mode = mode_of(write)
            if not mode:
                return '', '', '--write must be one of %s (got "%s")' % (', '.join(WRITE_MODES), write)
            if mode == 'ask' and yes:
                return 'project', '--yes', ''
            return mode, '--write=%s' % mode, ''
        if yes:
            return 'project', '--yes', ''
        value = self._run_ai_config().get(CONFIG_WRITE_KEY)
        if value not in ('', None):
            mode = mode_of(value)
            if not mode:
                return '', '', 'the key "%s" of the config %s must be one of %s (got "%s"; cx config show %s)' % (
                    CONFIG_WRITE_KEY, CONFIG_ARTIFACT, ', '.join(WRITE_MODES), value, CONFIG_ARTIFACT)
            return mode, 'the config %s, key %s' % (CONFIG_ARTIFACT, CONFIG_WRITE_KEY), ''
        return 'ask', 'default', ''

    # ------------------------------------------------------------------ --summarize
    def _summarize(self, ctx, log_dir, conversation, harness, task_ref, extra, model_name, project_path, con, verbose, space):
        """--summarize: one prompt to the harness (claude: its "haiku" unless --model says otherwise) writes a summary of
        a conversation's transcript into !AI/log/<id>.summary.md; a later hand-over points to it first. The
        conversation itself is not continued: no native session of it is used, and its order is kept."""
        hk = CONV.harness_key(harness)
        if conversation:
            conv, err = CONV.find_conversation(log_dir, conversation)
            if err:
                return self.cm.error(err)
        else:
            convs = CONV.list_conversations(log_dir)
            conv = convs[0] if convs else None
            if conv is None:
                return self.cm.error('--summarize: there is no conversation in %s yet' % log_dir)
        tp = CONV.transcript_path(conv)
        if not os.path.isfile(tp):
            return self.cm.error('--summarize: the conversation %s has no transcript yet (%s)' % (conv['id'], tp))
        with open(tp, encoding='utf-8', errors='replace') as f:
            transcript = f.read()
        flags = list(extra or [])
        if not model_name and hk == 'claude':
            flags = ['--model', SUMMARY_CLAUDE_MODEL] + flags
        if hk == 'codex' and '--skip-git-repo-check' not in flags:
            flags = ['--skip-git-repo-check'] + flags
        ask = ('Summarize conversation %s of this project for whoever continues it - a person or another agent. Its '
               'transcript was written by cMeta run-ai. Write Markdown with these sections: Goal; Done (the decisions and '
               'results, with the file paths and commands that matter); State now; Open items and next steps; Facts to keep '
               '(names, ids, paths, numbers agreed on). At most about 60 lines, in the language of the conversation, and '
               'nothing that is not in it. Change no file.' % conv['id'])
        if len(transcript) <= SUMMARY_INLINE_CHARS:
            prompt = ask + ' Use no tool: the transcript follows.\n\n<transcript>\n' + transcript.rstrip() + '\n</transcript>\n'
        else:
            prompt = ask + ' The transcript is long (%d characters): read the file %s, in parts.\n' % (len(transcript), tp.replace('\\', '/'))
        if con:
            print('%sRUN-AI: summarizing conversation %s with %s (%s)' % (space, conv['id'], harness, ' '.join(flags) or 'its default model'))
        rr = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': task_ref, 'ctx': ctx, 'path': project_path,
                             'prompt': prompt, 'interactive': False, 'stats': False, 'skip_output_file': True,
                             'unparsed': flags, 'con': con, 'verbose': verbose})
        text = str(rr.get('output') or '').strip()
        if text.startswith('# '):
            text = text.split('\n', 1)[1].strip() if '\n' in text else ''     # the file has its own title
        if rr.get('return', 1) > 0 or not text:
            return self.cm.error('--summarize: %s gave no summary (%s)' % (harness, rr.get('error') or 'empty output'))
        runs = conv.get('runs') or []
        written = CONV.now_iso()
        model_used = model_name or (SUMMARY_CLAUDE_MODEL if hk == 'claude' else 'the default model')
        sp = CONV.summary_path(conv)
        with open(sp, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# Summary of conversation %s\n\n> Written by `cxt run-ai --summarize` on %s with %s (%s) from the transcript '
                    'as of run %d; the transcript `%s` stays the record.\n\n%s\n' % (
                        conv['id'], written[:16].replace('T', ' '), harness, model_used, len(runs), os.path.basename(tp), text))
        conv['summary'] = {'file': os.path.basename(sp), 'written': written, 'runs': len(runs), 'harness': harness, 'model': model_used}
        CONV.save_conversation(conv, touch=False)
        if con:
            print('%sRUN-AI: summary of conversation %s (%d run(s)): %s' % (space, conv['id'], len(runs), sp))
        return {'return': 0, 'conversation': conv['id'], 'summary': sp, 'runs': len(runs), 'harness': harness, 'model': model_used,
                'inline': len(transcript) <= SUMMARY_INLINE_CHARS, 'text': text}

    # ------------------------------------------------------------------ run
    def run(self,
            ctx: dict,                      # cMeta context
            harness: str = '',              # claude (default) | codex | opencode | openclaw | antigravity (agy) | gemini | <x> (then the task run-<x>)
            agent: str = '',                # the old name of --harness (still accepted)
            project: str = '',              # cRef "category::artifact" of the artifact to work on (default: detect, else cwd)
            ai_dir: str = AI_DIR,           # the folder inside the project that holds the agent's memory and records
            model: str = '',                # the model in the harness's own names, or "<model>,<effort>" (--list_models shows them)
            effort: str = '',               # the reasoning effort, in the harness's vocabulary (--list_models shows it)
            list_models: bool = False,      # list the models and efforts of the harness (of every harness without --harness) and stop
            models: bool = False,           # short alias of "list_models"
            new: bool = False,              # start a new conversation instead of continuing the latest one
            conversation: str = '',         # continue this conversation (its id or a prefix; --conversations lists them)
            resume: str = '',               # alias of "conversation"
            conversations: bool = False,    # list the conversations of the project and stop
            summarize: bool = False,        # write !AI/log/<id>.summary.md for the latest (or --conversation=) conversation and stop
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            interactive: bool = False,      # preload the prompt, then stay in the interactive session
            i: bool = False,                # short alias of "interactive" (-i)
            yes: bool = False,              # answer "yes" to the agent's questions (edits, commands, ...)
            reproducible: bool = False,     # the sub-task's flags that cut the run-to-run variation
            stats: bool = True,             # record the token use and cost (ignored in an interactive session)
            no_log: bool = False,           # do not write the output, the stats, the run record and the conversation into !AI/log
            add_repos: str = '',            # claude only: cMeta repos to add to the context ("alias,alias"; "none")
            codex_state: str = 'project',   # codex only: where its threads, history and memories live - "project" (<project>/!AI/codex, CODEX_SQLITE_HOME) or "home" (CODEX_HOME)
            context: str = '',              # read-only memory and skills of more sources, ";"-separated: "category::artifact;claude:<folder>;..."
            skip_ai_uses: bool = False,     # do not follow ai_uses: the project's list, its repository's default, this machine's mapping
            no_seed: bool = False,          # claude: do not copy Claude Code's own memory of the folder into an empty !AI/memory
            context_depth: int = 1,         # follow ai_uses transitively this many levels (1: the list itself)
            context_limit: int = 20,        # at most this many context sources
            max_context_tokens: int = 0,    # fail (-q, --yes, no terminal) or ask when the estimated context is over this; 0 = config or 30000
            trim_context: bool = False,     # over that limit, leave context sources out (the last first) until it fits; config: trim_context
            dry_run: bool = False,         # show the project, its !AI, the conversation and the command; run nothing
            pending: bool = False,          # list the changes staged for the artifacts this project uses (!AI/pending) and stop
            apply_pending: bool = False,    # show them and apply them on the user's word (-q or --yes: without a question), then stop
            write: str = '',                # what the run may write: ask (the harness asks; the default) | project (no questions) | all (also the used artifacts' memory, directly) | none (read-only); the config key "write" is the default
            w: bool = False,                # short alias of "write=all" (-w)
            context_guard: str = '',        # a direct change in a used artifact's memory or skills, after the run: ask (keep it? else, and with nobody to ask, as restore) | restore (kept as a proposal, the file put back) | report | keep (kept and recorded) | off; the default follows --write (ask, restore, keep, restore)
            unparsed: list = None,          # extra flags for the harness (everything after "--")
    ):
        """Run a coding agent on a cMeta artifact; its memory, skills, logs and conversations live in the artifact's !AI folder."""
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''
        today = datetime.date.today().isoformat()

        given = str(harness or agent or '').strip().lower()
        harness = given or 'claude'
        task_ref, tool_ref = self._harness_refs(harness)
        hk = CONV.harness_key(harness)
        notes = []
        if agent:
            notes.append('--agent is now called --harness (both work)')

        if list_models or models:
            return self._list_models(given, con)

        # the harness must have its task before anything is written
        if not self._artifact_path(TASK_CATEGORY, task_ref):
            return self.cm.error('no task "%s" for the harness "%s" - the known harnesses are %s (any other <x> needs a task run-<x>)' % (
                task_ref, harness, ', '.join(h for h in HARNESSES if h != 'agy')))

        # an interactive session is what the user wants when there is no prompt at all
        interactive = bool(interactive or i) or not (prompt or prompt_file)
        extra = [str(x) for x in (unparsed or [])]
        conversation = str(conversation or resume or '').strip()
        # "--new" is also a control flag of the task engine (a fresh cache entry), which keeps it for itself: read it
        # from the engine's control records as well
        tasks_ctx = ctx.get('tasks') or {}
        new = bool(new or (tasks_ctx.get('run_control') or {}).get('new') or (tasks_ctx.get('cparams') or {}).get('new'))

        # 0. the model and the effort -> the harness's own flags, from the tool's _desc_models.yaml
        model_name, effort_name, note = self._split_model(model, effort)
        model_flags = []
        if model_name or effort_name:
            if note:
                notes.append(note)
            models_desc, models_file, why = self._load_models(harness)
            if models_desc is None:
                notes.append('%s: --model and --effort go to the harness as --model / --effort' % why)
            notes += self._check_model(models_desc, model_name, effort_name, today)
            model_flags, model_t, effort_t = self._native_flags(models_desc, model_name, effort_name)
            # the same flag after "--" would contradict them: run-ai's wins (only for a plain "<flag> <value>" pair)
            for tmpl, what in ((model_t if model_name else None, 'model'), (effort_t if effort_name else None, 'effort')):
                if tmpl and len(tmpl) == 2 and tmpl[1] in ('{{model}}', '{{effort}}') and tmpl[0].startswith('-'):
                    old, extra = self._pull_flag(extra, tmpl[0])
                    if old is not None:
                        notes.append('the %s given after "--" (%s %s) is replaced by --%s=%s' % (
                            what, tmpl[0], old, what, model_name if what == 'model' else effort_name))
            if hk == 'openclaw' and interactive and '--model' in model_flags:
                # OpenClaw's terminal UI refuses --model (only "openclaw agent" takes it): the model is chosen in it
                k = model_flags.index('--model')
                model_flags = model_flags[:k] + model_flags[k + 2:]
                notes.append('openclaw: its terminal UI takes no --model - type "/model %s" in it, or make it the default '
                             'once with "openclaw models set %s"' % (model_name, model_name))
            extra = model_flags + extra
            if model_flags:
                notes.append('model flags: %s' % ' '.join(model_flags))

        # 1. the project and its !AI folder
        r = self._resolve_project(project, con, space)
        if isinstance(r, dict):
            return r
        project_path, cref, how = r
        alias = self._alias_of(cref, project_path)
        ai_root = os.path.join(project_path, ai_dir)
        mem_dir = os.path.join(ai_root, MEMORY_DIR)
        skills_dir = os.path.join(ai_root, SKILLS_DIR)
        log_dir = os.path.join(ai_root, LOG_DIR)
        # the stamp names the records of this run and, for a new conversation, the conversation (reserved below for a
        # run that writes records)
        stamp, stamp_lock = self._new_stamp(log_dir, False)
        stamp_made = []

        if conversations:
            return self._list_conversations(log_dir, project_path, con)
        if _truthy(summarize):
            return self._summarize(ctx, log_dir, conversation, harness, task_ref, extra, model_name, project_path, con, verbose, space)

        # what the run may write: --write / -w, else --yes (project), else this machine's config, else "ask"; the guard
        # of the used artifacts follows it unless --context_guard names one
        write_mode, write_from, err = self._write_mode(write, w, yes)
        if err:
            return self.cm.error(err)
        guard_mode = str(context_guard or WRITE_GUARD[write_mode]).strip().lower()
        if guard_mode not in GUARD_MODES:
            return self.cm.error('--context_guard must be one of %s (got "%s")' % (', '.join(GUARD_MODES), context_guard))

        if pending or apply_pending:
            sources, skipped = self._context_sources(project_path, context, max(1, int(context_depth or 1)), context_limit, skip_ai_uses, cref)
            return self._pending(ai_root, '' if no_log else log_dir, cref or project_path, self._stage_sources(sources, ai_root),
                                 bool(apply_pending), bool(yes or ctx['control'].get('quiet', False)), con, space, stamp)

        # the harness's side of the write mode: "yes" for its task (its own flags that stop the questions and lift the
        # sandbox), or its read-only mode
        forward_yes = False
        if write_mode in ('project', 'all'):
            forward_yes = bool(yes) or hk in YES_HARNESSES
            notes.append('write: %s (%s) - %s; the memory and skills of the used artifacts %s' % (
                write_mode, write_from,
                ('%s asks nothing and may write' % harness) if forward_yes else
                ('%s has no switch for its questions that run-ai knows: it follows its own settings' % harness),
                'may be changed directly (kept, recorded there, the versions before the run saved)' if guard_mode == 'keep' else
                {'restore': 'take proposals only (a direct change is put back and staged)', 'ask': 'take proposals (you are asked about a direct change)',
                 'report': 'are compared after the run (a direct change is reported)', 'off': 'are not looked at after the run'}[guard_mode]))
        elif write_mode == 'none':
            read_only = READ_ONLY_FLAGS.get(hk)
            # the same setting given after "--" is the user's own choice for this run
            names = ('--sandbox', '-s') if hk == 'codex' else ((read_only[0],) if read_only else ())
            own = [x for x in extra if x.split('=')[0] in names or (hk == 'codex' and 'sandbox_mode' in x)]
            if read_only and not own:
                extra = read_only + extra
            notes.append('write: none (%s) - read-only: %s%s' % (
                write_from,
                ('%s runs with %s' % (harness, ' '.join(read_only))) if (read_only and not own) else
                ('the flags after "--" decide (%s)' % ' '.join(own)) if own else
                ('%s has no read-only mode that run-ai knows - it is told to change nothing, and nothing enforces that' % harness),
                '; --yes is left out' if yes else ''))
        elif write_from != 'default':
            notes.append('write: ask (%s) - %s asks before it edits or runs a command' % (write_from, harness))

        # codex keeps its SQLite state (threads, thread history, memories) INSIDE the project: CODEX_SQLITE_HOME, which
        # Codex 0.160 honours (the thread lands there and "codex exec resume" finds it; the rollout
        # files stay in CODEX_HOME). The lookups of conversations.py read the same store, before and after the run.
        codex_dir = ''
        project_codex = os.path.join(ai_root, 'codex')
        if str(codex_state or 'project').lower() != 'home':
            if hk == 'codex':
                codex_dir = project_codex
            # the transcript of a run with another harness re-exports the codex segments of the conversation from there too
            CONV.set_codex_sqlite_home(project_codex if (codex_dir or os.path.isdir(project_codex)) else '')
        else:
            CONV.set_codex_sqlite_home('')

        # 1a. the conversation: continue the latest (default), a given one, or start a new one
        conv, conv_how, native_sid, new_sid, handover = None, '', '', '', ''
        if no_log:
            notes.append('--no_log: no conversation is recorded or continued (the harness starts a fresh session)')
        else:
            if not dry_run:
                stamp_made = [d for d in (log_dir, ai_root) if not os.path.isdir(d)]
                stamp, stamp_lock = self._new_stamp(log_dir, True)
            if conversation:
                conv, err = CONV.find_conversation(log_dir, conversation)
                if err:
                    self._release_stamp(stamp_lock, stamp_made)
                    return self.cm.error(err)
            elif not new:
                convs = CONV.list_conversations(log_dir)
                conv = convs[0] if convs else None
            if conv is None:
                title = CONV.title_from_prompt(prompt or (('file ' + os.path.basename(prompt_file)) if prompt_file else ''), interactive, stamp)
                conv = CONV.new_conversation(log_dir, stamp, project_path, cref, title)
                conv_how = 'new'
                if new and CONV.list_conversations(log_dir):
                    notes.append('--new: a new conversation %s (the previous ones stay in %s; --conversations lists them)' % (stamp, log_dir))
            else:
                conv_how = 'continued'
                notes += self._recover_sessions(conv, project_path)
            sess = (conv.get('sessions') or {}).get(hk) or {}
            if sess.get('id') and CONV.session_exists(harness, sess['id'], project_path):
                native_sid = sess['id']
                if hk == 'codex':
                    pass        # run-codex --resume=<id> (a sub-command, not a flag)
                else:
                    extra = CONV.resume_flags(harness, native_sid, interactive) + extra
            else:
                if conv_how == 'continued' and conv.get('runs'):
                    # a hand-over needs something to hand over: a session that was quit before its first message
                    # leaves nothing in the store and nothing in the transcript
                    has_content = any(s.get('exported') for s in (conv.get('sessions') or {}).values()) or \
                        any(os.path.isfile(os.path.join(log_dir, '%s.%s.output.txt' % (r.get('stamp'), r.get('harness')))) for r in conv['runs'])
                    if has_content:
                        why = ('no %s session in it yet' % hk) if not sess.get('id') else ('its %s session %s is not in the store any more' % (hk, sess['id']))
                        handover = CONV.handover_text(conv, harness, log_dir, why)
                    else:
                        notes.append('the previous run(s) of this conversation left no transcript (quit before the first message): '
                                     'a fresh %s session, nothing to hand over' % hk)
                if CONV.chooses_id(harness):
                    new_sid = CONV.new_id()
                    extra = CONV.new_session_flags(harness, new_sid, conv['id'], alias, interactive) + extra

        # 1b. the context: other artifacts' memory and skills, read-only (--context, then ai_uses), after the
        #     orientation every harness gets first (where this project keeps its memory, skills and conversations)
        sources, skipped = self._context_sources(project_path, context, max(1, int(context_depth or 1)), context_limit, skip_ai_uses, cref)
        own_skills = self._list_skills(skills_dir)
        for name, changed, src in self._skill_drift(skills_dir):
            again = 'cxt import-ai "--project=%s" "--skills=%s" --overwrite' % (cref or project_path, src)
            notes.append({'source': 'WARNING: the skill %s is older than the one it was imported from, %s, which changed since: %s renews the copy',
                          'copy': 'the skill %s was changed here since it was imported from %s (which was not): carry the change over there '
                                  'if it should stay - %s would drop it',
                          'both': 'WARNING: the skill %s and the one it was imported from, %s, both changed since the import: compare them; '
                                  '%s takes the source\'s'}[changed] % (name, src, again))
        # the used artifacts are read-only for the run: each gets its staging folder under this project's !AI/pending
        guarded = self._stage_sources(sources, ai_root)
        # a budget, on request: over the token limit, the context sources are left out from the last - the lowest
        # priority: this machine's mapping, the repository's default, the deeper levels - until the estimate fits
        if sources and (_truthy(trim_context) or _truthy(self._run_ai_config().get(CONFIG_TRIM_KEY))):
            limit_now, limit_now_from = self._token_limit(max_context_tokens)
            index_fp = os.path.join(mem_dir, INDEX_FILE)
            index_now = ''
            if os.path.isfile(index_fp):
                with open(index_fp, encoding='utf-8', errors='replace') as f:
                    index_now = f.read()

            def estimate(kept):
                return self._estimate([
                    ('orientation', self._orientation(ai_root, conv, conv_how, log_dir, own_skills, kept, guard_mode,
                                                      own_workspace='~/.openclaw/workspace' if hk == 'openclaw' else '', write=write_mode), ''),
                    ('memory index', index_now, ''), ('skills', ' '.join('%s %s' % (n, d) for n, d, fp in own_skills), ''),
                    ('context sources', self._render_context(kept, True, guard_mode == 'keep') if kept else '', ''),
                    ('hand-over', handover, ''), ('prompt', prompt or '', '')])[1]
            left_out = []
            while sources and estimate(sources) > limit_now:
                left_out.insert(0, sources.pop())
            if left_out:
                notes.append('context trimmed to the limit of %s tokens (%s; --trim_context): left out %s' % (
                    '{:,}'.format(limit_now), limit_now_from, '; '.join(s['label'] for s in left_out)))
                skipped += [(s['label'], 'left out to fit the token limit (--trim_context)') for s in left_out]
                guarded = self._stage_sources(sources, ai_root)
        pending_root = os.path.join(ai_root, PEND.PENDING_DIR)
        # OpenClaw runs a turn in its own workspace (~/.openclaw/workspace, from its config), whatever the current
        # directory: it is told where the project is. Its workspace is not moved to the project, since OpenClaw keeps
        # its persona files there (AGENTS.md, SOUL.md, ...)
        orientation = self._orientation(ai_root, conv, conv_how, log_dir, own_skills, sources, guard_mode,
                                        own_workspace='~/.openclaw/workspace' if hk == 'openclaw' else '', write=write_mode)
        context_text = ''
        # with --no_log the files of the run go to the temp directory under names nobody can guess, and are removed after it
        temp_tag = 'run-ai-%s-%s' % (stamp, CONV.new_id()[:8])
        temp_files = []
        context_file = os.path.join(log_dir, '%s.%s.context.md' % (stamp, harness)) if not no_log else \
            os.path.join(tempfile.gettempdir(), '%s.%s.context.md' % (temp_tag, harness))
        if no_log:
            temp_files.append(context_file)

        # 2. the sub-task's parameters: everything the user gave, plus the records in !AI/log
        params = {'prompt': prompt, 'prompt_file': prompt_file, 'interactive': interactive, 'stats': stats}
        # only when asked for: not every run-<harness> task has them (run-openclaw has neither)
        if forward_yes:
            params['yes'] = True
        if reproducible:
            params['reproducible'] = True
        if harness == 'claude' and add_repos:
            params['add_repos'] = add_repos
        if native_sid and hk == 'codex':
            params['resume'] = native_sid
        if not no_log:
            params['output_file'] = os.path.join(log_dir, '%s.%s.output.txt' % (stamp, harness))
            if stats and not interactive:
                params['stats_file'] = os.path.join(log_dir, '%s.%s.stats.json' % (stamp, harness))
            # a prompt too long for a command line argument (an interactive session preloads it that way; opencode and
            # openclaw have no stdin mode) is written here by the run task, and the harness is asked to read it first
            if hk in LONG_PROMPT_HARNESSES:
                params['long_prompt_file'] = os.path.join(log_dir, '%s.%s.prompt.md' % (stamp, harness))
        else:
            params['skip_output_file'] = True       # else the run task writes run-<harness>-output.txt into the project
            # (and a long prompt goes to a temporary file the run task removes afterwards)

        # 3. how this harness reads (and, for claude, writes) the project's memory and skills
        env = {}
        settings, settings_file = None, ''
        mem_posix = mem_dir.replace('\\', '/')
        plugin_dirs = []
        if harness == 'claude':
            n_seed, native = self._seed_memory(project_path, mem_dir, apply=not (dry_run or no_seed))
            if n_seed:
                notes.append("%s %d memory file(s) from Claude's native folder %s (left as it is)" % (
                    'NOT copied (--no_seed):' if no_seed else ('would seed' if dry_run else 'seeded'), n_seed, native))
            user, extra, warn = self._user_settings(extra)
            if warn:
                notes.append(warn)
            else:
                settings = self._claude_settings(mem_posix, user)
                settings_file = os.path.join(log_dir, '%s.claude.settings.json' % stamp) if not no_log else \
                    os.path.join(tempfile.gettempdir(), '%s.claude.settings.json' % temp_tag)
                if no_log:
                    temp_files.append(settings_file)
                extra = ['--settings', settings_file] + extra
                notes.append('memory: read and written in %s (autoMemoryDirectory)' % mem_dir)
            if own_skills:
                plugin_file, created = self._ensure_plugin(ai_root, alias, cref, apply=not dry_run)
                plugin_dirs.append(ai_root)
                notes.append('skills: %d in %s, loaded as the plugin "%s" (--plugin-dir%s)' % (
                    len(own_skills), skills_dir, self._plugin_name(alias), '; plugin.json written' if created else ''))
            for s in sources:
                if s['plugin']:
                    plugin_dirs.append(s['plugin'])
            have_plugins = {os.path.normcase(os.path.abspath(extra[k + 1])) for k, x in enumerate(extra) if x == '--plugin-dir' and k + 1 < len(extra)}
            for d in plugin_dirs:
                if os.path.normcase(os.path.abspath(d)) not in have_plugins:
                    extra += ['--plugin-dir', d]
            # the orientation and the context go into the system prompt; a --append-system-prompt[-file] of the user's is
            # kept in front of them
            context_text = orientation + (self._render_context(sources, False, guard_mode == 'keep') if sources else '')
            user_file, extra = self._pull_flag(extra, '--append-system-prompt-file')
            user_text, extra = self._pull_flag(extra, '--append-system-prompt')
            if user_file and os.path.isfile(user_file):
                with open(user_file, encoding='utf-8', errors='replace') as f:
                    user_text = (user_text + '\n\n' if user_text else '') + f.read()
            if user_text:
                context_text = user_text.rstrip() + '\n\n' + context_text
            extra += ['--append-system-prompt-file', context_file]
            # read access to the context folders, so that a memory or a skill can be opened from the project
            have = {os.path.normcase(os.path.abspath(extra[k + 1])) for k, x in enumerate(extra) if x == '--add-dir' and k + 1 < len(extra)}
            for s in sources:
                if os.path.normcase(os.path.abspath(s['root'])) not in have:
                    extra += ['--add-dir', s['root']]
        else:
            own = self._memory_text(ai_root)
            if own_skills:
                own += self._skills_text('this project (%s/%s)' % (AI_DIR, SKILLS_DIR), own_skills)
                notes.append('skills: %d in %s, listed for the harness in the prompt' % (len(own_skills), skills_dir))
            context_text = orientation + (self._render_context(sources, True, guard_mode == 'keep') if sources else '')
            if hk == 'codex' and not interactive and '--skip-git-repo-check' not in extra:
                # "codex exec" refuses a folder that is neither a git repository nor a trusted project without it
                extra = ['--skip-git-repo-check'] + extra
            if hk == 'codex':
                # no --add-dir for the context: codex's --add-dir means "more WRITABLE roots" and codex refuses to start
                # with it under its read-only sandbox; the context is read-only anyway and codex reads the files named
                # in the context text as it is. Instructions that ask codex for session files of its own are overruled:
                # run-ai keeps the conversation itself
                own += ('Session records: run-ai keeps this session in %s/%s (the conversation and its transcript); do not write '
                        'resume scripts or session summaries into the project folder.\n' % (AI_DIR, LOG_DIR))
                if codex_dir:
                    env['CODEX_SQLITE_HOME'] = codex_dir
                    notes.append('codex state: threads, thread history and memories in %s (CODEX_SQLITE_HOME; --codex_state=home keeps them in CODEX_HOME)' % codex_dir)
            if hk == 'gemini':
                # gemini's equivalent of --add-dir: the context folders join the workspace, so a memory can be read.
                # Gemini CLI splits each value at its commas, so a folder with a comma in its path cannot be mounted:
                # its index is in the prompt all the same
                for s in sources:
                    if ',' in s['root']:
                        notes.append('context: %s is not mounted for gemini (--include-directories splits a path at its commas); '
                                     'its memory index is in the prompt' % s['root'])
                    else:
                        extra += ['--include-directories', s['root']]
            if hk == 'agy':
                # agy takes extra workspace folders like claude (repeatable --add-dir); its own file tools stay inside the
                # workspace by default (allowNonWorkspaceAccess), so a context memory must be mounted to be readable
                for s in sources:
                    extra += ['--add-dir', s['root']]
            memory_text = self._memory_text(ai_root)
            if hk == 'opencode':
                files = [(os.path.join(mem_dir, INDEX_FILE)).replace('\\', '/'), (os.path.join(mem_dir, '*.md')).replace('\\', '/'),
                         context_file.replace('\\', '/')]
                env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'instructions': files})
                notes.append('memory: read from %s as instructions (OPENCODE_CONFIG_CONTENT), with the orientation%s; opencode has no memory of its own' % (
                    mem_dir, ' and the context' if sources else ''))
                text = own.replace(memory_text, '')     # the memory, the orientation and the context go through the instructions
            else:
                text = context_text + own
                if memory_text.strip():
                    notes.append('memory: the index of %s%s is prepended to the prompt (%d chars); %s keeps its own memory in its home (v1)' % (
                        mem_dir, ' and the context' if context_text else '', len(text), harness))
                else:
                    notes.append('memory: %s has nothing yet; %s keeps its own memory in its home (v1)' % (mem_dir, harness))
            if text.strip():
                params['prompt'] = text + '\n' + CONV.REQUEST_MARK + '\n' + (prompt or '')
        if handover:
            if CONV.REQUEST_MARK not in (params.get('prompt') or ''):
                params['prompt'] = CONV.REQUEST_MARK + '\n' + (params.get('prompt') or '')
            params['prompt'] = handover + '\n' + params['prompt']
        for s in sources:
            notes.append('context: %s (%s) <- %s%s' % (s['label'], s['kind'], s['memory_dir'] if s['has_memory'] else 'no memory',
                                                     (', %d skill(s)%s' % (len(s['skills']), ' as a plugin' if (s['plugin'] and harness == 'claude') else ' listed')) if s['skills'] else ''))
        for label, why in skipped:
            notes.append('context skipped: %s - %s' % (label, why))
        if guarded:
            notes.append('context guard: %s' % {'ask': 'after the run you are asked about any direct change in a used artifact\'s memory or skills; not kept (or nobody to ask), it becomes a proposal in %s and the file is put back' % pending_root,
                                                'restore': 'a direct change in a used artifact\'s memory or skills becomes a proposal in %s and the file is put back' % pending_root,
                                                'report': 'direct changes in the used artifacts\' memory and skills are reported after the run',
                                                'keep': 'direct changes in the used artifacts\' memory and skills are kept: listed after the run, recorded in the '
                                                        'artifact\'s %s/%s, the versions before the run saved in %s' % (
                                                            AI_DIR, LOG_DIR, ('%s/%s.before' % (log_dir, stamp)) if not no_log else 'no folder (--no_log)'),
                                                'off': 'off (--context_guard=off)'}[guard_mode])
            staged_now = PEND.count(pending_root, guarded)
            if staged_now:
                notes.append('%d change(s) for used artifacts are staged: "cxt run-ai --pending" lists them, "--apply_pending" applies them on your word' % staged_now)

        # the estimate of what the harness will be given, against the limit
        index_fp = os.path.join(mem_dir, INDEX_FILE)
        index_text = ''
        if os.path.isfile(index_fp):
            with open(index_fp, encoding='utf-8', errors='replace') as f:
                index_text = f.read()
        parts = [('orientation', orientation, ''),
                 ('memory index', index_text, '%d entries%s' % (index_text.count('\n- ') + (1 if index_text.lstrip().startswith('- ') else 0),
                                                              ', read by claude at start' if harness == 'claude' else ', in the prompt')),
                 ('skills', ' '.join('%s %s' % (n, d) for n, d, fp in own_skills), '%d skill(s)' % len(own_skills)),
                 ('context sources', self._render_context(sources, True, guard_mode == 'keep') if sources else '', '%d source(s): their indexes and skills' % len(sources)),
                 ('hand-over', handover, ''),
                 ('prompt', prompt or '', ('file ' + os.path.basename(prompt_file)) if prompt_file else '')]
        est_rows, est_total = self._estimate(parts)
        limit, limit_from = self._token_limit(max_context_tokens)
        cache_line = self._cache_line(harness, conv if conv_how == 'continued' else None)
        over = est_total > limit

        conv_line = ''
        if conv is not None:
            if conv_how == 'new':
                conv_line = 'new conversation %s' % conv['id']
            elif native_sid:
                conv_line = 'conversation %s continued: %s resumes its session %s' % (conv['id'], hk, native_sid)
            elif handover:
                conv_line = 'conversation %s continued with %s: the transcript is handed over in the prompt' % (conv['id'], hk)
            else:
                conv_line = 'conversation %s continued with a fresh %s session (nothing to hand over)' % (conv['id'], hk)
            if new_sid:
                conv_line += ' (new %s session %s)' % (hk, new_sid)
            elif not native_sid and not CONV.chooses_id(harness):
                conv_line += ' (the %s session id is read from its store after the run)' % hk

        if con:
            print('')
            print('%sRUN-AI: harness %s -> task %s' % (space, harness, task_ref))
            print('%s        project: %s' % (space, project_path))
            print('%s                 %s%s' % (space, how, (' - ' + cref) if cref else ''))
            print('%s        !AI:     %s' % (space, ai_root))
            if model_name or effort_name:
                print('%s        model:   %s%s' % (space, model_name or '(the harness default)', (', effort ' + effort_name) if effort_name else ''))
            if conv_line:
                print('%s        %s' % (space, conv_line))
            for n in notes:
                print('%s        %s' % (space, n))
            if not no_log:
                print('%s        log:     %s' % (space, os.path.join(log_dir, '%s.%s.*' % (stamp, harness))))
            if extra:
                print('%s        flags:   %s' % (space, ' '.join(extra)))
            if params.get('resume'):
                print('%s        run-codex --resume=%s' % (space, params['resume']))
            if settings is not None:
                print('%s        settings: %s' % (space, json.dumps(settings)))
            if handover:
                print('%s        hand-over: %s' % (space, handover.strip()))
            print('%s        context estimate (chars/%d; the harness counts afterwards):' % (space, TOKEN_CHARS))
            for label, n, note in est_rows:
                print('%s          %-16s %7s tokens%s' % (space, label, '{:,}'.format(n), ('   ' + note) if note else ''))
            print('%s          %-16s %7s tokens   limit %s (%s)%s' % (space, 'total', '{:,}'.format(est_total), '{:,}'.format(limit), limit_from,
                                                                     '   OVER THE LIMIT' if over else ''))
            if cache_line:
                print('%s          %s' % (space, cache_line))

        if dry_run:
            if con:
                print('%sDRY RUN - nothing was run or created.' % space)
            return {'return': 0, 'dry_run': True, 'harness': harness, 'task': task_ref, 'model': model_name, 'effort': effort_name,
                    'model_flags': model_flags, 'project': project_path, 'cref': cref, 'how': how, 'ai_root': ai_root,
                    'conversation': conv['id'] if conv else '', 'conversation_how': conv_how, 'native_session': native_sid,
                    'new_session': new_sid, 'handover': handover, 'skills': [s[0] for s in own_skills], 'plugin_dirs': plugin_dirs,
                    'tokens_estimated': est_total, 'token_limit': limit, 'token_limit_from': limit_from, 'context_depth': context_depth,
                    'params': params, 'flags': extra, 'env': env, 'settings': settings, 'context': sources, 'context_skipped': skipped,
                    'write': write_mode, 'write_from': write_from, 'context_guard': guard_mode, 'notes': notes}

        if over:
            quiet = bool(ctx['control'].get('quiet', False))
            interactive_terminal = bool(getattr(sys.stdin, 'isatty', lambda: False)())
            what = 'the estimated context is %s tokens, over the limit of %s (%s)' % ('{:,}'.format(est_total), '{:,}'.format(limit), limit_from)
            if quiet or yes or not con or not interactive_terminal:
                self._release_stamp(stamp_lock, stamp_made)
                return self.cm.error('%s - lower --context_depth / --context_limit, use --skip_ai_uses, trim the memory index, or raise '
                                     '--max_context_tokens (or cx config set %s --meta.%s=<n>)' % (what, CONFIG_ARTIFACT, CONFIG_TOKENS_KEY))
            try:
                answer = input('RUN-AI: %s. Continue anyway? [y/N] ' % what).strip().lower()
            except Exception:
                answer = ''
            if answer not in ('y', 'yes'):
                self._release_stamp(stamp_lock, stamp_made)
                return self.cm.error('stopped: %s' % what)
            notes.append('the context estimate (%s tokens) is over the limit (%s); continued on the user\'s word' % ('{:,}'.format(est_total), '{:,}'.format(limit)))

        # 4. the folders, the settings and context files, the conversation and the run record (written before the run,
        #    so a crash still leaves a trace)
        os.makedirs(mem_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        if codex_dir:
            os.makedirs(codex_dir, exist_ok=True)
        if settings is not None:
            os.makedirs(os.path.dirname(settings_file), exist_ok=True)
            with open(settings_file, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(settings, f, indent=1)
        if context_file:
            os.makedirs(os.path.dirname(context_file), exist_ok=True)
            with open(context_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(context_text)
        run_entry = None
        if conv is not None:
            sid_now = native_sid or new_sid
            sessions = conv.setdefault('sessions', {})
            s = sessions.get(hk)
            if s and s.get('id') and s['id'] != sid_now:
                s.setdefault('previous', []).append({'id': s['id'], 'started': s.get('started', ''), 'runs': s.get('runs', 0),
                                                     'exported': s.get('exported', 0)})
                s['id'] = sid_now
                s['started'] = CONV.now_iso()
                s['runs'] = 0
            elif not s:
                s = sessions[hk] = {'id': sid_now, 'started': CONV.now_iso(), 'runs': 0}
            s['runs'] = int(s.get('runs') or 0) + 1
            s['last'] = CONV.now_iso()
            run_entry = {'stamp': stamp, 'harness': harness, 'mode': 'interactive' if interactive else 'prompt', 'model': model_name,
                         'effort': effort_name, 'prompt': CONV.title_from_prompt(prompt or (('file ' + os.path.basename(prompt_file)) if prompt_file else ''), interactive, stamp),
                         'started': CONV.now_iso(), 'session': sid_now, 'resumed': bool(native_sid), 'handover': bool(handover),
                         'tokens_estimated': est_total, 'token_limit': limit}
            conv.setdefault('runs', []).append(run_entry)
            CONV.save_conversation(conv)
        record = os.path.join(log_dir, '%s.%s.run.md' % (stamp, harness)) if not no_log else ''
        if record:
            lines = ['# run-ai %s - %s' % (stamp, harness), '',
                     '| | |', '|---|---|',
                     '| harness | `%s` (task `%s`) |' % (harness, task_ref),
                     '| project | `%s` |' % project_path,
                     '| resolved | %s%s |' % (how, (' - `%s`' % cref) if cref else ''),
                     '| started | %s |' % datetime.datetime.now().isoformat(timespec='seconds'),
                     '| mode | %s |' % ('interactive' if interactive else 'one prompt (-p)'),
                     '| model | %s |' % (('`%s`' % model_name) if model_name else 'the harness default'),
                     '| effort | %s |' % (('`%s`' % effort_name) if effort_name else 'the harness default'),
                     '| write | `%s` (%s); context guard `%s` |' % (write_mode, write_from, guard_mode),
                     '| conversation | %s |' % (('`%s` - %s' % (conv['id'], conv_how + (', native resume' if native_sid else (', hand-over' if handover else '')))) if conv else 'none (--no_log)'),
                     '| session | %s |' % (('%s `%s`' % (hk, native_sid or new_sid)) if (native_sid or new_sid) else ('%s: read from its store after the run' % hk if conv else '')),
                     '| prompt | %d chars%s |' % (len(params.get('prompt') or ''), (' + file `%s`' % prompt_file) if prompt_file else ''),
                     '| harness flags | `%s` |' % (' '.join(extra) if extra else ''),
                     '| environment | %s |' % (', '.join('`%s`' % k for k in env) if env else ''),
                     '| settings | `%s` |' % (os.path.basename(settings_file) if settings_file else ''),
                     '| skills | %s |' % ((', '.join(s[0] for s in own_skills) + (' (plugin)' if plugin_dirs else ' (listed in the prompt)')) if own_skills else 'none'),
                     '| context | %s `%s` |' % (('%d source(s)' % len(sources)) if sources else 'the orientation only', os.path.basename(context_file)),
                     '| context estimate | %s tokens of %s (%s)%s |' % ('{:,}'.format(est_total), '{:,}'.format(limit), limit_from, ('; ' + cache_line) if cache_line else ''),
                     '| output | `%s` |' % os.path.basename(params.get('output_file', '') or ''),
                     '| stats | `%s` |' % os.path.basename(params.get('stats_file', '') or ''), '']
            lines += ['- ' + n for n in notes]
            if handover:
                lines += ['', '> hand-over: ' + handover.strip()]
            with open(record, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(lines) + '\n')
        self._release_stamp(stamp_lock)     # the stamp is taken by the records now

        # 5. run the harness's task inside the project folder (the engine's "path" control: cd there, back afterwards)
        before = CONV.capture_before(harness, project_path)
        # the memory and skills of the used artifacts as they are now: compared again when the harness is back
        snaps = {g['ai']: PEND.snapshot(g['ai']) for g in guarded} if guard_mode != 'off' else {}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        t0 = time.time()
        try:
            rr = self.cm.access(dict(params, category=TASK_CATEGORY, command='run', arg1=task_ref, ctx=ctx,
                                     path=project_path, unparsed=extra, con=con, verbose=verbose))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        seconds = time.time() - t0

        # 6. close the conversation: the native session (discovered now for the harnesses that name it only afterwards)
        #    and the transcript, re-exported from the harnesses' own stores
        after_notes = []
        transcript = ''
        if rr.get('long_prompt_file') and os.path.isfile(rr['long_prompt_file']):
            after_notes.append('the prompt was too long for a command line argument: written to %s, %s was asked to read it first' % (
                os.path.basename(rr['long_prompt_file']), hk))
        if conv is not None and run_entry is not None:
            sid = native_sid or new_sid
            if not sid:
                sid = CONV.discover_session(harness, project_path, t0, rr, before)
                if sid:
                    run_entry['session'] = sid
                    s = conv['sessions'].get(hk) or {}
                    s['id'] = sid
                    conv['sessions'][hk] = s
                    after_notes.append('%s session %s (from its store)' % (hk, sid))
                else:
                    # no session was created (the harness failed to start, or it keeps none): drop the empty placeholder
                    s = conv['sessions'].get(hk) or {}
                    if not s.get('id') and not s.get('previous'):
                        conv['sessions'].pop(hk, None)
                    after_notes.append('no %s session was found in its store%s; the next run with %s hands the transcript over instead' % (
                        hk, (' (the harness exited with code %s)' % rr.get('returncode')) if rr.get('returncode') else '', hk))
            elif new_sid and rr.get('return', 1) > 0:
                # a failed run under a session id run-ai had chosen: did the harness get as far as a conversation? Not
                # when it is not signed in, its account is refused or a flag is wrong - and a session file alone does
                # not say so (Gemini CLI writes one before it checks the account): a session without a single turn
                # is not kept, so that the conversation shows no empty segment for it
                try:
                    started = bool(CONV.session_exists(harness, new_sid, project_path) and CONV.export_session(harness, new_sid, project_path))
                except Exception:
                    started = True      # unreadable: leave things as they are
                if not started:
                    s = conv['sessions'].get(hk) or {}
                    if s.get('id') == new_sid:
                        previous = s.get('previous') or []
                        if previous:
                            # back to the session this one was to replace (the next run finds it gone and starts another)
                            last = previous.pop()
                            last = last if isinstance(last, dict) else {'id': last}
                            for key in ('id', 'started', 'runs', 'exported'):
                                if key in last:
                                    s[key] = last[key]
                            if not previous:
                                s.pop('previous', None)
                        else:
                            conv['sessions'].pop(hk, None)
                    run_entry['session'] = ''
                    after_notes.append('%s did not get as far as a session: the next run with %s starts one and is handed the transcript' % (hk, hk))
            if hk == 'openclaw' and interactive and new_sid and run_entry.get('session') == new_sid:
                # OpenClaw's terminal UI files a new session under an id of its own (the key it was given names
                # run-ai's): that id is the one a later headless turn must name, or the turn would start a file of its own
                real = CONV.openclaw_session_id(new_sid)
                if real and real != new_sid:
                    s = conv['sessions'].get(hk) or {}
                    if s.get('id') == new_sid:
                        s['id'] = real
                    run_entry['session'] = real
                    after_notes.append('openclaw session %s (the id its terminal UI chose)' % real)
            run_entry['finished'] = CONV.now_iso()
            run_entry['seconds'] = round(seconds, 1)
            run_entry['return'] = rr.get('return', 1)
            tokens = rr.get('tokens') or {}
            if tokens:
                run_entry['tokens'] = {k: tokens[k] for k in ('sent', 'output', 'total', 'cost_usd') if k in tokens}
            CONV.save_conversation(conv)
            try:
                transcript, t_notes = CONV.write_transcript(conv, log_dir)
                after_notes += t_notes
                # what the transcript exported ("exported" per session) tells the next run whether there is a
                # conversation to hand over - also after an interactive run, which leaves no output file
                CONV.save_conversation(conv)
            except Exception as e:
                after_notes.append('the transcript could not be written: %s' % e)

        # 6b. the used artifacts are read-only for a run: about what changed in their memory and skills without the
        #     user's word the user is asked; not kept - or with nobody to ask - it becomes a proposal and is put back
        #     (or is only reported), for every harness alike. A run with --write=all has that word beforehand: its
        #     changes are kept and recorded, and the versions before the run saved ("keep")
        guard_notes, guard_records = [], []
        if snaps:
            def ask_user(source, ch):
                print('')
                print('%sRUN-AI: %d file(s) in the memory or skills of %s changed during this run - not through %s:' % (
                    space, len(ch), source['label'], pending_root))
                for rel, what, sha in ch[:20]:
                    print('%s          %-8s %s' % (space, what, rel))
                try:
                    return input('%s        Keep %s? [y/N]  (N: put back as before the run, and kept as a proposal for '
                                 '"cxt run-ai --apply_pending") ' % (space, 'it' if len(ch) == 1 else 'them')).strip().lower() in ('y', 'yes')
                except (Exception, KeyboardInterrupt):
                    return False        # no answer: put back, and kept as a proposal

            # somebody to ask: an interactive terminal, and neither -q nor --yes
            ask = ask_user if (guard_mode == 'ask' and con and not yes and not ctx['control'].get('quiet', False)
                               and bool(getattr(sys.stdin, 'isatty', lambda: False)())) else None
            try:
                guard_notes, guard_records = PEND.guard(guarded, snaps, t0, time.time(), guard_mode, pending_root, stamp,
                                                        ask, cref or project_path,
                                                        keep_root=os.path.join(log_dir, '%s.before' % stamp) if not no_log else '')
            except Exception as e:
                guard_notes = ['context guard: the used artifacts could not be compared with their state before the run: %s' % e]
        staged_now = PEND.count(pending_root, guarded) if guarded else 0
        if staged_now:
            guard_notes.append('%d change(s) for used artifacts are staged in %s: "cxt run-ai --pending" lists them, '
                               '"cxt run-ai --apply_pending" applies them on your word' % (staged_now, pending_root))
        if record:
            memories = sorted(os.path.basename(x) for x in _glob(mem_dir, '*.md'))
            with open(record, 'a', encoding='utf-8', newline='\n') as f:
                f.write('\n| finished | %s |\n| duration | %.0f s |\n| return | %s%s |\n' % (
                    datetime.datetime.now().isoformat(timespec='seconds'), seconds, rr.get('return', '?'),
                    (' - ' + str(rr.get('error', ''))) if rr.get('return', 0) > 0 else ''))
                if conv is not None:
                    f.write('| conversation files | `%s`, `%s` |\n' % (os.path.basename(conv['_path']), os.path.basename(transcript) if transcript else '-'))
                    if run_entry and run_entry.get('session'):
                        f.write('| session after the run | %s `%s` |\n' % (hk, run_entry['session']))
                f.write('| memory files after the run | %d%s |\n' % (len(memories), (': ' + ', '.join(memories[:20])) if memories else ''))
                for n in after_notes + guard_notes:
                    f.write('- %s\n' % n.strip())
        if con:
            print('')
            print('%sRUN-AI: done in %.0f s - records in %s' % (space, seconds, ai_root))
            if conv is not None:
                print('%s        conversation %s: %s' % (space, conv['id'], CONV.describe(conv)))
                if transcript:
                    print('%s        transcript:   %s' % (space, transcript))
                for n in after_notes:
                    print('%s        %s' % (space, n))
                print('%s        "cxt run-ai" continues it (any harness, any model); "cxt run-ai --new" starts another' % space)
            for n in guard_notes:
                print('%s        %s' % (space, n))

        CONV.set_codex_sqlite_home('')
        for fp in temp_files:
            try:
                os.remove(fp)
            except OSError:
                pass
        out = {'return': rr.get('return', 1), 'harness': harness, 'task': task_ref, 'model': model_name, 'effort': effort_name,
               'project': project_path, 'cref': cref, 'ai_root': ai_root, 'record': record, 'seconds': round(seconds, 1),
               'conversation': conv['id'] if conv else '', 'session': (run_entry or {}).get('session', ''), 'transcript': transcript,
               'codex_state': codex_dir or ('home' if hk == 'codex' else ''),
               'write': write_mode, 'write_from': write_from,
               'context_guard': guard_mode, 'context_changes': guard_records, 'pending': staged_now}
        if rr.get('return', 0) > 0:
            out['error'] = rr.get('error', 'the harness task failed')
        for k in ('output_file', 'stats_file', 'stats', 'returncode', 'tokens'):
            if k in rr:
                out[k] = rr[k]
        return out
