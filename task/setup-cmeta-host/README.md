# Prepare a cMeta host

`setup-cmeta-host` prepares selected services on **the machine where the task runs**.
It preserves the active cMeta home. Run it after installing cMeta and registering
this repository. Existing `run-openssh`, `start-tailscale-service`, and
`prevent-mac-to-sleep` tasks keep their behavior.

```text
cxt setup-cmeta-host
cxt setup-cmeta-host --check -q
cxt setup-cmeta-host --dry_run -q --profile=ssh
cxt setup-cmeta-host -q --apply --ssh --tailscale- --keep_awake-
```

In a terminal, the default mode explains and asks about each service, shows the
configuration, and asks whether to apply. The final answer defaults to **no**.
`-q` suppresses questions; it does not imply apply or select every feature.
Without a terminal, the default is inspection only. Scripted changes require
`-q --apply`. `--check` and `--dry_run` never configure services or install tools.
`--apply --dry_run` is a preview. `--check --apply` is an error.

| Profile | Initially selected |
| --- | --- |
| `fleet` (default) | SSH, Tailscale |
| `ssh` | SSH |
| `managed` | None: inspect an existing managed machine |
| `slurm` | None: do not change cluster-managed workers |
| `kubernetes` | None |
| `aks` | None |
| `mpi` | None: the MPI runtime and its transport belong to the workload |

Every feature can be selected or deselected with `--ssh`, `--ssh-`,
`--tailscale`, `--tailscale-`, `--keep_awake`, `--keep_awake-`,
`--boot_unlock`, and `--boot_unlock-`. Deselect means **leave alone**, including
an already running service. This task does not stop or uninstall services.
SSH is necessary only when choosing SSH as the remote execution transport.

## Windows

Apply needs an elevated terminal. SSH and Tailscale services are made Automatic
and started. SSH failure recovery restarts it after 60 seconds, three times.
An existing SSH configuration, host keys, authorized keys, ports, and firewall
rules remain. An existing sshd outside the OS drive needs explicit relocation:

```text
cxt setup-cmeta-host -q --apply --profile=ssh --sshd_source="D:\Tools\OpenSSH"
```

The entire package is copied and hash-checked into
`<SystemDrive>\Program Files\cMeta\OpenSSH`. The original stays. A running
service keeps its current process; the new binary is used on its next start.
Custom sshd service arguments and an existing destination require manual review.

If sshd is missing, the task uses the existing cMeta `openssh-server` tool
(its download verification/version selection stays there), copies the complete
package onto the OS drive, and creates only the sshd service. It preserves
ssh-agent. Supply `--keys=<public-key file>`; the wizard asks for it if missing.
The new server disables password/keyboard-interactive login and defaults to
IPv4 port 2222. Keys are added to `administrators_authorized_keys`, for Windows
administrator accounts. Non-administrator accounts use their own
`.ssh/authorized_keys`. Config and administrator keys are limited to
SYSTEM/Administrators. The binaries also allow authenticated users to read/execute.

`--port=2222` and `--remote_address=100.64.0.0/10` configure a **new** server
and its firewall rule. Existing SSH ports/rules are not rewritten. Existing
broader firewall allow rules can also admit traffic; inspect them when selecting
the intended access network. Verify the host-key fingerprint at the target before
trusting it from the controller.

Tailscale must already be installed, authenticated and Running. Setup enables
`tailscale set --unattended=true`, without changing identity, routes, or key
expiry. Inspection returns only safe status/preferences fields; full debug
preferences contain credentials and are never returned.

`--keep_awake` sets AC idle sleep and AC idle hibernation to Never. Battery
settings, lid/power-button actions and manual sleep remain separate.

## Windows data-volume unlock before login

Use only when the cMeta home/tools sit on a BitLocker data volume that is still
locked before login. Native machine auto-unlock is preferable when supported.
Some removable volumes instead have user-scoped auto-unlock that starts after login.
An elevated `--check --report=<new file>` lists volume GUIDs, persistent IDs and
external protector IDs without exporting key contents.

```text
cxt setup-cmeta-host -q --apply --profile=managed --boot_unlock --drive=D: --volume_guid=<guid> --persistent_id=<guid> --protector_id=<existing-external-key-guid>
```

Prerequisites: the OS volume is 100% encrypted with protection On
(`UsedSpaceOnlyEncrypted` is accepted); the exact data volume is currently
unlocked; the selected external-key protector already exists. Encryption,
recovery-key backups and protector creation are separate local operations.

The task exports that existing `.BEK` directly into
`<SystemDrive>\ProgramData\cMeta-BootUnlock`. This directory permits only SYSTEM
and Administrators. Key bytes never enter cMeta context, the controller, reports
or logs. Existing password/recovery/external protectors remain.

