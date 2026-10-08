"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import json
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# AMD's Python distribution of ROCm (TheRock): one aggregate index per channel, the "rocm" package with
# its libraries, the development files (hipcc, headers) and the device code of one GPU family as extras
CHANNELS = {
    'stable': 'https://stable.repo.amd.com/rocm/whl-next/',
    'nightly': 'https://nightly.repo.amd.com/rocm/whl-next/',
    'rc': 'https://rc.repo.amd.com/rocm/whl-next/',
    'dev': 'https://dev.repo.amd.com/rocm/whl-next/',
}
DEFAULT_CHANNEL = 'stable'
PYTHON = '3.12'

# AMD's Python distribution ships amd-smi (and rocminfo, hipcc), not rocm-smi, which this tool detects and
# questions: a rocm-smi that answers the two questions from amd-smi - its version lines, and the cards as
# rocm-smi's JSON - written next to amd-smi in the venv
ROCM_SMI_SHIM = r'''#!/usr/bin/env python3
"""rocm-smi for cMeta's rocm tool, answered by amd-smi (AMD's Python distribution of ROCm has no rocm-smi)."""
import json, os, re, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
amd_smi = os.path.join(here, 'amd-smi')
def run(*args):
    return subprocess.run([amd_smi] + list(args), capture_output = True, text = True)
if '--version' in sys.argv:
    out = run('version').stdout
    rocm = re.search(r'ROCm version:\s*([0-9][0-9.]*)', out)
    lib = re.search(r'AMDSMI Library version:\s*([0-9][0-9.+a-z]*)', out)
    print('ROCM-SMI version: ' + (rocm.group(1) if rocm else 'unknown') + ' (amd-smi)')
    print('ROCM-SMI-LIB version: ' + (lib.group(1) if lib else 'unknown'))
    sys.exit(0)
r = run('static', '--asic', '--vram', '--driver', '--bus', '--json')
if r.returncode != 0:
    sys.stderr.write(r.stderr); sys.exit(r.returncode)
try:
    data = json.loads(r.stdout)
except ValueError:
    sys.stderr.write(r.stdout); sys.exit(1)
gpus = data.get('gpu_data', data) if isinstance(data, dict) else data
cards = {}
for i, g in enumerate(gpus if isinstance(gpus, list) else []):
    asic, vram, driver, bus = g.get('asic', {}), g.get('vram', {}), g.get('driver', {}), g.get('bus', {})
    size = vram.get('size', {})
    mib = size.get('value') if isinstance(size, dict) else None
    card = {'Card Series': asic.get('market_name'), 'Card Model': asic.get('device_id'), 'Card Vendor': asic.get('vendor_name'),
            'GFX Version': asic.get('target_graphics_version'), 'PCI Bus': bus.get('bdf'), 'Driver version': driver.get('version'),
            'Unique ID': asic.get('asic_serial')}
    if isinstance(mib, (int, float)):
        card['VRAM Total Memory (B)'] = str(int(mib * 1024 * 1024))
    cards['card%d' % g.get('gpu', i)] = {k: v for k, v in card.items() if v not in (None, 'N/A')}
print(json.dumps(cards))
'''


def cards_from_amd_smi(data):
    """
    The GPUs of "amd-smi static --asic --vram --driver --bus --json" as rocm-smi's JSON (card0, card1 ...
    with rocm-smi's keys), which parse_rocm_smi_devices reads - what the rocm-smi written next to
    amd-smi by install() answers, for a ROCm found through rocm-sdk (no rocm-smi at all).
    """
    gpus = data.get('gpu_data', data) if isinstance(data, dict) else data
    cards = {}
    for i, g in enumerate(gpus if isinstance(gpus, list) else []):
        asic, vram, driver, bus = g.get('asic', {}), g.get('vram', {}), g.get('driver', {}), g.get('bus', {})
        size = vram.get('size', {})
        mib = size.get('value') if isinstance(size, dict) else None
        card = {'Card Series': asic.get('market_name'), 'Card Model': asic.get('device_id'), 'Card Vendor': asic.get('vendor_name'),
                'GFX Version': asic.get('target_graphics_version'), 'PCI Bus': bus.get('bdf'), 'Driver version': driver.get('version'),
                'Unique ID': asic.get('asic_serial')}
        if isinstance(mib, (int, float)):
            card['VRAM Total Memory (B)'] = str(int(mib * 1024 * 1024))
        cards['card%d' % g.get('gpu', i)] = {k: v for k, v in card.items() if v not in (None, 'N/A')}
    return cards


