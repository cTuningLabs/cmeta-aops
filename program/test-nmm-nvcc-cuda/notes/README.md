# CUDA Matrix Multiplication Program

This program demonstrates CUDA GPU-accelerated matrix multiplication along with CPU-based tests for threading, cryptography, and basic math.

## Features

1. **OpenMP Thread Test** - Tests CPU threading capabilities
2. **OpenSSL Crypto Test** - Tests SHA256 hashing
3. **Basic Math Test** - Tests sqrt, sin, pow functions
4. **CUDA Matrix Multiplication** - GPU-accelerated matrix operations for:
   - float32 (default)
   - float64
   - int64
   - int32
   - int16
   - int8

## Prerequisites

- NVIDIA CUDA Toolkit (nvcc compiler)
- OpenMP support
- OpenSSL development libraries
- C runtime libraries

### On Windows with CUDA Toolkit installed:

```bash
# Verify nvcc is installed
nvcc --version
```

### On Linux:

```bash
# Ubuntu/Debian
sudo apt-get install nvidia-cuda-toolkit libssl-dev libomp-dev

# CentOS/RHEL
sudo yum install cuda-toolkit openssl-devel libomp-devel
```

## Compilation

### Single Command (Recommended)

```bash
nvcc -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

### With More Verbose Output

```bash
nvcc -O3 -keep -Xcompiler "/W3" -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

### Explanation of Compiler Flags

| Flag | Meaning |
|------|---------|
| `-O3` | Enable all optimizations |
| `-o program` | Output executable name |
| `src/program.cu src/matmul.cu` | Source files (CUDA files) |
| `-lm` | Link math library |
| `-lssl -lcrypto` | Link OpenSSL libraries |
| `-fopenmp` | Enable OpenMP support |

## Usage

### Basic Matrix Multiplication (256x256 matrices)

```bash
./program float32 256 256 256
```

### With Specific Data Type

```bash
# Float64
./program float64 512 512 512

# Int32
./program int32 1024 1024 1024

# Int8
./program int8 2048 2048 2048
```

### With Repeat Iterations

```bash
# Run matmul 10 times
./program float32 256 256 256 10
```

### With Data Regeneration (clean=true)

```bash
# Regenerate random data between iterations
./program float32 256 256 256 10 1
```

### With Custom Seed

```bash
# Use seed value 42
./program float32 256 256 256 10 1 42
```

## Program Output

The program will display:

1. **OpenMP Test**: Thread count and thread IDs
2. **Crypto Test**: OpenSSL version and SHA256 hash
3. **Math Test**: Results of sqrt, sin, pow operations
4. **Matrix Multiplication**: 
   - Input dimensions (M x N) * (N x K)
   - Timing for each operation
   - Min/max timings across iterations
   - Aggregated result value

5. **JSON Results**: Saves `tmp-cmeta-program-stats.json` with detailed timing statistics

### Example Output

```
==================================================================
Testing OpenMP (CPU threads) ...

_OPENMP = 201511
max threads = 8
hello from thread 0 of 8
hello from thread 1 of 8
...

==================================================================
Testing crypto (OpenSSL SHA256) ...

OpenSSL version: OpenSSL 1.1.1k
SHA256("hello world") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824

==================================================================
Testing basic math ...

sqrt(16.00) = 4.00
sin(0.0) = 0.00
pow(2.0, 3.0) = 8.00

==================================================================
Testing CUDA matrix multiplication (GPU-accelerated) ...

Input:
  dtype  = float32
  M N K  = 256 256 256
  repeat = 1
  clean  = 0
  seed   = 1234567890
  aggregated_value = 3286.440430

Timing (seconds):
  matmul_time min = 0.002143530, max = 0.002143530
  data_prep   min = 0.000000000, max = 0.000000000
  sum         min = 0.000001234, max = 0.000001234
  total       min = 0.002144764, max = 0.002144764
```

## Compilation Troubleshooting

### "nvcc: command not found"
- Install CUDA Toolkit from https://developer.nvidia.com/cuda-downloads
- Add nvcc to PATH or use full path

### "Cannot find -lssl" or "-lcrypto"
**Windows**: Install OpenSSL from https://slproweb.com/products/Win32OpenSSL.html
**Linux**: `sudo apt-get install libssl-dev`

### "Cannot find -fopenmp"
**Windows**: Use `\fopenmp` instead or `-fno-openmp` to disable
**Linux**: `sudo apt-get install libomp-dev`

### CUDA Compute Capability
To target specific GPU architectures:
```bash
nvcc -arch=sm_70 -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

Valid architectures: sm_35, sm_50, sm_60, sm_70, sm_80, sm_90

## Performance Notes

- Matrix multiplication is offloaded to GPU using CUDA kernels
- Uses 16x16 thread blocks for efficient GPU utilization
- Each thread computes one output element using dot product
- Timing includes GPU memory transfers (host ↔ device)
- For optimal performance, use large matrix sizes (512+)
- OpenMP threads run on CPU independently from GPU operations

## Files

- `matmul.cu` - CUDA kernels and GPU implementations
- `matmul.h` - Function declarations
- `program.cu` - Main program with CPU tests and timing

## License

Copyright (C) 2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
