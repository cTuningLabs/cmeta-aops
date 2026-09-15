"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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
DEFAULT_OUTPUT_FILE = 'run-codex2-output.txt'

# Flags added by --yes to answer "yes" to every codex question:
#   --dangerously-bypass-approvals-and-sandbox
#       skip all approval prompts and run commands without sandboxing
#       (on Windows the sandbox helper is often unavailable, and then this is
#        the only way codex can write files at all)
#   --skip-git-repo-check
#       trust the current directory - without it codex refuses to start with
#       "Not inside a trusted directory and --skip-git-repo-check was not specified"
YES_FLAGS = ['--dangerously-bypass-approvals-and-sandbox']
TRUST_FLAGS = ['--skip-git-repo-check']

# If the user already chose a sandbox/approval policy after "--", --yes leaves it alone
PERMISSION_FLAGS = ['--dangerously-bypass-approvals-and-sandbox',
                    '--sandbox', '-s', '--ask-for-approval', '-a']

# Flag added by --stats. The human output of "codex exec" prints a token total but
# nothing structured, so we ask for the JSONL event stream instead and turn it back
# into readable text. The "turn.completed" events carry the usage.
STATS_FLAGS = ['--json']

# Flags added by --reproducible to cut the run-to-run variation of codex:
#   --ignore-user-config
#       do not load $CODEX_HOME/config.toml of this host (auth still works)
#   --ignore-rules
#       do not load the user/project execpolicy ".rules" files
# Note that codex output is never fully deterministic - the CLI exposes no
# temperature and no seed.
REPRODUCIBLE_FLAGS = ['--ignore-user-config', '--ignore-rules']

# --reproducible also needs a pinned model, since the default model of codex
# changes between releases
MODEL_FLAGS = ['--model', '-m']

# Flags that codex only accepts on its "exec" subcommand - an interactive session
# ("codex [prompt]") rejects them with "unexpected argument". Everything that
# --stats and --reproducible add falls in here, and so does the trust flag: an
# interactive codex simply asks about the directory in its TUI instead.
EXEC_ONLY_FLAGS = STATS_FLAGS + REPRODUCIBLE_FLAGS + TRUST_FLAGS

