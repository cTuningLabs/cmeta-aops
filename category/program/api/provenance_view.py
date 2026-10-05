"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The view of a program run's provenance record (`provenance.json`, format 1, written by the program
driver into the build folder): the requested / resolved / loaded table with the checks, the summary
of every build folder of a program, the differences between two records, and the options that
reproduce a run. Pure functions over the record's dict, so the command in v1.py stays thin and the
view can be tested without a cMeta instance. Every key is optional: an older or partial record
renders what it has.
"""

import os
import json

RECORD_FILENAME = 'provenance.json'

# Keys of the run context that are not tools (never a table row)
NOT_A_TOOL = {'host', 'runner', 'init', 'target', 'cmeta', 'program', 'session'}

# A path longer than this is shortened in the middle for the table
PATH_WIDTH = 46


###################################################################################################
def load_record(path):
    """The record at `path` (a provenance.json), or {'return': >0, 'error': ...}."""
    try:
        with open(path, 'r', encoding = 'utf-8') as f:
            record = json.load(f)
    except FileNotFoundError:
        return {'return': 16, 'error': f'no provenance record at {path}'}
    except Exception as e:
        return {'return': 1, 'error': f'cannot read the provenance record {path}: {e}'}
    if not isinstance(record, dict):
        return {'return': 1, 'error': f'the provenance record {path} is not a JSON object'}
    return {'return': 0, 'record': record, 'path': path}


def find_records(entry_path):
    """The build folders (tmp, tmp-*) of a program's cache entry that hold a record: [(target_tmp, path)], sorted."""
    found = []
    if entry_path and os.path.isdir(entry_path):
        for name in sorted(os.listdir(entry_path)):
            if name.startswith('tmp'):
                path = os.path.join(entry_path, name, RECORD_FILENAME)
                if os.path.isfile(path):
                    found.append((name, path))
    return found


def missing_message(program, folder, target_tmp = None):
    """What to say when a build folder has no record."""
    where = f'the build folder {folder}' if folder else f'the build folder "{target_tmp or "tmp"}" of program "{program}"'
    return (f'no provenance record in {where}: run the program first - '
            f'"cx program run {program}" writes {RECORD_FILENAME} there (--provenance=on is the default); '
            f'"cx program provenance {program} --all" lists the build folders that have one')


###################################################################################################
def short_path(path, width = PATH_WIDTH):
    """A path shortened in the middle to `width` characters, the end kept whole."""
    if not path:
        return ''
    path = str(path)
    if len(path) <= width:
        return path
    keep_end = width - 10
    return path[:7] + '...' + path[-keep_end:]


def _version_of(entry):
    if not isinstance(entry, dict):
        return ''
    v = entry.get('version')
    return str(v) if v not in (None, '') else ''


def _basename(path):
    return os.path.basename(str(path).rstrip('/\\')) if path else ''


def tool_rows(record):
    """
    One row per tool of the run: the requested version or name, the resolved version/name and path,
    the loaded libraries attributed to the tool, and the checks that concern it (a check with a
    `tool` key, or whose rule or detail names the tool).

    Returns:
        list of dicts: {'tool', 'requested', 'resolved', 'path', 'loaded': [names], 'checks': [checks]}
    """
    resolved = record.get('resolved') or {}
    requested_use = (record.get('requested') or {}).get('use') or {}
    loaded = (record.get('loaded') or {}).get('libraries') or []
    checks = record.get('checks') or []

    keys = [k for k in resolved if k not in NOT_A_TOOL]
    for k in requested_use:
        if k not in keys and k not in NOT_A_TOOL:
            keys.append(k)

    rows = []
    for key in sorted(keys):
        entry = resolved.get(key) or {}
        req = requested_use.get(key) or {}
        req_text = ''
        if isinstance(req, dict):
            parts = []
            if req.get('name'):
                parts.append(str(req['name']))
            if req.get('version') not in (None, ''):
                parts.append(str(req['version']))
            for k2, v2 in sorted(req.items()):
                if k2 not in ('name', 'version'):
                    parts.append(f'{k2}={v2}')
            req_text = ' '.join(parts)
        elif req not in (None, ''):
            req_text = str(req)

        res_parts = []
        name = entry.get('name') if isinstance(entry, dict) else None
        if name and name != key:
            res_parts.append(str(name))
        version = _version_of(entry)
        if version:
            res_parts.append(version)
        resolved_text = ' '.join(res_parts) if res_parts else ('resolved' if entry else '')

        path = entry.get('path') if isinstance(entry, dict) else None
        if not path and isinstance(entry, dict):
            path = entry.get('entry')

        # the libraries loaded from the tool's entry; a compiler's own runtime (libgomp, vcomp140) is marked
        libs = [_basename(l.get('path') or l.get('name')) + (' (runtime)' if l.get('role') == 'runtime' else '')
                for l in loaded if isinstance(l, dict) and l.get('tool') == key]

        own_checks = []
        for c in checks:
            if not isinstance(c, dict):
                continue
            if c.get('tool') == key or (c.get('tool') is None and key in (str(c.get('rule', '')) + ' ' + str(c.get('detail', '')))):
                own_checks.append(c)

        rows.append({'tool': key, 'requested': req_text or '(auto)', 'resolved': resolved_text,
                     'path': path or '', 'loaded': libs, 'checks': own_checks})
    return rows


