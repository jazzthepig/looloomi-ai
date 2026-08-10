"""
Capacity Analysis (Seth 2026-07-15) — how much AUM the book can actually run.
=============================================================================

Jazz: "容量不可以太小." Capacity is what turns Sharpe into real P&L — a great edge on an illiquid
instrument caps your fund size. This quantifies it: given each instrument's average daily volume
(ADV) and the book's target weights, at what AUM does the least-liquid position exceed a prudent
participation rate — and which names bind. Model: to build/exit a position without material impact,
trade ≤ PARTICIPATION of ADV over REBAL_TRADE_DAYS. Position notional = |weight| × AUM.
  capacity_per_name = PARTICIPATION × ADV × REBAL_TRADE_DAYS / |weight|
  book capacity     = min over held names.
Binance fapi daily quote-volume. Pure numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

_FAPI = "https://fapi.binance.com/fapi/v1/klines"
PARTICIPATION = 0.05        # ≤5% of daily volume (prudent, low-impact)
REBAL_TRADE_DAYS = 3        # spread a weekly rebalance over ~3 days


def _adv_usd(sym: str, days: int = 30) -> float:
    """Average daily USD volume (quote volume) over the last `days`."""
    try:
        u = f"{_FAPI}?symbol={sym}USDT&interval=1d&limit={days}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        qv = [float(k[7]) for k in r] if isinstance(r, list) else []
        return float(np.mean(qv)) if qv else 0.0
    except Exception:
        return 0.0


def capacity(weights: dict, participation: float = PARTICIPATION,
             adv_usd: dict | None = None) -> dict:
    """
    weights: {SYMBOL: signed weight}. Returns book capacity ($ AUM) + binding names + ADV table.

    adv_usd: optional {SYMBOL: adv} to inject. Supply it in any deployed path —
    `_adv_usd` calls Binance fapi directly, which is geo-blocked on Railway US and
    will return 0.0 for EVERY name there.

    UNPRICED NAMES ARE NOT SKIPPED (2026-08-10, S-132). The old loop did
    `if adv <= 0: continue`, which is the capacity version of a degraded value:
    book capacity is a MINIMUM over names, so dropping a name can only raise the
    answer — and the names whose volume lookup fails are disproportionately the
    thin ones that would have been binding. A book reporting $80m capacity because
    its two illiquid legs 404'd is worse than one reporting nothing. So: any
    unpriced name makes the number PARTIAL and says which names are missing; the
    caller decides, and `deployable_notional` refuses partials outright.
    """
    rows, unpriced = [], []
    for s, w in weights.items():
        if abs(w) < 1e-4:
            continue
        adv = float((adv_usd or {}).get(s, 0.0)) or _adv_usd(s)
        if adv <= 0:
            unpriced.append(s)
            continue
        cap = participation * adv * REBAL_TRADE_DAYS / abs(w)     # $ AUM this position can support
        rows.append({"symbol": s, "weight": round(w, 3), "adv_usd_m": round(adv / 1e6, 1),
                     "capacity_usd_m": round(cap / 1e6, 1)})
    if not rows:
        return {"status": "no_liquidity_data", "unpriced": unpriced}
    rows.sort(key=lambda r: r["capacity_usd_m"])
    book_cap = rows[0]["capacity_usd_m"]
    return {"book_capacity_usd_m": book_cap,
            "status": "partial" if unpriced else "complete",
            "unpriced": unpriced,
            "coverage_pct": round(100.0 * len(rows) / (len(rows) + len(unpriced)), 1),
            "participation_pct": participation * 100,
            "binding_names": [r["symbol"] for r in rows[:3]],
            "gross": round(sum(abs(r["weight"]) for r in rows), 2),
            "detail_least_liquid": rows[:6]}


if __name__ == "__main__":
    # representative scalable-book weights from the cached majors panel
    import numpy as np
    d = np.load("/tmp/panel12.npz"); close, fmean, fsum = d["close"], d["fmean"], d["fsum"]
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    import src.research.strategies.causal_positioning as cp
    cp.DEFAULT_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "ATOM"]
    from src.data.signals.scalable_paper import _target
    w = _target(close, ret, fmean, fsum)
    print(json.dumps(capacity(w), indent=2))
