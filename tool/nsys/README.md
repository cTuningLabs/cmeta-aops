# tool/nsys: NVIDIA Nsight Systems' command line

`cx tool setup nsys` finds `nsys` where a CUDA toolkit or an Nsight Systems install put it (`extra_paths` of
`_desc.yaml`: a toolkit's `bin`, `nsight-systems*/bin`, `/opt/nvidia/nsight-systems/*/bin`, the Windows
installer's folder). When none is found, or not the version asked, it installs Nsight Systems without root from
NVIDIA's CUDA redistributable archives (https://developer.download.nvidia.com/compute/cuda/redist): the component
`nsight_systems` of a CUDA release, checked against the sha256 of NVIDIA's list and unpacked into the tool's cache
entry (`content/<CUDA release>/target-<platform>/nsys`). tool/nvcc's `redist.py` reads NVIDIA's lists.

```
cx tool setup nsys                          # found, else the Nsight Systems of the newest CUDA this driver runs
cx tool setup nsys --version=2026.1.3       # the newest CUDA release that carries it (a prefix or the full version)
cx tool setup nsys --version=latest         # the Nsight Systems of the newest CUDA this driver runs
cx tool setup nsys --status                 # what is found here against that newest one
```

Programs ask for it with `--profile_cuda` (task/setup-run): `nsys profile --trace=cuda,nvtx`, then the summary of
the CUDA kernels (`nsys stats --report cuda_gpu_kern_sum`). An older Nsight Systems may record no CUDA activity on a
newer GPU or driver - its report then "does not contain CUDA kernel data" (or "CUDA trace data"): ask for a newer
one for the run, `--use.nsys.version=latest`.

Linux (x86_64, arm64) and Windows (x86_64) have archives; macOS has no Nsight Systems command line.
