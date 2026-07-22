---
name: add-tool
description: Add a new cMeta `tool` artifact (via `cx tool add`) that detects, installs and runs an external tool portably across Windows/macOS/Linux, then customize its `_desc.yaml` (detection + install) and optional `api_v1.py` (custom download-a-binary install). Use when the user asks to "add a tool", "make cMeta detect/install <X>", or "wrap a CLI so `cx tool setup/run` works cross-platform". Worked example: bazel.
---

# add-tool — wrap an external tool for `cx tool setup` / `cx tool run`

A **tool** artifact lives at `tool/<name>/` and describes how to **detect**,
**install**, **build** and **run** one external CLI (git, cmake, ninja, go,
bazel, …) portably across OSes. It is a *thin delegator*: `cx tool setup X`
and `cx tool run X -- <args>` both re-dispatch into the central task
`setup,a2f9b61079ce4333` (`task/setup/`), which orchestrates
**detect → install → build**. `tool run` additionally runs the resolved
binary via task `cmd,c9ba0a88df394d7f`, folding any dynamic-lib dirs into
`env['+PATH' | '+LD_LIBRARY_PATH' | '+DYLD_LIBRARY_PATH']`.

So authoring a tool = writing two files under `tool/<name>/`:

| File | Role | Required? |
|------|------|-----------|
| `_desc.yaml` | Detection + version + declarative install (per-OS commands) | **Yes** |
| `api_v1.py`  | Optional `CTool` hooks — custom install (e.g. download a release binary), install-cmd tweaks | Only if declarative install can't express it |

(`_cmeta.yaml` is written for you by `cx tool add`.)

> **Read first:** `AGENTS.md` (§5 tool/program) and `tool/git/_desc.yaml`
> (simplest declarative install), `tool/ninja/` + `tool/go/` (download-a-binary
> via `api_v1.py`). The `cx <cat> <cmd> --help` output is the source of truth if
> anything here disagrees.

---

## 1. Decide the install strategy first

This choice determines whether you need `api_v1.py` at all.

- **A. Package manager / official installer** (declarative, `_desc.yaml` only):
  the tool is available via winget (Windows), apt/dnf/etc. via
  `install_cmd_sudo` (Linux), or brew/`xcode-select` (macOS), or a one-line
  `curl … | sh` script. → Use `install_cmd:` / `install_cmd_version:`.
  Examples: `tool/git`, `tool/codex`.
- **B. Download a prebuilt release binary/archive** (needs `api_v1.py`): no
  clean package exists, or you want an exact pinned version placed in the
  category cache. → Implement the `install()` hook that calls task
  `download-file,03fed13e2e0447cf`. Examples: `tool/ninja`, `tool/go`,
  `tool/cmake`. **This is the right path for bazel.**

Both strategies still need the **detection** block in `_desc.yaml`.

---

## 2. Scaffold the artifact

**Qualify the target repo** — a bare `cx tool add <name>` lands in the default
`local` repo, **not** this content repo. Prefix with `<repo>:` so the artifact is
created under `cmeta-aops/tool/`:

```bash
# Create in THIS repo (the repo alias is from _cmr.yaml → ctuninglabs@cmeta-aops):
cx tool add ctuninglabs@cmeta-aops:bazel --yaml   # writes tool/bazel/_cmeta.yaml (fresh UID, category: tool,c393ba5c6fa14f66)

# --yaml matches the sibling tools (which use _cmeta.yaml); omit it for _cmeta.json.
# WRONG for this repo — goes to repos/local/tool/, then you'd have to `cx tool rm local:<name>`:
#   cx tool add bazel
```

`cx tool add` maps to the base `create_` (`cmeta/category_api_v1.py`). It only
creates `_cmeta.*` (and its generated `copyright:` may differ from the siblings —
fix it to `Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights
reserved.`). Then hand-author `_desc.yaml` (and `api_v1.py` if strategy B).

If you accidentally created it in the wrong repo, remove it with the repo-qualified
name (`cx tool rm local:<name> --force`) and re-add with the `<repo>:` prefix.

