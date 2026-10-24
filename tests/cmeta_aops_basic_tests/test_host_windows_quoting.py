"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host run from a Windows machine to a POSIX ssh host, with a command that holds a double quote (or ^, %, a line
break): cmd.exe toggles its quoting on every " of the one argument it hands to ssh.exe, so such a command never
rides on the command line. Without a terminal it goes on the host's stdin from a temporary script (as before); WITH
a terminal (stdin is the user's keyboard) it travels base64-encoded and runs there from a temporary script - seen
2026-10-22 when a detached run-ai with quoted words reached bash as '''...''' and an unquoted "(stop: ...)".
"""

import base64
import importlib.util
import pathlib
import re
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

CMD = """cx task run run-ai '--project=work::a b' -q 'it'"'"'s "quoted" (x) 100%'"""
HOST = {'alias': 'far', 'type': 'ssh', 'desc': {'access': {'shell': 'bash -l'}}, 'state': {}}


@pytest.fixture()
def host(monkeypatch):
    path = REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'
    spec = importlib.util.spec_from_file_location('category_host_quoting_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    c = module.Category.__new__(module.Category)
    c.cm = SimpleNamespace(error=lambda message: {'return': 1, 'error': message})
    c._here = lambda h: False
    c._ssh_parts = lambda h, **kw: {'return': 0, 'cmd': 'ssh -t u@far' if kw.get('tty') else 'ssh u@far'}
    c._cmd_stdin = lambda ctx, h, path: {'return': 0, 'cmd': 'STDIN ' + pathlib.Path(path).read_text(encoding='utf-8')}
    monkeypatch.setattr(module, 'windows_here', lambda: True)
    return module, c


def test_with_a_terminal_the_command_travels_encoded_and_arrives_intact(host):
    module, c = host
    r = c._cmd_run({}, dict(HOST), CMD, interactive=True)
    assert r['return'] == 0
    line = r['cmd']
    assert line.startswith('ssh -t u@far "') and line.endswith('"')

    # nothing cmd.exe reads in the argument: no ", ^ or %
    inner = line[len('ssh -t u@far "'):-1]
    assert not any(ch in inner for ch in '"^%')
    b64 = re.search(r'echo (\S+) \| base64 -d > \$f && bash -l \$f; rc=\$\?; rm -f \$f; exit \$rc$', inner).group(1)
    assert base64.b64decode(b64).decode('utf-8') == CMD


def test_without_a_terminal_it_goes_on_stdin_and_a_plain_command_stays_readable(host):
    module, c = host
    r = c._cmd_run({}, dict(HOST), CMD, interactive=False)
    assert r['cmd'] == 'STDIN ' + CMD + '\n'                      # the temporary script, fed to the host's shell

    assert c._cmd_run({}, dict(HOST), 'hostname; uptime', interactive=True)['cmd'] == "ssh -t u@far \"bash -l -c 'hostname; uptime'\""
    assert c._cmd_run({}, dict(HOST), "echo 'a b'", interactive=False)['cmd'] == "ssh u@far \"bash -l -c 'echo '\\''a b'\\'''\""


def test_on_linux_and_macos_nothing_changes(host, monkeypatch):
    module, c = host
    monkeypatch.setattr(module, 'windows_here', lambda: False)
    line = c._cmd_run({}, dict(HOST), CMD, interactive=True)['cmd']
    assert 'base64' not in line and line.startswith("ssh -t u@far \"bash -l -c '")


def test_a_powershell_host_is_left_to_its_own_route(host):
    module, c = host
    h = {'alias': 'win', 'type': 'ssh', 'desc': {'access': {'shell': 'powershell'}}, 'state': {}}
    line = c._cmd_run({}, h, 'Write-Output "x"', interactive=True)['cmd']
    assert 'base64 -d' not in line and line.startswith('ssh -t u@far "powershell -NoProfile -Command')
