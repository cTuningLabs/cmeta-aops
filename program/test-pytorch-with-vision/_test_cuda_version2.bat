set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
set PATH=C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64;%PATH%
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\extras\CUPTI\lib64;%PATH%

cx program run test-pytorch-with-vision -v -j --clean --compute=cuda --use.pip-torchvision.update --use.pip-torchvision.version=0.27.0 --use.pip-torchvision.with.flags="--no-deps"

::     --env.+PATH,="D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\bin\Hostx64\x64,C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64,C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64"
