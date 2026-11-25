"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import datetime
import json
import os
import shutil

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import sha256_of
from tool_c393ba5c6fa14f66.api.common_intel import (EULA_URL, VS_INTEGRATIONS, truthy, instance_of, linux_command,
                                                    windows_command, removal_commands, user_installer)

# What an install by this tool leaves in its install folder: the release, its file and checksum, Intel's instance
MARKER = 'cmeta-oneapi.json'

# The systems Intel publishes the package for (macOS has no oneAPI compilers; there is no build for ARM)
SYSTEMS = ('linux', 'windows')

# The environment script of an installed release, by system: <install folder>/<line>/<script> (2026.1/oneapi-vars.sh)
VARS_SCRIPT = {'linux': 'oneapi-vars.sh', 'windows': 'oneapi-vars.bat'}


def version_key(version):
    """2026.1.3 -> (2026, 1, 3): what orders the releases (a part that is no number counts 0)."""
    return tuple(int(p) if p.isdigit() else 0 for p in str(version or '').strip().split('.'))


def line_of(release):
    """2026.1.3 -> 2026.1: the line of oneAPI a release of Intel's package belongs to."""
    return '.'.join(str(release).strip().split('.')[:2])


def release_for(releases, system, asked, default, matches):
    """
    The release of the table (releases: of _desc.yaml) a request means on this system
    -> (name, its entry for the system, None), or (None, None, why not).

    The tool's version is the compiler's (icx --version), which Intel numbers apart from its package: the package
    2026.1.3 holds the compiler 2026.1.1. So a request names a line of oneAPI (2026.1; a range: >=2026.0) or a
    compiler version the table knows (compiler: of a release, where one was installed and read) - never the
    package's own number, which the detection after the install would not find. Without a version the request is
    the tool's default_version; "latest" is the newest release the table has for the system. The newest release
    that matches is taken - matches(request, version) is the engine's own comparison - and a release the table
    does not have for this system is never replaced by another one.
    """
    known = sorted((str(n) for n, files in (releases or {}).items() if isinstance(files, dict) and files.get(system)),
                   key = version_key, reverse = True)
    if not known:
        return None, None, f'no release of Intel Deep Learning Essentials is known for {system}'

    asked = str(asked or default or '').strip()
    if not asked or asked.lower() == 'latest':
        name = known[0]
    else:
        def answers(n):
            compiler = str(releases[n][system].get('compiler') or '')
            return matches(asked, line_of(n)) or bool(compiler and matches(asked, compiler))
        name = next((n for n in known if answers(n)), None)
        if name is None:
            lines = ', '.join(dict.fromkeys(line_of(n) for n in known))
            return None, None, (f'no known release of oneAPI matches "{asked}" on {system} (known lines: {lines}; a request '
                                f'names a line: the version of the tool is the compiler\'s, not the number of Intel\'s package)')

    return name, releases[name][system], None


