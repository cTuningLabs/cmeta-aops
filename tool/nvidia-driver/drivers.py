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


############################################################ Linux: a GPU without a running driver

# The compute capability (x 10, the lowest of the family) of an NVIDIA chip by its code name, as lspci names it
# (GB207GLM, AD107M, TU117): what the legacy branches and the open kernel modules are decided by. The longest prefix
# wins: GA100 is sm_80, the other Ampere chips sm_86.
ARCH_OF_CODENAME = [('GB2', 120), ('GB1', 100), ('GH', 90), ('AD', 89), ('GA100', 80), ('GA', 86), ('TU', 75),
                    ('GV', 70), ('GP', 60), ('GM', 50), ('GK', 30), ('GF', 20)]

PCI_GPU_RE = re.compile(r'\[03[0-9a-f]{2}\]:\s+NVIDIA Corporation\s+(?:(\S+)\s+)?(?:\[(.+?)\]\s+)?\[10de:([0-9a-f]{4})\]',
                        re.I)


def arch_of_codename(code):
    code = str(code or '').upper()
    for prefix, arch in sorted(ARCH_OF_CODENAME, key = lambda x: -len(x[0])):
        if code.startswith(prefix):
            return arch
    return None


def pci_gpus(lspci_nn):
    """The NVIDIA GPUs of "lspci -nn" (display controllers, class 03xx) before any driver runs: [{name,
    compute_cap, pci_id}] - the name of the PCI database (RTX PRO 1000 Blackwell Generation Laptop GPU) and the
    compute capability of its chip's code name (GB207GLM: 120), None when the database does not know it."""
    found = []
    for line in (lspci_nn or '').splitlines():
        m = PCI_GPU_RE.search(line)
        if not m:
            continue
        code, name, device = m.group(1) or '', m.group(2) or '', m.group(3)
        if code.lower() == 'device':
            code = ''
        found.append({'name': ('NVIDIA ' + name) if name else f'NVIDIA GPU 10de:{device}',
                      'compute_cap': arch_of_codename(code), 'pci_id': f'10de:{device}', 'driver_version': None})
    return found


############################################################ Linux: what is installed already

# Distribution packages that hold an NVIDIA kernel module (the driver itself) - left to the distribution to upgrade
DISTRO_DRIVER_RE = re.compile(r'^(nvidia-driver-|nvidia-dkms-|linux-modules-nvidia-|linux-objects-nvidia-|'
                              r'kmod-nvidia|akmod-nvidia|nvidia-open|nvidia-kmod)')

# ... and the user-space parts of a distribution's driver: nvidia-smi and the libraries, which NVIDIA's installer
# would collide with. Not the container toolkit, nor the firmware of linux-firmware.
DISTRO_USERSPACE_RE = re.compile(r'^(nvidia-utils-|libnvidia-(compute|decode|encode|extra|fbc1|gl|cfg1|common)|'
                                 r'nvidia-kernel-common-|nvidia-kernel-source-|nvidia-firmware-|nvidia-compute-utils-|'
                                 r'xserver-xorg-video-nvidia-)')


def distro_packages(dpkg_l):
    """(the packages of a distribution driver, the user-space packages) among the installed ones ("dpkg -l")."""
    drivers_, userspace = [], []
    for line in (dpkg_l or '').splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith('ii'):
            continue
        name = parts[1].split(':', 1)[0]
        if DISTRO_DRIVER_RE.match(name):
            drivers_.append(name)
        elif DISTRO_USERSPACE_RE.match(name):
            userspace.append(name)
    return drivers_, userspace


############################################################ Linux: Secure Boot

# The module-signing key pairs a Linux keeps for the modules it builds (private key, certificate): Ubuntu's (made by
# update-secureboot-policy, used by its DKMS) and DKMS's own
MOK_PAIRS = [('/var/lib/shim-signed/mok/MOK.priv', '/var/lib/shim-signed/mok/MOK.der'),
             ('/var/lib/dkms/mok.key', '/var/lib/dkms/mok.pub')]


def enrolled(mokutil_test_key_output):
    """mokutil --test-key: "<cert> is already enrolled"."""
    return 'is already enrolled' in (mokutil_test_key_output or '')


def signing_args(private_key, certificate):
    """NVIDIA's installer signs the modules it builds with this pair, so Secure Boot loads them."""
    return ['--module-signing-secret-key=' + private_key, '--module-signing-public-key=' + certificate]


############################################################ Linux: can it be built here? (versions vs build vs gcc)

def kernel_compiler(proc_version):
    """(compiler, version) the running kernel was built with, from /proc/version: ('gcc', '15.2.0'), ('clang',
    '19.1.7'), or (None, None)."""
    text = proc_version or ''
    m = re.search(r'clang version (\d+(?:\.\d+)+)', text)
    if m:
        return 'clang', m.group(1)
    m = re.search(r'gcc(?:-\d+)?\s+(?:\([^)]*\)\s+)?(?:version\s+)?(\d+\.\d+(?:\.\d+)?)', text)
    if m:
        return 'gcc', m.group(1)
    return None, None


