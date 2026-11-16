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
    def run(self,
            ctx,
            name: str = None,
            dataset_tags: str = None,
            filename: str = None,
            filedesc: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK dataset run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        _global = ctx_tasks['global']

        result = {'return':0}

        if filename and os.path.isfile(filename):
            # Here local file is forced to bypass all the logic of downloading, etc
            path = filename

            result['path'] = path
            result['qpath'] = self.cm.q(path)

            path_root = path
            if os.path.isfile(path):
                path_root = os.path.dirname(path)

            result['path_root'] = path
            result['qpath_root'] = self.cm.q(path)

        else:
            # A sub-dataset named with the dataset: <dataset>/<sub-dataset>[/<file>] (--dataset=ctuning-adpcm/adpcm-0007)
            rest = None
            if name and '/' in name:
                name, _, rest = name.partition('/')

            p = {'category': self.cmeta['uses_categories']['utils'],
                 'command': 'select_artifact',
                 'select_category': self.cmeta['uses_categories']['dataset'],
                 'select_artifact': name,
                 'select_tags': dataset_tags,
                 'con': con,
                 'quiet': quiet,
                 'load_files': ['_desc'],
                 'space': space,
                 'print_extra_line': True,
            }

            r = self.cm.access(p)
            if self.cm.catch_error(r, fail16=True):
                r['return'] = 1 # Force fail if dataset not found
                return r

            artifact = r['artifact']
            artifact_path = artifact['path']
            artifact_au = r['artifact_au']
            loaded_files = r['loaded_files']

            if con and verbose:
                print ('')
                print (f'{space}INFO: Selected dataset "{artifact_au}"')

            # What the dataset says of itself in its _desc.yaml, when it has one: "files" - its files in the
            # order a program takes them (the first is the default; they come with the result, so that a
            # program can take several) - and "number" - the number it stands for (a dataset that is a
            # number on a command line). Datasets without them behave as before
            desc_data = (loaded_files.get('_desc') or {}).get('data') or {}
            files_order = [str(f) for f in desc_data.get('files') or []] if isinstance(desc_data.get('files'), list) else []
            number = desc_data.get('number')

            result['artifact_au'] = artifact_au

            # A dataset made of sub-datasets ("sub_datasets" of its _desc.yaml): one of them is the dataset of
            # this run - the one named, or the first
            sub_datasets = desc_data.get('sub_datasets')
            if isinstance(sub_datasets, dict) and len(sub_datasets) > 0:
                return self._sub_dataset(ctx, artifact_path, artifact_au, desc_data, sub_datasets, rest, filename,
                                         con, quiet, verbose, space)
            if rest:
                return self.cm.error(f'dataset "{artifact_au}" has no sub-datasets ("{rest}" was asked for)')

            # Backward compatibility: datasets that ship their data inside a "files" subdirectory
            path_to_files = os.path.join(artifact_path, 'files')

            if os.path.isdir(path_to_files):
                # Check files
                fs = os.listdir(path_to_files)
                if len(fs) == 0:
                    return self.cm.error(f'dataset files not found in "{path_to_files}" ("{__file__}")')

                # By name, or in the dataset's own order ("files" of _desc.yaml) followed by the others
                ordered = [f for f in files_order if f in fs] + sorted(f for f in fs if f not in files_order)

                result['files'] = ordered
                result['path_files'] = path_to_files
                if number is not None:
                    result['number'] = str(number)

                if filename:
                    if filename not in fs:
                        return self.cm.error(f'dataset file "{filename}" not found in "{path_to_files}" ("{__file__}")')

                    path = os.path.join(path_to_files, filename)
                else:
                    fs = ordered
                    ifs = 0

                    if len(fs) > 1 and con and not quiet:
                        print ('')
                        print (f'{space}Available dataset files:')

                        print ('')
                        for n in range(0, len(fs)):
                            x = fs[n]
                            print (f'{space}{n}) {x}')
                        print ('')

                        r = self._ask(len(fs))
                        if r['return'] > 0: return r
                        ifs = r['index']

                        print ('')

                    path = os.path.join(path_to_files, fs[ifs])

                result['path'] = path
                result['qpath'] = self.cm.q(path)

            else:
                # Select among _desc* descriptions and prepare the dataset via "uses" (same as model)
                files = [
                    f for f in os.listdir(artifact_path)
                    if f.startswith("_desc")
                ]

                if len(files) == 0:
                    return self.cm.error(f'dataset descriptions not found in "{artifact_path}" ("{__file__}")')

                if filedesc:
                    filedesc = '_desc-' + filedesc
                    if filedesc not in files:
                        return self.cm.error(f'dataset file "{filedesc}" not found in "{artifact_path}" ("{__file__}")')

                    path_desc = os.path.join(artifact_path, filedesc)
                else:
                    fs = sorted(files)
                    ifs = 0

                    if len(fs) > 1 and con and not quiet:
                        print ('')
                        print (f'{space}Available dataset files:')

                        print ('')
                        for n in range(0, len(fs)):
                            x = fs[n][6:]
                            print (f'{space}{n}) {x}')
                        print ('')

                        r = self._ask(len(fs))
                        if r['return'] > 0: return r
                        ifs = r['index']

                        print ('')

                    path_desc = os.path.join(artifact_path, fs[ifs])

                # Load file
                r = self.cm.utils.files.read_file(path_desc)
                if self.cm.catch_error(r, fail16=True):
                    r['return'] = 1 # Force fail if file not found
                    return r

                _desc = r['data']

                r = self._prepare(ctx, _desc, con, quiet, verbose, space)
                if r['return'] > 0: return r

                if r['result'] is not None:
                    result = r['result']

                    result['return'] = 0

                    # What the description adds when the prepared result lacks it: the order of the
                    # files, the number, and a file of them asked for by name (--filename)
                    if isinstance(result, dict):
                        result = dict(result)       # the prepared result in the context stays as it was
                        result['artifact_au'] = artifact_au
                        if files_order and not result.get('files'):
                            result['files'] = files_order
                        if number is not None and result.get('number') is None:
                            result['number'] = str(number)
                        files = result.get('files')
                        if filename and isinstance(files, list) and filename in files and result.get('path'):
                            folder = result.get('path_entry') or os.path.dirname(result['path'])
                            result['path'] = os.path.join(folder, filename)
                            result['qpath'] = self.cm.q(result['path'])

        return result

    ############################################################
    def _sub_dataset(self, ctx, artifact_path, artifact_au, _desc, sub_datasets, rest, filename,
                     con, quiet, verbose, space):
        """
        One of the sub-datasets of a dataset: "sub_datasets" of its _desc.yaml names them in order (the first is the
        default), each with its files in the order a program takes them ("files"; the first is the main one), the
        number it stands for ("number"), its tags and a description ("desc"). The files of a sub-dataset are in
        files/<name>/ of the artifact when it is kept with it; otherwise the dataset's description prepares them
        ("uses", for example a download into the cache) and names the folder that holds a folder per sub-dataset
        ("path_root" of its result). Asked for as <dataset>/<name>[/<file>], or with --filename=<name>, <name>/<file>
        or <file> (a file of the default sub-dataset); without a name the first (or a choice, when asked).
        """

        names = [str(k) for k in sub_datasets]

        # What is asked for: a sub-dataset, a file of it, or a file of the default one
        sub = file = None
        for spec in (rest, filename):
            if not spec:
                continue
            head, _, tail = str(spec).partition('/')
            if head in sub_datasets:
                sub = head
                if tail:
                    file = tail
            elif tail:
                return self.cm.error(f'no sub-dataset "{head}" in dataset "{artifact_au}"; there are: ' + ', '.join(names))
            else:
                file = head

        if sub is None:
            sub = names[0]

            if len(names) > 1 and con and not quiet:
                print ('')
                print (f'{space}Available sub-datasets of "{artifact_au}":')

                print ('')
                for n, k in enumerate(names):
                    local = os.path.isdir(os.path.join(artifact_path, 'files', k))
                    print (f'{space}{n}) {k}{self._sub_dataset_label(sub_datasets[k], local)}')
                print ('')

                r = self._ask(len(names), 'sub-dataset')
                if r['return'] > 0: return r
                sub = names[r['index']]

                print ('')

        spec = sub_datasets[sub] if isinstance(sub_datasets[sub], dict) else {}

        # Kept with the artifact, else in the folder the description prepares ("sub_datasets_folder": where
        # inside what it prepares - a repository that holds several sets, one folder each)
        result = {}
        folder = os.path.join(artifact_path, 'files', sub)
        if not os.path.isdir(folder):
            r = self._prepare(ctx, _desc, con, quiet, verbose, space)
            if r['return'] > 0: return r
            prepared = r['result'] if isinstance(r['result'], dict) else {}
            root = prepared.get('path_root') or ''
            inside = str(_desc.get('sub_datasets_folder') or '').strip().replace('/', os.sep)
            if root and inside:
                root = os.path.join(root, inside)
            folder = os.path.join(root, sub) if root else ''
            if not folder or not os.path.isdir(folder):
                where = f' nor in the folder its description prepared ("{root}")' if root else \
                        ' and its description prepares no folder for it (no "uses" with a "path_root")'
                return self.cm.error(f'sub-dataset "{sub}" of dataset "{artifact_au}" is not in files/ of the artifact{where}')
            result = dict(prepared)         # the prepared result in the context stays as it was

        fs = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
        if len(fs) == 0:
            return self.cm.error(f'sub-dataset "{sub}" of dataset "{artifact_au}" has no files in "{folder}"')

        # The sub-dataset's files are those its description lists, in that order (a capsule's folder may hold
        # more - a meta file - which a program must not take); without a list, the folder's files by name
        order = [str(f) for f in spec.get('files') or []] if isinstance(spec.get('files'), list) else []
        ordered = [f for f in order if f in fs] if order else fs
        if order and not ordered:
            return self.cm.error(f'none of the files of sub-dataset "{sub}" of dataset "{artifact_au}" ({", ".join(order)}) is in "{folder}"')

        if file:
            if file not in fs:
                return self.cm.error(f'file "{file}" not found in sub-dataset "{sub}" of dataset "{artifact_au}" ("{folder}")')
            path = os.path.join(folder, file)
        else:
            path = os.path.join(folder, ordered[0])

        result.update({'return': 0,
                       'artifact_au': artifact_au,
                       'sub_dataset': sub,
                       'sub_datasets': names,
                       'files': ordered,
                       'path_files': folder,
                       'path': path,
                       'qpath': self.cm.q(path)})
        if spec.get('number') is not None:
            result['number'] = str(spec['number'])
        if isinstance(spec.get('tags'), list):
            result['tags'] = [str(t) for t in spec['tags']]
        if spec.get('desc'):
            result['desc'] = str(spec['desc'])

        if con and verbose:
            print ('')
            print (f'{space}INFO: Selected sub-dataset "{sub}" ({path})')

        return result

    ############################################################
    def _sub_dataset_label(self, spec, local):
        """What the list of sub-datasets says of one: its description, its files, where it is."""

        if not isinstance(spec, dict):
            spec = {}
        x = ''
        if spec.get('desc'):
            x += f' - {spec["desc"]}'
        if isinstance(spec.get('files'), list) and len(spec['files']) > 0:
            x += ' (' + ', '.join(str(f) for f in spec['files']) + ')'
        x += ' [with the artifact]' if local else ' [prepared on demand]'
        return x

    ############################################################
    def _prepare(self, ctx, _desc, con, quiet, verbose, space):
        """
        Prepare a dataset as its description says ("uses"); the result is what "result_from_ctx" names in the
        context (None without "uses" or "result_from_ctx").
        """

        _uses = _desc.get('uses')
        result_from_ctx = _desc.get('result_from_ctx')

        if not _uses:
            return {'return': 0, 'result': None}

        if con and verbose:
            print ('')
            print (f'{space}Preparing dataset ...')

        p = {'category': self.category_alias + ',' + self.category_uid,
             'command': 'use',
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
             'ctx': ctx,
             'desc': _uses,
             'local': None, #ctx['tasks']['local'],
             'task_artifact_alias': self.artifact_alias,
             'task_artifact_uid': self.artifact_uid,
             'task_artifact_path': self.artifact_path,
            }

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        if not result_from_ctx:
            return {'return': 0, 'result': None}

        r = self.cm.utils.common.expand_string(result_from_ctx, ctx['tasks'])
        if self.cm.catch_error(r): return r

        return {'return': 0, 'result': r['value']}

    ############################################################
    def _ask(self, count, what = 'dataset file'):
        """The user's choice in a list of count items (Enter: the first)."""

        from task_c36be4b9314a45e0.api.ctask import ask as ask_user
        while True:
            r = ask_user(f'Please select a {what} or press Enter for 0: ',
                         how = '-q (--quiet) to take the first of the list')
            if r['return'] > 0: return r
            x = r['answer'].strip()

            if x == "":
                return {'return': 0, 'index': 0}

            if x.isdigit() and int(x) >= 0 and int(x) < count:
                return {'return': 0, 'index': int(x)}
