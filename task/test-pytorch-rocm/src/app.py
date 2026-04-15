import os
import torch
import subprocess


print ('='*80)
print ("CMETA_COMPUTE:", os.environ.get('CMETA_COMPUTE'))

print ('')
print ("Torch version:", torch.__version__)

print ('')
print ("ROCm HIP version:", torch.version.hip)

if torch.cuda.is_available():
    print ('')
    print ("GPU device count:", torch.cuda.device_count())
    print ("Device name:", torch.cuda.get_device_name(0))
    
    try:
        driver = subprocess.check_output(
            ["rocm-smi", "--showid", "--showtemp"]
        ).decode().strip()
        
        print ('')
        print ("ROCm driver/system info:")
        print (driver)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print ("ROCm driver info not available")
else:
    print ("GPU not available")

print ('='*80)
