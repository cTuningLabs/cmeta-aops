import hashlib
import math
import os
import random
import ssl
import sys
import time
from typing import Any, Callable, List, Optional

from matmul import matmul_f32, matmul_f64, matmul_i64, matmul_i32, matmul_i16, matmul_i8

DTYPE_FLOAT32 = 0
DTYPE_FLOAT64 = 1
DTYPE_INT64 = 2
DTYPE_INT32 = 3
DTYPE_INT16 = 4
DTYPE_INT8 = 5


def now_seconds() -> float:
    return time.process_time()


def is_integer_string(s: Optional[str]) -> bool:
    if not s:
        return False
    return s.isdigit()


def parse_positive_size(s: str) -> Optional[int]:
    if not s or not s.isdigit():
        return None
    value = int(s)
    if value <= 0:
        return None
    return value


def parse_clean(s: str) -> Optional[int]:
    if s in ("0", "false", "no"):
        return 0
    if s in ("1", "true", "yes"):
        return 1
    return None


def parse_seed(s: str) -> Optional[int]:
    if not s:
        return None
    try:
        value = int(s, 10)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def random_0_1() -> float:
    return random.random()


def random_int_inclusive(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)


def fill_random_f32(mat: List[float], count: int) -> None:
    for i in range(count):
        mat[i] = float(random_0_1())


def fill_random_f64(mat: List[float], count: int) -> None:
    for i in range(count):
        mat[i] = random_0_1()


def fill_random_i64(mat: List[int], count: int) -> None:
    for i in range(count):
        mat[i] = int(random_int_inclusive(0, 15))


def fill_random_i32(mat: List[int], count: int) -> None:
    for i in range(count):
        mat[i] = int(random_int_inclusive(0, 15))


def fill_random_i16(mat: List[int], count: int) -> None:
    for i in range(count):
        mat[i] = int(random_int_inclusive(0, 15))


def fill_random_i8(mat: List[int], count: int) -> None:
    for i in range(count):
        mat[i] = int(random_int_inclusive(0, 15))


