# system-ssh-server

The system's own OpenSSH server of a Linux machine: key logins only, the fleet's key for this machine allowed, and
started at every boot by systemd - before anyone logs in, and without the cMeta repositories. That matters on a
machine whose repositories are on a drive unlocked later (a dual-boot laptop whose data is on a BitLocker drive): one
reaches it over ssh, then unlocks the drive.

```bash
cx task run system-ssh-server                      # status: installed, running, at boot, keys only, the keys allowed
cx task run system-ssh-server enable               # the fleet's key of this machine (cx host whoami)
cx task run system-ssh-server enable --host=<host> # the key of another host artifact
cx task run system-ssh-server enable --key=<file or <category>::<artifact>/<file>>   # a public key of your choice
cx task run system-ssh-server disable              # stopped, not started at boot; its settings and keys stay
```

## What `enable` does

1. Installs the OpenSSH server when it is missing (`apt-get install openssh-server`, or dnf), with sudo.
2. Writes `/etc/ssh/sshd_config.d/50-cmeta-keys-only.conf`: no passwords and no keyboard-interactive logins, root by
   key only. `sshd -t` checks the configuration; a configuration it refuses is removed again.
3. Adds the public key to `~/.ssh/authorized_keys` (once; the folder 700, the file 600). By default the key the fleet
   reaches this machine with: `cx host whoami` names the host artifact, `cx host key` its key (`access.key`, a `.pub`
   beside it). A private key file is refused.
4. `systemctl enable --now` the server's unit (`ssh.socket` on Ubuntu 22.10 and newer, else `ssh.service` or
   `sshd.service`), and has a running server read its settings again.

## Not this task

- **Windows**, or a machine whose repositories are there at boot: cMeta's own server, run as the user -
  `cx task run start-after-restart enable --what=ssh` (run-openssh, port 2222).
- **macOS:** Remote Login in System Settings.
