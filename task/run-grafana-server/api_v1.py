"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-grafana-server - a Grafana server on this machine (README.md): start (detached, or in the foreground for a host
that keeps it), status, stop. Its data source is the Prometheus of run-prometheus-server; its boards - the AI gateway
server's, llama.cpp's and vLLM's - are written from the panels below at every start (folder cMeta). Its settings,
data, record, log and the password of its admin: the state artifact local:grafana-server-<port>.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import time
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask, recorded_process_alive

TASK_CATEGORY = 'task,c36be4b9314a45e0'
STATE_CATEGORY = 'state'
TOOL = 'grafana,eb0e686ca9224b82'
SETUP_TASK = 'setup,a2f9b61079ce4333'

DEFAULT_PORT = 3000

CONFIG = 'task-run-grafana-server'
BUILT_IN = {'prometheus': 'http://127.0.0.1:9090', 'datasources': '', 'anonymous': 'auto', 'plugins': 'prometheus',
            'sub_path': '/grafana/ui', 'vllm_boards': 'yes'}
DEFAULT_SOURCE = 'cmeta-prometheus'


def parse_sources(prometheus, extra):
    """The data sources: "Prometheus" (uid cmeta-prometheus, the default) at the given address, then the named ones of
    "<name>=<URL>,..." (a list, or text separated by commas), each uid cmeta-ds-<its name>. Raises ValueError."""
    out = [{'name': 'Prometheus', 'uid': DEFAULT_SOURCE, 'url': str(prometheus).rstrip('/')}]
    items = extra if isinstance(extra, (list, tuple)) else str(extra or '').split(',')
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        name, sep, url = item.partition('=')
        name, url = name.strip(), url.strip().rstrip('/')
        if not sep or not name or not re.match(r'^https?://[^/\s]+', url):
            raise ValueError('a data source is <name>=<http(s) URL of a Prometheus>: "%s"' % item)
        uid = 'cmeta-ds-' + (re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'source')
        if uid in {x['uid'] for x in out} or name in {x['name'] for x in out}:
            raise ValueError('two data sources are named "%s"' % name)
        out.append({'name': name, 'uid': uid, 'url': url})
    return out


def clean_sub_path(value):
    """'/grafana/ui' from 'grafana/ui/', '' for none; letters, digits, - _ . / only."""
    v = '/' + str(value or '').strip().strip('/')
    if v == '/':
        return ''
    if not re.match(r'^(/[A-Za-z0-9._-]+)+$', v):
        raise ValueError('a sub-path is like /grafana/ui (got "%s")' % value)
    return v

# The data sources built into Grafana that run as programs of their own (gpx_*): not loaded unless plugins is "all" -
# the boards read Prometheus only, and each would be a process (14 of them, 2026-11-19)
OTHER_SOURCES = ['cloudwatch', 'elasticsearch', 'grafana-azure-monitor-datasource', 'grafana-postgresql-datasource',
                 'grafana-pyroscope-datasource', 'grafana-testdata-datasource', 'graphite', 'influxdb', 'jaeger', 'loki',
                 'mssql', 'mysql', 'opentsdb', 'parca', 'stackdriver', 'tempo', 'zipkin']


def listening(host, port, timeout=1.0):
    """Something accepts connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def alive(pid):
    if os.name == 'nt':
        r = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH'], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def http_json(url, timeout=5):
    """GET -> (status, the parsed JSON or the text)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            text = r.read().decode('utf-8', 'replace')
            try:
                return r.status, json.loads(text)
            except ValueError:
                return r.status, text[:200]
    except Exception as e:
        return 0, str(e)


