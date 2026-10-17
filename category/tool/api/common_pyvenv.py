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
  python           Python version of the environment (e.g. '3.12')
  extra            more requirement strings installed alongside (e.g. 'ansible-core==2.21.4')
  unsupported_os   {uname: message} for systems the tool does not run on (e.g. Windows for Ansible)
  bin              {uname: folder of the environment} holding the command, for packages that install
                   their programs as data rather than console scripts (impi-rt on Windows: Library/bin);
                   default bin, or Scripts on Windows
  c_compiler       True for a package that builds a C extension from source (python-augeas, which certbot's
                   Apache plugin needs, publishes no wheels): the C compiler of cMeta's compiler task is set up
                   first and passed to the build as CC - a machine without "cc" on its PATH works too

The version is not a SPEC key: default_version in the tool's _desc.yaml is the one place that says which
version cMeta installs by default (common_release.default_version reads it; a 'default_version' SPEC key of
a tool written before 0.46.1 is still read when the description has none).
"""

import os

from tool_c393ba5c6fa14f66.api.common_release import default_version


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

    def run(command, what):
        rr = tool.cm.utils.sys.run(command, env=env or None, con=con, verbose=verbose, text_cmd='RUN', space=space)
        if rr['return'] > 0:
            return rr
        if rr.get('returncode', 0) != 0:
            return tool.cm.error(f'{what} failed (return code {rr.get("returncode")})')
        return {'return': 0}

    if not os.path.isfile(python):
        r = run(f'{uv} venv --python {spec["python"]} "{venv}"', f'creating a Python {spec["python"]} environment')
        if r['return'] > 0:
            return r
    reqs = ' '.join(f'"{x}"' for x in [requirement] + list(spec.get('extra', [])))
    r = run(f'{uv} pip install --python "{python}" {reqs}', f'installing {requirement}')
    if r['return'] > 0:
        return r

    sub = (spec.get('bin') or {}).get(uname)
    cmddir = os.path.join(venv, *sub.split('/')) if sub else bindir
    found = os.path.join(cmddir, spec['name'] + exe)
    if not os.path.isfile(found):
        return tool.cm.error(f'{requirement} was installed but its "{spec["name"]}" command is missing in {cmddir}')
    return {'return': 0, 'install_cmd': None, 'found_path': found}
