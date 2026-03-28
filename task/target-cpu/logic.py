from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import struct
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# Generic helpers
# ============================================================

def _run(cmd: List[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None


def _parse_int_list(spec: str) -> List[int]:
    out: List[int] = []
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def _count_bits(x: int) -> int:
    return int(x).bit_count()


def _cpu_dirs() -> List[Path]:
    root = Path("/sys/devices/system/cpu")
    return sorted(
        [p for p in root.glob("cpu[0-9]*") if re.fullmatch(r"cpu\d+", p.name)],
        key=lambda p: int(p.name[3:]),
    )


def _sysctl_str(name: str) -> Optional[str]:
    try:
        return _run(["sysctl", "-n", name]).strip()
    except Exception:
        return None


def _sysctl_int(name: str) -> Optional[int]:
    s = _sysctl_str(name)
    return _to_int(s)


def _sysctl_boolish(name: str) -> Optional[bool]:
    s = _sysctl_str(name)
    if s is None:
        return None
    s = s.strip().lower()
    if s in {"1", "true", "yes"}:
        return True
    if s in {"0", "false", "no"}:
        return False
    return None


# ============================================================
# Unified architecture schema
# ============================================================

def _python_arch_raw() -> str:
    return (
        platform.machine()
        or platform.uname().machine
        or platform.uname().processor
        or ""
    ).strip()


def _default_interpreter_bits() -> int:
    return struct.calcsize("P") * 8


def _normalize_arch_name(raw: str) -> Dict[str, Any]:
    r = (raw or "").strip().lower().replace("-", "_")

    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "em64t": "x86_64",

        "i386": "x86_32",
        "i486": "x86_32",
        "i586": "x86_32",
        "i686": "x86_32",
        "x86": "x86_32",

        "arm64": "arm64",
        "aarch64": "arm64",
        "arm64e": "arm64",

        "arm": "arm32",
        "armv6l": "arm32",
        "armv7l": "arm32",
        "armv8l": "arm32",

        "riscv64": "riscv64",
        "riscv32": "riscv32",

        "ppc64": "ppc64",
        "ppc64le": "ppc64",
        "powerpc64": "ppc64",
        "powerpc64le": "ppc64",

        "ppc": "ppc32",
        "powerpc": "ppc32",

        "ia64": "ia64",
        "itanium": "ia64",

        "mips": "mips",
        "mips64": "mips64",
    }

    normalized = aliases.get(r, "unknown")

    family = "unknown"
    bits: Optional[int] = None

    if normalized == "x86_64":
        family, bits = "x86", 64
    elif normalized == "x86_32":
        family, bits = "x86", 32
    elif normalized == "arm64":
        family, bits = "arm", 64
    elif normalized == "arm32":
        family, bits = "arm", 32
    elif normalized == "riscv64":
        family, bits = "riscv", 64
    elif normalized == "riscv32":
        family, bits = "riscv", 32
    elif normalized == "ppc64":
        family, bits = "ppc", 64
    elif normalized == "ppc32":
        family, bits = "ppc", 32
    elif normalized == "ia64":
        family, bits = "ia64", 64
    elif normalized == "mips64":
        family, bits = "mips", 64
    elif normalized == "mips":
        family, bits = "mips", None

    return {
        "arch_raw": raw,
        "arch_normalized": normalized,
        "arch_family": family,
        "arch_bits": bits,
        "interpreter_bits": _default_interpreter_bits(),
    }


def _empty_normalized_features() -> Dict[str, bool]:
    return {
        "sse": False,
        "sse2": False,
        "ssse3": False,
        "sse4_1": False,
        "sse4_2": False,
        "avx": False,
        "avx2": False,
        "avx512f": False,
        "neon": False,
        "asimd": False,
        "sve": False,
        "sve2": False,
        "aes": False,
        "sha1": False,
        "sha2": False,
        "crc32": False,
        "vmx_or_svm": False,
        "arm_v8": False,
    }


# ============================================================
# Linux
# ============================================================

def _linux_usable_cpu_count() -> Optional[int]:
    if hasattr(os, "sched_getaffinity"):
        try:
            return len(os.sched_getaffinity(0))
        except Exception:
            pass

    status = Path("/proc/self/status")
    if status.exists():
        try:
            for line in status.read_text().splitlines():
                if line.startswith("Cpus_allowed_list:"):
                    spec = line.split(":", 1)[1].strip()
                    return len(_parse_int_list(spec))
        except Exception:
            pass
    return None


def _linux_sysfs_topology() -> Dict[str, Any]:
    cpus = []
    packages: Dict[str, set] = {}
    cores: Dict[tuple, set] = {}
    capacities: Dict[str, List[int]] = {}

    for cpu_dir in _cpu_dirs():
        cpu_id = int(cpu_dir.name[3:])
        topo = cpu_dir / "topology"

        def read_text(p: Path) -> Optional[str]:
            try:
                return p.read_text().strip()
            except Exception:
                return None

        physical_package_id = read_text(topo / "physical_package_id")
        core_id = read_text(topo / "core_id")
        thread_siblings = read_text(topo / "thread_siblings_list")
        core_siblings = read_text(topo / "core_siblings_list")

        cpu_entry = {
            "cpu": cpu_id,
            "physical_package_id": _to_int(physical_package_id),
            "core_id": _to_int(core_id),
            "thread_siblings": _parse_int_list(thread_siblings or ""),
            "core_siblings": _parse_int_list(core_siblings or ""),
        }
        cpus.append(cpu_entry)

        if physical_package_id is not None:
            packages.setdefault(physical_package_id, set()).add(cpu_id)

        if physical_package_id is not None and core_id is not None:
            cores.setdefault((physical_package_id, core_id), set()).add(cpu_id)

        cap_file = cpu_dir / "cpu_capacity"
        if cap_file.exists():
            try:
                cap = cap_file.read_text().strip()
                capacities.setdefault(cap, []).append(cpu_id)
            except Exception:
                pass

    return {
        "cpus": cpus,
        "package_count_sysfs": len(packages) or None,
        "physical_core_count_sysfs": len(cores) or None,
        "packages_sysfs": {
            str(k): sorted(v) for k, v in sorted(packages.items(), key=lambda x: int(x[0]))
        },
        "core_classes": {
            "kind": "cpu_capacity",
            "groups": {
                str(k): sorted(v) for k, v in sorted(capacities.items(), key=lambda x: int(x[0]))
            },
        } if capacities else {"kind": "cpu_capacity", "groups": {}},
    }


def _linux_lscpu() -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    try:
        raw = _run(["lscpu", "-J"])
        data = json.loads(raw)
        flat: Dict[str, Any] = {}
        for row in data.get("lscpu", []):
            field = row.get("field", "").rstrip(":")
            flat[field] = row.get("data")
        out["lscpu_summary"] = flat
        out["socket_count"] = _to_int(flat.get("Socket(s)"))
        out["cores_per_socket"] = _to_int(flat.get("Core(s) per socket"))
        out["threads_per_core"] = _to_int(flat.get("Thread(s) per core"))
        out["logical_cpu_count_lscpu"] = _to_int(flat.get("CPU(s)"))
        out["arch_raw_lscpu"] = flat.get("Architecture")
    except Exception as e:
        out["lscpu_error"] = str(e)

    try:
        raw = _run(["lscpu", "-p=cpu,core,socket,node,online"])
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cpu, core, socket, node, online = [x.strip() for x in line.split(",")]
            rows.append({
                "cpu": int(cpu),
                "core": int(core),
                "socket": int(socket),
                "node": int(node) if node != "" else None,
                "online": online.lower() == "y" if online else None,
            })
        out["lscpu_rows"] = rows
    except Exception as e:
        out["lscpu_rows_error"] = str(e)

    return out


def _linux_features() -> Dict[str, Any]:
    raw = set()

    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text().splitlines():
                if ":" not in line:
                    continue
                k, v = [x.strip() for x in line.split(":", 1)]
                lk = k.lower()
                if lk in ("flags", "features"):
                    raw.update(v.split())
        except Exception:
            pass

    norm = _empty_normalized_features()
    norm.update({
        "sse": "sse" in raw,
        "sse2": "sse2" in raw,
        "ssse3": "ssse3" in raw,
        "sse4_1": "sse4_1" in raw or "sse4.1" in raw,
        "sse4_2": "sse4_2" in raw or "sse4.2" in raw,
        "avx": "avx" in raw,
        "avx2": "avx2" in raw,
        "avx512f": "avx512f" in raw,
        "neon": "neon" in raw,
        "asimd": "asimd" in raw,
        "sve": "sve" in raw,
        "sve2": "sve2" in raw,
        "aes": "aes" in raw,
        "sha1": "sha1" in raw,
        "sha2": "sha2" in raw or "sha256" in raw,
        "crc32": "crc32" in raw,
        "vmx_or_svm": "vmx" in raw or "svm" in raw,
    })

    if norm["asimd"]:
        norm["neon"] = True
    if norm["neon"]:
        norm["asimd"] = True

    return {
        "features_raw": sorted(raw),
        "features_normalized": norm,
    }


def _linux_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": "linux",
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": _linux_usable_cpu_count(),
    }
    info.update(_linux_lscpu())
    info.update(_linux_sysfs_topology())
    info.update(_linux_features())

    if info.get("socket_count") is None:
        info["socket_count"] = info.get("package_count_sysfs")

    if info.get("physical_core_count") is None:
        info["physical_core_count"] = info.get("physical_core_count_sysfs")

    if info.get("physical_core_count") is None:
        s = info.get("socket_count")
        c = info.get("cores_per_socket")
        if s is not None and c is not None:
            info["physical_core_count"] = s * c

    raw_arch = info.get("arch_raw_lscpu") or _python_arch_raw()
    info.update(_normalize_arch_name(raw_arch))

    return info


