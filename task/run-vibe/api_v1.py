"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-vibe - the Mistral Vibe (https://github.com/mistralai/mistral-vibe) sibling of the "run-claude", "run-codex",
"run-opencode", "run-agy" and "run-hermes" tasks of cmeta-aops, with the same flags.

What is specific to vibe (3.0.4, checked with "vibe --help" on 2026-10-30):
- headless mode is "vibe -p <prompt>" or "--prompt-file <path>" (no command-line limit for a long prompt); the
  output is text by default ("--output text|json|streaming"); "--output-dir <dir>" writes export.json on every exit
  (the Vibe version, the effective config, the token usage, the cost, the stop reason, the outcome) and a copy of the
  session journal - this task reads it for the statistics and the session;
- exit codes: 0 finished, 1 usage or configuration, 2 infrastructure, 3 a limit reached (--max-turns, --max-price,
  --max-tokens, --time-limit), 4 aborted;
- "--auto-approve" (--yolo) approves every tool call (--yes); "--agent <name>" picks the approval agent (ask,
  accept-edits, smart-approve, auto-approve, or one of ~/.vibe/agents/);
- "--model <alias>" works in headless mode only, for new sessions: an interactive session takes its model from the
  config (or /model in it), so the flag is dropped there;
- "-c" continues this folder's last session, "--resume <id>" a given one (run-ai resumes by the session of the export);
- the interactive form is "vibe [<initial prompt>]": the prompt preset, then the terminal is the user's; a long one is
  written to a file and vibe is asked to read it first;
- vibe signs in with "vibe --setup" (a Mistral account in the browser, or an API key in the OS keyring or ~/.vibe/.env);
  MISTRAL_API_KEY in the environment works too, and is the user's own: it stays (ctask.drop_provider_variables drops
  only what a parent's gateway put there).

Not checked yet (no Mistral sign-in on the machine where it was written): the exact keys of export.json - they are
read defensively - and the text a headless run prints without a sign-in.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, MAX_PROMPT_ARG_CHARS, prompt_via_file, prompt_via_file_done, drop_provider_variables

OUTPUT_FILE_SUFFIX = '-output.txt'
DEFAULT_OUTPUT_FILE = 'run-vibe-output.txt'

YES_FLAGS = ['--auto-approve']
PERMISSION_FLAGS = ['--auto-approve', '--yolo', '--smart-approve', '--agent']
MODEL_FLAGS = ['--model']

# These make sense in headless mode only (vibe says so for --model); an interactive session drops them
RUN_ONLY_FLAGS = ['--output', '--max-turns', '--max-price', '--max-tokens', '--time-limit', '--prompt-file',
                  '--system-prompt-file', '--output-dir', '--model']

EXIT_CODES = {1: 'a usage or configuration error', 2: 'an infrastructure failure (the network, the provider)',
              3: 'a limit was reached (--max-turns, --max-price, --max-tokens, --time-limit)', 4: 'the run was aborted'}

SIGN_IN_HINT = ('vibe is not signed in: run "vibe --setup" once (cxt run-ai --harness=vibe --login) - a Mistral account in '
                'the browser, or an API key - or set MISTRAL_API_KEY')


