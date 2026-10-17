# Android Gradle app lifecycle

`task::android-gradle-app,175185dd757f45e1` builds a single-module Android APK
with the source project's Gradle wrapper, installs it through ADB, or launches
an installed activity. The task has no disk result cache: every build runs
Gradle's incremental build, and every deploy/run actually contacts the device.

```bat
cx task run android-gradle-app build --project_cref=project-category::my-app/src -q
cx task run android-gradle-app deploy --project_cref=project-category::my-app/src --serial=DEVICE -q
cx task run android-gradle-app run --package=com.example.app --activity=.MainActivity --serial=DEVICE -q
```

Use `--project_dir=<folder>` for sources outside cMeta or a CI source snapshot.
It overrides `project_cref`. `--module=app` and `--variant=debug` are defaults;
`--variant=release` uses the project's existing release signing configuration.
No release keys are created or changed.

`build` sets up the existing `jdk-temurin` tool (major version 21) and Android
SDK command-line tools (at least 17). No global Gradle installation is needed:
the wrapper selects and downloads the project's own Gradle version. Ordinary
`--use` options customize these dependencies, for example
`--use.openjdk.with.feature=17` (the vendor tool stores its result as `openjdk`).
Pass `--sdk_root=<directory>` to select another SDK root. Optional
`--sdk_packages="platforms;android-35,build-tools;35.0.0"` requests SDK packages
explicitly (commas separate packages; semicolons stay inside Android package IDs).
Android Gradle can also download missing platform and build-tools packages after
their licenses have been accepted.
SDK licenses must be accepted interactively using the SDK's `sdkmanager --licenses`.
The task does not answer license prompts.

Build output lives in `cache::android-gradle-app--<identity digest>` in the
caller's default local repository. Its metadata records the source identity,
module and variant. `outputs/<module>/outputs/apk/<variant>/` contains the APK;
`build.json` records the APK path, SHA-256, package/version and selected JDK/SDK.
An init script redirects all module build directories there, while
`--project-cache-dir` isolates Gradle's project state from copied `.gradle`
folders. User-wide Gradle dependency/wrapper caches retain their usual location.
The source's machine-local `local.properties` SDK pointer is refreshed, keeping
other properties. Sources and release signing settings stay in their source artifact.

`deploy` installs the last successful build for that source/module/variant,
checking its SHA-256 first. `--apk=<file>` instead installs an explicitly selected
APK. It uses `adb install -r -t`, preserving app data when Android permits the
update. A signature mismatch or downgrade fails; the task never uninstalls or
clears data to get around it. `--launch` additionally starts the activity;
otherwise `deploy` only installs. `run` only launches the installed app.

Device selection is `--serial`, then `ANDROID_SERIAL`, then the single connected
device. Multiple devices require an explicit serial; quiet mode never silently
chooses a tablet. Unauthorized/offline devices produce an explanatory error.
Build requires no connected Android device. Deploy/run require no build toolchain.

Deleting the cMeta cache is safe: rebuild before the next deploy. The installed
app and tablet data are independent of the host cache. Build actions take a
workspace lock and remove the old successful receipt before starting Gradle, so
a failed compilation cannot silently deploy the previous binary.

This prototype supports `debug`/`release`, one application module and one APK.
Product flavors, split APK installation, Play signing/upload, emulator setup,
device reset and Google OAuth changes are outside its current scope.
Validated on Windows with a USB Samsung SM-X520; other OS branches reuse the
existing tools but have not been tested in this session.

An application-specific task can be a pure `_desc.yaml` pipeline that supplies
the project cRef, module, package and activity, forwarding action/device options.
This avoids engine changes and avoids treating an Android GUI activity as a
native command-line program to push into `/data/local/tmp`.

For the canonical `cx program compile/run/clean/provenance` interface, use
`program::template-android-gradle-app,7c64f1611d5c4353`. It calls this task with
`workspace_dir` set to the normal program cache. `action=prepare` resolves the
source and lists inputs without setting up JDK/SDK/ADB; the program hook uses
that list to track XML/icons/Gradle files as well as Kotlin/Java sources.

Official references: [Android command-line builds](https://developer.android.com/build/building-cmdline),
[AGP 8.13 compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes),
and [ADB device selection and install](https://developer.android.com/tools/adb).