def kernel_at_least(kernel_release, minimum):
    """7.0.0-43-generic >= 7.0: the numbers of the release compared with as many numbers as the minimum has."""
    have, want = key(kernel_release.split('-')[0]), key(minimum)
    return have[:len(want)] >= want


def known_failure(version, kernel_release, known):
    """A known build failure of this driver release on this kernel (known_build_failures of _desc.yaml), or None: a
    branch from a kernel on, up to the release that fixed it when one did."""
    for k in known or []:
        if str(branch(version)) != str(k.get('branch')) or not kernel_at_least(kernel_release, str(k.get('kernel_from'))):
            continue
        if k.get('fixed_in') and key(version) >= key(k['fixed_in']):
            continue
        return k
    return None


def preflight(f, known = None):
    """What installing a driver release with NVIDIA's .run installer needs here, checked before anything is
    downloaded: [(state, what, detail)] with state ok / warn / fail - any fail stops the install.

    f: kernel (release), proc_version, cc (the version of the compiler found, None), make, headers, dkms (its version,
    or None), secure_boot, signing ((private key, certificate) enrolled, or None), distro_driver, distro_userspace
    (lists of packages), version (the release to install)."""
    checks = []
    add = lambda state, what, detail: checks.append((state, what, detail))

    kernel = f.get('kernel') or '?'
    compiler, kcc = kernel_compiler(f.get('proc_version'))
    if compiler == 'clang':
        add('warn', 'compiler', f'the kernel {kernel} was built with clang {kcc}: NVIDIA\'s installer builds with gcc - '
                                f'it may refuse the mix')
    elif not f.get('cc'):
        add('fail', 'compiler', f'no gcc: the kernel {kernel} was built with gcc {kcc or "?"} - Ubuntu / Debian: '
                                f'sudo apt install gcc{"-" + kcc.split(".")[0] if kcc else ""}')
    elif kcc and key(f['cc'])[:1] != key(kcc)[:1]:
        add('fail', 'compiler', f'gcc {f["cc"]} here, but the kernel {kernel} was built with gcc {kcc}: a module must be '
                                f'built by the same major version - sudo apt install gcc-{kcc.split(".")[0]}')
    else:
        add('ok', 'compiler', f'gcc {f["cc"]}, as the kernel {kernel} (gcc {kcc or "?"})')

    if not f.get('make'):
        add('fail', 'make', 'no make - Ubuntu / Debian: sudo apt install make (or build-essential)')

    if f.get('headers'):
        add('ok', 'kernel headers', f'/lib/modules/{kernel}/build')
    else:
        add('fail', 'kernel headers', f'missing for {kernel} - Ubuntu / Debian: sudo apt install linux-headers-{kernel}')

    if f.get('dkms'):
        add('ok', 'DKMS', f'{f["dkms"]}: the module is rebuilt for every new kernel')
    else:
        add('fail', 'DKMS', 'not installed: it rebuilds the module for every new kernel - Ubuntu / Debian: sudo apt '
                            'install dkms')

    if not f.get('secure_boot'):
        add('ok', 'Secure Boot', 'off: the module needs no signature')
    elif f.get('signing'):
        add('ok', 'Secure Boot', f'on: the module is signed with {f["signing"][1]}, enrolled in the firmware')
    else:
        add('fail', 'Secure Boot', 'on, and no module-signing key here is enrolled in the firmware: the module would not '
                                   'load. Ubuntu: sudo update-secureboot-policy --new-key && sudo update-secureboot-policy '
                                   '--enroll-key, then reboot and enroll it in the MOK manager')

    if f.get('distro_driver'):
        add('fail', 'distribution', f'its driver is installed ({", ".join(f["distro_driver"])}): upgrade it with the '
                                    f'distribution, not with NVIDIA\'s .run installer')
    elif f.get('distro_userspace'):
        add('fail', 'distribution', f'its NVIDIA user-space packages are installed without its driver, and NVIDIA\'s '
                                    f'installer would collide with them - remove them first: sudo apt purge '
                                    f'{" ".join(sorted(f["distro_userspace"]))}')

    version = f.get('version')
    failure = known_failure(version, kernel, known) if version else None
    if failure:
        add('warn', 'known failure', f'R{failure.get("branch")} did not build on kernel {failure.get("kernel_from")}+ '
                                     f'({failure.get("seen", "seen before")}) - if {version} fails too, an older branch: '
                                     f'--version={failure.get("try_branch") or "<branch>"}')
    return checks


def blocking(checks):
    return [c for c in checks if c[0] == 'fail']


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
