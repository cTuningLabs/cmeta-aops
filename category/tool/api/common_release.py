"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Install a tool from a pinned upstream release (install ladder tier 1), shared by the tools
whose api_v1.py only declares where their release assets live:

    from tool_c393ba5c6fa14f66.api.common_release import install_release

    SPEC = {'name': 'helm',
            'url': 'https://get.helm.sh/helm-v{version}-{os}-{arch}.{ext}',
            'ext': {'windows': 'zip', '*': 'tar.gz'},
            'checksum': {'file': '{url}.sha256sum'}}

    def install(self, ctx, params, cmd=None, *misc):
        return install_release(self, ctx, params, cmd, SPEC)

and whose _desc.yaml pins the version installed when none is asked for:

    default_version: '4.3.0'

What it does, with the Python standard library only (no tar/unzip binaries needed):
  1. picks the asset for this OS and CPU from the templates ({version}, {os}, {arch}, {ext}, {exe});
  2. downloads it with the download-file task (so proxies, mirrors and retries behave as for every other tool);
  3. verifies its SHA-256 (or a selected per-asset SHA-512) when upstream publishes one - a "<hash>  <file>" list, a per-asset file, or
     yq's multi-hash table - and fails on a mismatch;
  4. unpacks one binary, or retains a whole distribution when tree=True;
  5. does the same for the "extra" binaries some tools ship next to the main one (kwok for kwokctl).

A spec may leave an OS or CPU out; install_release then returns 16 with the declarative install_cmd,
so setup can fall back to a package manager where the tool declares one, or print install_help_text.

SPEC keys:
  name             binary name without extension (also the file name it is saved as)
  url              asset URL template
  os / arch        cMeta uname / uarch -> the upstream spelling (default: the same word)
  ext              archive extension per OS ('*' = any other OS); omit for a bare binary
  exe              suffix of the binary per OS inside the asset/archive (default '.exe' on Windows)
  member           path of the binary inside the archive (template); default: the first file named <name><exe>
  checksum         {'list': <url>}          a "<sha256>  <asset>" list (checksums.txt, SHA256SUMS, ...)
                   {'file': <url>}          a per-asset file holding "<sha256>[  <asset>]"
                   {'yq': <url>, 'order': <url>}   yq's table of several hashes per line
                   {'sha256': {<version>: {<asset>: <sha256>}}}   digests pinned in the spec, for
                                            releases that list them only in GitHub's API; another
                                            version is downloaded over HTTPS only
                   omitted: no checksum published upstream (HTTPS only)
  version_tag      tag/version spelling in the URL if it differs, e.g. 'kustomize/v{version}'
  unsupported      [[uname, uarch], ...] pairs upstream publishes nothing for (e.g. ['windows', 'arm64'])
  extra            list of {'name', 'url', 'checksum', 'member', 'ext'} fetched into the same folder
  tree             True: retain the entire distribution, including JDK/libraries/configuration;
                   requires member, the relative path to the launcher inside the archive
  checksum.algorithm  'sha256' (default) or 'sha512' for a per-asset checksum file

The version is not a SPEC key: default_version in the tool's _desc.yaml is the one place that says which
version cMeta installs by default, so that the description of a tool can be queried (cx tool show <tool>);
a 'default_version' SPEC key of a tool written before 0.46.1 is still read when the description has none.
"""

import ctypes
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile


def default_version(tool, spec=None):
    """The version a tool installs when none is asked for: default_version of its _desc.yaml, else the SPEC's."""
    desc = getattr(tool, 'cdesc', None) or {}
    version = desc.get('default_version') or (spec or {}).get('default_version')
    return str(version) if version is not None else None


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
    """Upstream checksum; the legacy sha256 result key also carries a selected per-file SHA-512."""
    if not checksum:
        return {'return': 0, 'sha256': None}
    if 'sha256' in checksum:
        digest = (checksum['sha256'].get(v['version']) or {}).get(asset)
        return {'return': 0, 'sha256': digest.lower() if digest else None}
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


