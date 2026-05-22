/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.

Developed with the help of ChatGPT and Claude.
*/

import Foundation

#if canImport(CryptoKit)
import CryptoKit
#elseif canImport(Crypto)
import Crypto
#endif

// MARK: - Timing

/// Monotonic wall-clock seconds (high-resolution).
func nowSeconds() -> Double {
    return ProcessInfo.processInfo.systemUptime
}

// MARK: - DType

enum DType {
    case float32, float64, int64, int32, int16, int8

    var name: String {
        switch self {
        case .float32: return "float32"
        case .float64: return "float64"
        case .int64:   return "int64"
        case .int32:   return "int32"
        case .int16:   return "int16"
        case .int8:    return "int8"
        }
    }

    static func parse(_ s: String) -> DType? {
        switch s {
        case "float32", "f32":           return .float32
        case "float64", "f64", "double": return .float64
        case "int64",   "i64":           return .int64
        case "int32",   "i32":           return .int32
        case "int16",   "i16":           return .int16
        case "int8",    "i8":            return .int8
        default:                         return nil
        }
    }
}

// MARK: - LCG RNG  (matches glibc rand() so seeded values are reproducible)

private var lcgState: UInt32 = 1

func seedRNG(_ seed: UInt32) {
    lcgState = seed == 0 ? 1 : seed
}

@inline(__always)
func lcgRand() -> Int32 {
    lcgState = lcgState &* 1103515245 &+ 12345
    return Int32(bitPattern: (lcgState >> 16) & 0x7fff)
}

@inline(__always)
func random01() -> Double {
    return Double(lcgRand()) / 32767.0
}

@inline(__always)
func randomIntInclusive(_ lo: Int, _ hi: Int) -> Int {
    let span = hi - lo + 1
    return lo + Int(lcgRand()) % span
}

// MARK: - Fill helpers

func fillRandomF32(_ mat: inout [Float]) {
    for i in mat.indices { mat[i] = Float(random01()) }
}

func fillRandomF64(_ mat: inout [Double]) {
    for i in mat.indices { mat[i] = random01() }
}

func fillRandomI64(_ mat: inout [Int64]) {
    for i in mat.indices { mat[i] = Int64(randomIntInclusive(0, 15)) }
}

func fillRandomI32(_ mat: inout [Int32]) {
    for i in mat.indices { mat[i] = Int32(randomIntInclusive(0, 15)) }
}

func fillRandomI16(_ mat: inout [Int16]) {
    for i in mat.indices { mat[i] = Int16(randomIntInclusive(0, 15)) }
}

func fillRandomI8(_ mat: inout [Int8]) {
    for i in mat.indices { mat[i] = Int8(randomIntInclusive(0, 15)) }
}

// MARK: - Sum helpers (reduce to Double for aggregation)

func sumF32(_ mat: [Float])  -> Double { mat.reduce(0.0) { $0 + Double($1) } }
func sumF64(_ mat: [Double]) -> Double { mat.reduce(0.0) { $0 + $1 } }
func sumI64(_ mat: [Int64])  -> Double { mat.reduce(0.0) { $0 + Double($1) } }
func sumI32(_ mat: [Int32])  -> Double { mat.reduce(0.0) { $0 + Double($1) } }
func sumI16(_ mat: [Int16])  -> Double { mat.reduce(0.0) { $0 + Double($1) } }
func sumI8 (_ mat: [Int8])   -> Double { mat.reduce(0.0) { $0 + Double($1) } }

// MARK: - Naive matmul (mirrors C++ implementations, including int accumulator widening)

func matmulF32(_ a: [Float], _ b: [Float], m: Int, n: Int, k: Int) -> [Float] {
    var c = [Float](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Float = 0
            for p in 0..<n { sum += a[i * n + p] * b[p * k + j] }
            c[i * k + j] = sum
        }
    }
    return c
}

func matmulF64(_ a: [Double], _ b: [Double], m: Int, n: Int, k: Int) -> [Double] {
    var c = [Double](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Double = 0
            for p in 0..<n { sum += a[i * n + p] * b[p * k + j] }
            c[i * k + j] = sum
        }
    }
    return c
}

func matmulI64(_ a: [Int64], _ b: [Int64], m: Int, n: Int, k: Int) -> [Int64] {
    var c = [Int64](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Int64 = 0
            for p in 0..<n { sum &+= a[i * n + p] &* b[p * k + j] }
            c[i * k + j] = sum
        }
    }
    return c
}

