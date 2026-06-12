set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
set PATH=C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64;%PATH%
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\extras\CUPTI\lib64;%PATH%

cx program run build-pytorch,de1ea5b65d8c4b5e -v --target_tmp=tmp-cuda2 --checkout=v2.12.0 --compute=cpu,cuda --use_cudnn -q

:: https://pytorch.org/get-started/previous-versions

