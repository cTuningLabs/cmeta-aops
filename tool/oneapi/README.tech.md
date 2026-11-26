# oneapi: Intel oneAPI (the DPC++/C++ compiler with SYCL, and its libraries)

The tool is the environment of an installed oneAPI release: its script `oneapi-vars`, which the
Intel compilers `icx` and `icpx` and the `xpu` target stand on.

```
cx tool status oneapi                                              what is installed, and its version
cx tool setup oneapi --install --with.accept_eula=yes              the default line of oneAPI
cx tool setup oneapi --version=2026.0 --install --with.accept_eula=yes
cx program run build-pytorch --compute=xpu --use.oneapi.with.accept_eula=yes
```

## What is installed

Intel Deep Learning Essentials: the oneAPI package Intel publishes for building PyTorch for its
GPUs - the DPC++/C++ compiler with SYCL, oneMKL, oneDNN, oneCCL, oneTBB, oneDPL, the profiling
interface PTI and the pieces around them. A SYCL extension is no package of its own: it is a part
of the compiler and its runtime, so the question "which extensions" is "which release".

The releases are a table in `_desc.yaml` (`releases:`): per release and system Intel's file, its
address, size and sha256. Intel keeps each file at an address that cannot be derived, so a new
release is added to the table by hand, from Intel's download page or its pages "PyTorch
Prerequisites for Intel GPUs".

| System | How | Where |
|---|---|---|
| Linux (x86_64) | Intel's installer, silently, without root | the tool's cache entry (`content/`) |
| Windows (x86_64) | Intel's installer, silently; it asks for administrator rights | where Intel installs: its default folder, or beside the oneAPI the machine has; `--with.install_dir=<folder>` names it |
| macOS, ARM | not published by Intel | - |

## The version, and what a request names

The version of the tool is the compiler's (`icx --version`), as it always was. Intel numbers the
compiler apart from the package: the package 2026.1.3 holds the compiler 2026.1.1. A request
therefore names a line of oneAPI - `--version=2026.1`, or a range such as `>=2026.0` - or a
compiler version the table knows (`compiler:`, written where a release was installed and asked).
The newest release of the table that answers the request is installed. The package's own number
(2026.1.3) is not a request: the detection after the install would not find it.

## The licence

oneAPI comes under Intel's End User License Agreement for Developer Tools
(https://www.intel.com/content/www/us/en/developer/articles/license/end-user-license-agreement.html).
It is the user's to read and accept: without `--with.accept_eula=yes` (in a program:
`--use.oneapi.with.accept_eula=yes`) the install stops before anything is downloaded and says so.
With it, the tool passes `--eula accept` to Intel's installer, and declines Intel's software
improvement program.

## Linux: what an install leaves, and how it is removed

The install runs as the user, into the cache entry, with an installation instance of its own
(`cmeta-<12 hex digits of the folder's name>`). Intel's installer keeps one install folder per
instance; with an instance per cache entry, several releases stand side by side and none of them
touches an oneAPI the user installed (the instance `default`: `~/intel/oneapi` or
`/opt/intel/oneapi`).

- In the cache entry: `content/` (the release; `content/<line>/oneapi-vars.sh` is the tool's
  path), `content/cmeta-oneapi.json` (the release, its file and sha256, the instance, the commands
  that remove it) and `log/` (Intel's logs). The downloaded file, its unpacked copy and the
  installer's copies of the packages are removed after the install.
- Outside it, in the user's home: Intel's installer itself (`~/intel/oneapi/installer`) and its
  records of what is installed (`~/intel/packagemanager`, `~/intel/installercache`).

To remove a release, run the commands under `remove` of `content/cmeta-oneapi.json` (Intel's
installer, `--action remove` for the instance), then delete the cache entry. Deleting the entry
alone leaves the instance in Intel's records.

## Windows

The tool downloads Intel's installer into its cache entry and hands the command to the setup task
(`requires_sudo: windows`): Windows asks with its administrator prompt. A quiet run (`-q`) from a
process that is not elevated does not start it - it prints the command to run in an elevated
terminal. Releases stand side by side in Intel's folder (`<line>\oneapi-vars.bat`), and the tool
detects each. The downloaded file is deleted when the installer ends well. Removal is Windows'
own: "Installed apps", or Intel's installer.

Without a folder, Intel's installer chooses: the folder of the oneAPI the machine has (its
installation instance), else `C:\Program Files (x86)\Intel\oneAPI`. `--with.install_dir=<folder>`
names it (`--install-dir` of Intel's installer):

    cx tool setup oneapi --version=2026.1 --install --with.accept_eula=yes --with.install_dir="D:\Program Files (x86)\Intel\oneAPI"

`"C:\Program Files (x86)\Intel\oneAPI\Installer\installer.exe" --list-products` lists what Intel
installed (its id and version), and `--list-instances` the instances; the tool searches the
oneAPI folders of drives C: and D:.

## Computing on an Intel GPU

The compiler builds SYCL programs on any x86_64 machine. To run them on an Intel GPU, the machine
also needs the GPU's compute runtime (Level Zero and OpenCL): on Windows the Intel graphics driver
brings it; on Linux `cx tool setup intel-gpu-runtime` sets it up without root. `sycl-ls` (in the
environment of `oneapi-vars`) lists the devices SYCL sees.
