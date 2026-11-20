# ai-account-status

A reusable cMeta AOps task for reading **remaining account allowances**, without an AI turn.
UID: `85f3b9fe115a4b62`. It depends on none of the pages that call it, nor on their settings.
Callers use the UID, so the move from a downstream repository requires no caller changes.

```sh
cx task run ai-account-status --harness=claude --json
cx task run ai-account-status --harness=codex --json
cx task run ai-account-status --harness=opencode --model=openai/gpt-5.1-codex --json
cx task run ai-account-status --harness=openclaw --model=anthropic/claude-sonnet-4-5 --json
```

Programmatic use returns structured data:

```python
status = cm.access({
    'category': 'task,c36be4b9314a45e0', 'command': 'run',
    'arg1': 'ai-account-status,85f3b9fe115a4b62',
    'harness': 'claude', 'gateway': 'login', 'model': '',
    'quiet': True, 'con': False, 'cache': False, 'store_global': False,
})
```

`return: 0` means the status check completed, including an unavailable allowance.
`available`, `reason`, `message`, `usage_url`, `checked_at`, `cached` and `stale`
explain the outcome. `account` contains allowlisted display fields only.
`windows` contain `usedPercent` (consumed, **not remaining**), optional
`windowDurationMins`, `resetsAt` (Unix seconds), and `label`.
`credits` is separate from subscription allowance; token counts and dollar costs
of an individual run are not remaining account quota.
`harness_version` (as cMeta's tool detection gives it; empty when the harness is not
found on the machine), `mechanism` (the way the account was read) and
`mechanism_note` say how the answer was obtained - see "Harness versions" below.
These keys were added on 2026-11-20; every key of before is as it was.

Account identity is shown by default, for example `Claude (you@example.com): 5h:
94% remaining` or `Codex (API): API usage…`. The same bracket is used in compact
and full browser displays. `identity` contains the allowlisted `kind` and `label`;
`account.authType` is `login` or `api` when the adapter can establish it. A missing
identity is explicitly shown as unavailable/unknown, never guessed from another
harness or an unrelated saved account.

Disable identity for **every app using this task in the serving cMeta home**:

```sh
cx config set task-ai-account-status --meta.show_identity=false
# Enable it again:
cx config set task-ai-account-status --meta.show_identity=true
```

Run the command with the website's `CMETA_HOME` on the machine serving the site.
This is a host configuration, independent of the browser/device and other cMeta
homes. No website restart is needed for a config change; refresh account status.
An individual call can override the setting with `show_identity=False`. When
disabled, emails/usernames and the identity label are omitted from returned data
and newly written cache entries, not just hidden by CSS. Earlier visible-mode
cache entries expire normally and are not reused by hidden mode.

The setting is also discovered automatically by `/cmeta.configs` (reference)
and `/settings` (editable on the cMeta server). Search for `task-ai-account-status`
or `show_identity`; choose **yes** to show identities or **no** to hide them.
Reset restores the enabled default. The cTuning platform's hosted config views
are read-only; change this machine setting on its cMeta server or through the CLI.
Both native booleans and the config convention yes/no (also true/false, on/off,
1/0) are accepted; explicit `show_identity` task arguments remain booleans.

Claude's email comes from the read-only OAuth profile endpoint using **the same
token** as the quota request. Its potentially stale local `oauthAccount` email is
never used. Codex uses its installed app-server's `account/read` result. Changing
the local Codex credentials/config invalidates the status cache. OpenCode uses
its own selected provider's OAuth profile/token claims or reports `API` for an
API credential in its supported store. OpenClaw displays an email only when its
provider status reports one. A selected cMeta gateway is labelled `API` and does
not read a personal login, except one that passes that login on (see Gateways). Unsupported identity adapters show `Account unknown`;
quota support is unchanged. No API key, prefix or credential fingerprint is shown.

| Harness | Automatic account quota | Source / limitation |
| --- | --- | --- |
| Codex | Yes, personal login | Installed `codex app-server`, `account/read` and `account/rateLimits/read`. No credential file is copied. |
| Claude | Yes, full OAuth personal login | Read-only Anthropic usage request using the server's existing login; five-hour, weekly and reported model windows. Inference-only tokens/API keys cannot supply subscription quota. |
| OpenCode | Yes, selected OpenAI/Anthropic OAuth provider | Reads that provider from OpenCode's legacy `auth.json`, never another harness's login. API credentials show `API`; plugins and newer credential stores return a specific diagnostic and usage link. |
| OpenClaw | Yes, where its CLI reports windows | `openclaw status --usage --json`, filtered to the explicit `provider/model`; ambiguous accounts are rejected. Requires a configured CLI/provider. |
| Vibe | Usage page | Mistral account dashboard; no automatic quota reader connected to the installed login. |
| Gemini | Usage page / CLI stats | Quota depends on Google login, Code Assist licence, API key or Vertex project. No automatic reader connected here. |
| Antigravity (`agy`) | Usage page / app quota view | Model allowances differ by account/plan; no standalone reader connected here. |
| Hermes | Provider dashboard | Multiple providers; run costs are not a subscription allowance. No automatic reader connected here. |
| Custom gateway / other harness | Explicit diagnostic | A personal account's quota would be misleading for another gateway/provider. |

No inference requests, purchases, browser login, token refresh, or credential writes
are performed by this task. Credential reads respect `CLAUDE_CONFIG_DIR`,
`CLAUDE_CODE_OAUTH_TOKEN`, `CODEX_HOME`, and OpenCode's `XDG_DATA_HOME`.
Claude's macOS keychain-only login is not read by this adapter. If a token expires,
run the relevant harness once to refresh its normal login and check again.

