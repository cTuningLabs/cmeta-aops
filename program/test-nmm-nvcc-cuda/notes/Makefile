# Makefile for CUDA Matrix Multiplication Program
# Builds the program using nvcc compiler

# Compiler
NVCC := nvcc

# Compiler flags
NVCC_FLAGS := -O3
NVCC_LIBS := -lm -lssl -lcrypto -fopenmp

# Source files
SOURCES := src/program.cu src/matmul.cu

# Output executable
OUTPUT := program

# Default target
all: $(OUTPUT)

# Build the program
$(OUTPUT): $(SOURCES)
	$(NVCC) $(NVCC_FLAGS) -o $(OUTPUT) $(SOURCES) $(NVCC_LIBS)
	@echo "Build successful: $(OUTPUT)"

# Run with default parameters (256x256 matrix, float32)
run: $(OUTPUT)
	./$(OUTPUT) float32 256 256 256

# Run with larger matrices (512x512)
run-large: $(OUTPUT)
	./$(OUTPUT) float32 512 512 512

# Run with multiple iterations (10x)
run-repeat: $(OUTPUT)
	./$(OUTPUT) float32 256 256 256 10

# Run with different data types
run-f64: $(OUTPUT)
	./$(OUTPUT) float64 256 256 256

run-i32: $(OUTPUT)
	./$(OUTPUT) int32 256 256 256

run-i8: $(OUTPUT)
	./$(OUTPUT) int8 256 256 256

# Clean build artifacts
clean:
	@rm -f $(OUTPUT)
	@echo "Cleaned"

# Clean and rebuild
rebuild: clean all

# Help target
help:
	@echo "CUDA Matrix Multiplication Program - Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  all           - Build the program (default)"
	@echo "  run           - Build and run with default parameters (256x256 float32)"
	@echo "  run-large     - Build and run with larger matrices (512x512)"
	@echo "  run-repeat    - Build and run with 10 iterations"
	@echo "  run-f64       - Build and run with float64"
	@echo "  run-i32       - Build and run with int32"
	@echo "  run-i8        - Build and run with int8"
	@echo "  clean         - Remove build artifacts"
	@echo "  rebuild       - Clean and rebuild"
	@echo "  help          - Display this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make run                # Default float32 256x256"
	@echo "  make run-large          # Larger matrices"
	@echo "  make run-repeat         # Multiple iterations for timing"

.PHONY: all run run-large run-repeat run-f64 run-i32 run-i8 clean rebuild help
