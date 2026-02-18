#include <cstdio>
#include <cuda_runtime.h>

int main() {
    // Print CUDA version
    int runtimeVersion = 0;
    cudaError_t versionErr = cudaRuntimeGetVersion(&runtimeVersion);
    
    if (versionErr == cudaSuccess) {
        int major = runtimeVersion / 1000;
        int minor = (runtimeVersion % 1000) / 10;
        printf("CUDA Version: %d.%d\n", major, minor);
    } else {
        printf("Failed to get CUDA version: %s\n", cudaGetErrorString(versionErr));
    }

    int deviceCount = 0;
    cudaError_t err = cudaGetDeviceCount(&deviceCount);

    if (err != cudaSuccess) {
        printf("cudaGetDeviceCount failed: %s\n", cudaGetErrorString(err));
        return 1;
    }

    if (deviceCount == 0) {
        printf("No CUDA devices found.\n");
        return 0;
    }

    printf("Found %d CUDA device(s):\n", deviceCount);

    for (int i = 0; i < deviceCount; ++i) {
        cudaDeviceProp prop;
        cudaGetDeviceProperties(&prop, i);
        printf("Device %d: %s\n", i, prop.name);
    }

    return 0;
}
