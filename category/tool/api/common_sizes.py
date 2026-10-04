"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Disk sizes of tools, for task/setup: how much a tool's install or build needs, read from the tool's
_desc_sizes.yaml (never from _desc.yaml, which is read for many other purposes), the free space of the
folder that receives it, what a finished setup took (learning), and the rules to suggest from that.

_desc_sizes.yaml: a list of rules, the first match wins; sizes in GB (floats); the keys of "if" are
optional and a missing key matches anything:

    sizes:
      - if: {method: install, os: linux, version: '>=22'}
        peak: 13          # during the setup: download + unpacked (+ build tree)
        kept: 11          # what stays in the cache afterwards
      - if: {method: install}
        peak: 6
      - if: {method: build}
        peak: 40
        kept: 3
      - peak: 2           # anything else

The keys of "if": version (fuzzy, as --version: cMeta's version matching), os (windows, linux, darwin),
arch (amd64, arm64), method (install, build), compute, and any key of the request's "with" (with.build,
with.static, ...). Matching is cMeta's matches_query, so there is no syntax of its own.
"""

import json
import math
import os
import shutil

SIZES_FILE = '_desc_sizes.yaml'
GB = 1024 ** 3


def load_sizes(tool_path, read_yaml = None):
    """The rules of the tool's _desc_sizes.yaml ([] without the file). read_yaml(path) -> dict."""
    path = os.path.join(tool_path, SIZES_FILE)
    if not os.path.isfile(path):
        return []
    if read_yaml is None:
        import yaml
        with open(path, encoding = 'utf-8') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = read_yaml(path) or {}
    return list(data.get('sizes') or [])


def request_facts(version = None, os_name = None, arch = None, method = None, compute = None, with_ = None):
    """The facts of a request that the rules match against (None values are left out)."""
    facts = {'version': version, 'os': os_name, 'arch': arch, 'method': method, 'compute': compute}
    facts = {k: v for k, v in facts.items() if v not in (None, '')}
    if with_:
        facts['with'] = dict(with_)
    return facts


def select_rule(rules, facts, matches_query, match_version_func = None):
    """
    The first rule whose "if" the facts satisfy, or None. A rule without "if" matches anything. The
    version condition is a fuzzy version (">=22", "3.12", "==1.2.3") applied to the request's version;
    a request without a version matches a rule without a version condition only.
    """
    for rule in rules or []:
        cond = dict(rule.get('if') or {})
        version_cond = cond.pop('version', None)
        if version_cond is not None:
            if 'version' not in facts:
                continue
            if not matches_query({'version': facts['version']}, {'@version': str(version_cond)},
                                 match_version_func = match_version_func, match_empty_version = False):
                continue
        # compute may be a list in the request: a scalar condition is "in", a list is "subset"
        if 'compute' in cond and isinstance(facts.get('compute'), list) and not isinstance(cond['compute'], list):
            if cond['compute'] not in facts['compute']:
                continue
            cond.pop('compute')
        if cond and not matches_query(facts, cond, match_version_func = match_version_func, match_empty_version = False):
            continue
        return rule
    return None


def free_gb(path):
    """Free space of the volume that holds the path (the nearest existing parent), in GB, or None."""
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return shutil.disk_usage(p).free / GB
    except OSError:
        return None


def folder_gb(path):
    """The size of a folder (files only, links not followed), in GB; 0 for a missing folder."""
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total / GB


def check_space(needed_gb, path, floor_gb = None, free = None):
    """
    Whether the folder's volume has room: (ok, free_gb, needed_gb). needed_gb is the rule's peak (None
    without a rule); floor_gb is the global minimum of free space (None when off). Without both, ok.
    """
    required = max([x for x in (needed_gb, floor_gb) if x is not None], default = None)
    if required is None:
        return True, None, None
    if free is None:
        free = free_gb(path)
    if free is None:
        return True, None, required
    return free >= required, free, required


