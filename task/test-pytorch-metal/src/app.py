import os
import torch
import subprocess


print ('='*80)
print ("CMETA_COMPUTE:", os.environ.get('CMETA_COMPUTE'))

print ('')
print ("Torch version:", torch.__version__)

print("MPS built:", torch.backends.mps.is_built())
print("MPS available:", torch.backends.mps.is_available())

if not torch.backends.mps.is_available():
    print("No MPS device found")
    exit(1)

if torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"

x = torch.tensor([1.0, 2.0, 3.0], device=device)
y = torch.tensor([4.0, 5.0, 6.0], device=device)

z = x + y

print("x device:", x.device)
print("y device:", y.device)
print("z device:", z.device)

print("x[0]:", x[0])
print("y[0]:", y[0])
print("z[0]:", z[0])

print(z)

print ('='*80)

