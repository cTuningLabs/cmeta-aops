# Tested configurations:

## 2.12.0

### Windows

 * CPU
 * CUDA without cuDNN

 * XPU
    Lots of tricks
    Fail with --compile.debug_info on circle deps
     https://github.com/pytorch/pytorch/pull/185217

 Note: don't clone repo and build in admin mode since many files will be unaccessible later in user mode (similar to sudo)

Note that it seems that building may include python packages into account so if the build stopped, some new packages installed (onnx for example)
and then restarted, the numbers of build files may increase for extra picked up packages!
