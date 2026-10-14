# Windows Subsystem for Linux

This Windows-only tool detects the WSL runtime and can install or update it using
Microsoft's built-in `wsl.exe` commands. Installing WSL may require administrator
rights, hardware virtualization, and a Windows restart. cMeta does not restart
Windows automatically or install a default Linux distribution during tool setup.

```powershell
cx tool setup wsl
cx tool setup wsl --install
cx tool setup wsl --upgrade
cx tool run wsl -- --version
```

`--install` permits installation when detection finds no usable WSL runtime; it
does not reinstall an already detected runtime. Run the install from an
administrator PowerShell terminal and restart Windows if Microsoft requests it.
The bootstrap command requires a Windows release that supports
`wsl --install --no-distribution --web-download`; on older systems, follow
[Microsoft's manual installation steps](https://learn.microsoft.com/windows/wsl/install-manual).

## Linux distributions

List installed distributions and their WSL versions with the existing task:

```powershell
cxt list-wsl
cx tool run wsl -- --list --online
```

To install a distribution under a chosen name and storage folder, choose an
available distribution from the online list and use a recent WSL release:

```powershell
cx tool run wsl -- --install <distribution> --name <instance-name> --location <install-folder>
```

For an official `.wsl` image, verify its SHA-256 checksum against the publisher's
checksum file, then import it as an independent WSL2 instance:

```powershell
cx tool run wsl -- --import <instance-name> <install-folder> <image.wsl> --version 2
```

Replace the angle-bracket placeholders before running those commands. Importing
an image normally starts with root; create the intended Linux user and set
`[user] default=<username>` in `/etc/wsl.conf`, then terminate and reopen only
that instance. Each distribution owns its Linux filesystem and user accounts.

NVIDIA GPU access in WSL uses the Windows NVIDIA driver. Follow
[NVIDIA's WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html);
install a CUDA toolkit inside Linux only when a workload needs one. Docker
Desktop can integrate with selected WSL2 distributions through its
[WSL integration settings](https://docs.docker.com/desktop/features/wsl/).

References: [Microsoft WSL installation](https://learn.microsoft.com/windows/wsl/install),
[WSL command reference](https://learn.microsoft.com/windows/wsl/reference), and
[Ubuntu WSL installation](https://documentation.ubuntu.com/wsl/latest/guides/install-ubuntu-wsl2/).
