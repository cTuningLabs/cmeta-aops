"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Install a tool from a pinned upstream release (install ladder tier 1), shared by the tools
whose api_v1.py only declares where their release assets live:

    from tool_c393ba5c6fa14f66.api.common_release import install_release

    SPEC = {'name': 'helm', 'default_version': '4.3.0',
            'url': 'https://get.helm.sh/helm-v{version}-{os}-{arch}.{ext}',
            'ext': {'windows': 'zip', '*': 'tar.gz'},
            'checksum': {'file': '{url}.sha256sum'}}

    def install(self, ctx, params, cmd=None, *misc):
        return install_release(self, ctx, params, cmd, SPEC)

What it does, with the Python standard library only (no tar/unzip binaries needed):
  1. picks the asset for this OS and CPU from the templates ({version}, {os}, {arch}, {ext}, {exe});
  2. downloads it with the download-file task (so proxies, mirrors and retries behave as for every other tool);
  3. verifies its SHA-256 when upstream publishes one - a "<hash>  <file>" list, a per-asset file, or
     yq's multi-hash table - and fails on a mismatch;
  4. unpacks one member of a .zip/.tar.gz (or takes a bare binary as is) and names it "<name>[.exe]";
  5. does the same for the "extra" binaries some tools ship next to the main one (kwok for kwokctl).

A spec may leave an OS or CPU out; install_release then returns 16 with the declarative install_cmd,
so setup can fall back to a package manager where the tool declares one, or print install_help_text.

SPEC keys:
  name             binary name without extension (also the file name it is saved as)
  default_version  pinned version when the user asks for none
  url              asset URL template
  os / arch        cMeta uname / uarch -> the upstream spelling (default: the same word)
  ext              archive extension per OS ('*' = any other OS); omit for a bare binary
  exe              suffix of the binary per OS inside the asset/archive (default '.exe' on Windows)
  member           path of the binary inside the archive (template); default: the first file named <name><exe>
  checksum         {'list': <url>}          a "<sha256>  <asset>" list (checksums.txt, SHA256SUMS, ...)
                   {'file': <url>}          a per-asset file holding "<sha256>[  <asset>]"
                   {'yq': <url>, 'order': <url>}   yq's table of several hashes per line
                   omitted: no checksum published upstream (HTTPS only)
  version_tag      tag/version spelling in the URL if it differs, e.g. 'kustomize/v{version}'
  unsupported      [[uname, uarch], ...] pairs upstream publishes nothing for (e.g. ['windows', 'arm64'])
  extra            list of {'name', 'url', 'checksum', 'member', 'ext'} fetched into the same folder
