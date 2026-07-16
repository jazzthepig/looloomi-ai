"""
顶格 RWA Strategy Study — the TRADEABLE version (Seth 2026-07-15).
==================================================================

Jazz's thesis: on tokenized-RWA perps, when funding pins at the cap (顶格, ~500-1000%+
annualized) the old trend exhausts and a NEW trend forms — direction set by 量能 (VOLUME),
not price momentum; bidirectional (crowded-longs can flush OR continue; crowded-shorts squeeze).

The prior backtest measured whether volume *correlates* with the new-trend sign — but its
"gated_strat" peeked at the realized trend to pick direction (not tradeable). This builds the
REAL rule: a direction decided AT ENTRY from side + volume, then the realized in-position return.

Entry: ~15d after a 顶格 event (let the old trend reset + read the volume). Direction rule
(known at entry):
  · short_crowded (−cap): LONG (squeeze up) unless volume is dead (<0.9×)
  · long_crowded  (+cap): LONG if volume expands (>1.1×); SHORT if volume dead (<0.9×); else skip
Hold +15d → +35d (the "new trend" window). Return booked in the position's direction.
IS/OOS split 60/40 chronological. Small-n by nature (young instrument class) — honest verdict only.

Data: Binance fapi funding + daily klines (same as the live board). Pure numpy.
"""
from __future__ import annotations

import datetime as dt
import numpy as np

from src.data.signals.dingge_rwa import RWA_PERPS, _client, _funding, _klv, _episodes

VOL_UP, VOL_DEAD = 1.10, 0.90
ENTRY_LAG, EXIT = 15, 35     # enter +15d after event, exit +35d


def _direction(side: int, vol_ratio: float) -> int:
    """Position direction known AT ENTRY. +1 long / -1 short / 0 skip."""
    if side < 0:                                  # crowded shorts → squeeze up
        return +1 if vol_ratio >= VOL_DEAD else 0
    # crowded longs → volume confirms continuation up, dead volume = flush down
    if vol_ratio > VOL_UP:
        return +1
    if vol_ratio < VOL_DEAD:
        return -1
    return 0


import datetime as _dt
COST_RT = 0.0030   # 30bps round-trip slippage/fee on these less-liquid RWA perps


def _funding_carry(fu, entry_date, exit_date, direction) -> float:
    """Net funding P&L over the hold. Perp: funding>0 → longs PAY shorts. A position's
    per-interval funding = −direction × rate. Sum over [entry,exit). THIS is the piece a
    price-only mark hides — decisive on 顶格 instruments where |rate| sits near the cap."""
    tot = 0.0
    for ts_ms, rate in fu:
        d = _dt.date.fromtimestamp(ts_ms / 1000)
        if entry_date <= d < exit_date:
            tot += rate
    return -direction * tot


def run() -> dict:
    trades = []
    with _client() as client:
        for s in RWA_PERPS:
            try:
                fu = _funding(client, s); K = _klv(client, s)
            except Exception:
                continue
            if not fu or not K:
                continue
            kd = sorted(K)
            for d, side in _episodes(fu):
                pre = [x for x in kd if x < d]
                fut = [x for x in kd if x >= d]
                if len(pre) < 15 or len(fut) < EXIT + 1:
                    continue
                volpre = np.mean([K[x][1] for x in pre[-15:]])
                volpost = np.mean([K[x][1] for x in fut[1:ENTRY_LAG + 1]])
                if volpre <= 0:
                    continue
                vr = volpost / volpre
                direction = _direction(side, vr)
                if direction == 0:
                    continue
                p_in = K[fut[ENTRY_LAG]][0]; p_out = K[fut[EXIT]][0]
                if not (p_in and p_out and p_in > 0):
                    continue
                gross = (p_out / p_in - 1.0) * direction
                entry_date, exit_date = fut[ENTRY_LAG], fut[EXIT]
                carry = _funding_carry(fu, entry_date, exit_date, direction)
                net = gross + carry - COST_RT
                trades.append({"sym": s, "date": d, "side": side, "vol_ratio": round(vr, 2),
                               "dir": direction,
                               "gross_pct": round(gross * 100, 2),
                               "funding_pct": round(carry * 100, 2),
                               "ret_pct": round(net * 100, 2)})
    trades.sort(key=lambda t: t["date"])
    n = len(trades)
    if n < 6:
        return {"n": n, "status": "insufficient_trades", "trades": trades}

    def _stat(sample, key="ret_pct"):
        r = np.array([t[key] for t in sample])
        return {"n": len(sample), "mean_pct": round(float(r.mean()), 2),
                "median_pct": round(float(np.median(r)), 2),
                "win_pct": round(float((r > 0).mean() * 100), 0),
                "sharpe_per_trade": round(float(r.mean() / r.std()), 2) if r.std() > 0 else None}

    sp = int(n * 0.6)
    return {"n": n,
            "gross_all": _stat(trades, "gross_pct"),
            "funding_all": _stat(trades, "funding_pct"),
            "net_all": _stat(trades), "net_IS": _stat(trades[:sp]), "net_OOS": _stat(trades[sp:]),
            "n_long": sum(1 for t in trades if t["dir"] > 0),
            "n_short": sum(1 for t in trades if t["dir"] < 0),
            "trades": trades}


if __name__ == "__main__":
    import json
    res = run()
    print(f"\n=== 顶格 TRADEABLE STRATEGY (entry-time direction rule) ===")
    if res.get("status"):
        print(res["status"], "n=", res["n"])
        for t in res.get("trades", []):
            print("  ", t)
    else:
        print(f"n={res['n']}  (long {res['n_long']} / short {res['n_short']})")
        for k in ("gross_all", "funding_all", "net_all", "net_IS", "net_OOS"):
            s = res[k]
            print(f"  {k:12}: n={s['n']:>3}  mean={s['mean_pct']:>7}%  median={s['median_pct']:>7}%  "
                  f"win={s['win_pct']}%  sharpe/trade={s['sharpe_per_trade']}")
        print("\n  sample trades (gross → funding → net):")
        for t in res["trades"][:16]:
            print(f"    {t['date']} {t['sym']:11} side={t['side']:+d} dir={t['dir']:+d} "
                  f"gross={t['gross_pct']:+6.1f}%  fund={t['funding_pct']:+6.1f}%  net={t['ret_pct']:+6.1f}%")
