from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    """
    Parse strings like:
      "0,1,2,3"
      "0-3"
      "0-3,8-11"
    """
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
    """
    Build topology from /sys/devices/system/cpu/cpuX/topology.
    This is useful even when lscpu is unavailable.
    """
    cpus = []
    packages: Dict[str, set] = {}
    cores: Dict[tuple, set] = {}
    capacities: Dict[str, List[int]] = {}

    for cpu_dir in _cpu_dirs():
        cpu_id = int(cpu_dir.name[3:])
        topo = cpu_dir / "topology"

        physical_package_id = None
        core_id = None
        thread_siblings = None
        core_siblings = None

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
        "core_capacity_groups": {
            str(k): sorted(v) for k, v in sorted(capacities.items(), key=lambda x: int(x[0]))
        },
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


def _linux_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": "linux",
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": _linux_usable_cpu_count(),
    }
    info.update(_linux_lscpu())
    info.update(_linux_sysfs_topology())

    # Prefer lscpu counts when available; otherwise fall back to sysfs-derived counts.
    if info.get("socket_count") is None:
        info["socket_count"] = info.get("package_count_sysfs")
    if info.get("physical_core_count") is None:
        info["physical_core_count"] = info.get("physical_core_count_sysfs")

    # Derive physical_core_count from lscpu summary if possible.
    if info.get("physical_core_count") is None:
        s = info.get("socket_count")
        c = info.get("cores_per_socket")
        if s is not None and c is not None:
            info["physical_core_count"] = s * c

    return info


def _sysctl_int(name: str) -> Optional[int]:
    try:
        return int(_run(["sysctl", "-n", name]))
    except Exception:
        return None


def _macos_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": "macos",
        "logical_cpu_count": os.cpu_count(),
        "usable_logical_cpu_count": os.cpu_count(),
        "physical_cpu_count": _sysctl_int("hw.physicalcpu"),
        "logical_cpu_count_sysctl": _sysctl_int("hw.logicalcpu"),
        "nperflevels": _sysctl_int("hw.nperflevels"),
        "performance_levels": [],
    }

    nperf = info["nperflevels"]
    if nperf:
        levels = []
        for i in range(nperf):
            levels.append({
                "perflevel": i,
                "physicalcpu": _sysctl_int(f"hw.perflevel{i}.physicalcpu"),
                "logicalcpu": _sysctl_int(f"hw.perflevel{i}.logicalcpu"),
            })
        info["performance_levels"] = levels

    return info


# ---------------- Windows low-level topology ----------------

# Constants from Windows headers
RelationProcessorCore = 0
RelationProcessorPackage = 3

ERROR_INSUFFICIENT_BUFFER = 122
LTP_PC_SMT = 0x1


class GROUP_AFFINITY(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_size_t),  # ULONG_PTR
        ("Group", wintypes.WORD),
        ("Reserved", wintypes.WORD * 3),
    ]


class PROCESSOR_RELATIONSHIP_HEADER(ctypes.Structure):
    """
    Fixed-size prefix of PROCESSOR_RELATIONSHIP.
    We only need the header plus the first GROUP_AFFINITY.
    """
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
  Select-Object DeviceID, Name, NumberOfCores, NumberOfLogicalProcessors
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


def _windows_getlogicalprocessorinfoex() -> Dict[str, Any]:
    """
    Enumerate cores/packages and per-core EfficiencyClass using
    GetLogicalProcessorInformationEx.
    """
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
    if ok:
        # Unexpected, but continue
        pass
    err = ctypes.get_last_error()
    if err != ERROR_INSUFFICIENT_BUFFER:
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

        # First GROUP_AFFINITY starts right after PROCESSOR_RELATIONSHIP_HEADER.
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

    # Packages
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

    # Prefer API package/core counts when available.
    if info.get("package_count") is None and info.get("package_count_api") is not None:
        info["package_count"] = info["package_count_api"]
    if info.get("physical_core_count") is None and info.get("physical_core_count_api") is not None:
        info["physical_core_count"] = info["physical_core_count_api"]

    return info


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
    }


if __name__ == "__main__":
    print(json.dumps(get_cpu_inventory(), indent=2, sort_keys=True))
