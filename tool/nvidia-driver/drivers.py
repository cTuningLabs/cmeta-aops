"""
The NVIDIA driver releases a machine's GPU can take, and how one is installed - plain functions without cMeta, so
that the offline tests import this file alone.

Windows: NVIDIA's download service (the driver search of nvidia.com) lists the drivers of one product - GeForce or
RTX/Quadro, desktop or notebook - on both branches: the production branch and, with qnf=1, the new feature branch
(the one that runs the newest CUDA). The product is found by its name in NVIDIA's product list (the name nvidia-smi
gives, compared without "NVIDIA" and "Generation").

Linux: NVIDIA's archive of .run installers (download.nvidia.com/XFree86/Linux-x86_64/), every release with its
sha256. A legacy GPU stops at a branch (Maxwell, Pascal and Volta at 580): the newest release of the branches it is
supported by.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import re
import urllib.parse
import urllib.request

VERSION_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?$')


def key(version):
    return tuple(int(x) for x in re.findall(r'\d+', str(version)))


def branch(version):
    """The branch of a driver release: 615 for 615.78.08."""
    k = key(version)
    return k[0] if k else 0


def fetch(url, timeout = 60):
    request = urllib.request.Request(url, headers = {'User-Agent': 'Mozilla/5.0 (cMeta tool nvidia-driver)'})
    with urllib.request.urlopen(request, timeout = timeout) as r:
        return r.read()


def last_branch(arch_min, legacy):
    """The newest driver branch a GPU of compute capability arch_min (x 10: 50 for Maxwell) is supported by, from the
    legacy rules of _desc.yaml ([{below_arch: 75, last_branch: 580}, ...]); None: no limit (or the GPU is unknown)."""
    if not arch_min:
        return None
    limits = [int(x['last_branch']) for x in (legacy or []) if int(arch_min) < int(x['below_arch'])]
    return min(limits) if limits else None


def matches(version, wanted, release_branch = None):
    """Whether a release is the one asked for: an exact release (615.78.08), a prefix (615.78) or a branch (615) -
    on Windows the branch NVIDIA names in the listing (616.92 is "Release 615"), when it is known."""
    wanted = str(wanted or '').strip()
    if not wanted:
        return True
    if release_branch and wanted.isdigit() and int(wanted) == int(release_branch):
        return True
    return key(version)[:len(key(wanted))] == key(wanted)


def pick(versions, wanted = None, max_branch = None, branches = None):
    """The newest of the releases that match what is asked for and that the GPU's branch limit allows; None if none.
    branches: {version: the branch NVIDIA names} where the version number does not say it (Windows)."""
    branches = branches or {}
    ok = [v for v in versions
          if matches(v, wanted, branches.get(v)) and (not max_branch or (branches.get(v) or branch(v)) <= max_branch)]
    return max(ok, key = key) if ok else None


############################################################ Linux: the .run archive

def linux_versions(index_html):
    """The releases in the listing of NVIDIA's archive (its folders named by version), oldest first."""
    found = set(re.findall(r"""href=['"]?(?:\./)?(\d+\.\d+(?:\.\d+)?)/""", index_html))
    return sorted(found, key = key)


def linux_runfile(base, version, machine = 'x86_64'):
    """The URLs of a release's .run installer and of its sha256 file."""
    url = f'{base}/{version}/NVIDIA-Linux-{machine}-{version}.run'
    return url, url + '.sha256sum'


def linux_sha256(text):
    """The digest in a .sha256sum file ("<digest>  <file name>")."""
    m = re.search(r'\b([0-9a-fA-F]{64})\b', text or '')
    return m.group(1).lower() if m else None


def module_type(proc_version, arch_min, open_min_arch):
    """The kernel module to build: the type the running driver uses (/proc/driver/nvidia/version says "Open Kernel
    Module" for the open one), else open for a GPU that has it (Turing and newer: arch >= open_min_arch), else the
    proprietary one."""
    if proc_version:
        return 'open' if 'open kernel module' in proc_version.lower() else 'proprietary'
    if arch_min and int(arch_min) >= int(open_min_arch):
        return 'open'
    return 'proprietary'


