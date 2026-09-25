"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask


def _flag_value(flags, name):
    """The value of "--name value" or "--name=value" in a claude command line, or ''."""
    for index, flag in enumerate(flags):
        if flag.split('=')[0] == name:
            if '=' in flag:
                return flag.split('=', 1)[1]
            if index + 1 < len(flags):
                return flags[index + 1]
    return ''


def _agent_generator(claude_path, flags):
    """
    The CMETA_GENERATOR record of a claude session: the agent and its version, and the model and
    effort (or thinking budget) it was started with. A model switched inside the session is not seen.
    """
    rec = {'method': 'agent', 'agent': 'Claude Code'}
    try:
        out = subprocess.run([claude_path or 'claude', '--version'], capture_output=True, text=True,
                             timeout=30).stdout.strip()
        if out[:1].isdigit():
            rec['agent'] = 'Claude Code ' + out.split()[0]
    except Exception:
        pass
    model = _flag_value(flags, '--model')
    if model:
        rec['model'] = model
    effort = _flag_value(flags, '--effort')
    if effort:
        rec['effort'] = effort
    elif os.environ.get('MAX_THINKING_TOKENS'):
        rec['thinking_budget'] = os.environ['MAX_THINKING_TOKENS']
    return rec


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def set_generator(self, ctx, desc = None, params = None, extra_desc_params = None):
        """
        Provenance (the "internal_func" step before claude starts): an artifact claude creates
        through cMeta records how it was made (the _cmeta "generator"), and one it updates records
        it as "last_generator". A task that runs claude may have set CMETA_GENERATOR already
        (method "task", its log, ...) - it is kept then.
        """
        params = params or {}

        if not os.environ.get('CMETA_GENERATOR'):
            claude_path = ctx['tasks']['global'].get('claude', {}).get('path', '')

            unparsed = params.get('unparsed') or []
            if isinstance(unparsed, str):
                unparsed = unparsed.split()
            flags = [str(u) for u in unparsed]

            value = json.dumps(_agent_generator(claude_path, flags))
            os.environ['CMETA_GENERATOR'] = value

            # The cmd step builds claude's environment from the host snapshot taken at bootstrap
            # plus the aggregated env - so the record must go into the aggregated env as well
            ctx['tasks']['aggregated'].setdefault('env', {})['CMETA_GENERATOR'] = value

        return {'return': 0}
