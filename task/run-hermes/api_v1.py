"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-hermes - the Hermes Agent (https://hermes-agent.nousresearch.com) sibling of the "run-claude", "run-codex",
"run-opencode", "run-openclaw", "run-agy" and "run-gemini" tasks of cmeta-aops, with the same flags.

Hermes Agent is Nous Research's open-source agent (MIT): a Python CLI with a learning loop (it writes skills from
experience), a persistent memory, skills in the agentskills.io format and many inference providers - Nous Portal,
Anthropic (a Claude Code login on Claude Max, or an API key), OpenAI Codex, OpenRouter, Copilot, and any
OpenAI-compatible endpoint (llama.cpp, Ollama, vLLM, LM Studio).

What is specific to hermes (v0.21.5 = release 2026.9.24, checked with "hermes chat --help" and probes on 2026-10-07):
- headless mode is "hermes chat -q <prompt>": on a non-TTY stdin, with "--oneshot" or with "-Q" it answers and exits;
  "-Q" prints only the final response and the session info; "--format stream-json" prints one JSON event per line
  (--stats) and implies quiet. "--query-file -" reads the prompt from stdin verbatim (nothing shell-interpreted), so a
  prompt too long for a command line - or any prompt on Windows, where "hermes" is a .cmd shim - goes that way;
- "--yolo" bypasses the approval prompts of dangerous commands (--yes); without it hermes decides with its "smart"
  approval mode (an auxiliary model judges a flagged command);
- "-m <provider>/<model>" and "--reasoning none|minimal|low|medium|high|xhigh|max|ultra" pin the model and the
  reasoning level for the run; "--provider <name>" forces a provider; there is no plugin switch, so --reproducible only
  warns when nothing is pinned;
- "--resume <session id>" (or "latest") and "--continue [name]" resume a session; "--in <dir>" scopes them to a folder;
  the ids live in HERMES_HOME/state.db (SQLite: "hermes sessions list", "hermes sessions export --format jsonl");
- the interactive form is "hermes chat -q <prompt>" on a terminal (the prompt is submitted as the first turn and the
  session stays), or plain "hermes chat"; a long prompt (over MAX_PROMPT_ARG_CHARS of the task category API) is written
  to a file and hermes is asked to read it first;
- a headless run without a provider exits 1 with "Hermes is not connected to any AI provider yet": the connection is
  made once by hand ("hermes model" picks a provider and signs in; "hermes auth add <provider>"; a key in
  HERMES_HOME/.env; or a local server as the "custom" provider) - this task repeats that hint;
- hermes reads AGENTS.md (or .hermes.md, CLAUDE.md, .cursorrules) from the working directory by itself, and its own
  memory (memories/MEMORY.md, USER.md) and skills (skills/) from HERMES_HOME; "--ignore-rules" turns that off;
- hermes does not update itself on launch ("hermes update" does); its installer brought its own Python and uv.

