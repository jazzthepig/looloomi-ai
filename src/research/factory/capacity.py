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


def capacity(weights: dict, participation: float = PARTICIPATION) -> dict:
    """weights: {SYMBOL: signed weight}. Returns book capacity ($ AUM) + binding names + ADV table."""
    rows = []
    for s, w in weights.items():
        if abs(w) < 1e-4:
            continue
        adv = _adv_usd(s)
        if adv <= 0:
            continue
        cap = participation * adv * REBAL_TRADE_DAYS / abs(w)     # $ AUM this position can support
        rows.append({"symbol": s, "weight": round(w, 3), "adv_usd_m": round(adv / 1e6, 1),
                     "capacity_usd_m": round(cap / 1e6, 1)})
    if not rows:
        return {"status": "no_liquidity_data"}
    rows.sort(key=lambda r: r["capacity_usd_m"])
    book_cap = rows[0]["capacity_usd_m"]
    return {"book_capacity_usd_m": book_cap,
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
