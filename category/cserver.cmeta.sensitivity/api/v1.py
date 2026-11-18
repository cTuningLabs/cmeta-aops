"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cserver.cmeta.sensitivity - Sensitivity and access: cMeta for organisations, a short course (2026-11-18). Eight lessons
with Back / Next and a table of contents: why labels, labelling a repository and an artifact, the scope of a call,
people and their records, writes under a scope, what YOU can see here (live), organising repositories, a check. The
rules are the engine's (cMeta 0.44: docs/sensitivity.md, the skill sensitivity-and-access); the page teaches them and
shows them at work for the person who reads it.

    cx app run cserver      ->  http://127.0.0.1:8004/cmeta.sensitivity
    ?lesson=6               ->  opens a lesson (the page keeps it in the address)

The live lesson: ?native_action=scope asks the engine, inside the request, what the scope of this request means for
every repository (cx repo scope: the label, whether this call reads it and writes into it, why) - the scope the host
passed for the person (a site with users, an API, an agent's key: clearance, allow_repos, hide_repos, write_repos,
default_sensitivity). It shows:

    - under a scope, the repositories the person reads - never the names of the others;
    - every repository to the host's administrators (misc.sensitivity_admin: true, set by a host for its owners and
      admins) - the scope of their own request;
    - without any scope (a shell's cserver): "no scope: you read everything this machine holds", and the list only to
      a browser on the server's own machine, behind the server's password, or to an administrator - a public host
      that passes no scope never names its repositories to a visitor;
    - on an engine before 0.44 (no labels, no scope): that the engine is too old - never an error.

files/sensitivity.yaml holds the title, the labels and their colours, the questions of the check; files/index.html
the lessons. Nothing is written.
"""

import html
import json
import os

import yaml

from cmeta.category import InitCategory

SETTINGS_FILE = 'sensitivity.yaml'
LESSONS = 8

# what the page says about each reason the engine gives (Repos.scope_table's "why")
WHY = {'open': 'not hidden from you (no clearance in this call)', 'clearance': 'within your clearance', 'granted': 'above your clearance, granted to you by name',
       'label': 'above your clearance', 'denied': 'hidden from you by name'}
FROM = {'label': '', 'secrets': 'a repository of secrets', 'local': "this machine's own repository", 'engine': "the engine's own",
        'default': 'no label: the default of this server'}


def _js(obj):
    """A JSON literal safe inside a <script> tag."""
    return json.dumps(obj, ensure_ascii = False).replace('</', '<\\/')


def _asset(path_to_files, url_files, rel):
    """The URL of a file of files/ with its modification time, so a browser never keeps an old copy."""
    url = url_files + rel
    try:
        return '%s?v=%d' % (url, int(os.path.getmtime(os.path.join(path_to_files, *rel.split('/')))))
    except Exception:
        return url


def _yes(value):
    return value is True or str(value).strip().lower() in ('1', 'true', 'yes', 'on')


class Category(InitCategory):
    """
    The course page (command web) and its live lesson (?native_action=scope).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def _uses(self, key):
        return ((self.cmeta or {}).get('uses_categories') or {}).get(key, key)

    def _settings(self):
        """files/sensitivity.yaml, read on every request (a small file; an edit shows without a restart)."""
        try:
            with open(os.path.join(self.path, 'files', SETTINGS_FILE), encoding = 'utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print('cMeta warning: cserver.cmeta.sensitivity: %s unreadable: %s' % (SETTINGS_FILE, e))
            return {}

    def _scope(self, misc = None):
        """
        What the scope of this request means for the repositories of this machine, for the person who asked: the rows
        of `cx repo scope` (asked inside the request, so under the scope the host passed), filtered by who may see
        which names. Never an error for an engine without the labels.
        """
        misc = misc or {}

        try:
            import cmeta
            engine = str(getattr(cmeta, '__version__', '') or '')
        except Exception:
            engine = ''

        repos = getattr(self.cm, 'repos', None)
        if not callable(getattr(repos, 'scope_table', None)):
            return {'supported': False, 'engine': engine,
                    'message': 'This cMeta engine (%s) is older than 0.44: it has no sensitivity labels and no scope of '
                               'a call, so there is nothing to show live. Everything else in this course is how 0.44 and '
                               'newer work.' % (engine or 'version unknown')}

        r = self.cm.access({'category': self._uses('repo'), 'command': 'scope', 'con': False})
        if r.get('return', 1) > 0:
            return {'supported': True, 'engine': engine, 'error': r.get('error', 'cx repo scope failed')}

        from cmeta.repos import sensitivity_label

        scoped = bool(getattr(repos, 'scoped', False))
        write_scoped = bool(getattr(repos, 'write_scoped', False))
        rank = getattr(repos, 'clearance', None)
        admin = _yes(misc.get('sensitivity_admin'))
        # without a scope: the machine's own browser, a browser past the server's password (the engine's cserver says
        # both), or an administrator of the host see the list - a host that passes no scope never names its
        # repositories to anyone else
        own_machine = _yes(misc.get('client_local')) or _yes(misc.get('password_gate'))

        rows = []
        for x in r.get('repos') or []:
            rows.append({'alias': str(x.get('alias') or x.get('uid') or ''), 'uid': str(x.get('uid') or ''),
                         'label': x.get('label'), 'sensitivity': str(x.get('sensitivity') or ''),
                         'from': str(x.get('from') or ''), 'from_text': FROM.get(str(x.get('from') or ''), ''),
                         'read': bool(x.get('read')), 'write': bool(x.get('write')),
                         'why': str(x.get('why') or ''), 'why_text': WHY.get(str(x.get('why') or ''), str(x.get('why') or ''))})

        if scoped or write_scoped:
            shown = rows if admin else [x for x in rows if x['read']]
            listed = True
        else:
            listed = admin or own_machine
            shown = rows if listed else []
            for x in shown:
                x['why_text'] = 'no scope: read as from a shell on this machine'

        return {'supported': True, 'engine': engine, 'scoped': scoped or write_scoped, 'read_scoped': scoped,
                'write_scoped': write_scoped,
                'clearance': None if rank is None else sensitivity_label(rank),
                'admin': admin, 'all': admin or (listed and not (scoped or write_scoped)), 'listed': listed,
                'rows': shown, 'count': len(shown),
                'read': sum(1 for x in shown if x['read']), 'write': sum(1 for x in shown if x['write'])}

    ############################################################
    def web_(
        self,
        ctx,  # Execution context dictionary with category, command, and control data.
        urls,  # The host's URLs: url (this page), url_files (files/ of this category), url_server.
        query = {},  # GET and POST parameters (?lesson=N opens a lesson).
        misc = {},  # Session bits: theme, ctuning_server (cPlatform), client_local / password_gate (the engine's
                    # cserver), sensitivity_admin (a host's owners and admins see every repository in the live lesson).
    ):
        """
        The course (command web), or ?native_action=scope as JSON.
        """
        query = query or {}
        misc = dict(misc or {})
        urls = urls or {}

        na = query.get('native_action', '')
        if na:
            try:
                out = self._scope(misc) if na == 'scope' else {'error': 'unknown native_action %r' % na}
            except Exception as e:
                print('cMeta warning: cserver.cmeta.sensitivity: native_action %r failed: %s: %s' % (na, type(e).__name__, e))
                out = {'error': '%s: %s' % (type(e).__name__, e)}
            return {'return': 0, 'json': out}

        settings = self._settings()
        platform = bool(misc.get('ctuning_server'))
        dark = misc.get('theme', '') == 'dark' or _yes(query.get('dark', ''))

        try:
            lesson = max(1, min(LESSONS, int(str(query.get('lesson') or '1').strip())))
        except ValueError:
            lesson = 1

        data = {'labels': settings.get('labels') or [], 'quiz': settings.get('quiz') or []}
        config = {'dark_mode': bool(dark), 'hosted': platform, 'lesson': lesson, 'lessons': LESSONS,
                  'api_url': urls.get('url') or '?'}

        path_to_files = os.path.join(self.path, 'files')
        url_files = urls.get('url_files') or ''
        with open(os.path.join(path_to_files, 'index.html'), encoding = 'utf-8') as f:
            body = f.read()
        title = str(settings.get('title') or 'Sensitivity and access')
        body = (body.replace('%%DATA%%', _js(data)).replace('%%CONFIG%%', _js(config))
                .replace('%%TITLE%%', html.escape(title)).replace('%%SUBTITLE%%', html.escape(str(settings.get('subtitle') or ''))))
        head = ('\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                '  <link type="text/css" rel="stylesheet" media="all" href="%s">\n'
                '  <script src="%s" defer></script>\n' % (_asset(path_to_files, url_files, 'css/sensitivity.css'),
                                                          _asset(path_to_files, url_files, 'js/sensitivity.js')))
        return {'return': 0, 'html_meta': {'page_title': title, 'page_extra_style': head, 'html': body}}
