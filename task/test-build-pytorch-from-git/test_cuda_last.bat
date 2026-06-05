cx . run ^
   --use.clone-git-pytorch.cache_extra_params.version_tag="main" ^
   --use.clone-git-pytorch.cache_extra_params.tag="main" ^
   --use.clone-git-pytorch.cache_extra_params.version="main" ^
   --use.clone-git-pytorch.path="x:\work\pytorch-src\main" ^
   --use.cmake.version=4.3.0 ^
   --use.target.compute=cpu,cuda-sdk ^
   --save_here 


:: --clean_build --fail


::   --use.cmd_before_cleaning.open_shell

::   --save_here --clean_build  -q

:: --fail
