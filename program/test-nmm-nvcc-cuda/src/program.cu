/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.

Developed with the help of ChatGPT and Claude.
*/

#include <ctype.h>
#include <float.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <omp.h>

#include <openssl/opensslv.h>
#include <openssl/crypto.h>
#include <openssl/sha.h>

#include <math.h>

#ifdef XOPENME
#include <xopenme.h>
#endif

#include "matmul.h"

typedef enum {
  DTYPE_FLOAT32 = 0,
  DTYPE_FLOAT64 = 1,
  DTYPE_INT64 = 2,
  DTYPE_INT32 = 3,
  DTYPE_INT16 = 4,
  DTYPE_INT8 = 5
} DType;

static double now_seconds(void) {
  return (double)clock() / (double)CLOCKS_PER_SEC;
}

static int is_integer_string(const char *s) {
  if (s == NULL || *s == '\0') {
    return 0;
  }
  for (size_t i = 0; s[i] != '\0'; ++i) {
    if (!isdigit((unsigned char)s[i])) {
      return 0;
    }
  }
  return 1;
}

static int parse_positive_size(const char *s, size_t *out) {
  char *end_ptr = NULL;
  unsigned long long value = strtoull(s, &end_ptr, 10);
  if (s == end_ptr || *end_ptr != '\0' || value == 0ULL) {
    return 0;
  }
  *out = (size_t)value;
  return 1;
}

static int parse_clean(const char *s, int *out) {
  if (strcmp(s, "0") == 0 || strcmp(s, "false") == 0 || strcmp(s, "no") == 0) {
    *out = 0;
    return 1;
  }
  if (strcmp(s, "1") == 0 || strcmp(s, "true") == 0 || strcmp(s, "yes") == 0) {
    *out = 1;
    return 1;
  }
  return 0;
}

static int parse_seed(const char *s, unsigned int *out) {
  char *end_ptr = NULL;
  unsigned long value = strtoul(s, &end_ptr, 10);
  if (s == end_ptr || *end_ptr != '\0') {
    return 0;
  }
  *out = (unsigned int)value;
  return 1;
}

static double random_0_1(void) {
  return (double)rand() / (double)RAND_MAX;
}

static int random_int_inclusive(int min_val, int max_val) {
  int span = max_val - min_val + 1;
  return min_val + (rand() % span);
}

static void fill_random_f32(float *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = (float)random_0_1();
  }
}

static void fill_random_f64(double *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = random_0_1();
  }
}

static void fill_random_i64(int64_t *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = (int64_t)random_int_inclusive(0, 15);
  }
}

static void fill_random_i32(int32_t *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = (int32_t)random_int_inclusive(0, 15);
  }
}

static void fill_random_i16(int16_t *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = (int16_t)random_int_inclusive(0, 15);
  }
}

static void fill_random_i8(int8_t *mat, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    mat[i] = (int8_t)random_int_inclusive(0, 15);
  }
}

static double sum_matrix_f32(const float *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += (double)mat[i];
  }
  return sum;
}

static double sum_matrix_f64(const double *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += mat[i];
  }
  return sum;
}

static double sum_matrix_i64(const int64_t *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += (double)mat[i];
  }
  return sum;
}

static double sum_matrix_i32(const int32_t *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += (double)mat[i];
  }
  return sum;
}

static double sum_matrix_i16(const int16_t *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += (double)mat[i];
  }
  return sum;
}

static double sum_matrix_i8(const int8_t *mat, size_t count) {
  double sum = 0.0;
  for (size_t i = 0; i < count; ++i) {
    sum += (double)mat[i];
  }
  return sum;
}

static void print_usage(const char *prog) {
  printf("Usage:\n");
  printf("  %s [dtype] M N K [repeat] [clean] [seed]\n", prog);
  printf("\n");
  printf("Arguments:\n");
  printf("  dtype  : float32 (default), float64, int64, int32, int16, int8\n");
  printf("  M,N,K  : positive integers for (M x N) * (N x K)\n");
  printf("  repeat : positive integer, default 1\n");
  printf("  clean  : 0/1 (or false/true), default 0\n");
  printf("  seed   : non-negative integer for RNG, default time(NULL)\n");
}

