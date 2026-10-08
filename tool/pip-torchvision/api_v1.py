"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import platform
import re
from urllib.parse import unquote

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# AMD's index of its Python distribution of ROCm (TheRock), per channel: torch and torchvision built against
# each ROCm 10 release ("+rocm10.1.0"), the same one tool/pip takes torch from on the "amd" route
AMD_INDEX = 'https://{channel}.repo.amd.com/rocm/whl-next/'


def torchvision_for_torch(torch_version):
    """
    The torchvision release that pairs with a torch release, by PyTorch's numbering: 2.x.y -> 0.(x+15).y
    (2.14.0 -> 0.29.0), 1.x.y -> 0.(x+1).y (1.13.1 -> 0.14.1); a local tag or a pre-release suffix of torch
    is ignored. None for another major version.
    """
    parts = str(torch_version).split('+')[0].split('.')
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None
    if major == 1:
        x = minor + 1
    elif major == 2:
        x = minor + 15
    else:
        return None
    version = f'0.{x}'
    if len(parts) > 2:
        m = re.match(r'(\d+)', parts[2])
        if m:
            version += '.' + m.group(1)
    return version


def torch_for_torchvision(torchvision_version):
    """The inverse: the torch release a torchvision release pairs with (0.28.0 -> 2.13.0, 0.14.1 -> 1.13.1)."""
    parts = str(torchvision_version).split('+')[0].split('.')
    try:
        x = int(parts[1])
    except (IndexError, ValueError):
        return None
    m = re.match(r'(\d+)', parts[2]) if len(parts) > 2 else None
    patch = m.group(1) if m else '0'
    return f'2.{x - 15}.{patch}' if x >= 15 else f'1.{x - 1}.{patch}'


def version_key(version):
    """Sort key: 0.29.0a0 before 0.29.0, 0.28.0 before both."""
    m = re.match(r'(\d+)\.(\d+)(?:\.(\d+))?(.*)', version)
    if not m:
        return (0, 0, 0, 0, version)
    suffix = m.group(4)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), 1 if suffix == '' else 0, suffix)


def versions_on_index(html, package, local_tag):
    """
    The versions of a package on a simple index page whose wheels carry a local tag ("rocm10.1.0"), without
    the tag, sorted (newest last): torchvision-0.28.0%2Brocm10.1.0-cp312-... -> 0.28.0.
    """
    found = set()
    for m in re.finditer(re.escape(package) + r'-([0-9][^-\s"<>]*?)-cp\d', html or ''):
        version = unquote(m.group(1))
        if version.endswith('+' + local_tag):
            found.add(version[:-len(local_tag) - 1])
    return sorted(found, key = version_key)


def choose_torchvision(wanted, available):
    """
    What to install from what the index has: (wanted, 'exact') when the pair is there; else a pre-release of
    the wanted release ((0.29.0a0, 'pre-release') for 0.29.0: what AMD publishes while torchvision's release
    is pending); else (None, <the newest final release>) - which pairs with an older torch - or (None, None).
    """
    if wanted in available:
        return wanted, 'exact'
    pre = [v for v in available if re.fullmatch(re.escape(wanted) + r'(a|b|rc)\d+', v)]
    if pre:
        return sorted(pre, key = version_key)[-1], 'pre-release'
    final = [v for v in available if re.fullmatch(r'\d+\.\d+\.\d+', v)]
    return None, (sorted(final, key = version_key)[-1] if final else None)


def amd_channel_of(torch_entry, _with):
    """The AMD channel torch came from: with.rocm_channel of this request, else the one in the torch step's index URL, else stable."""
    channel = (_with or {}).get('rocm_channel')
    if channel:
        return str(channel).lower()
    m = re.search(r'https://(\w+)\.repo\.amd\.com', json.dumps(torch_entry or {}, default = str))
    return m.group(1) if m else 'stable'


