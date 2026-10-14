# Versions of tools and the reproduction of a run

*A living document: the versioning and reproducibility of cMeta AOps as they are built, step by step. What is
there today is described as it works; what is planned is marked so.*

cMeta installs tools, builds programs and runs them with many moving parts: the version of every tool, the
options of every build, the machine. Two needs pull in opposite directions. A user who runs a task wants the
same result tomorrow as today, so the versions must not drift under them. A researcher wants to try the newest
versions and learn what works where, so the versions must be easy to move. This page describes how cmeta-aops
serves both: a version known to cMeta per tool, the newest one a word away, every choice recorded, and a run
that can be repeated with the versions it used.

## 1. The version a tool installs by default

Every tool that cMeta can install declares in its `_desc.yaml` the version it installs when none is asked
for:

```yaml
default_version: '4.53.6'      # a quoted string
```

It is the one place for that fact: the shared installers (`category/tool/api/common_release.py`,
`common_pyvenv.py`, `common_static_lib.py`) and a custom `install()` hook (`self.cdesc['default_version']`) read
it from the description, never from a copy in the code, so that `cx tool show <tool>` answers the question and
a bump is one edit. A tool with one default per implementation (`tool/mpi`: `--with.mpi=openmpi|mpich|intel`)
declares `default_versions`, one per implementation.

A tool installed through a channel (winget, Homebrew, the system package manager, an install script) takes
whatever the channel offers that day; it may declare a `default_version` as the version it was tested with,
and `--version=known` then asks for exactly that one where the channel can give it (`install_cmd_version`).

## 2. Versions by name: `known` and `latest`

Two words are accepted wherever a version goes - `--version=latest`, `--use.python.version=known`, a task's
`uses` entry:

| Word | Meaning | Source |
|---|---|---|
| `known` | the version cMeta is known to work with | `default_version` of the tool's `_desc.yaml` |
| `latest` | the newest version the tool can get | its channel's newest when the tool is installed through winget, Homebrew or the system package manager; upstream's newest otherwise (the GitHub release marked latest, else the newest tag or `cmd_get_latest_version`) - the rule `--status` uses |

