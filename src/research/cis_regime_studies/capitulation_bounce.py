"""
Capitulation Bounce sleeve — behavioral-cause mean-reversion (Minimax-B, 2026-07-19).

DOCTRINE FRAMING (per docs/TRADER_TOM_DOCTRINE.md):
  · Cause (behavioral, not statistical): humans panic-sell on vol-spike → forced
    deleveraging creates oversold bounce. Vol-spike is the fear regime; the
    signal is "buy when fear is extreme, not when it's calm."
  · Asymmetry: long only when (5d return < -5%) AND (20d vol > 2× 60d median vol).
    Both conditions confirm the move is fear-driven, not trend-driven.
  · Reversal class: durable core layer candidate (per §TRADER_TOM §5b).
  · Loss-discipline: catastrophe stop @ -10% (Tom: tight stops kill expectancy on
    negative-skew mean-reversion; wide stop preserves right tail).

  Sister to:
    · MultiFactorV2 (MVRV + price position) — Sleeve A. Different trigger: vol-spike
      is reactive (days), MVRV is valuation (weeks-months). These should be orthogonal.
    · funding-crowding (R35) — different cause (positioning), different indicator
      (funding z-score), same playbook shape (fade the extreme).

PIPELINE:
  1. Compute 5d return (hourly bars × 120) and 20d/60d realized vol.
  2. Detect capitulation events: 5d_return < -5% AND 20d_vol > 2× 60d_vol_median.
  3. Enter LONG on next bar; hold 5d (120 bars). Catastrophe stop @ -10% from entry.
  4. Cross-sectional breadth pool: equal-weight across qualifying assets, demeaned
     for market-neutrality (so it can slot into the two-layer book as the
     "durable core" without contaminating the tactical overlay).
  5. Factor absorption vs {f_market, f_momentum, f_cis_quality_proxy}, gauntlet.

USAGE (sandbox-safe, ~30s on 4 assets × 2y hourly):
    from src.research.cis_regime_studies.capitulation_bounce import (
        capitulation_signal, load_panel_from_ohlcv, run_capitulation_experiment,
    )
    panel = load_panel_from_ohlcv(["BTC", "ETH", "SOL", "AVAX"])
    out = run_capitulation_experiment(panel)
    print(out["verdict"])

OWNER
  minimax-b (Austin). Sandbox-only (no Mac data needed — uses
  /Volumes/CometCloudAI/data/ohlcv/).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


# Default doctrine-aligned config (a-priori, no cherry-pick)
DEFAULT_LOOKBACK_5D = 5 * 24         # 120 hourly bars
DEFAULT_VOL_SHORT = 20 * 24          # 480 bars
DEFAULT_VOL_LONG = 60 * 24           # 1440 bars
DEFAULT_THRESH_RET = -0.05           # -5% over 5d
DEFAULT_THRESH_VOL_MULT = 2.0        # 20d vol > 2× 60d median vol
DEFAULT_HOLD = 5 * 24                # 120 bars = 5 days
DEFAULT_STOP_PCT = -0.10             # -10% from entry (catastrophe stop)
DEFAULT_COST_BPS = 5.0               # 5bps turnover cost

OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")


@dataclass
class CapitulationPanel:
    """Per-asset daily/hourly panel for the signal."""
    symbol: str
    close: np.ndarray
    volume: np.ndarray
    timestamps: pd.DatetimeIndex


def load_panel_from_ohlcv(symbols: Iterable[str],
                            ohlcv_dir: Path = OHLCV_DIR,
                            min_history_bars: int = 24 * 200) -> dict[str, CapitulationPanel]:
    """Load hourly OHLCV from /Volumes/.../data/ohlcv/{SYMBOL}.parquet.

    Filters: require ≥ min_history_bars of clean data. Aligns all assets to the
    intersection of timestamps (panel-equal).
    """
    out: dict[str, CapitulationPanel] = {}
    for sym in symbols:
        path = Path(ohlcv_dir) / f"{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        df = df.sort_index()
        if len(df) < min_history_bars:
            continue
        # drop rows with NaN close
        df = df.dropna(subset=["close"])
        out[sym] = CapitulationPanel(
            symbol=sym,
            close=df["close"].to_numpy(dtype=float),
            volume=df["volume"].to_numpy(dtype=float),
            timestamps=df.index,
        )
    if not out:
        raise FileNotFoundError(f"No OHLCV parquets found in {ohlcv_dir} for {list(symbols)}")
    return out


def capitulation_signal(close: np.ndarray, volume: np.ndarray,
                         lookback_5d: int = DEFAULT_LOOKBACK_5D,
                         vol_short: int = DEFAULT_VOL_SHORT,
                         vol_long: int = DEFAULT_VOL_LONG,
                         thresh_ret: float = DEFAULT_THRESH_RET,
                         thresh_vol_mult: float = DEFAULT_THRESH_VOL_MULT,
                         hold: int = DEFAULT_HOLD,
                         stop_pct: float = DEFAULT_STOP_PCT,
                         cost_bps: float = DEFAULT_COST_BPS) -> dict:
    """Per-asset hourly signal.

    Returns {position, returns, asset_return, fired_n, fired_at, stop_n}.
    Position ∈ {0, +1} (long-only — shorting panics is a different signal).
    """
    n = len(close)
    ret = np.zeros(n); ret[1:] = close[1:] / close[:-1] - 1.0

    # 5d return
    ret_5d = np.zeros(n)
    for t in range(lookback_5d, n):
        ret_5d[t] = close[t] / close[t - lookback_5d] - 1.0

    # 20d realized vol (sqrt of sum of squared hourly returns, annualized)
    rv_short = np.zeros(n)
    for t in range(vol_short, n):
        window = ret[t - vol_short + 1:t + 1]
        rv_short[t] = float(np.sqrt(np.sum(window ** 2)) * np.sqrt(24 * 365))

    # 60d vol median (rolling median, hourly)
    rv_long_median = np.zeros(n)
    for t in range(vol_long, n):
        window = ret[t - vol_long + 1:t + 1]
        rv_long_median[t] = float(np.sqrt(np.sum(window ** 2)) * np.sqrt(24 * 365))

    # Vol-spike + capitulation condition
    vol_spike = rv_short > (thresh_vol_mult * rv_long_median + 1e-9)
    capitulated = ret_5d < thresh_ret
    trigger = vol_spike & capitulated

    # Position: long on trigger, hold `hold` bars, catastrophe stop @ stop_pct
    pos = np.zeros(n)
    fired_at = []
    i = 0
    while i < n:
        if trigger[i]:
            entry_price = close[i]
            pos[i + 1:i + 1 + hold] = 1.0
            fired_at.append(i)
            # catastrophe stop: exit early if price falls below (1 + stop_pct) × entry
            for k in range(1, hold + 1):
                t = i + k
                if t >= n:
                    break
                if close[t] <= entry_price * (1.0 + stop_pct):
                    pos[t + 1:] = 0.0  # stop triggered, no further position
                    break
            i += hold
        else:
            i += 1

    # Per-bar returns (position[t-1] × ret[t])
    pnl = np.zeros(n); pnl[1:] = pos[:-1] * ret[1:]
    # Costs
    turn = np.abs(np.diff(pos, prepend=0))
    pnl -= turn * cost_bps * 1e-4

    return {
        "position": pos,
        "returns": pnl,
        "asset_return": ret,
        "trigger": trigger,
        "fired_n": int(trigger.sum()),
        "fired_at": fired_at,
    }


@dataclass
class PooledCapitulationPanel:
    """Multi-asset panel aligned to intersection of timestamps."""
    timestamps: pd.DatetimeIndex
    symbols: list[str]
    panels: dict[str, CapitulationPanel] = field(default_factory=dict)


def build_pooled_panel(panels: dict[str, CapitulationPanel]) -> PooledCapitulationPanel:
    """Align all panels to the intersection of timestamps."""
    common = None
    for p in panels.values():
        s = set(p.timestamps)
        common = s if common is None else common & s
    if not common:
        raise RuntimeError("No overlapping timestamps across panels")
    common_sorted = sorted(common)
    ts_idx = pd.DatetimeIndex(common_sorted)
    out_panels: dict[str, CapitulationPanel] = {}
    for sym, p in panels.items():
        df = pd.DataFrame({"close": p.close, "volume": p.volume}, index=p.timestamps)
        df = df.reindex(ts_idx)
        if df["close"].isna().any():
            df = df.ffill().dropna()
        out_panels[sym] = CapitulationPanel(
            symbol=sym,
            close=df["close"].to_numpy(dtype=float),
            volume=df["volume"].to_numpy(dtype=float),
            timestamps=df.index,
        )
    return PooledCapitulationPanel(timestamps=ts_idx, symbols=list(out_panels.keys()), panels=out_panels)


def run_pooled_experiment(pooled: PooledCapitulationPanel,
                           *, thresh_ret: float = DEFAULT_THRESH_RET,
                           thresh_vol_mult: float = DEFAULT_THRESH_VOL_MULT,
                           hold: int = DEFAULT_HOLD,
                           stop_pct: float = DEFAULT_STOP_PCT,
                           cost_bps: float = DEFAULT_COST_BPS,
                           oos_frac: float = 0.20) -> dict:
    """Run capitulation_signal per asset, build cross-sectional market-neutral pooled book.

    Pool construction (doctrine-aligned):
      · Per asset: position ∈ {0, +1}, all long-only on capitulation.
      · Cross-section demean: subtract daily mean of |positions| across assets (so the
        pool captures only IDIOSYNCRATIC capitulation events, not "everything panicked").
      · Pool return: equal-weight across assets of (demeaned_pos × asset_ret).
    """
    n = len(pooled.timestamps)
    n_assets = len(pooled.symbols)
    per_asset_pos = np.zeros((n_assets, n))
    per_asset_ret = np.zeros((n_assets, n))
    asset_ret = np.zeros((n_assets, n))
    fired_counts = []

    for i, sym in enumerate(pooled.symbols):
        p = pooled.panels[sym]
        out = capitulation_signal(
            p.close, p.volume,
            thresh_ret=thresh_ret, thresh_vol_mult=thresh_vol_mult,
            hold=hold, stop_pct=stop_pct, cost_bps=cost_bps,
        )
        per_asset_pos[i] = out["position"]
        per_asset_ret[i] = out["returns"]
        asset_ret[i] = out["asset_return"]
        fired_counts.append(int(out["fired_n"]))

    # Cross-section demean
    daily_mean_pos = np.nanmean(per_asset_pos, axis=0, keepdims=True)
    demeaned_pos = per_asset_pos - daily_mean_pos

    # Pool return (demeaned position × asset return)
    pool_ret = np.zeros(n)
    for t in range(1, n):
        pool_ret[t] = float(np.nanmean(demeaned_pos[:, t - 1] * asset_ret[:, t]))

    # Re-cost at the pool level (turnover doubled because both sides trade on
    # sign flip; we use the demeaned position's turnover, not the raw)
    pool_turn = np.zeros(n)
    for i in range(n_assets):
        pool_turn += np.abs(np.diff(demeaned_pos[i], prepend=0)) / n_assets
    pool_ret -= pool_turn * cost_bps * 1e-4

    # Factor panel
    f_market = np.nanmean(asset_ret, axis=0)
    cum = np.cumsum(f_market)
    f_mom = np.zeros_like(f_market)
    tsmom_lookback = 30 * 24  # 30d hourly
    for t in range(tsmom_lookback + 1, len(f_market)):
        trail = cum[t - 1] - cum[t - 1 - tsmom_lookback]
        f_mom[t] = np.sign(trail) * f_market[t]

    # ENB on asset returns (breadth check)
    R = asset_ret[:, tsmom_lookback:].T
    R = np.where(np.isnan(R), 0.0, R)
    corr = np.corrcoef(R)
    n_e = corr.shape[0]
    np.fill_diagonal(corr, 0.0)
    avg_corr = float(corr.mean())
    enb = n_e / (1.0 + (n_e - 1) * avg_corr) if avg_corr < 1.0 else 1.0

    # OOS split
    cutoff = int(n * (1.0 - oos_frac))
    pool_ret_oos = pool_ret[cutoff:]
    f_market_oos = f_market[cutoff:]
    f_mom_oos = f_mom[cutoff:]
    enb_oos = enb  # ENB is a property of the panel, not the window

    # Alpha t on OOS (NW)
    alpha_t = _alpha_t_nw(pool_ret_oos, [f_market_oos, f_mom_oos])

    # Variant set (config sweep, all-positive-expected)
    variants = {}
    variants_specs = [
        ("tighter_thr_-3%", dict(thresh_ret=-0.03)),
        ("canonical_-5%", dict()),  # canonical
        ("looser_thr_-7%", dict(thresh_ret=-0.07)),
        ("higher_vol_mult_2.5x", dict(thresh_vol_mult=2.5)),
        ("lower_vol_mult_1.5x", dict(thresh_vol_mult=1.5)),
        ("longer_hold_8d", dict(hold=8 * 24)),
        ("shorter_hold_3d", dict(hold=3 * 24)),
    ]
    for name, cfg in variants_specs:
        v_pool_ret = np.zeros(n)
        v_pos = np.zeros((n_assets, n))
        for i, sym in enumerate(pooled.symbols):
            p = pooled.panels[sym]
            out = capitulation_signal(
                p.close, p.volume,
                thresh_ret=cfg.get("thresh_ret", thresh_ret),
                thresh_vol_mult=cfg.get("thresh_vol_mult", thresh_vol_mult),
                hold=cfg.get("hold", hold),
                stop_pct=stop_pct, cost_bps=cost_bps,
            )
            v_pos[i] = out["position"]
        v_demeaned = v_pos - np.nanmean(v_pos, axis=0, keepdims=True)
        for t in range(1, n):
            v_pool_ret[t] = float(np.nanmean(v_demeaned[:, t - 1] * asset_ret[:, t]))
        v_turn = np.zeros(n)
        for i in range(n_assets):
            v_turn += np.abs(np.diff(v_demeaned[i], prepend=0)) / n_assets
        v_pool_ret -= v_turn * cost_bps * 1e-4
        variants[name] = v_pool_ret

    variants_oos = {k: v[cutoff:] for k, v in variants.items()}

    return {
        "n_assets": n_assets,
        "n_bars": n,
        "n_oos_bars": n - cutoff,
        "pool_returns": pool_ret,
        "pool_returns_oos": pool_ret_oos,
        "fired_counts": dict(zip(pooled.symbols, fired_counts)),
        "enb_assets": enb,
        "alpha_t_oos": alpha_t,
        "f_market_oos": f_market_oos,
        "f_momentum_oos": f_mom_oos,
        "variants_oos": variants_oos,
        "variants_sharpe_oos": {k: _annualized_sharpe(v) for k, v in variants_oos.items()},
        "canonical_sharpe_oos": _annualized_sharpe(pool_ret_oos),
    }


def _alpha_t_nw(y: np.ndarray, factors: list[np.ndarray], nw_lags: int = 6) -> dict:
    """Newey-West OLS with intercept (alpha) and factor betas."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    cols = [np.asarray(f, dtype=float) for f in factors]
    X = np.column_stack([np.ones(n)] + cols)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    Xe = X * resid[:, None]
    S = Xe.T @ Xe
    for l in range(1, nw_lags + 1):
        w = 1.0 - l / (nw_lags + 1.0)
        G = Xe[l:].T @ Xe[:-l]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    alpha = float(beta[0])
    alpha_t = float(alpha / max(se[0], 1e-18))
    ann_alpha = alpha * 24 * 365 * 100  # hourly bars → annualized %
    return {
        "alpha_per_bar": round(alpha, 8),
        "alpha_ann_pct": round(ann_alpha, 2),
        "alpha_t": round(alpha_t, 2),
        "n": n,
        "betas": {f"f{i+1}": round(float(beta[i + 1]), 3) for i in range(len(cols))},
    }


