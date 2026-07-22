"""
Funding-Crowding signal — volume-confirmed positioning reversal (Seth, 2026-07-18).
====================================================================================
The strongest candidate of the 07-18 session (Refutation Ledger R34→R35). Fade a funding-crowding
EXTREME only when price+volume confirm the reversal is underway — NOT a blind contrarian fade
(R34 showed blind fade is orthogonal-but-sub-threshold; blind-fading hard extremes goes negative
because after a real extreme a new trend forms — dingge doctrine).

Signal (per perp, daily):
  crowded longs  (funding z > thr) + price rolling over (3d ret < 0) + volume expanding → SHORT the flush
  crowded shorts (funding z < −thr) + price bouncing   (3d ret > 0) + volume expanding → LONG the squeeze
  else flat. Hold `hold` days.

Empirical (Binance funding+OHLCV):
  · BTC full sample: raw +29%/yr, α +28.9%/yr, α t=2.42, ROBUST — momentum beta ≈ 0 (ORTHOGONAL).
  · a-priori config OOS (≥2023): α +22%/yr persists (t≈1.5). Real + persistent, but single-asset thin.
  · pooled BTC/ETH/SOL: α +18%/yr but t=1.65 — crypto co-moves ~0.79, so pooling ≠ breadth (R35).

STATUS: 🟡 orthogonal + persistent, NOT yet credited. Credit path = CROSS-CLASS breadth — run this same
signal on the RWA/equity/commodity perps (`dingge_rwa.SECTOR_ETF_PERPS`, corr ~0.22 to BTC), market-neutral,
through `signal_gauntlet`. That's where real ENB (2.5→8+) and significance come from. Minimax data lane.
Compliance: positioning language only; a research candidate, not advice.
"""
from __future__ import annotations

import numpy as np


def crowding_signal(funding: np.ndarray, price: np.ndarray, volume: np.ndarray,
                    zwin: int = 30, thr: float = 1.0, hold: int = 10,
                    vol_mult: float = 1.10, cost_bps: float = 5.0) -> dict:
    """Daily arrays (aligned). Returns {position, returns} — volume-confirmed crowding reversal,
    net of turnover cost. Position ∈ {−1,0,+1}, held `hold` days. Reusable per perp for the
    cross-class basket."""
    n = len(price)
    ret = np.zeros(n); ret[1:] = price[1:] / price[:-1] - 1
    raw = np.zeros(n)
    for i in range(max(zwin, 20), n):
        w = funding[i - zwin:i]
        z = (funding[i] - w.mean()) / (w.std() + 1e-9)
        r3 = price[i] / price[i - 3] - 1
        vexp = volume[i] / (volume[i - 20:i].mean() + 1e-9) > vol_mult
        if z > thr and r3 < 0 and vexp:
            raw[i] = -1.0                     # crowded longs flushing → short
        elif z < -thr and r3 > 0 and vexp:
            raw[i] = +1.0                     # crowded shorts squeezing → long
    pos = np.zeros(n)
    for i in range(n):
        if raw[i] != 0:
            pos[i:i + hold] = raw[i]
    r = np.zeros(n); r[1:] = pos[:-1] * ret[1:]
    turn = np.abs(np.diff(pos, prepend=0))
    r -= turn * cost_bps * 1e-4
    return {"position": pos, "returns": r, "asset_return": ret}


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    n = 400
    px = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    fund = rng.normal(0, 0.0003, n)
    vol = np.abs(rng.normal(1e6, 3e5, n))
    out = crowding_signal(fund, px, vol)
    print("triggers:", int((np.abs(out["position"]) > 0).sum()), "/", n,
          "| ann return:", round(out["returns"].mean() * 365 * 100, 2), "%")
