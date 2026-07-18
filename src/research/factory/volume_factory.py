"""
Volume Factory — new mechanism family from A-S1 substrate (Minimax-A, 2026-07-17).

The cross-sectional funding axis is saturated (R8 / R25 / R26 / R27). This factory
opens a *different mechanism family* (volume + taker-buy imbalance) without
modifying the validated `causal_positioning.py` panel loader. It reads the A-S1
substrate (Binance USDT-M klines with volume + taker-buy columns) and reuses the
factory's _xs_weights / _bt / _walkforward / evaluate_universe / pbo / combine
machinery for the honest gate (DSR + walk-forward + orthogonality).

Honest scope: this is ONE experiment. The funding axis was saturated by reaching
for any transformation of the same series; this factory reads DIFFERENT columns
(volume_base, volume_quote, taker_buy_quote) that the funding factory never saw.
Volume captures realised demand; taker-buy imbalance captures WHO initiated the
trade (buy-side vs sell-side aggression); both are different causal channels than
perp-crowding funding.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

# Reuse the validated factory's helpers (DRY — single source of truth for the
# honest gate + weight construction). Don't ship parallel implementations.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.research.factory.signal_factory import (   # noqa: E402
    _xs_weights, _roll_ret, _roll_std, _bt, _walkforward,
)
from src.research.validation.deflated_sharpe import evaluate_universe  # noqa: E402

AS1_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive")
A_S1_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
FEE = 0.0005


def load_a_s1_panel(symbols: list[str] = A_S1_SYMBOLS) -> tuple:
    """Read A-S1 substrate → (days, close, volume_base, volume_quote, taker_buy_quote).

    All panels are T × K. Volume in base units (e.g. BTC for BTCUSDT); taker_buy_quote
    is the quote-volume of buy-side taker aggression. Aligned by date index.
    """
    by_sym = {}
    all_days = set()
    for sym in symbols:
        p = AS1_DIR / f"{sym}_1d_ohlcv.csv"
        if not p.exists():
            raise FileNotFoundError(f"A-S1 missing: {p}")
        with p.open() as f:
            r = csv.DictReader(f)
            day2row = {row["date"]: row for row in r}
        by_sym[sym] = day2row
        all_days.update(day2row.keys())
    days = sorted(all_days)
    di = {d: i for i, d in enumerate(days)}
    T, K = len(days), len(symbols)
    close = np.full((T, K), np.nan)
    vbase = np.full((T, K), np.nan)
    vquote = np.full((T, K), np.nan)
    taker_buy_quote = np.full((T, K), np.nan)
    for j, sym in enumerate(symbols):
        for d, row in by_sym[sym].items():
            i = di[d]
            close[i, j] = float(row["close"])
            vbase[i, j] = float(row["volume_base"])
            vquote[i, j] = float(row["volume_quote"])
            taker_buy_quote[i, j] = float(row["taker_buy_quote"])
    # forward-fill any NaN closes (asset was listed late / data gap)
    for j in range(K):
        for i in range(1, T):
            if np.isnan(close[i, j]):
                close[i, j] = close[i - 1, j]
    return days, close, vbase, vquote, taker_buy_quote


# ── Volume-derived signals (new mechanism family) ──────────────────────────

def _vol_normalised(vol: np.ndarray, k: int = 20) -> np.ndarray:
    """Cross-sectional z-score of vol / trailing-k-day mean vol per asset.
    Returns T×K z-score; positive = unusually high vol today vs its own recent norm."""
    T, K = vol.shape
    out = np.full((T, K), np.nan)
    for j in range(K):
        for i in range(k, T):
            base = vol[i - k:i, j].mean()
            if base > 0:
                out[i, j] = (vol[i, j] - base) / base
    return out


def volume_price_trend(close: np.ndarray, vol: np.ndarray, k: int = 20) -> np.ndarray:
    """Minimax-A — long real demand (close up on high vol), short real supply (close down on high vol).
    vol_score = vol_z (per-asset, recent-norm-relative); direction = sign of k-day return.
    score = sign(rk) * vol_z. Cross-sectional weight: long positive, short negative."""
    rk = _roll_ret(close, k)
    z = _vol_normalised(vol, k)
    score = np.sign(rk) * np.nan_to_num(z)             # amplify high-vol directional days
    return _xs_weights(score, sign=+1.0)


def taker_buy_imbalance(vquote: np.ndarray, taker_buy_quote: np.ndarray) -> np.ndarray:
    """Minimax-A — taker buy-side aggression. score = (taker_buy_quote / vquote) - 0.5
    per asset per day. positive = buy-side dominated → LONG; negative = sell-side → SHORT.
    Cross-sectionally: where in the panel is the buy-imbalance most extreme?"""
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(vquote > 0, taker_buy_quote / vquote, np.nan)
    score = ratio - 0.5
    return _xs_weights(score, sign=+1.0)


def volume_weighted_momentum(close: np.ndarray, vol: np.ndarray, k: int = 30) -> np.ndarray:
    """Minimax-A — momentum weighted by recent volume. weight ∝ sign(rk) × √vol.
    Captures moves that happened on real demand (large vol days), ignoring noise moves."""
    rk = _roll_ret(close, k)
    score = np.nan_to_num(rk) * np.sqrt(np.nan_to_num(vol))
    return _xs_weights(score, sign=+1.0)


def signal_library(close, vbase, vquote, taker_buy_quote) -> dict[str, np.ndarray]:
    """{name: weight matrix T×K} for the volume family. Each dollar-neutral, gross 1."""
    return {
        "volume_price_trend":   volume_price_trend(close, vbase, k=20),
        "taker_buy_imbalance":  taker_buy_imbalance(vquote, taker_buy_quote),
        "volume_weighted_mom":  volume_weighted_momentum(close, vbase, k=30),
    }


def run() -> dict:
    days, close, vbase, vquote, taker_buy_quote = load_a_s1_panel()
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, vbase, vquote, taker_buy_quote)
    # T2 funding carry = 0 for this panel (no funding in the backtest loop on A-S1's volumes).
    # The honest PnL is price-only + turnover cost; document this limitation.
    fsum = np.zeros_like(close)
    pnl = {name: _bt(W, ret, fsum) for name, W in lib.items()}
    warm = 30   # shortest lookback (vol_z k=20 + k buffer)
    series = {name: p[warm:] for name, p in pnl.items()}
    wf = _walkforward(series)
    evals = evaluate_universe({n: list(s) for n, s in series.items()}, dsr_threshold=0.95)
    ann = {n: (float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else 0.0)
           for n, s in series.items()}
    survivors = [e.name for e in evals if e.survives]
    return {
        "days": len(days),
        "n_signals": len(lib),
        "ann_sharpe": {n: round(a, 2) for n, a in ann.items()},
        "wf": wf,
        "survivors": survivors,
        "evals": evals,
    }


if __name__ == "__main__":
    res = run()
    print(f"\n=== VOLUME FACTORY — {res['n_signals']} signals · {res['days']} days (A-S1 substrate) ===\n")
    print(f"{'signal':24} {'annSR':>6} {'WF':>5} {'pos_folds':>9} {'robust':>7}")
    for n in res["ann_sharpe"]:
        w = res["wf"][n]
        a = res["ann_sharpe"][n]
        print(f"{n:24} {a:>6.2f} {w['pos_folds']}/5  {w['mean_fold_sr']:>9.2f} "
              f"{'YES' if w['robust'] else 'no':>7}")
    print(f"\nDSR survivors (>=0.95): {len(res['survivors'])} — "
          f"{res['survivors'] if res['survivors'] else 'NONE'}")
    print("\nHonest limitations:")
    print("  • A-S1 substrate is 5 symbols × 563 days (2025-01-01 → 2026-07-17); 24-name")
    print("    cross-section would need volume for the wider universe.")
    print("  • T2 funding carry = 0 in this run; the backtest is price + vol + turnover cost only.")
    print("  • No cross-corr check vs the funding factory's nucleus here — that belongs in")
    print("    a cross-factory orthogonality harness (separate, future).")