def check_mark(check):
    """ok / FAIL / warn / info for a check."""
    if not isinstance(check, dict):
        return '?'
    if check.get('ok', False):
        return 'ok'
    level = str(check.get('level', 'error')).lower()
    return 'FAIL' if level == 'error' else ('warn' if level == 'warning' else 'info')


def summary_counts(record):
    """(ok, failed errors, warnings) over the checks."""
    ok = fail = warn = 0
    for c in record.get('checks') or []:
        mark = check_mark(c)
        if mark == 'ok':
            ok += 1
        elif mark == 'FAIL':
            fail += 1
        elif mark == 'warn':
            warn += 1
    return ok, fail, warn


def render(record, program = None, width = PATH_WIDTH):
    """The full text of one record: header, the tool table, the checks, the other libraries."""
    prog = record.get('program') or {}
    alias = prog.get('alias') or program or '?'
    target_tmp = prog.get('target_tmp') or 'tmp'
    host = record.get('host') or {}
    compute = record.get('compute')
    compute_text = ','.join(str(c) for c in compute) if isinstance(compute, list) else (str(compute) if compute else '?')
    binary = (record.get('build') or {}).get('binary') or {}
    loaded = record.get('loaded') or {}
    ok = record.get('ok')
    n_ok, n_fail, n_warn = summary_counts(record)

    lines = []
    lines.append(f'Provenance of program {alias} ({target_tmp})   created {record.get("created") or "?"}')
    bin_text = ''
    if binary:
        bin_text = f'   binary: {str(binary.get("format") or "?").upper()} {binary.get("arch") or ""}, ' + \
                   ('static' if binary.get('static') else 'dynamic')
    status = 'ok' if ok is True else ('FAILED' if ok is False else '?')
    lines.append(f'compute: {compute_text}   host: {host.get("uname") or "?"} {host.get("uarch") or ""}{bin_text}   '
                 f'result: {status} ({n_ok} ok, {n_fail} failed, {n_warn} warnings)')
    if loaded:
        method = loaded.get('method') or '?'
        libs = loaded.get('libraries') or []
        extra = f', {loaded["processes"]} processes' if loaded.get('processes') else ''
        lines.append(f'loaded: {len(libs)} libraries by {"the loader log" if method == "loader-log" else "resolution of the binary" if method == "resolved" else method}{extra}')
    lines.append('')

    rows = tool_rows(record)
    if rows:
        w_tool = max([len(r['tool']) for r in rows] + [4])
        w_req = max([len(r['requested']) for r in rows] + [9])
        w_res = max([len(r['resolved']) for r in rows] + [8])
        lines.append(f'  {"tool":{w_tool}}  {"requested":{w_req}}  {"resolved":{w_res}}  loaded')
        for r in rows:
            marks = [check_mark(c) for c in r['checks']]
            mark = ''
            if marks:
                mark = '  [' + ('FAIL' if 'FAIL' in marks else 'warn' if 'warn' in marks else 'ok') + ']'
            loaded_text = ', '.join(r['loaded']) if r['loaded'] else '-'
            lines.append(f'  {r["tool"]:{w_tool}}  {r["requested"]:{w_req}}  {r["resolved"]:{w_res}}  {loaded_text}{mark}')
            if r['path']:
                lines.append(f'  {"":{w_tool}}  {"":{w_req}}  {short_path(r["path"], width)}')
        lines.append('')
    else:
        lines.append('  (no tools recorded)')
        lines.append('')

    checks = record.get('checks') or []
    lines.append('checks:')
    if checks:
        for c in checks:
            if not isinstance(c, dict):
                continue
            level = str(c.get('level') or 'error')
            detail = c.get('detail')
            text = str(c.get('rule') or '?') + (f': {detail}' if detail else '')
            mark = check_mark(c)
            lines.append(f'  {mark:4}  {text}' + (f'  ({level})' if mark != 'ok' else ''))
    else:
        lines.append('  (none)')

    libs = loaded.get('libraries') or []
    others = [l for l in libs if isinstance(l, dict) and not l.get('tool')]
    if others:
        system = [l for l in others if l.get('system')]
        rest = [l for l in others if not l.get('system')]
        lines.append('')
        parts = []
        if system:
            names = sorted(set(_basename(l.get('path') or l.get('name')) for l in system))
            shown = ', '.join(names[:6]) + (', ...' if len(names) > 6 else '')
            parts.append(f'{len(system)} system ({shown})')
        for l in rest:
            name = _basename(l.get('path') or l.get('name'))
            folder = os.path.dirname(str(l.get('path') or ''))
            parts.append(f'{name} ({short_path(folder, width)})' if folder else name)
        lines.append('other libraries: ' + '; '.join(parts))

    missing = binary.get('missing') or []
    if missing:
        lines.append('not found by the loader rules: ' + ', '.join(str(m) for m in missing))

    return '\n'.join(lines)


