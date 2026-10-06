"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-gemini - the Google Gemini CLI (https://github.com/google-gemini/gemini-cli) sibling of the "run-claude",
"run-codex" and "run-opencode" tasks of cmeta-aops, with the same flags.

Who can use it: since 2026-06-18 Gemini CLI serves Gemini Code Assist Standard/Enterprise licences, paid API keys
(GEMINI_API_KEY) and Vertex AI. A personal Google account (free, Google AI Pro, Google AI Ultra) is refused with
"IneligibleTierError ... migrate to the Antigravity suite"; such accounts use Antigravity CLI ("run-agy").

What is specific to gemini (checked with 0.62.0: "gemini --help", its own code, and headless runs that fail on
purpose - no account, a refused account, an invalid API key):
- headless mode is "gemini -p <prompt>", whose text is appended to what arrives on stdin: this task sends the prompt
  on stdin with an empty "-p", so that no command line carries it (on Windows the tool is a gemini.cmd launcher, and
  cmd.exe would cut an argument at its first new line, expand %VAR% in it and cap the line at 8191 characters);
- the interactive form "gemini -i <prompt>" takes the prompt as an argument; a long one (over MAX_PROMPT_ARG_CHARS of
  the task category API, 30000 characters - 7000 through the gemini.cmd launcher, or any with a new line, "%" or '"'
  there) is written to a file and the session is given a one-line request to read it first; it then goes on as before;
- a headless run refuses a folder that is not a trusted workspace unless "--skip-trust" is given (or
  GEMINI_CLI_TRUST_WORKSPACE=true): this task adds the flag in headless mode;
- "--yolo" auto-approves every tool call (--yes); "-e none" loads no extensions (--reproducible);
- "--output-format stream-json" gives one JSON event per line (--stats): "init" with the session id and the model
  ("auto" by default), "message", "tool_use", "tool_result", and "result" with the status, an error and the
  statistics {total_tokens, input_tokens, output_tokens, cached, duration_ms, tool_calls, models: {<model>: ...}};
- "--session-id <uuid>" starts a session under a given id, "--resume <uuid | number | latest>" continues one of the
  current folder; the session file is ~/.gemini/tmp/<project>/chats/session-*.jsonl (GEMINI_CLI_HOME moves ~);
- the interactive form is "gemini -i <prompt>" (run the prompt, then stay), or plain "gemini" without a prompt;
- the sign-in is done once by hand in an interactive session; a headless run never opens a browser here
  (NO_BROWSER=true is set for it) and fails with a hint instead: exit 41 "Please set an Auth method ..." when
  nothing is configured, "Error authenticating: IneligibleTierError" for a refused account, a "result" event with
  status "error" when the API refuses the key.