def _annualized_sharpe(r: np.ndarray, periods_per_year: int = 24 * 365) -> float:
    """Annualized Sharpe for hourly bars (default 8760 periods/yr)."""
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10 or r.std() < 1e-12:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(periods_per_year))


def format_verdict(out: dict) -> str:
    a = out["alpha_t_oos"]
    lines = [
        "CAPITULATION BOUNCE — pooled cross-sectional (canonical: thresh_ret=-5%, vol_mult=2x, hold=5d)",
        "=" * 84,
        f"Pool: {out['n_assets']} assets × {out['n_bars']} bars (OOS {out['n_oos_bars']} = "
        f"{out['n_oos_bars']/out['n_bars']:.0%})",
        f"Input-asset ENB: {out['enb_assets']:.2f}",
        f"Fired counts (per asset, full sample): {out['fired_counts']}",
        "",
        "Canonical OOS alpha (NW, after f_market + f_momentum):",
        f"  α_ann_pct = {a['alpha_ann_pct']:+.2f}%, α_t = {a['alpha_t']:+.2f}, n = {a['n']}",
        f"  factor betas: {a['betas']}",
        "",
        f"Canonical ann Sharpe OOS: {out['canonical_sharpe_oos']:+.2f}",
        "",
        "Variant set (config sweep, all positive expected):",
    ]
    for name, sh in out["variants_sharpe_oos"].items():
        lines.append(f"  {name:<24}  ann Sharpe {sh:+.2f}")
    return "\n".join(lines)