def sum_matrix_f32(mat: List[float], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += float(mat[i])
    return total


def sum_matrix_f64(mat: List[float], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += mat[i]
    return total


def sum_matrix_i64(mat: List[int], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += float(mat[i])
    return total


def sum_matrix_i32(mat: List[int], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += float(mat[i])
    return total


def sum_matrix_i16(mat: List[int], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += float(mat[i])
    return total


def sum_matrix_i8(mat: List[int], count: int) -> float:
    total = 0.0
    for i in range(count):
        total += float(mat[i])
    return total


def print_usage(prog: str) -> None:
    print("Usage:")
    print(f"  {prog} [dtype] M N K [repeat] [clean] [seed]")
    print()
    print("Arguments:")
    print("  dtype  : float32 (default), float64, int64, int32, int16, int8")
    print("  M,N,K  : positive integers for (M x N) * (N x K)")
    print("  repeat : positive integer, default 1")
    print("  clean  : 0/1 (or false/true), default 0")
    print("  seed   : non-negative integer for RNG, default time(NULL)")


def write_stats_json(
    dtype: str,
    m: int,
    n: int,
    k: int,
    repeat: int,
    clean: int,
    seed: int,
    min_matmul: float,
    max_matmul: float,
    all_matmul: List[float],
    min_data_prep: float,
    max_data_prep: float,
    all_data_prep: List[float],
    min_sum: float,
    max_sum: float,
    all_sum: List[float],
    min_total: float,
    max_total: float,
    all_total: List[float],
    aggregated_value: float,
) -> bool:
    try:
        with open("tmp-cmeta-program-stats.json", "w", encoding="utf-8") as json_file:
            json_file.write("{\n")
            json_file.write("  \"input\": {\n")
            json_file.write(f"    \"dtype\": \"{dtype}\",\n")
            json_file.write(f"    \"M\": {m},\n")
            json_file.write(f"    \"N\": {n},\n")
            json_file.write(f"    \"K\": {k},\n")
            json_file.write(f"    \"repeat\": {repeat},\n")
            json_file.write(f"    \"clean\": {clean},\n")
            json_file.write(f"    \"seed\": {seed}\n")
            json_file.write("  },\n")
            json_file.write(f"  \"aggregated_value\": {aggregated_value:.12f},\n")
            json_file.write("  \"timing\": {\n")

            json_file.write("    \"matmul_time\": {\n")
            json_file.write(f"      \"min\": {min_matmul:.12f},\n")
            json_file.write(f"      \"max\": {max_matmul:.12f},\n")
            json_file.write("      \"all\": [")
            json_file.write(", ".join(f"{v:.12f}" for v in all_matmul))
            json_file.write("]\n")
            json_file.write("    },\n")

            json_file.write("    \"data_prep\": {\n")
            json_file.write(f"      \"min\": {min_data_prep:.12f},\n")
            json_file.write(f"      \"max\": {max_data_prep:.12f},\n")
            json_file.write("      \"all\": [")
            json_file.write(", ".join(f"{v:.12f}" for v in all_data_prep))
            json_file.write("]\n")
            json_file.write("    },\n")

            json_file.write("    \"sum\": {\n")
            json_file.write(f"      \"min\": {min_sum:.12f},\n")
            json_file.write(f"      \"max\": {max_sum:.12f},\n")
            json_file.write("      \"all\": [")
            json_file.write(", ".join(f"{v:.12f}" for v in all_sum))
            json_file.write("]\n")
            json_file.write("    },\n")

            json_file.write("    \"total\": {\n")
            json_file.write(f"      \"min\": {min_total:.12f},\n")
            json_file.write(f"      \"max\": {max_total:.12f},\n")
            json_file.write("      \"all\": [")
            json_file.write(", ".join(f"{v:.12f}" for v in all_total))
            json_file.write("]\n")
            json_file.write("    }\n")

            json_file.write("  }\n")
            json_file.write("}\n")
    except OSError:
        return False

    return True


def main(argv: List[str]) -> int:
    dtype = DTYPE_FLOAT32
    dtype_name = "float32"
    m = 0
    n = 0
    k = 0
    repeat = 1
    clean = 0
    seed = int(time.time())
    argi = 1

    print("==================================================================")
    print("Testing OpenMP ...")
    print()

    max_threads = os.cpu_count() or 1
    print("_OPENMP = 0")
    print(f"max threads = {max_threads}")

    for i in range(max_threads):
        print(f"hello from thread {i} of {max_threads}")

    print()

    print("==================================================================")
    print("Testing OpenSSL ...")
    print()

    print(f"OpenSSL version: {ssl.OPENSSL_VERSION}")

    msg = b"hello world"
    digest = hashlib.sha256(msg).hexdigest()
    print("SHA256(\"hello world\") = " + digest)
    print()

    print("==================================================================")
    print("Testing basic math ...")
    print()

    x = 16.0
    print(f"sqrt({x:.2f}) = {math.sqrt(x):.2f}")
    print(f"sin(0.0) = {math.sin(0.0):.2f}")
    print(f"pow(2.0, 3.0) = {math.pow(2.0, 3.0):.2f}")
    print()

    if len(argv) < 4:
        print_usage(argv[0])
        return 1

    print("==================================================================")
    print("Testing naive matmul ...")
    print()

    dtype_aliases = {
        "float32": (DTYPE_FLOAT32, "float32"),
        "f32": (DTYPE_FLOAT32, "float32"),
        "float64": (DTYPE_FLOAT64, "float64"),
        "f64": (DTYPE_FLOAT64, "float64"),
        "double": (DTYPE_FLOAT64, "float64"),
        "int64": (DTYPE_INT64, "int64"),
        "i64": (DTYPE_INT64, "int64"),
        "int32": (DTYPE_INT32, "int32"),
        "i32": (DTYPE_INT32, "int32"),
        "int16": (DTYPE_INT16, "int16"),
        "i16": (DTYPE_INT16, "int16"),
        "int8": (DTYPE_INT8, "int8"),
        "i8": (DTYPE_INT8, "int8"),
    }

    if argi < len(argv) and not is_integer_string(argv[argi]):
        token = argv[argi]
        dtype_info = dtype_aliases.get(token)
        if dtype_info is None:
            print(f"Error: unsupported dtype '{token}'.", file=sys.stderr)
            print_usage(argv[0])
            return 1
        dtype, dtype_name = dtype_info
        argi += 1

    if len(argv) - argi < 3:
        print("Error: M N K are required.", file=sys.stderr)
        print_usage(argv[0])
        return 1

    parsed_m = parse_positive_size(argv[argi])
    parsed_n = parse_positive_size(argv[argi + 1])
    parsed_k = parse_positive_size(argv[argi + 2])
    if parsed_m is None or parsed_n is None or parsed_k is None:
        print("Error: M N K must be positive integers.", file=sys.stderr)
        return 1

    m = parsed_m
    n = parsed_n
    k = parsed_k
    argi += 3

    if argi < len(argv):
        parsed_repeat = parse_positive_size(argv[argi])
        if parsed_repeat is None:
            print("Error: repeat must be a positive integer.", file=sys.stderr)
            return 1
        repeat = parsed_repeat
        argi += 1

    if argi < len(argv):
        parsed_clean = parse_clean(argv[argi])
        if parsed_clean is None:
            print("Error: clean must be one of 0/1/false/true/no/yes.", file=sys.stderr)
            return 1
        clean = parsed_clean
        argi += 1

    if argi < len(argv):
        parsed_seed = parse_seed(argv[argi])
        if parsed_seed is None:
            print("Error: seed must be a non-negative integer.", file=sys.stderr)
            return 1
        seed = parsed_seed
        argi += 1

    if argi != len(argv):
        print("Error: too many arguments.", file=sys.stderr)
        print_usage(argv[0])
        return 1

    a_count = m * n
    b_count = n * k
    c_count = m * k

    times_matmul = [0.0] * repeat
    times_data_prep = [0.0] * repeat
    times_sum = [0.0] * repeat
    times_total = [0.0] * repeat

    min_matmul_time = float("inf")
    max_matmul_time = 0.0
    min_data_prep_time = float("inf")
    max_data_prep_time = 0.0
    min_sum_time = float("inf")
    max_sum_time = 0.0
    min_total_time = float("inf")
    max_total_time = 0.0
    aggregated_value = 0.0

    random.seed(seed)

    fill_fn: Callable[[List[Any], int], None]
    matmul_fn: Callable[[List[Any], List[Any], List[Any], int, int, int], None]
    sum_fn: Callable[[List[Any], int], float]
    zero_value: Any

    if dtype == DTYPE_FLOAT32:
        fill_fn = fill_random_f32
        matmul_fn = matmul_f32
        sum_fn = sum_matrix_f32
        zero_value = 0.0
    elif dtype == DTYPE_FLOAT64:
        fill_fn = fill_random_f64
        matmul_fn = matmul_f64
        sum_fn = sum_matrix_f64
        zero_value = 0.0
    elif dtype == DTYPE_INT64:
        fill_fn = fill_random_i64
        matmul_fn = matmul_i64
        sum_fn = sum_matrix_i64
        zero_value = 0
    elif dtype == DTYPE_INT32:
        fill_fn = fill_random_i32
        matmul_fn = matmul_i32
        sum_fn = sum_matrix_i32
        zero_value = 0
    elif dtype == DTYPE_INT16:
        fill_fn = fill_random_i16
        matmul_fn = matmul_i16
        sum_fn = sum_matrix_i16
        zero_value = 0
    else:
        fill_fn = fill_random_i8
        matmul_fn = matmul_i8
        sum_fn = sum_matrix_i8
        zero_value = 0

    a = [zero_value] * a_count
    b = [zero_value] * b_count
    c = [zero_value] * c_count

    fill_fn(a, a_count)
    fill_fn(b, b_count)

    for r in range(repeat):
        total_t0 = now_seconds()
        data_prep_dt = 0.0
        if clean:
            prep_t0 = now_seconds()
            fill_fn(a, a_count)
            fill_fn(b, b_count)
            data_prep_dt = now_seconds() - prep_t0

        t0 = now_seconds()
        matmul_fn(a, b, c, m, n, k)
        matmul_dt = now_seconds() - t0

        t0 = now_seconds()
        aggregated_value += sum_fn(c, c_count)
        sum_dt = now_seconds() - t0

        total_dt = now_seconds() - total_t0

        times_data_prep[r] = data_prep_dt
        times_matmul[r] = matmul_dt
        times_sum[r] = sum_dt
        times_total[r] = total_dt

        min_data_prep_time = min(min_data_prep_time, data_prep_dt)
        max_data_prep_time = max(max_data_prep_time, data_prep_dt)
        min_matmul_time = min(min_matmul_time, matmul_dt)
        max_matmul_time = max(max_matmul_time, matmul_dt)
        min_sum_time = min(min_sum_time, sum_dt)
        max_sum_time = max(max_sum_time, sum_dt)
        min_total_time = min(min_total_time, total_dt)
        max_total_time = max(max_total_time, total_dt)

    print("Input:")
    print(f"  dtype  = {dtype_name}")
    print(f"  M N K  = {m} {n} {k}")
    print(f"  repeat = {repeat}")
    print(f"  clean  = {clean}")
    print(f"  seed   = {seed}")
    print(f"  aggregated_value = {aggregated_value:.12f}")
    print()
    print("Timing (seconds):")
    print(f"  matmul_time min = {min_matmul_time:.9f}, max = {max_matmul_time:.9f}")
    print(f"  data_prep   min = {min_data_prep_time:.9f}, max = {max_data_prep_time:.9f}")
    print(f"  sum         min = {min_sum_time:.9f}, max = {max_sum_time:.9f}")
    print(f"  total       min = {min_total_time:.9f}, max = {max_total_time:.9f}")
    print()

    print("==================================================================")
    print("Writing stats for cMeta ...")
    print()

    ok = write_stats_json(
        dtype_name,
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
        aggregated_value,
    )

    if not ok:
        print("Warning: could not write tmp-cmeta-program-stats.json", file=sys.stderr)
    else:
        print("Wrote tmp-cmeta-program-stats.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
