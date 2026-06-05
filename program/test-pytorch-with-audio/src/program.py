import os
import sys
import torch
import torchaudio

def normalize_device(device):
    device = (device or "cpu").strip().lower()

    # PyTorch ROCm uses the CUDA device API.
    if device == "rocm":
        return "cuda"

    return device


def is_device_available(device_type):
    if device_type == "cpu":
        return True

    if device_type == "cuda":
        return torch.cuda.is_available()

    if device_type == "xpu":
        return hasattr(torch, "xpu") and torch.xpu.is_available()

    if device_type == "mps":
        return (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        )

    return False


def get_device_name(device_type):
    if device_type == "cpu":
        return "CPU"

    if device_type == "cuda":
        return torch.cuda.get_device_name(0)

    if device_type == "xpu":
        try:
            return torch.xpu.get_device_name(0)
        except Exception:
            return "Intel XPU"

    if device_type == "mps":
        return "Apple Metal"

    return "Unknown"



def main():

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
        device = 'cuda'
    elif 'metal' in cmeta_targets:
        device = 'mps'
    elif 'xpu' in cmeta_targets:
        device = 'xpu'


    print ('')
    print (f'PyTorch target device: {device}')

    print ('')
    print ("Torch version:", torch.__version__)

    print ('')
    print ("TorchAudio version:", torchaudio.__version__)


    device_type = normalize_device(device)

    supported_devices = {"cpu", "cuda", "xpu", "mps"}

    if device not in supported_devices:
        print(f"FAIL: unsupported device '{raw_device}'")
        print(f"Supported values: {sorted(supported_devices | {'rocm'})}")
        return 1

    if not is_device_available(device_type):
        print(f"SKIP: {device_type} is not available")
        return 0

    device = torch.device(device_type)

    print ('')
    print ("Device Name:", get_device_name(device_type))

    try:
        waveform = torch.randn(1, 16000, device=device)

        print ('')
        print ("Waveform shape:", waveform.shape)
        print ("Waveform device:", waveform.device)

        resampled = torchaudio.functional.resample(
            waveform,
            orig_freq=16000,
            new_freq=8000,
        )

        print ('')
        print ("Resampled shape:", resampled.shape)
        print ("Resampled device:", resampled.device)

        if resampled.device.type != device.type:
            print(
                f"FAIL: output moved from "
                f"{device.type} to {resampled.device.type}"
            )
            return 1

        print ('')
        print (f"✓ torchaudio.functional.resample works on {device.type}")
        return 0

    except NotImplementedError as e:
        print(f"UNSUPPORTED: resample is not implemented for {device.type}")
        print(f"Reason: {e}")
        return 2

    except RuntimeError as e:
        print(f"RUNTIME ERROR while executing on {device.type}")
        print(f"Reason: {e}")
        return 3

    except Exception as e:
        print(f"UNEXPECTED ERROR on {device.type}: {type(e).__name__}")
        print(f"Reason: {e}")
        return 4

if __name__ == "__main__":
    r = main()
    print ('='*80)
    sys.exit(r)
