# tool/thunderbird

Mozilla Thunderbird, detected where the system keeps it and upgraded through the system's own channel, in the update
channel it follows - the monthly release or the ESR (extended support release). Thunderbird's profile, its own updates
and the desktop's links follow the system's installation, so this tool never keeps a copy in the cMeta cache.

```bash
cx tool setup thunderbird --status                  # the installed version, the newest one of its channel, outdated or not
cx tool upgrade thunderbird                         # the newest version of its channel through the system's channel
cx tool install thunderbird                         # where Thunderbird is missing: the monthly release
cx tool install thunderbird --with.channel=esr      # ... or the ESR
cx tool setup thunderbird --status --tool_path=...  # that copy: its channel and version
```

## The update channel: release or ESR

Mozilla publishes Thunderbird in two channels: the monthly release (160.0 on 2026-11-17) and the ESR (153.7.0esr). An
installation follows one of them and the tool keeps it there: its newest version is the newest of that channel, and an
upgrade never switches it (a profile used by a newer Thunderbird is not opened by an older one) - to change the
channel, uninstall Thunderbird first. The channel is read from the installation:

- **Windows:** `defaults/pref/channel-prefs.js` beside `thunderbird.exe` (`pref("app.update.channel", "esr")`),
  `update-settings.ini`, and the name of the Uninstall entry (`Mozilla Thunderbird ESR (x64 en-US)`), which also gives
  the language.
- **macOS:** the cask that installed it (`thunderbird` or `thunderbird@esr`), else the `esr` of `--version`
  (`Mozilla Thunderbird 153.7.0esr`): Mozilla's app keeps its channel in `Contents/Frameworks/ChannelPrefs.framework`,
  has no `channel-prefs.js`, and its `application.ini` says `153.7.0`.
- **Linux:** the snap's tracked channel (`esr/stable` for the ESR; since July 2026 the snap's `latest/stable` is the
  monthly release), the distribution's package (Debian's is the ESR), else `--version`.

A new installation takes the release, or the channel `--with.channel=esr|release` asks for.

## The channel of the system

- **Linux:** the snap when Thunderbird is one: `sudo snap refresh thunderbird`, refused while Thunderbird runs (close
  it and run the upgrade again); a missing one is installed as the snap where snap works (`--channel=esr/stable` for
  the ESR). Otherwise the distribution's package: apt (`apt-get update`, then `apt-get install [--only-upgrade]
  thunderbird`, non-interactive) or dnf (`dnf install|upgrade -y thunderbird`) - the distribution's Thunderbird,
  whichever channel it follows (Debian 12: the ESR, Fedora 44: the release). A tarball from Mozilla updates itself and
  is not driven.
- **Windows:** winget, the package of the channel and the language: `Mozilla.Thunderbird`, `Mozilla.Thunderbird.ESR`,
  `Mozilla.Thunderbird.de`, `Mozilla.Thunderbird.ESR.fr` ... (`winget upgrade`; `install` where it is missing). A
  Thunderbird installed by Mozilla's own installer is not linked to winget's package (`winget upgrade` answers "No
  installed package found", 0x8A150014): that package is then installed over it, in its folder. Refused while
  Thunderbird runs.
- **macOS:** Homebrew: `brew upgrade --cask <cask>` for the cask that installed it; an app from Mozilla's disk image is
  replaced by the cask of its channel (`brew install --cask --force`; the profile stays in `~/Library/Thunderbird`); a
  missing one is installed. Refused while Thunderbird runs.

## Versions

- **Installed:** `application.ini` beside `thunderbird.exe` on Windows (the exe prints nothing to a console);
  `--version` on Linux and macOS (the snap's mount warnings on stderr are not read). The ESR's `esr` is not kept for
  comparing versions.
- **Newest:** the one the system's channel gives, so that an upgrade brings exactly it (setup detects the tool again at
  that version after an upgrade): the snap's tracked channel (`snap info thunderbird`), apt's candidate (`apt-cache
  policy`; a note when its package lists are older than a day), dnf's (`dnf info`, as root when sudo needs no password:
  root installs it, and a user's own metadata can come from another mirror), winget's package (`winget show`), the cask
  (`brew info --json=v2 --cask`; the install then runs without Homebrew's own update, so it brings that version).
  Mozilla's newest of the channel (`product-details.mozilla.org/1.0/thunderbird_versions.json`) where none answers, and
  as a note when Mozilla is ahead of the system's channel (on 2026-11-17 Fedora 44 offered 157.0, a Windows machine's
  winget 159.0, Mozilla 160.0).
- **When the lists move:** apt's lists are refreshed before an install; when they, or dnf's metadata, then offer another
  version than the one asked for (the one `--status` found), nothing is installed and the error says to run the upgrade
  again - it then takes the new version.

## Tested (2026-11-17, test session 20261117/0801.tool)

| Machine | Thunderbird | What ran |
|---|---|---|
| Windows 11 laptop | 153.7.0 ESR, installed by Mozilla's installer (winget does not link it) | `--status`: up to date (winget `Mozilla.Thunderbird.ESR`); `upgrade`: nothing to do; `--with.channel` kept out |
| Windows 11 (NucBox) | none | `--status`: winget `Mozilla.Thunderbird` 159.0, Mozilla 160.0 as a note; an install with winget (159.0, found again at that version), removed again |
| macOS (Mac mini) | none; Mozilla's ESR disk image mounted read-only | `--status`: cask `thunderbird` 160.0; `--tool_path=<the mounted app>`: ESR (from `--version`), cask `thunderbird@esr` 153.7.0, up to date; an install of the cask `thunderbird`, removed again - its check then waited on the quarantined app's `--version`, so the version now comes from `application.ini` (not run again since) |
| Ubuntu 26.04 (P14s Gen 4), WSL Ubuntu 26.04 | none | `--status`: the snap's `latest/stable` 160.0; an install of the snap (160.0, found again at that version), removed again with the snaps it brought |
| Debian 12 container | installed by the tool | install (apt); 140.12.0 -> 153.7.0 by `upgrade`; `--upgrade` of a missing one; no-op upgrades |
| Fedora 44 container | installed by the tool | install (dnf) 158.0; `--upgrade` of a missing one; no-op upgrades |

Not run for real: an upgrade of an outdated Thunderbird with winget or Homebrew, and the fallback for a Thunderbird
that winget does not link (its exit code 0x8A150014 was seen on the laptop; the install over it was not run there).