def vars_scripts(folder, system):
    """The environment scripts of the releases in an install folder: <folder>/<line>/oneapi-vars.* (never the
    links "latest" and "common")."""
    name, found = VARS_SCRIPT[system], []
    if os.path.isdir(folder):
        for line in sorted(os.listdir(folder)):
            path = os.path.join(folder, line, name)
            if line not in ('latest', 'common') and os.path.isfile(path):
                found.append(path)
    return found


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def update_paths(self,
                     ctx: dict,
                     paths: dict,
                     params: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL oneapi api_v1 update_paths")

        new_paths = []

        for path in paths:
            if 'common' not in path and 'latest' not in path:
                new_paths.append(path)

        return {'return':0, 'paths':new_paths}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Intel Deep Learning Essentials (the oneAPI package Intel publishes for building PyTorch for its GPUs: the
        DPC++/C++ compiler with SYCL and the libraries around it), one release of the table in _desc.yaml, once
        the user has accepted Intel's EULA (--with.accept_eula=yes); the file checked against the sha256 the table
        has.

        Linux: Intel's installer runs without root into this cache entry (content/), with an installation instance
        of its own - nothing of the system changes, and several releases stand side by side, one per entry.
        Windows: the installer needs administrator rights and installs where Intel does: the tool downloads it and
        hands the command to the setup task (requires_sudo: windows - a quiet run from a plain process prints the
        command instead of starting it).
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if uname not in SYSTEMS or uarch != 'amd64':
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'Intel publishes oneAPI for Linux and Windows on x86_64 only ({uname}/{uarch} here)'}

        def matches(spec, version):
            return self.cm.packages.match_version(spec, version).get('matched', False)

        name, release, why = release_for(self.cdesc.get('releases'), uname, params.get('version'),
                                         self.cdesc.get('default_version'), matches)
        if why:
            return {'return': 16, 'install_cmd': cmd, 'error': why}

        _with = params.get('with', {}) or {}
        if not truthy(_with.get('accept_eula')):
            return self.cm.error(f'Intel oneAPI comes under Intel\'s End User License Agreement for Developer Tools ({EULA_URL}): '
                                 f'read it there and run again with --with.accept_eula=yes '
                                 f'(in a program: --use.oneapi.with.accept_eula=yes)')

        url = str(release['url'])
        filename = url.rsplit('/', 1)[-1]
        work = os.getcwd()
        downloads = os.path.join(work, 'downloads')
        installer = os.path.join(downloads, filename)

        if con:
            print ('')
            print (f'{space}INFO: Intel Deep Learning Essentials {name} (build {release.get("build")}) from {url}')
            print (f'{space}      (Intel\'s EULA accepted by the user: {EULA_URL})')

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                            'arg1': 'download-file,03fed13e2e0447cf',
                            'url': url, 'directory': 'downloads', 'filename': filename,
                            'env': params.get('env'), 'timeout': params.get('timeout'),
                            'con': con, 'quiet': quiet, 'verbose': verbose,
                            'unzip': False, 'check_file': installer})
        if self.cm.catch_error(r): return r

        digest, expected = sha256_of(installer), release.get('sha256')
        if expected and digest != str(expected):
            return self.cm.error(f'{filename}: sha256 {digest} is not the known {expected} (the file changed, or the download is broken)')
        if not expected and con:
            print (f'{space}WARNING: the tool knows no checksum of {filename} (sha256 of this download: {digest})')

        log = os.path.join(work, 'log')

        install_dir = str(_with.get('install_dir') or '').strip()

        if uname == 'windows':
            # The setup task runs the command, with its rule for administrator rights, and detects again after it
            gui = truthy(_with.get('gui'))
            vs_integration = str(_with.get('vs_integration', 'yes')).strip().lower() not in ('no', 'false', '0', 'off')
            if con:
                if gui:
                    print (f'{space}      with the wizard of Intel (--with.gui): the folder, the licence and the Visual Studio integration are its pages')
                else:
                    print (f'{space}      into {install_dir or "the folder Intel chooses (beside the oneAPI of this machine, else its default)"}'
                           + ('' if vs_integration else ', without the Visual Studio integration'))
            return {'return': 0, 'install_cmd': windows_command(installer, log, install_dir, gui, vs_integration)}

        if install_dir and con:
            print (f'{space}WARNING: --with.install_dir is for Windows: on Linux the release goes into this cache entry')

        folder = os.path.join(work, 'content')
        extract = os.path.join(work, 'extract')
        packages = os.path.join(work, 'installer-packages')
        instance = instance_of(folder)

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                            'arg1': 'cmd,c9ba0a88df394d7f',
                            'cmd': linux_command(installer, folder, extract, log, instance, packages),
                            'env': params.get('env'), 'timeout': params.get('timeout'),
                            'con': con, 'quiet': quiet, 'verbose': verbose,
                            'text_cmd': 'RUN:', 'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(r): return r
        if r.get('returncode', 1) != 0:
            return self.cm.error(f'Intel\'s installer ended with code {r.get("returncode")}: its log is in {log}')

        found = vars_scripts(folder, uname)
        if len(found) != 1:
            return self.cm.error(f'Intel\'s installer ended well, but {folder} has {len(found)} releases with '
                                 f'{VARS_SCRIPT[uname]} (expected one): {", ".join(found) or "none"}')

        # Intel's own installer of a user without root: what removes the instance again (README.tech.md)
        intel_installer = user_installer()
        remove = []
        if intel_installer:
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'cmd,c9ba0a88df394d7f',
                                'cmd': f'"{intel_installer}" --list-products --instance {instance}',
                                'env': params.get('env'), 'timeout': 300,
                                'con': False, 'quiet': quiet, 'verbose': False,
                                'capture_output': True, 'fail_if_nonzero_return_code': False})
            if r['return'] == 0 and r.get('returncode', 1) == 0:
                remove = removal_commands(intel_installer, r.get('stdout') or '', instance)

        with open(os.path.join(folder, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'package': 'Intel Deep Learning Essentials', 'release': name, 'build': release.get('build'),
                       'url': url, 'sha256': digest, 'instance': instance, 'eula': EULA_URL,
                       'installed': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec = 'seconds'),
                       'remove': remove},
                      f, indent = 2)

        for leftover in (downloads, extract, packages):
            shutil.rmtree(leftover, ignore_errors = True)

        return {'return': 0, 'install_cmd': None, 'found_path': found[0]}
