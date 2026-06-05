On Ubuntu 26.04 static build deps:

  sudo apt install libz-dev libzstd-dev libjitterentropy3-dev

    Still fails with some missing function ...

On AzureLinux static build deps [DIDN'T MANAGE TO GET ALL STATIC LIB DEPS - DON'T EXIST]

  sudo tdnf install -y \
   glibc-static \
   libstdc++-static \
   openssl-devel \
   zlib-devel \
   libzstd-devel

  sudo tdnf install zlib-devel libzstd-devel jitterentropy-devel


On Rocky Linux for static build: DOESN'T WORK
 gcc static didn't work - fails finding some static packages
 sudo dnf install -y dnf-plugins-core
 sudo dnf config-manager --set-enabled crb
 sudo dnf install -y \
   glibc-static \
   libstdc++-static \
   openssl-devel \
   zlib-devel \
   libzstd-devel
 sudo dnf install -y \
  openssl-static \
  zlib-static \
  libzstd-static

 Didn't manage to install LLVM because of old /lib64/libstdc++.so.6 
  strings /lib64/libstdc++.so.6 | grep GLIBCXX_3.4.30
 This didn't help:
  sudo dnf install gcc-toolset-12-gcc-c++ libstdc++-devel
