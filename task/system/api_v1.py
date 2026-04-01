"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import uuid
from typing import Any, Dict, List, Optional

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        # Just more user-friendly check for params (duplicate of "run")
        r = self.cm.check_params(params, ['fast'], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}


    ############################################################
    def run(self,
            ctx: dict,          # cMeta context
            fast: bool = False, # If true, use fast detection mode
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        result = {
          'return':0, 
        }

        result['features'] = get_system_info(fast)

        return result

###################################################################################################
def get_system_info(fast: bool = False) -> Dict[str, Any]:
    """
    Return normalized system/hardware information.

    Parameters
    ----------
    fast : bool, default False
        If True, gather a smaller benchmark-friendly subset and skip slower /
        heavier probes where practical.

    Notes
    -----
    - Standard library only.
    - Best effort: availability depends on OS, hardware, drivers, permissions,
      and installed OS utilities.
    - Power-supply / AC-adapter details are much less portable than CPU/RAM/etc.
    """
    system = platform.system().lower()

    info: Dict[str, Any] = {
        "schema_version": 3,
        "fast_mode": fast,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "os": {
            "family": platform.system(),
            "platform": sys.platform,
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
        },
        "system": {
            "vendor": None,
            "product_name": None,
            "product_version": None,
            "product_family": None,
            "product_sku": None,
            "serial_number": None,
            "uuid": None,
            "model_identifier": None,
            "friendly_name": None,
            "chassis_type": None,
            "is_virtual_machine": None,
        },
        "firmware": {
            "vendor": None,
            "version": None,
            "release_date": None,
            "name": None,
            "type": None,
        },
        "cpu": {
            "brand": None,
            "arch": platform.machine(),
            "physical_cores": None,
            "logical_cores": os.cpu_count(),
        },
        "memory": {
            "total_bytes": None,
        },
        "memory_devices": [],
        "video_adapters": [],
        "network": [],
        "storage": [],
        "pci": [],
        "usb": [],
        "power": {
            "ac_online": None,
            "charging": None,
            "battery_present": None,
            "battery_percent": None,
            "battery_state": None,
            "battery_health": None,
            "battery_cycle_count": None,
            "battery_design_capacity_mwh": None,
            "battery_full_charge_capacity_mwh": None,
            "adapter_watts": None,
            "adapter_vendor": None,
            "adapter_model": None,
        },
        "raw": {},
    }

    info["system"]["uuid"] = _best_effort_machine_uuid()

    if system == "windows":
        _fill_windows_info(info, fast=fast)
    elif system == "linux":
        _fill_linux_info(info, fast=fast)
    elif system == "darwin":
        _fill_macos_info(info, fast=fast)

    _normalize_system_info(info)

    if fast:
        return _compact_benchmark_view(info)

    return info


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------

def _run(args: List[str], timeout: int = 20, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=check,
    )


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _safe_run_text(args: List[str], timeout: int = 20) -> Optional[str]:
    try:
        cp = _run(args, timeout=timeout)
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout.strip()


def _safe_run_json(args: List[str], timeout: int = 20) -> Optional[Any]:
    text = _safe_run_text(args, timeout=timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _safe_run_plist(args: List[str], timeout: int = 30) -> Optional[Any]:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None
    if cp.returncode != 0 or not cp.stdout:
        return None
    try:
        return plistlib.loads(cp.stdout)
    except Exception:
        return None


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
            return text or None
    except Exception:
        return None


def _clean_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    bad = {
        "none", "null", "n/a", "na", "unknown", "not specified",
        "to be filled by o.e.m.", "to be filled by oem", "default string",
        "system product name", "system version", "system serial number",
        "unspecified", "not applicable",
    }
    if s.lower() in bad:
        return None
    return s


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _best_effort_machine_uuid() -> Optional[str]:
    try:
        node = uuid.getnode()
        if node:
            return f"{node:012x}"
    except Exception:
        pass
    return None


def _normalize_mac(value: Any) -> Optional[str]:
    s = _clean_value(value)
    if not s:
        return None
    s = s.replace("-", ":").lower()
    parts = s.split(":")
    if len(parts) == 6 and all(re.fullmatch(r"[0-9a-f]{1,2}", p) for p in parts):
        return ":".join(p.zfill(2) for p in parts)
    return s


def _extract_hex(text: Any, token: str) -> Optional[str]:
    s = _clean_value(text)
    if not s:
        return None
    m = re.search(re.escape(token) + r"([0-9A-Fa-f]+)", s)
    return m.group(1).lower() if m else None


def _extract_id_from_text(value: Any) -> Optional[str]:
    s = _clean_value(value)
    if not s:
        return None
    m = re.search(r"0x([0-9A-Fa-f]+)", s)
    if m:
        return m.group(1).lower()
    m = re.search(r"\b([0-9A-Fa-f]{4})\b", s)
    if m:
        return m.group(1).lower()
    return None


def _parse_human_bytes(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)

    s = s.replace(",", "")
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?B)\s*$", s, flags=re.I)
    if not m:
        return None

    num = float(m.group(1))
    unit = m.group(2).upper()
    mult = {
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
    }[unit]
    return int(num * mult)


def _classify_chassis(product_name: Optional[str], product_family: Optional[str]) -> Optional[str]:
    text = " ".join(x for x in [product_name or "", product_family or ""] if x).lower()
    if not text:
        return None
    if any(k in text for k in ["macbook", "thinkpad", "laptop", "notebook", "ultrabook"]):
        return "laptop"
    if any(k in text for k in ["mac mini", "mini pc", "mini"]):
        return "mini"
    if any(k in text for k in ["server", "poweredge", "proliant", "rack"]):
        return "server"
    if any(k in text for k in ["workstation", "precision", "z workstation"]):
        return "workstation"
    if any(k in text for k in ["desktop", "imac", "studio", "tower"]):
        return "desktop"
    return "unknown"


def _dedupe_dicts(items: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = tuple(item.get(k) for k in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_system_info(info: Dict[str, Any]) -> None:
    for section_name in ["system", "firmware", "cpu"]:
        for key, value in list(info[section_name].items()):
            if isinstance(value, str):
                info[section_name][key] = _clean_value(value)

    sysi = info["system"]
    if not sysi["friendly_name"]:
        sysi["friendly_name"] = (
            sysi["product_name"]
            or sysi["model_identifier"]
            or sysi["product_family"]
        )

    if not sysi["chassis_type"]:
        sysi["chassis_type"] = _classify_chassis(sysi.get("product_name"), sysi.get("product_family"))

    info["storage"] = _dedupe_dicts(info["storage"], keys=["name", "serial_number", "model"])
    info["video_adapters"] = _dedupe_dicts(
        info["video_adapters"], keys=["name", "pci_slot", "vendor_id", "device_id"]
    )
    info["memory_devices"] = _dedupe_dicts(
        info["memory_devices"], keys=["locator", "bank_locator", "serial_number", "part_number"]
    )


def _compact_benchmark_view(info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": info["schema_version"],
        "fast_mode": True,
        "python": info["python"],
        "os": {
            "family": info["os"]["family"],
            "release": info["os"]["release"],
            "version": info["os"]["version"],
            "machine": info["os"]["machine"],
            "hostname": info["os"]["hostname"],
        },
        "system": {
            "vendor": info["system"]["vendor"],
            "model": info["system"]["friendly_name"] or info["system"]["product_name"],
            "model_identifier": info["system"]["model_identifier"],
            "serial_number": info["system"]["serial_number"],
            "uuid": info["system"]["uuid"],
            "chassis_type": info["system"]["chassis_type"],
            "is_virtual_machine": info["system"]["is_virtual_machine"],
        },
        "firmware": {
            "vendor": info["firmware"]["vendor"],
            "version": info["firmware"]["version"],
            "release_date": info["firmware"]["release_date"],
            "type": info["firmware"]["type"],
        },
        "cpu": info["cpu"],
        "memory": info["memory"],
        "video_adapters": [
            {
                "name": v.get("name"),
                "vendor": v.get("vendor"),
                "model": v.get("model"),
                "vram_bytes": v.get("vram_bytes"),
                "pci_slot": v.get("pci_slot"),
                "vendor_id": v.get("vendor_id"),
                "device_id": v.get("device_id"),
                "is_integrated": v.get("is_integrated"),
                "is_discrete": v.get("is_discrete"),
            }
            for v in info["video_adapters"]
        ],
        "storage": [
            {
                "name": d.get("name"),
                "model": d.get("model"),
                "serial_number": d.get("serial_number"),
                "size_bytes": d.get("size_bytes"),
                "bus": d.get("bus"),
                "media_type": d.get("media_type"),
            }
            for d in info["storage"]
        ],
        "power": info["power"],
    }


def _guess_integrated_discrete(name: Optional[str], vendor: Optional[str]) -> Dict[str, Optional[bool]]:
    text = " ".join(x for x in [name or "", vendor or ""] if x).lower()
    if any(k in text for k in ["intel", "uhd", "iris", "apple", "vega graphics", "radeon graphics"]):
        return {"is_integrated": True, "is_discrete": False}
    if any(k in text for k in ["nvidia", "geforce", "quadro", "rtx", "gtx", "amd", "radeon rx", "arc "]):
        return {"is_integrated": False, "is_discrete": True}
    return {"is_integrated": None, "is_discrete": None}


# -----------------------------------------------------------------------------
# Windows backend
# -----------------------------------------------------------------------------

def _fill_windows_info(info: Dict[str, Any], fast: bool) -> None:
    ps = _which("powershell") or _which("pwsh")
    if not ps:
        return

    if fast:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$result = [ordered]@{}
$result.ComputerSystem = Get-CimInstance Win32_ComputerSystem |
    Select-Object Manufacturer, Model, TotalPhysicalMemory
$result.ComputerSystemProduct = Get-CimInstance Win32_ComputerSystemProduct |
    Select-Object Vendor, Name, Version, UUID, IdentifyingNumber
$result.BIOS = Get-CimInstance Win32_BIOS |
    Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, Name, SerialNumber
$result.Processor = Get-CimInstance Win32_Processor |
    Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
$result.Video = Get-CimInstance Win32_VideoController |
    Select-Object Name, AdapterCompatibility, DriverVersion, AdapterRAM, PNPDeviceID
$result.Disk = Get-CimInstance Win32_DiskDrive |
    Select-Object Model, SerialNumber, InterfaceType, Size, MediaType, DeviceID
$result.Battery = Get-CimInstance Win32_Battery |
    Select-Object Name, EstimatedChargeRemaining, BatteryStatus
$result | ConvertTo-Json -Depth 5
"""
    else:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$result = [ordered]@{}
$result.ComputerSystem = Get-CimInstance Win32_ComputerSystem |
    Select-Object Manufacturer, Model, TotalPhysicalMemory
$result.ComputerSystemProduct = Get-CimInstance Win32_ComputerSystemProduct |
    Select-Object Vendor, Name, Version, UUID, IdentifyingNumber
$result.BIOS = Get-CimInstance Win32_BIOS |
    Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, Name, SerialNumber
$result.Processor = Get-CimInstance Win32_Processor |
    Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
$result.Video = Get-CimInstance Win32_VideoController |
    Select-Object Name, AdapterCompatibility, DriverVersion, AdapterRAM, PNPDeviceID
$result.Disk = Get-CimInstance Win32_DiskDrive |
    Select-Object Model, SerialNumber, InterfaceType, Size, MediaType, DeviceID
$result.Memory = Get-CimInstance Win32_PhysicalMemory |
    Select-Object BankLabel, DeviceLocator, Manufacturer, PartNumber, SerialNumber, Capacity, Speed, ConfiguredClockSpeed
$result.Battery = Get-CimInstance Win32_Battery |
    Select-Object Name, EstimatedChargeRemaining, BatteryStatus
$result | ConvertTo-Json -Depth 6
"""
    data = _safe_run_json([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=90)
    if not isinstance(data, dict):
        return

    if not fast:
        info["raw"]["windows_cim"] = data

    cs = data.get("ComputerSystem") or {}
    csp = data.get("ComputerSystemProduct") or {}
    bios = data.get("BIOS") or {}
    cpu = data.get("Processor") or {}

    info["system"]["vendor"] = _clean_value(csp.get("Vendor") or cs.get("Manufacturer"))
    info["system"]["product_name"] = _clean_value(csp.get("Name") or cs.get("Model"))
    info["system"]["friendly_name"] = _clean_value(cs.get("Model"))
    info["system"]["product_version"] = _clean_value(csp.get("Version"))
    info["system"]["serial_number"] = _clean_value(csp.get("IdentifyingNumber") or bios.get("SerialNumber"))
    info["system"]["uuid"] = _clean_value(csp.get("UUID")) or info["system"]["uuid"]

    info["firmware"]["vendor"] = _clean_value(bios.get("Manufacturer"))
    info["firmware"]["version"] = _clean_value(bios.get("SMBIOSBIOSVersion"))
    info["firmware"]["name"] = _clean_value(bios.get("Name"))
    info["firmware"]["release_date"] = _clean_value(bios.get("ReleaseDate"))
    info["firmware"]["type"] = "BIOS/UEFI"

    info["cpu"]["brand"] = _clean_value(cpu.get("Name"))
    info["cpu"]["physical_cores"] = _to_int(cpu.get("NumberOfCores"))
    info["cpu"]["logical_cores"] = _to_int(cpu.get("NumberOfLogicalProcessors")) or info["cpu"]["logical_cores"]

    info["memory"]["total_bytes"] = _to_int(cs.get("TotalPhysicalMemory"))
    info["video_adapters"] = _parse_windows_video(data.get("Video"))
    info["storage"] = _parse_windows_storage(data.get("Disk"))
    info["power"] = _parse_windows_power(data.get("Battery"), info["power"])

    if not fast:
        info["memory_devices"] = _parse_windows_memory_devices(data.get("Memory"))

    vm_hint = " ".join(
        x for x in [
            info["system"]["vendor"] or "",
            info["system"]["product_name"] or "",
            info["cpu"]["brand"] or "",
        ] if x
    ).lower()
    info["system"]["is_virtual_machine"] = any(
        k in vm_hint for k in ["vmware", "virtualbox", "kvm", "qemu", "hyper-v", "virtual machine"]
    )


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_windows_video(rows: Any) -> List[Dict[str, Any]]:
    out = []
    for row in _ensure_list(rows):
        if not isinstance(row, dict):
            continue
        pnp = _clean_value(row.get("PNPDeviceID"))
        name = _clean_value(row.get("Name"))
        vendor = _clean_value(row.get("AdapterCompatibility"))
        kinds = _guess_integrated_discrete(name, vendor)

        out.append({
            "name": name,
            "vendor": vendor,
            "model": name,
            "driver": _clean_value(row.get("DriverVersion")),
            "vram_bytes": _to_int(row.get("AdapterRAM")),
            "pci_slot": None,
            "vendor_id": _extract_hex(pnp, "VEN_"),
            "device_id": _extract_hex(pnp, "DEV_"),
            "subsystem_id": _extract_hex(pnp, "SUBSYS_"),
            "class_code": _extract_hex(pnp, "CC_"),
            "bus": "PCI" if pnp and pnp.upper().startswith("PCI\\") else None,
            "is_integrated": kinds["is_integrated"],
            "is_discrete": kinds["is_discrete"],
            "display_attached": None,
        })
    return out


def _parse_windows_storage(rows: Any) -> List[Dict[str, Any]]:
    out = []
    for row in _ensure_list(rows):
        if not isinstance(row, dict):
            continue
        out.append({
            "name": _clean_value(row.get("DeviceID")),
            "model": _clean_value(row.get("Model")),
            "serial_number": _clean_value(row.get("SerialNumber")),
            "size_bytes": _to_int(row.get("Size")),
            "bus": _clean_value(row.get("InterfaceType")),
            "media_type": _clean_value(row.get("MediaType")),
        })
    return out


def _parse_windows_memory_devices(rows: Any) -> List[Dict[str, Any]]:
    out = []
    for row in _ensure_list(rows):
        if not isinstance(row, dict):
            continue
        out.append({
            "locator": _clean_value(row.get("DeviceLocator")),
            "bank_locator": _clean_value(row.get("BankLabel")),
            "manufacturer": _clean_value(row.get("Manufacturer")),
            "part_number": _clean_value(row.get("PartNumber")),
            "serial_number": _clean_value(row.get("SerialNumber")),
            "size_bytes": _to_int(row.get("Capacity")),
            "speed_mt_s": _to_int(row.get("Speed")),
            "configured_speed_mt_s": _to_int(row.get("ConfiguredClockSpeed")),
            "memory_type": None,
            "form_factor": None,
        })
    return out


def _parse_windows_power(rows: Any, base: Dict[str, Any]) -> Dict[str, Any]:
    rows = _ensure_list(rows)
    if not rows:
        base["battery_present"] = False
        return base

    row = rows[0]
    if not isinstance(row, dict):
        return base

    base["battery_present"] = True
    base["battery_percent"] = _to_int(row.get("EstimatedChargeRemaining"))
    status = _to_int(row.get("BatteryStatus"))
    base["battery_state"] = str(status) if status is not None else None

    # WMI BatteryStatus is not beautifully portable, but 6 often means charging.
    if status == 6:
        base["charging"] = True
    elif status is not None:
        base["charging"] = False

    return base


# -----------------------------------------------------------------------------
# Linux backend
# -----------------------------------------------------------------------------

def _fill_linux_info(info: Dict[str, Any], fast: bool) -> None:
    _fill_linux_dmi(info)
    _fill_linux_cpu_memory(info)
    info["storage"] = _fill_linux_storage()
    info["video_adapters"] = _fill_linux_video()
    info["power"] = _fill_linux_power(info["power"])

    if not fast:
        info["memory_devices"] = _fill_linux_memory_devices()
        info["pci"] = _fill_linux_pci()
        info["usb"] = _fill_linux_usb()

    vm_hint = " ".join(
        x for x in [
            info["system"]["vendor"] or "",
            info["system"]["product_name"] or "",
            info["system"]["model_identifier"] or "",
            info["cpu"]["brand"] or "",
        ] if x
    ).lower()
    info["system"]["is_virtual_machine"] = any(
        k in vm_hint for k in ["vmware", "virtualbox", "kvm", "qemu", "bochs", "hyper-v", "virtual machine"]
    )


def _fill_linux_dmi(info: Dict[str, Any]) -> None:
    dmi = "/sys/class/dmi/id"
    if not os.path.isdir(dmi):
        return

    info["system"]["vendor"] = _clean_value(_read_text(os.path.join(dmi, "sys_vendor")))
    info["system"]["product_name"] = _clean_value(_read_text(os.path.join(dmi, "product_name")))
    info["system"]["product_version"] = _clean_value(_read_text(os.path.join(dmi, "product_version")))
    info["system"]["product_family"] = _clean_value(_read_text(os.path.join(dmi, "product_family")))
    info["system"]["product_sku"] = _clean_value(_read_text(os.path.join(dmi, "product_sku")))
    info["system"]["serial_number"] = _clean_value(_read_text(os.path.join(dmi, "product_serial")))
    info["system"]["uuid"] = _clean_value(_read_text(os.path.join(dmi, "product_uuid"))) or info["system"]["uuid"]
    info["system"]["model_identifier"] = _clean_value(_read_text(os.path.join(dmi, "board_name")))

    info["firmware"]["vendor"] = _clean_value(_read_text(os.path.join(dmi, "bios_vendor")))
    info["firmware"]["version"] = _clean_value(_read_text(os.path.join(dmi, "bios_version")))
    info["firmware"]["release_date"] = _clean_value(_read_text(os.path.join(dmi, "bios_date")))
    info["firmware"]["type"] = "BIOS/UEFI"


def _fill_linux_cpu_memory(info: Dict[str, Any]) -> None:
    cpuinfo = _read_text("/proc/cpuinfo") or ""
    m = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, flags=re.MULTILINE)
    if m:
        info["cpu"]["brand"] = _clean_value(m.group(1))

    # Best-effort physical cores from physical id + core id.
    core_pairs = set()
    for block in cpuinfo.split("\n\n"):
        pid = None
        cid = None
        for line in block.splitlines():
            if ":" not in line:
                continue
            k, v = [x.strip() for x in line.split(":", 1)]
            if k == "physical id":
                pid = v
            elif k == "core id":
                cid = v
        if pid is not None and cid is not None:
            core_pairs.add((pid, cid))
    if core_pairs:
        info["cpu"]["physical_cores"] = len(core_pairs)

    meminfo = _read_text("/proc/meminfo") or ""
    m = re.search(r"^MemTotal:\s+(\d+)\s+kB$", meminfo, flags=re.MULTILINE)
    if m:
        info["memory"]["total_bytes"] = int(m.group(1)) * 1024


def _fill_linux_storage() -> List[Dict[str, Any]]:
    lsblk = _which("lsblk")
    out: List[Dict[str, Any]] = []

    if lsblk:
        data = _safe_run_json([lsblk, "-J", "-O", "-b"], timeout=30)
        if isinstance(data, dict):
            for dev in data.get("blockdevices", []):
                if dev.get("type") != "disk":
                    continue
                tran = _clean_value(dev.get("tran"))
                media_type = None
                if (tran or "").lower() == "nvme":
                    media_type = "NVMe SSD"
                elif dev.get("rota") == 0:
                    media_type = "SSD"
                elif dev.get("rota") == 1:
                    media_type = "HDD"

                out.append({
                    "name": dev.get("name"),
                    "model": _clean_value(dev.get("model")),
                    "serial_number": _clean_value(dev.get("serial")),
                    "size_bytes": _to_int(dev.get("size")),
                    "bus": tran,
                    "media_type": media_type,
                })
            if out:
                return out

    root = "/sys/block"
    if not os.path.isdir(root):
        return out

    for name in sorted(os.listdir(root)):
        if name.startswith(("loop", "ram", "dm-")):
            continue
        base = os.path.join(root, name)
        model = _clean_value(_read_text(os.path.join(base, "device/model")))
        serial = _clean_value(_read_text(os.path.join(base, "device/serial")))
        sectors = _to_int(_read_text(os.path.join(base, "size")))
        logical = _to_int(_read_text(os.path.join(base, "queue/logical_block_size"))) or 512

        bus = None
        if name.startswith("nvme"):
            bus = "NVMe"
        out.append({
            "name": name,
            "model": model,
            "serial_number": serial,
            "size_bytes": sectors * logical if sectors is not None else None,
            "bus": bus,
            "media_type": "NVMe SSD" if name.startswith("nvme") else None,
        })
    return out


def _fill_linux_video() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pci_root = "/sys/bus/pci/devices"
    if not os.path.isdir(pci_root):
        return out

    for slot in sorted(os.listdir(pci_root)):
        base = os.path.join(pci_root, slot)
        class_code = (_read_text(os.path.join(base, "class")) or "").lower().replace("0x", "")
        if not class_code.startswith("03"):
            continue

        out.append({
            "name": None,
            "vendor": None,
            "model": None,
            "driver": None,
            "vram_bytes": None,
            "pci_slot": slot.lower(),
            "vendor_id": (_read_text(os.path.join(base, "vendor")) or "").replace("0x", "") or None,
            "device_id": (_read_text(os.path.join(base, "device")) or "").replace("0x", "") or None,
            "subsystem_id": None,
            "class_code": class_code,
            "bus": "PCI",
            "is_integrated": None,
            "is_discrete": None,
            "display_attached": None,
        })

    # Enrich with lspci if available.
    lspci = _which("lspci")
    if lspci:
        text = _safe_run_text([lspci, "-D", "-nn"], timeout=30)
        if text:
            by_slot = {x["pci_slot"]: x for x in out if x.get("pci_slot")}
            for line in text.splitlines():
                m = re.match(
                    r"^([0-9a-fA-F:.]+)\s+(.+?)\s+\[([0-9a-fA-F]{4})\]:\s+(.+?)\s+\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]",
                    line
                )
                if not m:
                    continue
                slot = m.group(1).lower()
                if slot not in by_slot:
                    continue

                item = by_slot[slot]
                name = m.group(4)
                item["name"] = name
                item["model"] = name
                item["vendor_id"] = m.group(5).lower()
                item["device_id"] = m.group(6).lower()

                kinds = _guess_integrated_discrete(name, None)
                if "nvidia" in name.lower():
                    item["vendor"] = "NVIDIA"
                elif "amd" in name.lower() or "radeon" in name.lower():
                    item["vendor"] = "AMD"
                elif "intel" in name.lower():
                    item["vendor"] = "Intel"
                item["is_integrated"] = kinds["is_integrated"]
                item["is_discrete"] = kinds["is_discrete"]

    return out


def _fill_linux_memory_devices() -> List[Dict[str, Any]]:
    dmidecode = _which("dmidecode")
    if not dmidecode:
        return []

    text = _safe_run_text([dmidecode, "--type", "17"], timeout=60)
    if not text:
        return []

    devices = []
    current: Dict[str, Any] = {}

    for line in text.splitlines():
        if not line.strip():
            if current:
                devices.append(current)
                current = {}
            continue

        m = re.match(r"^\s*([^:]+):\s*(.*)$", line)
        if not m:
            continue

        key = m.group(1).strip()
        val = m.group(2).strip()

        if key == "Size":
            if val.lower() == "no module installed":
                current["_skip"] = True
            else:
                current["size_bytes"] = _parse_human_bytes(val)
        elif key == "Locator":
            current["locator"] = _clean_value(val)
        elif key == "Bank Locator":
            current["bank_locator"] = _clean_value(val)
        elif key == "Manufacturer":
            current["manufacturer"] = _clean_value(val)
        elif key == "Part Number":
            current["part_number"] = _clean_value(val)
        elif key == "Serial Number":
            current["serial_number"] = _clean_value(val)
        elif key == "Type":
            current["memory_type"] = _clean_value(val)
        elif key == "Form Factor":
            current["form_factor"] = _clean_value(val)
        elif key == "Speed":
            m2 = re.match(r"(\d+)\s*MT/s", val, flags=re.I)
            if m2:
                current["speed_mt_s"] = int(m2.group(1))
        elif key in {"Configured Memory Speed", "Configured Clock Speed"}:
            m2 = re.match(r"(\d+)\s*MT/s", val, flags=re.I)
            if m2:
                current["configured_speed_mt_s"] = int(m2.group(1))

    if current:
        devices.append(current)

    out = []
    for d in devices:
        if d.get("_skip"):
            continue
        out.append({
            "locator": d.get("locator"),
            "bank_locator": d.get("bank_locator"),
            "manufacturer": d.get("manufacturer"),
            "part_number": d.get("part_number"),
            "serial_number": d.get("serial_number"),
            "size_bytes": d.get("size_bytes"),
            "speed_mt_s": d.get("speed_mt_s"),
            "configured_speed_mt_s": d.get("configured_speed_mt_s"),
            "memory_type": d.get("memory_type"),
            "form_factor": d.get("form_factor"),
        })
    return out


def _fill_linux_pci() -> List[Dict[str, Any]]:
    out = []
    root = "/sys/bus/pci/devices"
    if not os.path.isdir(root):
        return out

    for slot in sorted(os.listdir(root)):
        base = os.path.join(root, slot)
        out.append({
            "slot": slot.lower(),
            "vendor_id": (_read_text(os.path.join(base, "vendor")) or "").replace("0x", "") or None,
            "device_id": (_read_text(os.path.join(base, "device")) or "").replace("0x", "") or None,
            "class_code": (_read_text(os.path.join(base, "class")) or "").replace("0x", "") or None,
        })
    return out


def _fill_linux_usb() -> List[Dict[str, Any]]:
    out = []
    root = "/sys/bus/usb/devices"
    if not os.path.isdir(root):
        return out

    for name in sorted(os.listdir(root)):
        base = os.path.join(root, name)
        if not os.path.isdir(base):
            continue
        vid = _read_text(os.path.join(base, "idVendor"))
        pid = _read_text(os.path.join(base, "idProduct"))
        if not vid and not pid:
            continue
        out.append({
            "name": name,
            "vendor_id": _clean_value(vid),
            "product_id": _clean_value(pid),
            "manufacturer": _clean_value(_read_text(os.path.join(base, "manufacturer"))),
            "product": _clean_value(_read_text(os.path.join(base, "product"))),
            "serial_number": _clean_value(_read_text(os.path.join(base, "serial"))),
        })
    return out


def _fill_linux_power(base: Dict[str, Any]) -> Dict[str, Any]:
    root = "/sys/class/power_supply"
    if not os.path.isdir(root):
        return base

    entries = [os.path.join(root, x) for x in os.listdir(root)]
    bat_dirs = [p for p in entries if os.path.basename(p).startswith("BAT")]
    ac_dirs = [
        p for p in entries
        if os.path.basename(p).upper() in {"AC", "ACAD", "ACADAPTER", "MAINS"}
        or _read_text(os.path.join(p, "type")) == "Mains"
    ]
    usb_dirs = [p for p in entries if _read_text(os.path.join(p, "type")) in {"USB", "USB_C", "USB_PD"}]

    for p in ac_dirs + usb_dirs:
        online = _read_text(os.path.join(p, "online"))
        if online in {"0", "1"}:
            base["ac_online"] = (online == "1")
            break

    if bat_dirs:
        base["battery_present"] = True
        p = bat_dirs[0]

        capacity = _read_text(os.path.join(p, "capacity"))
        status = _read_text(os.path.join(p, "status"))
        health = _read_text(os.path.join(p, "health"))
        cycle = _read_text(os.path.join(p, "cycle_count"))

        base["battery_percent"] = _to_int(capacity)
        base["battery_state"] = _clean_value(status)
        base["battery_health"] = _clean_value(health)
        base["battery_cycle_count"] = _to_int(cycle)

        if status:
            low = status.lower()
            if "charging" in low:
                base["charging"] = True
            elif "discharging" in low or "full" in low or "not charging" in low:
                base["charging"] = False

        energy_full_design = _read_text(os.path.join(p, "energy_full_design"))
        energy_full = _read_text(os.path.join(p, "energy_full"))
        charge_full_design = _read_text(os.path.join(p, "charge_full_design"))
        charge_full = _read_text(os.path.join(p, "charge_full"))

        if energy_full_design and energy_full_design.isdigit():
            base["battery_design_capacity_mwh"] = int(energy_full_design)
        elif charge_full_design and charge_full_design.isdigit():
            base["battery_design_capacity_mwh"] = int(charge_full_design)

        if energy_full and energy_full.isdigit():
            base["battery_full_charge_capacity_mwh"] = int(energy_full)
        elif charge_full and charge_full.isdigit():
            base["battery_full_charge_capacity_mwh"] = int(charge_full)
    else:
        base["battery_present"] = False

    for p in usb_dirs + ac_dirs:
        power_now = _read_text(os.path.join(p, "power_now"))
        voltage_now = _read_text(os.path.join(p, "voltage_now"))
        current_now = _read_text(os.path.join(p, "current_now"))

        base["adapter_model"] = _clean_value(_read_text(os.path.join(p, "model_name"))) or base["adapter_model"]
        base["adapter_vendor"] = _clean_value(_read_text(os.path.join(p, "manufacturer"))) or base["adapter_vendor"]

        if power_now and power_now.isdigit():
            base["adapter_watts"] = int(power_now) / 1_000_000.0
            break
        if voltage_now and current_now and voltage_now.isdigit() and current_now.isdigit():
            base["adapter_watts"] = (int(voltage_now) * int(current_now)) / 1_000_000_000_000.0
            break

    return base


# -----------------------------------------------------------------------------
# macOS backend
# -----------------------------------------------------------------------------

def _fill_macos_info(info: Dict[str, Any], fast: bool) -> None:
    _fill_macos_basic(info)
    _fill_macos_video(info)
    _fill_macos_storage(info, fast=fast)
    _fill_macos_power(info["power"])

    if not fast:
        _fill_macos_memory_devices(info)
        _fill_macos_usb(info)

    vm_hint = " ".join(
        x for x in [
            info["system"]["vendor"] or "",
            info["system"]["product_name"] or "",
            info["system"]["model_identifier"] or "",
            info["cpu"]["brand"] or "",
        ] if x
    ).lower()
    info["system"]["is_virtual_machine"] = any(
        k in vm_hint for k in ["vmware", "virtualbox", "parallels", "qemu", "virtual machine"]
    )


def _fill_macos_basic(info: Dict[str, Any]) -> None:
    sp = _which("system_profiler")
    if sp:
        data = _safe_run_plist([sp, "-xml", "SPHardwareDataType"], timeout=60)
        if isinstance(data, list) and data:
            items = data[0].get("_items") if isinstance(data[0], dict) else None
            if isinstance(items, list) and items:
                hw = items[0]
                info["system"]["vendor"] = "Apple"
                info["system"]["serial_number"] = _clean_value(hw.get("serial_number") or hw.get("machine_serial_number"))
                info["system"]["model_identifier"] = _clean_value(hw.get("machine_model") or hw.get("model_identifier"))
                info["system"]["friendly_name"] = _clean_value(hw.get("machine_name") or hw.get("model_name"))
                info["system"]["product_name"] = info["system"]["friendly_name"] or info["system"]["model_identifier"]
                info["cpu"]["brand"] = _clean_value(hw.get("chip_type") or hw.get("cpu_type") or hw.get("current_processor_name"))

                mem = hw.get("physical_memory")
                if isinstance(mem, str):
                    info["memory"]["total_bytes"] = _parse_human_bytes(mem)

                boot_rom = _clean_value(hw.get("boot_rom_version"))
                if boot_rom:
                    info["firmware"]["version"] = boot_rom
                    info["firmware"]["type"] = "EFI"

                platform_uuid = _clean_value(hw.get("platform_UUID"))
                if platform_uuid:
                    info["system"]["uuid"] = platform_uuid

                info["cpu"]["physical_cores"] = _to_int(hw.get("number_cores")) or info["cpu"]["physical_cores"]
                info["cpu"]["logical_cores"] = _to_int(hw.get("logical_cpu")) or info["cpu"]["logical_cores"]

    sysctl = _which("sysctl")
    if sysctl:
        mem = _safe_run_text([sysctl, "-n", "hw.memsize"])
        if mem and mem.isdigit():
            info["memory"]["total_bytes"] = int(mem)

        cpu_brand = _safe_run_text([sysctl, "-n", "machdep.cpu.brand_string"])
        if cpu_brand:
            info["cpu"]["brand"] = cpu_brand

        phys = _safe_run_text([sysctl, "-n", "hw.physicalcpu"])
        logical = _safe_run_text([sysctl, "-n", "hw.logicalcpu"])
        info["cpu"]["physical_cores"] = _to_int(phys) or info["cpu"]["physical_cores"]
        info["cpu"]["logical_cores"] = _to_int(logical) or info["cpu"]["logical_cores"]


def _fill_macos_video(info: Dict[str, Any]) -> None:
    sp = _which("system_profiler")
    if not sp:
        return

    data = _safe_run_plist([sp, "-xml", "SPDisplaysDataType"], timeout=60)
    if not isinstance(data, list) or not data:
        return

    items = data[0].get("_items") if isinstance(data[0], dict) else None
    if not isinstance(items, list):
        return

    out = []

    def walk(nodes: List[Any]) -> None:
        for item in nodes:
            if not isinstance(item, dict):
                continue

            name = _clean_value(item.get("_name") or item.get("sppci_model"))
            vendor = _clean_value(item.get("spdisplays_vendor"))

            vram = None
            for k in ["spdisplays_vram", "spdisplays_vram_shared", "spdisplays_vram_dynamic"]:
                if item.get(k):
                    vram = _parse_human_bytes(item.get(k))
                    if vram:
                        break

            kinds = _guess_integrated_discrete(name, vendor)

            out.append({
                "name": name,
                "vendor": vendor,
                "model": name,
                "driver": _clean_value(item.get("spdisplays_metal")),
                "vram_bytes": vram,
                "pci_slot": None,
                "vendor_id": _extract_id_from_text(item.get("spdisplays_vendor-id")),
                "device_id": _extract_id_from_text(item.get("spdisplays_device-id")),
                "subsystem_id": None,
                "class_code": None,
                "bus": "PCI",
                "is_integrated": kinds["is_integrated"],
                "is_discrete": kinds["is_discrete"],
                "display_attached": ("spdisplays_ndrvs" in item),
            })

            children = item.get("_items")
            if isinstance(children, list):
                walk(children)

    walk(items)
    info["video_adapters"] = out


def _fill_macos_storage(info: Dict[str, Any], fast: bool) -> None:
    sp = _which("system_profiler")
    if not sp:
        return

    dtypes = ["SPNVMeDataType"] if fast else ["SPNVMeDataType", "SPSerialATADataType", "SPStorageDataType"]
    out: List[Dict[str, Any]] = []

    for dtype in dtypes:
        data = _safe_run_plist([sp, "-xml", dtype], timeout=90)
        if not isinstance(data, list) or not data:
            continue
        items = data[0].get("_items") if isinstance(data[0], dict) else None
        if not isinstance(items, list):
            continue

        def walk(nodes: List[Any]) -> None:
            for item in nodes:
                if not isinstance(item, dict):
                    continue

                name = _clean_value(item.get("_name"))
                model = _clean_value(item.get("device_model") or item.get("spnvme_model") or item.get("spsata_model"))
                serial = _clean_value(item.get("device_serial") or item.get("spnvme_serial_number") or item.get("spsata_serial_number"))
                size = _parse_human_bytes(item.get("size") or item.get("spnvme_size") or item.get("_size_in_bytes"))

                if any([name, model, serial, size]):
                    out.append({
                        "name": name,
                        "model": model or name,
                        "serial_number": serial,
                        "size_bytes": size,
                        "bus": "NVMe" if dtype == "SPNVMeDataType" else ("SATA" if dtype == "SPSerialATADataType" else _clean_value(item.get("bus_protocol"))),
                        "media_type": "NVMe SSD" if dtype == "SPNVMeDataType" else _clean_value(item.get("medium_type")),
                    })

                children = item.get("_items")
                if isinstance(children, list):
                    walk(children)

        walk(items)

    info["storage"] = out


def _fill_macos_memory_devices(info: Dict[str, Any]) -> None:
    sp = _which("system_profiler")
    if not sp:
        return

    data = _safe_run_plist([sp, "-xml", "SPMemoryDataType"], timeout=60)
    if not isinstance(data, list) or not data:
        return

    items = data[0].get("_items") if isinstance(data[0], dict) else None
    if not isinstance(items, list):
        return

    out = []

    def walk(nodes: List[Any]) -> None:
        for item in nodes:
            if not isinstance(item, dict):
                continue

            name = _clean_value(item.get("_name"))
            size = _parse_human_bytes(item.get("dimm_size") or item.get("size"))
            typ = _clean_value(item.get("dimm_type") or item.get("type"))

            if any([name, size, typ]):
                out.append({
                    "locator": name,
                    "bank_locator": None,
                    "manufacturer": _clean_value(item.get("dimm_manufacturer") or item.get("manufacturer")),
                    "part_number": _clean_value(item.get("dimm_part_number") or item.get("part_number")),
                    "serial_number": _clean_value(item.get("dimm_serial_number") or item.get("serial_number")),
                    "size_bytes": size,
                    "speed_mt_s": None,
                    "configured_speed_mt_s": None,
                    "memory_type": typ,
                    "form_factor": None,
                })

            children = item.get("_items")
            if isinstance(children, list):
                walk(children)

    walk(items)
    info["memory_devices"] = out


def _fill_macos_usb(info: Dict[str, Any]) -> None:
    sp = _which("system_profiler")
    if not sp:
        return

    data = _safe_run_plist([sp, "-xml", "SPUSBDataType"], timeout=60)
    if not isinstance(data, list) or not data:
        return

    items = data[0].get("_items") if isinstance(data[0], dict) else None
    if not isinstance(items, list):
        return

    out = []

    def walk(nodes: List[Any]) -> None:
        for item in nodes:
            if not isinstance(item, dict):
                continue

            vid = _extract_id_from_text(item.get("vendor_id"))
            pid = _extract_id_from_text(item.get("product_id"))
            name = _clean_value(item.get("_name"))

            if any([vid, pid, name]):
                out.append({
                    "name": name,
                    "vendor_id": vid,
                    "product_id": pid,
                    "manufacturer": _clean_value(item.get("manufacturer")),
                    "product": name,
                    "serial_number": _clean_value(item.get("serial_num")),
                })

            children = item.get("_items")
            if isinstance(children, list):
                walk(children)

    walk(items)
    info["usb"] = out


def _fill_macos_power(base: Dict[str, Any]) -> Dict[str, Any]:
    pmset = _which("pmset")
    system_profiler = _which("system_profiler")

    if pmset:
        text = _safe_run_text([pmset, "-g", "batt"], timeout=20)
        if text:
            low = text.lower()
            if "ac power" in low:
                base["ac_online"] = True
            elif "battery power" in low:
                base["ac_online"] = False

            m = re.search(r"(\d+)%", text)
            if m:
                base["battery_percent"] = int(m.group(1))

            if "charging" in low:
                base["charging"] = True
                base["battery_state"] = "charging"
            elif "discharging" in low:
                base["charging"] = False
                base["battery_state"] = "discharging"
            elif "charged" in low:
                base["charging"] = False
                base["battery_state"] = "charged"

            base["battery_present"] = ("no batteries" not in low)

    if system_profiler:
        data = _safe_run_plist([system_profiler, "-xml", "SPPowerDataType"], timeout=60)
        if isinstance(data, list) and data:
            items = data[0].get("_items") if isinstance(data[0], dict) else None
            if isinstance(items, list) and items:
                item = items[0]

                cycle = item.get("sppower_battery_cycle_count")
                health = item.get("sppower_battery_health_info")
                watts = item.get("ac_charger_watts") or item.get("sppower_ac_charger_watts")
                vendor = item.get("ac_charger_information") or item.get("charger_model")

                base["battery_cycle_count"] = _to_int(cycle) or base["battery_cycle_count"]
                if isinstance(health, str):
                    base["battery_health"] = health
                elif isinstance(health, dict):
                    base["battery_health"] = _clean_value(json.dumps(health))
                if watts is not None:
                    if isinstance(watts, str) and watts.isdigit():
                        base["adapter_watts"] = int(watts)
                    elif isinstance(watts, int):
                        base["adapter_watts"] = watts
                if isinstance(vendor, str):
                    base["adapter_model"] = _clean_value(vendor) or base["adapter_model"]

    return base
