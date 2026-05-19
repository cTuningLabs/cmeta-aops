# Quick Start Guide

## 30-Second Setup

### Windows
```batch
compile.bat
program.exe float32 256 256 256
```

### Linux/macOS
```bash
make
./program float32 256 256 256
```

## One-Line Compilation

```bash
nvcc -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

## What Gets Compiled

**matmul.cu** - CUDA GPU kernels for:
- Matrix multiplication (float32, float64, int64, int32, int16, int8)
- GPU memory management (cudaMalloc, cudaMemcpy)
- Host-device data transfer

**program.cu** - Main program with:
- OpenMP thread test (CPU)
- OpenSSL SHA256 crypto test (CPU)
- Basic math test (CPU - sqrt, sin, pow)
- Matrix multiplication timing and benchmarking (GPU)

## Program Architecture

```
┌─────────────────────────────────┐
│     program.cu (Host/CPU)       │
├─────────────────────────────────┤
│ • Read command-line arguments   │
│ • Run CPU tests (threads, etc)  │
│ • Allocate host memory          │
│ • Call matmul functions         │
└────────────────┬────────────────┘
                 │
    ┌────────────▼────────────┐
    │   matmul.cu (GPU)       │
    ├─────────────────────────┤
    │ • Allocate GPU memory   │
    │ • Copy data H→D         │
    │ • Launch CUDA kernels   │
    │ • Copy results D→H      │
    │ • Free GPU memory       │
    └─────────────────────────┘
```

## Test Breakdown

### 1. OpenMP Thread Test
Displays available CPU threads and their IDs.
```
_OPENMP = 201511
max threads = 8
hello from thread 0 of 8
hello from thread 1 of 8
...
```

### 2. OpenSSL Crypto Test
Computes SHA256 hash of "hello world".
```
OpenSSL version: OpenSSL 1.1.1k
SHA256("hello world") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
```

### 3. Basic Math Test
Tests standard math library functions.
```
sqrt(16.00) = 4.00
sin(0.0) = 0.00
pow(2.0, 3.0) = 8.00
```

### 4. CUDA Matrix Multiplication
GPU-accelerated computation: (M × N) × (N × K) = M × K
```
Matrix sizes:   M=256, N=256, K=256
Execution time: ~2-3ms on modern GPU
```

## Usage Examples

### Default (256×256 float32)
```bash
./program float32 256 256 256
```

### Larger matrices (performance testing)
```bash
./program float32 1024 1024 1024
```

### Multiple iterations (for timing statistics)
```bash
./program float32 256 256 256 10
```

### Different data types
```bash
./program float64 512 512 512      # Double precision
./program int32 1024 1024 1024     # 32-bit integers
./program int8 2048 2048 2048      # 8-bit integers
```

### Regenerate data each iteration
```bash
./program float32 256 256 256 10 1
```

### With specific random seed
```bash
./program float32 256 256 256 10 1 42
```

## Output Files

- `tmp-cmeta-program-stats.json` - Detailed timing statistics in JSON format

Example JSON output:
```json
{
  "input": {
    "dtype": "float32",
    "M": 256,
    "N": 256,
    "K": 256,
    "repeat": 1,
    "clean": 0,
    "seed": 1234567890
  },
  "aggregated_value": 3286.440430,
  "timing": {
    "matmul_time": {
      "min": 0.002143530,
      "max": 0.002143530,
      "all": [0.002143530]
    },
    ...
  }
}
```

## GPU Memory Requirements

| Matrix Size | float32 | float64 | int8 |
|-------------|---------|---------|------|
| 256×256 | ~256MB | ~512MB | ~64MB |
| 512×512 | ~1GB | ~2GB | ~256MB |
| 1024×1024 | ~4GB | ~8GB | ~1GB |
| 2048×2048 | ~16GB | ~32GB | ~4GB |

## Typical Performance

| Operation | Time |
|-----------|------|
| Data transfer (host→device) | ~0.5-1ms |
| CUDA kernel (256×256) | ~0.5-1ms |
| Data transfer (device→host) | ~0.5-1ms |
| Total round-trip | ~2-3ms |

**Note:** Actual times depend on GPU capabilities and system load.

## Files Reference

```
program/
├── src/
│   ├── program.cu          # Main program (CPU + GPU coordination)
│   ├── matmul.cu           # CUDA kernels and implementations
│   └── matmul.h            # Function declarations
├── Makefile                # For Unix/Linux/macOS
├── compile.bat             # For Windows (batch)
├── compile.ps1             # For Windows (PowerShell)
├── README.md               # Full documentation
├── COMPILATION_GUIDE.md    # Detailed compilation steps
└── QUICK_START.md          # This file
```

## Common Commands Reference

```bash
# Compile
nvcc -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp

# Run basic test
./program float32 256 256 256

# Run with timing iterations
./program float32 256 256 256 10

# Run larger matrices for GPU load
./program float64 1024 1024 1024

# Using Makefile
make              # compile
make run          # compile and run default
make run-large    # compile and run larger matrices
make clean        # remove build files
```

## Next Steps

1. **Compile**: Use one of the provided scripts or commands
2. **Run**: Execute with desired matrix size and parameters
3. **Analyze**: Check output and `tmp-cmeta-program-stats.json`
4. **Optimize**: Adjust BLOCK_SIZE in matmul.cu for your GPU
5. **Profile**: Use `nvidia-smi` to monitor GPU usage

## Getting Help

- Check `README.md` for detailed documentation
- See `COMPILATION_GUIDE.md` for troubleshooting
- Review comments in `src/matmul.cu` for kernel details
- Run `make help` (Linux/macOS) for build options
