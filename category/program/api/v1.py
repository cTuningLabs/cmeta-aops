"""
Copyright (C) 2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import shutil

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

        p = self._prepare_input_from_params(params, base = False)

        p['command'] = 'run'
        p['skip_run'] = True

        return self.cm.access(p)

    ############################################################
    def run(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING program api v1 run")

        ctx = params['ctx']

        p = self._prepare_input_from_params(params)

        arg1 = p.pop('arg1', None)
        arg2 = p.pop('arg2', None)

        # Setup tool
        p.update({
            'category': self.cmeta['uses_categories']['task'],
            'command': 'run',
            'ctx': ctx,
            'arg1': self.cmeta['uses_artifacts']['task::compile-and-run-program'],
        })

        if arg1: p['name'] = arg1
        if arg2: p['compute'] = arg2

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        return r

    ############################################################
    def clean(self, params):
        """
        Clean all tmp directories in all programs
        """

        if self.cm.debug:
            self.logger.debug("RUNNING program api v1 clean")

        ctx = params['ctx']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        # p will be deep copied from params
        p = self._prepare_input_from_params(params, base = True)

        p['command'] = 'find'
        p['con'] = False

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        for a in r['artifacts']:
            path = a['path']

            path_tmp = os.path.join(path, 'tmp')
            if os.path.isdir(path_tmp):
                if con:
                    print (f'{space}Removing "{path_tmp}" ...')

                try:
                    shutil.rmtree(path_tmp)
                except Exception as e:
                    if con and verbose:
                        print (f'{space}  Problem removing directory: {e}')
 

        return r
