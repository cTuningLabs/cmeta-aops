# fix-ssh-key-permissions: the permissions OpenSSH wants on private keys, on any OS

OpenSSH uses a private key only when its owner alone can read it. On Linux and macOS that is no group or other
bits (`600`); on Windows it is an ACL without `Users`, `Authenticated Users` or `Everyone`, and Windows OpenSSH
says `UNPROTECTED PRIVATE KEY FILE` and ignores the key - while the tools built on it (rclone over sftp, git)
fail with an unrelated message. ssh also refuses a `~/.ssh` folder, `config` or `authorized_keys` that others
can write. This task makes or checks exactly those permissions - what ssh refuses, no more (the conventional
`700` on the folder and `600` on `config` are not demanded; `755` and `644` work and are left alone).

```
cx task run fix-ssh-key-permissions <file>                  # this key (a file named explicitly is tightened whatever it is)
cx task run fix-ssh-key-permissions <folder> [--recursive]  # every private key in it, found by its header
cx task run fix-ssh-key-permissions --ssh_dir               # ~/.ssh: the keys owner-only; folder, config, authorized_keys not writable by others
cx task run fix-ssh-key-permissions <path> --check          # report only: ok / too open, and who else can read
```

How it works:

- A private key is told by its first line (`-----BEGIN ... PRIVATE KEY-----`), never by its name; scripts, notes,
  `.pub` and `.ppk` files are never opened (by extension), and nothing of a key is printed.
- Linux and macOS: the forbidden bits are cleared (`chmod` keeps the rest); a key owned by another user is reported.
- Windows: `icacls` removes the inherited rules of a key and grants the user full access, SYSTEM and
  Administrators read; the check reads the rules with `Get-Acl` and compares SIDs (`S-1-5-18`, `S-1-5-32-544`,
  the user's own from `whoami /user`), so a localized Windows ("Administrateurs") or a domain account is handled
  the same as an English, local one. The `~/.ssh` folder and `config` are not looked at on Windows (its OpenSSH
  checks the keys alone).
- The result lists every path looked at with `ok`, `fixed` or `too open` and what was wrong; the counts
  `open` and `fixed` are returned for callers such as `cx secret import` and `cx secret check`.

Never memoized: every run looks at the files.
