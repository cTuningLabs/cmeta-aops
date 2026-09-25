"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Custom installer and builder for the AKS Flex Node agent ("aks-flex-node",
https://github.com/Azure/AKSFlexNode, MIT).

install() - tier 1: the official release archive. Upstream publishes
    aks-flex-node-linux-{amd64,arm64}.tar.gz and checksums.txt per release; the
    archive holds one binary named after the archive. We download both files,
    verify the SHA-256, unpack, and name the binary "aks-flex-node". On any
    other OS or architecture we return 16, so setup can fall back (there is no
    package-manager route) and --build can take over.

build() - from git, on Linux: clone the repository into the cMeta cache
    (clone-git-to-cache) at v<version>, or at --with.checkout=<tag|branch|commit>, set up
    go (tool/go) and run "go build", stamping Version, GitCommit and BuildTime
    exactly as upstream's Makefile does, so "aks-flex-node version" reports them.
    The agent and its dependencies are Linux-only; on Windows and macOS use WSL or
    a Linux container (the same cx commands work there).
"""

import datetime
import hashlib
import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

REPO_URL = 'https://github.com/Azure/AKSFlexNode'
DEFAULT_VERSION = '0.2.0'
VERSION_PKG = 'github.com/Azure/AKSFlexNode/pkg/cmd/version'

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _control(self, ctx, params):
        c = params.get('control', {})
        con = c.get('con', False)
        verbose = c.get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        return con, c.get('quiet', False), verbose, space

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Download, verify and unpack the official Linux release archive.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')
        if not version:
            version = version_simple = DEFAULT_VERSION

        if uname != 'linux' or uarch not in ('amd64', 'arm64'):
            return {'return': 16,
                    'error': f'AKS Flex Node publishes release archives for Linux amd64/arm64 only (this host: '
                             f'{uname}/{uarch}); build it from git with --build --skip_install',
                    'install_cmd': cmd}

        if not version_simple:
            return {'return': 16,
                    'error': f'the AKS Flex Node release download needs an exact x.y.z version; for a branch or '
                             f'commit use --build --skip_install --with.checkout=<ref>',
                    'install_cmd': cmd}

        con, quiet, verbose, space = self._control(ctx, params)
        env = params.get('env')
        timeout = params.get('timeout')

        tag = 'v' + version_simple
        archive = f'aks-flex-node-linux-{uarch}.tar.gz'
        base_url = f'{REPO_URL}/releases/download/{tag}'

        directory = 'content'
        path_dir = os.path.join(os.getcwd(), directory)
        path_archive = os.path.join(path_dir, archive)
        path_checksums = os.path.join(path_dir, 'checksums.txt')
        path_unpacked = os.path.join(path_dir, f'aks-flex-node-linux-{uarch}')
        path_tool = os.path.join(path_dir, 'aks-flex-node')

        if con:
            print('')
            print(f'{space}INFO: AKS Flex Node release: {base_url}/{archive}')

        for url, check_file in [(f'{base_url}/checksums.txt', path_checksums), (f'{base_url}/{archive}', path_archive)]:
            rx = self.cm.access({'category': 'task,c36be4b9314a45e0',
                                 'command': 'run',
                                 'arg1': 'download-file,03fed13e2e0447cf',
                                 'ctx': ctx,
                                 'url': url,
                                 'directory': directory,
                                 'env': env,
                                 'timeout': timeout,
                                 'con': con,
                                 'quiet': quiet,
                                 'verbose': verbose,
                                 'unzip': False,
                                 'check_file': check_file})
            if self.cm.catch_error(rx): return rx

        # Verify the archive against the release's checksums.txt ("<sha256>  <file name>" lines)
        r = self.cm.utils.files.safe_read_file(path_checksums)
        if self.cm.catch_error(r): return r
        expected = None
        for line in str(r['data']).splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip('*') == archive:
                expected = parts[0].lower()
        if not expected:
            return self.cm.error(f'{archive} is not listed in the checksums.txt of release {tag}')

        h = hashlib.sha256()
        with open(path_archive, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        if h.hexdigest() != expected:
            return self.cm.error(f'SHA-256 mismatch for {archive} of release {tag}: '
                                 f'expected {expected}, got {h.hexdigest()}')
        if con:
            print(f'{space}INFO: SHA-256 verified against checksums.txt ({expected[:16]}...)')

        # The archive holds exactly one regular file; extract only that member (no tar binary needed)
        import tarfile
        with tarfile.open(path_archive, 'r:gz') as t:
            try:
                member = t.getmember(os.path.basename(path_unpacked))
            except KeyError:
                return self.cm.error(f'{os.path.basename(path_unpacked)} is not in {archive}')
            if not member.isfile():
                return self.cm.error(f'unexpected entry type in {archive}: {member.name}')
            with t.extractfile(member) as src, open(path_unpacked, 'wb') as dst:
                dst.write(src.read())

        if not os.path.isfile(path_unpacked):
            return self.cm.error(f'{os.path.basename(path_unpacked)} was not found after unpacking {archive}')
        if os.path.isfile(path_tool):
            os.remove(path_tool)
        os.replace(path_unpacked, path_tool)
        os.chmod(path_tool, 0o755)

        return {'return': 0, 'install_cmd': None, 'found_path': path_tool}

    ############################################################
    def build(self,
              ctx: dict,
              params: dict,
    ):
        """
        Build aks-flex-node from git with the go tool.
        """

        _global = ctx['tasks']['global']
        _local = ctx['tasks']['local']
        exe = _global['host']['vars']['file_ext_exe']

        con, quiet, verbose, space = self._control(ctx, params)
        env = params.get('env') or {}
        timeout = params.get('timeout')

        uname = _global['host']['os']['uname']
        if uname != 'linux':
            # Its dependencies (umoci, unbounded, renameio) use Linux-only syscalls: checked 2026-09-25
            # at v0.2.0 on Windows ("undefined: unix.Mknod", "undefined: renameio.WriteFile", ...)
            return self.cm.error(f'the AKS Flex Node agent builds and runs on Linux only (this host: {uname}); '
                                 f'use WSL or a Linux container, where "cx tool setup aks-flex-node" downloads '
                                 f'the release and "--build --skip_install" builds it from git')

        version = params.get('version_simple') or params.get('version') or DEFAULT_VERSION
        checkout = (params.get('with') or {}).get('checkout') or ('v' + version)

        # 1. The source, cached by cMeta (reused across builds of the same revision)
        rx = self.cm.access({'category': 'task,c36be4b9314a45e0',
                             'command': 'run',
                             'arg1': 'clone-git-to-cache,86919b3cfdd443d2',
                             'ctx': ctx,
                             'name': 'aks-flex-node-src',
                             'url': REPO_URL,
                             'checkout': checkout,
                             'con': con,
                             'quiet': quiet,
                             'verbose': verbose})
        if self.cm.catch_error(rx): return rx
        path_src = rx['path_to_git_repo']
        commit = rx.get('checkout') or 'unknown'

        # 2. Go (go.mod pins the language version; GOTOOLCHAIN=auto fetches a newer toolchain if needed)
        rx = self.cm.access({'category': 'task,c36be4b9314a45e0',
                             'command': 'run',
                             'arg1': 'setup,a2f9b61079ce4333',
                             'ctx': ctx,
                             'name': 'go,8387494b5d574044',
                             'con': con,
                             'quiet': quiet,
                             'verbose': verbose})
        if self.cm.catch_error(rx, fail16=True): return rx
        go = _global.get('go', {}).get('qpath') or rx.get('tool_path')
        if not go:
            return self.cm.error('go was set up but its path is unknown')

        # 3. Build for the host OS, stamped like upstream's Makefile
        target_path = _local.get('target_path') or os.path.join(os.getcwd(), 'build')
        os.makedirs(target_path, exist_ok=True)
        path_tool = os.path.join(target_path, 'aks-flex-node' + exe)

        # Version = "git describe --tags --always" as in upstream's Makefile (v0.2.0, or
        # v0.2.1-alpha.1-5-g7f814fb on a branch), so detection can parse it
        git = _global.get('git', {}).get('qpath', 'git')
        r = self.cm.utils.sys.run(f'{git} -C "{path_src}" describe --tags --always', capture_output=True,
                                  con=False, verbose=verbose)
        stamp_version = (r.get('stdout') or '').strip() if r['return'] == 0 else ''
        if not stamp_version:
            stamp_version = checkout
        build_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ldflags = (f'-X {VERSION_PKG}.Version={stamp_version} -X {VERSION_PKG}.GitCommit={commit[:7]} '
                   f'-X {VERSION_PKG}.BuildTime={build_time} -w -s')

        benv = dict(env)
        benv.setdefault('CGO_ENABLED', '0')
        benv.setdefault('GOTOOLCHAIN', 'auto')

        cmd = f'cd "{path_src}" && {go} build -ldflags "{ldflags}" -o "{path_tool}" ./cmd/aks-flex-node'
        r = self.cm.utils.sys.run(cmd, env=benv, timeout=timeout, con=con, verbose=verbose,
                                  text_cmd='RUN', space=space)
        if self.cm.catch_error(r): return r
        if r.get('returncode', 0) != 0 or not os.path.isfile(path_tool):
            return self.cm.error(f'go build of aks-flex-node {checkout} failed (return code {r.get("returncode")})')

        return {'return': 0, 'found_path': path_tool}
