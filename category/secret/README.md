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

`cx secret store <alias>` keeps the value of a token secret that you type (paste) at a hidden prompt (a `*` for every
character, Backspace takes one away, Escape starts again - cMeta 0.43+; nothing shown before): it is never
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

## A value that cMeta makes, shown once when asked

`--generate` makes the value instead of asking for it: 256 random bits as text (`secrets.token_urlsafe(32)` of
Python, 43 characters). It is for a key that no service hands out - a client key, the master key of an encryption
tool. `--print_key` shows a generated value once and returns it in the answer; without it the value is never
shown, and a value you typed never is (`--print_key` without `--generate` is refused):

```
cx secret store my-client-key --generate                                  # a new random value, kept owner-only, never shown
cx secret store my-master --password_protected --generate --print_key     # sealed under a password, and shown once
cx secret generate my-client-key --print_key                              # the same for a token secret that names its file
cx secret add my-vault:my-master --yaml --password_protected --generate --print_key
                                                                          # the artifact and its value in one step
```

`--value_env=<NAME>` (store and add) takes the value from that environment variable of the calling process - for a
tool that has it in hand and has checked it (a keystore password it opened the keystore with): it is not asked again,
and only the variable's name is on the command line.

`cx secret add` (and `create`) takes the words of `store` - `--generate`, `--print_key`, `--password_protected`,
`--store` for a value typed at the prompt kept owner-only, `--force` - beside every word of the common `add`
(`--yaml`, `--desc.<key>=`, `--tags=` ...): with none of them it is the common `add`, and a request that needs a
person at a terminal is refused before the artifact is made, and when the value step does not end well (cancelled,
Ctrl-C, two passwords that differ) the artifact it made is removed again - the next add of the name works. A generated value without a password needs no
terminal (a script, a quiet run); a password is always typed by a person.

When to show a value: a key that can be made again (a client key: generate another, give the service its new
SHA-256) never needs it. A key that encrypts what you keep is different - the sealed file and its password are then
the only way back to your data, so a second copy belongs somewhere that survives this disk (a password manager,
paper in a safe place). Use `--print_key` at a terminal of your own, write the value down there and clear the screen:
what a terminal shows stays in its scroll-back, and in the transcript of an AI agent that ran the command.

## The value given to one command

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
cx secret generate <alias> [--comment=..]      # a new ed25519 key pair without a passphrase at ssh.key (--force: over it);
                                               # a token secret: a random value in its token file, owner-only, never
                                               # printed - only its SHA-256 (what another machine keeps to check it) -
                                               # unless --print_key asks to show it once
cx secret use <alias> --repo=<path>            # the identity into a clone's .git/config (name, email, core.sshCommand,
cx secret use <alias> --git_global             # gpg.format, user.signingkey, commit.gpgsign, allowed signers), or the user's
cx secret render <alias> --out=<file>          # a standalone git config include file (+ the ssh config stanza)
cx secret store <alias> [--password_protected] # a token typed at a hidden prompt, kept owner-only or encrypted;
                 [--generate [--print_key]]    # --generate: a random value instead, --print_key: shown once
cx secret add <repo>:<alias> --yaml [--password_protected] [--generate [--print_key]] [--store]
                                               # the artifact and, with one of these words, its value in one step
cx secret run <alias> --env.<NAME>={secret} [--window] -- <command>   # the value in the command's environment alone
cx secret settings <alias>                     # the git settings of a git or ssh identity (paths and names) - what
                                               # cx repo pull --identity=<alias> gives a clone (since 2026-11-14)
cm.access({'category': 'secret', 'command': 'call', 'arg1': <alias>, 'func': f})   # f(value) inside the call, its
                                               # dictionary the result - a Python caller only (cx repo pull hf://...
                                               # --identity=<alias> fetches a private Hub repository so; 2026-11-16)
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
