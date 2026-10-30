"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-vibe (2026-10-30): Mistral Vibe as a harness of run-ai. A fake "vibe" records the command lines: a short headless
prompt goes as "-p <text>", a long one (or --prompt_file alone) as "--prompt-file"; --yes is "--auto-approve"; every
headless run gets an --output-dir whose export.json gives the statistics and the session; an interactive session drops
the flags vibe takes in headless mode only (--model among them).
"""

import json
import os
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module')
def vibe(task_namespace):
    return task_namespace('run-vibe')


EXPORT = {'vibe_version': '3.0.4', 'config': {'active_model': 'devstral-2'},
          'usage': {'prompt_tokens': 1200, 'completion_tokens': 80, 'total_tokens': 1280}, 'cost': 0.0123,
          'stop_reason': 'end_turn', 'outcome': 'finished', 'session_id': 'abc123'}


class FakeProcess:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        if '--output-dir' in cmd:
            folder = cmd[cmd.index('--output-dir') + 1]
            with open(os.path.join(folder, 'export.json'), 'w', encoding='utf-8') as f:
                json.dump(EXPORT, f)
        self.stdout = iter(['ok\n'])

    def wait(self):
        return 0


def task(ns, monkeypatch, calls):
    CTask = ns['CTask']
    t = CTask.__new__(CTask)
    t.cm = SimpleNamespace(error=lambda message, code=1: {'return': code, 'error': message}, catch_error=lambda r: r.get('return', 0) > 0)

    def popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProcess(cmd, **kwargs)

    monkeypatch.setattr(ns['subprocess'], 'Popen', popen)
    monkeypatch.setattr(ns['subprocess'], 'call', lambda cmd, **kwargs: calls.append(cmd) or 0)
    return t


CTX = {'control': {'con': False}, 'tasks': {'nested_call': 0, 'global': {'vibe': {'path': 'vibe'}}}}


def test_a_headless_run_and_its_statistics(vibe, monkeypatch):
    calls = []
    r = task(vibe, monkeypatch, calls).run(CTX, prompt='Say ok', yes=True, skip_output_file=True, unparsed=['--model', 'devstral-2'])
    assert r['return'] == 0 and r['output'] == 'ok\n'
    cmd = calls[0]
    assert cmd[0] == 'vibe' and cmd[-2:] == ['-p', 'Say ok'] and '--auto-approve' in cmd and cmd[cmd.index('--model') + 1] == 'devstral-2'
    assert '--output-dir' in cmd and not os.path.exists(cmd[cmd.index('--output-dir') + 1])      # its own export folder, removed
    assert r['tokens']['sent'] == 1200 and r['tokens']['output'] == 80 and r['tokens']['total'] == 1280
    assert r['tokens']['cost_usd'] == 0.0123 and r['conversation_id'] == 'abc123' and r['stats']['stop_reason'] == 'end_turn'


def test_a_long_prompt_or_a_prompt_file_goes_as_a_file(vibe, monkeypatch, tmp_path):
    calls = []
    t = task(vibe, monkeypatch, calls)
    long = 'x' * (vibe['MAX_PROMPT_ARG_CHARS'] + 10)
    assert t.run(CTX, prompt=long, skip_output_file=True)['return'] == 0
    assert calls[0][-2] == '--prompt-file' and not os.path.exists(calls[0][-1])                # a file of its own, removed

    pf = tmp_path / 'p.md'
    pf.write_text('Review the code', encoding='utf-8')
    assert t.run(CTX, prompt_file=str(pf), skip_output_file=True)['return'] == 0
    assert calls[1][-2:] == ['--prompt-file', str(pf)]


def test_an_interactive_session_drops_the_headless_flags(vibe, monkeypatch):
    calls = []
    r = task(vibe, monkeypatch, calls).run(CTX, prompt='Start here', interactive=True, unparsed=['--model', 'devstral-2', '--max-turns', '5', '--trust'])
    assert r['return'] == 0 and r['interactive']
    assert calls[0] == ['vibe', '--trust', 'Start here']


def test_read_export_without_one(vibe, tmp_path):
    assert vibe['read_export'](str(tmp_path)) == {}
