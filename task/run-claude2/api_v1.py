"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import re
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Suffix appended to the prompt file name (without extension) when
# --output_file is not given
OUTPUT_FILE_SUFFIX = '-output.txt'

# Output file used when there is no prompt file to derive the name from
DEFAULT_OUTPUT_FILE = 'run-claude2-output.txt'

# Flags added by --yes to answer "yes" to every claude question (edits, Bash, ...).
# The workspace trust dialog ("do you trust the files in this folder") does not
# need a flag - claude always skips it in non-interactive mode (-p).
YES_FLAGS = ['--permission-mode', 'bypassPermissions']

# cMeta repositories added to the claude context (one "--add-dir <path>" each, the path
# resolved through "cx repo find" - so the same command works on every machine): the
# repository this task lives in, plus the aliases in the "agent_add_repos" key of the local
# cMeta config ("cx config set default --meta.agent_add_repos=alias,alias" - once per
# machine). --add_repos=<alias,alias> adds more; --add_repos=none adds nothing at all.
# Claude Code then reads their CLAUDE.md / AGENTS.md and the skills under .claude/skills/.
CONFIG_ADD_REPOS_KEY = 'agent_add_repos'

# If the user already passed one of these after "--", --yes leaves it alone
PERMISSION_FLAGS = ['--permission-mode', '--dangerously-skip-permissions',
                    '--allow-dangerously-skip-permissions']

# Flags added by --stats. The plain text output of "claude -p" carries no token
# counters, so we ask for the JSON event stream instead and turn it back into
# readable text ("--verbose" is required by claude for stream-json with "-p").
# The last event of that stream ("result") has the usage and the cost.
STATS_FLAGS = ['--output-format', 'stream-json', '--verbose']

# If the user already chose an output format after "--", --stats leaves it alone
OUTPUT_FORMAT_FLAGS = ['--output-format']

# Flags added by --reproducible to cut the run-to-run variation of claude:
#   --exclude-dynamic-system-prompt-sections
#       moves the per-machine sections (cwd, env, memory paths and the git status,
#       which changes while claude edits files) out of the system prompt
#   --strict-mcp-config
#       ignores whatever MCP servers happen to be configured on this host
# Note that claude output is never fully deterministic - the CLI has no
# temperature or seed flag and the API has no seed parameter.
REPRODUCIBLE_FLAGS = ['--exclude-dynamic-system-prompt-sections', '--strict-mcp-config']

