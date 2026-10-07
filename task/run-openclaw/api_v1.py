"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

This task is the OpenClaw (https://openclaw.ai) sibling of the "run-claude",
"run-codex" and "run-opencode" tasks.
"""

import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, prompt_via_file, prompt_via_file_done

# Suffix appended to the prompt file name (without extension) when --output_file is not given
OUTPUT_FILE_SUFFIX = '-output.txt'

# Output file used when there is no prompt file to derive the name from
DEFAULT_OUTPUT_FILE = 'run-openclaw-output.txt'

# Flags that decide the output format; --stats leaves them alone when passed after "--"
OUTPUT_FORMAT_FLAGS = ['--json']

# Flags that choose the session of a headless turn - "openclaw agent" refuses to run without one;
# the task adds "--agent <agent>" (default "main", the agent OpenClaw creates) unless one is passed after "--"
SESSION_FLAGS = ['--agent', '--session-id', '--session-key', '--to', '-t']

# Flags of the model and of the thinking level ("effort") in an openclaw command line
MODEL_FLAGS = ['--model']
THINKING_FLAGS = ['--thinking']

# "openclaw agent" and the terminal UI take the prompt as the value of --message (there is no stdin
# mode), and an OS caps a whole command line (32767 chars on Windows, 128 KB per argument on Linux).
# A longer prompt is written to a file and openclaw is asked to read it first: see prompt_via_file()
# in the task category API (MAX_PROMPT_ARG_CHARS there).


def _flag_value(flags, names):
    """The value of "<name> value" or "<name>=value" in an openclaw command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] in names:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def _sums(tokens):
    """The counters as run-claude reports them: sent = new input + cache write + cache read, total = sent + output."""
    if not tokens:
        return {}
    out = dict(tokens)
    for key in ('input', 'cache_write', 'cache_read', 'output'):
        out.setdefault(key, 0)
    out['sent'] = out['input'] + out['cache_write'] + out['cache_read']
    out['total'] = max(out['sent'] + out['output'], tokens.get('total', 0))
    return out


