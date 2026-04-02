import os
import vllm
import torch


print ('='*80)
print ("CMETA_COMPUTE:", os.environ.get('CMETA_COMPUTE'))

print ('')
print ("vLLM version:", vllm.__version__)

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

from vllm import LLM, SamplingParams

# Initialize model (use a small one for testing)
llm = LLM(model="facebook/opt-125m")

# Define sampling parameters
sampling_params = SamplingParams(
    temperature=0.7,
    max_tokens=50
)

# Run inference
outputs = llm.generate("Hello, my name is", sampling_params)

# Print result
for output in outputs:
    print(output.outputs[0].text)

print ('='*80)