static int write_stats_json(const char *dtype,
                            size_t m,
                            size_t n,
                            size_t k,
                            size_t repeat,
                            int clean,
                            unsigned int seed,
                            double min_matmul,
                            double max_matmul,
                            const double *all_matmul,
                            double min_data_prep,
                            double max_data_prep,
                            const double *all_data_prep,
                            double min_sum,
                            double max_sum,
                            const double *all_sum,
                            double min_total,
                            double max_total,
                            const double *all_total,
                            double aggregated_value) {
  FILE *json = fopen("tmp-cmeta-program-stats.json", "w");
  if (json == NULL) {
    return 0;
  }

  fprintf(json, "{\n");
  fprintf(json, "  \"input\": {\n");
  fprintf(json, "    \"dtype\": \"%s\",\n", dtype);
  fprintf(json, "    \"M\": %zu,\n", m);
  fprintf(json, "    \"N\": %zu,\n", n);
  fprintf(json, "    \"K\": %zu,\n", k);
  fprintf(json, "    \"repeat\": %zu,\n", repeat);
  fprintf(json, "    \"clean\": %d,\n", clean);
  fprintf(json, "    \"seed\": %u\n", seed);
  fprintf(json, "  },\n");
  fprintf(json, "  \"aggregated_value\": %.12f,\n", aggregated_value);
  fprintf(json, "  \"timing\": {\n");

  fprintf(json, "    \"matmul_time\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_matmul);
  fprintf(json, "      \"max\": %.12f,\n", max_matmul);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_matmul[i]);
  }
  fprintf(json, "]\n");
  fprintf(json, "    },\n");

  fprintf(json, "    \"data_prep\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_data_prep);
  fprintf(json, "      \"max\": %.12f,\n", max_data_prep);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_data_prep[i]);
  }
  fprintf(json, "]\n");
  fprintf(json, "    },\n");

  fprintf(json, "    \"sum\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_sum);
  fprintf(json, "      \"max\": %.12f,\n", max_sum);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_sum[i]);
  }
  fprintf(json, "]\n");
  fprintf(json, "    },\n");

  fprintf(json, "    \"total\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_total);
  fprintf(json, "      \"max\": %.12f,\n", max_total);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_total[i]);
  }
  fprintf(json, "]\n");
  fprintf(json, "    }\n");

  fprintf(json, "  }\n");
  fprintf(json, "}\n");
  fclose(json);
  return 1;
}

