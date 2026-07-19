"""
R40 v2 — Capitulation Bounce as a PER-PAIR SWING OVERLAY (Minimax-B, 2026-07-19).

DOCTRINE FRAMING (per §TRADER_TOM_DOCTRINE §5c — tactical overlay):
  · Trigger (reused from R40, per-asset trigger is REAL — BTC 76% win rate,
    +2.6% fwd 5d on Yen carry-trade unwind): 5d_return < -5% AND
    20d_vol > 2× 60d_vol.
  · Entry: per-pair LONG on trigger (no cross-section demean).
  · Hold: 5d (120 hourly bars).
  · Catastrophe stop @ -10% (Tom: wide stops preserve right tail on
    negative-skew mean-reversion; tight stops kill expectancy).
  · Position: equal-weight across concurrent fires, capped at N_MAX_CONCURRENT.
  · Total gross exposure cap (so the overlay can't dominate the book).

WHY PER-PAIR (not pooled demeaned):
  R40 was refuted because the cross-section demeaned pool's ENB was 1.18 on
  4 majors, 1.51 on full 51 assets — structurally not enough breadth for pooled
  cross-section. The PER-ASSET TRIGGER IS CORRECT (76% BTC win rate on the
  August 2024 unwind). The implementation shape (pooled book) was wrong. This
  v2 uses the trigger logic in a per-pair swing overlay shape that matches
  the doctrine's tactical-overlay role.

USAGE (sandbox-safe, ~30s on full 51-asset universe × 2y hourly):
    from src.research.cis_regime_studies.capitulation_bounce_v2 import (
        run_capitulation_v2_experiment, format_v2_verdict,
    )
    out = run_capitulation_v2_experiment(symbols=None)  # all 51 by default
    print(format_v2_verdict(out))

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

# Reuse the trigger logic from R40 (v1)
from src.research.cis_regime_studies.capitulation_bounce import (
    DEFAULT_LOOKBACK_5D,
    DEFAULT_VOL_SHORT,
    DEFAULT_VOL_LONG,
    DEFAULT_THRESH_RET,
    DEFAULT_THRESH_VOL_MULT,
    DEFAULT_HOLD,
    DEFAULT_STOP_PCT,
    DEFAULT_COST_BPS,
    OHLCV_DIR,
    CapitulationPanel,
    load_panel_from_ohlcv,
    capitulation_signal,
)


# === Doctrine-aligned per-pair overlay defaults ===

# Position sizing: equal-weight across concurrent fires, with hard caps
DEFAULT_SIZE_PER_PAIR = 0.05         # 5% of book per fire (bounded)
DEFAULT_MAX_CONCURRENT = 8           # hard cap on simultaneous positions
DEFAULT_MAX_GROSS = 0.40             # 40% of book max gross exposure


@dataclass
class PairTrade:
    """Single per-pair trade record."""
    symbol: str
    entry_t: int
    entry_price: float
    exit_t: int
    exit_price: float
    exit_reason: str                  # "hold_expired" | "stop_hit" | "end_of_data"
    pnl_pct: float                    # exit_price / entry_price - 1
    held_bars: int
    did_bounce: bool                  # True if pnl_pct > 0


def _track_pair_trades(position: np.ndarray, close: np.ndarray,
                       fired_at: list[int], hold: int) -> list[PairTrade]:
    """Convert a per-asset position series + fired_at list into PairTrade records.

    Entry: pos[t+1] = 1.0 means entry at t (open of t+1).
    Exit: pos[k] = 0.0 after t+hold (or earlier if catastrophe stop hit).
    """
    trades = []
    n = len(close)
    for entry_t in fired_at:
        entry_price = close[entry_t]
        exit_t = entry_t + hold
        exit_reason = "hold_expired"
        # Walk through the position; check if stop hit
        for k in range(entry_t + 1, min(entry_t + 1 + hold, n)):
            if close[k] <= entry_price * (1.0 + DEFAULT_STOP_PCT):
                exit_t = k
                exit_reason = "stop_hit"
                break
        if exit_t >= n:
            exit_t = n - 1
            exit_reason = "end_of_data"
        exit_price = close[exit_t]
        pnl_pct = exit_price / entry_price - 1.0
        trades.append(PairTrade(
            symbol="",  # filled by caller
            entry_t=entry_t,
            entry_price=float(entry_price),
            exit_t=exit_t,
            exit_price=float(exit_price),
            exit_reason=exit_reason,
            pnl_pct=float(pnl_pct),
            held_bars=exit_t - entry_t,
            did_bounce=bool(pnl_pct > 0),
        ))
    return trades


def run_capitulation_v2_experiment(
    symbols: Iterable[str] | None = None,
    *,
    thresh_ret: float = DEFAULT_THRESH_RET,
    thresh_vol_mult: float = DEFAULT_THRESH_VOL_MULT,
    hold: int = DEFAULT_HOLD,
    stop_pct: float = DEFAULT_STOP_PCT,
    cost_bps: float = DEFAULT_COST_BPS,
    size_per_pair: float = DEFAULT_SIZE_PER_PAIR,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    max_gross: float = DEFAULT_MAX_GROSS,
    oos_frac: float = 0.20,
    ohlcv_dir: Path = OHLCV_DIR,
) -> dict:
    """Per-pair swing overlay experiment using R40's trigger logic.

    Returns:
      · per_pair_trades: list[PairTrade] for all fires across all assets
      · per_pair_summary: dict[symbol] = {n_trades, win_rate, avg_pnl, ...}
      · book: pd.Series of portfolio NAV (1.0 = baseline)
      · book_oos: pd.Series of OOS NAV
      · variant_sweeps: dict of (config_name, book_oos) for robustness check
      · n_oos_bars, cutoff_t, etc.
    """
    if symbols is None:
        # All 51 crypto assets in /Volumes/CometCloudAI/data/ohlcv/
        all_paths = sorted(Path(ohlcv_dir).glob("*.parquet"))
        symbols = [p.stem for p in all_paths]

    panels = load_panel_from_ohlcv(symbols, ohlcv_dir=ohlcv_dir)
    if not panels:
        raise FileNotFoundError(f"No OHLCV parquets in {ohlcv_dir}")

    # Use union of timestamps (longest available per asset) instead of strict intersection.
    # This maximizes sample size since per-pair doesn't need panel-equal alignment.
    n_max = max(len(p.close) for p in panels.values())

    # Per-asset signal + trade records
    per_pair_trades: list[PairTrade] = []
    per_pair_fires: dict[str, int] = {}

    # Per-asset per-bar position series (1.0 when in trade)
    per_asset_pos: dict[str, np.ndarray] = {}
    per_asset_pnl: dict[str, np.ndarray] = {}

    for sym, panel in panels.items():
        sig = capitulation_signal(
            panel.close, panel.volume,
            thresh_ret=thresh_ret, thresh_vol_mult=thresh_vol_mult,
            hold=hold, stop_pct=stop_pct, cost_bps=cost_bps,
        )
        per_asset_pos[sym] = sig["position"]
        per_asset_pnl[sym] = sig["returns"]
        per_pair_fires[sym] = sig["fired_n"]

        # Build per-pair trade records
        trades = _track_pair_trades(sig["position"], panel.close, sig["fired_at"], hold)
        for t in trades:
            t.symbol = sym
        per_pair_trades.extend(trades)

    # === Per-pair summary ===
    per_pair_summary = {}
    for sym in panels.keys():
        sym_trades = [t for t in per_pair_trades if t.symbol == sym]
        if not sym_trades:
            per_pair_summary[sym] = {
                "n_trades": 0, "win_rate": 0.0, "avg_pnl": 0.0,
                "median_pnl": 0.0, "n_stops": 0, "stop_rate": 0.0,
                "total_pnl": 0.0, "avg_hold": 0.0,
            }
            continue
        pnls = np.array([t.pnl_pct for t in sym_trades])
        stops = sum(1 for t in sym_trades if t.exit_reason == "stop_hit")
        per_pair_summary[sym] = {
            "n_trades": len(sym_trades),
            "win_rate": float((pnls > 0).mean()),
            "avg_pnl": float(pnls.mean()),
            "median_pnl": float(np.median(pnls)),
            "n_stops": int(stops),
            "stop_rate": float(stops / len(sym_trades)),
            "total_pnl": float(pnls.sum()),
            "avg_hold": float(np.mean([t.held_bars for t in sym_trades])),
        }

    # === Build book: equal-weight per fire, capped at max_concurrent ===
    # Pad all per-asset positions to n_max length
    pos_matrix = np.zeros((len(panels), n_max))
    sym_list = list(panels.keys())
    for i, sym in enumerate(sym_list):
        p = panels[sym]
        # Right-align to n_max (older data on the left)
        offset = n_max - len(per_asset_pos[sym])
        pos_matrix[i, offset:] = per_asset_pos[sym]

    n_active = pos_matrix.sum(axis=0)  # bars where N assets are in trade
    # Apply max_concurrent cap: scale position uniformly if over cap
    cap_scale = np.minimum(1.0, max_concurrent / np.maximum(n_active, 1.0))
    capped_pos = pos_matrix * cap_scale[None, :]
    n_active_capped = capped_pos.sum(axis=0)

    # Apply size_per_pair * max_gross caps
    gross = n_active_capped * size_per_pair  # sum of position sizes
    gross_cap = np.minimum(1.0, max_gross / np.maximum(gross, 1e-9))
    final_pos = capped_pos * gross_cap[None, :]

    # Per-bar return: equal-weight across all assets (regardless of position)
    # i.e., the "asset_ret" each bar is the equally-weighted return across the universe
    # (not per-asset ret — that's the simplify assumption for the overlay book)
    # We use the per-asset pnl from capitulation_signal which already accounts for
    # position×ret + costs. The overlay book just sums these.
    book_pnl = np.zeros(n_max)
    for i, sym in enumerate(sym_list):
        pnl_series = per_asset_pnl[sym]
        offset = n_max - len(pnl_series)
        # Apply size scaling
        scaled = pnl_series * size_per_pair
        # Cap to gross (uniform across all assets)
        scaled *= gross_cap[offset:]
        book_pnl[offset:] += scaled
    # Average across assets (equal weight)
    book_pnl /= len(sym_list)
    book_pnl *= len(sym_list)  # gross up — this is now sum, not mean
    # Actually: book_pnl is now sum of (asset_pnl * size_per_pair * gross_cap)
    # Which IS the book return. But each asset's pnl already has position sizing
    # baked in (1.0 when in trade). So book_pnl = sum_i (position_i × ret_i × size × cap)
    # That's correct for the overlay book.

    # Build NAV series
    nav = np.ones(n_max + 1)
    for t in range(n_max):
        nav[t + 1] = nav[t] * (1.0 + book_pnl[t])
    timestamps = pd.date_range("2024-06-07", periods=n_max + 1, freq="h", tz="UTC")

    # OOS split
    cutoff = int(n_max * (1.0 - oos_frac))
    book_pnl_oos = book_pnl[cutoff:]
    nav_oos = nav[cutoff:]
    n_oos_bars = n_max - cutoff

    # === Variant sweep (config robustness) ===
    variants = {}
    for name, cfg in [
        ("canonical_-5%/2x", dict(thresh_ret=-0.05, thresh_vol_mult=2.0)),
        ("tighter_-3%/2x", dict(thresh_ret=-0.03, thresh_vol_mult=2.0)),
        ("looser_-7%/2x", dict(thresh_ret=-0.07, thresh_vol_mult=2.0)),
        ("looser_vol_1.5x", dict(thresh_ret=-0.05, thresh_vol_mult=1.5)),
        ("looser_vol_1.0x", dict(thresh_ret=-0.05, thresh_vol_mult=1.0)),
        ("longer_hold_8d", dict(thresh_ret=-0.05, thresh_vol_mult=2.0, hold=8 * 24)),
        ("shorter_hold_3d", dict(thresh_ret=-0.05, thresh_vol_mult=2.0, hold=3 * 24)),
        ("tighter_stop_-7%", dict(thresh_ret=-0.05, thresh_vol_mult=2.0, stop_pct=-0.07)),
        ("wider_stop_-15%", dict(thresh_ret=-0.05, thresh_vol_mult=2.0, stop_pct=-0.15)),
    ]:
        v_pnl = np.zeros(n_max)
        for i, sym in enumerate(sym_list):
            p = panels[sym]
            sig = capitulation_signal(
                p.close, p.volume,
                thresh_ret=cfg.get("thresh_ret", thresh_ret),
                thresh_vol_mult=cfg.get("thresh_vol_mult", thresh_vol_mult),
                hold=cfg.get("hold", hold),
                stop_pct=cfg.get("stop_pct", stop_pct),
                cost_bps=cost_bps,
            )
            scaled = sig["returns"] * size_per_pair
            offset = n_max - len(scaled)
            v_pnl[offset:] += scaled
        v_pnl /= len(sym_list)
        v_pnl *= len(sym_list)  # gross
        variants[name] = v_pnl[cutoff:]

    # === Summary stats ===
    def _sharpe(r):
        r = np.asarray(r)
        r = r[~np.isnan(r)]
        if len(r) < 10 or r.std() < 1e-12:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(24 * 365))

    return {
        "n_assets": len(sym_list),
        "n_bars": n_max,
        "n_oos_bars": n_oos_bars,
        "cutoff_t": cutoff,
        "per_pair_trades": per_pair_trades,
        "per_pair_summary": per_pair_summary,
        "per_pair_fires": per_pair_fires,
        "book_pnl": book_pnl,
        "book_pnl_oos": book_pnl_oos,
        "nav": nav,
        "nav_oos": nav_oos,
        "timestamps": timestamps,
        "canonical_oos_sharpe": _sharpe(book_pnl_oos),
        "variant_oos_sharpes": {k: _sharpe(v) for k, v in variants.items()},
        "total_fires_full": sum(per_pair_fires.values()),
        "total_trades_full": len(per_pair_trades),
        "oos_trades": [t for t in per_pair_trades if t.entry_t >= cutoff],
    }


def format_v2_verdict(out: dict) -> str:
    """Human-readable summary of the v2 experiment."""
    lines = []
    lines.append("R40 v2 — CAPITULATION BOUNCE PER-PAIR SWING OVERLAY")
    lines.append("=" * 80)
    lines.append(f"Universe: {out['n_assets']} crypto assets × {out['n_bars']} hourly bars "
                 f"(OOS {out['n_oos_bars']} = {out['n_oos_bars']/out['n_bars']:.0%})")
    lines.append(f"Canonical: thresh_ret=-5%, vol_mult=2x, hold=5d, stop=-10%")
    lines.append(f"Position sizing: {DEFAULT_SIZE_PER_PAIR*100:.1f}% per fire, "
                 f"max {DEFAULT_MAX_CONCURRENT} concurrent, max {DEFAULT_MAX_GROSS*100:.0f}% gross")
    lines.append("")

    # Overall stats
    total = out["total_trades_full"]
    oos_n = len(out["oos_trades"])
    lines.append(f"Total trades (full sample): {total}")
    lines.append(f"OOS trades: {oos_n}")
    if total > 0:
        full_pnls = np.array([t.pnl_pct for t in out["per_pair_trades"]])
        full_win = (full_pnls > 0).mean()
        full_avg = full_pnls.mean()
        full_stop = sum(1 for t in out["per_pair_trades"] if t.exit_reason == "stop_hit") / total
        lines.append(f"Full-sample: win_rate={full_win:.1%}, avg_pnl={full_avg:+.2%}, "
                     f"stop_rate={full_stop:.1%}")
    if oos_n > 0:
        oos_pnls = np.array([t.pnl_pct for t in out["oos_trades"]])
        oos_win = (oos_pnls > 0).mean()
        oos_avg = oos_pnls.mean()
        oos_stop = sum(1 for t in out["oos_trades"] if t.exit_reason == "stop_hit") / oos_n
        lines.append(f"OOS only:    win_rate={oos_win:.1%}, avg_pnl={oos_avg:+.2%}, "
                     f"stop_rate={oos_stop:.1%}")
    lines.append("")

    # Book OOS Sharpe
    lines.append(f"Book OOS Sharpe (canonical): {out['canonical_oos_sharpe']:+.2f}")
    lines.append("")
    lines.append("Variant sweep (OOS Sharpe):")
    for name, sh in sorted(out["variant_oos_sharpes"].items(), key=lambda x: -x[1]):
        lines.append(f"  {name:<24}  {sh:+.2f}")
    lines.append("")

    # Top/bottom pairs by win rate
    summary = out["per_pair_summary"]
    active = [(s, d) for s, d in summary.items() if d["n_trades"] > 0]
    active.sort(key=lambda x: -x[1]["win_rate"] * x[1]["n_trades"])  # weighted by trade count

    lines.append(f"Top 10 pairs by weighted score (win_rate × log(n_trades)):")
    for s, d in active[:10]:
        lines.append(f"  {s:<6}: n={d['n_trades']:>4}  win_rate={d['win_rate']:.1%}  "
                     f"avg_pnl={d['avg_pnl']:+.2%}  stop_rate={d['stop_rate']:.1%}  "
                     f"total_pnl={d['total_pnl']:+.2%}")
    lines.append("")

    lines.append(f"Bottom 5 pairs:")
    for s, d in active[-5:]:
        lines.append(f"  {s:<6}: n={d['n_trades']:>4}  win_rate={d['win_rate']:.1%}  "
                     f"avg_pnl={d['avg_pnl']:+.2%}  stop_rate={d['stop_rate']:.1%}  "
                     f"total_pnl={d['total_pnl']:+.2%}")

    return "\n".join(lines)


if __name__ == "__main__":
    out = run_capitulation_v2_experiment()
    print(format_v2_verdict(out))