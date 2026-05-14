cxt test-build-llama.cpp-from-git ^
   --use.clone-git-pytorch.tag="b9006" ^
   --use.clone-git-pytorch.cache_extra_params.version_tag="b9006" ^
   --use.clone-git-pytorch.cache_extra_params.tag="b9006" ^
   --use.clone-git-pytorch.cache_extra_params.version="9006" ^
   --use.clone-git-pytorch.path="X:\Work\llama-cpp-src\b9006" ^
   --use.target.compute=cpu ^
   --save_here -q 

:: --clean-build

::   --use.cmake.version=">=4.3.2" ^

:: --check_dir_size

::   --save_here --skip_configure -q

::--clean_build  -q

::   --use.cmd_before_building.open_shell ^

::   --use.cmd_before_cleaning.open_shell

::   --save_here --clean_build  -q

:: --fail
