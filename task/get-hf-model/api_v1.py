"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import re
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask, file_cache_folder

WILDCARDS = set('*?[')


def quoted(pattern):
    """A file or pattern of a repository for the hf command line: a POSIX path, quoted when it holds a wildcard (so that
    no shell turns "*.json" into the names of files of the current folder), else as it is."""
    p = '/'.join(x for x in str(pattern).replace('\\', '/').split('/') if x)
    return '"%s"' % p if WILDCARDS & set(p) else p


def patterns_of(value):
    """Patterns given as a list or as one text, separated by commas or semicolons."""
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).replace(';', ',').split(',')
    return [str(i).strip() for i in items if str(i).strip()]


def hf_words(revision = None, include = None, exclude = None):
    """The words of a download at a revision of the repository, by Hugging Face's own patterns (fnmatch on the path:
    "*.safetensors" matches the files of sub-folders too - exclude those)."""
    words = ''
    if revision:
        words += ' --revision ' + str(revision).strip()
    for p in patterns_of(include):
        words += ' --include ' + quoted(p)
    for p in patterns_of(exclude):
        words += ' --exclude ' + quoted(p)
    return words

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

            # A file of a Hugging Face repository is a POSIX path: a doubled separator of a description
            # ("mnist//train-...") matched with huggingface_hub 1.x and matches nothing with 2.x (only the
            # README came); the file names of the cache entry stay as described
            if files:
                for f in files:
                    includes += ' --include ' + quoted(f)

            ctx['tasks']['local']['includes'] = includes

            # A whole model at a revision, by patterns (2026-11-26, the models of the MLPerf benchmarks): the
            # revision of the repository (a commit, a branch or a tag) and Hugging Face's own include / exclude
            # patterns; a description without them downloads as before
            revision = str(params.get('revision') or '').strip()
            if revision and not re.match(r'^[A-Za-z0-9][A-Za-z0-9._/-]*$', revision):
                return self.cm.error(f'revision "{revision}" is not a commit, branch or tag name ("{__file__}")')
            ctx['tasks']['local']['hf_words'] = hf_words(revision, params.get('include'), params.get('exclude'))

            path_file_cache_list = ctx['tasks'].get('global', {}).get('init', {}).get('file_cache')
            if (ctx['tasks'].get('local') or {}).get('in_data_repository'):
                path_file_cache_list = None       # a data repository keeps the files inside the entry (portable, shared)
            if path_file_cache_list:
                # The place of the file cache that has these files already, else the first one that is there: a
                # drive that is away is passed over and the run says so; none there stops it (file_cache_folder)
                sub_directory = os.path.join('get-hf-model', xrepo)
                r = file_cache_folder(path_file_cache_list, sub_directory,
                                      con = ctx.get('control', {}).get('con', False))
                if r['return'] > 0:
                    return self.cm.error(r['error'])
                directory = os.path.join(r['path'], sub_directory)
            else:
                if not directory:
                    directory = 'content'

        ctx['tasks']['local']['directory'] = directory

        # the folder as one word of the command line: a path with a space (a user profile such as "C:/Users/First Last")
        # was cut at the space, and hf took the rest for a file of the model ("File not found in model")
        ctx['tasks']['local']['qdirectory'] = self.cm.q(directory)
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

        # a revision and patterns are what the entry holds: an entry of another revision or of other files is another one
        for key in ('revision', 'include', 'exclude'):
            if params.get(key):
                cache_params[key] = params[key]

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
