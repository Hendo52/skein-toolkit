# Cloudflare Workers AI configuration

This toolkit talks to Cloudflare Workers AI through `mcp-server/local-mcp.py`'s
`/cfproxy/{account_id}/...` route, which proxies and instruments
OpenAI-compatible chat-completions requests to
`https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/...`.

There is no `zone-config.json` or firewall/routing rule set for this project --
configuration is **entirely environment-variable based**:

| Variable | Set in | Purpose |
|----------|--------|---------|
| `CF_API_BASE` | `mcp-server/litellm.env` | LiteLLM's upstream base URL for `cf/*` models, e.g. `http://127.0.0.1:3100/cfproxy/<ACCOUNT_ID>/v1`. `<ACCOUNT_ID>` is your Cloudflare account ID. |
| `CF_API_KEY` | `mcp-server/litellm.env` | A Cloudflare API token (Workers AI permissions) sent as the `Authorization: Bearer` header. local-mcp.py forwards this header as-is to the Cloudflare API -- it does not store or read a separate token itself. |
| `CF_PROXY_USD_TO_AUD_RATE` | environment (optional) | Exchange rate used only for the architect's spend-review display; CF bills in USD. Default `1.42`. |
| `CF_PROXY_MONTHLY_BUDGET_AUD` | environment (optional) | Monthly CF spend budget (AUD) used to derive the daily spend-review threshold. Default `100.00`. |
| `CF_PROXY_DAILY_REVIEW_THRESHOLD_USD` | environment (optional) | Overrides the derived daily review threshold directly (USD). |

## Getting a Cloudflare API token

1. Log in to the Cloudflare dashboard and find your **Account ID** (right-hand
   sidebar of any account page).
2. Go to **My Profile -> API Tokens -> Create Token** and create a token with
   **Workers AI** read/edit permissions for your account.
3. Copy `mcp-server/litellm.env.example` to `mcp-server/litellm.env` and set:
   ```
   CF_API_BASE=http://127.0.0.1:3100/cfproxy/<ACCOUNT_ID>/v1
   CF_API_KEY=<your-token>
   ```

`mcp-server/litellm.env` is gitignored -- never commit real tokens.

## Why no zone-config files

Earlier drafts of the spin-off plan assumed a `cloudflare/zone-config.json`
and `cloudflare/rules/*` (DNS/firewall rules), mirroring a full Cloudflare
zone setup. This project does not use Cloudflare DNS, zones, or firewall
rules -- only the Workers AI inference API via a bearer token, configured
purely through the environment variables above. No zone-config files exist
or are needed.
