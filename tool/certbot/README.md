# certbot

Let's Encrypt's certificate client, detected through `certbot --version`.
Existing installations are reused. The fresh-install default is **5.8.0**
(4.0.0, the system version of the deployment host, before 2026-10-17); callers can
select another version. Missing versions use `common_pyvenv` with Python 3.12 and
the matching `certbot-apache` version. System Python/packages are unchanged.

`certbot-apache` needs `python-augeas`, which publishes no wheels: its small C
extension is built at install time. Before that build, cMeta sets up
[`lib-augeas`](../lib-augeas/) (the system's Augeas development files, with sudo;
brew on macOS) and the C compiler of its compiler task, passed to the build as
`CC`. A bare Debian, Fedora or Ubuntu system needs nothing installed by hand.

```sh
cx tool setup certbot
cx tool run certbot -- --version
cx tool setup certbot --versions
cx tool setup certbot --version=latest --new
cx tool setup certbot --status
```

Apache itself must already be installed (`cx tool setup apache2`). DNS plugins are optional and must be installed into the same Certbot
environment. Windows is unsupported; use a Linux/macOS web host. Installation
of the cached tool does not set up a renewal scheduler. For production scheduled
renewal, use a stable managed installation and verify its enabled timer/plugins;
do not schedule a binary that routine cache cleanup will remove.

See [setup-ssl-certificate](../../task/setup-ssl-certificate/README.md).
