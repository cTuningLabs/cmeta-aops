"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Generate with vLLM once and record what happened in tmp-cmeta-program-stats.json:
version, device, load and generation time, generated tokens and tokens per second.

Environment (set by the program's _desc.yaml from its parameters):
  CMETA_VLLM_MODEL        Hugging Face model (default Qwen/Qwen2.5-0.5B-Instruct)
  CMETA_VLLM_MAX_TOKENS   tokens to generate (default 64)
  CMETA_VLLM_GPU_MEM      gpu_memory_utilization (default 0.8; small GPUs need room for the display)
  CMETA_VLLM_MAX_LEN      max_model_len (default 4096)
  CMETA_VLLM_ENFORCE_EAGER  0 to allow CUDA graphs (default 1: eager)
  CMETA_VLLM_CPU_OFFLOAD_GB cpu_offload_gb (weights in CPU memory)
  CMETA_VLLM_DTYPE        dtype (auto, bfloat16, float16, float32)
  CMETA_VLLM_TP           tensor_parallel_size (GPUs)
"""

import json
import os
import time


def main():
    import vllm
    from vllm import LLM, SamplingParams

    model = os.environ.get('CMETA_VLLM_MODEL') or 'Qwen/Qwen2.5-0.5B-Instruct'
    max_tokens = int(os.environ.get('CMETA_VLLM_MAX_TOKENS') or 64)
    targets = os.environ.get('CMETA_TARGETS', '')

    print('vLLM', vllm.__version__, '| targets:', targets)

    kwargs = {'model': model,
              'max_model_len': int(os.environ.get('CMETA_VLLM_MAX_LEN') or 4096),
              'enforce_eager': True,
              'seed': 12345}
    if 'cuda' in targets or 'rocm' in targets or 'xpu' in targets:
        kwargs['gpu_memory_utilization'] = float(os.environ.get('CMETA_VLLM_GPU_MEM') or 0.8)
    # --enforce_eager=0 lets vLLM capture CUDA graphs (faster decoding, longer start)
    if os.environ.get('CMETA_VLLM_ENFORCE_EAGER', '').strip().lower() in ('0', 'false', 'no', 'off'):
        kwargs['enforce_eager'] = False
    # --cpu_offload_gb: weights kept in CPU memory (--compute=cpu,cuda offload experiments)
    if os.environ.get('CMETA_VLLM_CPU_OFFLOAD_GB'):
        kwargs['cpu_offload_gb'] = float(os.environ['CMETA_VLLM_CPU_OFFLOAD_GB'])
    if os.environ.get('CMETA_VLLM_DTYPE'):
        kwargs['dtype'] = os.environ['CMETA_VLLM_DTYPE']
    if os.environ.get('CMETA_VLLM_TP'):
        kwargs['tensor_parallel_size'] = int(os.environ['CMETA_VLLM_TP'])

    t0 = time.perf_counter()
    llm = LLM(**kwargs)
    t_load = time.perf_counter() - t0

    params = SamplingParams(temperature = 0.0, max_tokens = max_tokens)
    prompt = 'How does a computer work? Answer in two sentences.'

    t0 = time.perf_counter()
    outputs = llm.generate([prompt], params)
    t_gen = time.perf_counter() - t0

    text = outputs[0].outputs[0].text
    n = len(outputs[0].outputs[0].token_ids)
    print(text)

    stats = {'vllm': vllm.__version__,
             'model': model,
             'targets': targets,
             'load_s': round(t_load, 3),
             'generate_s': round(t_gen, 3),
             'generated_tokens': n,
             'tokens_per_second': round(n / t_gen, 2) if t_gen > 0 else None,
             'settings': {k: v for k, v in kwargs.items() if k != 'model'},
             'response': text}

    try:
        import torch
        stats['torch'] = torch.__version__
        stats['torch_cuda'] = torch.version.cuda
        if torch.cuda.is_available():
            stats['device'] = torch.cuda.get_device_name(0)
    except Exception:
        pass

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)
    print(json.dumps({k: v for k, v in stats.items() if k != 'response'}))


if __name__ == '__main__':
    # vLLM starts worker processes: the entry point must be guarded
    main()
