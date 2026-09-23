cx task run git-clone https://github.com/vllm-project/vllm.git --cache --cache_repo=fgg-work-usb ^
    --path=x:\work\vllm\v0.13.0 ^
    --tag=v0.13.0 --cache-extra-params.version=0.13.0 --cache-extra-params.name=vllm-src --cache-extra-tags=vllm,src,github -j --update
