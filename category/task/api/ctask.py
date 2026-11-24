"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from pathlib import Path
import os
import re
import logging
import tempfile
import time

# The longest prompt that travels as a command line argument. An interactive agent session preloads its
# first prompt that way (the terminal UI owns stdin), and some CLIs have no stdin mode at all. An OS caps a
# command line: 32767 characters for the whole line on Windows, 128 KB per argument on Linux. Over this
# length a prompt is written to a file and the argument becomes a one-line request to read it first
# (prompt_via_file below); the session reads it, follows it and stays interactive as before.
MAX_PROMPT_ARG_CHARS = 30000

# Model providers in the environment of an AI harness (2026-10-30). A run of a cMeta gateway (set-ai-gateway) names the
# variables it puts into its process in GATEWAY_VARS, and every run of a harness - Claude Code, Codex, OpenCode,
# OpenClaw, Gemini CLI, agy, Hermes - drops those of a parent's gateway first: a session that runs through a company
# gateway and starts another agent no longer hands it the gateway (its key, its URL, its model names). A login run of
# a harness that can take a gateway also drops what that harness itself would reach its models with, wherever it came
# from - the login means the tool's own account; a key is a gateway (an ai.gateway artifact). The user's own keys stay
# for the other harnesses, whose keys are one of their ways in (GEMINI_API_KEY for Gemini CLI, Hermes' providers).
GATEWAY_VARS = 'CMETA_AI_GATEWAY_VARS'
PROVIDERS = ('ANTHROPIC_', 'OPENAI_', 'AZURE_OPENAI_', 'MISTRAL_', 'GEMINI_', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_',
             'GOOGLE_GENERATIVE_AI_API_KEY', 'OPENROUTER_', 'GROQ_', 'DEEPSEEK_', 'XAI_', 'TOGETHER_', 'FIREWORKS_',
             'CEREBRAS_', 'CMETA_AI_GATEWAY_KEY')

# Claude Code's provider switches: each sends a session to Bedrock, Vertex, Foundry ... - away from both the claude.ai
# login and a gateway's URL
CLAUDE_SWITCHES = ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
                   'CLAUDE_CODE_USE_ANTHROPIC_AWS', 'CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD', 'CLAUDE_CODE_USE_MANTLE',
                   'CLAUDE_CODE_USE_GATEWAY')
LOGIN_DROPS = {'claude': ('ANTHROPIC_',) + CLAUDE_SWITCHES,           # CLAUDE_CODE_OAUTH_TOKEN stays: the login as a token
               'codex': ('OPENAI_', 'AZURE_OPENAI_', 'CODEX_API_KEY', 'CMETA_AI_GATEWAY_KEY'),
               'opencode': PROVIDERS}                                    # OpenCode takes every provider it finds

# A gateway run of Claude Code takes the key through an apiKeyHelper (2026-11-01): the user's own Anthropic key, token,
# URL or model names would compete with it - a 401 "invalid subscription key" from the gateway, which got the user's
# ANTHROPIC_* in its place - as would a claude.ai token or a provider switch. Codex and OpenCode name the gateway's
# provider on their command line or in their config, where the user's own keys do not compete: theirs stay.
GATEWAY_DROPS = {'claude': ('ANTHROPIC_', 'CLAUDE_CODE_OAUTH_TOKEN') + CLAUDE_SWITCHES}


def drop_provider_variables(harness='', login=False, env=None, gateway=False):
    """
    Removes from "env" (this process's environment by default, which the harness inherits) the variables a parent's
    gateway put there and, for a login run of claude / codex / opencode, the ones that harness takes its models from;
    for a gateway run ("gateway"), those that would compete with the gateway there (GATEWAY_DROPS: Claude Code's).
    Returns the names removed (sorted), so that the caller can say it.
    """
    env = os.environ if env is None else env
    names = {n for n in str(env.get(GATEWAY_VARS) or '').split(',') if n.strip()}
    h = str(harness or '').lower()
    starts = (LOGIN_DROPS.get(h, ()) if login else ()) + (GATEWAY_DROPS.get(h, ()) if gateway else ())
    if starts:
        names |= {n for n in env if n.startswith(starts)}
    dropped = sorted(n for n in names if env.pop(n, None) is not None)
    env.pop(GATEWAY_VARS, None)
    return dropped


def gateway_into_environment(variables, env=None):
    """A gateway's variables into "env" (this process's by default), with their names in GATEWAY_VARS for the runs below."""
    env = os.environ if env is None else env
    env.update({k: str(v) for k, v in (variables or {}).items()})
    if variables:
        env[GATEWAY_VARS] = ','.join(sorted(variables))


