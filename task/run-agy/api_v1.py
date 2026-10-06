"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-agy - the Antigravity CLI (https://antigravity.google/docs/cli) sibling of the "run-claude", "run-codex" and
"run-opencode" tasks of cmeta-aops, with the same flags.

Antigravity CLI ("agy") is Google's terminal coding agent: on 2026-06-18 Gemini CLI stopped serving personal Google
accounts (the free tier, Google AI Pro and Google AI Ultra) and Google pointed them at agy; Gemini CLI still serves
Gemini Code Assist Standard/Enterprise licences and paid API keys.

What is specific to agy (1.2.16, checked with "agy --help" and probes on 2026-10-03):
- headless mode is "agy --print=<prompt>" ("-p"): the prompt is the VALUE of the flag (a bare "-p" swallows the next
  flag as its prompt, agy says so itself), so it is passed as one "--print=<text>" argument; a very long prompt goes
  through stdin instead: "--print= --input-format stream-json --output-format stream-json" and one NDJSON message
  {"event": "user", "message": {"content": <prompt>}} (the multi-turn protocol of the headless docs);
- "--dangerously-skip-permissions" auto-approves every tool call (--yes); without it a headless agy soft-denies the
  tools that need an approval, unless the settings allow them;
- "--output-format stream-json" gives one JSON event per line (--stats): "init", "step_update" (text deltas) and
  "result", the last one with status, conversation_id, duration_seconds, num_turns and usage{input_tokens,
  output_tokens, thinking_tokens, cache_read_tokens, total_tokens}; "--output-format json" is the same envelope once,
  at the end. The exit code is 0 only for status SUCCESS;
- "--model <slug>" and "--effort low|medium|high|xhigh|max" pin the model; there is no extension switch
  (plugins are enabled in the settings), so --reproducible only warns when nothing is pinned;
- "--add-dir <folder>" (repeatable) mounts more folders into the workspace; "--continue" / "--conversation <id>" resume;
- the interactive form is "agy --prompt-interactive=<prompt>" ("-i"; run it, then stay), or plain "agy"; a long prompt
  (over MAX_PROMPT_ARG_CHARS of the task category API, 30000 characters - or, headless, one with an output format other
  than stream-json) is written to a file and agy is asked to read it first; the session then goes on as before;
- a headless run without a stored login prints the login URL, waits 60 s for the code and exits 1 with a JSON error
  ("authentication failed or timed out"); the login is done once by hand ("agy", Login with Google) and kept in the
  OS keyring; GEMINI_API_KEY + {"modelProvider": "gemini"} in ~/.gemini/antigravity-cli/settings.json is the other way;
- agy keeps its state (conversations, logs, settings) in ~/.gemini/antigravity-cli/ and ignores GEMINI_CLI_HOME
  (a HOME / USERPROFILE override is followed); it has no persistent memory, only conversations;
- the binary updates itself in place unless AGY_CLI_DISABLE_AUTO_UPDATE=true: this task sets it for the run.

