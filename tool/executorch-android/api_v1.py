"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup executorch-android": the official ExecuTorch runtime for Android, as PyTorch
publishes it on Maven Central (org.pytorch:executorch-android, an AAR), with the Java and native
libraries it needs (see _desc.yaml). Everything is checked against Maven Central's SHA-256 (or
SHA-1 where an old artifact has no SHA-256) and unpacked into the cache: the native libraries per
ABI under content/<version>/jni/<abi>/, the Java classes under content/<version>/jars/.
"""

import glob
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

MAVEN = 'https://repo1.maven.org/maven2'
ARTIFACT = ('org.pytorch', 'executorch-android')
MARKER = 'cmeta-executorch-android.json'
ABIS = ('arm64-v8a', 'x86_64')
POM_NS = {'m': 'http://maven.apache.org/POM/4.0.0'}

# The dependencies a program outside an app needs (androidx is for apps only)
NEEDED = {('org.jetbrains.kotlin', 'kotlin-stdlib'), ('com.facebook.fbjni', 'fbjni'),
          ('com.facebook.soloader', 'nativeloader')}


def maven_url(group, artifact, version, ext):
    return f'{MAVEN}/{group.replace(".", "/")}/{artifact}/{version}/{artifact}-{version}.{ext}'


def pom_dependencies(text):
    """The (groupId, artifactId, version) of a POM's dependencies, without test-scoped ones."""
    root = ET.fromstring(text)
    deps = []
    for d in root.findall('.//m:dependencies/m:dependency', POM_NS):
        def get(k):
            e = d.find('m:' + k, POM_NS)
            return e.text.strip() if e is not None and e.text else ''
        if get('scope') != 'test':
            deps.append((get('groupId'), get('artifactId'), get('version')))
    return deps


def needed_artifacts(poms):
    """
    The artifacts to fetch: the AAR and the NEEDED dependencies of the POMs read so far, as
    {(group, artifact): version}; poms maps (group, artifact) to the POM text.
    """
    found = {}
    for text in poms.values():
        for g, a, v in pom_dependencies(text):
            if (g, a) in NEEDED and v and (g, a) not in found:
                found[(g, a)] = v
    return found


