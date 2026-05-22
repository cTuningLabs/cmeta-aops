import ctypes
from typing import List


def _wrap_signed(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    value &= mask
    sign_bit = 1 << (bits - 1)
    if value & sign_bit:
        value -= (1 << bits)
    return value


def matmul_f32(a: List[float], b: List[float], c: List[float], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = ctypes.c_float(0.0)
            for p in range(n):
                prod = a[i * n + p] * b[p * k + j]
                sum_val = ctypes.c_float(sum_val.value + prod)
            c[i * k + j] = sum_val.value


def matmul_f64(a: List[float], b: List[float], c: List[float], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = 0.0
            for p in range(n):
                sum_val += a[i * n + p] * b[p * k + j]
            c[i * k + j] = sum_val


def matmul_i64(a: List[int], b: List[int], c: List[int], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = 0
            for p in range(n):
                sum_val = _wrap_signed(sum_val + (a[i * n + p] * b[p * k + j]), 64)
            c[i * k + j] = _wrap_signed(sum_val, 64)


def matmul_i32(a: List[int], b: List[int], c: List[int], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = 0
            for p in range(n):
                sum_val += int(a[i * n + p]) * int(b[p * k + j])
            c[i * k + j] = _wrap_signed(sum_val, 32)


def matmul_i16(a: List[int], b: List[int], c: List[int], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = 0
            for p in range(n):
                sum_val += int(a[i * n + p]) * int(b[p * k + j])
            c[i * k + j] = _wrap_signed(sum_val, 16)


def matmul_i8(a: List[int], b: List[int], c: List[int], m: int, n: int, k: int) -> None:
    for i in range(m):
        for j in range(k):
            sum_val = 0
            for p in range(n):
                sum_val += int(a[i * n + p]) * int(b[p * k + j])
            c[i * k + j] = _wrap_signed(sum_val, 8)
