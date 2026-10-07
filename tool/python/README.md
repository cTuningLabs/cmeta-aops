# python — the Python interpreter, with its virtual environment

`cx tool setup python` finds or makes a Python for the tasks and programs that need one, and
records it in the cMeta cache so that later requests reuse it. By default a request wants a Python
**in a virtual environment** (`with.venv`, on) **with pip** (`with.pip`, on): packages that tasks
install (`cx tool setup pip --with.package=numpy`) go into that environment and nowhere else.

```bash
cx tool setup python                               # the default Python for this machine
cx tool setup python --version=3.12                # a Python 3.12 (3.12.x)
cx tool setup python --version=">=3.10,<3.14"      # a range, in the style of pip
cx tool setup python --with.venv_path=d:\work99    # the venv d:\work99\.venv (made if missing)
cx tool setup python --with.venv_here              # the venv .venv of the current folder
cx tool setup python --with.here                   # a Python already in a venv of the current folder
cx tool setup python --with.venv-                  # a Python without a venv (the system's)
cx tool setup python --tool_path="{{sys.executable}}"   # this very Python (the one cMeta runs on)
cx tool setup python --versions                    # the versions uv can install
```

Inside a task or a program, the same options reach the Python through the storage key `python`:
`cxt test-python-numpy --use.python.version=3.12 --use.python.with.venv_path=d:\work99`. The
venv itself is made by `task/venv` with `uv venv --seed [--python <version>]`, so a version that is
not installed is downloaded by uv.

## Which Python a request gets

1. **Detection first.** Pythons on `PATH` are considered, with the Python cMeta itself runs on in
   front. Only Pythons in a virtual environment that has pip remain (unless `with.venv` is off).
   So when `cx` runs from a venv with pip, a plain request detects that venv and registers it:
   from then on the packages tasks install extend the user's own environment, by design.
2. **A new venv** when nothing was detected: in the tool's cache entry (`task--setup--python--<uid>/.venv`),
   with the requested version or uv's default.
3. **The cache** before all that: a request first looks for an entry whose parameters contain its
   own (name, version, `with.venv`, `with.pip`, `venv_path`). With several candidates, the highest
   version wins in quiet mode (`-q`); otherwise cMeta asks.

A request that names **no venv of its own** (no `with.venv_path`, `with.venv_here`, `tool_path`,
`with.here` and no `--path`) reuses these entries:

| Entry made by | Reused by a plain request? |
|---|---|
| a detected Python (no venv path recorded: the system Python, an activated venv, the venv cMeta runs from) | yes |
| a plain request, or one with a version (a venv in its own cache entry) | yes |
| a venv at a place the user chose (`with.venv_path`, `venv_here`, `--path`, `--use.venv.path`) outside the cache | yes |
| a program or a tool, with `venv_path` **inside its own cache entry** (`task--program--<name>/tmp/venv-cpu`) | **no**: it belongs to that program |

So a few venvs made in advance (`--version=3.12`, `--version=3.13`, or at chosen paths) are picked by
version by the programs that ask for them, while the venv a program builds for itself stays its own.
Before, a program's venv matched plain requests too, and in quiet mode its higher version often
won, so packages of unrelated tasks landed in it.

A request **with its own venv path** (`with.venv_path`, `venv_here`) looks for a Python only in that
venv: an existing venv there is reused, a missing one is made. A venv's Python given with `tool_path` or
found with `with.here` is registered as detected, and later plain requests may reuse it, as above.

A request that names **an interpreter that is no venv** (`--tool_path=<a conda env's python, a system
python>`, `--use.python.tool_path=...` from a program) while a venv is wanted gets **a venv made on that
interpreter** (`uv venv --python <interpreter>`): the request is turned into `python_base`, the entry is
matched on it next time, and a plain request never takes it (it is the Python of such requests only).
A version at the same time is refused - the interpreter decides the version. `--with.venv-` runs the
interpreter itself. Before (until 0.43.2), such a request was dropped by the venv rule and the venv was
made on a uv-managed Python: the interpreter named never ran (the provenance `python` check reports it).
The same holds with a venv path of the request (a program's venv in its build folder): the venv at that
path is made on the interpreter, and a venv found there that was made on another Python (the `home` of
its `pyvenv.cfg`) is left aside and remade (0.43.3). The interpreter itself is never taken as the venv,
even where it counts as "virtual" - a conda base, whose root has `condabin/` (on Linux and macOS such a
base was accepted as the venv until 0.43.3, so no venv was made and `pip` would have installed into it);
an activated conda base or venv found by a plain request is still used and extended, by design.

**A conda environment instead of a venv** (`--use.python.with.conda`, 0.43.3): the `venv` task makes a conda
environment in `.conda-env` of the entry (or of the request's venv path) with the conda cMeta set up
(`tool/conda`: a Miniforge, Miniconda or Anaconda on the machine, else the pinned Miniforge it installs) -
`conda create -y -p ... python[=<version>] pip`, plus `with.conda_packages` (comma-separated) and `with.channel`.
The python inside is conda's, pip is there so the pip tools work unchanged, and `tool/conda-package` installs
conda packages into it (`cx tool setup conda-package --with.package=numpy`). Such an entry is the Python of
conda requests only (never shared with a venv request), a conda request takes no detected python, and a
named interpreter at the same time is refused - the conda is chosen with `--use.conda.tool_path=<conda>`.
The environment carries `.cmeta-conda-env.json` (who made it); the provenance record says `the conda
environment .conda-env made by conda 26.7.2` and lists `runtime.python.conda_packages`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--version` | any | an exact version, `3.12` (any 3.12.x) or a range (`>=3.10,<3.14`) |
| `--with.venv` | on | only Pythons in a virtual environment; off: the system Python |
| `--with.pip` | on | only Pythons with pip |
| `--with.venv_path` | | the folder whose `.venv` is the venv to use or make |
| `--with.venv_here` | off | the `.venv` of the current folder |
| `--with.here` | off | a Python found in a venv under the current folder |
| `--with.activate` | off | add the venv's environment (`PATH`, `PYTHONPATH`) to the tasks that follow |
| `--tool_path` | | this Python, no detection (`{{sys.executable}}` = the Python cMeta runs on); not a venv's: a venv is made on it (`python_base`) |
| `--with.conda` | | a conda environment (`.conda-env`, by the conda of `tool/conda`) instead of a uv venv; `--with.conda_packages=a,b`, `--with.channel=<c>` go into `conda create`; never with `--tool_path` |
| `--paths` | | folders to search instead of `PATH` |

The result exposes `global.python.path`, `qpath`, `path_bin`, `path_home` and `version` to later
tasks (`{{global.python.qpath}} script.py` in a `cmd`).
