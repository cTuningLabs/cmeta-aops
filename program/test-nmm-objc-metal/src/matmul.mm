/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Developed with the help of ChatGPT and Claude.
*/

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "matmul.h"

#if defined(__APPLE__) && __has_include(<Metal/Metal.h>) && __has_include(<MetalPerformanceShaders/MetalPerformanceShaders.h>)
#define HAVE_METAL_MPS 1
#import <Metal/Metal.h>
#import <MetalPerformanceShaders/MetalPerformanceShaders.h>
#else
#define HAVE_METAL_MPS 0
#endif

#if HAVE_METAL_MPS
static id<MTLDevice> g_metal_device = nil;
static id<MTLCommandQueue> g_metal_queue = nil;
#endif

int matmul_init_metal(void) {
#if HAVE_METAL_MPS
  if (g_metal_device != nil && g_metal_queue != nil) {
    return 1;
  }

  g_metal_device = MTLCreateSystemDefaultDevice();
  if (g_metal_device == nil) {
    return 0;
  }

  if (!MPSSupportsMTLDevice(g_metal_device)) {
#if !__has_feature(objc_arc)
    [g_metal_device release];
#endif
    g_metal_device = nil;
    return 0;
  }

  g_metal_queue = [g_metal_device newCommandQueue];
  if (g_metal_queue == nil) {
#if !__has_feature(objc_arc)
    [g_metal_device release];
#endif
    g_metal_device = nil;
    return 0;
  }

  return 1;
#else
  return 0;
#endif
}

void matmul_shutdown_metal(void) {
#if HAVE_METAL_MPS
#if !__has_feature(objc_arc)
  [g_metal_queue release];
  [g_metal_device release];
#endif
  g_metal_queue = nil;
  g_metal_device = nil;
#endif
}

int matmul_f32_metal(const float *a, const float *b, float *c, size_t m, size_t n, size_t k) {
#if HAVE_METAL_MPS
  if (a == NULL || b == NULL || c == NULL) {
    return 0;
  }

  if (g_metal_device == nil || g_metal_queue == nil) {
    if (!matmul_init_metal()) {
      return 0;
    }
  }

  const NSUInteger a_size = (NSUInteger)(m * n * sizeof(float));
  const NSUInteger b_size = (NSUInteger)(n * k * sizeof(float));
  const NSUInteger c_size = (NSUInteger)(m * k * sizeof(float));

  id<MTLBuffer> a_buffer = [g_metal_device newBufferWithLength:a_size options:MTLResourceStorageModeShared];
  id<MTLBuffer> b_buffer = [g_metal_device newBufferWithLength:b_size options:MTLResourceStorageModeShared];
  id<MTLBuffer> c_buffer = [g_metal_device newBufferWithLength:c_size options:MTLResourceStorageModeShared];

  if (a_buffer == nil || b_buffer == nil || c_buffer == nil) {
#if !__has_feature(objc_arc)
    [a_buffer release];
    [b_buffer release];
    [c_buffer release];
#endif
    return 0;
  }

  memcpy([a_buffer contents], a, (size_t)a_size);
  memcpy([b_buffer contents], b, (size_t)b_size);

  MPSMatrixDescriptor *a_desc = [MPSMatrixDescriptor matrixDescriptorWithRows:(NSUInteger)m
                                                                       columns:(NSUInteger)n
                                                                      rowBytes:(NSUInteger)(n * sizeof(float))
                                                                      dataType:MPSDataTypeFloat32];
  MPSMatrixDescriptor *b_desc = [MPSMatrixDescriptor matrixDescriptorWithRows:(NSUInteger)n
                                                                       columns:(NSUInteger)k
                                                                      rowBytes:(NSUInteger)(k * sizeof(float))
                                                                      dataType:MPSDataTypeFloat32];
  MPSMatrixDescriptor *c_desc = [MPSMatrixDescriptor matrixDescriptorWithRows:(NSUInteger)m
                                                                       columns:(NSUInteger)k
                                                                      rowBytes:(NSUInteger)(k * sizeof(float))
                                                                      dataType:MPSDataTypeFloat32];

  MPSMatrix *a_mat = [[MPSMatrix alloc] initWithBuffer:a_buffer descriptor:a_desc];
  MPSMatrix *b_mat = [[MPSMatrix alloc] initWithBuffer:b_buffer descriptor:b_desc];
  MPSMatrix *c_mat = [[MPSMatrix alloc] initWithBuffer:c_buffer descriptor:c_desc];

  MPSMatrixMultiplication *mm = [[MPSMatrixMultiplication alloc] initWithDevice:g_metal_device
                                                                   transposeLeft:NO
                                                                  transposeRight:NO
                                                                      resultRows:(NSUInteger)m
                                                                   resultColumns:(NSUInteger)k
                                                                 interiorColumns:(NSUInteger)n
                                                                           alpha:1.0
                                                                            beta:0.0];

  id<MTLCommandBuffer> cmd = [g_metal_queue commandBuffer];
  if (cmd == nil) {
#if !__has_feature(objc_arc)
    [a_mat release];
    [b_mat release];
    [c_mat release];
    [mm release];
    [a_buffer release];
    [b_buffer release];
    [c_buffer release];
#endif
    return 0;
  }

  [mm encodeToCommandBuffer:cmd leftMatrix:a_mat rightMatrix:b_mat resultMatrix:c_mat];
  [cmd commit];
  [cmd waitUntilCompleted];

  if ([cmd status] != MTLCommandBufferStatusCompleted) {
#if !__has_feature(objc_arc)
    [a_mat release];
    [b_mat release];
    [c_mat release];
    [mm release];
    [a_buffer release];
    [b_buffer release];
    [c_buffer release];
#endif
    return 0;
  }

  memcpy(c, [c_buffer contents], (size_t)c_size);

#if !__has_feature(objc_arc)
  [a_mat release];
  [b_mat release];
  [c_mat release];
  [mm release];
  [a_buffer release];
  [b_buffer release];
  [c_buffer release];
#endif

  return 1;
#else
  (void)a;
  (void)b;
  (void)c;
  (void)m;
  (void)n;
  (void)k;
  return 0;
#endif
}

