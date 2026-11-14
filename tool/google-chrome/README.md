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
- **Windows:** winget, `Google.Chrome`. Chrome also updates itself there.
- **macOS:** Homebrew's cask `google-chrome`.

## Versions

- **Installed:** `google-chrome --version` on Linux and macOS; on Windows the version folder beside `chrome.exe`
  (`Application\157.0.8103.78\`), since `chrome.exe --version` prints nothing to a console.
- **Newest:** Google's version history of the stable channel for the platform
  (`versionhistory.googleapis.com/v1/chrome/platforms/<linux|win64|mac|...>/channels/stable/versions`). The apt
  repository may offer it a few hours later than the history lists it.
