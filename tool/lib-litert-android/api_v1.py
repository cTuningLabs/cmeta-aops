"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-litert-android": Google's LiteRT runtime for Android (see _desc.yaml) from its
official releases, checked and unpacked into the cache:
  - the AAR from Google Maven (com.google.ai.edge.litert:litert, Maven's SHA-256): libLiteRt.so
    (with the C API) and libLiteRtClGlAccelerator.so (the GPU accelerator) per ABI;
  - the C/C++ SDK from the GitHub release (the C API headers, with the build_config.h CMake would
    generate) for programs built against libLiteRt.so;
  - the NPU dispatch libraries from the GitHub release (Google Tensor; Qualcomm HTP v69-v81);
  - the release's test model (MobileNet v2, float32).
GitHub's SHA-256 digests come from the release's API (pinned below for the default release).

As a lib-* tool its features feed setup-compile directly (an NDK build links -lLiteRt with the C
SDK headers) and setup-run (the arm64-v8a runtime, GPU accelerator and Google Tensor NPU
libraries are pushed to the device's library folder).
"""

import glob
import hashlib
import json
import os
import re
import shutil
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

MAVEN = 'https://dl.google.com/android/maven2/com/google/ai/edge/litert/litert/{v}/litert-{v}.aar'
GITHUB = 'https://github.com/google-ai-edge/LiteRT/releases/download/v{v}/{name}'
RELEASE_API = 'https://api.github.com/repos/google-ai-edge/LiteRT/releases/tags/v{v}'
MODEL = 'https://raw.githubusercontent.com/google-ai-edge/LiteRT/v{v}/litert/test/testdata/mobilenet_v2_1.0_224.tflite'
ASSETS = ('litert_cc_sdk.zip', 'litert_npu_runtime_libraries_jit.zip')
MARKER = 'cmeta-litert-android.json'
ABIS = ('arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86')

# The GitHub digests of the default release, used when the release API is not reachable
PINNED = {'2.2.0': {'litert_cc_sdk.zip': '0aa619d80aef27303ad9c6e3759a20110f77e7b11ade9b68061b8c6e5904b0c6',
                    'litert_npu_runtime_libraries_jit.zip': 'd6d160104f110e690f1c9b0c54ab3855af1a12e405dcc6e644dd7e3e1955aac4'}}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def release_digests(api_json):
    """{asset name: sha256} from a GitHub release API document."""
    out = {}
    for a in json.loads(api_json).get('assets', []):
        d = a.get('digest') or ''
        if d.startswith('sha256:'):
            out[a['name']] = d[7:].lower()
    return out


def unpack(aar, npu_zip, sdk_zip, root):
    """The libraries per ABI, the NPU dispatch libraries per vendor and ABI, and the C SDK into root."""
    with zipfile.ZipFile(aar) as z:
        for n in z.namelist():
            parts = n.split('/')
            if len(parts) == 3 and parts[0] == 'jni' and parts[1] in ABIS and parts[2].endswith('.so'):
                d = os.path.join(root, 'jni', parts[1])
                os.makedirs(d, exist_ok = True)
                with open(os.path.join(d, parts[2]), 'wb') as f:
                    f.write(z.read(n))
    # <vendor>_runtime[_vNN]/src/main/jni/<abi>/<lib>.so -> npu/<vendor>[_vNN]/<abi>/<lib>.so
    with zipfile.ZipFile(npu_zip) as z:
        for n in z.namelist():
            m = re.match(r'^([^/]+?)_runtime(_v\d+)?/src/main/jni/([^/]+)/([^/]+\.so)$', n)
            if m and m.group(3) in ABIS:
                d = os.path.join(root, 'npu', m.group(1) + (m.group(2) or ''), m.group(3))
                os.makedirs(d, exist_ok = True)
                with open(os.path.join(d, m.group(4)), 'wb') as f:
                    f.write(z.read(n))
    sdk = os.path.join(root, 'sdk')
    with zipfile.ZipFile(sdk_zip) as z:
        z.extractall(sdk)
    template = glob.glob(os.path.join(sdk, '*', 'litert', 'build_common', 'build_config.h.in'))
    if template:
        with open(template[0], encoding = 'utf-8') as f:
            text = f.read()
        for flag in ('GPU', 'NPU'):
            text = text.replace(f'#cmakedefine01 LITERT_BUILD_CONFIG_DISABLE_{flag}', f'#define LITERT_BUILD_CONFIG_DISABLE_{flag} 0')
        with open(template[0][:-3], 'w', encoding = 'utf-8') as f:
            f.write(text)


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _entry(self, root):
        with open(os.path.join(root, MARKER), encoding = 'utf-8') as f:
            marker = json.load(f)
        jni = {abi: os.path.join(root, 'jni', abi) for abi in ABIS if os.path.isdir(os.path.join(root, 'jni', abi))}
        npu = {}
        for vendor_dir in sorted(glob.glob(os.path.join(root, 'npu', '*'))):
            npu[os.path.basename(vendor_dir)] = {abi: os.path.join(vendor_dir, abi) for abi in ABIS
                                                 if os.path.isdir(os.path.join(vendor_dir, abi))}
        include = sorted(glob.glob(os.path.join(root, 'sdk', '*')))
        libs = sorted(glob.glob(os.path.join(root, 'jni', 'arm64-v8a', '*.so')))
        libs += sorted(glob.glob(os.path.join(root, 'npu', 'google_tensor', 'arm64-v8a', '*.so')))
        lib_dirs = [d for d in (os.path.join(root, 'jni', 'arm64-v8a'), os.path.join(root, 'npu', 'google_tensor', 'arm64-v8a'))
                    if os.path.isdir(d)]
        return {'path': os.path.join(root, 'jni', 'arm64-v8a', 'libLiteRt.so'), 'detected_version': marker['version'],
                'features': {'root': root, 'jni': jni, 'npu': npu, 'include': include[0] if include else None,
                             'model': marker.get('model'), 'android_push_libs': libs, 'digests': marker['digests'],
                             # what setup-compile and setup-run take from a lib-* tool
                             'lib_names': ['LiteRt'],
                             'paths': {'includes': include[:1], 'libs': lib_dirs[:1], 'found_dynamic_libs': libs,
                                       'found_dynamic_lib_paths': lib_dirs}}}

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The runtimes this setup unpacked (content/<version>/ with the marker). Features: root, jni
        and npu folders per ABI, include (the C SDK), model (MobileNet v2), android_push_libs (the
        arm64-v8a runtime, GPU accelerator and Google Tensor NPU libraries to push to a device).
        """
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
        The AAR (Maven SHA-256), the C SDK and the NPU libraries (GitHub SHA-256) and the test
        model of the pinned (or requested) release, unpacked into content/<version>/.
        """
        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc['default_version'])
        if not version or not re.match(r'^\d+\.\d+\.\d+$', str(version)):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the LiteRT download needs an exact version such as {self.cdesc["default_version"]}'}

        downloads = os.path.join(os.getcwd(), 'downloads')

        def fetch(url, name, required = True):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'url': url, 'directory': 'downloads',
                                'filename': name, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if r['return'] > 0:
                return r if required else {'return': 0, 'path': None}
            return {'return': 0, 'path': os.path.join(downloads, name)}

        def check(path, sha, name):
            got = sha256_of(path)
            if got != sha:
                os.remove(path)
                return self.cm.error(f'{name}: SHA-256 {got} is not the published {sha}')
            return {'return': 0, 'sha256': got}

        if con:
            print ('')
            print (f'{space}INFO: LiteRT {version} for Android: Google Maven and github.com/google-ai-edge/LiteRT')

        digests = {}
        aar_name = f'litert-{version}.aar'
        r = fetch(MAVEN.format(v = version), aar_name)
        if self.cm.catch_error(r): return r
        aar = r['path']
        rs = fetch(MAVEN.format(v = version) + '.sha256', aar_name + '.sha256')
        if self.cm.catch_error(rs): return rs
        with open(rs['path'], encoding = 'utf-8', errors = 'replace') as f:
            words = f.read().split()
        r = check(aar, words[0].lower() if words else '', aar_name)
        if self.cm.catch_error(r): return r
        digests[aar_name] = r['sha256']

        published = dict(PINNED.get(version, {}))
        ra = fetch(RELEASE_API.format(v = version), f'release-v{version}.json', required = False)
        if ra.get('path') and os.path.isfile(ra['path']):
            with open(ra['path'], encoding = 'utf-8') as f:
                try:
                    published.update(release_digests(f.read()))
                except ValueError:
                    pass
        paths = {}
        for name in ASSETS:
            if name not in published:
                return self.cm.error(f'no SHA-256 for {name} of LiteRT {version} (GitHub release API unreachable?)')
            r = fetch(GITHUB.format(v = version, name = name), name)
            if self.cm.catch_error(r): return r
            r2 = check(r['path'], published[name], name)
            if self.cm.catch_error(r2): return r2
            digests[name] = r2['sha256']
            paths[name] = r['path']

        root = os.path.join(os.getcwd(), 'content', version)
        try:
            unpack(aar, paths['litert_npu_runtime_libraries_jit.zip'], paths['litert_cc_sdk.zip'], root)
        except (OSError, zipfile.BadZipFile) as e:
            return self.cm.error(f'cannot unpack the LiteRT {version} downloads: {e}')

        # The release's test model (the tag pins it); no digest is published for it
        model = None
        rm = fetch(MODEL.format(v = version), 'mobilenet_v2_1.0_224.tflite', required = False)
        if rm.get('path') and os.path.isfile(rm['path']):
            os.makedirs(os.path.join(root, 'models'), exist_ok = True)
            model = os.path.join(root, 'models', 'mobilenet_v2_1.0_224.tflite')
            shutil.move(rm['path'], model)
            digests['mobilenet_v2_1.0_224.tflite'] = sha256_of(model)

        if not os.path.isfile(os.path.join(root, 'jni', 'arm64-v8a', 'libLiteRt.so')):
            return self.cm.error(f'the LiteRT {version} AAR has no arm64-v8a libLiteRt.so')
        with open(os.path.join(root, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'digests': digests, 'model': model}, f, indent = 2)
        shutil.rmtree(downloads, ignore_errors = True)
        return {'return': 0, 'install_cmd': None, 'found_path': os.path.join(root, 'jni', 'arm64-v8a', 'libLiteRt.so')}
