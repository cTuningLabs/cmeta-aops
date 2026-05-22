package main

import (
	"crypto/sha256"
	"fmt"
	"math"
	"math/rand"
	"os"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

type dType int

const (
	dtypeFloat32 dType = iota
	dtypeFloat64
	dtypeInt64
	dtypeInt32
	dtypeInt16
	dtypeInt8
)

func nowSeconds() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}

func isIntegerString(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

func parsePositiveSize(s string) (int, bool) {
	v, err := strconv.ParseUint(s, 10, 64)
	if err != nil || v == 0 || v > uint64(^uint(0)>>1) {
		return 0, false
	}
	return int(v), true
}

func parseClean(s string) (int, bool) {
	switch s {
	case "0", "false", "no":
		return 0, true
	case "1", "true", "yes":
		return 1, true
	default:
		return 0, false
	}
}

func parseSeed(s string) (uint32, bool) {
	v, err := strconv.ParseUint(s, 10, 32)
	if err != nil {
		return 0, false
	}
	return uint32(v), true
}

func randomIntInclusive(rng *rand.Rand, minVal, maxVal int) int {
	return minVal + rng.Intn(maxVal-minVal+1)
}

func fillRandomF32(rng *rand.Rand, mat []float32) {
	for i := range mat {
		mat[i] = float32(rng.Float64())
	}
}

func fillRandomF64(rng *rand.Rand, mat []float64) {
	for i := range mat {
		mat[i] = rng.Float64()
	}
}

func fillRandomI64(rng *rand.Rand, mat []int64) {
	for i := range mat {
		mat[i] = int64(randomIntInclusive(rng, 0, 15))
	}
}

func fillRandomI32(rng *rand.Rand, mat []int32) {
	for i := range mat {
		mat[i] = int32(randomIntInclusive(rng, 0, 15))
	}
}

func fillRandomI16(rng *rand.Rand, mat []int16) {
	for i := range mat {
		mat[i] = int16(randomIntInclusive(rng, 0, 15))
	}
}

func fillRandomI8(rng *rand.Rand, mat []int8) {
	for i := range mat {
		mat[i] = int8(randomIntInclusive(rng, 0, 15))
	}
}

func sumMatrixF32(mat []float32) float64 {
	sum := 0.0
	for i := range mat {
		sum += float64(mat[i])
	}
	return sum
}

func sumMatrixF64(mat []float64) float64 {
	sum := 0.0
	for i := range mat {
		sum += mat[i]
	}
	return sum
}

func sumMatrixI64(mat []int64) float64 {
	sum := 0.0
	for i := range mat {
		sum += float64(mat[i])
	}
	return sum
}

func sumMatrixI32(mat []int32) float64 {
	sum := 0.0
	for i := range mat {
		sum += float64(mat[i])
	}
	return sum
}

func sumMatrixI16(mat []int16) float64 {
	sum := 0.0
	for i := range mat {
		sum += float64(mat[i])
	}
	return sum
}

func sumMatrixI8(mat []int8) float64 {
	sum := 0.0
	for i := range mat {
		sum += float64(mat[i])
	}
	return sum
}

func printUsage(prog string) {
	fmt.Println("Usage:")
	fmt.Printf("  %s [dtype] M N K [repeat] [clean] [seed]\n", prog)
	fmt.Println()
	fmt.Println("Arguments:")
	fmt.Println("  dtype  : float32 (default), float64, int64, int32, int16, int8")
	fmt.Println("  M,N,K  : positive integers for (M x N) * (N x K)")
	fmt.Println("  repeat : positive integer, default 1")
	fmt.Println("  clean  : 0/1 (or false/true), default 0")
	fmt.Println("  seed   : non-negative integer for RNG, default time(NULL)")
}

func writeStatsJSON(dtypeName string, m, n, k, repeat int, clean int, seed uint32, minMatmul, maxMatmul float64, allMatmul []float64, minDataPrep, maxDataPrep float64, allDataPrep []float64, minSum, maxSum float64, allSum []float64, minTotal, maxTotal float64, allTotal []float64, aggregatedValue float64) bool {
	f, err := os.Create("tmp-cmeta-program-stats.json")
	if err != nil {
		return false
	}
	defer f.Close()

	fmt.Fprintln(f, "{")
	fmt.Fprintln(f, "  \"input\": {")
	fmt.Fprintf(f, "    \"dtype\": \"%s\",\n", dtypeName)
	fmt.Fprintf(f, "    \"M\": %d,\n", m)
	fmt.Fprintf(f, "    \"N\": %d,\n", n)
	fmt.Fprintf(f, "    \"K\": %d,\n", k)
	fmt.Fprintf(f, "    \"repeat\": %d,\n", repeat)
	fmt.Fprintf(f, "    \"clean\": %d,\n", clean)
	fmt.Fprintf(f, "    \"seed\": %d\n", seed)
	fmt.Fprintln(f, "  },")
	fmt.Fprintf(f, "  \"aggregated_value\": %.12f,\n", aggregatedValue)
	fmt.Fprintln(f, "  \"timing\": {")

	fmt.Fprintln(f, "    \"matmul_time\": {")
	fmt.Fprintf(f, "      \"min\": %.12f,\n", minMatmul)
	fmt.Fprintf(f, "      \"max\": %.12f,\n", maxMatmul)
	fmt.Fprint(f, "      \"all\": [")
	for i := 0; i < repeat; i++ {
		if i > 0 {
			fmt.Fprint(f, ", ")
		}
		fmt.Fprintf(f, "%.12f", allMatmul[i])
	}
	fmt.Fprintln(f, "]")
	fmt.Fprintln(f, "    },")

	fmt.Fprintln(f, "    \"data_prep\": {")
	fmt.Fprintf(f, "      \"min\": %.12f,\n", minDataPrep)
	fmt.Fprintf(f, "      \"max\": %.12f,\n", maxDataPrep)
	fmt.Fprint(f, "      \"all\": [")
	for i := 0; i < repeat; i++ {
		if i > 0 {
			fmt.Fprint(f, ", ")
		}
		fmt.Fprintf(f, "%.12f", allDataPrep[i])
	}
	fmt.Fprintln(f, "]")
	fmt.Fprintln(f, "    },")

	fmt.Fprintln(f, "    \"sum\": {")
	fmt.Fprintf(f, "      \"min\": %.12f,\n", minSum)
	fmt.Fprintf(f, "      \"max\": %.12f,\n", maxSum)
	fmt.Fprint(f, "      \"all\": [")
	for i := 0; i < repeat; i++ {
		if i > 0 {
			fmt.Fprint(f, ", ")
		}
		fmt.Fprintf(f, "%.12f", allSum[i])
	}
	fmt.Fprintln(f, "]")
	fmt.Fprintln(f, "    },")

	fmt.Fprintln(f, "    \"total\": {")
	fmt.Fprintf(f, "      \"min\": %.12f,\n", minTotal)
	fmt.Fprintf(f, "      \"max\": %.12f,\n", maxTotal)
	fmt.Fprint(f, "      \"all\": [")
	for i := 0; i < repeat; i++ {
		if i > 0 {
			fmt.Fprint(f, ", ")
		}
		fmt.Fprintf(f, "%.12f", allTotal[i])
	}
	fmt.Fprintln(f, "]")
	fmt.Fprintln(f, "    }")

	fmt.Fprintln(f, "  }")
	fmt.Fprintln(f, "}")
	return true
}

func productFitsInt(a, b int) bool {
	if a == 0 || b == 0 {
		return true
	}
	return a <= int(^uint(0)>>1)/b
}

func main() {
	dtype := dtypeFloat32
	dtypeName := "float32"
	m, n, k := 0, 0, 0
	repeat := 1
	clean := 0
	seed := uint32(time.Now().Unix())
	argi := 1

	fmt.Println("==================================================================")
	fmt.Println("Testing OpenMP ...")
	fmt.Println()

	maxThreads := runtime.GOMAXPROCS(0)
	fmt.Printf("GOMAXPROCS = %d\n", maxThreads)
	fmt.Printf("max threads = %d\n", runtime.NumCPU())

	var wg sync.WaitGroup
	for i := 0; i < maxThreads; i++ {
		wg.Add(1)
		go func(threadID int) {
			defer wg.Done()
			fmt.Printf("hello from thread %d of %d\n", threadID, maxThreads)
		}(i)
	}
	wg.Wait()

	fmt.Println()

	fmt.Println("==================================================================")
	fmt.Println("Testing OpenSSL ...")
	fmt.Println()
	fmt.Println("OpenSSL version: Go crypto/sha256")

	msg := "hello world"
	hash := sha256.Sum256([]byte(msg))
	fmt.Printf("SHA256(\"hello world\") = %x\n", hash)
	fmt.Println()

	fmt.Println("==================================================================")
	fmt.Println("Testing basic math ...")
	fmt.Println()

	x := 16.0
	fmt.Printf("sqrt(%.2f) = %.2f\n", x, math.Sqrt(x))
	fmt.Printf("sin(0.0) = %.2f\n", math.Sin(0.0))
	fmt.Printf("pow(2.0, 3.0) = %.2f\n", math.Pow(2.0, 3.0))
	fmt.Println()

	if len(os.Args) < 4 {
		printUsage(os.Args[0])
		os.Exit(1)
	}

	fmt.Println("==================================================================")
	fmt.Println("Testing naive matmul ...")
	fmt.Println()

	if argi < len(os.Args) && !isIntegerString(os.Args[argi]) {
		switch strings.ToLower(os.Args[argi]) {
		case "float32", "f32":
			dtype = dtypeFloat32
			dtypeName = "float32"
		case "float64", "f64", "double":
			dtype = dtypeFloat64
			dtypeName = "float64"
		case "int64", "i64":
			dtype = dtypeInt64
			dtypeName = "int64"
		case "int32", "i32":
			dtype = dtypeInt32
			dtypeName = "int32"
		case "int16", "i16":
			dtype = dtypeInt16
			dtypeName = "int16"
		case "int8", "i8":
			dtype = dtypeInt8
			dtypeName = "int8"
		default:
			fmt.Fprintf(os.Stderr, "Error: unsupported dtype '%s'.\n", os.Args[argi])
			printUsage(os.Args[0])
			os.Exit(1)
		}
		argi++
	}

	if len(os.Args)-argi < 3 {
		fmt.Fprintln(os.Stderr, "Error: M N K are required.")
		printUsage(os.Args[0])
		os.Exit(1)
	}

	var ok bool
	m, ok = parsePositiveSize(os.Args[argi])
	argi++
	if !ok {
		fmt.Fprintln(os.Stderr, "Error: M N K must be positive integers.")
		os.Exit(1)
	}
	n, ok = parsePositiveSize(os.Args[argi])
	argi++
	if !ok {
		fmt.Fprintln(os.Stderr, "Error: M N K must be positive integers.")
		os.Exit(1)
	}
	k, ok = parsePositiveSize(os.Args[argi])
	argi++
	if !ok {
		fmt.Fprintln(os.Stderr, "Error: M N K must be positive integers.")
		os.Exit(1)
	}

	if argi < len(os.Args) {
		repeat, ok = parsePositiveSize(os.Args[argi])
		if !ok {
			fmt.Fprintln(os.Stderr, "Error: repeat must be a positive integer.")
			os.Exit(1)
		}
		argi++
	}

	if argi < len(os.Args) {
		clean, ok = parseClean(strings.ToLower(os.Args[argi]))
		if !ok {
			fmt.Fprintln(os.Stderr, "Error: clean must be one of 0/1/false/true/no/yes.")
			os.Exit(1)
		}
		argi++
	}

	if argi < len(os.Args) {
		seed, ok = parseSeed(os.Args[argi])
		if !ok {
			fmt.Fprintln(os.Stderr, "Error: seed must be a non-negative integer.")
			os.Exit(1)
		}
		argi++
	}

	if argi != len(os.Args) {
		fmt.Fprintln(os.Stderr, "Error: too many arguments.")
		printUsage(os.Args[0])
		os.Exit(1)
	}

	if !productFitsInt(m, n) || !productFitsInt(n, k) || !productFitsInt(m, k) {
		fmt.Fprintln(os.Stderr, "Error: matrix dimensions are too large.")
		os.Exit(1)
	}

	aCount := m * n
	bCount := n * k
	cCount := m * k

	timesMatmul := make([]float64, repeat)
	timesDataPrep := make([]float64, repeat)
	timesSum := make([]float64, repeat)
	timesTotal := make([]float64, repeat)

	minMatmulTime := math.MaxFloat64
	maxMatmulTime := 0.0
	minDataPrepTime := math.MaxFloat64
	maxDataPrepTime := 0.0
	minSumTime := math.MaxFloat64
	maxSumTime := 0.0
	minTotalTime := math.MaxFloat64
	maxTotalTime := 0.0
	aggregatedValue := 0.0

	rng := rand.New(rand.NewSource(int64(seed)))

	switch dtype {
	case dtypeFloat32:
		a := make([]float32, aCount)
		b := make([]float32, bCount)
		c := make([]float32, cCount)
		fillRandomF32(rng, a)
		fillRandomF32(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomF32(rng, a)
				fillRandomF32(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulF32(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixF32(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}

	case dtypeFloat64:
		a := make([]float64, aCount)
		b := make([]float64, bCount)
		c := make([]float64, cCount)
		fillRandomF64(rng, a)
		fillRandomF64(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomF64(rng, a)
				fillRandomF64(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulF64(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixF64(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}

	case dtypeInt64:
		a := make([]int64, aCount)
		b := make([]int64, bCount)
		c := make([]int64, cCount)
		fillRandomI64(rng, a)
		fillRandomI64(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomI64(rng, a)
				fillRandomI64(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulI64(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixI64(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}

	case dtypeInt32:
		a := make([]int32, aCount)
		b := make([]int32, bCount)
		c := make([]int32, cCount)
		fillRandomI32(rng, a)
		fillRandomI32(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomI32(rng, a)
				fillRandomI32(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulI32(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixI32(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}

	case dtypeInt16:
		a := make([]int16, aCount)
		b := make([]int16, bCount)
		c := make([]int16, cCount)
		fillRandomI16(rng, a)
		fillRandomI16(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomI16(rng, a)
				fillRandomI16(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulI16(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixI16(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}

	case dtypeInt8:
		a := make([]int8, aCount)
		b := make([]int8, bCount)
		c := make([]int8, cCount)
		fillRandomI8(rng, a)
		fillRandomI8(rng, b)

		for r := 0; r < repeat; r++ {
			totalT0 := nowSeconds()
			dataPrepDt := 0.0
			if clean != 0 {
				prepT0 := nowSeconds()
				fillRandomI8(rng, a)
				fillRandomI8(rng, b)
				dataPrepDt = nowSeconds() - prepT0
			}

			t0 := nowSeconds()
			matmulI8(a, b, c, m, n, k)
			matmulDt := nowSeconds() - t0

			t0 = nowSeconds()
			aggregatedValue += sumMatrixI8(c)
			sumDt := nowSeconds() - t0

			totalDt := nowSeconds() - totalT0

			timesDataPrep[r] = dataPrepDt
			timesMatmul[r] = matmulDt
			timesSum[r] = sumDt
			timesTotal[r] = totalDt

			if dataPrepDt < minDataPrepTime {
				minDataPrepTime = dataPrepDt
			}
			if dataPrepDt > maxDataPrepTime {
				maxDataPrepTime = dataPrepDt
			}
			if matmulDt < minMatmulTime {
				minMatmulTime = matmulDt
			}
			if matmulDt > maxMatmulTime {
				maxMatmulTime = matmulDt
			}
			if sumDt < minSumTime {
				minSumTime = sumDt
			}
			if sumDt > maxSumTime {
				maxSumTime = sumDt
			}
			if totalDt < minTotalTime {
				minTotalTime = totalDt
			}
			if totalDt > maxTotalTime {
				maxTotalTime = totalDt
			}
		}
	}

	fmt.Println("Input:")
	fmt.Printf("  dtype  = %s\n", dtypeName)
	fmt.Printf("  M N K  = %d %d %d\n", m, n, k)
	fmt.Printf("  repeat = %d\n", repeat)
	fmt.Printf("  clean  = %d\n", clean)
	fmt.Printf("  seed   = %d\n", seed)
	fmt.Printf("  aggregated_value = %.12f\n", aggregatedValue)
	fmt.Println("\nTiming (seconds):")
	fmt.Printf("  matmul_time min = %.9f, max = %.9f\n", minMatmulTime, maxMatmulTime)
	fmt.Printf("  data_prep   min = %.9f, max = %.9f\n", minDataPrepTime, maxDataPrepTime)
	fmt.Printf("  sum         min = %.9f, max = %.9f\n", minSumTime, maxSumTime)
	fmt.Printf("  total       min = %.9f, max = %.9f\n", minTotalTime, maxTotalTime)
	fmt.Println()

	fmt.Println("==================================================================")
	fmt.Println("Writing stats for cMeta ...")
	fmt.Println()

	if !writeStatsJSON(dtypeName, m, n, k, repeat, clean, seed, minMatmulTime, maxMatmulTime, timesMatmul, minDataPrepTime, maxDataPrepTime, timesDataPrep, minSumTime, maxSumTime, timesSum, minTotalTime, maxTotalTime, timesTotal, aggregatedValue) {
		fmt.Fprintln(os.Stderr, "Warning: could not write tmp-cmeta-program-stats.json")
	} else {
		fmt.Println("Wrote tmp-cmeta-program-stats.json")
	}
}