def _unpack_tree(archive, member, directory):
    """Retain a checked distribution. Reject traversal, special files and escaping links."""
    root = Path(directory).resolve()

    def safe_name(name):
        parts = PurePosixPath(name.replace('\\', '/')).parts
        if not parts or any(p in ('.', '..', '/') or ':' in p for p in parts):
            raise ValueError('Unsafe release archive member: ' + name)
        return parts

    selected = safe_name(member)
    if len(selected) < 2:
        raise ValueError('A tree release must have a distribution root and a launcher member')
    with tempfile.TemporaryDirectory(prefix='.unpack-', dir=str(root)) as temporary:
        stage = Path(temporary)
        if archive.endswith('.zip'):
            with zipfile.ZipFile(archive) as source:
                for info in source.infolist():
                    parts = safe_name(info.filename)
                    if parts[0] != selected[0] or stat.S_ISLNK(info.external_attr >> 16):
                        raise ValueError('Unexpected release archive root or zip symbolic link')
                    target = stage.joinpath(*parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source.open(info) as src, target.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
                        mode = (info.external_attr >> 16) & 0o777
                        if mode:
                            target.chmod(mode)
        else:
            with tarfile.open(archive, 'r:*') as source:
                for info in source.getmembers():
                    parts = safe_name(info.name)
                    if parts[0] != selected[0] or not (info.isfile() or info.isdir() or info.issym() or info.islnk()):
                        raise ValueError('Unexpected release archive root or special file')
                    target = stage.joinpath(*parts)
                    if not target.resolve().is_relative_to(stage):
                        raise ValueError('Release archive member escapes extraction directory')
                    if info.issym() or info.islnk():
                        if Path(info.linkname).is_absolute() or ':' in info.linkname or '\\' in info.linkname:
                            raise ValueError('Unsafe release archive link')
                        link = (target.parent if info.issym() else stage) / info.linkname
                        if not link.resolve().is_relative_to(stage / selected[0]):
                            raise ValueError('Release archive link escapes distribution')
                    # All paths/links are checked above, including on Python versions without data_filter.
                    if hasattr(tarfile, 'data_filter'):
                        source.extract(info, str(stage), filter='data')
                    else:
                        source.extract(info, str(stage))
        launcher = stage.joinpath(*selected)
        if not launcher.is_file():
            raise ValueError('Launcher was not found in release archive: ' + member)
        destination = root / selected[0]
        if destination.exists():
            raise ValueError('Distribution already exists; use a fresh tool cache entry: ' + str(destination))
        (stage / selected[0]).rename(destination)
    return str(root.joinpath(*selected))


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
    checksum = item.get('checksum') or {}
    algorithm = checksum.get('algorithm', 'sha256')
    algorithm_label = 'SHA-' + algorithm[3:]
    if algorithm not in ('sha256', 'sha512') or (algorithm == 'sha512' and 'file' not in checksum):
        return tool.cm.error('Release checksum must be SHA-256 or a per-asset SHA-512 file')
    rs = _expected_sha256(tool, ctx, params, checksum, dict(vv, url=url), asset, directory)
    if rs['return'] > 0:
        return rs
    if rs['sha256']:
        digest = hashlib.new(algorithm)
        with open(r['path'], 'rb') as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                digest.update(chunk)
        got = digest.hexdigest()
        if got != rs['sha256']:
            # Drop the bad download, or download-file would hand it back on the next attempt
            try:
                os.remove(r['path'])
            except OSError:
                pass
            return tool.cm.error(f'{algorithm_label} mismatch for {asset}: expected {rs["sha256"]}, got {got}')
        if con:
            print(f'{space}INFO: {algorithm_label} verified ({got[:16]}...)')
    elif con:
        print(f'{space}INFO: upstream publishes no checksum for {asset} (downloaded over HTTPS)')

    target = os.path.join(os.getcwd(), directory, item['name'] + v['host_exe'])
    if item.get('tree'):
        try:
            member = item['member'].format(**vv)
            target = _unpack_tree(r['path'], member, os.path.join(os.getcwd(), directory))
        except (KeyError, ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
            return tool.cm.error(str(error))
        os.remove(r['path'])
        os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return {'return': 0, 'path': target}
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
        version = version_simple = default_version(tool, spec)
        if not version:
            return tool.cm.error(f'{spec["name"]} pins no default_version in its _desc.yaml: give --version=<version>')
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
    main = {k: spec[k] for k in ('name', 'url', 'ext', 'member', 'checksum', 'tree') if k in spec}
    r = _fetch_one(tool, ctx, params, main, v, directory, con, space)
    if r['return'] > 0:
        return r
    found = r['path']
    for extra in spec.get('extra', []):
        rx = _fetch_one(tool, ctx, params, extra, v, directory, con, space)
        if rx['return'] > 0:
            return rx
    return {'return': 0, 'install_cmd': None, 'found_path': found}


# Windows search distributions need their Java entrypoints: vendor .bat files corrupt ! in paths.
def install_windows_search_launcher(launcher, kind):
    launcher = Path(launcher)
    script = launcher.parent / ('cmeta-' + kind + '.py')
    shutil.copyfile(__file__, script)
    wrapper = launcher.parent / ('cmeta-' + kind + '.cmd')
    wrapper.write_text('@echo off\nsetlocal DisableDelayedExpansion\n"' + sys.executable +
                       '" "%~dp0' + script.name + '" ' + kind + ' %*\nexit /b %errorlevel%\n', encoding='utf-8')
    return str(wrapper)


def _windows_jvm_options(value):
    """Use Windows' argument parser for the quoted options emitted by the Java JVM-options parser."""
    if not value.strip():
        return []
    argc = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = parse('java ' + value, ctypes.byref(argc))
    if not pointer:
        raise OSError('Cannot parse JVM options')
    try:
        return [pointer[i] for i in range(1, argc.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(pointer)


def _windows_search_command(kind, home, args, env, temporary):
    elastic = kind == 'elasticsearch'
    if not elastic and env.get('OPENSEARCH_FIPS_MODE', '').lower() == 'true':
        raise ValueError('The cMeta Windows launcher does not configure OpenSearch FIPS mode; use the upstream FIPS workflow')
    prefix = 'ES' if elastic else 'OPENSEARCH'
    conf = str(Path(env.get(prefix + '_PATH_CONF') or home / 'config').resolve())
    java_home = env.get(prefix + '_JAVA_HOME')
    if not elastic:
        java_home = java_home or env.get('JAVA_HOME')
    java = str(Path(java_home or home / 'jdk') / 'bin/java.exe')
    if not Path(java).is_file():
        raise ValueError('Java executable does not exist: ' + java)
    env.update({prefix + '_HOME': str(home), prefix + '_PATH_CONF': conf,
                prefix + '_DISTRIBUTION_TYPE': 'zip', 'HOSTNAME': env.get('COMPUTERNAME', '')})
    env.pop('JAVA_TOOL_OPTIONS', None)
    if elastic:
        env.pop('_JAVA_OPTIONS', None)
        env.update(JAVA=java, ES_JAVA_HOME=str(Path(java).parent.parent),
                   JAVA_TYPE='ES_JAVA_HOME' if java_home else 'bundled JDK')
        cli = ['-Xms4m', '-Xmx64m', '-XX:+UseSerialGC'] + _windows_jvm_options(env.get('CLI_JAVA_OPTS', ''))
        env['CLI_JAVA_OPTS'] = subprocess.list2cmdline(cli)
        if (home / 'lib/tools/server-launcher').is_dir():
            return [java, *cli, '-cp', str(home / 'lib/tools/server-launcher/*'),
                    'org.elasticsearch.server.launcher.ServerLauncher', *args]
        if (home / 'lib/cli-launcher').is_dir():
            return [java, *cli, '-Dcli.name=server', '-Dcli.script=' + str(home / 'bin/elasticsearch.bat'),
                    '-Dcli.libs=lib/tools/server-cli', '-Des.path.home=' + str(home), '-Des.path.conf=' + conf,
                    '-Des.distribution.type=zip', '-Des.java.type=' + env['JAVA_TYPE'],
                    '-cp', str(home / 'lib/*') + ';' + str(home / 'lib/cli-launcher/*'),
                    'org.elasticsearch.launcher.CliToolLauncher', *args]
    # Elasticsearch 7 and OpenSearch use the upstream JVM-options parser and bootstrap directly.
    (home / 'logs').mkdir(exist_ok=True)
    env.setdefault(prefix + '_TMPDIR', temporary)
    namespace = 'elasticsearch' if elastic else 'opensearch'
    classpath = str(home / 'lib/*')
    parser = subprocess.run([java, '-cp', classpath, 'org.' + namespace + '.tools.launchers.JvmOptionsParser', conf],
                            cwd=str(home), env=env, text=True, stdout=subprocess.PIPE)
    if parser.returncode:
        raise ValueError('Upstream JVM-options parser failed with code ' + str(parser.returncode))
    options = _windows_jvm_options(parser.stdout.strip())
    return [java, *options, '-D' + namespace, '-D' + namespace + '.path.home=' + str(home),
            '-D' + namespace + '.path.conf=' + conf, '-D' + namespace + '.distribution.type=zip',
            '-D' + namespace + '.bundled_jdk=true', *(['-Des.distribution.flavor=default'] if elastic else []),
            '-cp', classpath, 'org.' + namespace + '.bootstrap.' + ('Elasticsearch' if elastic else 'OpenSearch'), *args]


def _windows_search_main():
    kind = sys.argv[1]
    if kind not in ('elasticsearch', 'opensearch') or os.name != 'nt':
        raise ValueError('This launcher is for Elasticsearch/OpenSearch on Windows')
    home = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix='cmeta-' + kind + '-') as temporary:
        argv = _windows_search_command(kind, home, sys.argv[2:], env, temporary)
        # The old launchers pipe the keystore password; preserve the explicit environment interface.
        password = env.get('KEYSTORE_PASSWORD')
        if password is not None:
            return subprocess.run(argv, cwd=str(home), env=env, input=password + '\n', text=True).returncode
        return subprocess.call(argv, cwd=str(home), env=env)


if __name__ == '__main__':
    try:
        sys.exit(_windows_search_main())
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