HTTP authorization is sent only to the fixed provider HTTPS endpoint, with
redirects blocked. Raw credentials, provider responses and CLI status are never
logged or returned. Only normalized display data is cached in
`log::local:ai-account-status`, for two minutes, under a credential-identity hash.
Rate limits apply a bounded cooldown; last known values are explicitly marked
stale. This cache and the credentials are machine-local, outside this task folder.
The Claude/OpenCode usage endpoints are provider interfaces used by their clients,
not a promise of a stable public billing API.

For browsers, `client_script=True` returns the optional component in
`files/js/account-status.js`. Embed it before the app controller, then use
`window.CMetaAIAccountStatus.mount({get, query, values, onChange})`. An app whose AI runs on
another machine adds `where: () => '<machine>'`: the line then says which machine it checked.
It shares formatting, refresh handling, stale-selection protection, reset times,
usage-page links and run-usage display across all apps.
The hosting app remains responsible for authentication/access checks.

## Harness versions: the ways an account is read

A harness changes over time: where it keeps its login, how its usage is asked. The task does not follow the newest
harness alone. `_desc.yaml` declares, per harness (`harnesses:`), the cMeta tool that finds it and the **ways** its
account is read, the newest first, each with the harness version it starts at (`since`):

1. The installed harness's version is asked from cMeta's own tool detection (the `setup` task of the harness's tool
   artifact; nothing is installed). It is kept in `harness/<harness>.json` of `log::local:ai-account-status` and asked
   again when the program's file changed, else after an hour (the detection starts the program: seconds).
2. The first way whose `since` is not above that version is taken (no `since`: every version).
3. The answer says what was used: `harness_version`, `mechanism` (the way's name) and, when there is something to
   say, `mechanism_note`. `source` is unchanged.

| Case | What happens |
| --- | --- |
| The version is known | the way declared for it |
| The harness is not found by cMeta on this machine, or its version is not one the engine compares | the newest way; `mechanism_note` says so |
| The version is below every `since` | `available: false`, `reason: harness_version`, the message names both versions; `return` stays 0 and AI runs are not stopped |
| A way that starts the program (`codex-app-server`, `openclaw-status`) | starts the program cMeta found - the one whose version chose the way |

**When a harness changes, a way is added - none is replaced.** Add an entry above the others in `_desc.yaml` with
`since: <the first version that needs it>`, a reader for its name in `_selection` of `api_v1.py`, and a line under
`verified` once it was really read (harness version, system, day). The entries below it stay as they are, for the
machines that still run an older harness. `tests/cmeta_aops_basic_tests/test_ai_account_status_ways.py` holds the
rules: every way has its reader, the ways are the newest first, each harness names its tool by `alias,UID`.

Today each harness has one way, read on Windows on 2026-11-20: `claude-oauth-usage` (Claude Code 2.1.327),
`codex-app-server` (Codex 0.170.0), `opencode-auth-file` (OpenCode 1.19.5); `openclaw-status` is declared but
not yet read with success (its `verified` list is empty).

## Gateways

`gateway` is `login` (the harness's own login, the default) or an `ai.gateway` alias:

- A gateway that passes the harness's own login on (`auth: {header: login}`, such as `local-login`) reads that
  login, as `login` does: the run spends the login's allowance, only its address changes. Claude and Codex only
  (the harnesses such a gateway serves); the answer has `own_login: true`.
- A gateway with a key, one without a key (a local model server) and one this machine does not have are named in
  the message (`Through the AI gateway team-gateway with its key: ...`) and labelled `API`; no personal login is read,
  and no secret or its name is returned.

`machine_default=True` with an empty gateway checks the account of the gateway a run-ai run without a gateway flag
takes on this machine (set-ai-gateway: `run_ai_gateway_<harness>`, then the general `run_ai_gateway` for claude,
codex and opencode, else the login). `gateway` and `gateway_how` in the answer say which one and why. Without
`machine_default`, an empty gateway is the login, as before. A project's own choice (`ai_gateway`, the
`run_ai_config.gateway` of its last run) is not read: the caller passes that gateway when it knows it.

```sh
cx task run ai-account-status --harness=claude --gateway=local-login --json
cx task run ai-account-status --harness=codex --gateway= --machine_default --json
```

Offline regression tests (no credentials, network or model calls):

```sh
python -m pytest tests/cmeta_aops_basic_tests/test_ai_account_status.py tests/cmeta_aops_basic_tests/test_ai_account_status_ways.py -q
```

Provider references checked 2026-11-13:

- [Codex account/rate-limit protocol tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/rate_limits.rs)
- [Claude rate-limit status fields](https://code.claude.com/docs/en/statusline) and [Anthropic usage endpoint issue](https://github.com/anthropics/claude-code/issues/31021)
- [Claude cached account identity after switching logins](https://github.com/anthropics/claude-code/issues/81231)
- [OpenCode provider authentication](https://opencode.ai/docs/cli/providers/)
- [OpenClaw quota tracking](https://docs.openclaw.ai/concepts/usage-tracking)
- [Mistral Usage and limits](https://docs.mistral.ai/admin/billing-usage/usage-limits)
- [Gemini quotas](https://geminicli.com/docs/resources/quota-and-pricing/)
- [Antigravity plans and quota view](https://antigravity.google/docs/plans)
- [Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
