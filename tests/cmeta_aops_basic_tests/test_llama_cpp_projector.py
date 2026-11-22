"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-llama-cpp-server --mmproj offline: a model that reads pictures is served with its projector - the one its file
names (auto), a file of its artifact or a path - by a llama.cpp whose server takes one (build 5331 and later; a build
without a number is asked itself); an older one is refused with the build that serves pictures; the projector is never
taken as the model's file; a running server without it is not taken for one with it.
"""
import json

from test_model_server_tasks import Engine, llama_cpp_task


class VisionEngine(Engine):
    """The stand-in engine with a model artifact of two files: the language model, which names its projector, and
    the projector (sorted first by name, as in Qwen3-VL's artifact); the setup reports the given build."""

    def __init__(self, tmp_path, version='12590', config=None):
        super().__init__(tmp_path, config)
        self.version = version
        self.folder = tmp_path / 'model-vl'
        self.folder.mkdir(exist_ok=True)
        (self.folder / '_desc-mmproj-vl-q8_0.gguf.yaml').write_text('uses: []\n', encoding='utf-8')
        (self.folder / '_desc-vl-q4_k_m.gguf.yaml').write_text('uses: []\nmmproj: mmproj-vl-q8_0.gguf\n', encoding='utf-8')

    def access(self, p):
        if str(p.get('category')).startswith('model,') and p.get('command') == 'find':
            self.calls.append(p)
            return {'return': 0, 'artifacts': [{'path': str(self.folder)}]}
        if str(p.get('arg1') or '').startswith('model,'):
            self.calls.append(p)
            f = self.tmp / ('file-%s' % (p.get('filedesc') or p.get('filename') or 'first'))
            f.write_text('')
            return {'return': 0, 'path': str(f)}
        r = super().access(p)
        if str(p.get('arg1') or '').startswith('setup,'):
            r['version'] = self.version
        return r


def vision_task(task_namespace, tmp_path, monkeypatch, version='12590', config=None):
    task, ns, started, stopped, server = llama_cpp_task(task_namespace, tmp_path, monkeypatch)
    task.cm = VisionEngine(tmp_path, version, config)
    return task, ns, started, stopped, server


def test_the_build_says_whether_the_server_takes_a_projector(task_namespace):
    ns = task_namespace('run-llama-cpp-server')
    supported = ns['projector_supported']
    assert ns['PROJECTOR_SINCE'] == 5331
    assert supported('12590') is True and supported('5331') is True and supported('b5331') is True
    assert supported('5330') is False and supported('4000') is False
    assert supported('0.5.0-dev (build 11324, commit 32dd62ee6)') is True
    assert supported('') is None and supported('a build of my own') is None


def test_the_projector_is_never_the_model_file(task_namespace):
    pick = task_namespace('run-llama-cpp-server')['default_model_file']
    files = ['_desc-mmproj-vl-q8_0.gguf.yaml', '_desc-vl-q4_k_m.gguf.yaml']
    assert pick(files, {'mmproj-vl-q8_0.gguf'}) == 'vl-q4_k_m.gguf'
    # nothing to skip: the model task chooses as before
    assert pick(files, set()) == '' and pick(['_desc-a.gguf.yaml', '_desc-b.gguf.yaml'], {'b.gguf'}) == ''


def test_auto_serves_the_projector_the_model_file_names(task_namespace, tmp_path, monkeypatch):
    task, ns, started, _, _ = vision_task(task_namespace, tmp_path, monkeypatch)
    r = task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl', mmproj='auto')
    assert r['return'] == 0, r
    cmd = started[0][0]
    assert cmd[cmd.index('-m') + 1].endswith('file-vl-q4_k_m.gguf')               # the model, not the projector
    assert cmd[cmd.index('--mmproj') + 1].endswith('file-mmproj-vl-q8_0.gguf')
    rec = json.loads((tmp_path / 'state-llama-cpp-server-8689' / 'server.json').read_text(encoding='utf-8'))
    assert rec['mmproj'] == 'auto' and rec['mmproj_path'].endswith('file-mmproj-vl-q8_0.gguf')


def test_without_mmproj_nothing_changes_but_the_model_file(task_namespace, tmp_path, monkeypatch):
    task, ns, started, _, _ = vision_task(task_namespace, tmp_path, monkeypatch)
    assert task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl')['return'] == 0
    cmd = started[0][0]
    assert '--mmproj' not in cmd and cmd[cmd.index('-m') + 1].endswith('file-vl-q4_k_m.gguf')


def test_an_older_build_is_refused_and_a_build_without_a_number_is_asked(task_namespace, tmp_path, monkeypatch):
    task, ns, started, _, _ = vision_task(task_namespace, tmp_path, monkeypatch, version='5000')
    r = task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl', mmproj='auto')
    assert r['return'] == 1 and 'from build 5331' in r['error'] and not started

    class Help:
        def __init__(self, text):
            self.stdout, self.stderr = text, ''
    for text, ok in (('  --mmproj FILE   path to a multimodal projector file', True), ('  -m FILE  model path', False)):
        task, ns, started, _, _ = vision_task(task_namespace, tmp_path, monkeypatch, version='')
        monkeypatch.setattr(ns['subprocess'], 'run', lambda *a, **k: Help(text))
        r = task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl', mmproj='auto')
        assert (r['return'] == 0) is ok and bool(started) is ok


def test_a_running_server_without_the_projector_is_not_taken_for_one(task_namespace, tmp_path, monkeypatch):
    task, ns, started, stopped, server = vision_task(task_namespace, tmp_path, monkeypatch)
    assert task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl')['return'] == 0
    r = task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl', mmproj='auto')
    assert r['return'] == 0 and r.get('already') and r.get('other_model')          # said; --swap replaces it
    r = task.run({'control': {'con': False}}, action='start', port=8689, model='hf-x@vl', mmproj='auto', swap=True)
    assert r['return'] == 0 and stopped and '--mmproj' in started[-1][0]
