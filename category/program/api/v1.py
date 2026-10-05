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

        # --target is --compute by another name ("cx program targets" lists them); before, it was
        # ignored without a word and the program ran on the default CPU
        if 'target' in p:
            target = p.pop('target')
            if 'compute' not in p:
                p['compute'] = target

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        return r

    ############################################################
    def targets(self, params):
        """
        List the compute targets that --compute (or --target) of "cx program run" accepts: the
        task/target--<name> artifacts. Several go together: --compute=cpu,cuda.

            cx program targets
        """

        ctx = params['ctx']
        con = ctx['control'].get('con', False)

        r = self.cm.access({'category': self.cmeta['uses_categories']['task'],
                            'command': 'find',
                            'arg1': 'target--*'})
        if self.cm.catch_error(r): return r

        targets = []
        for a in r.get('artifacts', []):
            alias = a['cmeta_ref_parts']['artifact_alias']
            if not alias.startswith('target--'):
                continue
            meta = a.get('cmeta', {})
            targets.append({'target': alias[len('target--'):], 'name': meta.get('name', ''),
                            'desc': meta.get('desc', ''), 'sort': meta.get('sort', 0)})

        targets.sort(key = lambda t: (t['sort'], t['target']))

        if con:
            width = max([len(t['target']) for t in targets] + [6])
            print ('')
            print ('Compute targets ("cx program run <program> --compute=<target>[,<target>...]"):')
            print ('')
            for t in targets:
                desc = t['desc']
                if desc.startswith('Compute target: '):
                    desc = desc[len('Compute target: '):]
                print (f'  {t["target"]:{width}}  {desc}')
            print ('')
            print ('A bare --compute (or --target) asks which ones to use.')

        return {'return': 0, 'targets': targets}

    ############################################################
    def provenance(self, params):
        """
        Show the provenance record of a program run (provenance.json in the program's build folder,
        written by "cx program run"): what was requested, what was resolved, what the binary loads,
        and the checks between them.

            cx program provenance <program> [--target_tmp=<name>]   # one build folder (default: tmp)
            cx program provenance <program> --all                   # every build folder with a record
            cx program provenance <program> --diff=<other target_tmp | path to a provenance.json>
            cx program provenance <program> --as_flags              # the options that reproduce the run
            cx program provenance <program> --as_json               # the record itself
        """

        from . import provenance_view as view

        ctx = params['ctx']
        con = ctx['control'].get('con', False)

        p = self._prepare_input_from_params(params, base = True)
        if not p.get('arg1'):
            return self.cm.error('name the program: cx program provenance <program> [--target_tmp=<name>] [--all] [--diff=...] [--as_flags] [--as_json]')

        target_tmp = params.get('target_tmp')
        show_all = bool(params.get('all', False))
        other = params.get('diff')
        as_flags = bool(params.get('as_flags', False))
        as_json = bool(params.get('as_json', params.get('json', False)))

        # The program (this command's own options are not the find command's)
        for key in ('target_tmp', 'all', 'diff', 'as_flags', 'as_json', 'json'):
            p.pop(key, None)
        p['command'] = 'find'
        p['con'] = False
        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        artifacts = r.get('artifacts', [])
        if len(artifacts) != 1:
            return self.cm.error(f'"{p["arg1"]}" names {len(artifacts)} programs; name exactly one')

        parts = artifacts[0].get('cmeta_ref_parts', {})
        alias = parts.get('artifact_alias') or p['arg1']
        uid = parts.get('artifact_uid')

        # Its build folders: the cache entry of task compile-and-run-program for this program
        # (read only: a program that never ran has no entry, and this command creates none)
        cache_category = self.cmeta.get('uses_categories', {}).get('cache')
        if not cache_category:
            # the dependency is declared in the category's meta, which the index reads
            return self.cm.error('the program category\'s dependency on the cache category is not in the index yet: '
                                 'run "cx category update <repo>:program" or "cx --reindex" and retry')
        r = self.cm.access({
            'category': cache_category,
            'command': 'read',
            'arg1': f'task--program--{alias or uid}',
            'tags': ['task', 'c36be4b9314a45e0', 'compile-and-run-program', '05437a1aae224270'],
        })
        if r['return'] == 16:
            return self.cm.error(view.missing_message(alias, None, target_tmp))
        if self.cm.catch_error(r): return r

        entry_path = r['artifact']['path']
        records = view.find_records(entry_path)

        if show_all:
            if con:
                print ('')
                print (f'Provenance records of program {alias} ({entry_path}):')
                print ('')
                if not records:
                    print ('  (none)')
            summaries = []
            for name, path in records:
                rx = view.load_record(path)
                if rx['return'] > 0:
                    if con:
                        print (f'  {name:14}  {rx["error"]}')
                    continue
                summaries.append({'target_tmp': name, 'path': path, 'ok': rx['record'].get('ok'),
                                  'created': rx['record'].get('created'), 'compute': rx['record'].get('compute')})
                if con:
                    print (view.summary_line(name, rx['record']))
            if con:
                print ('')
            return {'return': 0, 'records': summaries, 'entry_path': entry_path}

        # One record: the folder asked for, else tmp; when tmp has none but others do, list them
        if not target_tmp:
            if os.path.isfile(os.path.join(entry_path, 'tmp', view.RECORD_FILENAME)) or not records:
                target_tmp = 'tmp'
            else:
                if con:
                    print ('')
                    print (f'No record in the default build folder "tmp"; the build folders of {alias} with a record:')
                    print ('')
                    for name, path in records:
                        rx = view.load_record(path)
                        if rx['return'] == 0:
                            print (view.summary_line(name, rx['record']))
                    print ('')
                    print (f'Pick one: cx program provenance {alias} --target_tmp=<name>')
                return {'return': 0, 'records': [{'target_tmp': n, 'path': pth} for n, pth in records], 'entry_path': entry_path}

        folder = os.path.join(entry_path, target_tmp)
        path = os.path.join(folder, view.RECORD_FILENAME)
        rx = view.load_record(path)
        if rx['return'] == 16:
            return self.cm.error(view.missing_message(alias, folder, target_tmp))
        if self.cm.catch_error(rx): return rx
        record = rx['record']

        result = {'return': 0, 'record': record, 'path': path, 'entry_path': entry_path, 'target_tmp': target_tmp}

        if other:
            # Another build folder of the same program, or a record file (from another machine)
            other_path = other if os.path.isfile(other) else os.path.join(entry_path, other, view.RECORD_FILENAME)
            ry = view.load_record(other_path)
            if ry['return'] == 16:
                return self.cm.error(f'no provenance record for --diff: {other_path}')
            if self.cm.catch_error(ry): return ry
            d = view.diff(record, ry['record'])
            result['diff'] = d
            result['diff_path'] = other_path
            if con:
                print ('')
                print (view.render_diff(d, f'{alias} ({target_tmp})', other if os.path.isfile(other) else f'{alias} ({other})'))
                print ('')
            return result

        if as_flags:
            flags = view.as_flags(record)
            result['flags'] = flags
            if con:
                print (flags)
            return result

        if as_json:
            import json
            if con:
                print (json.dumps(record, indent = 2))
            return result

        text = view.render(record, program = alias)
        result['text'] = text
        if con:
            print ('')
            print (text)
            print ('')
        return result

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

