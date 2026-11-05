"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cserver.cmeta.targets - where a cMeta program runs: the compute targets against the operating systems, and the
programs against the targets they declare, read live from the artifacts plugged into this machine.

    cx app run cserver      ->  http://127.0.0.1:8004/cmeta.targets

The data:

    targets    "cx program targets": the task/target--<name> artifacts with the "support" block of their _desc.yaml
               (kind, hardware, host_os = the OS of the machine cMeta runs on, device_os = the OS of a device it
               drives, status)
    programs   the program artifacts: constraints.supported_compute of their _cmeta, the "on" block of their
               _desc.yaml (requires_os, a route per OS such as "windows: docker")
    words      files/targets.yaml: the title, the OS columns, the kinds and their colours, the four pillars, the
               families of programs, the GitHub folders of the repositories

    cx cserver.cmeta.targets matrix [--as_json]     the same matrices in a terminal
    ?native_action=matrix                           the JSON the page renders

Nothing is run and nothing is written. A host may name the only repositories whose programs are shown (only_repos -
a cPlatform project pointer: "only_repos": "ctuninglabs@cmeta-aops" in cmeta_params_for_html); the hide_repos of a
call applies as everywhere.
"""

import fnmatch
import html
import json
import os
import urllib.parse

import yaml

from cmeta.category import InitCategory

SETTINGS_FILE = 'targets.yaml'
SAFE = ':,()-_./@'


def _js(obj):
    """A JSON literal safe inside a <script> tag."""
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/')


def _asset(path_to_files, url_files, rel):
    """The URL of a file of files/ with its modification time, so a browser never keeps an old copy."""
    url = url_files + rel
    try:
        return '%s?v=%d' % (url, int(os.path.getmtime(os.path.join(path_to_files, *rel.split('/')))))
    except Exception:
        return url


def _listed(patterns, *names):
    """True when one of the names (a repository's alias, its UID) matches one of the patterns; no patterns = all."""
    if not patterns:
        return True
    names = [str(n).lower() for n in names if n]
    return any(fnmatch.fnmatch(n, p) for p in patterns for n in names)


class Category(InitCategory):
    """
    The page of the compute targets and the programs (command web) and its data in a terminal (command matrix).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def _uses(self, key):
        return ((self.cmeta or {}).get('uses_categories') or {}).get(key, key)

    def _settings(self):
        """files/targets.yaml, read on every request (a small file; an edit shows without a restart)."""
        try:
            with open(os.path.join(self.path, 'files', SETTINGS_FILE), encoding = 'utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print('cMeta warning: cserver.cmeta.targets: %s unreadable: %s' % (SETTINGS_FILE, e))
            return {}

    def _count(self, key, patterns):
        """How many artifacts of a category the shown repositories hold."""
        r = self.cm.access({'category': self._uses(key), 'command': 'find', 'con': False})
        if r.get('return', 1) > 0:
            return 0
        return sum(1 for a in r.get('artifacts', [])
                   if _listed(patterns, (a.get('cmeta_ref_parts') or {}).get('repo_alias'),
                              (a.get('cmeta_ref_parts') or {}).get('repo_uid')))

    def _matrix(self, misc = None, only_repos = ''):
        """The targets with what they support, the programs with the targets they declare, the words of the page."""
        misc = misc or {}
        settings = self._settings()
        patterns = [x.strip().lower() for x in str(only_repos or '').split(',') if x.strip()]

        # the targets ("cx program targets" reads the support block of each target task)
        r = self.cm.access({'category': self._uses('program'), 'command': 'targets', 'con': False})
        if r.get('return', 1) > 0:
            return {'error': r.get('error', 'cx program targets failed')}

        kind_of = {}
        for k in settings.get('kinds') or []:
            for x in [k.get('id')] + list(k.get('also') or []):
                kind_of[x] = k.get('id')

        targets = []
        for t in r.get('targets') or []:
            s = t.get('support') or {}
            desc = str(t.get('desc') or '')
            if desc.startswith('Compute target: '):
                desc = desc[len('Compute target: '):]
            targets.append({'id': t['target'], 'name': t.get('name') or t['target'], 'desc': desc,
                            'kind': kind_of.get(s.get('kind'), s.get('kind') or ''), 'hardware': s.get('hardware') or '',
                            'host_os': list(s.get('host_os') or []), 'device_os': s.get('device_os') or '',
                            'status': s.get('status') or ('supported' if s else 'undeclared'), 'programs': 0})
        by_id = {t['id']: t for t in targets}

        # the programs and the targets each declares
        r = self.cm.access({'category': self._uses('program'), 'command': 'find', 'con': False})
        if r.get('return', 1) > 0:
            return {'error': r.get('error', 'cx program find failed')}

        cref_url = str(misc.get('cref_url') or '')
        github = settings.get('github') or {}
        families = settings.get('families') or []

        programs = []
        for a in r.get('artifacts') or []:
            parts = a.get('cmeta_ref_parts') or {}
            repo, repo_uid = parts.get('repo_alias') or '', parts.get('repo_uid') or ''
            if not _listed(patterns, repo, repo_uid):
                continue

            meta = a.get('cmeta') or {}
            alias = parts.get('artifact_alias') or ''
            compute = [str(x) for x in ((meta.get('constraints') or {}).get('supported_compute') or [])]

            # the program's own route: requires_os and a route per OS ("windows: docker:sglang")
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a.get('path') or '', '_desc'))
            data = (rd.get('data') or {}) if rd.get('return', 1) == 0 else {}
            on = data.get('on') or data.get(True) or {}     # PyYAML (YAML 1.1) reads the key on: as True
            on = on if isinstance(on, dict) else {}
            requires = [str(x) for x in (on.get('requires_os') or [])]
            routes = {k: str(v) for k, v in on.items() if k in ('linux', 'windows', 'darwin') and v}

            # where it runs: the OS of its targets (a device's own OS for a device target), narrowed to requires_os;
            # an OS left out but given a route (docker) is reached through that route
            native, via = set(), {}
            for c in compute:
                t = by_id.get(c)
                if not t or t['status'] == 'placeholder':
                    continue
                t['programs'] += 1
                if t['device_os']:
                    native.add(t['device_os'])
                else:
                    native.update(t['host_os'])
            if requires:
                for o in [o for o in native if o in ('linux', 'windows', 'darwin') and o not in requires]:
                    native.discard(o)
            for o, route in routes.items():
                if o not in native:
                    via[o] = route

            family = next((f.get('name') for f in families
                           if any(fnmatch.fnmatch(alias, m) for m in (f.get('match') or []))), 'Other programs')

            cref = 'program::%s,%s' % (alias, parts.get('artifact_uid') or '')
            link = (cref_url + urllib.parse.quote(cref, safe = SAFE)) if cref_url else \
                   ('%s/program/%s' % (github[repo].rstrip('/'), alias) if repo in github else '')

            programs.append({'alias': alias, 'name': str(meta.get('name') or alias), 'desc': str(meta.get('desc') or ''),
                             'tags': [str(x) for x in (meta.get('tags') or [])][:8], 'repo': repo, 'family': family,
                             'targets': compute, 'os': sorted(native), 'via': via, 'requires_os': requires,
                             'link': link, 'cmd': 'cx program run %s %s' % (alias, compute[0] if compute else 'cpu')})

        order = {f.get('name'): i for i, f in enumerate(families)}
        programs.sort(key = lambda p: (order.get(p['family'], 999), p['alias']))

        return {'title': settings.get('title') or 'cMeta programs everywhere', 'subtitle': settings.get('subtitle') or '',
                'os': settings.get('os') or [], 'kinds': settings.get('kinds') or [], 'pillars': settings.get('pillars') or [],
                'families': [f.get('name') for f in families], 'targets': targets, 'programs': programs,
                'counts': {'programs': len(programs), 'targets': sum(1 for t in targets if t['status'] == 'supported'),
                           'planned': sum(1 for t in targets if t['status'] == 'placeholder'),
                           'tools': self._count('tool', patterns), 'tasks': self._count('task', patterns)}}

    ############################################################
    def web_(
        self,
        ctx,  # Execution context dictionary with category, command, and control data.
        urls,  # The host's URLs: url (this page), url_files (files/ of this category), url_server.
        query = {},  # GET and POST parameters.
        misc = {},  # Session bits (theme, ctuning_server on cPlatform; cref_url on a host with artifact pages).
        only_repos = '',  # The repositories whose programs are shown (aliases, UIDs or patterns): set by a host in the
                          # call - a project pointer of the cPlatform -, never by the address; '' = every one.
    ):
        """
        The page (command web), or ?native_action=matrix as JSON.
        """
        query = query or {}
        misc = dict(misc or {})
        urls = urls or {}

        url_server = urls.get('url_server') or '/'
        platform = bool(misc.get('ctuning_server'))
        if not misc.get('cref_url') and not platform:
            misc['cref_url'] = url_server.rstrip('/') + '/cref/'     # the engine cserver's artifact page

        na = query.get('native_action', '')
        if na:
            try:
                out = self._matrix(misc, only_repos) if na == 'matrix' else {'error': 'unknown native_action %r' % na}
            except Exception as e:
                print('cMeta warning: cserver.cmeta.targets: native_action %r failed: %s: %s' % (na, type(e).__name__, e))
                out = {'error': '%s: %s' % (type(e).__name__, e)}
            return {'return': 0, 'json': out}

        try:
            data = self._matrix(misc, only_repos)
        except Exception as e:
            data = {'error': '%s: %s' % (type(e).__name__, e)}

        dark = misc.get('theme', '') == 'dark' or str(query.get('dark', '')).lower() in ('1', 'true', 'yes')
        config = {'dark_mode': bool(dark), 'hosted': platform, 'state': {k: str(query.get(k) or '') for k in ('q', 'target', 'os')}}

        path_to_files = os.path.join(self.path, 'files')
        url_files = urls.get('url_files') or ''
        with open(os.path.join(path_to_files, 'index.html'), encoding = 'utf-8') as f:
            body = f.read()
        title = data.get('title') or 'cMeta programs everywhere'
        body = (body.replace('%%DATA%%', _js(data)).replace('%%CONFIG%%', _js(config))
                .replace('%%TITLE%%', html.escape(title)).replace('%%SUBTITLE%%', html.escape(data.get('subtitle') or '')))
        head = ('\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                '  <link type="text/css" rel="stylesheet" media="all" href="%s">\n'
                '  <script src="%s" defer></script>\n' % (_asset(path_to_files, url_files, 'css/targets.css'),
                                                          _asset(path_to_files, url_files, 'js/targets.js')))
        return {'return': 0, 'html_meta': {'page_title': title, 'page_extra_style': head, 'html': body}}

    ############################################################
    def matrix_(
        self,
        ctx,  # Execution context dictionary with category, command, and control data.
        only_repos = '',  # The repositories whose programs are shown (aliases, UIDs or patterns); '' = every one.
        as_json = False,  # Print the JSON instead of the tables.
    ):
        """
        The targets against the operating systems and the programs against the targets, in a terminal.

            cx cserver.cmeta.targets matrix [--only_repos=ctuninglabs@cmeta-aops] [--as_json]
        """
        data = self._matrix({}, only_repos)
        if data.get('error'):
            return self.cm.error(data['error'])

        if ctx['control'].get('con', False):
            if as_json:
                print(json.dumps(data, indent = 2, ensure_ascii = False))
            else:
                oss = data['os']
                w = max([len(t['id']) for t in data['targets']] + [8])
                print('')
                print('%-*s  %s  programs' % (w, 'target', '  '.join('%-7s' % o['name'] for o in oss)))
                for t in data['targets']:
                    cells = []
                    for o in oss:
                        if t['status'] == 'placeholder':
                            mark = '-'
                        elif o.get('device'):
                            mark = 'runs' if t['device_os'] == o['id'] else ''
                        elif t['device_os']:
                            mark = 'drives' if o['id'] in t['host_os'] else ''
                        else:
                            mark = 'runs' if o['id'] in t['host_os'] else ''
                        cells.append('%-7s' % mark)
                    print('%-*s  %s  %d' % (w, t['id'], '  '.join(cells), t['programs']))
                print('')
                c = data['counts']
                print('%d programs, %d targets (%d planned), %d tools, %d tasks' %
                      (c['programs'], c['targets'], c['planned'], c['tools'], c['tasks']))
                print('')

        return {'return': 0, **data}
