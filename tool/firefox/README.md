# tool/firefox

Mozilla Firefox, detected where the system keeps it and upgraded through the system's own channel. A browser updates
through its channel - its profile, its updates and the desktop's links follow that installation - so this tool never
keeps a copy in the cMeta cache.

```bash
cx tool setup firefox --status      # the installed version, the newest one, outdated or not
cx tool upgrade firefox             # the newest version through the system's channel
cx tool install firefox             # the same where Firefox is missing
```

## The channel

- **Linux:** the snap when Firefox is one (Ubuntu's `firefox` package of version `1snap1` only installs the snap):
  `sudo snap refresh firefox`. A running Firefox is not refreshed - snap waits until it is closed - so the upgrade
  says so and stops: close Firefox and run it again. A missing Firefox is installed as the snap where snap works.
  Otherwise the distribution's package: apt (`apt-get update`, then `apt-get install [--only-upgrade] firefox`,
  non-interactive) or dnf (`dnf install|upgrade -y firefox`). Other package managers are not driven.
- **Windows:** winget, the package of the installation's channel and language (`Mozilla.Firefox`,
  `Mozilla.Firefox.de`, `Mozilla.Firefox.ESR` ..., from the name of its Uninstall entry): `winget upgrade`, or
  `install` where Firefox is missing. A Firefox installed by Mozilla's own installer is not linked to winget's package
  (`winget upgrade` answers "No installed package found", 0x8A150014): that package is then installed over it, in its
  folder. Firefox also updates itself there.
- **macOS:** Homebrew's cask (`firefox`, or `firefox@esr` when that one installed it): `brew upgrade --cask` for the
  cask that installed it; an app from Mozilla's disk image is replaced by the cask (`brew install --cask --force`; the
  profile stays in `~/Library/Application Support/Firefox`); a missing one is installed.

## Versions

- **Installed:** `application.ini` beside `firefox.exe` on Windows (`firefox.exe --version` prints nothing to a
  console) and in `Firefox.app/Contents/Resources` on macOS - no program is started there: a quarantined app (a
  Homebrew cask's) waits for the user to allow its first start; `firefox --version` on Linux (snap's mount warnings on
  stderr are not read).
- **Newest:** the one the system's channel gives, so that an upgrade brings exactly it (setup detects the tool again at
  that version after an upgrade): the snap's tracked channel (`snap info firefox`; `latest/stable` for a missing one),
  apt's candidate (a note when its package lists are older than a day), dnf's (as root when sudo needs no password),
  winget's package (`winget show`), the cask (`brew info`; the install then runs without Homebrew's own update).
  Mozilla's latest release (`product-details.mozilla.org/1.0/firefox_versions.json`) where none answers, and as a note
  when Mozilla is ahead of the system's channel. Before 2026-11-17 Mozilla's version was the newest one on Windows,
  macOS and with apt, so an upgrade ended "not found after the upgrade" whenever winget, the cask or the distribution
  was behind Mozilla.
- **When the lists move:** apt's lists are refreshed before an install; when they, or dnf's metadata, then offer another
  version than the one asked for (the one `--status` found), nothing is installed and the error says to run the upgrade
  again - it then takes the new version.