# Longest prompt that --interactive preloads without a warning. An interactive
# session owns stdin, so the prompt cannot be piped in and travels as a command
# line argument instead - and Windows caps a whole command line at 32767 chars.
MAX_INTERACTIVE_PROMPT_CHARS = 30000

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
            interactive: bool = False,      # preload the prompt, then stay in the interactive codex session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # answer "yes" to all codex questions (approvals, sandbox, trust)
            reproducible: bool = False,     # cut the run-to-run variation of codex
            stats: bool = False,            # print token usage at the end
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for codex (everything after "--")
    ):

        """
        Assemble a prompt, run the "codex" CLI non-interactively (codex exec) and exit.

        This is the codex sister of the "run-claude2" task and takes the same flags.

        The prompt is the text of "prompt_file" (when given), then a new line,
        then "prompt".

        With "interactive" (or its short alias "i"), codex is started as a normal
        interactive session instead: the assembled prompt is preloaded as the first
        message and codex keeps the terminal afterwards, so the preset prompt can be
        followed up on by hand. This is also what happens when no prompt is given at
        all - an empty prompt opens a session rather than failing, so a plain
        "cx task run run-codex2" is just "codex" with the flags below. Since an
        interactive session owns the terminal, nothing can be captured: "stats",
        "stats_file" and "output_file" are switched off, the result carries no output,
        and a non-zero exit code of codex is reported but not turned into an error
        (quitting a session is normal).
        Note that codex accepts several flags only on its "exec" subcommand (see
        EXEC_ONLY_FLAGS) - "reproducible" therefore has no effect in this mode, and
        "yes" is reduced to skipping the approvals and the sandbox.

        The output is streamed to the console while codex runs and is recorded
        into "output_file". When "output_file" is not given, it defaults to the
        prompt file name without extension + "-output.txt" (or
        "run-codex2-output.txt" when there is no prompt file).

        With "yes", codex runs fully unattended: approvals are skipped, commands
        run without the sandbox and the current directory is trusted without a
        git repository check (see YES_FLAGS/TRUST_FLAGS). A sandbox or approval
        flag passed after "--" always wins over "yes".

        With "reproducible", the per-machine configuration of codex is ignored so
        that two runs of the same prompt start from the same input (see
        REPRODUCIBLE_FLAGS). This cuts the variation between runs but cannot
        remove it: codex output is never fully deterministic - the CLI exposes no
        temperature and no seed. Pin the model after "--" ("-m gpt-5.6-sol") to
        complete the setup.

        With "stats", codex is asked for its JSONL event stream instead of the
        human transcript, so that the token counters of this prompt can be printed
        (and recorded) at the end. The output stays readable - the events are
        turned back into text while codex runs. "stats_file" records the same
        statistics to a file (as JSON when its extension is ".json", otherwise as
        the printed text) and turns "stats" on by itself. Unlike claude, codex
        reports no cost.

        Args:
            ctx (dict): cMeta context.
            prompt (str): Prompt text (appended after the prompt file text).
            prompt_file (str): File with the prompt text (read as UTF-8).
            interactive (bool): If True, preload the prompt (optional here) and stay in the codex session.
            i (bool): Short alias of "interactive".
            yes (bool): If True, answer "yes" to all codex questions and never prompt.
            reproducible (bool): If True, cut the run-to-run variation of codex (never zero).
            stats (bool): If True, print the token usage of this prompt at the end.
            stats_file (str): File to record the statistics (JSON if it ends with ".json"); implies "stats".
            output_file (str): File to record the output (overrides the default name).
            skip_output_file (bool): If True, do not record the output to a file.
            append_output_file (bool): If True, append to the output file instead of overwriting it.
            skip_output_header (bool): If True, do not add the summary header to the output file.
            unparsed (list): Extra flags passed to codex (everything after "--").

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **output** (str): Full output of codex ('' if `interactive`).
                - **output_file** (str): Where the output was recorded ('' if skipped).
                - **prompt** (str): The assembled prompt sent to codex.
                - **returncode** (int): Return code of the codex CLI.
                - **duration** (float): Run time in seconds.
                - **interactive** (bool): True if codex was run as an interactive session.
                - **stats** (dict): Usage, turns and thread ID collected from codex if `stats`.
                - **tokens** (dict): Sent/output/total tokens if `stats`.
                - **stats_file** (str): Where the statistics were recorded ('' if none).
        """

        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']

        # Path to the codex CLI detected/installed by the "setup" task (see _desc.yaml)
        codex_path = _global.get('codex', {}).get('path', '')

        if not codex_path:
            return self.cm.error('the "codex" tool was not set up (no path in the global context)', 1)

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
        # session instead of failing (an interactive codex is useful on its own)
        if full_prompt == '' and not interactive:
            interactive = True

            if con:
                print ('')
                print (f'{space}INFO: no prompt was given (--prompt / --prompt_file) - '
                       f'opening an interactive codex session')

        if interactive and len(full_prompt) > MAX_INTERACTIVE_PROMPT_CHARS and con:
            print ('')
            print (f'{space}WARNING: the prompt is {len(full_prompt)} chars long - an interactive '
                   f'session takes it as a command line argument, which the OS may refuse')
            print (f'{space}         drop --interactive to send it through stdin instead')

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
        # Build the codex command line.
        #
        # Non-interactive: "codex exec -" reads the prompt from stdin rather than from
        # the command line - a prompt file can easily be longer than the OS limit.
        # Interactive: codex owns stdin, so the prompt can only travel as the trailing
        # positional argument ("codex [options] [prompt]").

        base_cmd = [codex_path] if interactive else [codex_path, 'exec', '-']

        # Flags added on top of base_cmd - kept apart so that they can be reported as they are
        flags = []

        extra_flags = [str(u) for u in unparsed] if unparsed else []

        extra_keys = [x.split('=')[0] for x in extra_flags]

        if yes:
            # Do not fight with a sandbox/approval flag that the user passed after "--"
            user_permission_flags = [x for x in extra_flags if x.split('=')[0] in PERMISSION_FLAGS]

            if user_permission_flags:
                if con:
                    print ('')
                    print (f'{space}INFO: --yes keeps the sandbox/approval flags '
                           f'passed after "--": {" ".join(user_permission_flags)}')
            else:
                flags += YES_FLAGS

            # Trusting the directory is a separate question in codex
            flags += [x for x in TRUST_FLAGS if x not in extra_keys]

        if reproducible:
            # Add only what the user did not pass after "--" already
            flags += [x for x in REPRODUCIBLE_FLAGS if x not in extra_keys]

            # The model must be pinned too - and only the user knows which one to use.
            # Pointless in an interactive session, where every flag of --reproducible
            # is dropped again below as "exec"-only.
            if con and not interactive and not [x for x in extra_keys if x in MODEL_FLAGS]:
                print ('')
                print (f'{space}WARNING: --reproducible: no model was pinned - the default '
                       f'model of codex can change between releases')
                print (f'{space}         pass one after "--", i.e. -m gpt-5.6-sol')

        # When codex prints its JSONL event stream we must turn it back into text
        parse_stream = False

        if stats:
            if [x for x in extra_keys if x in STATS_FLAGS]:
                # Already requested by the user - just parse it
                parse_stream = True
            else:
                flags += STATS_FLAGS
                parse_stream = True

        flags += extra_flags

        if interactive:
            # An interactive codex rejects the "exec"-only flags outright, so drop
            # them rather than let the session fail to start
            dropped = [x for x in flags if x.split('=')[0] in EXEC_ONLY_FLAGS]

            if dropped:
                flags = [x for x in flags if x.split('=')[0] not in EXEC_ONLY_FLAGS]

                if con:
                    print ('')
                    print (f'{space}INFO: codex accepts these only on "codex exec", so they are '
                           f'dropped from the interactive session: {" ".join(dropped)}')

                    if reproducible:
                        print (f'{space}      (--reproducible therefore has no effect here)')

        cmd = base_cmd + flags

        # In an interactive session the prompt is the trailing positional argument
        if interactive and full_prompt:
            cmd.append(full_prompt)

        if con:
            print ('')
            print (f'{space}RUN: {" ".join(base_cmd + flags)}')
            if full_prompt:
                where = 'as an argument' if interactive else 'via stdin'
                print (f'{space}     (prompt: {len(full_prompt)} chars {where})')
            if interactive:
                print (f'{space}     (interactive session - codex keeps this terminal)')
            if output_file:
                print (f'{space}     (output: {output_file})')
            print ('')

        start_time = time.time()

        ###########################################################################################
        # Interactive: hand the terminal over to codex.
        # No pipes at all - stdin/stdout/stderr stay attached to this console, so the
        # codex TUI behaves exactly as if it had been started by hand. Nothing can be
        # captured in return, so this path ends here.

        if interactive:
            try:
                returncode = subprocess.call(cmd)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                return self.cm.error(f'cannot run "{codex_path}": {e}', 1)

            duration = time.time() - start_time

            if con:
                print ('')
                if returncode != 0:
                    # Leaving a session early is normal - report the code, do not fail the task
                    print (f'{space}INFO: codex exited with return code {returncode}')
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
        # Non-interactive: run codex on the prompt and collect everything it prints

        try:
            process = subprocess.Popen(
                cmd,
                stdin = subprocess.PIPE,
                stdout = subprocess.PIPE,
                stderr = subprocess.STDOUT,
                text = True,
                encoding = 'utf-8',
                errors = 'replace',
                bufsize = 1,
            )
        except Exception as e:
            return self.cm.error(f'cannot run "{codex_path}": {e}', 1)

        try:
            process.stdin.write(full_prompt)
            process.stdin.close()
        except Exception as e:
            process.kill()
            return self.cm.error(f'cannot send the prompt to codex: {e}', 1)

        # Stream the output while codex works and keep it for the output file
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
            print (f'{space}WARNING: codex did not report any statistics for this run')

        # Description of this run - shared by the output file and the statistics file
        run_info = {
            'task': 'run-codex2',
            'date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'codex': codex_path,
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
            f'codex: {codex_path}',
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
                    data['codex_result'] = run_stats

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
            return self.cm.error(f'codex failed with return code {returncode}', 99)

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
                           line: str,       # one line of the codex "--json" output
                           run_stats: dict, # updated in place with usage, turns and thread ID
    ):
        """
        Turn one codex JSONL event into readable text.

        Args:
            line (str): One line (one JSON event) of the codex output.
            run_stats (dict): Updated in place with 'usage', 'turns' and 'thread_id'.

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

        event_type = event.get('type', '')

        item = event.get('item', {})
        if not isinstance(item, dict):
            item = {}

        item_type = item.get('type', '')

        # Show commands and file changes as soon as codex starts them
        if event_type == 'item.started':
            if item_type == 'command_execution':
                return [self._shorten('[command] ' + str(item.get('command', ''))) + '\n']

            if item_type == 'file_change':
                return [self._describe_file_change(item) + '\n']

            return []

        if event_type == 'item.completed':
            # The answer of the agent (reasoning items are skipped)
            if item_type == 'agent_message':
                text = item.get('text', '')
                return [text.rstrip() + '\n'] if text.strip() != '' else []

            if item_type == 'command_execution':
                exit_code = item.get('exit_code')
                if exit_code:
                    return [f'[command failed with exit code {exit_code}]\n']
                return []

            if item_type == 'file_change':
                if item.get('status') == 'failed':
                    return ['[file change failed]\n']
                return []

            if item_type == 'mcp_tool_call':
                return [self._shorten('[tool: ' + str(item.get('server', '')) + '.'
                                      + str(item.get('tool', '')) + ']') + '\n']

            if item_type == 'web_search':
                return [self._shorten('[web search] ' + str(item.get('query', ''))) + '\n']

            return []

        # Statistics of one turn (a run can have several turns)
        if event_type == 'turn.completed':
            usage = event.get('usage', {})
            if isinstance(usage, dict):
                totals = run_stats.setdefault('usage', {})
                for key in usage:
                    if isinstance(usage[key], int):
                        totals[key] = totals.get(key, 0) + usage[key]

            run_stats['turns'] = run_stats.get('turns', 0) + 1

            return []

        if event_type == 'turn.failed':
            run_stats['error'] = event.get('error', {})
            return [self._shorten('[turn failed] ' + str(event.get('error', ''))) + '\n']

        if event_type == 'thread.started':
            run_stats['thread_id'] = event.get('thread_id', '')
            return []

        if event_type == 'error':
            return [self._shorten('[error] ' + str(event.get('message', event))) + '\n']

        return []


    ############################################################
    def _shorten(self,
                 text: str,      # text to shorten
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
    def _describe_file_change(self,
                              item: dict,  # "file_change" item of a codex event
    ):
        """
        Describe a file change of codex in one line.

        Args:
            item (dict): "file_change" item of a codex event.

        Returns:
            str: One line such as '[file change] add: /path/to/file'.
        """

        changes = item.get('changes', [])
        if not isinstance(changes, list):
            changes = []

        described = []
        for change in changes:
            if isinstance(change, dict):
                described.append(f'{change.get("kind","?")}: {change.get("path","?")}')

        return self._shorten('[file change] ' + ', '.join(described))


    ############################################################
    def _get_tokens(self,
                    run_stats: dict,  # statistics collected from the codex events
    ):
        """
        Summarize the token counters of one prompt.

        Note that codex counts differently from claude: "input_tokens" is the
        whole input including the part served from the cache ("cached_input_tokens"),
        while claude reports the cached tokens as separate buckets. "sent" is
        therefore the input as reported by codex, not a sum.

        Args:
            run_stats (dict): Statistics collected from the codex events.

        Returns:
            dict: Token counters ('input', 'cached', 'cache_write', 'sent',
                  'output', 'reasoning', 'total').
        """

        usage = run_stats.get('usage', {})
        if not isinstance(usage, dict):
            usage = {}

        sent = usage.get('input_tokens', 0) or 0
        cached = usage.get('cached_input_tokens', 0) or 0

        tokens = {
            'input': max(sent - cached, 0),
            'cached': cached,
            'cache_write': usage.get('cache_write_input_tokens', 0) or 0,
            'sent': sent,
            'output': usage.get('output_tokens', 0) or 0,
            'reasoning': usage.get('reasoning_output_tokens', 0) or 0,
        }

        tokens['total'] = tokens['sent'] + tokens['output']

        return tokens


    ############################################################
    def _format_stats(self,
                      run_stats: dict,  # statistics collected from the codex events
    ):
        """
        Format the token statistics of one prompt for the console and the output file.

        Args:
            run_stats (dict): Statistics collected from the codex events ({} if there are none).

        Returns:
            list: Text lines (empty when codex reported no statistics).
        """

        if not run_stats.get('usage'):
            return []

        tokens = self._get_tokens(run_stats)

        stats_lines = [
            'Statistics for this prompt:',
            f'  Tokens sent:     {tokens["sent"]}'
            f' (new: {tokens["input"]}, cached: {tokens["cached"]},'
            f' cache write: {tokens["cache_write"]})',
            f'  Tokens received: {tokens["output"]} (reasoning: {tokens["reasoning"]})',
            f'  Tokens total:    {tokens["total"]}',
        ]

        turns = run_stats.get('turns')
        if turns is not None:
            stats_lines.append(f'  Turns:           {turns}')

        thread_id = run_stats.get('thread_id')
        if thread_id:
            stats_lines.append(f'  Thread ID:       {thread_id}')

        return stats_lines
