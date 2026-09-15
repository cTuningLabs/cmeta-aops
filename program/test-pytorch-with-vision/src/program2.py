import os
import torch
import torchvision

cmeta_targets = os.environ.get('CMETA_TARGETS').split(',')

print ('='*80)
print ("CMETA_TARGETS:", cmeta_targets)

# Check top device
device = 'cpu'
if 'xpu' in cmeta_targets:
    device = 'xpu'
elif 'cuda' in cmeta_targets:
    device = 'cuda'
elif 'rocm' in cmeta_targets:
    device = 'rocm'

print ('')
print (f'PyTorch device: {device}')

print ('')
print ("Torch version:", torch.__version__)

print ('')
print ("TorchVision version:", torchvision.__version__)

if device == 'cuda':

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