The setup task resolves the word to a concrete version **before the cache lookup** (`task/setup/upgrade.py`,
`resolve_version`, called from the task's `check_params`), so the cache entry's key, the `version` the result
reports and the provenance record of a program run hold a real version. Two runs on two machines are
comparable, and a later lookup of "what worked on this kind of machine" has exact data. The word and the
version it became are in the result (`version_resolved`) and in the entry's parameters (`version_word`).

```
cx tool setup yq --version=known         # 4.53.6, the pin
cx tool setup yq --version=latest        # 4.54.1 today, from the cached lookup
cx tool setup yq --versions              # the list, the known and the newest version, their sources, the policy
```

A version the request names (`--version=4.53.6`, a condition such as `>=4.50,<4.54`) is never touched.

## 3. The policy of a request without a version

A request without a version follows a policy:

| Policy | A request without a version takes | Note |
|---|---|---|
| `known` (the default) | whatever is found first, else the pin | the behaviour before the policy existed; no network for the choice |
| `latest` | the newest version | the research mode: the lookup is cached (section 5) |
| `ask` | the newest or the known one, as answered | "the newest version of X is 4.54.1, the one known to cMeta is 4.53.6: install the newest one? (y/N)"; without a terminal, or with `-q`, the known one |

The policy comes from the narrowest source that names one:

1. `--use.<tool>.version_policy=latest` - one tool of one run (or `--version=latest` for that tool);
2. `--use.init.version_policy=latest` - the whole run (every tool of every sub-task);
3. `CMETA_VERSION_POLICY=latest` - a shell, a CI job, a container;
4. `cx config set task --meta.version_policy=latest` - this machine (the key `version_policy` of `config::task`);
5. `version_policy: latest` in the tool's `_desc.yaml` - the tool author's word for a tool whose newest is
   always right (a mature command-line tool nothing is compiled against);
6. `known`.

The flag wins over the variable and the variable over the config (`task/init` reads them in that order and
carries the result as `init.version_policy`); a user's explicit choice wins over the tool's own.

## 4. When the version chosen cannot be obtained

A version chosen by a word, not named by the request, may fall back to the other one, once, with one
`cMeta warning:` line that says what happened:

- `latest` whose lookup gives nothing (offline, an unreachable source): the known version;
- `known` or `latest` whose install fails (the download is gone, the channel refuses it): the other one; the
  cache entry then records the version obtained (`version_fallback` in the result says from which to which and
  why).

A version the request names fails loudly, as every forced configuration does: a build that fails with the
latest LLVM is reported, never retried with another version behind the user's back. Walking the versions on
purpose is the exploration run of section 8.

## 5. The lookup of the newest version: once, cached, honest offline

A lookup happens only when a resolution needs one (`latest`, `ask`, `--versions`, `--status`): `known` never
asks the network for the choice. The answer is cached per tool in the artifact `tmp::tool-versions` of the local
repository (`<tool>.json`: the known and the newest version, their sources, the versions listed, the notes,
when it was asked) and trusted for `versions_ttl_hours`:

| Setting | Where |
|---|---|
| 24 hours | the default |
| `--use.init.versions_ttl_hours=1` | the run |
| `CMETA_VERSIONS_TTL_HOURS=1` | a shell |
| `cx config set task --meta.versions_ttl_hours=1` | the machine |
| `--refresh_versions` | this request asks again (`--use.<tool>.refresh_versions`) |

Within a run a tool is asked once. Offline, or when the source fails, the cached answer is used if there is
one, else the known version with a line; a setup never fails because a lookup failed. The costs to keep in
mind: the GitHub `releases/latest` redirect is one HTTPS request and no API quota; `git ls-remote --tags` needs
git and a few seconds; winget, Homebrew and pip queries take seconds and gain most from the cache.

## 6. Reproduce a run: `-r` and `cx @repro/<stamp>/repro.json`

Any command run with `-r` (`--repro`) writes, in the directory it was run from, a folder
`repro/<YYYYMMDD-HHMMSS>/`:

| File | Content |
|---|---|
| `repro.json` | the original request with `use.<tool>.version` = the version each tool of the run was used at (a word, a partial version such as `3.12` or a range in the request becomes what it resolved to) - the engine's `@file` include replays it |
| `tools.json` | every tool of the run: version, path, cache entry, parameters, the word it was resolved from |
| `run.json` | the command line, the directory, the time, the result, the host (OS, architecture, hostname), the cMeta and Python versions |
| `README.md` | how to rerun and how to change one version at a time |

```
cx program run test-hello-c-cpu cpu -r          # the run, with every tool it used recorded
cx @repro/20261014-003306/repro.json            # the same command, every tool pinned to its version
```

A pinned version that is no longer on the machine is installed where cMeta can (a release download, a pinned
package) and fails loudly otherwise: remove that tool's `version` line from `repro.json` to let it float, or set
another version - `known`, `latest` or a number - to try the change one tool at a time. The engine's own
`cmeta-repro-input.json`, `cmeta-repro-input2.json` and `cmeta-repro-output.json` are written as before.

The provenance record of a program run ([provenance.md](provenance.md)) says, after the fact, which tools and
libraries a binary used; the reproduction folder says, before the next run, which versions to use. The two
agree because both read the same global context of the run.

### A worked example: a compiler, a Python and a torch chosen, the cache wiped, the same versions back

Three runs on Windows, each with `-r` (the same commands work on Linux and macOS):

```
cx program run test-nmm-c-cpu --use.compiler-c.name=clang --use.clang.version=21.1.8 -r
cx program run model-cnn-ylecun-mnist-pytorch --use.python.version=3.12 --use.pip-torch.version=2.9.1 --epochs=1 -r
cx program run model-cnn-ylecun-mnist-pytorch --use.python.version=3.12 --use.pip-torch.version=latest --epochs=1 -r
```

The first compiles the matrix multiply with clang of LLVM 21.1.8 (downloaded into the cache) instead of the default
compiler; the second trains the MNIST CNN for one epoch with Python 3.12 and torch 2.9.1 (the paired torchvision
0.24.1 follows); the third asks for the newest torch. Each writes `repro/<stamp>/`, and its `repro.json` pins what
was used - the request's `3.12` and `latest` become what they resolved to:

| Run | Pins in `repro.json` (some of them) |
|---|---|
| clang | `compiler-c`: `clang`, `clang` 21.1.8, `llvm` 21.1.8, `msvc` 19.51.36260, `microsoft-sdk` 10.0.26100.0, `lib-openssl` 4.0.0 |
| torch 2.9.1 | `python` 3.12.14, `pip-torch` 2.9.1, `pip-torchvision` 0.24.1, `pip-numpy` 2.5.4, `pip-huggingface_hub` 2.2.0 |
| torch latest | `python` 3.12.14, `pip-torch` 2.14.1, `pip-torchvision` 0.29.1, the rest as above |

Then every cache entry is removed and each run is replayed from its file:

```
cx cache clean --all --force
cx @repro/<stamp>/repro.json -r
```

The replay downloads LLVM 21.1.8 again, makes the Python 3.12.14 venv again, installs torch 2.9.1 (or 2.14.1, not
whatever is newest on the day of the replay) and the same packages, and runs the same command; with `-r` it writes
its own folder, so the versions of the two runs can be compared tool by tool. Two things stay outside the pins:
what the machine itself provides (the compiler of Visual Studio, the Windows SDK, winget - a pin that the machine no
longer meets fails loudly), and the bytes of a download that a publisher replaces under the same version (a pinned
dataset revision is planned, section 8).

## 7. For the Python API

- `cm.access({'category': 'task', 'command': 'run', 'arg1': 'setup', 'name': 'yq', 'versions': True})` returns
  `versions` (the list), `known`, `latest`, `latest_source`, `policy` and `versions_lookup` (the cached record);
  with `refresh_versions: True` it asks again. An exploration space is built from `versions`.
- A setup's result carries `version` (what was used), `version_resolved` (the word and what it became) and,
  after a fallback, `version_fallback`.
- `ctx['tasks']['global'][<tool>]` holds every tool of a run with its `version` and `path`;
  `category/task/api/provenance.py` `collect_resolved(global)` trims them to one dict, `write_repro(cm, ctx,
  result)` writes the reproduction folder for any run.

## 8. Planned

- **The bounds of `latest` in meta**, with a reason and a date (a version range known to break, a maximum until
  a dependency has wheels), so that `latest` is the newest version that can work; and `since`, when the known
  version was last confirmed.
- **`cx tool check-updates`**: the known versions against the newest ones for every tool, as a report (weekly
  on the fleet; a bump stays a decision).
- **The exploration run**: one task run per version of one tool, each in a fresh cache entry, the verdicts
  recorded (works, fails, the error's class, the machine) - first in the test sessions, then as records that a
  promotion script reads to move `known` forward and to bound `latest`.
- **Models, datasets, prompts and benchmarks** as versioned, cached artifacts in the same scheme (a model's
  revision, a dataset's snapshot, a prompt's hash), so that a run's reproduction folder pins them too; cMeta's
  artifacts and UIDs are the identities.
- **A knowledge layer** read at setup time: what worked on this kind of machine for this task - the resolver
  keeps a slot for it.

## 9. The configuration keys cmeta-aops reads

The config category holds one artifact per task family (`cx config set <artifact> --meta.<key>=<value>`,
`cx config read <artifact>`). The keys read today:

| Artifact | Key | Read by | Meaning |
|---|---|---|---|
| `task` | `default_cache_repo` | the task engine | the repository that holds the cache entries of every run (`--use.init.default_cache_repo` for one run) |
| `task` | `file_cache` | `clone-git-to-cache`, `get-hf-model`, `get-hf-dataset`, `tool/hf` | folders (`os.pathsep`-separated) that keep large downloads and clones outside the cache entries, the first that exists or can be made |
| `task` | `version_policy` | `task/init` for `task/setup` | the policy of a request without a version (section 3) |
| `task` | `versions_ttl_hours` | `task/init` for `task/setup` | how long a cached lookup of a newest version is trusted (section 5) |
| `task` | `min_free_gb` | `task/setup`, `compile-and-run-program` | the free disk space an install or build must leave ([tool-sizes.md](tool-sizes.md)) |
| `task` | `test_session.repo`, `test_session.artifact`, `test_session.max_keep_mib`, `test_session.prices.*` | `test-session` | where the sessions live, how much a kept sandbox may hold, the prices of the models for the costs |
| `task` | `compile_and_run_program.target_tmp` | `compile-and-run-program` | the temporary folder of a target ([task/target/README.tech.md](../../task/target/README.tech.md)) |
| `task-run-ai` | `write`, `local_ai_uses.*`, `max_context_tokens`, `trim_context` | `run-ai` | what a run may write, this machine's mapping of used artifacts, the context limit ([task/run-ai/README.md](../../task/run-ai/README.md)) |
| `default` | `agent_add_repos` | `run-claude` | repositories added to the agent's context ([agent-tasks.md](agent-tasks.md)) |

The environment variables of this page: `CMETA_VERSION_POLICY`, `CMETA_VERSIONS_TTL_HOURS`; of the typed words
of the command line: `CMETA_CLI_TYPES=off` ([task-engine.md](task-engine.md)); of provenance:
`CMETA_PROVENANCE`, `CMETA_TEST_SESSION` ([provenance.md](provenance.md)).
