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


def generator_via():
    """'cmeta <version>' of the engine this task runs in ('cmeta' when the version cannot be read)."""
    try:
        from cmeta.version import __version__
        return 'cmeta ' + str(__version__)
    except Exception:
        return 'cmeta'


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
 
