# Android Gradle application program template

An Android APK is a `program` whose compile step builds with Gradle and whose
run step installs/launches through ADB. This template uses the existing
`compile-and-run-program` driver, source-change checks, build entries, build
stamps and provenance. The driver and existing native program templates are
unchanged.

The `android-app` target describes an Android application runtime without
probing a device during compilation. ADB is set up only for deployment/launch.
Native Android executables continue to use the existing `android-cpu` target.

An application program supplies its own `_cmeta.json`, `_desc.yaml` and small
`api_v1.py`:

```json
{
  "artifact": "<new 16-hex UID>",
  "authors": "Your name",
  "category": "program,22788f3c30d04e6d",
  "constraints": {"supported_compute": ["android-app"]},
  "uses_categories": {"task": "task,c36be4b9314a45e0"},
  "uses_artifacts": {"task::android-gradle-app": "android-gradle-app,175185dd757f45e1"}
}
```

```yaml
inherits:
  - template-android-gradle-app,7c64f1611d5c4353
local_vars:
  android_project_cref: project-category::my-app,UID/src
  android_module: app
  android_package: com.example.app
  android_activity: .MainActivity
```

```python
from program_22788f3c30d04e6d.api.common_android_gradle import InitAndroidGradleProgram

class CProgram(InitAndroidGradleProgram):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)
```

Index that program in its destination repo, then:

```bat
cx program compile my-android-app -q
cx program run my-android-app -q
cx program run my-android-app --cmd=deploy --serial=DEVICE -q
cx program run my-android-app --cmd=launch --serial=DEVICE -q
cx program provenance my-android-app
cx program clean my-android-app
```

The default `run` builds when needed, installs and launches. `--cmd=deploy`
builds when needed and only installs. `--cmd=launch` skips the compile phase and
only opens the already installed activity. `--skip_compile --cmd=deploy` installs
the existing program build without rebuilding and fails if its receipt is missing.
The inherited default compute is `android-app`; it can also be supplied explicitly.

Build inputs resolve from the project's cRef. The hook declares all inputs,
including Gradle `.kts`/properties, Android XML and icons, so changes/additions/
deletions participate in the driver's source digest comparison. Generated
`build`, hidden `.gradle`/IDE files and temporary directories are excluded.
Signing files contribute hashes only; their contents never enter JSON records.

APK output, `build.json`, Gradle project state, repro contexts, build stamp and
`provenance.json` all reside under the normal program cache's `tmp` directory
(or its `--target_tmp`/`--target_path` override). Cleaning that build workspace
removes its APK; the next compile recreates it. The standalone lifecycle task's
separate cache remains available to callers using it directly.

Use compile parameters for choices that should coexist as separate builds:

```bat
cx program compile my-android-app --compile.variant=release -q
cx program run my-android-app --compile.variant=release --cmd=deploy -q
cx program compile my-android-app --compile.project_dir="D:\source-snapshot" -q
cx program compile my-android-app --compile.sdk_root="D:\Android\Sdk" -q
cx program compile my-android-app "--compile.sdk_packages=platforms;android-35,build-tools;35.0.0" -q
cx program compile my-android-app --recompile -q
```

Normal `--use` tool customizations work. Device selection and install/hash guards
come from `task::android-gradle-app`; app data is retained on ordinary updates.
The template currently supports one application module and a single debug or
release APK. APK payload/library inspection and native profiling are not provided:
the current provenance inspector understands ELF/PE/Mach-O and records that an
APK is outside that inspection, alongside the build inputs/tools and APK receipt.
