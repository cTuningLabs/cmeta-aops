"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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
        directory = params.get('directory')
        filename = params.get('filename')
        filenames = params.get('filenames')
        features = params.setdefault('features', {})

        skip_cmd = False
        if not (repo or directory or filename or filenames):
            return self.cm.error(f'HF repo, directory, filename and/or filenames are not defined for "{__file__}"')

        skip_cmd = True if not repo else False
        ctx['tasks']['local']['skip_cmd'] = skip_cmd

        if not filenames: 
            filenames = {}

        if not repo:
            if directory and not os.path.isdir(directory):
                return self.cm.error(f'Local HF model is used but directory "{directory}" is not found ("{__file__}")')

            if filename:
                _filename = os.path.join(directory, filename) if directory else filename
                if not os.path.isfile(_filename):
                    return self.cm.error(f'Local HF model is used but file "{filename}" is not found ("{__file__}")')


        if filename and 'model' not in filenames:
            filenames['model'] = filename
        elif not filename and 'model' in filenames:
            filename = filenames['model']

        if filenames:
            ctx['tasks']['local']['filenames'] = filenames

        xlibrary = features.get('library')
        if filename and not xlibrary:
            name, ext = os.path.splitext(filename)
            exts = {'.gguf': 'gguf', '.pt': 'pytorch', '.onnx': 'onnx'}

            xlibrary = exts.get(ext)
            if xlibrary:
                features['library'] = xlibrary

        if features:
            ctx['tasks']['local']['features'] = features

        if skip_cmd:
            if filename:
                if not directory:
                    directory = os.path.dirname(filename)
                    filename = os.path.basename(filename)

        else:
            ctx['tasks']['local']['repo'] = repo

            xrepo = repo.replace('/', '@')
            if xlibrary:
                xrepo += f'--{xlibrary}'

            ctx['tasks']['local']['xrepo'] = xrepo

            files = filename.split(';') if filename else []
            if filenames:
                for k in filenames:
                    f = filenames[k]
                    if f not in files:
                        files.append(f) 

            ctx['tasks']['local']['files'] = files

            includes = ''

            if files:
                for f in files:
                    includes += f' --include {f}'

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
                    sub_directory = os.path.join('get-hf-model', xrepo)
                    directory = os.path.join(path_file_cache, sub_directory)
            else:
                if not directory:
                    directory = 'content'

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

        _local = ctx['tasks']['local']

        directory = _local.get('directory')
        filename = _local['filename']
        filenames = _local.get('filenames')
        files = _local.get('files', {})
        skip_cmd = _local['skip_cmd']
        features = _local.get('features')

        path_root = os.path.abspath(directory)
        path = os.path.join(path_root, filename) if filename else path_root

        paths = {}
        qpaths = {}

        if filenames:
            for k in filenames:
                f = filenames[k]
                p = os.path.join(path_root, f)
                if not os.path.isfile(p):
                    return self.cm.error(f'Model sub-file "{p}" not found in "{path_root}" ("{__file__})"')
                paths[k] = p
                qpaths[k] = self.cm.q(p)

        result['path'] = path
        result['qpath'] = self.cm.q(path)

        result['path_root'] = path_root
        result['qpath_root'] = self.cm.q(path_root)

        result['skip_cmd'] = skip_cmd

        if features:
            result['features'] = features

        _features = result.setdefault('features', {})

        if paths:
            _features['paths'] = paths
            _features['qpaths'] = qpaths

        _misc = result.setdefault('misc', {})
        if directory:
            _misc['directory'] = directory
        if filename:
            _misc['filename'] = filename
        if filenames:
            _misc['filenames'] = filenames
        if files:
            _misc['files'] = files

        _misc['files'] = files

        return result
