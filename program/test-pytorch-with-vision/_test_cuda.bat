set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
set PATH=C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64;%PATH%
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\extras\CUPTI\lib64;%PATH%

cx program run test-pytorch-with-vision -v -j --clean --compute=cuda
