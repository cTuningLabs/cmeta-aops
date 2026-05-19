@echo off
REM Compilation script for CUDA Matrix Multiplication Program on Windows
REM This script compiles the CUDA program using nvcc

set NVCC=nvcc
set OUTPUT=program.exe
set SRC_DIR=src

REM Check if nvcc is available
where nvcc >nul 2>nul
if errorlevel 1 (
    echo Error: nvcc compiler not found
    echo Please install NVIDIA CUDA Toolkit from https://developer.nvidia.com/cuda-downloads
    exit /b 1
)

echo Compiling CUDA program...
echo.

REM Compile with optimizations
%NVCC% -O3 -o %OUTPUT% %SRC_DIR%\program.cu %SRC_DIR%\matmul.cu -lm -lssl -lcrypto -fopenmp

if errorlevel 1 (
    echo.
    echo Compilation failed!
    exit /b 1
)

echo.
echo Compilation successful! Output: %OUTPUT%
echo.
echo To run the program, use:
echo   %OUTPUT% float32 256 256 256
echo   %OUTPUT% float64 512 512 512
echo   %OUTPUT% int32 1024 1024 1024
echo.
echo For more information, see README.md
pause
