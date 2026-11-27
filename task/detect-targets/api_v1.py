"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

detect-targets - the compute targets of this machine. Each target task declares a cheap probe (`probe:` beside `support:`
in its _desc.yaml: files, device classes, drivers per OS - nothing installed, well under a second for all); the answers
and the machine's OS, kernel and driver versions make a fingerprint. The findings are kept in a state artifact of the
machine (state::local:detect-targets) and taken again while the fingerprint is the same; when it differs (a new GPU, a
driver or a runtime upgraded) the targets are detected again and what changed is said. --full runs the target task of
each present target too (its tools, devices, compute capability ...), which takes longer - that is what the cache spares.

A target is an artifact: task/target--<name> in any repository, a private one too, with its `support:` and `probe:`
blocks, its set-up (`uses:`) and, when it needs one, its own probe code (`{script: probe.py}`). The targets are found
by their alias among the repositories this call sees, so a target of a repository the call must not see is neither
probed nor named; the findings are kept per set of targets probed (targets-<its hash>.json).
"""

import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CATEGORY = 'task,c36be4b9314a45e0'
STATE = 'state'
STATE_ARTIFACT = 'local:detect-targets'
PREFIX = 'target--'


def read(path):
    try:
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            return f.read()
    except OSError:
        return None


def gfx_of_kfd(topology = '/sys/class/kfd/kfd/topology/nodes'):
    """The AMD GPU families the kernel's ROCm interface exposes (gfx942 ...)."""
    names = []
    for node in sorted(glob.glob(os.path.join(topology, '*'))):
        props = read(os.path.join(node, 'properties')) or ''
        m = re.search(r'^gfx_target_version\s+(\d+)', props, re.M)
        simd = re.search(r'^simd_count\s+(\d+)', props, re.M)
        if m and simd and int(simd.group(1)) > 0 and int(m.group(1)):
            v = int(m.group(1))
            names.append('gfx%d%x%x' % (v // 10000, (v // 100) % 100, v % 100))
    return names


def driver_of(device_dir):
    link = os.path.join(device_dir, 'driver')
    return os.path.basename(os.path.realpath(link)) if os.path.islink(link) else ''


def windows_devices(classes):
    """
    The present devices of Windows of the given device classes (Display, ComputeAccelerator, SoftwareComponent ...:
    the ones the probes name), in one PowerShell call: [{name, class, vendor, driver, id}] - id is the device's
    instance id, the name of its key in the registry.
    """
    names = sorted({str(c) for c in classes or [] if re.fullmatch(r'[A-Za-z0-9]+', str(c))})
    if not names:
        return []
    ps = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -in " + ','.join("'%s'" % c for c in names)
          + " -and $_.Present } | "
          "ForEach-Object { $_.PNPClass + '|' + $_.Name + '|' + $_.PNPDeviceID }; "
          "Get-CimInstance Win32_VideoController | ForEach-Object { 'DRIVER|' + $_.Name + '|' + $_.DriverVersion }")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output = True, text = True,
                             timeout = 60, stdin = subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    drivers = {}
    devices = []
    for line in out.splitlines():
        parts = line.strip().split('|')
        if len(parts) != 3:
            continue
        if parts[0] == 'DRIVER':
            drivers[parts[1]] = parts[2]
            continue
        m = re.search(r'VEN_([0-9A-Fa-f]{4})', parts[2])
        devices.append({'class': parts[0], 'name': parts[1], 'vendor': (m.group(1).upper() if m else ''), 'id': parts[2]})
    for d in devices:
        d['driver'] = drivers.get(d['name'], '')
    return devices


def windows_registry(key, value = None):
    """
    The registry of this machine (HKEY_LOCAL_MACHINE): the data of a key's value, or without a value the names of
    the key's values. None when the key or the value is not there.
    """
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            if value is not None:
                return winreg.QueryValueEx(k, value)[0]
            return [winreg.EnumValue(k, i)[0] for i in range(winreg.QueryInfoKey(k)[1])]
    except (ImportError, OSError):
        return None


ENUM_KEY = 'SYSTEM\\CurrentControlSet\\Enum\\'
CLASS_KEY = 'SYSTEM\\CurrentControlSet\\Control\\Class\\'


def driver_value(device_id, value, registry = windows_registry):
    """
    A value of a Windows device's driver key: the device's own key (Enum, by its instance id) names the driver key
    (Driver = {class}, then a number), and the value is in that key of Control, Class - where a GPU driver says its
    OpenCL library (OpenCLDriverName) and its Vulkan manifest (VulkanDriverName), and where the Khronos loaders read
    them.
    """
    driver = registry(ENUM_KEY + device_id, 'Driver')
    return registry(CLASS_KEY + driver, value) if driver else None


def cpu_vendor(host):
    """The vendor of this machine's CPU as the CPU says it (GenuineIntel, AuthenticAMD ...), '' when it says none."""
    if host['system'] == 'linux':
        m = re.search(r'^vendor_id\s*:\s*(\S+)', read('/proc/cpuinfo') or '', re.M)
        return m.group(1) if m else ''
    if host['system'] == 'windows':
        # "Intel64 Family 6 Model 197 Stepping 2, GenuineIntel"
        return (os.environ.get('PROCESSOR_IDENTIFIER') or '').rpartition(',')[2].strip()
    if host['system'] == 'darwin':
        try:
            return subprocess.run(['sysctl', '-n', 'machdep.cpu.vendor'], capture_output = True, text = True, timeout = 10,
                                  stdin = subprocess.DEVNULL).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ''
    return ''


def adb_devices(port = None, timeout = 3):
    """
    The Android devices the adb server of this machine lists, asked on its socket (the request "host:devices-l" of
    adb's own protocol): [{serial, state, model ...}]. Nothing is started: without a running adb server the answer
    is None (a device shows after "adb devices" or "cx host connect" started one).
    """
    import socket

    port = int(port or os.environ.get('ANDROID_ADB_SERVER_PORT') or 5037)
    request = b'host:devices-l'

    def take(sock, n):
        data = b''
        while len(data) < n:
            block = sock.recv(n - len(data))
            if not block:
                break
            data += block
        return data

    try:
        with socket.create_connection(('127.0.0.1', port), timeout = timeout) as sock:
            sock.sendall(b'%04x' % len(request) + request)
            if take(sock, 4) != b'OKAY':
                return None
            text = take(sock, int(take(sock, 4), 16)).decode('utf-8', 'replace')
    except (OSError, ValueError):
        return None

    devices = []
    for line in text.splitlines():
        words = line.split()
        if len(words) < 2:
            continue
        device = {'serial': words[0], 'state': words[1]}
        device.update(w.split(':', 1) for w in words[2:] if ':' in w)
        devices.append(device)
    return devices


def classes_of(checks):
    """The Windows device classes that the checks of a probe name (pnp, pnp_driver_value; inside all / any too)."""
    out = set()
    for check in checks or []:
        if not isinstance(check, dict):
            continue
        for key in ('pnp', 'pnp_driver_value'):
            out.update((check.get(key) or {}).get('class') or [])
        for key in ('all', 'any'):
            if isinstance(check.get(key), list):
                out |= classes_of(check[key])
    return out


def pci_devices(root = '/sys/bus/pci/devices'):
    """The PCI devices of a Linux machine as its kernel lists them: [{vendor, device, driver}] (ids as 0x10de)."""
    out = []
    for dev in sorted(glob.glob(os.path.join(root, '*'))):
        vendor = (read(os.path.join(dev, 'vendor')) or '').strip().lower()
        if vendor:
            out.append({'vendor': vendor, 'device': (read(os.path.join(dev, 'device')) or '').strip().lower(),
                        'driver': driver_of(dev)})
    return out


def script_probe(folder, name, host):
    """
    A target's own probe: probe(host) of a Python file of the target artifact - a backend looks for its device its own
    way, without a change of this task (a target of any repository, a private one too). It answers {'present': bool,
    'devices': [...], 'versions': {...}} and is expected to be as cheap as the declared checks. The file is one of the
    artifact's own folder; what it raises, or an answer of another shape, is said as 'error' and the target is absent.
    """
    if not folder or os.path.basename(str(name)) != str(name):
        return {'error': 'the probe script "%s" is not a file of the target artifact' % name}
    path = os.path.join(folder, str(name))
    try:
        import importlib.util

        module_name = 'cmeta_target_probe_' + hashlib.sha256(path.encode('utf-8')).hexdigest()[:12]
        module_spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        answer = module.probe(dict(host))
    except Exception as e:      # the target's own code: its failure is its answer, the other targets are still probed
        return {'error': '%s: %s' % (name, e)}
    if not isinstance(answer, dict):
        return {'error': '%s: probe(host) answered no dictionary' % name}
    return {'present': bool(answer.get('present')), 'devices': [str(d) for d in answer.get('devices') or []],
            'versions': {str(k): str(v) for k, v in (answer.get('versions') or {}).items()}}


def probe(spec, host, cache, folder = None):
    """
    One target's probe on this machine: {'present': bool, 'devices': [...], 'versions': {...}} from its spec of this OS
    (any of the checks: all / any of checks, glob [+ version regex, names], kfd_gfx, drm_vendor [+ drivers], accel_driver,
    pci [+ device, drivers], pnp, pnp_driver_value, registry_values, cpu_vendor, adb_devices, machine, always, and
    script: the target's own probe - folder is the target artifact's). A script that failed adds 'error'.
    """
    out = {'present': False, 'devices': [], 'versions': {}}
    if not isinstance(spec, dict):
        return out
    for check in spec.get('any') or []:
        if check.get('always'):
            out['present'] = True
        if 'machine' in check and host['machine'].lower() in [m.lower() for m in check['machine']]:
            out['present'] = True
            out['devices'].append(host.get('chip') or host['machine'])
        # all: every check of the list holds (a GPU and the file its driver installs); any: one of them
        for key, holds in (('all', all), ('any', any)):
            if key in check:
                subs = [probe({'any': [c]}, host, cache, folder) for c in check[key] or []]
                if subs and holds(x['present'] for x in subs):
                    out['present'] = True
                    for x in subs:
                        if x['present']:
                            out['devices'] += x['devices']
                            out['versions'].update(x['versions'])
                for x in subs:
                    if x.get('error'):
                        out['error'] = x['error']
        if 'script' in check:
            found = script_probe(folder, check['script'], host)
            if found.get('error'):
                out['error'] = found['error']
            elif found['present']:
                out['present'] = True
                out['devices'] += found['devices']
                out['versions'].update(found['versions'])
        if 'pci' in check:
            if 'pci' not in cache:
                cache['pci'] = pci_devices()
            want = check['pci']
            for d in cache['pci']:
                if d['vendor'] in [str(v).lower() for v in want.get('vendor') or []] and (
                        not want.get('device') or d['device'] in [str(v).lower() for v in want['device']]) and (
                        not want.get('drivers') or d['driver'] in want['drivers']):
                    out['present'] = True
                    out['devices'].append('%s:%s (%s)' % (d['vendor'], d['device'], d['driver'] or 'no driver'))
        if 'glob' in check:
            # names: the files found are the devices
            hits = sorted(glob.glob(check['glob']))
            if hits:
                out['present'] = True
                if check.get('names'):
                    out['devices'] += [os.path.basename(h) for h in hits]
                if check.get('version'):
                    m = re.search(check['version'], read(hits[0]) or '')
                    if m:
                        out['versions'][os.path.basename(hits[0])] = m.group(1)
        if check.get('kfd_gfx'):
            gfx = gfx_of_kfd()
            if gfx:
                out['present'] = True
                out['devices'] += gfx
                v = (read('/sys/module/amdgpu/version') or '').strip()
                out['versions']['amdgpu'] = v or host.get('kernel', '')
        if 'drm_vendor' in check:
            for card in sorted(glob.glob('/sys/class/drm/card[0-9]*')):
                dev = os.path.join(card, 'device')
                if (read(os.path.join(dev, 'vendor')) or '').strip().lower() != check['drm_vendor'].lower():
                    continue
                drv = driver_of(dev)
                if not check.get('drivers') or drv in check['drivers']:
                    out['present'] = True
                    out['devices'].append('%s (%s)' % ((read(os.path.join(dev, 'device')) or '').strip(), drv))
        if 'accel_driver' in check:
            for acc in sorted(glob.glob('/sys/class/accel/accel*')):
                drv = driver_of(os.path.join(acc, 'device'))
                if drv in check['accel_driver']:
                    out['present'] = True
                    out['devices'].append('%s (%s)' % (os.path.basename(acc), drv))
        if 'pnp' in check:
            if 'windows' not in cache:
                cache['windows'] = windows_devices(cache.get('windows_classes'))
            want = check['pnp']
            for d in cache['windows']:
                if d['class'] in (want.get('class') or []) and d['vendor'] in [v.upper() for v in want.get('vendor') or []]:
                    out['present'] = True
                    out['devices'].append(d['name'])
                    if d.get('driver'):
                        out['versions'][d['name']] = d['driver']
        if 'pnp_driver_value' in check:
            if 'windows' not in cache:
                cache['windows'] = windows_devices(cache.get('windows_classes'))
            want = check['pnp_driver_value']
            for d in cache['windows']:
                if d['class'] in (want.get('class') or []) and d.get('id') and driver_value(
                        d['id'], want['value'], cache.get('registry', windows_registry)):
                    out['present'] = True
                    out['devices'].append(d['name'])
                    if d.get('driver'):
                        out['versions'][d['name']] = d['driver']
        if 'registry_values' in check:
            names = cache.get('registry', windows_registry)(check['registry_values']) or []
            if names:
                out['present'] = True
                out['devices'] += [os.path.basename(str(n).replace('\\', '/')) for n in names]
        if 'cpu_vendor' in check:
            if 'cpu_vendor' not in cache:
                cache['cpu_vendor'] = cpu_vendor(host)
            if cache['cpu_vendor'] in check['cpu_vendor']:
                out['present'] = True
                out['devices'].append('CPU (%s)' % cache['cpu_vendor'])
        if check.get('adb_devices'):
            if 'adb' not in cache:
                cache['adb'] = adb_devices()
            for d in cache['adb'] or []:
                if d['state'] == 'device':
                    out['present'] = True
                    out['devices'].append('%s (%s)' % (d.get('model') or 'Android device', d['serial']))
    out['devices'] = sorted(set(out['devices']))
    return out


def fingerprint(host, probes):
    """What decides whether the findings still hold: the OS, kernel, CPU, and each probe's devices and versions."""
    data = {'host': {k: host.get(k) for k in ('system', 'kernel', 'machine', 'chip')},
            'probes': {t: {'present': p['present'], 'devices': p['devices'], 'versions': p['versions']} for t, p in sorted(probes.items())}}
    return hashlib.sha256(json.dumps(data, sort_keys = True).encode('utf-8')).hexdigest()


def host_facts():
    facts = {'system': platform.system().lower(), 'kernel': platform.release(), 'machine': platform.machine().lower()}
    if facts['system'] == 'darwin':
        try:
            facts['chip'] = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output = True, text = True,
                                           timeout = 10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return facts


def choose(present, supported, how = None):
    """
    The target of --compute=auto among the targets present here that the program supports. An accelerator of this
    machine itself first: one kind -> it, several -> None (the caller lists them: never a guess). When there is none,
    a portable interface over its devices the same way (opencl, vulkan, the openvino stack: `auto: portable` in the
    target's description). Else cpu (when supported). A target that is another device driven from this machine (an
    Android tablet: `support.device_os`) is never taken by itself. how: {target: 'portable' | 'never'}.
    -> (compute or None, candidates).
    """
    how = how or {}
    fits = [t for t in present if t != 'cpu' and (not supported or t in supported) and how.get(t) != 'never']
    for group in ([t for t in fits if how.get(t) != 'portable'], [t for t in fits if how.get(t) == 'portable']):
        if len(group) == 1:
            return group[0], group
        if group:
            return None, group
    return ('cpu' if (not supported or 'cpu' in supported) else None), []


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            redetect: bool = False,   # detect again whatever the fingerprint says
            full: bool = False,       # also run the target task of each present target (its tools and devices)
            only: str = '',           # targets or kinds to look at: cuda,rocm or gpu,npu (default: every target with a probe)
            supported: str = '',      # the targets a program supports (comma-separated): the choice of --compute=auto
            ):
        """
        The compute targets of this machine, cached with a fingerprint (the module's docstring).
        """
        con = ctx['control'].get('con', False)
        host = host_facts()

        # every target task with its support and probe blocks (data)
        r = self.cm.access({'category': TASK_CATEGORY, 'command': 'find', 'arg1': PREFIX + '*', 'con': False})
        if r['return'] > 0:
            return r
        targets = {}
        folders = {}
        for a in r.get('artifacts') or []:
            alias = a['cmeta_ref_parts'].get('artifact_alias', '')
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            desc = (rd.get('data') or {}) if rd.get('return', 1) == 0 else {}
            targets[alias[len(PREFIX):]] = desc
            folders[alias[len(PREFIX):]] = a['path']

        wanted = [w.strip().lower() for w in str(only or '').split(',') if w.strip()]
        probes = {}
        no_probe = []

        def spec_of(desc):
            return (desc.get('probe') or {}).get(host['system']) or (desc.get('probe') or {}).get('all')

        # one question to Windows for the device classes that the probes of all targets name
        cache = {'windows_classes': set().union(*[classes_of((spec_of(d) or {}).get('any')) for d in targets.values()])}

        for name, desc in sorted(targets.items()):
            kind = str((desc.get('support') or {}).get('kind') or '')
            spec = spec_of(desc)
            if not spec:
                # said only for a target this OS runs (support.host_os): the others are no target here at all
                if host['system'] in ((desc.get('support') or {}).get('host_os') or []) and (
                        not wanted or name in wanted or kind in wanted):
                    no_probe.append(name)
                continue
            probes[name] = dict(probe(spec, host, cache, folders.get(name)), kind = kind)

            # another device driven from here is never the choice of --compute=auto; a portable interface comes second
            if (desc.get('support') or {}).get('device_os'):
                probes[name]['auto'] = 'never'
            elif desc.get('auto') == 'portable':
                probes[name]['auto'] = 'portable'

        fp = fingerprint(host, probes)

        # The findings are kept per set of targets probed: a call that sees fewer repositories (hide_repos, a
        # clearance) has its own - it neither reads what a call that sees more found, nor says that a target it
        # must not know of "is gone"
        kept = 'targets-' + hashlib.sha256(','.join(sorted(probes)).encode('utf-8')).hexdigest()[:12] + '.json'
        state = self._state(kept)
        cached = state.get('findings') if state.get('fingerprint') == fp and not redetect else None
        changed = [] if cached or not state.get('fingerprint') else self._changes(state.get('probes') or {}, probes)

        # --only is a view: every probe was asked and the findings kept are of all of them (a filtered run that kept
        # its few targets as the machine's made the next run say the others "are gone"); it limits what is shown,
        # returned and, with --full, which target tasks run
        shown = {t: p for t, p in probes.items() if not wanted or t in wanted or p['kind'] in wanted}

        features = (cached or {}).get('features') or {}
        present = sorted(t for t, p in shown.items() if p['present'])
        if full:
            for t in present:
                if t in features and not redetect:
                    continue
                rt = self.cm.access({'category': TASK_CATEGORY, 'command': 'run', 'arg1': PREFIX + t, 'ctx': ctx,
                                     'new': bool(redetect or changed), 'con': False, 'quiet': True})
                features[t] = rt.get('features') if rt.get('return', 1) == 0 else {'error': rt.get('error', '')}

        findings = {'present': sorted(t for t, p in probes.items() if p['present']), 'features': features,
                    'time': time.strftime('%Y-%m-%dT%H:%M:%S')}
        if not cached or full:
            self._save(kept, {'fingerprint': fp, 'host': host, 'probes': probes, 'findings': findings})

        fits = [s.strip() for s in str(supported or '').split(',') if s.strip()]
        chosen, candidates = choose(present, fits, {t: p['auto'] for t, p in shown.items() if p.get('auto')})

        # the other devices the program could run on: never the choice of --compute=auto, said with their command lines
        attached = [t for t in present if shown[t].get('auto') == 'never' and (not fits or t in fits)]
        if con:
            print(f'Targets of this machine ({host["system"]} {host["machine"]}, '
                  + ('cached, fingerprint unchanged' if cached else ('detected again: ' + '; '.join(changed) if changed else 'detected')) + '):')
            for t, p in sorted(shown.items()):
                mark = 'yes' if p['present'] else ' - '
                extra = ', '.join(p['devices'])[:90] if p['devices'] else ''
                note = {'portable': '  (a portable interface)', 'never': '  (another device)'}.get(p.get('auto'), '') if p['present'] else ''
                if p.get('error'):
                    note += f'  (its probe failed - {p["error"]})'
                print(f'  {mark}  {t:<12} {p["kind"]:<6} {extra}{note}')
            if no_probe:
                print(f'  (no probe declared: {", ".join(no_probe)})')
        return {'return': 0, 'present': present, 'probes': shown, 'features': {t: f for t, f in features.items() if t in shown},
                'fingerprint': fp,
                'cached': bool(cached), 'changed': changed, 'no_probe': no_probe, 'auto': chosen, 'candidates': candidates,
                'attached': attached}

    ############################################################
    @staticmethod
    def _changes(old, new):
        """What differs between two probe sets, in words."""
        out = []
        for t in sorted(set(old) | set(new)):
            a, b = old.get(t) or {}, new.get(t) or {}
            if bool(a.get('present')) != bool(b.get('present')):
                out.append(f'{t} {"appeared" if b.get("present") else "is gone"}')
            elif t not in old or t not in new:
                # a target probed for the first time (or no longer): nothing of it changed on the machine
                continue
            elif a.get('devices') != b.get('devices'):
                out.append(f'{t}: other devices')
            elif a.get('versions') != b.get('versions'):
                out.append(f'{t}: other driver or runtime versions')
        return out or (['the OS or kernel changed'] if set(old) == set(new) else ['other targets are probed'])

    def _folder(self):
        r = self.cm.access({'category': STATE, 'command': 'find', 'arg1': STATE_ARTIFACT, 'con': False})
        if r.get('return', 1) == 0 and r.get('artifacts'):
            return r['artifacts'][0]['path']
        r = self.cm.access({'category': STATE, 'command': 'create', 'arg1': STATE_ARTIFACT, 'con': False, 'quiet': True})
        return r.get('path') if r.get('return', 1) == 0 else None

    def _state(self, name):
        folder = self._folder()
        text = read(os.path.join(folder, name)) if folder else None
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {}

    def _save(self, name, data):
        folder = self._folder()
        if folder:
            with open(os.path.join(folder, name), 'w', encoding = 'utf-8') as f:
                json.dump(data, f, indent = 2)