def shortage_message(tool, version, method, os_name, needed_gb, free, path, rule_based):
    """The message of a short-of-space install or build."""
    what = f'{tool}' + (f' {version}' if version else '') + f' ({method}, {os_name})'
    need = (f'needs about {needed_gb:g} GB during the setup' if rule_based
            else f'needs at least {needed_gb:g} GB free (the configured minimum)')
    return (f'{what} {need}; {free:.1f} GB are free in {path}. '
            f'Free space, give --path=<folder on another disk>, or --skip_size_check.')


###################################################################################################
# Learning: what finished setups took, and the rules to suggest

def records_from_cache(cache_entries):
    """
    The size records of a tool's cache entries: [{version, os, arch, method, with, kept_gb, peak_gb}]
    from each entry's _cmeta.json params and cmeta-task-cached-result.json _impact (disk_gb, peak_gb,
    disk_method, disk_os, disk_arch), for entries that recorded a size.
    """
    out = []
    for entry in cache_entries:
        try:
            meta = json.load(open(os.path.join(entry, '_cmeta.json'), encoding = 'utf-8'))
            result = json.load(open(os.path.join(entry, 'cmeta-task-cached-result.json'), encoding = 'utf-8'))
        except (OSError, ValueError):
            continue
        impact = result.get('_impact') or {}
        if impact.get('disk_gb') is None:
            continue
        params = meta.get('params') or {}
        out.append({'entry': os.path.basename(entry), 'version': params.get('version'),
                    'os': impact.get('disk_os'), 'arch': impact.get('disk_arch'), 'method': impact.get('disk_method'),
                    'with': params.get('with') or {}, 'kept_gb': impact['disk_gb'], 'peak_gb': impact.get('peak_gb')})
    return out


def round_up_gb(x, margin = 0.2):
    """A size with a margin, rounded up to a readable number (0.1 GB below 1, 0.5 below 10, else 1)."""
    x = x * (1 + margin)
    step = 0.1 if x < 1 else (0.5 if x < 10 else 1)
    return math.ceil(x / step - 1e-9) * step


def suggest_rules(records, margin = 0.2):
    """
    Rules to paste into _desc_sizes.yaml from the records: one rule per (method, os, arch, major
    version) with the largest sizes seen (peak from peak_gb, else from kept), plus a default rule.
    """
    groups = {}
    for r in records:
        major = str(r['version']).split('.')[0] if r.get('version') else None
        key = (r.get('method'), r.get('os'), r.get('arch'), major)
        g = groups.setdefault(key, {'kept': 0, 'peak': 0})
        g['kept'] = max(g['kept'], r.get('kept_gb') or 0)
        g['peak'] = max(g['peak'], r.get('peak_gb') or r.get('kept_gb') or 0)
    rules = []
    for (method, os_name, arch, major), g in sorted(groups.items(), key = lambda kv: -kv[1]['peak']):
        cond = {k: v for k, v in (('method', method), ('os', os_name), ('arch', arch)) if v}
        if major:
            cond['version'] = f'>={major},<{int(major) + 1}' if major.isdigit() else major
        rules.append({'if': cond, 'peak': round_up_gb(g['peak'], margin), 'kept': round_up_gb(g['kept'], margin)})
    if rules:
        rules.append({'peak': max(r['peak'] for r in rules)})
    return rules


def rules_to_yaml(rules):
    """The rules as the text of a _desc_sizes.yaml."""
    lines = ['sizes:']
    for r in rules:
        cond = r.get('if') or {}
        if cond:
            items = ', '.join(f"{k}: '{v}'" if k == 'version' else f'{k}: {v}' for k, v in cond.items())
            lines.append(f'  - if: {{{items}}}')
            lines.append(f"    peak: {r['peak']:g}")
            if r.get('kept') is not None:
                lines.append(f"    kept: {r['kept']:g}")
        else:
            lines.append(f"  - peak: {r['peak']:g}")
    return '\n'.join(lines) + '\n'
