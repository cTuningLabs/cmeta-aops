"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The Android SDK command-line tools (sdkmanager). Installed SDKs are detected first. Otherwise the zip of
the pinned (or requested) release for this host OS and CPU is downloaded from Google's repository, checked
against the SHA-1 that Google's repository index (repository2-3.xml) lists for it and unpacked as
<entry>/content/cmdline-tools/latest/ - the layout from which sdkmanager finds its SDK root (the entry's
content folder, where it then installs packages such as "ndk;<version>"). No administrator rights. Since
2026-10 winget has no package of them any more; a macOS release without a zip for the CPU falls back to brew.
"""

import hashlib
import os
import re
import shutil
import stat
import xml.etree.ElementTree as ET
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

REPOSITORY = 'https://dl.google.com/android/repository'
INDEX = REPOSITORY + '/repository2-3.xml'
HOST_OS = {'windows': 'windows', 'linux': 'linux', 'darwin': 'macosx'}
HOST_ARCH = {'amd64': 'x64', 'arm64': 'aarch64'}


def archive_of(index_xml, version, host_os, host_arch):
    """
    (file name, size, SHA-1) of the zip of "cmdline-tools;<version>" for a host in Google's index, or None. An
    archive that names a CPU (macOS since 22.0: mac_x86_64, mac_arm64) is taken only for that CPU; one that names
    none (Linux, Windows: Java with launch scripts) for any.
    """
    root = ET.fromstring(index_xml)
    for pkg in root.iter('remotePackage'):
        if pkg.get('path') != f'cmdline-tools;{version}':
            continue
        for a in pkg.iter('archive'):
            arch = a.findtext('host-arch')
            if a.findtext('host-os') == host_os and (arch is None or arch == host_arch) and a.find('complete') is not None:
                c = a.find('complete')
                return c.findtext('url'), int(c.findtext('size') or 0), (c.findtext('checksum') or '').lower()
    return None


def unpack(path, dest):
    """The zip's cmdline-tools/ folder into dest, with the Unix file modes it records (sdkmanager is a script)."""
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            if not name.startswith('cmdline-tools/') or info.is_dir():
                continue
            target = os.path.abspath(os.path.join(dest, *name.split('/')[1:]))
            if not target.startswith(dest + os.sep):
                raise ValueError(f'{info.filename} would be unpacked outside {dest}')
            os.makedirs(os.path.dirname(target), exist_ok = True)
            with z.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            mode = stat.S_IMODE(info.external_attr >> 16)
            if os.name != 'nt' and mode:
                os.chmod(target, mode)

