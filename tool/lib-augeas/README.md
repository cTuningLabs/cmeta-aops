# lib-augeas: the development files of Augeas

`cx tool setup lib-augeas` finds `augeas.h` or installs the system's development package of Augeas (with libxml2's
and pkg-config), so that a Python package built against Augeas compiles: `python-augeas`, which certbot's Apache
plugin needs and which publishes no wheels. `tool/certbot` sets it up first on Linux and macOS.

| System | Installed |
|---|---|
| Debian, Ubuntu | `libaugeas-dev pkg-config` (with sudo) |
| Fedora, RHEL, Rocky, Amazon Linux | `augeas-devel pkgconf-pkg-config` |
| openSUSE | `augeas-devel pkg-config` |
| Alpine | `augeas-dev pkgconf` |
| Arch | `augeas pkgconf` |
| macOS | `brew install augeas pkgconf` |

A quiet run (`-q`) uses `sudo -n`, so it fails at once instead of waiting for a password where sudo needs one.
