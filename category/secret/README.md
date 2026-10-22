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

## Commands

```
cx secret ls                                   # alias, kind, repository, hosts, used by - never a value
cx secret show <alias>                         # the references of one identity
cx secret check [<alias>] [--fix]              # the files exist, the mode, passphrase as declared, the variables set;
                                               # --fix makes a key of the artifact that others can read owner-only
cx secret which <cat>::<artifact>/<file>       # the secret holding a copy of that file, and its path (since 2026-10-22)
cx secret import [<alias>] [--force]           # copy the files in from files.from (files.names), tighten the private
                                               # key, mark files.status imported (done 2026-10-15 for the four)
cx secret generate <alias> [--comment=..]      # a new ed25519 key pair without a passphrase at ssh.key (--force: over it)
cx secret use <alias> --repo=<path>            # the identity into a clone's .git/config (name, email, core.sshCommand,
cx secret use <alias> --git_global             # gpg.format, user.signingkey, commit.gpgsign, allowed signers), or the user's
cx secret render <alias> --out=<file>          # a standalone git config include file (+ the ssh config stanza)
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
