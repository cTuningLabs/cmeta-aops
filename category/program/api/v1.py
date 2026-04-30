"""
Copyright (C) 2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from cmeta.category import InitCategory

# We save some internal names to be used as cMeta command
_compile = compile

class Category(InitCategory):
    """
    """

    def __init__(
        self,
        *args,  # Positional argument value.
        **kwargs,  # Value for kwargs.
    ):
        """
        __init__ function.

        Args:
            *args: Positional argument value.
            **kwargs: Value for kwargs.

        Returns:
            dict: Operation result.

        Raises:
            Exception: Propagated runtime errors, if any.
        """
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def compile(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING program api v1 compile")

        input('xyz')

        p = self._prepare_input_from_params(params, base = False)

        p['category'] = self.cmeta['uses_categories']['task']
        p['command'] = 'run'
        p['name'] = params.get('arg1')
        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']

        return self.cm.access(p)

    ############################################################
    def run(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING program api v1 run")

        input('xyz')

        ctx = params['ctx']

        p = self._prepare_input_from_params(params)

        unparsed = p.pop('unparsed', [])

        # Setup tool
        p.update({'category': self.cmeta['uses_categories']['task'],
                  'command': 'run',
                  'ctx': ctx,
        })

        pp = copy.deepcopy(p)

        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']
        p['name'] = params.get('arg1')

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        cmd = r['cmd']

        for param in unparsed:
            param = param.strip()
            if ' ' in param and not param.startswith('"'):
                param = '"' + param + '"'

            cmd += ' ' + param
        
        # Clean some params (needed for "setup tool" task but not for "cmd" task)

        for k in ['detect','install', 'build', 'skip_install', 'skip_detect', 'skip_build',
                  'name', 'tool_tags', 'tool_api_ver', 'tool_path', 'paths', 'with',
                  'version']:
            if k in pp:
                del(pp[k])

        pp['arg1'] = self.cmeta['uses_artifacts']['tool::cmd']
        pp['cmd'] = cmd
        pp['ctx'] = ctx
        pp['print_extra_line'] = True

        r = self.cm.access(pp)
        self.cm.catch_error(r)

        return r
