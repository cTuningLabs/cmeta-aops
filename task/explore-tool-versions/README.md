# explore-tool-versions: try a tool at several versions, keep a verdict per version

`cx task run explore-tool-versions <tool>` sets up the tool at each version asked for, each in a fresh cache entry,
and, with `--program`, runs a program with that version. It records one verdict per version (works or fails, the
class of the error, the machine), and from the verdicts of one or many machines it proposes the next
`default_version` of the tool or a limit of its `latest`. It is how the version cMeta installs by default moves
forward on evidence (see [versions-and-reproducibility.md](../../docs/cmeta-aops/versions-and-reproducibility.md)).

```
cx task run explore-tool-versions yq                                   # known and latest (and the newest, when a limit excludes it)
cx task run explore-tool-versions yq --versions=4.53.6,4.54.1,latest   # these versions (numbers and the words known, latest)
cx task run explore-tool-versions yq --last=3                          # the three newest released versions the tool lists
cx task run explore-tool-versions python --versions=3.12.14,3.14.8 --program=test-nmm-python-cpu
cx task run explore-tool-versions clang --versions=21.1.8,22.1.7 --program=test-nmm-c-cpu --use.compiler-c.name=clang
cx task run explore-tool-versions llvm --program=test-nmm-c-cpu --use_key=compiler-c --use.compiler-c.name=clang   # the pin of llvm: the compiler's version, which clang hands to llvm
cx task run explore-tool-versions --promote --verdicts=<file.jsonl|folder>[,...] [--min_os=2]
```

## Which versions it tries

Never a range by itself. It tries the versions chosen this way:

- **No `--versions` and no `--last`:** two versions, sometimes three. `known` is the tool's `default_version`, the
  one cMeta installs today. `latest` is the newest version `latest` may take. When a limit of `latest` excludes
  the newest version, that version is tried too.
- **`--versions=a,b,...`:** exactly these: version numbers, or the words `known` and `latest`.
- **`--last=<n>`:** the `n` newest released versions, without pre-releases, of the list the tool publishes.

`known`, `latest` and the list come from `cx tool setup <tool> --versions`. That lookup is cached per tool in
`tmp::tool-versions/<tool>.json` for 24 hours (`--refresh_versions` of this task asks again):

- the list is the output of the tool's `cmd_get_versions`: the release tags on GitHub for yq,
  `uv python list --all-versions` for Python (what the machine's uv can install);
- the newest version comes from the tool's channel (winget, brew, apt, pip, ...) or from upstream.

The first lines of a run name each version and why it is tried, e.g. `4.53.6 (known), 4.54.1 (latest)`.

## How each version is tried

- **One version, one fresh entry:** the setup runs with `--new`, so an entry made before is never what is
  judged. The entry is removed afterwards unless `--keep`. A failed attempt stays as a `failed` entry
  (`cx cache clean --failed` removes those). A program run keeps its entries.
- **With `--program`:** the program runs with `--use.<use_key>.version=<version>`. `use_key` is the tool's alias
  unless named, e.g. `compiler-c`. The `--use` words of this command line reach the program too. A tool that another
  tool sets up with a version of its own needs the key of the one asked for: `llvm` under `clang` takes
  `--use_key=compiler-c` (the compiler's version, which clang hands to llvm); `--use.llvm.version` alone leaves the
  compiler asking for the clang of the known llvm, and every newer version fails (the round of 2026-10-17).
- **A crash is a verdict:** a sub-task that raises gives a failed verdict of class `crash`, and the other versions
  are still tried.

## Where the verdicts go

To one JSONL file, one JSON object per line, written as each version finishes:

- **The file:** `--output`, by default `explore-tool-versions-<tool>-<host>-<stamp>.jsonl` in the current
  directory. The host name in the default name keeps files from several machines apart in one folder.
- **A test session:** when the shell has one (`CMETA_TEST_SESSION`), the file is also copied into it, under
  `attachments/` of its record.
- **The fields:** `tool`, `version` (asked), `chosen_as` (known, latest, asked, ...), `obtained`, `program`,
  `works`, `stage` (setup or program), `error_class`, `error` (its first line), `limit` (the limit of `latest`
  that excludes the version), `seconds`, `host` (uname, arch, os, hostname, python), `cmeta`, `aops`, `time`.
- **The error classes:** not available, checksum, download, build, crash, else the stage.

## Several machines and `--promote`

`--promote` reads verdict files, nothing else: it never contacts a machine. To use several machines:

1. Run the same exploration on each machine.
2. Put their verdict files in one folder; files that come from a test session can stay where they are.
3. Run `--promote --verdicts=<that folder>` once. A folder is read recursively (its `*.jsonl`); several files or
   folders are separated by commas.

It groups the verdicts by tool and by version: the one obtained, else the one asked. It prints the evidence (where
each version worked and where it failed, with the class of the error), then the proposals:

- **A next `default_version`:** the newest version, newer than `default_version` and not a pre-release, that
  worked wherever it was tried, on at least `--min_os` operating systems (2).
- **A limit of `latest`:** a version newer than `default_version` that failed somewhere for a reason other than
  "not available" and that no limit excludes yet. The proposal is a `latest_limits` entry with the class and the
  first line of the error, and today's date.
- **A note:** a version that some machine's channel does not offer (an older uv, a missing release asset) and
  that failed nowhere else. It is not a limit, because `latest` never takes a version the channel does not list;
  the fix is to update the channel on that machine.

It never changes a tool's meta. A person reads the evidence and commits the change.

The verdicts stay in test sessions until their shape has settled; a public category of verdicts (the crowd layer)
comes after.
