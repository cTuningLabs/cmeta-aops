# setup-ssl-certificate

Use Certbot with Let's Encrypt to issue/install or renew certificates on an
Apache host. Requires Apache; `tool::certbot` detects an existing Certbot first,
or prepares a pinned Certbot/Apache plugin in an isolated Python environment.
No private keys or credential contents are returned or copied into cMeta.

```sh
cxt setup-ssl-certificate labs.example.org --plan
cxt setup-ssl-certificate labs.example.org --dry-run -q
cxt setup-ssl-certificate labs.example.org --test-renewal -q
cxt setup-ssl-certificate example.org --action=renew -q
cxt setup-ssl-certificate '*' --action=list
cxt setup-ssl-certificate '*' --action=renew --dry-run -q
```

The default `action=ensure` issues missing certificates, installs them into
Apache and adds HTTP-to-HTTPS redirects. Existing certificates keep all SANs
and are renewed only when due. `--force-renewal` deliberately bypasses that due
check; it can consume issuance limits. `action=renew` uses saved lineage settings
and requires existing certificates. Shared multi-domain lineages run once.
`--cert-name` disambiguates a single hostname covered by multiple certificates.
`--email` also accepts the Let's Encrypt account terms for a new account;
existing accounts can be reused without supplying an address again.

`--plan` inventories enabled Apache vhosts and Certbot certificates, then prints
commands without issuance or installation. `--dry-run` performs staging validation
using `certonly`/`renew`, without installing an untrusted staging certificate.
`--test-renewal` tests the saved renewal configuration after an actual operation.
Normal operations ask to proceed; `-q` skips the task question and uses `sudo -n`.
Operator-triggered renewal disables Certbot 4.x/newer random sleep; older detected
clients retain their delay policy. Scheduled renewal retains its normal policy.
Additional options: `--apache-ctl`, `--sudo=no`, `--redirect=no`, `--timeout=600`.

## Domain selection and wildcards

| Input | Meaning |
|---|---|
| `ctuning.ai` | Exact hostname; preserves SANs if an existing lineage covers it. |
| `labs.ctuning.ai` | Exact subdomain, with its own lineage when not already covered. |
| `'*'` | All concrete names in active Apache `ServerName`/`ServerAlias` entries. |
| `'*.ctuning.ai'` | A real wildcard certificate, requiring DNS-01 validation. |

`*` does not enumerate DNS or include arbitrary unconfigured subdomains. Wildcard
Apache aliases are reported and skipped in all-domain selection. A wildcard cert
does not cover the apex domain; request/manage that separately when needed.

For a new wildcard, install a Certbot DNS plugin in the SAME Certbot environment
and provide its private credentials file on the web host:

```sh
cxt setup-ssl-certificate '*.example.org' --dns-plugin=dns-cloudflare \
  --dns-credentials=/etc/letsencrypt/cloudflare.ini --email=admin@example.org -q
```

This example assumes authoritative DNS is at Cloudflare. It does not work for
domains still using Namecheap DNS. No DNS provider/account changes are made by
this task. Manual TXT challenges are not offered as automatic renewal. Existing
wildcards can use `--action=renew` with their saved DNS authenticator.

## Automatic renewal and execution on another machine

Certbot stores lineages under `/etc/letsencrypt/live/<cert-name>/` and saves
authenticator/installer settings under `/etc/letsencrypt/renewal/`. Apache uses
`fullchain.pem` and `privkey.pem`; successful renewal updates those links and
the saved Apache installer reloads Apache. Keep port 80 accessible for HTTP-01.
DNS A/AAAA records must route to the host serving validation.

The host must schedule `certbot renew`, usually through the package's enabled
`certbot.timer`. A cMeta cache installation alone creates no timer; use a stable
managed installation for scheduled production renewal, and make sure the timer
runs the same installation/plugins. Cache cleanup must not remove the scheduled
binary. Verify `systemctl is-enabled certbot.timer` and `systemctl is-active
certbot.timer`, then use the task's renewal dry-run. macOS scheduling is separate.

```sh
cx host run my-web-host 'cxt setup-ssl-certificate labs.example.org --plan -q'
cx host run my-web-host 'cxt setup-ssl-certificate labs.example.org --test-renewal -q'
```

The task and tool must be available in that host's orchestrator. They have no
fixed repository requirement. `--on` can also be used where the task engine
supports remote execution. A native Windows run gives a clear host-selection error.

References: [Certbot usage and renewal](https://eff-certbot.readthedocs.io/en/stable/using.html),
[Apache name-based vhosts](https://httpd.apache.org/docs/2.4/vhosts/name-based.html).
