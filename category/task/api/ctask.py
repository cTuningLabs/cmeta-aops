"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from pathlib import Path
import os
import logging
import tempfile

# The longest prompt that travels as a command line argument. An interactive agent session preloads its
# first prompt that way (the terminal UI owns stdin), and some CLIs have no stdin mode at all. An OS caps a
# command line: 32767 characters for the whole line on Windows, 128 KB per argument on Linux. Over this
# length a prompt is written to a file and the argument becomes a one-line request to read it first
# (prompt_via_file below); the session reads it, follows it and stays interactive as before.
MAX_PROMPT_ARG_CHARS = 30000


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
 
