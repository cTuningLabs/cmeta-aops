"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

ai.gateway - a place that serves models to the AI harnesses (README.md): a company's gateway, a vendor's API, a
llama.cpp or vLLM server here or on a host. The artifact (_desc.yaml) names the base URL, the wires it speaks
(anthropic: the Messages API; openai: chat completions and the Responses API), the catalog of its models, how the key
travels (auth.header) and which secret artifact holds it (auth.secret) - never a value. "connect" gives a harness the
environment and the arguments it needs, "models" lists what a harness can use there, "test" says hello on every wire.
"""

import json
import os
import time
import urllib.error
import urllib.request

from cmeta.category import InitCategory

CATEGORY = 'ai.gateway,ae1ae632e0ec4f75'
SECRET_CATEGORY = 'secret,9d63451ea1f14010'

# the wire each harness speaks (opencode and openclaw take both, through their provider packages)
HARNESS_WIRES = {'claude': ('anthropic',), 'codex': ('openai',), 'opencode': ('anthropic', 'openai'),
                 'openclaw': ('anthropic', 'openai'), 'hermes': ('openai',)}

# the variable Codex's provider block reads the key from (the block names the variable, never the value)
KEY_VAR = 'CMETA_AI_GATEWAY_KEY'

ANTHROPIC_VERSION = '2023-06-01'


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
                'repo': parts.get('repo_alias') or parts.get('artifact_repo_alias', ''), 'desc': desc if isinstance(desc, dict) else {}}

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

    def _catalog(self, desc, wire, header, key):
        """The model names a wire offers -> (names, the url, an error or ''): the wire's own catalog (catalogs: {wire:
        path}) when declared, else the whole catalog - of which the anthropic wire takes the claude-* names."""
        cats = desc.get('catalogs') if isinstance(desc.get('catalogs'), dict) else {}
        own = cats.get(wire)
        path = own or desc.get('catalog')
        if not path:
            return [], '', 'no catalog declared (catalog: /v1/models)'
        url = self._url(desc, path)
        status, data = self._http(url, self._headers(header, key, {'anthropic-version': ANTHROPIC_VERSION} if wire == 'anthropic' else None))
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

    def _reachable(self, desc, wire, header, key):
        """The catalog of the wire answers -> ''; else what went wrong, with the start command of a local gateway.
        A gateway without a catalog is not probed."""
        cats = desc.get('catalogs') if isinstance(desc.get('catalogs'), dict) else {}
        if not (cats.get(wire) or desc.get('catalog')):
            return ''
        names, url, e = self._catalog(desc, wire, header, key)
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
    def ls_(self, ctx, arg1: str = None):
        """
        The gateways this machine knows: alias, base URL, wires, auth (the header and the secret's name), repository.

            cx ai.gateway ls
        """
        r = self.cm.access({'category': CATEGORY, 'command': 'find', 'arg1': arg1 or '*', 'con': False})
        if r['return'] > 0 and r['return'] != 16:
            return r
        rows = []
        for a in sorted(r.get('artifacts', []), key = lambda a: a['cmeta_ref_parts']['artifact_alias']):
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            desc = (rd.get('data') or {}) if rd['return'] == 0 else {}
            desc = desc if isinstance(desc, dict) else {}
            auth = desc.get('auth') or {}
            rows.append({'alias': a['cmeta_ref_parts']['artifact_alias'], 'uid': a['cmeta_ref_parts']['artifact_uid'],
                         'base_url': str(desc.get('base_url') or ''), 'wires': ','.join(sorted(self._wires(desc))),
                         'auth': str(auth.get('header') or 'none') + (' (' + str(auth['secret']) + ')' if auth.get('secret') else ''),
                         'provided_by': str((desc.get('provided_by') or {}).get('task') or ''),
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

    ############################################################ models
    def models_(self, ctx, arg1: str = None, harness: str = ''):
        """
        The models a harness can use through a gateway - the catalog of each wire the harness speaks (claude: the
        anthropic wire; codex: the openai wire; opencode: both), as the gateway lists it now; the declared defaults
        beside. Prints the names; -j for the data.

            cx ai.gateway models dapple --harness=claude
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
        starts the harness, never for a record), the extra command-line words, the model to pass when the user named
        none, the wire. Prints the names of the variables and the words, never a value.

            cx ai.gateway connect dapple --harness=claude
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
        # a gateway that does not answer is an error here, with the command that starts a local one - never a harness
        # started without a model, which could fall back to a provider it is logged into
        err = self._reachable(desc, avail[0], header, key)
        if err:
            return self.cm.error('%s for %s: %s' % (alias, harness, err))
        mine, top = self._defaults(desc, harness)
        chosen = str(model or mine.get('default') or top or '')
        env, args, notes, occ = {}, [], [], None
        wire = avail[0]
        if harness == 'claude':
            env['ANTHROPIC_BASE_URL'] = self._url(desc, wires['anthropic'])
            env['ANTHROPIC_AUTH_TOKEN' if header == 'bearer' else 'ANTHROPIC_API_KEY'] = key or 'local'
            for a, var in (('opus', 'ANTHROPIC_DEFAULT_OPUS_MODEL'), ('sonnet', 'ANTHROPIC_DEFAULT_SONNET_MODEL'),
                           ('haiku', 'ANTHROPIC_DEFAULT_HAIKU_MODEL')):
                if mine.get(a):
                    env[var] = str(mine[a])
            env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
            if not chosen:
                # no default declared (a local server): the loaded model's name, so that Claude Code names it
                names, _, e = self._catalog(desc, 'anthropic', header, key)
                chosen = names[0] if names else ''
            notes.append('Claude Code on an API key: the claude.ai connectors (HubSpot, Microsoft 365, ...) are unavailable '
                         'in this session; beside a subscription login it asks once whether to use the key')
        elif harness == 'codex':
            p = 'model_providers.' + alias
            args = ['-c', 'model_provider="%s"' % alias,
                    '-c', '%s.name="%s"' % (p, str(desc.get('description') or alias).replace('"', "'")),
                    '-c', '%s.base_url="%s"' % (p, self._url(desc, wires['openai'])),
                    '-c', '%s.wire_api="%s"' % (p, str(desc.get('codex_wire') or 'responses'))]
            if key:
                args += ['-c', '%s.env_key="%s"' % (p, KEY_VAR)]
                if header != 'bearer':
                    args += ['-c', '%s.env_http_headers.%s="%s"' % (p, header, KEY_VAR)]
                env[KEY_VAR] = key
            if not chosen:
                names, _, e = self._catalog(desc, 'openai', header, key)
                chosen = names[0] if names else ''
                if e:
                    notes.append('no model declared and the catalog is not readable (%s): the harness decides' % e)
        elif harness == 'opencode':
            providers = {}
            ant = alias if 'anthropic' in avail else ''
            oai = (alias + '-openai' if ant else alias) if 'openai' in avail else ''
            lists = {}
            for w in avail:
                names, _, e = self._catalog(desc, w, header, key)
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
        out = {'return': 0, 'gateway': alias, 'harness': harness, 'wire': wire, 'model': chosen, 'env': env, 'args': args,
               'notes': notes, 'base_url': str(desc.get('base_url') or ''), 'provided_by': desc.get('provided_by') or {}}
        if occ:
            out['opencode_config'] = occ
        if ctx['control'].get('con', False):
            print('%s for %s: the %s wire of %s' % (alias, harness, wire, out['base_url']))
            print('  environment: ' + (', '.join(sorted(env)) or 'nothing'))
            print('  words: ' + (' '.join(args) or 'none'))
            if occ:
                print('  opencode providers: ' + ', '.join(sorted(occ['provider'])))
            print('  model: ' + (chosen or 'the harness decides'))
            for n in notes:
                print('  note: ' + n)
        return out

    ############################################################ test
    def test_(self, ctx, arg1: str = None, model: str = ''):
        """
        Hello on every wire a gateway offers, with the usage each answer reports, and the catalog's size: what works
        before a harness is pointed at it. One short answer per wire; the key is never printed.

            cx ai.gateway test dapple
            cx ai.gateway test llama-cpp-local --model=<the loaded model>
        """
        g = self._one(ctx, arg1)
        if g['return'] > 0:
            return g
        alias, desc, wires = g['alias'], g['desc'], self._wires(g['desc'])
        key, header, err = self._key(ctx, desc)
        if err:
            return self.cm.error(err)
        con = ctx['control'].get('con', False)
        out = {'return': 0, 'gateway': alias, 'wires': {}}
        prompt = 'Say hello in five words.'
        for wire in sorted(wires):
            names, url, e = self._catalog(desc, wire, header, key)
            mine, top = self._defaults(desc, 'claude' if wire == 'anthropic' else 'codex')
            m = model or (mine.get('haiku') if wire == 'anthropic' else '') or mine.get('default') or top or (names[0] if names else '')
            res = {'catalog': len(names) if not e else e, 'model': m}
            started = time.monotonic()
            if wire == 'anthropic':
                status, data = self._http(self._url(desc, wires[wire]).rstrip('/') + '/v1/messages',
                                          self._headers(header, key, {'anthropic-version': ANTHROPIC_VERSION}),
                                          {'model': m, 'max_tokens': 40, 'messages': [{'role': 'user', 'content': prompt}]})
                if status == 200 and isinstance(data, dict):
                    res['text'] = ' '.join(b.get('text', '') for b in data.get('content', []) if isinstance(b, dict)).strip()[:120]
                    res['usage'] = data.get('usage')
            else:
                status, data = self._http(self._url(desc, wires[wire]).rstrip('/') + '/chat/completions',
                                          self._headers(header, key),
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
