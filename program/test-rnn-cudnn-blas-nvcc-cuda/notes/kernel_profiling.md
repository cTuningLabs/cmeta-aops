Time (%)  Total Time (ns)  Instances  Avg (ns)  Med (ns)  Min (ns)  Max (ns)  StdDev (ns)                                                  Name
--------  ---------------  ---------  --------  --------  --------  --------  -----------  ----------------------------------------------------------------------------------------------------
    26.2          1047350         50   20947.0   16510.0     15678     40699       9043.6  void cutlass::Kernel2<cutlass_80_tensorop_s1688gemm_64x64_32x6_nn_align4>(T1::Params)
    21.9           876110         40   21902.8   19357.5     16830     42875       6185.7  void cutlass::Kernel2<cutlass_80_tensorop_s1688gemm_64x64_32x6_tn_align4>(T1::Params)
    11.6           462820          1  462820.0  462820.0    462820    462820          0.0  cudnn::initstates(unsigned long long, curandStateXORWOW *)
    11.1           441767          8   55220.9   54777.0     43675     71927       8026.3  void cutlass::Kernel2<cutlass_80_tensorop_s1688gemm_64x64_16x6_tn_align4>(T1::Params)
     8.3           329751          4   82437.8   82518.0     78934     85781       2872.1  void cutlass::Kernel2<cutlass_80_tensorop_s1688gemm_128x128_16x5_nt_align4>(T1::Params)
     8.1           324758         40    8118.9    5503.5      3615     23773       5231.7  void elemWiseRNNcell<float, float, float, (cudnnRNNMode_t)0, (cudnnRNNBiasMode_t)2>(int, int, int,
     6.7           269502         40    6737.6    5167.0      4799     22205       4462.6  void RNN_elementWise_bp1<float, float, float>(int, int, int, int, T1 *, T1 *, T1 *, T2 *, int, cudn
     3.0           118867         14    8490.5    2912.0      1472     29564       9236.7  void initGPUData_ker<float>(T1 *, int, T1)
     1.7            66904          2   33452.0   33452.0     31068     35836       3371.5  void GENERIC_elementWise_bp2<float, float, float, (int)1, (cudnnRNNBiasMode_t)2>(int, int, T1 *, T1
     1.5            58329          2   29164.5   29164.5     23901     34428       7443.7  void cutlass::Kernel2<cutlass_80_tensorop_s1688gemm_256x64_16x4_nt_align4>(T1::Params)


Sure! Let me break down the anatomy of these kernel names:

---

### CUTLASS GEMM Kernels (the `cutlass::Kernel2<...>` ones)

Taking `cutlass_80_tensorop_s1688gemm_64x64_32x6_nn_align4` as an example:

| Part | Value | Meaning |
|---|---|---|
| `80` | 80 | Target architecture — **SM 8.0** (Ampere) |
| `tensorop` | — | Uses **Tensor Cores** |
| `s` | s | Data type: **s**ingle precision (FP32) |
| `1688` | 16×8×8 | Tensor Core **warp tile shape** (M×N×K) |
| `gemm` | — | General Matrix Multiply |
| `64x64` | 64×64 | **Thread block tile** size (M×N output per CTA) |
| `32x6` | 32, 6 | **K tile** × **pipeline stages** (prefetch depth) |
| `nn` | nn | Matrix layouts: **N**on-transposed × **N**on-transposed |
| `tn` | tn | **T**ransposed input × **N**on-transposed output |
| `nt` | nt | **N**on-transposed × **T**ransposed |
| `align4` | 4 | Memory alignment in elements (4 × 4 bytes = 16B) |

The layout suffix (`nn`, `tn`, `nt`) maps directly to RNN operations:
- `nn` → forward pass weight multiply
- `tn` → backward pass weight gradient
- `nt` → backward pass input gradient

---

### RNN Element-wise Kernels

**`elemWiseRNNcell<float, float, float, (cudnnRNNMode_t)0, (cudnnRNNBiasMode_t)2>`**

| Part | Meaning |
|---|---|
| `float, float, float` | input type, output type, compute type — all FP32 |
| `RNNMode_t)0` | cell type **0 = RELU** (matches your `-cellMode0`) |
| `RNNBiasMode_t)2` | bias mode **2 = DOUBLE_BIAS** |

**`RNN_elementWise_bp1`** — backward pass phase 1 (gradient through activation)

**`GENERIC_elementWise_bp2`** — backward pass phase 2 (gradient through bias)

---

### Other Kernels

| Kernel | Meaning |
|---|---|
| `initstates(unsigned long long, curandStateXORWOW*)` | Initializes **dropout random state** using XORWOW RNG — runs once, hence 1 instance |
| `initGPUData_ker<float>` | Fills GPU buffers with initial data (setup cost) |

---

### Why the tile size variants (`64x64`, `128x128`, `256x64`)?

CUTLASS automatically selects different tile sizes for different matrix shapes within the same RNN:
- **128×128** — large square matrices (hidden→hidden, most efficient)
- **64×64** — smaller or non-square multiplications
- **256×64** — tall/skinny matrices (e.g. input projection)

The biggest time consumers (`26% + 22%`) are the core GEMM ops using Tensor Cores on SM80, which is exactly what you want to see for a well-utilized GPU.

