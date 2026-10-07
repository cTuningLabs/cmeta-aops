"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The conversations of run-ai (2026-10-04): the state that lets "cxt run-ai" pick up where the last run stopped,
with any harness and any model, and the transcript of every conversation kept in the project's !AI/log.

A conversation is a thread of runs on one project. Each harness keeps its own native session for it (Claude Code a
session id in ~/.claude/projects/<slug>/<id>.jsonl, Codex a thread in CODEX_HOME, Antigravity a conversation in
~/.gemini/antigravity-cli, OpenCode a session in its database, OpenClaw and Gemini CLI a session file). run-ai
remembers them per conversation:

    !AI/log/<id>.conversation.json     id = the stamp of the first run (YYYYMMDD-HHMMSS); the runs, the title, and
                                       per harness the native session (id, when, how many runs)
    !AI/log/<id>.transcript.md         the whole conversation, re-exported from the native stores after every run
                                       (one segment per harness session; what cannot be exported is kept from
                                       run-ai's own records)
    !AI/log/<id>.summary.md            on request (--summarize): a summary of the transcript, which a hand-over
                                       points to first

The default run continues the conversation with the latest run; --new starts another; --conversation=<id or prefix>
picks one; --conversations lists them. Continuing with the harness that holds a native session resumes it natively
(claude --resume, codex resume / codex exec resume, agy --conversation, opencode --session, openclaw --session-id,
gemini --resume); continuing with another harness, or when the native session is gone, starts a new native session
and hands the transcript over in the prompt ("read !AI/log/<id>.transcript.md first").

Each harness has a small adapter here: how a NEW session is named (some let run-ai choose the id, some reveal it
only afterwards), how a session is RESUMED, how run-ai DISCOVERS the id after a run, whether the session still EXISTS,
and how to EXPORT its transcript. Nothing here talks to the network or to any account: only local files and the
harness's own flags.
"""

import datetime
import glob
import io
import json
import os
import re
import sqlite3
import uuid

CONVERSATION_SUFFIX = '.conversation.json'
TRANSCRIPT_SUFFIX = '.transcript.md'
SUMMARY_SUFFIX = '.summary.md'
MAX_TEXT = 40000          # longest single message kept in a transcript
MAX_TRANSCRIPT = 6000000  # bytes; beyond it the oldest segments are summarised to their headers

HARNESS_KEY = {'antigravity': 'agy'}    # harness names that share one native store
CLAUDE_META_TAGS = ('<command-name>', '<command-message>', '<command-args>', '<local-command-stdout>', '<local-command-caveat>',
                    '<system-reminder>', '<user-prompt-submit-hook>')


def _glob(directory, *pattern):
    """glob.glob in a directory whose own name is taken as it is: a folder called "notes [draft]" is not a pattern."""
    return glob.glob(os.path.join(glob.escape(directory), *pattern))


def harness_key(harness):
    return HARNESS_KEY.get(harness, harness)


def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def local_ts(value):
    """An ISO timestamp as the stores write it (Claude: UTC with a Z) -> local time, 'YYYY-MM-DD HH:MM:SS'."""
    s = str(value or '')
    if not s:
        return ''
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        d = datetime.datetime.fromisoformat(s)
        if d.tzinfo is not None:
            d = d.astimezone()
        return d.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return s[:19].replace('T', ' ')


def _read_json(path):
    try:
        with io.open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _ro_sqlite(path):
    """A read-only connection; a WAL database that refuses "mode=ro" is opened plainly (SELECTs write nothing)."""
    try:
        return sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True, timeout=5)
    except Exception:
        return sqlite3.connect(path, timeout=5)


# ====================================================================== the conversation files
def list_conversations(log_dir):
    """All conversations of a project, newest activity first."""
    out = []
    for fp in _glob(log_dir, '*' + CONVERSATION_SUFFIX):
        d = _read_json(fp)
        if isinstance(d, dict) and d.get('id'):
            d['_path'] = fp
            out.append(d)
    # the times are kept to the second: among conversations of the same second the one started last comes first
    out.sort(key=lambda d: (str(d.get('updated') or d.get('started') or ''), str(d.get('started') or ''), len(d['id']), d['id']), reverse=True)
    return out


def find_conversation(log_dir, wanted):
    """--conversation=<id or prefix> -> (conversation, error)."""
    wanted = str(wanted or '').strip()
    convs = list_conversations(log_dir)
    exact = [c for c in convs if c['id'] == wanted]
    if exact:
        return exact[0], ''
    pref = [c for c in convs if c['id'].startswith(wanted)]
    if len(pref) == 1:
        return pref[0], ''
    if not pref:
        return None, 'no conversation "%s" in %s (--conversations lists them)' % (wanted, log_dir)
    return None, '"%s" matches %d conversations: %s' % (wanted, len(pref), ', '.join(c['id'] for c in pref))


def new_conversation(log_dir, cid, project_path, cref, title):
    return {'id': cid, 'project': project_path, 'cref': cref, 'started': now_iso(), 'updated': now_iso(),
            'title': title, 'runs': [], 'sessions': {}, '_path': os.path.join(log_dir, cid + CONVERSATION_SUFFIX)}


def save_conversation(conv, touch=True):
    """touch=False keeps "updated" (the order of the conversations): a summary is no activity of the conversation."""
    if touch:
        conv['updated'] = now_iso()
    data = {k: v for k, v in conv.items() if not k.startswith('_')}
    _write_json(conv['_path'], data)


def transcript_path(conv):
    return os.path.join(os.path.dirname(conv['_path']), conv['id'] + TRANSCRIPT_SUFFIX)


def summary_path(conv):
    """!AI/log/<id>.summary.md: what --summarize wrote from the transcript."""
    return os.path.join(os.path.dirname(conv['_path']), conv['id'] + SUMMARY_SUFFIX)


def title_from_prompt(prompt, interactive, stamp):
    text = ' '.join(str(prompt or '').split())
    if text:
        return text[:90] + ('...' if len(text) > 90 else '')
    return 'interactive session %s' % stamp if interactive else 'run %s' % stamp


def describe(conv, short=True):
    """One line per conversation for --conversations and the console."""
    runs = conv.get('runs') or []
    harnesses = []
    for r in runs:
        if r.get('harness') and r['harness'] not in harnesses:
            harnesses.append(r['harness'])
    last = runs[-1] if runs else {}
    s = '%s  %d run(s), %s, last %s%s' % (conv['id'], len(runs), '/'.join(harnesses) or 'no run yet',
                                          (last.get('finished') or last.get('started') or conv.get('updated') or '?')[:16],
                                          (' with ' + last['harness']) if last.get('harness') else '')
    if (conv.get('summary') or {}).get('runs'):
        s += '  [summary after run %d]' % int(conv['summary']['runs'])
    if conv.get('title'):
        s += '  - %s' % conv['title']
    return s


# ====================================================================== the adapters
# claude --------------------------------------------------------------------------------------------------------
CLAUDE_SLUG_MAX = 200     # Claude Code cuts a longer slug to 200 characters and appends "-<hash of the path>"


def claude_session_cwd(folder):
    """The working directory a session of a Claude project folder recorded ('' when none says)."""
    for fp in sorted(_glob(folder, '*.jsonl')):
        try:
            with io.open(fp, encoding='utf-8', errors='replace') as f:
                for n, line in enumerate(f):
                    if n >= 50:
                        break
                    if '"cwd"' not in line:
                        continue
                    try:
                        cwd = json.loads(line).get('cwd')
                    except (ValueError, AttributeError):
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return ''


def claude_project_dirs(project_path):
    """<config dir>/projects/<slug>: the slug is the path with every non-alphanumeric turned into "-"; the drive
    letter follows the shell's spelling, so both cases are tried. A slug longer than 200 characters is cut to 200
    and followed by "-" and a hash of the path that depends on Claude Code's runtime (Bun or Node), so it is not
    computed here: the existing folders with that prefix are taken, less those whose sessions recorded another
    working directory (two long paths can share the first 200 characters of their slugs)."""
    base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
    p = os.path.normpath(project_path)
    variants = {p}
    if len(p) > 1 and p[1] == ':':
        variants |= {p[0].lower() + p[1:], p[0].upper() + p[1:]}
    out = []
    for v in sorted(variants):
        slug = re.sub(r'[^A-Za-z0-9]', '-', v)
        if len(slug) <= CLAUDE_SLUG_MAX:
            out.append(os.path.join(base, 'projects', slug))
            continue
        for d in sorted(_glob(os.path.join(base, 'projects'), slug[:CLAUDE_SLUG_MAX] + '-*')):
            if d in out or not os.path.isdir(d) or len(os.path.basename(d)) <= CLAUDE_SLUG_MAX + 1:
                continue
            cwd = claude_session_cwd(d)
            if cwd and os.path.normcase(os.path.normpath(cwd)) != os.path.normcase(p):
                continue
            out.append(d)
    return out


def claude_session_file(project_path, sid):
    for d in claude_project_dirs(project_path):
        fp = os.path.join(d, '%s.jsonl' % sid)
        if os.path.isfile(fp):
            return fp
    return ''


def _blocks(content):
    """A message's content -> (kind, text) pairs; tool results are dropped, tool calls become one line."""
    if isinstance(content, str):
        return [('text', content)]
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get('type')
        if t == 'text':
            out.append(('text', b.get('text') or ''))
        elif t == 'tool_use':
            inp = b.get('input') or {}
            hint = ''
            if isinstance(inp, dict):
                for key in ('command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt', 'skill'):
                    if inp.get(key):
                        hint = ' '.join(str(inp[key]).split())
                        break
            out.append(('tool', '%s %s' % (b.get('name') or '?', hint[:160])))
        elif t == 'tool_result':
            out.append(('result', ''))
    return out


def claude_export(project_path, sid):
    """-> list of (role, timestamp, [(kind, text)]) or None when the session file is not there."""
    fp = claude_session_file(project_path, sid)
    if not fp:
        return None
    out = []
    with io.open(fp, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get('type')
            if t not in ('user', 'assistant') or d.get('isSidechain'):
                continue
            msg = d.get('message') or {}
            blocks = _blocks(msg.get('content'))
            if not blocks or all(k == 'result' for k, _ in blocks):
                continue
            if t == 'user' and d.get('isMeta'):
                continue
            blocks = [(k, v) for k, v in blocks if k != 'result']
            if t == 'user':
                # slash commands and their output are recorded as user entries: not part of the conversation
                blocks = [(k, v) for k, v in blocks if not (k == 'text' and str(v).lstrip().startswith(CLAUDE_META_TAGS))]
            if not blocks:
                continue
            out.append(('user' if t == 'user' else 'assistant', local_ts(d.get('timestamp')), blocks))
    return out


# codex ---------------------------------------------------------------------------------------------------------
def codex_home():
    """CODEX_HOME: the rollout files, auth, config."""
    return os.environ.get('CODEX_HOME') or os.path.join(os.path.expanduser('~'), '.codex')


_CODEX_SQLITE_HOME = ''


def set_codex_sqlite_home(path):
    """run-ai keeps Codex's SQLite state (threads, history, memories) inside the project (CODEX_SQLITE_HOME); the lookups
    below must read the same store, before and after the run."""
    global _CODEX_SQLITE_HOME
    _CODEX_SQLITE_HOME = path or ''


def codex_sqlite_home():
    """Where Codex's state_*.sqlite and thread_history_*.sqlite live: CODEX_SQLITE_HOME when set (by run-ai or the
    environment), else CODEX_HOME. Codex 0.160 honours the variable; the rollout files stay under CODEX_HOME."""
    return _CODEX_SQLITE_HOME or os.environ.get('CODEX_SQLITE_HOME') or codex_home()


def _codex_cwd(raw):
    raw = str(raw or '')
    return raw[4:] if raw.startswith('\\\\?\\') else raw


def codex_threads(project_path, since=0):
    """The Codex threads of a folder from CODEX_HOME/state_*.sqlite (newest first): [(id, created, source)]."""
    out = []
    for db in sorted(_glob(codex_sqlite_home(), 'state_*.sqlite'), reverse=True):
        try:
            con = _ro_sqlite(db)
            rows = con.execute('select id, created_at, source, cwd from threads order by created_at desc limit 200').fetchall()
            con.close()
        except Exception:
            continue
        for tid, created, source, cwd in rows:
            if created and created >= since and _same_path(_codex_cwd(cwd), project_path):
                out.append((tid, created, source))
        if out or rows:
            break
    if not out:
        # the legacy layout: the first line of every rollout file names the cwd
        for fp in sorted(_glob(codex_home(), 'sessions', '*', '*', '*', 'rollout-*.jsonl'), key=os.path.getmtime, reverse=True)[:40]:
            if since and os.path.getmtime(fp) < since:
                continue
            try:
                with io.open(fp, encoding='utf-8', errors='replace') as f:
                    meta = json.loads(f.readline()).get('payload') or {}
            except Exception:
                continue
            if _same_path(_codex_cwd(meta.get('cwd')), project_path) and meta.get('id'):
                out.append((meta['id'], os.path.getmtime(fp), meta.get('source') or ''))
    return out


def codex_exists(sid):
    for db in _glob(codex_sqlite_home(), 'state_*.sqlite'):
        try:
            con = _ro_sqlite(db)
            n = con.execute('select count(*) from threads where id=?', (sid,)).fetchone()[0]
            con.close()
            if n:
                return True
        except Exception:
            pass
    return bool(_glob(codex_home(), 'sessions', '*', '*', '*', 'rollout-*-%s.jsonl' % sid))


def codex_export(sid):
    """The thread from CODEX_HOME/thread_history_*.sqlite (Codex >= 0.160), else from the rollout file."""
    out = []
    for db in sorted(_glob(codex_sqlite_home(), 'thread_history_*.sqlite'), reverse=True):
        try:
            con = _ro_sqlite(db)
            rows = con.execute('select item_type, item_json, created_at_ms from thread_items where thread_id=? order by rollout_ordinal', (sid,)).fetchall()
            con.close()
        except Exception:
            continue
        for item_type, item_json, created in rows:
            try:
                d = json.loads(item_json)
            except Exception:
                continue
            ts = datetime.datetime.fromtimestamp((created or 0) / 1000).isoformat(timespec='seconds').replace('T', ' ') if created else ''
            if item_type == 'userMessage':
                text = '\n'.join(str(c.get('text') or '') for c in (d.get('content') or []) if isinstance(c, dict))
                out.append(('user', ts, [('text', text)]))
            elif item_type == 'agentMessage':
                out.append(('assistant', ts, [('text', str(d.get('text') or ''))]))
            elif item_type == 'commandExecution':
                out.append(('assistant', ts, [('tool', 'command ' + ' '.join(str(d.get('command') or '').split())[:160])]))
            elif item_type == 'fileChange':
                changes = ', '.join('%s %s' % ((c.get('kind') or {}).get('type', '?') if isinstance(c.get('kind'), dict) else c.get('kind', '?'), c.get('path', '?'))
                                    for c in (d.get('changes') or []) if isinstance(c, dict))
                out.append(('assistant', ts, [('tool', 'file change ' + changes[:160])]))
            elif item_type == 'webSearch':
                out.append(('assistant', ts, [('tool', 'web search ' + str(d.get('query') or '')[:160])]))
        if rows:
            return out
    files = _glob(codex_home(), 'sessions', '*', '*', '*', 'rollout-*-%s.jsonl' % sid)
    if not files:
        return None
    with io.open(files[0], encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('type') != 'response_item':
                continue
            p = d.get('payload') or {}
            if p.get('type') == 'message' and p.get('role') in ('user', 'assistant'):
                text = '\n'.join(str(c.get('text') or '') for c in (p.get('content') or []) if isinstance(c, dict))
                if text.startswith(('# AGENTS.md instructions', '<environment_context>')):
                    continue
                out.append((p['role'], str(d.get('timestamp') or '')[:19].replace('T', ' '), [('text', text)]))
    return out


# antigravity (agy) ----------------------------------------------------------------------------------------------
def agy_home():
    return os.path.join(os.path.expanduser('~'), '.gemini', 'antigravity-cli')


def agy_last_conversation(project_path):
    d = _read_json(os.path.join(agy_home(), 'cache', 'last_conversations.json')) or {}
    for k, v in d.items():
        if _same_path(k, project_path):
            return str(v)
    return ''


def agy_newest_conversation(since):
    files = [fp for fp in _glob(agy_home(), 'conversations', '*.db') if os.path.getmtime(fp) >= since]
    files.sort(key=os.path.getmtime, reverse=True)
    return os.path.splitext(os.path.basename(files[0]))[0] if files else ''


def agy_exists(sid):
    return os.path.isfile(os.path.join(agy_home(), 'conversations', '%s.db' % sid))


# the step types of agy's conversation store (SQLite, protobuf blobs; 1.2.16, seen 2026-10-04)
AGY_STEP_TYPES = {14: 'user', 15: 'assistant', 132: 'tool', 101: 'system'}
_AGY_NOISE = re.compile(r'^[\w$:(\"\'!-]{0,4}[0-9a-f]{8}-[0-9a-f]{4}-|sessionID|^[A-Za-z0-9+/=_-]{16,}$|^bot-')


def agy_export(sid):
    """Best effort: agy keeps each conversation as protobuf blobs in conversations/<id>.db (table steps). The readable
    runs of those blobs are recovered: the user's prompts, the model's reasoning and answers, the tool calls with
    their arguments; identifiers and binary noise are dropped. Short final answers can be lost in the noise."""
    db = os.path.join(agy_home(), 'conversations', '%s.db' % sid)
    if not os.path.isfile(db):
        return None
    try:
        con = _ro_sqlite(db)
        rows = con.execute('select idx, step_type, step_payload from steps order by idx').fetchall()
        con.close()
    except Exception:
        return None
    out = []
    for idx, step_type, payload in rows:
        kind = AGY_STEP_TYPES.get(step_type, 'step %s' % step_type)
        runs, seen_runs = [], set()
        for s in re.findall(rb'[\x20-\x7e]{4,}', payload or b''):
            r = s.decode('ascii', 'replace').strip()
            if r and r not in seen_runs and not _AGY_NOISE.search(r):
                seen_runs.add(r)
                runs.append(r)
        if kind == 'tool':
            name = next((r for r in runs if re.match(r'^[a-z][a-z0-9_]{2,40}$', r) and not re.match(r'^call_?\d+$', r)), '?')
            args = next((r for r in runs if r.startswith('{')), '')
            out.append(('assistant', '', [('tool', '%s %s' % (name, args[:160]))]))
            continue
        if kind == 'system':
            text = next((r for r in runs if r.startswith('[')), '')
            if text:
                out.append(('assistant', '', [('tool', 'system notice: ' + text[:160])]))
            continue
        texts = [r for r in runs if len(r.split()) >= 3 and not r.startswith('{')]
        if not texts:
            continue
        # the user step repeats the prompt: keep the longest run and anything that is not a prefix of it
        if kind == 'user':
            texts.sort(key=len, reverse=True)
            texts = [texts[0]] + [t for t in texts[1:] if t not in texts[0]]
        out.append(('user' if kind == 'user' else 'assistant', '', [('text', '\n\n'.join(texts))]))
    return out


# opencode ------------------------------------------------------------------------------------------------------
def opencode_db():
    base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'opencode', 'opencode.db')


def opencode_sessions(project_path, since=0):
    """[(id, created ms)] of the folder, newest first."""
    db = opencode_db()
    if not os.path.isfile(db):
        return []
    try:
        con = _ro_sqlite(db)
        rows = con.execute('select id, directory, time_created from session order by time_created desc limit 200').fetchall()
        con.close()
    except Exception:
        return []
    return [(sid, created) for sid, directory, created in rows
            if _same_path(str(directory or '').replace('/', os.sep), project_path) and (created or 0) >= since * 1000]


def opencode_exists(sid):
    db = opencode_db()
    if not os.path.isfile(db):
        return False
    try:
        con = _ro_sqlite(db)
        n = con.execute('select count(*) from session where id=?', (sid,)).fetchone()[0]
        con.close()
        return bool(n)
    except Exception:
        return False


def opencode_export(sid):
    db = opencode_db()
    if not os.path.isfile(db):
        return None
    out = []
    try:
        con = _ro_sqlite(db)
        msgs = con.execute('select id, data, time_created from message where session_id=? order by time_created', (sid,)).fetchall()
        for mid, data, created in msgs:
            try:
                m = json.loads(data)
            except Exception:
                continue
            role = m.get('role') or '?'
            ts = datetime.datetime.fromtimestamp((created or 0) / 1000).isoformat(timespec='seconds').replace('T', ' ') if created else ''
            blocks = []
            for (pdata,) in con.execute('select data from part where message_id=? order by time_created', (mid,)).fetchall():
                try:
                    p = json.loads(pdata)
                except Exception:
                    continue
                if p.get('type') == 'text':
                    blocks.append(('text', str(p.get('text') or '')))
                elif p.get('type') == 'tool':
                    blocks.append(('tool', '%s %s' % (p.get('tool') or '?', ' '.join(json.dumps((p.get('state') or {}).get('input') or {}, ensure_ascii=False).split())[:160])))
            if blocks:
                out.append(('user' if role == 'user' else 'assistant', ts, blocks))
        con.close()
    except Exception:
        return None
    return out


# openclaw ------------------------------------------------------------------------------------------------------
def openclaw_state_dir():
    """OpenClaw's state: OPENCLAW_STATE_DIR, else <OPENCLAW_HOME or the home>/.openclaw (OpenClaw 2026.6)."""
    if os.environ.get('OPENCLAW_STATE_DIR', '').strip():
        return os.path.expanduser(os.environ['OPENCLAW_STATE_DIR'].strip())
    home = os.environ.get('OPENCLAW_HOME', '').strip()
    return os.path.join(os.path.expanduser(home) if home else os.path.expanduser('~'), '.openclaw')


def _openclaw_entry(sid):
    """(the entry of OpenClaw's session index filed under the key agent:<agent>:explicit:<sid>, its sessions folder)."""
    for index in sorted(_glob(openclaw_state_dir(), 'agents', '*', 'sessions', 'sessions.json')):
        entries = _read_json(index)
        if not isinstance(entries, dict):
            continue
        for key, entry in entries.items():
            if isinstance(entry, dict) and key.endswith(':explicit:%s' % sid):
                return entry, os.path.dirname(index)
    return None, ''


def openclaw_session_id(sid):
    """The id of the session OpenClaw keeps under the key named after sid ('' when there is none)."""
    entry, folder = _openclaw_entry(sid)
    return str((entry or {}).get('sessionId') or '')


def openclaw_session_file(sid):
    """<state>/agents/<agent>/sessions/<file>.jsonl ("main" unless the turn was routed to another agent). A headless
    turn names its file after the id run-ai chose; the terminal UI, given the key agent:<agent>:explicit:<id>, files a
    new session under an id of its own - the index sessions.json beside the files says which. The <id>.trajectory.jsonl
    there is OpenClaw's runtime trace, not the conversation."""
    entry, folder = _openclaw_entry(sid)
    if entry:
        for fp in (entry.get('sessionFile') or '', os.path.join(folder, '%s.jsonl' % entry.get('sessionId'))):
            if fp and os.path.isfile(fp):
                return fp
    for fp in sorted(_glob(openclaw_state_dir(), 'agents', '*', 'sessions', '%s.jsonl' % sid)):
        return fp
    return ''


def openclaw_exists(sid):
    return bool(openclaw_session_file(sid))


def openclaw_export(sid):
    """OpenClaw's session file (version 3): a "session" line (id, cwd), then "message" lines whose message has a role
    (user, assistant, toolResult) and a content - a string or a list of text and tool-call parts. Tool results are
    left out; a tool call becomes one line."""
    fp = openclaw_session_file(sid)
    if not fp:
        return None
    out = []
    with io.open(fp, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get('message') if isinstance(d, dict) else None
            if d.get('type') != 'message' or not isinstance(msg, dict) or msg.get('role') not in ('user', 'assistant'):
                continue
            content = msg.get('content')
            blocks = []
            for part in ([{'type': 'text', 'text': content}] if isinstance(content, str) else (content or [])):
                if not isinstance(part, dict):
                    continue
                kind = part.get('type')
                if kind == 'text' and str(part.get('text') or '').strip():
                    blocks.append(('text', str(part['text'])))
                elif kind in ('toolCall', 'tool_call', 'tool_use'):
                    args = part.get('arguments') or part.get('input') or part.get('args') or {}
                    hint = ''
                    if isinstance(args, dict):
                        for key in ('command', 'path', 'file_path', 'url', 'query', 'pattern'):
                            if args.get(key):
                                hint = ' '.join(str(args[key]).split())[:200]
                                break
                    blocks.append(('tool', ('%s %s' % (part.get('name') or 'tool', hint)).strip()))
            if blocks:
                out.append((msg['role'], local_ts(d.get('timestamp') or ''), blocks))
    return out


# gemini --------------------------------------------------------------------------------------------------------
def gemini_home():
    """Gemini CLI keeps its state in <home>/.gemini; GEMINI_CLI_HOME replaces the home."""
    return os.path.join(os.environ.get('GEMINI_CLI_HOME') or os.path.expanduser('~'), '.gemini')


def gemini_chat_file(sid):
    """The file of a session: <gemini home>/tmp/<project>/chats/session-<start>-<first 8 characters of the id>.jsonl,
    whose first line carries the whole id."""
    for fp in _glob(gemini_home(), 'tmp', '*', 'chats', 'session-*%s.jsonl' % str(sid)[:8]):
        try:
            with io.open(fp, encoding='utf-8', errors='replace') as f:
                if json.loads(f.readline()).get('sessionId') == sid:
                    return fp
        except Exception:
            continue
    return ''


def gemini_exists(sid):
    return bool(gemini_chat_file(sid))


def gemini_messages(fp):
    """The messages of a session file. The file is a log: a header line, then either {"$set": {"messages": [...]}} -
    the whole list as it is from there on - or one message per line, added to the list (the same id again replaces
    the earlier one: a streamed answer is rewritten as it grows). -> the list at the end."""
    messages = []
    with io.open(fp, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            if isinstance(d.get('$set'), dict):
                if isinstance(d['$set'].get('messages'), list):
                    messages = [m for m in d['$set']['messages'] if isinstance(m, dict)]
            elif d.get('type') and 'content' in d:
                if d.get('id') and any(m.get('id') == d['id'] for m in messages):
                    messages = [d if m.get('id') == d['id'] else m for m in messages]
                else:
                    messages.append(d)
    return messages


def gemini_export(sid):
    """A user message carries a list of parts, an answer (type "gemini") its text and its tool calls."""
    fp = gemini_chat_file(sid)
    if not fp:
        return None
    out = []
    for m in gemini_messages(fp):
        if m.get('type') not in ('user', 'gemini', 'model'):
            continue
        content = m.get('content')
        if isinstance(content, list):
            text = '\n'.join(str(c.get('text') or '') for c in content if isinstance(c, dict))
        else:
            text = str(content or '')
        if text.startswith('<session_context>'):
            continue        # what the CLI tells the model about the folder, not a turn of the conversation
        blocks = [('text', text)] if text.strip() else []
        for call in m.get('toolCalls') or []:
            if not isinstance(call, dict):
                continue
            args = call.get('args') if isinstance(call.get('args'), dict) else {}
            hint = next((str(args[k]) for k in ('command', 'file_path', 'path', 'pattern', 'query', 'url', 'description', 'prompt') if args.get(k)), '')
            blocks.append(('tool', '%s %s' % (call.get('name') or '?', ' '.join(hint.split())[:160])))
        if blocks:
            out.append(('user' if m['type'] == 'user' else 'assistant', local_ts(m.get('timestamp') or ''), blocks))
    return out


# hermes --------------------------------------------------------------------------------------------------------
# Hermes Agent keeps its sessions in <HERMES_HOME>/state.db (SQLite, its own schema and a search index): they are read
# through its CLI - "hermes sessions list" (newest first: "<id>  <date>  <title> ...") and "hermes sessions export
# --format jsonl --session-id <id> -" (one JSON object per message on stdout) - never through the database itself.
HERMES_SESSION_RE = re.compile(r'\b(\d{8}_\d{6}_[0-9a-f]{6}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b', re.I)


def hermes_home():
    """HERMES_HOME, else ~/.hermes (Linux, macOS) or %LOCALAPPDATA%\\hermes (Windows)."""
    if os.environ.get('HERMES_HOME'):
        return os.environ['HERMES_HOME']
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], 'hermes')
    return os.path.join(os.path.expanduser('~'), '.hermes')


def hermes_bin():
    """The hermes command: on PATH, else where its installer puts the shim (~/.local/bin; <HERMES_HOME>/bin/hermes.cmd and
    %LOCALAPPDATA%/hermes/bin/hermes.cmd on Windows), else ''."""
    import shutil
    found = shutil.which('hermes') or (shutil.which('hermes.cmd') if os.name == 'nt' else '')
    if found:
        return found
    candidates = [os.path.join(os.path.expanduser('~'), '.local', 'bin', 'hermes')]
    if os.name == 'nt':
        candidates = [os.path.join(hermes_home(), 'bin', 'hermes.cmd')]
        if os.environ.get('LOCALAPPDATA'):
            candidates.append(os.path.join(os.environ['LOCALAPPDATA'], 'hermes', 'bin', 'hermes.cmd'))
    return next((c for c in candidates if os.path.isfile(c)), '')


def hermes_run(args, timeout=120):
    """-> (exit code, stdout) of "hermes <args>" without colours; (-1, '') when hermes is not there or hangs."""
    import subprocess
    binary = hermes_bin()
    if not binary:
        return -1, ''
    env = dict(os.environ)
    env.setdefault('NO_COLOR', '1')
    try:
        p = subprocess.run([binary] + list(args), capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or '') + (('\n' + p.stderr) if p.returncode != 0 and p.stderr else '')
    except Exception:
        return -1, ''


def hermes_sessions(limit=50):
    """The sessions "hermes sessions list" knows, newest first: [(id, the line)]."""
    rc, out = hermes_run(['sessions', 'list', '--limit', str(limit)])
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        m = HERMES_SESSION_RE.search(line)
        if m and m.group(1) not in [f[0] for f in found]:
            found.append((m.group(1), line.strip()))
    return found


def hermes_exists(sid):
    return any(s == sid for s, _ in hermes_sessions(500))


def hermes_newest_session(t0=0):
    """The newest session of the list, when its id's own timestamp (<yyyymmdd>_<hhmmss>) is not older than t0."""
    for sid, _ in hermes_sessions(5):
        m = re.match(r'(\d{8})_(\d{6})_', sid)
        if m and t0:
            try:
                started = datetime.datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').timestamp()
                if started < t0 - 120:
                    return ''
            except ValueError:
                pass
        return sid
    return ''


def hermes_export(sid):
    """The messages of a session as hermes exports them (JSONL on stdout): a user message, an answer with its text and
    tool calls, a tool result (dropped: the call is shown). The keys are read by their shape."""
    rc, out = hermes_run(['sessions', 'export', '--format', 'jsonl', '--session-id', sid, '-'], timeout=300)
    if rc != 0 or not out.strip():
        return None
    messages = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        # one object may be a session header with its messages inside
        inner = d.get('messages') if isinstance(d.get('messages'), list) else None
        for m in (inner if inner is not None else [d]):
            if isinstance(m, dict):
                messages.append(m)
    out_list = []
    for m in messages:
        role = str(m.get('role') or m.get('type') or '').lower()
        if role in ('human',):
            role = 'user'
        if role in ('ai', 'model', 'agent'):
            role = 'assistant'
        if role not in ('user', 'assistant'):
            continue
        content = m.get('content')
        if isinstance(content, list):
            text = '\n'.join(str(c.get('text') or '') for c in content if isinstance(c, dict))
        else:
            text = str(content or m.get('text') or '')
        blocks = [('text', text)] if text.strip() else []
        for call in m.get('tool_calls') or m.get('toolCalls') or []:
            if not isinstance(call, dict):
                continue
            fn = call.get('function') if isinstance(call.get('function'), dict) else call
            name = fn.get('name') or call.get('name') or '?'
            args = fn.get('arguments') or call.get('arguments') or call.get('args') or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {'text': args}
            hint = next((str(args[k]) for k in ('command', 'cmd', 'file_path', 'path', 'pattern', 'query', 'url', 'description', 'prompt')
                         if isinstance(args, dict) and args.get(k)), '')
            blocks.append(('tool', '%s %s' % (name, ' '.join(hint.split())[:160])))
        if blocks:
            ts = m.get('timestamp') or m.get('created_at') or m.get('ts') or ''
            if isinstance(ts, (int, float)):
                ts = datetime.datetime.fromtimestamp(ts / 1000.0 if ts > 1e11 else ts).isoformat(timespec='seconds')
            out_list.append((role, local_ts(str(ts)) if ts else '', blocks))
    return out_list


# ====================================================================== the adapter table
def openclaw_session_key(sid):
    """The key OpenClaw files a session under when a headless turn names it (--session-id <id>); its terminal UI takes
    the key (--session <key>), so a conversation can go on in either."""
    return 'agent:main:explicit:%s' % sid


def new_session_flags(harness, sid, cid, alias, interactive=False):
    """The flags that start a NEW native session under the id run-ai chose (harnesses that let it choose)."""
    h = harness_key(harness)
    if h == 'claude':
        return ['--session-id', sid, '--name', 'run-ai %s %s' % (cid, alias or '')]
    if h == 'openclaw' and interactive:
        return ['--session', openclaw_session_key(sid)]
    if h in ('openclaw', 'gemini'):
        return ['--session-id', sid]
    return []


def chooses_id(harness):
    return harness_key(harness) in ('claude', 'openclaw', 'gemini')


def resume_flags(harness, sid, interactive=False):
    """The flags that RESUME a native session (codex needs a sub-command instead: run-codex --resume=<id>)."""
    h = harness_key(harness)
    if h == 'openclaw' and interactive:
        return ['--session', openclaw_session_key(sid)]
    return {'claude': ['--resume', sid], 'agy': ['--conversation', sid], 'opencode': ['--session', sid],
            'openclaw': ['--session-id', sid], 'gemini': ['--resume', sid], 'hermes': ['--resume', sid]}.get(h, [])


def session_exists(harness, sid, project_path):
    h = harness_key(harness)
    if h == 'claude':
        return bool(claude_session_file(project_path, sid))
    if h == 'codex':
        return codex_exists(sid)
    if h == 'agy':
        return agy_exists(sid)
    if h == 'opencode':
        return opencode_exists(sid)
    if h == 'openclaw':
        return openclaw_exists(sid)
    if h == 'gemini':
        return gemini_exists(sid)
    if h == 'hermes':
        return hermes_exists(sid)
    return True     # unknown harness: let it try


def discover_session(harness, project_path, t0, task_result=None, before=None):
    """The id of the native session a run created, for the harnesses that reveal it only afterwards.
    task_result: the run-<harness> result (its stats may name the session); before: state captured before the run."""
    h = harness_key(harness)
    stats = (task_result or {}).get('stats') or {}
    if h == 'codex':
        tid = stats.get('thread_id')
        if tid:
            return tid
        threads = codex_threads(project_path, since=int(t0) - 5)
        return threads[0][0] if threads else ''
    if h == 'agy':
        sid = stats.get('session_id') or ''
        if sid:
            return sid
        last = agy_last_conversation(project_path)
        if last and last != (before or {}).get('agy_last'):
            return last
        return agy_newest_conversation(t0 - 5) or last
    if h == 'opencode':
        sid = stats.get('session_id') or stats.get('sessionID') or ''
        if sid:
            return sid
        sessions = opencode_sessions(project_path, since=t0 - 5)
        return sessions[0][0] if sessions else ''
    if h == 'hermes':
        sid = stats.get('session_id') or ''
        if sid:
            return sid
        return hermes_newest_session(t0)
    return stats.get('session_id') or ''


def capture_before(harness, project_path):
    if harness_key(harness) == 'agy':
        return {'agy_last': agy_last_conversation(project_path)}
    return {}


def export_session(harness, sid, project_path):
    """-> list of (role, ts, blocks), or None when the native store cannot be read (agy keeps protobuf blobs)."""
    h = harness_key(harness)
    if h == 'claude':
        return claude_export(project_path, sid)
    if h == 'codex':
        return codex_export(sid)
    if h == 'agy':
        return agy_export(sid)
    if h == 'opencode':
        return opencode_export(sid)
    if h == 'openclaw':
        return openclaw_export(sid)
    if h == 'gemini':
        return gemini_export(sid)
    if h == 'hermes':
        return hermes_export(sid)
    return None


def native_store_hint(harness):
    h = harness_key(harness)
    return {'claude': '~/.claude/projects/<slug>/<id>.jsonl', 'codex': 'state_*.sqlite + thread_history_*.sqlite in CODEX_SQLITE_HOME (run-ai: <project>/!AI/codex) or CODEX_HOME; rollout-*.jsonl in CODEX_HOME',
            'agy': '~/.gemini/antigravity-cli/conversations/<id>.db (protobuf blobs; the readable runs are recovered)', 'opencode': '~/.local/share/opencode/opencode.db',
            'openclaw': '~/.openclaw/agents/<agent>/sessions/<id>.jsonl (OPENCLAW_STATE_DIR moves ~/.openclaw)', 'gemini': '~/.gemini/tmp/<project>/chats/session-*.jsonl',
            'hermes': '<HERMES_HOME>/state.db (~/.hermes; SQLite, read through "hermes sessions list" and "hermes sessions export --format jsonl")'}.get(h, '')


# ====================================================================== the transcript
# The line run-ai puts between what it prepends to a prompt (the hand-over, the orientation, the context) and the
# request itself: the harnesses without a system-prompt file get all of it as the user's message, and the transcript
# keeps the request only
REQUEST_MARK = '<!-- run-ai: the request of this run follows -->'
PREPENDED_NOTE = '_(what run-ai put before the request - a hand-over, the orientation, the context - is left out here; the run\'s records in !AI/log keep it)_'


def _render_messages(messages, names):
    lines = []
    for role, ts, blocks in messages:
        lines += ['### %s%s' % (names.get(role, role), ('  (%s)' % ts) if ts else ''), '']
        for kind, text in blocks:
            text = str(text or '')
            if role == 'user' and kind == 'text' and REQUEST_MARK in text:
                lines += [PREPENDED_NOTE, '']
                text = text.split(REQUEST_MARK)[-1].lstrip('\r\n')
            if not text.strip():
                continue
            if kind == 'tool':
                lines += ['`-> %s`' % text.replace('`', "'"), '']
            else:
                if len(text) > MAX_TEXT:
                    text = text[:MAX_TEXT] + '\n\n[... %d more characters not kept in the transcript]' % (len(text) - MAX_TEXT)
                lines += [text.rstrip(), '']
    return lines


def _own_records(conv, harness, sid, log_dir):
    """What run-ai itself knows about a session when its store cannot be read: the prompts and outputs of its runs."""
    lines = []
    for r in conv.get('runs') or []:
        if harness_key(r.get('harness', '')) != harness_key(harness) or (r.get('session') and r['session'] != sid):
            continue
        lines += ['### Run %s (%s)' % (r.get('stamp'), r.get('mode', '')), '']
        if r.get('prompt'):
            lines += ['**Prompt (as given to run-ai):** %s' % r['prompt'], '']
        out = os.path.join(log_dir, '%s.%s.output.txt' % (r.get('stamp'), r.get('harness')))
        if os.path.isfile(out):
            try:
                with io.open(out, encoding='utf-8', errors='replace') as f:
                    text = f.read()
                text = '\n'.join(l for l in text.splitlines() if not l.startswith('# ')).strip()
                if len(text) > MAX_TEXT:
                    text = text[:MAX_TEXT] + '\n[... truncated]'
                lines += ['**Output:**', '', text, '']
            except Exception:
                pass
        elif r.get('mode') == 'interactive':
            lines += ['(interactive session: nothing was captured by run-ai)', '']
    return lines


SEGMENT_HEADER = re.compile(r'\n## \S+ - session `[^`]*` \(started ')


def _old_segment(old_text, harness, sid):
    """The text of a session's segment in the previous transcript (kept when the native store is gone). The segment
    is found by its harness and session id - the count of runs in its header changes - and ends at the next segment
    header, not at a "## " heading inside a message."""
    if not old_text:
        return []
    m = re.search(r'(?m)^## %s - session `%s` \(started [^\n]*\n' % (re.escape(harness), re.escape(str(sid))), old_text)
    if not m:
        return []
    rest = old_text[m.end():]
    end = SEGMENT_HEADER.search(rest)
    body = rest[:end.start()] if end else rest
    return body.strip('\n').splitlines()


def write_transcript(conv, log_dir):
    """Re-export every session of the conversation into <id>.transcript.md -> (path, [notes])."""
    path = transcript_path(conv)
    old = ''
    if os.path.isfile(path):
        try:
            with io.open(path, encoding='utf-8', errors='replace') as f:
                old = f.read()
        except Exception:
            old = ''
    runs = conv.get('runs') or []
    harnesses = []
    for r in runs:
        if r.get('harness') and r['harness'] not in harnesses:
            harnesses.append(r['harness'])
    head = ['# Conversation %s - %s' % (conv['id'], conv.get('title') or ''), '',
            '| | |', '|---|---|',
            '| project | `%s`%s |' % (conv.get('project', ''), (' (`%s`)' % conv['cref']) if conv.get('cref') else ''),
            '| started | %s |' % conv.get('started', ''),
            '| updated | %s |' % now_iso(),
            '| runs | %d (%s) |' % (len(runs), ', '.join(harnesses)),
            '| sessions | %s |' % ', '.join('%s `%s`' % (h, s.get('id')) for h, s in (conv.get('sessions') or {}).items()),
            '', '> Written by run-ai after every run from the harnesses\' own session stores; tool results are left out, tool calls are one line each.',
            '> `cxt run-ai` continues this conversation; `cxt run-ai --new` starts another.', '', '---', '']
    body, notes = [], []
    # the segments in the order the sessions were started, the sessions a harness had before its current one included
    entries = []
    for h, s in (conv.get('sessions') or {}).items():
        for p in s.get('previous') or []:
            p = p if isinstance(p, dict) else {'id': p}          # older files kept the ids only
            if p.get('id'):
                entries.append((p.get('started') or '', h, p))
        if s.get('id'):
            entries.append((s.get('started') or '', h, s))
    segments = sorted(entries, key=lambda x: x[0])
    for started, h, s in segments:
        header = '## %s - session `%s` (started %s, %d run(s))' % (h, s.get('id'), started, s.get('runs', 0))
        body += [header, '']
        if harness_key(h) == 'agy':
            body += ['> best effort: agy keeps protobuf blobs; the prompts, the reasoning and the tool calls are recovered as readable text, '
                     'short final answers may be missing - the Output of each run below the segment is run-ai\'s own record', '']
        messages = None
        try:
            messages = export_session(h, s.get('id'), conv.get('project', ''))
        except Exception as e:
            notes.append('%s: the transcript could not be exported (%s)' % (h, e))
            messages = None
        if messages:
            body += _render_messages(messages, {'user': 'User', 'assistant': {'claude': 'Claude', 'codex': 'Codex', 'agy': 'Antigravity', 'opencode': 'OpenCode', 'openclaw': 'OpenClaw', 'gemini': 'Gemini', 'hermes': 'Hermes'}.get(harness_key(h), 'Assistant')})
            s['exported'] = len(messages)
            if harness_key(h) == 'agy':
                body += _own_records(conv, h, s.get('id'), log_dir)
        else:
            kept = _old_segment(old, h, s.get('id'))
            if kept:
                body += kept + ['']
                notes.append('%s: the native session is not readable any more; the segment of the previous transcript is kept' % h)
            else:
                body += ['(not exported from the harness\'s own store: %s)' % (native_store_hint(h) or 'unknown layout'), ''] + _own_records(conv, h, s.get('id'), log_dir)
                if harness_key(h) != 'agy':
                    notes.append('%s: nothing exported from %s' % (h, native_store_hint(h) or 'its store'))
        body.append('')
    text = '\n'.join(head + body).rstrip() + '\n'
    if len(text.encode('utf-8')) > MAX_TRANSCRIPT:
        notes.append('the transcript is over %d MB' % (MAX_TRANSCRIPT // 1000000))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return path, notes


def handover_text(conv, harness, log_dir, why):
    """The prompt prefix that hands a conversation over to a harness that has no native session for it."""
    runs = conv.get('runs') or []
    harnesses = []
    for r in runs:
        if r.get('harness') and r['harness'] not in harnesses:
            harnesses.append(r['harness'])
    last = runs[-1] if runs else {}
    tp = transcript_path(conv).replace('\\', '/')
    # a summary written by --summarize is read first when there is one; the transcript stays the record
    summary = conv.get('summary') or {}
    sp = summary_path(conv)
    read_first = ''
    if summary and os.path.isfile(sp):
        read_first = ('read its summary %s (written after run %d of %d), then its transcript as far as you need: %s' % (
            sp.replace('\\', '/'), int(summary.get('runs') or 0), len(runs), tp))
    # the title (the first words of the first request) is left out on purpose: quoted here, in front of the prompt,
    # it reads like an instruction of this run to a model that has not seen the conversation yet
    return ('You continue conversation %s of this project%s: %d run(s) so far with %s, the last on %s. Before anything '
            'else, %s (the end is the most recent part). Then go on from where the conversation '
            'stopped and answer the request at the end of this message. The project\'s memory and files are where they '
            'always are.\n' % (
                conv['id'], (' (' + why + ')') if why else '', len(runs), ', '.join(harnesses) or 'no harness',
                (last.get('finished') or last.get('started') or '?')[:16], read_first or ('read its transcript: %s' % tp)))


def new_id():
    return str(uuid.uuid4())
