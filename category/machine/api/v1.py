"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

machine - a physical or cloud machine as an asset: who owns it, what it is, when and how it was
acquired, what it costs, where it is. Everything that can be logged in to on it (an OS, a WSL
distro, a container, a phone) is a host artifact that points back here with "machine: <cRef>".

Declared in _desc.yaml by hand (the layout is in ../README.md).
"""

import os

from cmeta.category import InitCategory

DESC_FILE = '_desc.yaml'

LIST_COLUMNS = ['MACHINE', 'OWNER', 'KIND', 'STATUS', 'MODEL', 'ACQUIRED', 'HOSTS']


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def list_(
        self,
        ctx,
        arg1=None,          # machine alias, UID or wildcard (default: all)
        tags=None,          # only machines with these tags
        owner=None,         # only this owner (fgg, dapple, ctuning ...)
        kind=None,          # only this kind (laptop, desktop, vm, phone, tablet, cluster ...)
        sort=None,          # accepted for compatibility with the base command
        skip_uids=False,    # accepted for compatibility with the base command
    ):
        """
        The machines as a table, with the hosts that live on each.

            cx machine ls
            cx machine ls --owner=fgg
        """

        con = ctx['control'].get('con', False)

        r = self._select(ctx, arg1, tags, owner, kind)
        if self.cm.catch_error(r): return r
        machines = r['machines']

        r = self._hosts_by_machine(ctx)
        if self.cm.catch_error(r): return r
        by_machine = r['by_machine']

        rows = []
        for m in machines:
            d = m['desc']
            hosts = by_machine.get(m['alias'], [])
            rows.append([m['alias'], str(d.get('owner', '-')), str(d.get('kind', '-')),
                         'retired' if d.get('retired') is True else '-',
                         str(d.get('model') or d.get('name') or '-'), str(d.get('acquired', '-')),
                         ', '.join(hosts) if hosts else '-'])

        if con:
            widths = [len(c) for c in LIST_COLUMNS]
            for row in rows:
                for i, cell in enumerate(row):
                    widths[i] = max(widths[i], len(cell))
            fmt = '  '.join('{:<' + str(w) + '}' for w in widths)
            print(fmt.format(*LIST_COLUMNS).rstrip())
            for row in rows:
                print(fmt.format(*row).rstrip())
            if not rows:
                print('no machines' + (' match' if (arg1 or tags or owner or kind) else ' yet'))

        return {'return': 0, 'machines': [{'alias': m['alias'], 'desc': m['desc'], 'hosts': by_machine.get(m['alias'], []),
                                          'retired': m['desc'].get('retired') is True,
                                          'status': 'retired' if m['desc'].get('retired') is True else '-'}
                                          for m in machines]}

    ############################################################
    def show_(
        self,
        ctx,
        arg1=None,          # machine alias
    ):
        """
        A machine's declared facts (_desc.yaml) and its hosts.

            cx machine show my-pc
        """

        con = ctx['control'].get('con', False)

        if not arg1:
            return self.cm.error('which machine? cx machine show <machine>')

        r = self._select(ctx, arg1)
        if self.cm.catch_error(r): return r
        machines = r['machines']
        if len(machines) != 1:
            return self.cm.error(f'"{arg1}" matches {len(machines)} machines')
        m = machines[0]

        r = self._hosts_by_machine(ctx)
        if self.cm.catch_error(r): return r
        hosts = r['by_machine'].get(m['alias'], [])

        if con:
            import yaml
            print(f'# {m["alias"]}  ({m["path"]})')
            print('')
            print(yaml.safe_dump(m['desc'], sort_keys=False, allow_unicode=True, width=120).rstrip())
            print('')
            print('# hosts: ' + (', '.join(hosts) if hosts else 'none yet'))

        return {'return': 0, 'machine': {'alias': m['alias'], 'path': m['path'], 'desc': m['desc'], 'hosts': hosts,
                                         'retired': m['desc'].get('retired') is True,
                                         'status': 'retired' if m['desc'].get('retired') is True else '-'}}

    ############################################################
    def _select(self, ctx, arg1=None, tags=None, owner=None, kind=None):
        p = self._prepare_input_from_params({'ctx': ctx, 'arg1': arg1, 'tags': tags}, base=True)
        p['command'] = 'find'
        p['con'] = False
        r = self.cm.access(p)
        if r['return'] > 0 and r['return'] != 16: return r

        machines = []
        for a in r.get('artifacts', []):
            path = a['path']
            parts = a.get('cmeta_ref_parts', {})
            alias = parts.get('artifact_alias') or parts.get('artifact_uid') or os.path.basename(path)
            desc = {}
            f = os.path.join(path, DESC_FILE)
            if os.path.isfile(f):
                rr = self.cm.utils.files.safe_read_file(f, logger=self.logger)
                if rr['return'] == 0:
                    desc = rr.get('data') or {}
            if owner and str(desc.get('owner', '')) != owner: continue
            if kind and str(desc.get('kind', '')) != kind: continue
            machines.append({'alias': alias, 'uid': parts.get('artifact_uid'), 'path': path, 'desc': desc})

        machines.sort(key=lambda x: x['alias'])
        return {'return': 0, 'machines': machines}

    def _hosts_by_machine(self, ctx):
        """{machine alias: [host aliases]} from the host artifacts' "machine:" references."""
        r = self.cm.access({'category': self.cmeta['uses_categories']['host'], 'command': 'find', 'con': False})
        if r['return'] > 0 and r['return'] != 16: return r

        by_machine = {}
        for a in r.get('artifacts', []):
            f = os.path.join(a['path'], DESC_FILE)
            if not os.path.isfile(f): continue
            rr = self.cm.utils.files.safe_read_file(f, logger=self.logger)
            if rr['return'] > 0: continue
            ref = str((rr.get('data') or {}).get('machine') or '')
            if not ref: continue
            if '::' in ref: ref = ref.split('::')[-1]
            ref = ref.split(',')[0].strip()
            parts = a.get('cmeta_ref_parts', {})
            by_machine.setdefault(ref, []).append(parts.get('artifact_alias') or parts.get('artifact_uid'))

        for k in by_machine:
            by_machine[k].sort()
        return {'return': 0, 'by_machine': by_machine}
