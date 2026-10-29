"""Project isolation, readiness checks, and preservation of global probe observations."""
import contextlib
import copy
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import yaml

spec = importlib.util.spec_from_file_location('host_projects_test', Path(__file__).parents[1] / 'api/v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Projects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.cat = module.Category.__new__(module.Category)
        self.cat._host_cache = {}
        self.cat.path = str(Path(__file__).parents[1])
        self.cat.logger = None
        self.cat.cm = types.SimpleNamespace(error=lambda error: {'return': 1, 'error': error})
        self.cat.cm.utils = types.SimpleNamespace(files=types.SimpleNamespace(safe_write_file=self.write))
        self.cat._read_yaml = lambda path: yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {}
        self.host = {'alias': 'vm', 'path': str(self.path), 'type': 'ssh', 'status': 'up',
                     'machine': 'machine', 'state': {'cmeta_version': 'global', 'projects': {'other': {'repos': {'keep': {}}}}},
                     'desc': {'access': {'shell': 'bash -l'}, 'cmeta': {'home': '/global', 'install': 'uv-tool'},
                              'sync': {'repos_path': '/global/repos', 'repos': ['global-only']},
                              'projects': {'web': {'path': '/apps/web', 'venv': '/apps/web/.venv',
                                                   'cmeta': {'home': '/apps/web/CMR', 'install': 'pip'},
                                                   'server': {'url': 'http://127.0.0.1:1/'}}}}}

    def write(self, path, value, **kwargs):
        Path(path).write_text(yaml.safe_dump(value))
        return {'return': 0}

    def test_selection_isolates_global_configuration_and_cache(self):
        before = copy.deepcopy(self.host)
        selected = self.cat._project_host(self.host, 'web')['host']
        self.assertEqual(selected['desc']['cmeta']['home'], '/apps/web/CMR')
        self.assertNotIn('upgrade', selected['desc']['cmeta'])
        self.assertEqual(selected['desc']['sync'], {})
        selected['desc']['access']['user'] = 'changed'
        self.assertEqual(self.host, before)
        self.assertGreater(self.cat._project_host(self.host, 'missing')['return'], 0)

    def test_project_upgrade_rejects_host_wide_actions_before_selection(self):
        for option in ('restart', 'system', 'firmware'):
            result = self.cat.upgrade_({}, project='web', **{option: True})
            self.assertGreater(result['return'], 0)
            self.assertIn('whole host', result['error'])

    def test_fleet_selection_ignores_migration_stubs(self):
        real = {'cmeta': {}, 'path': '/real'}
        stub = {'cmeta': {'migrated_to': 'vm,1234'}, 'path': '/stub'}
        self.cat._prepare_input_from_ctx = lambda ctx, **kwargs: {}
        self.cat.cm.access = lambda params: {'return': 0, 'artifacts': [stub, real]}
        self.cat._load_host = mock.Mock(return_value=self.host)
        result = self.cat._select({})
        self.assertEqual(result['hosts'], [self.host])
        self.cat._load_host.assert_called_once_with(real)

    @unittest.skipIf(os.name == 'nt', 'POSIX shell integration runs on the Linux host')
    def test_shell_context_handles_spaces_and_never_falls_back_on_setup_failure(self):
        root = self.path / "project's app"
        bindir = root / '.venv/bin'
        bindir.mkdir(parents=True)
        cx = bindir / 'cx'
        cx.write_text('#!/bin/sh\nprintf "project:%s:%s\\n" "$CMETA_HOME" "$PWD"\n')
        cx.chmod(0o700)
        (bindir / 'activate').write_text('export VIRTUAL_ENV=' + module.shlex.quote(str(root / '.venv')) + '\n'
                                        'export PATH=' + module.shlex.quote(str(bindir)) + ':"$PATH"\n')
        project = self.host['desc']['projects']['web']
        project.update(path=str(root), venv=str(root / '.venv'), cmeta={'home': str(root / 'CMR')})
        selected = self.cat._project_host(self.host, 'web')['host']
        command = self.cat._project_command(selected, 'cx; pwd')
        result = subprocess.run(['bash', '-c', command], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(f'project:{root}/CMR:{root}', result.stdout.decode())
        selected['project_desc']['venv'] = str(root / 'missing')
        marker = self.path / 'must-not-exist'
        command = self.cat._project_command(selected, 'true; touch ' + module.shlex.quote(str(marker)))
        result = subprocess.run(['bash', '-c', command], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    def test_project_probe_preserves_global_and_other_projects(self):
        self.write(self.path / 'state.yaml', self.host['state'])
        selected = self.cat._project_host(self.host, 'web')['host']
        self.cat._cmd_stdin = lambda *args: {'return': 0, 'cmd': 'probe'}
        self.cat._run_local = lambda *args, **kwargs: {'returncode': 0, 'stdout': 'hostname=vm\ncmeta_version=project\ncmeta_home=/apps/web/CMR\n'}
        self.cat._project_status_all = lambda ctx, hosts: hosts[0].update(project_status={'web': {'status': 'down'}})
        result = self.cat._probe_one({}, selected, 5, False)
        saved = self.cat._read_yaml(self.path / 'state.yaml')
        self.assertEqual(result['return'], 0)
        self.assertEqual(saved['cmeta_version'], 'global')
        self.assertEqual(saved['projects']['other']['repos'], {'keep': {}})
        self.assertEqual(saved['projects']['web']['cmeta_version'], 'project')
        self.assertEqual(saved['projects']['web']['server']['status'], 'down')
        self.cat._probe_one({}, self.host, 5, False)
        saved = self.cat._read_yaml(self.path / 'state.yaml')
        self.assertIn('web', saved['projects'])

        # a project the host no longer declares leaves state.yaml at its next probe (72c644c)
        self.assertNotIn('other', saved['projects'])

    @unittest.skipIf(os.name == 'nt', 'POSIX shell integration runs on the Linux host')
    def test_global_cx_on_the_host_ignores_an_activated_project(self):
        global_bin = self.path / 'global/bin'
        project_bin = self.path / 'project/bin'
        global_bin.mkdir(parents=True)
        project_bin.mkdir(parents=True)
        for directory, label in ((global_bin, 'global'), (project_bin, 'project')):
            cx = directory / 'cx'
            cx.write_text(f'#!/bin/sh\nprintf "{label}:%s\\n" "$CMETA_HOME"\n')
            cx.chmod(0o700)
        self.host['state']['cx'] = str(global_bin / 'cx')
        with mock.patch.dict(os.environ, {'VIRTUAL_ENV': str(project_bin.parent),
                                         'CMETA_HOME': '/project',
                                         'PATH': str(project_bin) + ':' + os.environ['PATH']}):
            command = self.cat._global_command_here(self.host, 'cx')
            result = subprocess.run(['bash', '-c', command], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode().strip(), 'global:/global')

    def test_http_readiness_uses_local_responses_without_following_redirects(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500 if self.path == '/error' else 302)
                self.send_header('Location', 'http://127.0.0.1:1/not-the-project')
                self.end_headers()
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        base = copy.deepcopy(self.host['desc']['projects']['web'])
        self.host['desc']['projects'] = {
            name: dict(base, server={'url': address})
            for name, address in {'redirect': url, 'error': url + '/error', 'refused': 'http://127.0.0.1:1/'}.items()}

        def temp_script(script, suffix='.sh'):
            path = self.path / ('status' + suffix)
            path.write_text(script)
            return {'return': 0, 'path': str(path)}
        self.cat._temp_script = temp_script
        self.cat._cmd_stdin = lambda ctx, host, path: {'return': 0, 'cmd': path}
        def local(path, **kwargs):
            # Run the exact Python payload locally, without requiring bash on Windows.
            code = Path(path).read_text().split('\n', 1)[1].rsplit('CMETA_PROJECT_STATUS', 1)[0]
            result = subprocess.run([sys.executable, '-c', code], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            return {'returncode': result.returncode, 'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}
        self.cat._run_local = local
        self.cat._project_status_all({}, [self.host], timeout=1, cmd_timeout=5)
        status = self.host['project_status']
        self.assertEqual(status['redirect']['status'], 'up')
        self.assertEqual(status['redirect']['http_status'], 302)
        self.assertEqual(status['error']['status'], 'unhealthy')
        self.assertIn(status['refused']['status'], ('down', 'timeout'))
        self.host['status'] = 'down'
        self.cat._run_local = lambda *args, **kwargs: self.fail('must not query an unreachable host')
        self.cat._project_status_all({}, [self.host])
        self.assertEqual(self.host['project_status']['redirect']['status'], 'host down')

    def test_child_rows_keep_host_status_and_requested_indentation(self):
        self.host['project_status'] = {'web': {'status': 'down', 'url': 'http://127.0.0.1:1/'}}
        row = self.cat._row(self.host, True)
        self.assertEqual(row['status'], 'up')
        self.assertEqual(row['projects'][0]['status'], 'down')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.cat._print_table(['HOST', 'STATUS'], [row], projects=self.cat._project_details([self.host]))
        self.assertTrue(any(line.startswith('  * web  server: down') for line in output.getvalue().splitlines()))

    def test_a_quoted_command_for_a_local_wsl_or_docker_host_travels_as_a_script(self):
        """On Windows a command for wsl.exe / docker exec is one argument that cmd.exe parses: with a double
        quote in it, it goes to the host's shell on stdin instead (the route ssh hosts already take)."""
        scripts = []
        self.cat._temp_script = lambda cmd: (scripts.append(cmd), {'return': 0, 'path': 'script.sh'})[1]
        self.cat._cmd_stdin = lambda ctx, host, path: {'return': 0, 'cmd': 'stdin < ' + path, 'here': False}
        hosts = {'wsl': {'alias': 'w', 'type': 'wsl', 'status': 'up', 'desc': {'access': {'distro': 'ubuntu', 'shell': 'bash -l'}}},
                 'docker': {'alias': 'd', 'type': 'docker', 'status': 'up', 'desc': {'access': {'container': 'box', 'shell': 'bash -l'}}}}
        quoted = 'E=$(sed -n "s/x/y/p" f | head -1); uv tool install "cmeta${E:+[$E]}"'
        with mock.patch.object(module.os, 'name', 'nt'):
            for kind, host in hosts.items():
                scripts.clear()
                self.assertEqual(self.cat._cmd_run({}, host, quoted)['cmd'], 'stdin < script.sh', kind)
                self.assertEqual(scripts, [quoted], kind)
                # a plain command still rides on the command line; so do an interactive one and a raw one on stdin
                plain = self.cat._cmd_run({}, host, 'uv tool upgrade cmeta')['cmd']
                self.assertTrue(plain.endswith('bash -l -c "uv tool upgrade cmeta"'), plain)
                self.assertNotIn('stdin', self.cat._cmd_run({}, host, 'echo "x"', interactive=True)['cmd'])
                self.assertNotIn('stdin <', self.cat._cmd_run({}, host, 'sh -s "x"', raw=True, stdin=True)['cmd'])
                self.assertEqual(len(scripts), 1, kind)
        # on a POSIX machine the command is one argument of the local process, single-quoted: no script
        with mock.patch.object(module.os, 'name', 'posix'):
            scripts.clear()
            self.assertIn("-c '", self.cat._cmd_run({}, hosts['docker'], quoted)['cmd'])
            self.assertEqual(scripts, [])

    # After a restart: the declared projects are waited for (2026-10-29: a site's backend failed at every start
    # after a reboot while the detached launcher returned 0)

    def stub_checks(self, rounds):
        """Each round of the wait sees the next (server status, public URL status) of rounds; the last one repeats."""
        calls = []
        self.host['desc']['projects']['web']['server']['public'] = ['https://example.org/repo/']
        def now():
            return rounds[min(len(calls), len(rounds)) - 1]
        def project_status(ctx, hosts):
            calls.append(1)
            hosts[0]['project_status'] = {'web': {'status': now()[0], 'url': 'http://127.0.0.1:1/'}}
        def public_status(hosts):
            hosts[0]['public_status'] = {'web': [{'url': 'https://example.org/repo/', 'status': now()[1]}]}
        self.cat._project_status_all = project_status
        self.cat._public_status_all = public_status
        return calls

    def test_wait_projects_waits_until_server_and_public_urls_answer(self):
        calls = self.stub_checks([('down', 'unreachable'), ('up', 'http 502'), ('up', 'works')])
        with mock.patch.object(module.time, 'sleep') as sleep:
            self.assertEqual(self.cat._wait_projects({}, self.host, False, 300), [])
        self.assertEqual((len(calls), sleep.call_count), (3, 2))

    def test_wait_projects_reports_what_still_fails_when_the_time_is_up(self):
        calls = self.stub_checks([('up', 'http 502')])
        clock = iter(range(0, 10000, 100))
        with mock.patch.object(module.time, 'sleep'), mock.patch.object(module.time, 'monotonic', lambda: next(clock)):
            self.assertEqual(self.cat._wait_projects({}, self.host, False, 300), ['web'])
        self.assertEqual(len(calls), 3)
        # a project without a server URL is not a failure; neither is a retired one
        self.stub_checks([('not configured', 'works')])
        self.assertEqual(self.cat._wait_projects({}, self.host, False, 0), [])

    def restart(self, **kwargs):
        self.host['desc']['commands'] = {'after_restart': ['sh ~/_start.sh &']}
        stamps = iter(['boot-1', 'boot-2'])
        self.cat.cm.catch_error = lambda r: r.get('return', 0) > 0
        self.cat._get_host = lambda ctx, alias: {'return': 0, 'host': self.host}
        self.cat._status = lambda ctx, h, *a, **k: 'up'
        self.cat._shell = lambda h: 'bash -l'
        self.cat._cmd_run = lambda ctx, h, cmd, **k: {'return': 0, 'cmd': 'ssh vm ' + cmd}
        self.cat._run_local = lambda cmd, **k: {'returncode': 255 if 'shutdown' in cmd else 0}
        self.cat._boot_stamp = lambda ctx, h: next(stamps)
        self.cat._refresh_state = lambda ctx, h, con: None
        waited = []
        self.cat._wait_projects = lambda ctx, h, con, timeout: waited.append(timeout) or ['web']
        with mock.patch.object(module.time, 'sleep'):
            r = self.cat.restart_({'control': {'quiet': True}}, arg1='vm', **kwargs)
        return r, waited

    def test_restart_fails_when_a_project_does_not_answer(self):
        r, waited = self.restart(check_timeout=120)
        self.assertEqual((r['return'], waited), (1, [120]))
        self.assertIn('not every project answers', r['error'])
        self.assertIn('web', r['error'])
        self.assertEqual(r['after_restart'], [{'cmd': 'sh ~/_start.sh &', 'returncode': 0}])

    def test_restart_without_check_or_without_after_restart_does_not_wait(self):
        for flags in ({'skip_check': True}, {'skip_after': True}):
            r, waited = self.restart(**flags)
            self.assertEqual((r['return'], waited), (0, []), flags)


if __name__ == '__main__':
    unittest.main()