"""

import json
import os
import subprocess
import threading
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, MAX_PROMPT_ARG_CHARS, prompt_via_file, prompt_via_file_done

OUTPUT_FILE_SUFFIX = '-output.txt'
DEFAULT_OUTPUT_FILE = 'run-gemini-output.txt'

YES_FLAGS = ['--yolo']
PERMISSION_FLAGS = ['--yolo', '-y', '--approval-mode']

STATS_FLAGS = ['--output-format', 'stream-json']
OUTPUT_FORMAT_FLAGS = ['--output-format', '-o']

# --reproducible: no host-specific extensions. gemini output is never deterministic (no temperature, no seed).
REPRODUCIBLE_FLAGS = ['--extensions', 'none']
EXTENSION_FLAGS = ['--extensions', '-e']

MODEL_FLAGS = ['--model', '-m']

# A headless gemini refuses an untrusted workspace; the flag trusts the current folder for this session only
TRUST_FLAGS = ['--skip-trust']
TRUST_ENV = 'GEMINI_CLI_TRUST_WORKSPACE'

# The output format is for headless runs; an interactive session is text
RUN_ONLY_FLAGS = OUTPUT_FORMAT_FLAGS

# An interactive session takes its first prompt as a command line argument, which the OS caps (MAX_PROMPT_ARG_CHARS
# of the task category API): a longer prompt is written to a file the session is asked to read first. A launcher
# script (gemini.cmd on Windows) runs through cmd.exe, where an argument with these, or longer than this, does not
# arrive as it was written: the same file then
SCRIPT_UNSAFE = ('\n', '\r', '%', '"')
SCRIPT_MAX_ARG_CHARS = 7000

# A headless run must never open a browser for a sign-in nobody is there to finish: gemini then fails instead
NO_BROWSER_ENV = 'NO_BROWSER'

# What a failed run most likely needs, by the text gemini printed (the first match wins)
FAILURE_HINTS = (
    (('IneligibleTierError', 'no longer supported for Gemini Code Assist for individuals'),
     'Gemini CLI no longer serves personal Google accounts (free, Google AI Pro, Google AI Ultra): use a Gemini Code '
     'Assist Standard/Enterprise licence, a paid GEMINI_API_KEY or Vertex AI - or Antigravity CLI, which serves '
     'personal accounts ("cx task run run-agy")'),
    (('Please set an Auth method',),
     'gemini is not signed in: start it once by hand ("cx tool run gemini") and choose how to sign in, or set '
     'GEMINI_API_KEY (or GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_GENAI_USE_GCA)'),
    (('API key not valid', 'API_KEY_INVALID'),
     'the GEMINI_API_KEY of this environment is not valid'),
    (('RESOURCE_EXHAUSTED', 'Resource has been exhausted', 'Quota exceeded'),
     'the quota of this account or key is used up'),
    (('not running in a trusted directory',),
     'the folder is not a trusted workspace: pass --skip-trust after "--" or set GEMINI_CLI_TRUST_WORKSPACE=true'),
    (('Error authenticating',),
     'gemini is not signed in, or the stored login is not accepted: start it once by hand ("cx tool run gemini") and sign in'),
)


def _failure_hint(output):
    """The hint for a failed run, from what gemini printed, or ''."""
    for needles, hint in FAILURE_HINTS:
        if any(n in output for n in needles):
            return hint
    return ''


def _error_text(error):
    """The readable part of an error of the event stream: its message, taken out of the JSON the API wraps it in
    ('[API Error: {"error": {"message": "{ \\"error\\": {\\"message\\": \\"API key not valid...\\"}}"}}]')."""
    text = error.get('message') if isinstance(error, dict) and error.get('message') else error
    text = str(text)
    for _ in range(4):
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            break
        try:
            inner = json.loads(text[start:end + 1])
        except Exception:
            break
        if not isinstance(inner, dict):
            break
        message = inner['error'].get('message') if isinstance(inner.get('error'), dict) else inner.get('message')
        if not isinstance(message, str) or not message.strip():
            break
        text = message
    return ' '.join(text.split())


def _flag_value(flags, names):
    """The value of "<name> value" or "<name>=value" in a command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] in names:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def _agent_generator(gemini_path, flags):
    """The CMETA_GENERATOR record of a gemini session: the agent and its version, and the model it was started with."""
    rec = {'method': 'agent', 'agent': 'Gemini CLI'}
    try:
        out = subprocess.run([gemini_path or 'gemini', '--version'], capture_output=True, text=True, timeout=60, shell=False).stdout.strip()
        version = next((x for x in out.split() if x[:1].isdigit()), '')
        if version:
            rec['agent'] = 'Gemini CLI ' + version
    except Exception:
        pass
    model = _flag_value(flags, MODEL_FLAGS)
    if model:
        rec['model'] = model
    return rec


