# manage-cloudflare-tunnel

The Cloudflare Tunnel service of this machine. A tunnel exposes local web servers under public hostnames with
no inbound port opened: `cloudflared` keeps an outgoing connection to Cloudflare's edge, and Cloudflare sends each
request for a hostname down it to a local port.

The task handles a **remotely managed** tunnel: you create the tunnel and its routes (hostname -> local service)
in the Cloudflare dashboard, and the machine holds only the tunnel's token. `cloudflared` runs as a system
service, with the token in a root-only file passed by `--token-file`, so the token never shows on a command line,
in a unit file or in `ps`:

| OS | Service | Token |
|---|---|---|
| Linux | systemd unit `/etc/systemd/system/cloudflared.service` | `/etc/cloudflared/token` (0600, root) |
| macOS | launchd daemon `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` (logs in `/Library/Logs/com.cloudflare.cloudflared.*.log`) | `/etc/cloudflared/token` |
| Windows | status only for now | - |

The binary comes from `tool::cloudflared`: an installed `cloudflared` is used where it is (the package of
pkg.cloudflare.com, brew), else the pinned release is downloaded (SHA-256 checked) and copied to
`/usr/local/bin/cloudflared`, because a root service must not run a binary from the cMeta cache.

```sh
cxt manage-cloudflare-tunnel                       # status (no root needed)
cxt manage-cloudflare-tunnel --strict -q           # the same, an error when something is not right
cxt manage-cloudflare-tunnel --public-             # status without asking the public hostnames

cxt manage-cloudflare-tunnel install --token_file=<file> --plan   # the steps, nothing changed
cxt manage-cloudflare-tunnel install --token_file=<file> -q
cxt manage-cloudflare-tunnel install                # in a terminal: the token is asked, hidden
cxt manage-cloudflare-tunnel install --token_file=<file> --force  # replace the token/unit of an existing tunnel

cxt manage-cloudflare-tunnel restart
cxt manage-cloudflare-tunnel upgrade [--version=<v>] [--plan]
cxt manage-cloudflare-tunnel uninstall              # the service and the token removed, the binary kept

cx host run <host> "cxt manage-cloudflare-tunnel -q"    # a fleet host
```

## The status

It reads the connector's own metrics server (`127.0.0.1:20241`-`20245`; `--metrics=<host:port>` to name it):
`/ready` gives the connections to the edge and `/config` the routes the dashboard set. So the status shows the
routes without the dashboard and without root. For each route the origin is tried (a TCP connect), and the
public hostname is asked over HTTPS without following redirects. The answer can be a status code, `401/403: a
login is asked` (the origin's login), `Cloudflare Access login` (a redirect to `cloudflareaccess.com`), or
`502/503/530: Cloudflare cannot reach the origin`.

```
cloudflared: 2026.9.3 at /usr/bin/cloudflared (apt)
service:     systemd cloudflared.service active, enabled
             /usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token
connector:   ready, 4 connection(s) to the edge, connector 1b2c..., metrics 127.0.0.1:20241
routes (set in the Cloudflare dashboard, configuration version 3):
  cmeta.example.org -> http://127.0.0.1:8228  (origin listening, public: 401: a login is asked)
verdict:     OK
```

## Adding a hostname to a tunnel

You add routes in the dashboard. No change on the machine is needed, because the connector picks up the new
configuration within seconds:

1. Open **Zero Trust -> Networks -> Tunnels -> (the tunnel) -> Edit -> Public hostnames** ("Published
   application routes" in newer dashboards).
2. Add a hostname: a subdomain, a domain (any zone of the same Cloudflare account) and a service, e.g. `HTTP` +
   `127.0.0.1:8188`. Cloudflare creates the DNS record itself: a proxied CNAME to `<tunnel id>.cfargotunnel.com`.
   An existing A/AAAA/CNAME record of the same name blocks this: delete it first.
3. Run `cxt manage-cloudflare-tunnel` on the machine to see the new route and whether its origin listens.

The token is in the dashboard too (the tunnel -> the install command: the long word after `--token`). Keep it in a
file readable by you only, give it with `--token_file`, and delete that file afterwards. A token that leaked is
rotated in the dashboard ("Refresh token"), followed by `install --force` with the new one.

## Upgrade

`upgrade` follows how the service's binary came:

- **The distribution's package:** `apt-get install --only-upgrade cloudflared` (or `dnf upgrade cloudflared`).
- **brew:** `brew upgrade cloudflared`.
- **This task's copy in `/usr/local/bin`:** the release asked for (the tool's pin by default) is set up through
  `tool::cloudflared` and copied over.

The service is then restarted, and the task waits up to `--wait` seconds (30) for the connector. When the
connector is not ready, the error quotes cloudflared's last `ERR` line (from the journal or the macOS log).

## Rules

- **Root:** steps run with `sudo -n` in a quiet or non-terminal run (`sudo -n true` is checked first, before
  anything changes), and with plain `sudo` in a terminal.
- **Confirmation:** without `-q`, the steps are shown and confirmed first.
- **Production:** on a production host, only `status` is a light check. Run `install`, `restart`, `upgrade` and
  `uninstall` with the owner's agreement.
