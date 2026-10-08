"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Generate with SGLang's offline engine once and record what happened in tmp-cmeta-program-stats.json:
version, device, load and generation time, generated tokens and tokens per second - the way
test-vllm does for vLLM.

Environment (set by the program's _desc.yaml from its parameters):
  CMETA_SGLANG_MODEL              Hugging Face model (default Qwen/Qwen2.5-0.5B-Instruct)
  CMETA_SGLANG_MAX_TOKENS         tokens to generate (default 64)
  CMETA_SGLANG_GPU_MEM            mem_fraction_static: the share of the GPU memory for weights and KV cache (default 0.8)
  CMETA_SGLANG_MAX_LEN            context_length (default 4096)
  CMETA_SGLANG_CUDA_GRAPH         0 to run without CUDA / HIP graphs (default 1: SGLang captures them at start; its
                                  eager decoding is no usable default on ROCm)
  CMETA_SGLANG_TP                 tp_size (GPUs)
  CMETA_SGLANG_ATTENTION_BACKEND  attention_backend (flashinfer, triton, torch_native, aiter ...; SGLang's choice when empty)
"""

import json
import os
import time


def main():
    from importlib.metadata import version as package_version
    import sglang as sgl

    model = os.environ.get('CMETA_SGLANG_MODEL') or 'Qwen/Qwen2.5-0.5B-Instruct'
    max_tokens = int(os.environ.get('CMETA_SGLANG_MAX_TOKENS') or 64)
    targets = os.environ.get('CMETA_TARGETS', '')

    try:
        sglang_version = package_version('sglang')
    except Exception:
        sglang_version = getattr(sgl, '__version__', 'unknown')

    print('SGLang', sglang_version, '| targets:', targets)

    kwargs = {'model_path': model,
              'context_length': int(os.environ.get('CMETA_SGLANG_MAX_LEN') or 4096),
              'random_seed': 12345,
              'log_level': 'warning'}
    if 'cuda' in targets or 'rocm' in targets:
        kwargs['mem_fraction_static'] = float(os.environ.get('CMETA_SGLANG_GPU_MEM') or 0.8)
    # --cuda_graph=0 runs without graphs (a shorter start; on ROCm the decoding then crawls)
    if os.environ.get('CMETA_SGLANG_CUDA_GRAPH', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        kwargs['disable_cuda_graph'] = True
    if os.environ.get('CMETA_SGLANG_TP'):
        kwargs['tp_size'] = int(os.environ['CMETA_SGLANG_TP'])
    if os.environ.get('CMETA_SGLANG_ATTENTION_BACKEND'):
        kwargs['attention_backend'] = os.environ['CMETA_SGLANG_ATTENTION_BACKEND']

    t0 = time.perf_counter()
    llm = sgl.Engine(**kwargs)
    t_load = time.perf_counter() - t0

    prompt = 'How does a computer work? Answer in two sentences.'
    sampling = {'temperature': 0.0, 'max_new_tokens': max_tokens}

    try:
        # The first generation compiles the kernels of the attention backend (triton / aiter on ROCm: more
        # than two minutes on an MI300X); vLLM does that at start, SGLang's engine does not: a short
        # warm-up, timed apart from the measured generation
        t0 = time.perf_counter()
        llm.generate([prompt], {'temperature': 0.0, 'max_new_tokens': 4})
        t_warmup = time.perf_counter() - t0

        t0 = time.perf_counter()
        outputs = llm.generate([prompt], sampling)
        t_gen = time.perf_counter() - t0
    finally:
        llm.shutdown()

    out = outputs[0]
    text = out.get('text', '')
    meta = out.get('meta_info', {}) or {}
    n = meta.get('completion_tokens')
    if n is None:
        n = len(text.split())
    print(text)

    stats = {'sglang': sglang_version,
             'model': model,
             'targets': targets,
             'load_s': round(t_load, 3),
             'warmup_s': round(t_warmup, 3),
             'generate_s': round(t_gen, 3),
             'generated_tokens': n,
             'prompt_tokens': meta.get('prompt_tokens'),
             'tokens_per_second': round(n / t_gen, 2) if t_gen > 0 and n else None,
             'settings': {k: v for k, v in kwargs.items() if k != 'model_path'},
             'response': text}

    try:
        import torch
        stats['torch'] = torch.__version__
        stats['torch_cuda'] = torch.version.cuda
        stats['torch_hip'] = getattr(torch.version, 'hip', None)
        if torch.cuda.is_available():
            stats['device'] = torch.cuda.get_device_name(0)
    except Exception:
        pass

    with open('tmp-cmeta-program-stats.json', 'w', encoding = 'utf-8') as f:
        json.dump(stats, f, indent = 2)
    print(json.dumps({k: v for k, v in stats.items() if k != 'response'}))


if __name__ == '__main__':
    # SGLang's engine starts worker processes: the entry point must be guarded
    main()
