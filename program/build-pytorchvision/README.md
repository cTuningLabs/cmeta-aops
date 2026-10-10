# build-pytorchvision: torchvision from source, paired with the torch of the Python

torchvision's compiled operators (`torchvision::nms`, the image decoders) must be built against the exact
torch they run with: a torchvision built or downloaded for another torch loads no operators. This program
builds torchvision in the Python of the run, **against the torch found there**, and checks out the vision
release that pairs with it (PyTorch's numbering, 2.x.y -> 0.(x+15).y: torch 2.14.1 -> torchvision v0.29.1;
a development torch such as 2.15.0a0+git... takes `main`; `--checkout=<tag|branch>` overrides). The
package is versioned as the tag (`BUILD_VERSION`) and requires that torch (`PYTORCH_VERSION`), so a later
`pip install torchvision==0.29.1` finds it satisfied and never swaps the torch.

## One venv for the pair

The torch build, this build and the programs that use the pair share one venv through the same
`--use.python.venv_path=<folder>` (the folder that holds `.venv`):

```bash
V=~/cmeta-tests/torch-pair                                   # any folder of your choice

# torch and torchvision both built from source (CUDA or ROCm as the target says)
cx program run build-pytorch       --compute=cuda --use.python.venv_path=$V      # hours
cx program run build-pytorchvision --compute=cuda --use.python.venv_path=$V      # minutes, paired by itself
cx program run test-pytorch-with-vision --compute=cuda --use.python.venv_path=$V # the pip steps find both satisfied

# torch built, torchvision from PyTorch's wheels
cx program run build-pytorch --compute=cuda --use.python.venv_path=$V
cx program run test-pytorch-with-vision --compute=cuda --use.python.venv_path=$V # tool/pip-torchvision pins the pair

# torch from PyTorch's wheels, torchvision built
cx program run build-pytorchvision --compute=cuda --torch=pip --use.python.venv_path=$V
cx program run test-pytorch-with-vision --compute=cuda --use.python.venv_path=$V
```

Without `--use.python.venv_path` each program takes the shared Python of the machine (cMeta's own, or
the venv it finds), as `test-pytorch-with-vision` always did for the pip pair.

For a CUDA build the torch of that Python must be for the CUDA toolkit of the run: torch does not compile
CUDA operators with a toolkit of another major version than the one it was built for (a torch for CUDA 12
and a CUDA 13 toolkit). The program checks this when it pairs the checkout with the torch, before anything
is cloned, and names the Python it took and the ways out: a Python whose torch fits
(`--use.python.venv_path=<folder>`; a new folder with `--torch=pip` gets PyTorch's wheel for the machine) or
the CPU operators only (`--compute=cpu`).

The pip steps keep the CUDA line of a torch that is installed: `--torch=pip` and the test program replace
neither the torch nor its line unless the request names another (`--use.pip-torch.with.ver=13.2`, a torch
version that is not the installed one), and torchvision, when it comes from PyTorch's wheels, is taken from
the index of the installed torch.

| Parameter | Default | Meaning |
|---|---|---|
| `--checkout` | the pair of the torch found | the vision tag or branch to build |
| `--torch` | the torch already in the Python | `pip`: PyTorch's wheel for the target first (`--torch_version` pins it) |
| `--compute` | `cpu` | `cuda`, `rocm`: the GPU operators are built (`FORCE_CUDA`), for this machine's architectures |
| `--max_jobs` | the build programs' default | compile jobs |
| `--use_cudnn` | off | cuDNN at build time |
| `--clean` | | removes the tree's `build/` first |

The torch built with the wheel route: a torchvision wheel of PyTorch's index is built against PyTorch's own
torch wheel of the same release and CUDA line; with a torch built from source it loads when the versions
and the CUDA major version agree (torchvision checks the latter at import), which the tag build gives.

## Notes

The tree is cloned into the cache (`clone-git-to-cache`), the build runs `pip install --no-build-isolation`
in it, and `cmake` and `ninja` come from cMeta's tools. Windows: do not clone or build as administrator,
the files are then unreadable to the normal user. A build interrupted and restarted may compile more
files when packages appeared in the venv in between (setup.py looks at what is installed).