func matmulI32(_ a: [Int32], _ b: [Int32], m: Int, n: Int, k: Int) -> [Int32] {
    var c = [Int32](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Int64 = 0
            for p in 0..<n { sum += Int64(a[i * n + p]) * Int64(b[p * k + j]) }
            c[i * k + j] = Int32(truncatingIfNeeded: sum)
        }
    }
    return c
}

func matmulI16(_ a: [Int16], _ b: [Int16], m: Int, n: Int, k: Int) -> [Int16] {
    var c = [Int16](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Int64 = 0
            for p in 0..<n { sum += Int64(a[i * n + p]) * Int64(b[p * k + j]) }
            c[i * k + j] = Int16(truncatingIfNeeded: sum)
        }
    }
    return c
}

func matmulI8(_ a: [Int8], _ b: [Int8], m: Int, n: Int, k: Int) -> [Int8] {
    var c = [Int8](repeating: 0, count: m * k)
    for i in 0..<m {
        for j in 0..<k {
            var sum: Int64 = 0
            for p in 0..<n { sum += Int64(a[i * n + p]) * Int64(b[p * k + j]) }
            c[i * k + j] = Int8(truncatingIfNeeded: sum)
        }
    }
    return c
}

// MARK: - Argument parsing helpers

func isPositiveIntegerString(_ s: String) -> Bool {
    return !s.isEmpty && s.allSatisfy { $0.isNumber } && (Int(s) ?? 0) > 0
}

func parsePositiveSize(_ s: String) -> Int? {
    guard let v = Int(s), v > 0 else { return nil }
    return v
}

func parseClean(_ s: String) -> Bool? {
    switch s {
    case "0", "false", "no":  return false
    case "1", "true",  "yes": return true
    default:                  return nil
    }
}

func parseSeed(_ s: String) -> UInt32? {
    guard let v = UInt32(s) else { return nil }
    return v
}

// MARK: - Usage

func printUsage(_ prog: String) {
    print("Usage:")
    print("  \(prog) [dtype] M N K [repeat] [clean] [seed]")
    print("")
    print("Arguments:")
    print("  dtype  : float32 (default), float64, int64, int32, int16, int8")
    print("  M,N,K  : positive integers for (M x N) * (N x K)")
    print("  repeat : positive integer, default 1")
    print("  clean  : 0/1 (or false/true), default 0")
    print("  seed   : non-negative integer for RNG, default time-based")
}

// MARK: - JSON output

func writeStatsJSON(
    dtype: String,
    m: Int, n: Int, k: Int,
    repeatCount: Int,
    clean: Bool,
    seed: UInt32,
    minMatmul:   Double, maxMatmul:   Double, allMatmul:   [Double],
    minDataPrep: Double, maxDataPrep: Double, allDataPrep: [Double],
    minSum:      Double, maxSum:      Double, allSum:      [Double],
    minTotal:    Double, maxTotal:    Double, allTotal:    [Double],
    aggregatedValue: Double
) -> Bool {
    func fmtDouble(_ v: Double) -> String { String(format: "%.12f", v) }
    func arrayStr(_ vals: [Double]) -> String { vals.map { fmtDouble($0) }.joined(separator: ", ") }

    func timingEntry(_ key: String, _ mn: Double, _ mx: Double, _ all: [Double], last: Bool) -> String {
        var s  = "    \"\(key)\": {\n"
        s     += "      \"min\": \(fmtDouble(mn)),\n"
        s     += "      \"max\": \(fmtDouble(mx)),\n"
        s     += "      \"all\": [\(arrayStr(all))]\n"
        s     += last ? "    }" : "    },"
        return s
    }

    var json  = "{\n"
    json     += "  \"input\": {\n"
    json     += "    \"dtype\": \"\(dtype)\",\n"
    json     += "    \"M\": \(m),\n"
    json     += "    \"N\": \(n),\n"
    json     += "    \"K\": \(k),\n"
    json     += "    \"repeat\": \(repeatCount),\n"
    json     += "    \"clean\": \(clean ? 1 : 0),\n"
    json     += "    \"seed\": \(seed)\n"
    json     += "  },\n"
    json     += "  \"aggregated_value\": \(fmtDouble(aggregatedValue)),\n"
    json     += "  \"timing\": {\n"
    json     += timingEntry("matmul_time", minMatmul,   maxMatmul,   allMatmul,   last: false) + "\n"
    json     += timingEntry("data_prep",  minDataPrep, maxDataPrep, allDataPrep, last: false) + "\n"
    json     += timingEntry("sum",        minSum,      maxSum,      allSum,      last: false) + "\n"
    json     += timingEntry("total",      minTotal,    maxTotal,    allTotal,    last: true)  + "\n"
    json     += "  }\n"
    json     += "}\n"

    do {
        try json.write(toFile: "tmp-cmeta-program-stats.json", atomically: true, encoding: .utf8)
        return true
    } catch {
        return false
    }
}