def ini_text(folder, host, port, password, anonymous, home_board, disabled=(), sub_path=''):
    """grafana.ini: its folders in the state artifact, 127.0.0.1 by default, no sign-up, no calls home, embedding
    allowed (a cMeta page may show a board), a viewer without sign-in only when asked or on 127.0.0.1 alone."""
    p = lambda *x: os.path.join(folder, *x).replace('\\', '/')
    return '\n'.join([
        '# written by run-grafana-server at every start: change the config task-run-grafana-server, not this file', '',
        '[paths]', 'data = ' + p('data'), 'logs = ' + p('logs'), 'plugins = ' + p('plugins'), 'provisioning = ' + p('provisioning'), '',
        '[server]', 'http_addr = ' + host, 'http_port = %d' % port] + (
        # served under a sub-path: a cMeta server's page (cserver.grafana) passes it through at that path
        ['root_url = %%(protocol)s://%%(domain)s:%%(http_port)s%s/' % sub_path, 'serve_from_sub_path = true'] if sub_path else []) + [
        '',
        # no websocket (Grafana Live): a page passing Grafana through answers plain requests only
        '[live]', 'max_connections = 0', '',
        '[security]', 'admin_user = admin', 'admin_password = ' + password, 'allow_embedding = true', 'cookie_samesite = lax',
        'disable_gravatar = true', '',
        '[auth.anonymous]', 'enabled = ' + ('true' if anonymous else 'false'), 'org_role = Viewer', '',
        '[users]', 'allow_sign_up = false', '',
        '[analytics]', 'reporting_enabled = false', 'check_for_updates = false', 'check_for_plugin_updates = false',
        'feedback_links_enabled = false', '',
        '[news]', 'news_feed_enabled = false', '',
        # no plugin fetched from grafana.com at a start; the data sources it does not need not loaded
        '[plugins]', 'preinstall_disabled = true', 'disable_plugins = ' + ','.join(disabled), '',
        '[dashboards]', 'default_home_dashboard_path = ' + home_board, ''])


# ------------------------------------------------------------------------------------------------ the boards
# The AI gateway server's (cmeta_ai_gateway_*), llama.cpp's (llamacpp:*) and vLLM's (vllm:*), each written from a
# short list of panels; a panel's series are PromQL over the names the servers publish at /metrics.

# every board draws from the source its "Prometheus" selector names (DEFAULT_SOURCE first)
DS = {'type': 'prometheus', 'uid': '${datasource}'}
SOURCE_VARIABLE = {'name': 'datasource', 'label': 'Prometheus', 'type': 'datasource', 'query': 'prometheus',
                   'current': {'text': 'Prometheus', 'value': DEFAULT_SOURCE}, 'hide': 0, 'refresh': 1, 'regex': '',
                   'includeAll': False, 'multi': False}


