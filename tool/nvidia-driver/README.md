# tool/nvidia-driver

The NVIDIA GPU driver: detected by `nvidia-smi`, installed and upgraded with NVIDIA's own packages.

```bash
cx tool setup nvidia-driver --status          # installed, newest for this GPU, outdated or not
cx tool upgrade nvidia-driver                 # the newest driver for this GPU
cx tool upgrade nvidia-driver --version=615   # the newest of a branch (or 615.78.08, one release)
cx tool install nvcc                          # then the newest CUDA toolkit this driver runs
```

## Which driver

- **Windows:** the drivers NVIDIA's download service lists for the GPU (the driver search of nvidia.com), on both
  branches: the production branch and the new feature branch, which runs the newest CUDA. The product is found by the
  name `nvidia-smi` gives in NVIDIA's product list.
- **Linux:** NVIDIA's archive of `.run` installers (`download.nvidia.com/XFree86/Linux-x86_64/`).
- **Older GPUs** stop at a branch (`legacy_branches` in `_desc.yaml`): Maxwell, Pascal and Volta at 580, Kepler at
  470, Fermi at 390. The newest release of that branch is taken.
- **CUDA:** a driver branch runs the CUDA of the same line (`cuda_of_branch`): CUDA 13.4 needs R615, 13.2 R595. Since
  CUDA 13.1 on Windows and 13.4 on Linux the toolkit installers carry no driver, so the driver comes from here and
  the toolkit from `tool/nvcc`.

## How it is installed

- **Windows:** the package is downloaded into the cache entry and its signature checked (signed by NVIDIA
  Corporation; NVIDIA publishes no checksum for it). It then runs with `-s -noreboot` and administrator rights: a UAC
  prompt, or nothing in an elevated terminal. A quiet run (`-q`) never asks, so it refuses in a terminal that is not
  elevated. The screen may go dark for a moment.
- **Linux:** the `.run` installer is checked against its sha256 and run with sudo (`sudo -n` in a quiet run):
  `--silent --dkms --no-x-check --skip-module-load --rebuild-initramfs` and the kernel module type in use (open or
  proprietary; open for Turing and newer when none runs). The new driver is installed next to the running one, and
  the next boot loads it. The initramfs is rebuilt: one that carries the old modules would load the old
  driver again. Until the reboot `nvidia-smi` may fail, while the module on disk (`modinfo nvidia`) already
  has the new version: the installed version detected here.
- **A module that does not build** against the kernel is named with its first compiler error, and the driver stays as
  it was (NVIDIA's installer stops before it removes anything). A newer kernel can be ahead of a driver release: an
  older branch may build (`--version=<branch>`).
- **Refused on Linux:**
  - a driver that came from the distribution's packages: upgrade it with them;
  - Secure Boot on: the module built here is not signed.

After an install the cached record of `tool/cuda` (the CUDA version of the driver) is dropped, so the next run that
needs it, `tool/nvcc` included, reads the new driver.

**Windows Update** may replace a newer feature-branch driver with an older production one from the computer's
maker. If a driver went back on its own, `--status` shows it.
