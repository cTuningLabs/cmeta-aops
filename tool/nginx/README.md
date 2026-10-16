# tool/nginx

nginx, the web server and reverse proxy.

```
cx tool setup nginx                      # detect it (its path and version: nginx -v)
cx tool setup nginx --install -q         # install it: the distribution's package (sudo), brew on macOS, the zip on Windows
cx tool setup nginx --versions           # nginx's releases; the stable line (1.30) is the default
```

On Linux the distribution's `nginx` package; after it the service is enabled and started where systemd runs (the
RPM packages do not start it); in a container nothing is started. On macOS Homebrew's.

On Windows the official zip of nginx.org (`nginx-<version>.zip`) is unpacked whole into cMeta's cache - nginx.exe
needs `conf/`, `html/`, `logs/` and `temp/` next to it. Start it in its folder (`start nginx`), stop it with
`nginx -s stop`. nginx.org signs its files with PGP only: the zip comes over HTTPS.

Apache and nginx both listen on port 80 by default: on one machine, one of them must move first.

Removal: the package manager (`sudo apt-get remove nginx`), `brew uninstall nginx`; on Windows the cache entry
(`cx cache rm "*setup--nginx*"`).
