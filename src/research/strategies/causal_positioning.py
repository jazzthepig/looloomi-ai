"""
Causal Positioning Sleeve — the orthogonal forced-flow strategy (Seth, 2026-07-10).
===================================================================================

The upgrade thesis (reports/STRATEGY_UPGRADE_2026-07-10.md): our 5 DSR-certified
strategies are 0.67 correlated — one idea in five costumes (ENB≈2.2). The math says
the highest-value addition is not a sixth swing variant but a single UNCORRELATED
sleeve. This is that sleeve, and it trades a different driver than price/TA — so it
is structurally orthogonal to the whole swing lineage.

CAUSE (positioning / cause #2): perpetual funding is a tax the crowded side pays.
Extreme POSITIVE funding = over-leveraged longs whose liquidation is a forced future
SELL (bearish); extreme NEGATIVE funding = crowded shorts whose squeeze is a forced
future BUY (bullish). The positioning is a decision already made; the forced flow
propagates into price later — upstream, knowable now. We fade the crowd.

CONSTRUCTION (cross-sectional, market-neutral, universe-wide):
  signal[i,t]  = cross-sectional z-score of trailing-Kwin-day mean funding
  weight[i,t]  = -z  → demeaned (dollar-neutral) → scaled to gross Σ|w| = 1
  return[t+1]  = Σ w·price_return  +  funding carry (short of +funding receives)  − costs
Delta-neutral by construction ⇒ ~zero crypto beta ⇒ ~zero correlation to directional
swing. Universe-agnostic: add assets to the cross-section, the signal only sharpens.

VALIDATED (24 assets, Binance perps, 2024-01 → 2025-10, 5bps costs):
  full-sample ann Sharpe ≈ +1.2 (Kwin 7), +38% total, 10% maxDD; survives 10bps.
  chronological OOS (IS picks Kwin, measure last 40%): OOS ann Sharpe +1.02 — stable,
  no sign flip. CORRELATION to the swing book = +0.002 (the decisive property).
  Standalone Sharpe is modest vs swing's in-sample 5+, but (a) it is the FIRST real
  second bet (ENB 2.16→2.85), (b) its book value GROWS as swing's inflated in-sample
  Sharpe deflates to realistic OOS levels, (c) market-neutral ⇒ carries in regimes
  where the directional swing fails.

Data: Binance USDT-perp funding history (/fapi/v1/fundingRate) + daily klines. All
reachable without geo-block from research infra. Pure numpy.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


# ── Signal ───────────────────────────────────────────────────────────────────

def positioning_weights(fmean: np.ndarray, kwin: int = 7) -> np.ndarray:
    """T×K daily mean-funding panel → T×K market-neutral contrarian weights.
    Fade the crowd: short high-funding (crowded longs), long low/negative funding."""
    T, K = fmean.shape
    W = np.zeros((T, K))
    for i in range(T):
        roll = fmean[max(0, i - kwin + 1):i + 1].mean(0)
        z = roll - roll.mean()
        sd = z.std()
        z = z / sd if sd > 0 else z
        w = -z                       # contrarian
        w = w - w.mean()             # dollar-neutral
        g = np.abs(w).sum()
        W[i] = w / g if g > 0 else w  # gross = 1
    return W


# ── Backtest ─────────────────────────────────────────────────────────────────

@dataclass
class SleeveResult:
    daily_pnl: np.ndarray
    ann_sharpe: float
    total_return_pct: float
    max_dd_pct: float


def backtest(close: np.ndarray, fmean: np.ndarray, fsum: np.ndarray,
             *, kwin: int = 7, fee: float = 0.0005) -> SleeveResult:
    """close/fmean/fsum: T×K aligned panels (fsum = daily summed funding).
    Returns daily pnl (price PnL + funding carry − turnover cost) and headline metrics."""
    T, K = close.shape
    ret = np.zeros((T, K))
    ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    W = positioning_weights(fmean, kwin)
    pnl = np.zeros(T)
    for i in range(1, T - 1):
        turn = np.abs(W[i] - W[i - 1]).sum()
        pnl[i + 1] = (W[i] * ret[i + 1]).sum() - (W[i] * fsum[i + 1]).sum() - fee * turn
    sd = pnl.std(ddof=1)
    ann = float(pnl.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    cum = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(cum) - cum).max() * 100)
    return SleeveResult(daily_pnl=pnl, ann_sharpe=round(ann, 3),
                        total_return_pct=round(pnl.sum() * 100, 2), max_dd_pct=round(dd, 2))


# ── Panel loader (Binance perps) ─────────────────────────────────────────────

def load_binance_panel(assets: list[str], start=(2024, 1, 1)):
    """Fetch aligned (dates, close, fmean, fsum) panels from Binance USDT perps.
    fmean = daily mean funding (signal), fsum = daily summed funding (carry)."""
    import datetime as dt
    import httpx
    c = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    base = "https://fapi.binance.com"
    start_ms = int(dt.datetime(*start).timestamp() * 1000)

    def klines(sym):
        r = c.get(f"{base}/fapi/v1/klines", params={"symbol": sym, "interval": "1d", "limit": 1000})
        return {int(k[0]) // 86400000: float(k[4]) for k in r.json()}

    def funding(sym):
        out, cur = {}, start_ms
        for _ in range(6):
            r = c.get(f"{base}/fapi/v1/fundingRate", params={"symbol": sym, "startTime": cur, "limit": 500})
            j = r.json()
            if not j:
                break
            for x in j:
                out.setdefault(int(x["fundingTime"]) // 86400000, []).append(float(x["fundingRate"]))
            cur = int(j[-1]["fundingTime"]) + 1
            if len(j) < 500:
                break
        return out

    cl, fm, fs = {}, {}, {}
    for a in assets:
        sym = a + "USDT"
        cl[a] = klines(sym)
        fu = funding(sym)
        fm[a] = {d: sum(v) / len(v) for d, v in fu.items()}
        fs[a] = {d: sum(v) for d, v in fu.items()}
    days = sorted(set(d for a in assets for d in fm[a]))
    di = {d: i for i, d in enumerate(days)}
    T, K = len(days), len(assets)
    close = np.full((T, K), np.nan); fmean = np.zeros((T, K)); fsum = np.zeros((T, K))
    for j, a in enumerate(assets):
        for d, v in cl[a].items():
            if d in di:
                close[di[d], j] = v
        for d, v in fm[a].items():
            fmean[di[d], j] = v
        for d, v in fs[a].items():
            fsum[di[d], j] = v
    for j in range(K):
        for i in range(1, T):
            if np.isnan(close[i, j]):
                close[i, j] = close[i - 1, j]
    return days, close, fmean, fsum


DEFAULT_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
                    "DOT", "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
                    "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]


if __name__ == "__main__":
    import datetime as dt
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE)
    print(f"panel: {len(days)} days x {len(DEFAULT_UNIVERSE)} assets | "
          f"{dt.date.fromtimestamp(days[0]*86400)} → {dt.date.fromtimestamp(days[-1]*86400)}")
    for kw in (5, 7, 10):
        r = backtest(close, fmean, fsum, kwin=kw)
        print(f"  Kwin={kw}: ann Sharpe {r.ann_sharpe:+.2f} | total {r.total_return_pct:+.1f}% | maxDD {r.max_dd_pct:.1f}%")
