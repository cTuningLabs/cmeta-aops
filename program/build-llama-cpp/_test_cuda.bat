::set CUDA_HOME=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2
::set PATH=%CUDA_HOME%\bin;%PATH%
cx program run build-llama-cpp,a48c282bec5c45b8 --compute=cuda --compile.fastest -v -j --target_tmp=tmp-cuda-dynamic -j --clean
:: --checkout=b9006
::--checkout=master
:: --env.+PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64"
::--clean
::--clean
:: --recompile
:: --clean
