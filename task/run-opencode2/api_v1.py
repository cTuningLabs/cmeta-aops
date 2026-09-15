"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

This task is the OpenCode.AI (https://opencode.ai) sibling of the "run-claude2"
and "run-codex2" tasks.
"""

import json
import os
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Suffix appended to the prompt file name (without extension) when
# --output_file is not given
OUTPUT_FILE_SUFFIX = '-output.txt'

# Output file used when there is no prompt file to derive the name from
DEFAULT_OUTPUT_FILE = 'run-opencode2-output.txt'

# Flag added by --yes to answer "yes" to every opencode question. "--auto"
# auto-approves every permission that is not explicitly denied in the config,
# and opencode accepts it both in the TUI and on "opencode run".
YES_FLAGS = ['--auto']

# If the user already passed one of these after "--", --yes leaves it alone
PERMISSION_FLAGS = ['--auto']

# Flags added by --stats. The human output of "opencode run" carries no token
# counters, so we ask for the JSON event stream instead and turn it back into
# readable text. The assistant message events carry the usage and the cost.
STATS_FLAGS = ['--format', 'json']

# If the user already chose an output format after "--", --stats leaves it alone
OUTPUT_FORMAT_FLAGS = ['--format']

# Flag added by --reproducible to cut the run-to-run variation of opencode:
#   --pure
#       run without the external plugins configured on this host
# Note that opencode output is never fully deterministic - the CLI exposes no
# temperature and no seed.
REPRODUCIBLE_FLAGS = ['--pure']

# --reproducible also needs a pinned model ("provider/model", i.e.
# "anthropic/claude-opus-5"), since the default model of opencode depends on
# whichever providers happen to be authenticated on this host
MODEL_FLAGS = ['--model', '-m']

# Flags that opencode only accepts on its "run" subcommand - an interactive
# session ("opencode [project]") rejects them. "--auto" and "--pure" are
# accepted in both modes, so only the output format has to be dropped.
RUN_ONLY_FLAGS = OUTPUT_FORMAT_FLAGS

# Longest prompt that travels without a warning. Unlike claude ("claude -p") and
# codex ("codex exec -"), "opencode run" has no stdin mode at all - the prompt is
# always a command line argument, and an OS caps a whole command line (32767
# chars on Windows, ~2MB of argv on Linux).
MAX_PROMPT_ARG_CHARS = 30000

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            interactive: bool = False,      # preload the prompt, then stay in the interactive opencode session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # answer "yes" to all opencode questions (auto-approve permissions)
            reproducible: bool = False,     # cut the run-to-run variation of opencode
            stats: bool = False,            # print token usage and cost at the end
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for opencode (everything after "--")
    ):

        """
        Assemble a prompt, run the "opencode" CLI non-interactively (opencode run) and exit.

        This is the OpenCode.AI sister of the "run-claude2" and "run-codex2" tasks
        and takes the same flags.

        The prompt is the text of "prompt_file" (when given), then a new line,
        then "prompt".

        With "interactive" (or its short alias "i"), opencode is started as a normal
        interactive session instead: the assembled prompt is preloaded as the first
        message and opencode keeps the terminal afterwards, so the preset prompt can
        be followed up on by hand. This is also what happens when no prompt is given
        at all - an empty prompt opens a session rather than failing. Since an
        interactive session owns the terminal, nothing can be captured: "stats",
        "stats_file" and "output_file" are switched off, the result carries no output,
        and a non-zero exit code of opencode is reported but not turned into an error
        (quitting a session is normal). opencode accepts the output format only on
        "opencode run" (see RUN_ONLY_FLAGS), so it is dropped from a session.

        Unlike claude ("claude -p") and codex ("codex exec -"), "opencode run" has
        no stdin mode - the prompt is always passed as a command line argument, in
        both modes. A prompt longer than MAX_PROMPT_ARG_CHARS is therefore warned
        about and may be refused by the OS.

        The output is streamed to the console while opencode runs and is recorded
        into "output_file". When "output_file" is not given, it defaults to the
        prompt file name without extension + "-output.txt" (or
        "run-opencode2-output.txt" when there is no prompt file).

        With "yes", opencode runs unattended: every permission that is not
        explicitly denied is auto-approved via "--auto". A permission flag passed
        after "--" always wins over "yes".

        With "reproducible", the per-machine parts of the opencode session are
        removed so that two runs of the same prompt start from the same input (see
        REPRODUCIBLE_FLAGS). This cuts the variation between runs but cannot remove
        it: opencode output is never fully deterministic - the CLI exposes no
        temperature and no seed. Pin the model after "--"
        ("--model anthropic/claude-opus-5 --variant high") to complete the setup.

        With "stats", opencode is asked for its JSON event stream instead of the
        human transcript, so that the token counters and the cost of this prompt
        can be printed (and recorded) at the end. The output stays readable - the
        events are turned back into text while opencode runs. "stats_file" records
        the same statistics to a file (as JSON when its extension is ".json",
        otherwise as the printed text) and turns "stats" on by itself.

        Args:
            ctx (dict): cMeta context.
            prompt (str): Prompt text (appended after the prompt file text).
            prompt_file (str): File with the prompt text (read as UTF-8).
            interactive (bool): If True, preload the prompt (optional here) and stay in the opencode session.
            i (bool): Short alias of "interactive".
            yes (bool): If True, auto-approve all opencode permissions and never prompt.
            reproducible (bool): If True, cut the run-to-run variation of opencode (never zero).
            stats (bool): If True, print token usage and cost of this prompt at the end.
            stats_file (str): File to record the statistics (JSON if it ends with ".json"); implies "stats".
            output_file (str): File to record the output (overrides the default name).
            skip_output_file (bool): If True, do not record the output to a file.
            append_output_file (bool): If True, append to the output file instead of overwriting it.
            skip_output_header (bool): If True, do not add the summary header to the output file.
            unparsed (list): Extra flags passed to opencode (everything after "--").

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **output** (str): Full output of opencode ('' if `interactive`).
                - **output_file** (str): Where the output was recorded ('' if skipped).
                - **prompt** (str): The assembled prompt sent to opencode.
                - **returncode** (int): Return code of the opencode CLI.
                - **duration** (float): Run time in seconds.
                - **interactive** (bool): True if opencode was run as an interactive session.
                - **stats** (dict): Usage, cost and session ID collected from opencode if `stats`.
                - **tokens** (dict): Sent/output/total tokens and cost in USD if `stats`.
                - **stats_file** (str): Where the statistics were recorded ('' if none).
        """

        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']

        # Path to the opencode CLI detected/installed by the "setup" task (see _desc.yaml)
        opencode_path = _global.get('opencode', {}).get('path', '')

        if not opencode_path:
            return self.cm.error('the "opencode" tool was not set up (no path in the global context)', 1)

        # "--i" and "-i" are the short spellings of "--interactive"
        interactive = interactive or i

        ###########################################################################################
        # Assemble the prompt: prompt file text + "\n" + prompt text

        texts = []

        if prompt_file:
            prompt_file = os.path.abspath(os.path.expanduser(prompt_file))

            if not os.path.isfile(prompt_file):
                return self.cm.error(f'prompt file was not found: {prompt_file}', 1)

            # Always read as raw text (utils.files.read_file would parse .json/.yaml prompts).
            # "utf-8-sig" transparently strips the BOM that Windows editors add.
            try:
                with open(prompt_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                    texts.append(f.read().strip())
            except Exception as e:
                return self.cm.error(f'cannot read prompt file {prompt_file}: {e}', 1)

        if prompt:
            texts.append(prompt.strip())

        full_prompt = '\n'.join([t for t in texts if t != ''])

        # Without a prompt there is nothing to run non-interactively - open a
        # session instead of failing (an interactive opencode is useful on its own)
        if full_prompt == '' and not interactive:
            interactive = True

            if con:
                print ('')
                print (f'{space}INFO: no prompt was given (--prompt / --prompt_file) - '
                       f'opening an interactive opencode session')

        # "opencode run" has no stdin mode, so the prompt is an argument in both modes
        if full_prompt != '' and len(full_prompt) > MAX_PROMPT_ARG_CHARS and con:
            print ('')
            print (f'{space}WARNING: the prompt is {len(full_prompt)} chars long - opencode takes it '
                   f'as a command line argument, which the OS may refuse')
            print (f'{space}         (opencode has no stdin mode - use run-claude2 or run-codex2 '
                   f'for a very long prompt)')

        ###########################################################################################
        # Pick the output and statistics files.
        # An interactive session keeps the terminal, so there is no stream to collect.

        if interactive:
            if con and (stats or stats_file or output_file):
                print ('')
                print (f'{space}INFO: --interactive keeps the terminal - the output and the '
                       f'statistics of the session cannot be collected')

            stats = False
            stats_file = ''
        elif stats_file:
            stats_file = os.path.abspath(os.path.expanduser(stats_file))

            # Recording the statistics requires collecting them
            stats = True

        if interactive or skip_output_file:
            output_file = ''
        else:
            if not output_file:
                if prompt_file:
                    output_file = os.path.splitext(prompt_file)[0] + OUTPUT_FILE_SUFFIX
                else:
                    output_file = DEFAULT_OUTPUT_FILE

            output_file = os.path.abspath(os.path.expanduser(output_file))

        ###########################################################################################
        # Build the opencode command line.
        #
        # Non-interactive: "opencode run [message..]" - the prompt is the trailing
        # positional argument (there is no stdin mode).
        # Interactive: "opencode [project] [prompt]" - the prompt is the trailing
        # positional argument too.

        base_cmd = [opencode_path] if interactive else [opencode_path, 'run']

        # Flags added on top of base_cmd - kept apart so that they can be reported as they are
        flags = []

        extra_flags = [str(u) for u in unparsed] if unparsed else []

        extra_keys = [x.split('=')[0] for x in extra_flags]

        if yes:
            # Do not fight with a permission flag that the user passed after "--"
            user_permission_flags = [x for x in extra_flags if x.split('=')[0] in PERMISSION_FLAGS]

            if user_permission_flags:
                if con:
                    print ('')
                    print (f'{space}INFO: --yes is ignored - permission flags were '
                           f'passed after "--": {" ".join(user_permission_flags)}')
            else:
                flags += YES_FLAGS

        if reproducible:
            # Add only what the user did not pass after "--" already
            flags += [x for x in REPRODUCIBLE_FLAGS if x not in extra_keys]

            # The model must be pinned too - and only the user knows which one to use.
            # opencode has no default model of its own: it picks one from whichever
            # providers are authenticated on this host, so this matters more here
            # than for claude or codex.
            if con and not [x for x in extra_keys if x in MODEL_FLAGS]:
                print ('')
                print (f'{space}WARNING: --reproducible: no model was pinned - opencode picks one '
                       f'from the providers authenticated on this host')
                print (f'{space}         pass one after "--", i.e. '
                       f'--model anthropic/claude-opus-5 --variant high')

        # When opencode prints its JSON event stream we must turn it back into text
        parse_stream = False

        if stats:
            user_format_flags = [x for x in extra_flags
                                 if x.split('=')[0] in OUTPUT_FORMAT_FLAGS]

            if user_format_flags:
                if con:
                    print ('')
                    print (f'{space}INFO: --stats is ignored - an output format was '
                           f'passed after "--": {" ".join(user_format_flags)}')
            else:
                flags += STATS_FLAGS
                parse_stream = True

        flags += extra_flags

        if interactive:
            # An interactive opencode rejects the "run"-only flags outright, so drop
            # them rather than let the session fail to start
            dropped = [x for x in flags if x.split('=')[0] in RUN_ONLY_FLAGS]

            if dropped:
                flags = [x for x in flags if x.split('=')[0] not in RUN_ONLY_FLAGS]

                if con:
                    print ('')
                    print (f'{space}INFO: opencode accepts these only on "opencode run", so they '
                           f'are dropped from the interactive session: {" ".join(dropped)}')

        cmd = base_cmd + flags

        # The prompt is the trailing positional argument in both modes
        if full_prompt:
            cmd.append(full_prompt)

        if con:
            print ('')
            print (f'{space}RUN: {" ".join(base_cmd + flags)}')
            if full_prompt:
                print (f'{space}     (prompt: {len(full_prompt)} chars as an argument)')
            if interactive:
                print (f'{space}     (interactive session - opencode keeps this terminal)')
            if output_file:
                print (f'{space}     (output: {output_file})')
            print ('')

        start_time = time.time()

        ###########################################################################################
        # Interactive: hand the terminal over to opencode.
        # No pipes at all - stdin/stdout/stderr stay attached to this console, so the
        # opencode TUI behaves exactly as if it had been started by hand. Nothing can
        # be captured in return, so this path ends here.

        if interactive:
            try:
                returncode = subprocess.call(cmd)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                return self.cm.error(f'cannot run "{opencode_path}": {e}', 1)

            duration = time.time() - start_time

            if con:
                print ('')
                if returncode != 0:
                    # Leaving a session early is normal - report the code, do not fail the task
                    print (f'{space}INFO: opencode exited with return code {returncode}')
                print (f'{space}Duration: {duration:.1f} sec')

            return {'return':0,
                    'output': '',
                    'output_file': '',
                    'prompt': full_prompt,
                    'returncode': returncode,
                    'duration': duration,
                    'interactive': True,
                    'stats_file': ''}

        ###########################################################################################
        # Non-interactive: run opencode on the prompt and collect everything it prints.
        # stdin is closed right away - opencode does not read the prompt from there,
        # but a tool it runs might otherwise block on an inherited console.

        try:
            process = subprocess.Popen(
                cmd,
                stdin = subprocess.DEVNULL,
                stdout = subprocess.PIPE,
                stderr = subprocess.STDOUT,
                text = True,
                encoding = 'utf-8',
                errors = 'replace',
                bufsize = 1,
            )
        except Exception as e:
            return self.cm.error(f'cannot run "{opencode_path}": {e}', 1)

        # Stream the output while opencode works and keep it for the output file
        lines = []
        run_stats = {}

        try:
            for line in process.stdout:
                texts = self._parse_stream_line(line, run_stats) if parse_stream else [line]

                for text in texts:
                    lines.append(text)
                    if con:
                        print (text, end='', flush=True)
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            return self.cm.error('interrupted by the user', 1)

        returncode = process.wait()

        duration = time.time() - start_time

        output = ''.join(lines)

        stats_lines = self._format_stats(run_stats)

        if stats and not stats_lines and con:
            print ('')
            print (f'{space}WARNING: opencode did not report any statistics for this run')

        # Description of this run - shared by the output file and the statistics file
        run_info = {
            'task': 'run-opencode2',
            'date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'opencode': opencode_path,
            'prompt_file': prompt_file,
            'prompt_size': len(full_prompt),
            'extra_flags': flags,
            'duration': round(duration, 1),
            'return_code': returncode,
            'output_file': output_file,
        }

        info_lines = [
            f'task: {run_info["task"]}',
            f'date: {run_info["date"]}',
            f'opencode: {opencode_path}',
            f'prompt file: {prompt_file if prompt_file else "(none)"}',
            f'prompt size: {len(full_prompt)} chars',
            f'extra flags: {" ".join(flags) if flags else "(none)"}',
            f'duration: {duration:.1f} sec',
            f'return code: {returncode}',
        ]

        ###########################################################################################
        # Record the output

        if output_file:
            text = output

            if not skip_output_header:
                header = ['# ' + x for x in info_lines + stats_lines]

                header += ['', '']

                text = '\n'.join(header) + output

            if append_output_file and os.path.isfile(output_file):
                try:
                    with open(output_file, 'a', encoding='utf-8', newline='\n') as f:
                        f.write('\n' + text)
                except Exception as e:
                    return self.cm.error(f'cannot append to the output file {output_file}: {e}', 1)
            else:
                r = self.cm.utils.files.write_file(output_file, text, file_format='text', encoding='utf-8')
                if self.cm.catch_error(r): return r

            if con:
                print ('')
                print (f'{space}Output was recorded to "{output_file}"')

        ###########################################################################################
        # Record the statistics

        if stats_file:
            if not run_stats:
                if con:
                    print ('')
                    print (f'{space}WARNING: no statistics to record to "{stats_file}"')
                stats_file = ''
            else:
                if os.path.splitext(stats_file)[1].lower() == '.json':
                    data = dict(run_info)
                    data['tokens'] = self._get_tokens(run_stats)
                    data['opencode_result'] = run_stats

                    r = self.cm.utils.files.write_file(stats_file, data, file_format='json',
                                                       sort_keys=False)
                else:
                    data = '\n'.join(info_lines + stats_lines) + '\n'

                    r = self.cm.utils.files.write_file(stats_file, data, file_format='text',
                                                       encoding='utf-8')

                if self.cm.catch_error(r): return r

                if con:
                    print ('')
                    print (f'{space}Statistics were recorded to "{stats_file}"')

        if con and stats_lines:
            print ('')
            for x in stats_lines:
                print (f'{space}{x}')

        if con:
            print ('')
            print (f'{space}Duration: {duration:.1f} sec')

        if returncode != 0:
            return self.cm.error(f'opencode failed with return code {returncode}', 99)

        result = {'return':0,
                  'output': output,
                  'output_file': output_file,
                  'prompt': full_prompt,
                  'returncode': returncode,
                  'duration': duration,
                  'interactive': False}

        if run_stats:
            result['stats'] = run_stats
            result['tokens'] = self._get_tokens(run_stats)

        result['stats_file'] = stats_file

        return result


    ############################################################
    def _parse_stream_line(self,
                           line: str,       # one line of the opencode "--format json" output
                           run_stats: dict, # updated in place with usage, cost and session ID
    ):
        """
        Turn one opencode JSON event into readable text.

        opencode is a young and fast-moving CLI, and its "--format json" event
        schema is not frozen - so this walks the event for the interesting parts
        instead of hard-coding one shape: assistant text, tool calls, and the
        "tokens"/"cost" of every assistant message. Anything that cannot be
        recognized is passed through unchanged, so no output is ever swallowed.

        Args:
            line (str): One line (one JSON event) of the opencode output.
            run_stats (dict): Updated in place with 'tokens', 'cost', 'messages' and 'session_id'.

        Returns:
            list: Text chunks to print and record (empty for events with nothing to show).
        """

        line = line.strip()

        if line == '':
            return []

        try:
            event = json.loads(line)
        except Exception:
            # Not a JSON event (a log line from the CLI, ...) - keep it as it is
            return [line + '\n']

        if not isinstance(event, dict):
            return [str(event).rstrip() + '\n']

        self._collect_stats(event, run_stats)

        return self._describe_event(event)


    ############################################################
    def _describe_event(self,
                        event: dict,  # one opencode JSON event
    ):
        """
        Describe one opencode event as readable text.

        Args:
            event (dict): One opencode JSON event.

        Returns:
            list: Text chunks to print and record (empty for events with nothing to show).
        """

        texts = []

        # An event carries either one "part" or a whole message with "parts"
        parts = []

        for key in ['part', 'parts', 'info', 'message', 'properties']:
            value = event.get(key)

            if isinstance(value, dict):
                parts += value.get('parts', []) if isinstance(value.get('parts'), list) else [value]
            elif isinstance(value, list):
                parts += value

        if not parts:
            parts = [event]

        for part in parts:
            if not isinstance(part, dict):
                continue

            part_type = str(part.get('type', ''))

            # Assistant text (reasoning/thinking parts are skipped)
            if part_type in ['text', 'message', 'assistant']:
                text = part.get('text', '')
                if isinstance(text, str) and text.strip() != '':
                    texts.append(text.rstrip() + '\n')

            # A tool call - show the tool and the most telling of its inputs
            elif part_type == 'tool':
                texts.append(self._describe_tool(part) + '\n')

            elif part_type in ['error', 'step-error']:
                texts.append(self._shorten('[error] ' + str(part.get('error', part))) + '\n')

        return texts


    ############################################################
    def _describe_tool(self,
                       part: dict,  # "tool" part of an opencode event
    ):
        """
        Describe a tool call of opencode in one line.

        Args:
            part (dict): "tool" part of an opencode event.

        Returns:
            str: One line such as '[tool: bash] git status'.
        """

        name = part.get('tool', part.get('name', '?'))

        state = part.get('state', {})
        if not isinstance(state, dict):
            state = {}

        tool_input = state.get('input', part.get('input', {}))
        if not isinstance(tool_input, dict):
            tool_input = {}

        hint = ''
        for key in ['command', 'filePath', 'file_path', 'path', 'pattern', 'url', 'description']:
            if tool_input.get(key):
                hint = str(tool_input[key])
                break

        return self._shorten(f'[tool: {name}] {hint}'.rstrip())


    ############################################################
    def _shorten(self,
                 text: str,         # text to shorten
                 length: int = 120, # maximum length
    ):
        """
        Put a text on one line and cut it to a readable length.

        Args:
            text (str): Text to shorten.
            length (int): Maximum length.

        Returns:
            str: One-line text.
        """

        text = ' '.join(str(text).split())

        if len(text) > length:
            text = text[:length] + ' ...'

        return text


    ############################################################
    def _collect_stats(self,
                       event: dict,     # one opencode JSON event
                       run_stats: dict, # updated in place
                       depth: int = 0,  # recursion guard
    ):
        """
        Add the token counters and the cost of one opencode event to the totals.

        A run has several assistant messages (one per turn plus the sub-agents),
        each carrying its own "tokens" ({input, output, reasoning, cache:{read,write}})
        and "cost". They are summed here; the session ID is kept for reference.

        Args:
            event (dict): One opencode JSON event (walked recursively).
            run_stats (dict): Updated in place with 'tokens', 'cost', 'messages' and 'session_id'.
            depth (int): Recursion guard (opencode nests messages a few levels deep).

        Returns:
            None
        """

        if depth > 6 or not isinstance(event, dict):
            return

        tokens = event.get('tokens')

        if isinstance(tokens, dict):
            totals = run_stats.setdefault('tokens', {})

            for key in ['input', 'output', 'reasoning']:
                if isinstance(tokens.get(key), (int, float)):
                    totals[key] = totals.get(key, 0) + tokens[key]

            cache = tokens.get('cache', {})
            if isinstance(cache, dict):
                for key in ['read', 'write']:
                    if isinstance(cache.get(key), (int, float)):
                        totals['cache_' + key] = totals.get('cache_' + key, 0) + cache[key]

            if isinstance(event.get('cost'), (int, float)):
                run_stats['cost'] = run_stats.get('cost', 0) + event['cost']

            run_stats['messages'] = run_stats.get('messages', 0) + 1

        for key in ['sessionID', 'sessionId', 'session_id']:
            if isinstance(event.get(key), str) and event[key] != '':
                run_stats['session_id'] = event[key]
                break

        # opencode wraps the assistant message into the event a level or two deep
        for value in event.values():
            if isinstance(value, dict):
                self._collect_stats(value, run_stats, depth + 1)
            elif isinstance(value, list):
                for x in value:
                    if isinstance(x, dict):
                        self._collect_stats(x, run_stats, depth + 1)


    ############################################################
    def _get_tokens(self,
                    run_stats: dict,  # statistics collected from the opencode events
    ):
        """
        Summarize the token counters of one prompt.

        opencode counts like claude, not like codex: "input" excludes the tokens
        served from (or written to) the prompt cache, so "sent" is their sum.

        Args:
            run_stats (dict): Statistics collected from the opencode events.

        Returns:
            dict: Token counters ('input', 'cache_write', 'cache_read', 'sent',
                  'output', 'reasoning', 'total') and 'cost_usd'.
        """

        collected = run_stats.get('tokens', {})
        if not isinstance(collected, dict):
            collected = {}

        tokens = {
            'input': collected.get('input', 0) or 0,
            'cache_write': collected.get('cache_write', 0) or 0,
            'cache_read': collected.get('cache_read', 0) or 0,
            'output': collected.get('output', 0) or 0,
            'reasoning': collected.get('reasoning', 0) or 0,
        }

        tokens['sent'] = tokens['input'] + tokens['cache_write'] + tokens['cache_read']
        tokens['total'] = tokens['sent'] + tokens['output']
        tokens['cost_usd'] = run_stats.get('cost', 0) or 0

        return tokens


    ############################################################
    def _format_stats(self,
                      run_stats: dict,  # statistics collected from the opencode events
    ):
        """
        Format the token/cost statistics of one prompt for the console and the output file.

        Args:
            run_stats (dict): Statistics collected from the opencode events ({} if there are none).

        Returns:
            list: Text lines (empty when opencode reported no statistics).
        """

        if not run_stats.get('tokens'):
            return []

        tokens = self._get_tokens(run_stats)

        stats_lines = [
            'Statistics for this prompt:',
            f'  Tokens sent:     {tokens["sent"]}'
            f' (new: {tokens["input"]}, cache write: {tokens["cache_write"]},'
            f' cache read: {tokens["cache_read"]})',
            f'  Tokens received: {tokens["output"]} (reasoning: {tokens["reasoning"]})',
            f'  Tokens total:    {tokens["total"]}',
        ]

        messages = run_stats.get('messages')
        if messages is not None:
            stats_lines.append(f'  Messages:        {messages}')

        # opencode reports a cost only for providers it knows the pricing of
        # (0 for a subscription login or a local model)
        if run_stats.get('cost') is not None:
            stats_lines.append(f'  Cost:            {tokens["cost_usd"]:.4f} USD')

        session_id = run_stats.get('session_id')
        if session_id:
            stats_lines.append(f'  Session ID:      {session_id}')

        return stats_lines
