// Converted from C to Java by GitHub Copilot (GPT-4.1)
// Copyright (C) 2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).

import java.util.Random;

public class Matmul {
    public static void matmulF32(float[] a, float[] b, float[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                float sum = 0.0f;
                for (int p = 0; p < n; ++p) {
                    sum += a[i * n + p] * b[p * k + j];
                }
                c[i * k + j] = sum;
            }
        }
    }

    public static void matmulF64(double[] a, double[] b, double[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                double sum = 0.0;
                for (int p = 0; p < n; ++p) {
                    sum += a[i * n + p] * b[p * k + j];
                }
                c[i * k + j] = sum;
            }
        }
    }

    public static void matmulI64(long[] a, long[] b, long[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                long sum = 0;
                for (int p = 0; p < n; ++p) {
                    sum += a[i * n + p] * b[p * k + j];
                }
                c[i * k + j] = sum;
            }
        }
    }

    public static void matmulI32(int[] a, int[] b, int[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                long sum = 0;
                for (int p = 0; p < n; ++p) {
                    sum += (long)a[i * n + p] * (long)b[p * k + j];
                }
                c[i * k + j] = (int)sum;
            }
        }
    }

    public static void matmulI16(short[] a, short[] b, short[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                long sum = 0;
                for (int p = 0; p < n; ++p) {
                    sum += (long)a[i * n + p] * (long)b[p * k + j];
                }
                c[i * k + j] = (short)sum;
            }
        }
    }

    public static void matmulI8(byte[] a, byte[] b, byte[] c, int m, int n, int k) {
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < k; ++j) {
                long sum = 0;
                for (int p = 0; p < n; ++p) {
                    sum += (long)a[i * n + p] * (long)b[p * k + j];
                }
                c[i * k + j] = (byte)sum;
            }
        }
    }
}