def _claude_session_usage(session_id, since):
    """
    The token counts of the model calls Claude Code made for one OpenClaw turn (the claude-cli
    provider): the assistant messages of its session file <claude config>/projects/<slug>/<id>.jsonl
    written since the turn started, each message once (Claude Code writes a line per content block,
    all with the message's usage). {} when the file is not found.
    """
    base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
    files = glob.glob(os.path.join(glob.escape(os.path.join(base, 'projects')), '*', glob.escape(str(session_id)) + '.jsonl'))
    if not files:
        return {}
    usage_by_message = {}
    try:
        with open(files[0], encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                message = d.get('message') if isinstance(d, dict) else None
                if d.get('type') != 'assistant' or not isinstance(message, dict) or not isinstance(message.get('usage'), dict):
                    continue
                stamp = str(d.get('timestamp') or '')
                try:
                    when = datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
                except ValueError:
                    continue
                if when < since - 2:
                    continue
                usage_by_message[message.get('id') or len(usage_by_message)] = message['usage']
    except OSError:
        return {}
    if not usage_by_message:
        return {}
    tokens = {'input': 0, 'cache_write': 0, 'cache_read': 0, 'output': 0}
    for usage in usage_by_message.values():
        for src, dst in (('input_tokens', 'input'), ('cache_creation_input_tokens', 'cache_write'),
                         ('cache_read_input_tokens', 'cache_read'), ('output_tokens', 'output')):
            if isinstance(usage.get(src), (int, float)):
                tokens[dst] += usage[src]
    tokens = _sums(tokens)
    tokens['model_calls'] = len(usage_by_message)
    tokens['from'] = "Claude Code's session %s (the claude-cli provider)" % session_id
    return tokens


def _openclaw_argv(openclaw_path):
    """
    The argv prefix that starts openclaw.

    On Windows npm installs "openclaw.cmd", a batch shim. A batch file is parsed by cmd.exe, which
    would interpret characters such as & | < > % in a prompt passed as an argument - so the shim is
    bypassed and node runs the package's entry script (openclaw.mjs) directly, exactly as the shim
    does. On Linux and macOS "openclaw" is the script itself and is run as it is.
    """
    if openclaw_path.lower().endswith('.cmd'):
        base = os.path.dirname(openclaw_path)
        script = os.path.join(base, 'node_modules', 'openclaw', 'openclaw.mjs')
        node = os.path.join(base, 'node.exe')
        if not os.path.isfile(node):
            node = shutil.which('node') or 'node'
        if os.path.isfile(script):
            return [node, script]
    return [openclaw_path]


def _agent_generator(argv, flags):
    """
    The CMETA_GENERATOR record of an openclaw run: the agent and its version, and the model and
    thinking level it was started with (--model / --thinking).
    """
    rec = {'method': 'agent', 'agent': 'OpenClaw'}
    try:
        out = subprocess.run(argv + ['--version'], capture_output=True, text=True, timeout=60).stdout
        version = next((x for x in out.split() if x[:1].isdigit()), '')
        if version:
            rec['agent'] = 'OpenClaw ' + version
    except Exception:
        pass
    model = _flag_value(flags, MODEL_FLAGS)
    if model:
        rec['model'] = model
    effort = _flag_value(flags, THINKING_FLAGS)
    if effort:
        rec['effort'] = effort
    return rec


# The agent CLIs OpenClaw may run as sub-agents, as cMeta tools (alias: UID). They are set up before
# openclaw starts - detected where they are, never installed here - and their folders go first on the
# PATH of the openclaw process, so a sub-agent is the copy cMeta knows (pinned, recorded), not whatever
# the shell's PATH holds; an agent that is not on this machine is reported and skipped.
SUB_AGENTS = {'claude': '383841b240c74e88', 'codex': 'cdbf5f6e6882460f', 'opencode': '7777071804e84fb5',
              'gemini': '40a20e8dca604ece', 'agy': '433f36c666ce47f1'}
DEFAULT_AGENTS = ','.join(SUB_AGENTS)


def _child_env(bins, base = None):
    """The environment of the openclaw process: the given folders first on PATH, then the shell's."""
    env = dict(os.environ if base is None else base)
    folders = [b for b in bins if b]
    if folders:
        env['PATH'] = os.pathsep.join(folders + ([env['PATH']] if env.get('PATH') else []))
    return env


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def agents_on_path(self, ctx, agents, con = False, space = ''):
        """
        Set up the agent CLIs named in `agents` (comma-separated aliases of SUB_AGENTS, or any tool alias)
        as cMeta tools, detect only, and return {'bins': [folder, ...], 'found': {alias: path}, 'missing': [alias]}.
        A tool that is not on this machine is skipped (no install from here).
        """
        names = [a.strip() for a in str(agents or '').split(',') if a.strip()]
        bins, found, missing = [], {}, []
        g = ctx['tasks']['global']
        for alias in names:
            name = f'{alias},{SUB_AGENTS[alias]}' if alias in SUB_AGENTS else alias
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'ctx': ctx, 'name': name, 'skip_install': True, 'con': False, 'quiet': True})
            tool = g.get(alias) if isinstance(g.get(alias), dict) else None
            path = (tool or {}).get('path')
            if r.get('return', 1) != 0 or not path:
                missing.append(alias)
                continue
            folder = (tool or {}).get('path_bin') or os.path.dirname(str(path))
            found[alias] = str(path)
            if folder and folder not in bins:
                bins.append(folder)
        if con and (found or missing):
            print ('')
            if found:
                print (f'{space}INFO: sub-agents on the PATH of openclaw (cMeta tools): ' +
                       ', '.join(f'{a} ({p})' for a, p in found.items()))
            if missing:
                print (f'{space}INFO: sub-agents not on this machine (not installed from here): ' + ', '.join(missing))
        return {'return': 0, 'bins': bins, 'found': found, 'missing': missing}

    ############################################################
    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            long_prompt_file: str = '',     # where a prompt too long for the command line is written for openclaw to read
            interactive: bool = False,      # open the terminal UI with the prompt as the first message
            i: bool = False,                # short alias of "interactive" (--i / -i)
            gateway: bool = False,          # run the turn through a running OpenClaw Gateway instead of --local
            agent: str = 'main',            # the OpenClaw agent of a headless turn (--agent)
            session: str = '',              # an explicit session id (--session-id); default: the agent's session
            stats: bool = False,            # print the token usage and cost at the end
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            dry_run: bool = False,          # print the openclaw command line and run nothing
            agents: str = DEFAULT_AGENTS,   # the agent CLIs put first on openclaw's PATH as cMeta tools (detected, not installed); '' = none
            unparsed: list = None,          # extra flags for openclaw (everything after "--")
    ):

        """
        Assemble a prompt and run one OpenClaw agent turn headless ("openclaw agent --local
        --message <prompt>"), or open the OpenClaw terminal UI.

        This is the OpenClaw sister of the "run-claude", "run-codex" and "run-opencode"
        tasks and takes the same flags. The prompt is the text of "prompt_file" (when given),
        then a new line, then "prompt".

        With "interactive" (or "i"), or with no prompt at all, the terminal UI is opened instead
        ("openclaw tui --local", the same as "openclaw chat"), with the assembled prompt sent as
        its first message. The UI owns the terminal, so nothing can be captured: "stats",
        "stats_file" and "output_file" are switched off, and a non-zero exit code is reported
        but not turned into an error.

        By default the turn runs in the embedded agent runtime of this machine ("--local"), with
        the model-provider keys of the shell or of OpenClaw's auth store. With "gateway" it goes
        through a running OpenClaw Gateway instead.

        With "stats", OpenClaw is asked for JSON output ("--json"); the reply text is printed and
        recorded as usual, and the token usage and cost found in the result are printed at the end.
        "stats_file" records the same statistics and turns "stats" on.

        The prompt is the value of "--message" in both modes (openclaw has no stdin mode), which
        the OS caps (32767 characters for the whole command line on Windows). A prompt longer than
        MAX_PROMPT_ARG_CHARS of the task category API (30000) is therefore written to a file -
        "long_prompt_file" when given, else next to the prompt file, else a temporary file removed
        after the run - and openclaw is asked to read it first: it then follows it, and the terminal
        UI stays open as before.

        Args:
            ctx (dict): cMeta context.
            prompt (str): Prompt text (appended after the prompt file text).
            prompt_file (str): File with the prompt text (read as UTF-8).
            long_prompt_file (str): Where a prompt too long for the command line is written for openclaw to read.
            interactive (bool): If True, open the terminal UI with the prompt as the first message.
            i (bool): Short alias of "interactive".
            gateway (bool): If True, run through a running OpenClaw Gateway instead of "--local".
            agent (str): The OpenClaw agent that runs a headless turn ("--agent", default "main").
            session (str): An explicit session id ("--session-id"); default: the agent's own session.
            stats (bool): If True, print token usage and cost of this turn at the end.
            stats_file (str): File to record the statistics (JSON if it ends with ".json"); implies "stats".
            output_file (str): File to record the output (overrides the default name).
            skip_output_file (bool): If True, do not record the output to a file.
            append_output_file (bool): If True, append to the output file instead of overwriting it.
            skip_output_header (bool): If True, do not add the summary header to the output file.
            dry_run (bool): If True, print the openclaw command line and run nothing.
            unparsed (list): Extra flags passed to openclaw (everything after "--").

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **output** (str): The output of openclaw ('' if `interactive`).
                - **output_file** (str): Where the output was recorded ('' if skipped).
                - **prompt** (str): The assembled prompt.
                - **long_prompt_file** (str): The file the prompt was written to when it was too long for the command line ('' if none).
                - **cmd** (list): The openclaw command line (the prompt shortened).
                - **returncode** (int): Return code of openclaw.
                - **duration** (float): Run time in seconds.
                - **interactive** (bool): True if the terminal UI was opened.
                - **tokens** (dict): Token usage and cost if `stats` and OpenClaw reported them.
                - **stats_file** (str): Where the statistics were recorded ('' if none).
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']
        openclaw_path = _global.get('openclaw', {}).get('path', '')
        if not openclaw_path:
            return self.cm.error('the "openclaw" tool was not set up (no path in the global context)', 1)

        interactive = interactive or i
        argv0 = _openclaw_argv(openclaw_path)

        # The sub-agents OpenClaw may call (claude, codex, ...) come from cMeta's tools, first on its PATH
        sub = self.agents_on_path(ctx, agents, con = con, space = space)
        openclaw_bin = _global.get('openclaw', {}).get('path_bin') or os.path.dirname(openclaw_path)
        child_env = _child_env([openclaw_bin] + sub['bins'])

        ###########################################################################################
        # Assemble the prompt: prompt file text + "\n" + prompt text

        texts = []
        if prompt_file:
            prompt_file = os.path.abspath(os.path.expanduser(prompt_file))
            if not os.path.isfile(prompt_file):
                return self.cm.error(f'prompt file was not found: {prompt_file}', 1)
            try:
                with open(prompt_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                    texts.append(f.read().strip())
            except Exception as e:
                return self.cm.error(f'cannot read prompt file {prompt_file}: {e}', 1)
        if prompt:
            texts.append(prompt.strip())
        full_prompt = '\n'.join([t for t in texts if t != ''])

        if full_prompt == '' and not interactive:
            interactive = True
            if con:
                print ('')
                print (f'{space}INFO: no prompt was given (--prompt / --prompt_file) - opening the OpenClaw terminal UI')

        # The prompt is the value of --message in both modes (openclaw has no stdin mode), which the OS caps:
        # a long one is written to a file and openclaw is asked to read it first (the terminal UI then goes on
        # as before)
        pr = prompt_via_file(full_prompt, 'openclaw', path=long_prompt_file, prompt_file=prompt_file,
                             con=con, space=space)
        if pr['return'] > 0:
            return pr

        ###########################################################################################
        # Output and statistics files (an interactive session keeps the terminal: nothing to collect)

        if interactive:
            if con and (stats or stats_file or output_file):
                print ('')
                print (f'{space}INFO: --interactive keeps the terminal - the output and the statistics cannot be collected')
            stats, stats_file = False, ''
        elif stats_file:
            stats_file = os.path.abspath(os.path.expanduser(stats_file))
            stats = True

        if interactive or skip_output_file:
            output_file = ''
        else:
            if not output_file:
                output_file = (os.path.splitext(prompt_file)[0] + OUTPUT_FILE_SUFFIX) if prompt_file else DEFAULT_OUTPUT_FILE
            output_file = os.path.abspath(os.path.expanduser(output_file))

        ###########################################################################################
        # The openclaw command line

        extra_flags = [str(u) for u in unparsed] if unparsed else []
        flags = []
        parse_json = False

        if interactive:
            base = argv0 + ['tui'] + ([] if gateway else ['--local'])
        else:
            base = argv0 + ['agent'] + ([] if gateway else ['--local'])
            # "openclaw agent" needs a session target: the agent (and a session id) unless given after "--"
            if not [x for x in extra_flags if x.split('=')[0] in SESSION_FLAGS]:
                flags += ['--agent', agent or 'main'] + (['--session-id', session] if session else [])
            if stats:
                if [x for x in extra_flags if x.split('=')[0] in OUTPUT_FORMAT_FLAGS]:
                    parse_json = True        # the user asked for JSON already
                else:
                    flags += ['--json']
                    parse_json = True

        flags += extra_flags
        cmd = base + flags + (['--message', pr['text']] if full_prompt else [])
        shown = base + flags + (['--message', f'<prompt: {len(full_prompt)} chars>' if not pr['file']
                                 else f'<the request to read {pr["file"]}>'] if full_prompt else [])

        if con:
            print ('')
            print (f'{space}RUN: {" ".join(shown)}')
            if pr['file']:
                print (f'{space}     (prompt: {len(full_prompt)} chars in a file openclaw is asked to read first: {pr["file"]})')
            if interactive:
                print (f'{space}     (terminal UI - openclaw keeps this terminal)')
            if output_file:
                print (f'{space}     (output: {output_file})')
            print ('')

        if dry_run:
            prompt_via_file_done(pr)
            return {'return': 0, 'cmd': shown, 'prompt': full_prompt, 'long_prompt_file': pr['file'], 'output': '',
                    'output_file': '', 'interactive': interactive, 'dry_run': True,
                    'agents': {'found': sub['found'], 'missing': sub['missing'], 'path': child_env.get('PATH', '')}}

        # Provenance: artifacts created through cMeta during the run record how they were made
        # (unless a task that runs openclaw set CMETA_GENERATOR already)
        if not os.environ.get('CMETA_GENERATOR'):
            os.environ['CMETA_GENERATOR'] = json.dumps(_agent_generator(argv0, extra_flags))

        start_time = time.time()

        ###########################################################################################
        # Interactive: hand the terminal over to openclaw

        if interactive:
            try:
                returncode = subprocess.call(cmd, env=child_env)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                prompt_via_file_done(pr)
                return self.cm.error(f'cannot run "{openclaw_path}": {e}', 1)
            prompt_via_file_done(pr)
            duration = time.time() - start_time
            if con:
                print ('')
                if returncode != 0:
                    print (f'{space}INFO: openclaw exited with return code {returncode}')
                print (f'{space}Duration: {duration:.1f} sec')
            return {'return': 0, 'output': '', 'output_file': '', 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                    'cmd': shown, 'returncode': returncode, 'duration': duration, 'interactive': True, 'stats_file': ''}

        ###########################################################################################
        # Headless: one agent turn, output streamed and collected

        try:
            process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1, env=child_env)
        except Exception as e:
            prompt_via_file_done(pr)
            return self.cm.error(f'cannot run "{openclaw_path}": {e}', 1)

        lines = []
        try:
            for line in process.stdout:
                lines.append(line)
                if con and not parse_json:
                    print (line, end='', flush=True)
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            prompt_via_file_done(pr)
            return self.cm.error('interrupted by the user', 1)

        returncode = process.wait()
        prompt_via_file_done(pr)
        duration = time.time() - start_time
        output = ''.join(lines)

        tokens = {}
        if parse_json:
            reply, tokens = self._from_json(output, start_time)
            if reply is not None:
                output = reply if reply.endswith('\n') else reply + '\n'
            if con:
                print (output, end='', flush=True)
            if not tokens and con:
                print ('')
                print (f'{space}WARNING: openclaw reported no token usage for this turn')

        stats_lines = self._format_stats(tokens)
        info = {'task': 'run-openclaw', 'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'openclaw': openclaw_path,
                'prompt_file': prompt_file, 'prompt_size': len(full_prompt), 'extra_flags': flags,
                'duration': round(duration, 1), 'return_code': returncode, 'output_file': output_file}
        info_lines = [f'task: run-openclaw', f'date: {info["date"]}', f'openclaw: {openclaw_path}',
                      f'prompt file: {prompt_file or "(none)"}', f'prompt size: {len(full_prompt)} chars',
                      f'extra flags: {" ".join(flags) if flags else "(none)"}', f'duration: {duration:.1f} sec',
                      f'return code: {returncode}']

        if output_file:
            text = output if skip_output_header else '\n'.join(['# ' + x for x in info_lines + stats_lines] + ['', '']) + output
            if append_output_file and os.path.isfile(output_file):
                with open(output_file, 'a', encoding='utf-8', newline='\n') as f:
                    f.write('\n' + text)
            else:
                r = self.cm.utils.files.write_file(output_file, text, file_format='text', encoding='utf-8')
                if self.cm.catch_error(r): return r
            if con:
                print ('')
                print (f'{space}Output was recorded to "{output_file}"')

        if stats_file:
            if not tokens:
                stats_file = ''
            elif os.path.splitext(stats_file)[1].lower() == '.json':
                r = self.cm.utils.files.write_file(stats_file, dict(info, tokens=tokens), file_format='json', sort_keys=False)
                if self.cm.catch_error(r): return r
            else:
                r = self.cm.utils.files.write_file(stats_file, '\n'.join(info_lines + stats_lines) + '\n',
                                                   file_format='text', encoding='utf-8')
                if self.cm.catch_error(r): return r

        if con:
            for x in ([''] + stats_lines if stats_lines else []):
                print (f'{space}{x}')
            print ('')
            print (f'{space}Duration: {duration:.1f} sec')

        if returncode != 0:
            hint = ''
            if 'No API key found for provider' in output:
                hint = (' - the model\'s provider has no key on this machine: "cx tool run openclaw -- models status" shows '
                        'which are authenticated; --model=claude-cli/<model> runs through the local Claude Code login, and '
                        '"cx tool run openclaw -- models set claude-cli/<model>" makes it the default')
            return self.cm.error(f'openclaw failed with return code {returncode}{hint}', 99)

        result = {'return': 0, 'output': output, 'output_file': output_file, 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                  'cmd': shown, 'returncode': returncode, 'duration': duration, 'interactive': False, 'stats_file': stats_file}
        if tokens:
            result['tokens'] = tokens
        return result


    ############################################################
    def _from_json(self, output, since=0):
        """
        The reply text and the token usage in OpenClaw's "--json" result.

        OpenClaw 2026.6 prints its log lines ("[agent/cli-backend] ...") and then one JSON object:
        the reply in "payloads" (a list of {"text": ...}) and "meta.finalAssistantVisibleText", the
        usage of the turn in "meta.agentMeta.usage" (input, output, cacheRead, cacheWrite). The schema
        of a young, fast-moving CLI is not frozen, so other shapes are still looked for: the reply
        text ("reply", "text", "content", "output", "message") and the usage ("usage"/"tokens" with
        input/output/prompt/completion counters, "cost") anywhere in the result. Anything
        unrecognized leaves the raw output in place.
        """
        match = re.search(r'(?m)^\{', output)
        try:
            data = json.JSONDecoder().raw_decode(output[match.start():])[0] if match else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return None, {}

        reply = None
        meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
        payloads = data.get('payloads')
        if isinstance(payloads, list):
            texts = [p['text'] for p in payloads if isinstance(p, dict) and isinstance(p.get('text'), str) and p['text'].strip()]
            if texts:
                reply = '\n\n'.join(texts)
        if reply is None and isinstance(meta.get('finalAssistantVisibleText'), str) and meta['finalAssistantVisibleText'].strip():
            reply = meta['finalAssistantVisibleText']
        for key in ('reply', 'text', 'output', 'content', 'message', 'result'):
            if reply:
                break
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                reply = v
                break
            if isinstance(v, dict):
                for k2 in ('text', 'content', 'reply'):
                    if isinstance(v.get(k2), str) and v[k2].strip():
                        reply = v[k2]
                        break
            if reply:
                break

        tokens = {}
        agent_meta = meta.get('agentMeta') if isinstance(meta.get('agentMeta'), dict) else {}
        binding = agent_meta.get('cliSessionBinding') if isinstance(agent_meta.get('cliSessionBinding'), dict) else {}
        if agent_meta.get('provider') == 'claude-cli' and binding.get('sessionId'):
            # the claude-cli provider runs Claude Code, whose own session has the real counts of every model call
            # of the turn; OpenClaw's "usage" is that of the last call only, with too few output tokens
            tokens = _claude_session_usage(binding['sessionId'], since)
            if tokens:
                return reply, tokens

        def walk(d, depth=0):
            if depth > 6 or not isinstance(d, dict):
                return
            for key in ('usage', 'tokens'):
                u = d.get(key)
                if isinstance(u, dict):
                    for src, dst in (('input', 'input'), ('input_tokens', 'input'), ('prompt_tokens', 'input'),
                                     ('output', 'output'), ('output_tokens', 'output'), ('completion_tokens', 'output'),
                                     ('cache_read', 'cache_read'), ('cacheRead', 'cache_read'),
                                     ('cache_write', 'cache_write'), ('cacheWrite', 'cache_write'),
                                     ('total', 'total'), ('total_tokens', 'total')):
                        if isinstance(u.get(src), (int, float)):
                            tokens[dst] = tokens.get(dst, 0) + u[src]
            for key in ('cost', 'costUsd', 'cost_usd'):
                if isinstance(d.get(key), (int, float)):
                    tokens['cost_usd'] = tokens.get('cost_usd', 0) + d[key]
            for v in d.values():
                if isinstance(v, dict):
                    walk(v, depth + 1)
                elif isinstance(v, list):
                    for x in v:
                        walk(x, depth + 1)

        usage = agent_meta.get('usage')
        if isinstance(usage, dict):
            walk({'usage': usage})          # the turn's usage; "lastCallUsage" beside it is a part of it
            cost = usage.get('cost')
            if isinstance(cost, dict) and isinstance(cost.get('total'), (int, float)) and cost['total'] > 0:
                tokens['cost_usd'] = cost['total']
        else:
            walk(data)
        return reply, _sums(tokens)


    ############################################################
    def _format_stats(self, tokens):
        """The token/cost statistics of one turn as text lines (empty when there are none)."""
        if not tokens:
            return []
        lines = ['Statistics for this prompt:',
                 f'  Tokens sent:     {tokens.get("sent", tokens.get("input", 0))}'
                 f' (new: {tokens.get("input", 0)}, cache write: {tokens.get("cache_write", 0)},'
                 f' cache read: {tokens.get("cache_read", 0)})',
                 f'  Tokens received: {tokens.get("output", 0)}',
                 f'  Tokens total:    {tokens.get("total", 0)}']
        if tokens.get('from'):
            lines.append(f'  Counted from:    {tokens["from"]}')
        if 'cost_usd' in tokens:
            lines.append(f'  Cost:            {tokens["cost_usd"]:.4f} USD')
        return lines
