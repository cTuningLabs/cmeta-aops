"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

category/task/api/binary_deps.py: the dependencies of ELF, PE and Mach-O binaries read from their
headers, and their resolution under a given environment, in pure Python. Offline: the binaries are
built here from a few hundred bytes, plus the running interpreter and one real system library.
"""

import importlib.util
import os
import pathlib
import struct
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def bd():
    spec = importlib.util.spec_from_file_location("binary_deps_under_test", REPO_ROOT / "category" / "task" / "api" / "binary_deps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- generators -----------------------------------------------------------------------------------

def make_elf(bits = 64, endian = "<", machine = 0x3E, needed = (), rpath = None, runpath = None,
             interp = "/lib64/ld-linux-x86-64.so.2", static = False, e_type = 2):
    """An ELF with one PT_LOAD (vaddr == file offset), and unless static PT_INTERP + PT_DYNAMIC."""
    strings, offsets = bytearray(b"\0"), {}
    for s in list(needed) + [x for x in (rpath, runpath) if x]:
        offsets[s] = len(strings)
        strings += s.encode() + b"\0"
    ehsize, phentsize = (64, 56) if bits == 64 else (52, 32)
    n_ph = 1 if static else 3
    cur = ehsize + n_ph * phentsize
    interp_off, interp_bytes = cur, (b"" if static else interp.encode() + b"\0")
    cur = (cur + len(interp_bytes) + 7) & ~7
    strtab_off = cur
    cur = (cur + len(strings) + 7) & ~7
    dyn_off = cur
    dyn = bytearray()
    fmt = endian + ("qQ" if bits == 64 else "iI")
    if not static:
        for n in needed:
            dyn += struct.pack(fmt, 1, offsets[n])                 # DT_NEEDED
        if rpath:
            dyn += struct.pack(fmt, 15, offsets[rpath])            # DT_RPATH
        if runpath:
            dyn += struct.pack(fmt, 29, offsets[runpath])          # DT_RUNPATH
        dyn += struct.pack(fmt, 5, strtab_off) + struct.pack(fmt, 10, len(strings)) + struct.pack(fmt, 0, 0)
    total = dyn_off + len(dyn)

    def phdr(p_type, offset, filesz):
        if bits == 64:
            return struct.pack(endian + "IIQQQQQQ", p_type, 5, offset, offset, offset, filesz, filesz, 8)
        return struct.pack(endian + "IIIIIIII", p_type, offset, offset, offset, filesz, filesz, 5, 8)

    phdrs = phdr(1, 0, total)
    if not static:
        phdrs += phdr(3, interp_off, len(interp_bytes)) + phdr(2, dyn_off, len(dyn))
    ident = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1 if endian == "<" else 2, 1]) + b"\0" * 9
    if bits == 64:
        header = ident + struct.pack(endian + "HHIQQQIHHHHHH", e_type, machine, 1, 0, ehsize, 0, 0, ehsize, phentsize, n_ph, 0, 0, 0)
    else:
        header = ident + struct.pack(endian + "HHIIIIIHHHHHH", e_type, machine, 1, 0, ehsize, 0, 0, ehsize, phentsize, n_ph, 0, 0, 0)
    body = bytearray(header + phdrs)
    body += interp_bytes
    body += b"\0" * (strtab_off - len(body))
    body += strings
    body += b"\0" * (dyn_off - len(body))
    body += dyn
    return bytes(body)


def make_pe(bits = 64, imports = (), delay = (), machine = None, dll = False, delay_old_style = False):
    """A PE32+/PE32 with one .rdata section holding the import and delay-import tables."""
    machine = machine if machine is not None else (0x8664 if bits == 64 else 0x14C)
    e_lfanew, size_opt = 0x80, (240 if bits == 64 else 224)
    image_base = 0x140000000 if bits == 64 else 0x400000
    sec_rva, sec_raw, sec_size = 0x1000, 0x200, 0x400
    data = bytearray(sec_size)
    names = {}
    pos = 0x100
    for n in list(imports) + list(delay):
        names[n] = sec_rva + pos
        data[pos:pos + len(n) + 1] = n.encode() + b"\0"
        pos += len(n) + 1
    p = 0
    for n in imports:
        data[p:p + 20] = struct.pack("<IIIII", sec_rva + 0x300, 0, 0, names[n], sec_rva + 0x300)
        p += 20
    p = 0x200
    for n in delay:
        name_field = names[n] if not delay_old_style else image_base + names[n]
        data[p:p + 32] = struct.pack("<IIIIIIII", 0 if delay_old_style else 1, name_field, 0, 0, 0, 0, 0, 0)
        p += 32
    dos = (b"MZ" + b"\0" * 58 + struct.pack("<I", e_lfanew)).ljust(e_lfanew, b"\0")
    characteristics = 0x2102 if dll else 0x0102      # EXECUTABLE_IMAGE | 32BIT_MACHINE (| DLL)
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, size_opt, characteristics)
    opt = bytearray(size_opt)
    opt[0:2] = struct.pack("<H", 0x20B if bits == 64 else 0x10B)
    if bits == 64:
        opt[24:32] = struct.pack("<Q", image_base)
        ndirs_off, dirs_off = 108, 112
    else:
        opt[28:32] = struct.pack("<I", image_base)
        ndirs_off, dirs_off = 92, 96
    opt[ndirs_off:ndirs_off + 4] = struct.pack("<I", 16)
    if imports:
        opt[dirs_off + 8:dirs_off + 16] = struct.pack("<II", sec_rva, 20 * (len(imports) + 1))
    if delay:
        opt[dirs_off + 13 * 8:dirs_off + 13 * 8 + 8] = struct.pack("<II", sec_rva + 0x200, 32 * (len(delay) + 1))
    section = b".rdata\0\0" + struct.pack("<IIIIIIHHI", sec_size, sec_rva, sec_size, sec_raw, 0, 0, 0, 0, 0x40000040)
    headers = (dos + b"PE\0\0" + coff + bytes(opt) + section).ljust(sec_raw, b"\0")
    return headers + bytes(data)


LC_LOAD_DYLIB, LC_RPATH, LC_ID_DYLIB = 0xC, 0x8000001C, 0xD
CPU_ARM64, CPU_X86_64 = 0x0100000C, 0x01000007


def make_macho(needed = (), rpaths = (), cputype = CPU_ARM64, filetype = 2, soname = None):
    cmds = b""
    ncmds = 0
    for n in needed:
        name = n.encode() + b"\0"
        size = (24 + len(name) + 7) & ~7
        cmds += struct.pack("<IIIIII", LC_LOAD_DYLIB, size, 24, 0, 0, 0) + name.ljust(size - 24, b"\0")
        ncmds += 1
    if soname:
        name = soname.encode() + b"\0"
        size = (24 + len(name) + 7) & ~7
        cmds += struct.pack("<IIIIII", LC_ID_DYLIB, size, 24, 0, 0, 0) + name.ljust(size - 24, b"\0")
        ncmds += 1
    for rp in rpaths:
        p = rp.encode() + b"\0"
        size = (12 + len(p) + 7) & ~7
        cmds += struct.pack("<III", LC_RPATH, size, 12) + p.ljust(size - 12, b"\0")
        ncmds += 1
    header = struct.pack("<IIIIIIII", 0xFEEDFACF, cputype, 0, filetype, ncmds, len(cmds), 0, 0)
    return header + cmds


def make_fat(slices):
    """A fat Mach-O: slices = [(cputype, bytes)], 4 KiB aligned."""
    header = struct.pack(">II", 0xCAFEBABE, len(slices))
    archs, blobs, offset = b"", b"", 4096
    for cputype, blob in slices:
        archs += struct.pack(">IIIII", cputype, 0, offset, len(blob), 12)
        padded = blob.ljust((len(blob) + 4095) & ~4095, b"\0")
        blobs += padded
        offset += len(padded)
    return (header + archs).ljust(4096, b"\0") + blobs


def make_ld_cache(entries, old = False):
    """glibc's ld.so.cache: the new 'glibc-ld.so.cache1.1' layout, or the old one followed by the new one."""
    strings, offs = bytearray(), {}
    for k, v in entries:
        for s in (k, v):
            if s not in offs:
                offs[s] = len(strings)
                strings += s.encode() + b"\0"
    header = b"glibc-ld.so.cache1.1" + struct.pack("<II", len(entries), len(strings)) + b"\0" * 4 + struct.pack("<I", 0) + b"\0" * 12
    assert len(header) == 48
    table = b"".join(struct.pack("<iIIIQ", 1, 48 + 24 * len(entries) + offs[k], 48 + 24 * len(entries) + offs[v], 0, 0)
                     for k, v in entries)
    new = header + table + bytes(strings)
    if not old:
        return new
    old_strings, old_offs = bytearray(), {}
    for k, v in entries:
        for s in (k, v):
            if s not in old_offs:
                old_offs[s] = len(old_strings)
                old_strings += s.encode() + b"\0"
    old_part = b"ld.so-1.7.0\0" + struct.pack("<I", len(entries)) + \
               b"".join(struct.pack("<iII", 1, old_offs[k], old_offs[v]) for k, v in entries) + bytes(old_strings)
    old_part = old_part.ljust((len(old_part) + 7) & ~7, b"\0")
    return old_part + new


