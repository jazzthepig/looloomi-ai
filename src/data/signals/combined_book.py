"""
Combined Book — the live NAV of the factory's walk-forward-validated nucleus (Seth 2026-07-15).
================================================================================================

Stage 3 of the loop-as-factory plan: fold the orthogonal, walk-forward-robust signals the
factory shortlisted into ONE market-neutral live paper book, marked daily, honest on funding +
cost. Not per-signal toys — a single NAV curve that IS the ensemble. Success = this curve
tracking the backtested aggregate (combined Sharpe ~1.56, ENB ~3.7) forward.

The NUCLEUS + blend weights come from the factory run (src/research/factory/signal_factory.py).
When the scheduled factory re-runs, it rewrites this config → the book self-recalibrates as
signals decay (Stage 4). Weights are the correlation-de-duplicated inverse-variance blend.

State → Redis `combined_book:state`; NAV curve → Supabase `combined_book_nav`.
Reuses the factory signal library + causal panel loader. Pure numpy + project helpers.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

_log = logging.getLogger("combined_book")
_STATE_KEY = "combined_book:state"
_FEE = 0.0005
_REBAL_DAYS = 7

# ── Deployed nucleus (from signal_factory batch, 2026-07-15) ────────────────────
# 4 walk-forward-robust, mutually-orthogonal signals; blend = combiner inverse-variance weights.
NUCLEUS = {
    "positioning_funding":  0.3974,
    "low_downside_vol_30":  0.1458,
    "momentum_120d":        0.1415,
    "neg_skew_pref_60":     0.3153,
}


_NUCLEUS_KEY = "combined_book:nucleus"


async def _live_nucleus() -> dict:
    """Prefer the nucleus the scheduled factory last wrote to Redis (Stage 4 self-recalibration);
    fall back to the deployed constant. This is how the book decays-out dead signals without a
    code change."""
    try:
        from src.data.market.data_layer import _redis_get
        n = await _redis_get(_NUCLEUS_KEY)
        if isinstance(n, dict) and n:
            return n
    except Exception:
        pass
    return NUCLEUS


def _combined_target(close, ret, fmean, fsum, nucleus: dict) -> dict[str, float]:
    """Today's combined market-neutral weights = blend of the nucleus signals' current
    weight vectors, renormalised to gross Σ|w|=1. Returns {SYMBOL: weight}."""
    from src.research.factory.signal_factory import signal_library
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    lib = signal_library(close, ret, fmean, fsum)
    K = close.shape[1]
    blended = np.zeros(K)
    for name, bw in nucleus.items():
        W = lib.get(name)
        if W is None:
            continue
        row = np.nan_to_num(W[-1])
        blended += bw * row
    g = np.abs(blended).sum()
    if g <= 0:
        return {}
    blended = blended / g
    return {DEFAULT_UNIVERSE[i]: float(blended[i]) for i in range(K) if abs(blended[i]) > 1e-4}


async def _load_live_panel():
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
    start = (dt.date.today() - dt.timedelta(days=300))
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=(start.year, start.month, start.day))
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    last_px = {DEFAULT_UNIVERSE[i]: float(close[-1, i]) for i in range(close.shape[1])}
    last_fund = {DEFAULT_UNIVERSE[i]: float(fmean[-1, i]) for i in range(close.shape[1])}
    return close, ret, fmean, fsum, last_px, last_fund


async def mark_and_rebalance(dry_run: bool = False) -> dict:
    """Daily mark of the combined book; weekly rebalance. Idempotent per day."""
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()
    try:
        close, ret, fmean, fsum, px, fund = await _load_live_panel()
    except Exception as e:
        return {"status": "error", "reason": str(e)[:120]}
    if len(px) < 5:
        return {"status": "skipped", "reason": "insufficient_live_data"}

    nucleus = await _live_nucleus()
    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or not state.get("weights"):
        w = _combined_target(close, ret, fmean, fsum, nucleus)
        state = {"inception": today.isoformat(), "nav": 1.0, "weights": w,
                 "mark_prices": {s: px[s] for s in w if s in px},
                 "last_rebal": today.isoformat(), "last_mark": today.isoformat()}
        if not dry_run:
            await _redis_set(_STATE_KEY, state, ttl=0)
            await _write_nav(today, 1.0, 0.0, sum(abs(x) for x in w.values()), len(w), 0.0, 0.0, 0.0, True, w)
        return {"status": "inception", "nav": 1.0, "n": len(w), "date": today.isoformat()}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    w = state["weights"]; mp = state["mark_prices"]
    price_pnl = funding_pnl = 0.0
    for s, wi in w.items():
        if s in px and s in mp and mp[s] > 0:
            price_pnl += wi * (px[s] / mp[s] - 1.0)
        fr = fund.get(s, 0.0) * 3          # ~daily funding (3× 8h)
        funding_pnl += -wi * fr
    daily_ret = price_pnl + funding_pnl
    nav = state["nav"] * (1.0 + daily_ret)

    last_rebal = dt.date.fromisoformat(state["last_rebal"])
    cost = 0.0; rebalanced = False; new_w = w
    if (today - last_rebal).days >= _REBAL_DAYS:
        tgt = _combined_target(close, ret, fmean, fsum, nucleus)
        if tgt:
            turn = sum(abs(tgt.get(s, 0) - w.get(s, 0)) for s in set(tgt) | set(w))
            cost = _FEE * turn
            nav *= (1.0 - cost)
            new_w = tgt; rebalanced = True

    state = {**state, "nav": nav, "weights": new_w,
             "mark_prices": {s: px[s] for s in new_w if s in px},
             "last_rebal": today.isoformat() if rebalanced else state["last_rebal"],
             "last_mark": today.isoformat()}
    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        await _write_nav(today, nav, daily_ret, sum(abs(x) for x in new_w.values()),
                         len(new_w), funding_pnl, price_pnl, cost, rebalanced, new_w)
    return {"status": "marked", "nav": round(nav, 5), "daily_return_pct": round(daily_ret * 100, 3),
            "rebalanced": rebalanced, "n": len(new_w), "date": today.isoformat()}


async def _write_nav(d, nav, dret, gross, n, fpnl, ppnl, cost, rebal, weights):
    from src.api.store import supabase_insert_table
    longs = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])[:3])
    shorts = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: kv[1])[:3])
    try:
        await supabase_insert_table("combined_book_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6), "daily_return": round(dret, 6),
            "gross": round(gross, 4), "n_positions": n, "funding_pnl": round(fpnl, 6),
            "price_pnl": round(ppnl, 6), "cost": round(cost, 6), "rebalanced": rebal,
            "nucleus": NUCLEUS, "top_longs": longs, "top_shorts": shorts}])
    except Exception as e:
        _log.warning("[combined_book] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/combined_book_nav",
                            params={"select": "mark_date,nav,daily_return,rebalanced,top_longs,top_shorts",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data", "note": "combined book not yet marked"}
    navs = [x["nav"] for x in rows]
    rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365)) if len(rets) > 5 and np.std(rets) > 0 else None)
    peak = np.maximum.accumulate(navs); dd = float((peak - navs).max() / peak.max()) if navs else 0
    # honest backtest ref — prefer the weekly-recomputed OOS numbers from the factory (Redis);
    # fall back to the last measured values. OOS (blend fit on train) is the honest expectation.
    ref = {"oos_combined_sharpe": 1.05, "in_sample_sharpe": 1.56, "enb": 3.68, "oos_days": 296}
    try:
        from src.data.market.data_layer import _redis_get
        live_ref = await _redis_get("combined_book:refs")
        if isinstance(live_ref, dict) and live_ref.get("oos_combined_sharpe") is not None:
            ref = live_ref
    except Exception:
        pass
    ref["note"] = "OOS (blend fit on train only) is the honest expectation; in-sample inflates"
    # ── tracking monitor (跟踪): is the LIVE book tracking its OOS expectation? ──
    exp = ref.get("oos_combined_sharpe")
    drift = None
    if sharpe is not None and exp is not None and len(rets) >= 20:
        gap = sharpe - exp
        drift = {"live_ann_sharpe": round(sharpe, 2), "expected_oos_sharpe": exp,
                 "gap": round(gap, 2), "n_days": len(rets),
                 "status": ("on_track" if gap >= -0.75 else "DRIFT — live materially below OOS expectation, investigate")}
    return {"status": "ok", "nucleus": NUCLEUS, "backtest_ref": ref,
            "pbo": ref.get("pbo"), "tracking": drift or {"status": "warming_up", "n_days": len(rets)},
            "days": len(rows), "inception": rows[0]["mark_date"], "nav": navs[-1],
            "return_pct": round((navs[-1] - 1) * 100, 2), "ann_sharpe_live": round(sharpe, 2) if sharpe else None,
            "max_dd_pct": round(dd * 100, 2), "latest": rows[-1], "curve": rows}


if __name__ == "__main__":
    import asyncio, json
    print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=True)), indent=2))
