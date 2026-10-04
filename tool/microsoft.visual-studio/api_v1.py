"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# winget packages of Visual Studio Build Tools by release year (--with.year); the newest first
BUILD_TOOLS_WINGET_IDS = {
    '2026': 'Microsoft.VisualStudio.BuildTools',
    '2022': 'Microsoft.VisualStudio.2022.BuildTools',
    '2019': 'Microsoft.VisualStudio.2019.BuildTools',
    '2017': 'Microsoft.VisualStudio.2017.BuildTools',
}

# The cl.exe versions of each release (the tool's version is cl.exe's: 19.44 is Visual Studio 2022)
CL_MINORS = {'2026': (50, 59), '2022': (30, 49), '2019': (20, 29), '2017': (10, 19)}

VCVARS_DIR = os.path.join('VC', 'Auxiliary', 'Build')


def year_for(version, matches):
    """
    The newest Build Tools release whose cl.exe has the version asked for: a plain version
    (19.44.35217, 19.44) by its major.minor, a range (>=19.10,<19.50) by the newest minor in it;
    None when no release has it.
    """
    v = str(version or '').strip().lstrip('=')
    parts = v.split('.')
    if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
        major, minor = int(parts[0]), int(parts[1])
        if major != 19:
            return None
        return next((y for y, (lo, hi) in CL_MINORS.items() if lo <= minor <= hi), None)
    for year, (lo, hi) in CL_MINORS.items():
        if any(matches(version, f'19.{minor}.0') for minor in range(hi, lo - 1, -1)):
            return year
    return None


def version_of(artifact):
    """The cl.exe version a cache entry of this tool was made for ('' when it has none)."""
    return str(artifact.get('cmeta', {}).get('params', {}).get('version') or '')


def version_numbers(version):
    """19.50.35726 -> (19, 50, 35726): the key that orders cl.exe versions (a part that is no number counts 0)."""
    return tuple(int(p) if p.isdigit() else 0 for p in str(version or '').strip().lstrip('=').split('.'))


def is_exact_version(version):
    """True for one plain version (19.44, 19.44.35211, ==19.44); a range (<19.50, >=19.10,<19.50) or nothing is not."""
    v = str(version or '').strip().lstrip('=')
    return v != '' and all(p.isdigit() for p in v.split('.'))


def describe(version):
    """A cl.exe version with its Visual Studio release: '19.50.35726 (2026)'."""
    year = year_for(version, lambda *a: False)
    return f'{version} ({year})' if year else version


def vswhere_installations():
    """
    The installation folders of every Visual Studio 2017+ (any edition, Build Tools included,
    on any drive), as the Visual Studio Installer's vswhere lists them; [] without vswhere.
    """
    candidates = [shutil.which('vswhere')]
    for pf in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        if pf:
            candidates.append(os.path.join(pf, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe'))
    vswhere = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not vswhere:
        return []
    try:
        out = subprocess.run([vswhere, '-all', '-products', '*', '-property', 'installationPath', '-utf8'],
                             capture_output = True, timeout = 60)
    except Exception:
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.decode('utf-8', 'replace').splitlines() if line.strip()]


def standard_installations():
    """Visual Studio folders in the usual places: <Program Files[ (x86)]>\\Microsoft Visual Studio\\<year>\\<edition>."""
    roots = [os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
             r'D:\Program Files', r'D:\Program Files (x86)']
    found = []
    for root in dict.fromkeys(r for r in roots if r):
        found += sorted(glob.glob(os.path.join(root, 'Microsoft Visual Studio', '*', '*')))
    return found


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def find_paths(self,
                   ctx: dict,
                   params: dict = {},
    ):
        """
        The vcvars scripts of all Visual Studio installations with the C++ tools. vswhere lists
        them wherever they are (Build Tools go to Program Files (x86), Visual Studio 2026 can be
        on another drive); the usual folders are searched too, and the extra_paths of _desc.yaml
        (a recursive search) only when nothing else is found.
        """

        bits = ctx['tasks']['global']['host']['os'].get('bits') or '64'
        name = f'vcvars{bits}.bat'

        found = []
        seen = set()

        def add(path):
            key = os.path.normcase(os.path.normpath(path))
            if key not in seen and os.path.isfile(path):
                seen.add(key)
                found.append(path)

        for install_dir in vswhere_installations() + standard_installations():
            add(os.path.join(install_dir, VCVARS_DIR, name))

        if not found:
            for pattern in self.cdesc.get('extra_paths', {}).get('windows', []):
                for path in glob.glob(os.path.join(pattern, name), recursive = True):
                    add(path)

        return {'return': 0, 'found_paths': found}

    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str,
                              params: dict,
                              env: dict,
                              timeout,
                              uninstall_cmd: str = None,
    ):
        """
        The winget package of the Build Tools release: --with.year, else the release whose cl.exe
        has the version asked for (the tool's version is cl.exe's: 19.44 is 2022), else the
        newest (2026). A version that no release has stops here, before anything is installed.
        """

        year = params.get('with', {}).get('year')
        version = params.get('version')
        if not year and version:
            year = year_for(version, lambda spec, v: self.cm.packages.match_version(spec, v).get('matched', False))
            if not year:
                return self.cm.error(f'no Visual Studio Build Tools release has cl.exe {version}: the version of '
                                     f'this tool is cl.exe\'s (19.5x is 2026, 19.3x-19.4x 2022, 19.2x 2019, 19.1x 2017); '
                                     f'--with.year picks a release')
        year = str(year or '2026')
        winget_id = BUILD_TOOLS_WINGET_IDS.get(year)
        if not winget_id:
            return self.cm.error(f'unknown Visual Studio Build Tools release "{year}" '
                                 f'(--with.year: {", ".join(BUILD_TOOLS_WINGET_IDS)})')

        return {'return': 0, 'install_cmd': (install_cmd or '').replace('@VS_BUILD_TOOLS@', winget_id)}

    ############################################################
    def filter_tool_cache_artifacts(self,
                                    ctx: dict,
                                    artifacts: list,
                                    tmp_artifacts: list,
                                    params: dict,
                                    path: str = None,
                                    **extra,
    ):
        """
        A request that names no exact version (none at all, or a range such as nvcc's host-compiler
        limits), no vcvars script (tool_path) and no path takes the newest installation among the
        cached entries that match: the Visual Studio is the environment of a compiler whose version
        is decided already (msvc passes its version on, clang asks for none), not a choice to put to
        the user. The entries of that version all stay (one per Windows SDK). Before, two
        installations meant the question "More than 1 cache entry found" in every such run, and -q
        took the first - the newest, which this rule makes the answer without the question.
        """

        version = str(params.get('version') or '').strip()

        if is_exact_version(version) or params.get('tool_path') or path or len(artifacts) < 2:
            return {'return': 0}

        newest = max((version_of(a) for a in artifacts), key = version_numbers)
        kept = [a for a in artifacts if version_of(a) == newest]

        if len(kept) == len(artifacts):
            return {'return': 0}

        control = ctx.get('control', {})
        if control.get('con', False):
            space = '  ' * ctx.get('tasks', {}).get('nested_call', 0) if control.get('verbose', False) else ''
            others = sorted({version_of(a) for a in artifacts if version_of(a) != newest}, key = version_numbers, reverse = True)
            within = f' within {version}' if version else ''
            print (f"{space}INFO: {len(artifacts)} cached Visual Studio installations{within}: taking cl.exe {describe(newest)} "
                   f"({', '.join(describe(v) for v in others)} also would; "
                   f"--use.microsoft-visual-studio.version=<version> picks another)")

        return {'return': 0, 'artifacts': kept}
