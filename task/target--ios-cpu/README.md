# iOS CPU target

An iPhone or iPad on a Mac's USB as a compute target: programs are compiled on the Mac with Xcode's clang and the
iOS SDK (`tool/apple.xcode`, `tool/apple.xcode.clang`, `-cpp`), put into an app bundle, signed, installed and
launched with `devicectl`, their console attached; the files they write come back from the app's Documents folder.

```bash
cx task run target--ios-cpu -q                                  # the only paired device
cx task run target--ios-cpu --device="iPhone 17"                # by name, UDID, serial number or model
cx program run test-nmm-c-cpu ios-cpu -q
cx program run test-nmm-c-cpu ios-cpu --use.target--ios-cpu.device=<UDID> -q
```

## What the Mac needs, once

- Xcode (the App Store), opened once: the licence, the iOS platform; `xcode-select -s /Applications/Xcode.app/Contents/Developer`.
- An Apple Account in Xcode > Settings > Accounts, its team selected, Manage Certificates > + > Apple Development
  (a free personal team runs apps on one's own devices; its profiles last seven days and are made again).
- The device: connected over USB, unlocked, "Trust This Computer" answered, Developer Mode on
  (Settings > Privacy & Security; a restart).
- After the first install, the device must trust the developer once: Settings > General > VPN & Device Management.

## How a program runs

- `init` lists the paired devices (`devicectl list devices --json-output`) and selects one; `run` records the device
  and finds the signing identity (`security find-identity`), its team (the certificate's OU) and a development
  profile of that team for the bundle id (`org.ctuning.cmeta.runner`, `--bundle_id`) that provisions the device. Without
  one, it builds the minimal runner project in its cache entry with `xcodebuild -allowProvisioningUpdates
  -allowProvisioningDeviceRegistration`: Xcode registers the device in the team and makes the profile. The
  entitlements of the profile go to `entitlements.plist` in the cache entry.
- Every program runs under that one bundle id (a free team allows ten app ids a week): `setup-run` makes
  `<program>.app` around the executable, signs it (`codesign`, through the user's GUI session with `launchctl asuser`
  when the session's login keychain is locked - an ssh session) and installs it; the run is `devicectl device process
  launch --console --terminate-existing <bundle id> <arguments>`.
- The compiled program's `main` is the target's launcher (`src/cmeta_ios_main.c`, the program's own main is renamed
  `cmeta_program_main` by the compile flags): it enters the app's Documents folder, removes last run's output files,
  calls the program and writes its exit code into `tmp-cmeta-ios-exit.txt`, which `setup-run` copies back and checks.
- A cached target whose profile expired or disappeared is made again (`filter_cache_artifacts`).

Not yet on iOS: OpenMP (Apple's clang has no runtime for it; programs that ask for it are built without, `_OPENMP`
undefined), OpenSSL (`test-nmm-c-cpu` skips its OpenSSL test with `-DCMETA_SKIP_OPENSSL`), the GPU (Metal) and the
Neural Engine as targets.
