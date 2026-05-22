/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.

Developed with the help of ChatGPT and Claude.
*/

#ifndef MATMUL_H
#define MATMUL_H

#include <stdint.h>
#include <stddef.h>

void matmul_f32(const float *a, const float *b, float *c, size_t m, size_t n, size_t k);
void matmul_f64(const double *a, const double *b, double *c, size_t m, size_t n, size_t k);
void matmul_i64(const int64_t *a, const int64_t *b, int64_t *c, size_t m, size_t n, size_t k);
void matmul_i32(const int32_t *a, const int32_t *b, int32_t *c, size_t m, size_t n, size_t k);
void matmul_i16(const int16_t *a, const int16_t *b, int16_t *c, size_t m, size_t n, size_t k);
void matmul_i8(const int8_t *a, const int8_t *b, int8_t *c, size_t m, size_t n, size_t k);

#endif
