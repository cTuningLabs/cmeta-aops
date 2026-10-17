"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

NVIDIA NemoClaw (https://github.com/NVIDIA/NemoClaw, Apache-2.0): the CLI built as upstream's installer builds it
(scripts/install.sh of the release tag), into the cache entry and without its system changes (no nvm, no npm link
into a global prefix, no OpenShell package):

    git clone --depth 1 --branch v<version> https://github.com/NVIDIA/NemoClaw content/NemoClaw-<version>
    node scripts/lib/openshell-sdk-install.mts prepare      # the reviewed OpenShell SDK archive into npm's cache
    npm install --ignore-scripts --prefer-offline --include=optional --@nvidia:registry=https://npm.pkg.github.com
    node scripts/lib/openshell-sdk-install.mts check
    npm run --if-present build:cli
    (nemoclaw/) npm ci --ignore-scripts && npm run build

with cMeta's git and Node.js (tool/node-js, 22.19 or newer), npm's cache in the entry. The launcher content/bin/nemoclaw
runs bin/nemoclaw.js with that Node and sets NEMOCLAW_OPENSHELL_BIN to cMeta's OpenShell CLI when it has one.
"""

import os
import re
import stat
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

REPOSITORY = 'https://github.com/NVIDIA/NemoClaw'
MIN_NODE = (22, 19, 0)

BUILD = [
    ('', ['node', 'scripts/lib/openshell-sdk-install.mts', 'prepare']),
    ('', ['npm', 'install', '--ignore-scripts', '--prefer-offline', '--include=optional',
          '--@nvidia:registry=https://npm.pkg.github.com']),
    ('', ['node', 'scripts/lib/openshell-sdk-install.mts', 'check']),
    ('', ['npm', 'run', '--if-present', 'build:cli']),
    ('nemoclaw', ['npm', 'ci', '--ignore-scripts']),
    ('nemoclaw', ['npm', 'run', 'build']),
]


def launcher_text(node, script, openshell = ''):
    """The launcher: NemoClaw's bin/nemoclaw.js with cMeta's Node (and its OpenShell CLI when known)."""
    q = lambda s: "'" + str(s).replace("'", "'\"'\"'") + "'"
    lines = ['#!/bin/sh', '# Written by cMeta (tool/nemoclaw): NemoClaw with the Node.js it was built with']
    if openshell:
        lines.append(f': "${{NEMOCLAW_OPENSHELL_BIN:={openshell}}}"')
        lines.append('export NEMOCLAW_OPENSHELL_BIN')
        lines.append(f'PATH={q(os.path.dirname(openshell))}:"$PATH"; export PATH')
    lines.append(f'PATH={q(os.path.dirname(node))}:"$PATH"; export PATH')
    lines.append(f'exec {q(node)} {q(script)} "$@"')
    return '\n'.join(lines) + '\n'


def node_ok(text):
    """Whether "node --version" says 22.19 or newer."""
    m = re.search(r'v?(\d+)\.(\d+)\.(\d+)', text or '')
    return bool(m) and tuple(int(x) for x in m.groups()) >= MIN_NODE


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _setup(self, ctx, params, name):
        c = params.get('control', {})
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                            'ctx': ctx, 'name': name, 'con': c.get('con', False), 'quiet': c.get('quiet', False),
                            'verbose': c.get('verbose', False)})
        return r

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The pinned (or requested) release tag cloned and built into content/ (see the module docstring).
        """
        uname = ctx['tasks']['global']['host']['os']['uname']
        c = params.get('control', {})
        con = c.get('con', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if c.get('verbose') else ''

        if uname == 'windows':
            return self.cm.error('NemoClaw runs on Linux and macOS: on Windows set it up in WSL2 (cx tool setup nemoclaw --on=wsl)')

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc.get('default_version'))
        if not version:
            return self.cm.error(f'the NemoClaw build needs an exact release such as {self.cdesc.get("default_version")}')

        r = self._setup(ctx, params, 'git,959d8c0fbc004bd0')
        if self.cm.catch_error(r, fail16 = True): return r
        git = r.get('path') or 'git'

        r = self._setup(ctx, params, 'node-js,238f15e1d6184359')
        if self.cm.catch_error(r, fail16 = True): return r
        node = r.get('path') or ''
        p = subprocess.run([node, '--version'], stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        if not node_ok(p.stdout.decode('utf-8', 'replace')):
            return self.cm.error(f'NemoClaw needs Node.js 22.19 or newer, {node} is {p.stdout.decode().strip()}: '
                                 f'cx tool setup node-js --version=<a newer one> --new')

        # cMeta's OpenShell CLI for NemoClaw (optional: an OpenShell of NemoClaw's own installer works as well)
        r = self._setup(ctx, params, 'openshell,7990c822d96f41d4')
        openshell = r.get('path', '') if r['return'] == 0 else ''

        entry = os.getcwd()
        src = os.path.join(entry, 'content', f'NemoClaw-{version}')
        env = dict(os.environ, PATH = os.path.dirname(node) + os.pathsep + os.environ.get('PATH', ''),
                   npm_config_cache = os.path.join(entry, 'npm-cache'), npm_config_update_notifier = 'false',
                   npm_config_fund = 'false', npm_config_audit = 'false')

        def run(args, cwd, what):
            if con:
                print(f'{space}RUN: {" ".join(args)}  (in {cwd})')
            p = subprocess.run(args, cwd = cwd, env = env, stdin = subprocess.DEVNULL)
            if p.returncode != 0:
                return self.cm.error(f'{what} failed (return code {p.returncode})')
            return {'return': 0}

        if not os.path.isdir(os.path.join(src, '.git')):
            os.makedirs(os.path.dirname(src), exist_ok = True)
            r = run([git, 'clone', '--depth', '1', '--branch', f'v{version}', REPOSITORY, src], entry,
                    f'cloning NemoClaw v{version}')
            if r['return'] > 0: return r

        for sub, args in BUILD:
            r = run(args, os.path.join(src, sub) if sub else src, ' '.join(args[:3]))
            if r['return'] > 0: return r

        script = os.path.join(src, 'bin', 'nemoclaw.js')
        if not os.path.isfile(script):
            return self.cm.error(f'NemoClaw v{version} was built in {src} but has no bin/nemoclaw.js')
        launcher = os.path.join(entry, 'content', 'bin', 'nemoclaw')
        os.makedirs(os.path.dirname(launcher), exist_ok = True)
        with open(launcher, 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write(launcher_text(node, script, openshell))
        os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return {'return': 0, 'install_cmd': None, 'found_path': launcher}