def linux_install_args(kind, nouveau_loaded = False):
    """The options of NVIDIA's .run installer for an unattended install next to a running driver: no questions
    (--silent), the module rebuilt by DKMS for every new kernel, no check for a running X server, the new modules not
    loaded now, and the initramfs rebuilt - a silent install leaves it as it is, and an initramfs that carries the
    old modules loads the old driver at the next boot. The new driver starts with that boot."""
    args = ['--silent', '--dkms', '--no-x-check', '--skip-module-load', '--rebuild-initramfs',
            '--kernel-module-type=' + kind]
    if nouveau_loaded:
        args.append('--disable-nouveau')
    return args


def build_error(log_text):
    """The first compiler error in the installer's output or log, or None: the kernel module of a release may not
    build against a newer kernel."""
    for line in (log_text or '').splitlines():
        if ' error: ' in line or line.startswith('error: '):
            return line.strip()
    return None


############################################################ Windows: the download service

def normalize(name):
    """A product name without the words NVIDIA, Generation and (R)/(TM): "rtx pro 1000 blackwell laptop gpu"."""
    words = re.sub(r'\((?:r|tm)\)', ' ', str(name or '').lower()).replace('-', ' ').split()
    return ' '.join(w for w in words if w not in ('nvidia', 'generation'))


def products(xml_text):
    """NVIDIA's product list: [(series id, product id, name)]."""
    items = re.findall(r'<LookupValue ParentID="(\d+)"[^>]*>\s*<Name>([^<]*)</Name>\s*<Value>(\d+)</Value>', xml_text)
    return [(int(p), int(v), n.strip()) for p, n, v in items]


def find_product(product_list, gpu_name):
    """(series id, product id, name) of the GPU nvidia-smi names, or None: the same words, then the same words but
    "Laptop"/"Notebook" and "GPU" (NVIDIA's list and the driver do not always agree on those)."""
    want = normalize(gpu_name)
    for p in product_list:
        if normalize(p[2]) == want:
            return p

    def loose(n):
        return ' '.join(w for w in normalize(n).split() if w not in ('gpu', 'laptop', 'notebook', 'mobile', 'max-q'))

    laptop = any(w in want.split() for w in ('laptop', 'notebook', 'mobile', 'max-q'))
    for p in product_list:
        n = normalize(p[2]).split()
        if loose(p[2]) == loose(gpu_name) and laptop == any(w in n for w in ('laptop', 'notebook', 'mobile', 'max-q')):
            return p
    return None


def lookup_url(base, series, product, os_id, new_feature = True, results = 20):
    """The query of the download service: the drivers of a product for an OS (57: Windows 10/11 64-bit), DCH drivers,
    both branches with new_feature."""
    q = {'func': 'DriverManualLookup', 'psid': series, 'pfid': product, 'osID': os_id, 'languageCode': 1033,
         'beta': 0, 'isWHQL': 0, 'dltype': -1, 'dch': 1, 'upCRD': -1, 'qnf': 1 if new_feature else 0,
         'sort1': 0, 'numberOfResults': results}
    return base + '?' + urllib.parse.urlencode(q)


def lookup_drivers(json_text):
    """The drivers the download service answered: [{version, name, date, url, size}], newest first."""
    try:
        data = json.loads(json_text)
    except ValueError:
        return []
    out = []
    for x in data.get('IDS') or []:
        info = x.get('downloadInfo') or {}
        version, url = str(info.get('Version') or ''), str(info.get('DownloadURL') or '')
        if VERSION_RE.match(version) and url.lower().endswith('.exe'):
            name = urllib.parse.unquote(str(info.get('Name') or ''))
            m = re.search(r'\bRelease\s+(\d{3})\b', name)
            out.append({'version': version, 'name': name, 'branch': int(m.group(1)) if m else branch(version),
                        'date': str(info.get('ReleaseDateTime') or ''), 'url': url,
                        'size': str(info.get('DownloadURLFileSize') or '')})
    return sorted(out, key = lambda d: key(d['version']), reverse = True)


def windows_install_args():
    """The options of NVIDIA's Windows package (its setup runs them): no window, no restart."""
    return ['-s', '-noreboot']


def windows_version(driver_version):
    """The NVIDIA version of a Windows driver version: 32.0.15.9713 -> 597.13 (the last five digits)."""
    digits = ''.join(str(driver_version or '').split('.')[-2:])
    if len(digits) < 5 or not digits.isdigit():
        return None
    return f'{int(digits[-5:-2])}.{digits[-2:]}'
