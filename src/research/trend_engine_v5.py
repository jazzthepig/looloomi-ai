"""
Trend Engine V5 — the honest successor to CometCloudLongShortV4 (Seth, 2026-07-20).
====================================================================================
Refutation Ledger R40. Re-validated LS V4 (EMA9/21 4h stop-and-reverse, the freqtrade/Nautilus
parity strategy) with the FULL gauntlet on 3.5y of 4h data (BTC/ETH/SOL, net 5bps):

  RE-VALIDATION VERDICT — LS V4 as an ALPHA source is REFUTED:
    · annSR +0.18 single / +0.08 pooled — indistinguishable from zero
    · absorption: momentum beta t=9→24, residual α NEGATIVE — the entire return stream is
      TSMOM wearing an EMA-cross costume (the 2026-06 "beat BTC-hold by 11.6pp in a bear" was
      just the short side of trend beta in a downtrend, not alpha)
    · 95–105 flips/yr ≈ 9.5%/yr cost drag — massive churn for the SAME momentum exposure
    · decaying: H1 SR +1.01 → H2 SR −0.79

  DEVELOPMENT — same trend exposure, EFFICIENT construction (this module):
    slow the signal down; churn was the killer, not the trend premise.
      V4  EMA9/21 4h flip   : pooled SR +0.08,  ~100 flips/yr    (the baseline, refuted)
      V5a EMA54/126 flip    : pooled SR +0.52,  ~15 flips/yr     (13× less churn, better everywhere)
      V5c EMA54/126 LONG-only: pooled SR +0.96, ~8 flips/yr, positive BOTH halves (H1 +1.21 / H2 +0.67)
    V5c wins because crypto's trend premium is asymmetric — the long side carries the drift; the
    short side of a flip system mostly pays churn + funding for crash-catching optionality.

  HONEST LABEL: this is a MOMENTUM-BETA HARVESTING ENGINE, NOT alpha (residual α ≈ 0 by
  construction — it IS the momentum factor). That is exactly the "tactical trend-riding overlay"
  role of the two-layer doctrine (TRADER_TOM §5b: press the confirmed up-trend, defend otherwise).
  Size it as beta, never headline it as alpha. Caveats: FRAGILE per-quarter (trend engines lose in
  chop — expected); long-only worst bar ≈ −14σ (crash exposure — cap size / pair with the defensive
  layer); funding not modeled (long perps pay when crowded — validate live paper first).
"""
from __future__ import annotations

import numpy as np


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def trend_v5(price: np.ndarray, fast: int = 54, slow: int = 126,
             long_only: bool = True, cost_bps: float = 5.0) -> dict:
    """V5 slow-trend engine on 4h closes (54/126 ≈ 9/21 daily). Returns {position, returns}.
    long_only=True is the validated default (V5c); False gives the symmetric flip (V5a)."""
    px = np.asarray(price, dtype=float)
    f, s = ema(px, fast), ema(px, slow)
    pos = np.sign(f - s) if not long_only else np.where(f > s, 1.0, 0.0)
    ret = np.zeros(len(px)); ret[1:] = px[1:] / px[:-1] - 1
    r = np.zeros(len(px)); r[1:] = pos[:-1] * ret[1:]
    turn = np.abs(np.diff(pos, prepend=0))
    r -= turn * cost_bps * 1e-4
    return {"position": pos, "returns": r, "asset_return": ret}


def trend_book(prices: dict, **kw) -> dict:
    """Equal-weight multi-asset V5 book: {symbol: 4h closes} → pooled daily-ish return stream.
    Diversification across assets is what smooths the per-asset chop (breadth doctrine)."""
    n = min(len(p) for p in prices.values())
    rs = [trend_v5(np.asarray(p)[-n:], **kw)["returns"] for p in prices.values()]
    return {"returns": np.mean(rs, axis=0), "n_assets": len(rs)}


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    n = 4000
    drift = np.concatenate([np.full(2000, 0.0004), np.full(2000, -0.0002)])   # up-trend then chop
    px = 100 * np.cumprod(1 + drift + rng.normal(0, 0.01, n))
    out = trend_v5(px)
    exposed = out["position"].mean()
    print(f"exposure {exposed:.2f} (long in up-trend, flat after) | ann-ish SR "
          f"{out['returns'].mean()/out['returns'].std()*np.sqrt(6*365):+.2f}")
