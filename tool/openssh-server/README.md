# openssh-server — the OpenSSH server (sshd)

`cx tool setup openssh-server` finds or gets the OpenSSH server program, `sshd`, for
[`task/run-openssh`](../../task/run-openssh/README.md), which runs it as the user on a port of its
own. The tool only provides the program: it starts nothing and changes no system configuration.

```bash
cx tool setup openssh-server
cx tool run openssh-server -- -V          # sshd's version
```

## Per system

| System | Where `sshd` comes from |
|---|---|
| Windows (x64, ARM64) | the portable [Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH) release, downloaded into the cMeta cache |
| Linux | the system's `sshd` (`/usr/sbin/sshd`); when it is missing, the `openssh-server` package of the distribution's package manager (needs sudo) |
| macOS | the system's `sshd` (`/usr/sbin/sshd`), part of macOS |

### Windows

The release zip (`OpenSSH-Win64.zip` or `OpenSSH-ARM64.zip`) is downloaded from GitHub, checked
against the SHA-256 pinned in `api_v1.py` and unpacked into the tool's cache entry, with the
programs that `sshd.exe` starts for each login (`sshd-session.exe`, `sshd-auth.exe`), `ssh-keygen`
and `sftp-server`. Nothing is installed in the system: no installer, no service, no administrator
rights, and the optional Windows feature "OpenSSH Server" is neither needed nor touched.

The pinned release is `RELEASE` in `api_v1.py`; a new release needs its two SHA-256 digests (from
the GitHub release page or its API) in `ASSETS`.

### Linux and macOS

`sshd` is found in `PATH` and in `/usr/sbin`, where distributions and macOS keep it even when
`/usr/sbin` is not in a user's `PATH`. Its version is read from `sshd -V`.

## Version

The version is the OpenSSH version that `sshd -V` prints, for example `10.0p2` on Windows
(`OpenSSH_for_Windows_10.0p2`) or `9.6p1` on Ubuntu 24.04 (`OpenSSH_9.6p1 Ubuntu-...`).