# ============================================================
# macOS
# ============================================================

def _macos_features() -> Dict[str, Any]:
    raw = set()
    norm = _empty_normalized_features()

    # Intel-style feature strings
    for key in ("machdep.cpu.features", "machdep.cpu.leaf7_features"):
        s = _sysctl_str(key)
        if s:
            feats = {x.lower() for x in s.split()}
            raw.update(feats)

    # Apple-silicon-ish / sysctl probes
    probes = {
        "neon": ["hw.optional.neon", "hw.optional.AdvSIMD"],
        "asimd": ["hw.optional.arm.FEAT_AdvSIMD", "hw.optional.AdvSIMD"],
        "aes": ["hw.optional.aes", "hw.optional.arm.FEAT_AES"],
        "sha1": ["hw.optional.arm.FEAT_SHA1"],
        "sha2": ["hw.optional.arm.FEAT_SHA256", "hw.optional.arm.FEAT_SHA2"],
        "crc32": ["hw.optional.armv8_crc32", "hw.optional.arm.FEAT_CRC32"],
        "sve": ["hw.optional.arm.FEAT_SVE"],
        "sve2": ["hw.optional.arm.FEAT_SVE2"],
        "arm_v8": ["hw.optional.armv8_1_atomics", "hw.optional.armv8_crc32"],
    }

    for feat_name, keys in probes.items():
        for key in keys:
            val = _sysctl_boolish(key)
            if val:
                norm[feat_name] = True
                raw.add(key.lower())
                break

    intel_aliases = {
        "sse": ["sse"],
        "sse2": ["sse2"],
        "ssse3": ["ssse3"],
        "sse4_1": ["sse4.1", "sse4_1"],
        "sse4_2": ["sse4.2", "sse4_2"],
        "avx": ["avx1.0", "avx"],
        "avx2": ["avx2"],
        "avx512f": ["avx512f"],
        "aes": ["aes"],
    }

    for dst, names in intel_aliases.items():
        if any(name in raw for name in names):
            norm[dst] = True

    if norm["asimd"]:
        norm["neon"] = True
    if norm["neon"]:
        norm["asimd"] = True

    return {
        "features_raw": sorted(raw),
        "features_normalized": norm,
    }


