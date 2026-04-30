cx . run ^
   --use.clone-git-pytorch.tag="v2.11.0" ^
   --use.clone-git-pytorch.cache_extra_params.version_tag="v2.11.0" ^
   --use.clone-git-pytorch.cache_extra_params.tag="v2.11.0" ^
   --use.clone-git-pytorch.cache_extra_params.version="2.11.0" ^
   --use.clone-git-pytorch.path="x:\work\pytorch-src\v2.11.0" ^
   --use.cmake.version=4.3.0 ^
   --use.target.compute=cpu,xpu ^
   --save_here -q --clean-build

:: --check_dir_size

::   --save_here --skip_configure -q

::--clean_build  -q

::   --use.cmd_before_building.open_shell ^

::   --use.cmd_before_cleaning.open_shell

::   --save_here --clean_build  -q

:: --fail