Not checked yet: whether a headless agy wants the folder to be a trusted workspace, the stdin NDJSON path, and
whether "input_tokens" includes the cached part.
"""

import json
import os
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, MAX_PROMPT_ARG_CHARS, prompt_via_file, prompt_via_file_done

OUTPUT_FILE_SUFFIX = '-output.txt'
DEFAULT_OUTPUT_FILE = 'run-agy-output.txt'

YES_FLAGS = ['--dangerously-skip-permissions']
PERMISSION_FLAGS = ['--dangerously-skip-permissions', '--mode', '--sandbox']

STATS_FLAGS = ['--output-format', 'stream-json']
OUTPUT_FORMAT_FLAGS = ['--output-format']

MODEL_FLAGS = ['--model']
EFFORT_FLAGS = ['--effort']

# These make sense in headless mode only; an interactive session is text
RUN_ONLY_FLAGS = ['--output-format', '--input-format', '--json-schema', '--print-timeout', '--disable-slash-commands']

# Above MAX_PROMPT_ARG_CHARS (the task category API: the OS caps a command line; Windows at 32 K characters) a
# headless prompt goes through stdin with these flags; an interactive one is written to a file agy is asked to read
STDIN_FLAGS = ['--print=', '--input-format', 'stream-json']

NO_AUTO_UPDATE_ENV = 'AGY_CLI_DISABLE_AUTO_UPDATE'

SIGN_IN_HINT = ('agy is not signed in: run "agy" once by hand and sign in with Google (a personal Google account, with '
                'or without Google AI Pro/Ultra, or a Gemini Enterprise licence), or set GEMINI_API_KEY with '
                '{"modelProvider": "gemini"} in ~/.gemini/antigravity-cli/settings.json')


def _flag_value(flags, names):
    """The value of "<name> value" or "<name>=value" in a command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] in names:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def _agent_generator(agy_path, flags, env):
    """The CMETA_GENERATOR record of an agy session: the agent and its version, and the model it was started with."""
    rec = {'method': 'agent', 'agent': 'Antigravity CLI'}
    try:
        out = subprocess.run([agy_path or 'agy', '--version'], capture_output=True, text=True, timeout=60, shell=False, env=env).stdout.strip()
        version = next((x for x in out.split() if x[:1].isdigit()), '')
        if version:
            rec['agent'] = 'Antigravity CLI ' + version
    except Exception:
        pass
    model = _flag_value(flags, MODEL_FLAGS)
    if model:
        rec['model'] = model
    effort = _flag_value(flags, EFFORT_FLAGS)
    if effort:
        rec['effort'] = effort
    return rec


