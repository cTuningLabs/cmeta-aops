fn _wrap_signed(value: Int, bits: Int) -> Int:
    var mask = (1 << bits) - 1
    var wrapped = value & mask
    var sign_bit = 1 << (bits - 1)
    if wrapped & sign_bit:
        wrapped -= (1 << bits)
    return wrapped


fn matmul_f32(a: List[Float32], b: List[Float32], mut c: List[Float32], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Float32 = 0.0
            for p in range(n):
                sum_val += a[i * n + p] * b[p * k + j]
            c[i * k + j] = sum_val


fn matmul_f64(a: List[Float64], b: List[Float64], mut c: List[Float64], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Float64 = 0.0
            for p in range(n):
                sum_val += a[i * n + p] * b[p * k + j]
            c[i * k + j] = sum_val


fn matmul_i64(a: List[Int64], b: List[Int64], mut c: List[Int64], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Int64 = 0
            for p in range(n):
                sum_val = Int64(_wrap_signed(Int(sum_val + (a[i * n + p] * b[p * k + j])), 64))
            c[i * k + j] = Int64(_wrap_signed(Int(sum_val), 64))


fn matmul_i32(a: List[Int32], b: List[Int32], mut c: List[Int32], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Int = 0
            for p in range(n):
                sum_val += Int(a[i * n + p]) * Int(b[p * k + j])
            c[i * k + j] = Int32(_wrap_signed(sum_val, 32))


fn matmul_i16(a: List[Int16], b: List[Int16], mut c: List[Int16], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Int = 0
            for p in range(n):
                sum_val += Int(a[i * n + p]) * Int(b[p * k + j])
            c[i * k + j] = Int16(_wrap_signed(sum_val, 16))


fn matmul_i8(a: List[Int8], b: List[Int8], mut c: List[Int8], m: Int, n: Int, k: Int) -> None:
    for i in range(m):
        for j in range(k):
            var sum_val: Int = 0
            for p in range(n):
                sum_val += Int(a[i * n + p]) * Int(b[p * k + j])
            c[i * k + j] = Int8(_wrap_signed(sum_val, 8))
