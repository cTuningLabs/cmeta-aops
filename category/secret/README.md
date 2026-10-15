# secret: identities and credentials as cMeta artifacts

A `secret` artifact describes ONE identity or credential: a git identity (name, email, the ssh key that pushes, the
key that signs), an ssh key alone, a token, a file. The meta (`_desc.yaml`) never holds a value: it names files
inside the artifact (self-contained), files in another artifact (a cRef such as `my-vault::ssh-work/2026/...`)
or an environment variable (`env:GITHUB_TOKEN_RO`). Where the artifact lives decides who can see it: a repository
with `secrets: true` in its `_cmr.yaml` (a private repository of the person, kept apart from the repositories that travel) is never synced to a
host, never zipped, never read by an agent, and has no public remote.

Written 2026-10-15 as the example of the "run on any host" design (the work item "improving default tool versions
in cmeta-aops", `20261015.summary-on-design5.md`). The category moves to cmeta-aops with its UID when the design is
built; the artifacts stay private. Today the engine's generic commands work (`cx secret find`, `cx secret ls` and
`cx secret show` of `api/v1.py` print references only; `cx secret check` looks at the files); `import`, `generate`,
`use`, `render` and the channels into containers and hosts come with the implementation.

## Kinds

```
kind: git       a whole git identity: identity (name, email, accounts), ssh (transport key, passphrase policy,
                hosts), signing (format, key, allowed signers, sign_commits)
kind: ssh       one ssh key: key, public_key, passphrase, hosts, users
kind: token     one secret value by reference: env: NAME, or a file inside: files/token
kind: file      any file by reference (a certificate, a keystore): files: {...}
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

## Commands (today and planned)

```
cx secret ls                                   # alias, kind, repository, hosts, used by - never a value
cx secret show <alias>                         # the references of one identity
cx secret check [<alias>]                      # the files exist, the mode, passphrase as declared, the variables set
cx secret import [<alias>] [--force]           # copy the files in from files.from (files.names), tighten the private
                                               # key, mark files.status imported (done 2026-10-15 for the four)
cx secret generate <alias>                     # planned: a new key pair
cx secret use <alias> --repo=<path> [--global] # planned: write the identity into a clone's .git/config (name, email,
                                               #          core.sshCommand, gpg.format, user.signingkey, allowed signers)
cx secret render <alias> --out=<file>          # planned: a standalone .gitconfig (+ the ssh config stanza)
```

With the "run on any host" design: `--secret=<alias>,<alias>` on a run, or `on: {secrets: [...]}` in a task, gives
an instance the identity through one of four channels chosen by host type: a build-time secret mount (an image that
clones a private repository), a temporary run-time env file, read-only file mounts of the keys, ssh-agent
forwarding. Nothing is baked into an image.
