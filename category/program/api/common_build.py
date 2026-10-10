"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared by the programs that build large projects from source (build-vllm, build-pytorch, build-pytorchvision):

    from program_22788f3c30d04e6d.api.common_build import default_max_jobs

Their build systems start one compile job per CPU unless MAX_JOBS says otherwise, and a compile job
can take several GiB of RAM (a CUDA kernel, PyTorch's vectorized C++ kernels): on a laptop with many
cores and little RAM the build then ends in an out-of-memory kill - and the kernel's killer takes the
user's session with it. default_max_jobs() sizes MAX_JOBS to the RAM that is free for the build.
"""

import os
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


def default_max_jobs(device, nvcc_threads = 1):
    """Parallel compile jobs that fit the RAM: 4 GiB per CUDA/ROCm job, 3 GiB per C++ job, after 2 GiB kept
    for the system. The budget is the RAM available now when the OS says it (a build next to a browser, a
    VM or another build gets fewer jobs), the machine's RAM otherwise; never more jobs than CPUs, never
    fewer than one; one job per CPU, as the build systems do, when the RAM is unknown."""
    cpus = os.cpu_count() or 1
    ram = total_ram_gib()
    if ram is None:
        return cpus
    available = available_ram_gib()
    budget = ram if available is None else min(ram, available)
    per_job = (CUDA_JOB_GIB if device in ('cuda', 'rocm') else CXX_JOB_GIB) * max(1, nvcc_threads)
    return max(1, min(cpus, int((budget - SYSTEM_RESERVE_GIB) / per_job)))
