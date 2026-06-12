from vllm import LLM, SamplingParams

print(vllm.__version__)

model_name = "Qwen/Qwen2.5-0.5B-Instruct"

llm = LLM(
    model=model_name,
)

sampling_params = SamplingParams(
    temperature=0.7,
    max_tokens=64,
)

prompt = "What is the computer?"

outputs = llm.generate(
    [prompt],
    sampling_params,
)

for output in outputs:
    print(output.outputs[0].text)