void matmul_f32(const float *a, const float *b, float *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      float sum = 0.0f;
      for (size_t p = 0; p < n; ++p) {
        sum += a[i * n + p] * b[p * k + j];
      }
      c[i * k + j] = sum;
    }
  }
}

void matmul_f64(const double *a, const double *b, double *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      double sum = 0.0;
      for (size_t p = 0; p < n; ++p) {
        sum += a[i * n + p] * b[p * k + j];
      }
      c[i * k + j] = sum;
    }
  }
}

void matmul_i64(const int64_t *a, const int64_t *b, int64_t *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      int64_t sum = 0;
      for (size_t p = 0; p < n; ++p) {
        sum += a[i * n + p] * b[p * k + j];
      }
      c[i * k + j] = sum;
    }
  }
}

void matmul_i32(const int32_t *a, const int32_t *b, int32_t *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      int64_t sum = 0;
      for (size_t p = 0; p < n; ++p) {
        sum += (int64_t)a[i * n + p] * (int64_t)b[p * k + j];
      }
      c[i * k + j] = (int32_t)sum;
    }
  }
}

void matmul_i16(const int16_t *a, const int16_t *b, int16_t *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      int64_t sum = 0;
      for (size_t p = 0; p < n; ++p) {
        sum += (int64_t)a[i * n + p] * (int64_t)b[p * k + j];
      }
      c[i * k + j] = (int16_t)sum;
    }
  }
}

void matmul_i8(const int8_t *a, const int8_t *b, int8_t *c, size_t m, size_t n, size_t k) {
  for (size_t i = 0; i < m; ++i) {
    for (size_t j = 0; j < k; ++j) {
      int64_t sum = 0;
      for (size_t p = 0; p < n; ++p) {
        sum += (int64_t)a[i * n + p] * (int64_t)b[p * k + j];
      }
      c[i * k + j] = (int8_t)sum;
    }
  }
}