def digest(path, kind):
    h = hashlib.new(kind)
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def unpack(path, root, name):
    """The native libraries per ABI and the classes of an AAR (or a plain jar) into root."""
    jars = os.path.join(root, 'jars')
    os.makedirs(jars, exist_ok = True)
    if path.endswith('.jar'):
        with open(path, 'rb') as src, open(os.path.join(jars, name + '.jar'), 'wb') as dst:
            dst.write(src.read())
        return
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            n = info.filename
            if n == 'classes.jar':
                with z.open(info) as src, open(os.path.join(jars, name + '.jar'), 'wb') as dst:
                    dst.write(src.read())
            parts = n.split('/')
            if len(parts) == 3 and parts[0] == 'jni' and parts[1] in ABIS and parts[2].endswith('.so'):
                d = os.path.join(root, 'jni', parts[1])
                os.makedirs(d, exist_ok = True)
                with z.open(info) as src, open(os.path.join(d, parts[2]), 'wb') as dst:
                    dst.write(src.read())


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _entry(self, root):
        with open(os.path.join(root, MARKER), encoding = 'utf-8') as f:
            marker = json.load(f)
        lib = os.path.join(root, 'jni', 'arm64-v8a', 'libexecutorch.so')
        return {'path': lib, 'detected_version': marker['version'],
                'features': {'root': root, 'artifacts': marker['artifacts'],
                             'jni': {abi: os.path.join(root, 'jni', abi) for abi in ABIS
                                     if os.path.isdir(os.path.join(root, 'jni', abi))},
                             'jars': sorted(glob.glob(os.path.join(root, 'jars', '*.jar')))}}

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The runtimes this setup unpacked (content/<version>/ with the marker), or --tool_path to
        an unpacked one's libexecutorch.so. Features: root, jni (per ABI), jars, artifacts.
        """

        if params.get('tool_path'):
            roots = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(params['tool_path']))))]
        else:
            roots = sorted(glob.glob(os.path.join(os.getcwd(), 'content', '*')))
        parsed = [self._entry(r) for r in roots if os.path.isfile(os.path.join(r, MARKER))]
        return {'return': 0, 'parsed_paths_with_versions': parsed}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The AAR of the pinned (or requested) version and its dependencies from Maven Central,
        each checked against Maven Central's digest, unpacked into content/<version>/.
        """

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc['default_version'])
        if not version or not re.match(r'^\d+\.\d+\.\d+([.-][\w.]+)?$', str(version)):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the ExecuTorch runtime download needs an exact version such as {self.cdesc["default_version"]}'}

        downloads = os.path.join(os.getcwd(), 'downloads')
        root = os.path.join(os.getcwd(), 'content', version)

        def fetch(url, required = True):
            name = url.rsplit('/', 1)[-1]
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'url': url, 'directory': 'downloads',
                                'filename': name, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if r['return'] > 0:
                return r if required else {'return': 0, 'path': None}
            return {'return': 0, 'path': os.path.join(downloads, name)}

        def verified(url):
            """The artifact, checked against Maven Central's SHA-256, else its SHA-1."""
            r = fetch(url)
            if r['return'] > 0: return r
            for kind in ('sha256', 'sha1'):
                rs = fetch(f'{url}.{kind}', required = False)
                if rs['return'] > 0: return rs
                if rs['path'] and os.path.isfile(rs['path']):
                    with open(rs['path'], encoding = 'utf-8', errors = 'replace') as f:
                        words = f.read().split()
                    published = words[0].lower() if words else ''
                    if re.fullmatch(r'[0-9a-f]{40,64}', published):
                        got = digest(r['path'], kind)
                        if got != published:
                            return self.cm.error(f'{os.path.basename(url)}: {kind} {got} is not the published {published}')
                        return {'return': 0, 'path': r['path'], 'digest': f'{kind}:{got}'}
            return self.cm.error(f'Maven Central publishes no SHA-256 or SHA-1 for {url}')

        group, artifact = ARTIFACT
        if con:
            print ('')
            print (f'{space}INFO: ExecuTorch {version} for Android from Maven Central ({group}:{artifact})')

        poms, todo, done = {}, {(group, artifact): version}, {}
        while todo:
            (g, a), v = todo.popitem()
            if (g, a) in done:
                continue
            ext = 'aar' if (g, a) in (ARTIFACT, ('com.facebook.fbjni', 'fbjni')) else 'jar'
            r = verified(maven_url(g, a, v, ext))
            if self.cm.catch_error(r): return r
            done[(g, a)] = {'version': v, 'file': os.path.basename(r['path']), 'digest': r['digest']}
            try:
                unpack(r['path'], root, a)
            except (OSError, zipfile.BadZipFile) as e:
                return self.cm.error(f'cannot unpack {r["path"]}: {e}')
            rp = fetch(maven_url(g, a, v, 'pom'))
            if self.cm.catch_error(rp): return rp
            with open(rp['path'], encoding = 'utf-8') as f:
                poms[(g, a)] = f.read()
            for key, dep_version in needed_artifacts(poms).items():
                if key not in done:
                    todo[key] = dep_version

        missing = [n for n in ('libexecutorch.so', 'libfbjni.so', 'libc++_shared.so')
                   if not os.path.isfile(os.path.join(root, 'jni', 'arm64-v8a', n))]
        if missing:
            return self.cm.error(f'the ExecuTorch {version} runtime lacks {", ".join(missing)} for arm64-v8a')

        with open(os.path.join(root, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'artifacts': {f'{g}:{a}': d for (g, a), d in done.items()}}, f, indent = 2)

        import shutil
        shutil.rmtree(downloads, ignore_errors = True)
        return {'return': 0, 'install_cmd': None, 'found_path': os.path.join(root, 'jni', 'arm64-v8a', 'libexecutorch.so')}
