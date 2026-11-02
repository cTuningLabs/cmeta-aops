/*
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The Core ML probe of task/target--ios-npu: built for the device (iOS 17 and newer, where Core ML lists its compute
devices), run there as an app, it prints one JSON line (after CMETA_PROBE:) with the compute devices Core ML
offers - the CPU, the GPU and the Neural Engine with its core count - which is how an app reaches the Neural
Engine: through a Core ML model, never directly.
*/

#import <Foundation/Foundation.h>
#import <CoreML/CoreML.h>
#import <Metal/Metal.h>
#include <stdio.h>

int main(int argc, char **argv) {
  @autoreleasepool {
    NSArray *devices = MLAllComputeDevices();
    NSMutableString *list = [NSMutableString string];
    int cores = 0, cpu = 0, gpu = 0, ne = 0;

    for (id<MLComputeDeviceProtocol> d in devices) {
      NSString *sep = list.length ? @", " : @"";
      if ([d isKindOfClass:[MLNeuralEngineComputeDevice class]]) {
        ne++;
        cores = (int)[(MLNeuralEngineComputeDevice *)d totalCoreCount];
        [list appendFormat:@"%@{\"type\": \"neural_engine\", \"cores\": %d}", sep, cores];
      } else if ([d isKindOfClass:[MLGPUComputeDevice class]]) {
        gpu++;
        [list appendFormat:@"%@{\"type\": \"gpu\", \"name\": \"%@\"}", sep, [(MLGPUComputeDevice *)d metalDevice].name];
      } else if ([d isKindOfClass:[MLCPUComputeDevice class]]) {
        cpu++;
        [list appendFormat:@"%@{\"type\": \"cpu\"}", sep];
      }
    }

    printf("CMETA_PROBE: {\"compute_devices\": [%s], \"neural_engine\": %s, \"neural_engine_cores\": %d, "
           "\"cpu_devices\": %d, \"gpu_devices\": %d}\n",
           [list UTF8String], ne ? "true" : "false", cores, cpu, gpu);
    return 0;
  }
}