int main(int argc, char *argv[]) {

  DType dtype = DTYPE_FLOAT32;
  const char *dtype_name = "float32";
  size_t m = 0;
  size_t n = 0;
  size_t k = 0;
  size_t repeat = 1;
  int clean = 0;
  unsigned int seed = (unsigned int)time(NULL);
  int argi = 1;

#ifdef XOPENME
  /******************************************************/
  printf("==================================================================\n");
  printf("Testing xOpenME ...\n");
  printf("\n");

  xopenme_init(2,0);
#endif

  /******************************************************/
  printf("==================================================================\n");
  printf("Testing OpenMP (CPU threads) ...\n");
  printf("\n");

  printf("_OPENMP = %d\n", _OPENMP);
  printf("max threads = %d\n", omp_get_max_threads());

  #pragma omp parallel num_threads(omp_get_max_threads())
  {
      printf("hello from thread %d of %d\n",
             omp_get_thread_num(), omp_get_num_threads());
  }

  printf("\n");

  /******************************************************/
  printf("==================================================================\n");
  printf("Testing crypto (OpenSSL SHA256) ...\n");
  printf("\n");

  /* 1. Print OpenSSL version */
  printf("OpenSSL version: %s\n",
         OpenSSL_version(OPENSSL_VERSION));

  /* 2. Compute SHA-256 of "hello world" */
  const char *msg = "hello world";
  unsigned char hash[SHA256_DIGEST_LENGTH];

  SHA256((const unsigned char *)msg,
         strlen(msg),
         hash);

  printf("SHA256(\"hello world\") = ");

  for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
      printf("%02x", hash[i]);
  }

  printf("\n");


  /******************************************************/
  printf("==================================================================\n");
  printf("Testing basic math ...\n");
  printf("\n");

  double x = 16.0;

  printf("sqrt(%.2f) = %.2f\n", x, sqrt(x));
  printf("sin(0.0) = %.2f\n", sin(0.0));
  printf("pow(2.0, 3.0) = %.2f\n", pow(2.0, 3.0));

  printf("\n");


  /******************************************************/
  if (argc < 4) {
    print_usage(argv[0]);
    return 1;
  }

  printf("==================================================================\n");
  printf("Testing CUDA matrix multiplication (GPU-accelerated) ...\n");
  printf("\n");

  if (argi < argc && !is_integer_string(argv[argi])) {
    if (strcmp(argv[argi], "float32") == 0 || strcmp(argv[argi], "f32") == 0) {
      dtype = DTYPE_FLOAT32;
      dtype_name = "float32";
    } else if (strcmp(argv[argi], "float64") == 0 || strcmp(argv[argi], "f64") == 0 || strcmp(argv[argi], "double") == 0) {
      dtype = DTYPE_FLOAT64;
      dtype_name = "float64";
    } else if (strcmp(argv[argi], "int64") == 0 || strcmp(argv[argi], "i64") == 0) {
      dtype = DTYPE_INT64;
      dtype_name = "int64";
    } else if (strcmp(argv[argi], "int32") == 0 || strcmp(argv[argi], "i32") == 0) {
      dtype = DTYPE_INT32;
      dtype_name = "int32";
    } else if (strcmp(argv[argi], "int16") == 0 || strcmp(argv[argi], "i16") == 0) {
      dtype = DTYPE_INT16;
      dtype_name = "int16";
    } else if (strcmp(argv[argi], "int8") == 0 || strcmp(argv[argi], "i8") == 0) {
      dtype = DTYPE_INT8;
      dtype_name = "int8";
    } else {
      fprintf(stderr, "Error: unsupported dtype '%s'.\n", argv[argi]);
      print_usage(argv[0]);
      return 1;
    }
    ++argi;
  }

  if (argc - argi < 3) {
    fprintf(stderr, "Error: M N K are required.\n");
    print_usage(argv[0]);
    return 1;
  }

  if (!parse_positive_size(argv[argi++], &m) ||
      !parse_positive_size(argv[argi++], &n) ||
      !parse_positive_size(argv[argi++], &k)) {
    fprintf(stderr, "Error: M N K must be positive integers.\n");
    return 1;
  }

  if (argi < argc) {
    if (!parse_positive_size(argv[argi++], &repeat)) {
      fprintf(stderr, "Error: repeat must be a positive integer.\n");
      return 1;
    }
  }

  if (argi < argc) {
    if (!parse_clean(argv[argi++], &clean)) {
      fprintf(stderr, "Error: clean must be one of 0/1/false/true/no/yes.\n");
      return 1;
    }
  }

  if (argi < argc) {
    if (!parse_seed(argv[argi++], &seed)) {
      fprintf(stderr, "Error: seed must be a non-negative integer.\n");
      return 1;
    }
  }

  if (argi != argc) {
    fprintf(stderr, "Error: too many arguments.\n");
    print_usage(argv[0]);
    return 1;
  }

  const size_t a_count = m * n;
  const size_t b_count = n * k;
  const size_t c_count = m * k;

  double *times_matmul = (double *)malloc(repeat * sizeof(double));
  double *times_data_prep = (double *)malloc(repeat * sizeof(double));
  double *times_sum = (double *)malloc(repeat * sizeof(double));
  double *times_total = (double *)malloc(repeat * sizeof(double));
  if (times_matmul == NULL || times_data_prep == NULL || times_sum == NULL || times_total == NULL) {
    fprintf(stderr, "Error: unable to allocate timing arrays.\n");
    free(times_matmul);
    free(times_data_prep);
    free(times_sum);
    free(times_total);
    return 1;
  }

  double min_matmul_time = DBL_MAX;
  double max_matmul_time = 0.0;
  double min_data_prep_time = DBL_MAX;
  double max_data_prep_time = 0.0;
  double min_sum_time = DBL_MAX;
  double max_sum_time = 0.0;
  double min_total_time = DBL_MAX;
  double max_total_time = 0.0;
  double aggregated_value = 0.0;

  srand(seed);

#ifdef XOPENME
  xopenme_clock_start(0);
