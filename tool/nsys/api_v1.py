"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/nsys: NVIDIA Nsight Systems' command line, found where a CUDA toolkit or an Nsight Systems install put it
(_desc.yaml extra_paths), else installed without root from NVIDIA's CUDA redistributable archives: the component
nsight_systems of a CUDA release, checked against the sha256 of NVIDIA's list and unpacked into this cache entry.
--version=<nsys version> (2026.1.3.425, or a prefix such as 2026.1) takes the newest CUDA release that carries it;
without one, the release of the newest CUDA this driver runs. tool/nvcc's redist.py reads NVIDIA's lists.
"""

import importlib.util
import os
import sys

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# The tool whose redist.py reads NVIDIA's CUDA redistributable archives, and the component of Nsight Systems there
NVCC = 'nvcc,7f0e9193fef74919'
COMPONENT = 'nsight_systems'


def nsys_version(m):
    """The Nsight Systems version of a CUDA release's manifest (2026.1.3.425), or None."""
    entry = m.get(COMPONENT)
    return entry.get('version') if isinstance(entry, dict) else None


def pick(releases, manifest_of, wanted = None, matches = None, newest_for_driver = None):
    """
    (release, nsys version) to install from the releases of NVIDIA's list (oldest first):
      - with wanted, the newest release whose Nsight Systems matches it (matches(wanted, version));
      - without, newest_for_driver (the newest release this driver runs) when it carries Nsight Systems, else the
        newest older one that does.
    (None, why) when none does.
    """
    if wanted:
        for release in reversed(releases):
            v = nsys_version(manifest_of(release))
            if v and matches(wanted, v):
                return release, v
        span = f' ({releases[0]} to {releases[-1]})' if releases else ''
        return None, f'Nsight Systems {wanted} not available in NVIDIA\'s CUDA archives{span}'

    end = releases.index(newest_for_driver) + 1 if newest_for_driver in releases else len(releases)
    for release in reversed(releases[:end]):
        v = nsys_version(manifest_of(release))
        if v:
            return release, v
    return None, 'no CUDA release of NVIDIA\'s list carries Nsight Systems'


# How Nsight Systems names a CPU at the end of its target folders (target-windows-x64, target-windows-armv8)
ARCH_WORDS = {'amd64': 'x64', 'arm64': 'armv8'}


