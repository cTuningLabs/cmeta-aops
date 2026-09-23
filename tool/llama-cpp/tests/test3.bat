cx config set task --meta.winget_install_flags="--silent --accept-source-agreements --accept-package-agreements --disable-interactivity"

:: On Linux/Debian, can use only high version (until custom install)
:: But on Windows - need specific version
cxt test-clang-cpp --use.llvm.version=22.1.1 -q -v

