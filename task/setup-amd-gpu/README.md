# setup-amd-gpu: a Linux machine made ready for its AMD GPU and NPU

The kernel drivers give an AMD GPU (`amdgpu`) and a Ryzen AI NPU (`amdxdna`) their device nodes, and a
fresh account still cannot compute on them:

| What a run opens | Owner | Who can open it on a fresh system |
|---|---|---|
| `/dev/dri/renderD*` (Vulkan, OpenCL, ROCm) | `root:render` | a desktop login, through an ACL of its seat |
| `/dev/kfd` (ROCm) | `root:render` | the same |
| `/dev/accel/accel*` (the NPU) | `root:render` | the same |

A login over ssh, a service and a container are not a desktop login. The NPU runtime (XRT) also locks its
buffers in memory, beyond the default limit of a login.

```bash
cx task run setup-amd-gpu              # do what is missing
cx task run setup-amd-gpu --check      # only report
cx task run setup-amd-gpu --dry_run    # the commands, nothing runs
cx task run setup-amd-gpu --npu-       # leave the NPU alone (the rocm target calls it this way)
```

## What it does

| Step | Command | Holds |
|---|---|---|
| `groups` | `usermod -aG render,video <user>` (the groups that own the nodes; `video` with a GPU, as AMD's ROCm guide asks) | from the next login |
| `access` | `setfacl -m u:<user>:rw <nodes>` | at once, until the next boot |
| `memlock` | a line in `/etc/security/limits.d/90-amd-npu-memlock.conf` (with an NPU) | from the next login |
| `memlock-now` | `prlimit --pid <the cx process> --memlock=unlimited:unlimited` (with an NPU) | at once, for this run |

Only the missing steps run. The "at once" steps let the run that called the task go on without a new login;
the lasting ones make the next login right by itself. Until that next login, each run lifts the memory-lock
limit of its own process again (`memlock-now`); after it, a run finds everything in place and changes nothing. Without `setfacl` on the
system the task says that a new login is needed.

Every step needs root: `sudo -n` (it never waits at a hidden prompt) unless the run is interactive (a
terminal, without `-q`), where `sudo` may ask once. Without passwordless sudo a non-interactive run fails and
prints the commands to run by hand.

## The result

`devices` (`gpus`, `kfd`, `npus` with the PCI address, the driver, and for an NPU its firmware version),
`access` per node after the run, `steps` with their return codes, `changed`, `ready` and `relogin`.

## Where it is used

The `rocm` target runs it first (`task/target--rocm`), so `cx program run <program> --compute=rocm` on a fresh
machine sets the access up by itself. ROCm's own packages are not installed here: `tool/rocm` and the tools a
program needs do that. On Windows the AMD driver brings everything, and the task does nothing.