# --reproducible also needs an exact model version ("claude-haiku-4-5-20251001"),
# since aliases such as "haiku" move to another model over time
MODEL_FLAGS = ['--model']
EXACT_MODEL_PATTERN = r'-\d{8}$'

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
            interactive: bool = False,      # preload the prompt, then stay in the interactive claude session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # answer "yes" to all claude questions (edits, Bash, ...)
            reproducible: bool = False,     # cut the run-to-run variation of claude
            stats: bool = False,            # print token usage and cost at the end
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            add_repos: str = '',            # cMeta repos to add to the claude context ("alias,alias"; "none" = not even the defaults)
            unparsed: list = None,          # extra flags for claude (everything after "--")
    ):

        """
        Assemble a prompt, run the "claude" CLI non-interactively (claude -p) and exit.

        The prompt is the text of "prompt_file" (when given), then a new line,
        then "prompt".

        With "interactive" (or its short alias "i"), claude is started as a normal
        interactive session instead: the assembled prompt is preloaded as the first
        message and claude keeps the terminal afterwards, so the preset prompt can
        be followed up on by hand. This is also what happens when no prompt is given
        at all - an empty prompt opens a session rather than failing, so a plain
        "cx task run run-claude2" is just "claude" with the flags below. Since an
        interactive session owns the terminal, nothing can be captured: "stats",
        "stats_file" and "output_file" are switched off, the result carries no output,
        and a non-zero exit code of claude is reported but not turned into an error
        (quitting a session is normal).

        The output is streamed to the console while claude runs and is recorded
        into "output_file". When "output_file" is not given, it defaults to the
        prompt file name without extension + "-output.txt" (or
        "run-claude2-output.txt" when there is no prompt file).

        With "yes", claude runs fully unattended: every permission question
        (file edits, Bash, ...) is answered "yes" via
        "--permission-mode bypassPermissions". The workspace trust question is
        skipped by claude itself in non-interactive mode ("-p"). A permission
        flag passed after "--" always wins over "yes".

        With "reproducible", the per-machine parts of the claude session are
        removed so that two runs of the same prompt start from the same input
        (see REPRODUCIBLE_FLAGS). This cuts the variation between runs but cannot
        remove it: claude output is never fully deterministic - neither the CLI
        nor the API offers a temperature or a seed. Pass an exact model version
        after "--" ("--model claude-haiku-4-5-20251001") to complete the setup.

        With "stats", claude is asked for its JSON event stream instead of plain
        text, so that the token counters and the cost of this prompt can be
        printed (and recorded) at the end. The output stays readable - the events
        are turned back into text while claude runs. "stats_file" records the same
        statistics to a file (as JSON when its extension is ".json", otherwise as
        the printed text) and turns "stats" on by itself.

        Args:
            ctx (dict): cMeta context.
            prompt (str): Prompt text (appended after the prompt file text).
            prompt_file (str): File with the prompt text (read as UTF-8).
            interactive (bool): If True, preload the prompt (optional here) and stay in the claude session.
            i (bool): Short alias of "interactive".
            yes (bool): If True, answer "yes" to all claude questions and never prompt.
            reproducible (bool): If True, cut the run-to-run variation of claude (never zero).
            stats (bool): If True, print token usage and cost of this prompt at the end.
            stats_file (str): File to record the statistics (JSON if it ends with ".json"); implies "stats".
            output_file (str): File to record the output (overrides the default name).
            skip_output_file (bool): If True, do not record the output to a file.
            append_output_file (bool): If True, append to the output file instead of overwriting it.
            skip_output_header (bool): If True, do not add the summary header to the output file.
            add_repos (str): cMeta repositories to add to the claude context, comma-separated aliases; the
                defaults (the repository of this task, then the "agent_add_repos" key of the local cMeta
                config) are added whenever plugged in; "none" adds nothing. Each becomes "--add-dir <path>"
                with the path resolved by cMeta.
            unparsed (list): Extra flags passed to claude (everything after "--").

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **output** (str): Full output of claude ('' if `interactive`).
                - **output_file** (str): Where the output was recorded ('' if skipped).
                - **prompt** (str): The assembled prompt sent to claude.
                - **returncode** (int): Return code of the claude CLI.
                - **duration** (float): Run time in seconds.
                - **interactive** (bool): True if claude was run as an interactive session.
                - **stats** (dict): Raw "result" event of claude (usage, cost, ...) if `stats`.
                - **tokens** (dict): Sent/output/total tokens and cost in USD if `stats`.
                - **stats_file** (str): Where the statistics were recorded ('' if none).
        """

        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']

        # Path to the claude CLI detected/installed by the "setup" task (see _desc.yaml)
        claude_path = _global.get('claude', {}).get('path', '')

        if not claude_path:
            return self.cm.error('the "claude" tool was not set up (no path in the global context)', 1)

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
        # session instead of failing (an interactive claude is useful on its own)
        if full_prompt == '' and not interactive:
            interactive = True

            if con:
                print ('')
                print (f'{space}INFO: no prompt was given (--prompt / --prompt_file) - '
                       f'opening an interactive claude session')

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
        # Build the claude command line.
        #
        # Non-interactive ("-p"): the assembled prompt goes through stdin rather than
        # the command line - a prompt file can easily be longer than the OS limit.
        # Interactive: claude owns stdin, so the prompt can only travel as the
        # trailing positional argument ("claude [options] [prompt]").

        base_cmd = [claude_path] if interactive else [claude_path, '-p']

        # Flags added on top of base_cmd - kept apart so that they can be reported as they are
        flags = []

        extra_flags = [str(u) for u in unparsed] if unparsed else []

        # cMeta repositories -> "--add-dir <path>": Claude Code reads their CLAUDE.md, AGENTS.md and skills.
        # Portable: the alias is resolved here, on this machine, through cMeta's own registry.
        wanted = [x.strip() for x in str(add_repos or '').split(',') if x.strip()]
        if 'none' in [x.lower() for x in wanted]:
            wanted = [x for x in wanted if x.lower() != 'none']
            defaults = []
        else:
            defaults = [x for x in self._default_add_repos() if x not in wanted]
        user_dirs = [os.path.normcase(os.path.abspath(extra_flags[k + 1])) for k, x in enumerate(extra_flags) if x == '--add-dir' and k + 1 < len(extra_flags)]
        added, missing = [], []
        for alias in wanted + defaults:
            rr = self.cm.access({'category': 'repo', 'command': 'find', 'arg1': alias, 'con': False})
            arts = rr.get('artifacts') or [] if rr.get('return', 1) == 0 else []
            path = arts[0].get('path') if len(arts) == 1 else None
            if path and os.path.isdir(path):
                if os.path.normcase(os.path.abspath(path)) not in user_dirs:
                    flags += ['--add-dir', path]
                    added.append((alias, path))
            elif alias in wanted:
                missing.append(alias)
        if con and (added or missing):
            print ('')
            for alias, path in added:
                print (f'{space}INFO: repository added to the claude context: {alias} ({path})')
            for alias in missing:
                print (f'{space}WARNING: --add_repos: repository "{alias}" is not plugged in (cx repo list) - skipped')

        if yes:
            # Do not fight with a permission flag that the user passed after "--"
            user_permission_flags = [x for x in extra_flags
                                     if x.split('=')[0] in PERMISSION_FLAGS]

            if user_permission_flags:
                if con:
                    print ('')
                    print (f'{space}INFO: --yes is ignored - permission flags were '
                           f'passed after "--": {" ".join(user_permission_flags)}')
            else:
                flags += YES_FLAGS

        if reproducible:
            # Add only what the user did not pass after "--" already
            flags += [x for x in REPRODUCIBLE_FLAGS
                      if x not in [y.split('=')[0] for y in extra_flags]]

            # The model must be pinned too - and only the user knows which one to use
            model = ''
            for index, flag in enumerate(extra_flags):
                if flag.split('=')[0] in MODEL_FLAGS:
                    if '=' in flag:
                        model = flag.split('=', 1)[1]
                    elif index + 1 < len(extra_flags):
                        model = extra_flags[index + 1]
                    break

            if con and not re.search(EXACT_MODEL_PATTERN, model):
                print ('')
                if model:
                    print (f'{space}WARNING: --reproducible: model "{model}" is an alias that will '
                           f'move to another model over time')
                else:
                    print (f'{space}WARNING: --reproducible: no model was pinned - the default '
                           f'model can change between runs')
                print (f'{space}         pass an exact version after "--", i.e. '
                       f'--model claude-haiku-4-5-20251001')

        # When claude prints its JSON event stream we must turn it back into text
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
                print (f'{space}     (interactive session - claude keeps this terminal)')
            if output_file:
                print (f'{space}     (output: {output_file})')
            print ('')

        start_time = time.time()

        ###########################################################################################
        # Interactive: hand the terminal over to claude.
        # No pipes at all - stdin/stdout/stderr stay attached to this console, so the
        # claude TUI behaves exactly as if it had been started by hand. Nothing can be
        # captured in return, so this path ends here.

        if interactive:
            try:
                returncode = subprocess.call(cmd)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                return self.cm.error(f'cannot run "{claude_path}": {e}', 1)

            duration = time.time() - start_time

            if con:
                print ('')
                if returncode != 0:
                    # Leaving a session early is normal - report the code, do not fail the task
                    print (f'{space}INFO: claude exited with return code {returncode}')
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
        # Non-interactive: run claude on the prompt and collect everything it prints

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
            return self.cm.error(f'cannot run "{claude_path}": {e}', 1)

        try:
            process.stdin.write(full_prompt)
            process.stdin.close()
        except Exception as e:
            process.kill()
            return self.cm.error(f'cannot send the prompt to claude: {e}', 1)

        # Stream the output while claude works and keep it for the output file
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

        # If claude streamed no assistant text (rare), fall back to the final result event
        if parse_stream and output.strip() == '' and isinstance(run_stats.get('result'), str):
            output = run_stats['result'].rstrip() + '\n'

        stats_lines = self._format_stats(run_stats)

        if stats and not stats_lines and con:
            print ('')
            print (f'{space}WARNING: claude did not report any statistics for this run')

        # Description of this run - shared by the output file and the statistics file
        run_info = {
            'task': 'run-claude2',
            'date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'claude': claude_path,
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
            f'claude: {claude_path}',
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
                    data['claude_result'] = run_stats

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
            return self.cm.error(f'claude failed with return code {returncode}', 99)

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
                           line: str,       # one line of the claude "stream-json" output
                           run_stats: dict, # updated in place with the final "result" event
    ):
        """
        Turn one claude "stream-json" event into readable text.

        Args:
            line (str): One line (one JSON event) of the claude output.
            run_stats (dict): Updated in place with the final "result" event (usage, cost, ...).

        Returns:
            list: Text chunks to print and record (empty for events with nothing to show).
        """

        line = line.strip()

        if line == '':
            return []

        try:
            event = json.loads(line)
        except Exception:
            # Not a JSON event (a warning from the CLI, ...) - keep it as it is
            return [line + '\n']

        event_type = event.get('type', '')

        # Assistant messages: text blocks and tool calls (thinking blocks are skipped)
        if event_type == 'assistant':
            texts = []

            for block in event.get('message', {}).get('content', []):
                block_type = block.get('type', '')

                if block_type == 'text':
                    text = block.get('text', '')
                    if text.strip() != '':
                        texts.append(text.rstrip() + '\n')

                elif block_type == 'tool_use':
                    texts.append(self._describe_tool(block) + '\n')

            return texts

        # The last event of the stream carries the statistics of the whole prompt
        if event_type == 'result':
            run_stats.update(event)

        return []


    ############################################################
    def _describe_tool(self,
                       block: dict,  # "tool_use" content block of an assistant message
    ):
        """
        Describe a tool call of claude in one line.

        Args:
            block (dict): "tool_use" content block of an assistant message.

        Returns:
            str: One line such as '[tool: Bash] git status'.
        """

        name = block.get('name', '?')

        tool_input = block.get('input', {})
        if not isinstance(tool_input, dict):
            tool_input = {}

        hint = ''
        for key in ['command', 'file_path', 'path', 'pattern', 'url', 'description']:
            if tool_input.get(key):
                hint = str(tool_input[key]).replace('\n', ' ')
                break

        if len(hint) > 100:
            hint = hint[:100] + ' ...'

        return f'[tool: {name}] {hint}'.rstrip()


    ############################################################
    def _default_add_repos(self) -> list:
        """
        The repositories added to the claude context unless --add_repos says "none":
        the repository this task lives in (the first _cmr.yaml / _cmr.json above the task
        folder), then the aliases in the "agent_add_repos" key of the local cMeta config
        (a comma-separated string or a list) - in that order, without duplicates.

        Returns:
            list: Repository aliases (may be empty).
        """
        import yaml

        defaults = []

        # 1) the repository that carries this task
        d = os.path.dirname(os.path.abspath(self.path))
        while True:
            found = [os.path.join(d, x) for x in ('_cmr.yaml', '_cmr.json') if os.path.isfile(os.path.join(d, x))]
            if found:
                try:
                    with open(found[0], encoding='utf-8') as f:
                        meta = yaml.safe_load(f) or {}
                    alias = str(meta.get('artifact', '')).split(',')[0].strip()
                    if alias:
                        defaults.append(alias)
                except Exception:
                    pass
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent

        # 2) the local cMeta config: cx config set default --meta.agent_add_repos=alias,alias
        r = self.cm.access({'category': 'config,cc6bfe174be847ed', 'command': 'get',
                            'arg1': 'default', 'con': False})
        cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
        extra = cfg.get(CONFIG_ADD_REPOS_KEY, []) or []
        if isinstance(extra, str):
            extra = [x.strip() for x in extra.split(',') if x.strip()]
        for alias in extra:
            alias = str(alias).strip()
            if alias and alias not in defaults:
                defaults.append(alias)

        return defaults

    ############################################################
    def _get_tokens(self,
                    run_stats: dict,  # final "result" event of claude
    ):
        """
        Summarize the token counters of one prompt.

        "sent" is everything claude sent to the model: new input tokens, tokens
        written to the prompt cache and tokens read back from it.

        Args:
            run_stats (dict): Final "result" event of claude.

        Returns:
            dict: Token counters ('input', 'cache_write', 'cache_read', 'sent',
                  'output', 'total') and 'cost_usd'.
        """

        usage = run_stats.get('usage', {})
        if not isinstance(usage, dict):
            usage = {}

        tokens = {
            'input': usage.get('input_tokens', 0) or 0,
            'cache_write': usage.get('cache_creation_input_tokens', 0) or 0,
            'cache_read': usage.get('cache_read_input_tokens', 0) or 0,
            'output': usage.get('output_tokens', 0) or 0,
        }

        tokens['sent'] = tokens['input'] + tokens['cache_write'] + tokens['cache_read']
        tokens['total'] = tokens['sent'] + tokens['output']
        tokens['cost_usd'] = run_stats.get('total_cost_usd', 0) or 0

        return tokens


    ############################################################
    def _format_stats(self,
                      run_stats: dict,  # final "result" event of claude
    ):
        """
        Format the token/cost statistics of one prompt for the console and the output file.

        Args:
            run_stats (dict): Final "result" event of claude ({} if there is none).

        Returns:
            list: Text lines (empty when claude reported no statistics).
        """

        if not run_stats:
            return []

        tokens = self._get_tokens(run_stats)

        stats_lines = [
            'Statistics for this prompt:',
            f'  Tokens sent:     {tokens["sent"]}'
            f' (new: {tokens["input"]}, cache write: {tokens["cache_write"]},'
            f' cache read: {tokens["cache_read"]})',
            f'  Tokens received: {tokens["output"]}',
            f'  Tokens total:    {tokens["total"]}',
        ]

        num_turns = run_stats.get('num_turns')
        if num_turns is not None:
            stats_lines.append(f'  Turns:           {num_turns}')

        if run_stats.get('total_cost_usd') is not None:
            stats_lines.append(f'  Cost:            {tokens["cost_usd"]:.4f} USD')

        api_ms = run_stats.get('duration_api_ms')
        if api_ms:
            stats_lines.append(f'  API time:        {api_ms/1000:.1f} sec')

        # Per-model breakdown (a run can use several models, i.e. with sub-agents)
        model_usage = run_stats.get('modelUsage', {})
        if isinstance(model_usage, dict):
            for model in sorted(model_usage):
                mu = model_usage[model]
                if not isinstance(mu, dict):
                    continue
                stats_lines.append(
                    f'  Model {model}:'
                    f' sent={mu.get("inputTokens",0)+mu.get("cacheCreationInputTokens",0)+mu.get("cacheReadInputTokens",0)},'
                    f' received={mu.get("outputTokens",0)},'
                    f' cost={mu.get("costUSD",0):.4f} USD')

        session_id = run_stats.get('session_id')
        if session_id:
            stats_lines.append(f'  Session ID:      {session_id}')

        return stats_lines
