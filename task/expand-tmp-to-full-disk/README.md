# expand-tmp-to-full-disk: /tmp on the disk, not in RAM

Ubuntu 26.04, Fedora and Arch mount `/tmp` as a **tmpfs**: a filesystem in RAM (and swap) of half the
memory, on Ubuntu with a per-user quota (`systemd`'s `tmp.mount`, `size=50%`, `usrquota`). Tools that
unpack in `/tmp` then fail on a machine with hundreds of GB free: pip with a 6 GB wheel ("Disk quota
exceeded"), an archive extracted by an installer ("No space left on device").

```bash
cx task run expand-tmp-to-full-disk            # do what is missing
cx task run expand-tmp-to-full-disk --check    # only report: what /tmp is, what would change
cx task run expand-tmp-to-full-disk --dry_run  # the commands, nothing runs
```

## What it does on Linux

| Step | Command | Holds |
|---|---|---|
| `mask` | `systemctl mask tmp.mount` (when the tmpfs comes from systemd's unit) | from the next boot |
| `fstab` | the `tmpfs /tmp` line of `/etc/fstab` commented out (a backup `/etc/fstab.cmeta-backup`) | from the next boot |
| `unmount` | `systemctl stop tmp.mount` or `umount /tmp`; when a process holds a file there, `umount -l /tmp` (lazy: new opens go to the disk, that process keeps its file) | at once |
| `mode` | `chmod 1777 /tmp` when the folder beneath had lost it | at once |

The folder `/tmp` of the root filesystem, which the tmpfs hid, is `/tmp` afterwards: world-writable with
the sticky bit, cleaned at boot by `systemd-tmpfiles` as before. What was in the tmpfs is gone with it
(it was temporary). A `/tmp` on its own disk partition is left alone.

Every step needs root: `sudo -n` (never a hidden prompt) unless the run is interactive (a terminal,
without `-q`), where `sudo` may ask once. Without passwordless sudo a non-interactive run fails and prints
the commands to run by hand.

## Other systems

- **macOS:** `/tmp` is `/private/tmp` on the root volume: the task reports its free space and does nothing.
- **Windows:** the task stops with an error. `TEMP` is a folder on a disk already.

## The result

`before` and `after` (`fstype`, `source`, `options`, `total`, `free` of `/tmp`), `steps` with their return
codes, `changed`, `ready` (`/tmp` is on a disk now) and `reboot` (the lasting part is done, the tmpfs could
not be unmounted: a reboot finishes it).

## The alternative that keeps the tmpfs

A tmpfs without the quota and with a larger share of the memory is a drop-in for the unit
(`systemctl edit tmp.mount`, `Options=mode=1777,strictatime,nosuid,nodev,size=90%,nr_inodes=1m`), still
limited by RAM plus swap. This task does not do that: the request was the whole disk.