def write(path, data):
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(data)
    return str(path)


# --- ELF ------------------------------------------------------------------------------------------

def test_elf64_dynamic(bd, tmp_path):
    p = write(tmp_path / "app", make_elf(needed = ["libfoo.so.1", "libbar.so"], runpath = "$ORIGIN/../lib:/opt/x/lib"))
    i = bd.inspect(p)
    assert i["error"] is None and i["format"] == "elf" and i["arch"] == "x86_64" and i["bits"] == 64
    assert i["kind"] == "executable" and i["interpreter"] == "/lib64/ld-linux-x86-64.so.2"
    assert i["needed"] == ["libfoo.so.1", "libbar.so"] and i["runpath"] == ["$ORIGIN/../lib", "/opt/x/lib"]
    assert i["rpath"] == [] and i["static"] is False


def test_elf32_big_endian_with_rpath(bd, tmp_path):
    p = write(tmp_path / "app32", make_elf(bits = 32, endian = ">", machine = 0x14, needed = ["libc.so.6"],
                                           rpath = "/usr/local/lib", interp = "/lib/ld.so.1", e_type = 3))
    i = bd.inspect(p)
    assert i["format"] == "elf" and i["arch"] == "ppc" and i["bits"] == 32 and i["kind"] == "shared"
    assert i["needed"] == ["libc.so.6"] and i["rpath"] == ["/usr/local/lib"] and i["runpath"] == []


