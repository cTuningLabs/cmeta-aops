/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.

Developed with the help of ChatGPT and Claude.
*/

#include <cuda_runtime.h>
#include <stdint.h>
#include <stddef.h>

#define BLOCK_SIZE 16

// CUDA kernel for float32 matrix multiplication
__global__ void matmul_f32_kernel(const float *a, const float *b, float *c, 
                                  size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    float sum = 0.0f;
    for (size_t p = 0; p < n; ++p) {
      sum += a[row * n + p] * b[p * k + col];
    }
    c[row * k + col] = sum;
  }
}

// CUDA kernel for float64 matrix multiplication
__global__ void matmul_f64_kernel(const double *a, const double *b, double *c, 
                                  size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    double sum = 0.0;
    for (size_t p = 0; p < n; ++p) {
      sum += a[row * n + p] * b[p * k + col];
    }
    c[row * k + col] = sum;
  }
}

// CUDA kernel for int64 matrix multiplication
__global__ void matmul_i64_kernel(const int64_t *a, const int64_t *b, int64_t *c, 
                                  size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    int64_t sum = 0;
    for (size_t p = 0; p < n; ++p) {
      sum += a[row * n + p] * b[p * k + col];
    }
    c[row * k + col] = sum;
  }
}

// CUDA kernel for int32 matrix multiplication
__global__ void matmul_i32_kernel(const int32_t *a, const int32_t *b, int32_t *c, 
                                  size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    int64_t sum = 0;
    for (size_t p = 0; p < n; ++p) {
      sum += (int64_t)a[row * n + p] * (int64_t)b[p * k + col];
    }
    c[row * k + col] = (int32_t)sum;
  }
}

// CUDA kernel for int16 matrix multiplication
__global__ void matmul_i16_kernel(const int16_t *a, const int16_t *b, int16_t *c, 
                                  size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    int64_t sum = 0;
    for (size_t p = 0; p < n; ++p) {
      sum += (int64_t)a[row * n + p] * (int64_t)b[p * k + col];
    }
    c[row * k + col] = (int16_t)sum;
  }
}

// CUDA kernel for int8 matrix multiplication
__global__ void matmul_i8_kernel(const int8_t *a, const int8_t *b, int8_t *c, 
                                 size_t m, size_t n, size_t k) {
  size_t row = blockIdx.y * blockDim.y + threadIdx.y;
  size_t col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < m && col < k) {
    int64_t sum = 0;
    for (size_t p = 0; p < n; ++p) {
      sum += (int64_t)a[row * n + p] * (int64_t)b[p * k + col];
    }
    c[row * k + col] = (int8_t)sum;
  }
}

// Host wrapper for float32 matrix multiplication
void matmul_f32(const float *a, const float *b, float *c, size_t m, size_t n, size_t k) {
  float *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(float);
  size_t b_bytes = n * k * sizeof(float);
  size_t c_bytes = m * k * sizeof(float);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_f32_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}

// Host wrapper for float64 matrix multiplication
void matmul_f64(const double *a, const double *b, double *c, size_t m, size_t n, size_t k) {
  double *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(double);
  size_t b_bytes = n * k * sizeof(double);
  size_t c_bytes = m * k * sizeof(double);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_f64_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}

// Host wrapper for int64 matrix multiplication
void matmul_i64(const int64_t *a, const int64_t *b, int64_t *c, size_t m, size_t n, size_t k) {
  int64_t *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(int64_t);
  size_t b_bytes = n * k * sizeof(int64_t);
  size_t c_bytes = m * k * sizeof(int64_t);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_i64_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}

// Host wrapper for int32 matrix multiplication
void matmul_i32(const int32_t *a, const int32_t *b, int32_t *c, size_t m, size_t n, size_t k) {
  int32_t *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(int32_t);
  size_t b_bytes = n * k * sizeof(int32_t);
  size_t c_bytes = m * k * sizeof(int32_t);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_i32_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}

// Host wrapper for int16 matrix multiplication
void matmul_i16(const int16_t *a, const int16_t *b, int16_t *c, size_t m, size_t n, size_t k) {
  int16_t *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(int16_t);
  size_t b_bytes = n * k * sizeof(int16_t);
  size_t c_bytes = m * k * sizeof(int16_t);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_i16_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}

// Host wrapper for int8 matrix multiplication
void matmul_i8(const int8_t *a, const int8_t *b, int8_t *c, size_t m, size_t n, size_t k) {
  int8_t *d_a, *d_b, *d_c;
  
  size_t a_bytes = m * n * sizeof(int8_t);
  size_t b_bytes = n * k * sizeof(int8_t);
  size_t c_bytes = m * k * sizeof(int8_t);
  
  cudaMalloc(&d_a, a_bytes);
  cudaMalloc(&d_b, b_bytes);
  cudaMalloc(&d_c, c_bytes);
  
  cudaMemcpy(d_a, a, a_bytes, cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b, b_bytes, cudaMemcpyHostToDevice);
  
  dim3 block_size(BLOCK_SIZE, BLOCK_SIZE);
  dim3 grid_size((k + BLOCK_SIZE - 1) / BLOCK_SIZE, (m + BLOCK_SIZE - 1) / BLOCK_SIZE);
  
  matmul_i8_kernel<<<grid_size, block_size>>>(d_a, d_b, d_c, m, n, k);
  
  cudaMemcpy(c, d_c, c_bytes, cudaMemcpyDeviceToHost);
  
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
}
