# tool/apache2

The Apache HTTP Server: `apache2` on Debian and Ubuntu, `httpd` on the RPM distributions, Homebrew and Windows.

```
cx tool setup apache2                    # detect it (its path and version)
cx tool setup apache2 --install -q       # install it: the distribution's package (sudo), brew on macOS, winget on Windows
cx tool setup apache2 --versions         # Apache's 2.4 releases (a package manager installs its distribution's own)
```

On Linux the package is `apache2` (Debian, Ubuntu, SUSE, Alpine), `httpd` on Rocky, Alma, CentOS, Fedora, Amazon
Linux and Azure Linux (found through the distribution's `ID_LIKE`), `apache` on Arch. After the install the service
is enabled and started where systemd runs (`systemctl enable --now`; the Debian package starts it itself, the RPM
ones do not); without a passwordless sudo the command is printed. In a container nothing is started.

On Windows winget installs Apache Lounge's build (`ApacheLounge.httpd`; it needs the Visual C++ runtime).

A certificate for it: `cx task run setup-ssl-certificate` (Let's Encrypt through tool/certbot). Apache and nginx both
listen on port 80 by default: on one machine, one of them must move first.

Removal: the package manager (`sudo apt-get remove apache2`, `sudo dnf remove httpd`), `brew uninstall httpd`,
`winget uninstall ApacheLounge.httpd`.
