"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The JDK of one vendor, downloaded into the tool's cache entry, for the tools jdk-<vendor>:

    from tool_c393ba5c6fa14f66.api.common_jdk import jdk_init, install_jdk, jdk_finish

    def init(self, ctx, params={}):            return jdk_init(self, params)
    def install(self, ctx, params, cmd=None, *misc): return install_jdk(self, ctx, params, 'zulu')
    def finish_dynamic_result(self, ctx, result={}, params={}): return jdk_finish(result, params, 'zulu')

What it does: finds the archive of the latest release of --with.feature (the major version,
default 25; --version pins a release where the vendor publishes one) for this OS and CPU, checks its
SHA-256 against the vendor's, unpacks it into "content" and returns its javac:

  temurin     Eclipse Temurin (Adoptium API): Windows, Linux (also musl), macOS
  microsoft   the Microsoft Build of OpenJDK (aka.ms): Windows, Linux, macOS
  corretto    Amazon Corretto (corretto.aws): Windows, Linux, macOS
  zulu        Azul Zulu (Azul's metadata API): Windows, Linux, macOS
  oracle      Oracle JDK (download.oracle.com): Oracle's license applies (its No-Fee Terms and
              Conditions for the current releases)

x64 and aarch64 everywhere. The result's features name the vendor and the JDK home; --with.add_env
also exports JAVA_HOME and the bin folder on PATH.
"""

import json
import os
import platform
import shutil
import tarfile
import urllib.parse
import urllib.request
import zipfile

from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

DEFAULT_FEATURE = '25'
ARCH = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}
OS = {'windows': 'windows', 'linux': 'linux', 'darwin': 'macos'}


def _get(url, timeout = 60):
    request = urllib.request.Request(url, headers = {'User-Agent': 'cmeta-aops'})
    with urllib.request.urlopen(request, timeout = timeout) as response:
        return response.read().decode('utf-8', 'replace')


def resolve(vendor, feature, version, uname, uarch, musl = False, get = None):
    """The JDK archive of a vendor for this system: ({'url', 'sha256', 'filename'}, error)."""
    get = get or _get
    arch = ARCH.get(str(uarch).lower())
    if not arch or uname not in OS:
        return None, f'{vendor} has no JDK for {uname} on {uarch}'
    if musl and vendor != 'temurin':
        return None, f'{vendor} publishes no JDK for musl (Alpine) Linux: use jdk-temurin'
    ext = 'zip' if uname == 'windows' else 'tar.gz'
    os_name = OS[uname]

    if vendor == 'temurin':
        os_name = {'darwin': 'mac'}.get(uname, 'alpine-linux' if musl else uname)
        query = f'architecture={arch}&os={os_name}&image_type=jdk&jvm_impl=hotspot&vendor=eclipse'
        if version:
            data = json.loads(get(f'https://api.adoptium.net/v3/assets/release_name/eclipse/'
                                  f'jdk-{urllib.parse.quote(version)}?{query}'))
        else:
            data = (json.loads(get(f'https://api.adoptium.net/v3/assets/feature_releases/{feature}/ga?{query}'
                                   f'&page_size=1&sort_order=DESC')) or [None])[0]
        if not data or not data.get('binaries'):
            return None, f'Temurin has no JDK {version or feature} for {os_name} {arch}'
        package = data['binaries'][0]['package']
        return {'url': package['link'], 'sha256': package['checksum'], 'filename': package['name']}, None

    if vendor == 'microsoft':
        url = f'https://aka.ms/download-jdk/microsoft-jdk-{version or feature}-{os_name}-{arch}.{ext}'
        sums = get(url + '.sha256sum.txt').split()
        if not sums:
            return None, f'no SHA-256 for {url}'
        return {'url': url, 'sha256': sums[0], 'filename': sums[1] if len(sums) > 1 else os.path.basename(url)}, None

    if vendor == 'corretto':
        if version:
            return None, 'Amazon Corretto: pick the major version with --with.feature (not --version)'
        name = f'amazon-corretto-{feature}-{arch}-{os_name}-jdk.{ext}'
        sha = get(f'https://corretto.aws/downloads/latest_sha256/{name}').split()
        if not sha:
            return None, f'no SHA-256 for {name}'
        return {'url': f'https://corretto.aws/downloads/latest/{name}', 'sha256': sha[0], 'filename': name}, None

    if vendor == 'zulu':
        query = (f'java_version={version or feature}&os={os_name}&arch={arch}&archive_type={ext}&java_package_type=jdk'
                 f'&javafx_bundled=false&crac_supported=false&release_status=ga&availability_types=CA&latest=true&page_size=1')
        packages = json.loads(get(f'https://api.azul.com/metadata/v1/zulu/packages/?{query}'))
        if not packages:
            return None, f'Zulu has no JDK {version or feature} for {os_name} {arch}'
        detail = json.loads(get(f'https://api.azul.com/metadata/v1/zulu/packages/{packages[0]["package_uuid"]}'))
        return {'url': packages[0]['download_url'], 'sha256': detail['sha256_hash'], 'filename': packages[0]['name']}, None

    if vendor == 'oracle':
        if version:
            return None, 'Oracle JDK: pick the major version with --with.feature (older updates need an Oracle account)'
        name = f'jdk-{feature}_{os_name}-{arch}_bin.{ext}'
        url = f'https://download.oracle.com/java/{feature}/latest/{name}'
        sha = get(url + '.sha256').split()
        if not sha:
            return None, f'no SHA-256 for {url}'
        return {'url': url, 'sha256': sha[0], 'filename': name}, None

    return None, f'unknown JDK vendor "{vendor}"'


def find_javac(root, exe = ''):
    """The javac of an unpacked JDK (bin/javac, or Contents/Home/bin/javac on macOS), or None."""
    found = []
    for d, dirs, files in os.walk(root):
        if 'javac' + exe in files and os.path.basename(d) == 'bin':
            found.append(os.path.join(d, 'javac' + exe))
    return min(found, key = len) if found else None


def jdk_init(tool, params):
    """The major version (part of the cache identity of the tool)."""
    _with = params.setdefault('with', {})
    _with['feature'] = str(_with.get('feature') or DEFAULT_FEATURE)
    return {'return': 0}


def install_jdk(tool, ctx, params, vendor):
    """The tool's install() hook: the vendor's JDK into the cache entry (see the module docstring)."""
    _global = ctx['tasks']['global']
    host = _global['host']['os']
    uname, uarch = host['uname'], host.get('uarch')
    musl = uname == 'linux' and platform.libc_ver()[0] != 'glibc'
    feature = str(params.get('with', {}).get('feature') or DEFAULT_FEATURE)
    version = params.get('version_simple')
    if params.get('version') and not version:
        return tool.cm.error(f'jdk-{vendor} installs exact releases only, not "{params.get("version")}"')
    try:
        info, error = resolve(vendor, feature, version, uname, uarch, musl)
    except (OSError, ValueError, KeyError) as e:
        return tool.cm.error(f'could not find the {vendor} JDK {version or feature}: {e}')
    if error:
        return tool.cm.error(error)

    if params.get('control', {}).get('con'):
        print(f'INFO: {vendor} JDK {version or feature}: {info["url"]}')

    r = _download(tool, ctx, params, info['url'], 'download', info['filename'])
    if r['return'] > 0:
        return r
    archive = r['path']
    digest = _sha256(archive)
    if digest != info['sha256'].lower():
        os.remove(archive)
        return tool.cm.error(f'SHA-256 mismatch for {info["filename"]}: expected {info["sha256"]}, got {digest}')

    content = os.path.join(os.getcwd(), 'content')
    shutil.rmtree(content, ignore_errors = True)
    os.makedirs(content)
    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            z.extractall(content)
    else:
        with tarfile.open(archive) as t:
            t.extractall(content, **({'filter': 'fully_trusted'} if hasattr(tarfile, 'data_filter') else {}))
    os.remove(archive)

    javac = find_javac(content, _global['host']['vars'].get('file_ext_exe', ''))
    if not javac:
        return tool.cm.error(f'no bin/javac in the {vendor} JDK archive {info["filename"]}')
    if uname != 'windows':
        for name in os.listdir(os.path.dirname(javac)):
            p = os.path.join(os.path.dirname(javac), name)
            os.chmod(p, os.stat(p).st_mode | 0o111)
    return {'return': 0, 'install_cmd': None, 'found_path': javac}


def jdk_finish(result, params, vendor):
    """The tool's finish_dynamic_result(): the vendor and the JDK home as features; with
    --with.add_env also JAVA_HOME and the bin folder on PATH (as tool/openjdk)."""
    path = result.get('path')
    if path:
        path_bin = os.path.dirname(path)
        path_home = os.path.dirname(path_bin)
        features = result.setdefault('features', {})
        features.update({'vendor': vendor, 'home': path_home,
                         'feature': params.get('with', {}).get('feature')})
        if params.get('with', {}).get('add_env', False):
            env = result.setdefault('_aggregate', {}).setdefault('env', {})
            env['JAVA_HOME'] = path_home
            env['JAVA_PATH'] = path_home
            p = env.setdefault('+PATH', [])
            if path_bin not in p:
                p.insert(0, path_bin)
    return {'return': 0, 'result': result}
