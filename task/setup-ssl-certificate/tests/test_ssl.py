"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import importlib.util
from pathlib import Path
import types

import pytest
from cmeta import CMeta


@pytest.fixture
def module():
    cm = CMeta()
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'setup-ssl-certificate,bc27270ee3ef4e56', 'info': True, 'con': False})
    assert r['return'] == 0, r
    spec = importlib.util.spec_from_file_location('ssl_task_test', Path(__file__).parents[1] / 'api_v1.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_active_apache_inventory(module):
    text = '''VirtualHost configuration:
*:80 is a NameVirtualHost
 default server ctuning.ai (/etc/apache2/sites-enabled/main.conf:1)
 port 80 namevhost ctuning.ai (/etc/apache2/sites-enabled/main.conf:1)
         alias www.ctuning.ai
 port 80 namevhost labs.ctuning.ai (/etc/apache2/sites-enabled/labs.conf:1)
         alias *.internal.example.org
*:443 ctuning.ai (/etc/apache2/sites-enabled/main-ssl.conf:1)
*:8080 localhost (/etc/apache2/sites-enabled/local.conf:1)
ServerRoot: "/etc/apache2"
'''
    names = module.apache_domains(text)
    assert names == ['ctuning.ai', 'www.ctuning.ai', 'labs.ctuning.ai', '*.internal.example.org']
    p = module.make_plan('*', names, [], 'ensure')
    assert p['domains'] == names[:3] and p['skipped_wildcard_aliases'] == names[3:]


def test_preserves_sans_and_groups_shared_lineages(module):
    existing = module.certificates('''Certificate Name: public-site
    Domains: example.org www.example.org
    Expiry Date: 2027-01-01 (VALID: 70 days)
    Private Key Path: /etc/letsencrypt/live/public-site/privkey.pem
''')
    p = module.make_plan('*', ['example.org', 'www.example.org'], existing, 'renew')
    assert len(p['jobs']) == 1 and p['jobs'][0]['domains'] == ['example.org', 'www.example.org']
    assert 'Private Key' not in repr(p)


@pytest.mark.parametrize('domain', ['https://example.org', '127.0.0.1', 'localhost', 'x;id.example.org', '-x.example.org', 'x..example.org', 'x.*.example.org'])
def test_rejects_invalid_domains(module, domain):
    with pytest.raises(ValueError): module.domain_name(domain)


def test_wildcard_is_dns_challenge_not_glob(module):
    with pytest.raises(ValueError, match='DNS-01'):
        module.make_plan('*.example.org', ['labs.example.org'], [], 'ensure')
    p = module.make_plan('*.example.org', [], [], 'ensure', dns_plugin='dns-cloudflare')
    assert p['domains'] == ['*.example.org'] and p['jobs'][0]['domains'] == ['*.example.org']
    existing = [{'name': 'wildcard', 'domains': ['*.example.org']}]
    assert module.make_plan('*.example.org', [], existing, 'renew')['jobs'][0]['name'] == 'wildcard'


def test_missing_and_ambiguous_certificate_fail(module):
    with pytest.raises(ValueError, match='No existing'):
        module.make_plan('example.org', [], [], 'renew')
    existing = [{'name': n, 'domains': ['example.org']} for n in ('first', 'second')]
    with pytest.raises(ValueError, match='Multiple'):
        module.make_plan('example.org', [], existing, 'ensure')
    assert module.make_plan('example.org', [], existing, 'ensure', cert_name='second')['jobs'][0]['name'] == 'second'


@pytest.mark.parametrize('mode', ['plan', 'dry_run', 'ensure', 'renew'])
@pytest.mark.parametrize('client_version', ['3.0.0', '4.0.0'])
def test_command_selection_and_no_force_by_default(module, monkeypatch, mode, client_version):
    monkeypatch.setattr(module.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 1000, raising=False)
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/usr/sbin/' + name)
    fake_cm = types.SimpleNamespace(
        access=lambda p: {'return': 0, 'path': '/usr/bin/certbot', 'version': client_version},
        catch_error=lambda r, **kw: r['return'] != 0,
        error=lambda message: {'return': 1, 'error': message})
    task = object.__new__(module.CTask)
    task.cm = fake_cm
    task.category_alias, task.category_uid = 'task', 'c36be4b9314a45e0'
    calls = []
    def execute(ctx, argv, timeout=60):
        calls.append(argv)
        if argv[-1] == '-S': return {'stdout': '*:80 labs.example.org (/etc/apache2/labs.conf:1)', 'stderr': ''}
        if argv[-1] == 'certificates': return {'stdout': 'Certificate Name: labs.example.org\n Domains: labs.example.org\n'}
        return {'stdout': '', 'stderr': ''}
    task.command = execute
    result = task.run({'control': {'quiet': True}}, 'labs.example.org',
                      action='renew' if mode == 'renew' else 'ensure', plan=mode == 'plan', dry_run=mode == 'dry_run')
    assert result['return'] == 0, result
    certificate_calls = [c for c in calls if '/usr/bin/certbot' in c and c[-1] != 'certificates']
    if mode == 'plan': assert not certificate_calls
    else:
        cmd = certificate_calls[0]
        assert cmd[:2] == ['sudo', '-n'] and '--force-renewal' not in cmd
        if mode == 'dry_run': assert 'certonly' in cmd and '--dry-run' in cmd and '--redirect' not in cmd
        if mode == 'ensure': assert 'run' in cmd and '--apache' in cmd and '--keep-until-expiring' in cmd
        if mode == 'renew':
            assert 'renew' in cmd and '--cert-name' in cmd and '--apache' not in cmd
            assert ('--no-random-sleep-on-renew' in cmd) == (client_version == '4.0.0')
