"""
Scalable Book — live NAV of the profit-max, high-capacity multi-strategy book (Seth 2026-07-15).
==================================================================================================

The strategy a quant runs for "收益最大化 with capacity": a diversified book of three orthogonal,
scalable sleeves on the DEEPEST instruments (crypto majors), vol-targeted:
  · FACTOR — market-neutral cross-sectional (funding-crowd + extracted value/mom/vol)
  · TREND  — multi-horizon time-series momentum (the CTA engine; scales to size, no crowding)
  · CARRY  — funding carry (receive on the crowded side), market-neutral
Equal-gross blend of the three (each sleeve gross ~1/3), marked daily (price + funding), weekly
rebalance. Research: sleeves mutually corr 0.1–0.2; combined vol-targeted ~1.0 Sharpe; TREND is
the capacity engine. This is a CANDIDATE accruing a live track record — not yet validated.

State → Redis `scalable_book:state`; NAV → Supabase `scalable_book_nav`. Reuses the panel loader
+ signal_factory sleeves. Pure numpy + project helpers.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

_log = logging.getLogger("scalable_book")
_STATE_KEY = "scalable_book:state"
_FEE = 0.0005
_REBAL_DAYS = 7
_TREND_H = (20, 60, 120, 250)


def _norm(w):
    g = np.abs(w).sum()
    return w / g if g > 0 else w


def _factor_w(close, ret, fmean, fsum) -> np.ndarray:
    """Today's market-neutral cross-sectional weights (inverse-var blend of the validated sleeves)."""
    from src.research.factory.signal_factory import signal_library, _bt
    lib = signal_library(close, ret, fmean, fsum)
    keep = [k for k in ("positioning_funding", "momentum_extracted", "lowvol_extracted",
                        "neg_skew_extracted", "downside_vol_extracted") if k in lib]
    pnls = np.array([_bt(lib[k], ret, fsum)[180:] for k in keep]).T
    v = pnls.var(0); v[v == 0] = 1e18
    bw = (1 / v) / (1 / v).sum()
    W = np.sum([bw[i] * lib[keep[i]][-1] for i in range(len(keep))], axis=0)
    return _norm(np.nan_to_num(W))


def _trend_w(close, ret) -> np.ndarray:
    """Today's multi-horizon TSMOM weights: consensus sign across horizons × inverse-vol, unit gross."""
    T, K = close.shape
    vol = ret[-30:].std(0)
    sig = np.mean([np.sign(np.nan_to_num(close[-1] / close[-h - 1] - 1.0)) for h in _TREND_H if T > h], axis=0)
    iv = np.where(vol > 0, 1.0 / vol, 0.0)
    return _norm(np.nan_to_num(sig * iv))


def _carry_w(fmean) -> np.ndarray:
    """Today's funding-carry weights: short high-funding, long low/negative, market-neutral."""
    f = np.nan_to_num(fmean[-1])
    return _norm(-(f - f.mean()))


TARGET_VOL_ANN = 0.10
_MAX_LEV = 3.0


