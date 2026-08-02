<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# The `tool` category — portable detect / install / build / run

A **tool** artifact (`tool/<name>/`, category `tool,c393ba5c6fa14f66`) describes how to
**detect**, **install**, **build** and **run** one external CLI (git, cmake, ninja, go,
python, cuda, nvcc, node-js, claude, codex, openclaw, …) portably across OSes. It is a
*thin delegator*: `cx tool setup X` and `cx tool run X -- <args>` both re-dispatch into
the central task **`setup,a2f9b61079ce4333`** (`task/setup/`), which orchestrates
**detect → install → build**; `tool run` additionally runs the resolved binary via task
`cmd,c9ba0a88df394d7f`, folding dynamic-lib dirs into
`env['+PATH' | '+LD_LIBRARY_PATH' | '+DYLD_LIBRARY_PATH']`.

Authoring = one or two files (see the **`add-tool`** skill for the full guide):

| File | Role | Required |
|------|------|----------|
| `_desc.yaml` | detection + version + declarative install (per-OS) | yes |
| `api_v1.py` | optional `CTool` hooks — custom install (download a release binary), cmd tweaks | only if declarative install can't express it |

## `setup` result stored in `global.<name>`

After `setup name:X`, `ctx['tasks']['global'][X]` holds (among others):
`path` (binary), `qpath` (quoted path), `path_bin` / `qpath_bin` (its dir, quoted),
`version`, `features` (from the tool's `features:` block), and — for cached tools —
`path_cmeta_cache`/`qpath_cmeta_cache`. Downstream `_desc.yaml` templates reference
`{{global.X.qpath}}` etc. `setup` forces `store_global`, `storage_key: "{{$params.name}}"`,
`cache: True`, `cache_params: [name, @version, tool_path]` — so a tool is set up once per
run and reused across runs from the category cache.

## `_desc.yaml` — detection (always)

```yaml
names:
  - git{{global.host.vars.file_ext_exe}}   # .exe on Windows, "" elsewhere
match_version:
  - regex: '...'                            # applied to cmd_get_version output; `group` picks the capture
    group: 1
cmd_get_version: '{{tool_path}} --version'  # {{tool_path}} = the found binary
extra_paths:                                # extra dirs to search beyond PATH (per OS, glob ** allowed)
  windows: [ "{{global.host.os_env.APPDATA}}\\npm" ]
```

`setup/detect.py` searches each `names` filename on `aggregated.env.PATH` + `os_env.PATH`
+ `extra_paths`, runs `cmd_get_version` on each hit, and regex-matches the version
(`re.IGNORECASE | re.MULTILINE`, first `match_version` entry that matches wins). It filters
by requested `--version`, sorts (`@detected_version-`), and returns `path`/`version`/
`path_bin`/`features`. **npm-shim tools** need every candidate name (e.g.
`[openclaw{{file_ext_exe}}, openclaw.cmd]`) because on Windows the binary is `X.cmd`, not
`X.exe`.

## `_desc.yaml` — version listing (`cx tool setup X --versions`)

The setup `--versions` path runs `cmd_get_versions`, first setting up any
`cmd_get_versions_uses`, then extracting versions with `cmd_get_versions_regex`
(per-line `re.search`, **first match per line only**, sorted `@version-`).

Two idioms in this repo:

```yaml
# GitHub tags (claude, codex, llvm, gcc, node-js, ...)
cmd_get_versions: '{{global.git.qpath}} ls-remote --tags https://github.com/anthropics/claude-code'
cmd_get_versions_uses:
  - task: setup,a2f9b61079ce4333
    name: git,959d8c0fbc004bd0
cmd_get_versions_regex: 'refs/tags/v([\d.]+)(?:\^\{\})?$'
```

```yaml
# npm registry (openclaw) — GitHub tags weren't semver; --json prints one per line
cmd_get_versions: 'npm view openclaw versions --json'
cmd_get_versions_uses:
  - task: setup,a2f9b61079ce4333
    name: node-js,238f15e1d6184359
    with:
      add_tool_path_to_env: True   # put node/npm on PATH for the command
cmd_get_versions_regex: '"([0-9][^"]*)"'
```

Anchor GitHub-tag regexes tightly to exclude junk tag schemes — e.g. codex has
`rust-vv…`, `rusty-v8-…`, `winget-test-…` noise, so it anchors on `rust-v` + a digit:
`'refs/tags/rust-v(\d[\w.\-]*?)(?:\^\{\})?$'`.

## `_desc.yaml` — install (declarative)

Per-OS (or a single `all:`), templated against `ctx['tasks']`:

```yaml
install_cmd:
  windows: 'powershell -ExecutionPolicy ByPass -c "irm https://.../install.ps1 | iex"'
  linux:   '{{global.curl.qpath}} -fsSL https://.../install.sh | bash'
install_cmd_version:                 # used ONLY when --version=X is passed AND that version isn't already present
  linux:   '{{global.curl.qpath}} -fsSL https://.../install.sh | bash -s -- {{simple_version}}'
install_uses:                        # extra tools to set up first (added to setup's common winget/curl/brew)
  all:
    - task: setup,a2f9b61079ce4333
      name: node-js,238f15e1d6184359
install_help_text: |                 # shown if every strategy fails (use a | block scalar to avoid YAML `key:` traps)
  Install manually per https://...
extra_paths: { ... }                 # npm/global-bin dirs so re-detect finds it after install
```

Version placeholders the engine substitutes into `install_cmd_version` (see
`task/setup/install.py`, selected only `if version and install_cmd_ver`):
`{{simple_version}}` (comparators stripped; only for exact versions — fuzzy ranges fall
back to plain `install_cmd`), `{{version}}`, `{{major_version}}`, `{{pip_version}}`
(adds `==`). `{{name}}` → the resolved package name; per-distro names via `package_name`
/ `package_name_os_id`.

### Cross-platform install patterns actually used here

- **npm global package** (`openclaw`): `install_cmd: {all: 'npm install -g openclaw'}`,
  `install_cmd_version: {all: 'npm install -g openclaw@{{simple_version}}'}`, dep `node-js`.
- **Official script that accepts a version arg** (`claude`, `codex`): read the script to
  confirm the arg — claude's `install.sh`/`install.cmd` take `[stable|latest|VERSION]`
  (`bash -s -- {{simple_version}}` / `install.cmd {{simple_version}}`); codex's takes
  `--release VERSION` (sh) or `$env:CODEX_RELEASE` (ps1).
- **Package manager** (`gcc`): `install_cmd: {linux: '{{global.host.os_extra.install_cmd_sudo}}'}`,
  `install_cmd_version: {linux: '{{global.host.os_extra.install_cmd_sudo_version}}'}`.
- **Download a prebuilt binary** (`ninja`, `go`, `cmake`, bazel-style): implement the
  `install()` hook in `api_v1.py` calling task `download-file,03fed13e2e0447cf`
  (`filename` to rename to the plain tool name, `make_check_file_executable`), and return
  `{'return':0, 'install_cmd': None, 'found_path': <abs path>}` (or `{'return':16,
  'install_cmd': cmd}` to fall back to the declarative command).

## `_desc.yaml` — compiler tools carry `features.flags`

Compiler tools (gcc, clang, clang-cpp, msvc, nvcc, icx/icpx, android-ndk clang) are
tagged `lang-c` / `lang-cpp` / `lang-cuda` and expose a per-OS **`features.flags`**
dictionary that the `program` compile machinery consumes — `dynamic_build`/`static_build`,
`openmp`, `fast: -O3`, `d: -D`, `include_path: -I`, `lib_path: -L`, `lib_prefix: -l`,
`lib_file: -o`, `static_lib1: rcs`, plus `vars.file_ext_{exe,lib,dlib,obj}`. See
[program-and-compute.md](program-and-compute.md).

## Verifying safely

- `cx tool setup X --versions` — no side effects (lists versions).
- `cx tool setup X --detect` — detect only (never installs; `detect=True` forces
  `install=build=False`).
- `cx tool setup X --version=<already-installed>` — detection matches, no install.
- `cx tool run X -- --version` — full set-up-then-run path.
- Real installs and versioned installs mutate the machine (global CLIs get overwritten) —
  do them deliberately. In non-interactive shells pass `--install`/`--quiet` (the setup
  prompt uses `input()` and would raise `EOFError`).