# The AI gateways - the category ai.gateway and the task set-ai-gateway (cmeta-aops) - in one place for the harness
# tasks: where the task is not found (a trimmed copy of cmeta-aops) a run is a login run, and a gateway asked for is
# an error that says why - never the login in a gateway's place without a word.
GATEWAY_TASK = 'set-ai-gateway,e10aa0a00edd4a2c'
NO_GATEWAYS = ('no AI gateway can be used here: no plugged repository provides the task set-ai-gateway and the category '
               'ai.gateway (cx repo list) - -ln, or no gateway flag, runs on the tool\'s own login')


def gateways_here(cm):
    """Whether a repository that provides the AI gateways (the task set-ai-gateway) is plugged on this machine."""
    try:
        r = cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'find', 'arg1': GATEWAY_TASK, 'con': False})
    except Exception:
        return False
    return r.get('return', 1) == 0 and bool(r.get('artifacts'))


def gateway_asked(gateway='', gw=''):
    """Whether a gateway was named for a run: --gateway=<alias> (not "login"), or -gw bare or with an alias."""
    named = str(gateway or '').strip().lower()
    return (bool(named) and named != 'login') or gw not in (None, False, '', 'False', 'false')


def choose_gateway(cm, ctx, harness, gateway='', gw='', ln=False):
    """Login or a gateway for a harness run (run-claude, run-codex, run-opencode): what set-ai-gateway decides where
    a repository provides it; else a login run - and a gateway asked for is an error (NO_GATEWAYS)."""
    if not gateways_here(cm):
        if gateway_asked(gateway, gw):
            return {'return': 1, 'error': NO_GATEWAYS}
        return {'return': 0, 'gateway': 'login', 'how': 'no AI gateways on this machine'}
    return cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': GATEWAY_TASK, 'ctx': ctx,
                      'harness': harness, 'gateway': gateway, 'gw': gw, 'ln': ln, 'con': False,
                      'quiet': ctx['control'].get('quiet', False)})


# A terminal that keeps the history of what runs in it (2026-11-18). A program on the terminal's alternate screen
# redraws its window in place, so nothing it shows ever reaches the history one scrolls back to: Claude Code's
# fullscreen renderer (its setting "tui": "fullscreen", which Claude Code may save by itself) and Codex's TUI (on the
# alternate screen by default) left only the lines printed before them. A terminal that wants the whole history - the
# sessions of /ai.sessions, recorded and replayed in every browser that attaches, on any OS - sets
# CMETA_NO_ALT_SCREEN=1, and a harness run asks its harness for the inline mode (main_screen below). A harness not in
# main_screen has no known inline mode: it keeps its history inside itself (the page passes it the wheel).
NO_ALT_SCREEN = 'CMETA_NO_ALT_SCREEN'


def main_screen_asked(env=None):
    """Whether the terminal of this run asked its programs to keep the main screen (CMETA_NO_ALT_SCREEN = 1, yes,
    true or on)."""
    env = os.environ if env is None else env
    return str(env.get(NO_ALT_SCREEN) or '').strip().lower() in ('1', 'yes', 'true', 'on')


def main_screen(harness, flags=(), env=None):
    """
    The main screen for an interactive run of "harness" when its terminal asked for it (CMETA_NO_ALT_SCREEN): the
    harness's own variable set in "env" (this process's environment by default, which the harness inherits), or the
    flags to add to its command - never one the run was given already, nor against a choice made there.
    Returns (flags to add, what was done in a few words; '' when nothing was).
    """
    env = os.environ if env is None else env
    if not main_screen_asked(env):
        return [], ''
    given = [str(f) for f in (flags or [])]
    names = [f.split('=')[0] for f in given]
    h = str(harness or '').lower()
    if h == 'claude':
        # Claude Code: the classic renderer, whatever its settings say (its own words: "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1
        # forces that any time"), set here unless the terminal set it already; not against CLAUDE_CODE_NO_FLICKER, the
        # renderer chosen in the run's environment
        if env.get('CLAUDE_CODE_NO_FLICKER') and not env.get('CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN'):
            return [], ''
        if not env.get('CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN'):
            env['CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN'] = '1'
        return [], 'CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1 (the classic renderer)'
    if h == 'codex':
        # Codex: "--no-alt-screen - runs the TUI in inline mode, preserving terminal scrollback history" (also on
        # "codex resume"); not when the run sets the mode itself (-c tui.alternate_screen=...)
        if '--no-alt-screen' in names or any('tui.alternate_screen' in f for f in given):
            return [], ''
        return ['--no-alt-screen'], '--no-alt-screen (the TUI inline)'
    if h == 'hermes':
        # Hermes Agent: its classic REPL is inline; its TUI (--tui) keeps the terminal's scrollback with --native
        if '--tui' in names and not ({'--native', '--tui-native'} & set(names)):
            return ['--native'], '--native (the TUI on the terminal\'s scrollback)'
        return [], ''
    return [], ''


