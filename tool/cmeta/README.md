# cMeta in a selected Python

`tool::cmeta` detects or installs the cMeta Python package and exposes its CLI as
`{{global.cmeta.cmd}}`. That command is the selected Python plus `-m cmeta`, so it
cannot accidentally invoke another environment's `cx` shim. `path`/`qpath` point
to the interpreter; use `cmd` when invoking cMeta.

```sh
cx tool setup cmeta -q
cx tool run cmeta -q -- --version
cx tool setup cmeta --versions -q
cx tool setup cmeta --status -q
cx tool check-updates cmeta -q
```

The existing `tool::python` selects the interpreter. To prepare a separate cached
venv rather than modify the detected Python, select it explicitly:

```sh
cx tool setup cmeta --use.python.install --use.python.version=3.13 --use.python.cache_extra_tags=my-project-cmeta-runtime -q
```

Cache entries include the selected Python path/version and source options. A
different requested cMeta version can replace the package in the **same** Python;
use a different Python cache tag/name for engines that must coexist. A standalone
tool setup intentionally uses the Python you select. A consuming task may provide
stronger isolation (the cTuning task chooses separate Python caches per request).

## Versions and sources

`default_version` lives in `_desc.yaml`. Normal setup detects a compatible
installed version first; installation without a version pins to that default.
The shared setup framework handles version constraints, `known`, `latest`,
`--versions`, `--status` and `--upgrade`. `check-updates` compares the declared
pin with upstream; it does not install or promote a pin. Stable versions are
queried from PyPI's JSON API. Installation uses the standard pip channel and
sets up `tool::python-pip` only when needed.

```sh
cx tool setup cmeta --version=known -q
cx tool setup cmeta --version=latest -q
cx tool setup cmeta --version=0.37.1 -q
cx tool setup cmeta --upgrade -q
cx tool setup cmeta --with.url=git+https://github.com/ctuninglabs/cmeta --with.url_tag=v0.37.1 -q
cx tool setup cmeta --with.file="/absolute/path/to/cmeta" --with.flags=-e -q
```

Append the same `--use.python.*` selection to each command when targeting a
dedicated venv. A Git source sets up `tool::git`; `url_tag` accepts a tag, branch
or commit. A local source is a Python project directory, wheel or source archive.
`with.flags=-e` makes a project directory editable. Source flags precede the
source argument, allowing pip flags that consume that argument.

Use exactly one source (`with.file` or `with.url`), without `version`; its package
metadata determines the installed version. A requested source is installed on a
cache miss even if another installed distribution reports the same version.
Source options participate in cache matching. Reuse does not fetch a moving Git
branch again; request `--update` to refresh that tool setup. Editable local code
changes remain visible through that editable installation.

This tool selects an engine, not a cMeta home. Set `CMETA_HOME` for a child CMD
when separate repositories are required. If the host also overrides
`CMETA_INTERNAL_REPO_PATH`, select the runtime engine's shipped `internal-repo`
for that child; do not leave it pointing at a different engine's checkout.
