# The hardware a tool needs — `hardware` in `_desc.yaml`

Some tools run only on given hardware: FastFlowLM's builds from 1.0.13 on use AVX-512 and stop at once with
"illegal instruction" on a processor without it. A tool can declare what the machine must have, and `task/setup`
checks it **before** downloading or building anything: a machine without it gets one clear sentence instead of a
download, an install and a crash. Without a declaration there is no check and nothing changes.

## The rules

```yaml
hardware:
  - versions: '>=1.0.13'        # the versions the rule is for (a fuzzy version, as in _desc_sizes.yaml); none: all
    cpu_features: [avx512f]     # the CPU features, as task::target--cpu names them
    why: the builds from 1.0.13 on use AVX-512 (AMD Ryzen AI processors have it)
```

The feature names are those of `task::target--cpu` (`cx task run target--cpu`): `sse2`, `ssse3`, `sse4_1`,
`sse4_2`, `avx`, `avx2`, `avx512f`, `neon`, `asimd`, `sve`, `sve2`, `aes`, `sha1`, `sha2`, `crc32`, `arm_v8`, and
on Linux and macOS any flag the CPU lists (`avx512bw`, `amx_tile`, ...). `why` goes into the message.

## The check

- Before an install and before a build, for the version being set up: a rule without `versions` counts for every
  version, one with `versions` only for a known version it matches - an unknown version is never refused.
- The CPU's inventory comes from `task::target--cpu` (cached per machine). A feature is missing only when the
  inventory read the CPU's flags and says it is not there; then the setup stops with "*<tool> <version> is not
  supported on this machine: it needs the CPU feature(s) avx512f, which this processor (<name>) does not have - <why>*".
- What the inventory cannot tell - no flags read at all (a container without `/proc/cpuinfo`, an unknown system), a
  name outside the list Windows answers for - only warns: an unseen system is never refused.
- `--skip_hardware_check` skips the check (to try anyway).
- `cx task run explore-tool-versions` records such a refusal as **not supported here**: it is neither a limit of
  "latest" nor a broken version, and its proposals list it as a note.

A tool can still check at run time what no rule can say before (`tool/flm` starts `flm version` once after
unpacking and names a missing NPU driver on Windows).
