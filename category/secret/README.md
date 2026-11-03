# secret: identities and credentials as cMeta artifacts

A `secret` artifact describes ONE identity or credential: a git identity (name, email, the ssh key that pushes, the
key that signs), an ssh key alone, a token, a file. The meta (`_desc.yaml`) never holds a value: it names files
inside the artifact (self-contained), files in another artifact (a cRef such as `my-vault::ssh-work/2026/...`)
or an environment variable (`env:GITHUB_TOKEN_RO`). Where the artifact lives decides who can see it: a repository
with `secrets: true` in its `_cmr.yaml` (a private repository of the person, kept apart from the repositories that travel) is never synced to a
host, never zipped, never read by an agent, and has no public remote.

Written 2026-10-15 as the example of the "run on any host" design (the work item "improving default tool versions
in cmeta-aops", `20261015.summary-on-design5.md`). The category moves to cmeta-aops with its UID when the design is
built; the artifacts stay private. `cx secret ls` and `cx secret show` print references only, `check` looks at the files,
`import` copies them in, `generate` makes a key pair, `use` and `render` give a git identity to a clone or a machine (since
2026-10-17); the channels into containers and hosts come next.

## Kinds

```
kind: git       a whole git identity: identity (name, email, accounts), ssh (transport key, passphrase policy,
                hosts), signing (format, key, allowed signers, sign_commits)
kind: ssh       one ssh key: key, public_key, passphrase, hosts, users
kind: token     one secret value by reference: env: NAME, or a file inside: files/token
kind: file      any file by reference (a certificate, a keystore, a dotenv): file: {path: files/<name>}
```

## Where the files are

```
ssh:
  key: files/id_ed25519_x                      # inside this artifact: self-contained (recommended: one folder = one identity)
  key: my-vault::ssh-work/2026/id_ed25519      # in another artifact: a reference (a key that must stay where it is)
  key: env:MY_KEY_PATH                         # from the environment of the run
```

`files.status: not imported` plus `files.from: <cRef>` says the files are not here yet; `cx secret import <alias>`
copies them in from `from` (keeps the original), `cx secret generate <alias>` makes a new key pair (ssh-keygen).
A private key inside an artifact is owner-only: `import` tightens it and `check` verifies it through the public
task `fix-ssh-key-permissions` (mode 600 on Linux and macOS; on Windows an ACL of the user alone with SYSTEM and
Administrators read, by SIDs - the rule of the author's fix-permissions.bat, now on every OS).

## Passphrases

`ssh.passphrase: ask | agent | none`: `ask` = the key has a passphrase and an interactive prompt is fine (the human's
key), `agent` = the key has a passphrase and must come from an ssh-agent (a quiet run with no agent fails before
starting), `none` = the key has no passphrase (automation, containers, hosts). Never a value here. An identity with
`ask` or `agent` is refused by a quiet run (`-q`) with the cure: use its `without-pass` twin.

## A token typed in, kept with a password

`cx secret store <alias>` keeps the value of a token secret that you type (paste) at a hidden prompt: it is never
printed, and it is written to the artifact readable by you alone (mode 600; on Windows the owner-only ACL). With
`--password_protected` it is encrypted with a password you choose (asked twice), and every use asks for that
password again - a copy of the file, a backup or a program that reads files gets nothing usable without it:

```
cx secret add my-vault:my-pypi --yaml --desc.service=pypi      # the artifact first; service: what it is for
cx secret store my-pypi --password_protected                    # the token, then the password twice
cx secret check my-pypi --unlock                                # does the password open it? (nothing printed)
```

```
# secret/my-pypi/_desc.yaml (service by add, the rest by store)
service: pypi                   # the task upload-to-pypi takes this secret when --secret names none
kind: token
password_protected: true        # encrypted: the password is asked at each use
token:
  file: files/token.sealed      # the encrypted value (the plain form would be files/token)
  stored: '2026-11-03T18:10+01:00'
```

The encryption uses Python's standard library alone: two keys from the password by scrypt (n=2^17, r=8, p=1, a new
random salt each time), the value XORed with an HMAC-SHA256 key stream, an HMAC-SHA256 tag over the parameters and
the encrypted value (encrypt-then-MAC). `files/token.sealed` is a small JSON text (`format: cmeta-secret-sealed-v1`)
that holds no trace of the value or the password; a wrong password and a changed file are both refused by the tag.
A short password keeps the value from a casual reader, not from someone who copies the file and tries passwords for
long: prefer a passphrase, and a token with the narrowest scope the service offers (a PyPI token for one project).

`cx secret run <alias> --env.<NAME>={secret} -- <command>` runs a command with the value in its environment and
nowhere else (not on its command line, not in a file, not in cMeta's own environment); `{secret}` stands for the
value in the text of a variable. A password-protected secret asks for its password first, and a quiet run (`-q`) is
refused. On Windows, from a process without a terminal (an AI agent) or with `--window`, all of it happens in a
console window of its own: the password is typed there, the command runs there, SUCCESS or FAILED stays on the screen
until Enter, and the output and the verdict come back to the process that waited. The task `upload-to-pypi` uses it
for twine (`TWINE_PASSWORD`), taking the token secret that declares `service: pypi` when `--secret` names none.

## Commands

```
cx secret ls                                   # alias, kind, repository, hosts, used by - never a value
cx secret show <alias>                         # the references of one identity
cx secret check [<alias>] [--fix] [--unlock]   # the files exist, the mode, passphrase as declared, the variables set;
                                               # --fix makes a key of the artifact that others can read owner-only;
                                               # --unlock: does the password open a sealed value (since 2026-11-03)
cx secret which <cat>::<artifact>/<file>       # the secret holding a copy of that file, and its path (since 2026-10-22)
cx secret import [<alias>] [--force]           # copy the files in from files.from (files.names), tighten the private
                                               # key, mark files.status imported (done 2026-10-15 for the four)
cx secret generate <alias> [--comment=..]      # a new ed25519 key pair without a passphrase at ssh.key (--force: over it)
cx secret use <alias> --repo=<path>            # the identity into a clone's .git/config (name, email, core.sshCommand,
cx secret use <alias> --git_global             # gpg.format, user.signingkey, commit.gpgsign, allowed signers), or the user's
cx secret render <alias> --out=<file>          # a standalone git config include file (+ the ssh config stanza)
cx secret store <alias> [--password_protected] # a token typed at a hidden prompt, kept owner-only or encrypted
cx secret run <alias> --env.<NAME>={secret} [--window] -- <command>   # the value in the command's environment alone
```

## On another machine: a copy of the keys a host references

A host artifact names its ssh key by a reference into a private repository that stays on the first machine
(`key: fgg.crypt::ssh-x/2026/id_ed25519`). A secret whose `files.from` is that folder (`fgg.crypt::ssh-x/2026`) and
whose `files.names` list the file holds a copy of it once imported; on a machine that has the secret and not the
private repository, `cx secret which fgg.crypt::ssh-x/2026/id_ed25519` names that copy, and `cx host` uses it.
The secrets a second orchestrator needs go there once, by name:

```
cx host push <host> my-secrets --artifacts="secret::git-work-without-pass;secret::ssh-cloud-vm" --secrets
```

into a folder readable by the host's user alone, followed there by `cx secret check --fix` (a copy over sftp
arrives readable by the group: 664). Nothing of the private repository travels, and `cx host sync` never takes a
repository with `secrets: true`.

With the "run on any host" design: `--secret=<alias>,<alias>` on a run, or `on: {secrets: [...]}` in a task, gives
an instance the identity through one of four channels chosen by host type: a build-time secret mount (an image that
clones a private repository), a temporary run-time env file, read-only file mounts of the keys, ssh-agent
forwarding. Nothing is baked into an image.
