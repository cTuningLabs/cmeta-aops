import torch

print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())

if torch.cuda.is_available():
    print("Device name:", torch.cuda.get_device_name(0))

print("Torch version:", torch.__version__)
print("CUDA runtime used by PyTorch:", torch.version.cuda)

import subprocess

driver = subprocess.check_output(
    ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]
).decode().strip()

print("CUDA driver version:", driver)
