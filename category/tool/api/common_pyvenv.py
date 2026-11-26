"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Install a Python command-line tool into its own virtual environment, shared by the tools
whose api_v1.py only declares the package:

    from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv

    SPEC = {'name': 'yamllint', 'package': 'yamllint', 'python': '3.12'}

    def install(self, ctx, params, cmd=None, *misc):
        return install_pyvenv(self, ctx, params, cmd, SPEC)

and whose _desc.yaml pins the version installed when none is asked for:

    default_version: '1.38.0'

What it does:
  1. sets up tool/uv (detected, or installed without admin rights);
  2. creates a virtual environment in the tool's cache entry with the pinned Python version
     (uv downloads that Python if the machine has none) - so the tool never touches the
     system Python or another tool's packages;
  3. installs "<package>==<version>" (plus any pinned extras) with "uv pip install";
  4. returns the console script of the environment, which setup then detects and versions.

SPEC keys:
  name             the console script (without .exe)
  package          the PyPI package (default: name)
  python           Python version of the environment (e.g. '3.12': the machine's own of that version, else the one uv
                   downloads), or the path of an interpreter (a tool that must have the system's own Python)
  extra            more requirement strings installed alongside (e.g. 'ansible-core==2.21.4')
  unsupported_os   {uname: message} for systems the tool does not run on (e.g. Windows for Ansible)
  bin              {uname: folder of the environment} holding the command, for packages that install
                   their programs as data rather than console scripts (impi-rt on Windows: Library/bin);
                   default bin, or Scripts on Windows
  c_compiler       True for a package that builds a C extension from source (python-augeas, which certbot's
                   Apache plugin needs, publishes no wheels): the C compiler of cMeta's compiler task is set up
                   first and passed to the build as CC - a machine without "cc" on its PATH works too
  (--with.exclude_newer=<YYYY-MM-DD | release> of the request: uv resolves the package's dependencies as of that
                   day - "release": the day after the pinned version was uploaded to PyPI; see resolution_date)
  c_libraries      the C libraries such a build compiles against, as the names of the tools that set them up first
                   (the tool's install_uses, e.g. ['lib-augeas']): their include and library folders go to the build's
                   CFLAGS and LDFLAGS, unless the compiler searches them anyway (/usr/include, /usr/lib) - Homebrew's
                   /opt/homebrew is not among Apple clang's folders
  index            the package index the environment is filled from INSTEAD of PyPI: a vendor's own index that carries
                   the package and what it needs (AMD's ROCm wheels: PyPI only has placeholders of the same names, so
                   the two are never mixed) - uv's --index-url. --with.exclude_newer=release reads the release day
                   from PyPI and is refused for such a package: a day (YYYY-MM-DD) is given instead

The version is not a SPEC key: default_version in the tool's _desc.yaml is the one place that says which
version cMeta installs by default (common_release.default_version reads it; a 'default_version' SPEC key of
a tool written before 0.46.1 is still read when the description has none).
"""

import datetime
import json
import os
import re
import urllib.error
import urllib.request

from tool_c393ba5c6fa14f66.api.common_release import default_version

PYPI_JSON = 'https://pypi.org/pypi/{package}/{version}/json'


def pypi_upload_day(package, version, timeout = 60):
    """The day (UTC, YYYY-MM-DD) the first file of a package's version was uploaded to PyPI; ValueError with the
    reason when PyPI does not say (no such version, no network)."""
    url = PYPI_JSON.format(package = package, version = version)
    try:
        with urllib.request.urlopen(url, timeout = timeout) as resp:
            data = json.loads(resp.read().decode('utf-8', 'replace'))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ValueError(f'PyPI does not say when {package} {version} was released ({url}: {e})')
    days = sorted(str(f.get('upload_time_iso_8601') or f.get('upload_time') or '')[:10] for f in data.get('urls') or [])
    days = [d for d in days if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d)]
    if not days:
        raise ValueError(f'PyPI names no upload time for {package} {version} ({url})')
    return days[0]


def resolution_date(asked, package, version, lookup = pypi_upload_day):
    """
    The day (YYYY-MM-DD) after which no release counts when a package's dependencies are resolved
    (--with.exclude_newer): the day asked for, or - for the word "release" - the day AFTER the pinned version was
    uploaded to PyPI, so that everything released up to that day counts and nothing later (an old release then gets
    the dependencies of its own time). '' when nothing is asked; ValueError for anything that is no day.
    """
    asked = str(asked or '').strip()
    if not asked or asked.lower() in ('false', 'no', 'off'):
        return ''
    if asked.lower() == 'release':
        if not version:
            raise ValueError(f'--with.exclude_newer=release needs a version of {package} (--version=<x.y.z>): the release day is that version\'s')
        day = datetime.date.fromisoformat(lookup(package, version)) + datetime.timedelta(days = 1)
        return day.isoformat()
    wrong = ValueError(f'--with.exclude_newer: a day (YYYY-MM-DD) or the word "release" (got "{asked}")')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}([T ].*)?', asked):
        raise wrong
    try:
        return datetime.date.fromisoformat(asked[:10]).isoformat()
    except ValueError:
        raise wrong


def searched_anyway(folder):
    """True for a folder the C compiler searches by itself: naming it with -I / -L could reorder the system's own."""
    f = folder.replace('\\', '/').rstrip('/')
    return f in ('/usr/include', '/usr/lib', '/usr/lib64') or f.startswith('/usr/lib/')


def library_flags(_global, names):
    """(CFLAGS, LDFLAGS) words for the include and library folders of the C libraries set up by these tools."""
    cflags, ldflags = [], []
    for name in names:
        paths = ((_global.get(name) or {}).get('features') or {}).get('paths') or {}
        for flag, words, folders in (('-I', cflags, paths.get('includes') or [paths.get('include')]),
                                     ('-L', ldflags, paths.get('libs') or [paths.get('lib')])):
            for d in folders:
                word = flag + (f'"{d}"' if d and ' ' in d else (d or ''))
                if d and not searched_anyway(d) and word not in words:
                    words.append(word)
    return cflags, ldflags


def index_words(index):
    """The words that make uv fill an environment from this package index instead of PyPI ('' for none); ValueError
    for what is no http(s) address or would break the command line."""
    index = str(index or '').strip()
    if not index:
        return ''
    if not re.fullmatch(r'https?://[A-Za-z0-9._~:/@%+=-]+', index):
        raise ValueError(f'the package index "{index}" is no plain http(s) address')
    return f' --index-url {index}'


def install_pyvenv(tool, ctx, params, cmd, spec):
    """The tool's install() hook for a pinned PyPI package in its own environment (see the module docstring)."""
    _global = ctx['tasks']['global']
    uname = _global['host']['os']['uname']
    c = params.get('control', {})
    con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

    message = (spec.get('unsupported_os') or {}).get(uname)
    if message:
        return tool.cm.error(message)

    version = params.get('version')
    version_simple = params.get('version_simple')
    if not version:
        version = version_simple = default_version(tool, spec)
        if not version:
            return tool.cm.error(f'{spec["name"]} pins no default_version in its _desc.yaml: give --version=<version>')
    requirement = spec.get('package', spec['name']) + ('==' + version_simple if version_simple else version)

    r = tool.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                        'ctx': ctx, 'name': 'uv,92f171fc18714ebd', 'con': con, 'quiet': quiet, 'verbose': verbose})
    if tool.cm.catch_error(r, fail16=True):
        return r
    uv = _global.get('uv', {}).get('qpath') or r.get('tool_path')

    venv = os.path.join(os.getcwd(), 'venv')
    exe = _global['host']['vars'].get('file_ext_exe', '')
    bindir = os.path.join(venv, 'Scripts' if uname == 'windows' else 'bin')
    python = os.path.join(bindir, 'python' + exe)

    # A source build of a C extension: the C compiler of the pipeline (global "compiler-c"), set up if needed
    env = {}
    if spec.get('c_compiler'):
        if 'compiler-c' not in _global:
            r = tool.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'compiler,f3925b201c704bde',
                                'ctx': ctx, 'lang': 'c', 'con': con, 'quiet': quiet, 'verbose': verbose})
            if tool.cm.catch_error(r, fail16=True):
                return r
        cc = (_global.get('compiler-c') or {}).get('path')
        if not cc:
            return tool.cm.error(f'{spec["name"]} builds a C extension, but no C compiler was set up')
        env['CC'] = cc

    # ... and the C libraries it compiles against, after what the caller's CFLAGS / LDFLAGS say ("'augeas.h' file not
    # found" for python-augeas with Homebrew's augeas on macOS, 2026-11-24)
    cflags, ldflags = library_flags(_global, spec.get('c_libraries') or [])
    if cflags:
        env['CFLAGS'] = ' '.join([w for w in [os.environ.get('CFLAGS', '')] if w] + cflags)
    if ldflags:
        env['LDFLAGS'] = ' '.join([w for w in [os.environ.get('LDFLAGS', '')] if w] + ldflags)

    def run(command, what):
        rr = tool.cm.utils.sys.run(command, env=env or None, con=con, verbose=verbose, text_cmd='RUN', space=space)
        if rr['return'] > 0:
            return rr
        if rr.get('returncode', 0) != 0:
            return tool.cm.error(f'{what} failed (return code {rr.get("returncode")})')
        return {'return': 0}

    if not os.path.isfile(python):
        r = run(f'{uv} venv --python "{spec["python"]}" "{venv}"', f'creating a Python {spec["python"]} environment')
        if r['return'] > 0:
            return r
    reqs = ' '.join(f'"{x}"' for x in [requirement] + list(spec.get('extra', [])))

    # A vendor's own package index instead of PyPI (SPEC key "index")
    try:
        source = index_words(spec.get('index'))
    except ValueError as e:
        return tool.cm.error(str(e))
    if source and con:
        print(f'{space}INFO: {requirement} and what it needs come from {str(spec["index"]).strip()} (not from PyPI)')

    # --with.exclude_newer=<day | release>: the dependencies as they were on that day (uv's --exclude-newer)
    asked_day = (params.get('with') or {}).get('exclude_newer')
    if source and str(asked_day or '').strip().lower() == 'release':
        return tool.cm.error(f'--with.exclude_newer=release reads the release day from PyPI, and {requirement} comes from '
                             f'{str(spec["index"]).strip()}: give the day (YYYY-MM-DD)')
    try:
        day = resolution_date(asked_day, spec.get('package', spec['name']), version_simple)
    except ValueError as e:
        return tool.cm.error(str(e))
    older = f' --exclude-newer {day}' if day else ''
    if day and con:
        print(f'{space}INFO: the dependencies of {requirement} are resolved as of {day} (--with.exclude_newer)')

    r = run(f'{uv} pip install{older}{source} --python "{python}" {reqs}', f'installing {requirement}')
    if r['return'] > 0:
        return r

    sub = (spec.get('bin') or {}).get(uname)
    cmddir = os.path.join(venv, *sub.split('/')) if sub else bindir
    found = os.path.join(cmddir, spec['name'] + exe)
    if not os.path.isfile(found):
        return tool.cm.error(f'{requirement} was installed but its "{spec["name"]}" command is missing in {cmddir}')
    return {'return': 0, 'install_cmd': None, 'found_path': found}