def flag_value(flags, names):
    """The value of "<name> value" or "<name>=value" in a command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] in names:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def drop_flags(flags, names):
    """The flags without "<name> value" / "<name>=value" of the given names (a flag that takes no value - none of
    RUN_ONLY_FLAGS - would take its neighbour with it)."""
    out, skip = [], False
    for flag in flags:
        if skip:
            skip = False
            continue
        key = flag.split('=')[0]
        if key in names:
            skip = '=' not in flag
            continue
        out.append(flag)
    return out


def read_export(output_dir):
    """The statistics of vibe's export.json in its --output-dir: the tokens, the cost, the stop reason, the outcome, the
    model and the session - read defensively (the keys were not documented when this was written). {} without one."""
    path = os.path.join(output_dir, 'export.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}

    def find(obj, keys):
        """The first value under one of the keys, anywhere in the export (a usage block may be nested)."""
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] not in (None, ''):
                    return obj[k]
            for v in obj.values():
                got = find(v, keys)
                if got not in (None, ''):
                    return got
        elif isinstance(obj, list):
            for v in obj:
                got = find(v, keys)
                if got not in (None, ''):
                    return got
        return None

    stats = {'raw': data}
    tokens = {}
    for name, keys in (('input', ('prompt_tokens', 'input_tokens', 'session_prompt_tokens')),
                       ('output', ('completion_tokens', 'output_tokens', 'session_completion_tokens')),
                       ('total_reported', ('total_tokens', 'session_total_tokens'))):
        value = find(data, keys)
        if isinstance(value, (int, float)):
            tokens[name] = value
    if tokens:
        stats['tokens'] = tokens
    for name, keys in (('cost_usd', ('cost', 'session_cost', 'total_cost', 'cost_usd')),
                       ('stop_reason', ('stop_reason', 'reason')), ('outcome', ('outcome', 'status')),
                       ('model', ('active_model', 'model')), ('session_id', ('session_id', 'sessionId', 'session')),
                       ('turns', ('turns', 'num_turns', 'steps'))):
        value = find(data, keys)
        if value not in (None, '') and not isinstance(value, (dict, list)):
            stats[name] = value
    return stats


class CTask(InitCTask):
    """run-vibe: run Mistral Vibe on an assembled prompt, headless or interactive, and record the output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self,
            ctx: dict,                      # cMeta context
            prompt: str = '',               # prompt text
            prompt_file: str = '',          # file with the prompt text
            long_prompt_file: str = '',     # where a prompt too long for the command line is written for vibe to read (interactive)
            interactive: bool = False,      # preset the prompt in an interactive vibe session
            i: bool = False,                # short alias of "interactive" (--i / -i)
            yes: bool = False,              # approve every tool call (--auto-approve)
            reproducible: bool = False,     # warn when no model is pinned after "--"
            stats: bool = False,            # print the token usage and the cost at the end (from vibe's export)
            stats_file: str = '',           # record the statistics to this file (.json = JSON, otherwise text)
            output_file: str = '',          # where to record the output
            skip_output_file: bool = False, # do not record the output at all
            append_output_file: bool = False, # append to the output file instead of overwriting it
            skip_output_header: bool = False, # do not add the summary header to the output file
            unparsed: list = None,          # extra flags for vibe (everything after "--")
    ):
        """Assemble a prompt and run Mistral Vibe on it (vibe -p / --prompt-file), or open an interactive session (vibe [prompt])."""
        con = ctx['control'].get('con', False)

        # What a parent's gateway put into the environment never reaches this run (its key, its URL, its model
        # names: a session through a company gateway that starts another agent); the user's own keys stay -
        # MISTRAL_API_KEY is one of vibe's ways in (ctask.drop_provider_variables)
        dropped = drop_provider_variables('vibe')
        if dropped and con:
            print('AI gateway: none for vibe - %s of a parent\'s gateway left the environment of this run' % ', '.join(dropped))
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''
        _global = ctx['tasks']['global']

        vibe_path = (_global.get('vibe') or {}).get('path', '')
        if not vibe_path:
            return self.cm.error('the "vibe" tool was not set up (no path in the global context)', 1)

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
                print(f'{space}INFO: no prompt was given (--prompt / --prompt_file) - opening an interactive vibe session')

        # ---- the output and statistics files
        if interactive:
            if con and (stats or stats_file or output_file):
                print('')
                print(f'{space}INFO: --interactive keeps the terminal - the output and the statistics of the session cannot be collected')
            stats, stats_file = False, ''
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
        base_cmd = [vibe_path]
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

        if reproducible and con and '--model' not in extra_keys:
            print('')
            print(f'{space}WARNING: --reproducible: no --model pinned - the active model of vibe\'s config decides')
            print(f'{space}         pass it after "--", i.e. --model <alias> (an alias of ~/.vibe/config.toml)')

        flags += extra_flags

        # vibe's export (the statistics, the session): into a folder of its own unless one was asked for after "--"
        export_dir, own_export = '', False
        if not interactive:
            export_dir = flag_value(extra_flags, ['--output-dir'])
            if not export_dir:
                export_dir = tempfile.mkdtemp(prefix = 'run-vibe-export-')
                own_export = True
                flags += ['--output-dir', export_dir]

        # the prompt: headless as -p <text>, or --prompt-file when it is long or comes from --prompt_file alone;
        # interactive as the initial prompt, a long one in a file vibe is asked to read first
        prompt_path, own_prompt = '', False
        pr = prompt_via_file(full_prompt, 'vibe', when=interactive, path=long_prompt_file, prompt_file=prompt_file,
                             con=con, space=space)
        if pr['return'] > 0:
            return pr
        if interactive:
            dropped = [x for x in flags if x.split('=')[0] in RUN_ONLY_FLAGS]
            if dropped:
                flags = drop_flags(flags, RUN_ONLY_FLAGS)
                if con:
                    print('')
                    print(f'{space}INFO: vibe takes these in headless mode only, so they are dropped from the session: {" ".join(dropped)}')
            cmd = base_cmd + flags + ([pr['text']] if full_prompt else [])
        else:
            if prompt_file and not prompt.strip():
                prompt_path = prompt_file
            elif len(full_prompt) > MAX_PROMPT_ARG_CHARS:
                fd, prompt_path = tempfile.mkstemp(prefix = 'run-vibe-prompt-', suffix = '.md')
                with os.fdopen(fd, 'w', encoding = 'utf-8', newline = '\n') as f:
                    f.write(full_prompt)
                own_prompt = True
            cmd = base_cmd + flags + (['--prompt-file', prompt_path] if prompt_path else ['-p', full_prompt])

        if con:
            print('')
            shown = ' '.join(base_cmd + flags)
            if interactive:
                shown += ' <prompt>' if full_prompt else ''
            else:
                shown += f' --prompt-file {prompt_path}' if prompt_path else ' -p <prompt>'
            print(f'{space}RUN: {shown}')
            if full_prompt:
                print(f'{space}     (prompt: {len(full_prompt)} chars' + (f', in a file vibe is asked to read first: {pr["file"]}' if pr['file'] else '') + ')')
            if interactive:
                print(f'{space}     (interactive session - vibe keeps this terminal)')
            if output_file:
                print(f'{space}     (output: {output_file})')
            print('')

        if not os.environ.get('CMETA_GENERATOR'):
            from task_c36be4b9314a45e0.api.ctask import GENERATOR_VIA_KEY, generator_via
            rec = {'method': 'agent', 'agent': 'Mistral Vibe', GENERATOR_VIA_KEY: generator_via()}
            model = flag_value(extra_flags, MODEL_FLAGS)
            if model:
                rec['model'] = model
            os.environ['CMETA_GENERATOR'] = json.dumps(rec)

        start_time = time.monotonic()

        def clean():
            prompt_via_file_done(pr)
            if own_prompt:
                try:
                    os.remove(prompt_path)
                except OSError:
                    pass

        # ---- interactive: hand the terminal over
        if interactive:
            try:
                returncode = subprocess.call(cmd)
            except KeyboardInterrupt:
                returncode = 1
            except Exception as e:
                clean()
                return self.cm.error(f'cannot run "{vibe_path}": {e}', 1)
            clean()
            duration = time.monotonic() - start_time
            if con:
                print('')
                if returncode != 0:
                    print(f'{space}INFO: vibe exited with return code {returncode}')
                print(f'{space}Duration: {duration:.1f} sec')
            return {'return': 0, 'output': '', 'output_file': '', 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                    'returncode': returncode, 'duration': duration, 'interactive': True, 'stats_file': ''}

        # ---- headless: run and collect everything
        try:
            process = subprocess.Popen(cmd, stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                                       text = True, encoding = 'utf-8', errors = 'replace', bufsize = 1)
        except Exception as e:
            clean()
            return self.cm.error(f'cannot run "{vibe_path}": {e}', 1)

        lines = []
        try:
            for line in process.stdout:
                lines.append(line)
                if con:
                    print(line, end = '', flush = True)
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            clean()
            return self.cm.error('interrupted by the user', 1)
        returncode = process.wait()
        clean()
        duration = time.monotonic() - start_time
        output = ''.join(lines)

        run_stats = read_export(export_dir) if export_dir else {}
        if own_export:
            shutil.rmtree(export_dir, ignore_errors = True)
        stats_lines = self._format_stats(run_stats)
        if stats and not stats_lines and con:
            print('')
            print(f'{space}WARNING: vibe did not report any statistics for this run')

        run_info = {'task': 'run-vibe', 'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'vibe': vibe_path,
                    'prompt_file': prompt_file, 'prompt_size': len(full_prompt), 'extra_flags': flags,
                    'duration': round(duration, 1), 'return_code': returncode, 'output_file': output_file}
        info_lines = [f'task: {run_info["task"]}', f'date: {run_info["date"]}', f'vibe: {vibe_path}',
                      f'prompt file: {prompt_file if prompt_file else "(none)"}', f'prompt size: {len(full_prompt)} chars',
                      f'extra flags: {" ".join(flags) if flags else "(none)"}', f'duration: {duration:.1f} sec',
                      f'return code: {returncode}']

        if output_file:
            text = output if skip_output_header else '\n'.join(['# ' + x for x in info_lines + stats_lines] + ['', '']) + output
            if append_output_file and os.path.isfile(output_file):
                try:
                    with open(output_file, 'a', encoding = 'utf-8', newline = '\n') as f:
                        f.write('\n' + text)
                except Exception as e:
                    return self.cm.error(f'cannot append to the output file {output_file}: {e}', 1)
            else:
                r = self.cm.utils.files.write_file(output_file, text, file_format = 'text', encoding = 'utf-8')
                if self.cm.catch_error(r):
                    return r
            if con:
                print('')
                print(f'{space}Output was recorded to "{output_file}"')

        if stats_file and run_stats:
            if os.path.splitext(stats_file)[1].lower() == '.json':
                data = dict(run_info, tokens = self._get_tokens(run_stats), vibe_export = run_stats.get('raw'))
                r = self.cm.utils.files.write_file(stats_file, data, file_format = 'json', sort_keys = False)
            else:
                r = self.cm.utils.files.write_file(stats_file, '\n'.join(info_lines + stats_lines) + '\n', file_format = 'text', encoding = 'utf-8')
            if self.cm.catch_error(r):
                return r
        elif stats_file:
            stats_file = ''

        if con and stats and stats_lines:
            print('')
            for x in stats_lines:
                print(f'{space}{x}')
        if con:
            print('')
            print(f'{space}Duration: {duration:.1f} sec')

        if returncode != 0:
            low = output.lower()
            hint = ''
            if 'api key' in low or 'api_key' in low or 'unauthorized' in low or '401' in low or '--setup' in low:
                hint = ' (' + SIGN_IN_HINT + ')'
            what = EXIT_CODES.get(returncode, 'an error')
            return self.cm.error(f'vibe failed with return code {returncode}: {what}{hint}', 99)

        result = {'return': 0, 'output': output, 'output_file': output_file, 'prompt': full_prompt, 'long_prompt_file': pr['file'],
                  'returncode': returncode, 'duration': duration, 'interactive': False}
        if run_stats:
            result['stats'] = {k: v for k, v in run_stats.items() if k != 'raw'}
            result['tokens'] = self._get_tokens(run_stats)
            if run_stats.get('session_id'):
                result['conversation_id'] = str(run_stats['session_id'])
        result['stats_file'] = stats_file
        return result

    @staticmethod
    def _get_tokens(run_stats):
        c = run_stats.get('tokens') or {}
        tokens = {'input': c.get('input', 0) or 0, 'cache_read': 0, 'output': c.get('output', 0) or 0, 'reasoning': 0, 'tool': 0}
        tokens['sent'] = tokens['input']
        tokens['total'] = c.get('total_reported') or (tokens['input'] + tokens['output'])
        cost = run_stats.get('cost_usd')
        tokens['cost_usd'] = cost if isinstance(cost, (int, float)) else 0
        return tokens

    def _format_stats(self, run_stats):
        if not run_stats.get('tokens') and run_stats.get('cost_usd') is None:
            return []
        t = self._get_tokens(run_stats)
        lines = ['Statistics for this prompt:',
                 f'  Tokens sent:     {t["sent"]}',
                 f'  Tokens received: {t["output"]}',
                 f'  Tokens total:    {t["total"]}']
        if isinstance(run_stats.get('cost_usd'), (int, float)):
            lines.append(f'  Cost:            {run_stats["cost_usd"]:.4f} USD')
        for key, label in (('model', 'Model'), ('turns', 'Turns'), ('stop_reason', 'Stop reason'), ('outcome', 'Outcome')):
            if run_stats.get(key) not in (None, ''):
                lines.append(f'  {label + ":":<17}{run_stats[key]}')
        if run_stats.get('session_id'):
            lines.append(f'  Session:         {run_stats["session_id"]} (vibe --resume <id> continues it)')
        return lines