class CTask(InitCTask):
    """run-agy: run Google's Antigravity CLI on an assembled prompt, headless or interactive, and record the output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            long_prompt_file: str = '',     # where a prompt too long for the command line is written for agy to read
            interactive: bool = False,      # run the prompt, then stay in the interactive agy session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # auto-approve every tool call (--dangerously-skip-permissions)
            reproducible: bool = False,     # warn when no model / effort is pinned after "--" (agy has no extension switch)
            stats: bool = False,            # print token usage at the end (JSON event stream, turned back into text)
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for agy (everything after "--")
    ):
        """Assemble a prompt and run Antigravity CLI on it (agy --print), or open an interactive session (agy [-i])."""
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''
        _global = ctx['tasks']['global']

        agy_path = _global.get('agy', {}).get('path', '')
        if not agy_path:
            return self.cm.error('the "agy" tool was not set up (no path in the global context)', 1)

        interactive = interactive or i

        # ---- the environment of the run: the binary must not update itself under cMeta's feet
        env = dict(os.environ)
        env.setdefault(NO_AUTO_UPDATE_ENV, 'true')

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
                print(f'{space}INFO: no prompt was given (--prompt / --prompt_file) - opening an interactive agy session')

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
        base_cmd = [agy_path]
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
            missing = [x for x in ('--model', '--effort') if x not in extra_keys]
            if missing:
                print('')
                print(f'{space}WARNING: --reproducible: {" and ".join(missing)} not pinned - the defaults of agy change between releases')
                print(f'{space}         pass them after "--", i.e. --model <slug> --effort medium ("agy models" lists the slugs)')

        user_format = _flag_value(extra_flags, OUTPUT_FORMAT_FLAGS)
        parse_stream = False
        if stats:
            if user_format:
                if con:
                    print('')
                    print(f'{space}INFO: --stats is ignored - an output format was passed after "--": --output-format {user_format}')
            else:
                flags += STATS_FLAGS
                parse_stream = True

        flags += extra_flags

        # a long headless prompt goes through stdin as one NDJSON message; that protocol needs the stream-json output.
        # Otherwise - an interactive session, or another output format asked for - a long prompt is written to a file
        # and agy is asked to read it first (an interactive session then goes on as before)
        prompt_on_stdin = False
        if not interactive and len(full_prompt) > MAX_PROMPT_ARG_CHARS and (not user_format or user_format == 'stream-json'):
            prompt_on_stdin = True
            if not parse_stream and not user_format:
                flags += STATS_FLAGS
            parse_stream = True
        pr = prompt_via_file(full_prompt, 'agy', when=not prompt_on_stdin, path=long_prompt_file, prompt_file=prompt_file,
                             con=con, space=space)
        if pr['return'] > 0:
            return pr

        if interactive:
            dropped = [x for x in flags if x.split('=')[0] in RUN_ONLY_FLAGS]
            if dropped:
                flags = [x for x in flags if x.split('=')[0] not in RUN_ONLY_FLAGS]
                if con:
                    print('')
                    print(f'{space}INFO: agy takes these in headless mode only, so they are dropped from the session: {" ".join(dropped)}')
            cmd = base_cmd + flags + (['--prompt-interactive=' + pr['text']] if full_prompt else [])
        elif prompt_on_stdin:
            cmd = base_cmd + flags + STDIN_FLAGS
        else:
            cmd = base_cmd + flags + ['--print=' + pr['text']]

        if con:
            print('')
            shown = ' '.join(base_cmd + flags)
            if interactive:
                shown += ' --prompt-interactive=<prompt>' if full_prompt else ''
            elif prompt_on_stdin:
                shown += ' ' + ' '.join(STDIN_FLAGS) + '  < <prompt as NDJSON>'
            else:
                shown += ' --print=<prompt>'
            print(f'{space}RUN: {shown}')
            if full_prompt:
                where = f'in a file agy is asked to read first: {pr["file"]}' if pr['file'] \
                    else ('through stdin' if prompt_on_stdin else 'as an argument')
                print(f'{space}     (prompt: {len(full_prompt)} chars {where})')
            if interactive:
                print(f'{space}     (interactive session - agy keeps this terminal)')
            if output_file:
                print(f'{space}     (output: {output_file})')
            print('')

        if not os.environ.get('CMETA_GENERATOR'):
            os.environ['CMETA_GENERATOR'] = json.dumps(_agent_generator(agy_path, extra_flags, env))

        start_time = time.time()

        # ---- interactive: hand the terminal over
        if interactive:
            try:
                returncode = subprocess.call(cmd, env=env)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                prompt_via_file_done(pr)
                return self.cm.error(f'cannot run "{agy_path}": {e}', 1)
            prompt_via_file_done(pr)
            duration = time.time() - start_time
            if con:
                print('')
                if returncode != 0:
                    print(f'{space}INFO: agy exited with return code {returncode}')
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
            return self.cm.error(f'cannot run "{agy_path}": {e}', 1)

        if prompt_on_stdin:
            try:
                process.stdin.write(json.dumps({'event': 'user', 'message': {'content': full_prompt}}) + '\n')
                process.stdin.close()
            except Exception as e:
                process.kill()
                process.wait()
                return self.cm.error(f'cannot send the prompt to agy through stdin: {e}', 1)

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

        stats_lines = self._format_stats(run_stats)
        if stats and not stats_lines and con:
            print('')
            print(f'{space}WARNING: agy did not report any statistics for this run')
        if verbose and state['unknown'] and con:
            print(f'{space}INFO: {state["unknown"]} event(s) of the stream had an unknown shape and were not shown')

        run_info = {'task': 'run-agy', 'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'agy': agy_path,
                    'prompt_file': prompt_file, 'prompt_size': len(full_prompt), 'extra_flags': flags,
                    'duration': round(duration, 1), 'return_code': returncode, 'output_file': output_file}
        info_lines = [f'task: {run_info["task"]}', f'date: {run_info["date"]}', f'agy: {agy_path}',
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
                    data['agy_result'] = run_stats
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

        failed = returncode != 0 or str(run_stats.get('status', 'SUCCESS')).upper() not in ('SUCCESS', '')
        if failed:
            low = output.lower()
            hint = ''
            if 'authentication required' in low or 'authentication failed' in low or 'not logged into antigravity' in low:
                hint = ' (' + SIGN_IN_HINT + ')'
            elif 'quota' in low or 'rate limit' in low:
                hint = ' (the quota of the Google account is used up or the request was rate-limited: "/usage" in an interactive agy shows the window)'
            elif 'flags provided but not defined' in low:
                hint = ' (an unknown flag was passed after "--": "agy --help" lists them)'
            elif 'not a trusted' in low or 'workspace trust' in low:
                hint = ' (the folder is not a trusted workspace: open it once with "agy" by hand and trust it)'
            what = f'return code {returncode}' if returncode != 0 else f'status {run_stats.get("status")}'
            return self.cm.error(f'agy failed with {what}{hint}', 99)

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
        """One "--output-format stream-json" line -> readable text; the statistics are collected on the way.
        Three event types are documented (init, step_update, result); anything else with an error is shown, the rest
        is counted and dropped. A line that is not JSON is a log line of the CLI and passes through."""
        line = line.strip()
        if line == '':
            return []
        try:
            event = json.loads(line)
        except Exception:
            return [line + '\n']
        if not isinstance(event, dict):
            return [str(event).rstrip() + '\n']
        kind = str(event.get('type') or event.get('event') or '')
        # agy 1.2.16 (seen 2026-10-04) nests the payload under the event's own name:
        #   {"event": "init", "conversation_id": ..., "init": {"cwd": ..., "tools": [...]}}
        #   {"event": "step_update", "step_update": {"conversation_id", "step_index", "state": "ACTIVE"|"DONE",
        #                                            "step_type": "user_input"|"agent_response"|..., "text_delta", "usage"}}
        #   {"event": "result", "result": {"conversation_id", "status", "response", "duration_seconds", "num_turns", "usage"}}
        payload = event.get(kind) if isinstance(event.get(kind), dict) else event
        for holder in (event, payload):
            for key in ('conversation_id', 'conversationId', 'session_id'):
                if isinstance(holder.get(key), str) and holder[key]:
                    run_stats['session_id'] = holder[key]
            for key in ('model', 'modelName', 'model_name'):
                if isinstance(holder.get(key), str) and holder[key]:
                    run_stats.setdefault('model', holder[key])
        if kind == 'init':
            return []
        if kind == 'step_update':
            step_type = str(payload.get('step_type') or '')
            if step_type == 'user_input':
                return []
            delta = self._text_delta(payload)
            if delta and step_type in ('agent_response', ''):
                state['streamed'] += len(delta)
                return [delta]
            tool = self._tool_hint(payload)
            if tool:
                return [tool + '\n']
            if payload.get('error'):
                return [self._shorten('[error] ' + str(payload['error'])) + '\n']
            if step_type and step_type not in ('agent_response',) and str(payload.get('state', '')).upper() != 'DONE':
                return [self._shorten('[step: %s]' % step_type) + '\n']
            state['unknown'] += 0 if step_type else 1
            return []
        if kind == 'result' or 'usage' in payload:
            self._collect_stats(payload, run_stats)
            out = []
            response = str(payload.get('response') or '')
            if response and state['streamed'] == 0:
                out.append(response.rstrip() + '\n')
            elif state['streamed'] > 0:
                out.append('\n')
            if str(payload.get('status', '')).upper() not in ('SUCCESS', '') and payload.get('error'):
                out.append(self._shorten('[error] ' + str(payload['error'])) + '\n')
            return out
        if kind == 'error' or event.get('error'):
            return [self._shorten('[error] ' + str(event.get('message') or event.get('error') or event)) + '\n']
        state['unknown'] += 1
        return []

    @staticmethod
    def _text_delta(event):
        """The text of a step_update, wherever the young schema puts it (1.2.16: step_update.text_delta)."""
        for holder in (event, event.get('step_update') or {}, event.get('step') or {}, event.get('update') or {}, event.get('message') or {}):
            if isinstance(holder, dict):
                for key in ('text_delta', 'textDelta', 'delta', 'text'):
                    if isinstance(holder.get(key), str) and holder[key]:
                        return holder[key]
        return ''

    def _tool_hint(self, event):
        for holder in (event, event.get('step_update') or {}, event.get('step') or {}, event.get('update') or {}):
            if not isinstance(holder, dict):
                continue
            call = holder.get('tool_call') or holder.get('toolCall') or holder.get('tool_use') or holder.get('tool')
            if isinstance(call, dict):
                name = call.get('name') or call.get('tool_name') or call.get('toolName') or '?'
                params = call.get('parameters') or call.get('input') or call.get('args') or {}
                hint = next((str(params[k]) for k in ('command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt')
                             if isinstance(params, dict) and params.get(k)), '')
                return self._shorten(f'[tool: {name}] {hint}')
            if isinstance(call, str) and call:
                return self._shorten(f'[tool: {call}]')
        return ''

    @staticmethod
    def _shorten(text, length=120):
        text = ' '.join(str(text).split())
        return text[:length] + ' ...' if len(text) > length else text

    @staticmethod
    def _collect_stats(event, run_stats):
        """The counters of the final event: usage{input_tokens, output_tokens, thinking_tokens, cache_read_tokens,
        total_tokens}, duration_seconds, num_turns, status, conversation_id."""
        usage = event.get('usage') if isinstance(event.get('usage'), dict) else {}
        totals = run_stats.setdefault('tokens', {})

        def add(key, value):
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value

        add('input', usage.get('input_tokens'))
        add('output', usage.get('output_tokens'))
        add('reasoning', usage.get('thinking_tokens'))
        add('cache_read', usage.get('cache_read_tokens'))
        if isinstance(usage.get('total_tokens'), (int, float)):
            totals['total_reported'] = usage['total_tokens']
        if isinstance(event.get('duration_seconds'), (int, float)):
            run_stats['duration_s'] = event['duration_seconds']
        if isinstance(event.get('num_turns'), (int, float)):
            run_stats['turns'] = event['num_turns']
        if event.get('status'):
            run_stats['status'] = event['status']
        if event.get('error'):
            run_stats['error'] = event['error']
        if isinstance(event.get('conversation_id'), str) and event['conversation_id']:
            run_stats['session_id'] = event['conversation_id']
        raw = {k: v for k, v in event.items() if k != 'response'}
        run_stats['raw'] = raw

    @staticmethod
    def _get_tokens(run_stats):
        c = run_stats.get('tokens') or {}
        tokens = {'input': c.get('input', 0) or 0, 'cache_read': c.get('cache_read', 0) or 0, 'output': c.get('output', 0) or 0,
                  'reasoning': c.get('reasoning', 0) or 0, 'tool': 0}
        # whether "input_tokens" already holds the cached part is not documented: "sent" is the input count as reported
        tokens['sent'] = tokens['input']
        tokens['total'] = c.get('total_reported') or (tokens['input'] + tokens['output'] + tokens['reasoning'])
        tokens['cost_usd'] = 0                      # agy reports no cost; a Google login is a subscription quota
        return tokens

    def _format_stats(self, run_stats):
        if not run_stats.get('tokens'):
            return []
        t = self._get_tokens(run_stats)
        lines = ['Statistics for this prompt:',
                 f'  Tokens sent:     {t["sent"]} (cache read: {t["cache_read"]})',
                 f'  Tokens received: {t["output"]} (reasoning: {t["reasoning"]})',
                 f'  Tokens total:    {t["total"]}']
        if run_stats.get('model'):
            lines.append(f'  Model:           {run_stats["model"]}')
        if run_stats.get('turns') is not None:
            lines.append(f'  Turns:           {run_stats["turns"]}')
        if run_stats.get('duration_s') is not None:
            lines.append(f'  Agent time:      {run_stats["duration_s"]:.1f} sec')
        if run_stats.get('status'):
            lines.append(f'  Status:          {run_stats["status"]}')
        if run_stats.get('session_id'):
            lines.append(f'  Conversation:    {run_stats["session_id"]} (agy --conversation <id> continues it)')
        return lines