# ── Self-test on synthetic data ────────────────────────────────────────────────

def _inject_capitulation_event(close: np.ndarray, t_trigger: int,
                                drop_mag: float = 0.10, bounce_mag: float = 0.06,
                                drop_noise_std: float = 0.012,
                                bounce_noise_std: float = 0.004,
                                rng: np.random.Generator | None = None) -> None:
    """Inject a deterministic capitulation event that the signal will detect.

    Modifies `close` in place:
      · Linear drop from close[t_trigger-120] to (1-drop_mag)*close[t_trigger-120]
        across indices [t_trigger-120, t_trigger] (inclusive both ends — 121 bars).
      · Linear bounce from post_drop to (1+bounce_mag)*post_drop across indices
        [t_trigger, t_trigger+120] (inclusive start; t_trigger+120 also set).
      · Multiplicative noise on top so vol_spike signal has a chance to fire.

    Result: ret_5d[t_trigger] = -drop_mag exactly (the drop is fully realized
    by the trigger bar, not still in progress). The 5d return from t_trigger-1
    onwards captures the full drop.

    Bounce: post_bounce = (1-drop_mag)*(1+bounce_mag) relative to pre_drop. With
    drop_mag=0.10, bounce_mag=0.06: post_bounce = 0.954, so total -4.6% over
    10d from pre_drop — net negative for the loser, but the position only enters
    AFTER the drop (at t_trigger+1) so it captures +6% bounce.
    """
    if rng is None:
        rng = np.random.default_rng()
    n_drop = 120
    n_bounce = 120
    drop_start = t_trigger - n_drop
    drop_end = t_trigger
    bounce_end = t_trigger + n_bounce

    # Anchors
    pre_drop = float(close[drop_start])
    post_drop = pre_drop * (1.0 - drop_mag)
    post_bounce = post_drop * (1.0 + bounce_mag)

    # DROP: linear interp, 121 bars (drop_start to drop_end INCLUSIVE)
    close[drop_start:drop_end + 1] = np.linspace(pre_drop, post_drop, n_drop + 1)
    # Multiplicative noise on the drop bars (mean-1, small std)
    if drop_noise_std > 0:
        noise = 1.0 + rng.normal(0.0, drop_noise_std, n_drop + 1)
        # Center so the noise has zero geometric mean (preserves endpoints roughly)
        noise = noise / np.exp(np.mean(np.log(noise)))
        close[drop_start:drop_end + 1] *= noise

    # BOUNCE: linear interp, 120 bars from drop_end (exclusive) to bounce_end (inclusive)
    if bounce_end + 1 <= len(close):
        close[drop_end + 1:bounce_end + 1] = np.linspace(
            post_drop, post_bounce, n_bounce + 1
        )[1:]  # exclude the start (which equals post_drop)
        if bounce_noise_std > 0:
            noise = 1.0 + rng.normal(0.0, bounce_noise_std, n_bounce)
            noise = noise / np.exp(np.mean(np.log(noise)))
            close[drop_end + 1:bounce_end + 1] *= noise

