"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import ipaddress
import json
import os
import platform
import re
import shlex
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask, ask


def domain_name(value):
    text = str(value).strip().rstrip('.').lower()
    wildcard = text.startswith('*.')
    base = text[2:] if wildcard else text
    try:
        base = base.encode('idna').decode('ascii')
        ipaddress.ip_address(base)
    except ValueError:
        pass
    else:
        raise ValueError('Use a DNS hostname, not an IP address: ' + text)
    if len(base) > 253 or '.' not in base or any(
            not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in base.split('.')):
        raise ValueError('Invalid certificate domain: ' + text)
    return ('*.' if wildcard else '') + base


def apache_domains(output):
    """Parse active vhosts from apachectl -S, including ServerAlias entries."""
    result = []
    for line in output.splitlines():
        match = re.search(r'(?:default server|namevhost|alias)\s+(\S+)', line)
        if not match:
            match = re.match(r'\s*\S+:\d+\s+(\S+)\s+\(', line)
        if not match:
            continue
        try:
            name = domain_name(match.group(1))
        except ValueError:
            continue  # localhost/IP-only/internal vhosts are not public DNS names.
        if name not in result:
            result.append(name)
    return result


def certificates(output):
    """Read names and SANs from Certbot's stable human-readable inventory."""
    result, current = [], None
    for line in output.splitlines():
        text = line.strip()
        if text.startswith('Certificate Name:'):
            current = {'name': text.split(':', 1)[1].strip(), 'domains': []}
            result.append(current)
        elif current is not None and text.startswith('Domains:'):
            current['domains'] = [domain_name(d) for d in text.split(':', 1)[1].split()]
        elif current is not None and text.startswith('Expiry Date:'):
            current['expiry'] = text.split(':', 1)[1].strip()
    return result


