# tool/nvidia-container-toolkit

The NVIDIA Container Toolkit lets a container on a Linux engine use the NVIDIA GPU of its machine:
`docker run --gpus all` needs its runtime hook, `podman run --device nvidia.com/gpu=all` its CDI description of
the GPUs. Docker Desktop on Windows passes the GPU through WSL2 by itself and needs none of it.

```
cx tool setup nvidia-container-toolkit                 # detect nvidia-ctk (its version)
cx tool setup nvidia-container-toolkit --install -q    # Linux: install the pinned version and configure the engines (sudo)
cx tool setup nvidia-container-toolkit --versions      # the releases (github.com/NVIDIA/nvidia-container-toolkit)
```

What `--install` does on Linux (`api_v1.py`):

- adds NVIDIA's package repository and its signing key (the stable channel of nvidia.github.io/libnvidia-container);
- installs the four packages of the version asked for (`default_version` in `_desc.yaml` when none is), pinned -
  apt on Debian and Ubuntu, dnf / yum / tdnf / zypper on the RPM distributions;
- configures the engines that are there: docker gets the `nvidia` runtime and is restarted
  (`nvidia-ctk runtime configure --runtime=docker`), podman reads the CDI file of the GPUs
  (`nvidia-ctk cdi generate`; the packages of 1.18 and newer also keep `/var/run/cdi/nvidia.yaml` current).

Without a passwordless sudo the configuration commands are printed for you to run. The NVIDIA driver must be
installed first (`nvidia-smi` works).

`get-host--docker` checks it before it makes a CUDA instance on Linux (`--on=docker` or `--on=podman` with a
CUDA program, `--compute=cuda`): an engine that cannot give a container the GPU fails there with this cure, instead
of a container that starts without its GPU.

Remove it with the distribution's package manager (`sudo apt-get remove nvidia-container-toolkit
nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1`), then
`/etc/apt/sources.list.d/nvidia-container-toolkit.list` and the `nvidia` runtime entry of `/etc/docker/daemon.json`.
