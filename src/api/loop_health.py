"""
Loop Health — one probe that answers "is every part of the loop flowing?" (Seth, 2026-07-10).
==============================================================================================

Per LOOP_ENGINEERING.md: the failure mode is an orphaned stage that hides for months
(the narrative engine did exactly that). This is the instrument that makes that
impossible — it checks each stage of INGEST → COMPUTE → STORE → SERVE → MEASURE →
FEED BACK against the live system and reports flowing / stale / broken per stage.

Runnable two ways:
  - as a script:  python3 -m src.api.loop_health [BASE_URL]   (probes live HTTP)
  - as an endpoint: GET /internal/loop-health  (wire check_loop_health into a router)

No secrets needed — it reasons from the public + internal HTTP surface the app already
exposes, so it works from anywhere (sandbox, CI, prod).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict

import httpx

DEFAULT_BASE = "https://looloomi.ai"


@dataclass
class StageHealth:
    stage: str
    status: str          # "flowing" | "stale" | "broken"
    detail: str


async def _get(client: httpx.AsyncClient, url: str, **kw):
    try:
        r = await client.get(url, timeout=30, **kw)
        return r.status_code, (r.json() if "json" in r.headers.get("content-type", "") else r.text)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def check_loop_health(base: str = DEFAULT_BASE) -> dict:
    """Probe every loop stage. Returns {overall, stages:[...], checked_at}."""
    out: list[StageHealth] = []
    async with httpx.AsyncClient(headers={"User-Agent": "loop-health"}) as c:
        # ── SERVE + COMPUTE: the CIS universe is the spine ──────────────────
        sc, body = await _get(c, f"{base}/api/v1/cis/universe")
        universe = (body or {}).get("universe", []) if isinstance(body, dict) else []
        n = len(universe)
        out.append(StageHealth("compute/serve (CIS universe)",
                               "flowing" if n >= 20 else ("stale" if n else "broken"),
                               f"{n} assets, regime={(body or {}).get('macro_regime') if isinstance(body, dict) else '?'}"))

        # ── STORE (hot): Mac Mini push freshness + causes populated ─────────
        sc, bs = await _get(c, f"{base}/internal/build-state")
        if isinstance(bs, dict):
            lp = bs.get("last_cis_push", {})
            age = lp.get("age_seconds")
            fresh = isinstance(age, (int, float)) and age < 3 * 3600
            out.append(StageHealth("store/hot (Mac Mini → Redis push)",
                                   "flowing" if fresh else "stale",
                                   f"last push age={age}s, assets={lp.get('asset_count')}, sha={bs.get('git_sha_short')}"))
        else:
            out.append(StageHealth("store/hot (Mac Mini → Redis push)", "broken", str(bs)[:80]))

        # ── DATA COMPLETENESS: are the PILLARS actually populated? ──────────
        # The gap that hid the 2026-07-19 T1 stall for 4 days: the T2 fallback keeps writing rows
        # (so universe size / push-freshness stay green) but T2 NEVER writes pillar_f/m/o/s/a — they
        # land NULL. A liveness check ("rows flowing") cannot see this; only a completeness check can.
        # Anything pillar-dependent (v5, asset-vector risk moments, edge_map) is silently dead while
        # this is broken. Also surfaces the data_tier so a T1→T2 fallback is visible, not masked.
        def _pillar_val(a):
            if not isinstance(a, dict):
                return None
            v = a.get("pillar_o")
            if v is None:
                v = (a.get("pillars") or {}).get("O")
            if v is None:
                v = a.get("o")
            return v
        n_pillar = sum(1 for a in universe if _pillar_val(a) is not None)
        tiers = {str(a.get("data_tier")) for a in universe if isinstance(a, dict)}
        out.append(StageHealth(
            "data completeness (pillars populated)",
            "flowing" if (n and n_pillar >= 0.5 * n) else ("broken" if n else "stale"),
            f"{n_pillar}/{n} assets have non-null pillar_O (null ⇒ T1 engine stalled / T2 fallback); "
            f"data_tier={sorted(tiers)}"))

        # causes attached? (fwd-supply / positioning are NESTED blocks, not flat fields)
        def _has(a, block, inner):
            b = a.get(block) if isinstance(a, dict) else None
            return isinstance(b, dict) and b.get(inner) is not None
        fs = sum(1 for a in universe if _has(a, "forward_supply", "forward_supply_risk"))
        pos = sum(1 for a in universe if _has(a, "positioning", "positioning_pressure"))
        out.append(StageHealth("compute/store (upstream causes)",
                               "flowing" if (fs or pos) else "broken",
                               f"forward_supply on {fs}/{n}, positioning on {pos}/{n} assets"))

        # ── MEASURE + FEED BACK: track record → conviction weights ──────────
        sc, rm = await _get(c, f"{base}/api/v1/portfolio/risk-meter")
        cf = rm.get("conviction_factors") if isinstance(rm, dict) else None
        if isinstance(cf, dict) and any(v not in (None,) for v in cf.values()):
            spread = max(cf.values()) - min(cf.values()) if cf else 0
            out.append(StageHealth("measure→feedback (outcomes → conviction)",
                                   "flowing" if spread > 0 else "stale",
                                   f"conviction_factors={cf}"))
        else:
            out.append(StageHealth("measure→feedback (outcomes → conviction)", "broken",
                                   "no conviction_factors — track record not feeding back"))

        # ── COMPUTE (narrative): NMA differentiated (not flat-neutral) ──────
        syms = ["BTC", "ETH", "SOL"]
        sc, nb = await _get(c, f"{base}/api/v1/market/narrative", params={"symbols": ",".join(syms)})
        if isinstance(nb, dict) and nb:
            scores = [v.get("nma_score") for v in nb.values() if isinstance(v, dict)]
            scores = [s for s in scores if isinstance(s, (int, float))]
            diff = (max(scores) - min(scores)) if len(scores) > 1 else 0
            out.append(StageHealth("compute (narrative / NMA)",
                                   "flowing" if diff > 1.0 else "stale",
                                   f"nma spread={round(diff,1)} across {syms} (flat⇒degraded sources)"))
        else:
            out.append(StageHealth("compute (narrative / NMA)", "broken", str(nb)[:80]))

    statuses = [s.status for s in out]
    overall = "broken" if "broken" in statuses else ("stale" if "stale" in statuses else "flowing")
    return {"overall": overall, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base": base, "stages": [asdict(s) for s in out]}


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    res = asyncio.run(check_loop_health(base))
    print(f"\nLOOP HEALTH — {res['overall'].upper()}  ({res['base']}, {res['checked_at']})\n")
    for s in res["stages"]:
        mark = {"flowing": "✅", "stale": "🟡", "broken": "🔴"}.get(s["status"], "?")
        print(f"  {mark} {s['stage']:<42} {s['status']:<8} — {s['detail']}")
    print()
