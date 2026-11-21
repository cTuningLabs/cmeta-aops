"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

ai.gateway - a place that serves models to the AI harnesses (README.md): a company's gateway, a vendor's API, a
llama.cpp or vLLM server here or on a host. The artifact (_desc.yaml) names the base URL, the wires it speaks
(anthropic: the Messages API; openai: chat completions and the Responses API), the catalog of its models, how the key
travels (auth.header) and which secret artifact holds it (auth.secret) - never a value. "connect" gives a harness the
environment and the arguments it needs, "models" lists what a harness can use there, "test" says hello on every wire.

A pass-through - a server that sits between a harness and the place its requests go to, to log or to forward them -
is an artifact too: "upstream" names where its traffic goes (another gateway's alias: its wires, catalog, key and
models are taken from there unless the artifact says otherwise), and auth.header "login" says the harness keeps its
own account and only the address changes.

A gateway server reached over a network may ask its clients for a key of its own (client_key: {header, secret}): the
secret holds it, every request to that gateway carries it in that header, and the server keeps only its SHA-256 and
passes it on to nobody.
"""

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cmeta.category import InitCategory

CATEGORY = 'ai.gateway,ae1ae632e0ec4f75'
SECRET_CATEGORY = 'secret,9d63451ea1f14010'
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'

# This machine's default for the harness runs, in config::default (the task set-ai-gateway reads it): the general
# switch, the gateway it means, and a key per harness that goes before them (login | <alias>)
CONFIG_ARTIFACT = 'default'
CONFIG_ON = 'run_ai_gateway'
CONFIG_NAME = 'run_ai_gateway_name'
CONFIG_HARNESS = 'run_ai_gateway_'

# the wire each harness speaks (opencode and openclaw take both, through their provider packages)
HARNESS_WIRES = {'claude': ('anthropic',), 'codex': ('openai',), 'opencode': ('anthropic', 'openai'),
                 'openclaw': ('anthropic', 'openai'), 'hermes': ('openai',)}

# the variable the key travels in to Codex's provider block (which names the variable, never the value) and to Claude
# Code's apiKeyHelper
KEY_VAR = 'CMETA_AI_GATEWAY_KEY'

# The run a request belongs to: run-ai puts the cMeta artifact it runs from, its conversation and its run into this
# variable ("project=<cRef>;conversation=<id>;run=<stamp>", each value percent-encoded). A gateway that asks for it -
# its run_header names the header, a gateway server of one's own that keeps a line per request - is sent it by the
# harness; no other gateway ever is.
RUN_VAR = 'CMETA_AI_RUN'

# The variable that carries a gateway's client key to Codex (its env_http_headers names it): never on a command line
CLIENT_KEY_VAR = 'CMETA_AI_GATEWAY_CLIENT_KEY'

ANTHROPIC_VERSION = '2023-06-01'

# auth.header "login": the harness keeps its own account (a subscription), the artifact changes only the address its
# requests go to - a pass-through in front of the vendor's own address. The harnesses with a recipe for it:
LOGIN = 'login'
LOGIN_HARNESSES = ('claude', 'codex')

# what a pass-through takes from the gateway its "upstream" names, when it does not say it itself
INHERITED = ('wires', 'catalog', 'catalogs', 'auth', 'models', 'codex_wire', 'opencode_openai_npm', 'thinking_off')

# thinking_off (2026-11-21): what a request adds to turn the hidden reasoning of an open model off - for a server that
# reads it, such as llama.cpp, vLLM or SGLang with a Qwen3-like chat template:
#   thinking_off: {chat_template_kwargs: {enable_thinking: false}}
# A task that asks a model itself (gen-ai) adds it to its request; nothing else reads it. A gateway that declares none
# gets nothing added (a vendor's API may refuse a word it does not know).


def key_helper():
    """
    Claude Code's apiKeyHelper for a gateway key: this Python, isolated, prints KEY_VAR. Claude Code runs the helper
    through a shell - cmd or bash on Windows, sh elsewhere: a quoted path with forward slashes and a program without
    $, % or backslashes reads the same in each.
    """
    return '"%s" -I -c "import os;print(os.environ.get(\'%s\', \'\'))"' % (sys.executable.replace('\\', '/'), KEY_VAR)


class Category(InitCategory):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################ the artifacts
    def _one(self, ctx, arg1):
        """One gateway artifact -> {'return': 0, 'alias', 'uid', 'path', 'repo', 'desc'}; 16 when there is none."""
        if not arg1:
            return self.cm.error('name a gateway: cx ai.gateway <command> <alias> (cx ai.gateway ls shows them)')
        r = self.cm.access({'category': CATEGORY, 'command': 'find', 'arg1': arg1, 'con': False})
        if r['return'] > 0:
            return r
        arts = r.get('artifacts', [])
        if not arts:
            return {'return': 16, 'error': 'gateway "%s" not found (cx ai.gateway ls shows them)' % arg1}
        if len(arts) > 1:
            return self.cm.error('"%s" names %d gateways - use alias,UID' % (arg1, len(arts)))
        a = arts[0]
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
        desc = (rd.get('data') or {}) if rd['return'] == 0 else {}
        parts = a['cmeta_ref_parts']
        return {'return': 0, 'alias': parts['artifact_alias'], 'uid': parts['artifact_uid'], 'path': a['path'],
                'repo': parts.get('repo_alias') or parts.get('artifact_repo_alias', ''),
                'desc': self._inherit(desc if isinstance(desc, dict) else {})}

    def _inherit(self, desc):
        """A pass-through that names another gateway as its upstream (upstream: <alias>) takes from it what it does
        not say itself - the wires, the catalog, how the key travels, the models: one place to change them. An
        upstream given as an address, or per wire, brings nothing; an upstream's own upstream is not followed."""
        up = desc.get('upstream')
        if not isinstance(up, str) or not up.strip() or '://' in up:
            return desc
        r = self.cm.access({'category': CATEGORY, 'command': 'find', 'arg1': up.strip(), 'con': False})
        arts = r.get('artifacts', []) if r.get('return', 1) == 0 else []
        if len(arts) != 1:
            return desc
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(arts[0]['path'], '_desc'))
        parent = (rd.get('data') or {}) if rd['return'] == 0 else {}
        if not isinstance(parent, dict):
            return desc
        return dict({k: parent[k] for k in INHERITED if k in parent}, **desc)

    @staticmethod
    def _wires(desc):
        """{wire: path under the base} - a wire with no path ('' or null) is right under the base."""
        w = desc.get('wires') or {}
        return {str(k).lower(): ('' if v is None else str(v)) for k, v in w.items()} if isinstance(w, dict) else {}

    @staticmethod
    def _url(desc, path):
        base = str(desc.get('base_url') or '').rstrip('/')
        path = str(path or '')
        return base + (path if (not path or path.startswith('/')) else '/' + path)

    def _key(self, ctx, desc):
        """The key of a gateway -> (the value or '', the header name or 'none', an error or ''). The value comes from
        the secret artifact auth.secret names (kind token: files/token, or env: NAME) and is returned to the caller
        only - the task that starts a harness; nothing here prints it."""
        auth = desc.get('auth') or {}
        header = str(auth.get('header') or 'none').strip().lower()
        if header == 'none':
            return '', 'none', ''
        if header == LOGIN:
            # the harness's own account: there is no key to find, and none is ever read
            return '', LOGIN, ''
        name = str(auth.get('secret') or '').strip()
        if not name:
            return '', header, 'auth.header is "%s" but auth.secret names no secret' % header
        r = self.cm.access({'category': SECRET_CATEGORY, 'command': 'find', 'arg1': name, 'con': False})
        arts = r.get('artifacts', []) if r.get('return', 1) in (0, 16) else []
        if not arts:
            return '', header, ('the secret "%s" is not on this machine - from the machine that has it: '
                                'cx host push <this host> <its secrets repository> --artifacts="secret::%s" --secrets' % (name, name))
        path = arts[0]['path']
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(path, '_desc'))
        sd = (rd.get('data') or {}) if rd['return'] == 0 else {}
        token = sd.get('token') if isinstance(sd, dict) else None
        if isinstance(token, str):
            token = {'file': token}
        token = token or {}
        if token.get('env'):
            v = os.environ.get(str(token['env']), '').strip()
            return v, header, '' if v else 'the secret "%s" names the variable %s, which is not set' % (name, token['env'])
        f = str(token.get('file') or 'files/token')
        fp = os.path.join(path, *f.replace('\\', '/').split('/'))
        if not os.path.isfile(fp):
            return '', header, 'the secret "%s" has no %s (cx secret import %s)' % (name, f, name)
        with open(fp, encoding = 'utf-8') as h:
            v = h.read().strip()
        return v, header, '' if v else 'the secret "%s": %s is empty' % (name, f)

    def _client_key(self, ctx, desc):
        """The key a gateway asks of its clients (client_key: {header, secret}) - a gateway server of one's own reached over
        a network checks it before anything else and passes it on to nobody. -> (the headers to add: {} when the gateway
        asks none, an error or ''). The value comes from the secret, like a key, and is never printed."""
        ck = desc.get('client_key')
        if not ck:
            return {}, ''
        if not isinstance(ck, dict):
            return {}, 'client_key must be {header: <a header name>, secret: <the secret that holds the key>}'
        header = str(ck.get('header') or '').strip().lower()
        if not re.fullmatch(r'[a-z0-9-]{1,64}', header) or header in ('authorization', 'x-api-key'):
            return {}, 'client_key.header must be a header of its own (letters, digits, dashes; not authorization, not x-api-key)'
        value, _, err = self._key(ctx, {'auth': {'header': header, 'secret': ck.get('secret')}})
        if err:
            return {}, 'client_key: ' + err
        return {header: value}, ''

    @staticmethod
    def _headers(header, key, extra = None):
        h = {'Content-Type': 'application/json'}
        if key and header == 'bearer':
            h['Authorization'] = 'Bearer ' + key
        elif key:
            h[header] = key
        h.update(extra or {})
        return h

    @staticmethod
    def _http(url, headers, body = None, timeout = 60):
        """GET, or POST a dict -> (the status or 0, the parsed JSON or the text's head)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data = data, headers = headers)
        try:
            with urllib.request.urlopen(req, timeout = timeout) as r:
                status, text = r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode('utf-8', 'replace')
        except Exception as e:
            return 0, str(e)
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text[:400]

    def _catalog(self, desc, wire, header, key, client = None):
        """The model names a wire offers -> (names, the url, an error or ''): the wire's own catalog (catalogs: {wire:
        path}) when declared, else the whole catalog - of which the anthropic wire takes the claude-* names."""
        cats = desc.get('catalogs') if isinstance(desc.get('catalogs'), dict) else {}
        own = cats.get(wire)
        path = own or desc.get('catalog')
        if not path:
            return [], '', 'no catalog declared (catalog: /v1/models)'
        url = self._url(desc, path)
        extra = dict(client or {})
        if wire == 'anthropic':
            extra['anthropic-version'] = ANTHROPIC_VERSION
        status, data = self._http(url, self._headers(header, key, extra))
        if status != 200 or not isinstance(data, dict):
            return [], url, 'http %s from %s: %s' % (status, url, str(data)[:200])
        names = [str(m.get('id')) for m in (data.get('data') or []) if isinstance(m, dict) and m.get('id')]
        if wire == 'anthropic' and not own and any(n.lower().startswith('claude') for n in names):
            # a vendor-mixed catalog (a gateway): the anthropic wire takes the Claude names; a local server's catalog
            # (its loaded models, whatever their names) is taken whole
            names = [n for n in names if n.lower().startswith('claude')]
        return sorted(names, key = str.lower), url, ''

    @staticmethod
    def _start_hint(desc):
        """The command that starts a local gateway (provided_by: {task, params}), or ''."""
        pb = desc.get('provided_by') if isinstance(desc.get('provided_by'), dict) else {}
        if not pb.get('task'):
            return ''
        words = ['cx', 'task', 'run', str(pb['task'])]
        for k, v in (pb.get('params') or {}).items():
            words.append('--%s=%s' % (k, v))
        return ' '.join(words)

    def _reachable(self, desc, wire, header, key, client = None):
        """The catalog of the wire answers -> ''; else what went wrong, with the start command of a local gateway.
        A gateway without a catalog is not asked anything - but one that names the task providing it must at least
        accept a connection (a pass-through for a login has no catalog to read without that login)."""
        cats = desc.get('catalogs') if isinstance(desc.get('catalogs'), dict) else {}
        if not (cats.get(wire) or desc.get('catalog')) or header == LOGIN:
            hint = self._start_hint(desc)
            u = urllib.parse.urlsplit(str(desc.get('base_url') or ''))
            if not hint or not u.hostname:
                return ''
            port = u.port or (443 if u.scheme == 'https' else 80)
            try:
                with socket.create_connection((u.hostname, port), timeout = 2):
                    return ''
            except OSError:
                return 'the gateway does not answer (nothing listens on %s:%d); start it: %s' % (u.hostname, port, hint)
        names, url, e = self._catalog(desc, wire, header, key, client)
        if not e:
            return ''
        hint = self._start_hint(desc)
        return 'the gateway does not answer (%s)%s' % (e, ('; start it: ' + hint) if hint else '')

    @staticmethod
    def _defaults(desc, harness):
        """The models block of a harness ({default, opus, sonnet, haiku, ...}) and the top-level default."""
        models = desc.get('models') if isinstance(desc.get('models'), dict) else {}
        mine = models.get(harness) if isinstance(models.get(harness), dict) else {}
        top = models.get('default') if isinstance(models.get('default'), str) else ''
        return mine, top

    ############################################################ ls
    def list_(self, ctx, arg1: str = None):
        """
        The gateways this machine knows: alias, base URL, wires, auth (the header and the secret's name), repository.
        (cx ai.gateway ls: the engine turns ls into list before it looks for the command, so the listing is list_.)

            cx ai.gateway ls
        """
        r = self.cm.access({'category': CATEGORY, 'command': 'find', 'arg1': arg1 or '*', 'con': False})
        if r['return'] > 0 and r['return'] != 16:
            return r
        rows = []
        for a in sorted(r.get('artifacts', []), key = lambda a: a['cmeta_ref_parts']['artifact_alias']):
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            desc = (rd.get('data') or {}) if rd['return'] == 0 else {}
            desc = self._inherit(desc if isinstance(desc, dict) else {})
            auth = desc.get('auth') or {}
            # where a pass-through sends its traffic: a gateway's alias, an address, or one address per wire
            up = desc.get('upstream')
            up = ', '.join('%s: %s' % (k, v) for k, v in sorted(up.items())) if isinstance(up, dict) else str(up or '')
            rows.append({'alias': a['cmeta_ref_parts']['artifact_alias'], 'uid': a['cmeta_ref_parts']['artifact_uid'],
                         'base_url': str(desc.get('base_url') or ''), 'wires': ','.join(sorted(self._wires(desc))),
                         'auth': str(auth.get('header') or 'none') + (' (' + str(auth['secret']) + ')' if auth.get('secret') else '')
                                 + (' + client key (%s)' % (desc.get('client_key') or {}).get('secret', '?') if isinstance(desc.get('client_key'), dict) else ''),
                         'provided_by': str((desc.get('provided_by') or {}).get('task') or ''), 'upstream': up,
                         'repo': a['cmeta_ref_parts'].get('repo_alias') or a['cmeta_ref_parts'].get('artifact_repo_alias', '')})
        if ctx['control'].get('con', False):
            if not rows:
                print('no gateway artifacts (cx ai.gateway add <repository>:<alias>, then its _desc.yaml - the README)')
            else:
                w = max(len(x['alias']) for x in rows)
                print('%-*s  %-44s  %-17s  %-30s  %s' % (w, 'GATEWAY', 'BASE URL', 'WIRES', 'AUTH (secret)', 'REPO'))
                for x in rows:
                    print('%-*s  %-44s  %-17s  %-30s  %s' % (w, x['alias'], x['base_url'][:44], x['wires'], x['auth'][:30], x['repo']))
        return {'return': 0, 'gateways': rows}

    ############################################################ this machine's default, and the choice of one
    def _machine_default(self):
        """What config::default says of the harness runs -> {'on', 'name', 'harness': {<harness>: login | <alias>}}."""
        try:
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': CONFIG_ARTIFACT, 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
        except Exception:
            cfg = {}
        cfg = cfg if isinstance(cfg, dict) else {}
        on = cfg.get(CONFIG_ON) is True or str(cfg.get(CONFIG_ON) or '').strip().lower() in ('true', 'yes', 'on', '1')
        return {'on': on, 'name': str(cfg.get(CONFIG_NAME) or '').strip(),
                'harness': {k[len(CONFIG_HARNESS):]: str(v).strip() for k, v in cfg.items()
                            if k.startswith(CONFIG_HARNESS) and k != CONFIG_NAME and v not in (None, '')}}

    def default_(self, ctx, arg1: str = None, harness: str = '', unset: bool = False):
        """
        This machine's default gateway for the harness runs (config::default): shown, set, or removed. A run takes it
        when nothing closer says otherwise - a flag, what its project ran with last, what its project declares.

            cx ai.gateway default                        # what the runs take here
            cx ai.gateway default acme                   # acme becomes the default
            cx ai.gateway default acme --harness=codex   # ... the default of Codex, where Codex has a key of its own
            cx ai.gateway default --unset                # no default gateway: the tools run on their own logins
        """
        con = ctx['control'].get('con', False)
        harness = str(harness or '').strip().lower()
        alias = str(arg1 or '').strip()
        before = self._machine_default()
        out = {'return': 0}

        def write(command, meta):
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': command, 'arg1': CONFIG_ARTIFACT, 'meta': meta, 'con': False})
            return r if r.get('return', 1) > 0 else None

        if unset:
            if alias:
                return self.cm.error('--unset removes the default gateway of this machine: it takes no gateway (got "%s")' % alias)
            # a harness's own key goes too when it names a gateway; one that pins the harness to its login stays
            gone = [k for k in (CONFIG_ON, CONFIG_NAME) if before['on'] or before['name']]
            own = before['harness'].get(harness, '')
            if harness and own and own.lower() != LOGIN:
                gone.append(CONFIG_HARNESS + harness)
            if gone:
                err = write('unset', {k: '' for k in gone})
                if err:
                    return err
            out['removed'] = gone
            if con:
                print('default gateway of this machine: %s' % ('removed (%s of config::%s)' % (', '.join(gone), CONFIG_ARTIFACT)
                                                             if gone else 'there was none'))

        elif alias:
            if alias.lower() == LOGIN:
                return self.cm.error('"login" is no gateway: cx ai.gateway default --unset removes the default gateway, and the tools run on their own logins')
            g = self._one(ctx, alias)
            if g['return'] > 0:
                return self.cm.error(g.get('error') or 'gateway "%s" not found' % alias)
            alias = g['alias']
            # where a harness has a key of its own, that key decides for it: it is the one to change
            if harness and harness in before['harness']:
                meta = {CONFIG_HARNESS + harness: alias}
            else:
                meta = {CONFIG_ON: True, CONFIG_NAME: alias}
            err = write('set', meta)
            if err:
                return err
            out['written'] = meta
            if con:
                print('default gateway of this machine: %s (%s of config::%s)' % (alias, ', '.join(sorted(meta)), CONFIG_ARTIFACT))

        now = self._machine_default()
        out.update({'default': now['name'] if now['on'] else '', 'name': now['name'], 'on': now['on'], 'harness': now['harness']})
        if con:
            if not unset and not alias:
                print('default gateway of this machine: %s' % (now['name'] if now['on'] and now['name'] else 'none - the tools run on their own logins'))
                if now['name'] and not now['on']:
                    print('  %s names %s, but %s is off: used by a bare -gw only' % (CONFIG_NAME, now['name'], CONFIG_ON))
            for h in sorted(now['harness']):
                print('  %s: %s (%s%s - it goes before the default)' % (h, now['harness'][h], CONFIG_HARNESS, h))
            if not unset and not alias:
                print('  a run takes it when nothing closer says otherwise: a flag (-gw=<alias>, -ln), what its project ran with last, what its project declares')
        return out

    def pick_(self, ctx, arg1: str = None, harness: str = ''):
        """
        The gateways of this machine as a numbered list, and a question: which one. For a person at a terminal - a
        run that nobody watches names its gateway (-gw=<alias>) or takes the default.

            cx ai.gateway pick
            cx ai.gateway pick --harness=codex           # those Codex can use
        """
        harness = str(harness or '').strip().lower()
        r = self.list_({'control': {'con': False}}, arg1)
        if r['return'] > 0:
            return r
        need = HARNESS_WIRES.get(harness)
        rows = []
        for x in r['gateways']:
            wires = [w for w in x['wires'].split(',') if w]
            login = x['auth'].split(' ')[0] == LOGIN
            if need and (not [w for w in need if w in wires] or (login and harness not in LOGIN_HARNESSES)):
                continue
            rows.append(dict(x, pays='the harness\'s own login' if login else ('no key' if x['auth'] == 'none' else 'a key: ' + x['auth'])))
        if not rows:
            return self.cm.error('no gateway of this machine%s (cx ai.gateway ls)' % ((' that %s can use' % harness) if harness else ''))

        default = self._machine_default()
        default = default['harness'].get(harness) or default['name']
        default = default if default in [x['alias'] for x in rows] else ''

        w = max(len(x['alias']) for x in rows)
        print('')
        print('The gateways of this machine%s:' % ((' for ' + harness) if harness else ''))
        for i, x in enumerate(rows, 1):
            print('  %2d  %-*s  %-46s  %s%s' % (i, w, x['alias'], x['base_url'][:46], x['pays'],
                                              '   <- the default here' if x['alias'] == default else ''))
        # an empty line between the list and its question (the user, 2026-11-19), as the other selections of cMeta
        print('')
        try:
            answer = input('Which one? [1-%d or its name%s]: ' % (len(rows), (', Enter = ' + default) if default else '')).strip()
        except EOFError:
            # the input closed at once: nobody to ask after all (on Windows a NUL input looks like a terminal) - the
            # default, as for a run with -q
            print('')
            if default:
                print('nobody to answer: the default, %s' % default)
                return {'return': 0, 'gateway': default, 'gateways': [x['alias'] for x in rows], 'default': default, 'unasked': True}
            return self.cm.error('no gateway chosen (nobody to ask, and no default: name one, -gw=<alias>)')
        except KeyboardInterrupt:
            return self.cm.error('no gateway chosen')
        if not answer:
            answer = default
        chosen = ''
        if answer.isdigit() and 1 <= int(answer) <= len(rows):
            chosen = rows[int(answer) - 1]['alias']
        elif answer in [x['alias'] for x in rows]:
            chosen = answer
        if not chosen:
            return self.cm.error('no gateway chosen%s' % ((' ("%s" is none of the list)' % answer) if answer else ''))
        return {'return': 0, 'gateway': chosen, 'gateways': [x['alias'] for x in rows], 'default': default}

    ############################################################ models
    def models_(self, ctx, arg1: str = None, harness: str = ''):
        """
        The models a harness can use through a gateway - the catalog of each wire the harness speaks (claude: the
        anthropic wire; codex: the openai wire; opencode: both), as the gateway lists it now; the declared defaults
        beside. Prints the names; -j for the data.

            cx ai.gateway models acme --harness=claude
            cx ai.gateway models llama-cpp-local
        """
        g = self._one(ctx, arg1)
        if g['return'] > 0:
            return g
        desc, wires = g['desc'], self._wires(g['desc'])
        key, header, err = self._key(ctx, desc)
        if err:
            return self.cm.error(err)
        harness = str(harness or '').strip().lower()
        wanted = HARNESS_WIRES.get(harness, tuple(wires)) if harness else tuple(wires)
        out = {'return': 0, 'gateway': g['alias'], 'harness': harness, 'models': {}, 'catalogs': {}, 'errors': {}}
        for wire in wanted:
            if wire not in wires:
                out['errors'][wire] = 'the gateway does not offer this wire'
                continue
            names, url, e = self._catalog(desc, wire, header, key)
            out['catalogs'][wire] = url
            if e:
                out['errors'][wire] = e
            else:
                out['models'][wire] = names
        mine, top = self._defaults(desc, harness) if harness else ({}, '')
        out['defaults'] = dict(mine, **({'default': top} if top and not mine.get('default') else {}))
        if ctx['control'].get('con', False):
            print('%s%s' % (g['alias'], (' for ' + harness) if harness else ''))
            for wire in wanted:
                if wire in out['models']:
                    print('  %s wire (%s): %d model(s)' % (wire, out['catalogs'][wire], len(out['models'][wire])))
                    for n in out['models'][wire]:
                        print('    ' + n)
                else:
                    print('  %s wire: %s' % (wire, out['errors'].get(wire, '')))
            if out['defaults']:
                print('  declared: ' + ', '.join('%s=%s' % (k, v) for k, v in out['defaults'].items()))
        return out

    ############################################################ connect
    def connect_(self, ctx, arg1: str = None, harness: str = '', model: str = ''):
        """
        What a harness needs to use a gateway: the environment (the key included - this result is for the task that
        starts the harness, never for a record), the extra command-line words, OpenCode's providers and Claude Code's
        settings, the model to pass when the user named none, the wire. Prints the names of the variables and the
        words, never a value.

            cx ai.gateway connect acme --harness=claude
            cx ai.gateway connect llama-cpp-local --harness=codex
        """
        g = self._one(ctx, arg1)
        if g['return'] > 0:
            return g
        alias, desc, wires = g['alias'], g['desc'], self._wires(g['desc'])
        harness = str(harness or '').strip().lower()
        need = HARNESS_WIRES.get(harness)
        if not need:
            return self.cm.error('no connection recipe for the harness "%s" (claude, codex, opencode)' % harness)
        avail = [w for w in need if w in wires]
        if not avail:
            return self.cm.error('%s needs the %s wire; the gateway "%s" offers %s' % (
                harness, ' or '.join(need), alias, ', '.join(sorted(wires)) or 'none'))
        key, header, err = self._key(ctx, desc)
        if err:
            return self.cm.error(err)
        # the harness's own account through another address (auth.header: login): a recipe per harness, and nothing
        # of a key - no variable, no helper, no catalog asked on its behalf
        own_login = header == LOGIN
        if own_login and harness not in LOGIN_HARNESSES:
            return self.cm.error('the gateway "%s" passes a harness\'s own login on: %s have a recipe for that, %s has none' % (
                alias, ' and '.join(LOGIN_HARNESSES), harness))
        # the gateway's own key, when it asks one of its clients (client_key): with every request made here and given to
        # the harness below
        client, err = self._client_key(ctx, desc)
        if err:
            return self.cm.error('%s: %s' % (alias, err))
        # a gateway that does not answer is an error here, with the command that starts a local one - never a harness
        # started without a model, which could fall back to a provider it is logged into
        err = self._reachable(desc, avail[0], header, key, client)
        if err:
            return self.cm.error('%s for %s: %s' % (alias, harness, err))
        mine, top = self._defaults(desc, harness)
        chosen = str(model or mine.get('default') or top or '')
        env, args, notes, occ, ccs = {}, [], [], None, None
        wire = avail[0]
        if own_login:
            notes.append('%s on its own login (the account that pays is the harness\'s own), through %s' % (
                harness, str(desc.get('base_url') or '')))
        if harness == 'claude':
            env['ANTHROPIC_BASE_URL'] = self._url(desc, wires['anthropic'])

            # The key: a bearer token as ANTHROPIC_AUTH_TOKEN; any other (x-api-key, a local server's placeholder) in
            # KEY_VAR, printed by an apiKeyHelper. As ANTHROPIC_API_KEY beside a claude.ai login, Claude Code warned
            # "Both claude.ai and ANTHROPIC_API_KEY set" at every start (and asked once whether to use the key); a key
            # from apiKeyHelper is neither (Claude Code 2.1.310, 2026-11-01). The settings go into the run's --settings
            # (run-claude); the claude.ai connectors, unavailable on a key, are switched off there, so that no notice
            # says so at the start either. A login stays a login: the address above is all that is set.
            if own_login:
                ccs = None
            elif header == 'bearer':
                env['ANTHROPIC_AUTH_TOKEN'] = key or 'local'
                ccs = {}
            else:
                env[KEY_VAR] = key or 'local'
                ccs = {'apiKeyHelper': key_helper()}
            if ccs is not None:
                ccs['disableClaudeAiConnectors'] = True

            for a, var in (('opus', 'ANTHROPIC_DEFAULT_OPUS_MODEL'), ('sonnet', 'ANTHROPIC_DEFAULT_SONNET_MODEL'),
                           ('haiku', 'ANTHROPIC_DEFAULT_HAIKU_MODEL')):
                if mine.get(a):
                    env[var] = str(mine[a])
            if not own_login:
                env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
            if not chosen and not own_login:
                # no default declared (a local server): the loaded model's name, so that Claude Code names it
                names, _, e = self._catalog(desc, 'anthropic', header, key, client)
                chosen = names[0] if names else ''
            if not own_login:
                notes.append('Claude Code on a key: the claude.ai connectors (HubSpot, Microsoft 365, ...) are unavailable in '
                             'this session (switched off in its settings); -ln for a session that needs them')
        elif harness == 'codex':
            p = 'model_providers.' + alias
            args = ['-c', 'model_provider="%s"' % alias,
                    '-c', '%s.name="%s"' % (p, str(desc.get('description') or alias).replace('"', "'")),
                    '-c', '%s.base_url="%s"' % (p, self._url(desc, wires['openai'])),
                    '-c', '%s.wire_api="%s"' % (p, str(desc.get('codex_wire') or 'responses'))]
            if own_login:
                # Codex sends its own ChatGPT login to a provider that asks for it (the token and the account's id)
                args += ['-c', '%s.requires_openai_auth=true' % p]
            elif key:
                args += ['-c', '%s.env_key="%s"' % (p, KEY_VAR)]
                if header != 'bearer':
                    args += ['-c', '%s.env_http_headers.%s="%s"' % (p, header, KEY_VAR)]
                env[KEY_VAR] = key
            if not chosen and not own_login:
                names, _, e = self._catalog(desc, 'openai', header, key, client)
                chosen = names[0] if names else ''
                if e:
                    notes.append('no model declared and the catalog is not readable (%s): the harness decides' % e)
        elif harness == 'opencode':
            providers = {}
            ant = alias if 'anthropic' in avail else ''
            oai = (alias + '-openai' if ant else alias) if 'openai' in avail else ''
            lists = {}
            for w in avail:
                names, _, e = self._catalog(desc, w, header, key, client)
                lists[w] = names
            if ant:
                providers[ant] = {'npm': '@ai-sdk/anthropic', 'name': '%s (anthropic wire)' % alias,
                                  'options': {'baseURL': self._url(desc, wires['anthropic']).rstrip('/') + '/v1', 'apiKey': key or 'local'},
                                  'models': {n: {'name': n} for n in lists.get('anthropic') or ([chosen] if chosen else [])}}
            if oai:
                options = {'baseURL': self._url(desc, wires['openai'])}
                if key and header == 'bearer':
                    options['apiKey'] = key
                else:
                    options['apiKey'] = 'local'
                    if key:
                        options['headers'] = {header: key}
                providers[oai] = {'npm': str(desc.get('opencode_openai_npm') or '@ai-sdk/openai'), 'name': '%s (openai wire)' % alias,
                                  'options': options,
                                  'models': {n: {'name': n} for n in lists.get('openai') or ([chosen] if chosen else [])}}
            occ = {'provider': providers}
            if chosen and '/' not in chosen:
                if ant and (chosen.lower().startswith('claude') or not oai):
                    chosen = ant + '/' + chosen
                elif oai:
                    chosen = oai + '/' + chosen
            elif not chosen:
                for w, prov in (('anthropic', ant), ('openai', oai)):
                    if prov and lists.get(w):
                        chosen = prov + '/' + lists[w][0]
                        break
            wire = ','.join(avail)
        # the run this session belongs to, for a gateway that asks for it (run_header): Claude Code sends custom
        # headers from ANTHROPIC_CUSTOM_HEADERS, Codex a provider's env_http_headers, OpenCode a provider's headers
        run_header = str(desc.get('run_header') or '').strip().lower()
        run = os.environ.get(RUN_VAR, '').strip()
        if run_header and run and re.fullmatch(r'[a-z0-9-]{1,64}', run_header):
            if harness == 'claude':
                env['ANTHROPIC_CUSTOM_HEADERS'] = '%s: %s' % (run_header, run)
            elif harness == 'codex':
                args += ['-c', 'model_providers.%s.env_http_headers.%s="%s"' % (alias, run_header, RUN_VAR)]
                env[RUN_VAR] = run
            elif harness == 'opencode':
                for prov in occ['provider'].values():
                    prov['options'].setdefault('headers', {})[run_header] = run
        # the client key: Claude Code sends it among its custom headers (one per line), Codex from a variable its
        # provider names, OpenCode from its providers' headers - never on a command line
        for name, value in client.items():
            if harness == 'claude':
                lines = [x for x in str(env.get('ANTHROPIC_CUSTOM_HEADERS') or '').split(chr(10)) if x.strip()]
                env['ANTHROPIC_CUSTOM_HEADERS'] = chr(10).join(['%s: %s' % (name, value)] + lines)
            elif harness == 'codex':
                args += ['-c', 'model_providers.%s.env_http_headers.%s="%s"' % (alias, name, CLIENT_KEY_VAR)]
                env[CLIENT_KEY_VAR] = value
            elif harness == 'opencode':
                for prov in occ['provider'].values():
                    prov['options'].setdefault('headers', {})[name] = value
        # what a plain HTTP client sends with each request (a task asking a model itself): the key in its header, the
        # client key, the run - the values are for the caller only, like env
        plain = {k: v for k, v in self._headers(header, key if header not in ('none', LOGIN) else '', client).items() if k != 'Content-Type'}
        if run_header and run and re.fullmatch(r'[a-z0-9-]{1,64}', run_header):
            plain[run_header] = run
        out = {'return': 0, 'gateway': alias, 'harness': harness, 'wire': wire, 'model': chosen, 'env': env, 'args': args,
               'notes': notes, 'base_url': str(desc.get('base_url') or ''), 'provided_by': desc.get('provided_by') or {},
               'request_headers': plain,
               # what a plain HTTP client needs beside the headers (2026-11-21): the wires with what a pass-through
               # inherits from its upstream, and how a request turns an open model's reasoning off when that is declared
               'wires': dict(wires)}
        if isinstance(desc.get('thinking_off'), dict):
            out['thinking_off'] = desc['thinking_off']
        if client:
            out['client_key_header'] = next(iter(client))
        if occ:
            out['opencode_config'] = occ
        if ccs is not None:
            out['claude_settings'] = ccs
        if own_login:
            # for the task that starts the harness: this run is a login run in everything but its address
            out['own_login'] = True
        if ctx['control'].get('con', False):
            print('%s for %s: the %s wire of %s' % (alias, harness, wire, out['base_url']))
            print('  environment: ' + (', '.join(sorted(env)) or 'nothing'))
            print('  words: ' + (' '.join(args) or 'none'))
            if occ:
                print('  opencode providers: ' + ', '.join(sorted(occ['provider'])))
            if ccs:
                print('  claude settings: ' + ', '.join(sorted(ccs)))
            print('  model: ' + (chosen or 'the harness decides'))
            for n in notes:
                print('  note: ' + n)
        return out

    ############################################################ test
    def test_(self, ctx, arg1: str = None, model: str = ''):
        """
        Hello on every wire a gateway offers, with the usage each answer reports, and the catalog's size: what works
        before a harness is pointed at it. One short answer per wire; the key is never printed.

            cx ai.gateway test acme
            cx ai.gateway test llama-cpp-local --model=<the loaded model>
        """
        g = self._one(ctx, arg1)
        if g['return'] > 0:
            return g
        alias, desc, wires = g['alias'], g['desc'], self._wires(g['desc'])
        key, header, err = self._key(ctx, desc)
        if err:
            return self.cm.error(err)
        client, err = self._client_key(ctx, desc)
        if err:
            return self.cm.error('%s: %s' % (arg1, err))
        if header == LOGIN:
            return self.cm.error('the gateway "%s" passes a harness\'s own login on, and this command has none to send: '
                                 'test it with a harness (cx task run run-claude --gateway=%s -- -p hello)' % (alias, alias))
        con = ctx['control'].get('con', False)
        out = {'return': 0, 'gateway': alias, 'wires': {}}
        prompt = 'Say hello in five words.'
        for wire in sorted(wires):
            names, url, e = self._catalog(desc, wire, header, key, client)
            mine, top = self._defaults(desc, 'claude' if wire == 'anthropic' else 'codex')
            m = model or (mine.get('haiku') if wire == 'anthropic' else '') or mine.get('default') or top or (names[0] if names else '')
            res = {'catalog': len(names) if not e else e, 'model': m}
            started = time.monotonic()
            if wire == 'anthropic':
                status, data = self._http(self._url(desc, wires[wire]).rstrip('/') + '/v1/messages',
                                          self._headers(header, key, dict(client, **{'anthropic-version': ANTHROPIC_VERSION})),
                                          {'model': m, 'max_tokens': 40, 'messages': [{'role': 'user', 'content': prompt}]})
                if status == 200 and isinstance(data, dict):
                    res['text'] = ' '.join(b.get('text', '') for b in data.get('content', []) if isinstance(b, dict)).strip()[:120]
                    res['usage'] = data.get('usage')
            else:
                status, data = self._http(self._url(desc, wires[wire]).rstrip('/') + '/chat/completions',
                                          self._headers(header, key, client),
                                          {'model': m, 'messages': [{'role': 'user', 'content': prompt}], 'max_completion_tokens': 40})
                if status == 200 and isinstance(data, dict) and data.get('choices'):
                    res['text'] = str((data['choices'][0].get('message') or {}).get('content') or '').strip()[:120]
                    res['usage'] = data.get('usage')
            res['status'] = status
            res['seconds'] = round(time.monotonic() - started, 1)
            if status != 200:
                res['error'] = str(data)[:300]
            out['wires'][wire] = res
            if con:
                print('%s: %s wire, model %s: http %s in %s s%s' % (alias, wire, m or '?', status, res['seconds'],
                                                                   ('; catalog: %s' % res['catalog'])))
                if res.get('text'):
                    print('  text: ' + res['text'])
                if res.get('usage'):
                    print('  usage: ' + json.dumps(res['usage'])[:300])
                if res.get('error'):
                    print('  error: ' + res['error'])
        if any(w.get('status') != 200 for w in out['wires'].values()):
            out['return'] = 1
            out['error'] = 'a wire of %s did not answer 200 (above)' % alias
        return out
