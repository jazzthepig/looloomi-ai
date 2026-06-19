# Code Review + UX/UI Review
**Date:** 2026-03-19
**Scope:** Full codebase — backend routers, store, frontend components
**Reviewers:** Seth + Austin

---

## Critical Bugs (Fix Before Next Demo)

### 1. Batch history endpoint is unreachable — sparklines silently broken

`src/api/routers/cis.py`, lines 139 and 154

```python
@router.get("/api/v1/cis/history/{symbol}")   # registered FIRST
async def get_cis_history(symbol: str, ...):

@router.get("/api/v1/cis/history/batch")       # registered SECOND — never reached
async def get_cis_history_batch(symbols: str, ...):
```

FastAPI matches routes in registration order. Any request to `/api/v1/cis/history/batch` matches `{symbol} = "batch"` and goes to the single-asset handler. The batch endpoint is unreachable. `CISLeaderboard.jsx` line 232 silently hits the wrong endpoint — sparklines load zero data.

**Fix:** Register batch route before the `{symbol}` route, or rename to `/api/v1/cis/history-batch`.

---

### 2. Internal CIS push endpoint unprotected when env var absent

`src/api/routers/cis.py`, line 31

```python
_INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

if _INTERNAL_TOKEN:          # ← if env var missing, entire if block is skipped
    if not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
```

If `INTERNAL_API_TOKEN` is not set in Railway env, ANY caller can push arbitrary CIS scores to the cache and trigger WebSocket broadcasts. This is the ROADMAP Phase 1.3 fix listed as "reject-by-default" — it was not actually implemented.

**Fix:**
```python
if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
    raise HTTPException(status_code=401, detail="Invalid token")
```

---

### 3. CORS misconfiguration — credentialed requests broken in browsers

