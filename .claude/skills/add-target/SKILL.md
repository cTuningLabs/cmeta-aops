---
name: add-target
description: Add a compute target - a `task/target--<name>` artifact - to any cMeta repository, a private one too, with its `support`, its set-up, its `probe` and what it tells tools and instances, so that `--compute=<name>`, `cx program targets`, `detect-targets` and `--compute=auto` find it with no change of shared code. Use when asked to "add a target / backend / accelerator", "support a new GPU / NPU / device", "add a private backend", or whenever code is about to name targets in a list.
---

# add-target - a compute target is an artifact, found by query

A **target** is what `--compute=<name>` names: a CPU, a GPU, an NPU, a stack over them, another device driven from
the machine. It is one artifact, `task/target--<name>`, in **any** repository. Nothing else names it:

| Who | Finds targets by |
|---|---|
| `cx program run <program> --compute=<name>` (the task `target`) | the alias `target--<name>` among the repositories plugged in |
| `cx program targets` | every `target--*` and its `support:` block |
| `cx task run detect-targets`, `--compute=auto` | every `target--*` and its `probe:` block |
| shared code that needs a fact of a target | `ctask.targets(cm)` (below) |

So a backend that must not be public is a target in a repository of its own, and its programs beside it. A call that
must not see that repository (`--hide_repos`, a site's clearance) neither probes nor names the target.

The guide with every probe check: [`task/target/README.tech.md`](../../../task/target/README.tech.md).

## 1. Scaffold

```bash
cx task add <repository>:target--<name> --yaml      # a bare name lands in the local repository
```

Remove the `copyright:` key it writes, keep `authors:`. Then write `_desc.yaml`; add `api_v1.py` only when the
target detects features of its own (what `cx task run detect-targets --full` shows: devices, versions, capabilities).

## 2. `_desc.yaml`

```yaml
store_global: True
storage_key: target--<name>
cache: True

uses:                                  # its set-up: the driver, runtime or SDK as cMeta tools
  - task: setup,a2f9b61079ce4333
    name: <tool>

env_if_not_used:                       # what programs see when the target is not asked for ...
  CMETA_TARGET_<NAME>: 0
env:                                   # ... and when it is
  CMETA_TARGET_<NAME>: 1

support:                               # read by "cx program targets"
  kind: gpu                            # cpu, gpu, npu, stack, app
  hardware: '<what it is>'
  host_os: [linux, windows, darwin]    # where cMeta runs
  device_os: android                   # only for another device driven from the host (android, ios)
  status: supported                    # or placeholder

probe:                                 # read by detect-targets: per OS (linux, windows, darwin) or all
  linux:
    any:
      - {pci: {vendor: ['0x<id>']}}
```

Optional facts, each read by shared code through the query - declare them, never add the name to a list in code:

| Key | Says | Read by |
|---|---|---|
| `auto: portable` | an interface over the devices of other targets (opencl, vulkan, openvino): `--compute=auto` takes it only when no accelerator of the machine itself fits | `detect-targets` |
| `support.device_os` | another device: never the choice of `--compute=auto` by itself; pushed to and run on the device | `detect-targets`, `setup-run`, `compile-and-run-program` |
| `instance_overlay: [docker, podman, wsl]` | in such an instance (`--on=docker` ...) the device must be given to it: the instance is made with the template's compute overlay of this target's name, and a template without one stops the run | the task category (`--on`) |
| `backends: {<tool's storage key>: <backend>}` | the backend of a tool that this target selects, for a tool that does not list the target itself | `InitCTool.target_backends` |

A probe is cheap by contract (it runs at every `--compute=auto`): a file, a device id, a driver. For a device no
declared check describes, `{script: probe.py}` calls `probe(host)` of that file of the artifact. What takes time
belongs to the target task itself.

## 3. Programs and tools

- A program lists the targets it supports in `constraints.supported_compute` (its `_cmeta`); a dependency of one
  target is gated in its `uses` (`if: '"<name>" in {{global.target.compute|$[]}}'`).
- A tool with backends of its own maps targets to them as **data**: `target_backends:` in the tool's `_desc.yaml`
  (`tool/llama-cpp` is the worked case), read with `self.target_backends(compute)`.

## 4. The rule: no target names in shared code

Shared code - the task category, `setup-run`, `compile-and-run-program`, `detect-targets`, the instance tasks, a
page - never holds a list of target names, and never tests `compute == '<name>'` to decide something a target
could say about itself. It asks:

```python
from task_c36be4b9314a45e0.api.ctask import targets, targets_on_device, instance_compute

found = targets(self.cm)                                   # {name: its _desc.yaml}, every repository the call sees
android = targets_on_device(found, compute, 'android')     # a fact of the targets, not a list of three names
overlay = instance_compute(found, compute, 'docker')       # which target asks for its overlay in a container
```

When a new fact is needed, add a key to the targets' descriptions and read it this way.

**Where a target's name is right:** inside an adaptor that chooses among what *its* tool, library or vendor
supports - the wheel index of a CUDA version, the CMake flag of one backend, a check of NVIDIA's driver libraries, a
program's own `if:` conditions. That is a selector for a supported version, and it lives with the tool or program
it belongs to, as data where it can be.

## 5. Verify

```bash
cx program targets                                  # the target with its support block
cx task run detect-targets                          # there or not, its devices
cx task run detect-targets --supported=cpu,<name>   # what --compute=auto would take
cx task run detect-targets --hide_repos=<repository>   # a private target: not listed, not named
cx task run target --compute=<name>                 # its set-up runs
```

- [ ] the target is found on every OS in `support.host_os`, and absent where its device is not
- [ ] no file outside the target artifact (and its programs and tools) names it
- [ ] `python -m pytest tests/cmeta_aops_basic_tests/test_detect_targets.py tests/cmeta_aops_basic_tests/test_targets_from_the_graph.py`
      (a probe word the task does not read fails the first; a list of names back in shared code fails the second)
