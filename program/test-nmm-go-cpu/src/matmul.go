package main

func matmulF32(a []float32, b []float32, c []float32, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := float32(0)
			for p := 0; p < n; p++ {
				sum += a[i*n+p] * b[p*k+j]
			}
			c[i*k+j] = sum
		}
	}
}

func matmulF64(a []float64, b []float64, c []float64, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := float64(0)
			for p := 0; p < n; p++ {
				sum += a[i*n+p] * b[p*k+j]
			}
			c[i*k+j] = sum
		}
	}
}

func matmulI64(a []int64, b []int64, c []int64, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := int64(0)
			for p := 0; p < n; p++ {
				sum += a[i*n+p] * b[p*k+j]
			}
			c[i*k+j] = sum
		}
	}
}

func matmulI32(a []int32, b []int32, c []int32, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := int64(0)
			for p := 0; p < n; p++ {
				sum += int64(a[i*n+p]) * int64(b[p*k+j])
			}
			c[i*k+j] = int32(sum)
		}
	}
}

func matmulI16(a []int16, b []int16, c []int16, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := int64(0)
			for p := 0; p < n; p++ {
				sum += int64(a[i*n+p]) * int64(b[p*k+j])
			}
			c[i*k+j] = int16(sum)
		}
	}
}

func matmulI8(a []int8, b []int8, c []int8, m, n, k int) {
	for i := 0; i < m; i++ {
		for j := 0; j < k; j++ {
			sum := int64(0)
			for p := 0; p < n; p++ {
				sum += int64(a[i*n+p]) * int64(b[p*k+j])
			}
			c[i*k+j] = int8(sum)
		}
	}
}
