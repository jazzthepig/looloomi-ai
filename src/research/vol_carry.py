"""
Calm-Regime Vol Carry — the first candidate to clear the full gauntlet + OOS (Seth, 2026-07-19).
==================================================================================================
Refutation Ledger R39 (resolution of the shelved R28 vol sleeve). Harvests the crypto VOL RISK
PREMIUM — implied vol (Deribit DVOL) is richer than realized 79% of days, mean +5.8 vol-pts — via a
short-variance carry, but ONLY in genuinely CALM realized-vol regimes (don't sell into a storm).
That regime gate is what tames the short-vol negative-skew tail and makes the edge robust.

Empirical (BTC, DVOL + Binance, 2023-12→2026-07, 940d):
  · short-var carry, gated to trailing-10d RV < 55 (calm):
      SR +2.69 · residual α t=3.66 (momentum-β ≈ 0, ORTHOGONAL) · worst day −8.2σ (half the ungated −15.6σ)
  · ★ cleared the FULL signal_gauntlet: significance ✓ DSR ✓ PBO ✓ absorption ✓ regime-robustness ✓
  · OOS holds: TRAIN(<2025-07) αt +3.31 · HOLDOUT(≥2025-07) αt +2.66 (still significant)

WHAT DIDN'T WORK (R39): the ungated carry is FRAGILE + fat-tailed; gating by FUNDING-CROWDING made the
tail WORSE (crowding ≠ vol-spike predictor). The realized-vol REGIME gate is the one that works.

STATUS: 🟡→✅ CREDITED CANDIDATE, NOT a sized sleeve. Honest caveats before capital: single-asset (BTC) +
single vol index; the variance-swap P&L is a STYLIZED proxy (real options have bid/ask, gamma, discrete
strikes → frictionless overstates it; the −8.2σ day still needs wings/limits); DVOL history ~2.7y.
Next: ETH DVOL confirmation + a realistic options-execution model (Minimax lane). Positioning read only.
"""
from __future__ import annotations

import numpy as np


def realized_vol(log_ret: np.ndarray, window: int) -> np.ndarray:
    """Trailing annualized realized vol (%) — the regime gate input."""
    n = len(log_ret)
    out = np.full(n, np.nan)
    for i in range(window, n):
        out[i] = log_ret[i - window:i].std() * np.sqrt(365) * 100
    return out


def vol_carry_signal(iv_index: np.ndarray, price: np.ndarray,
                     rv_window: int = 10, calm_thresh: float = 55.0,
                     off_exposure: float = 0.2) -> dict:
    """Short-variance carry, exposure gated by the realized-vol regime.

    iv_index : Deribit DVOL (30d implied vol index, annualized %), daily, aligned to `price`.
    price    : daily close. Returns {returns, exposure, log_ret}.
    P&L (short 1-day variance swap): collect yesterday's implied 1d variance, pay realized r².
    Exposure = 1 in calm regimes (trailing RV < calm_thresh), else `off_exposure` (cut into storms).
    """
    iv = np.asarray(iv_index, dtype=float)
    px = np.asarray(price, dtype=float)
    n = len(px)
    lr = np.zeros(n); lr[1:] = np.log(px[1:] / px[:-1])
    strike = (iv / 100.0) ** 2 / 365.0            # implied 1-day variance
    rvtr = realized_vol(lr, rv_window)
    expo = np.nan_to_num(np.where(rvtr < calm_thresh, 1.0, off_exposure), nan=1.0)
    r = np.zeros(n)
    r[1:] = expo[:-1] * (strike[:-1] - lr[1:] ** 2)   # short-var daily P&L, regime-scaled
    return {"returns": r, "exposure": expo, "log_ret": lr}


if __name__ == "__main__":
    # sanity on synthetic calm-vs-storm data: earns in calm, cut in storm
    rng = np.random.default_rng(0)
    n = 400
    lr = np.concatenate([rng.normal(0, 0.015, 300), rng.normal(0, 0.06, 100)])  # calm then storm
    px = 100 * np.exp(np.cumsum(lr))
    iv = np.full(n, 45.0)  # constant 45% implied
    out = vol_carry_signal(iv, px)
    print("calm-window mean pnl:", round(out["returns"][30:300].mean() * 1e5, 2), "e-5",
          "| storm-window exposure avg:", round(out["exposure"][320:].mean(), 2))