#endif

  if (dtype == DTYPE_FLOAT32) {
    float *a = (float *)malloc(a_count * sizeof(float));
    float *b = (float *)malloc(b_count * sizeof(float));
    float *c = (float *)malloc(c_count * sizeof(float));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate float32 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_f32(a, a_count);
    fill_random_f32(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_f32(a, a_count);
        fill_random_f32(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_f32(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_f32(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else if (dtype == DTYPE_FLOAT64) {
    double *a = (double *)malloc(a_count * sizeof(double));
    double *b = (double *)malloc(b_count * sizeof(double));
    double *c = (double *)malloc(c_count * sizeof(double));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate float64 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_f64(a, a_count);
    fill_random_f64(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_f64(a, a_count);
        fill_random_f64(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_f64(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_f64(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else if (dtype == DTYPE_INT64) {
    int64_t *a = (int64_t *)malloc(a_count * sizeof(int64_t));
    int64_t *b = (int64_t *)malloc(b_count * sizeof(int64_t));
    int64_t *c = (int64_t *)malloc(c_count * sizeof(int64_t));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate int64 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_i64(a, a_count);
    fill_random_i64(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_i64(a, a_count);
        fill_random_i64(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_i64(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_i64(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else if (dtype == DTYPE_INT32) {
    int32_t *a = (int32_t *)malloc(a_count * sizeof(int32_t));
    int32_t *b = (int32_t *)malloc(b_count * sizeof(int32_t));
    int32_t *c = (int32_t *)malloc(c_count * sizeof(int32_t));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate int32 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_i32(a, a_count);
    fill_random_i32(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_i32(a, a_count);
        fill_random_i32(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_i32(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_i32(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else if (dtype == DTYPE_INT16) {
    int16_t *a = (int16_t *)malloc(a_count * sizeof(int16_t));
    int16_t *b = (int16_t *)malloc(b_count * sizeof(int16_t));
    int16_t *c = (int16_t *)malloc(c_count * sizeof(int16_t));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate int16 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_i16(a, a_count);
    fill_random_i16(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_i16(a, a_count);
        fill_random_i16(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_i16(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_i16(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else {
    int8_t *a = (int8_t *)malloc(a_count * sizeof(int8_t));
    int8_t *b = (int8_t *)malloc(b_count * sizeof(int8_t));
    int8_t *c = (int8_t *)malloc(c_count * sizeof(int8_t));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate int8 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_matmul);
      free(times_data_prep);
      free(times_sum);
      free(times_total);
      return 1;
    }

    fill_random_i8(a, a_count);
    fill_random_i8(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double total_t0 = now_seconds();
      double data_prep_dt = 0.0;
      if (clean) {
        double prep_t0 = now_seconds();
        fill_random_i8(a, a_count);
        fill_random_i8(b, b_count);
        data_prep_dt = now_seconds() - prep_t0;
      }

      double t0 = now_seconds();
      matmul_i8(a, b, c, m, n, k);
      double matmul_dt = now_seconds() - t0;

      t0 = now_seconds();
      aggregated_value += sum_matrix_i8(c, c_count);
      double sum_dt = now_seconds() - t0;

      double total_dt = now_seconds() - total_t0;

      times_data_prep[r] = data_prep_dt;
      times_matmul[r] = matmul_dt;
      times_sum[r] = sum_dt;
      times_total[r] = total_dt;

      if (data_prep_dt < min_data_prep_time) {
        min_data_prep_time = data_prep_dt;
      }
      if (data_prep_dt > max_data_prep_time) {
        max_data_prep_time = data_prep_dt;
      }
      if (matmul_dt < min_matmul_time) {
        min_matmul_time = matmul_dt;
      }
      if (matmul_dt > max_matmul_time) {
        max_matmul_time = matmul_dt;
      }
      if (sum_dt < min_sum_time) {
        min_sum_time = sum_dt;
      }
      if (sum_dt > max_sum_time) {
        max_sum_time = sum_dt;
      }
      if (total_dt < min_total_time) {
        min_total_time = total_dt;
      }
      if (total_dt > max_total_time) {
        max_total_time = total_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  }

  printf("Input:\n");
  printf("  dtype  = %s\n", dtype_name);
  printf("  M N K  = %zu %zu %zu\n", m, n, k);
  printf("  repeat = %zu\n", repeat);
  printf("  clean  = %d\n", clean);
  printf("  seed   = %u\n", seed);
  printf("  aggregated_value = %.12f\n", aggregated_value);
  printf("\nTiming (seconds):\n");
  printf("  matmul_time min = %.9f, max = %.9f\n", min_matmul_time, max_matmul_time);
  printf("  data_prep   min = %.9f, max = %.9f\n", min_data_prep_time, max_data_prep_time);
  printf("  sum         min = %.9f, max = %.9f\n", min_sum_time, max_sum_time);
  printf("  total       min = %.9f, max = %.9f\n", min_total_time, max_total_time);
  printf("\n");

  printf("==================================================================\n");
  printf("Writing stats for cMeta ...\n");
  printf("\n");

  if (!write_stats_json(dtype_name,
                        m,
                        n,
                        k,
                        repeat,
                        clean,
                        seed,
                        min_matmul_time,
                        max_matmul_time,
                        times_matmul,
                        min_data_prep_time,
                        max_data_prep_time,
                        times_data_prep,
                        min_sum_time,
                        max_sum_time,
                        times_sum,
                        min_total_time,
                        max_total_time,
                        times_total,
                        aggregated_value)) {
    fprintf(stderr, "Warning: could not write tmp-cmeta-program-stats.json\n");
  } else {
    printf("Wrote tmp-cmeta-program-stats.json\n");
  }

#ifdef XOPENME
  xopenme_clock_end(0);
  xopenme_dump_state();
  xopenme_finish();
#endif

  free(times_matmul);
  free(times_data_prep);
  free(times_sum);
  free(times_total);

  return 0;
}
