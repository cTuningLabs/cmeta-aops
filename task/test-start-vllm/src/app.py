import os
import vllm
import torch
#from multiprocessing import freeze_support
from vllm import LLM, SamplingParams

def main():
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

    llm = LLM(
        model="facebook/opt-125m",
        gpu_memory_utilization=0.70,
        max_model_len=512,
        max_num_seqs=1,
#        cpu_offload_gb=2,
    )

    params = SamplingParams(
        temperature=0.0,
        max_tokens=32,
    )

    prompts = [
      "Hello, my name is",
      "The capital of France is",
    ]

    for prompt in prompts:
        print ('='*80)

        print (f'Prompt: {prompt}')
        print ('')

        print ('Answer:')
        print ('')

        outputs = llm.generate([prompt], params)

        for output in outputs:
            print(output.outputs[0].text)

        print ('='*80)

if __name__ == "__main__":
 #   freeze_support()
    main()
