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

| Harness | Automatic account quota | Source / limitation |
| --- | --- | --- |
| Codex | Yes, personal login | Installed `codex app-server`, `account/read` and `account/rateLimits/read`. No credential file is copied. |
| Claude | Yes, full OAuth personal login | Read-only Anthropic usage request using the server's existing login; five-hour, weekly and reported model windows. Inference-only tokens/API keys cannot supply subscription quota. |
| OpenCode | Yes, selected OpenAI/Anthropic OAuth provider | Reads that provider from OpenCode's legacy `auth.json`, never another harness's login. API keys, plugins and newer credential stores return a specific diagnostic and usage link. |
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
`window.CMetaAIAccountStatus.mount({get, query, values, onChange})`.
It shares formatting, refresh handling, stale-selection protection, reset times,
usage-page links and run-usage display across all apps.
The hosting app remains responsible for authentication/access checks.

Offline regression tests (no credentials, network or model calls):

```sh
python -m pytest tests/cmeta_aops_basic_tests/test_ai_account_status.py -q
```

Provider references checked 2026-11-13:

- [Codex account/rate-limit protocol tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/rate_limits.rs)
- [Claude rate-limit status fields](https://code.claude.com/docs/en/statusline) and [Anthropic usage endpoint issue](https://github.com/anthropics/claude-code/issues/31021)
- [OpenCode provider authentication](https://opencode.ai/docs/cli/providers/)
- [OpenClaw quota tracking](https://docs.openclaw.ai/concepts/usage-tracking)
- [Mistral Usage and limits](https://docs.mistral.ai/admin/billing-usage/usage-limits)
- [Gemini quotas](https://geminicli.com/docs/resources/quota-and-pricing/)
- [Antigravity plans and quota view](https://antigravity.google/docs/plans)
- [Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
