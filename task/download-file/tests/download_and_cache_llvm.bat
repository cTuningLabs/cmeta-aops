cxt download-file --url=https://github.com/llvm/llvm-project/releases/download/llvmorg-22.1.2/clang+llvm-22.1.2-x86_64-pc-windows-msvc.tar.xz ^
     --cache ^
     --cache-extra-alias=llvm ^
     --unzip ^
     --clean_after_unzip ^
     --strip_folders=1 ^
     --check_file=content/bin/clang.exe ^
     -j