def prompt_via_file(prompt, tool, when=True, path='', prompt_file='', force=False, why='',
                    limit=MAX_PROMPT_ARG_CHARS, con=False, space=''):
    """
    The text to put on a command line in place of a prompt that cannot travel as an argument.

    A prompt that fits (at most "limit" characters, and no "force") - or any prompt when "when" is False,
    i.e. it goes another way such as stdin - is returned as it is. Otherwise it is written to a file and
    the returned text is a one-line request to read that file first and follow it: the agent reads it,
    does what it says and the session goes on as it would have with the prompt itself (interactive
    sessions stay interactive). The file is "path" when given (run-ai names one in the project's !AI/log),
    else "<prompt_file without extension>-prompt.md" next to the prompt file, else a temporary file that
    the caller removes after the run with prompt_via_file_done().

    "force" asks for the file whatever the length (a launcher script that would mangle the argument), with
    "why" as the reason to print.

    Returns {'return': 0, 'text': <command line text>, 'file': <file written or ''>, 'temporary': bool,
             'reason': <why the file was used or ''>}, or {'return': 1, 'error': ...} when the file
    cannot be written.
    """

    if not when or not prompt or (len(prompt) <= limit and not force):
        return {'return': 0, 'text': prompt, 'file': '', 'temporary': False, 'reason': ''}

    reason = ('too long for a command line argument (%d characters)' % len(prompt)) if len(prompt) > limit \
        else (why or 'it cannot travel as a command line argument')

    temporary = False
    if path:
        file = os.path.abspath(os.path.expanduser(path))
    elif prompt_file:
        file = os.path.splitext(os.path.abspath(os.path.expanduser(prompt_file)))[0] + '-prompt.md'
    else:
        try:
            handle, file = tempfile.mkstemp(prefix='run-%s-prompt-' % tool, suffix='.md')
            os.close(handle)
        except Exception as e:
            return {'return': 1, 'error': 'cannot create a temporary file for the prompt: %s' % e}
        temporary = True

    try:
        folder = os.path.dirname(file)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(file, 'w', encoding='utf-8', newline='\n') as f:
            f.write(prompt if prompt.endswith('\n') else prompt + '\n')
    except Exception as e:
        return {'return': 1, 'error': 'cannot write the prompt to %s: %s' % (file, e)}

    text = ('Read the whole file "%s" first - in several reads if one read truncates it. It holds the first '
            'request of this session (%d characters); then follow it.' % (file.replace('\\', '/'), len(prompt)))

    if con:
        print('')
        print('%sINFO: the prompt is %s - it is written to %s and %s is asked to read it first%s' % (
            space, reason, file, tool, ' (the file is removed after the run)' if temporary else ''))

    return {'return': 0, 'text': text, 'file': file, 'temporary': temporary, 'reason': reason}


def prompt_via_file_done(result):
    """Remove the temporary file prompt_via_file() made, if any (a file named by the caller is kept)."""

    if result and result.get('temporary') and result.get('file'):
        try:
            os.remove(result['file'])
        except Exception:
            pass
        result['temporary'] = False

    return {'return': 0}


def ask(question, how='-q (--quiet) to take the default answers', optional=False):
    """
    A question to the person who runs the command (every prompt of a task goes through here).

    input() raises when nobody can answer: EOFError when the standard input is closed or at its end (a
    detached job, nohup, a CI step, a pipe that has no more lines), RuntimeError when Python has no
    standard input at all, OSError or ValueError when its handle is invalid or closed (a job started
    without a console on Windows) - and the run ended in a traceback in the middle of an install. Here that is an
    error of the run that says how to answer in advance ("how": the flag that makes the question
    unnecessary). An answer is never made up: the default of "install (Y/n)?" may install with sudo. An
    answer that is piped in (echo y | cx ...) is read as before.

    "optional": no answer is the empty answer (a pause before going on, a choice whose default changes
    nothing) instead of an error.

    Returns {'return': 0, 'answer': <the line typed>}, or {'return': 1, 'error': ..., 'no_terminal': True}.
    """

    try:
        return {'return': 0, 'answer': input(question)}
    except (EOFError, OSError):
        # the end of the input, or a standard input that cannot be read (an invalid handle, a terminal that hung up)
        pass
    except (RuntimeError, ValueError) as e:
        # "input(): lost sys.stdin", "I/O operation on closed file" - anything else is not ours
        if 'stdin' not in str(e) and 'closed file' not in str(e):
            raise

    # The prompt was printed and its line left open
    print('')

    if optional:
        return {'return': 0, 'answer': '', 'no_terminal': True}

    text = ' '.join(str(question).split())
    return {'return': 1,
            'error': 'no answer to "%s": there is no terminal to answer in (the standard input is closed). '
                     'Run the command in a terminal, or add %s' % (text, how),
            'no_terminal': True}


