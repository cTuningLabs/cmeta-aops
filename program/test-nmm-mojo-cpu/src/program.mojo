import std.sys
from std.math import sqrt, sin, pow
from matmul import matmul_f32, matmul_f64, matmul_i64, matmul_i32, matmul_i16, matmul_i8
import std.time as time_module

comptime DTYPE_FLOAT32 = 0
comptime DTYPE_FLOAT64 = 1
comptime DTYPE_INT64 = 2
comptime DTYPE_INT32 = 3
comptime DTYPE_INT16 = 4
comptime DTYPE_INT8 = 5


fn now_seconds() -> Float64:
    return time_module.perf_counter()


fn is_integer_string(s: String) -> Bool:
    if len(s) == 0:
        return False
    for c in s.codepoint_slices():
        if c < "0" or c > "9":
            return False
    return True


fn parse_positive_size(s: String) -> Int:
    if len(s) == 0 or not is_integer_string(s):
        return -1
    var value: Int = 0
    for c in s.codepoint_slices():
        # Convert character digit to integer
        if c == "0":
            value = value * 10 + 0
        elif c == "1":
            value = value * 10 + 1
        elif c == "2":
            value = value * 10 + 2
        elif c == "3":
            value = value * 10 + 3
        elif c == "4":
            value = value * 10 + 4
        elif c == "5":
            value = value * 10 + 5
        elif c == "6":
            value = value * 10 + 6
        elif c == "7":
            value = value * 10 + 7
        elif c == "8":
            value = value * 10 + 8
        elif c == "9":
            value = value * 10 + 9
    if value <= 0:
        return -1
    return value


fn parse_clean(s: String) -> Int:
    if s == "0" or s == "false" or s == "no":
        return 0
    if s == "1" or s == "true" or s == "yes":
        return 1
    return -1


fn parse_seed(s: String) -> Int:
    if len(s) == 0:
        return -1
    if not is_integer_string(s):
        return -1
    var value: Int = 0
    for c in s.codepoint_slices():
        if c == "0":
            value = value * 10 + 0
        elif c == "1":
            value = value * 10 + 1
        elif c == "2":
            value = value * 10 + 2
        elif c == "3":
            value = value * 10 + 3
        elif c == "4":
            value = value * 10 + 4
        elif c == "5":
            value = value * 10 + 5
        elif c == "6":
            value = value * 10 + 6
        elif c == "7":
            value = value * 10 + 7
        elif c == "8":
            value = value * 10 + 8
        elif c == "9":
            value = value * 10 + 9
    if value < 0:
        return -1
    return value


