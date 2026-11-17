# tool/google-chrome

Google Chrome, detected where the system keeps it and upgraded through the system's own channel. A browser updates
through its channel - its profile, its updates and the desktop's links follow that installation - so this tool never
keeps a copy in the cMeta cache.

```bash
cx tool setup google-chrome --status   # the installed version, the newest one, outdated or not
cx tool upgrade google-chrome          # the newest version through the system's channel
cx tool install google-chrome          # the same where Chrome is missing
```

## The channel

- **Linux (x86_64):** Google's package. An installed Chrome is upgraded from Google's apt repository, which its
  package added (`apt-get update`, then `apt-get install --only-upgrade google-chrome-stable`); a missing one is
  installed from `google-chrome-stable_current_amd64.deb`, downloaded into the cache entry, which adds the repository.
  An rpm system uses dnf and Google's rpm. A running Chrome uses the new version after its next start. Google
  publishes no Chrome for Linux on arm64.
- **Windows:** winget, `Google.Chrome` (the machine-wide package): `winget upgrade`, or `install` where Chrome is
  missing. A Chrome in Program Files that winget does not link to its package (installed by Google's own installer:
  `winget upgrade` answers "No installed package found", 0x8A150014) gets that package installed over it; a Chrome of
  the user's own folder (`LOCALAPPDATA`) is not replaced - it updates itself. Chrome also updates itself there.
- **macOS:** Homebrew's cask `google-chrome`: `brew upgrade --cask` when the cask installed it; an app from Google's disk
  image is replaced by the cask (`brew install --cask --force`; the profile stays in `~/Library/Application
  Support/Google/Chrome`); a missing one is installed.

## Versions

- **Installed:** `google-chrome --version` on Linux; on Windows the version folder beside `chrome.exe`
  (`Application\157.0.8103.78\`), since `chrome.exe --version` prints nothing to a console; on macOS
  `CFBundleShortVersionString` of `Google Chrome.app/Contents/Info.plist` - no program is started there: a quarantined
  app (a Homebrew cask's) waits for the user to allow its first start.
- **Newest:** the one the system's channel gives, so that an upgrade brings exactly it (setup detects the tool again at
  that version after an upgrade): apt's candidate from Google's repository (a note when apt's lists are older than a
  day), dnf's, winget's package (`winget show`), the cask (`brew info`; the install then runs without Homebrew's own
  update). Google's version history of the stable channel for the platform
  (`versionhistory.googleapis.com/v1/chrome/platforms/<linux|win64|mac|...>/channels/stable/versions`) for a missing
  Chrome on Linux - Google's current package is installed then - and where no channel answers, and as a note when
  Google is ahead. Before 2026-11-17 the history was the newest version everywhere: on 2026-11-17 it listed
  158.0.8127.37 for Windows and macOS while winget and the cask offered 157.0.8103.79, so an upgrade there ended "not
  found after the upgrade".
- **When the channel moves:** apt's lists are refreshed before an upgrade; when they, dnf's metadata or the downloaded
  current package then offer another version than the one asked for (the one `--status` found), nothing is installed
  and the error says to run the upgrade again.
