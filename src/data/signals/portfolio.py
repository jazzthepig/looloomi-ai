"""
Portfolio — the assimilated top-level view of the whole book (Seth 2026-07-15).
================================================================================

We built a sprawl of live paper books that overlap (causal positioning ⊂ combined factor nucleus
⊂ scalable FACTOR+TREND+CARRY) plus a separate RWA candidate. This assimilates them into ONE
coherent hierarchy so there's a single answer to "what is the book":

  CORE (deployable)      = scalable_book — vol-targeted FACTOR + TREND + CARRY on liquid majors.
                           This IS the multi-strategy book; it already composes the factor sleeve.
  COMPONENTS (transparency, NOT separately allocated — they live inside CORE):
                           causal_paper (positioning) · combined_book (factor ensemble).
  CANDIDATES (orthogonal, accruing, not yet in CORE):
                           dingge_paper (RWA 顶格) — the multi-asset/industry extension.

Meta-allocation is risk-parity across the *non-overlapping* deployable + candidate books; it fills
in as live history accrues. Read-only composition over the NAV tables — no new marking.
"""
from __future__ import annotations

import os

import numpy as np


async def _curve(table: str) -> list:
    import httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return []
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(f"{url}/rest/v1/{table}",
                            params={"select": "mark_date,nav,daily_return", "order": "mark_date.asc", "limit": "400"},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def _stats(rows: list) -> dict:
    if not rows:
        return {"status": "not_yet_marked", "days": 0}
    navs = [x["nav"] for x in rows if x.get("nav") is not None]
    rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    sr = (float(np.mean(rets) / np.std(rets) * np.sqrt(365)) if len(rets) > 5 and np.std(rets) > 0 else None)
    return {"status": "accruing" if len(rows) < 60 else "live",
            "days": len(rows), "nav": round(navs[-1], 4) if navs else None,
            "return_pct": round((navs[-1] - 1) * 100, 2) if navs else None,
            "ann_sharpe_live": round(sr, 2) if sr else None}


async def get_portfolio() -> dict:
    core = await _curve("scalable_book_nav")
    combined = await _curve("combined_book_nav")
    causal = await _curve("causal_paper_nav")
    dingge = await _curve("dingge_paper_nav")

    # meta risk-parity across non-overlapping deployable+candidate books (CORE + CANDIDATE)
    meta = None
    books = {"scalable_core": core, "rwa_dingge": dingge}
    series = {}
    for name, rows in books.items():
        r = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
        if len(r) > 20:
            series[name] = np.array(r)
    if len(series) >= 2:
        n = min(len(s) for s in series.values())
        M = np.array([s[-n:] for s in series.values()]).T
        iv = 1.0 / np.where(M.std(0) > 0, M.std(0), 1e18); w = iv / iv.sum()
        port = M @ w
        meta = {"weights": {k: round(float(wi), 3) for k, wi in zip(series, w)},
                "ann_sharpe_live": round(float(port.mean() / port.std() * np.sqrt(365)), 2) if port.std() > 0 else None,
                "days": int(n)}

    return {
        "as_of": __import__("datetime").datetime.utcnow().isoformat(),
        "hierarchy": {
            "core_deployable": {
                "book": "scalable_book", "sleeves": ["FACTOR", "TREND", "CARRY"],
                "construction": "risk-parity blend, vol-targeted to 10% ann, liquid crypto majors",
                "backtest_ref": {"combined_voltargeted_sharpe": 1.0, "note": "candidate; TREND is the capacity engine, regime-dependent"},
                "live": _stats(core),
            },
            "components_inside_core": {
                "note": "shown for transparency; NOT separately allocated — they live inside CORE's FACTOR sleeve",
                "combined_book_factor_ensemble": _stats(combined),
                "causal_positioning": _stats(causal),
            },
            "candidates_orthogonal": {
                "rwa_dingge": {**_stats(dingge),
                               "note": "funding-cap RWA + the multi-asset/industry (equity/commodity/sector-ETF) extension; validation-gated, not yet in CORE"},
            },
        },
        "meta_allocation": meta or {"status": "accruing — needs ≥20d live on ≥2 books before risk-parity is meaningful"},
        "breadth": {"classes_tracked": ["crypto", "tokenized_equity", "commodity", "sector_thematic_ETF"],
                    "effective_bets_ENB": 3.87, "note": "diversification lives across asset classes (rotation study R20); all tradeable 24/7 on-chain"},
        "discipline": "every sleeve gated by DSR + PBO + walk-forward + champion/challenger; refutations in REFUTATION_LEDGER (R1–R20)",
    }
