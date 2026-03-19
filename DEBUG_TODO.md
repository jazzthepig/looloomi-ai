# Debug & Fix Todo List
**As of:** 2026-03-19 · **Source:** Week 1 code review + Shadow critique reports

---

## 🔴 Critical — Fix Before Next Demo

### 1. Internal token auth is too permissive
**File:** `src/api/main.py` L405
**Bug:** `if _INTERNAL_TOKEN and x_internal_token and x_internal_token != _INTERNAL_TOKEN` — if env var is empty OR header is missing, request passes through. Any unauthenticated request gets accepted.
**Fix:** Flip to reject-by-default:
```python
if _INTERNAL_TOKEN:
    if not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### 2. Debug log leaks internal token to stdout
**File:** `src/api/main.py` L403
**Bug:** `print(f"[DEBUG] INTERNAL_TOKEN env: '{_INTERNAL_TOKEN}'...")` prints the real token on every push.
**Fix:** Remove or mask: `print(f"[DEBUG] Token present: {bool(_INTERNAL_TOKEN)}, header present: {bool(x_internal_token)}")`

### 3. Agent API pillar keys return null
**File:** `src/api/main.py` L564-570
**Bug:** Agent endpoint reads `.get("Fundamental")`, `.get("Momentum")`, etc. but `cis_provider.py` stores pillars as `{"F": ..., "M": ..., "O": ..., "S": ..., "A": ...}`. Every pillar returns `None`.
**Fix:**
```python
"f": a.get("pillars", {}).get("F"),
"m": a.get("pillars", {}).get("M"),
"r": a.get("pillars", {}).get("O"),
"ss": a.get("pillars", {}).get("S"),
"a": a.get("pillars", {}).get("A"),
```

### 4. Agent endpoint score key mismatch
**File:** `src/api/main.py` L563
**Bug:** `"sc": a.get("cis_score", 0)` — but `cis_provider.py` returns `"score"`, not `"cis_score"`. Local engine also uses `"score"`. Agent endpoint returns 0 for all.
**Fix:** `"sc": a.get("score", a.get("cis_score", 0))`

---

## 🟡 Important — Fix This Week

### 5. Bare `except:` in agent endpoint
**File:** `src/api/main.py` L551
**Bug:** Catches `KeyboardInterrupt`, `SystemExit`, etc.
**Fix:** `except Exception:`

### 6. Bare `except:` in WebSocket broadcast
**File:** `src/api/main.py` L593
**Bug:** Silently swallows all exceptions. Dead connections accumulate in `active_connections` list forever.
**Fix:**
```python
async def broadcast(self, message: dict):
    dead = []
    for conn in self.active_connections:
        try:
            await conn.send_json(message)
        except Exception:
            dead.append(conn)
    for conn in dead:
        try:
            self.active_connections.remove(conn)
        except ValueError:
            pass
```

### 7. WebSocket `disconnect()` raises on missing connection
**File:** `src/api/main.py` L586
**Bug:** `.remove()` raises `ValueError` if connection already removed.
**Fix:** Wrap in try/except or use `set` instead of `list`.

### 8. Sparkline fetch is sequential (~2.4s for 30 assets)
**File:** `dashboard/src/components/CISLeaderboard.jsx` L226-240
**Bug:** Serial `fetch()` with 80ms delay per asset.
**Fix:** Batch endpoint `GET /api/v1/cis/history/batch?symbols=BTC,ETH,...` or `Promise.all` with concurrency limit of 5.

### 9. `_redirects` file is dead weight
**Files:** `dashboard/public/_redirects`, `dashboard/dist/_redirects`
**Issue:** Functions proxy supersedes `_redirects` for `/api/*` and `/internal/*`. File creates confusion.
**Fix:** Delete both files.

### 10. Cloudflare proxy missing CORS preflight handler
**File:** `functions/api/[[path]].js`
**Bug:** No `OPTIONS` handler. Browsers send preflight for `POST` requests (e.g., agent calls). Will fail with CORS error.
**Fix:** Add OPTIONS handler:
```javascript
if (request.method === 'OPTIONS') {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Internal-Token',
    },
  });
}
```

---

## 🟢 Minor — Clean Up When Convenient

### 11. CISLeaderboard footer says "CIS v3.1"
**File:** `dashboard/src/components/CISLeaderboard.jsx` ~L734
**Fix:** Update to "CIS v4.0"

### 12. `main.py` is 917 lines — needs router split
**File:** `src/api/main.py`
**Action:** Split into `routers/market.py`, `routers/cis.py`, `routers/signals.py`, `routers/vault.py`, `routers/onchain.py`

### 13. Vault data is hardcoded in main.py
**File:** `src/api/main.py` L702-798
**Action:** Move to `data/vault/fund_registry.py` or database. 97 lines of static JSON in the API file.

### 14. No test coverage anywhere
**Action:** Start with:
- Unit test for `_sanitize_floats()` — NaN, Inf, nested dicts
- Unit test for grade boundaries in `cis_provider.py`
- Integration test for `/api/v1/cis/universe` response shape

---

## Already Fixed (Week 1) ✅

- ~~`cis_push.py` JSON key mismatch (`scores` → `universe`)~~ — Minimax
- ~~Railway `Header()` binding for internal token~~ — commit `23f98ac`
- ~~BTC self-benchmark → Alpha artificially low~~ — commit `777a58d`
- ~~NaN serialization crash~~ — commit `a60abc7`
- ~~Double CIS fetch causing page crash~~ — commit `a75f7cf`
- ~~CISWidget null safety~~ — commit `ae76e5a`
- ~~Wrong CoinGecko IDs (STX/WIF)~~ — commit `55f10c7`
- ~~Upstash Redis bridge (local → Railway)~~ — commit `3ce7336`
- ~~Supabase score history~~ — commit `df86bea`
- ~~Cloudflare Pages Functions proxy~~ — commit `aa8fe01`

---

*14 open items. 10 fixed. Prioritize 1-4 before any Nic demo.*