def supported_options(program, help_words, options, timeout = 60):
    """
    Which of these options a program takes, whatever its version: the ones its own help names (program + help_words,
    e.g. ['profile', '--help']). A tool adapts to the version it wraps by asking it - never by a version number, never
    by a guess. An option is found as a whole word of the help's text. A program that cannot be run or prints no help
    takes none.

        extra = supported_options(nsys, ['profile', '--help'], ['--trace-fork-before-exec'])
    """
    import re
    import subprocess

    try:
        p = subprocess.run([str(program)] + [str(w) for w in help_words], stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                           stdin = subprocess.DEVNULL, timeout = timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    text = p.stdout.decode('utf-8', 'replace')
    return [o for o in options if re.search(r'(?<![\w-])' + re.escape(str(o)) + r'(?![\w-])', text)]


def pins(ctx):
    """
    A copy of the pins of a run: what "--use.<storage key>.<param>=<value>" (and the machine's own defaults, the key
    "use" of config::task) put into ctx['tasks']['use'] - the versions and settings the outermost command line asks of
    the sub-tasks, by their storage keys.

    How the pins reach the tasks a task starts (the three ways a task starts another one):

      1. A sub-task of the SAME STACK (its tools must agree with the caller's: a tool set up for the run, a compiler):
         the caller's context itself - {'ctx': ctx, ...} in the call. The pins reach it, a tool already chosen in this
         run is the same one for it (ctx['tasks']['global'], by storage key: in one run a storage key is one choice -
         a second request that asks another version gets the first choice, and the engine says so), and what it adds
         to the run's environment is seen by the caller. The engine gives the caller back its own params, local
         values and control afterwards - also when the sub-task fails.

      2. A RUN OF ITS OWN in this process (one variant of an exploration, one host of many, a sub-run whose tools
         must not be taken from the caller's): no ctx in the call. It starts as an outermost run - nothing the
         caller or an earlier variant chose is seen by it - and the engine gives it the pins the caller's run was
         given, below its own "use": {'use': {<storage key>: {'version': ...}}} is what a variant adds or changes.
         Nothing to hand on by hand (before 2026-11-23: {'use': pins(ctx)} - still right, and no longer needed).

      3. A run in ANOTHER PROCESS, here or on another host (cx host run, a pod, a Slurm job, a container): the pins
         as words of its command line - use_words(run_pins(ctx)) after "cx task run <task>" / "cx program run
         <program>". The machine's own defaults are not sent: every machine, and every process, reads its own.

    This function gives everything in force (for a record, a message); what is handed on is run_pins(ctx).
    """
    import copy

    return copy.deepcopy((((ctx or {}).get('tasks') or {}).get('use')) or {})


def run_pins(ctx):
    """
    A copy of the pins GIVEN FOR THIS RUN - by the command line's --use.<storage key>.<param>=<value> and by the callers'
    "use" - without the machine's own defaults (the key "use" of config::task, which pins(ctx) holds too): what goes
    with a sub-run on another machine, which has defaults of its own (a path of this machine's Python means nothing
    there). The task engine keeps them in ctx['tasks']['use_run'].

    Asking for them says that they go with a run the engine of this process does not see: the engine then does not
    judge, at the end of the outermost run, which pins no task took (ctx['tasks']['pins_not_judged']).
    """
    import copy

    tasks = (ctx or {}).get('tasks') if isinstance(ctx, dict) else None
    given = (tasks or {}).get('use_run') or {}
    if given and isinstance(tasks, dict):
        tasks['pins_not_judged'] = True
    return copy.deepcopy(given)


def use_words(use):
    """
    The pins of a run (a dict as pins(ctx) gives it) as the command line words that make them again:
    {'python': {'version': '3.12'}, 'nvcc': {'with': {'debug': True}}} -> ['--use.python.version=3.12',
    '--use.nvcc.with.debug'] - what the engine's command line reads back into the same dict (key=value: the value as
    text, typed by the task that takes it; a key alone: True; "key-": False; "key,=a,b": a list). The words are not
    quoted: a caller that builds a shell line quotes each one. ValueError for what a command line cannot carry (a key
    with a dot, "=", "," or a space; a list item with a comma; a value that is not text, a number, a switch or a list).
    """
    words = []

    def walk(prefix, value):
        for key, v in value.items():
            key = str(key)
            if not key or any(c in key for c in '.=, \t\n') or key.endswith('-'):
                raise ValueError(f'the pin key "{key}" (under {prefix}) cannot be written on a command line')
            name = f'{prefix}.{key}'
            if isinstance(v, dict):
                walk(name, v)
            elif v is None:
                continue
            elif v is True:
                words.append(name)
            elif v is False:
                words.append(name + '-')
            elif isinstance(v, (list, tuple)):
                items = [str(x) for x in v]
                if any(',' in x for x in items) or not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in v):
                    raise ValueError(f'the pin {name} is a list a command line cannot carry: {v!r}')
                words.append(f'{name},={",".join(items)}')
            elif isinstance(v, (str, int, float)):
                words.append(f'{name}={v}')
            else:
                raise ValueError(f'the pin {name} is a {type(v).__name__}: a command line cannot carry it')

    walk('--use', use or {})
    return words


