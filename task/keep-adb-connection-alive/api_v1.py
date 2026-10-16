"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import re
import shlex
import sys
import time
from pathlib import Path

from task_c36be4b9314a45e0.api.ctask import InitCTask, ask


def endpoint(value):
    """A shell-safe TCP endpoint; retain adb's default port for legacy bare addresses."""
    value = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]+', value):
        raise ValueError('give an IP:port from Wireless debugging, for example 192.0.2.10:43291')
    if ':' not in value:
        value += ':5555'
    address, port = value.rsplit(':', 1)
    if not address or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('ADB endpoint must have a valid port from 1 to 65535')
    return value


def mdns_services(text):
    """Only connection services: pairing ports must never be used by adb connect."""
    services = []
    for line in (text or '').splitlines():
        words = line.split()
        if len(words) >= 3 and words[1].rstrip('.') == '_adb-tls-connect._tcp':
            try:
                services.append({'name': words[0].rstrip('.'), 'endpoint': endpoint(words[-1])})
            except ValueError:
                pass
    return services


def devices(text):
    return {w[0]: w[1] for line in (text or '').splitlines()
            if len(w := line.split()) >= 2 and w[1] in ('device', 'offline', 'unauthorized')}


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def command(self, ctx, args, capture=True, timeout=15):
        adb = ctx['tasks']['global']['adb']['path']
        words = [str(adb)] + [str(a) for a in args]
        if any('"' in w or '\n' in w or '\r' in w for w in words):
            return self.cm.error('invalid quote or newline in adb argument')
        windows = ctx['tasks']['global']['host']['os']['uname'] == 'windows'
        cmd = ' '.join('"%s"' % w for w in words) if windows else ' '.join(shlex.quote(w) for w in words)
        return self.cm.access({'category': self.category_alias + ',' + self.category_uid,
                               'command': 'run', 'arg1': 'cmd,c9ba0a88df394d7f', 'ctx': ctx,
                               'cmd': cmd, 'capture_output': capture, 'timeout': timeout,
                               'fail_if_nonzero_return_code': False, 'con': not capture,
                               'verbose': False, 'text_cmd': 'ADB:', 'print_extra_line': False})

    def host_config(self, host):
        if not host:
            return None, {}, {}
        name = host.split('::')[-1]
        r = self.cm.access({'category': self.cmeta['uses_categories']['host'], 'command': 'find',
                            'arg1': name, 'base': True, 'con': False})
        if r.get('return') or len(r.get('artifacts', [])) != 1:
            raise ValueError('host must resolve to exactly one Android fleet artifact: ' + host)
        root = Path(r['artifacts'][0]['path'])
        r = self.cm.utils.files.safe_read_file(str(root / '_desc.yaml'))
        if r.get('return'): raise ValueError(r.get('error'))
        desc = r.get('data') or {}
        if desc.get('type') != 'adb': raise ValueError('the selected host is not an adb device')
        r = self.cm.utils.files.safe_read_file(str(root / 'state.yaml')) if (root / 'state.yaml').exists() else {}
        if r.get('return'): raise ValueError(r.get('error'))
        state = r.get('data') or {}
        access = desc.get('access') or {}
        config = access.get('wireless') or {}
        if not isinstance(config, dict): raise ValueError('access.wireless must be a mapping')
        config = dict(config)
        if not access.get('wireless') and access.get('serial'):
            config['serial'] = str(access['serial'])
        return root, config, state.get('adb_connection') or {}

    def guide(self):
        print('cMeta info: Connect the watch and computer to the same Wi-Fi network.')
        print('cMeta info: Watch: Settings > Developer options > ADB debugging and Wireless debugging ON.')
        print('cMeta info: First pairing: Pair new device shows a PAIRING IP:port and a temporary PIN.')
        print('cMeta info: Use --pair; enter that PIN directly at the adb prompt. The PIN is not saved here.')
        print('cMeta info: Then use IP:port from the MAIN Wireless debugging screen; its port is different.')
        print('cMeta info: If the watch sleeps or changes networks, enable Wi-Fi/debugging and reconnect.')

    def identity(self, ctx, serial, expected, required, timeout):
        if not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]+', serial):
            raise ValueError('invalid adb transport serial')
        r = self.command(ctx, ['-s', serial, 'shell',
                              'getprop ro.serialno; getprop ro.product.model; '
                              'getprop ro.product.manufacturer; pm list features'], timeout=timeout)
        if self.cm.catch_error(r, fail16=True) or r.get('returncode'):
            raise ValueError(r.get('error') or (r.get('stderr') or 'device did not answer').strip())
        lines = (r.get('stdout') or '').replace('\r', '').splitlines()
        if len(lines) < 3: raise ValueError('device identity response was incomplete')
        number, model, manufacturer = (line.strip() for line in lines[:3])
        features = {line.strip()[8:].split('=')[0] for line in lines[3:] if line.strip().startswith('feature:')}
        if expected and number != expected:
            raise ValueError('connected device identity differs from this host; refusing to select it')
        missing = set(required) - features
        if missing: raise ValueError('selected device lacks required features: ' + ', '.join(sorted(missing)))
        return {'serial': serial, 'device_serial': number, 'model': model, 'manufacturer': manufacturer,
                'required_features_verified': list(required)}

    def remember(self, root, receipt):
        if root is None: return
        path = root / 'state.yaml'
        r = self.cm.utils.files.safe_read_file(str(path)) if path.exists() else {}
        if r.get('return'): raise ValueError(r.get('error'))
        state = r.get('data') or {}
        state['adb_connection'] = receipt
        r = self.cm.utils.files.safe_write_file(str(path), state, atomic=True, sort_keys=False)
        if r.get('return'): raise ValueError(r.get('error'))

    def connect_once(self, ctx, root, config, saved, ip, serial, timeout):
        expected = str(config.get('device_serial') or saved.get('device_serial') or '')
        required = config.get('required_features') or []
        if isinstance(required, str): required = [required]
        r = self.command(ctx, ['devices'], timeout=timeout)
        if self.cm.catch_error(r, fail16=True) or r.get('returncode'):
            raise ValueError('adb devices failed: ' + (r.get('error') or r.get('stderr') or 'unknown error'))
        attached = devices(r.get('stdout'))
        # A known hardware identity can appear under a new mDNS transport or USB serial.
        candidates = [serial] if serial else [saved.get('serial')]
        if expected and not serial: candidates += [s for s, status in attached.items() if status == 'device']
        for candidate in dict.fromkeys(c for c in candidates if c):
            if attached.get(candidate) == 'device':
                try:
                    receipt = self.identity(ctx, candidate, expected, required, timeout)
                except ValueError:
                    if serial: raise
                    continue
                receipt.update(endpoint=saved.get('endpoint', ''), mdns_service=saved.get('mdns_service', ''))
                self.remember(root, receipt)
                return receipt
        if serial:
            raise ValueError('selected adb serial is not connected: ' + serial)

        chosen = str(ip or config.get('endpoint') or saved.get('endpoint') or '')
        r = self.command(ctx, ['mdns', 'services'], timeout=timeout)
        services = mdns_services(r.get('stdout', '')) if r.get('return') == 0 else []
        known_name = config.get('mdns_service') or saved.get('mdns_service')
        old_address = chosen.rsplit(':', 1)[0] if chosen else ''
        matches = [s for s in services if (known_name and s['name'] == known_name) or
                   (expected and s['name'].startswith('adb-' + expected + '-')) or
                   (expected and old_address and s['endpoint'].rsplit(':', 1)[0] == old_address)]
        # Explicit endpoints win; do not guess among several advertised peers.
        if not ip and len(matches) == 1: chosen = matches[0]['endpoint']
        if not chosen: raise ValueError('no watch endpoint configured; run cx host connect <watch> interactively or give --endpoint=IP:port')
        chosen = endpoint(chosen)
        r = self.command(ctx, ['connect', chosen], timeout=timeout)
        if self.cm.catch_error(r, fail16=True) or r.get('returncode'):
            raise ValueError(r.get('error') or r.get('stderr') or 'adb connect failed')
        receipt = self.identity(ctx, chosen, expected, required, timeout)
        service = next((s['name'] for s in services if s['endpoint'] == chosen), saved.get('mdns_service', ''))
        receipt.update(endpoint=chosen, mdns_service=service)
        self.remember(root, receipt)
        return receipt

    def run(self, ctx: dict, env: dict = None, ip: str = None, period: int = 10,
            host: str = '', serial: str = '', once: bool = False, pair: bool = False,
            pairing_endpoint: str = '', duration: int = 0, timeout: int = 15,
            instructions: bool = False):
        """Reconnect a wireless Android host once, or keep its connection alive until Ctrl+C.

        Legacy: cxt keep-adb-connection-alive IP:port [period] still loops indefinitely.
        --host reads a fleet host's access.wireless settings and retains non-secret identity
        in its state.yaml. --once returns after connecting. --pair guides first-time pairing;
        adb itself reads the PIN from the terminal, never from task parameters. --duration
        bounds a keep-alive run in seconds. No adb server reset or device reboot is performed.
        """
        try:
            period, timeout, duration = int(period or 10), int(timeout), int(duration or 0)
            if period < 1 or not 1 <= timeout <= 60 or duration < 0:
                raise ValueError('period must be positive, timeout 1..60 seconds and duration nonnegative')
            if env: ctx['tasks'].setdefault('aggregated', {}).setdefault('env', {}).update(env)
            if instructions:
                self.guide()
                return {'return': 0, 'instructions': True}
            root, config, saved = self.host_config(host)
            serial = serial or config.get('serial') or ''
            quiet = ctx['control'].get('quiet', False)
            if pair:
                self.guide()
                if quiet or not sys.stdin or not sys.stdin.isatty():
                    raise ValueError('pairing needs a terminal for the watch PIN; run cx host connect <watch> --pair without -q')
                if not pairing_endpoint:
                    r = ask('PAIRING IP:port from Pair new device: ', how='--pairing_endpoint=IP:port')
                    if r['return']: return r
                    pairing_endpoint = r['answer'].strip()
                r = self.command(ctx, ['pair', endpoint(pairing_endpoint)], capture=False, timeout=60)
                if self.cm.catch_error(r, fail16=True): return r
                if r.get('returncode'): raise ValueError('adb pairing failed; open Pair new device and try its current PIN/port')
            if not ip and not serial and not config.get('endpoint') and not saved.get('endpoint'):
                self.guide()
                if quiet:
                    raise ValueError('give --endpoint=IP:port to cx host connect, or --ip=IP:port to this task; pair first if required')
                r = ask('CONNECTION IP:port from main Wireless debugging screen: ', how='--ip=IP:port (or cx host connect --endpoint=IP:port)')
                if r['return']: return r
                ip = endpoint(r['answer'])
            deadline = time.monotonic() + duration if duration else None
            result = None
            while True:
                try:
                    result = self.connect_once(ctx, root, config, saved, ip, serial, timeout)
                    saved = result
                    # The initial explicit address is a bootstrap hint. Later iterations follow discovery/state.
                    ip = None
                    if ctx['control'].get('con'):
                        print('cMeta info: connected %s (%s), adb -s %s' %
                              (result.get('model') or 'Android device', result.get('device_serial') or '?', result['serial']))
                    if once: return dict(result, **{'return': 0, 'connected': True})
                except ValueError as exc:
                    if once: raise
                    result = None
                    if ctx['control'].get('con'): print('cMeta warning: %s; retrying in %ss' % (exc, period))
                if deadline is not None and time.monotonic() >= deadline:
                    if result: return dict(result, **{'return': 0, 'connected': True})
                    raise ValueError('keep-alive ended without a connected device; check Wi-Fi and the current debugging port')
                wait = period if deadline is None else min(period, max(0, deadline - time.monotonic()))
                time.sleep(wait)
        except KeyboardInterrupt:
            return {'return': 0, 'stopped': True}
        except (OSError, ValueError, KeyError) as exc:
            return self.cm.error(str(exc))