def test_static_elf(bd, tmp_path):
    p = write(tmp_path / "static", make_elf(static = True, machine = 0xB7))
    i = bd.inspect(p)
    assert i["format"] == "elf" and i["arch"] == "aarch64" and i["static"] is True
    assert i["interpreter"] is None and i["needed"] == []
    r = bd.resolve(p, env = {}, uname = "linux", system_dirs = [])
    assert r["deps"] == [] and r["missing"] == [] and bd.describe(r) == "ELF aarch64, static"


def test_elf_resolution_rpath_env_runpath_system(bd, tmp_path):
    app = write(tmp_path / "bin" / "app", make_elf(needed = ["libfoo.so.1", "libbar.so", "libc.so.6", "libgone.so"],
                                                    runpath = "$ORIGIN/../lib"))
    write(tmp_path / "lib" / "libfoo.so.1", b"x")
    write(tmp_path / "envlib" / "libbar.so", b"x")
    write(tmp_path / "sys" / "libc.so.6", b"x")
    r = bd.resolve(app, env = {"LD_LIBRARY_PATH": str(tmp_path / "envlib")}, uname = "linux", system_dirs = [str(tmp_path / "sys")])
    by = {d["name"]: d for d in r["deps"]}
    assert by["libfoo.so.1"]["source"] == "runpath" and by["libfoo.so.1"]["path"] == str(tmp_path / "lib" / "libfoo.so.1")
    assert by["libbar.so"]["source"] == "env" and not by["libbar.so"]["system"]
    assert by["libc.so.6"]["source"] == "system" and by["libc.so.6"]["system"] is True
    assert by["libgone.so"]["path"] is None and r["missing"] == ["libgone.so"]
    text = bd.describe(r)
    assert text.startswith("ELF x86_64, dynamic: ") and "libc.so.6 (system)" in text and "libgone.so (missing)" in text