def find_nsys(root, exe = '', system = None, uarch = None):
    """
    The command line of an unpacked Nsight Systems: nsys[.exe] in a target-<system>-...<cpu> folder - at the top of
    the Linux archive, under nsight-systems/<version>/ in the Windows one (host-* holds the GUI and the scripts of the
    reports). An archive carries the command lines of other targets too (Windows: target-windows-armv8 beside
    target-windows-x64, and target-linux-x64 for remote targets): with system (linux, windows) and uarch (amd64,
    arm64), only the folder of this system and CPU is taken - never another one. None when there is none.
    """
    if not os.path.isdir(root):
        return None
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.relpath(dirpath, root).count(os.sep) >= 3:
            dirnames[:] = []
        if os.path.basename(dirpath).startswith('target-') and 'nsys' + exe in filenames:
            found.append(os.path.join(dirpath, 'nsys' + exe))
    found.sort()
    if not system:
        return found[0] if found else None

    def ours(path):
        name = os.path.basename(os.path.dirname(path))
        return name.startswith('target-' + system + '-') and (not uarch or name.endswith(ARCH_WORDS.get(uarch, uarch)))

    mine = [f for f in found if ours(f)]
    return mine[0] if mine else None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _redist(self):
        """tool/nvcc's redist.py (found by its UID), or (None, why)."""
        name = 'cmeta_tool_nvcc_redist'
        if name in sys.modules:
            return sys.modules[name], None
        r = self.cm.access({'category': 'tool', 'command': 'find', 'arg1': NVCC, 'con': False})
        if r['return'] > 0 or not r.get('artifacts'):
            return None, f'tool {NVCC}, which reads NVIDIA\'s CUDA archives, is not found: {r.get("error", "")}'
        path = os.path.join(r['artifacts'][0]['path'], 'redist.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
        return module, None

    ############################################################
    def _driver_cuda(self, ctx):
        """The CUDA version of the driver (13.3), from tool/cuda, or None."""
        cuda = ctx['tasks']['global'].get('cuda', {}).get('features', {})
        v = str((cuda.get('versions') or {}).get('cuda version') or '')
        return v if v[:1].isdigit() else None

    ############################################################
    def _choose(self, ctx, redist, wanted):
        """(release, nsys version, manifest) or (None, why, None); NVIDIA's lists read once per release."""
        manifests = {}

        def manifest_of(release):
            if release not in manifests:
                manifests[release] = redist.manifest(release)
            return manifests[release]

        def matches(spec, version):
            return self.cm.packages.match_version(spec, version).get('matched', False)

        releases = redist.releases()
        newest = None
        if not wanted:
            newest, _ = redist.choose(releases, None, None, self._driver_cuda(ctx), None, None, None)
        release, v = pick(releases, manifest_of, wanted, matches, newest)
        return release, v, manifests.get(release)

    ############################################################
    def latest_version(self, ctx, params):
        """
        The Nsight Systems of the newest CUDA release this driver runs - the one an install without --version
        takes - for --status, --upgrade and --version=latest (task/setup asks for it).
        """
        redist, why = self._redist()
        if redist is None:
            return {'return': 16, 'error': why}
        try:
            release, v, _ = self._choose(ctx, redist, None)
        except (OSError, ValueError) as e:
            return {'return': 16, 'error': f'cannot read the list of CUDA releases at {redist.BASE}: {e}'}
        if not release:
            return {'return': 16, 'error': v}
        return {'return': 0, 'version': v, 'source': f'CUDA {release} - {redist.BASE}'}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Nsight Systems from NVIDIA's CUDA redistributable archives into content/<release>/ of this cache entry (see
        the module); its archive checked against the sha256 of NVIDIA's list.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        redist, why = self._redist()
        if redist is None:
            return self.cm.error(why)

        platform = redist.platform_of(uname, uarch)
        if not platform:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'nsys publishes no release asset for {uname}/{uarch} in NVIDIA\'s CUDA archives'}

        try:
            release, v, m = self._choose(ctx, redist, params.get('version'))
        except (OSError, ValueError) as e:
            return self.cm.error(f'cannot read the list of CUDA releases at {redist.BASE}: {e}')
        if not release:
            return {'return': 16, 'install_cmd': cmd, 'error': v}

        archives = redist.components(m, platform, [COMPONENT])
        if not archives:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'nsys publishes no release asset for {uname}/{uarch} in CUDA {release}'}
        _, relative_path, sha, size = archives[0]
        filename = relative_path.rsplit('/', 1)[-1]

        if con:
            print ('')
            print (f'{space}INFO: Nsight Systems {v} of CUDA {release} for {platform} ({size / 2**20:.0f} MiB) '
                   f'from {redist.BASE}')

        # the cache entry: downloads/ for the archive, content/<release>/ for Nsight Systems
        work = os.getcwd()
        root = os.path.join(work, 'content', release)

        try:
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'chdir': work,
                                'url': f'{redist.BASE}/{relative_path}', 'directory': 'downloads',
                                'filename': filename, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r): return r
        finally:
            os.chdir(work)

        archive = os.path.join(work, 'downloads', filename)
        digest = redist.sha256_of(archive)
        if sha and digest != sha:
            return self.cm.error(f'{filename}: sha256 {digest} is not the {sha} of NVIDIA\'s list')

        try:
            redist.unpack_into(archive, root)
        except (OSError, ValueError) as e:
            return self.cm.error(f'cannot unpack {filename} into {root}: {e}')
        os.remove(archive)

        nsys = find_nsys(root, '.exe' if uname == 'windows' else '', uname, uarch)
        if not nsys:
            return self.cm.error(f'Nsight Systems {v} was unpacked into {root} but has no nsys for {uname}/{uarch} '
                                 f'(a target-{uname}-...{ARCH_WORDS.get(uarch, uarch)} folder)')

        return {'return': 0, 'install_cmd': None, 'found_path': nsys}
