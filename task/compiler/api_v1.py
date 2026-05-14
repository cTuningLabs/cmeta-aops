"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        """

        # Checking even for cached entries!
        r = self.cm.check_params(params, [
                'lang',
                'extra_tags',
                'extra_match',
                'name',
                'text',
                'compute',
                'with',
            ], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        lang = params.get('lang')
        extra_tags = params.get('extra_tags')
        extra_match = params.get('extra_match')
        name = params.get('name')
        text = params.get('text')
        compute = params.get('compute')
        version = params.get('version')
        _with = params.get('with', {})

        if not lang:
            return self.cm.error(f'"lang" is not specified in "{__file__}"')

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        uname = ctx['tasks']['global']['host']['os']['uname']

        tool_tags = [f'lang-{lang}']

        tool_match = {} if extra_match is None or extra_match == '' else extra_match
        tool_constraints = tool_match.setdefault('constraints', {})
        supports_os = tool_constraints.setdefault('supports_os', [])

        if uname not in supports_os: supports_os.append(uname)

        if not compute:
            compute = ['cpu']
        elif type(compute) == str:
            compute = compute.split(',')

        supports_compute = tool_constraints.setdefault('supports_compute', [])
        supports_compute += compute

        if extra_tags and type(extra_tags) == str:
            extra_tags = self.cm.utils.common.split(extra_tags)

        if extra_tags:
            tool_tags += extra_tags

        if text and con:
            print ('')
            print (f'{space}{text}')

        ###########################################################################################
        # SELECT TOOL ARTIFACT
        if not name:
            p = {'category': self.cmeta['uses_categories']['utils'],
                 'command': 'select_artifact',
                 'select_category': self.cmeta['uses_categories']['tool'],
                 'select_tags': tool_tags,
                 'select_match': tool_match,
                 'con': con,
                 'quiet': quiet,
                 'verbose': verbose,
                 'space': space,
                 'print_extra_line': True,
            }

            r = self.cm.access(p)
            if self.cm.catch_error(r, fail16=True): 
                if r['return'] == 16:
                    if tool_constraints:
                        r['error'] += f' and constraints "{tool_constraints}"'
                    r['return'] = 99
                return r

            artifact = r['artifact']

            name = artifact['cmeta_ref_parts']['artifact_alias']

        # Setup compiler (note that there is duplicate in finish_dynamic_result too!) to update cache params
        # Don't forget CXT here to update global context for further tasks and tools in a higher level pipeline
        p = {'ctx': ctx,
             'category': self.category_alias + ',' + self.category_uid,
             'command': 'run',
             'arg1': 'setup,a2f9b61079ce4333',
             'name': name,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
        }

        if version:
            p['version'] = version

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        version = r.get('version')
        constraints = r.get('constraints',{})
        constraints_compute = constraints.get('supports_compute')

        result.update(r)

        result['tool'] = {
          'name': name,
          'tags': tool_tags,
          'match': tool_match,
        }

        _update_params = {
          'name': name,
        }

        if version: _update_params['version'] = version
        if constraints_compute: _update_params['supported_compute'] = constraints_compute

        result['_update_params'] = _update_params

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        name = result['tool']['name']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        version = result.get('version')

        _result = {'return':0}

        # Setup compiler dynamically (for ENV if needed)
        # Don't forget CXT here to update global context for further tasks and tools in a higher level pipeline
        p = {'ctx': ctx,
             'category': self.category_alias + ',' + self.category_uid,
             'command': 'run',
             'arg1': 'setup,a2f9b61079ce4333',
             'name': name,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
        }

        if version: p['version'] = version

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 99
            return r

        result.update(r)

        _with = params.get('with', {})

        _fast = _with.get('fast', False)
        _static = _with.get('static', False)
        _debug = _with.get('debug', False)
        _openmp = _with.get('openmp', False)
        _profile = _with.get('profile', False)

        compiler_flags = []

        flags = result.get('features', {}).get('flags','')

        if _static:
            x = flags.get('static_build_debug') if _debug else flags.get('static_build')
        else:
            x = flags.get('dynamic_build_debug') if _debug else flags.get('dynamic_build')

        if x and x not in compiler_flags:
            compiler_flags.append(x)

        if _openmp:
            openmp_flag = flags.get('openmp')
            if not openmp_flag:
                return self.cm.error(f'openmp requested but flag is not defined in compiler meta in "{__file__}" ({__name__})')
        
            if openmp_flag not in compiler_flags:
                compiler_flags.append(openmp_flag)

        result['compiler_flags'] = compiler_flags

        _result['result'] = result
        return _result
