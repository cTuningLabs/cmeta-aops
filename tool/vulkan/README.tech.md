# Vulkan in cMeta: the runtime, the SDK and the vulkan target

| Artifact | Does |
|---|---|
| `tool/vulkan` | the Vulkan runtime: the loader library and the GPUs its drivers expose |
| `tool/vulkan-sdk` | what building Vulkan programs needs: headers, `glslc`, the loader library to link with |
| `task/target--vulkan` | the `vulkan` target: fails without a Vulkan device, sets up the SDK for builds |

## The runtime: tool/vulkan

```bash
cx tool setup vulkan -j                     # loader, Vulkan version, devices
cx tool setup vulkan --tool_path=<loader>   # a given loader (vulkan-1.dll, libvulkan.so.1, libvulkan.1.dylib)
```

- The devices come from the loader itself (`vulkan_probe.py` through ctypes): no SDK and no
  `vulkaninfo` needed. On macOS, MoltenVK is found through portability enumeration.
- The features are `devices`, `gpus`, `vendors` and `paths.loader`. Each device has its index,
  type (discrete, integrated, CPU), vendor, name, Vulkan version and device-local memory.
- Installing:
  - the loader comes with the GPU driver on Windows;
  - on Linux, `libvulkan1` and `mesa-vulkan-drivers` (the distribution's names, with sudo);
  - on macOS, `brew install vulkan-loader molten-vk`.

## The SDK: tool/vulkan-sdk

```bash
cx tool setup vulkan-sdk                       # detect, else install the pinned SDK (1.4.363.0)
cx tool setup vulkan-sdk --version=1.4.350.0   # another LunarG release
cx tool setup vulkan-sdk --versions            # the releases (Vulkan-Headers tags)
cx tool setup vulkan-sdk --detect -j           # detect only
```

- It is detected wherever an SDK can be: `$VULKAN_SDK`, the LunarG folders
  (`C:\VulkanSDK\<version>`, `~/VulkanSDK/<version>/{x86_64,macOS}`), the distribution packages
  (`/usr`) and Homebrew. A folder counts when it has `glslc` and `vulkan/vulkan_core.h`.
- Installed down the ladder, without administrator rights first:
  1. the LunarG SDK into the cMeta cache: the Linux x86_64 tarball, or the Windows installer
     in copy-only mode (into `~/VulkanSDK/<version>` when the cache path holds a `!`, which the
     installer refuses);
  2. Homebrew on macOS (`vulkan-headers vulkan-loader molten-vk shaderc spirv-headers
     vulkan-tools`), winget on Windows (`KhronosGroup.VulkanSDK`);
  3. the distribution packages, with sudo, elsewhere (Linux arm64, ...).
- The result exports `VULKAN_SDK` and puts the SDK's `bin` on `PATH` for the steps that follow.
  That is how CMake's FindVulkan finds headers, library and `glslc`.
- The features are `paths.root`, `bin`, `include`, `lib`, `glslc`, `header`, `loader_lib`
  (the library to link with) and `kind` (`lunarg` or `system`). The LunarG Linux SDK has no
  loader, so `loader_lib` is then the system's `libvulkan.so.1`.

## The vulkan target

```bash
cx program run llama-cpp --compute=vulkan
cx program run build-llama-cpp --compute=vulkan --target_tmp=auto
cx program run test-ollama --compute=vulkan          # sets OLLAMA_VULKAN=1
```

- It fails when the loader lists no device. When it lists only CPU devices (Mesa's llvmpipe),
  it warns.
- It sets `CMETA_TARGET_VULKAN=1`, and its SDK step sets up `tool/vulkan-sdk` for builds.
- Several GPUs may expose Vulkan (an Intel iGPU and an NVIDIA GPU, say). llama.cpp then uses
  all of them unless `--devices=Vulkan1` picks one, and `perf.devices` records which it used.
- The same GPU through CUDA and through Vulkan: build llama.cpp with `--compute=cuda,vulkan`,
  then run with `--devices=CUDA0` or `--devices=Vulkan0`.
