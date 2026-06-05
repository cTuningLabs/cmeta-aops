"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict,
                     cparams: dict,
    ):
        """
        """


        repo = params.get('repo')
        filename = params.get('filename')

        skip_cmd = False
        if not repo and not filename: 
            return self.cm.error(f'HF repo and filename are not defined for "{__file__}"')
        elif filename and not repo:
            if not os.path.isfile(filename):
                return self.cm.error(f'HF repo is not defined but file "{filename}" is not found in "{__file__}"')

            skip_cmd = True

        ctx['tasks']['local']['skip_cmd'] = skip_cmd

        if filename:
            features = params.setdefault('features', {})
            if 'library' not in features:
                name, ext = os.path.splitext(filename)
                if ext == '.gguf':
                    features['library'] = 'gguf'
                elif ext == '.pt':
                    features['library'] = 'pytorch'
                elif ext == '.onnx':
                    features['library'] = 'onnx'

        if not skip_cmd:
            ctx['tasks']['local']['repo'] = repo

            xrepo = repo.replace('/', '--')
            ctx['tasks']['local']['xrepo'] = xrepo


            includes = ''

            if filename:
                for f in filename.split(';'):
                    includes += f'--include {f}'

            ctx['tasks']['local']['includes'] = includes


            path_file_cache_list = ctx['tasks'].get('global', {}).get('init', {}).get('file_cache')
            if path_file_cache_list:
                path_file_cache = None

                for x in path_file_cache_list.split(os.pathsep):
                    if os.path.isdir(x):
                        path_file_cache = x
                        break
                    else:
                        try:
                           os.makedirs(x, exist_ok=True)
                           path_file_cache = x
                           break
                        except:
                           pass

                if path_file_cache:
                    sub_directory = f'get-hf-model--{xrepo}'

# FGG remarked because we can reuse multiple files in the same dir ...
#                    if filename:
#                        sub_directory += f'--{filename}'

                    directory = os.path.join(path_file_cache, sub_directory)
            else:
                directory = params.get('directory')
                if not directory:
                    directory = 'content'


        else:
            directory = os.path.dirname(filename)
            filename = os.path.basename(filename)

        ctx['tasks']['local']['directory'] = directory
        ctx['tasks']['local']['filename'] = filename

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

        features = params.get('features')
        if features:
            cache_params['features'] = features

        cache_params['path_root'] = ctx['tasks']['local']['directory']
        cache_params['filename'] = ctx['tasks']['local']['filename']

        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        result = {'return':0}

        directory = ctx['tasks']['local'].get('directory')
        filename = ctx['tasks']['local']['filename']

        if directory:
            path = os.path.abspath(directory)
            path_root = path
            if filename:
                path = os.path.join(path, filename)
        else:
            path = filename
            path_root = os.path.dirname(path)

        if filename and not os.path.isfile(path):
            return self.cm.error(f'Model file "{path}" not found in "{__file__}"')

        if not filename and not os.path.isdir(path):
            return self.cm.error(f'Model path "{path}" not found in "{__file__}"')


        result['path'] = path
        result['qpath'] = self.cm.q(path)

        result['path_root'] = path_root
        result['qpath_root'] = self.cm.q(path_root)
 
        return result

