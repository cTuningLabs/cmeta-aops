"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).

The check run after build-pytorchvision compiles and installs torchvision: the versions and compute backends of the
torch it is built against, then torchvision itself - its version and one of its compiled operators (non-maximum
suppression) on the device the build is for, against the CPU.
"""

import os
import sys

import torch

print(f"Python        : {sys.version}")
print(f"PyTorch       : {torch.__version__}")

print(f"CUDA          : {torch.cuda.is_available()} (devices: {torch.cuda.device_count()})")

# cuDNN where it works: on a GPU too old for this torch it raises (an sm_50 GPU beside torch for CUDA 13, 2026-11-26)
try:
    if torch.backends.cudnn.enabled and torch.backends.cudnn.version():
        print("cuDNN enabled :", torch.backends.cudnn.enabled)
        print("cuDNN version  :", torch.backends.cudnn.version())
except RuntimeError as e:
    print("cuDNN         : not usable here -", str(e).split('. ')[0])

_mps = getattr(torch.backends, 'mps', None)
print(f"MPS/Metal     : {bool(_mps and _mps.is_available())}")

_xpu = getattr(torch, 'xpu', None)
print(f"XPU           : {bool(_xpu and _xpu.is_available())}")

# The device of the check: the one the build is for (CMETA_TORCH_DEVICE - torch's "cuda" for CUDA and ROCm, mps, xpu,
# cpu), else the first one torch has
device = os.environ.get('CMETA_TORCH_DEVICE') or (
    'cuda' if torch.cuda.is_available()
    else ('mps' if _mps and _mps.is_available() else 'cpu')
)
a = torch.ones(4, 4, device=device)
b = torch.ones(4, 4, device=device)
c = torch.matmul(a, b)
print(f"Matmul (4x4 ones, device={device}) sum: {c.sum().item()}")

# torchvision: one of its compiled operators on that device, against the CPU
import torchvision
from torchvision.ops import nms

print(f"torchvision   : {torchvision.__version__}")
boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 11, 11], [20, 20, 30, 30]], dtype=torch.float32)
scores = torch.tensor([0.9, 0.8, 0.7])
keep_cpu = nms(boxes, scores, 0.5).tolist()
keep = nms(boxes.to(device), scores.to(device), 0.5).cpu().tolist()
print(f"nms on {device}: kept {keep} (the CPU: {keep_cpu})")
if keep != keep_cpu:
    sys.exit(f'torchvision nms on {device} differs from the CPU')