Fastest correct route: **clone the nearest existing tool** and edit.
- Strategy A → copy `tool/git/_desc.yaml`.
- Strategy B → copy `tool/ninja/_desc.yaml` + `tool/ninja/api_v1.py`.

After any hand-edit or file move: **`cx --reindex`**.

**Copyright headers are load-bearing.** Copy the verbatim proprietary block
from a sibling `.py`; keep the `authors:`/`copyright:` lines at the top of
`_desc.yaml`. Do not relicense.

---

## 3. `_desc.yaml` — detection (always required)

The engine finds the binary by name on `PATH` (+ `extra_paths`), runs a version
command, and regex-matches the version.

```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

names:
  - bazel{{global.host.vars.file_ext_exe}}   # {{...file_ext_exe}} = ".exe" on Windows, "" elsewhere

match_version:
  - regex: "bazel ([0-9][0-9A-Za-z.\\-]*)"    # applied to cmd_get_version output; `group` picks the capture
    group: 1

cmd_get_version: '{{tool_path}} --version'     # {{tool_path}} = the detected binary
```

Detection keys:
- `names:` — list of candidate filenames; templated. Always append
  `{{global.host.vars.file_ext_exe}}` so Windows looks for `.exe`. A trailing
  `.` in a name means "match a file with **no** extension".
- `cmd_get_version:` — command to print the version (`{{tool_path}}` is the
  found binary). Common: `--version` / `version`.
- `match_version:` — list of `{regex, group}`; first match wins. Escape
  backslashes for YAML.
- `extra_paths:` (per OS, glob `**` allowed) — extra dirs to search beyond
  `PATH`, e.g. winget install locations. Optional.

Optional "list available versions" (`cx tool setup <name> --versions`):
```yaml
cmd_get_versions: '{{global.git.qpath}} ls-remote --tags https://github.com/bazelbuild/bazel'
cmd_get_versions_uses:                 # ensure git is set up before running the above
  - task: setup,a2f9b61079ce4333
    name: git,959d8c0fbc004bd0
cmd_get_versions_regex: 'refs/tags/(\d+\.\d+\.\d+)$'
```
`{{global.<tool>.qpath}}` is the quoted path to a tool set up earlier in the run
(e.g. `global.git.qpath`, `global.curl.qpath`, `global.winget.qpath`).

---

## 4. `_desc.yaml` — declarative install (Strategy A)

Per-OS commands, templated against `ctx['tasks']` (`{{global....}}`). The `setup`
task picks `windows` / `linux` / `darwin` (falling back to `linux`), or a single
`all:` key for every OS.

```yaml
install_cmd:
  linux:   '{{global.host.os_extra.install_cmd_sudo}}'          # apt/dnf/... install <name>, filled by host
  darwin:  'xcode-select --install'
  windows: "{{global.winget.qpath}} install --id=Bazel.Bazel -e --no-upgrade {{global.init.winget_install_flags|}}"

install_cmd_version:                                            # used when a --version is requested
  windows: "{{global.winget.qpath}} install --id=Bazel.Bazel -e --version={{simple_version}} --no-upgrade {{global.init.winget_install_flags|}}"
  linux:   '{{global.host.os_extra.install_cmd_sudo_version}}'

requires_sudo:            # forces non-interactive sudo handling
  linux: True
  darwin: True

install_uses:            # extra tools this install needs, set up first (see task/setup install_uses)
  all:
    - task: setup,a2f9b61079ce4333
      name: curl,bfbb8526694d4f21

install_help_text: |     # shown if every strategy fails
  Please install Bazel per https://bazel.build/install
```

Version placeholders the engine substitutes into `install_cmd_version`:
`{{version}}`, `{{simple_version}}` (no comparators), `{{major_version}}`,
`{{pip_version}}` (adds `==`). `{{name}}` → the resolved package/artifact name.
Per-distro package names: `package_name` or `package_name_os_id: {ubuntu: ..., fedora: ...}`.

Note: `task/setup/_desc.yaml` already contributes common `install_uses`
(winget on Win, curl on Linux/macOS, brew on macOS) — you only add tool-specific
deps. Set `skip_common_install_uses: True` to opt out.

---

## 5. `api_v1.py` — custom install (Strategy B)

