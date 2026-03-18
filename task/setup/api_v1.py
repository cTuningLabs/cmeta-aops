"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

from . import build
from . import common
from . import detect
from . import install

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    install_tool = install.install_tool
    build_tool = build.build_tool
    read_tool = common.read_tool
    detect_existing_tool = detect.detect_existing_tool

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize storage_key and cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup init")

        r = self.cm.check_params(params, [
                'detect','install', 'build', 'skip_install', 'skip_detect', 'skip_build',
                'name', 'tool_tags', 'tool_api_ver', 'tool_path', 'paths', 
                'version', 'env', 'timeout', 'with', 'arg3',
            ], __name__)
        if self.cm.catch_error(r): return r

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        name = params.get('name')
        tool_tags = params.get('tool_tags')
        tool_api_ver = params.get('tool_api_ver')

        ###########################################################################################
        # SELECT TOOL ARTIFACT
        r = self.read_tool(
            ctx=ctx,
            name=name,
            tool_tags=tool_tags,
            tool_api_ver=tool_api_ver,
        )
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

        desc = r['desc']
        tool_api_code = r['tool_api_code']
        artifact_au = r['artifact_au']

        result = {'return':0}

        if 'uses' in desc:
            result['uses'] = desc['uses']

        # Update params
        params['name'] = artifact_au

        storage_key = desc.get('storage_key')

        # Check if extra init from a tool
        if hasattr(tool_api_code, 'init') and callable(getattr(tool_api_code, 'init')):
            r = tool_api_code.init(ctx, params)
            if self.cm.catch_error(r): return r

            if r.get('storage_key'):
                storage_key = r['storage_key']

        if storage_key:
            result['storage_key'] = storage_key

        return result

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict,
                     cparams: dict = {},
    ):
        """
        """

        name = params.get('name')
        tool_tags = params.get('tool_tags')
        tool_api_ver = params.get('tool_api_ver')

        ###########################################################################################
        # SELECT TOOL ARTIFACT
        r = self.read_tool(
            ctx=ctx,
            name=name,
            tool_tags=tool_tags,
            tool_api_ver=tool_api_ver,
        )
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

        desc = r['desc']
        tool_api_code = r['tool_api_code']
        artifact_au = r['artifact_au']

        # Check if extra init from a tool
        if hasattr(tool_api_code, 'check_params') and callable(getattr(tool_api_code, 'check_params')):
            r = tool_api_code.check_params(ctx, params, cparams)
            if self.cm.catch_error(r): return r

        # Check tool path
        tool_path = params.get('tool_path')
        if tool_path:
            if tool_path == '{{sys.executable}}':
                import sys
                tool_path = sys.executable

            if not os.path.isfile(tool_path):
                return self.cm.error(f'path to tool "{tool_path}" not found')

            params['tool_path'] = os.path.normpath(tool_path)

        return {'return':0}

    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 cache_alias_template,
                                 cache_extra_alias,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup customize_cache_artifact")

        result = {'return':0}

        name = params.get('name')

        if cache_extra_alias is None: 
            cache_extra_alias = ''

        if cache_extra_alias !='':
            cache_extra_alias += self.cache_sep

        cache_extra_alias += f'{name}'

        result['cache_extra_alias'] = cache_extra_alias

        name = params.get('name')
        tool_tags = params.get('tool_tags')
        tool_api_ver = params.get('tool_api_ver')

        ###########################################################################################
        # SELECT TOOL ARTIFACT
        r = self.read_tool(
            ctx=ctx,
            name=name,
            tool_tags=tool_tags,
            tool_api_ver=tool_api_ver,
        )
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

        desc = r['desc']
        tool_api_code = r['tool_api_code']
        artifact_au = r['artifact_au']

        uname = ctx['tasks']['global']['host']['os']['uname']

        # Check if params keys are defined in cdesc to be added to cache_tags
        for k in desc.get('cache_params', []):
            # Check if need to expand
            v = None

            if k.startswith('{{') or k.startswith('}}'):
                k = k[2:-2]

                kk = k[1:] if k.startswith('@') else k

                r = self.cm.utils.common.expand_string('{{'+kk+'}}', ctx['tasks'])
                if self.cm.catch_error(r): return r
                v = r['string']

            else:
                kk = k[1:] if k.startswith('@') else k

            if v is None:
                v = params.get(kk)

            if v is not None:
                cache_params[k] = v


        if desc.get('cache_params_with', False):
            if 'with' in params:
                cache_params['with'] = params['with']

        desc_cache_params_use = desc.get('cache_params_use')
        if desc_cache_params_use:
            v = None

            if 'all' in desc_cache_params_use:
                v = desc_cache_params_use['all']
            elif uname in desc_cache_params_use:
                v = desc_cache_params_use[uname]
            elif 'linux' in desc_cache_params_use:
                v = desc_cache_params_use['linux']

            if v:
                v = v.copy()

                r = self.cm.utils.common.expand_strings_in_dict(v, ctx['tasks'])
                if self.cm.catch_error(r): return r

                cache_params_use = cache_params.setdefault('use', {})
                cache_params_use = self.cm.utils.common.deep_merge(cache_params_use, v, append_lists=True)


        # Check if extra init from a tool
        if hasattr(tool_api_code, 'customize_cache_artifact') and callable(getattr(tool_api_code, 'customize_cache_artifact')):
            r = tool_api_code.customize_cache_artifact(
                 ctx, 
                 result, 
                 params, 
                 cache_tags, 
                 cache_params,
            )
            if self.cm.catch_error(r): return r

            if 'result' in r: result = r['result']

        return result

    ############################################################
    def run(self, ctx, **kwargs):
        """
        Setup a tool with possible install and build
        """

        task_desc = self.cdesc

        name = kwargs.get('name')
        tool_tags = kwargs.get('tool_tags')
        tool_api_ver = kwargs.get('tool_api_ver')
        version = kwargs.get('version', '')

        install = kwargs.get('install')
        build = kwargs.get('build')

        kwargs_copy = kwargs.copy()

        here = kwargs_copy.get('here', False)
        if here:
            kwargs_copy['paths'] = [os.path.join(ctx['origin']['pwd'], '**', '.*', '**')]

        detect = kwargs_copy.pop('detect', None)
        skip_detect = kwargs_copy.pop('skip_detect', False)
        skip_install = kwargs_copy.pop('skip_install', False)
        skip_build = kwargs_copy.pop('skip_build', False)

        result = {'return':0}

        ctx_tasks = ctx['tasks']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        # Read tool
        r = self.read_tool(
            ctx=ctx,
            name=name,
            tool_tags=tool_tags,
            tool_api_ver=tool_api_ver,
        )
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

        kwargs_copy['tool_read'] = r
        kwargs_copy['task_desc'] = self.cdesc

        space = r['space']
        desc = r['desc']
        artifact_au = r['artifact_au']

        cache_params = ctx['tasks']['run_control'].get('cache_params')

        uname = ctx_tasks['global']['host']['os']['uname']

        # Checking various conditions
        if detect is None and install is None and build is None:
            detect = True
            install = True
            build = True
        else:
            if detect is True:
                if install is None: install = False
                if build is None: build = False

            if install is True:
                if detect is None: detect = False
                if build is None: build = False

            if build is True:
                if detect is None: detect = False
                if install is None: install = False

        success = False

        ##############################################################################
        if detect and not skip_detect:
            # Attempt to detect tool

            r = self.detect_existing_tool(ctx, **kwargs_copy)
            # Fail if return error > 0 and return error !=16
            # If want to fail on error 16, add "r, fail16=True")
            if self.cm.catch_error(r): return r

            if r['return'] == 0:
                result = r
                success = True

            else:
                x = ''
                if version:
                    x += f' with version "{version}"'
                if cache_params:
                    if x != '': x += ' and'
                    x += f' with cache params "{cache_params}"'

                err = r['error'] + x 

                if con and verbose:
                    print ('')
                    print (f'{space}WARNING: ' + err)

        ##############################################################################
        if not success and install and not skip_install:
            # Attempt to install tool

            r = self.install_tool(ctx, **kwargs_copy)
            if self.cm.catch_error(r): return r

            if r['return'] == 0:
                if not r.get('failed', False):
                    found_path = r.get('found_path')
                    found_paths = r.get('found_paths')

                    if found_path:
                        kwargs_copy['tool_path'] = found_path
                    if found_paths:
                        kwargs_copy['paths'] = found_paths

                    r = self.detect_existing_tool(ctx, **kwargs_copy)
                    if self.cm.catch_error(r): return r

                    if r['return'] == 0:
                        result = r
                        success = True
            elif con:
                print ('')
                err = r['error']
                print (f'{space}WARNING: {err}')

        ##############################################################################
        if not success and build and not skip_build:
            # Attempt to build tool

            r = self.build_tool(ctx, **kwargs_copy)
            if self.cm.catch_error(r): return r

            if r['return'] == 0:
                if not r.get('failed', False):
                    found_path = r.get('found_path')
                    found_paths = r.get('found_paths')

                    if found_path:
                        kwargs_copy['tool_path'] = found_path
                    if found_paths:
                        kwargs_copy['paths'] = found_paths

                    r = self.detect_existing_tool(ctx, **kwargs_copy)
                    if self.cm.catch_error(r): return r

                    if r['return'] == 0:
                        result = r
                        success = True
            elif con:
                print ('')
                err = r['error']
                print (f'{space}WARNING: {err}')

        ##############################################################################
        if not success:
            if con:
                helper_text = desc.get('install_help_text', '')

                if not helper_text:
                    helper = desc.get('install_help', {})
                    key = uname if uname in helper else 'linux'
                    helper_text = helper.get(key)

                if helper_text:
                    print ('')
                    print ('='*80)
                    print (helper_text)
                    print ('='*80)

            x = f' with version "{version}"' if version else ''
            _with = kwargs.get('with',{})
            if _with:
                if x != '': x += ' and'
                x += f' with params "{_with}"'
            return self.cm.error(f'failed to find tool "{artifact_au}"{x}')

        ##############################################################################
        # Check path to tool
        tool_path = result.get('path')

        if not tool_path:
            tool_path = kwargs.get('tool_path')

        if tool_path:
            _update_params = result.setdefault('_update_params',{})
            if 'tool_path' not in _update_params:
                _update_params['tool_path'] = os.path.normpath(tool_path)

        return result


    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Mostly used to update storage_key
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK setup finish_dynamic_result")

        _result = {'return':0}

        name = params.get('name')
        tool_tags = params.get('tool_tags')
        tool_api_ver = params.get('tool_api_ver')

        r = self.read_tool(
            ctx=ctx,
            name=name,
            tool_tags=tool_tags,
            tool_api_ver=tool_api_ver,
        )
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

        tool_api_code = r['tool_api_code']

        if hasattr(tool_api_code, 'finish_dynamic_result') and callable(getattr(tool_api_code, 'finish_dynamic_result')):
            r = tool_api_code.finish_dynamic_result(
                 ctx, 
                 result, 
                 params, 
            )
            if self.cm.catch_error(r): return r

            if 'result' in r: _result['result'] = r['result']

        return _result
