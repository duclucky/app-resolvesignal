# ResolveSignal

Investigate whether two retail offers are actually comparable before acting on a price alert. Exact variants, source quotes, missing facts and review history stay visible. The app never changes store prices.

Public demo: https://app.resolvesignal.com . This is a shared demonstration: results and reviews are public. Choose two public HTTPS product pages from US storefronts with USD prices. Product links, results and reviews are public; do not enter private information.

## Run locally

Verified with CPython 3.13 on Windows and Linux. From this directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
.venv/Scripts/python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

On Linux use `python3.13 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes -r requirements.linux.lock`, then `.venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000`.

Open http://127.0.0.1:8000 . Fictional samples and the local quality suite work without credentials. `run.ps1` is a Windows convenience launcher. Docker setup is in `deployment/vps/Dockerfile`; build from the application root. Verification used an existing pinned Windows/Linux runtime; a fresh dependency installation or Dockerfile build is not claimed.

Connections are configured on the server; there is no browser settings page. Copy `.env.example` to `.env` only when enabling integrations, and configure keys locally. Never commit populated environment files. Local state defaults to `data/investigations.sqlite3`; set `APP_DATA_DIR` and `APP_ENV_FILE` for separate profiles. Local access remains bound to loopback.

## First look

Choose **Check your products** on the homepage to enter two product links, or use the secondary saved-result action to explore without provider calls. An empty local installation offers clearly labeled fictional examples; it does not include the hosted demo's database. `/start` remains a compact source-context/fallback route. A real saved-example shortcut requires completed selected-source evidence, successful NVIDIA/Nebius and Tavily steps and a verified LangSmith receipt.

Public `/new` accepts one pair of public HTTPS product URLs from any storefront. Select the exact product version, paste Offer A and Offer B, then choose **Run a new check**. This uses Tavily and NVIDIA on Nebius within the configured caps. Merely opening the form or viewing saved results does not call providers. Public CSV is hidden; private profiles retain CSV and page-only inspection. Saved examples remain available separately.

Case detail leads with action, reason and missing facts, followed by compact offers, selected quotes and version-specific review. **More details** preserves all attributes, source evidence, provider receipts, sourced confirmations and history. **Download group** provides CSV, JSON and an HTML report. Public **Technical validation** retains the offline suite and integration receipts, omits owner tools and rejects developer-batch creation.

## Local/private input journey

1. Open **Live check** (public) or **New check** (private). Select the exact size/color/version on each US product page, then paste both full HTTPS links. Any product type can be investigated; private/account/search pages are unsuitable.
2. Choose public page inspection or live agent investigation. Public inspection uses no Tavily/Nebius inference. Live mode requires configured keys and enabled credit caps.
3. Open a case from the queue. Inspect the decision, unknown fields, quoted sources and actual provider steps.
4. Save a revision-specific review; export the full batch as CSV, JSON or an HTML report.
5. Recheck for a new evidence revision. Previous evidence/reviews remain historical; a fresh revision needs a new review. Cancelled/interrupted attempts cannot be counted as fresh positive decisions.

Routes: `/new`, `/investigations`, `/cases/{id}`, `/quality` (Technical validation in the footer). CSV preview supports at most 25 rows with `sku,reference_url,competitor_url` columns in local profiles. The public demo accepts one live pair per request. It also retains saved real and clearly fictional examples.

## Integrations and evidence

- **NVIDIA on Nebius Token Factory:** `nvidia/Nemotron-3.5-Super-VL` asks a bounded evidence question and proposes fields with exact supporting quotes. An OpenAI-compatible HTTP endpoint is used; no OpenAI service is required.
- **Tavily:** searches for relevant evidence and extracts permitted source text. Search snippets remain discovery leads. Adafruit pages 6090/6089 are fetched directly under a narrow source/rate policy; they are not sent to remote extraction. Tavily can research permitted follow-up sources in the agent workflow.
- **LangSmith:** records minimized outcomes, counters and provider summaries with readback verification. Source pages, prompts, URLs, keys and review notes are excluded. Trace failure does not discard the local decision.