class CTask(InitCTask):
    """run-gemini: run Google's Gemini CLI on an assembled prompt, headless or interactive, and record the output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            long_prompt_file: str = '',     # where a prompt too long for the command line is written for the session to read
            interactive: bool = False,      # run the prompt, then stay in the interactive gemini session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # auto-approve every tool call (--yolo)
            reproducible: bool = False,     # no host-specific extensions (-e none); pin the model after "--"
            stats: bool = False,            # print token usage at the end (JSON event stream, turned back into text)
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for gemini (everything after "--")
    ):
        """Assemble a prompt and run Gemini CLI on it (gemini -p), or open an interactive session (gemini [-i])."""
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''
        _global = ctx['tasks']['global']

        gemini_path = _global.get('gemini', {}).get('path', '')
        if not gemini_path:
            return self.cm.error('the "gemini" tool was not set up (no path in the global context)', 1)

        interactive = interactive or i

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
                print(f'{space}INFO: no prompt was given (--prompt / --prompt_file) - opening an interactive gemini session')

        # An interactive session takes its first prompt as a command line argument: a long one - or, through the
        # gemini.cmd launcher, one that cmd.exe would mangle - is written to a file and the session is asked to read
        # it first (it then goes on interactively as before). A headless run sends the prompt on stdin.
        launcher = os.path.splitext(gemini_path)[1].lower() in ('.cmd', '.bat')
        pr = prompt_via_file(full_prompt, 'gemini', when=interactive, path=long_prompt_file, prompt_file=prompt_file,
                             force=launcher and any(c in full_prompt for c in SCRIPT_UNSAFE),
                             why='one the launcher script %s would mangle as a command line argument' % os.path.basename(gemini_path),
                             limit=SCRIPT_MAX_ARG_CHARS if launcher else MAX_PROMPT_ARG_CHARS, con=con, space=space)
        if pr['return'] > 0:
            return pr

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
        base_cmd = [gemini_path]
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

        if reproducible:
            if not [x for x in extra_keys if x in EXTENSION_FLAGS]:
                flags += REPRODUCIBLE_FLAGS
            if con and not [x for x in extra_keys if x in MODEL_FLAGS]:
                print('')
                print(f'{space}WARNING: --reproducible: no model was pinned - the default ("auto") routes between models and changes between releases')
                print(f'{space}         pass one after "--", i.e. --model gemini-3.1-pro-preview')

        parse_stream = False
        if stats:
            user_format_flags = [x for x in extra_flags if x.split('=')[0] in OUTPUT_FORMAT_FLAGS]
            if user_format_flags:
                if con:
                    print('')
                    print(f'{space}INFO: --stats is ignored - an output format was passed after "--": {" ".join(user_format_flags)}')
            else:
                flags += STATS_FLAGS
                parse_stream = True

        if not interactive and not [x for x in extra_keys if x in TRUST_FLAGS] and not os.environ.get(TRUST_ENV):
            # a headless gemini stops in a folder that is not a trusted workspace; trust it for this session
            flags += TRUST_FLAGS

        flags += extra_flags

        if interactive:
            dropped = [x for x in flags if x.split('=')[0] in RUN_ONLY_FLAGS]
            if dropped:
                flags = [x for x in flags if x.split('=')[0] not in RUN_ONLY_FLAGS]
                if con:
                    print('')
                    print(f'{space}INFO: gemini takes the output format in headless mode only, so it is dropped from the session: {" ".join(dropped)}')
            # the prompt, or the one-line request to read its file (see prompt_via_file above)
            cmd = base_cmd + flags + (['-i', pr['text']] if full_prompt else [])
        else:
            # the prompt goes on stdin; "-p" (empty) only switches to headless mode
            cmd = base_cmd + flags + ['-p', '']

        if con:
            print('')
            print(f'{space}RUN: {" ".join(base_cmd + flags)}' + (' -i <prompt>' if interactive and full_prompt else (' -p "" < <prompt>' if not interactive else '')))
            if full_prompt:
                print(f'{space}     (prompt: {len(full_prompt)} chars ' + ('in a file the session is asked to read first: %s)' % pr['file'] if pr['file']
                                                                           else ('as an argument)' if interactive else 'on stdin)')))
            if interactive:
                print(f'{space}     (interactive session - gemini keeps this terminal)')
            if output_file:
                print(f'{space}     (output: {output_file})')
            print('')

        if not os.environ.get('CMETA_GENERATOR'):
            os.environ['CMETA_GENERATOR'] = json.dumps(_agent_generator(gemini_path, extra_flags))

        start_time = time.time()

        # ---- interactive: hand the terminal over
        if interactive:
            try:
                returncode = subprocess.call(cmd)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                prompt_via_file_done(pr)
                return self.cm.error(f'cannot run "{gemini_path}": {e}', 1)
            prompt_via_file_done(pr)
            duration = time.time() - start_time
            if con:
                print('')
                if returncode != 0:
                    print(f'{space}INFO: gemini exited with return code {returncode}')
                print(f'{space}Duration: {duration:.1f} sec')
            return {'return': 0, 'output': '', 'output_file': '', 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                    'returncode': returncode, 'duration': duration, 'interactive': True, 'stats_file': ''}

        # ---- headless: run and collect everything; nobody is there to finish a sign-in, so no browser is opened
        run_env = dict(os.environ)
        run_env.setdefault(NO_BROWSER_ENV, 'true')
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1, env=run_env)
        except Exception as e:
            return self.cm.error(f'cannot run "{gemini_path}": {e}', 1)

        def send_prompt():
            # bytes, so that the text arrives as it is (no new-line translation), from a thread, so that a long prompt
            # cannot block against the output gemini writes meanwhile
            try:
                process.stdin.buffer.write(full_prompt.encode('utf-8'))
                process.stdin.close()
            except Exception:
                pass
        sender = threading.Thread(target=send_prompt, daemon=True)
        sender.start()

        lines = []
        run_stats = {}
        try:
            for line in process.stdout:
                for text in (self._parse_stream_line(line, run_stats) if parse_stream else [line]):
                    lines.append(text)
                    if con:
                        print(text, end='', flush=True)
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            return self.cm.error('interrupted by the user', 1)
        returncode = process.wait()
        duration = time.time() - start_time
        output = ''.join(lines)

        stats_lines = self._format_stats(run_stats)
        if stats and not stats_lines and con:
            print('')
            print(f'{space}WARNING: gemini did not report any statistics for this run')

        run_info = {'task': 'run-gemini', 'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'gemini': gemini_path,
                    'prompt_file': prompt_file, 'prompt_size': len(full_prompt), 'extra_flags': flags,
                    'duration': round(duration, 1), 'return_code': returncode, 'output_file': output_file}
        info_lines = [f'task: {run_info["task"]}', f'date: {run_info["date"]}', f'gemini: {gemini_path}',
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
                    data['gemini_result'] = run_stats
                    r = self.cm.utils.files.write_file(stats_file, data, file_format='json', sort_keys=False)
                else:
                    r = self.cm.utils.files.write_file(stats_file, '\n'.join(info_lines + stats_lines) + '\n', file_format='text', encoding='utf-8')
                if self.cm.catch_error(r):
                    return r
                if con:
                    print('')
                    print(f'{space}Statistics were recorded to "{stats_file}"')

        if con and stats_lines:
            print('')
            for x in stats_lines:
                print(f'{space}{x}')
        if con:
            print('')
            print(f'{space}Duration: {duration:.1f} sec')

        # gemini exits with the HTTP status of a refused request (400), 41 without an auth method, 1 for the rest; a
        # "result" event with status "error" is a failure too, whatever the exit code
        failed = returncode != 0 or str(run_stats.get('status', '')).lower() == 'error'
        if failed:
            hint = _failure_hint(output + ' ' + str(run_stats.get('error', '')))
            return self.cm.error(f'gemini failed with return code {returncode}' + (f': {hint}' if hint else ''), 99)

        result = {'return': 0, 'output': output, 'output_file': output_file, 'prompt': full_prompt, 'returncode': returncode,
                  'duration': duration, 'interactive': False}
        if run_stats:
            result['stats'] = run_stats
            result['tokens'] = self._get_tokens(run_stats)
        result['stats_file'] = stats_file
        return result

    # ------------------------------------------------------------------ the JSON event stream
    def _parse_stream_line(self, line, run_stats):
        """One "--output-format stream-json" line -> readable text; the statistics are collected on the way.
        The schema is young (init, message, tool_use, tool_result, error, result), so this walks the event for the
        interesting parts and passes anything else through unchanged."""
        line = line.strip()
        if line == '':
            return []
        try:
            event = json.loads(line)
        except Exception:
            return [line + '\n']            # a log line of the CLI, not an event
        if not isinstance(event, dict):
            return [str(event).rstrip() + '\n']
        kind = str(event.get('type', ''))
        for key in ('session_id', 'sessionId'):
            if isinstance(event.get(key), str) and event[key]:
                run_stats['session_id'] = event[key]
        if kind == 'init':
            if event.get('model'):
                run_stats['model'] = event['model']
            return []
        if kind == 'message':
            if event.get('role') == 'user':
                return []
            content = event.get('content')
            if isinstance(content, list):
                content = ''.join(str(x.get('text', '')) for x in content if isinstance(x, dict))
            content = str(content or '')
            if not content:
                return []
            return [content if event.get('delta') else content.rstrip() + '\n']
        if kind == 'tool_use':
            params = event.get('parameters') or event.get('input') or {}
            hint = next((str(params[k]) for k in ('command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt') if isinstance(params, dict) and params.get(k)), '')
            return [self._shorten(f'[tool: {event.get("tool_name") or event.get("name") or "?"}] {hint}') + '\n']
        if kind == 'tool_result':
            if str(event.get('status', '')).lower() in ('error', 'failed'):
                return [self._shorten('[tool error] ' + str(event.get('output') or event.get('error') or '')) + '\n']
            return []
        if kind == 'error':
            return [self._shorten('[error] ' + _error_text(event.get('message') or event.get('error') or event), 400) + '\n']
        if kind == 'result' or 'stats' in event:
            self._collect_stats(event, run_stats)
            if event.get('status'):
                run_stats['status'] = str(event['status'])
            if str(event.get('status', '')).lower() == 'error' and event.get('error'):
                run_stats['error'] = _error_text(event['error'])
                return [self._shorten('[error] ' + run_stats['error'], 400) + '\n']
            return []
        return [line + '\n']

    @staticmethod
    def _shorten(text, length=120):
        text = ' '.join(str(text).split())
        return text[:length] + ' ...' if len(text) > length else text

    @staticmethod
    def _collect_stats(event, run_stats):
        """The token counters of the final event, mapped to input, output, cache_read, reasoning, tool. Two shapes:
        the stream of 0.62 gives the totals of the run at the top level - {"stats": {total_tokens, input_tokens,
        output_tokens, cached, input, duration_ms, tool_calls, models: {<model>: {the same counters}}}} - and the
        "-o json" report nests them per model: {"stats": {"models": {<model>: {"tokens": {prompt, candidates, cached,
        thoughts, tool, total}}}}}. The models that worked are kept as a list (the default "auto" routes between two)."""
        stats = event.get('stats') if isinstance(event.get('stats'), dict) else event
        totals = run_stats.setdefault('tokens', {})

        def number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        def add(key, value):
            if number(value):
                totals[key] = totals.get(key, 0) + value

        def first(d, *keys):
            return next((d[k] for k in keys if number(d.get(k))), None)

        models = stats.get('models') if isinstance(stats.get('models'), dict) else {}
        if first(stats, 'input_tokens', 'prompt_tokens', 'output_tokens', 'candidates_tokens') is not None:
            add('input', first(stats, 'input_tokens', 'prompt_tokens'))
            add('output', first(stats, 'output_tokens', 'candidates_tokens'))
            add('cache_read', first(stats, 'cached', 'cached_tokens'))
            add('reasoning', first(stats, 'thoughts_tokens', 'reasoning_tokens', 'thoughts'))
            add('tool', first(stats, 'tool_tokens'))
        else:
            for m in models.values():
                t = m.get('tokens') if isinstance(m, dict) and isinstance(m.get('tokens'), dict) else (m if isinstance(m, dict) else {})
                add('input', first(t, 'prompt', 'input_tokens'))
                add('output', first(t, 'candidates', 'output_tokens'))
                add('cache_read', first(t, 'cached', 'cached_tokens'))
                add('reasoning', first(t, 'thoughts', 'thoughts_tokens'))
                add('tool', first(t, 'tool'))
        if number(stats.get('total_tokens')):
            totals['total_reported'] = stats['total_tokens']
        if models:
            run_stats['models'] = sorted(str(name) for name in models)
            run_stats.setdefault('model', run_stats['models'][0])
        for key in ('duration_ms', 'tool_calls', 'turns'):
            if number(stats.get(key)):
                run_stats[key] = stats[key]
        run_stats['raw'] = stats

    @staticmethod
    def _get_tokens(run_stats):
        c = run_stats.get('tokens') or {}
        tokens = {'input': c.get('input', 0) or 0, 'cache_read': c.get('cache_read', 0) or 0, 'output': c.get('output', 0) or 0,
                  'reasoning': c.get('reasoning', 0) or 0, 'tool': c.get('tool', 0) or 0}
        tokens['sent'] = tokens['input']            # gemini's prompt count includes the cached part
        # gemini's own total when it gives one (it knows what its counters include), else the sum
        tokens['total'] = c.get('total_reported') or (tokens['input'] + tokens['output'] + tokens['reasoning'] + tokens['tool'])
        tokens['cost_usd'] = 0                      # gemini reports no cost
        return tokens

    def _format_stats(self, run_stats):
        if not run_stats.get('tokens'):
            return []
        t = self._get_tokens(run_stats)
        lines = ['Statistics for this prompt:',
                 f'  Tokens sent:     {t["sent"]} (of which cached: {t["cache_read"]})',
                 f'  Tokens received: {t["output"]} (reasoning: {t["reasoning"]}, tool: {t["tool"]})',
                 f'  Tokens total:    {t["total"]}']
        if run_stats.get('model'):
            used = [m for m in run_stats.get('models') or [] if m != run_stats['model']]
            lines.append(f'  Model:           {run_stats["model"]}' + (f' ({", ".join(used)})' if used else ''))
        if run_stats.get('duration_ms') is not None:
            lines.append(f'  API time:        {run_stats["duration_ms"] / 1000:.1f} sec')
        if run_stats.get('session_id'):
            lines.append(f'  Session ID:      {run_stats["session_id"]}')
        return lines
