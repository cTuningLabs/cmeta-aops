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
venv: an existing venv there is reused, a missing one is made. A Python given with `tool_path` or
found with `with.here` is registered as detected, and later plain requests may reuse it, as above.

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
| `--tool_path` | | this Python, no detection (`{{sys.executable}}` = the Python cMeta runs on) |
| `--paths` | | folders to search instead of `PATH` |

The result exposes `global.python.path`, `qpath`, `path_bin`, `path_home` and `version` to later
tasks (`{{global.python.qpath}} script.py` in a `cmd`).
