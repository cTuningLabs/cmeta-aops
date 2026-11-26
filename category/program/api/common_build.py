"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared by the programs that build large projects from source (build-vllm, build-pytorch, build-pytorchvision,
build-llama-cpp with its own lighter figure per job):

    from program_22788f3c30d04e6d.api.common_build import default_max_jobs

Their build systems start one compile job per CPU unless MAX_JOBS says otherwise, and a compile job
can take several GiB of RAM (a CUDA kernel, PyTorch's vectorized C++ kernels): on a laptop with many
cores and little RAM the build then ends in an out-of-memory kill - and the kernel's killer takes the
user's session with it. default_max_jobs() sizes MAX_JOBS to the RAM that is free for the build.

The optional parts of such a build - resolve_components(): a program declares its parts ("components") and named sets
of them ("variations") in its _desc.yaml; a request turns parts on or off (--compile.components.<name>, <name>-) or
names a set (--compile.variation=<name>); the function says, for this system and these targets, which parts are on,
why, the build variables that follow and the submodules that need not be fetched with everything under them.
"""

import os
import re
import subprocess
import sys

SYSTEM_RESERVE_GIB = 2.0    # kept for the OS, a desktop, the build's own driver processes
CUDA_JOB_GIB = 4.0          # a CUDA or HIP kernel (nvcc/hipcc, their host compiler and ptxas)
CXX_JOB_GIB = 3.0           # a C++ job: PyTorch 2.14's ATen kernels (*.AVX2.cpp, *.AVX512.cpp) pass 1.5 GiB
                            # and peak higher - 15 jobs of "2 GiB" on a 30 GiB laptop ended in an OOM kill


def _windows_memory_status():
    """GlobalMemoryStatusEx, or None."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('sullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        return m
    except Exception:
        return None


def total_ram_gib():
    """The machine's RAM in GiB, or None."""
    try:
        if hasattr(os, 'sysconf') and 'SC_PHYS_PAGES' in os.sysconf_names:
            return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30
    except (ValueError, OSError):
        pass
    if sys.platform == 'darwin':
        try:
            import subprocess
            return int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'])) / 2**30
        except Exception:
            return None
    if os.name == 'nt':
        m = _windows_memory_status()
        return None if m is None else m.ullTotalPhys / 2**30
    return None


def available_ram_gib():
    """The RAM a new process can take now, in GiB: MemAvailable of /proc/meminfo on Linux (the free
    pages plus the reclaimable cache), the free physical memory on Windows; None where the OS does not
    say it this simply (macOS)."""
    if sys.platform.startswith('linux'):
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemAvailable:'):
                        return int(line.split()[1]) / 2**20   # kB
        except (OSError, ValueError, IndexError):
            pass
        return None
    if os.name == 'nt':
        m = _windows_memory_status()
        return None if m is None else m.ullAvailPhys / 2**30
    return None


def default_max_jobs(device, nvcc_threads = 1, per_job_gib = None):
    """Parallel compile jobs that fit the RAM: 4 GiB per CUDA/ROCm job, 3 GiB per C++ job (or per_job_gib, the
    figure of a lighter project), after 2 GiB kept for the system. The budget is the RAM available now when
    the OS says it (a build next to a browser, a VM or another build gets fewer jobs), the machine's RAM
    otherwise; never more jobs than CPUs, never fewer than one; one job per CPU, as the build systems do,
    when the RAM is unknown."""
    cpus = os.cpu_count() or 1
    ram = total_ram_gib()
    if ram is None:
        return cpus
    available = available_ram_gib()
    budget = ram if available is None else min(ram, available)
    per_job = (per_job_gib or (CUDA_JOB_GIB if device in ('cuda', 'rocm') else CXX_JOB_GIB)) * max(1, nvcc_threads)
    return max(1, min(cpus, int((budget - SYSTEM_RESERVE_GIB) / per_job)))


###################################################################################################
# The host compilers a build takes: its own limits, by system

def version_key(version):
    """19.44.35211 -> (19, 44, 35211): what orders versions (a part that is no number counts 0)."""
    return tuple(int(p) if p.isdigit() else 0 for p in str(version or '').strip().split('.'))


def msvc_installed(run = subprocess.run, environ = None):
    """
    The MSVC compilers of this Windows machine: [(cl.exe version, installation folder)], the newest first.

    Every Visual Studio installation the Visual Studio Installer's vswhere lists (its fixed place under
    %ProgramFiles(x86)%), the toolset each one's vcvars takes (the one its
    VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt names), and the version that toolset's cl.exe prints in
    its banner - the version cMeta's msvc tool detects for that installation. An installation without the C++ tools
    is not listed. [] where it cannot be asked (no vswhere: no Visual Studio Installer, or another system).
    """
    environ = os.environ if environ is None else environ
    base = environ.get('ProgramFiles(x86)') or ''
    vswhere = os.path.join(base, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe') if base else ''
    if not vswhere or not os.path.isfile(vswhere):
        return []
    try:
        p = run([vswhere, '-all', '-products', '*', '-property', 'installationPath', '-utf8'],
                stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE, timeout = 60)
        folders = [x.strip() for x in p.stdout.decode('utf-8', 'replace').splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        return []

    found = {}
    for folder in folders:
        named = os.path.join(folder, 'VC', 'Auxiliary', 'Build', 'Microsoft.VCToolsVersion.default.txt')
        if not os.path.isfile(named):
            continue
        with open(named, encoding = 'utf-8', errors = 'replace') as f:
            toolset = f.read().strip()
        for host, target in (('Hostx64', 'x64'), ('HostARM64', 'arm64')):         # the same toolset: the same version
            cl = os.path.join(folder, 'VC', 'Tools', 'MSVC', toolset, 'bin', host, target, 'cl.exe')
            if toolset and os.path.isfile(cl):
                break
        else:
            continue
        try:
            p = run([cl], stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE, timeout = 60)
        except (OSError, subprocess.SubprocessError):
            continue
        said = re.search(r'version\s*([0-9][0-9.]*)', (p.stderr + p.stdout).decode('utf-8', 'replace'), re.I)
        if said:
            found.setdefault(said.group(1).rstrip('.'), folder)                # two editions of one release: the first listed
    return sorted(found.items(), key = lambda x: version_key(x[0]), reverse = True)


def compiler_outside_limits(installed, limits, matches):
    """
    The compiler a build takes when it declares limits on it.

    installed: [(version, where)], the newest first; limits: [{'exclude': <a version range, as a request writes it:
    '>=19.51,<19.52'>, 'reason': ..., 'since': ...}]; matches(range, version) -> bool (cMeta's own version match).

    -> {'newest': the newest installed one (version, where) or None,
        'excluded': [(version, where, reason)] - the installed ones a limit excludes, the newest first,
        'choice': (version, where) - the newest one no limit excludes, when the newest itself is excluded;
                  None when nothing is to be changed (none installed or listed, or the newest is not excluded)
                  and when no installed one is left ('none_left': True)}
    """
    installed = sorted(installed or [], key = lambda x: version_key(x[0]), reverse = True)
    excluded, free = [], []
    for version, where in installed:
        why = next((str(l.get('reason') or 'declared without a reason') for l in (limits or [])
                    if l.get('exclude') and matches(str(l['exclude']), version)), None)
        if why is None:
            free.append((version, where))
        else:
            excluded.append((version, where, why))
    result = {'newest': installed[0] if installed else None, 'excluded': excluded, 'choice': None, 'none_left': False}
    if installed and excluded and excluded[0][0] == installed[0][0]:
        if free:
            result['choice'] = free[0]
        else:
            result['none_left'] = True
    return result


def host_compute(compute, system, sycl_targets = ('xpu',)):
    """
    The targets a build asks its host compilers (C and C++) for: its targets without those whose kernels another
    compiler builds, which the build finds by itself - on Linux, xpu: PyTorch builds for an Intel GPU with the
    machine's compiler (GCC, as Intel's own instructions do) and compiles its SYCL kernels with icpx of oneAPI,
    which its CMake finds in the oneAPI environment. Asked for xpu, the compiler task would take the one compiler
    that names it (icpx) for everything, and the third-party code that builds with -Werror stops on icpx's warnings.
    Every other system and target: the targets as they are (Windows builds with MSVC and names icx itself).
    """
    compute = [str(c) for c in (compute or [])]
    if system != 'linux' or not any(c in sycl_targets for c in compute):
        return compute
    return [c for c in compute if c not in sycl_targets] or ['cpu']


def toolkit_request(rules, built, asked, matches):
    """
    What a build asks of a vendor's toolkit for the version of the program it builds (toolkits: <target>: <tool> of
    a program's _desc.yaml).

    rules: [{'program_version': '>=2.15,<2.16' - the versions of the program the rule is for,
             'version': '2026.1' - the toolkit release its vendor names for them,
             'works_with': '>=2026.0' - optional: the releases the build is seen to work with, when that is known to
                                        be more than the named one,
             'reason': ..., 'source': ...}];
    built: the version that is built ('2.15.0'; '' when it is no release - a branch);
    asked: the version the request names for the tool ('' when none); matches(range, version) -> bool.

    -> {'rule': the first rule whose program_version the built version matches, or None,
        'version': what to ask the tool for - the rule's version, when the request names none; else None,
        'outside': True when the request names a plain version outside what the rule says works}

    A version no rule names asks nothing, and a version the request names is taken as asked.
    """
    rule = None
    if built:
        rule = next((r for r in (rules or []) if isinstance(r, dict) and r.get('program_version') and
                     matches(str(r['program_version']), str(built))), None)
    result = {'rule': rule, 'version': None, 'outside': False}
    if not rule or not rule.get('version'):
        return result

    asked = str(asked or '').strip()
    if not asked:
        result['version'] = str(rule['version'])
    elif re.fullmatch(r'=*[0-9.]+', asked):
        result['outside'] = not matches(str(rule.get('works_with') or rule['version']), asked.lstrip('='))
    return result


def drivers_older_than_named(rules, built, versions, matches):
    """
    The drivers of a machine that are older than the one a vendor names for the version of the program that is
    built (drivers: <target>: <system> of a program's _desc.yaml).

    rules: [{'program_version': '>=2.15,<2.16', 'min': '32.0.101.9033', 'source': ...}]; built: the version that is
    built ('' for a branch); versions: the driver versions the target read on this machine; matches(range, version).

    -> (the first rule whose program_version the built version matches, or None,
        the versions older than its 'min', as they were given). A version that is no dotted number is left out:
        nothing is said of what cannot be compared.
    """
    rule = None
    if built:
        rule = next((r for r in (rules or []) if isinstance(r, dict) and r.get('program_version') and r.get('min') and
                     matches(str(r['program_version']), str(built))), None)
    if not rule:
        return None, []
    least = version_key(rule['min'])
    older = [v for v in (versions or []) if re.fullmatch(r'[0-9]+(\.[0-9]+)*', str(v).strip()) and version_key(v) < least]
    return rule, older


###################################################################################################
# What a Python project's metadata lists

def declared_license_files(folder):
    """
    The licence files a Python project lists in its metadata (project.license-files of its pyproject.toml, PEP 639):
    paths or patterns relative to the project. A build back-end refuses the build when one of them matches no file -
    so a source tree fetched without some of its submodules still needs the ones that hold such a file.

    -> the list ([] when the project lists none or has no pyproject.toml); None when this Python cannot read TOML
       (before 3.11) or the file cannot be read: the caller then leaves nothing out.
    """
    path = os.path.join(str(folder or ''), 'pyproject.toml')
    if not os.path.isfile(path):
        return []
    try:
        import tomllib
    except ImportError:
        return None
    try:
        with open(path, 'rb') as f:
            project = (tomllib.load(f) or {}).get('project') or {}
    except (OSError, ValueError):
        return None
    listed = project.get('license-files')
    return [str(x) for x in listed] if isinstance(listed, list) else []


###################################################################################################
# The optional parts of a build

ON_WORDS, OFF_WORDS = ('on', 'true', 'yes', '1'), ('off', 'false', 'no', '0')


def source_submodules(folder):
    """The paths of the git submodules a source tree declares (the "path = ..." lines of its .gitmodules, as Git
    writes that file), in its order; none when the tree has no such file."""
    path = os.path.join(str(folder or ''), '.gitmodules')
    if not os.path.isfile(path):
        return []
    found = []
    with open(path, encoding = 'utf-8') as f:
        for line in f:
            key, eq, value = line.strip().partition('=')
            if eq and key.strip() == 'path' and value.strip():
                found.append(value.strip())
    return found


def _switch(value):
    """on / off / None (not a switch) of a word, a bool or a number."""
    if isinstance(value, bool):
        return 'on' if value else 'off'
    word = str(value).strip().lower()
    return 'on' if word in ON_WORDS else 'off' if word in OFF_WORDS else None


def required_by(component, targets):
    """
    The targets of a run that cannot be built without a part (its required_for: {<target>: <why>} or a list):
    [(target, why)], in the order of the run's targets.
    """
    needed = (component or {}).get('required_for') or {}
    if isinstance(needed, (list, tuple)):
        needed = {str(t): '' for t in needed}
    needed = {str(t).lower(): str(why or 'it needs this part').strip() for t, why in needed.items()}
    return [(t, needed[t]) for t in (str(x).lower() for x in targets or []) if t in needed]


def required_flags(components, targets, given_flags = None):
    """
    The build variables of the parts the targets of a run cannot be built without (required_for), on - for a run that
    asks no part and no variation, whose build is otherwise the one of before the parts were declared: the parts the
    targets need are on all the same. A variable the request set itself is left to it - unless it turns such a part
    off, which is an error (as in resolve_components).
    -> {'return': 0, 'flags': {<variable>: <value when on>}, 'reasons': [(part, target, why)]} or {'return': 1, 'error'}
    """
    given_flags = {str(k): v for k, v in (given_flags or {}).items()}
    flags, reasons = {}, []
    for name, c in (components or {}).items():
        needed_by = required_by(c, targets)
        if not needed_by:
            continue
        reasons.append((name, needed_by[0][0], needed_by[0][1]))
        for var, values in ((c or {}).get('flags') or {}).items():
            if var not in given_flags:
                flags[var] = str(values[0])
                continue
            v, off_value = str(given_flags[var]).strip().lower(), str(values[1]).strip().lower()
            if v == off_value or (_switch(v) == 'off' and _switch(off_value) == 'off'):
                return {'return': 1, 'error': f'--compile.d.{var}={given_flags[var]}: the target {needed_by[0][0]} cannot be '
                                              f'built without the part {name} ({needed_by[0][1]})'}
    return {'return': 0, 'flags': flags, 'reasons': reasons}


def resolve_components(components, variations = None, variation = None, asked = None, facts = None, given_flags = None):
    """
    Which optional parts of a build are on, and what follows.

    components (a program's _desc.yaml), in the order they are declared - {name: {...}}:
        desc        what the part is, in words
        flags       {<build variable>: [<value when on>, <value when off>]}
        submodules  the git submodules of the source the part alone reads: with the part off they are fetched
                    without their own submodules (their folders stay - a build's own checks may want them). A version
                    of the source may carry one in its own tree instead: see facts['submodules']
        os          the systems the part can be built on (linux, darwin, windows); none: all
        targets     the compute targets it is for (cuda, rocm ...): on only when one of them is asked; none: all
        requires    other parts it needs on
        required_for  the targets that cannot be built without it: {<target>: <why>} (or a list of targets) - with
                    one of them asked, the part is on whatever its default or the variation says, and asking it off
                    is an error
        default     on | off | auto (the build's own choice: no variable is set, its submodules are fetched whole),
                    or by system: {windows: off, '*': auto}; none: auto
    variations: {name: {desc, components: {<part>: on | off | auto}}} - named sets; variation: the one asked for
    asked: {<part>: on | off} - the request's own word (--compile.components.<part>, <part>-)
    facts: {'os': 'windows', 'targets': ['cpu']} - this run; and 'submodules': the submodules this version of the source
           has (source_submodules) - a part's submodule that is not among them is nothing to leave out, and is said
    given_flags: {<build variable>: <value>} - the build variables the request set itself (--compile.d.<VAR>=...):
                 such a variable is the request's word for its part, and is left as it is

    The order of the rule, the first that speaks: the part cannot be built here -> off; the request asked the part;
    the request set one of the part's build variables; a target that requires it (required_for) -> on; the variation;
    the part's default. Then: a part whose required part is off is off. A request that cannot be honoured is an error, never a silent change: an unknown
    part or variation, a part asked on where it cannot be built or whose required part is off, a part asked one way
    and its build variable set the other way.

    -> {'return': 0, 'parts': {name: {'state': on | off | auto, 'why': ..., 'applies': bool}}, 'flags': {VAR: value},
        'not_recursive': [submodule paths], 'not_in_source': [the declared ones this source does not have],
        'lines': [the table for the console]}  or  {'return': 1, 'error': ...}
    """
    components = components or {}
    variations = variations or {}
    asked = {str(k): v for k, v in (asked or {}).items()}
    facts = facts or {}
    given_flags = {str(k): v for k, v in (given_flags or {}).items()}
    system = str(facts.get('os') or '').lower()
    targets = [str(t).lower() for t in (facts.get('targets') or [])]

    def error(text):
        return {'return': 1, 'error': text}

    unknown = sorted(k for k in asked if k not in components)
    if unknown:
        return error(f'--compile.components: no such part{"s" if len(unknown) != 1 else ""} of this build: {", ".join(unknown)} '
                     f'(its parts: {", ".join(components) or "none declared"})')
    chosen = {}
    if variation not in (None, '', False):
        variation = str(variation)
        if variation not in variations:
            return error(f'--compile.variation={variation}: no such variation of this build (it has: {", ".join(variations) or "none"})')
        chosen = (variations[variation] or {}).get('components') or {}
        strange = sorted(k for k in chosen if k not in components)
        if strange:
            return error(f'the variation {variation} names parts this build does not declare: {", ".join(strange)}')

    parts = {}
    for name, c in components.items():
        c = c or {}
        only_os = [str(x).lower() for x in (c.get('os') or [])]
        only_targets = [str(x).lower() for x in (c.get('targets') or [])]
        wish = _switch(asked[name]) if name in asked else None
        if name in asked and wish is None:
            return error(f'--compile.components.{name}: on or off (got "{asked[name]}")')

        why_not = ''
        if only_os and system not in only_os:
            why_not = f'not for {system or "this system"} (only {", ".join(only_os)})'
        elif only_targets and not [t for t in targets if t in only_targets]:
            why_not = f'only for the target{"s" if len(only_targets) != 1 else ""} {", ".join(only_targets)}'
        needed_by = required_by(c, targets)
        if why_not:
            if wish == 'on':
                return error(f'--compile.components.{name}: this part cannot be built here - {why_not}')
            if needed_by:
                return error(f'the target {needed_by[0][0]} needs the part {name} ({needed_by[0][1]}), which cannot be built '
                             f'here - {why_not}')
            parts[name] = {'state': 'off', 'why': why_not, 'applies': False}
            continue

        # the request's own build variables of this part: its word for the part
        said = {}
        for var, values in (c.get('flags') or {}).items():
            if var in given_flags:
                v = str(given_flags[var]).strip().lower()
                on_value, off_value = (str(x).strip().lower() for x in values)
                said[var] = 'on' if v == on_value or (_switch(v) == 'on' and _switch(on_value) == 'on') else \
                            'off' if v == off_value or (_switch(v) == 'off' and _switch(off_value) == 'off') else None
        by_flag = sorted({x for x in said.values() if x})
        if len(by_flag) > 1:
            return error(f'the build variables of the part {name} are set both ways: ' + ', '.join(f'{k}={given_flags[k]}' for k in said))
        by_flag = by_flag[0] if by_flag else None

        if needed_by and 'off' in (wish, by_flag):
            word = f'--compile.components.{name}-' if wish == 'off' else \
                   f'--compile.d.{next(k for k, v in said.items() if v == "off")}={given_flags[next(k for k, v in said.items() if v == "off")]}'
            return error(f'{word}: the target {needed_by[0][0]} cannot be built without the part {name} ({needed_by[0][1]})')

        if wish:
            if by_flag and by_flag != wish:
                var = next(k for k, v in said.items() if v == by_flag)
                return error(f'--compile.components.{name} is asked {wish}, and --compile.d.{var}={given_flags[var]} says {by_flag}: one of them')
            parts[name] = {'state': wish, 'why': 'asked', 'applies': True, 'asked': True}
        elif by_flag:
            var = next(k for k, v in said.items() if v == by_flag)
            parts[name] = {'state': by_flag, 'why': f'by --compile.d.{var}={given_flags[var]}', 'applies': True, 'asked': True}
        elif needed_by:
            parts[name] = {'state': 'on', 'why': f'needed by the target {needed_by[0][0]}', 'applies': True}
        elif name in chosen:
            state = _switch(chosen[name]) or ('auto' if str(chosen[name]).strip().lower() == 'auto' else None)
            if state is None:
                return error(f'the variation {variation} says "{chosen[name]}" for the part {name}: on, off or auto')
            parts[name] = {'state': state, 'why': f'variation {variation}', 'applies': True}
        else:
            default = c.get('default')
            where = ''
            if isinstance(default, dict):
                where = f' on {system}' if system in default else ''
                default = default.get(system, default.get('*'))
            state = 'auto' if default in (None, '') or str(default).strip().lower() == 'auto' else _switch(default)
            if state is None:
                return error(f'the part {name} declares the default "{default}": on, off or auto')
            parts[name] = {'state': state, 'why': 'the build\'s own choice' if state == 'auto' else f'default{where}', 'applies': True}

    # a part whose required part is off (in the order declared: a requirement is declared before what needs it, or after)
    changed = True
    while changed:
        changed = False
        for name, c in components.items():
            for need in (c or {}).get('requires') or []:
                if need not in components:
                    return error(f'the part {name} requires "{need}", which this build does not declare')
                if parts[name]['state'] != 'off' and parts[need]['state'] == 'off':
                    if parts[name].get('asked') and parts[name]['state'] == 'on':
                        return error(f'--compile.components.{name}: this part needs {need}, which is off ({parts[need]["why"]}) - '
                                     f'add --compile.components.{need}')
                    parts[name] = {'state': 'off', 'why': f'needs {need}, which is off', 'applies': parts[name]['applies']}
                    changed = True

    flags, not_recursive = {}, []
    for name, c in components.items():
        c, part = c or {}, parts[name]
        if part['state'] == 'off':
            for path in c.get('submodules') or []:
                if path not in not_recursive:
                    not_recursive.append(str(path))
        if part['applies'] and part['state'] in ('on', 'off'):
            for var, values in (c.get('flags') or {}).items():
                if var not in given_flags:
                    flags[var] = str(values[0 if part['state'] == 'on' else 1])
    # a submodule that a part which is not off also names is fetched whole
    for name, c in components.items():
        if parts[name]['state'] != 'off':
            not_recursive = [x for x in not_recursive if x not in ((c or {}).get('submodules') or [])]

    # ... and one this version of the source does not have is nothing to leave out
    not_in_source = []
    if facts.get('submodules') is not None:
        have = [str(x) for x in facts['submodules']]
        not_in_source = [x for x in not_recursive if x not in have]
        not_recursive = [x for x in not_recursive if x in have]

    width = max([len(n) for n in components] + [4])
    lines = [f'The parts of this build' + (f' (variation {variation}' if variation else ' (no variation') +
             f'; {system or "?"}, {",".join(targets) or "cpu"}):']
    for name, c in components.items():
        part = parts[name]
        what = [f'{k}={v}' for k, v in flags.items() if k in ((c or {}).get('flags') or {})]
        if part['state'] == 'off' and (c or {}).get('submodules'):
            left = [x for x in (c or {}).get('submodules') if x in not_recursive]
            if left:
                what.append(', '.join(left) + ' without ' + ('its' if len(left) == 1 else 'their') + ' own submodules')
            gone = [x for x in (c or {}).get('submodules') if x in not_in_source]
            if gone:
                what.append(', '.join(gone) + ': no submodule of this source')
        lines.append(f'  {name:<{width}}  {part["state"]:<4}  {part["why"]}' + (f'  ->  {"; ".join(what)}' if what else ''))
    return {'return': 0, 'parts': parts, 'flags': flags, 'not_recursive': not_recursive, 'not_in_source': not_in_source,
            'lines': lines, 'variation': variation or ''}

