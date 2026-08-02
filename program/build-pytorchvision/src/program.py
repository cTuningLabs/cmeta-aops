"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).

Minimal verification script run after build-pytorch compiles and installs PyTorch.
Prints version and available compute backends so the build can be confirmed.
"""

import sys

import torch

print(f"Python        : {sys.version}")
print(f"PyTorch       : {torch.__version__}")

print(f"CUDA          : {torch.cuda.is_available()} (devices: {torch.cuda.device_count()})")

if torch.backends.cudnn.enabled and torch.backends.cudnn.version():
    print("cuDNN enabled :", torch.backends.cudnn.enabled)
    print("cuDNN version  :", torch.backends.cudnn.version())

_mps = getattr(torch.backends, 'mps', None)
print(f"MPS/Metal     : {bool(_mps and _mps.is_available())}")

_xpu = getattr(torch, 'xpu', None)
print(f"XPU           : {bool(_xpu and _xpu.is_available())}")

# Quick functional check on the default device
device = (
    'cuda' if torch.cuda.is_available()
    else ('mps' if _mps and _mps.is_available() else 'cpu')
)
a = torch.ones(4, 4, device=device)
b = torch.ones(4, 4, device=device)
c = torch.matmul(a, b)
print(f"Matmul (4x4 ones, device={device}) sum: {c.sum().item()}")