def sdkmanager_java_cmd(ctx, path_bin):
    """The Java command of sdkmanager on Windows (java -classpath lib/sdkmanager-classpath.jar ...), or None."""
    _global = ctx['tasks']['global']
    if _global['host']['os']['uname'] != 'windows':
        return None
    tools = os.path.dirname(path_bin)
    jar = os.path.join(tools, 'lib', 'sdkmanager-classpath.jar')
    jdk_bin = (_global.get('openjdk') or {}).get('path_bin')
    java = os.path.join(jdk_bin, 'java.exe') if jdk_bin else None
    if not os.path.isfile(jar) or not java or not os.path.isfile(java):
        return None
    return (f'"{java}" "-Dcom.android.sdklib.toolsdir={tools}" -classpath "{jar}" '
            f'com.android.sdklib.tool.sdkmanager.SdkManagerCli')


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def detect_versions(self, ctx, paths, params=None):
        """Use the installed SDK package's revision when every candidate has one.

        Some Windows sdkmanager launchers mishandle ! in JAVA_HOME and print a
        Java diagnostic even for --version. Never record that diagnostic as a version.
        Legacy layouts without source.properties keep command-based detection.
        """
        versions = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            properties = os.path.join(os.path.dirname(os.path.dirname(path)), 'source.properties')
            try:
                with open(properties, encoding='utf-8') as stream:
                    text = stream.read()
            except OSError:
                return {'return': 0}
            match = re.search(r'(?m)^Pkg\.Revision\s*=\s*(\d+(?:\.\d+)*)\s*$', text)
            if not match:
                return {'return': 0}
            versions[candidate] = {'output': match.group(1)}
        return {'return': 0, 'found_paths_with_versions': versions}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The zip of the pinned (or requested) release for this host from Google's repository, checked against the
        index's SHA-1 and unpacked into content/cmdline-tools/latest/.
        """

        # The shared download helper, imported here: the detection and the offline tests need none of it
        from tool_c393ba5c6fa14f66.api.common_release import _download

        host = ctx['tasks']['global']['host']['os']
        uname, uarch = host['uname'], host.get('uarch')
        c = params.get('control', {})
        con, verbose = c.get('con', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc.get('default_version'))
        if not version:
            return self.cm.error(f'the download needs an exact release such as {self.cdesc.get("default_version")} '
                                 f'(the "cmdline-tools;<release>" packages of {INDEX})')

        r = _download(self, ctx, params, INDEX, 'downloads', 'repository2-3.xml')
        if self.cm.catch_error(r): return r
        with open(r['path'], encoding = 'utf-8') as f:
            index = f.read()

        # A release asked for as "23" is "23.0" in the index
        found = archive_of(index, version, HOST_OS.get(uname), HOST_ARCH.get(uarch))
        if not found and '.' not in version:
            found = archive_of(index, version + '.0', HOST_OS.get(uname), HOST_ARCH.get(uarch))
        if not found:
            why = f'Google\'s repository index has no command-line tools {version} for {uname}/{uarch} ({INDEX})'
            if uname == 'darwin' and cmd:
                return {'return': 16, 'error': why, 'install_cmd': cmd}
            return self.cm.error(why)

        name, size, sha1 = found
        if con:
            print ('')
            print (f'{space}INFO: Android SDK command-line tools {version}: {REPOSITORY}/{name} ({size / 1e6:.0f} MB download)')

        r = _download(self, ctx, params, f'{REPOSITORY}/{name}', 'downloads', name)
        if self.cm.catch_error(r): return r

        h = hashlib.sha1()
        with open(r['path'], 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        if h.hexdigest() != sha1:
            os.remove(r['path'])
            return self.cm.error(f'{name}: SHA-1 {h.hexdigest()} is not the one of Google\'s index ({sha1})')

        root = os.path.join(os.getcwd(), 'content', 'cmdline-tools', 'latest')
        try:
            unpack(r['path'], root)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            return self.cm.error(f'cannot unpack {name}: {e}')
        shutil.rmtree(os.path.join(os.getcwd(), 'downloads'), ignore_errors = True)

        sdkmanager = os.path.join(root, 'bin', 'sdkmanager' + ('.bat' if uname == 'windows' else ''))
        if not os.path.isfile(sdkmanager):
            return self.cm.error(f'{name} was unpacked into {root} but has no {os.path.basename(sdkmanager)}')
        return {'return': 0, 'install_cmd': None, 'found_path': sdkmanager}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _result = {'return':0}

        _with = params.get('with',{})

        path_bin = result['path_bin']

        path_home = os.path.dirname(os.path.dirname(os.path.dirname(path_bin)))
        qpath_home = self.cm.utils.files.quote_path(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        # Windows: Google's sdkmanager.bat enables delayed expansion, which drops every "!" of JAVA_HOME and of its
        # own folder (a JDK in a folder whose name has a "!": "Java version 17 or higher is required"). The command
        # of the tool (cx tool run, the NDK's version list and fallback) is its Java entry point instead, with the
        # option the .bat adds. Releases from 23.0 have no such jar: their .bat is a shim of the Android CLI, kept
        cmd = sdkmanager_java_cmd(ctx, path_bin)
        if cmd:
            result['cmd'] = cmd

        if _with.get('add_env', True):
            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['ANDROID_HOME'] = path_home # Legacy
            _aggregate_env['ANDROID_SDK_ROOT'] = path_home # New

            _result['result'] = result

        return _result

