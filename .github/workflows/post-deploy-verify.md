# Post-Deploy Verification
*GitHub Agentic Workflow — Phase F, HARNESS_UPGRADE.md*

## Trigger
on: push: branches: [main]

## Goal

After Railway has had time to deploy (wait 3 minutes for the build to complete),
hit the CometCloud production API endpoints and verify that the deployment is
healthy. If any endpoint fails, open a GitHub issue labeled `incident` with the
findings.

**Production URL:** `https://web-production-0cdf76.up.railway.app`

## Endpoints to check (in order)

### 1. CIS Universe (critical)
```
GET /api/v1/cis/universe
```
Pass criteria:
- HTTP 200
- Response contains `assets` array with at least 10 entries
- At least one asset has a `cis_score` field
- No asset has `signal` value of BUY, SELL, HOLD, AVOID, ACCUMULATE, or REDUCE

Fail criteria:
- `assets: []` or missing → Railway env var `COINGECKO_API_KEY` is missing
- HTTP 500 → Python exception in scoring; check Railway logs

### 2. Macro Pulse (important)
```
GET /api/v1/market/macro-pulse
```
Pass criteria:
- HTTP 200
- `btc_price` is a number > 1000
- `fear_greed_value` is a number 0–100

### 3. Signal Feed (important)
```
GET /api/v1/market/signals
```
Pass criteria:
- HTTP 200
- `signals` array with at least 3 entries
- Each signal has `title`, `description`, `signal` fields

### 4. DeFi Overview (moderate)
```
GET /api/v1/market/defi-overview
```
Pass criteria:
- HTTP 200
- `total_tvl` > 50000000000 ($50B)

## Reporting

### If all checks pass
Post a commit status: "Deploy verification: PASS — all 4 checks green"

### If any check fails
1. Post a commit status: "Deploy verification: PARTIAL/FAIL — [specific failures]"
2. Open a GitHub issue with title: "Deploy incident: [commit hash] — [what failed]"
3. Label the issue: `incident`, `priority: high`
4. Issue body should include:
   - Which endpoints failed
   - HTTP status codes received
   - Expected vs actual response shape
   - Suggested remediation from the table below

## Remediation shortcuts

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| CIS assets = 0 | `COINGECKO_API_KEY` missing | Railway → Variables → add key |
| HTTP 500 on CIS | Python crash in scoring | Check Railway logs; notify Jazz |
| MacroPulse btc_price null | CoinGecko rate limit | Redis cache recovers in <5min |
| Signal feed empty | DeFiLlama unreachable | Check DeFiLlama status; data recovers |
| HTTP 503 on all routes | Railway build still in progress | Wait 2 min and retry |

## Context

This workflow runs automatically after every push to main. Railway auto-deploys take
~90 seconds. The 3-minute wait gives Railway time to build and switch traffic. If the
deploy verifier fails, it means real users are hitting a broken production environment
and Jazz should be notified immediately.