def _panel(pid, title, exprs, unit, x, y, w=12, h=8, kind='timeseries', desc=''):
    p = {'id': pid, 'type': kind, 'title': title, 'description': desc, 'datasource': DS,
         'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
         'fieldConfig': {'defaults': {'unit': unit}, 'overrides': []},
         'targets': [{'refId': chr(65 + i), 'expr': e, 'legendFormat': l, 'datasource': DS} for i, (e, l) in enumerate(exprs)]}
    if kind == 'timeseries':
        p['fieldConfig']['defaults']['custom'] = {'lineWidth': 2, 'fillOpacity': 8, 'showPoints': 'never', 'spanNulls': False}       # a gap is a time without requests: never bridged
        p['options'] = {'legend': {'displayMode': 'list', 'placement': 'bottom'}, 'tooltip': {'mode': 'multi'}}
    else:
        # a count in a range is a whole number: Prometheus extrapolates increase() to the range's edges
        p['fieldConfig']['defaults']['decimals'] = 0 if unit == 'short' else 1
        p['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                        'colorMode': 'none', 'graphMode': 'none', 'textMode': 'value'}
    return p


def _board(uid, title, variable, metric, panels, desc):
    """A board with one variable (the routes or the servers), its panels in rows of the given widths."""
    return {'uid': uid, 'title': title, 'description': desc, 'tags': ['cmeta'], 'timezone': 'browser',
            'schemaVersion': 39, 'version': 1, 'editable': True, 'refresh': '30s',
            'time': {'from': 'now-24h', 'to': 'now'},
            'templating': {'list': [dict(SOURCE_VARIABLE), {'name': variable[0], 'label': variable[1], 'type': 'query', 'datasource': DS,
                                     'query': {'query': 'label_values(%s, %s)' % (metric, variable[2]), 'refId': 'v'},
                                     'definition': 'label_values(%s, %s)' % (metric, variable[2]),
                                     'includeAll': True, 'multi': True, 'allValue': '.*', 'refresh': 2,
                                     'current': {'text': 'All', 'value': '$__all'}}]},
            'panels': panels}


def _layout(rows):
    """[[(title, exprs, unit, kind, desc), ...], ...] -> panels: a row of stats (h 4) or of charts (h 8)."""
    out, y, pid = [], 0, 1
    for row in rows:
        w = 24 // len(row)
        h = 4 if row[0][3] == 'stat' else 8
        for i, (title, exprs, unit, kind, desc) in enumerate(row):
            out.append(_panel(pid, title, exprs, unit, i * w, y, w, h, kind, desc))
            pid += 1
        y += h
    return out


def gateway_board():
    f = '{gateway=~"$route"}'
    g = 'cmeta_ai_gateway_'
    q50 = 'histogram_quantile(0.5, sum by (le) (rate(%s%%s_bucket%s[$__rate_interval])))' % (g, f)
    q95 = 'histogram_quantile(0.95, sum by (le) (rate(%s%%s_bucket%s[$__rate_interval])))' % (g, f)
    rows = [
        [('Requests', [('sum(increase(%srequests_total%s[$__range]))' % (g, f), '')], 'short', 'stat', 'Requests passed on in the time range'),
         ('Input tokens', [('sum(increase(%sinput_tokens_total%s[$__range]))' % (g, f), '')], 'short', 'stat', 'The cached parts included'),
         ('Output tokens', [('sum(increase(%soutput_tokens_total%s[$__range]))' % (g, f), '')], 'short', 'stat', 'Reasoning included'),
         ('Read from the cache', [('sum(increase(%sinput_cached_tokens_total%s[$__range])) / sum(increase(%sinput_tokens_total%s[$__range]))' % (g, f, g, f), '')],
          'percentunit', 'stat', 'The share of the input tokens the provider read from its prompt cache')],
        [('Requests per minute, by route', [('sum by (gateway) (rate(%srequests_total%s[$__rate_interval])) * 60' % (g, f), '{{gateway}}')], 'short', 'timeseries', ''),
         ('Tokens per minute', [('sum(rate(%sinput_tokens_total%s[$__rate_interval])) * 60' % (g, f), 'input'),
                                ('sum(rate(%sinput_cached_tokens_total%s[$__rate_interval])) * 60' % (g, f), 'input read from the cache'),
                                ('sum(rate(%soutput_tokens_total%s[$__rate_interval])) * 60' % (g, f), 'output')], 'short', 'timeseries', '')],
        [('Time to first token', [(q50 % 'time_to_first_token_seconds', 'median'), (q95 % 'time_to_first_token_seconds', '95 in 100 under')], 's', 'timeseries', ''),
         ('Whole latency', [(q50 % 'e2e_request_latency_seconds', 'median'), (q95 % 'e2e_request_latency_seconds', '95 in 100 under')], 's', 'timeseries', '')],
        [('Output speed (median)', [('1 / (%s)' % (q50 % 'time_per_output_token_seconds'), 'tokens per second')], 'short', 'timeseries',
          'One over the median time per output token'),
         ('Output tokens per minute, by model', [('sum by (model) (rate(%soutput_tokens_total%s[$__rate_interval])) * 60' % (g, f), '{{model}}')], 'short', 'timeseries', '')],
        [('Not answered per minute, by status', [('sum by (status_code) (rate(%srequests_total{gateway=~"$route",status_code!~"2..|3.."}[$__rate_interval])) * 60' % g, '{{status_code}}')],
          'short', 'timeseries', 'Requests the upstream refused or failed'),
         ('Requests running now', [('sum(%snum_requests_running)' % g, 'running')], 'short', 'timeseries', '')],
    ]
    return _board('cmeta-ai-gateway', 'AI gateway', ('route', 'Route', 'gateway'), g + 'requests_total', _layout(rows),
                  'The cMeta AI gateway server: requests, tokens, the provider cache, times (its /metrics)')


def llama_cpp_board():
    f = '{job=~"$server"}'
    rows = [
        [('Generated tokens', [('sum(increase(llamacpp:tokens_predicted_total%s[$__range]))' % f, '')], 'short', 'stat', ''),
         ('Prompt tokens', [('sum(increase(llamacpp:prompt_tokens_total%s[$__range]))' % f, '')], 'short', 'stat', ''),
         ('Prompt from its cache', [('sum(increase(llamacpp:prompt_tokens_cached_total%s[$__range])) / (sum(increase(llamacpp:prompt_tokens_total%s[$__range])) + sum(increase(llamacpp:prompt_tokens_cached_total%s[$__range])))' % (f, f, f), '')],
          'percentunit', 'stat', 'The share of the prompt llama.cpp took from its cache instead of computing it'),
         ('Largest context', [('max(llamacpp:n_tokens_max%s)' % f, '')], 'short', 'stat', 'The most tokens a request held so far')],
        [('Generated tokens per second', [('sum by (job) (rate(llamacpp:tokens_predicted_total%s[$__rate_interval]))' % f, '{{job}}')], 'short', 'timeseries', ''),
         ('Prompt tokens per second', [('sum by (job) (rate(llamacpp:prompt_tokens_total%s[$__rate_interval]))' % f, '{{job}} computed'),
                                       ('sum by (job) (rate(llamacpp:prompt_tokens_cached_total%s[$__rate_interval]))' % f, '{{job}} from its cache')], 'short', 'timeseries', '')],
        [('Generation speed (its own average)', [('llamacpp:predicted_tokens_seconds%s' % f, '{{job}}')], 'short', 'timeseries', 'Tokens per second while generating'),
         ('Prompt speed (its own average)', [('llamacpp:prompt_tokens_seconds%s' % f, '{{job}}')], 'short', 'timeseries', 'Prompt tokens per second while reading a prompt')],
        [('Requests', [('sum by (job) (llamacpp:requests_processing%s)' % f, '{{job}} processing'), ('sum by (job) (llamacpp:requests_deferred%s)' % f, '{{job}} waiting')],
          'short', 'timeseries', ''),
         ('Busy slots per decode', [('llamacpp:n_busy_slots_per_decode%s' % f, '{{job}}')], 'short', 'timeseries', '')],
    ]
    return _board('cmeta-llama-cpp', 'llama.cpp', ('server', 'Server', 'job'), 'llamacpp:prompt_tokens_total', _layout(rows),
                  'llama.cpp servers (run-llama-cpp-server, --metrics): tokens, speeds, its cache, requests')


def vllm_board():
    f = '{job=~"$server"}'
    q = 'histogram_quantile(%s, sum by (le, job) (rate(vllm:%s_bucket' + f + '[$__rate_interval])))'
    rows = [
        [('Generated tokens', [('sum(increase(vllm:generation_tokens_total%s[$__range]))' % f, '')], 'short', 'stat', ''),
         ('Prompt tokens', [('sum(increase(vllm:prompt_tokens_total%s[$__range]))' % f, '')], 'short', 'stat', ''),
         ('Prefix cache hits', [('sum(increase(vllm:prefix_cache_hits_total%s[$__range])) / sum(increase(vllm:prefix_cache_queries_total%s[$__range]))' % (f, f), '')],
          'percentunit', 'stat', 'The share of the prompt tokens vLLM found in its prefix cache'),
         ('KV cache in use', [('max(vllm:kv_cache_usage_perc%s or vllm:gpu_cache_usage_perc%s)' % (f, f), '')], 'percentunit', 'stat', '')],
        [('Tokens per second', [('sum by (job) (rate(vllm:generation_tokens_total%s[$__rate_interval]))' % f, '{{job}} generated'),
                                ('sum by (job) (rate(vllm:prompt_tokens_total%s[$__rate_interval]))' % f, '{{job}} prompt')], 'short', 'timeseries', ''),
         ('Requests', [('sum by (job) (vllm:num_requests_running%s)' % f, '{{job}} running'), ('sum by (job) (vllm:num_requests_waiting%s)' % f, '{{job}} waiting')],
          'short', 'timeseries', '')],
        [('Time to first token', [(q % ('0.5', 'time_to_first_token_seconds'), '{{job}} median'), (q % ('0.95', 'time_to_first_token_seconds'), '{{job}} 95 in 100 under')],
          's', 'timeseries', ''),
         ('Time between tokens', [(q % ('0.5', 'inter_token_latency_seconds'), '{{job}} median'), (q % ('0.95', 'inter_token_latency_seconds'), '{{job}} 95 in 100 under')],
          's', 'timeseries', '')],
        [('KV cache in use', [('vllm:kv_cache_usage_perc%s or vllm:gpu_cache_usage_perc%s' % (f, f), '{{job}}')], 'percentunit', 'timeseries', ''),
         ('Whole latency', [(q % ('0.5', 'e2e_request_latency_seconds'), '{{job}} median'), (q % ('0.95', 'e2e_request_latency_seconds'), '{{job}} 95 in 100 under')],
          's', 'timeseries', '')],
    ]
    return _board('cmeta-vllm', 'vLLM', ('server', 'Server', 'job'), 'vllm:prompt_tokens_total', _layout(rows),
                  'vLLM servers (run-vllm-server): tokens, requests, its caches, times')


BOARDS = {'cmeta-ai-gateway.json': gateway_board, 'cmeta-llama-cpp.json': llama_cpp_board, 'cmeta-vllm.json': vllm_board}


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def _state(self, ctx, port):
        """The state artifact of the server on this port (local:grafana-server-<port>): its folder."""
        r = self.cm.access({'category': STATE_CATEGORY, 'command': 'get', 'arg1': 'local:grafana-server-%d' % port,
                            'ctx': ctx, 'con': False})
        if r.get('return', 1) > 0:
            return r
        return {'return': 0, 'path': r['artifact']['path']}

    def _defaults(self):
        """The defaults of a start: config::task-run-grafana-server over BUILT_IN (a key empty or absent: built in)."""
        out = dict(BUILT_IN)
        try:
            r = self.cm.access({'category': 'config', 'command': 'read', 'arg1': CONFIG, 'con': False})
            cfg = r.get('config_cmeta') if r.get('return', 1) == 0 else None
        except Exception:
            cfg = None
        for k in BUILT_IN:
            if isinstance(cfg, dict) and cfg.get(k) not in (None, ''):
                out[k] = cfg[k]
        return out

    @staticmethod
    def _write_record(folder, rec):
        with open(os.path.join(folder, 'server.json'), 'w', encoding='utf-8') as f:
            json.dump(rec, f, indent=1)

    @staticmethod
    def _read_record(folder):
        fp = os.path.join(folder, 'server.json')
        if not os.path.isfile(fp):
            return {}
        try:
            with open(fp, encoding='utf-8') as f:
                rec = json.load(f)
            rec['_written'] = os.path.getmtime(fp)      # when the record was written: its process must be of that run
            return rec
        except Exception:
            return {}

    def _status(self, host, port, rec, sub_path=''):
        """Running (its /api/health says the database is ok), whether it is the recorded process."""
        pid = int(rec.get('pid') or 0)
        up = listening(host, port)
        sub = rec.get('sub_path', sub_path) if rec else sub_path
        status, health = http_json('http://%s:%d%s/api/health' % (host, port, sub)) if up else (0, '')
        ok = status == 200 and isinstance(health, dict) and health.get('database') == 'ok'
        pid_alive = recorded_process_alive(pid, rec.get('_written', 0), alive) if pid else False
        return {'running': ok, 'listening': up, 'version': health.get('version', '') if ok else '', 'pid': pid,
                'pid_alive': pid_alive, 'ours': bool(pid) and up and pid_alive}

    @staticmethod
    def _password(folder):
        """The admin's password: made once (random), kept in the state artifact (admin-password.txt, the owner's
        alone where the OS says so); Grafana takes it at its first start and keeps it in its database."""
        fp = os.path.join(folder, 'admin-password.txt')
        if os.path.isfile(fp):
            with open(fp, encoding='utf-8') as f:
                value = f.read().strip()
            if value:
                return value, fp
        value = secrets.token_urlsafe(18)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(value + '\n')
        try:
            os.chmod(fp, 0o600)
        except OSError:
            pass
        return value, fp

    def _upstream_boards(self, folder, which):
        """The boards of a server's makers declared in _desc.yaml (upstream_boards: <which>: version, folder, files with
        url and sha256), each downloaded once into the state artifact (upstream-boards/<sha256>.json) and checked:
        {'folder', 'files': [paths], 'notes': [what could not be had]}."""
        try:
            import yaml
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_desc.yaml'), encoding='utf-8') as f:
                decl = ((yaml.safe_load(f) or {}).get('upstream_boards') or {}).get(which) or {}
        except Exception as e:
            return {'folder': '', 'files': [], 'notes': ['the declaration of the %s boards cannot be read: %s' % (which, e)]}
        cache = os.path.join(folder, 'upstream-boards')
        os.makedirs(cache, exist_ok=True)
        out, notes = [], []
        for item in decl.get('files') or []:
            url, want = str(item.get('url') or ''), str(item.get('sha256') or '').lower()
            fp = os.path.join(cache, want + '.json')
            if not os.path.isfile(fp):
                try:
                    with urllib.request.urlopen(url, timeout=30) as r:
                        raw = r.read()
                except Exception as e:
                    notes.append('%s: not downloaded (%s)' % (url, e))
                    continue
                got = hashlib.sha256(raw).hexdigest()
                if got != want:
                    notes.append('%s: SHA-256 %s, declared %s - not used' % (url, got, want))
                    continue
                with open(fp, 'wb') as f:
                    f.write(raw)
            out.append(fp)
        return {'folder': str(decl.get('folder') or which), 'files': out, 'notes': notes}

    def _provision(self, folder, sources, vllm=False):
        """The data sources (the first the default) and the boards - ours in the folder cMeta, vLLM's in its own -
        written again; {'home', 'notes'}."""
        prov = os.path.join(folder, 'provisioning')
        boards = os.path.join(prov, 'boards')
        for d in ('datasources', 'dashboards', 'plugins', 'alerting', 'notifiers'):
            os.makedirs(os.path.join(prov, d), exist_ok=True)
        os.makedirs(boards, exist_ok=True)
        # JSON is YAML: Grafana reads these files without a YAML writer here
        with open(os.path.join(prov, 'datasources', 'cmeta.yaml'), 'w', encoding='utf-8') as f:
            json.dump({'apiVersion': 1,
                       'deleteDatasources': [],
                       'prune': True,              # a source taken out of the list leaves Grafana too
                       'datasources': [{'name': x['name'], 'type': 'prometheus', 'uid': x['uid'], 'access': 'proxy',
                                        'url': x['url'], 'isDefault': i == 0, 'editable': False,
                                        'jsonData': {'timeInterval': '10s'}} for i, x in enumerate(sources)]}, f, indent=1)
        providers = [{'name': 'cmeta', 'folder': 'cMeta', 'type': 'file', 'disableDeletion': True, 'allowUiUpdates': False,
                      'updateIntervalSeconds': 60, 'options': {'path': boards.replace('\\', '/')}}]
        for name, make in BOARDS.items():
            with open(os.path.join(boards, name), 'w', encoding='utf-8') as f:
                json.dump(make(), f, indent=1)
        notes = []
        upstream = os.path.join(prov, 'boards-vllm')
        if os.path.isdir(upstream):
            for n in os.listdir(upstream):
                os.remove(os.path.join(upstream, n))
        if vllm:
            u = self._upstream_boards(folder, 'vllm')
            notes += u['notes']
            if u['files']:
                os.makedirs(upstream, exist_ok=True)
                for fp in u['files']:
                    with open(fp, 'rb') as src, open(os.path.join(upstream, os.path.basename(fp)), 'wb') as dst:
                        dst.write(src.read())
                providers.append({'name': 'vllm', 'folder': u['folder'], 'type': 'file', 'disableDeletion': True,
                                  'allowUiUpdates': False, 'updateIntervalSeconds': 60,
                                  'options': {'path': upstream.replace('\\', '/')}})
        with open(os.path.join(prov, 'dashboards', 'cmeta.yaml'), 'w', encoding='utf-8') as f:
            json.dump({'apiVersion': 1, 'providers': providers}, f, indent=1)
        return {'home': os.path.join(boards, 'cmeta-ai-gateway.json').replace('\\', '/'), 'notes': notes}

    def _choices(self, prometheus, datasources, sub_path, vllm_boards):
        """What the command line and the config of this machine say: the sources, the sub-path, vLLM's boards."""
        d = self._defaults()
        sources = parse_sources(str(prometheus or d['prometheus']), datasources or d['datasources'])
        sub = clean_sub_path(d['sub_path'] if sub_path in (None, '') else sub_path)
        vllm = str(vllm_boards or d['vllm_boards']).strip().lower() in ('yes', 'true', '1', 'on')
        return d, sources, sub, vllm

    def _reload(self, folder, host, port, rec, status, prometheus, datasources, vllm_boards, con):
        """The data sources and the boards as the config says now, written and - while Grafana runs - read again by it
        (its provisioning API, as its admin: the password from the state artifact). Nothing else changes; a new port,
        sub-path or sign-in rule needs a restart."""
        try:
            d, sources, _, vllm = self._choices(prometheus, datasources, '', vllm_boards)
        except ValueError as e:
            return self.cm.error(str(e))
        prov = self._provision(folder, sources, vllm)
        reloaded = []
        if status['running']:
            password, _ = self._password(folder)
            auth = 'Basic ' + base64.b64encode(('admin:' + password).encode('utf-8')).decode('ascii')
            base = 'http://%s:%d%s' % (host, port, rec.get('sub_path', '') if rec else '')
            for what in ('datasources', 'dashboards'):
                req = urllib.request.Request(base + '/api/admin/provisioning/%s/reload' % what, data=b'', method='POST',
                                             headers={'Authorization': auth})
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        if r.status == 200:
                            reloaded.append(what)
                except Exception as e:
                    return self.cm.error('Grafana on port %d did not read its %s again: %s' % (port, what, e))
            if rec:
                rec = {k: v for k, v in rec.items() if k != '_written'}
                rec['sources'] = sources
                self._write_record(folder, rec)
        if con:
            print('Grafana on port %d: %d data source(s) (%s)%s - %s' % (port, len(sources), ', '.join(x['name'] for x in sources),
                  ', vLLM\'s boards' if vllm else '', 'read again by the running server' if reloaded else 'written for its next start'))
            for n in prov['notes']:
                print('  note: ' + n)
        return {'return': 0, 'port': port, 'sources': sources, 'vllm_boards': vllm, 'reloaded': reloaded, 'notes': prov['notes']}

    def run(self,
            ctx: dict,
            action: str = 'start',          # start | status | stop | restart | reload
            port: int = DEFAULT_PORT,       # 3000 by default (Grafana's own)
            host: str = '127.0.0.1',        # the address to listen on (another than 127.0.0.1: others reach its sign-in page)
            prometheus: str = '',           # the Prometheus it draws from (default: the config's, else http://127.0.0.1:9090)
            datasources: str = '',          # more Prometheus servers it may draw from: <name>=<URL>,... (default: the config's)
            sub_path: str = '',             # the path it is served under (default: the config's, else /grafana/ui - for cserver.grafana)
            vllm_boards: str = '',          # vLLM's official boards too: yes | no (default: the config's, else yes)
            anonymous: str = '',            # a viewer without sign-in: auto (only on 127.0.0.1) | yes | no (default: the config's, else auto)
            timeout: int = 120,             # seconds to wait for it to be ready before "start" gives up (its first start sets up its database)
            foreground: bool = False,       # keep the server attached to this console (its log on the screen; Ctrl-C ends it)
            unparsed: list = None,          # extra words for "grafana server" (everything after "--")
    ):
        """
        A Grafana server on this machine with Prometheus as its data source and the boards of the AI gateway,
        llama.cpp and vLLM.

            cx task run run-grafana-server
            cx task run run-grafana-server --action=status
            cx task run run-grafana-server --action=stop
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        action = str(action or 'start').strip().lower()
        port = int(port)
        st = self._state(ctx, port)
        if st['return'] > 0:
            return st
        folder = st['path']
        rec = self._read_record(folder)
        try:
            sub = clean_sub_path(rec['sub_path']) if rec.get('sub_path') is not None else clean_sub_path(self._defaults()['sub_path'])
        except ValueError as e:
            return self.cm.error(str(e))
        status = self._status(host, port, rec, sub)
        url = 'http://%s:%d%s' % (host, port, sub)

        if action == 'status':
            if con:
                if status['running']:
                    print('Grafana %s on %s: up (pid %s%s); boards: %s/dashboards/f/cmeta' % (status['version'], url, rec.get('pid', '?'),
                          '' if status['pid_alive'] else ' - not the recorded process', url))
                    print('  the admin\'s password: %s' % os.path.join(folder, 'admin-password.txt'))
                elif status['listening']:
                    print('something listens on %s but does not answer /api/health as Grafana' % url)
                else:
                    print('Grafana on %s: down' % url)
            return {'return': 0, 'port': port, 'host': host, 'url': url, 'state': folder, 'record': rec, **status}

        if action in ('stop', 'restart'):
            pid = int(rec.get('pid') or 0)
            if pid and recorded_process_alive(pid, rec.get('_written', 0), alive):
                stop_process(pid)
                for _ in range(100):
                    if not alive(pid):
                        break
                    time.sleep(0.2)
                if con:
                    print('Grafana on port %d: stopped (pid %d)' % (port, pid))
            elif status['listening'] and con:
                print('port %d is taken by a process this task did not start - not stopped' % port)
            elif con:
                print('Grafana on port %d: not running' % port)
            try:
                os.remove(os.path.join(folder, 'server.json'))
            except OSError:
                pass
            if action == 'stop':
                return {'return': 0, 'port': port, 'stopped': bool(pid)}
            status = self._status(host, port, {})

        if action == 'reload':
            return self._reload(folder, host, port, rec, status, prometheus, datasources, vllm_boards, con)

        if action not in ('start', 'restart'):
            return self.cm.error('--action must be start, status, stop, restart or reload (got "%s")' % action)

        if status['running']:
            if con:
                print('Grafana on %s is up already (pid %s)' % (url, rec.get('pid', '?')))
            return {'return': 0, 'port': port, 'host': host, 'url': url, 'already': True, 'state': folder, 'record': rec, **status}
        if status['listening']:
            return self.cm.error('port %d is taken by another process; --port=<another> or stop it' % port)

        try:
            d, sources, sub, vllm = self._choices(prometheus, datasources, sub_path, vllm_boards)
        except ValueError as e:
            return self.cm.error(str(e))
        url = 'http://%s:%d%s' % (host, port, sub)
        prometheus = sources[0]['url']
        anon = str(anonymous or d['anonymous']).strip().lower()
        if anon not in ('auto', 'yes', 'no', 'true', 'false', '1', '0', 'on', 'off'):
            return self.cm.error('--anonymous must be auto, yes or no (got "%s")' % anon)
        anon_on = (host in ('127.0.0.1', 'localhost', '::1')) if anon == 'auto' else anon in ('yes', 'true', '1', 'on')

        # the tool (installed from its release, checked): bin/grafana in the distribution, its home one folder up
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': SETUP_TASK, 'name': TOOL, 'ctx': ctx,
                            'con': con, 'quiet': quiet})
        if r.get('return', 1) > 0:
            return r
        binary = str(r.get('path') or '')
        home = os.path.dirname(os.path.dirname(binary))
        if not os.path.isdir(os.path.join(home, 'public')):
            return self.cm.error('no Grafana distribution around %s (its public/ folder is missing)' % binary)

        for d2 in ('data', 'logs', 'plugins'):
            os.makedirs(os.path.join(folder, d2), exist_ok=True)
        prov = self._provision(folder, sources, vllm)
        home_board = prov['home']
        password, password_file = self._password(folder)
        ini = os.path.join(folder, 'grafana.ini')
        with open(ini, 'w', encoding='utf-8') as f:
            plugins = str(d['plugins'] or 'prometheus').strip().lower()
            f.write(ini_text(folder, host, port, password, anon_on, home_board, [] if plugins == 'all' else OTHER_SOURCES, sub))
        try:
            os.chmod(ini, 0o600)
        except OSError:
            pass

        command = [binary, 'server', '--homepath', home, '--config', ini]
        command += [str(u) for u in unparsed] if unparsed else []
        log = os.path.join(folder, 'server.log')
        rec = {'port': port, 'host': host, 'url': url, 'sub_path': sub, 'sources': sources, 'vllm_boards': vllm,
               'prometheus': prometheus, 'anonymous': anon_on, 'home': home,
               'config': ini, 'command': command, 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
        if con:
            print('')
            print('RUN: %s' % ' '.join(command))
            print('     (log: %s)' % (log if not foreground else 'this console'))
        if foreground:
            p = subprocess.Popen(command, cwd=home)
            self._write_record(folder, dict(rec, pid=p.pid, foreground=True, log=''))
            try:
                rc = p.wait()
            except KeyboardInterrupt:
                p.terminate()
                rc = 0
            try:
                os.remove(os.path.join(folder, 'server.json'))
            except OSError:
                pass
            return {'return': 0, 'port': port, 'returncode': rc, 'foreground': True}

        with open(log, 'ab') as out:
            if os.name == 'nt':
                # a hidden console of its own, not none: a program it starts shares it (Grafana starts one per data
                # source plugin) - detached from any console, each of them opened a window of its own (2026-11-19)
                p = subprocess.Popen(command, cwd=home, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=0x08000000 | 0x00000200)        # CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP
            else:
                p = subprocess.Popen(command, cwd=home, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        rec = dict(rec, pid=p.pid, log=log)
        self._write_record(folder, rec)

        started = time.monotonic()
        ready = False
        while time.monotonic() - started < int(timeout):
            if p.poll() is not None:
                break
            if self._status(host, port, rec)['running']:
                ready = True
                break
            time.sleep(1)
        if not ready:
            tail = ''
            try:
                with open(log, 'rb') as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 1500))
                    tail = f.read().decode('utf-8', 'replace')
            except OSError:
                pass
            if p.poll() is not None:
                return self.cm.error('grafana ended with code %s before it was ready; its log %s ends with:\n%s' % (p.returncode, log, tail))
            return self.cm.error('grafana was not ready within %d s; its log %s ends with:\n%s' % (int(timeout), log, tail))
        status = self._status(host, port, rec)
        if con:
            print('Grafana %s up on %s (pid %d) in %.0f s, drawing from %s' % (status['version'], url, p.pid, time.monotonic() - started, prometheus))
            print('  boards: %s/dashboards/f/cmeta  (%s)' % (url, 'look without signing in' if anon_on else 'sign in as admin'))
            print('  the admin\'s password: %s' % password_file)
            print('  stop: cx task run run-grafana-server --action=stop --port=%d' % port)
        return {'return': 0, 'port': port, 'host': host, 'url': url, 'pid': p.pid, 'state': folder, 'record': rec,
                'seconds': round(time.monotonic() - started, 1), **status}
