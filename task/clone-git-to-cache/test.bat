set checkout=b9006

cxt clone-git-to-cache ^
    src-llama-cpp ^
    https://github.com/ggml-org/llama.cpp ^
    --checkout=%checkout% 

::    --path="x:\work\llama-cpp-src\%checkout%" -j

::    --cache-extra-params.tag=%tag% ^
::    --cache-extra-params.version=%version% ^
::   --cache-extra-params.name=%name% ^
::   --cache-extra-tags=%name%,github
