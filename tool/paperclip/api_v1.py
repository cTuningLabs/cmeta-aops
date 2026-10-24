"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Paperclip (https://github.com/paperclipai/paperclip, MIT): its CLI "paperclipai" from npm, installed into the cache
entry with cMeta's Node.js (tool/node-js, 24.11 or newer) - not into a global npm prefix and not through npx:

    npm install --prefix content --no-save --no-audit --no-fund paperclipai@<version>

with npm's cache in the entry, then a launcher content/bin/paperclipai (paperclipai.cmd on Windows) that runs
content/node_modules/paperclipai/dist/index.js with that Node. The launcher turns Paperclip's anonymous telemetry off
(PAPERCLIP_TELEMETRY_DISABLED=1) unless the caller set the variable, and puts its Node first on the PATH (the server
starts child processes with "node").
"""

import os
import re
import stat
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

PACKAGE = 'paperclipai'
MIN_NODE = (24, 11, 0)
NODE_TOOL = 'node-js,238f15e1d6184359'

# Asked for when the Node.js found here is older than MIN_NODE: the node-js tool's default (an LTS of 24.x)
NODE_FALLBACK = '24.21.0'


def node_version(text):
    """"v24.21.0" (node --version) -> (24, 21, 0), or None."""
    m = re.search(r'v?(\d+)\.(\d+)\.(\d+)', text or '')
    return tuple(int(x) for x in m.groups()) if m else None


def launcher_posix(node, script):
    """The launcher of Linux and macOS: the CLI with cMeta's Node, telemetry off unless asked for."""
    q = lambda s: "'" + str(s).replace("'", "'\"'\"'") + "'"
    return '\n'.join([
        '#!/bin/sh',
        '# Written by cMeta (tool/paperclip): the Paperclip CLI with the Node.js it was installed with',
        '',
        ': "${PAPERCLIP_TELEMETRY_DISABLED:=1}"',
        'export PAPERCLIP_TELEMETRY_DISABLED',
        f'PATH={q(os.path.dirname(node))}:"$PATH"; export PATH',
        '',
        f'exec {q(node)} {q(script)} "$@"',
        ''])


def launcher_cmd(node, script):
    """The launcher of Windows (cmd): the same."""
    return '\r\n'.join([
        '@echo off',
        'rem Written by cMeta (tool/paperclip): the Paperclip CLI with the Node.js it was installed with',
        '',
        'if not defined PAPERCLIP_TELEMETRY_DISABLED set "PAPERCLIP_TELEMETRY_DISABLED=1"',
        f'set "PATH={os.path.dirname(node)};%PATH%"',
        '',
        f'"{node}" "{script}" %*',
        ''])


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _node(self, ctx, params, version = ''):
        """cMeta's Node.js (the given version, else whichever the node-js tool finds or installs) -> (path, version tuple)."""
        c = params.get('control', {})
        request = {'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333', 'ctx': ctx,
                   'name': NODE_TOOL, 'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)}
        if version:
            request['version'] = version
        r = self.cm.access(request)
        if r['return'] > 0:
            return r
        node = r.get('path') or ''
        p = subprocess.run([node, '--version'], stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        return {'return': 0, 'node': node, 'version': node_version(p.stdout.decode('utf-8', 'replace'))}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The pinned (or requested) version of the npm package installed into content/ (see the module docstring).
        """
        uname = ctx['tasks']['global']['host']['os']['uname']
        c = params.get('control', {})
        con = c.get('con', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if c.get('verbose') else ''

        version = params.get('version_simple') or (None if params.get('version') else self.cdesc.get('default_version'))
        if not version:
            return self.cm.error(f'the Paperclip installation needs an exact version such as {self.cdesc.get("default_version")}')

        # Node.js 24.11 or newer: the one found, else the node-js tool's LTS default, asked for by its version
        r = self._node(ctx, params)
        if self.cm.catch_error(r, fail16 = True): return r
        if not r['version'] or r['version'] < MIN_NODE:
            if con:
                print(f'{space}cMeta info: Paperclip needs Node.js {".".join(map(str, MIN_NODE))} or newer; {r["node"]} is '
                      f'{".".join(map(str, r["version"] or ())) or "unknown"} - setting up Node.js {NODE_FALLBACK}')
            r = self._node(ctx, params, NODE_FALLBACK)
            if self.cm.catch_error(r, fail16 = True): return r
            if not r['version'] or r['version'] < MIN_NODE:
                return self.cm.error(f'Paperclip needs Node.js {".".join(map(str, MIN_NODE))} or newer, {r["node"]} is older: '
                                     f'cx tool setup node-js --version=<a newer one> --new')
        node = r['node']

        entry = os.getcwd()
        content = os.path.join(entry, 'content')
        os.makedirs(content, exist_ok = True)
        npm = os.path.join(os.path.dirname(node), 'npm.cmd' if uname == 'windows' else 'npm')
        if not os.path.isfile(npm):
            return self.cm.error(f'no npm next to {node}')

        env = dict(os.environ, PATH = os.path.dirname(node) + os.pathsep + os.environ.get('PATH', ''),
                   npm_config_cache = os.path.join(entry, 'npm-cache'), npm_config_update_notifier = 'false',
                   npm_config_fund = 'false', npm_config_audit = 'false', PAPERCLIP_TELEMETRY_DISABLED = '1')

        # the public registry, whatever a ~/.npmrc of the user says (upstream's own advice for an E404)
        args = [npm, 'install', '--prefix', content, '--no-save', '--registry', 'https://registry.npmjs.org',
                f'{PACKAGE}@{version}']
        if con:
            print(f'{space}RUN: {" ".join(args)}')
        p = subprocess.run(args, cwd = entry, env = env, stdin = subprocess.DEVNULL, shell = (uname == 'windows'))
        if p.returncode != 0:
            return self.cm.error(f'npm install {PACKAGE}@{version} failed (return code {p.returncode})')

        script = os.path.join(content, 'node_modules', PACKAGE, 'dist', 'index.js')
        if not os.path.isfile(script):
            return self.cm.error(f'{PACKAGE}@{version} was installed in {content} but has no dist/index.js')

        bin_dir = os.path.join(content, 'bin')
        os.makedirs(bin_dir, exist_ok = True)
        if uname == 'windows':
            launcher = os.path.join(bin_dir, 'paperclipai.cmd')
            with open(launcher, 'w', encoding = 'utf-8', newline = '') as f:
                f.write(launcher_cmd(node, script))
        else:
            launcher = os.path.join(bin_dir, 'paperclipai')
            with open(launcher, 'w', encoding = 'utf-8', newline = '\n') as f:
                f.write(launcher_posix(node, script))
            os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        return {'return': 0, 'install_cmd': None, 'found_path': launcher}