def folder_as_named(named, base=None):
    """
    The current directory under the name the request gave it.

    A task runs in the folder it was asked to work in (--path, the venv path of a python request) and
    os.getcwd() names that folder by its physical path: on Linux and macOS every link in the path is
    resolved (/home/me/work -> /mnt/disk/work, ~/CMETA moved to another disk behind a link, /tmp ->
    /private/tmp on every Mac), while the next request names the folder as before. What a task records
    from os.getcwd() is then not what the next request looks for: a venv made at <link>/venv was recorded
    under its physical path and found under its name, so one venv became two pythons, each with its own
    record of every package. cMeta records a folder as it was named and resolves no link (the two names can
    mean different things: the link is what survives when the disk behind it changes); Windows does so
    by itself (its current directory keeps the name it was given).

    Returns "named" (made absolute against "base", the directory the request was made in, and
    normalised) when it is the current directory under another name, else os.getcwd() - also when
    "named" is empty or is not the current directory at all.
    """

    here = os.getcwd()

    if not named:
        return here

    path = named if os.path.isabs(named) else os.path.join(base or here, named)
    path = os.path.normpath(path)

    if os.path.normcase(path) == os.path.normcase(here):
        return here

    try:
        if os.path.samefile(path, here):
            return path
    except OSError:
        pass

    return here


# The key of the generator record that names what launched the agent or the task: "via: cmeta <engine version>".
# A record {"method": "agent", "agent": "Claude Code 2.1.292", "by": ..., "model": ...} then says that the agent ran
# through a cMeta task (run-ai, run-claude, ...) rather than by hand. One constant, so the word can change in one place.
GENERATOR_VIA_KEY = 'via'


AI_RUN_ENV = 'CMETA_AI_RUN'      # set by run-ai for the harness it starts: the run it belongs to (run-ai's RUN_REF_ENV)
UID16 = re.compile(r'^[0-9a-fA-F]{16}$')     # a cMeta UID: 16 hex digits in either case (kept in lower case)


def ai_run_record(harness=''):
    """
    What the generator record of an agent that run-ai (cxai) started adds (the user, 2026-11-19: "can we add
    cmeta_task: run-ai along with harness"): {'cmeta_task': 'run-ai', 'harness': <name>, 'ai_run': {'project':
    '<category UID>::<artifact UID>', 'conversation': <id>, 'run': <stamp>}}, from CMETA_AI_RUN. The project is named
    by its UIDs alone - it resolves on any machine that has it (cx utils cref), while the artifacts that carry the
    record may be public and its name private; a project without a cRef (a plain folder) is left out. {} outside
    run-ai.
    """
    import urllib.parse
    ref = os.environ.get(AI_RUN_ENV, '')
    if not ref:
        return {}
    fields = {}
    for part in ref.split(';'):
        k, _, v = part.partition('=')
        if k.strip() and v:
            fields[k.strip()] = urllib.parse.unquote(v)
    run = {}
    cat, sep, art = fields.get('project', '').partition('::')
    if sep:
        cu, au = cat.split(',')[-1].strip(), art.split(',')[-1].strip()
        if UID16.match(cu) and UID16.match(au):
            run['project'] = cu.lower() + '::' + au.lower()
    for k in ('conversation', 'run'):
        if fields.get(k):
            run[k] = fields[k]
    out = {'cmeta_task': 'run-ai'}
    if harness:
        out['harness'] = harness
    if run:
        out['ai_run'] = run
    return out


def generator_via():
    """'cmeta <version>' of the engine this task runs in ('cmeta' when the version cannot be read)."""
    try:
        from cmeta.version import __version__
        return 'cmeta ' + str(__version__)
    except Exception:
        return 'cmeta'