Subclass `CTool` and implement `install()`. Contract (from
`task/setup/install.py::install_tool`):

- Signature: `install(self, ctx, params, cmd=None, *misc)` where `misc[0]` is the
  declarative `uninstall_cmd`. `params` carries `version`, `version_simple`,
  `control` (`con`/`quiet`/`verbose`), `env`, `timeout`.
- **Return contract** (`{'return':0,...}` ok / `{'return':>0,'error':...}` fail;
  test peers with `self.cm.catch_error(r)`):
  - `{'return':0, 'install_cmd': None, 'found_path': <abs path to binary>}` —
    "I installed it myself, don't run any shell install_cmd." `setup` then
    re-detects at `found_path`.
  - `{'return':16, 'install_cmd': cmd}` — "I can't handle this case; fall back to
    the declarative `install_cmd`." (Return 16 = soft/"not handled".)
- Other optional `CTool` hooks: `init(ctx,params)` (resolve/inject params, set
  `storage_key`), `check_params`, `customize_install_cmd(ctx, install_cmd, params, env, timeout, uninstall_cmd)` (tweak the shell command), `post_install`, `finish_dynamic_result`.

Download a release asset via task `download-file,03fed13e2e0447cf`. Key params:
`url`, `directory` (subdir under the cache entry, use `'content'`), `filename`
(override the saved name — **important** so the binary is named `bazel`, not the
versioned asset name), `unzip` (+ `strip_folders`, `clean_after_unzip` for
archives; `False` for a bare binary), `check_file` (abs path that must exist
after), `make_check_file_executable: True` (chmod +x on non-Windows).

---

## 6. Worked example — bazel (cross-platform, Strategy B)

Bazel ships a **single static binary** per OS/arch on GitHub releases:
`bazel-<ver>-<os>-<arch>[.exe]`, `os ∈ {windows,linux,darwin}`,
`arch ∈ {x86_64,arm64}`, Windows adds `.exe`. `bazel --version` prints
`bazel 7.4.1`. A bare binary → no unzip; just download, rename to `bazel`,
chmod +x.

### `tool/bazel/_desc.yaml`

```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

names:
  - bazel{{global.host.vars.file_ext_exe}}

match_version:
  - regex: "bazel ([0-9][0-9A-Za-z.\\-]*)"
    group: 1

cmd_get_version: '{{tool_path}} --version'

# Optional: `cx tool setup bazel --versions`
cmd_get_versions: '{{global.git.qpath}} ls-remote --tags https://github.com/bazelbuild/bazel'
cmd_get_versions_uses:
  - task: setup,a2f9b61079ce4333
    name: git,959d8c0fbc004bd0
cmd_get_versions_regex: 'refs/tags/(\d+\.\d+\.\d+)$'

extra_paths:
  linux:
    - "{{user_home}}/bin/**"
    - "/home/linuxbrew/.linuxbrew/**"
  darwin:
    - "/opt/homebrew/opt/bazel*/**"
  windows:
    - "{{global.host.os_env.LOCALAPPDATA}}\\Microsoft\\WinGet\\Packages\\**"

install_help_text: |
  Could not download Bazel automatically.
  Install it manually per https://bazel.build/install and retry `cx tool setup bazel`.
```

### `tool/bazel/api_v1.py`