// MARK: - Timing bookkeeping

struct TimingStats {
    var min: Double = Double.greatestFiniteMagnitude
    var max: Double = 0.0
    var all: [Double]

    init(repeat repeatCount: Int) { all = [Double](repeating: 0, count: repeatCount) }

    mutating func record(_ dt: Double, at idx: Int) {
        all[idx] = dt
        if dt < min { min = dt }
        if dt > max { max = dt }
    }
}

// ===================================================================
// main
// ===================================================================

let args = CommandLine.arguments
var argi = 1

// -------------------------------------------------------------------
print("==================================================================")
print("Testing threads ...")
print("")

let maxThreads = ProcessInfo.processInfo.activeProcessorCount
print("active processor count (max threads) = \(maxThreads)")

let dispatchGroup = DispatchGroup()
let concurrentQueue = DispatchQueue(label: "com.ctuninglabs.thread-test",
                                    attributes: .concurrent)
let printLock = NSLock()

for i in 0..<maxThreads {
    dispatchGroup.enter()
    concurrentQueue.async {
        printLock.lock()
        print("hello from thread \(i) of \(maxThreads)")
        printLock.unlock()
        dispatchGroup.leave()
    }
}
dispatchGroup.wait()
print("")

// -------------------------------------------------------------------
print("==================================================================")
print("Testing crypto ...")
print("")

let message = "hello world"
#if canImport(CryptoKit) || canImport(Crypto)
let messageData = Data(message.utf8)
let sha256Digest = SHA256.hash(data: messageData)
let sha256Hex = sha256Digest.map { String(format: "%02x", $0) }.joined()
print("SHA256(\"\(message)\") = \(sha256Hex)")
#else
print("SHA256 not available on this platform (requires CryptoKit on macOS or swift-crypto on Linux)")
print("SHA256(\"\(message)\") = <skipped>")
#endif
print("")

// -------------------------------------------------------------------
print("==================================================================")
print("Testing basic math ...")
print("")

let mathX = 16.0
print(String(format: "sqrt(%.2f) = %.2f",    mathX, mathX.squareRoot()))
print(String(format: "sin(0.0) = %.2f",      sin(0.0)))
print(String(format: "pow(2.0, 3.0) = %.2f", pow(2.0, 3.0)))
print("")

// -------------------------------------------------------------------
if args.count < 4 {
    printUsage(args[0])
    exit(1)
}

print("==================================================================")
print("Testing naive matmul ...")
print("")

// Parse optional dtype (present only if first remaining arg is not a plain integer)
var dtype = DType.float32
if argi < args.count, !isPositiveIntegerString(args[argi]) {
    guard let d = DType.parse(args[argi]) else {
        fputs("Error: unsupported dtype '\(args[argi])'.\n", stderr)
        printUsage(args[0])
        exit(1)
    }
    dtype = d
    argi += 1
}

// Parse M N K
guard args.count - argi >= 3 else {
    fputs("Error: M N K are required.\n", stderr)
    printUsage(args[0])
    exit(1)
}
guard let m = parsePositiveSize(args[argi]),
      let n = parsePositiveSize(args[argi + 1]),
      let k = parsePositiveSize(args[argi + 2]) else {
    fputs("Error: M N K must be positive integers.\n", stderr)
    exit(1)
}
argi += 3

// Parse optional repeat
var repeatCount = 1
if argi < args.count {
    guard let r = parsePositiveSize(args[argi]) else {
        fputs("Error: repeat must be a positive integer.\n", stderr)
        exit(1)
    }
    repeatCount = r
    argi += 1
}

// Parse optional clean
var clean = false
if argi < args.count {
    guard let c = parseClean(args[argi]) else {
        fputs("Error: clean must be one of 0/1/false/true/no/yes.\n", stderr)
        exit(1)
    }
    clean = c
    argi += 1
}

// Parse optional seed (default: current time)
var seed = UInt32(Date().timeIntervalSince1970) & 0xFFFFFFFF
if argi < args.count {
    guard let s = parseSeed(args[argi]) else {
        fputs("Error: seed must be a non-negative integer.\n", stderr)
        exit(1)
    }
    seed = s
    argi += 1
}

guard argi == args.count else {
    fputs("Error: too many arguments.\n", stderr)
    printUsage(args[0])
    exit(1)
}

