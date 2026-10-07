"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The identity of a program's build: the request that made it. A program's builds live in cache
entries of task compile-and-run-program that are found by their params, like every other task
entry: the program, the explicit choices of the request - the --use tree (tool names, versions,
variants), the compile and the with parameters - and the compute targets the run resolved. Two
requests that differ get two entries (task--program--<program>--<uid>), so a 12.9 and a 13.3
build of one program coexist and compare; the same request reuses its entry, whose build folders
(tmp, --target_tmp) and their stamps guard against a changed resolution. The entry's folder name
says nothing; its params do:

    params:
      program: test-nmm-nvcc-cuda
      program_uid: 0123456789abcdef
      request: {use: {nvcc: {version: '12.9'}}, compile: {static: true}, compute: [cuda]}
      request_digest: 3f9a2c1e8b7d6a54        the key the lookup matches (sha1 of the request, 16 hex)
      resolved: {nvcc: {name, version, path}, compiler-cpp: {...}}      written after a run

The plain request - no explicit choice, the cpu target - keeps the entry name task--program--<program>
that every program had before this scheme, and adopts such an entry when it exists without params,
so the builds made before stay where they are.
"""

import copy
import hashlib
import json
import os

TAGS = ['task', 'c36be4b9314a45e0', 'compile-and-run-program', '05437a1aae224270']
CACHED_RESULT = 'cmeta-task-cached-result.json'


###################################################################################################
def complete_restored_tools(global_ctx, cached_result = CACHED_RESULT):
    """
    A reused build replays its compile-time context into `global`: every tool with the features of
    the day it was built. A tool entry re-detected since ("cx tool setup <tool> --update": a model
    added to lib-litert-android, a flag the tool's desc gained) may hold feature keys the snapshot
    lacks; they are completed here from the entry's current cached result. A key the snapshot has
    keeps its value - the record of what the build used - and nothing is written. Returns
    {tool key: [feature keys added]}; {} when every restored tool was already complete.
    """
    added = {}
    for key, tool in list((global_ctx or {}).items()):
        if not isinstance(tool, dict):
            continue
        entry = tool.get('path_cmeta_cache')
        if not entry or not isinstance(entry, str):
            continue
        path = os.path.join(entry, cached_result)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding = 'utf-8') as f:
                current = json.load(f)
        except (OSError, ValueError):
            continue
        current_features = current.get('features') if isinstance(current, dict) else None
        if not isinstance(current_features, dict):
            continue
        features = tool.get('features')
        if not isinstance(features, dict):
            features = {}
            tool['features'] = features
        new = [k for k in current_features if k not in features]
        for k in new:
            features[k] = copy.deepcopy(current_features[k])
        if new:
            added[key] = new
    return added
PLAIN = {'compute': ['cpu']}

# Control switches a --use entry may carry that are not part of a request's identity
USE_CONTROL = {'update', 'clean', 'new', 'path', 'cache_repo', 'cache_name', 'skip', 'con', 'quiet', 'verbose', 'install', 'ask'}
TRUE_WORDS, FALSE_WORDS = ('true', 'yes', 'on'), ('false', 'no', 'off')


###################################################################################################
def normalize(value, drop = ()):
    """
    A request value as a comparable, JSON-ready value: dicts with sorted keys and no empty members
    (the keys in `drop` left out), numbers as text (a version given as 13 or 3.12 means the text),
    the boolean words as booleans. None for nothing.
    """
    if isinstance(value, dict):
        out = {}
        for k in sorted(value, key = str):
            if str(k) in drop:
                continue
            v = normalize(value[k])
            if v is not None and v != {} and v != [] and v != '':
                out[str(k)] = v
        return out
    if isinstance(value, (list, tuple)):
        return [v for v in (normalize(x) for x in value) if v is not None and v != '']
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    if text.lower() in TRUE_WORDS:
        return True
    if text.lower() in FALSE_WORDS:
        return False
    return text


def request_identity(request_params, request_use, compute):
    """
    {use, compile, with, compute}: the explicit choices of the request (the --use tree, --compile.*,
    --with.*, as given before the program's defaults joined) and the compute targets the run resolved
    (sorted; cpu when none). The plain request is {'compute': ['cpu']}.
    """
    identity = {}
    use = {}
    for key, spec in (request_use or {}).items():
        v = normalize(spec, drop = USE_CONTROL) if isinstance(spec, dict) else normalize(spec)
        if v is not None and v != {} and v != '':
            use[str(key)] = v
    if use:
        identity['use'] = dict(sorted(use.items()))
    params = request_params or {}
    for key in ('compile', 'with'):
        if isinstance(params.get(key), dict):
            v = normalize(params[key])
            if v:
                identity[key] = v
    targets = sorted({str(c).strip().lower() for c in (compute or []) if str(c).strip()})
    identity['compute'] = targets or ['cpu']
    return identity


def digest(identity):
    """The key of a request: the first 16 hex digits of the sha1 of its canonical JSON."""
    text = json.dumps(identity or {}, sort_keys = True, separators = (',', ':'), ensure_ascii = True)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]


def describe(identity):
    """One line: 'nvcc 12.9, compiler-c clang, static, cuda'; 'plain (cpu, no explicit choice)' for the plain request."""
    if not identity or identity == PLAIN:
        return 'plain (cpu, no explicit choice)'
    parts = []
    for key, spec in (identity.get('use') or {}).items():
        if isinstance(spec, dict):
            words = [key] + [str(spec[k]) for k in ('name', 'version') if spec.get(k)]
            words += [f'{k}={v}' for k, v in spec.items() if k not in ('name', 'version')]
            parts.append(' '.join(words))
        else:
            parts.append(f'{key} {spec}')
    for key in ('compile', 'with'):
        for k, v in (identity.get(key) or {}).items():
            parts.append(k if v is True else f'{k}={v}')
    parts.append(','.join(identity.get('compute') or ['cpu']))
    return ', '.join(parts)


def entry_params(alias, uid, identity):
    """The params of a build entry: the program, the request and its digest."""
    return {'program': alias or uid, 'program_uid': uid, 'request': identity, 'request_digest': digest(identity)}


def plain_name(alias):
    return f'task--program--{alias}'


###################################################################################################
def _entry(a):
    parts = a.get('cmeta_ref_parts') or {}
    params = (a.get('cmeta') or {}).get('params') or {}
    return {'path': a['path'], 'alias': parts.get('artifact_alias'), 'uid': parts.get('artifact_uid'),
            'params': params if params.get('request_digest') else None}


def find_entries(cm, cache_category, alias, uid = None, identity = None):
    """
    The build entries of a program - every request, or the one request `identity` - as
    [{'path', 'alias', 'uid', 'params'}], in index order; an entry made before this scheme (the plain
    name, no request in its params) comes last with params None. Read only.
    """
    program = alias or uid
    match = {'params': {'program': program}}
    if identity is not None:
        match['params']['request_digest'] = digest(identity)
    r = cm.access({'category': cache_category, 'command': 'find', 'tags': TAGS, 'match': match, 'con': False})
    if r['return'] > 0 and r['return'] != 16:
        return r
    found = [_entry(a) for a in r.get('artifacts', [])] if r['return'] == 0 else []
    found = [e for e in found if e['params'] is not None]
    r = cm.access({'category': cache_category, 'command': 'find', 'arg1': plain_name(program), 'tags': TAGS, 'con': False})
    if r['return'] > 0 and r['return'] != 16:
        return r
    for a in (r.get('artifacts', []) if r['return'] == 0 else []):
        e = _entry(a)
        if e['params'] is None and e['path'] not in [f['path'] for f in found]:
            found.append(e)
    return {'return': 0, 'entries': found}


def find_or_create_entry(cm, cache_category, alias, uid, identity):
    """
    The build entry of this request: the one whose params carry the request's digest; for the plain
    request, an entry of the plain name without params (made before this scheme) is adopted and gets
    the params; else a new entry - the plain name for the plain request, task--program--<program>--<uid>
    otherwise. Returns {'return': 0, 'path', 'alias', 'uid', 'params', 'created', 'adopted'}.
    """
    r = find_entries(cm, cache_category, alias, uid, identity)
    if r['return'] > 0:
        return r
    params = entry_params(alias, uid, identity)
    matching = [e for e in r['entries'] if e['params'] is not None]
    if matching:
        e = matching[0]
        return {'return': 0, 'path': e['path'], 'alias': e['alias'], 'uid': e['uid'], 'params': e['params'],
                'created': False, 'adopted': False}
    legacy = [e for e in r['entries'] if e['params'] is None]
    plain = identity == PLAIN
    if plain and legacy:
        e = legacy[0]
        rr = cm.access({'category': cache_category, 'command': 'update', 'arg1': f"{e['alias']},{e['uid']}" if e['alias'] else e['uid'],
                        'meta': {'params': params}, 'con': False})
        if rr['return'] > 0:
            return rr
        return {'return': 0, 'path': e['path'], 'alias': e['alias'], 'uid': e['uid'], 'params': params,
                'created': False, 'adopted': True}
    if plain:
        name = plain_name(alias or uid)
    else:
        new_uid = cm.utils.generate_cmeta_uid()
        name = f'{plain_name(alias or uid)}--{new_uid},{new_uid}'
    rr = cm.access({'category': cache_category, 'command': 'create', 'arg1': name, 'tags': TAGS, 'meta': {'params': params}, 'con': False})
    if rr['return'] > 0:
        return rr
    meta = rr.get('meta') or {}
    entry_uid = meta.get('artifact') or (name.split(',')[-1] if ',' in name else None)
    return {'return': 0, 'path': rr['path'], 'alias': name.split(',')[0], 'uid': entry_uid, 'params': params,
            'created': True, 'adopted': False}


def resolved_of(record_resolved):
    """The resolved toolchain for the entry's params: name, version and path of every tool of the run."""
    out = {}
    for key, v in (record_resolved or {}).items():
        if isinstance(v, dict):
            item = {k: v[k] for k in ('name', 'version', 'path') if v.get(k)}
            if item:
                out[str(key)] = item
    return out


def update_entry(cm, cache_category, entry, resolved):
    """Writes the resolved toolchain of a run into the entry's params (deep-merged by the cache category)."""
    if not entry or not (entry.get('uid') or entry.get('alias')):
        return {'return': 0}
    name = f"{entry['alias']},{entry['uid']}" if entry.get('alias') and entry.get('uid') else (entry.get('uid') or entry.get('alias'))
    return cm.access({'category': cache_category, 'command': 'update', 'arg1': name,
                      'meta': {'params': {'resolved': resolved_of(resolved)}}, 'con': False})