def fetch(url, timeout = 60):
    """The text at a URL, or None (no network, no page)."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout = timeout) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception:
        return None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params2(self,
                      ctx: dict,
                      params: dict,
                      cparams: dict,
    ):
        """
        """

        # Check torch version (if installed) to calculate compatible torchvision version!
        if 'version' not in params:

            torch = ctx['tasks']['global'].get('pip-torch')
            if torch:
                torch_version = torch['version']

                # The torch that is installed, not the one the step recorded (a run that pins another torch,
                # --use.pip-torch.version=2.13.0, left the global at the version of a previous entry)
                pip_cmd = (ctx['tasks']['global'].get('pip') or {}).get('cmd')
                if not pip_cmd:
                    python = (ctx['tasks']['global'].get('python') or {}).get('path')
                    pip_cmd = f'{self.cm.q(python)} -m pip' if python else None
                if pip_cmd:
                    r = self.cm.utils.sys.run(f'{pip_cmd} show torch', capture_output = True, fail_on_error = False, logger = self.logger)
                    m = re.search(r'^Version:\s*(\S+)', r.get('stdout') or '', re.M) if r.get('returncode') == 0 else None
                    if m:
                        torch_version = m.group(1)
                xversion = torchvision_for_torch(torch_version)
                if xversion:
                    params['version'] = xversion

                _with = params.setdefault('with', {})

                # Complex version (alpha/dev/local build, e.g. "2.12.0a0+git0d62256"):
                # pip would try to reinstall a stable torch to satisfy torchvision's dep.
                # --no-deps prevents that so our source-built torch is left untouched.
                if re.search(r'\+|a\d|b\d|rc\d|\.dev\d|\.post\d', torch_version):
                    pf = _with.get('post_flags', '')
                    if '--no-deps' not in pf:
                        _with['post_flags'] = ('--no-deps ' + pf).strip()

                # torch from AMD's index of its ROCm distribution ("2.14.0+rocm10.1.0"): torchvision comes
                # from the same index and channel, built against the same ROCm release ("0.29.0+rocm10.1.0").
                # AMD's index lags on torchvision: while torchvision's release is pending it carries a
                # pre-release of it (0.29.0a0+rocm10.1.0 next to torch 2.14.0+rocm10.1.0, 2026-10), which
                # is taken; when it has neither, the newest final release there pairs with an older torch,
                # and the error says which --use.pip-torch.version takes that pair. An unpinned torchvision
                # loads no operators (ABI mismatch), and pip finds no distribution for a pin the index lacks.
                m = re.search(r'\+(rocm(\d+)[\w.]*)', torch_version)
                if m and int(m.group(2)) >= 10 and params.get('version'):
                    tag = m.group(1)
                    wanted = params['version']
                    channel = amd_channel_of(torch, _with)
                    available = versions_on_index(fetch(AMD_INDEX.format(channel = channel) + 'torchvision/'), 'torchvision', tag)
                    pick, kind = choose_torchvision(wanted, available)
                    if pick:
                        params['version'] = pick + '+' + tag
                        if kind == 'pre-release' and ctx['control'].get('con', False):
                            print ('')
                            print (f'INFO: torchvision {wanted} is not on AMD\'s {channel} index for {tag} yet: its pre-release {pick} is taken (torch {torch_version})')
                    elif kind:
                        pair = torch_for_torchvision(kind)
                        return self.cm.error(f'AMD\'s {channel} index has no torchvision {wanted} for {tag} (torch {torch_version} is installed): '
                                             f'its newest is {kind}, which pairs with torch {pair} - add --use.pip-torch.version={pair} '
                                             f'(and --new, when a torch is already set up)')
                    else:
                        # The index could not be read: the computed pair
                        params['version'] = wanted + '+' + tag
                    # The same index as torch (the auto route would take PyTorch's for a GPU family it covers)
                    _with['rocm_source'] = 'amd'
                    _with['rocm_channel'] = channel

        # Call function in tool::pip / api_v1.py
        return self.task_setup_tool_code._common_compute_init(
            ctx, 
            params, 
            skip_extras = True,
            cuda_vers = ['13.2', '13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8'],
        )
