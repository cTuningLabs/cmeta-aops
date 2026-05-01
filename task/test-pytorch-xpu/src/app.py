import os
import torch
import subprocess


print ('='*80)
print ("CMETA_COMPUTE:", os.environ.get('CMETA_COMPUTE'))

print ('')
print ("Torch version:", torch.__version__)

print ("XPU available:", torch.xpu.is_available())

if torch.xpu.is_available():
    print("Device name:", torch.xpu.get_device_name(0))
else:
    print("No XPU device found")
    exit(1)

device = os.environ.get('CMETA_COMPUTE')
if not device:
    if torch.xpu.is_available():
        device = "xpu"
    else:
        device = "cpu"

x = torch.tensor([1.0, 2.0, 3.0], device=device)
y = torch.tensor([4.0, 5.0, 6.0], device=device)

z = x + y

print("x device:", x.device)
print("y device:", y.device)
print("z device:", z.device)

print("x[0,0,0]:", x[0])
print("y[0,0,0]:", y[0])
print("z[0,0,0]:", z[0])

print(z)

print ('='*80)