def tree_signature(path):
    """
    A cheap signature of a repository on this machine: the modification times of its folder and of its first-level
    folders (a category folder changes when an artifact is added, moved or removed in it) - one directory listing.
    os.stat of each folder itself: on Windows a listing's entry carries the time the parent's index cached, which NTFS
    updates later (a tool added a moment ago did not show).
    """
    try:
        stamps = [os.stat(path).st_mtime_ns]
        with os.scandir(path) as entries:
            stamps += [os.stat(e.path).st_mtime_ns for e in entries
                       if e.is_dir(follow_symlinks=False) and not e.name.startswith('.')]
        return str(max(stamps))
    except OSError:
        return ''


MOUNTED_SIGNATURES = 'mounted-signatures.json'


def write_signatures(folder, mounts):
    """
    The signatures of repositories seen live by another system (an instance, a WSL distribution: [{repo, path}]) as
    that system has just indexed them, into <folder>/mounted-signatures.json (the folder of its host artifact).
    """
    import json
    try:
        with open(os.path.join(folder, MOUNTED_SIGNATURES), 'w', encoding='utf-8') as f:
            json.dump({m['repo']: tree_signature(m['path']) for m in mounts if m.get('path')}, f, indent=1, sort_keys=True)
    except OSError:
        pass


def changed_mounts(folder, mounts):
    """
    The repositories of mounts that changed here since the other system indexed them: its index knows only what it
    saw, so these are reindexed there before a run (cx repo reindex <alias>). Never recorded: all of them.
    """
    import json
    try:
        with open(os.path.join(folder, MOUNTED_SIGNATURES), encoding='utf-8') as f:
            known = json.load(f) or {}
    except (OSError, ValueError):
        known = {}
    return [m for m in mounts if m.get('path') and known.get(m['repo']) != tree_signature(m['path'])]


# A process a task recorded (a server's number in a file) is still the one it started only while the record was
# written after the machine's last boot and the process did not start after the record was written: after a reboot
# the numbers are given out again, and the same number may belong to any program - or to the task's own new process
# tree (2026-11-13: a website's start said "Already running" over a helper of its own start and stayed down; a stop
# would have killed that process). Every task that keeps a process number asks recorded_process_alive() before it
# says "running" or stops anything (the website runtime of manage-cmeta-project has the same three functions).