def _macos_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": "macos",
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": os.cpu_count(),
        "physical_core_count": _sysctl_int("hw.physicalcpu"),
        "logical_cpu_count_sysctl": _sysctl_int("hw.logicalcpu"),
        "nperflevels": _sysctl_int("hw.nperflevels"),
        "performance_levels": [],
    }

    nperf = info["nperflevels"]
    if nperf:
        levels = []
        groups = {}
        for i in range(nperf):
            phys = _sysctl_int(f"hw.perflevel{i}.physicalcpu")
            logi = _sysctl_int(f"hw.perflevel{i}.logicalcpu")
            row = {
                "perflevel": i,
                "physicalcpu": phys,
                "logicalcpu": logi,
            }
            levels.append(row)
            groups[f"perflevel{i}"] = row

        info["performance_levels"] = levels
        info["core_classes"] = {
            "kind": "perflevel",
            "groups": groups,
        }
    else:
        info["core_classes"] = {
            "kind": "perflevel",
            "groups": {},
        }

    info.update(_macos_features())
    info.update(_normalize_arch_name(_python_arch_raw()))
    return info


# ============================================================
# Windows
# ============================================================

RelationProcessorCore = 0
RelationProcessorPackage = 3

ERROR_INSUFFICIENT_BUFFER = 122
LTP_PC_SMT = 0x1


