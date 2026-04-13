"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize_code(self,
                       ctx: dict,
                       params: dict = {},
    ):
        # Just check for extra code and base
        _with = params.get('with', {})

        package = _with.get('package')
        if not package:
            package = params.get('arg3')

        r = {'return':0, 'artifacts':[]}
        if package:
            sub_tool = f'pip-{package}'

            ii = {
              'category':self.cmeta['category'],
              'command':'find',
              'arg1':sub_tool,
            }

            r = self.cm.access(ii)
            if self.cm.catch_error(r): return r

            if r['return'] == 16:
                r['artifacts'] = []

        return r

    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        Mostly used to update storage_key
        We need to check package before further key expansions from desc
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 init")

        result = {'return':0}

        _with = params.setdefault('with', {})

        # Check _with parameters (others are checked in "setup" task)
        r = self.cm.check_params(_with, [
                'arg3', 'package', 'extras', 'variations',
                'file', 'url', 'url_tag',
                'flags', 'post_flags',
            ], __name__)
        if self.cm.catch_error(r): return r

        package = _with.get('package')
        if not package:
            package = params.get('arg3')
            if package:
                _with['package'] = params.pop('arg3')

        if not package:
            return self.cm.error(f'"package" is not defined @ "init" ({__file__})')

        extras = _with.get('extras')
        if not extras:
            extras = params.get('arg4')
            if extras:
                _with['extras'] = params.pop('extras')

        extras = _with.get('extras')
        if extras and type(extras) == str:
            _with['extras'] = [item.strip().lower() for item in extras.split(",")]

        return result

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL pip api_v1 check_params")

        result = {'return':0}

        return result

    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str = None,
                              params: dict = {},
                              *misc: dict,
    ):
        """
        """

        result = {'return':0}

        _control = params.get('control', {})
        _with = params.get('with', {})

        force_update = _control.get('clean', False) or _control.get('update', False) or _control.get('new', False)

        flags = _with.get('flags')

        extras = _with.get('extras')
        package_file = _with.get('file')
        package_url = _with.get('url')
        package_url_tag = _with.get('url_tag') # to assemble url[extras]@version

        version = params.get('version')
        version_pip = params.get('version_pip')
        version_simple = params.get('version_simple')

        custom_version = ''
        if package_file:
            custom_package = '{{params.with.file}}'
            # version is ignored here

        elif package_url:
            custom_package = '{{params.with.url}}'
            # version is ignored here
            if package_url_tag:
                custom_package += '@' + package_url_tag
        else:
            custom_package = '{{params.with.package}}'
            if version_pip:
                custom_version = f'"{version_pip}"' # We need "" to prepare install cmd potentially with special characters such as <, >, etc

        if extras:
            x = ','.join(extras)
            custom_package += f'[{x}]'

        custom_package += custom_version

        install_cmd = install_cmd.replace('{{custom_package}}', custom_package)

        # Check force update
        if force_update:
            if not flags:
                flags = ''
            if '--force-reinstall' not in flags:
                flags += ' --force-reinstall'
            _with['flags'] = flags.strip()   

        result['install_cmd'] = install_cmd

        return result

    ############################################################
    def customize_tool_cache_artifact(self,
                                      ctx,
                                      result,
                                      params,
                                      cache_tags,
                                      cache_params,
                                      cache_features,
                                      cache_meta,
        ):

        if self.cm.debug:
            self.logger.debug("RUNNING TASK tool python customize_tool_cache_artifact")

        _with = params.get('with', {})
#        if _with:
#            cache_params_with = cache_params.setdefault('with',{})
#            cache_params_with.update(_with)

        package = _with['package']

        cache_extra_alias = result['cache_extra_alias']
        cache_extra_alias += self.cache_sep + package
        result['cache_extra_alias'] = cache_extra_alias

        # We need to move @version from cache_params (if present)
        # to cache_features since we can install only 1 pip package with the same version!
        if '@version' in cache_params:
            ver = cache_params.pop('@version')
            if '@version' not in cache_features:
                cache_features['@version'] = ver

        return {'return':0}

    ############################################################
    def _common_compute_init(self,
            ctx: dict,
            params: dict,
            skip_extras: bool = False,
    ):
        """
        """

        _with = params.get('with', {})

        flags = _with.get('flags')
        if not flags: flags = ''

        post_flags = _with.get('post_flags')
        if not post_flags: post_flags = ''

        extras = _with.setdefault('extras', [])

        # We need variations to differentiate different installations with different features (cpu, gpu ...)
        variations = _with.setdefault('variations', {})
        variations_compute = variations.setdefault('compute', [])

        result = {'return':0}

        # Check target compute
        target = ctx['tasks']['global']['target']

        compute = target['compute']

        ###########################################################################################
        # Set CUDA if in compute
        if 'cuda' in compute:
            if not skip_extras and 'cuda' not in extras:
                extras.append('cuda')

            if 'cuda' not in variations_compute:
                variations_compute.append('cuda')
                
            # Wrong torch variation may be installed so we need to force update it ...
            if '--force-reinstall' not in flags:
                if flags != '': flags += ' '
                flags += '--force-reinstall'

            # Check CUDA wheel
            if '--index-url ' not in post_flags:
                compute_features = target['features']['cuda']
                cuda_version = compute_features['versions']['cuda version']

                found = False
                ver_lists = ['13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8']

                for ver in ver_lists:
                    r = self.cm.utils.common.compare_versions(cuda_version, ver)
                    if r['return'] == 0 and (r['comparison'] == '>' or r['comparison'] == '='):
                        found = True
                        break

                if found:
                    if post_flags != '': post_flags += ' '
                    ver = ver.replace('.','')
                    post_flags = f'--index-url https://download.pytorch.org/whl/cu{ver}'

        ###########################################################################################
        # Add CPU as default base
        if not skip_extras and 'cpu' not in extras:
            extras.append('cpu')

        if 'cpu' not in variations_compute:
            variations_compute.append('cpu')

        if post_flags:
            _with['post_flags'] = post_flags

        return result