"""

import hashlib
import os
import stat
import tarfile
import zipfile


def _pick(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return mapping if mapping is not None else default
    if key in mapping:
        return mapping[key]
    return mapping.get('*', default)


def _download(tool, ctx, params, url, directory, filename):
    c = params.get('control', {})
    path = os.path.join(os.getcwd(), directory, filename)
    r = tool.cm.access({'category': 'task,c36be4b9314a45e0',
                        'command': 'run',
                        'arg1': 'download-file,03fed13e2e0447cf',
                        'ctx': ctx,
                        'url': url,
                        'directory': directory,
                        'filename': filename,
                        'env': params.get('env'),
                        'timeout': params.get('timeout'),
                        'con': c.get('con', False),
                        'quiet': c.get('quiet', False),
                        'verbose': c.get('verbose', False),
                        'unzip': False,
                        'check_file': path})
    if r['return'] > 0:
        return r
    return {'return': 0, 'path': path}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(tool, ctx, params, checksum, v, asset, directory):
    """The SHA-256 upstream publishes for `asset`, or None when it publishes none."""
    if not checksum:
        return {'return': 0, 'sha256': None}
    kind = 'list' if 'list' in checksum else 'file' if 'file' in checksum else 'yq' if 'yq' in checksum else None
    url = checksum[kind].format(**v)
    # The version is part of the file name: download-file keeps a file that already exists, and
    # "cx tool setup <tool> --upgrade" installs the newer release into the same cache entry, where
    # the checksums of the old release would otherwise be reused and fail every download
    r = _download(tool, ctx, params, url, directory, f'_sums_{v["version"]}_' + os.path.basename(url.split('?')[0]))
    if r['return'] > 0:
        return r
    with open(r['path'], encoding='utf-8', errors='replace') as f:
        lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    if kind == 'file':
        first = lines[0].split() if lines else []
        return {'return': 0, 'sha256': first[0].lower() if first else ''}
    if kind == 'list':
        for x in lines:
            parts = x.split()
            if len(parts) >= 2 and parts[-1].lstrip('*').split('/')[-1] == asset:
                return {'return': 0, 'sha256': parts[0].lower()}
        return tool.cm.error(f'{asset} is not listed in {url}')
    # yq: "checksums" has one line per asset with several hashes, "checksums_hashes_order" names them
    ro = _download(tool, ctx, params, checksum['order'].format(**v), directory, f'_sums_{v["version"]}_order')
    if ro['return'] > 0:
        return ro
    with open(ro['path'], encoding='utf-8', errors='replace') as f:
        order = [x.strip() for x in f.read().splitlines() if x.strip()]
    if 'SHA-256' not in order:
        return tool.cm.error(f'SHA-256 is not in {checksum["order"]}')
    col = order.index('SHA-256') + 1
    for x in lines:
        parts = x.split()
        if parts and parts[0] == asset and len(parts) > col:
            return {'return': 0, 'sha256': parts[col].lower()}
    return tool.cm.error(f'{asset} is not listed in {url}')


def _unpack(archive, member, name, dest):
    """Extract one file of a .zip/.tar.gz to dest; member = exact path or None to search by name."""
    def match(n):
        return (member and n.replace('\\', '/').lstrip('./') == member) or \
               (not member and os.path.basename(n.replace('\\', '/')) == name)
    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not info.is_dir() and match(info.filename):
                    with z.open(info) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
                    return True
    else:
        with tarfile.open(archive, 'r:*') as t:
            for m in t.getmembers():
                if m.isfile() and match(m.name):
                    with t.extractfile(m) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
                    return True
    return False


def _fetch_one(tool, ctx, params, item, v, directory, con, space):
    """Download, verify and place one binary; returns {'return': 0, 'path': <binary>}."""
    ext = _pick(item.get('ext'), v['uname'])
    vv = dict(v, ext=ext or '')
    url = item['url'].format(**vv)
    asset = os.path.basename(url.split('?')[0])
    if con:
        print(f'{space}INFO: {item["name"]} release asset: {url}')
    r = _download(tool, ctx, params, url, directory, asset)
    if r['return'] > 0:
        return r
    rs = _expected_sha256(tool, ctx, params, item.get('checksum'), dict(vv, url=url), asset, directory)
    if rs['return'] > 0:
        return rs
    if rs['sha256']:
        got = _sha256(r['path'])
        if got != rs['sha256']:
            # Drop the bad download, or download-file would hand it back on the next attempt
            try:
                os.remove(r['path'])
            except OSError:
                pass
            return tool.cm.error(f'SHA-256 mismatch for {asset}: expected {rs["sha256"]}, got {got}')
        if con:
            print(f'{space}INFO: SHA-256 verified ({got[:16]}...)')
    elif con:
        print(f'{space}INFO: upstream publishes no checksum for {asset} (downloaded over HTTPS)')

    target = os.path.join(os.getcwd(), directory, item['name'] + v['host_exe'])
    if ext:
        member = item.get('member')
        member = member.format(**vv) if member else None
        tmp = target + '.part'
        if not _unpack(r['path'], member, item['name'] + v['exe'], tmp):
            return tool.cm.error(f'{member or item["name"] + v["exe"]} was not found in {asset}')
        os.replace(tmp, target)
        os.remove(r['path'])
    elif os.path.abspath(r['path']) != os.path.abspath(target):
        os.replace(r['path'], target)
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {'return': 0, 'path': target}


def install_release(tool, ctx, params, cmd, spec):
    """The tool's install() hook for a pinned upstream release (see the module docstring)."""
    _global = ctx['tasks']['global']
    uname = _global['host']['os']['uname']
    uarch = _global['host']['os']['uarch']
    c = params.get('control', {})
    con = c.get('con', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if c.get('verbose') else ''

    version = params.get('version')
    version_simple = params.get('version_simple')
    if not version:
        version = version_simple = spec['default_version']
    if not version_simple:
        return {'return': 16, 'install_cmd': cmd,
                'error': f'the {spec["name"]} release download needs an exact version (got "{version}")'}

    os_name = _pick(spec.get('os', {}), uname, uname)
    arch = _pick(spec.get('arch', {}), uarch, uarch)
    if os_name is None or arch is None or (spec.get('os') and uname not in spec['os'] and '*' not in spec['os']) or \
            (spec.get('arch') and uarch not in spec['arch'] and '*' not in spec['arch']) or \
            [uname, uarch] in [list(x) for x in spec.get('unsupported', [])]:
        return {'return': 16, 'install_cmd': cmd,
                'error': f'{spec["name"]} publishes no release asset for {uname}/{uarch}'}

    host_exe = _global['host']['vars'].get('file_ext_exe', '')
    exe = _pick(spec.get('exe'), uname, '.exe' if uname == 'windows' else '')
    v = {'version': version_simple, 'os': os_name, 'arch': arch, 'exe': exe, 'host_exe': host_exe, 'uname': uname}
    if spec.get('version_tag'):
        v['tag'] = spec['version_tag'].format(**v)

    directory = 'content'
    os.makedirs(os.path.join(os.getcwd(), directory), exist_ok=True)
    main = {k: spec[k] for k in ('name', 'url', 'ext', 'member', 'checksum') if k in spec}
    r = _fetch_one(tool, ctx, params, main, v, directory, con, space)
    if r['return'] > 0:
        return r
    found = r['path']
    for extra in spec.get('extra', []):
        rx = _fetch_one(tool, ctx, params, extra, v, directory, con, space)
        if rx['return'] > 0:
            return rx
    return {'return': 0, 'install_cmd': None, 'found_path': found}
