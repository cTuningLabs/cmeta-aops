"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

get-hf-model at a revision, by patterns (2026-11-26, the models of the MLPerf benchmarks): the words of the hf
command line - a revision, Hugging Face's include / exclude patterns quoted so that no shell expands them (the cache
entry's _cmeta.json for "*.json"), plain file names as before. Offline: the task's helpers, without the engine.
"""

import os

TASK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'task', 'get-hf-model')


def helpers():
    path = os.path.join(TASK, 'api_v1.py')
    with open(path, encoding = 'utf-8') as f:
        src = f.read().replace('from task_c36be4b9314a45e0.api.ctask import InitCTask, file_cache_folder',
                               'class InitCTask:\n    pass\nfile_cache_folder = None')
    ns = {'__name__': 'get_hf_model_under_test', '__file__': path}
    exec(compile(src, path, 'exec'), ns)
    return ns


def test_plain_file_names_stay_as_they_were():
    quoted = helpers()['quoted']
    assert quoted('model-q8_0.gguf') == 'model-q8_0.gguf'
    assert quoted('mnist//train-00000-of-00001.parquet') == 'mnist/train-00000-of-00001.parquet'
    assert quoted('a\\b.json') == 'a/b.json'


def test_a_model_at_a_revision_by_patterns():
    hf_words = helpers()['hf_words']
    assert hf_words() == ''
    words = hf_words('b5c939de8f754692c1647ca79fbf85e8c1e70f8a', ['*.safetensors', '*.json', '*.jinja'], 'metal/*;original/*')
    assert words == (' --revision b5c939de8f754692c1647ca79fbf85e8c1e70f8a'
                     ' --include "*.safetensors" --include "*.json" --include "*.jinja"'
                     ' --exclude "metal/*" --exclude "original/*"')


def test_the_command_reads_the_words_and_old_descriptions_do_not_need_them():
    with open(os.path.join(TASK, '_desc.yaml'), encoding = 'utf-8') as f:
        text = f.read()
    assert '{{local.includes}}{{local.hf_words|}} --local-dir' in text


def test_the_download_folder_is_one_word_of_the_command_line():
    """A folder with a space in its path (a file cache under "C:/Users/First Last") was cut at the space: hf took the
    rest for a file of the model and said "File not found in model" (a Windows machine of the fleet, 2026-11-27)."""
    tasks = os.path.dirname(TASK)
    for task in ('get-hf-model', 'get-hf-dataset'):
        with open(os.path.join(tasks, task, '_desc.yaml'), encoding = 'utf-8') as f:
            desc = f.read()
        assert '--local-dir {{local.qdirectory}}' in desc and '--local-dir {{local.directory}}' not in desc, task
        with open(os.path.join(tasks, task, 'api_v1.py'), encoding = 'utf-8') as f:
            assert "['qdirectory'] = self.cm.q(directory)" in f.read(), task
