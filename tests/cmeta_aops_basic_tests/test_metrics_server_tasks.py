"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-prometheus-server and run-grafana-server without the engine: the targets and the Prometheus configuration,
Grafana's settings, what it provisions (the data source, the three boards), the admin's password made once, and a
start on Windows that opens no window (each of Grafana's data source plugins opened one, 2026-11-19).
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_the_targets_by_name_and_the_configuration(task_namespace):
    ns = task_namespace('run-prometheus-server')
    targets = ns['parse_targets']('ai-gateway=127.0.0.1:8401, gen4=http://100.1.2.3:8686/metrics,https://h.example:443/x/metrics')
    by = {t['name']: t for t in targets}
    assert by['ai-gateway'] == {'name': 'ai-gateway', 'scheme': 'http', 'address': '127.0.0.1:8401', 'path': '/metrics'}
    assert by['gen4']['address'] == '100.1.2.3:8686' and by['gen4']['path'] == '/metrics'
    assert by['h.example-443']['scheme'] == 'https' and by['h.example-443']['path'] == '/x/metrics'
    assert {t['name'] for t in ns['parse_targets'](['x=1.2.3.4:5', ''])} == {'x'}          # a list, as a config holds it
    with pytest.raises(ValueError):
        ns['parse_targets']('a=127.0.0.1')                                                  # no port
    with pytest.raises(ValueError):
        ns['parse_targets']('a=1.2.3.4:1,a=1.2.3.4:2')                                      # one name twice

    cfg = json.loads(ns['config_text'](targets, '10s'))
    jobs = {j['job_name']: j for j in cfg['scrape_configs']}
    assert set(jobs) == {'ai-gateway', 'gen4', 'h.example-443'} and cfg['global']['scrape_interval'] == '10s'
    assert jobs['gen4']['static_configs'] == [{'targets': ['100.1.2.3:8686']}] and jobs['h.example-443']['scheme'] == 'https'


def test_grafana_settings_load_prometheus_alone_and_call_nobody(task_namespace, tmp_path):
    ns = task_namespace('run-grafana-server')
    ini = ns['ini_text'](str(tmp_path), '127.0.0.1', 3000, 'pw', True, 'home.json', ns['OTHER_SOURCES'])
    sections, cur = {}, ''
    for line in ini.splitlines():
        if line.startswith('['):
            cur = line.strip('[]')
        elif ' = ' in line:
            k, _, v = line.partition(' = ')
            sections.setdefault(cur, {})[k] = v
    assert sections['server'] == {'http_addr': '127.0.0.1', 'http_port': '3000'}
    assert sections['auth.anonymous']['enabled'] == 'true' and sections['auth.anonymous']['org_role'] == 'Viewer'
    assert sections['security']['allow_embedding'] == 'true' and sections['users']['allow_sign_up'] == 'false'
    assert sections['analytics']['reporting_enabled'] == 'false' and sections['analytics']['check_for_updates'] == 'false'
    disabled = set(sections['plugins']['disable_plugins'].split(','))
    assert sections['plugins']['preinstall_disabled'] == 'true' and 'loki' in disabled and 'prometheus' not in disabled
    assert sections['paths']['data'] == str(tmp_path / 'data').replace('\\', '/')
    other = ns['ini_text'](str(tmp_path), '0.0.0.0', 3000, 'pw', False, 'h', [])     # on every address: no viewer without sign-in
    lines = other.splitlines()
    assert lines[lines.index('[auth.anonymous]') + 1] == 'enabled = false' and 'disable_plugins = ' in lines


def test_grafana_provisions_its_source_and_three_boards(task_namespace, tmp_path):
    ns = task_namespace('run-grafana-server')
    cls = ns['CTask']
    home = cls._provision(str(tmp_path), 'http://127.0.0.1:9090')
    prov = tmp_path / 'provisioning'
    source = json.loads((prov / 'datasources' / 'cmeta.yaml').read_text(encoding='utf-8'))['datasources'][0]
    assert source['uid'] == 'cmeta-prometheus' and source['url'] == 'http://127.0.0.1:9090' and source['isDefault']
    provider = json.loads((prov / 'dashboards' / 'cmeta.yaml').read_text(encoding='utf-8'))['providers'][0]
    assert provider['folder'] == 'cMeta' and Path(provider['options']['path']) == prov / 'boards'
    boards = {b['uid']: b for b in (json.loads(p.read_text(encoding='utf-8')) for p in (prov / 'boards').glob('*.json'))}
    assert set(boards) == {'cmeta-ai-gateway', 'cmeta-llama-cpp', 'cmeta-vllm'} and home.endswith('cmeta-ai-gateway.json')
    names = {'cmeta-ai-gateway': 'cmeta_ai_gateway_', 'cmeta-llama-cpp': 'llamacpp:', 'cmeta-vllm': 'vllm:'}
    for uid, b in boards.items():
        exprs = [t['expr'] for p in b['panels'] for t in p['targets']]
        assert exprs and all(names[uid] in e for e in exprs), uid
        assert all(p['datasource']['uid'] == 'cmeta-prometheus' for p in b['panels'])
        cells = set()                                   # no two panels on one cell of the grid
        for p in b['panels']:
            g = p['gridPos']
            for x in range(g['x'], g['x'] + g['w']):
                for y in range(g['y'], g['y'] + g['h']):
                    assert (x, y) not in cells, (uid, p['title'])
                    cells.add((x, y))


def test_the_admins_password_is_made_once(task_namespace, tmp_path):
    cls = task_namespace('run-grafana-server')['CTask']
    first, path = cls._password(str(tmp_path))
    again, _ = cls._password(str(tmp_path))
    assert len(first) >= 20 and first == again and Path(path).read_text(encoding='utf-8').strip() == first


def test_a_start_on_windows_opens_no_window():
    for task in ('run-prometheus-server', 'run-grafana-server'):
        source = (REPO / 'task' / task / 'api_v1.py').read_text(encoding='utf-8')
        assert '0x08000000' in source and '0x00000008 |' not in source, task      # CREATE_NO_WINDOW, never DETACHED_PROCESS


def test_prometheus_knows_when_it_began_to_read_live(task_namespace, tmp_path):
    """scraped_since: from its blocks (or its head) once, then kept - an import of older blocks never moves it, so an
    import ends where the live readings begin and a series never holds two counters."""
    ns = task_namespace('run-prometheus-server')
    data = tmp_path / 'data'
    (data / '01LIVE').mkdir(parents=True)
    (data / '01LIVE' / 'meta.json').write_text(json.dumps({'minTime': 1700000000000, 'maxTime': 1700000060000}), encoding='utf-8')
    assert ns['blocks_min_time'](str(data)) == 1700000000.0 and ns['has_data'](str(data))
    assert not ns['has_data'](str(tmp_path / 'nothing'))
    task = ns['CTask'].__new__(ns['CTask'])
    assert task._scraped_since(str(tmp_path), '127.0.0.1', 1, False) == 1700000000.0
    (data / '01IMPORT').mkdir()
    (data / '01IMPORT' / 'meta.json').write_text(json.dumps({'minTime': 1600000000000, 'maxTime': 1600000060000}), encoding='utf-8')
    assert task._scraped_since(str(tmp_path), '127.0.0.1', 1, False) == 1700000000.0
    assert task._scraped_since(str(tmp_path / 'empty'), '127.0.0.1', 1, False) is None

