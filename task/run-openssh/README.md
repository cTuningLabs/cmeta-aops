# run-openssh — an OpenSSH server run as the user

`cx task run run-openssh` starts an OpenSSH server (sshd) as the current user, on a port of its
own, so another machine can log in for experiments: running tests and benchmarks remotely, or
joining an MPI or Ray cluster that starts its processes over SSH. It needs no system service, no
administrator rights and no change to the system's own SSH configuration, and it allows only key
logins with the keys it is given.

```bash
cx task run run-openssh --keys=<public key file>        # start (the default action)
cx task run run-openssh status                          # running? on which address and port?
cx task run run-openssh stop                            # stops the server and ends its logins
```

The start prints how to connect and the fingerprint of the server's host key:

```
INFO: OpenSSH server started (PID 10348) on 100.101.102.103:2222, 1 key(s) allowed
INFO: connect with: ssh -p 2222 <user>@100.101.102.103
INFO: host key: 256 SHA256:... cmeta-run-openssh-default (ED25519)
INFO: stop with: cx task run run-openssh stop --port=2222
```

## Options

| Option | Default | Meaning |
|---|---|---|
| first argument or `--action` | `start` | `start`, `status` or `stop` |
| `--keys` | `~/.ssh/authorized_keys` | the public keys allowed to log in: public key files, `authorized_keys` files or the keys themselves, separated by commas |
| `--listen` | the Tailscale address, else `127.0.0.1` | the address to listen on |
| `--port` | `2222` | the port to listen on |
| `--name` | `default` | a name for the server; several servers run side by side with different names or ports |

Examples:

```bash
cx task run run-openssh --keys=~/.ssh/id_ed25519.pub
cx task run run-openssh --keys=laptop.pub,desktop.pub --port=2223
cx task run run-openssh --keys="ssh-ed25519 AAAA... me@laptop"
cx task run run-openssh --listen=127.0.0.1               # this machine only (e.g. for a test)
cx task run run-openssh status --port=2223
cx task run run-openssh stop --port=2223
```

A start while the same server (name and port) runs only shows its status: stop it first to
change its address or keys.

## Where it listens

By default the server listens only on the machine's [Tailscale](https://tailscale.com) address,
the one `tailscale ip -4` reports, so only the machines of the same tailnet can reach it. The
address must be in Tailscale's range (100.64.0.0/10) and belong to this machine. Without the
`tailscale` command or a Tailscale address, the server listens on `127.0.0.1` and says so: only
the machine itself can connect then. Tailscale's address range is not trusted on its own, because
the carrier-grade NAT of some mobile and internet providers hands out addresses from the same
range.

`--listen=<address>` picks another address, for example a LAN address. `--listen=0.0.0.0` listens
on every network of the machine and prints a warning: the system firewall decides then who can
connect.

On Windows, Tailscale's own firewall rule (`Tailscale-In`) admits connections to its address, so
the server needs no firewall change there. Another address may need a firewall rule, which needs
administrator rights.

## Logins

- **Keys only:** password and keyboard-interactive logins are off. Only the keys of `--keys` (or
  of `~/.ssh/authorized_keys`) are allowed; they are copied into the server's own
  `authorized_keys`, so the user's file is never changed.
- **One user:** a server that a user runs can log in only that same user.
- **Windows:** a login gets `cmd.exe`, in the user's home folder.
- **Linux and macOS:** a login gets the user's shell. The server runs without PAM, so a login
  does not start a PAM session.
- **File transfer:** `scp` and `sftp` work where the server finds its `sftp-server`.

To connect from another machine, give `ssh` the private key that matches one of the allowed keys
and the port:

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519 <user>@<address>
```

or put it into `~/.ssh/config`, which MPI and other launchers read too:

```
Host my-laptop
    HostName 100.101.102.103
    Port 2222
    User <user>
    IdentityFile ~/.ssh/id_ed25519
```

The first connection asks to confirm the host key: compare it with the fingerprint that the start
printed.

## Stop

`stop` ends the server and every login it serves. On Linux and macOS each login is a child process
of the server that would otherwise outlive it; the task ends those children too, like
`taskkill /T` does on Windows.

The task recognizes its server by the PID it recorded and by the program name (`sshd`), so a PID
that another program has received since is left alone.

## The server and its files

- **Windows:** the portable Win32-OpenSSH release of
  [`tool/openssh-server`](../../tool/openssh-server/README.md), downloaded into the cMeta cache and
  checked against its pinned SHA-256. Nothing is installed in the system, and the Windows OpenSSH
  feature and its service are neither needed nor touched.
- **Linux and macOS:** the system's `sshd` (`/usr/sbin/sshd`), run as the user; the system's own
  SSH service and its configuration are not touched. On Linux, `tool/openssh-server` installs the
  `openssh-server` package with the package manager when `sshd` is missing (which needs sudo).

Each server keeps its files in the cache entry `task--run-openssh`, one folder per name and port
(`default-2222`, ...):

| File | Content |
|---|---|
| `ssh_host_ed25519_key`, `.pub` | the server's host key, made on the first start and kept, so clients see the same host key every time |
| `authorized_keys` | the keys allowed, written at every start |
| `sshd_config` | the configuration, written at every start and checked with `sshd -t` |
| `sshd.log` | the server's log |
| `sshd.pid`, `listen.txt` | the running server's PID and address |

```bash
cx cache find task--run-openssh        # the folder
```

Removing a server's folder removes its host key: clients then see a new host key and warn.

## Troubleshooting

- **`sshd rejects its configuration`:** the message carries sshd's own explanation, for example a
  port that another program uses or an address that is not on this machine.
- **The client cannot connect:** check `cx task run run-openssh status`, the address
  (`tailscale ip -4` on the server) and, for an address other than Tailscale's or `127.0.0.1`, the
  firewall. `sshd.log` in the server's folder shows refused keys.
- **`Permission denied (publickey)`:** the client's key is not among the allowed keys, or the
  client logs in as another user than the one who started the server.
- **A port below 1024** needs root on Linux; use a higher one.