def _shrink_cov(X: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf-style shrinkage toward a constant-correlation target. A 60-obs sample cov over
    many assets is noisy/ill-conditioned → the raw vol-target mis-estimates risk. Shrinking the
    off-diagonals toward a common correlation stabilises w'Σw (institutional standard). Shrinkage
    intensity grows when obs are scarce relative to dimension (δ ≈ K/n)."""
    X = np.nan_to_num(X)
    n, K = X.shape
    S = np.cov(X.T)
    if K < 2 or n < 3:
        return S
    var = np.clip(np.diag(S), 1e-12, None); std = np.sqrt(var)
    R = S / np.outer(std, std)
    rbar = (R.sum() - K) / (K * (K - 1))          # average pairwise correlation
    F = rbar * np.outer(std, std)                 # constant-correlation target
    np.fill_diagonal(F, var)
    delta = float(min(0.8, max(0.1, K / n)))      # more shrinkage when sample is thin vs dimension
    return (1 - delta) * S + delta * F


def _target(close, ret, fmean, fsum) -> dict:
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    wf, wt, wc = _factor_w(close, ret, fmean, fsum), _trend_w(close, ret), _carry_w(fmean)
    blended = (wf + wt + wc) / 3.0        # equal-gross risk-parity across the 3 sleeves
    # ── genuine VOL-TARGET on a SHRUNK covariance (constant risk = the CTA construction; shrinkage
    # keeps the risk estimate honest on a short 60-obs window) ──
    cov = _shrink_cov(ret[-60:])
    port_var = float(blended @ cov @ blended)
    tgt_daily = TARGET_VOL_ANN / np.sqrt(365)
    if port_var > 0:
        scale = min(tgt_daily / np.sqrt(port_var), _MAX_LEV)
        blended = blended * scale
    K = close.shape[1]
    return {DEFAULT_UNIVERSE[i]: float(blended[i]) for i in range(K) if abs(blended[i]) > 1e-4}


async def _load_panel():
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
    s = dt.date.today() - dt.timedelta(days=320)
    _, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=(s.year, s.month, s.day))
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    px = {DEFAULT_UNIVERSE[i]: float(close[-1, i]) for i in range(close.shape[1])}
    fund = {DEFAULT_UNIVERSE[i]: float(fmean[-1, i]) for i in range(close.shape[1])}
    return close, ret, fmean, fsum, px, fund


async def mark_and_rebalance(dry_run: bool = False) -> dict:
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()
    try:
        close, ret, fmean, fsum, px, fund = await _load_panel()
    except Exception as e:
        return {"status": "error", "reason": str(e)[:120]}
    if len(px) < 5:
        return {"status": "skipped", "reason": "insufficient_live_data"}

    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or not state.get("weights"):
        w = _target(close, ret, fmean, fsum)
        state = {"inception": today.isoformat(), "nav": 1.0, "weights": w,
                 "mark_prices": {s: px[s] for s in w if s in px},
                 "last_rebal": today.isoformat(), "last_mark": today.isoformat()}
        if not dry_run:
            await _redis_set(_STATE_KEY, state, ttl=0)
            await _write(today, 1.0, 0.0, 0.0, 0.0, len(w), True, w)
        return {"status": "inception", "nav": 1.0, "n": len(w), "date": today.isoformat()}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    w, mp = state["weights"], state["mark_prices"]
    price_pnl = funding_pnl = 0.0
    for s, wi in w.items():
        if s in px and s in mp and mp[s] > 0:
            price_pnl += wi * (px[s] / mp[s] - 1.0)
        funding_pnl += -wi * fund.get(s, 0.0) * 3
    dret = price_pnl + funding_pnl
    nav = state["nav"] * (1.0 + dret)

    last_rebal = dt.date.fromisoformat(state["last_rebal"])
    rebalanced = False; new_w = w
    if (today - last_rebal).days >= _REBAL_DAYS:
        tgt = _target(close, ret, fmean, fsum)
        if tgt:
            turn = sum(abs(tgt.get(s, 0) - w.get(s, 0)) for s in set(tgt) | set(w))
            nav *= (1.0 - _FEE * turn); new_w = tgt; rebalanced = True

    state = {**state, "nav": nav, "weights": new_w,
             "mark_prices": {s: px[s] for s in new_w if s in px},
             "last_rebal": today.isoformat() if rebalanced else state["last_rebal"],
             "last_mark": today.isoformat()}
    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        await _write(today, nav, dret, price_pnl, funding_pnl, len(new_w), rebalanced, new_w)
    return {"status": "marked", "nav": round(nav, 5), "daily_return_pct": round(dret * 100, 3),
            "rebalanced": rebalanced, "n": len(new_w), "date": today.isoformat()}


async def _write(d, nav, dret, ppnl, fpnl, n, rebal, weights):
    from src.api.store import supabase_insert_table
    longs = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])[:3])
    shorts = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: kv[1])[:3])
    try:
        await supabase_insert_table("scalable_book_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6), "daily_return": round(dret, 6),
            "gross": round(sum(abs(x) for x in weights.values()), 4), "n_positions": n,
            "price_pnl": round(ppnl, 6), "funding_pnl": round(fpnl, 6), "rebalanced": rebal,
            "sleeves": ["FACTOR", "TREND", "CARRY"], "top_longs": longs, "top_shorts": shorts}])
    except Exception as e:
        _log.warning("[scalable_book] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/scalable_book_nav",
                            params={"select": "mark_date,nav,daily_return,rebalanced,top_longs,top_shorts",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data", "note": "scalable book not yet marked"}
    navs = [x["nav"] for x in rows]
    rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365)) if len(rets) > 5 and np.std(rets) > 0 else None)
    return {"status": "ok", "sleeves": ["FACTOR", "TREND", "CARRY"],
            "validation": "candidate — accruing, capacity-honest (liquid majors)",
            "days": len(rows), "inception": rows[0]["mark_date"], "nav": navs[-1],
            "return_pct": round((navs[-1] - 1) * 100, 2), "ann_sharpe_live": round(sharpe, 2) if sharpe else None,
            "latest": rows[-1], "curve": rows}


if __name__ == "__main__":
    import asyncio, json
    print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=True)), indent=2))
