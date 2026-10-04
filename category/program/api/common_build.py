"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared by the programs that build large projects from source (build-vllm, build-pytorch):

    from program_22788f3c30d04e6d.api.common_build import default_max_jobs

Their build systems start one compile job per CPU unless MAX_JOBS says otherwise, and a CUDA
kernel can take several GiB of RAM to compile: on a laptop with many cores and little RAM the
build then fails with an out-of-memory kill. default_max_jobs() sizes MAX_JOBS to the RAM.
"""

import os
import sys


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
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        except Exception:
            return None
    return None


def default_max_jobs(device, nvcc_threads = 1):
    """Parallel compile jobs that fit the RAM: CUDA kernels take ~4 GiB per job, C++ ~2 GiB."""
    cpus = os.cpu_count() or 1
    ram = total_ram_gib()
    per_job = 4.0 if device in ('cuda', 'rocm') else 2.0
    jobs = cpus if ram is None else max(1, min(cpus, int(ram / (per_job * max(1, nvcc_threads)))))
    return jobs