`src/api/main.py`, lines 32–38

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,   # ← incompatible with allow_origins=["*"]
    ...
)
```

The CORS spec forbids `Access-Control-Allow-Origin: *` when credentials are included. Browsers reject this combination. Any fetch that sends cookies or Authorization headers from a cross-origin page will fail. FastAPI itself emits a warning about this.

**Fix:** Either set explicit origins or remove `allow_credentials=True` (the API uses bearer tokens in query params/headers, not cookies, so credentials mode is likely unnecessary).

---

### 4. `market.py` import path missing `src.` prefix

`src/api/routers/market.py`, line 9

```python
from data.market.data_layer import (    # ← missing src. prefix
```

All other routers use `from src.data...` or rely on the path manipulation in `main.py`. This is inconsistent and likely causes import errors unless `data/` is on `sys.path` separately. Compare with `intelligence.py` line 8: same issue. `onchain.py` line 8: same. The three newer routers all have this — `cis.py` correctly uses `from src.data.cis...`.

**Fix:** Audit all three newer routers and add `src.` prefix, or verify that `sys.path` manipulation in `main.py` makes the shorter path work consistently.

---

### 5. Portfolio optimization blocks the event loop

`src/api/routers/vault.py`, lines 104–115

```python
@router.post("/api/v1/portfolio/optimize")
async def optimize_portfolio(request: PortfolioRequest):
    optimizer = CryptoPortfolioOptimizer(assets=request.assets)
    optimizer.fetch_historical_data(days=90)   # ← blocking network + pandas call, no await
```

`fetch_historical_data()` makes HTTP requests and does matrix math. Called synchronously inside an async handler, it blocks the entire event loop — all WebSocket connections, incoming requests, everything — for however long it takes (likely 2–10 seconds). Same issue in `get_portfolio_stats()`.

**Fix:** Wrap in `asyncio.to_thread()` or use `run_in_executor`.

---

## High Priority

### 6. `total_score.toFixed(1)` crash when score is null

`dashboard/src/components/CISLeaderboard.jsx`, lines 700 and 765

```jsx
{item.total_score.toFixed(1)}              // line 700 — throws if null/undefined
{selectedAsset?.total_score.toFixed(1)}    // line 765 — optional chains the asset but not the score
```

The Railway fallback `cis_provider.py` may return `score` (not `cis_score`). The mapping at line 182 sets `total_score: asset.cis_score` — if the key is absent, `total_score` is `undefined` and `.toFixed()` throws, crashing the entire leaderboard render.

**Fix:** `(item.total_score ?? 0).toFixed(1)` and `(selectedAsset?.total_score ?? 0).toFixed(1)`.

---

### 7. SignalRow click handler prop never forwarded

`dashboard/src/components/SignalFeed.jsx`, lines 47 and 280–286

```jsx
// Component definition — onClick not destructured
const SignalRow = ({ signal, isNew }) => {  // line 47

// Usage — onClick prop passed but goes nowhere
<SignalRow
  key={signal.id || idx}
  signal={signal}
  onClick={onSignalClick}   // line 283 — ignored
  isNew={idx === 0}
/>
```

Signal rows have `cursor: pointer` set but clicking does nothing. The `onSignalClick` prop passed from the parent is silently dropped.

---

### 8. `GRADE_LABELS` defined but never used — dead compliance risk

`dashboard/src/components/CISLeaderboard.jsx`, lines 54–60

```javascript
const GRADE_LABELS = {
  A: "Priority Allocation",
  B: "Qualified",
  C: "Watchlist",
  D: "Avoid",          // ← advisory language, never rendered but creates confusion
  F: "Eliminated",
};
```

This object is declared and never referenced anywhere in the file. It's dead code. The concern is that someone adds a reference to it in the future without noticing `D: "Avoid"`. Delete it.

---

### 9. Railway URL hardcoded in Cloudflare proxy source

`functions/api/[[path]].js`, line 1

```javascript
const RAILWAY_URL = 'https://web-production-0cdf76.up.railway.app';
```

The internal Railway URL is in version-controlled source. Anyone with repo access (or who clones/forks it) has the direct backend URL — bypassing Cloudflare entirely, including any WAF rules, rate limits, or future DDoS protection. This also leaks the deployment identifier.

**Fix:** Move to a Cloudflare Pages environment variable (`env.RAILWAY_URL`).

---

### 10. `_p()` helper duplicated — module-level function needed

`src/api/routers/cis.py`, lines 224 and 287

The identical `_p()` helper function is defined twice — once inside `agent_cis_endpoint()` and once inside `_broadcast_cis_update()`. If the logic ever needs updating, it must be changed in two places.

**Fix:** Hoist to module-level.

---

## Medium Priority

### 11. `asynccontextmanager` import unused

`src/api/store.py`, line 12

```python
from contextlib import asynccontextmanager   # unused
```

Dead import. Minor noise, but also caused by the router split — clean it up.

---

### 12. On-chain address handler calls two APIs sequentially

`src/api/routers/onchain.py`, line 29

```python
balance, txs = await get_eth_balance(address), await get_eth_transactions(address)
```

Python evaluates this left to right — `get_eth_balance` completes before `get_eth_transactions` starts. Use `asyncio.gather()` for ~2x latency improvement.

---

### 13. OHLCV error check fragile

`src/api/routers/market.py`, lines 32–33

```python
if data and "error" in data[0]:
```

If `data` is not a list, or is an empty list, `data[0]` raises `IndexError` / `TypeError`. The API returns an unhandled 500 instead of a clean 502.

---

### 14. `sparkFetchedRef` not reset on data refresh

`dashboard/src/components/CISLeaderboard.jsx`, lines 221–248

`sparkFetchedRef.current = true` is set on first fetch. If data refreshes (externalData prop changes, or parent re-fetches universe), sparklines won't update because the ref gate is still `true`. Sparklines will be stale.

**Fix:** Reset `sparkFetchedRef.current = false` in the data fetch effect when new data arrives.

---

### 15. Pillar weights sum to 100 but PILLAR_DEFS shows `key: "alpha"` not `"A"`

`dashboard/src/components/CISLeaderboard.jsx`, line 84 vs line 155/183

The pillar key in the PILLAR_DEFS array is `"alpha"`, but in CISWidget.jsx the same pillar is sometimes displayed as `"A"`. The detail panel at line 779 does `selectedAsset?.pillars[p.key]` where p.key is `"alpha"`. This only works if the pillars object was built with key `"alpha"` — which it is (line 155, 183). But CISWidget's component (different file) may use `"A"` internally. Verify consistency across both components.

---

### 16. VaultPage.jsx has 200+ lines of commented-out fictional fund data

`dashboard/src/components/VaultPage.jsx`, lines 12–170

Large block of commented-out placeholder fund data (ArkStream Capital, Nebula Ventures, Quantum Hedge, Phoenix Digital) left in production code. These are fictional entities with fabricated performance numbers. Even commented out, this creates confusion in the codebase and is a compliance risk if accidentally uncommented.

**Fix:** Delete the commented block. Git history preserves it if ever needed.

---

### 17. `VCDealFlowTracker` instantiated as new object per request

`src/api/routers/intelligence.py`, lines 33 and 49

A new `VCDealFlowTracker()` object is created on every request. If the tracker's `__init__` is expensive (loads data files, establishes connections), this is a performance issue. Cache as a module-level singleton.

---

## UX / UI Review

### A. Inconsistent loading states

`CISLeaderboard.jsx` line 400–406 shows plain text "Loading CIS data..." while `SignalFeed.jsx` has proper skeleton loaders with animated pulse. The leaderboard is the most prominent component — it should match the skeleton pattern.

---

### B. Error retry uses page reload

`CISLeaderboard.jsx` line 412:
```jsx
<button onClick={() => window.location.reload()}>Retry</button>
```
Refreshes the entire SPA. Should call `fetchData()` directly — the component already has it in scope.

---

### C. Detail panel description always empty

The asset detail panel (`selectedAsset?.description`) is always `""` because the data mapping at lines 158 and 187 hardcodes `description: ""`. The empty description section still renders a bottom border and takes space. Either populate descriptions from the CIS data or remove the empty section.

---

### D. Fixed 300px detail panel too narrow

`CISLeaderboard.jsx` line 640:
```jsx
gridTemplateColumns: "1fr 300px"
```
On a 1280px screen, the detail panel is 300px with 5 pillar bars + labels. The pillar labels ("Fundamental", "Market Structure", etc.) are truncated at small sizes. The panel needs ~340–360px minimum, or the grid should use `minmax(280px, 300px)`.

---

### E. CSS injected into DOM via side effect

`CISLeaderboard.jsx` lines 209–218:
```jsx
useEffect(() => {
  const id = "cis-responsive-css";
  if (!document.getElementById(id)) {
    const s = document.createElement("style");
    s.id = id;
    s.textContent = CIS_CSS;
    document.head.appendChild(s);
  }
}, []);
```
Programmatic DOM style injection is an anti-pattern in React. Move `CIS_CSS` to a proper `.css` file or use CSS modules. The current approach also fails in SSR and leaks if the component is unmounted/remounted.

---

### F. Naming collision: two components named `CISLeaderboard`

`CISWidget.jsx` line 116 exports `export function CISLeaderboard(...)` — a simplified table component. `CISLeaderboard.jsx` exports a full-featured leaderboard as its default. Both are in the same components directory. This is a maintenance trap — any developer importing by name will get confused.

**Fix:** Rename the CISWidget version to `CISLeaderboardTable` or similar.

---

### G. `maxHeight: 500` on leaderboard table is arbitrary

`CISLeaderboard.jsx` line 659:
```jsx
maxHeight: 500,
```
With 50+ assets, 500px creates a cramped scroll area inside an already-scrolling page. Use `max-height: calc(100vh - 380px)` or `max-height: none` with virtual scrolling (see ROADMAP performance item).

---

### H. Signal type `REGULATORY` maps to same color as `FUNDING`

`SignalFeed.jsx` lines 12–13:
```javascript
FUNDING:    { color: T.blue, ... },
REGULATORY: { color: "#4B9EFF", ... },   // identical to T.blue
```
These two signal types are visually indistinguishable. Assign a distinct color to REGULATORY (e.g., orange `#FF6B00`).

---

### I. Backtest strip shows `+0.00%` for TradFi assets

`CISLeaderboard.jsx` lines 525–537 — Known issue: Binance klines don't carry SPY/AAPL/GLD/TLT. All TradFi assets show `0.00%` in the backtest strip, which is misleading. Either filter TradFi assets out of the backtest display, or add a `—` placeholder with a tooltip explaining the data gap.

---

## Verdict

**Ship-blocker:** Item 1 (batch history routing bug) explains why sparklines never populate. Fix takes 2 lines.
**Security:** Items 2, 3, 9 — address before any public/investor exposure.
**Stability:** Items 5, 6 — crash risks under normal usage.
**Cleanup:** Items 8, 11, 14, 16 — low effort, high clarity.

**Suggested fix order for next push:**
1. Swap route order for batch history (Item 1) — 2 lines
2. Internal token reject-by-default (Item 2) — 1 line
3. `total_score` null guard (Item 6) — 2 lines
4. SignalRow onClick forwarding (Item 7) — 1 line
5. GRADE_LABELS delete (Item 8) — 6 lines deleted
6. CORS credentials flag (Item 3) — 1 line deleted
7. asynccontextmanager unused import (Item 11) — 1 line deleted
8. Delete commented VaultPage data (Item 16) — 200 lines deleted