```python
"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Download a prebuilt Bazel binary from GitHub releases (any OS/arch).
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL bazel api_v1 install")

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        uname = _global['host']['os']['uname']   # windows | linux | darwin
        uarch = _global['host']['os']['uarch']   # amd64 | arm64
        exe   = _global['host']['vars']['file_ext_exe']  # ".exe" on Windows else ""

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            # Default pinned version when the user didn't request one
            version = '7.4.1'
            version_simple = version

        if not version_simple:
            # Only exact/simple versions can map to a release asset.
            # Return 16 + the original cmd so setup can fall back to install_cmd.
            return {
                'return': 16,
                'error': f'custom install for "bazel" needs an exact version in "{__file__}"',
                'install_cmd': cmd,
            }

        con     = params.get('control', {}).get('con', False)
        quiet   = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space   = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env     = params.get('env')
        timeout = params.get('timeout')

        # Map cMeta OS/arch -> Bazel asset naming
        if uarch == 'amd64':
            uarch2 = 'x86_64'
        elif uarch == 'arm64':
            uarch2 = 'arm64'
        else:
            uarch2 = None

        uos = {'windows': 'windows', 'linux': 'linux', 'darwin': 'darwin'}.get(uname)

        if not uos or not uarch2:
            return {
                'return': 16,
                'error': f'custom install for "bazel" could not build a download URL for {uname}/{uarch}',
                'install_cmd': cmd,
            }

        asset = f'bazel-{version_simple}-{uos}-{uarch2}{exe}'
        url   = f'https://github.com/bazelbuild/bazel/releases/download/{version_simple}/{asset}'

        directory = 'content'
        # Save under a stable name so detection (names: bazel{{ext}}) finds it
        path_to_tool = os.path.join(os.getcwd(), directory, 'bazel' + exe)

        if con:
            print ('')
            print (f'{space}INFO: Current path: {os.getcwd()}')
            print (f'{space}INFO: Bazel download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_tool}')
            print ('')

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'filename': 'bazel' + exe,        # rename the versioned asset -> "bazel"
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'unzip': False,                   # single binary, nothing to extract
              'clean': True,
              'check_file': path_to_tool,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
            'return': 0,
            'install_cmd': None,                # tell setup NOT to run a shell install
            'found_path': path_to_tool,
        }
```

---

## 7. Reindex, test, verify

```bash
cx --reindex
cx tool find bazel                 # confirm indexed (should resolve to tool/bazel in THIS repo)
cx tool setup bazel -j             # detect-only pass; if not found it PROMPTS "install? (Y/n)"
cx tool setup bazel --install -j   # auto-proceed with install (no prompt) — needed in non-interactive shells
cx tool setup bazel --version=7.4.1 --new -j
cx tool run bazel -- --version     # sets up then runs; args go after -- (expect: bazel 7.4.1)
cx tool setup bazel --versions     # (if you added cmd_get_versions) list release tags
```

> **Interactive install prompt:** when detection fails, `setup` calls `input()`
> to ask before installing. That raises `EOFError` under a non-interactive shell
> (CI, piped, agent). `install.py` proceeds automatically when `install is True`,
> `quiet`, or `not con` — so pass **`--install`** (or `-q`) to install
> unattended, or `--con` to genuinely answer the prompt.

Add a `test.bat` mirroring siblings (e.g. `tool/codex/test.bat`):
```bat
cx tool run bazel -- --version
```

Cache notes: each setup result + downloaded binary lands in a `cache` entry
(`cx cache show|clean|delete`), keyed by `name`/`@version`/`tool_path` (see
`task/setup/_desc.yaml` `cache_params`). Force a fresh entry with `--new`,
rebuild with `--update`, wipe with `--clean`.

---

## 8. Checklist / gotchas

- [ ] Created with the **repo-qualified** name (`cx tool add ctuninglabs@cmeta-aops:<name>`), not a bare `cx tool add <name>` (which lands in `local`).
- [ ] Fixed the auto-generated `copyright:` in `_cmeta.*` to match the siblings.
- [ ] `names:` ends with `{{global.host.vars.file_ext_exe}}`.
- [ ] `match_version` regex tested against real `cmd_get_version` output; YAML backslashes escaped.
- [ ] Strategy B: `install()` imports `from tool_c393ba5c6fa14f66.api.ctool import InitCTool`
      (bazel's own tool UID stays out of code — this is the **category** UID, same in every tool's `api_v1.py`).
- [ ] Strategy B: pass `filename` to `download-file` so the binary is stored under the plain tool name.
- [ ] Strategy B: return `install_cmd: None` on success, or `{'return':16,'install_cmd':cmd}` to fall back.
- [ ] Ran `cx --reindex` after editing YAML.
- [ ] Verified with `cx tool run <name> -- --version` (real run, not just `--info`); used `--install` for unattended install.
- [ ] Verbatim proprietary copyright headers preserved; referenced sub-tasks by `alias,UID`.
- [ ] Don't touch author scratch siblings (`*.yaml2`, `*.py2`, `*.arc1`, `tmp*/`).
```
