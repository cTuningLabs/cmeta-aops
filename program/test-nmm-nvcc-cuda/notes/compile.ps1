# PowerShell compilation script for CUDA Matrix Multiplication Program on Windows
# This script compiles the CUDA program using nvcc

param(
    [string]$Configuration = "Release"
)

$NVCC = "nvcc"
$OUTPUT = "program.exe"
$SRC_DIR = "src"
$NVCC_FLAGS = "-O3"
$LIBS = "-lm -lssl -lcrypto -fopenmp"

Write-Host "CUDA Matrix Multiplication Program - Compiler Script" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""

# Check if nvcc is available
$nvccPath = Get-Command $NVCC -ErrorAction SilentlyContinue
if (-not $nvccPath) {
    Write-Host "Error: nvcc compiler not found" -ForegroundColor Red
    Write-Host "Please install NVIDIA CUDA Toolkit from https://developer.nvidia.com/cuda-downloads" -ForegroundColor Yellow
    exit 1
}

Write-Host "NVCC path: $($nvccPath.Source)" -ForegroundColor Cyan
Write-Host ""

# Display compilation details
Write-Host "Compilation Configuration:" -ForegroundColor Cyan
Write-Host "  Output:        $OUTPUT"
Write-Host "  Sources:       $SRC_DIR\program.cu $SRC_DIR\matmul.cu"
Write-Host "  NVCC flags:    $NVCC_FLAGS"
Write-Host "  Libraries:     $LIBS"
Write-Host ""

# Compile
Write-Host "Compiling..." -ForegroundColor Yellow
$compileCmd = "$NVCC $NVCC_FLAGS -o $OUTPUT $SRC_DIR\program.cu $SRC_DIR\matmul.cu $LIBS"
Write-Host "Command: $compileCmd" -ForegroundColor Gray
Write-Host ""

Invoke-Expression $compileCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Compilation successful!" -ForegroundColor Green
    Write-Host "Output: $OUTPUT" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage examples:" -ForegroundColor Yellow
    Write-Host "  .\$OUTPUT float32 256 256 256"
    Write-Host "  .\$OUTPUT float64 512 512 512"
    Write-Host "  .\$OUTPUT int32 1024 1024 1024"
    Write-Host "  .\$OUTPUT float32 256 256 256 10 1 42"
    Write-Host ""
    Write-Host "For more information, see README.md" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "Compilation failed!" -ForegroundColor Red
    exit 1
}