def boot_time():
    """When this machine started (seconds since the epoch), or 0 when the system does not say."""
    import subprocess
    import sys
    import time
    try:
        if sys.platform.startswith('linux'):
            with open('/proc/stat', encoding='ascii', errors='replace') as f:
                for line in f:
                    if line.startswith('btime '):
                        return float(line.split()[1])
        elif os.name == 'nt':
            import ctypes
            ticks = ctypes.windll.kernel32.GetTickCount64
            ticks.restype = ctypes.c_ulonglong
            return time.time() - ticks() / 1000.0     # the wall clock minus the time since the start
        else:                                          # macOS and the BSDs: "{ sec = 1794470153, usec = 0 } ..."
            import re
            out = subprocess.run(['sysctl', '-n', 'kern.boottime'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, text=True, timeout=10).stdout
            m = re.search(r'sec\s*=\s*(\d+)', out)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return 0.0


def process_started(pid):
    """When a process started (seconds since the epoch), or None when the system does not say."""
    import subprocess
    import sys
    import time
    try:
        pid = int(pid)
        if sys.platform.startswith('linux'):
            with open('/proc/%d/stat' % pid, encoding='ascii', errors='replace') as f:
                fields = f.read().rsplit(')', 1)[-1].split()
            boot = boot_time()
            # starttime, the 22nd field: clock ticks after the boot (the 20th after the name)
            return boot + int(fields[19]) / os.sysconf('SC_CLK_TCK') if boot else None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                    return None
                created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                return created / 1e7 - 11644473600.0     # 100 ns since 1601 -> seconds since 1970
            finally:
                kernel32.CloseHandle(handle)
        out = subprocess.run(['ps', '-o', 'lstart=', '-p', str(pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, text=True, timeout=10, env=dict(os.environ, LC_ALL='C')).stdout.strip()
        if out:
            return time.mktime(time.strptime(out, '%a %b %d %H:%M:%S %Y'))
    except Exception:
        pass
    return None


def process_exists(pid):
    """Whether a process of this number runs on this machine: the engine's pid_exists (cMeta 0.38.12+), else
    os.kill(pid, 0) - a process this one may not signal exists too."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        from cmeta.utils.sys import pid_exists
        return bool(pid_exists(pid))
    except ImportError:
        pass
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def recorded_process_alive(pid, written, alive=None):
    """Whether the process a record names (pid) is still the one the record was written for: written (the record's
    time - a pid file's mtime, or the time.time() kept in it) after the machine's last boot, the process alive (alive(pid)
    when the task has its own check - the program's name, say -, else process_exists), and not started more than 5 s
    after written (a task writes its record right after starting the process)."""
    try:
        pid = int(pid)
        written = float(written)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    boot = boot_time()
    if boot and written < boot - 2:
        return False
    if not (alive(pid) if alive else process_exists(pid)):
        return False
    started = process_started(pid)
    return not (started is not None and started > written + 5)


def recorded_file_alive(pid_file, pid=None, alive=None):
    """recorded_process_alive() for a pid file: its number (or pid, when the caller read it already) and its mtime."""
    try:
        written = os.path.getmtime(pid_file)
        if pid is None:
            with open(pid_file, encoding='utf-8', errors='replace') as f:
                pid = int((f.read().split() or ['0'])[0])
    except (OSError, ValueError):
        return False
    return recorded_process_alive(pid, written, alive)


# A server started on Windows by a command that is run with a time limit dies with that command: the engine's run()
# puts a timed command in a job that ends everything it started when it returns (KILL_ON_JOB_CLOSE), and "cx host up
# <host> --project=..." - the Start button of the hosts page - runs a server's start command that way (2026-11-18: a
# server came up and was gone a second later). Breaking away from the job does not help: for a direct child the
# engine's job refuses it, and from a cx command it "succeeds" out of the launcher's inner job only. So the system
# itself starts the process (Win32_Process.Create): it belongs to no job of the caller. Such a process gets the user's
# own environment (what Windows keeps for the account), not the caller's - a server does not inherit the keys of the
# session that asked for it - and no stream of the caller: it writes its own log, or shows its own console window.

def start_by_system(line, cwd='', window=False, timeout=60):
    """Windows: start a command line as a process of its own, by the system, outside every job of this process ->
    (its process number, '') or (0, why not). window: a console window of its own on the desktop of this session
    (False: no window at all). The line travels in a variable: no quoting of PowerShell touches it."""
    import subprocess
    if os.name != 'nt':
        return 0, 'Windows only'
    script = ('$s = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]%d }; '
              '$a = @{ CommandLine = $env:CMETA_START_LINE; ProcessStartupInformation = $s }; '
              'if ($env:CMETA_START_DIR) { $a.CurrentDirectory = $env:CMETA_START_DIR }; '
              '$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $a; '
              "if ($r.ReturnValue -ne 0) { Write-Output ('failed ' + $r.ReturnValue); exit 1 }; "
              "Write-Output ('started ' + $r.ProcessId)") % (1 if window else 0)       # SW_SHOWNORMAL | SW_HIDE
    env = dict(os.environ, CMETA_START_LINE=str(line), CMETA_START_DIR=str(cwd or ''))
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 0, 'PowerShell could not ask the system: %s' % e
    words = r.stdout.decode('utf-8', 'replace').split()
    if r.returncode == 0 and len(words) >= 2 and words[-2] == 'started' and words[-1].isdigit():
        return int(words[-1]), ''
    said = (r.stdout + b' ' + r.stderr).decode('utf-8', 'replace').strip()
    # Win32_Process.Create's own codes: 2 access denied, 3 insufficient privilege, 8 unknown failure, 9 path not found
    return 0, 'Win32_Process.Create did not start it: %s' % (' '.join(said.split())[-300:] or 'no answer')


# The file cache: the folders outside the cache entries that keep large downloads and clones (the keys file_cache and
# hf.cache of config::task - one place, or several separated as PATH is, the first one first). The rule (2026-11-17:
# a model was downloaded a second time to another drive while the USB drive of the cache was away, and nothing said so):
#   - a place that is there is used; one whose folder is missing where its parent folder is there is made - its last
#     folder only, so that a path of a drive that is away never becomes a folder of the machine's own disk;
#   - a place that is away (its drive is not connected, its parent folder does not exist, it cannot be made) is passed
#     over for the next one of the list, and the run says so in one line;
#   - what is asked for (a model, a clone) is taken from the place that has it already, whichever it is, before a new
#     copy is made in the first one;
#   - no place of the list is there: the run stops and says what to do - never a silent download somewhere else.
# A drive that is there but does not answer yet (Windows: "the device is not ready", after a standby) is given a
# moment; a drive letter that does not exist is not waited for.
FILE_CACHE_WAIT = 3.0                 # seconds
FILE_CACHE_NOT_READY = (21, 31, 55, 1167)      # Windows: not ready, not functioning, no longer available, not connected
_FILE_CACHE_SAID = set()              # the lines said already in this process (a run asks for the cache several times)


def file_cache_place(place):
    """A place of the file cache now: ('there', '') | ('to make', '') - its last folder is missing, its parent is
    there | ('not ready', why) - its drive is there but does not answer | ('away', why)."""
    if os.path.isdir(place):
        return 'there', ''

    full = os.path.abspath(place)
    drive = os.path.splitdrive(full)[0]
    if drive:
        try:
            os.stat(drive + os.sep)
        except OSError as e:
            name = 'the drive %s' % drive if len(drive) == 2 else drive
            if getattr(e, 'winerror', None) in FILE_CACHE_NOT_READY:
                return 'not ready', '%s does not answer' % name
            return 'away', '%s is not connected' % name

    if os.path.exists(full):
        return 'away', 'it is a file, not a folder'
    parent = os.path.dirname(full)
    if not os.path.isdir(parent):
        return 'away', 'its folder %s does not exist' % parent
    return 'to make', ''


def file_cache_folder(places, sub_folder='', key='file_cache', con=False, space='', wait=FILE_CACHE_WAIT):
    """The folder of the file cache to use now, by the rule above.

    places: the value of the config key (one place, or several separated as PATH is); sub_folder: what the caller
    keeps there (get-hf-model/<repository>) - a place that has it already is taken first; key: the key of
    config::task the places come from, for the messages; con: say on the console that a place was passed over.

    Returns {'return': 0, 'path': the folder (made when its last folder was missing), 'away': {place: why},
    'note': the line about a place passed over, or ''} - 'path' is '' when no place is given - or
    {'return': 1, 'error': ..., 'away': ...} when no place of the list can be used."""
    listed = [p.strip() for p in str(places or '').split(os.pathsep) if p.strip()]
    if not listed:
        return {'return': 0, 'path': '', 'away': {}, 'note': ''}

    states, away = {}, {}
    deadline = time.monotonic() + wait
    for place in listed:
        state, why = file_cache_place(place)
        while state == 'not ready' and time.monotonic() < deadline:
            time.sleep(0.25)
            state, why = file_cache_place(place)
        states[place] = state
        if why:
            away[place] = why

    # what is asked for is taken where it is already; else the first place that is there or can be made
    usable = [p for p in listed if p not in away]
    having = [p for p in usable if sub_folder and os.path.isdir(os.path.join(p, sub_folder))]
    path = ''
    for place in having + [p for p in usable if p not in having]:
        if states[place] == 'to make':
            try:
                os.mkdir(place)
            except OSError as e:
                away[place] = 'it cannot be made (%s)' % (e.strerror or e)
                continue
        path = place
        break

    change = 'cx config set task "--meta.%s=<a folder>%s<another folder>"' % (key, os.pathsep)
    if not path:
        if len(listed) == 1:
            text = 'the file cache %s is not available: %s. Connect its drive, or name a second place for such a ' \
                   'day (%s)' % (listed[0], away[listed[0]], change)
        else:
            text = 'no place of the file cache is available: %s. Connect one of the drives, or change the key %s ' \
                   'of the task config (%s)' % ('; '.join('%s - %s' % (p, away[p]) for p in listed), key, change)
        return {'return': 1, 'error': text, 'away': away}

    note = ''
    before = [p for p in listed[:listed.index(path)] if p in away]
    if before:
        note = 'the file cache %s is not available (%s): using %s' % (before[0], away[before[0]], path)
        if con and note not in _FILE_CACHE_SAID:
            _FILE_CACHE_SAID.add(note)
            print('%sWARNING: %s' % (space, note))
    return {'return': 0, 'path': path, 'away': away, 'note': note}


class InitCTask:
    """
    """

    ############################################################
    def __init__(self,
                 cm = None,
                 module_file_path = None,
                 logger: logging.Logger = None):

        self.cm = cm

        file_path = Path(module_file_path)

        module_name = file_path.stem

        path_parts = file_path.parts
        
        task_module_name = '___' + path_parts[-3] + '___.' + path_parts[-2] + '.' + module_name

        module_path = os.path.dirname(module_file_path)
        path = os.path.dirname(module_path)

        self.module_file_path = module_file_path
        self.module_path = module_path
        self.module_name = module_name
        self.path = path
        self.task_module_name = task_module_name

        # Create a child logger that inherits CMeta's configuration
        self.logger = logger if logger is not None else self.cm.logger.getChild(self.task_module_name)

        if self.cm.debug:
            import inspect

            stack = inspect.stack()

            caller_frame = stack[1]

            self.logger.debug(f"Initializing CTask class from: {caller_frame.filename}:{caller_frame.lineno}")

    ############################################################
    def init_call(self,
                  ctx,
                  category = None,
                  command = None,
                  task = None,
        ):

        params = {}

        params['category'] = category if category else ctx['category']
        params['command'] = command if command else 'run'
        if task: params['arg1'] = task

        ctx_control = ctx['control']

        for key in ['con', 'verbose', 'quiet']:
            if key in ctx_control:
                params[key] = ctx_control[key]
            
        return {'return':0, 'params': params}


    ############################################################
    def customize_cache_artifact(self, 
                                 *args, 
                                 **params
        ):
        return {'return':0}
 
