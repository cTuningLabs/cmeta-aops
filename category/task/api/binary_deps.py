"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The dependencies of a binary, read from its headers in pure Python (no ldd, otool or dumpbin): ELF
(DT_NEEDED, RPATH/RUNPATH, the interpreter), PE (the import and delay-import tables) and Mach-O
(LC_LOAD_DYLIB and friends, @rpath), and the resolution of every dependency to the file the loader
would take under a given environment. Any format can be read on any OS - only the headers are read
(a few kilobytes, whatever the size of the binary).

Used by the provenance record of a program run (category/task/api/provenance.py) and, later, by the
static-build tests instead of ldd/otool/PE reads.

API (stable for the callers):

  inspect(path) -> dict
      {'format': 'elf' | 'pe' | 'macho' | None, 'arch': str | None, 'bits': 32 | 64 | None,
       'static': bool,                 # ELF: no dynamic loader and no needed libraries;
                                       # PE and Mach-O: nothing needed beyond the OS runtime
       'interpreter': str | None,      # ELF PT_INTERP
       'needed': [str],                # library names as recorded in the binary (ELF/PE/Mach-O)
       'delay_needed': [str],          # PE delay-import DLLs
       'rpath': [str], 'runpath': [str],   # ELF; Mach-O LC_RPATH goes to 'rpath'
       'kind': 'executable' | 'shared' | 'object' | None,
       'slices': [str],                # Mach-O fat: the architectures it holds
       'error': str | None}            # a file that is not a binary of a known format

  resolve(path, env = None, cwd = None, uname = None, system_dirs = None, ld_cache = None) -> dict
      inspect() plus
      {'deps': [{'name': str, 'path': str | None, 'source': str | None, 'system': bool}],
       'missing': [str]}
      'source' says where the loader would take the file from: 'rpath', 'runpath', 'env'
      (LD_LIBRARY_PATH / PATH / DYLD_LIBRARY_PATH of `env`), 'app' (the binary's folder, or
      @loader_path / @executable_path), 'cwd' (Windows: the current folder), 'absolute' (a path
      written into the binary), 'system' (the OS folders, ld.so.cache, the macOS shared cache),
      'api' (a Windows API-set name resolved by the OS), None when not found. `env` defaults to
      os.environ; `uname` ('windows' | 'linux' | 'darwin') defaults to the current OS; the search
      order follows the binary's format, the host's own folders are used only when the format is
      the host's (or when `system_dirs` / `ld_cache` name them).

  is_system_library(name_or_path, uname = None) -> bool
      True for the OS's own runtime: glibc/musl and the dynamic loader on Linux; libSystem, libc++,
      libobjc and the /System frameworks on macOS; KERNEL32/USER32/..., api-ms-win-*, ucrtbase,
      VCRUNTIME*/MSVCP* on Windows. Not a policy: callers decide what else is allowed (libstdc++,
      libgcc_s, the CUDA driver, NVIDIA's shared libraries, the OpenMP runtimes).

  describe(info) -> str
      One line for messages: "ELF x86_64, dynamic: libcudart.so.12 (…/cuda-12.9/lib64), libcrypto.so.3 (system), …".
"""

import glob
import os
import struct
import sys

###################################################################################################
# Formats and architectures

ELF_MACHINES = {0x02: 'sparc', 0x03: 'i386', 0x08: 'mips', 0x14: 'ppc', 0x15: 'ppc64', 0x16: 's390',
                0x28: 'arm', 0x2A: 'superh', 0x32: 'ia64', 0x3E: 'x86_64', 0xB7: 'aarch64',
                0xF3: 'riscv', 0xF7: 'bpf', 0x102: 'loongarch'}
PE_MACHINES = {0x14C: 'i386', 0x8664: 'x86_64', 0x1C0: 'arm', 0x1C4: 'arm', 0xAA64: 'aarch64',
               0x200: 'ia64', 0x5064: 'riscv', 0x6264: 'loongarch'}
MACHO_CPU = {7: 'i386', 0x01000007: 'x86_64', 12: 'arm', 0x0100000C: 'aarch64', 18: 'ppc', 0x01000012: 'ppc64'}

# Linux multiarch folder of an architecture (Debian/Ubuntu)
MULTIARCH = {'x86_64': 'x86_64-linux-gnu', 'i386': 'i386-linux-gnu', 'aarch64': 'aarch64-linux-gnu',
             'arm': 'arm-linux-gnueabihf', 'riscv': 'riscv64-linux-gnu', 'ppc64': 'powerpc64le-linux-gnu',
             's390': 's390x-linux-gnu', 'loongarch': 'loongarch64-linux-gnu'}

# The OS's own runtime, by the start of the library's basename (Linux) or path (macOS) or lower-case
# name (Windows). Not a policy: libstdc++, libgcc_s, OpenMP runtimes, zlib, OpenSSL are libraries.
LINUX_SYSTEM_PREFIXES = ('ld-linux', 'ld-musl', 'ld64.so', 'ld.so', 'ld-2.', 'linux-vdso', 'linux-gate',
                         'libc.so', 'libc-2.', 'libc.musl', 'libm.so', 'libm-2.', 'libdl.so', 'libdl-2.',
                         'libpthread.so', 'libpthread-2.', 'librt.so', 'librt-2.', 'libresolv.so',
                         'libresolv-2.', 'libutil.so', 'libutil-2.', 'libnsl.so', 'libanl.so', 'libmvec.so',
                         'libBrokenLocale', 'libnss_', 'libthread_db')
DARWIN_SYSTEM_PREFIXES = ('/usr/lib/libSystem', '/usr/lib/libc++', '/usr/lib/libobjc', '/usr/lib/system/',
                          '/usr/lib/libresolv', '/usr/lib/libiconv', '/usr/lib/libcharset', '/System/Library/',
                          'libSystem', 'libc++', 'libobjc')
WINDOWS_SYSTEM_NAMES = {'kernel32', 'kernelbase', 'user32', 'gdi32', 'advapi32', 'shell32', 'ole32',
                        'oleaut32', 'ws2_32', 'ntdll', 'shlwapi', 'comdlg32', 'winmm', 'rpcrt4', 'sechost',
                        'bcrypt', 'bcryptprimitives', 'comctl32', 'version', 'imm32', 'setupapi', 'userenv',
                        'iphlpapi', 'dbghelp', 'psapi', 'crypt32', 'wldap32', 'normaliz', 'winhttp',
                        'wininet', 'secur32', 'cfgmgr32', 'powrprof', 'dwmapi', 'uxtheme', 'opengl32',
                        'mswsock', 'winspool', 'propsys', 'msvcrt'}
WINDOWS_SYSTEM_PREFIXES = ('api-ms-win-', 'ext-ms-', 'ucrtbase', 'msvcrt', 'msvcr', 'vcruntime', 'msvcp',
                           'concrt')

# ELF
PT_LOAD, PT_DYNAMIC, PT_INTERP = 1, 2, 3
DT_NULL, DT_NEEDED, DT_STRTAB, DT_STRSZ, DT_SONAME, DT_RPATH, DT_RUNPATH = 0, 1, 5, 10, 14, 15, 29
ET_EXEC, ET_DYN, ET_REL = 2, 3, 1

# Mach-O
MH_MAGIC, MH_CIGAM, MH_MAGIC_64, MH_CIGAM_64 = 0xFEEDFACE, 0xCEFAEDFE, 0xFEEDFACF, 0xCFFAEDFE
FAT_MAGIC, FAT_CIGAM, FAT_MAGIC_64, FAT_CIGAM_64 = 0xCAFEBABE, 0xBEBAFECA, 0xCAFEBABF, 0xBFBAFECA
LC_LOAD_DYLIB, LC_ID_DYLIB, LC_LAZY_LOAD_DYLIB = 0xC, 0xD, 0x20
LC_LOAD_WEAK_DYLIB, LC_RPATH, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB = 0x80000018, 0x8000001C, 0x8000001F, 0x80000023
MH_EXECUTE, MH_DYLIB, MH_BUNDLE, MH_OBJECT, MH_DYLINKER = 2, 6, 8, 1, 7

MAX_STRINGS = 64 * 1024 * 1024    # a string table larger than this is not read


class _Reader:
    """Bounded reads of a file that is never loaded whole."""

    def __init__(self, f, size):
        self.f, self.size = f, size

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError(f'read of {length} bytes at {offset} beyond the file ({self.size} bytes)')
        self.f.seek(offset)
        data = self.f.read(length)
        if len(data) != length:
            raise ValueError(f'short read at {offset}')
        return data

    def cstring(self, offset, limit = 4096):
        """A NUL-terminated string at offset (at most `limit` bytes)."""
        chunk = self.read(offset, min(limit, self.size - offset))
        end = chunk.find(b'\0')
        if end < 0:
            end = len(chunk)
        return chunk[:end].decode('utf-8', 'replace')


def _blank(path):
    return {'path': path, 'format': None, 'arch': None, 'bits': None, 'static': False, 'interpreter': None,
            'needed': [], 'delay_needed': [], 'rpath': [], 'runpath': [], 'kind': None, 'slices': [], 'error': None}


###################################################################################################
def inspect(path):
    """The format, architecture and recorded dependencies of a binary (see the module docstring)."""
    info = _blank(path)
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            r = _Reader(f, size)
            head = r.read(0, min(64, size)) if size else b''
            if head.startswith(b'\x7fELF'):
                _inspect_elf(r, info)
            elif head.startswith(b'MZ') and size >= 0x40:
                _inspect_pe(r, info)
            elif len(head) >= 4 and struct.unpack('<I', head[:4])[0] in (
                    MH_MAGIC, MH_CIGAM, MH_MAGIC_64, MH_CIGAM_64, FAT_MAGIC, FAT_CIGAM, FAT_MAGIC_64, FAT_CIGAM_64):
                _inspect_macho(r, 0, size, info, path)
            else:
                info['error'] = 'not an ELF, PE or Mach-O file'
    except (OSError, ValueError, struct.error) as e:
        info['format'] = info['format'] if info.get('error') is None and info['format'] else info['format']
        info['error'] = f'{type(e).__name__}: {e}'
    return info


###################################################################################################
# ELF

def _inspect_elf(r, info):
    ident = r.read(0, 16)
    bits = {1: 32, 2: 64}.get(ident[4])
    endian = {1: '<', 2: '>'}.get(ident[5])
    if not bits or not endian:
        raise ValueError('ELF header: unknown class or data encoding')
    info.update({'format': 'elf', 'bits': bits})
    if bits == 64:
        e_type, e_machine, _, _, e_phoff, e_shoff, _, _, e_phentsize, e_phnum, e_shentsize, e_shnum, _ = \
            struct.unpack(endian + 'HHIQQQIHHHHHH', r.read(16, 48))
    else:
        e_type, e_machine, _, _, e_phoff, e_shoff, _, _, e_phentsize, e_phnum, e_shentsize, e_shnum, _ = \
            struct.unpack(endian + 'HHIIIIIHHHHHH', r.read(16, 36))
    info['arch'] = ELF_MACHINES.get(e_machine, f'elf-machine-{e_machine:#x}')
    info['kind'] = {ET_EXEC: 'executable', ET_DYN: 'shared', ET_REL: 'object'}.get(e_type)
    if e_phnum == 0xFFFF and e_shoff:          # PN_XNUM: the real count is in section header 0
        sh0 = r.read(e_shoff, e_shentsize)
        e_phnum = struct.unpack(endian + 'I', sh0[28:32] if bits == 32 else sh0[44:48])[0]

    loads, dynamic, interp = [], None, None
    for i in range(e_phnum):
        ph = r.read(e_phoff + i * e_phentsize, e_phentsize)
        if bits == 64:
            p_type, _, p_offset, p_vaddr, _, p_filesz, p_memsz, _ = struct.unpack(endian + 'IIQQQQQQ', ph[:56])
        else:
            p_type, p_offset, p_vaddr, _, p_filesz, p_memsz, _, _ = struct.unpack(endian + 'IIIIIIII', ph[:32])
        if p_type == PT_LOAD:
            loads.append((p_vaddr, p_offset, p_filesz, p_memsz))
        elif p_type == PT_DYNAMIC:
            dynamic = (p_offset, p_filesz)
        elif p_type == PT_INTERP and p_filesz:
            interp = r.cstring(p_offset, p_filesz)
    info['interpreter'] = interp

    if dynamic:
        entry = 16 if bits == 64 else 8
        fmt = endian + ('qQ' if bits == 64 else 'iI')
        off, length = dynamic
        tags = []
        for i in range(length // entry):
            d_tag, d_val = struct.unpack(fmt, r.read(off + i * entry, entry))
            if d_tag == DT_NULL:
                break
            tags.append((d_tag, d_val))
        strtab = next((v for t, v in tags if t == DT_STRTAB), None)
        strsz = next((v for t, v in tags if t == DT_STRSZ), None)
        if strtab is not None:
            foff = _elf_vaddr_to_offset(strtab, loads)
            if foff is not None:
                if strsz is None or strsz > MAX_STRINGS:
                    strsz = min(MAX_STRINGS, r.size - foff)
                strings = r.read(foff, min(strsz, r.size - foff))

                def s(at):
                    end = strings.find(b'\0', at)
                    return strings[at:end if end >= 0 else len(strings)].decode('utf-8', 'replace')

                for t, v in tags:
                    if t == DT_NEEDED:
                        info['needed'].append(s(v))
                    elif t == DT_RPATH:
                        info['rpath'].extend(x for x in s(v).split(':') if x)
                    elif t == DT_RUNPATH:
                        info['runpath'].extend(x for x in s(v).split(':') if x)
                    elif t == DT_SONAME:
                        info['soname'] = s(v)
    info['static'] = interp is None and not info['needed']


def _elf_vaddr_to_offset(vaddr, loads):
    for p_vaddr, p_offset, p_filesz, p_memsz in loads:
        if p_vaddr <= vaddr < p_vaddr + max(p_filesz, p_memsz):
            return vaddr - p_vaddr + p_offset
    return None


###################################################################################################
# PE

def _inspect_pe(r, info):
    e_lfanew = struct.unpack('<I', r.read(0x3C, 4))[0]
    if e_lfanew + 24 > r.size or r.read(e_lfanew, 4) != b'PE\0\0':
        raise ValueError('MZ file without a PE header')
    machine, nsections, _, _, _, size_opt, characteristics = struct.unpack('<HHIIIHH', r.read(e_lfanew + 4, 20))
    opt = e_lfanew + 24
    magic = struct.unpack('<H', r.read(opt, 2))[0]
    if magic == 0x20B:
        bits, image_base, dirs_off, ndirs_off = 64, struct.unpack('<Q', r.read(opt + 24, 8))[0], 112, 108
    elif magic == 0x10B:
        bits, image_base, dirs_off, ndirs_off = 32, struct.unpack('<I', r.read(opt + 28, 4))[0], 96, 92
    else:
        raise ValueError(f'PE optional header: unknown magic {magic:#x}')
    info.update({'format': 'pe', 'bits': bits, 'arch': PE_MACHINES.get(machine, f'pe-machine-{machine:#x}'),
                 'kind': 'shared' if characteristics & 0x2000 else 'executable'})
    ndirs = struct.unpack('<I', r.read(opt + ndirs_off, 4))[0] if size_opt >= ndirs_off + 4 else 0

    def directory(index):
        if index >= ndirs or dirs_off + index * 8 + 8 > size_opt:
            return 0, 0
        return struct.unpack('<II', r.read(opt + dirs_off + index * 8, 8))

    sections = []
    sec = opt + size_opt
    for i in range(nsections):
        s = r.read(sec + i * 40, 40)
        vsize, va, rsize, raw = struct.unpack('<IIII', s[8:24])
        sections.append((va, max(vsize, rsize), raw, rsize))

    def offset_of(rva):
        for va, span, raw, rsize in sections:
            if va <= rva < va + span:
                return raw + rva - va
        if not sections and rva < r.size:
            return rva
        raise ValueError(f'RVA {rva:#x} is in no section')

    def fix(value):     # delay-import tables may hold virtual addresses instead of RVAs
        return value - image_base if value >= image_base else value

    imp_rva, _ = directory(1)
    if imp_rva:
        p = offset_of(imp_rva)
        while p + 20 <= r.size:
            _, _, _, name_rva, first_thunk = struct.unpack('<IIIII', r.read(p, 20))
            if not name_rva and not first_thunk:
                break
            if name_rva:
                info['needed'].append(r.cstring(offset_of(name_rva), 512))
            p += 20

    delay_rva, _ = directory(13)
    if delay_rva:
        p = offset_of(delay_rva)
        while p + 32 <= r.size:
            attributes, name_rva, _, _, _, _, _, _ = struct.unpack('<IIIIIIII', r.read(p, 32))
            if not name_rva:
                break
            info['delay_needed'].append(r.cstring(offset_of(name_rva if attributes & 1 else fix(name_rva)), 512))
            p += 32

    info['static'] = all(is_system_library(n, 'windows') for n in info['needed'] + info['delay_needed'])


###################################################################################################
# Mach-O

def _inspect_macho(r, base, size, info, path, wanted_arch = None):
    magic_le = struct.unpack('<I', r.read(base, 4))[0]
    if magic_le in (FAT_MAGIC, FAT_CIGAM, FAT_MAGIC_64, FAT_CIGAM_64):
        # a fat file: big-endian header; the magic read little-endian is the swapped constant
        endian = '>' if magic_le in (FAT_CIGAM, FAT_CIGAM_64) else '<'
        is64 = magic_le in (FAT_MAGIC_64, FAT_CIGAM_64)
        nfat = struct.unpack(endian + 'I', r.read(base + 4, 4))[0]
        if nfat > 64:
            raise ValueError('fat Mach-O with an implausible number of slices')
        slices = []
        for i in range(nfat):
            if is64:
                cputype, _, offset, slice_size, _, _ = struct.unpack(endian + 'IIQQII', r.read(base + 8 + i * 32, 32))
            else:
                cputype, _, offset, slice_size, _ = struct.unpack(endian + 'IIIII', r.read(base + 8 + i * 20, 20))
            slices.append((MACHO_CPU.get(cputype, f'cpu-{cputype:#x}'), offset, slice_size))
        info['slices'] = [a for a, _, _ in slices]
        if not slices:
            raise ValueError('fat Mach-O without slices')
        host = wanted_arch or _host_arch()
        chosen = next((s for s in slices if s[0] == host), slices[0])
        _inspect_macho(r, base + chosen[1], chosen[2], info, path)
        return

    endian = '<' if magic_le in (MH_MAGIC, MH_MAGIC_64) else '>'
    is64 = magic_le in (MH_MAGIC_64, MH_CIGAM_64)
    header_size = 32 if is64 else 28
    _, cputype, _, filetype, ncmds, sizeofcmds = struct.unpack(endian + 'IIIIII', r.read(base, 24))
    info.update({'format': 'macho', 'bits': 64 if is64 else 32,
                 'arch': MACHO_CPU.get(cputype, f'cpu-{cputype:#x}'),
                 'kind': {MH_EXECUTE: 'executable', MH_DYLIB: 'shared', MH_BUNDLE: 'shared', MH_OBJECT: 'object',
                          MH_DYLINKER: 'executable'}.get(filetype)})
    p = base + header_size
    end = min(base + header_size + sizeofcmds, base + size)
    for _ in range(ncmds):
        if p + 8 > end:
            break
        cmd, cmdsize = struct.unpack(endian + 'II', r.read(p, 8))
        if cmdsize < 8:
            break
        if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB, LC_LAZY_LOAD_DYLIB):
            name_off = struct.unpack(endian + 'I', r.read(p + 8, 4))[0]
            info['needed'].append(r.cstring(p + name_off, cmdsize - name_off))
        elif cmd == LC_ID_DYLIB:
            name_off = struct.unpack(endian + 'I', r.read(p + 8, 4))[0]
            info['soname'] = r.cstring(p + name_off, cmdsize - name_off)
        elif cmd == LC_RPATH:
            path_off = struct.unpack(endian + 'I', r.read(p + 8, 4))[0]
            info['rpath'].append(r.cstring(p + path_off, cmdsize - path_off))
        p += cmdsize
    info['static'] = all(is_system_library(n, 'darwin') for n in info['needed'])


def _host_arch():
    import platform
    m = platform.machine().lower()
    return {'amd64': 'x86_64', 'x86_64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86': 'i386',
            'i386': 'i386', 'i686': 'i386'}.get(m, m)


def _host_uname():
    if os.name == 'nt':
        return 'windows'
    return 'darwin' if sys.platform == 'darwin' else 'linux'


###################################################################################################
def is_system_library(name_or_path, uname = None):
    """True for the OS's own runtime (see the module docstring); never a policy about other libraries."""
    uname = uname or _host_uname()
    text = str(name_or_path)
    base = text.replace('\\', '/').rsplit('/', 1)[-1]
    if uname == 'windows':
        lower = base.lower()
        stem = lower[:-4] if lower.endswith('.dll') else lower
        return stem in WINDOWS_SYSTEM_NAMES or any(lower.startswith(p) for p in WINDOWS_SYSTEM_PREFIXES)
    if uname == 'darwin':
        return text.startswith(DARWIN_SYSTEM_PREFIXES[:8]) or base.startswith(DARWIN_SYSTEM_PREFIXES[8:])
    return base.startswith(LINUX_SYSTEM_PREFIXES)


###################################################################################################
def resolve(path, env = None, cwd = None, uname = None, system_dirs = None, ld_cache = None):
    """inspect() plus the file the loader would take for every dependency (see the module docstring)."""
    info = inspect(path)
    info['deps'], info['missing'] = [], []
    if info['error'] or not info['format']:
        return info
    env = os.environ if env is None else env
    uname = uname or _host_uname()
    app_dir = os.path.dirname(os.path.abspath(path))
    names = list(info['needed']) + list(info.get('delay_needed') or [])

    if info['format'] == 'elf':
        resolver = _ElfResolver(info, app_dir, env, uname, system_dirs, ld_cache)
        lib_uname = 'linux'
    elif info['format'] == 'pe':
        resolver = _PeResolver(info, app_dir, env, cwd, uname, system_dirs)
        lib_uname = 'windows'
    else:
        resolver = _MachoResolver(info, app_dir, env, uname, system_dirs)
        lib_uname = 'darwin'

    for name in names:
        found, source = resolver.find(name)
        system = is_system_library(found or name, lib_uname)
        info['deps'].append({'name': name, 'path': found, 'source': source, 'system': system})
        if found is None and source is None and not system:
            info['missing'].append(name)
    return info


def _split_path_list(value, sep):
    """The folders of a PATH-like list; a ':'-separated list read on Windows keeps its drive letters."""
    parts = [x for x in (value or '').split(sep) if x]
    if sep == ':' and os.name == 'nt':
        merged = []
        for x in parts:
            if merged and len(merged[-1]) == 1 and merged[-1].isalpha() and x[:1] in (chr(92), '/'):
                merged[-1] = merged[-1] + ':' + x
            else:
                merged.append(x)
        parts = merged
    return parts


def _file_in(folder, name, case_insensitive = False):
    """The file `name` in `folder`, or None; a case-insensitive match lists the folder."""
    if not folder:
        return None
    candidate = os.path.normpath(os.path.join(folder, name))
    if os.path.isfile(candidate):
        return candidate
    if case_insensitive and os.path.isdir(folder):
        lower = name.lower()
        try:
            for entry in os.listdir(folder):
                if entry.lower() == lower and os.path.isfile(os.path.join(folder, entry)):
                    return os.path.normpath(os.path.join(folder, entry))
        except OSError:
            pass
    return None


class _ElfResolver:
    def __init__(self, info, app_dir, env, uname, system_dirs, ld_cache):
        self.info, self.app_dir, self.env = info, app_dir, env
        self.host_is_linux = uname == 'linux'
        musl = 'ld-musl' in (info.get('interpreter') or '')
        self.cache = None
        if ld_cache or (self.host_is_linux and not musl and system_dirs is None):
            self.cache = _read_ld_so_cache(ld_cache or '/etc/ld.so.cache')
        if system_dirs is not None:
            self.system_dirs = list(system_dirs)
        elif self.host_is_linux:
            self.system_dirs = _linux_system_dirs(info.get('arch'), musl)
        else:
            self.system_dirs = []

    def _expand(self, folder):
        origin = self.app_dir
        return folder.replace('${ORIGIN}', origin).replace('$ORIGIN', origin)

    def find(self, name):
        if '/' in name:
            p = os.path.normpath(name if os.path.isabs(name) else os.path.join(self.app_dir, name))
            return (p, 'absolute') if os.path.isfile(p) else (None, None)
        rpath = [] if self.info['runpath'] else self.info['rpath']
        for folder in rpath:
            f = _file_in(self._expand(folder), name)
            if f:
                return f, 'rpath'
        for folder in _split_path_list(self.env.get('LD_LIBRARY_PATH'), ':'):
            f = _file_in(folder, name)
            if f:
                return f, 'env'
        for folder in self.info['runpath']:
            f = _file_in(self._expand(folder), name)
            if f:
                return f, 'runpath'
        if self.cache and name in self.cache:
            p = self.cache[name]
            if os.path.isfile(p):
                return p, 'system'
        for folder in self.system_dirs:
            f = _file_in(folder, name)
            if f:
                return f, 'system'
        return None, None


def _linux_system_dirs(arch, musl):
    if musl:
        dirs = []
        for conf in glob.glob('/etc/ld-musl-*.path'):
            try:
                with open(conf, encoding = 'utf-8', errors = 'replace') as f:
                    for line in f.read().replace(':', '\n').splitlines():
                        if line.strip():
                            dirs.append(line.strip())
            except OSError:
                pass
        return dirs + ['/lib', '/usr/local/lib', '/usr/lib']
    dirs = _ld_so_conf_dirs('/etc/ld.so.conf')
    triplet = MULTIARCH.get(arch or '')
    for d in (['/lib/' + triplet, '/usr/lib/' + triplet] if triplet else []) + \
             ['/lib64', '/usr/lib64', '/lib', '/usr/lib', '/usr/local/lib', '/lib32', '/usr/lib32']:
        if d not in dirs:
            dirs.append(d)
    return dirs


def _ld_so_conf_dirs(conf, seen = None):
    seen = seen if seen is not None else set()
    dirs = []
    if conf in seen or not os.path.isfile(conf):
        return dirs
    seen.add(conf)
    try:
        with open(conf, encoding = 'utf-8', errors = 'replace') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                if line.startswith('include '):
                    pattern = line[8:].strip()
                    if not os.path.isabs(pattern):
                        pattern = os.path.join(os.path.dirname(conf), pattern)
                    for inc in sorted(glob.glob(pattern)):
                        dirs.extend(_ld_so_conf_dirs(inc, seen))
                elif line not in dirs:
                    dirs.append(line)
    except OSError:
        pass
    return dirs


def _read_ld_so_cache(path):
    """name -> path of glibc's ld.so.cache (the old 'ld.so-1.7.0' and the new 'glibc-ld.so.cache1.1' layouts)."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    result = {}
    old_magic, new_magic = b'ld.so-1.7.0\0', b'glibc-ld.so.cache1.1'
    pos = 0
    if data.startswith(old_magic):
        nlibs = struct.unpack_from('<I', data, 12)[0]
        strings = 16 + nlibs * 12
        for i in range(nlibs):
            _, key, value = struct.unpack_from('<iII', data, 16 + i * 12)
            k, v = _cstr(data, strings + key), _cstr(data, strings + value)
            if k and k not in result:
                result[k] = v
        pos = data.find(new_magic, strings)
    elif data.startswith(new_magic):
        pos = 0
    else:
        return result or None
    if pos >= 0 and data[pos:pos + len(new_magic)] == new_magic:
        nlibs = struct.unpack_from('<I', data, pos + 20)[0]
        entries = pos + 48
        for i in range(nlibs):
            _, key, value = struct.unpack_from('<iII', data, entries + i * 24)
            k, v = _cstr(data, pos + key), _cstr(data, pos + value)
            if k and k not in result:
                result[k] = v
    return result


def _cstr(data, at):
    if at < 0 or at >= len(data):
        return ''
    end = data.find(b'\0', at)
    return data[at:end if end >= 0 else len(data)].decode('utf-8', 'replace')


class _PeResolver:
    def __init__(self, info, app_dir, env, cwd, uname, system_dirs):
        self.info, self.app_dir, self.env, self.cwd = info, app_dir, env, cwd
        self.ci = True     # DLL names are case-insensitive on Windows (and so is the match in a fake layout)
        if system_dirs is not None:
            self.system_dirs = list(system_dirs)
        else:
            root = env.get('SystemRoot') or env.get('SYSTEMROOT') or env.get('windir') or \
                   (os.environ.get('SystemRoot') if uname == 'windows' else None)
            self.system_dirs = []
            if root:
                sub = 'SysWOW64' if info.get('bits') == 32 and os.path.isdir(os.path.join(root, 'SysWOW64')) else 'System32'
                self.system_dirs = [os.path.join(root, sub), os.path.join(root, 'System'), root]

    def find(self, name):
        lower = name.lower()
        if lower.startswith(('api-ms-win-', 'ext-ms-')):
            return None, 'api'
        if '\\' in name or '/' in name:
            p = os.path.normpath(name if os.path.isabs(name) else os.path.join(self.app_dir, name))
            return (p, 'absolute') if os.path.isfile(p) else (None, None)
        f = _file_in(self.app_dir, name, self.ci)
        if f:
            return f, 'app'
        for folder in self.system_dirs:
            f = _file_in(folder, name, self.ci)
            if f:
                return f, 'system'
        if self.cwd:
            f = _file_in(self.cwd, name, self.ci)
            if f:
                return f, 'cwd'
        for folder in _split_path_list(self.env.get('PATH') or self.env.get('Path'), os.pathsep if os.name == 'nt' else ';'):
            f = _file_in(folder, name, self.ci)
            if f:
                return f, 'env'
        return None, None


class _MachoResolver:
    def __init__(self, info, app_dir, env, uname, system_dirs):
        self.info, self.app_dir, self.env = info, app_dir, env
        self.host_is_darwin = uname == 'darwin'
        self.fallback = _split_path_list(env.get('DYLD_FALLBACK_LIBRARY_PATH'), ':') or \
                        ([os.path.expanduser('~/lib'), '/usr/local/lib', '/usr/lib'] if self.host_is_darwin else [])
        if system_dirs is not None:
            self.fallback = list(system_dirs) + self.fallback

    def _expand(self, p):
        return p.replace('@loader_path', self.app_dir).replace('@executable_path', self.app_dir)

    def find(self, name):
        base = name.rsplit('/', 1)[-1]
        for folder in _split_path_list(self.env.get('DYLD_LIBRARY_PATH'), ':'):
            f = _file_in(folder, base)
            if f:
                return f, 'env'
        if name.startswith('@rpath/'):
            rest = name[len('@rpath/'):]
            for rp in self.info['rpath']:
                f = os.path.normpath(os.path.join(self._expand(rp), rest))
                if os.path.isfile(f):
                    return f, 'rpath'
        elif name.startswith(('@loader_path/', '@executable_path/')):
            f = os.path.normpath(self._expand(name))
            if os.path.isfile(f):
                return f, 'app'
        else:
            if name.startswith(('/usr/lib/', '/System/Library/')) and self.host_is_darwin:
                # macOS 11+: the shared cache holds these; the file may not exist on disk
                return name, 'system'
            if os.path.isfile(name):
                return name, 'system' if name.startswith(('/usr/lib/', '/System/Library/')) else 'absolute'
        for folder in self.fallback:
            f = _file_in(folder, base)
            if f:
                return f, 'system' if folder in ('/usr/lib', '/usr/local/lib') else 'env'
        if name.startswith(('/usr/lib/', '/System/Library/')) and not self.host_is_darwin:
            return None, 'system'
        return None, None


###################################################################################################
def describe(info):
    """One line: format, architecture, static or the dependencies with where they come from."""
    if not info or info.get('error'):
        return f"not a binary ({(info or {}).get('error') or 'no information'})"
    fmt = {'elf': 'ELF', 'pe': 'PE', 'macho': 'Mach-O'}.get(info.get('format'), str(info.get('format')))
    head = f"{fmt} {info.get('arch') or '?'}"
    if info.get('slices') and len(info['slices']) > 1:
        head += f" (fat: {', '.join(info['slices'])})"
    if info.get('static'):
        return head + ', static'
    parts = []
    deps = info.get('deps')
    if deps is not None:
        for d in deps:
            if d['path'] and not d['system']:
                where = os.path.dirname(d['path'])
            elif d['system'] or d['source'] in ('api', 'system'):
                where = 'system'
            elif d['path']:
                where = os.path.dirname(d['path'])
            else:
                where = 'missing'
            parts.append(f"{d['name'].rsplit('/', 1)[-1]} ({where})")
    else:
        parts = [n.rsplit('/', 1)[-1] for n in list(info.get('needed') or []) + list(info.get('delay_needed') or [])]
    return head + ', dynamic: ' + ', '.join(parts) if parts else head + ', dynamic'
