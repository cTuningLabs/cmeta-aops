import os
import torch


print ('='*80)
print ("CMETA_COMPUTE:", os.environ.get('CMETA_COMPUTE'))

print ('')
print ("Torch version:", torch.__version__)

print ('')
print ("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print ("CUDA device count:", torch.cuda.device_count())
    print ("Device name:", torch.cuda.get_device_name(0))
    print ("CUDA runtime used by PyTorch:", torch.version.cuda)

    import subprocess

    driver = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]
    ).decode().strip()

    print ('')
    print ("System CUDA driver version:", driver)

print ('='*80)

device = 'cuda'

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