Deterministic rules validate selected variants, condition, pack quantity, currency, stock, price eligibility and freshness before showing a comparable listed-price gap. Unknown fields stay unknown. Search/extraction or substring success alone does not prove a claim. Retrieved text is untrusted; no page instructions are executed.

The selected Adafruit 256GB/512GB pair is a **same-merchant variant control**, not a competitor-price opportunity. Real runtime calls and a supported mismatch have been observed. Price and stock are timestamped observations, not current purchase guarantees. A complete natural positive-price pair, universal retailer retrieval, measured time savings and customer adoption have not been established. Generic products require matching validated product barcodes before a positive comparison; other missing or conflicting details remain explicit. Barcodes from model claims need an exact labeled source span, a valid checksum and no competing labeled barcode on that page. A single Product microdata block is supported alongside JSON-LD. Shipping and tax may differ.

Operator confirmations can fill genuinely checked missing attributes only with a source URL, excerpt and explicit attestation. They remain visibly operator-assisted and are not independently verified. They cannot overwrite known contradictions and must be reconfirmed after recheck.

Toloka and Tendem were experimental integrations and were removed on user instruction. No runtime client, background watcher, owner dispatch API/CLI or external review import remains. Historical private receipts are outside this source package.

## Credit and access controls

Configure `NEBIUS_API_KEY`, `TAVILY_API_KEY`, the exact `NEBIUS_MODEL`, and `LIVE_CALLS_ENABLED`. Optional tracing uses `LANGSMITH_API_KEY`, `LANGSMITH_WORKSPACE_ID`, `LANGSMITH_ENABLED`.

Application caps reserve conservative usage; they are not actual billing or account balances. Maximum configurable limits are USD 5 Nebius and 200 Tavily credits. LangSmith allows at most 100 root-run reservations per database. Failed/uncertain calls retain reservations; do not delete state to extend allowance. No auto top-up or PAYG setting is changed.

A live case has a 120-second deadline and bounded tool/model attempts, source context and retries. Non-HTTPS/private-network URLs, unsafe redirects and cross-origin writes are rejected. Direct source connections use validated public IPs while TLS verifies the original hostname. Hosted profiles lock settings. The public demo permits two live starts/rechecks per anonymous visitor session within three shared starts/rechecks per rolling hour. Atomic admissions and the session-signing secret persist in SQLite across restarts; opening saved results does not consume them. A signed HttpOnly/Secure/SameSite=Lax cookie identifies a seven-day visitor session. This is anonymous fairness, not authenticated identity: clearing cookies creates another session but cannot bypass the shared cap. Existing cumulative credit caps still apply. The 30-POST-per-minute guard remains process-local and cases are limited to 20 revisions. These are demo guards, not production multi-tenant guarantees.

The homepage starts with **Check your products**. When evidence is missing, result recovery steps explain blocked or unreadable sources, exact product/barcode checks and missing offer terms. Open the sources, try different links, or save what still needs checking. Source confirmations require an exact same-store source for unfamiliar storefronts; they cannot supply an unsupported barcode or erase contradictions.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest -q --basetemp .cache/new-unique-run
node --test tests/ui-state.test.cjs
.venv/Scripts/python.exe scripts/quality_eval.py --output .cache/local-quality.json
```

Use a fresh app-local test directory. On Linux replace the Python executable path with `.venv/bin/python`. Local quality has 37 fictional, sourced regression scenarios; it measures those rule paths, not natural retail accuracy. Tests use controlled providers and do not make paid calls. Live checks need explicit scoped credit authorization and configured caps.

## Local review package

```powershell
.venv/Scripts/python.exe scripts/package_release.py
```

Creates `../deliverables/price-alert-investigator-source.zip` with a checked source manifest. It allowlists source, fixtures, tests, setup and license files; excludes credentials, databases, caches, captures and historical provider jobs. It does not publish a repository, video or competition entry.

Original application code is MIT licensed. See `THIRD_PARTY_NOTICES.md` for the React Bits Spotlight adaptation and its separate license. The ecommerce API directory was a research reference; its product implementation was not imported.