def test_elf_rpath_is_ignored_when_runpath_exists(bd, tmp_path):
    write(tmp_path / "rp" / "libfoo.so.1", b"x")
    write(tmp_path / "run" / "libfoo.so.1", b"x")
    # ELF rpaths are ":"-separated lists, so the test keeps them relative to $ORIGIN (a drive letter would split)
    both = write(tmp_path / "both", make_elf(needed = ["libfoo.so.1"], rpath = "$ORIGIN/rp", runpath = "$ORIGIN/run"))
    only = write(tmp_path / "only", make_elf(needed = ["libfoo.so.1"], rpath = "$ORIGIN/rp"))
    r = bd.resolve(both, env = {}, uname = "linux", system_dirs = [])
    assert r["deps"][0]["source"] == "runpath" and r["deps"][0]["path"].startswith(str(tmp_path / "run"))
    r = bd.resolve(only, env = {}, uname = "linux", system_dirs = [])
    assert r["deps"][0]["source"] == "rpath"
    # LD_LIBRARY_PATH beats RUNPATH but not RPATH
    write(tmp_path / "env" / "libfoo.so.1", b"x")
    r = bd.resolve(both, env = {"LD_LIBRARY_PATH": str(tmp_path / "env")}, uname = "linux", system_dirs = [])
    assert r["deps"][0]["source"] == "env"
    r = bd.resolve(only, env = {"LD_LIBRARY_PATH": str(tmp_path / "env")}, uname = "linux", system_dirs = [])
    assert r["deps"][0]["source"] == "rpath"


@pytest.mark.parametrize("old", [False, True])
def test_elf_ld_so_cache(bd, tmp_path, old):
    lib = write(tmp_path / "cached" / "libbar.so", b"x")
    cache = write(tmp_path / "ld.so.cache", make_ld_cache([("libbar.so", lib), ("libzzz.so.9", "/nowhere/libzzz.so.9")], old = old))
    assert bd._read_ld_so_cache(cache) == {"libbar.so": lib, "libzzz.so.9": "/nowhere/libzzz.so.9"}
    app = write(tmp_path / "app", make_elf(needed = ["libbar.so", "libzzz.so.9"]))
    r = bd.resolve(app, env = {}, uname = "linux", system_dirs = [], ld_cache = cache)
    by = {d["name"]: d for d in r["deps"]}
    assert by["libbar.so"]["source"] == "system" and by["libbar.so"]["path"] == lib
    assert by["libzzz.so.9"]["path"] is None and r["missing"] == ["libzzz.so.9"]      # the cache names a file that is gone


# --- PE -------------------------------------------------------------------------------------------

