# Configuration

Local fictional examples need no provider accounts or `.env` file. This guide enables real agent investigations in your own local copy. The hosted demo is already configured by its operator.

## Enable the live agent

1. Stop the local server with `Ctrl+C`.
2. Copy the blank template from the repository root. If `.env` already exists, edit it instead of replacing it.

   Windows PowerShell:

   ```powershell
   Copy-Item -LiteralPath .env.example -Destination .env
   ```

   Linux:

   ```sh
   cp .env.example .env
   ```

3. Add your Nebius Token Factory and Tavily keys in a local editor. Keep the exact model ID below. Set both usage caps to positive amounts you are willing to consume. Example:

   ```dotenv
   NEBIUS_API_KEY=replace-with-your-own-nebius-key
   TAVILY_API_KEY=replace-with-your-own-tavily-key
   NEBIUS_MODEL=nvidia/Nemotron-3.5-Super-VL
   LIVE_CALLS_ENABLED=true
   NEBIUS_BUDGET_USD=0.50
   TAVILY_CREDIT_CAP=20

   LANGSMITH_API_KEY=
   LANGSMITH_WORKSPACE_ID=
   LANGSMITH_ENABLED=false
   ```

   The keys above are placeholders. The caps are example application allowances, not a price quote or guaranteed provider billing limits. Real checks use your provider account/credits. Opening the form makes no live request.

4. Restart with the command in the [README](../README.md#run-locally). Open **New check**, select **Use AI and web sources**, enter two public HTTPS product links with USD prices, then **Run a new check**.
5. Read the result and source evidence before saving your review. A completed check can still return **More info needed** when access is blocked or facts are absent.

The committed `.env.example` deliberately leaves live calls off and both caps at `0`. Do not commit a populated `.env` or put keys in screenshots, issues or review notes.

## Settings reference

| Variable | Default | Meaning |
|---|---|---|
| `NEBIUS_API_KEY` | Blank | Nebius Token Factory key; required for live mode. |
| `TAVILY_API_KEY` | Blank | Tavily key; required for live mode. |
| `NEBIUS_MODEL` | `nvidia/Nemotron-3.5-Super-VL` in template | Model supported by the current reservation policy; another model requires code/pricing review. |
| `LIVE_CALLS_ENABLED` | `false` | Set exactly `true` for the live agent. |
| `NEBIUS_BUDGET_USD` | `0` | Cumulative application reservation cap for this database; positive for live mode, supported maximum `5`. |
| `TAVILY_CREDIT_CAP` | `0` | Cumulative application reservation cap for this database; positive for live mode, supported maximum `200`. |
| `LANGSMITH_API_KEY` | Blank | Optional tracing key. |
| `LANGSMITH_WORKSPACE_ID` | Blank | Workspace ID if required by the account/key. |
| `LANGSMITH_ENABLED` | `false` | Set exactly `true` for optional tracing with a configured key. |
| `APP_ENV_FILE` | Root `.env` | Alternative file path; set as a process environment variable before startup. |
| `APP_DATA_DIR` | Root `data/` | Alternative SQLite state directory; set as a process environment variable before startup. |

Process environment variables override the selected environment file. Default state is `data/investigations.sqlite3`: results, versions, reviews and reservations persist there. No live database is included in the repository.

## Optional LangSmith tracing

Add the key locally, a workspace ID if required, and `LANGSMITH_ENABLED=true`. The app records minimized outcomes, counters and provider summaries and verifies storage by readback. Prompts, page text, URLs, keys and review notes are excluded. Failed optional tracing leaves the local result intact.

Tracing is not required for fictional examples or an ordinary local investigation. The hosted real saved-example shortcut has stricter evidence/receipt requirements than an ordinary local result.

## Usage and access limits

- Counters are conservative application reservations, not invoices or account balances. Failed or uncertain calls retain reservations. Do not delete state to reset an allowance; inspect usage and choose a permitted allowance deliberately.
- Each case has a 120-second deadline and bounded calls, tokens/context and retries. LangSmith permits at most 100 root-run reservations per database.
- The public demo accepts one pair per request, two live starts/rechecks per anonymous visitor session within three shared starts/rechecks per rolling hour, and 20 versions per case. Signed sessions and atomic admissions persist in SQLite across service restarts. Clearing cookies does not bypass the shared limit; sessions are not authenticated identities.
- A separate 30-POST/minute public-demo guard is process-local. Saved results and made-up examples remain available when hourly live allowance is exhausted. Cumulative credit caps still apply.
- Local/private mode also offers CSV preview, up to 25 rows, and direct page inspection. Direct inspection makes network requests but uses neither Tavily nor Nebius inference. Live CSV investigations can consume multiple case allowances.
- Non-HTTPS links, private-network destinations, unsafe redirects and cross-origin writes are rejected. Direct reads pin validated public IPs while TLS verifies the original hostname.

## Local hosting boundary

The documented command binds to `127.0.0.1`. The app has a loopback-host guard and no production account system; changing the bind address alone is not a complete public deployment setup. Hosted settings and public-demo behavior are operator-managed. `deployment/vps/Dockerfile` is supplied, but a fresh build or turnkey authenticated deployment is not claimed.

See [Troubleshooting](troubleshooting.md) for recovery steps.
