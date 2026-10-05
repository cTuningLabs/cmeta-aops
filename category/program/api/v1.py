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

            cx program provenance <program> [--target_tmp=<name>]   # one build folder (default: the newest record)
            cx program provenance <program> --all                   # every build entry (one per request) and folder with a record
            cx program provenance <program> --entry=<alias|uid|digest> [--target_tmp=<name>]   # one entry
            cx program provenance <program> --diff=<other target_tmp | <entry>:<target_tmp> | path to a provenance.json>
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
        for key in ('target_tmp', 'all', 'diff', 'as_flags', 'as_json', 'json', 'entry'):
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

        # Its build entries: one per request (category/task/api/build_identity.py), the one made before
        # the entries per request among them (read only: this command creates none)
        cache_category = self.cmeta.get('uses_categories', {}).get('cache')
        if not cache_category:
            # the dependency is declared in the category's meta, which the index reads
            return self.cm.error('the program category\'s dependency on the cache category is not in the index yet: '
                                 'run "cx category update <repo>:program" or "cx --reindex" and retry')
        rx = view.program_entries(self.cm, cache_category, alias, uid)
        if self.cm.catch_error(rx): return rx
        all_entries = rx['entries']
        if not all_entries:
            return self.cm.error(view.missing_message(alias, None, target_tmp))

        entries = all_entries
        wanted = params.get('entry')
        if wanted:
            entries = [e for e in all_entries if view.entry_matches(e, wanted)]
            if not entries:
                return self.cm.error(f'no build entry "{wanted}" of program {alias}; the entries: ' +
                                     '; '.join(view.entry_line(e) for e in all_entries))

        records = view.find_records_in(entries)         # [(entry, target_tmp, path)]

        if show_all:
            if con:
                print ('')
                print (f'Provenance records of program {alias}:')
            summaries = []
            for entry in entries:
                own = [(e, n, p) for e, n, p in records if e is entry]
                if con:
                    print ('')
                    print (f'  {view.entry_line(entry)}')
                    print (f'  {entry["path"]}')
                    if not own:
                        print ('  (no record)')
                for e, name, path in own:
                    ry = view.load_record(path)
                    if ry['return'] > 0:
                        if con:
                            print (f'  {name:14}  {ry["error"]}')
                        continue
                    summaries.append({'target_tmp': name, 'path': path, 'ok': ry['record'].get('ok'),
                                      'created': ry['record'].get('created'), 'compute': ry['record'].get('compute'),
                                      'entry': entry.get('alias'), 'entry_uid': entry.get('uid'),
                                      'request': (entry.get('params') or {}).get('request')})
                    if con:
                        print (view.summary_line(name, ry['record']))
            if con:
                print ('')
            return {'return': 0, 'records': summaries, 'entry_path': entries[0]['path'],
                    'entries': [{'alias': e.get('alias'), 'uid': e.get('uid'), 'path': e['path'], 'params': e.get('params')} for e in entries]}

        # One record: the folder asked for (in the entry asked for, else wherever its record is newest);
        # else the newest record of the entries, "tmp" of a single entry first
        chosen = None
        if target_tmp:
            candidates = [(e, n, p) for e, n, p in records if n == target_tmp]
            if not candidates:
                folder = os.path.join(entries[0]['path'], target_tmp) if len(entries) == 1 else None
                return self.cm.error(view.missing_message(alias, folder, target_tmp))
            chosen = view.newest(candidates)
        elif len(entries) == 1 and os.path.isfile(os.path.join(entries[0]['path'], 'tmp', view.RECORD_FILENAME)):
            chosen = (entries[0], 'tmp', os.path.join(entries[0]['path'], 'tmp', view.RECORD_FILENAME))
        elif records:
            chosen = view.newest(records)
        else:
            return self.cm.error(view.missing_message(alias, os.path.join(entries[0]['path'], 'tmp'), 'tmp'))

        entry, target_tmp, path = chosen
        rx = view.load_record(path)
        if rx['return'] == 16:
            return self.cm.error(view.missing_message(alias, os.path.dirname(path), target_tmp))
        if self.cm.catch_error(rx): return rx
        record = rx['record']

        result = {'return': 0, 'record': record, 'path': path, 'entry_path': entry['path'], 'target_tmp': target_tmp,
                  'entry': entry.get('alias'), 'entry_uid': entry.get('uid'),
                  'entries': len(all_entries), 'records': len(view.find_records_in(all_entries))}

        if other:
            # Another build folder of the same entry, <entry>:<folder> of another, or a record file (from another machine)
            other_path = view.other_record_path(other, entry, all_entries)
            if not other_path:
                return self.cm.error(f'no build entry for --diff={other}; the entries: ' + '; '.join(view.entry_line(e) for e in all_entries))
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
            if len(all_entries) > 1 or entry.get('params') is None:
                print (f'{view.entry_line(entry)}   ({result["records"]} records in {len(all_entries)} entries: --all lists them, --entry=<alias|uid|digest> picks one)')
                print ('')
            print (text)
            print ('')
        return result

    ############################################################
    def clean(self, params):
        """
        Remove the build folders of a program: the tmp* folders of its build entries
        (task--program--<program>[--<uid>], one per request), where "cx program run" builds and
        runs, or the one named by --target_tmp. The entries and the program artifact stay
        ("cx cache delete <entry>" removes an entry, with any venv inside it). Build folders that
        runs before 2026-06 left inside a program artifact are listed, not removed.

            cx program clean <program>                            every build folder of the program
            cx program clean <program> --target_tmp=tmp-static    one build folder (in every entry that has it)
            cx program clean <program> --entry=<alias|uid|digest> the folders of one entry
            cx program clean --all                                every program that has build entries
        """

        if self.cm.debug:
            self.logger.debug("RUNNING program api v1 clean")

        ctx = params['ctx']
        con = ctx['control'].get('con', False)

        target_tmp = params.get('target_tmp')
        every_program = bool(params.get('all', False))

        p = self._prepare_input_from_params(params, base = True)
        for key in ('target_tmp', 'all', 'entry'):
            p.pop(key, None)
        if not p.get('arg1') and not every_program:
            return self.cm.error('name the program (cx program clean <program> [--target_tmp=<name>]), or --all for every program')
        p['command'] = 'find'
        p['con'] = False
        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        cache_category = self.cmeta.get('uses_categories', {}).get('cache')
        if not cache_category:
            return self.cm.error('the program category\'s dependency on the cache category is not in the index yet: '
                                 'run "cx category update <repo>:program" or "cx --reindex" and retry')

        from . import provenance_view as view

        wanted = params.get('entry')
        removed, legacy, without_entry = [], [], []
        for a in r['artifacts']:
            parts = a.get('cmeta_ref_parts', {})
            alias = parts.get('artifact_alias') or parts.get('artifact_uid')

            # The program's build entries, one per request (read only: a program that never ran has none, this makes none)
            rx = view.program_entries(self.cm, cache_category, alias, parts.get('artifact_uid'))
            if self.cm.catch_error(rx): return rx
            entries = rx['entries']
            if wanted:
                entries = [e for e in entries if view.entry_matches(e, wanted)]
            if not entries:
                without_entry.append(alias)
            found_folder = False
            for entry in entries:
                entry_path = entry['path']
                names = [target_tmp] if target_tmp else sorted(x for x in os.listdir(entry_path) if x.startswith('tmp'))
                for name in names:
                    folder = os.path.join(entry_path, name)
                    if not os.path.isdir(folder):
                        continue
                    found_folder = True
                    try:
                        shutil.rmtree(folder)
                    except Exception as e:
                        return self.cm.error(f'{alias}: can\'t remove {folder}: {e}')
                    removed.append(folder)
                    if con:
                        print (f'Removed {folder}')
            if target_tmp and entries and not found_folder:
                return self.cm.error(f'{alias}: no build folder "{target_tmp}" in ' + ', '.join(e['path'] for e in entries))

            # Builds that runs before 2026-06 left inside the artifact (or the author's scratch): reported, kept
            for x in sorted(os.listdir(a['path'])):
                if x.startswith('tmp') and os.path.isdir(os.path.join(a['path'], x)):
                    legacy.append(os.path.join(a['path'], x))

        if con:
            if not removed:
                print ('No build folder to remove' + (f' ({len(without_entry)} program(s) without a cache entry)' if without_entry else ''))
            if legacy:
                print ('')
                print ('Folders inside program artifacts, left in place (builds before 2026-06, or scratch):')
                for folder in legacy:
                    print (f'  {folder}')

        return {'return': 0, 'removed': removed, 'legacy': legacy, 'without_entry': without_entry}

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

