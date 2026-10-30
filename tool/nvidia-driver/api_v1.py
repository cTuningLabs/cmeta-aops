"""
The NVIDIA GPU driver as a cMeta tool (README.md): detected by nvidia-smi, installed and upgraded with NVIDIA's own
packages - on Windows the driver NVIDIA's download service lists for the GPU, on Linux the .run installer of NVIDIA's
archive. The releases and the rules are in drivers.py and _desc.yaml.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import hashlib
import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

from . import drivers

LINUX_MACHINES = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}


def run(cmd, timeout = 120):
    """(return code, output) of a command; never raises (127: it could not be started)."""
    try:
        p = subprocess.run(cmd, stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                           timeout = timeout)
        return p.returncode, p.stdout.decode('utf-8', 'replace')
    except Exception as e:
        return 127, str(e)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def gpus(nvidia_smi):
    """The GPUs nvidia-smi sees: [{name, compute_cap (x 10), driver_version}], and its error text when it cannot."""
    if not nvidia_smi:
        return [], 'no nvidia-smi'
    rc, out = run([nvidia_smi, '--query-gpu=name,compute_cap,driver_version', '--format=csv,noheader'], 60)
    if rc != 0:
        return [], out.strip().splitlines()[0] if out.strip() else f'nvidia-smi exited with {rc}'
    found = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(',')]
        if len(parts) >= 3 and parts[0]:
            cap = parts[1].replace('.', '')
            found.append({'name': parts[0], 'compute_cap': int(cap) if cap.isdigit() else None,
                          'driver_version': parts[2]})
    return found, ''


def windows_gpu_names():
    """The NVIDIA display adapters Windows knows (also without a working nvidia-smi): [(name, driver version)]."""
    rc, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   "Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' } | "
                   "ForEach-Object { $_.Name + '|' + $_.DriverVersion }"], 60)
    return [tuple(x.strip().split('|', 1)) for x in out.splitlines() if '|' in x] if rc == 0 else []


def linux_module_version():
    """The version of the nvidia module on disk for the running kernel (what the next boot loads), or None."""
    rc, out = run(['modinfo', '-F', 'version', 'nvidia'], 30)
    v = out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else ''
    return v if drivers.VERSION_RE.match(v) else None


def linux_running():
    """/proc/driver/nvidia/version: the driver that runs now ('' when none is loaded)."""
    try:
        with open('/proc/driver/nvidia/version', encoding = 'utf-8', errors = 'replace') as f:
            return f.read()
    except OSError:
        return ''


def linux_package_of(path):
    """The distribution package that owns a file (dpkg or rpm), or None: a driver installed by .run owns none."""
    real = os.path.realpath(path)
    if shutil.which('dpkg'):
        rc, out = run(['dpkg', '-S', real], 30)
        if rc == 0 and ':' in out:
            return out.split(':', 1)[0].strip()
    if shutil.which('rpm'):
        rc, out = run(['rpm', '-qf', real], 30)
        if rc == 0 and out.strip() and 'not owned' not in out:
            return out.strip().splitlines()[0]
    return None


def branches_of(releases):
    """{version: branch} of the releases whose listing names their branch (Windows: 616.92 is "Release 615")."""
    return {x['version']: x['branch'] for x in releases.get('releases') or [] if x.get('branch')}


def secure_boot_on():
    rc, out = run(['mokutil', '--sb-state'], 30)
    return rc == 0 and 'enabled' in out.lower()


class CTool(InitCTool):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)
        self._desc = None

    def facts(self):
        """The facts of _desc.yaml: the URLs, the legacy branches, the open kernel modules."""
        if self._desc is None:
            r = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_desc'))
            self._desc = (r.get('data') or {}) if r.get('return', 1) == 0 else {}
        return self._desc

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The installed driver of each nvidia-smi found: on Linux the module on disk (an install changes it before
        the reboot that loads it, and nvidia-smi fails between the two), else the version nvidia-smi reports."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        versions = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            v = linux_module_version() if uname == 'linux' else None
            if not v:
                found, _ = gpus(path)
                v = found[0]['driver_version'] if found else None
            if v:
                versions[candidate] = {'output': f'DRIVER version : {v}'}
        return {'return': 0, 'found_paths_with_versions': versions} if versions else {'return': 0}

    ############################################################
    def check_features(self, ctx, paths, params):
        """The GPUs, the driver that runs now (on Linux it differs from the installed one until a reboot), the kernel
        module type and how the driver was installed."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        for p in paths:
            features = p.setdefault('features', {})
            found, error = gpus(p['path'])
            features['gpus'] = found
            caps = [g['compute_cap'] for g in found if g.get('compute_cap')]
            features['compute_cap_int_min'] = min(caps) if caps else None
            if found:
                features['running_version'] = found[0]['driver_version']
            else:
                features['nvidia_smi_error'] = error
            if uname == 'linux':
                proc = linux_running()
                features['kernel_module'] = 'open' if 'open kernel module' in proc.lower() else ('proprietary' if proc else None)
                package = linux_package_of(p['path'])
                features['installed_by'] = package or 'nvidia .run installer'
                installed = linux_module_version()
                running = features.get('running_version')
                features['reboot_pending'] = bool(installed and (not running or installed != running))
        return {'return': 0, 'paths': paths}

    ############################################################
    def latest_version(self, ctx, params):
        """The newest driver for this machine's GPU (task/setup asks it for --status and --upgrade)."""
        r = self.releases(ctx, params)
        if r['return'] > 0:
            return r
        best = drivers.pick([x['version'] for x in r['releases']], max_branch = r['max_branch'], branches = branches_of(r))
        if not best:
            return {'return': 16, 'error': 'no driver release for this GPU'}
        return {'return': 0, 'version': best, 'source': r['source']}

    def gpu(self, ctx):
        """{name, compute_cap} of the oldest NVIDIA GPU here (the one that limits the driver branch), and a note."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        smi = shutil.which('nvidia-smi')
        found, error = gpus(smi)
        if found:
            return min(found, key = lambda g: g.get('compute_cap') or 999), ''
        if uname == 'windows':
            names = windows_gpu_names()
            if names:
                return {'name': names[0][0], 'compute_cap': None, 'driver_version': drivers.windows_version(names[0][1])}, error
        return None, error

    def releases(self, ctx, params):
        """The driver releases for this machine and GPU: {releases: [{version, url, ...}], max_branch, source, gpu}."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        f = self.facts()
        gpu, note = self.gpu(ctx)
        if gpu is None:
            return {'return': 16, 'error': f'no NVIDIA GPU found ({note})'}
        max_branch = drivers.last_branch(gpu.get('compute_cap'), f.get('legacy_branches'))

        try:
            if uname == 'windows':
                plist = drivers.products(drivers.fetch(f['product_list']).decode('utf-8', 'replace'))
                product = drivers.find_product(plist, gpu['name'])
                if not product:
                    return {'return': 16, 'error': f'NVIDIA\'s product list has no "{gpu["name"]}" ({f["product_list"]})'}
                url = drivers.lookup_url(f['download_service'], product[0], product[1], f.get('windows_os_id', 57))
                found = drivers.lookup_drivers(drivers.fetch(url).decode('utf-8', 'replace'))
                return {'return': 0, 'releases': found, 'max_branch': max_branch, 'gpu': gpu,
                        'source': f'NVIDIA\'s driver search for {product[2]}'}

            if uname == 'linux':
                machine = LINUX_MACHINES.get(os.uname().machine)
                if not machine:
                    return {'return': 16, 'error': f'NVIDIA has no Linux driver archive for {os.uname().machine}'}
                if machine != 'x86_64':
                    return {'return': 16, 'error': 'only the x86_64 archive of NVIDIA\'s Linux drivers is supported yet'}
                base = f['linux_archive']
                versions = drivers.linux_versions(drivers.fetch(base + '/').decode('utf-8', 'replace'))
                found = [{'version': v, 'url': drivers.linux_runfile(base, v, machine)[0]} for v in versions]
                return {'return': 0, 'releases': found, 'max_branch': max_branch, 'gpu': gpu,
                        'source': base + '/'}
        except Exception as e:
            return {'return': 16, 'error': f'cannot read NVIDIA\'s list of drivers: {e}'}

        return {'return': 16, 'error': f'no NVIDIA driver install for {uname} (macOS has none)'}

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """The newest driver for the GPU (or the release / branch --version names), with NVIDIA's own installer."""
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        c = params.get('control', {})
        con, quiet = c.get('con', False), c.get('quiet', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if c.get('verbose') else ''

        r = self.releases(ctx, params)
        if r['return'] > 0:
            return dict(r, install_cmd = None)
        gpu, max_branch = r['gpu'], r['max_branch']
        wanted = str(params.get('version') or '').strip()

        if not gpu.get('compute_cap') and uname == 'linux' and not wanted:
            return {'return': 16, 'install_cmd': None,
                    'error': 'the GPU\'s compute capability is unknown (nvidia-smi does not answer: a driver installed '
                             'before the last reboot?) - reboot, or name the branch with --version=<branch>'}

        version = drivers.pick([x['version'] for x in r['releases']], wanted, max_branch, branches_of(r))
        if not version:
            limit = f' (the GPU is supported up to branch {max_branch})' if max_branch else ''
            return {'return': 16, 'install_cmd': None,
                    'error': f'no NVIDIA driver {wanted or "release"} for {gpu["name"]}{limit} in {r["source"]}'}
        release = next(x for x in r['releases'] if x['version'] == version)
        cuda = (self.facts().get('cuda_of_branch') or {}).get(str(release.get('branch') or drivers.branch(version)))

        if con:
            print('')
            print(f'{space}INFO: NVIDIA driver {version}{f" (CUDA {cuda})" if cuda else ""} for {gpu["name"]}'
                  f'{f", supported up to branch {max_branch}" if max_branch else ""} - {r["source"]}')

        content = os.path.join(os.getcwd(), 'content')
        os.makedirs(content, exist_ok = True)

        if uname == 'linux':
            rr = self.install_linux(ctx, params, release, gpu, content, con, quiet, space)
        else:
            rr = self.install_windows(ctx, params, release, content, con, quiet, space)
        if rr['return'] > 0:
            return dict(rr, install_cmd = None)

        self.forget_cuda(con, space)
        return {'return': 0, 'install_cmd': None, 'found_path': rr['found_path']}

    def download(self, ctx, params, url, content, filename):
        """Into the cache entry's content folder (download-file: a download that broke off continues)."""
        from tool_c393ba5c6fa14f66.api.common_release import _download
        return _download(self, ctx, params, url, os.path.relpath(content), filename)

    def install_linux(self, ctx, params, release, gpu, content, con, quiet, space):
        version = release['version']
        smi = shutil.which('nvidia-smi')
        if smi:
            package = linux_package_of(smi)
            if package:
                return {'return': 16, 'error': f'the driver here comes from the package {package}: upgrade it with the '
                                               f'distribution (sudo apt install nvidia-driver-<branch>, or cx task run '
                                               f'upgrade-os), not with NVIDIA\'s .run installer'}
        if secure_boot_on():
            return {'return': 16, 'error': 'Secure Boot is on: the module the .run installer builds is not signed '
                                           'and would not load - use the distribution\'s signed driver packages'}

        installed = linux_module_version()
        if installed == version:
            if con:
                print(f'{space}INFO: NVIDIA driver {version} is already installed (modinfo nvidia)')
            return {'return': 0, 'found_path': smi or '/usr/bin/nvidia-smi'}

        url, sha_url = drivers.linux_runfile(self.facts()['linux_archive'], version)
        try:
            expected = drivers.linux_sha256(drivers.fetch(sha_url).decode('utf-8', 'replace'))
        except Exception as e:
            return {'return': 16, 'error': f'cannot read the sha256 of the driver ({sha_url}): {e}'}
        if not expected:
            return {'return': 16, 'error': f'no sha256 in {sha_url}'}

        filename = os.path.basename(url)
        r = self.download(ctx, params, url, content, filename)
        if r['return'] > 0:
            return r
        path = r['path']
        if sha256(path) != expected:
            os.remove(path)
            return {'return': 16, 'error': f'the download of {url} does not match its sha256 (removed)'}

        rc, lsmod = run(['lsmod'], 30)
        kind = drivers.module_type(linux_running(), gpu.get('compute_cap'),
                                   self.facts().get('open_kernel_modules_min_arch', 75))
        cmd = ['sh', path] + drivers.linux_install_args(kind, nouveau_loaded = 'nouveau' in lsmod)
        if os.geteuid() != 0:
            cmd = ['sudo', '-n'] + cmd if quiet else ['sudo'] + cmd
        if con:
            print(f'{space}INFO: installing NVIDIA driver {version} ({kind} kernel module, DKMS) next to the running '
                  f'one: {" ".join(cmd)}')
            print('')
        rc = subprocess.call(cmd)
        new = linux_module_version()
        if rc != 0 or new != version:
            log = ''
            try:
                with open('/var/log/nvidia-installer.log', encoding = 'utf-8', errors = 'replace') as f:
                    log = f.read()
            except OSError:
                pass
            why = f'NVIDIA\'s installer exited with {rc} and the module on disk is {new or "none"}, not {version}'
            error = drivers.build_error(log)
            if error:
                running = linux_module_version() or installed
                older = f' - an older release may build: --version={drivers.branch(running)}' if running else ''
                why = (f'the kernel module of NVIDIA driver {version} does not build against this kernel '
                       f'({os.uname().release}): {error}{older}; the driver here is unchanged ({new or "none"})')
            tail = ''.join(log.splitlines(True)[-25:])
            return {'return': 16, 'error': why + (f'\n{tail}' if tail else '')}
        os.remove(path)
        if con:
            print('')
            print(f'{space}INFO: NVIDIA driver {version} is installed; the driver that runs now'
                  f'{f" ({installed})" if installed else ""} stays until the next boot - reboot to load it')
        return {'return': 0, 'found_path': shutil.which('nvidia-smi') or '/usr/bin/nvidia-smi'}

    def install_windows(self, ctx, params, release, content, con, quiet, space):
        version = release['version']
        elevated = ctx['tasks']['global']['host'].get('os_extra', {}).get('elevated', False)
        filename = release['url'].rsplit('/', 1)[-1]
        if quiet and not elevated:
            return {'return': 16, 'error': f'installing the NVIDIA driver needs administrator rights, which a quiet '
                                           f'run (-q) does not ask for: run "cx tool upgrade nvidia-driver" without '
                                           f'-q, or in an elevated terminal'}

        if con:
            print(f'{space}INFO: downloading {release["url"]} ({release.get("size") or "?"})')
        r = self.download(ctx, params, release['url'], content, filename)
        if r['return'] > 0:
            return r
        path = r['path']

        # The package is signed by NVIDIA (no checksum is published for it): Windows checks the signature
        rc, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                       f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
                       "$s.Status.ToString() + '|' + $s.SignerCertificate.Subject"], 120)
        status, _, subject = out.strip().partition('|')
        if rc != 0 or status != 'Valid' or 'NVIDIA Corporation' not in subject:
            os.remove(path)
            return {'return': 16, 'error': f'the driver package is not signed by NVIDIA (signature: {out.strip()}) - removed'}

        args = drivers.windows_install_args()
        if elevated:
            cmd = [path] + args
        else:
            arglist = ','.join(f"'{a}'" for a in args)
            cmd = ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   f"$p = Start-Process -FilePath '{path}' -ArgumentList {arglist} -Verb RunAs -Wait -PassThru; "
                   "exit $p.ExitCode"]
        if con:
            print(f'{space}INFO: installing NVIDIA driver {version} (signed by NVIDIA; the screen may go dark for a '
                  f'moment){"" if elevated else " - accept the administrator prompt (UAC)"}')
            print(f'{space}      {" ".join(cmd)}')
            print('')
        rc = subprocess.call(cmd)

        found, error = gpus(shutil.which('nvidia-smi') or r'C:\Windows\System32\nvidia-smi.exe')
        new = found[0]['driver_version'] if found else None
        if new != version:
            return {'return': 16, 'error': f'NVIDIA\'s installer exited with {rc} and the driver is '
                                           f'{new or error or "unknown"}, not {version}'}
        os.remove(path)
        if con and rc != 0:
            print(f'{space}INFO: NVIDIA\'s installer exited with {rc}: a restart may finish the install')
        return {'return': 0, 'found_path': shutil.which('nvidia-smi') or r'C:\Windows\System32\nvidia-smi.exe'}

    def forget_cuda(self, con, space):
        """Drop the cached records of tool/cuda (the CUDA version of the driver), so that the next run that needs it
        reads the new driver."""
        r = self.cm.access({'category': 'cache', 'command': 'find', 'arg1': 'task--setup--cuda--*', 'con': False})
        for a in (r.get('artifacts') or []) if r.get('return', 1) == 0 else []:
            alias = (a.get('cmeta_ref_parts') or {}).get('artifact_alias') or os.path.basename(a.get('path', ''))
            rd = self.cm.access({'category': 'cache', 'command': 'delete', 'arg1': alias, 'force': True, 'con': False})
            if con and rd.get('return', 1) == 0:
                print(f'{space}INFO: the cached record of tool "cuda" ({alias}) is dropped: the next run reads the new driver')
