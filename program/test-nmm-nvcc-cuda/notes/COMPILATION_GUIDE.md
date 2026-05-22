# CUDA Compilation Guide

Quick reference for compiling the CUDA matrix multiplication program.

## Quick Start

### Windows with CUDA Toolkit

**Using batch script:**
```bash
compile.bat
```

**Using PowerShell:**
```powershell
.\compile.ps1
```

**Using command line (cmd):**
```cmd
nvcc -O3 -o program.exe src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

**Using Makefile (with MinGW/GNU make installed):**
```bash
make
make run
```

### Linux / macOS

**Using Makefile:**
```bash
make
make run
```

**Using command line:**
```bash
nvcc -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

## Complete Compilation Command

```bash
nvcc -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

### Compiler Flags Breakdown

```
nvcc                 # NVIDIA CUDA compiler
-O3                  # Optimization level 3 (maximum)
-o program           # Output executable name
src/program.cu       # Main program source file
src/matmul.cu        # CUDA kernels and GPU implementation
-lm                  # Link math library (for sqrt, sin, pow)
-lssl -lcrypto       # Link OpenSSL libraries (for SHA256)
-fopenmp             # Enable OpenMP support (for threading)
```

## Alternative Compilation Options

### With Architecture Specification (for specific GPU)

```bash
nvcc -arch=sm_70 -O3 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

Supported architectures:
- `sm_35` - Kepler, GTX 750
- `sm_50` - Maxwell, GTX 960/970/980
- `sm_60` - Pascal, GTX 1060/1070/1080
- `sm_70` - Volta, V100
- `sm_80` - Ampere, RTX 30 series
- `sm_90` - Ada, RTX 40 series

### With Debug Symbols

```bash
nvcc -g -G -O0 -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

### With Verbose Output

```bash
nvcc -O3 -v -o program src/program.cu src/matmul.cu -lm -lssl -lcrypto -fopenmp
```

### Separate Compilation

```bash
# Compile CUDA kernels to object file
nvcc -c -O3 -o matmul.o src/matmul.cu

# Compile main program
nvcc -c -O3 -o program.o src/program.cu

# Link together
nvcc -o program matmul.o program.o -lm -lssl -lcrypto -fopenmp
```

## Running After Compilation

### Basic Run
```bash
./program float32 256 256 256
```

### With Multiple Iterations
```bash
./program float32 256 256 256 10
```

### With Data Regeneration
```bash
./program float32 256 256 256 10 1
```

### With Specific Seed
```bash
./program float32 256 256 256 10 1 42
```

### Different Data Types
```bash
./program float64 512 512 512      # 64-bit floating point
./program int64 1024 1024 1024     # 64-bit integer
./program int32 1024 1024 1024     # 32-bit integer
./program int16 2048 2048 2048     # 16-bit integer
./program int8 2048 2048 2048      # 8-bit integer
```

## Environment Setup

### Windows - Ensure CUDA Toolkit is installed

1. Download from: https://developer.nvidia.com/cuda-downloads
2. Install CUDA Toolkit (default location: C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x)
3. Add to PATH (usually done automatically)
4. Verify: `nvcc --version`

### Windows - Install OpenSSL

Option 1: Using Visual Studio package
- Include OpenSSL during CUDA Toolkit installation

Option 2: Pre-built binaries
- Download from https://slproweb.com/products/Win32OpenSSL.html
- Install to default location

Option 3: Using package manager (vcpkg)
```bash
vcpkg install openssl
```

### Linux (Ubuntu/Debian)

```bash
# Update package manager
sudo apt-get update

# Install CUDA Toolkit
sudo apt-get install nvidia-cuda-toolkit

# Install development libraries
sudo apt-get install libssl-dev libomp-dev

# Verify installation
nvcc --version
openssl version
```

### Linux (CentOS/RHEL)

```bash
# Install CUDA Toolkit
sudo yum install cuda-toolkit

# Install development libraries
sudo yum install openssl-devel libomp-devel

# Verify installation
nvcc --version
openssl version
```

### macOS

```bash
# Using Homebrew
brew install cuda-toolkit openssl

# Add to PATH in ~/.zprofile or ~/.bash_profile
export PATH=/opt/homebrew/opt/cuda-toolkit/bin:$PATH

# Verify
nvcc --version
```

## Troubleshooting

### Issue: "nvcc: command not found"
**Solution:**
- Ensure CUDA Toolkit is installed
- Add nvcc to PATH: `export PATH=/usr/local/cuda/bin:$PATH`
- On Windows, run from Developer Command Prompt or add to PATH

### Issue: "cannot find -lssl" or "-lcrypto"
**Solution:**
- Install OpenSSL development libraries
- Windows: https://slproweb.com/products/Win32OpenSSL.html
- Linux: `sudo apt-get install libssl-dev`
- macOS: `brew install openssl`

### Issue: "cannot find -fopenmp"
**Solution:**
- Install OpenMP: `sudo apt-get install libomp-dev` (Linux)
- Or compile without OpenMP: remove `-fopenmp` flag

### Issue: "CUDA capability doesn't support"
**Solution:**
- Reduce compute capability: `nvcc -arch=sm_50 ...`
- Or update GPU drivers/CUDA Toolkit

### Issue: Compilation succeeds but program crashes
**Solution:**
- Ensure NVIDIA GPU drivers are updated
- Try with smaller matrices first
- Check GPU memory with `nvidia-smi`

## Build Scripts Summary

| File | Purpose | Usage |
|------|---------|-------|
| `compile.bat` | Windows batch compilation | `compile.bat` |
| `compile.ps1` | Windows PowerShell compilation | `.\compile.ps1` |
| `Makefile` | Unix/Linux make build | `make` |

## Performance Tips

1. **Use larger matrices** (512+ size) to fully utilize GPU
2. **Run multiple iterations** with `-repeat` flag for consistent timing
3. **Profile the code** to identify bottlenecks
4. **Check GPU usage** with `nvidia-smi` while running
5. **Minimize host-device transfers** by batching operations

## Further Reading

- CUDA Documentation: https://docs.nvidia.com/cuda/
- OpenSSL Documentation: https://www.openssl.org/docs/
- OpenMP Documentation: https://www.openmp.org/
