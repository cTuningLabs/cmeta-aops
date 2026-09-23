cx config set task --meta.winget_install_flags="--silent --accept-source-agreements --accept-package-agreements"

cxt test-clang-cpp --use.llvm.version=22.1.0 -q -v

