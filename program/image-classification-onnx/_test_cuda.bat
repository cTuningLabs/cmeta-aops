set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
set PATH=C:\Program Files\NVIDIA\CUDNN\v9.21\bin\13.2\x64;%PATH%
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\extras\CUPTI\lib64;%PATH%

:: NOTE: the CUDA execution provider needs the "onnxruntime-gpu" pip package
:: instead of the default CPU-only "onnxruntime".
cx program run image-classification-onnx,e34d672079744b8f -v -j --clean --compute=cuda
