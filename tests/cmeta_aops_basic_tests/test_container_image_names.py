"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The image names of the container category (2026-10-17), offline: a base built under a moving tag (-cmeta-latest,
-cmeta-git[-<ref>]) is tagged with the cMeta it holds (-cmeta-0.37.4, -cmeta-git-<commit8>); a git install is named
apart from a PyPI one; the refresh lines of Containerfile.base leave the identity of a build unchanged (images built
before them are recognized); the listing reads the cMeta of each image from its tags or its base; "clean --old"
removes only the images a newer build replaced; an image on a base is built again when its base changed.
"""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def mod():
    path = REPO_ROOT / 'category' / 'container' / 'api' / 'v1.py'
    spec = importlib.util.spec_from_file_location('container_category_v1', str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_tag_that_names_the_cmeta_inside(mod):
    vt = mod.version_tag
    assert vt('cmeta/ubuntu:26.04-cmeta-latest', 'pypi', '0.37.4') == 'cmeta/ubuntu:26.04-cmeta-0.37.4'
    assert vt('cmeta/ubuntu:26.04-cuda13.3.1-devel-cmeta-latest', 'pypi', '0.38.0rc1') == \
        'cmeta/ubuntu:26.04-cuda13.3.1-devel-cmeta-0.38.0rc1'
    assert vt('cmeta/ubuntu:26.04-cmeta-latest', 'pypi', '0.37.4+local') == 'cmeta/ubuntu:26.04-cmeta-0.37.4-local'
    assert vt('cmeta/ubuntu:26.04-cmeta-0.37.4', 'pypi', '0.37.4') is None          # pinned: the tag says it already
    git = {'url': 'https://github.com/cTuningLabs/cmeta', 'vcs_info': {'vcs': 'git', 'commit_id': '1a2b3c4d5e6f' + '0' * 28}}
    assert vt('cmeta/ubuntu:26.04-cmeta-git', 'git', '0.37.4.1', git) == 'cmeta/ubuntu:26.04-cmeta-git-1a2b3c4d'
    assert vt('cmeta/ubuntu:26.04-cmeta-git-dev', 'git', '0.37.4.1', git) == 'cmeta/ubuntu:26.04-cmeta-git-dev-1a2b3c4d'
    assert vt('cmeta/ubuntu:26.04-cmeta-git', 'git', '0.37.4.1', {}) is None


def test_the_cmeta_read_from_tags(mod):
    of = mod.cmeta_of_tags
    assert of(['cmeta/ubuntu:26.04-cmeta-latest', 'cmeta/ubuntu:26.04-cmeta-0.37.4']) == '0.37.4'
    assert of(['cmeta/ubuntu:26.04-cmeta-git', 'cmeta/ubuntu:26.04-cmeta-git-1a2b3c4d']) == 'git-1a2b3c4d'
    assert of(['cmeta/ubuntu:26.04-cmeta-local-0f1e2d3c']) == 'local-0f1e2d3c'
    assert of(['cmeta/ubuntu:26.04-cmeta-latest']) == '' and of(['cmeta/ubuntu:26.04-cmeta-git-dev']) == ''
    assert mod.short_image('localhost/cmeta/ubuntu:26.04-cmeta-latest') == 'cmeta/ubuntu:26.04-cmeta-latest'


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))
    r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(REPO_ROOT), 'con': False})
    assert r['return'] == 0, r
    return c


def render(cm, out, **keys):
    r = cm.access({'category': 'container', 'command': 'render', 'arg1': 'ubuntu', 'engine': 'docker', 'out': str(out),
                   'template': keys, 'con': False})
    assert r['return'] == 0, r
    return r


def test_a_git_install_is_named_apart_from_pypi(cm, tmp_path):
    assert render(cm, tmp_path / 'a')['image'] == 'cmeta/ubuntu:26.04-cmeta-latest'
    assert render(cm, tmp_path / 'b', cmeta_version='0.37.4')['image'] == 'cmeta/ubuntu:26.04-cmeta-0.37.4'
    assert render(cm, tmp_path / 'c', cmeta_source='git')['image'] == 'cmeta/ubuntu:26.04-cmeta-git'
    assert render(cm, tmp_path / 'd', cmeta_source='git', cmeta_git_ref='Dev/X')['image'] == 'cmeta/ubuntu:26.04-cmeta-git-dev-x'


def test_the_refresh_lines_leave_the_identity_unchanged(cm, tmp_path, mod):
    r = render(cm, tmp_path / 'e')
    files = r['files']
    assert mod.REFRESH_BLOCK in files['Containerfile']
    assert files['Containerfile'].index(mod.REFRESH_BLOCK) < files['Containerfile'].index('astral.sh/uv/install.sh')
    before = dict(files, Containerfile=files['Containerfile'].replace(mod.REFRESH_BLOCK, ''))
    args = ([], '', r['params']['from'], '', r['image'])
    assert mod.build_identity(files, *args) == mod.build_identity(before, *args) == r['params_hash']


class FakeEngine:
    """docker images / image inspect / rmi of a fixed set of images."""

    def __init__(self, images):
        self.images = images          # [{'id', 'tags', 'labels'}]
        self.calls = []

    def __call__(self, engine, args, capture=True, con=False, timeout=None):
        self.calls.append(args)
        if args[0] == 'images':
            lines = []
            for im in self.images:
                for t in im['tags'] or ['<none>:<none>']:
                    lines.append(f'{im["id"]} ~~ {t} ~~ 1.2GB ~~ 2 days ago')
            return {'return': 0, 'returncode': 0, 'stdout': '\n'.join(lines)}
        if args[:2] == ['image', 'inspect']:
            import json
            ids = args[2:]
            return {'return': 0, 'returncode': 0, 'stdout': json.dumps(
                [{'Id': im['id'], 'Parent': im.get('parent', ''), 'Config': {'Labels': im['labels']}}
                 for im in self.images if im['id'] in ids])}
        if args[0] == 'rmi':
            return {'return': 0, 'returncode': 0, 'stdout': ''}
        return {'return': 0, 'returncode': 0, 'stdout': ''}


IMAGES = [
    {'id': 'sha256:aaa', 'tags': ['cmeta/ubuntu:26.04-cmeta-0.37.4', 'cmeta/ubuntu:26.04-cmeta-latest'],
     'labels': {'cmeta.container': '1', 'cmeta.kind': 'base', 'cmeta.moving_tag': 'cmeta/ubuntu:26.04-cmeta-latest'}},
    {'id': 'sha256:bbb', 'tags': ['cmeta/ubuntu:26.04-cmeta-0.37.3'],                    # replaced by a refresh
     'labels': {'cmeta.container': '1', 'cmeta.kind': 'base', 'cmeta.moving_tag': 'cmeta/ubuntu:26.04-cmeta-latest'}},
    {'id': 'sha256:ccc', 'tags': ['cmeta/llama-cpp:ubuntu-26.04'],
     'labels': {'cmeta.container': '1', 'cmeta.kind': 'app', 'cmeta.moving_tag': 'cmeta/ubuntu:26.04-cmeta-latest',
                'cmeta.base_image_id': 'sha256:aaa'}},       # an app built before its own moving_tag was empty
    {'id': 'sha256:ddd', 'tags': [], 'labels': {'cmeta.container': '1'}},             # left without a tag
    {'id': 'sha256:eee', 'tags': ['cmeta/debian:12-cmeta-0.37.1'], 'labels': {'cmeta.container': '1'}},   # pinned
    # the classic builder's layers of an app: untagged, with the base's labels, each the parent of the next
    {'id': 'sha256:fff', 'tags': [], 'labels': {'cmeta.container': '1', 'cmeta.moving_tag': 'cmeta/ubuntu:26.04-cmeta-latest'}},
    {'id': 'sha256:ggg', 'tags': ['cmeta/cmeta-test:ubuntu-26.04'], 'parent': 'sha256:fff',
     'labels': {'cmeta.container': '1', 'cmeta.base_image_id': 'sha256:aaa'}},
]


def category(mod, engine):
    c = object.__new__(mod.Category)
    c._engine_run = engine
    c._pick_engine = lambda engine='', need_binary=True: {'return': 0, 'engine': 'docker'}
    c._check_daemon = lambda engine: {'return': 0}
    return c


def test_the_listing_names_the_cmeta_of_every_image(mod):
    rows = {r['id']: r for r in category(mod, FakeEngine(IMAGES))._image_rows('docker')}
    assert rows['sha256:aaa']['tags'][0] == 'cmeta/ubuntu:26.04-cmeta-latest'          # the moving tag first
    assert rows['sha256:aaa']['cmeta'] == '0.37.4' and rows['sha256:bbb']['cmeta'] == '0.37.3'
    assert rows['sha256:ccc']['cmeta'] == '0.37.4'                                     # from the base it was built on
    assert rows['sha256:ddd']['tags'] == [] and rows['sha256:eee']['cmeta'] == '0.37.1'
    assert 'sha256:fff' not in rows and rows['sha256:ggg']['cmeta'] == '0.37.4'      # a layer is no image


def test_clean_old_removes_only_replaced_images(mod, capsys):
    engine = FakeEngine(IMAGES)
    r = category(mod, engine).clean_({'control': {}}, old=True)
    assert sorted(r['removed']) == ['sha256:bbb', 'sha256:ddd']
    assert ['rmi', 'cmeta/ubuntu:26.04-cmeta-0.37.3'] in engine.calls and ['rmi', 'sha256:ddd'] in engine.calls


def test_an_image_on_a_base_follows_its_base(mod):
    """The app's label cmeta.base_image_id is not the base image now: it is built again; the same base: skipped."""
    built = []

    class CM:
        def access(self, ii):
            built.append(ii['image'])
            return {'return': 0, 'image_id': 'sha256:new'}

    c = category(mod, FakeEngine([]))
    c.cm = CM()
    labels = {'cmeta/llama-cpp:ubuntu-26.04': {'cmeta.params_hash': 'h-app', 'cmeta.base_image_id': 'sha256:old'},
              'cmeta/ubuntu:26.04-cmeta-latest': {'cmeta.params_hash': 'h-base'}}
    ids = {'cmeta/ubuntu:26.04-cmeta-latest': 'sha256:now'}
    c._image_labels = lambda engine, image: labels.get(image)
    c._image_tags = lambda engine, image: (ids.get(image), [image])
    c._tag_cmeta = lambda ctx, spec: ('', '')
    base = {'engine': 'docker', 'image': 'cmeta/ubuntu:26.04-cmeta-latest', 'params_hash': 'h-base', 'labels': {},
            'files': {}, 'copy_files': [], 'build_secrets': {}, 'platform': ''}
    app = dict(base, image='cmeta/llama-cpp:ubuntu-26.04', params_hash='h-app', base_spec=base,
               base_image='cmeta/ubuntu:26.04-cmeta-latest')
    ctx = {'control': {'con': False}}

    assert c._build_spec(ctx, app)['return'] == 0 and built == ['cmeta/llama-cpp:ubuntu-26.04']

    built.clear()
    labels['cmeta/llama-cpp:ubuntu-26.04']['cmeta.base_image_id'] = 'sha256:now'
    assert c._build_spec(ctx, app).get('skipped') and built == []

    # an image built before the label existed is not built again by itself; --refresh_cmeta builds both
    del labels['cmeta/llama-cpp:ubuntu-26.04']['cmeta.base_image_id']
    assert c._build_spec(ctx, app).get('skipped') and built == []
    c._build_spec(ctx, app, refresh=True)
    assert built == ['cmeta/ubuntu:26.04-cmeta-latest', 'cmeta/llama-cpp:ubuntu-26.04']
