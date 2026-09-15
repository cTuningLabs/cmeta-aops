"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/obsidian: Obsidian is an Electron desktop app that prints nothing useful for "--version" on the command line
(and would open a window), so the version is read from what the installer left behind - the file version of
Obsidian.exe on Windows, Info.plist inside Obsidian.app on macOS, the AppImage name or dpkg on Linux. Linux has no
distribution package: install() downloads the AppImage of the release from GitHub (tier 1 of the install ladder);
Windows and macOS go through winget and brew (tier 2, declared in _desc.yaml).
"""

import os
import plistlib
import re
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

VERSION_RE = re.compile(r'(\d+\.\d+\.\d+)')


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '').strip()
    except Exception:
        return ''


def _version_windows(path):
    # PowerShell reads the version resource of the executable without starting it
    out = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                "(Get-Item -LiteralPath '%s').VersionInfo.ProductVersion" % path.replace("'", "''")])
    m = VERSION_RE.search(out)
    return m.group(1) if m else ''


def _version_darwin(path):
    # .../Obsidian.app/Contents/MacOS/Obsidian -> .../Obsidian.app/Contents/Info.plist
    plist = os.path.join(os.path.dirname(os.path.dirname(path)), 'Info.plist')
    try:
        with open(plist, 'rb') as f:
            v = str(plistlib.load(f).get('CFBundleShortVersionString', ''))
        m = VERSION_RE.search(v)
        return m.group(1) if m else ''
    except Exception:
        return ''


def _version_linux(path):
    m = VERSION_RE.search(os.path.basename(path))          # Obsidian-1.9.14.AppImage
    if m:
        return m.group(1)
    out = _run(['dpkg-query', '-W', '-f=${Version}', 'obsidian'])   # the .deb
    m = VERSION_RE.search(out)
    return m.group(1) if m else ''


class CTool(InitCTool):
    """Obsidian: version from the installed files, AppImage download on Linux."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: list,
                        params: dict = {},
    ):
        """Version of every detected Obsidian without launching it (see the module docstring)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for xpath in paths:
            path = xpath[1:] if xpath.startswith('!') else xpath
            if uname == 'windows':
                version = _version_windows(path)
            elif uname == 'darwin':
                version = _version_darwin(path)
            else:
                version = _version_linux(path)
            found[xpath] = {'output': version or 'unknown', 'cmd': 'file metadata', 'cmd_call': None}
        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """Linux: download the AppImage of the release (tier 1). Other systems: fall back to install_cmd (winget / brew)."""
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']
        if uname != 'linux':
            return {'return': 16, 'install_cmd': cmd}

        version_simple = params.get('version_simple') or params.get('version') or self.cdesc['default_version']
        if not VERSION_RE.fullmatch(str(version_simple)):
            return {'return': 16, 'error': 'the AppImage download needs an exact version such as %s' % self.cdesc['default_version'], 'install_cmd': cmd}
        suffix = {'amd64': '', 'x86_64': '', 'arm64': '-arm64', 'aarch64': '-arm64'}.get(uarch)
        if suffix is None:
            return {'return': 16, 'error': 'no Obsidian AppImage for architecture %s' % uarch, 'install_cmd': cmd}

        filename = 'Obsidian-%s%s.AppImage' % (version_simple, suffix)
        urls = [t.format(version=version_simple, filename=filename) for t in self.cdesc['download_url_templates']]
        directory = 'content'
        path_to_tool = os.path.join(os.getcwd(), directory, filename)

        control = params.get('control', {})
        con, quiet, verbose = control.get('con', False), control.get('quiet', False), control.get('verbose', False)
        if con:
            print('')
            for url in urls:
                print('INFO: Download URL: %s' % url)
            print('INFO: Check file: %s' % path_to_tool)

        rx = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf', 'ctx': ctx,
                             'directory': directory, 'url': urls, 'env': params.get('env'), 'timeout': params.get('timeout'),
                             'con': con, 'quiet': quiet, 'verbose': verbose, 'unzip': False, 'check_file': path_to_tool,
                             'make_check_file_executable': True})
        if self.cm.catch_error(rx):
            return rx
        return {'return': 0, 'install_cmd': None, 'found_path': path_to_tool}