def make_plan(requested, registered, existing, action, cert_name='', dns_plugin=''):
    if isinstance(requested, str):
        requested = requested.split(',')
    if not isinstance(requested, (list, tuple)) or not requested:
        raise ValueError('domains must be a hostname, comma-separated hostnames, or *')
    all_domains = list(requested) == ['*']
    if '*' in requested and not all_domains:
        raise ValueError('* must be used alone')
    selected = [n for n in registered if not n.startswith('*.')] if all_domains else [domain_name(n) for n in requested]
    selected = list(dict.fromkeys(selected))
    if not selected:
        raise ValueError('No public domains found in enabled Apache virtual hosts')
    if cert_name and len(selected) != 1:
        raise ValueError('cert-name requires a single requested domain')
    if dns_plugin and not re.fullmatch(r'dns-[a-z0-9-]+', dns_plugin):
        raise ValueError('dns-plugin must be a Certbot plugin name such as dns-cloudflare')
    jobs, seen = [], set()
    for domain in selected:
        matches = [c for c in existing if domain in c['domains'] and (not cert_name or c['name'] == cert_name)]
        exact = [c for c in matches if c['name'] == (cert_name or domain)]
        if len(matches) > 1 and not exact:
            raise ValueError('Multiple certificates contain ' + domain + '; select cert-name explicitly')
        current = (exact or matches or [None])[0]
        if action == 'renew' and not current:
            raise ValueError('No existing certificate for ' + domain + '; use action=ensure first')
        names = current['domains'] if current else [domain]
        if any(n.startswith('*.') for n in names) and action == 'ensure' and not dns_plugin:
            raise ValueError('Wildcard issuance requires DNS-01: supply --dns-plugin and its configured credentials; Apache HTTP-01 cannot issue wildcard certificates')
        name = current['name'] if current else (cert_name or domain.replace('*.', 'wildcard.'))
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name):
            raise ValueError('Unsupported certificate name: ' + name)
        if name not in seen:
            jobs.append({'name': name, 'domains': names, 'existing': bool(current)})
            seen.add(name)
    return {'domains': selected, 'registered_domains': registered, 'jobs': jobs,
            'skipped_wildcard_aliases': [n for n in registered if n.startswith('*.')] if all_domains else []}


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def command(self, ctx, argv, timeout=60):
        result = self.cm.access(dict(category=self.category_alias + ',' + self.category_uid,
            command='run', arg1='cmd,c9ba0a88df394d7f', ctx=ctx, con=False,
            quiet=ctx['control'].get('quiet', False), cmd=' '.join(shlex.quote(str(v)) for v in argv),
            capture_output=True, timeout=timeout))
        if self.cm.catch_error(result, fail16=True):
            raise ValueError(result.get('error', 'Command failed'))
        if result.get('returncode', 0):
            raise ValueError((result.get('stderr') or result.get('stdout') or 'Command failed').strip())
        return result

    def run(self, ctx, domains='*', action='ensure', plan: bool=False,
            dry_run: bool=False, force_renewal: bool=False, test_renewal: bool=False,
            dns_plugin='', dns_credentials='', email='', cert_name='', apache_ctl='',
            sudo: bool=True, redirect: bool=True, timeout: int=600):
        """Issue/install or renew Certbot certificates for enabled Apache domains.

        domains=* selects concrete ServerName/ServerAlias names from apachectl -S.
        A literal *.example.org requests a real wildcard and needs DNS-01.
        ensure installs missing certificates and preserves existing SAN sets;
        renew uses each existing lineage's saved authenticator and renews when due.
        plan lists commands without issuance; dry_run validates against staging
        without installing a certificate. test_renewal tests saved renewal afterward.
        Apache/Certbot (and chosen plugins) must already be installed. Run on the
        target host using cx host run or the task engine's --on option.
        """
        try:
            if platform.system() not in ('Linux', 'Darwin'):
                raise ValueError('This Apache/Certbot task currently supports Linux and macOS; run it on the web host')
            if action not in ('ensure', 'renew', 'list'):
                raise ValueError('action must be ensure, renew or list')
            ctl = apache_ctl or next((shutil.which(p) for p in ('apache2ctl', 'apachectl', 'httpd') if shutil.which(p)), None)
            if not ctl:
                raise ValueError('Install Apache on the target web host first')
            setup = self.cm.access(dict(category=self.category_alias + ',' + self.category_uid,
                command='run', arg1='setup,a2f9b61079ce4333', name='certbot,1b27b22465d9409b', ctx=ctx,
                con=False, quiet=ctx['control'].get('quiet', False), skip_install=plan or action == 'list'))
            if self.cm.catch_error(setup, fail16=True): return setup
            certbot = setup['path']
            version = re.match(r'^(\d+)', str(setup.get('version', '')))
            # Verified with Certbot 4.x; preserve older clients' usual delay policy.
            no_random_sleep = ['--no-random-sleep-on-renew'] if version and int(version.group(1)) >= 4 else []
            prefix = [] if os.geteuid() == 0 or not sudo else ['sudo'] + (['-n'] if ctx['control'].get('quiet') else [])
            config = self.command(ctx, prefix + [ctl, '-S'])
            registered = apache_domains(config.get('stdout', '') + '\n' + config.get('stderr', ''))
            inventory = self.command(ctx, prefix + [certbot, 'certificates'])
            existing = certificates(inventory.get('stdout', ''))
            selection = make_plan(domains, registered, existing, action, cert_name, dns_plugin)
            if dns_credentials and not dns_plugin:
                raise ValueError('dns-credentials requires dns-plugin')
            if dns_credentials and not os.path.isfile(os.path.expanduser(dns_credentials)):
                raise ValueError('DNS credentials file does not exist on this host')
            commands = []
            for job in selection['jobs']:
                if action == 'renew':
                    argv = prefix + [certbot, 'renew', '--cert-name', job['name']] + no_random_sleep
                else:
                    argv = prefix + [certbot, 'certonly' if dry_run else 'run']
                    argv += ['--authenticator', dns_plugin] if dns_plugin else ['--apache']
                    if dns_plugin:
                        if dns_credentials: argv += ['--' + dns_plugin + '-credentials', os.path.expanduser(dns_credentials)]
                        # DNS plugins authenticate; Apache installs the resulting certificate.
                        if not dry_run: argv += ['--installer', 'apache']
                    if redirect and not dry_run: argv += ['--redirect']
                    argv += ['--cert-name', job['name']]
                    if not force_renewal: argv += ['--keep-until-expiring']
                    for domain in job['domains']: argv += ['-d', domain]
                    if email: argv += ['--email', email, '--agree-tos']
                argv += ['--non-interactive']
                if dry_run: argv += ['--dry-run']
                if force_renewal and not dry_run: argv += ['--force-renewal']
                commands.append(argv)
            selection.update(action=action, commands=commands, dry_run=dry_run)
            if ctx['control'].get('con'):
                print(json.dumps(selection, indent=2))
            if plan or action == 'list':
                return dict(selection, **{'return': 0})
            if not ctx['control'].get('quiet'):
                response = ask('Run these certificate operations? [Y/n] ')
                if response['return']: return response
                if response['answer'].strip().lower() not in ('', 'y', 'yes'):
                    return {'return': 0, 'status': 'declined'}
            results = []
            for job, argv in zip(selection['jobs'], commands):
                result = self.command(ctx, argv, timeout)
                if ctx['control'].get('con'):
                    print(result.get('stdout', ''))
                    print(result.get('stderr', ''))
                results.append({'certificate': job['name'], 'status': 'validated' if dry_run else 'completed'})
                if test_renewal and not dry_run:
                    self.command(ctx, prefix + [certbot, 'renew', '--cert-name', job['name'], '--dry-run'] + no_random_sleep, timeout)
            self.command(ctx, prefix + [ctl, '-t'])
            return dict(selection, results=results, **{'return': 0})
        except (ValueError, OSError) as error:
            return self.cm.error(str(error))