class GROUP_AFFINITY(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_size_t),
        ("Group", wintypes.WORD),
        ("Reserved", wintypes.WORD * 3),
    ]


class PROCESSOR_RELATIONSHIP_HEADER(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.BYTE),
        ("EfficiencyClass", wintypes.BYTE),
        ("Reserved", wintypes.BYTE * 20),
        ("GroupCount", wintypes.WORD),
    ]


class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_HEADER(ctypes.Structure):
    _fields_ = [
        ("Relationship", wintypes.DWORD),
        ("Size", wintypes.DWORD),
    ]


def _windows_wmi_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "packages": [],
    }

    ps = r"""
$items = Get-CimInstance Win32_Processor |
  Select-Object DeviceID, Name, Architecture, NumberOfCores, NumberOfLogicalProcessors
$items | ConvertTo-Json -Depth 3
""".strip()

    try:
        raw = _run(["powershell", "-NoProfile", "-Command", ps])
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        info["packages"] = data
        info["package_count"] = len(data)
        info["physical_core_count"] = sum(
            int(x.get("NumberOfCores") or 0) for x in data
        )
        info["logical_cpu_count_wmi"] = sum(
            int(x.get("NumberOfLogicalProcessors") or 0) for x in data
        )
    except Exception as e:
        info["wmi_error"] = str(e)

    return info


def _windows_architecture_from_wmi(packages: List[Dict[str, Any]]) -> str:
    mapping = {
        0: "x86",
        1: "mips",
        2: "alpha",
        3: "powerpc",
        5: "arm",
        6: "ia64",
        9: "x64",
        12: "arm64",
    }
    for pkg in packages:
        val = pkg.get("Architecture")
        if val is not None:
            try:
                return mapping.get(int(val), str(val))
            except Exception:
                return str(val)
    return _python_arch_raw()


def _windows_getlogicalprocessorinfoex() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "core_rows": [],
        "package_rows": [],
        "efficiency_class_groups": {},
    }

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    func = kernel32.GetLogicalProcessorInformationEx
    func.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    func.restype = wintypes.BOOL

    needed = wintypes.DWORD(0)
    ok = func(RelationProcessorCore, None, ctypes.byref(needed))
    err = ctypes.get_last_error()
    if not ok and err != ERROR_INSUFFICIENT_BUFFER:
        raise ctypes.WinError(err)

    buf = ctypes.create_string_buffer(needed.value)
    ok = func(RelationProcessorCore, ctypes.byref(buf), ctypes.byref(needed))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

    offset = 0
    core_rows = []
    while offset < needed.value:
        hdr = SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_HEADER.from_buffer(buf, offset)
        if hdr.Relationship != RelationProcessorCore:
            offset += hdr.Size
            continue

        base = offset + ctypes.sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_HEADER)
        prh = PROCESSOR_RELATIONSHIP_HEADER.from_buffer(buf, base)
        ga_offset = base + ctypes.sizeof(PROCESSOR_RELATIONSHIP_HEADER)
        ga = GROUP_AFFINITY.from_buffer(buf, ga_offset)

        logical_count = _count_bits(int(ga.Mask))
        row = {
            "efficiency_class": int(prh.EfficiencyClass),
            "smt": bool(prh.Flags & LTP_PC_SMT),
            "group": int(ga.Group),
            "mask": int(ga.Mask),
            "logical_cpu_count": logical_count,
        }
        core_rows.append(row)
        offset += hdr.Size

    info["core_rows"] = core_rows
    info["physical_core_count_api"] = len(core_rows)
    info["logical_cpu_count_api"] = sum(r["logical_cpu_count"] for r in core_rows)

    groups: Dict[str, Dict[str, Any]] = {}
    for row in core_rows:
        key = str(row["efficiency_class"])
        g = groups.setdefault(key, {
            "efficiency_class": row["efficiency_class"],
            "physical_core_count": 0,
            "logical_cpu_count": 0,
            "smt_core_count": 0,
        })
        g["physical_core_count"] += 1
        g["logical_cpu_count"] += row["logical_cpu_count"]
        if row["smt"]:
            g["smt_core_count"] += 1

    info["efficiency_class_groups"] = groups
    info["core_classes"] = {
        "kind": "efficiency_class",
        "groups": groups,
    }

    needed = wintypes.DWORD(0)
    ok = func(RelationProcessorPackage, None, ctypes.byref(needed))
    err = ctypes.get_last_error()
    if not ok and err != ERROR_INSUFFICIENT_BUFFER:
        raise ctypes.WinError(err)

    buf2 = ctypes.create_string_buffer(needed.value)
    ok = func(RelationProcessorPackage, ctypes.byref(buf2), ctypes.byref(needed))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

    offset = 0
    packages = []
    while offset < needed.value:
        hdr = SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_HEADER.from_buffer(buf2, offset)
        if hdr.Relationship == RelationProcessorPackage:
            packages.append({"relationship": "package", "size": int(hdr.Size)})
        offset += hdr.Size

    info["package_rows"] = packages
    info["package_count_api"] = len(packages)

    return info