It copies `scripts/unlock-data.ps1`, writes protected identity configuration, and
registers `cMeta-Unlock-Data-AtStartup` as SYSTEM/Highest, delayed 15 seconds.
The helper waits up to 180 seconds for the exact volume GUID **and** persistent
ID, requires its expected drive letter and OS protection On, unlocks if needed,
and writes safe `last-run.json`. Setup checks an initial SYSTEM run; a separate
reboot-before-login test is still required. No reboot is performed by this task.
Only one data-volume task is provisioned. Existing unlock directories/tasks are
never replaced; rerun inspection instead. Partial failures remain for review.

For maintenance, inspect `Get-ScheduledTaskInfo cMeta-Unlock-Data-AtStartup` and
the protected `last-run.json`. If the disk arrives after the retry window, run
`Start-ScheduledTask cMeta-Unlock-Data-AtStartup`. Before removing this mechanism,
confirm another unlock method and recovery backup, unregister the task, and
remove its exact protected directory locally. Never attach its `.BEK` to a report.

## Linux and macOS

Linux uses existing distro SSH and Tailscale systemd services; install those
through your normal tooling first. It detects `ssh.service` or `sshd.service`
and enables/starts only selected services. It preserves SSH configuration,
authorization, ports and firewall rules. `--keep_awake` masks sleep, suspend,
hibernate and hybrid-sleep targets **on all power sources**; record their prior
mask state before restoring them. Non-systemd Linux needs a separate service backend.

macOS uses Remote Login (`systemsetup`) for SSH and, if selected, the installed
Homebrew Tailscale formula via `brew services start tailscale`, as the existing
macOS helper does. GUI/App Store Tailscale clients have different startup behavior;
this task does not replace them or claim unattended access for them. System
permissions such as Full Disk Access may need to be granted locally. AC idle
sleep can be disabled with `pmset -c sleep 0`.

Unix apply uses sudo when needed; quiet runs use `sudo -n` and fail if a password
is required. No command silently changes sudoers or reboots a host.

## Register on the controller, then execute through the chosen transport

```text
cxt setup-cmeta-host --check -q --profile=managed --report=host-setup.json
cx host add <private-repo>:<host-alias> --yaml
```

Setup and registration are separate. The report contains safe observed metadata,
selected features/profile and the active cMeta home; it refuses to overwrite a
previous file. On the controller, use the available fleet `host` category to
create an artifact, fill its `_desc.yaml`, then probe it. A direct SSH example:

```yaml
type: ssh
os: windows

access:
  hostname: TARGET-PC
  address: 100.x.y.z
  port: 2222
  user: Windows user
  key: <controller-side private-key artifact reference>
  shell: powershell
  options: -o StrictHostKeyChecking=yes

cmeta:
  home: 'D:\CMETA'
  install: uv-tool

sync:
  default: none
```

The fleet host category is currently in a separate/private repository. This public
task has no dependency on it. A `machine` asset can be linked separately. Do not
copy private keys onto workers or infer controller key paths from a public-key file.

For Slurm, register the login/submission host using its actual access transport;
worker inventory and a Slurm cluster entry should describe partitions, node names,
GPU resources and allocations. A future submission task should use `sbatch`/`srun`
and let the scheduler allocate workers, rather than directly occupying their GPUs.
Kubernetes/AKS targets should reference a controller kubeconfig context/namespace
and launch Jobs with the cMeta environment in their image. MPI should be a workload
launcher selecting its runtime, ranks and scheduler/SSH transport. Neither a host
artifact nor this setup task enrolls a worker into a cluster. These profiles are
setup defaults and metadata only; scheduler/API execution adapters are future work.

## Validation and references

The prototype has local Windows read-only CLI checks, a read-only NucBox inspection,
and automated selection/quiet/preview/identity tests. The boot helper is executed
in child Windows PowerShell processes against mocked volumes, including wrong-drive
and unprotected-OS refusals. Its original NucBox procedure was verified before login
after a real reboot. The generalized provisioner has not been used to reconfigure
a live host; Linux/macOS apply and new Windows SSH installation need disposable-host
integration tests before relying on them for unattended recovery.

- [Microsoft OpenSSH setup](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- [Win32 OpenSSH installer/service privileges](https://github.com/PowerShell/openssh-portable/blob/latestw_all/contrib/win32/openssh/install-sshd.ps1)
- [Tailscale unattended mode](https://tailscale.com/kb/1088/run-unattended)
- [Apple systemsetup](https://support.apple.com/en-ie/guide/remote-desktop/apd95406b8d/mac)
- [Slurm srun](https://slurm.schedmd.com/srun.html)
- [AKS kubeconfig access](https://learn.microsoft.com/en-us/azure/aks/control-kubeconfig-access)
- [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
- [Open MPI with Slurm](https://docs.open-mpi.org/en/main/launching-apps/slurm.html)
