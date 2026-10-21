"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Retired inventory remains visible without contacting its historical endpoints.
"""

import contextlib
import copy
import importlib.util
import io
from pathlib import Path
from unittest import mock


def category(name):
    path = Path(__file__).parents[2] / 'category' / name / 'api/v1.py'
    spec = importlib.util.spec_from_file_location('retired_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.Category.__new__(module.Category)


def host(retired=True):
    return {
        'alias': 'old-vm-destroyed', 'type': 'ssh', 'machine': 'old-vm',
        'desc': {'retired': retired, 'access': {'address': '192.0.2.1'},
                 'projects': {'web': {'server': {'url': 'https://example.invalid/'}}}},
        'state': {'projects': {'web': {'server': {'status': 'down', 'http_status': 503}}}},
    }


def test_retired_host_never_contacts_transport_or_project_server():
    module, cat = category('host')
    retired = host()
    original = copy.deepcopy(retired['state'])
    with mock.patch.object(module.socket, 'create_connection', side_effect=AssertionError('network contacted')), \
            mock.patch.object(cat, '_run_local', side_effect=AssertionError('remote command executed')):
        cat._status_all({}, [retired])
        cat._project_status_all({}, [retired])

    assert retired['status'] == 'retired'
    for live in (False, True):
        row = cat._row(retired, live)
        assert row['status'] == 'retired'
        assert row['retired'] is True
        assert row['projects'][0]['status'] == 'retired'
        assert row['projects'][0]['server']['url'] == 'https://example.invalid/'
        assert 'http_status' not in row['projects'][0]['server']
    assert retired['state'] == original


def test_retired_project_selection_keeps_retirement():
    _, cat = category('host')
    selected = host(False)
    selected['host_desc'] = host()['desc']
    assert cat._status({}, selected) == 'retired'
    assert cat._row(selected, False)['retired'] is True


def test_unmarked_and_reactivated_hosts_still_check_their_connection():
    module, cat = category('host')
    for flag in (False, None):
        active = host(flag)
        if flag is None:
            active['desc'].pop('retired')
        with mock.patch.object(cat, '_here', return_value=False), \
                mock.patch.object(module.socket, 'create_connection') as connect:
            assert cat._status({}, active) == 'up'
            connect.assert_called_once_with(('192.0.2.1', 22), timeout=3)
        assert cat._row(active, False)['retired'] is False


def test_saved_host_listing_mentions_retirement_without_live_checks():
    _, cat = category('host')
    cat.cm = mock.Mock()
    cat.cm.catch_error.return_value = False
    cat._select = mock.Mock(return_value={'return': 0, 'hosts': [host(), host(False)]})
    cat._status_all = mock.Mock(side_effect=AssertionError('live check requested'))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = cat.list_({'control': {'con': True}})
    assert result['return'] == 0
    assert 'STATUS' in output.getvalue()
    assert 'retired' in output.getvalue()


def test_machine_list_and_show_expose_declared_retirement():
    _, cat = category('machine')
    cat.cm = mock.Mock()
    cat.cm.catch_error.return_value = False
    machines = [{'alias': 'old-vm', 'path': '/inventory/old-vm', 'desc': {'retired': True}},
                {'alias': 'current-vm', 'path': '/inventory/current-vm', 'desc': {}}]
    cat._select = mock.Mock(return_value={'return': 0, 'machines': machines})
    cat._hosts_by_machine = mock.Mock(return_value={'return': 0, 'by_machine': {'old-vm': ['old-endpoint']}})
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = cat.list_({'control': {'con': True}})
    assert 'STATUS' in output.getvalue() and 'retired' in output.getvalue()
    assert result['machines'][0]['status'] == 'retired'
    assert result['machines'][0]['retired'] is True
    assert result['machines'][1]['status'] == '-'
    assert result['machines'][1]['retired'] is False
    cat._select.return_value = {'return': 0, 'machines': machines[:1]}
    shown = cat.show_({'control': {'con': False}}, arg1='old-vm')['machine']
    assert shown['retired'] is True and shown['status'] == 'retired'
    assert shown['hosts'] == ['old-endpoint']
