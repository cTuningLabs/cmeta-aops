set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
set PATH=C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64;%PATH%
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\extras\CUPTI\lib64;%PATH%

cx program run image-classification-pytorch,847cab73d50c4e1d -v -j --clean --compute=cuda --use.pip-torchvision.version=0.27.0 --use.pip-torchvision.with.flags="--no-deps"
