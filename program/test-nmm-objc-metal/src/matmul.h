/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Developed with the help of ChatGPT and Claude.
*/

#ifndef MATMUL_H
#define MATMUL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int matmul_init_metal(void);
void matmul_shutdown_metal(void);

int matmul_f32_metal(const float *a, const float *b, float *c, size_t m, size_t n, size_t k);

void matmul_f32(const float *a, const float *b, float *c, size_t m, size_t n, size_t k);
void matmul_f64(const double *a, const double *b, double *c, size_t m, size_t n, size_t k);
void matmul_i64(const int64_t *a, const int64_t *b, int64_t *c, size_t m, size_t n, size_t k);
void matmul_i32(const int32_t *a, const int32_t *b, int32_t *c, size_t m, size_t n, size_t k);
void matmul_i16(const int16_t *a, const int16_t *b, int16_t *c, size_t m, size_t n, size_t k);
void matmul_i8(const int8_t *a, const int8_t *b, int8_t *c, size_t m, size_t n, size_t k);

#ifdef __cplusplus
}
#endif

#endif
