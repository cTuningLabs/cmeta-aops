/*
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The Metal probe of task/target--ios-gpu: built for the device, run there as an app, it prints one JSON line
(after CMETA_PROBE:) with the Metal device, its GPU families (the highest Apple, Common and Metal family it
supports, asked by number so that a family newer than this SDK still counts), limits and features.
*/

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/message.h>
#include <stdio.h>

static const char *yes(BOOL b) { return b ? "true" : "false"; }

int main(int argc, char **argv) {
  @autoreleasepool {
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    if (dev == nil) {
      printf("CMETA_PROBE: {\"error\": \"no Metal device\"}\n");
      return 1;
    }

    int apple = 0, common = 0, metal = 0;
    for (int i = 1; i <= 20; i++) if ([dev supportsFamily:(MTLGPUFamily)(1000 + i)]) apple = i;
    for (int i = 1; i <= 5; i++) if ([dev supportsFamily:(MTLGPUFamily)(3000 + i)]) common = i;
    for (int i = 1; i <= 5; i++) if ([dev supportsFamily:(MTLGPUFamily)(5000 + i)]) metal = i + 2;   /* 5001 = Metal 3 */

    const char *arch = "";
    if ([dev respondsToSelector:@selector(architecture)]) arch = [[dev.architecture name] UTF8String];

    /* Declared for macOS first: asked by selector, so the probe builds with any iOS SDK */
    unsigned long long working_set = 0;
    SEL wss = @selector(recommendedMaxWorkingSetSize);
    if ([dev respondsToSelector:wss]) working_set = ((unsigned long long (*)(id, SEL))objc_msgSend)(dev, wss);

    MTLSize t = dev.maxThreadsPerThreadgroup;

    printf("CMETA_PROBE: {\"name\": \"%s\", \"architecture\": \"%s\", \"registry_id\": %llu, \"unified_memory\": %s, "
           "\"apple_family\": %d, \"common_family\": %d, \"metal_version\": %d, "
           "\"max_threads_per_threadgroup\": [%lu, %lu, %lu], \"max_threadgroup_memory_length\": %lu, "
           "\"max_buffer_length\": %llu, \"recommended_max_working_set_size\": %llu, \"current_allocated_size\": %llu, "
           "\"raytracing\": %s, \"function_pointers\": %s, \"dynamic_libraries\": %s, \"float32_filtering\": %s, "
           "\"bc_texture_compression\": %s}\n",
           [dev.name UTF8String], arch, (unsigned long long)dev.registryID, yes(dev.hasUnifiedMemory),
           apple, common, metal,
           (unsigned long)t.width, (unsigned long)t.height, (unsigned long)t.depth, (unsigned long)dev.maxThreadgroupMemoryLength,
           (unsigned long long)dev.maxBufferLength, working_set, (unsigned long long)dev.currentAllocatedSize,
           yes(dev.supportsRaytracing), yes(dev.supportsFunctionPointers), yes(dev.supportsDynamicLibraries),
           yes(dev.supports32BitFloatFiltering), yes(dev.supportsBCTextureCompression));
    return 0;
  }
}