Not checked yet: the token counters of the stream-json events with a paid provider (the probe used a local Ollama
model through the "custom" provider), and the Windows .cmd shim with an interactive session.
"""

import json
import os
import re
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, MAX_PROMPT_ARG_CHARS, prompt_via_file, prompt_via_file_done

OUTPUT_FILE_SUFFIX = '-output.txt'
DEFAULT_OUTPUT_FILE = 'run-hermes-output.txt'

YES_FLAGS = ['--yolo']
PERMISSION_FLAGS = ['--yolo']

STATS_FLAGS = ['--format', 'stream-json']
OUTPUT_FORMAT_FLAGS = ['--format']
QUIET_FLAGS = ['-Q']
ONESHOT_FLAGS = ['--oneshot']

MODEL_FLAGS = ['--model', '-m']
EFFORT_FLAGS = ['--reasoning']

# These make sense in headless mode only; an interactive session is a terminal
RUN_ONLY_FLAGS = ['--format', '--oneshot', '--query-file', '-Q', '--quiet', '--max-turns', '--run-budget', '--source', '--image']

# The prompt on stdin, read verbatim ("--query-file -"): above MAX_PROMPT_ARG_CHARS, and always behind a .cmd shim
STDIN_FLAGS = ['--query-file', '-']
# What a Windows .cmd shim mangles on its way to the Python behind it: such a prompt never goes as an argument
CMD_UNSAFE = set('"%!^&|<>\r\n')

NOT_CONNECTED_HINT = ('hermes is not connected to a provider: connect it once by hand - "cx tool run hermes -- model" (the picker: '
                      'Nous Portal has a free tier; Anthropic needs a Claude Code login on Claude Max or ANTHROPIC_API_KEY; OpenAI Codex, '
                      'OpenRouter, ...), "cx tool run hermes -- auth add <provider>", "cx tool run hermes -- config set OPENROUTER_API_KEY <key>", '
                      'or a local server: "config set model.provider custom", "model.base_url http://localhost:8080/v1", "model.default <model>"')

# a hermes session id is "<yyyymmdd>_<hhmmss>_<6 hex>" (20261007_164201_45c8de); a UUID is taken too, should it change
SESSION_ID_RE = re.compile(r'\b(\d{8}_\d{6}_[0-9a-f]{6}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b', re.I)
VERSION_RE = re.compile(r'\((\d{4}\.\d{1,2}\.\d{1,2})\)')


def _flag_value(flags, names):
    """The value of "<name> value" or "<name>=value" in a command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] in names:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def hermes_version(hermes_path, env=None):
    """The release of a hermes ("2026.9.24": the bracketed part of "Hermes Agent v0.21.5+8859.g0e21933 (2026.9.24) ..."),
    else its own number, else ''."""
    try:
        out = subprocess.run([hermes_path or 'hermes', '--version'], capture_output=True, text=True, timeout=60, shell=False, env=env).stdout
    except Exception:
        return ''
    m = VERSION_RE.search(out or '')
    if m:
        return m.group(1)
    m = re.search(r'\bv(\d+\.\d+\.\d+)', out or '')
    return m.group(1) if m else ''


def _agent_generator(hermes_path, flags, env):
    """The CMETA_GENERATOR record of a hermes session: the agent and its release, and the model it was started with."""
    from task_c36be4b9314a45e0.api.ctask import GENERATOR_VIA_KEY, generator_via
    rec = {'method': 'agent', 'agent': 'Hermes Agent', GENERATOR_VIA_KEY: generator_via()}
    version = hermes_version(hermes_path, env)
    if version:
        rec['agent'] = 'Hermes Agent ' + version
    model = _flag_value(flags, MODEL_FLAGS)
    if model:
        rec['model'] = model
    effort = _flag_value(flags, EFFORT_FLAGS)
    if effort:
        rec['effort'] = effort
    return rec


def session_id_in_text(text):
    """The session id hermes prints at the end of a quiet run ("Session: <id>", in whatever words), or ''."""
    for line in reversed((text or '').splitlines()):
        if 'session' in line.lower():
            m = SESSION_ID_RE.search(line)
            if m:
                return m.group(1)
    return ''