def is_rocm_sdk(path):
    """Whether the detected tool is rocm-sdk (AMD's Python distribution in a python) rather than rocm-smi."""
    return os.path.basename(path or '').startswith('rocm-sdk')


def prefer_rocm_smi(paths):
    """
    Drop a rocm-sdk next to a rocm-smi (an install of this tool: its venv has both, and the rocm-smi
    written there answers everything), so that one installation is one candidate.
    """
    kept = []
    for p in paths:
        path = p.get('path', '')
        if is_rocm_sdk(path) and os.path.isfile(os.path.join(os.path.dirname(path), 'rocm-smi')):
            continue
        kept.append(p)
    return kept


def gfx_name(target_version):
    """The GPU family of the kernel's gfx_target_version (kfd): 110502 -> gfx1152, 90402 -> gfx942."""
    v = int(target_version)
    return f'gfx{v // 10000}{(v // 100) % 100:x}{v % 100:x}'


def gfx_from_kfd(topology = '/sys/class/kfd/kfd/topology/nodes'):
    """The GPU families the kernel's ROCm interface exposes, in node order (the nodes with compute units)."""
    names = []
    for node in sorted(glob.glob(os.path.join(topology, '*')), key = lambda p: int(os.path.basename(p)) if os.path.basename(p).isdigit() else 0):
        try:
            with open(os.path.join(node, 'properties')) as f:
                props = dict(line.split(None, 1) for line in f if ' ' in line)
        except OSError:
            continue
        if int(props.get('simd_count', 0)) > 0 and props.get('gfx_target_version', '0').strip() != '0':
            names.append(gfx_name(props['gfx_target_version'].strip()))
    return names


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        The versions rocm-smi prints, the ROCm version itself (amd-smi next to it, or the rocm-sdk CLI of
        AMD's Python distribution, or /opt/rocm/.info/version), the folders of the installation, the GPUs
        from rocm-smi's JSON.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL rocm api_v1 check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        paths = prefer_rocm_smi(paths)

        for p in paths:
            # Parsing standard output
            output = p['output'].split('\n')

            versions = {}

            features = p.setdefault('features', {})

            for o in output:
                oo = o.split(':')

                if len(oo) == 2:
                    versions[oo[0].strip().lower()] = oo[1].strip()

            if versions:
                features_versions = features.setdefault('versions', {})
                features_versions.update(versions)

            # The folders of the installation: bin next to rocm-smi (hipcc, amd-smi, rocminfo are there
            # in AMD's own layouts), home above it; for rocm-sdk (AMD's distribution in a python) the
            # folders it names: "rocm-sdk path --bin" (hipcc, amd-smi) and "--root"
            rocm_smi_path = p['path'] # path to rocm-smi, or to rocm-sdk
            sdk = is_rocm_sdk(rocm_smi_path)
            path_bin = os.path.dirname(os.path.realpath(rocm_smi_path))
            path_home = os.path.dirname(path_bin)
            if sdk:
                sdk_bin, sdk_root = self._sdk_paths(rocm_smi_path, env, timeout)
                if sdk_bin:
                    path_bin = sdk_bin
                    path_home = sdk_root or os.path.dirname(sdk_bin)
            fpaths = features.setdefault('paths', {})
            fpaths['bin'] = path_bin
            fpaths['qbin'] = self.cm.q(path_bin)
            fpaths['home'] = path_home
            fpaths['qhome'] = self.cm.q(path_home)
            if sdk:
                features['rocm_sdk'] = rocm_smi_path

            rocm_version = self._rocm_version(path_bin, env, timeout)
            if rocm_version:
                features.setdefault('versions', {})['rocm'] = rocm_version
                features['rocm_version'] = rocm_version

            # Checking devices: rocm-smi's JSON, or amd-smi's (next to hipcc) turned into it for rocm-sdk
            amd_smi = os.path.join(path_bin, 'amd-smi')
            if sdk and os.path.isfile(amd_smi):
                rocm_smi_cmd = self.cm.q(amd_smi) + ' static --asic --vram --driver --bus --json'
            else:
                rocm_smi_cmd = rocm_smi_path + ' --showbus --showuniqueid --showproductname --showdriverversion --showmeminfo vram --json'

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': rocm_smi_cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con,
                  'quiet': quiet,
                  'verbose': verbose,
                  'text_cmd': 'RUN:',
                  'capture_output': True,
                  # Important to be able to continue processing detect/install/build
                  'fail_if_nonzero_return_code': False,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']

            if returncode != 0 and not sdk:
                # Fallback for older rocm-smi versions that may not support one of the explicit flags.
                rocm_smi_cmd = rocm_smi_path + ' --json'

                ii['cmd'] = rocm_smi_cmd
                rx = self.cm.access(ii)
                if self.cm.catch_error(rx): return rx

                returncode = rx['returncode']

            if returncode != 0:
                return self.cm.error(f'failed to detect ROCm capabilities using CMD "{rocm_smi_cmd}" in "{__file__}"')

            if returncode == 0:
                rocm_smi_json = parse_json(rx.get('stdout', ''))
                if sdk:
                    rocm_smi_json = cards_from_amd_smi(rocm_smi_json)
                devices = parse_rocm_smi_devices(rocm_smi_json)

                if devices:
                    # Propagate a single known driver version if present on all devices.
                    driver_versions = {d.get('driver_version') for d in devices if d.get('driver_version')}
                    if len(driver_versions) == 1:
                        features_versions = features.setdefault('versions', {})
                        features_versions.setdefault('driver version', next(iter(driver_versions)))

                # The GPU families from the kernel, in node order, next to what rocm-smi says
                gfx = gfx_from_kfd()
                if gfx:
                    features['gfx'] = gfx
                    for device, name in zip(devices, gfx):
                        device.setdefault('gfx', name)

                features['devices'] = devices

        return {'return':0, 'paths':paths}


    ############################################################
    def _sdk_paths(self, rocm_sdk, env, timeout):
        """The bin folder (hipcc, amd-smi) and the root of AMD's distribution, as "rocm-sdk path" names them."""
        found = []
        for flag in ('--bin', '--root'):
            r = self.cm.utils.sys.run(f'{self.cm.q(rocm_sdk)} path {flag}', capture_output = True, fail_on_error = False,
                                      env = env, timeout = timeout or 60, logger = self.logger)
            line = ((r.get('stdout') or '').strip().splitlines() or [''])[0].strip() if r.get('returncode') == 0 else ''
            found.append(line if line and os.path.isdir(line) else None)
        return found[0], found[1]


    ############################################################
    def _rocm_version(self, path_bin, env, timeout):
        """
        The ROCm version: "amd-smi version" (ROCm version: 10.1.0) next to rocm-smi, else the rocm-sdk
        CLI of AMD's Python distribution, else /opt/rocm/.info/version. None when nothing says it.
        """
        import shutil
        for exe, regex in (('amd-smi', r'ROCm version:\s*([0-9][0-9.]*)'), ('rocm-sdk', r'^\s*([0-9][0-9.]*)\s*$')):
            # next to rocm-smi, else on PATH or in AMD's own folders (a distribution's rocm-smi is in
            # /usr/bin while AMD's amd-smi sits in /opt/rocm/core-<v>/bin)
            candidates = [os.path.join(path_bin, exe), shutil.which(exe) or ''] + sorted(glob.glob(f'/opt/rocm*/core-*/bin/{exe}'), reverse = True) + glob.glob(f'/opt/rocm*/bin/{exe}')
            path = next((c for c in candidates if c and os.path.isfile(c)), None)
            if not path:
                continue
            r = self.cm.utils.sys.run(f'{self.cm.q(path)} version', capture_output = True, fail_on_error = False,
                                      env = env, timeout = timeout or 60, logger = self.logger)
            m = re.search(regex, r.get('stdout') or '', re.M) if r.get('returncode') == 0 else None
            if m:
                return m.group(1)
        home = os.path.dirname(path_bin)
        for info in (os.path.join(home, '.info', 'version'), '/opt/rocm/.info/version'):
            try:
                with open(info) as f:
                    text = f.read().strip()
                m = re.match(r'([0-9][0-9.]*)', text)
                if m:
                    return m.group(1)
            except OSError:
                pass
        return None


    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        ROCm from AMD's Python distribution (TheRock), without root: a virtual environment in the cache
        entry with the "rocm" package - its libraries, the development files (hipcc, amdclang, headers,
        CMake files) and the device code of this machine's GPU family (device-gfx942, device-gfx1152 ...)
        - from one of AMD's channels: stable (the default), nightly, rc (release candidates) or dev
        (--with.channel=<name>); --version pins the ROCm version (10.1.0), the newest of the channel
        otherwise. The GPU family comes from the kernel (--with.gfx=<name> overrides it; a machine
        without an AMD GPU can still get the libraries and hipcc for a family given this way).

        On Linux x86_64 only (what AMD publishes). Elsewhere, and when the distribution's own packages
        are wanted instead, install_cmd (apt on Ubuntu 26.04 and later) is tried after this.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL rocm api_v1 install")

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        con = params.get('control', {}).get('con', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        _with = params.get('with', {}) or {}
        channel = str(_with.get('channel') or DEFAULT_CHANNEL).lower()
        if channel not in CHANNELS:
            return self.cm.error(f'ROCm channel "{channel}" is not one of {", ".join(CHANNELS)} in "{__file__}"')
        index = CHANNELS[channel]

        if uname != 'linux' or uarch != 'amd64':
            return {'return': 16,
                    'error': f'AMD publishes its Python distribution of ROCm for Linux x86_64 only ({uname}/{uarch} here)',
                    'install_cmd': cmd}

        gfx = _with.get('gfx')
        if not gfx:
            found = gfx_from_kfd()
            if not found:
                return {'return': 16,
                        'error': 'no AMD GPU in the kernel\'s ROCm interface (/sys/class/kfd): the device code of the ROCm to install cannot be chosen (--with.gfx=<family> names one)',
                        'install_cmd': cmd}
            gfx = found[0]

        version = params.get('version_simple') or ''
        requirement = f'rocm[libraries,devel,device-{gfx}]' + (f'=={version}' if version else '')

        uv = (_global.get('uv') or {}).get('qpath')
        if not uv:
            return self.cm.error(f'uv is needed to install ROCm from AMD\'s Python distribution in "{__file__}"')

        venv = os.path.join(os.getcwd(), 'content', 'venv')
        bindir = os.path.join(venv, 'bin')
        python = os.path.join(bindir, 'python')
        rocm_smi = os.path.join(bindir, 'rocm-smi')

        if con:
            print('')
            print(f'{space}INFO: ROCm from AMD\'s Python distribution, channel "{channel}": {requirement}')
            print(f'{space}INFO: index: {index}')
            print(f'{space}INFO: venv: {venv}')

        def run(line, what):
            r = self.cm.utils.sys.run(line, capture_output = not con, con = con, print_cmd = con, fail_on_error = False,
                                      timeout = params.get('timeout'), env = params.get('env'), logger = self.logger)
            if r.get('returncode', 0) != 0:
                err = (r.get('stderr') or '').strip().splitlines()
                return self.cm.error(f'{what} failed (exit code {r.get("returncode")})' + (f': {err[-1]}' if err else ''))
            return {'return': 0}

        if not os.path.isfile(python):
            r = run(f'{uv} venv --python {PYTHON} "{venv}"', f'creating a Python {PYTHON} environment for ROCm')
            if r['return'] > 0: return r

        r = run(f'{uv} pip install --python "{python}" --index-url {index} "{requirement}"', f'installing {requirement}')
        if r['return'] > 0: return r

        # The development tree (hipcc, headers) is laid out and the device files linked into it
        r = run(f'"{os.path.join(bindir, "rocm-sdk")}" init', 'rocm-sdk init')
        if r['return'] > 0: return r

        if not os.path.isfile(rocm_smi):
            if not os.path.isfile(os.path.join(bindir, 'amd-smi')):
                return self.cm.error(f'{requirement} was installed but neither rocm-smi nor amd-smi is in {bindir}')
            with open(rocm_smi, 'w') as f:
                f.write(ROCM_SMI_SHIM)
            os.chmod(rocm_smi, 0o755)
            if con:
                print(f'{space}INFO: AMD\'s distribution has no rocm-smi: a rocm-smi answered by amd-smi was written in {bindir}')

        with open(os.path.join(os.getcwd(), 'content', 'cmeta-rocm.json'), 'w') as f:
            json.dump({'channel': channel, 'index': index, 'requirement': requirement, 'gfx': gfx, 'python': PYTHON}, f, indent = 2)

        return {'return': 0, 'install_cmd': None, 'found_path': rocm_smi}


def parse_json(s):
    s = (s or '').strip()
    if not s:
        return {}

    try:
        return json.loads(s)
    except Exception:
        return {}


def _get_alias(d, aliases):
    if not isinstance(d, dict):
        return None

    folded = {str(k).strip().lower(): v for k, v in d.items()}

    for alias in aliases:
        if alias.lower() in folded:
            return folded[alias.lower()]

    return None


def _parse_int(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value)
    # Keep digits only, so values like "4,096 MiB" or "17163091968 B" can be parsed.
    digits = ''.join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    try:
        return int(digits)
    except Exception:
        return None


def _parse_memory_total(gpu_data):
    memory_total = _get_alias(gpu_data, [
        'vram total memory (b)',
        'vram total memory (bytes)',
        'memory total (b)',
        'memory total (bytes)',
    ])
    memory_total_mib = _get_alias(gpu_data, [
        'vram total memory (mib)',
        'memory total (mib)',
    ])

    total_bytes = _parse_int(memory_total)
    total_mib = _parse_int(memory_total_mib)

    if total_bytes is None and total_mib is not None:
        total_bytes = total_mib * 1024 * 1024

    return total_bytes, total_mib


def parse_rocm_smi_devices(rocm_json):
    if not isinstance(rocm_json, dict):
        return []

    cleaned_devices = []

    for top_key, top_value in rocm_json.items():
        if not isinstance(top_value, dict):
            continue

        # Typical rocm-smi JSON format uses keys like "card0", "card1", etc.
        if not re.match(r'^(card|gpu)\d+$', str(top_key).strip().lower()):
            continue

        index = _parse_int(re.sub(r'\D+', '', str(top_key)))
        name = _get_alias(top_value, [
            'card series',
            'card model',
            'device name',
            'product name',
            'gpu name',
        ])
        uuid = _get_alias(top_value, [
            'unique id',
            'gpu uuid',
            'serial number',
        ])
        bus_id = _get_alias(top_value, [
            'pci bus',
            'pci bus id',
            'pci bus address',
            'pcie bus',
        ])
        driver_version = _get_alias(top_value, [
            'driver version',
            'amdgpu driver version',
        ])
        compute_cap = _get_alias(top_value, [
            'gpu gfx',
            'gfx version',
            'asic',
            'target gfx version',
        ])

        memory_total, memory_total_mib = _parse_memory_total(top_value)

        cleaned = {}

        if index is not None:
            cleaned['index'] = index
        if name is not None:
            cleaned['name'] = str(name).strip()
        if uuid is not None:
            cleaned['uuid'] = str(uuid).strip()
        if bus_id is not None:
            cleaned['pci.bus_id'] = str(bus_id).strip()
        if driver_version is not None:
            cleaned['driver_version'] = str(driver_version).strip()
        if compute_cap is not None:
            cleaned['compute_cap'] = str(compute_cap).strip()
        if memory_total is not None:
            cleaned['memory.total'] = memory_total
        if memory_total_mib is not None:
            cleaned['memory.total [MiB]'] = f'{memory_total_mib} MiB'

        cleaned_devices.append(cleaned)

    return cleaned_devices
