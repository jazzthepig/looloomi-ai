"""
Centralised freqtrade baselines — single source of truth for parity checks.

Each strategy ported to Nautilus has a corresponding baseline file at:
    /Volumes/CometCloudAI/cometcloud-local/_reports/backtest/{strategy}_{YYYYMMDD}.md

Baselines here are aggregated for parity comparison in `runners/single_run.py`.

Tolerance bands are derived from STRATEGY_VALIDATION.md gate discipline:
- n_trades: ±30% — backtest variance + position flipping
- CAGR:    ±5pp — not too strict (allows structural differences)
- MaxDD:   ±5pp — not too strict (same)
- WinRate: ±8pp — backtest variance + entry timing
- Sharpe:  ±0.40 — looser for crypto where Sharpe distribution has fat tails
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class BaselineMetrics:
    """Freqtrade baseline for one strategy."""
    strategy: str
    source_report: str          # e.g. "CometCloudLongShortV4_20260626.md"
    pairs: tuple[str, ...]      # e.g. ("BTC", "ETH", "SOL", "BNB", "XRP")
    timeframe: str              # e.g. "4h"
    timerange: tuple[str, str]  # e.g. ("20250503", "20260312")
    fee: float                  # 0.0005 = 5bps
    starting_balance: float
    # Metrics
    n_trades: int
    cagr_pct: float
    max_dd_pct: float
    win_rate_pct: float
    sharpe: float
    # Optional
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    profit_factor: Optional[float] = None
    avg_hold: Optional[str] = None
    # Verdict from C
    c_verdict: str = "UNKNOWN"


# ── Tolerance bands ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Tolerance:
    """Per-metric tolerance for parity checks."""
    n_trades_pct: float = 0.30     # ±30% on trade count
    cagr_abs: float = 5.0           # ±5pp on CAGR
    max_dd_abs: float = 5.0         # ±5pp on MaxDD
    win_rate_abs: float = 8.0       # ±8pp on win rate
    sharpe_abs: float = 0.40        # ±0.40 on Sharpe

    def check(self, ours: dict, baseline: BaselineMetrics) -> dict:
        """Returns {metric: (delta, pass_bool)}."""
        return {
            "n_trades":   (ours["n_trades"] - baseline.n_trades,
                           abs(ours["n_trades"] - baseline.n_trades) <= baseline.n_trades * self.n_trades_pct),
            "CAGR_pct":   (ours["cagr_pct"] - baseline.cagr_pct,
                           abs(ours["cagr_pct"] - baseline.cagr_pct) <= self.cagr_abs),
            "MaxDD_pct":  (ours["max_dd_pct"] - baseline.max_dd_pct,
                           abs(ours["max_dd_pct"] - baseline.max_dd_pct) <= self.max_dd_abs),
            "WinRate_pct":(ours["win_rate_pct"] - baseline.win_rate_pct,
                           abs(ours["win_rate_pct"] - baseline.win_rate_pct) <= self.win_rate_abs),
            "Sharpe":     (ours["sharpe"] - baseline.sharpe,
                           abs(ours["sharpe"] - baseline.sharpe) <= self.sharpe_abs),
        }


DEFAULT_TOLERANCE = Tolerance()


# ── Strategies ported so far ────────────────────────────────────────────────

LS_V4 = BaselineMetrics(
    strategy="CometCloudLongShortV4",
    source_report="CometCloudLongShortV4_20260626.md",
    pairs=("BTC", "ETH", "SOL", "BNB", "XRP"),
    timeframe="4h",
    timerange=("20250503", "20260312"),
    fee=0.0005,
    starting_balance=10_000.0,
    n_trades=292,
    cagr_pct=-6.59,
    max_dd_pct=11.39,
    win_rate_pct=47.9,
    sharpe=-0.76,
    sortino=-2.29,
    calmar=-3.04,
    profit_factor=0.91,
    avg_hold="1 day, 8:02:00",
    c_verdict="NEEDS-WORK (Gate 6: CAGR -6.59% vs BTC-hold +24.74%)",
)

META_V4 = BaselineMetrics(
    strategy="CometCloudMetaV4",
    source_report="CometCloudMetaV4_20260626.md",
    pairs=("BTC", "ETH", "SOL"),
    timeframe="4h",
    timerange=("20250503", "20260312"),
    fee=0.001,
    starting_balance=10_000.0,
    n_trades=406,
    cagr_pct=-5.47,
    max_dd_pct=11.45,
    win_rate_pct=57.4,
    sharpe=-1.34,
    sortino=-15.37,
    calmar=-2.51,
    profit_factor=0.89,
    avg_hold="1 day, 23:20:00",
    c_verdict="NEEDS-WORK (Gate 6: CAGR -5.47% vs BTC-hold +25.86%)",
)


# ── Registry ────────────────────────────────────────────────────────────────

_BASELINES: dict[str, BaselineMetrics] = {
    "ls_v4":     LS_V4,
    "meta_v4":   META_V4,
}


def get_baseline(name: str) -> BaselineMetrics:
    if name not in _BASELINES:
        raise KeyError(f"unknown baseline {name!r}; known: {list(_BASELINES)}")
    return _BASELINES[name]


def list_baselines() -> list[str]:
    return list(_BASELINES.keys())


def register_baseline(metrics: BaselineMetrics) -> None:
    """Add or replace a baseline. Use for new strategies."""
    _BASELINES[metrics.strategy] = metrics


# ── CLI / smoke ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Known baselines:")
    for name in list_baselines():
        b = get_baseline(name)
        d = asdict(b)
        print(f"  {name}: {d['pairs']} @ {d['timeframe']} "
              f"n={d['n_trades']} CAGR={d['cagr_pct']}% "
              f"WR={d['win_rate_pct']}% Sharpe={d['sharpe']}")