class CTask(InitCTask):
    """run-hermes: run Hermes Agent on an assembled prompt, headless or interactive, and record the output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            long_prompt_file: str = '',     # where a prompt too long for the command line is written for hermes to read (interactive)
            interactive: bool = False,      # seed an interactive hermes session with the prompt and stay in it
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # bypass the approval prompts of dangerous commands (--yolo)
            reproducible: bool = False,     # warn when no model / reasoning level is pinned after "--"
            stats: bool = False,            # print token usage at the end (JSON event stream, turned back into text)
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for hermes (everything after "--")
    ):
        """Assemble a prompt and run Hermes Agent on it (hermes chat -q, one shot), or open an interactive session."""
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''
        _global = ctx['tasks']['global']

        hermes_path = _global.get('hermes', {}).get('path', '')
        if not hermes_path:
            return self.cm.error('the "hermes" tool was not set up (no path in the global context)', 1)
        cmd_shim = hermes_path.lower().endswith(('.cmd', '.bat'))

        interactive = interactive or i

        # ---- the environment of the run: plain text for the records
        env = dict(os.environ)
        env.setdefault('NO_COLOR', '1')

        # ---- the prompt: prompt file text + "\n" + prompt text
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
                print('')
                print(f'{space}INFO: no prompt was given (--prompt / --prompt_file) - opening an interactive hermes session')

        # ---- the output and statistics files
        if interactive:
            if con and (stats or stats_file or output_file):
                print('')
                print(f'{space}INFO: --interactive keeps the terminal - the output and the statistics of the session cannot be collected')
            stats = False
            stats_file = ''
        elif stats_file:
            stats_file = os.path.abspath(os.path.expanduser(stats_file))
            stats = True

        if interactive or skip_output_file:
            output_file = ''
        else:
            if not output_file:
                output_file = os.path.splitext(prompt_file)[0] + OUTPUT_FILE_SUFFIX if prompt_file else DEFAULT_OUTPUT_FILE
            output_file = os.path.abspath(os.path.expanduser(output_file))

        # ---- the command line
        base_cmd = [hermes_path, 'chat']
        flags = []
        extra_flags = [str(u) for u in unparsed] if unparsed else []
        extra_keys = [x.split('=')[0] for x in extra_flags]

        if yes:
            user_permission_flags = [x for x in extra_flags if x.split('=')[0] in PERMISSION_FLAGS]
            if user_permission_flags:
                if con:
                    print('')
                    print(f'{space}INFO: --yes is ignored - permission flags were passed after "--": {" ".join(user_permission_flags)}')
            else:
                flags += YES_FLAGS

        if reproducible and con:
            missing = [x for x in ('--model', '--reasoning') if x not in extra_keys and not (x == '--model' and '-m' in extra_keys)]
            if missing:
                print('')
                print(f'{space}WARNING: --reproducible: {" and ".join(missing)} not pinned - the defaults of hermes are its configuration')
                print(f'{space}         pass them after "--", i.e. --model <provider>/<model> --reasoning medium')

        user_format = _flag_value(extra_flags, OUTPUT_FORMAT_FLAGS)
        parse_stream = False
        if stats:
            if user_format:
                if con:
                    print('')
                    print(f'{space}INFO: --stats is ignored - an output format was passed after "--": --format {user_format}')
                parse_stream = user_format == 'stream-json'
            else:
                flags += STATS_FLAGS
                parse_stream = True
        elif user_format == 'stream-json':
            parse_stream = True

        if not interactive:
            # quiet unless the stream (which implies it) or the user's own -v / -Q; one shot in every case
            if not parse_stream and not any(k in extra_keys for k in ('-Q', '--quiet', '-v', '--verbose')):
                flags += QUIET_FLAGS
            if '--oneshot' not in extra_keys:
                flags += ONESHOT_FLAGS

        flags += extra_flags

        # a headless prompt goes through stdin when it is too long for a command line, and always behind a .cmd shim
        # (which mangles quotes and percent signs); an interactive session cannot do that: such a prompt is written to a
        # file and hermes is asked to read it first (the session then goes on as before)
        prompt_on_stdin = (not interactive) and (len(full_prompt) > MAX_PROMPT_ARG_CHARS or cmd_shim)
        pr = prompt_via_file(full_prompt, 'hermes', when=not prompt_on_stdin, path=long_prompt_file, prompt_file=prompt_file,
                             force=bool(interactive and cmd_shim and any(c in CMD_UNSAFE for c in full_prompt)),
                             why='the hermes command on Windows is a .cmd shim that mangles such characters' if cmd_shim else '',
                             con=con, space=space)
        if pr['return'] > 0:
            return pr

        if interactive:
            dropped = [x for x in flags if x.split('=')[0] in RUN_ONLY_FLAGS]
            if dropped:
                flags = [x for x in flags if x.split('=')[0] not in RUN_ONLY_FLAGS]
                if con:
                    print('')
                    print(f'{space}INFO: hermes takes these in headless mode only, so they are dropped from the session: {" ".join(dropped)}')
            cmd = base_cmd + flags + (['-q', pr['text']] if full_prompt else [])
        elif prompt_on_stdin:
            cmd = base_cmd + flags + STDIN_FLAGS
        else:
            cmd = base_cmd + flags + ['-q', pr['text']]

        if con:
            print('')
            shown = ' '.join(base_cmd + flags)
            if interactive:
                shown += ' -q <prompt>' if full_prompt else ''
            elif prompt_on_stdin:
                shown += ' ' + ' '.join(STDIN_FLAGS) + '  < <prompt>'
            else:
                shown += ' -q <prompt>'
            print(f'{space}RUN: {shown}')
            if full_prompt:
                where = f'in a file hermes is asked to read first: {pr["file"]}' if pr['file'] \
                    else ('through stdin' if prompt_on_stdin else 'as an argument')
                print(f'{space}     (prompt: {len(full_prompt)} chars {where})')
            if interactive:
                print(f'{space}     (interactive session - hermes keeps this terminal)')
            if output_file:
                print(f'{space}     (output: {output_file})')
            print('')

        if not os.environ.get('CMETA_GENERATOR'):
            os.environ['CMETA_GENERATOR'] = json.dumps(_agent_generator(hermes_path, extra_flags, env))

        start_time = time.time()

        # ---- interactive: hand the terminal over
        if interactive:
            try:
                returncode = subprocess.call(cmd, env=env)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                prompt_via_file_done(pr)
                return self.cm.error(f'cannot run "{hermes_path}": {e}', 1)
            prompt_via_file_done(pr)
            duration = time.time() - start_time
            if con:
                print('')
                if returncode != 0:
                    print(f'{space}INFO: hermes exited with return code {returncode}')
                print(f'{space}Duration: {duration:.1f} sec')
            return {'return': 0, 'output': '', 'output_file': '', 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                    'returncode': returncode, 'duration': duration, 'interactive': True, 'stats_file': ''}

        # ---- headless: run and collect everything
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE if prompt_on_stdin else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1, env=env)
        except Exception as e:
            prompt_via_file_done(pr)
            return self.cm.error(f'cannot run "{hermes_path}": {e}', 1)

        if prompt_on_stdin:
            try:
                process.stdin.write(full_prompt)
                process.stdin.close()
            except Exception as e:
                process.kill()
                process.wait()
                return self.cm.error(f'cannot send the prompt to hermes through stdin: {e}', 1)

        lines = []
        run_stats = {}
        state = {'streamed': 0, 'unknown': 0}
        try:
            for line in process.stdout:
                for text in (self._parse_stream_line(line, run_stats, state) if parse_stream else [line]):
                    lines.append(text)
                    if con:
                        print(text, end='', flush=True)
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            prompt_via_file_done(pr)
            return self.cm.error('interrupted by the user', 1)
        returncode = process.wait()
        prompt_via_file_done(pr)
        duration = time.time() - start_time
        output = ''.join(lines)

        if not run_stats.get('session_id'):
            sid = session_id_in_text(output)
            if sid:
                run_stats['session_id'] = sid

        stats_lines = self._format_stats(run_stats)
        if stats and not run_stats.get('tokens') and con:
            print('')
            print(f'{space}WARNING: hermes did not report any token counters for this run')
        if verbose and state['unknown'] and con:
            print(f'{space}INFO: {state["unknown"]} event(s) of the stream had an unknown shape and were not shown')

        run_info = {'task': 'run-hermes', 'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'hermes': hermes_path,
                    'prompt_file': prompt_file, 'prompt_size': len(full_prompt), 'extra_flags': flags,
                    'duration': round(duration, 1), 'return_code': returncode, 'output_file': output_file}
        info_lines = [f'task: {run_info["task"]}', f'date: {run_info["date"]}', f'hermes: {hermes_path}',
                      f'prompt file: {prompt_file if prompt_file else "(none)"}', f'prompt size: {len(full_prompt)} chars',
                      f'extra flags: {" ".join(flags) if flags else "(none)"}', f'duration: {duration:.1f} sec',
                      f'return code: {returncode}']

        if output_file:
            text = output if skip_output_header else '\n'.join(['# ' + x for x in info_lines + stats_lines] + ['', '']) + output
            if append_output_file and os.path.isfile(output_file):
                try:
                    with open(output_file, 'a', encoding='utf-8', newline='\n') as f:
                        f.write('\n' + text)
                except Exception as e:
                    return self.cm.error(f'cannot append to the output file {output_file}: {e}', 1)
            else:
                r = self.cm.utils.files.write_file(output_file, text, file_format='text', encoding='utf-8')
                if self.cm.catch_error(r):
                    return r
            if con:
                print('')
                print(f'{space}Output was recorded to "{output_file}"')

        if stats_file:
            if not run_stats:
                if con:
                    print('')
                    print(f'{space}WARNING: no statistics to record to "{stats_file}"')
                stats_file = ''
            else:
                if os.path.splitext(stats_file)[1].lower() == '.json':
                    data = dict(run_info)
                    data['tokens'] = self._get_tokens(run_stats)
                    data['hermes_result'] = run_stats
                    r = self.cm.utils.files.write_file(stats_file, data, file_format='json', sort_keys=False)
                else:
                    r = self.cm.utils.files.write_file(stats_file, '\n'.join(info_lines + stats_lines) + '\n', file_format='text', encoding='utf-8')
                if self.cm.catch_error(r):
                    return r
                if con:
                    print('')
                    print(f'{space}Statistics were recorded to "{stats_file}"')

        if con and stats and stats_lines:
            print('')
            for x in stats_lines:
                print(f'{space}{x}')
        if con:
            print('')
            print(f'{space}Duration: {duration:.1f} sec')

        if returncode != 0 or run_stats.get('error'):
            low = output.lower()
            hint = ''
            if 'not connected to any ai provider' in low or 'no api key' in low or ('hermes model' in low and 'provider' in low):
                hint = ' (' + NOT_CONNECTED_HINT + ')'
            elif 'context window' in low and 'minimum' in low:
                hint = (' (hermes wants a model with a context window of at least 64K tokens: a local server must serve one - '
                        'llama.cpp -c 64000, OLLAMA_CONTEXT_LENGTH=65536 for Ollama - and "cx tool run hermes -- config set '
                        'model.context_length 65536" tells hermes so)')
            elif re.search(r"model\b.{0,80}?\bnot found|unknown model|no such model|model\b.{0,80}?\bdoes not exist", low):
                hint = ' (the model is not one of the provider: "cx tool run hermes -- model" lists them; the name is <provider>/<model>)'
            elif 'rate limit' in low or 'quota' in low or 'insufficient' in low and 'credit' in low:
                hint = ' (the provider rate-limited the request or the credits are used up)'
            elif 'unrecognized arguments' in low:
                hint = ' (an unknown flag was passed after "--": "hermes chat --help" lists them)'
            what = f'return code {returncode}' if returncode != 0 else f'error {run_stats.get("error")}'
            return self.cm.error(f'hermes failed with {what}{hint}', 99)

        result = {'return': 0, 'output': output, 'output_file': output_file, 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                  'returncode': returncode, 'duration': duration, 'interactive': False}
        if run_stats:
            result['stats'] = run_stats
            result['tokens'] = self._get_tokens(run_stats)
            if run_stats.get('session_id'):
                result['conversation_id'] = run_stats['session_id']
        result['stats_file'] = stats_file
        return result

    # ------------------------------------------------------------------ the JSON event stream
    def _parse_stream_line(self, line, run_stats, state):
        """One "--format stream-json" line -> readable text; the statistics are collected on the way. The events are
        read by their shape rather than by a fixed schema: text deltas are streamed, a final text is shown when nothing
        was streamed, tool calls are summarised, usage counters and the session id are kept, errors are shown. A line
        that is not JSON is a log line of the CLI and passes through."""
        raw = line.strip()
        if raw == '':
            return []
        try:
            event = json.loads(raw)
        except Exception:
            return [raw + '\n']
        if not isinstance(event, dict):
            return [str(event).rstrip() + '\n']
        kind = str(event.get('type') or event.get('event') or event.get('kind') or '').lower()
        subtype = str(event.get('subtype') or '').lower()
        payload = event.get('data') if isinstance(event.get('data'), dict) else event
        # hermes v0.21.5 (seen 2026-10-07): {"type": "system", "subtype": "init", "model", "session_id", "timestamp"} first,
        # {"type": "result", "session_id", "exit_code", "text", "tokens": {input, output, total, cache_read, cache_write},
        # "duration_ms", "error"?, "timestamp"} last; the events in between are read by their shape
        for holder in (event, payload):
            for key in ('session_id', 'sessionId', 'session', 'conversation_id'):
                v = holder.get(key)
                if isinstance(v, str) and v and SESSION_ID_RE.search(v):
                    run_stats['session_id'] = SESSION_ID_RE.search(v).group(1)
            for key in ('model', 'model_name', 'modelName'):
                if isinstance(holder.get(key), str) and holder[key]:
                    run_stats.setdefault('model', holder[key])
            if isinstance(holder.get('usage'), dict):
                self._collect_usage(holder['usage'], run_stats)
            if isinstance(holder.get('tokens'), dict):
                self._collect_usage(holder['tokens'], run_stats)
            for key in ('cost', 'cost_usd', 'total_cost', 'total_cost_usd'):
                if isinstance(holder.get(key), (int, float)):
                    run_stats['cost_usd'] = holder[key]
            if isinstance(holder.get('duration_ms'), (int, float)):
                run_stats['duration_s'] = holder['duration_ms'] / 1000.0
            if isinstance(holder.get('exit_code'), int):
                run_stats['exit_code'] = holder['exit_code']
        if kind == 'system' or subtype == 'init':
            return []
        if kind in ('error',) or (isinstance(payload.get('error'), (str, dict)) and payload.get('error')):
            err = payload.get('error') or event.get('message') or event
            run_stats['error'] = err if isinstance(err, str) else json.dumps(err)[:300]
            out = [self._shorten('[error] ' + run_stats['error']) + '\n']
            final = self._text_of(payload, ('text', 'response'))
            if final and state['streamed'] == 0:
                out.insert(0, final.rstrip() + '\n')
            return out
        # a tool call
        call = payload.get('tool_call') or payload.get('tool') or (payload if kind.startswith('tool') else None)
        if isinstance(call, dict) and (call.get('name') or call.get('tool_name') or call.get('function')):
            name = call.get('name') or call.get('tool_name') or (call.get('function') or {}).get('name') or '?'
            args = call.get('arguments') or call.get('args') or call.get('input') or call.get('parameters') or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {'text': args}
            hint = next((str(args[k]) for k in ('command', 'cmd', 'file_path', 'path', 'pattern', 'query', 'url', 'description', 'prompt')
                         if isinstance(args, dict) and args.get(k)), '')
            if 'result' in kind or 'output' in kind:
                return []
            return [self._shorten(f'[tool: {name}] {hint}') + '\n']
        # text: a delta streams ({"type": "text", "text": "hello"} in v0.21.5, one event per chunk), a final text shows
        # when nothing streamed
        if kind in ('text', 'delta', 'text_delta', 'content_delta', 'chunk', 'assistant_delta', 'message_delta'):
            delta = self._text_of(payload, ('text', 'delta', 'content', 'chunk'))
            if delta:
                state['streamed'] += len(delta)
                return [delta]
            return []
        delta = self._text_of(payload, ('delta', 'text_delta', 'content_delta', 'chunk'))
        if delta and ('delta' in kind or 'chunk' in kind or not kind or kind in ('content', 'assistant', 'message')):
            state['streamed'] += len(delta)
            return [delta]
        final = self._text_of(payload, ('response', 'final_response', 'final', 'text', 'content', 'message', 'answer', 'output'))
        if final and (kind in ('final', 'result', 'response', 'done', 'complete', 'completed', 'end', 'assistant', 'message', 'text', 'final_response', 'turn_end', 'turn.completed')
                      or 'final' in kind or 'result' in kind or 'done' in kind or 'complete' in kind):
            if state['streamed'] == 0:
                return [final.rstrip() + '\n']
            return ['\n']
        if kind in ('init', 'start', 'session', 'session_start', 'thinking', 'reasoning', 'status', 'heartbeat', 'turn_start', 'turn.started', 'user', 'system'):
            return []
        state['unknown'] += 1
        return []

    @staticmethod
    def _text_of(holder, keys):
        if not isinstance(holder, dict):
            return ''
        for key in keys:
            v = holder.get(key)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict):
                for k2 in ('text', 'content'):
                    if isinstance(v.get(k2), str) and v[k2]:
                        return v[k2]
            if isinstance(v, list):
                parts = [p.get('text') for p in v if isinstance(p, dict) and isinstance(p.get('text'), str)]
                if parts:
                    return ''.join(parts)
        return ''

    @staticmethod
    def _shorten(text, length=120):
        text = ' '.join(str(text).split())
        return text[:length] + ' ...' if len(text) > length else text

    @staticmethod
    def _collect_usage(usage, run_stats):
        """Usage counters in either the OpenAI (prompt_tokens / completion_tokens) or the Anthropic (input_tokens /
        output_tokens, cache_read_input_tokens) spelling; the last report of a key wins (hermes reports totals)."""
        totals = run_stats.setdefault('tokens', {})

        def take(key, *names):
            for n in names:
                if isinstance(usage.get(n), (int, float)):
                    totals[key] = usage[n]
                    return

        take('input', 'input_tokens', 'prompt_tokens', 'input')
        take('output', 'output_tokens', 'completion_tokens', 'output')
        take('cache_read', 'cache_read_input_tokens', 'cache_read_tokens', 'cached_tokens', 'cache_read')
        take('reasoning', 'reasoning_tokens', 'thinking_tokens', 'reasoning')
        take('total_reported', 'total_tokens', 'total')
        details = usage.get('completion_tokens_details') or usage.get('output_tokens_details')
        if isinstance(details, dict) and isinstance(details.get('reasoning_tokens'), (int, float)):
            totals['reasoning'] = details['reasoning_tokens']
        details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details')
        if isinstance(details, dict) and isinstance(details.get('cached_tokens'), (int, float)):
            totals['cache_read'] = details['cached_tokens']

    @staticmethod
    def _get_tokens(run_stats):
        c = run_stats.get('tokens') or {}
        tokens = {'input': c.get('input', 0) or 0, 'cache_read': c.get('cache_read', 0) or 0, 'output': c.get('output', 0) or 0,
                  'reasoning': c.get('reasoning', 0) or 0, 'tool': 0}
        tokens['sent'] = tokens['input']
        tokens['total'] = c.get('total_reported') or (tokens['input'] + tokens['output'] + tokens['reasoning'])
        tokens['cost_usd'] = run_stats.get('cost_usd', 0) or 0
        return tokens

    def _format_stats(self, run_stats):
        lines = []
        if run_stats.get('tokens'):
            t = self._get_tokens(run_stats)
            lines += ['Statistics for this prompt:',
                      f'  Tokens sent:     {t["sent"]} (cache read: {t["cache_read"]})',
                      f'  Tokens received: {t["output"]} (reasoning: {t["reasoning"]})',
                      f'  Tokens total:    {t["total"]}']
            if t['cost_usd']:
                lines.append(f'  Cost:            ${t["cost_usd"]:.4f}')
            if run_stats.get('model'):
                lines.append(f'  Model:           {run_stats["model"]}')
        if run_stats.get('duration_s') is not None and lines:
            lines.append(f'  Agent time:      {run_stats["duration_s"]:.1f} sec')
        if run_stats.get('session_id'):
            if not lines:
                lines.append('Statistics for this prompt:')
            lines.append(f'  Session:         {run_stats["session_id"]} (hermes chat --resume <id> continues it)')
        return lines