def _windows_features() -> Dict[str, Any]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    f = kernel32.IsProcessorFeaturePresent
    f.argtypes = [wintypes.DWORD]
    f.restype = wintypes.BOOL

    PF_XMMI_INSTRUCTIONS_AVAILABLE = 6
    PF_XMMI64_INSTRUCTIONS_AVAILABLE = 10
    PF_ARM_V8_INSTRUCTIONS_AVAILABLE = 29
    PF_SSSE3_INSTRUCTIONS_AVAILABLE = 36
    PF_SSE4_1_INSTRUCTIONS_AVAILABLE = 37
    PF_SSE4_2_INSTRUCTIONS_AVAILABLE = 38
    PF_AVX_INSTRUCTIONS_AVAILABLE = 39
    PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
    PF_AVX512F_INSTRUCTIONS_AVAILABLE = 41

    norm = _empty_normalized_features()
    norm.update({
        "sse": bool(f(PF_XMMI_INSTRUCTIONS_AVAILABLE)),
        "sse2": bool(f(PF_XMMI64_INSTRUCTIONS_AVAILABLE)),
        "ssse3": bool(f(PF_SSSE3_INSTRUCTIONS_AVAILABLE)),
        "sse4_1": bool(f(PF_SSE4_1_INSTRUCTIONS_AVAILABLE)),
        "sse4_2": bool(f(PF_SSE4_2_INSTRUCTIONS_AVAILABLE)),
        "avx": bool(f(PF_AVX_INSTRUCTIONS_AVAILABLE)),
        "avx2": bool(f(PF_AVX2_INSTRUCTIONS_AVAILABLE)),
        "avx512f": bool(f(PF_AVX512F_INSTRUCTIONS_AVAILABLE)),
        "arm_v8": bool(f(PF_ARM_V8_INSTRUCTIONS_AVAILABLE)),
    })

    raw = [k for k, v in norm.items() if v]

    return {
        "features_raw": sorted(raw),
        "features_normalized": norm,
    }


def _windows_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": "windows",
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": os.cpu_count(),
    }

    info.update(_windows_wmi_info())

    try:
        api_info = _windows_getlogicalprocessorinfoex()
        info.update(api_info)
    except Exception as e:
        info["api_error"] = str(e)
        info.setdefault("core_classes", {"kind": "efficiency_class", "groups": {}})

    info.update(_windows_features())

    if info.get("package_count") is None and info.get("package_count_api") is not None:
        info["package_count"] = info["package_count_api"]

    if info.get("physical_core_count") is None and info.get("physical_core_count_api") is not None:
        info["physical_core_count"] = info["physical_core_count_api"]

    raw_arch = _windows_architecture_from_wmi(info.get("packages", []))
    info.update(_normalize_arch_name(raw_arch))

    return info


# ============================================================
# Public API
# ============================================================

def get_cpu_inventory() -> Dict[str, Any]:
    system = platform.system()
    if system == "Linux":
        return _linux_info()
    if system == "Darwin":
        return _macos_info()
    if system == "Windows":
        return _windows_info()

    return {
        "platform": system.lower(),
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": os.cpu_count(),
        "physical_core_count": None,
        "package_count": None,
        "core_classes": {"kind": "unknown", "groups": {}},
        "features_raw": [],
        "features_normalized": _empty_normalized_features(),
        **_normalize_arch_name(_python_arch_raw()),
    }


if __name__ == "__main__":
    print(json.dumps(get_cpu_inventory(), indent=2, sort_keys=True))
