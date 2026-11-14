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
  says so and stops: close Firefox and run it again. Otherwise the distribution's package with apt
  (`apt-get update`, then `apt-get install --only-upgrade firefox`). Other package managers are not driven yet.
- **Windows:** winget, `Mozilla.Firefox` (`winget upgrade`, or `install` where it is missing). Firefox also updates
  itself there.
- **macOS:** Homebrew's cask `firefox`.

## Versions

- **Installed:** `firefox --version` on Linux and macOS (snap's mount warnings on stderr are not read); on Windows
  `application.ini` beside `firefox.exe`, since `firefox.exe --version` prints nothing to a console.
- **Newest:** for a snap, the version its tracked channel offers (`snap info firefox`) - what a refresh brings; else
  Mozilla's latest release (`product-details.mozilla.org/1.0/firefox_versions.json`).