def summary_line(target_tmp, record, width = 14):
    """One line for `--all`: folder, date, compute, host, result, checks."""
    compute = record.get('compute')
    compute_text = ','.join(str(c) for c in compute) if isinstance(compute, list) else (str(compute) if compute else '?')
    host = record.get('host') or {}
    created = str(record.get('created') or '?')[:16]
    ok = record.get('ok')
    status = 'ok' if ok is True else ('FAILED' if ok is False else '?')
    n_ok, n_fail, n_warn = summary_counts(record)
    return (f'  {target_tmp:{width}}  {created:16}  {compute_text:10}  {host.get("uname") or "?"}/{host.get("uarch") or "?"}'
            f'  {status:6}  checks: {n_ok} ok, {n_fail} failed, {n_warn} warnings')


###################################################################################################
def _leaves(d, prefix = ''):
    """{dotted key: scalar} of a nested dict (lists as their JSON text)."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f'{prefix}.{k}' if prefix else str(k)
            if isinstance(v, dict):
                out.update(_leaves(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, sort_keys = True)
            else:
                out[key] = v
    return out


def diff(a, b):
    """
    The differences between two records, by section.

    Returns:
        dict: {'requested': [(key, a, b)], 'resolved': [(tool, field, a, b)], 'loaded': {'added': [...],
               'removed': [...]}, 'checks': [(rule, a_mark, b_mark)], 'context': [(key, a, b)]}
    """
    out = {'requested': [], 'resolved': [], 'loaded': {'added': [], 'removed': []}, 'checks': [], 'context': []}

    la, lb = _leaves(a.get('requested') or {}), _leaves(b.get('requested') or {})
    for k in sorted(set(la) | set(lb)):
        if la.get(k) != lb.get(k):
            out['requested'].append((k, la.get(k), lb.get(k)))

    ra, rb = a.get('resolved') or {}, b.get('resolved') or {}
    for tool in sorted(set(ra) | set(rb)):
        ea, eb = ra.get(tool) or {}, rb.get(tool) or {}
        if not ea or not eb:
            out['resolved'].append((tool, 'present', bool(ea), bool(eb)))
            continue
        for field in ('name', 'version', 'path', 'entry'):
            if ea.get(field) != eb.get(field):
                out['resolved'].append((tool, field, ea.get(field), eb.get(field)))

    def lib_keys(rec):
        libs = (rec.get('loaded') or {}).get('libraries') or []
        return {str(l.get('path') or l.get('name')) for l in libs if isinstance(l, dict)}
    ka, kb = lib_keys(a), lib_keys(b)
    out['loaded']['added'] = sorted(kb - ka)
    out['loaded']['removed'] = sorted(ka - kb)

    def check_marks(rec):
        return {str(c.get('rule')): check_mark(c) for c in (rec.get('checks') or []) if isinstance(c, dict)}
    ca, cb = check_marks(a), check_marks(b)
    for rule in sorted(set(ca) | set(cb)):
        if ca.get(rule) != cb.get(rule):
            out['checks'].append((rule, ca.get(rule), cb.get(rule)))

    for key in ('compute', 'host', 'build.binary.static', 'build.binary.format', 'loaded.method'):
        va, vb = a, b
        for part in key.split('.'):
            va = va.get(part) if isinstance(va, dict) else None
            vb = vb.get(part) if isinstance(vb, dict) else None
        if va != vb:
            out['context'].append((key, va, vb))
    return out


def diff_is_empty(d):
    return not (d['requested'] or d['resolved'] or d['loaded']['added'] or d['loaded']['removed'] or d['checks'] or d['context'])


def render_diff(d, label_a = 'A', label_b = 'B'):
    """The text of a diff()."""
    lines = [f'Differences: {label_a} -> {label_b}']
    if diff_is_empty(d):
        lines.append('  none')
        return '\n'.join(lines)
    if d['context']:
        lines.append('context:')
        for key, va, vb in d['context']:
            lines.append(f'  {key}: {va} -> {vb}')
    if d['requested']:
        lines.append('requested:')
        for key, va, vb in d['requested']:
            lines.append(f'  {key}: {va if va is not None else "(none)"} -> {vb if vb is not None else "(none)"}')
    if d['resolved']:
        lines.append('resolved:')
        for tool, field, va, vb in d['resolved']:
            if field == 'present':
                lines.append(f'  {tool}: {"present" if va else "absent"} -> {"present" if vb else "absent"}')
            else:
                lines.append(f'  {tool} {field}: {va if va is not None else "(none)"} -> {vb if vb is not None else "(none)"}')
    if d['loaded']['added'] or d['loaded']['removed']:
        lines.append('loaded libraries:')
        for p in d['loaded']['removed']:
            lines.append(f'  - {p}')
        for p in d['loaded']['added']:
            lines.append(f'  + {p}')
    if d['checks']:
        lines.append('checks:')
        for rule, ma, mb in d['checks']:
            lines.append(f'  {rule}: {ma or "(none)"} -> {mb or "(none)"}')
    return '\n'.join(lines)


###################################################################################################
def _flag_value(value):
    if isinstance(value, bool):
        return None if value else 'False'
    if isinstance(value, (list, tuple)):
        return ','.join(str(v) for v in value)
    return str(value)


def _flags_of(prefix, d):
    """--<prefix>.<key>=<value> for a flat or nested dict (a True boolean becomes the bare flag)."""
    flags = []
    for key, value in sorted((d or {}).items()):
        if isinstance(value, dict):
            flags += _flags_of(f'{prefix}.{key}', value)
            continue
        if value is None:
            continue
        v = _flag_value(value)
        flags.append(f'--{prefix}.{key}' if v is None else f'--{prefix}.{key}={v}')
    return flags


def as_flags(record):
    """
    The options that reproduce the resolved configuration of a run, one line:
    the chosen compiler tools (`--use.compiler-<lang>.name=<tool>`), the version of every resolved
    tool (`--use.<tool>.version=<version>`), the explicit compile and with params of the request,
    `--compute=<list>` and `--target_tmp=<name>`.
    """
    resolved = record.get('resolved') or {}
    requested = record.get('requested') or {}
    flags = []

    for key in sorted(resolved):
        entry = resolved.get(key) or {}
        if key.startswith('compiler-') and isinstance(entry, dict):
            name = entry.get('name') or (entry.get('tool') or {}).get('name') if isinstance(entry.get('tool'), dict) else entry.get('name')
            if name:
                flags.append(f'--use.{key}.name={name}')

    for key in sorted(resolved):
        if key in NOT_A_TOOL or key.startswith('compiler-'):
            continue
        version = _version_of(resolved.get(key))
        if version:
            flags.append(f'--use.{key}.version={version}')

    flags += _flags_of('compile', requested.get('compile'))
    flags += _flags_of('with', requested.get('with'))

    compute = record.get('compute') or requested.get('compute')
    if compute:
        flags.append('--compute=' + (','.join(str(c) for c in compute) if isinstance(compute, list) else str(compute)))

    target_tmp = (record.get('program') or {}).get('target_tmp')
    if target_tmp:
        flags.append(f'--target_tmp={target_tmp}')

    return ' '.join(flags)