def test_pe64_imports_and_delay_imports(bd, tmp_path):
    p = write(tmp_path / "app.exe", make_pe(imports = ["KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "libfoo.dll"],
                                            delay = ["delayed.dll"]))
    i = bd.inspect(p)
    assert i["error"] is None and i["format"] == "pe" and i["arch"] == "x86_64" and i["bits"] == 64 and i["kind"] == "executable"
    assert i["needed"] == ["KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "libfoo.dll"]
    assert i["delay_needed"] == ["delayed.dll"] and i["static"] is False


def test_pe32_system_only_is_static_and_old_delay_tables(bd, tmp_path):
    p = write(tmp_path / "small.exe", make_pe(bits = 32, imports = ["KERNEL32.dll", "USER32.dll"], delay = ["ADVAPI32.dll"],
                                              delay_old_style = True))
    i = bd.inspect(p)
    assert i["format"] == "pe" and i["arch"] == "i386" and i["bits"] == 32
    assert i["needed"] == ["KERNEL32.dll", "USER32.dll"] and i["delay_needed"] == ["ADVAPI32.dll"] and i["static"] is True
    d = write(tmp_path / "lib.dll", make_pe(imports = ["KERNEL32.dll"], dll = True))
    assert bd.inspect(d)["kind"] == "shared"


def test_pe_resolution_order(bd, tmp_path):
    app = write(tmp_path / "app" / "app.exe", make_pe(imports = ["KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "libfoo.dll", "gone.dll"],
                                                      delay = ["delayed.dll"]))
    write(tmp_path / "winroot" / "System32" / "KERNEL32.dll", b"x")
    write(tmp_path / "app" / "LibFoo.dll", b"x")                      # the import says libfoo.dll: names are case-insensitive
    write(tmp_path / "onpath" / "delayed.dll", b"x")
    env = {"SystemRoot": str(tmp_path / "winroot"), "PATH": str(tmp_path / "onpath")}
    r = bd.resolve(app, env = env, uname = "windows")
    by = {d["name"]: d for d in r["deps"]}
    assert by["KERNEL32.dll"]["source"] == "system" and by["KERNEL32.dll"]["system"] is True
    assert by["api-ms-win-crt-runtime-l1-1-0.dll"]["source"] == "api" and by["api-ms-win-crt-runtime-l1-1-0.dll"]["system"] is True
    assert by["libfoo.dll"]["source"] == "app" and by["libfoo.dll"]["path"].lower().endswith("libfoo.dll")
    assert by["delayed.dll"]["source"] == "env"
    assert by["gone.dll"]["path"] is None and r["missing"] == ["gone.dll"]
    assert "gone.dll (missing)" in bd.describe(r) and "KERNEL32.dll (system)" in bd.describe(r)
    # the current folder is searched after the system folders
    write(tmp_path / "cwd" / "gone.dll", b"x")
    r = bd.resolve(app, env = env, cwd = str(tmp_path / "cwd"), uname = "windows")
    assert {d["name"]: d for d in r["deps"]}["gone.dll"]["source"] == "cwd"


# --- Mach-O ---------------------------------------------------------------------------------------

def test_macho64_and_fat(bd, tmp_path):
    thin = make_macho(needed = ["/usr/lib/libSystem.B.dylib", "@rpath/libfoo.dylib"], rpaths = ["@loader_path/../lib"])
    p = write(tmp_path / "app", thin)
    i = bd.inspect(p)
    assert i["error"] is None and i["format"] == "macho" and i["arch"] == "aarch64" and i["bits"] == 64 and i["kind"] == "executable"
    assert i["needed"] == ["/usr/lib/libSystem.B.dylib", "@rpath/libfoo.dylib"] and i["rpath"] == ["@loader_path/../lib"]
    assert i["static"] is False
    fat = write(tmp_path / "fat", make_fat([(CPU_X86_64, make_macho(needed = ["/usr/lib/libSystem.B.dylib"], cputype = CPU_X86_64)),
                                            (CPU_ARM64, thin)]))
    f = bd.inspect(fat)
    assert f["format"] == "macho" and f["slices"] == ["x86_64", "aarch64"] and f["arch"] in ("x86_64", "aarch64")
    assert "fat: x86_64, aarch64" in bd.describe(f)
    lib = write(tmp_path / "libbar.dylib", make_macho(needed = ["/usr/lib/libSystem.B.dylib"], filetype = 6, soname = "@rpath/libbar.dylib"))
    j = bd.inspect(lib)
    assert j["kind"] == "shared" and j["static"] is True and j["soname"] == "@rpath/libbar.dylib"


def test_macho_resolution(bd, tmp_path):
    app = write(tmp_path / "bin" / "app", make_macho(needed = ["/usr/lib/libSystem.B.dylib", "@rpath/libfoo.dylib", "@rpath/libgone.dylib",
                                                               "@loader_path/libnear.dylib"],
                                                     rpaths = ["@loader_path/../lib"]))
    write(tmp_path / "lib" / "libfoo.dylib", b"x")
    write(tmp_path / "bin" / "libnear.dylib", b"x")
    r = bd.resolve(app, env = {}, uname = "darwin", system_dirs = [])
    by = {d["name"]: d for d in r["deps"]}
    assert by["/usr/lib/libSystem.B.dylib"]["source"] == "system" and by["/usr/lib/libSystem.B.dylib"]["system"] is True
    assert by["@rpath/libfoo.dylib"]["source"] == "rpath" and by["@rpath/libfoo.dylib"]["path"] == str(tmp_path / "lib" / "libfoo.dylib")
    assert by["@loader_path/libnear.dylib"]["source"] == "app"
    assert by["@rpath/libgone.dylib"]["path"] is None and r["missing"] == ["@rpath/libgone.dylib"]
    # DYLD_LIBRARY_PATH wins over @rpath; a system library stays system when read on another OS
    write(tmp_path / "env" / "libfoo.dylib", b"x")
    r = bd.resolve(app, env = {"DYLD_LIBRARY_PATH": str(tmp_path / "env")}, uname = "linux", system_dirs = [])
    by = {d["name"]: d for d in r["deps"]}
    assert by["@rpath/libfoo.dylib"]["source"] == "env"
    assert by["/usr/lib/libSystem.B.dylib"]["system"] is True and "/usr/lib/libSystem.B.dylib" not in r["missing"]


# --- tables, describe, errors ---------------------------------------------------------------------

def test_is_system_library(bd):
    assert bd.is_system_library("libc.so.6", "linux") and bd.is_system_library("/lib64/ld-linux-x86-64.so.2", "linux")
    assert bd.is_system_library("libpthread.so.0", "linux") and bd.is_system_library("libm.so.6", "linux")
    for lib in ("libstdc++.so.6", "libgcc_s.so.1", "libcrypt.so.1", "libgomp.so.1", "libcrypto.so.3", "libcudart.so.12"):
        assert not bd.is_system_library(lib, "linux"), lib
    for lib in ("KERNEL32.dll", "kernel32.dll", "api-ms-win-core-heap-l1-1-0.dll", "VCRUNTIME140.dll", "MSVCP140.dll",
                "ucrtbase.dll", "ntdll.dll", r"C:\Windows\System32\ADVAPI32.dll"):
        assert bd.is_system_library(lib, "windows"), lib
    for lib in ("libomp.dll", "VCOMP140.DLL", "cudnn64_9.dll", "libcrypto-3-x64.dll", "python314.dll"):
        assert not bd.is_system_library(lib, "windows"), lib
    for lib in ("/usr/lib/libSystem.B.dylib", "/usr/lib/libc++.1.dylib", "/usr/lib/libobjc.A.dylib",
                "/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation", "libSystem.B.dylib"):
        assert bd.is_system_library(lib, "darwin"), lib
    for lib in ("/opt/homebrew/opt/libomp/lib/libomp.dylib", "@rpath/libtorch.dylib", "/usr/local/lib/libz.dylib"):
        assert not bd.is_system_library(lib, "darwin"), lib


def test_not_a_binary(bd, tmp_path):
    text = write(tmp_path / "notes.txt", b"just text, long enough to not be a header\n" * 4)
    i = bd.inspect(text)
    assert i["format"] is None and i["error"] and i["needed"] == []
    assert bd.describe(i).startswith("not a binary")
    r = bd.resolve(text)
    assert r["deps"] == [] and r["missing"] == []
    missing = bd.inspect(str(tmp_path / "absent"))
    assert missing["format"] is None and missing["error"]
    truncated = write(tmp_path / "trunc", make_elf(needed = ["libfoo.so.1"])[:70])
    t = bd.inspect(truncated)
    assert t["format"] == "elf" and t["error"]                     # a header cut short is reported, not raised


# --- real files -----------------------------------------------------------------------------------

def test_the_running_interpreter(bd):
    exe = os.path.realpath(sys.executable)
    r = bd.resolve(exe)
    assert r["error"] is None and r["format"] in ("elf", "pe", "macho") and r["arch"] and r["bits"] in (32, 64)
    names = [d["name"] for d in r["deps"]]
    if r["format"] == "pe":
        assert any(n.lower().startswith(("kernel32", "api-ms-win")) for n in names)
    elif r["format"] == "elf":
        assert r["interpreter"] and names                            # a dynamic interpreter needs at least libc
        assert all(d["path"] for d in r["deps"] if d["system"]), r["deps"]
    else:
        assert any(n.startswith("/usr/lib/libSystem") for n in names)
    assert bd.describe(r)


def test_a_real_system_library(bd):
    if os.name == "nt":
        path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "kernel32.dll")
        i = bd.inspect(path)
        assert i["format"] == "pe" and i["kind"] == "shared" and any(n.lower() == "ntdll.dll" for n in i["needed"])
    elif sys.platform == "darwin":
        r = bd.resolve(os.path.realpath(sys.executable))
        system = [d for d in r["deps"] if d["name"].startswith("/usr/lib/libSystem")]
        assert system and system[0]["source"] == "system"
    else:
        r = bd.resolve(os.path.realpath(sys.executable))
        libc = [d for d in r["deps"] if d["name"].startswith("libc.so")]
        if not libc:
            pytest.skip("the interpreter does not need libc directly")
        assert libc[0]["path"] and os.path.isfile(libc[0]["path"]) and libc[0]["source"] == "system"
        i = bd.inspect(libc[0]["path"])
        assert i["format"] == "elf" and i["kind"] == "shared"
