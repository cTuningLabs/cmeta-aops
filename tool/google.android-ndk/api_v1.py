"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup google.android-ndk": the Android NDK. An NDK of an Android SDK (or one on the
PATH) is detected first. Otherwise the zip of the pinned (or requested) NDK for this host OS is
downloaded from Google's repository into the cache, checked against the SHA-1 that Google's
repository index (repository2-3.xml) lists for it, and unpacked with its file modes and symlinks
(install ladder tier 1): no Java, no sdkmanager, no administrator rights. Where Google publishes
no zip for the host (Linux on ARM), setup falls back to sdkmanager (the SDK command-line tools).
"""

import glob
import hashlib
import os
import shutil
import stat
import xml.etree.ElementTree as ET
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

REPOSITORY = 'https://dl.google.com/android/repository'
INDEX = REPOSITORY + '/repository2-3.xml'
HOST_OS = {'windows': 'windows', 'linux': 'linux', 'darwin': 'macosx'}


def ndk_archive(index_xml, version, host_os):
    """(file name, size, SHA-1) of an NDK version's zip for a host OS in Google's index, or None."""
    root = ET.fromstring(index_xml)
    for pkg in root.iter('remotePackage'):
        if pkg.get('path') == f'ndk;{version}':
            for a in pkg.iter('archive'):
                if a.findtext('host-os') == host_os and a.find('complete') is not None:
                    c = a.find('complete')
                    return c.findtext('url'), int(c.findtext('size') or 0), (c.findtext('checksum') or '').lower()
    return None


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def extract_zip(path, dest):
    """Unpack a zip with the Unix file modes and symlinks it records (Python's extractall drops
    them: the NDK's clang would not be executable)."""
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            target = os.path.abspath(os.path.join(dest, info.filename))
            if target != dest and not target.startswith(dest + os.sep):
                raise ValueError(f'{info.filename} would be unpacked outside {dest}')
            mode = (info.external_attr >> 16) & 0xFFFF
            if info.is_dir():
                os.makedirs(target, exist_ok = True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok = True)
            if stat.S_ISLNK(mode) and os.name != 'nt':
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(z.read(info).decode('utf-8'), target)
                continue
            with z.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            if os.name != 'nt' and stat.S_IMODE(mode):
                os.chmod(target, stat.S_IMODE(mode))


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _sdkmanager(self, ctx, params, version, why):
        """The fallback: sdkmanager of the SDK command-line tools (set up here: they need Java)."""
        c = params.get('control', {})
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                            'ctx': ctx, 'name': 'google.android-sdk.command-line-tools,2ee8eb31da764eef',
                            'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
        if self.cm.catch_error(r): return r
        q = ctx['tasks']['global']['google-android-sdk-command-line-tools']['qpath']
        return {'return': 16, 'error': why, 'install_cmd': f'{q} "ndk;{version}"'}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The NDK zip of the pinned (or requested) version for this host OS from Google's
        repository, checked against the index's SHA-1 and unpacked into content/<version>/.
        """

        host = ctx['tasks']['global']['host']['os']
        uname, uarch = host['uname'], host.get('uarch')
        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc['default_version'])
        if not version:
            return self.cm.error(f'the NDK download needs an exact version such as {self.cdesc["default_version"]} '
                                 f'(the full revision: cx tool setup google.android-ndk --versions)')
        host_os = HOST_OS.get(uname)
        if not host_os or (uname == 'linux' and uarch != 'amd64'):
            return self._sdkmanager(ctx, params, version, f'Google publishes no NDK zip for {uname}/{uarch}')

        downloads = os.path.join(os.getcwd(), 'downloads')

        def fetch(url, name):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'url': url, 'directory': 'downloads',
                                'filename': name, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose,
                                'check_file': os.path.join(downloads, name)})
            if self.cm.catch_error(r): return r
            return {'return': 0, 'path': os.path.join(downloads, name)}

        r = fetch(INDEX, 'repository2-3.xml')
        if self.cm.catch_error(r): return r
        with open(r['path'], encoding = 'utf-8') as f:
            archive = ndk_archive(f.read(), version, host_os)
        if not archive:
            return self.cm.error(f'NDK {version} for {host_os} is not in Google\'s repository index ({INDEX}): '
                                 f'cx tool setup google.android-ndk --versions')
        name, size, sha1 = archive
        if con:
            print ('')
            print (f'{space}INFO: Android NDK {version}: {REPOSITORY}/{name} ({size / 1e6:.0f} MB download)')

        r = fetch(f'{REPOSITORY}/{name}', name)
        if self.cm.catch_error(r): return r
        got = sha1_of(r['path'])
        if got != sha1:
            os.remove(r['path'])
            return self.cm.error(f'{name}: SHA-1 {got} is not the one of Google\'s index ({sha1})')
        if con:
            print (f'{space}INFO: SHA-1 verified ({got[:16]}...); unpacking ...')

        root = os.path.join(os.getcwd(), 'content', version)
        try:
            extract_zip(r['path'], root)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            return self.cm.error(f'cannot unpack {name}: {e}')
        shutil.rmtree(downloads, ignore_errors = True)

        exe = '.cmd' if uname == 'windows' else ''
        found = sorted(glob.glob(os.path.join(root, '*', 'ndk-which' + exe)))
        if not found:
            return self.cm.error(f'{name} was unpacked into {root} but has no ndk-which{exe}')
        return {'return': 0, 'install_cmd': None, 'found_path': found[0]}

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

        path_home = path_bin
        qpath_home = self.cm.utils.files.quote_path(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        return _result