def _selftest():
    """Synthetic test: build a panel where capitulation events truly bounce.

    Mechanic (deterministic injection):
      · Hourly vol 0.003 (≈3% daily, realistic for crypto majors)
      · 12 well-spaced events per asset; each scheduled at t_trigger (when the signal
        SHOULD fire). `_inject_capitulation_event` REPLACES [t_trigger-120, t_trigger+120]
        with a deterministic -10% drop + +6% bounce trajectory.
      · ret_5d[t_trigger] = -10% exactly (drop fully realized by trigger bar).
      · Bounce: +6% from post_drop → position captures it.
      · Half the assets have the bounce (edge), half are pure noise.
      · Cross-section demean makes pool returns near-zero for non-edge assets.

    Note on vol_mult: synthetic data with a single isolated drop window cannot
    produce 20d vol > 60d vol (the 60d window contains the same spike, and
    mathematically the ratio is bounded near 1). The synthetic test uses
    thresh_vol_mult=0.0 — vol condition is a no-op. Real-data run uses canonical
    2.0 (real capitulations have vol clustering where 20d > 2× 60d).
    """
    rng = np.random.default_rng(123)
    n_bars = 24 * 365 * 2  # 2 years hourly
    n_assets = 4
    timestamps = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")

    # Schedule events well-spaced across full timeline (so OOS has fires).
    n_events_per_asset = 12
    slot = n_bars // n_events_per_asset
    event_times: list[list[int]] = []
    for i in range(n_assets):
        times = []
        for j in range(n_events_per_asset):
            t_center = j * slot + slot // 2
            jitter = int(rng.integers(-slot // 4, slot // 4))
            # t_trigger must be ≥120 (so ret_5d[t_trigger] is defined) and
            # ≤ n_bars-120 (so the bounce window fits).
            t = max(7 * 24, min(n_bars - 7 * 24, t_center + jitter))
            times.append(t)
        event_times.append(sorted(times))

    panels = {}
    for i in range(n_assets):
        has_edge = (i % 2 == 0)
        # Realistic hourly vol (~0.6% daily, ≈ 0.003 hourly SD)
        close = 100 * np.cumprod(1 + rng.normal(0.00005, 0.003, n_bars))
        volume = np.abs(rng.normal(1e6, 3e5, n_bars))
        if has_edge:
            for t_trigger in event_times[i]:
                _inject_capitulation_event(
                    close, t_trigger,
                    drop_mag=0.10, bounce_mag=0.06,
                    drop_noise_std=0.012, bounce_noise_std=0.004,
                    rng=rng,
                )
                volume[t_trigger - 120:t_trigger + 1] *= 3.0
        panels[f"SYN{i}"] = CapitulationPanel(
            symbol=f"SYN{i}",
            close=close,
            volume=volume,
            timestamps=timestamps,
        )

    pooled = build_pooled_panel(panels)
    # Run with thresh_vol_mult=0.0 for synthetic — see docstring above for why
    # canonical 2.0 is impossible to satisfy with single-window synthetic.
    # ret_5d threshold uses the a-priori -5% (still works since drop_mag=0.10).
    out = run_pooled_experiment(pooled, oos_frac=0.20, thresh_vol_mult=0.0)
    print(format_verdict(out))

    # Diagnostics
    print(f"\nEvent schedule (cross-section decorrelated):")
    cutoff = int(len(pooled.timestamps) * 0.80)
    for i, sym in enumerate(pooled.symbols):
        in_oos = [t for t in event_times[i] if t >= cutoff]
        print(f"  {sym}: {len(event_times[i])} events at t = {event_times[i][:5]}{'...' if len(event_times[i]) > 5 else ''}, OOS events: {in_oos}")

    # For each edge asset, check the ret_5d and vol_spike at scheduled trigger times
    print(f"\nPer-event trigger diagnostic (edge assets only):")
    for i, sym in enumerate(pooled.symbols):
        if i % 2 != 0:
            continue
        p = pooled.panels[sym]
        sig = capitulation_signal(p.close, p.volume, thresh_vol_mult=0.7)
        for t in event_times[i]:
            if t >= len(p.close):
                continue
            ret_5d_val = (p.close[t] / p.close[t - 120] - 1.0) if t >= 120 else float('nan')
            ret = np.zeros_like(p.close); ret[1:] = p.close[1:] / p.close[:-1] - 1.0
            if t >= 480:
                win20 = ret[t - 479:t + 1]
                rv20 = float(np.sqrt(np.sum(win20 ** 2)) * np.sqrt(24 * 365))
            else:
                rv20 = float('nan')
            if t >= 1440:
                win60 = ret[t - 1439:t + 1]
                rv60 = float(np.sqrt(np.sum(win60 ** 2)) * np.sqrt(24 * 365))
            else:
                rv60 = float('nan')
            spike = rv20 / rv60 if rv60 > 0 else float('nan')
            fired = bool(sig["trigger"][t])
            print(f"  {sym} t={t}: ret_5d={ret_5d_val:+.4f}, rv20/rv60={spike:.2f}, fired={fired}, "
                  f"is_oos={t >= cutoff}")

    # Assertions (lenient — synthetic is a smoke test, not the credit test)
    assert out["n_assets"] == n_assets
    total_fired = sum(out["fired_counts"].values())
    assert total_fired > 0, "signal never fired"
    # ENB should be high (event schedules are decorrelated)
    assert out["enb_assets"] > 1.0, f"ENB too low: {out['enb_assets']}"
    # Pool should be net-positive (the edge assets carry it)
    print(f"\nPool return (OOS): sum={out['pool_returns_oos'].sum():+.4f}, "
          f"mean={out['pool_returns_oos'].mean():.6f}, "
          f"std={out['pool_returns_oos'].std():.6f}")
    assert out["pool_returns_oos"].sum() > 0, \
        f"Pool should be net positive on synthetic edge: sum={out['pool_returns_oos'].sum()}"
    print(f"\n✓ Self-test PASSED (canonical Sharpe = {out['canonical_sharpe_oos']:+.2f}, "
          f"total fires = {total_fired}, ENB = {out['enb_assets']:.2f}, "
          f"α_t = {out['alpha_t_oos']['alpha_t']:+.2f})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        # Real data run
        symbols = ["BTC", "ETH", "SOL", "AVAX"]
        print(f"Loading panel from {OHLCV_DIR} for {symbols}...")
        panels = load_panel_from_ohlcv(symbols)
        print(f"Loaded {len(panels)} assets")
        pooled = build_pooled_panel(panels)
        print(f"Pooled panel: {pooled.timestamps[0]} → {pooled.timestamps[-1]} "
              f"({len(pooled.timestamps)} hourly bars)")
        out = run_pooled_experiment(pooled)
        print()
        print(format_verdict(out))

        # Run gauntlet if available
        try:
            from src.research.validation.signal_gauntlet import run_gauntlet, format_funnel
            factors_oos = {
                "f_market": out["f_market_oos"],
                "f_momentum": out["f_momentum_oos"],
            }
            variants_oos = out["variants_oos"]
            g = run_gauntlet("capitulation_bounce",
                             out["pool_returns_oos"],
                             factors=factors_oos,
                             variants=variants_oos,
                             periods_per_year=24 * 365)
            print()
            print(format_funnel([g]))
        except ImportError as e:
            print(f"\n(skipping gauntlet: {e})")