fn sum_matrix_f32(mat: List[Float32], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += Float64(mat[i])
    return total


fn sum_matrix_f64(mat: List[Float64], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += mat[i]
    return total


fn sum_matrix_i64(mat: List[Int64], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += Float64(mat[i])
    return total


fn sum_matrix_i32(mat: List[Int32], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += Float64(mat[i])
    return total


fn sum_matrix_i16(mat: List[Int16], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += Float64(mat[i])
    return total


fn sum_matrix_i8(mat: List[Int8], count: Int) -> Float64:
    var total: Float64 = 0.0
    for i in range(count):
        total += Float64(mat[i])
    return total


fn print_usage(prog: String) -> None:
    print("Usage:")
    print("  " + prog + " [dtype] M N K [repeat] [clean] [seed]")
    print()
    print("Arguments:")
    print("  dtype  : float32 (default), float64, int64, int32, int16, int8")
    print("  M,N,K  : positive integers for (M x N) * (N x K)")
    print("  repeat : positive integer, default 1")
    print("  clean  : 0/1 (or false/true), default 0")
    print("  seed   : non-negative integer for RNG, default time()")


fn write_stats_json(
    dtype: String,
    m: Int,
    n: Int,
    k: Int,
    repeat: Int,
    clean: Int,
    seed: Int,
    min_matmul: Float64,
    max_matmul: Float64,
    all_matmul: List[Float64],
    min_data_prep: Float64,
    max_data_prep: Float64,
    all_data_prep: List[Float64],
    min_sum: Float64,
    max_sum: Float64,
    all_sum: List[Float64],
    min_total: Float64,
    max_total: Float64,
    all_total: List[Float64],
    aggregated_value: Float64,
) -> Bool:
    try:
        var file = open("tmp-cmeta-program-stats.json", "w")
        file.write("{\n")
        file.write("  \"input\": {\n")
        file.write("    \"dtype\": \"" + dtype + "\",\n")
        file.write("    \"M\": " + String(m) + ",\n")
        file.write("    \"N\": " + String(n) + ",\n")
        file.write("    \"K\": " + String(k) + ",\n")
        file.write("    \"repeat\": " + String(repeat) + ",\n")
        file.write("    \"clean\": " + String(clean) + ",\n")
        file.write("    \"seed\": " + String(seed) + "\n")
        file.write("  },\n")
        file.write("  \"aggregated_value\": " + String(aggregated_value) + ",\n")
        file.write("  \"timing\": {\n")

        file.write("    \"matmul_time\": {\n")
        file.write("      \"min\": " + String(min_matmul) + ",\n")
        file.write("      \"max\": " + String(max_matmul) + ",\n")
        file.write("      \"all\": [")
        for i in range(len(all_matmul)):
            if i > 0:
                file.write(", ")
            file.write(String(all_matmul[i]))
        file.write("]\n")
        file.write("    },\n")

        file.write("    \"data_prep\": {\n")
        file.write("      \"min\": " + String(min_data_prep) + ",\n")
        file.write("      \"max\": " + String(max_data_prep) + ",\n")
        file.write("      \"all\": [")
        for i in range(len(all_data_prep)):
            if i > 0:
                file.write(", ")
            file.write(String(all_data_prep[i]))
        file.write("]\n")
        file.write("    },\n")

        file.write("    \"sum\": {\n")
        file.write("      \"min\": " + String(min_sum) + ",\n")
        file.write("      \"max\": " + String(max_sum) + ",\n")
        file.write("      \"all\": [")
        for i in range(len(all_sum)):
            if i > 0:
                file.write(", ")
            file.write(String(all_sum[i]))
        file.write("]\n")
        file.write("    },\n")

        file.write("    \"total\": {\n")
        file.write("      \"min\": " + String(min_total) + ",\n")
        file.write("      \"max\": " + String(max_total) + ",\n")
        file.write("      \"all\": [")
        for i in range(len(all_total)):
            if i > 0:
                file.write(", ")
            file.write(String(all_total[i]))
        file.write("]\n")
        file.write("    }\n")

        file.write("  }\n")
        file.write("}\n")
        file.close()
    except e:
        return False

    return True


fn run_program(argv_list: List[String]) -> Int:
    var dtype = DTYPE_FLOAT32
    var dtype_name = "float32"
    var _ = 0
    var _ = 0
    var _ = 0
    var repeat = 1
    var clean = 0
    var seed_value = Int(now_seconds())
    var argi = 1

    print("==================================================================")
    print("Testing OpenMP ...")
    print()

    var max_threads = 4
    print("_OPENMP = 0")
    print("max threads = " + String(max_threads))

    for i in range(max_threads):
        print("hello from thread " + String(i) + " of " + String(max_threads))

    print()

    print("==================================================================")
    print("Testing basic math ...")
    print()

    var x = 16.0
    print("sqrt(" + String(x) + ") = " + String(sqrt(x)))
    print("sin(0.0) = " + String(sin(0.0)))
    print("pow(2.0, 3.0) = " + String(pow(2.0, 3.0)))
    print()

    if len(argv_list) < 4:
        print_usage(argv_list[0])
        return 1

    print("==================================================================")
    print("Testing naive matmul ...")
    print()

    if argi < len(argv_list) and not is_integer_string(argv_list[argi]):
        var token = argv_list[argi]
        if token == "float32" or token == "f32":
            dtype = DTYPE_FLOAT32
            dtype_name = "float32"
        elif token == "float64" or token == "f64" or token == "double":
            dtype = DTYPE_FLOAT64
            dtype_name = "float64"
        elif token == "int64" or token == "i64":
            dtype = DTYPE_INT64
            dtype_name = "int64"
        elif token == "int32" or token == "i32":
            dtype = DTYPE_INT32
            dtype_name = "int32"
        elif token == "int16" or token == "i16":
            dtype = DTYPE_INT16
            dtype_name = "int16"
        elif token == "int8" or token == "i8":
            dtype = DTYPE_INT8
            dtype_name = "int8"
        else:
            print("Error: unsupported dtype '" + token + "'")
            print_usage(argv_list[0])
            return 1
        argi += 1

    if len(argv_list) - argi < 3:
        print("Error: M N K are required.")
        print_usage(argv_list[0])
        return 1

    var parsed_m = parse_positive_size(argv_list[argi])
    var parsed_n = parse_positive_size(argv_list[argi + 1])
    var parsed_k = parse_positive_size(argv_list[argi + 2])
    
    if parsed_m < 0 or parsed_n < 0 or parsed_k < 0:
        print("Error: M N K must be positive integers.")
        return 1

    m = parsed_m
    n = parsed_n
    k = parsed_k
    argi += 3

    if argi < len(argv_list):
        var parsed_repeat = parse_positive_size(argv_list[argi])
        if parsed_repeat < 0:
            print("Error: repeat must be a positive integer.")
            return 1
        repeat = parsed_repeat
        argi += 1

    if argi < len(argv_list):
        var parsed_clean = parse_clean(argv_list[argi])
        if parsed_clean < 0:
            print("Error: clean must be one of 0/1/false/true/no/yes.")
            return 1
        clean = parsed_clean
        argi += 1

    if argi < len(argv_list):
        var parsed_seed = parse_seed(argv_list[argi])
        if parsed_seed < 0:
            print("Error: seed must be a non-negative integer.")
            return 1
        seed_value = parsed_seed
        argi += 1

    if argi != len(argv_list):
        print("Error: too many arguments.")
        print_usage(argv_list[0])
        return 1

    var a_count = m * n
    var b_count = n * k
    var c_count = m * k

    var times_matmul = List[Float64]()
    var times_data_prep = List[Float64]()
    var times_sum = List[Float64]()
    var times_total = List[Float64]()
    for _ in range(repeat):
        times_matmul.append(0.0)
        times_data_prep.append(0.0)
        times_sum.append(0.0)
        times_total.append(0.0)

    var min_matmul_time = Float64(1e10)
    var max_matmul_time = 0.0
    var min_data_prep_time = Float64(1e10)
    var max_data_prep_time = 0.0
    var min_sum_time = Float64(1e10)
    var max_sum_time = 0.0
    var min_total_time = Float64(1e10)
    var max_total_time = 0.0
    var aggregated_value = 0.0

    var rng_seed = seed_value

    if dtype == DTYPE_FLOAT32:
        var a = List[Float32]()
        var b = List[Float32]()
        var c = List[Float32]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Float32(seed) / 2147483647.0)
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Float32(seed) / 2147483647.0)
        for _ in range(c_count):
            c.append(0.0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Float32(seed) / 2147483647.0
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Float32(seed) / 2147483647.0
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_f32(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_f32(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    elif dtype == DTYPE_FLOAT64:
        var a = List[Float64]()
        var b = List[Float64]()
        var c = List[Float64]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Float64(seed) / 2147483647.0)
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Float64(seed) / 2147483647.0)
        for _ in range(c_count):
            c.append(0.0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Float64(seed) / 2147483647.0
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Float64(seed) / 2147483647.0
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_f64(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_f64(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    elif dtype == DTYPE_INT64:
        var a = List[Int64]()
        var b = List[Int64]()
        var c = List[Int64]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Int64(seed % 16))
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Int64(seed % 16))
        for _ in range(c_count):
            c.append(0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Int64(seed % 16)
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Int64(seed % 16)
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_i64(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_i64(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    elif dtype == DTYPE_INT32:
        var a = List[Int32]()
        var b = List[Int32]()
        var c = List[Int32]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Int32(seed % 16))
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Int32(seed % 16))
        for _ in range(c_count):
            c.append(0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Int32(seed % 16)
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Int32(seed % 16)
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_i32(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_i32(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    elif dtype == DTYPE_INT16:
        var a = List[Int16]()
        var b = List[Int16]()
        var c = List[Int16]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Int16(seed % 16))
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Int16(seed % 16))
        for _ in range(c_count):
            c.append(0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Int16(seed % 16)
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Int16(seed % 16)
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_i16(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_i16(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    else:  # DTYPE_INT8
        var a = List[Int8]()
        var b = List[Int8]()
        var c = List[Int8]()
        
        # Initialize with random values
        var seed = rng_seed
        for _ in range(a_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            a.append(Int8(seed % 16))
        for _ in range(b_count):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            b.append(Int8(seed % 16))
        for _ in range(c_count):
            c.append(0)

        for r in range(repeat):
            var total_t0 = now_seconds()
            var data_prep_dt = 0.0
            if clean:
                var prep_t0 = now_seconds()
                seed = rng_seed
                for i in range(a_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    a[i] = Int8(seed % 16)
                for i in range(b_count):
                    seed = (seed * 1103515245 + 12345) & 0x7fffffff
                    b[i] = Int8(seed % 16)
                data_prep_dt = now_seconds() - prep_t0

            var t0 = now_seconds()
            matmul_i8(a, b, c, m, n, k)
            var matmul_dt = now_seconds() - t0

            var st0 = now_seconds()
            aggregated_value += sum_matrix_i8(c, c_count)
            var sum_dt = now_seconds() - st0

            var total_dt = now_seconds() - total_t0

            times_data_prep[r] = data_prep_dt
            times_matmul[r] = matmul_dt
            times_sum[r] = sum_dt
            times_total[r] = total_dt

            if data_prep_dt < min_data_prep_time:
                min_data_prep_time = data_prep_dt
            if data_prep_dt > max_data_prep_time:
                max_data_prep_time = data_prep_dt
            if matmul_dt < min_matmul_time:
                min_matmul_time = matmul_dt
            if matmul_dt > max_matmul_time:
                max_matmul_time = matmul_dt
            if sum_dt < min_sum_time:
                min_sum_time = sum_dt
            if sum_dt > max_sum_time:
                max_sum_time = sum_dt
            if total_dt < min_total_time:
                min_total_time = total_dt
            if total_dt > max_total_time:
                max_total_time = total_dt

    print("Input:")
    print("  dtype  = " + dtype_name)
    print("  M N K  = " + String(m) + " " + String(n) + " " + String(k))
    print("  repeat = " + String(repeat))
    print("  clean  = " + String(clean))
    print("  seed   = " + String(seed_value))
    print("  aggregated_value = " + String(aggregated_value))
    print()
    print("Timing (seconds):")
    print("  matmul_time min = " + String(min_matmul_time) + ", max = " + String(max_matmul_time))
    print("  data_prep   min = " + String(min_data_prep_time) + ", max = " + String(max_data_prep_time))
    print("  sum         min = " + String(min_sum_time) + ", max = " + String(max_sum_time))
    print("  total       min = " + String(min_total_time) + ", max = " + String(max_total_time))
    print()

    print("==================================================================")
    print("Writing stats for cMeta ...")
    print()

    var ok = write_stats_json(
        dtype_name,
        m,
        n,
        k,
        repeat,
        clean,
        seed_value,
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
        print("Warning: could not write tmp-cmeta-program-stats.json")
    else:
        print("Wrote tmp-cmeta-program-stats.json")

    return 0


fn main() -> None:
    var argv_list = List[String]()
    var argv = std.sys.argv()
    for i in range(len(argv)):
        argv_list.append(String(argv[i]))
    var _ = run_program(argv_list)
