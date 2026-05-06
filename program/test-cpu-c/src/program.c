#include <ctype.h>
#include <float.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef enum {
  DTYPE_FLOAT32 = 0,
  DTYPE_FLOAT64 = 1
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

static double random_0_1(void) {
  return (double)rand() / (double)RAND_MAX;
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

static void matmul_f32(const float *a, const float *b, float *c, size_t m, size_t n, size_t k) {
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

static void matmul_f64(const double *a, const double *b, double *c, size_t m, size_t n, size_t k) {
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

static void print_usage(const char *prog) {
  printf("Usage:\n");
  printf("  %s [dtype] M N K [repeat] [clean]\n", prog);
  printf("\n");
  printf("Arguments:\n");
  printf("  dtype  : float32 (default) or float64\n");
  printf("  M,N,K  : positive integers for (M x N) * (N x K)\n");
  printf("  repeat : positive integer, default 1\n");
  printf("  clean  : 0/1 (or false/true), default 0\n");
}

static int write_stats_json(const char *dtype,
                            size_t m,
                            size_t n,
                            size_t k,
                            size_t repeat,
                            int clean,
                            double min_with,
                            double max_with,
                            const double *all_with,
                            double min_without,
                            double max_without,
                            const double *all_without) {
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
  fprintf(json, "    \"clean\": %d\n", clean);
  fprintf(json, "  },\n");
  fprintf(json, "  \"timing\": {\n");

  fprintf(json, "    \"with_data\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_with);
  fprintf(json, "      \"max\": %.12f,\n", max_with);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_with[i]);
  }
  fprintf(json, "]\n");
  fprintf(json, "    },\n");

  fprintf(json, "    \"without_data\": {\n");
  fprintf(json, "      \"min\": %.12f,\n", min_without);
  fprintf(json, "      \"max\": %.12f,\n", max_without);
  fprintf(json, "      \"all\": [");
  for (size_t i = 0; i < repeat; ++i) {
    fprintf(json, "%s%.12f", (i == 0) ? "" : ", ", all_without[i]);
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
  int argi = 1;

  if (argc < 4) {
    print_usage(argv[0]);
    return 1;
  }

  if (argi < argc && !is_integer_string(argv[argi])) {
    if (strcmp(argv[argi], "float32") == 0 || strcmp(argv[argi], "f32") == 0) {
      dtype = DTYPE_FLOAT32;
      dtype_name = "float32";
    } else if (strcmp(argv[argi], "float64") == 0 || strcmp(argv[argi], "f64") == 0 || strcmp(argv[argi], "double") == 0) {
      dtype = DTYPE_FLOAT64;
      dtype_name = "float64";
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

  if (argi != argc) {
    fprintf(stderr, "Error: too many arguments.\n");
    print_usage(argv[0]);
    return 1;
  }

  const size_t a_count = m * n;
  const size_t b_count = n * k;
  const size_t c_count = m * k;

  double *times_with_data = (double *)malloc(repeat * sizeof(double));
  double *times_without_data = (double *)malloc(repeat * sizeof(double));
  if (times_with_data == NULL || times_without_data == NULL) {
    fprintf(stderr, "Error: unable to allocate timing arrays.\n");
    free(times_with_data);
    free(times_without_data);
    return 1;
  }

  double min_with_data = DBL_MAX;
  double max_with_data = 0.0;
  double min_without_data = DBL_MAX;
  double max_without_data = 0.0;

  srand((unsigned int)time(NULL));

  if (dtype == DTYPE_FLOAT32) {
    float *a = (float *)malloc(a_count * sizeof(float));
    float *b = (float *)malloc(b_count * sizeof(float));
    float *c = (float *)malloc(c_count * sizeof(float));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate float32 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_with_data);
      free(times_without_data);
      return 1;
    }

    fill_random_f32(a, a_count);
    fill_random_f32(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double t0 = now_seconds();
      if (clean) {
        fill_random_f32(a, a_count);
        fill_random_f32(b, b_count);
      }
      matmul_f32(a, b, c, m, n, k);
      double with_dt = now_seconds() - t0;
      times_with_data[r] = with_dt;
      if (with_dt < min_with_data) {
        min_with_data = with_dt;
      }
      if (with_dt > max_with_data) {
        max_with_data = with_dt;
      }

      if (clean) {
        fill_random_f32(a, a_count);
        fill_random_f32(b, b_count);
      }
      t0 = now_seconds();
      matmul_f32(a, b, c, m, n, k);
      double without_dt = now_seconds() - t0;
      times_without_data[r] = without_dt;
      if (without_dt < min_without_data) {
        min_without_data = without_dt;
      }
      if (without_dt > max_without_data) {
        max_without_data = without_dt;
      }
    }

    free(a);
    free(b);
    free(c);
  } else {
    double *a = (double *)malloc(a_count * sizeof(double));
    double *b = (double *)malloc(b_count * sizeof(double));
    double *c = (double *)malloc(c_count * sizeof(double));

    if (a == NULL || b == NULL || c == NULL) {
      fprintf(stderr, "Error: unable to allocate float64 matrices.\n");
      free(a);
      free(b);
      free(c);
      free(times_with_data);
      free(times_without_data);
      return 1;
    }

    fill_random_f64(a, a_count);
    fill_random_f64(b, b_count);

    for (size_t r = 0; r < repeat; ++r) {
      double t0 = now_seconds();
      if (clean) {
        fill_random_f64(a, a_count);
        fill_random_f64(b, b_count);
      }
      matmul_f64(a, b, c, m, n, k);
      double with_dt = now_seconds() - t0;
      times_with_data[r] = with_dt;
      if (with_dt < min_with_data) {
        min_with_data = with_dt;
      }
      if (with_dt > max_with_data) {
        max_with_data = with_dt;
      }

      if (clean) {
        fill_random_f64(a, a_count);
        fill_random_f64(b, b_count);
      }
      t0 = now_seconds();
      matmul_f64(a, b, c, m, n, k);
      double without_dt = now_seconds() - t0;
      times_without_data[r] = without_dt;
      if (without_dt < min_without_data) {
        min_without_data = without_dt;
      }
      if (without_dt > max_without_data) {
        max_without_data = without_dt;
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
  printf("\nTiming (seconds):\n");
  printf("  with_data    min = %.9f, max = %.9f\n", min_with_data, max_with_data);
  printf("  without_data min = %.9f, max = %.9f\n", min_without_data, max_without_data);

  if (!write_stats_json(dtype_name,
                        m,
                        n,
                        k,
                        repeat,
                        clean,
                        min_with_data,
                        max_with_data,
                        times_with_data,
                        min_without_data,
                        max_without_data,
                        times_without_data)) {
    fprintf(stderr, "Warning: could not write tmp-cmeta-program-stats.json\n");
  } else {
    printf("Wrote tmp-cmeta-program-stats.json\n");
  }

  free(times_with_data);
  free(times_without_data);
  return 0;
}
