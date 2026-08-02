"""
Copyright (C) 2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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

            for entry in os.listdir(path):
                if entry.startswith('tmp'):
                    path_tmp = os.path.join(path, entry)
                    if os.path.isdir(path_tmp):
                        if con:
                            print (f'{space}Removing "{path_tmp}" ...')

                        try:
                            shutil.rmtree(path_tmp)
                        except Exception as e:
                            if con and verbose:
                                print (f'{space}  Problem removing directory: {e}')
 

        return r

    ############################################################
    def update_desc_(
                    self, 
                    ctx, 
                    desc: dict = None,
                    updates: dict = None,
    ):
        """
        """

        if desc and updates:
            for key2 in updates:

                _update = desc.setdefault(key2, {})

                for key3 in updates[key2]:
                    if key3 == 'uses':
                        # [target to update]
                        target_uses = _update.setdefault(key3, [])

                        # [what to update]
                        for _use in updates[key2][key3]:
                            match = _use.get('match')
                            update = _use.get('update')
                            append = _use.get('append')
                            prepend = _use.get('prepend')
                            substitute = _use.get('substitute')
                            append_lists = _use.get('append_lists', False)

                            for index in range(0, len(target_uses)):
                                target = target_uses[index]
                                matched = True

                                for match_key in match:
                                    if match_key not in target:
                                        matched = False
                                        break

                                    match_value = match[match_key]
                                    if match_value != target[match_key]:
                                        matched = False
                                        break

                                if matched:
                                    if update:
                                        self.cm.utils.common.deep_merge(target_uses[index], update, append_lists=append_lists)
                                    if append:
                                        target_uses[index+1:index+1] = append
                                    if prepend:
                                        target_uses[index:index] = prepend
                                    if substitute:
                                        target_uses[index] = substitute

                                    break

                    else:
                        if key3.startswith('+'):
                            value3 = updates[key2][key3]
                            key3 = key3[1:]
                            x = _update.setdefault(key3, [])
                            x += value3
                        else:
                            _update[key3] = updates[key2][key3]

        return {'return': 0}

