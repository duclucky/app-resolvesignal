# Troubleshooting

**More info needed** is a completed evidence-gap result. It is different from a request that failed to start.

| Symptom | What to check | Next step |
|---|---|---|
| Live option disabled | `LIVE_CALLS_ENABLED` is not exactly `true`, or the local copy is unconfigured. | Try **Try made-up examples**, or follow [Live configuration](configuration.md#enable-the-live-agent) and restart. |
| Keys present, usage failure | One cap is `0`, or cumulative reservations have reached it. | Check both `NEBIUS_BUDGET_USD` and `TAVILY_CREDIT_CAP` and usage status. Account credits do not update app settings. |
| Public hourly allowance exhausted | Session or shared admissions reached their rolling limit. | View saved results or try made-up examples. Wait for allowance to replenish; the form shows remaining counts. |
| Provider access/quota failure | Key, model access, quota or temporary provider failure. | Verify access in the provider console, keep the supported model ID and inspect saved call statuses. Never paste keys into issues/reviews. |
| Blocked page or no usable evidence | The store may return HTTP 401/403/429, require login or omit selected-product details. | Follow **How to complete this check**. Open the source or try another public page with the exact version selected. The app does not bypass access protections. |
| **More info needed** despite similar titles | Barcode, variant, condition, pack size, price terms or fresh prices may be missing. | Expand **Missing details** and inspect **Source evidence**. Generic products need matching valid barcodes; titles/SKUs are insufficient. Never invent facts. |
| Comparable prices, monitor-availability action | The cheaper offer is not in stock. | Review stock and check times; comparable listed terms do not establish a purchase opportunity or automatic repricing. |
| Review no longer current after a check | Reviews belong to the version that was reviewed. | Review the new result and save a new review. Old reviews remain in **More details → Earlier result versions**. |
| Saved case missing locally | A fresh clone has no hosted results or live database. | Create a local example or an authorized new check. Hosted case URLs are separate from local state. |
| Dependency installation fails | Wrong Python version or platform lock. | Use CPython 3.13 and the Windows/Linux lock from the README. Keep `--require-hashes`; inspect the non-secret error before changing dependencies. |
| `node` not recognized | Node is only required for JavaScript tests. | The app and Python tests work without Node. Verification used Node.js 24 for `node --test tests/ui-state.test.cjs`. |
| Port 8000 in use | Another local service is listening there. | Stop only your own previous instance, or choose another port and match its allowed write origin below. |

## Check local status

Open [healthz](http://127.0.0.1:8000/healthz) for service health and [api/status](http://127.0.0.1:8000/api/status) for configured/enabled flags and reservations. They do not return configured key values. Counters are not billed cost or remaining account balance.

**Technical validation** in the footer runs the 37 fictional rule scenarios, not a natural retail accuracy benchmark. Keep external evaluation flags off for an offline check.

## Use a different local port

The write-origin guard must match the address you open. Example for port 8001, in Windows PowerShell:

```powershell
$env:APP_ALLOWED_ORIGINS='http://127.0.0.1:8001,http://localhost:8001'
.venv/Scripts/python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8001
```

Linux:

```sh
APP_ALLOWED_ORIGINS=http://127.0.0.1:8001,http://localhost:8001 .venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001`. This changes the local origin/port, not public-access policy. Close the terminal or unset `APP_ALLOWED_ORIGINS` when returning to port 8000.