let aCount = m * n
let bCount = n * k
let cCount = m * k

var statsMatmul   = TimingStats(repeat: repeatCount)
var statsDataPrep = TimingStats(repeat: repeatCount)
var statsSum      = TimingStats(repeat: repeatCount)
var statsTotal    = TimingStats(repeat: repeatCount)
var aggregatedValue = 0.0

seedRNG(seed)

// Run the typed matmul loop (avoids code-gen overhead of generics for this benchmark)
switch dtype {

case .float32:
    var a = [Float](repeating: 0, count: aCount)
    var b = [Float](repeating: 0, count: bCount)
    fillRandomF32(&a); fillRandomF32(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomF32(&a); fillRandomF32(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulF32(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumF32(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }

case .float64:
    var a = [Double](repeating: 0, count: aCount)
    var b = [Double](repeating: 0, count: bCount)
    fillRandomF64(&a); fillRandomF64(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomF64(&a); fillRandomF64(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulF64(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumF64(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }

case .int64:
    var a = [Int64](repeating: 0, count: aCount)
    var b = [Int64](repeating: 0, count: bCount)
    fillRandomI64(&a); fillRandomI64(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomI64(&a); fillRandomI64(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulI64(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumI64(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }

case .int32:
    var a = [Int32](repeating: 0, count: aCount)
    var b = [Int32](repeating: 0, count: bCount)
    fillRandomI32(&a); fillRandomI32(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomI32(&a); fillRandomI32(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulI32(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumI32(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }

case .int16:
    var a = [Int16](repeating: 0, count: aCount)
    var b = [Int16](repeating: 0, count: bCount)
    fillRandomI16(&a); fillRandomI16(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomI16(&a); fillRandomI16(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulI16(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumI16(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }

case .int8:
    var a = [Int8](repeating: 0, count: aCount)
    var b = [Int8](repeating: 0, count: bCount)
    fillRandomI8(&a); fillRandomI8(&b)
    for r in 0..<repeatCount {
        let totalT0 = nowSeconds()
        var dataPrepDt = 0.0
        if clean {
            let t = nowSeconds(); fillRandomI8(&a); fillRandomI8(&b)
            dataPrepDt = nowSeconds() - t
        }
        let t0 = nowSeconds()
        let c = matmulI8(a, b, m: m, n: n, k: k)
        let matmulDt = nowSeconds() - t0
        let t1 = nowSeconds()
        aggregatedValue += sumI8(c)
        let sumDt = nowSeconds() - t1
        let totalDt = nowSeconds() - totalT0
        statsDataPrep.record(dataPrepDt, at: r)
        statsMatmul.record(matmulDt, at: r)
        statsSum.record(sumDt, at: r)
        statsTotal.record(totalDt, at: r)
    }
}

print("Input:")
print("  dtype  = \(dtype.name)")
print("  M N K  = \(m) \(n) \(k)")
print("  repeat = \(repeatCount)")
print("  clean  = \(clean ? 1 : 0)")
print("  seed   = \(seed)")
print(String(format: "  aggregated_value = %.12f", aggregatedValue))
print("\nTiming (seconds):")
print(String(format: "  matmul_time min = %.9f, max = %.9f",
             statsMatmul.min, statsMatmul.max))
print(String(format: "  data_prep   min = %.9f, max = %.9f",
             statsDataPrep.min, statsDataPrep.max))
print(String(format: "  sum         min = %.9f, max = %.9f",
             statsSum.min, statsSum.max))
print(String(format: "  total       min = %.9f, max = %.9f",
             statsTotal.min, statsTotal.max))
print("")

// -------------------------------------------------------------------
print("==================================================================")
print("Writing stats for cMeta ...")
print("")

let ok = writeStatsJSON(
    dtype:           dtype.name,
    m: m, n: n, k: k,
    repeatCount:     repeatCount,
    clean:           clean,
    seed:            seed,
    minMatmul:       statsMatmul.min,   maxMatmul:   statsMatmul.max,   allMatmul:   statsMatmul.all,
    minDataPrep:     statsDataPrep.min, maxDataPrep: statsDataPrep.max, allDataPrep: statsDataPrep.all,
    minSum:          statsSum.min,      maxSum:      statsSum.max,      allSum:      statsSum.all,
    minTotal:        statsTotal.min,    maxTotal:    statsTotal.max,    allTotal:    statsTotal.all,
    aggregatedValue: aggregatedValue
)

if ok {
    print("Wrote tmp-cmeta-program-stats.json")
} else {
    fputs("Warning: could not write tmp-cmeta-program-stats.json\n", stderr)
}
