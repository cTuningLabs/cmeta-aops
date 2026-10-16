# certbot

Let's Encrypt's certificate client, detected through `certbot --version`.
Existing installations are reused. The fresh-install default is **4.0.0**,
the system version verified on the deployment host; callers can select another
version. Missing versions use `common_pyvenv` with Python 3.12 and the matching
`certbot-apache` version. System Python/packages are unchanged.

```sh
cx tool setup certbot
cx tool run certbot -- --version
cx tool setup certbot --versions
cx tool setup certbot --version=latest --new
cx tool setup certbot --status
```

Apache and its system libraries, including libaugeas on Linux, must already be
installed. DNS plugins are optional and must be installed into the same Certbot
environment. Windows is unsupported; use a Linux/macOS web host. Installation
of the cached tool does not set up a renewal scheduler. For production scheduled
renewal, use a stable managed installation and verify its enabled timer/plugins;
do not schedule a binary that routine cache cleanup will remove.

See [setup-ssl-certificate](../../task/setup-ssl-certificate/README.md).
