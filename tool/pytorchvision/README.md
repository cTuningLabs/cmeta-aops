# pytorchvision

torchvision as a cMeta tool, the mirror of `pytorch`: detected when the Python of the run has it (built
earlier, or PyTorch's wheel), built from source by [program/build-pytorchvision](../../program/build-pytorchvision/README.md)
otherwise - against the torch of that Python, at the vision release that pairs with it (torch 2.14.1 gives
v0.29.1; `--version=0.29.1` names the release instead).

```bash
V=~/cmeta-tests/torch-pair
cx tool setup pytorch        --with.compute=cuda --use.python.venv_path=$V                  # torch from source (hours)
cx tool setup pytorchvision  --with.compute=cuda --use.python.venv_path=$V                  # torchvision against it (minutes)
cx tool setup pytorchvision  --with.compute=cuda --with.torch=pip --use.python.venv_path=$V # PyTorch's wheel torch first
cx program run test-pytorch-with-vision --compute=cuda --use.python.venv_path=$V            # uses the pair as it is
```

The same `--use.python.venv_path` on every run keeps the pair in one venv. Without it the tool works in the
shared Python of the machine, like `pytorch`. A tool setup takes the target as `--with.compute` (a program run
takes `--compute`).

| Option | Meaning |
|---|---|
| `--version=<x.y.z>` | the vision release to build (its tag `v<x.y.z>`); the default is the pair of the torch found |
| `--with.torch=pip` | PyTorch's wheel torch for the target into the Python before the build |
| `--with.compute=cuda` | the target (`cpu` when absent) |
| `--with.clean`, `--with.recompile` | passed to the build program |
