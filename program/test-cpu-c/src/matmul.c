/*
Converted from C++ to plain C by GitHub Copilot (GPT-4.1)
Copyright (C) 2026 Grigori Fursin and cTuning Labs. All rights reserved.
*/

#include <stdint.h>
#include <stddef.h>

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
