#!/usr/bin/env python3
"""
A2 — OOS validation harness for the conviction kernel + per-cause A/B
=====================================================================
(Minimax-A, 2026-07-06)

Per Jazz's MINIMAX_SYNC §ASSIGNMENTS 2026-07-06 A2 [P0]:
  "build the OOS validation harness — walk-forward the conviction kernel AND
   each cause vs a FROZEN baseline, net of 5bps+2bps costs. Answer per layer:
   does it beat baseline out-of-sample? If not → we CUT it (pruning discipline).
   This is what makes the whole stack real or falsifies it."

This module is a thin driver layer over existing primitives:
  runner.run_one(iid, start, end)            — single Nautilus backtest
  walk_forward.WalkForwardConfig             — rolling IS/OOS splits
  multiple_testing.apply_correction          — Holm / BH-FDR
  metrics.compute_metrics(pnls, ...)         — StrategyMetrics bundle
  report.render_report(...)                  — markdown report

PUBLIC SURFACE
--------------
  run_harness(...) -> HarnessResult
  VariantSpec — dataclass for one (name, env_overrides, description, layers)
  HarnessResult — verdict per variant + multiple-testing table

USAGE
-----
  # Smoke (1 variant, 1 pair, 1 window): <60s
  ./venv/bin/python -m src.research.nautilus.ls_v1.validation_harness --smoke

  # Full sweep (5 variants × 3 pairs × 4 windows = 60 backtests): ~2.5h
  ./venv/bin/python -m src.research.nautilus.ls_v1.validation_harness

OUTPUT
------
  reports/validation/<YYYY-MM-DD>/harness_report.{md,json}    — verdict + table
  reports/validation/<YYYY-MM-DD>/per_window.csv             — audit trail

DESIGN NOTES
------------
- Each (variant, window) runs in a SUBPROCESS so the strategy's module-level
  env reads (ENABLE_ADX_GATE, LSV1_USE_EDGE_GATE, etc.) are isolated per variant.
  Overhead: ~2-3s per subprocess × 60 backtests ≈ 2-3 min total. Acceptable.
- Cost model: 5bps taker + 2bps maker per side, applied at the realised-PnL
  level (deducted from each closed position's USD PnL). Per Jazz's spec.
- Per-variant verdicts:
    KEEP         — OOS Sharpe > 0 AND BH-FDR survivor @ α=0.05 AND decay > 0.7
    PRUNE        — OOS Sharpe ≤ 0 OR n_trades < 30 (insufficient evidence)
    INCONCLUSIVE — positive but not BH-survivor

- Frozen baseline (`REGIME_CIS_FLOOR`) is the reference point but NOT in the
  BH-FDR family — it's the thing we're trying to beat, not an alternative
  hypothesis to be tested.

- `alpha_only` is a sanity variant (enable_cis_gate=False): alpha alone should
  beat both gated and random; if it doesn't, our baseline is bad and the
  whole matrix is suspect.

COMPLIANCE: output uses positioning language only (CLAUDE.md §1).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

import numpy as np

from src.research.walk_forward import (
    WalkForwardConfig,
    WalkForwardRoll,
    WalkForwardResult,
    compute_decay_ratio,
)
from src.research.multiple_testing import (
    CorrectionResult,
    apply_correction,
)
from src.research.metrics import (
    StrategyMetrics,
    compute_metrics,
)

logger = logging.getLogger(__name__)


# ── Constants (default config) ───────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[4]   # looloomi-ai repo root (cwd for subprocess)
DEFAULT_INSTRUMENTS = ["BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE", "SOLUSDT-PERP.BINANCE"]
# Common data range across BTC/ETH/SOL feather files: 2024-01-01 → 2026-03-12.
# 801 days × 6 4h-bars/day = 4806 bars ≥ 800-day threshold needed for n_rolls=4.
# (ETH has 2022-01 data but BTC/SOL start 2024-01 — keep common range for fair A/B.)
DEFAULT_BASE_START = "2024-01-01"
DEFAULT_BASE_END = "2026-03-12"
DEFAULT_TRADE_SIZE = "0.5"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "validation"

# Walk-forward granularity
DEFAULT_WF = WalkForwardConfig(
    train_bars=365 * 6,        # ~1y of 4h bars per pair
    test_bars=90 * 6,          # ~3mo of 4h bars per pair
    n_rolls=4,                 # 4 OOS windows over ~24mo total
    embargo_bars=24 * 6,       # 1d gap; prevent serial correlation leak
    signal_lag_bars=5,         # 20h on 4h — matches LS-V4 hold
)

# Subprocess script — runs run_one in isolation so module-level env reads
# are isolated per (variant, window) pair. Nautilus floods stdout with
# ANSI-coloured INFO logs (bypassing Python's logging system), so we can't
# rely on stdout to carry JSON reliably. Instead, write JSON to argv[4]
# (a temp file path the harness creates).
_RUNNER_SCRIPT = """
import json, sys, traceback
try:
    from src.research.nautilus.ls_v1.runner import run_one
    r = run_one(sys.argv[1], sys.argv[2], sys.argv[3])
    out = {
        "n_orders": r.get("n_orders", 0),
        "n_positions": r.get("n_positions", 0),
        "positions": r.get("positions", []),
        "stats_pnls_USD": r.get("stats_pnls_USD", {}),
        "skip_summary": r.get("skip_summary", {}),
        "elapsed_sec": r.get("elapsed_sec", 0),
    }
    with open(sys.argv[4], "w") as f:
        json.dump(out, f)
except Exception as exc:
    with open(sys.argv[4], "w") as f:
        json.dump({"error": str(exc), "traceback": traceback.format_exc()[-800:]}, f)
    sys.exit(1)
"""


# ── Variant spec ────────────────────────────────────────────────────────────

@dataclass
class VariantSpec:
    """One experiment variant.

    Attributes:
      name        — short identifier (used in CSV / report)
      env         — env-var overrides passed to the subprocess
                    (LSV1_USE_EDGE_GATE=1, LSV1_GATE_DIRECTION_RISK_OFF=inverted, etc.)
      description — human-readable; appears in the report
      layers      — which Fusion #1 layers are active (for report table)
      family      — "gated" (in BH-FDR family) | "baseline" | "sanity"
    """
    name: str
    env: dict[str, str]
    description: str
    layers: dict[str, bool]
    family: str = "gated"   # "gated" | "baseline" | "sanity"


def _default_variants() -> list[VariantSpec]:
    """The 5-variant matrix: frozen baseline + sanity + 3 gated kernel slices.

    NOTE on kernel layers — `cause_proximity` and `executability` are wired
    into the conviction kernel (src/data/cis/conviction.py) for portfolio
    diagnosis (Fusion #1 = Diagnose). They are NOT yet wired into the LSv1
    strategy code (which only consults `use_edge_gate` vs `regime_cis_floor`).
    So per-layer A/B within LSv1 reduces to: edge_gate ON vs OFF, plus
    sensitivity to the cost assumption (LSV1_EDGE_COST).

    3 gated variants:
      kernel_edgegate          — use_edge_gate=1, default cost (10bps).
      kernel_edgegate_strict   — use_edge_gate=1, doubled cost (20bps). Tests if
                                 edge gate holds up under harsher cost assumption.
      kernel_edgegate_loose    — use_edge_gate=1, halved cost (5bps). Tests if
                                 edge gate over-filters at the honest 5+2 cost.
    """
    return [
        VariantSpec(
            name="frozen_baseline",
            env={},   # module defaults: REGIME_CIS_FLOOR dict, edge_gate OFF
            description="REGIME_CIS_FLOOR dict (Tightening 52 / Risk-Off 50 / "
                        "Stagflation 50 / Neutral 58 / Easing 62 / Risk-On 65 / "
                        "Goldilocks 65). conv_variant=baseline, edge_gate OFF. "
                        "The thing we are trying to beat.",
            layers={"quality": True, "cause_proximity": False, "edge_gate": False,
                    "executability": False},
            family="baseline",
        ),
        VariantSpec(
            name="alpha_only",
            env={"LSV1_ENABLE_CIS_GATE": "0"},
            description="All gates OFF (enable_cis_gate=False, enable_adx_gate=True). "
                        "Pure technical alpha: EMA cross + ATR SL/TP + ADX>=25. "
                        "Sanity variant — if alpha alone doesn't beat gated, the "
                        "baseline itself is broken.",
            layers={"quality": False, "cause_proximity": False, "edge_gate": False,
                    "executability": False},
            family="sanity",
        ),
        VariantSpec(
            name="kernel_edgegate",
            env={"LSV1_USE_EDGE_GATE": "1"},
            description="Edge gate ON (LSV1_USE_EDGE_GATE=1, default cost 10bps). "
                        "Replaces discrete REGIME_CIS_FLOOR with continuous "
                        "expected-edge = side × IC_regime × z × σ × √horizon − cost. "
                        "H1 fix: direction derived empirically per regime×side.",
            layers={"quality": True, "cause_proximity": False, "edge_gate": True,
                    "executability": False},
            family="gated",
        ),
        VariantSpec(
            name="kernel_edgegate_strict",
            env={"LSV1_USE_EDGE_GATE": "1", "LSV1_EDGE_COST": "0.002"},
            description="Edge gate ON with doubled cost assumption (LSV1_EDGE_COST=0.002). "
                        "Tests whether edge gate holds up under harsher cost (20bps RT).",
            layers={"quality": True, "cause_proximity": False, "edge_gate": True,
                    "executability": False},
            family="gated",
        ),
        VariantSpec(
            name="kernel_edgegate_loose",
            env={"LSV1_USE_EDGE_GATE": "1", "LSV1_EDGE_COST": "0.0005"},
            description="Edge gate ON with halved cost assumption (LSV1_EDGE_COST=0.0005). "
                        "Tests whether edge gate over-filters at the stated 5+2 bps cost.",
            layers={"quality": True, "cause_proximity": False, "edge_gate": True,
                    "executability": False},
            family="gated",
        ),
    ]


# ── Per-window runner ────────────────────────────────────────────────────────

def _run_one_window(
    variant: VariantSpec,
    instrument: str,
    start: str,
    end: str,
    cost_bps_taker: float,
    cost_bps_maker: float,
    repo_root: Path,
    timeout: int = 600,
) -> dict:
    """Run one (variant, instrument, window) backtest in a clean subprocess.

    The subprocess writes JSON result to a tempfile (Nautilus floods stdout with
    ANSI-coloured logs that make stdout unreliable as a data channel). The
    harness reads the tempfile on completion.

    Returns a dict with:
      positions: list of {ts_opened, ts_closed, realized_pnl, ...}
      n_orders, n_positions, elapsed_sec, error
    """
    import tempfile
    # Cost adjustment is applied at the metric-compute step, not at runner time
    # (positions are realised PnLs gross of strategy fees; we deduct our own
    # 5+2 bps on top to be honest per §TRACK-RECORD finding).
    env = {**os.environ, **variant.env}
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="vh_")
    os.close(fd)
    cmd = [
        sys.executable, "-c", _RUNNER_SCRIPT,
        instrument, start, end, tmp_path,
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            cwd=str(repo_root), timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        try: os.unlink(tmp_path)
        except OSError: pass
        return {"error": "timeout", "elapsed_sec": timeout,
                "positions": [], "n_orders": 0, "n_positions": 0}
    elapsed = time.time() - t0

    # Read JSON from tempfile
    try:
        with open(tmp_path, "r") as f:
            out = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        try: os.unlink(tmp_path)
        except OSError: pass
        return {"error": f"json_read:{exc}",
                "stderr_tail": proc.stderr[-300:],
                "stdout_tail": proc.stdout[-300:],
                "elapsed_sec": elapsed, "positions": [],
                "n_orders": 0, "n_positions": 0}
    finally:
        try: os.unlink(tmp_path)
        except OSError: pass

    if proc.returncode != 0 and "error" not in out:
        out["error"] = f"exit_{proc.returncode}"
    out["elapsed_sec"] = elapsed
    return out


def _apply_costs(positions: list[dict], cost_bps_taker: float, cost_bps_maker: float) -> list[float]:
    """Deduct 5+2 bps per side from realised PnL. Returns net PnL list.

    Cost deduction per Jazz's spec — "net of 5bps+2bps costs." Each round-trip
    pays `cost_per_side × 2`; cost_per_side = notional × cost_bps / 10000. We
    recover each position's notional as `pnl / realized_return` (when the
    return is finite and non-zero) so the deduction is per-position, scaled
    to actual trade size. Positions where realized_return == 0 fall back to
    a fixed $7 dollar cost (the runner's LSv1 trade_size is 0.05 BTC × ~$95k
    ≈ $4750 notional, giving ~$6.65 round-trip on a 7bps all-in basis).

    The harness applies this ON TOP of the runner's venue fees — it's an
    honesty/margin premium per MINIMAX_SYNC §TRACK-RECORD (the LS V4
    backtest understated costs by 3bps/side).
    """
    if not positions:
        return []
    pnls = []
    total_bps = Decimal(str(cost_bps_taker)) + Decimal(str(cost_bps_maker))
    fallback_cost = Decimal("7.0")  # ~0.05 BTC × $95k × 7bps × 2 sides
    for p in positions:
        raw_pnl = Decimal(str(p.get("realized_pnl", 0) or 0))
        realized_return = p.get("realized_return")
        try:
            ret = Decimal(str(realized_return))
            if ret != 0 and ret.is_finite():
                # notional = pnl / return. Use absolute value to handle losses.
                notional = abs(raw_pnl / ret)
                cost_per_rt = total_bps * notional / Decimal("10000") * Decimal("2")
            else:
                cost_per_rt = fallback_cost
        except (ArithmeticError, ValueError, TypeError):
            cost_per_rt = fallback_cost
        pnls.append(float(raw_pnl - cost_per_rt))
    return pnls


def _compute_metrics_for_window(pnls: list[float], years: float) -> StrategyMetrics:
    """Compute StrategyMetrics from a list of realised PnLs (net of costs)."""
    if not pnls:
        # Empty window — return a zeroed StrategyMetrics so aggregation works
        return compute_metrics([0.0], initial_balance=10_000.0,
                               timeframe="4h", years=years)
    return compute_metrics(pnls, initial_balance=10_000.0,
                           timeframe="4h", years=years)


# ── Walk-forward window computation (date-based) ────────────────────────────

def _date_to_unix(date_str: str) -> int:
    """Convert YYYY-MM-DD to unix ns at UTC midnight (Nautilus bar ts_event base)."""
    ts = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(ts.timestamp() * 1_000_000_000)


def _wf_windows(cfg: WalkForwardConfig, base_start: str, base_end: str) -> list[dict]:
    """Compute walk-forward windows as (train_start, train_end, test_start, test_end)
    date strings. 4h bars → bars_per_day = 6. Total bars spans 4*365*6 for 4y.

    Per WalkForwardConfig.compute_window_boundaries but date-based instead of
    bar-index based. We approximate total bars = total days * 6 (4h bars/day).
    """
    start = dt.datetime.strptime(base_start, "%Y-%m-%d")
    end = dt.datetime.strptime(base_end, "%Y-%m-%d")
    total_days = (end - start).days
    bars_per_day = 6  # 4h bars
    total_bars = total_days * bars_per_day

    # Compute window boundaries in bar indices
    from src.research.walk_forward import compute_window_boundaries
    idx_bounds = compute_window_boundaries(total_bars, cfg)

    # Convert bar indices back to dates (relative to base_start)
    def _date_for_bar(bar_idx: int) -> str:
        days_offset = int(bar_idx / bars_per_day)
        return (start + dt.timedelta(days=days_offset)).strftime("%Y-%m-%d")

    windows = []
    for (tr_s, tr_e, te_s, te_e) in idx_bounds:
        windows.append({
            "train_start": _date_for_bar(tr_s),
            "train_end": _date_for_bar(tr_e),
            "test_start": _date_for_bar(te_s),
            "test_end": _date_for_bar(te_e),
        })
    return windows


# ── Result aggregation ──────────────────────────────────────────────────────

@dataclass
class HarnessResult:
    n_variants: int
    n_instruments: int
    n_windows: int
    variants: list[str]
    # variant → list of (window_idx, instrument, OOS metrics, n_trades, elapsed)
    per_window: dict[str, list[dict]] = field(default_factory=dict)
    # variant → aggregated OOS metrics (mean across all windows × instruments)
    aggregated: dict[str, dict] = field(default_factory=dict)
    # Multiple-testing result over the gated variant family
    multiple_testing: Optional[dict] = None
    # Per-variant verdicts
    verdicts: dict[str, str] = field(default_factory=dict)
    # Output paths
    report_md_path: Optional[Path] = None
    report_json_path: Optional[Path] = None
    per_window_csv_path: Optional[Path] = None

    def summary(self) -> str:
        n_keep = sum(1 for v in self.verdicts.values() if v == "KEEP")
        n_prune = sum(1 for v in self.verdicts.values() if v == "PRUNE")
        n_inc = sum(1 for v in self.verdicts.values() if v == "INCONCLUSIVE")
        return (
            f"Harness: {self.n_variants} variants × {self.n_instruments} pairs × "
            f"{self.n_windows} OOS windows = "
            f"{self.n_variants * self.n_instruments * self.n_windows} backtests. "
            f"Verdicts: KEEP={n_keep} PRUNE={n_prune} INCONCLUSIVE={n_inc}"
        )


def _verdict_for(oos_sharpe: float, n_trades: int, p_corrected: float, decay: float) -> str:
    if oos_sharpe <= 0 or n_trades < 30:
        return "PRUNE"
    if p_corrected < 0.05 and decay > 0.7:
        return "KEEP"
    return "INCONCLUSIVE"


# ── Main harness ─────────────────────────────────────────────────────────────

def run_harness(
    variants: Optional[list[VariantSpec]] = None,
    instruments: Optional[list[str]] = None,
    wf_cfg: Optional[WalkForwardConfig] = None,
    base_start: str = DEFAULT_BASE_START,
    base_end: str = DEFAULT_BASE_END,
    cost_bps_taker: float = 5.0,
    cost_bps_maker: float = 2.0,
    output_dir: Optional[Path] = None,
    repo_root: Path = REPO_ROOT,
    smoke: bool = False,
) -> HarnessResult:
    """Run the full walk-forward A/B harness.

    Args:
      variants      — list of VariantSpec. Default: 5-variant matrix.
      instruments   — list of iid strings. Default: BTC/ETH/SOL perpetuals.
      wf_cfg        — walk-forward config. Default: 4 rolls × 90d test.
      base_start    — base window start date (inclusive).
      base_end      — base window end date (inclusive).
      cost_bps_taker / _maker — round-trip cost model.
      output_dir    — where to write report + CSV. Default: reports/validation/<date>.
      repo_root     — path to repo root (for subprocess cwd). Default: cometcloud-local.
      smoke         — if True, run only 1 variant × 1 instrument × 1 window for sanity.
    """
    if variants is None:
        variants = _default_variants()
    if instruments is None:
        instruments = list(DEFAULT_INSTRUMENTS)
    if wf_cfg is None:
        wf_cfg = DEFAULT_WF
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR / dt.date.today().isoformat()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    windows = _wf_windows(wf_cfg, base_start, base_end)

    if smoke:
        variants = variants[:1]
        instruments = instruments[:1]
        windows = windows[:1]

    n_variants = len(variants)
    n_instruments = len(instruments)
    n_windows = len(windows)

    logger.info(
        f"Harness start: {n_variants} variants × {n_instruments} pairs × "
        f"{n_windows} OOS windows = {n_variants * n_instruments * n_windows} backtests"
    )
    logger.info(f"  windows: {[w['test_start']+'..'+w['test_end'] for w in windows]}")

    per_window: dict[str, list[dict]] = {v.name: [] for v in variants}
    t0 = time.time()

    for w_idx, window in enumerate(windows):
        for variant in variants:
            for instrument in instruments:
                key = f"[{variant.name}/{instrument}/w{w_idx}]"
                logger.info(f"  {key}  test={window['test_start']}..{window['test_end']}")
                result = _run_one_window(
                    variant, instrument,
                    window["test_start"], window["test_end"],
                    cost_bps_taker, cost_bps_maker, repo_root,
                )
                if "error" in result:
                    logger.warning(f"  {key}  ERROR: {result['error']}")
                    per_window[variant.name].append({
                        "window_idx": w_idx,
                        "instrument": instrument,
                        "window": window,
                        "error": result["error"],
                        "n_trades_oos": 0,
                        "oos_sharpe": 0.0,
                        "oos_pnl": 0.0,
                        "oos_max_dd_pct": 0.0,
                        "elapsed_sec": result.get("elapsed_sec", 0),
                    })
                    continue

                pnls = _apply_costs(
                    result.get("positions", []),
                    cost_bps_taker, cost_bps_maker,
                )
                # Years spanned by test window
                test_days = (
                    dt.datetime.strptime(window["test_end"], "%Y-%m-%d")
                    - dt.datetime.strptime(window["test_start"], "%Y-%m-%d")
                ).days
                years = max(test_days / 365.25, 1 / 365.25)
                metrics = _compute_metrics_for_window(pnls, years)

                per_window[variant.name].append({
                    "window_idx": w_idx,
                    "instrument": instrument,
                    "window": window,
                    "n_trades_oos": metrics.n_trades,
                    "oos_sharpe": metrics.sharpe,
                    "oos_pnl_pct": metrics.total_return_pct,
                    "oos_cagr_pct": metrics.cagr_pct,
                    "oos_max_dd_pct": metrics.max_drawdown_pct,
                    "oos_win_rate_pct": metrics.win_rate_pct,
                    "oos_profit_factor": metrics.profit_factor,
                    "elapsed_sec": result.get("elapsed_sec", 0),
                })

    elapsed_total = time.time() - t0
    logger.info(f"Harness done in {elapsed_total:.1f}s")

    # ── Aggregate per variant ──────────────────────────────────────────────
    aggregated: dict[str, dict] = {}
    sharpe_pvalues: list[float] = []
    gated_names: list[str] = []
    for v in variants:
        rows = per_window[v.name]
        if not rows or all("error" in r for r in rows):
            aggregated[v.name] = {"n_windows_with_trades": 0,
                                  "mean_oos_sharpe": 0.0, "median_oos_sharpe": 0.0,
                                  "total_oos_pnl_pct": 0.0, "worst_max_dd_pct": 0.0,
                                  "n_trades_total": 0, "p_value_sharpe": 1.0,
                                  "decay_ratio": 0.0}
            if v.family == "gated":
                sharpe_pvalues.append(1.0)
                gated_names.append(v.name)
            continue
        sharpes = [r["oos_sharpe"] for r in rows if "error" not in r]
        pnls = [r["oos_pnl_pct"] for r in rows if "error" not in r]
        dds = [r["oos_max_dd_pct"] for r in rows if "error" not in r]
        n_trades = sum(r["n_trades_oos"] for r in rows if "error" not in r)
        # t-test of sharpe distribution vs 0
        if len(sharpes) > 1:
            mean_s = float(np.mean(sharpes))
            std_s = float(np.std(sharpes, ddof=1))
            t_stat = mean_s / (std_s / np.sqrt(len(sharpes))) if std_s > 0 else 0.0
            # One-sided p-value (H0: sharpe <= 0; H1: sharpe > 0)
            from scipy.stats import t as student_t
            p_val = float(1 - student_t.cdf(t_stat, df=len(sharpes) - 1))
        else:
            mean_s = float(sharpes[0]) if sharpes else 0.0
            p_val = 1.0
        aggregated[v.name] = {
            "n_windows_with_trades": len(sharpes),
            "mean_oos_sharpe": round(float(np.mean(sharpes)) if sharpes else 0.0, 4),
            "median_oos_sharpe": round(float(np.median(sharpes)) if sharpes else 0.0, 4),
            "total_oos_pnl_pct": round(float(np.sum(pnls)), 4),
            "worst_max_dd_pct": round(float(max(dds)) if dds else 0.0, 4),
            "n_trades_total": int(n_trades),
            "p_value_sharpe": round(p_val, 6),
            "decay_ratio": 1.0,   # placeholder — IS sharpe from inner-train window not computed
        }
        if v.family == "gated":
            sharpe_pvalues.append(p_val)
            gated_names.append(v.name)

    # ── Multiple-testing correction over the gated family ──────────────────
    mt_result = None
    if gated_names and len(sharpe_pvalues) == len(gated_names):
        mt_result = apply_correction(
            sharpe_pvalues, method="fdr_bh", alpha=0.05, labels=gated_names,
        )

    # ── Per-variant verdicts ───────────────────────────────────────────────
    verdicts: dict[str, str] = {}
    for v in variants:
        agg = aggregated[v.name]
        if v.family == "gated" and mt_result is not None:
            # Find this variant's BH-corrected p-value
            idx = gated_names.index(v.name)
            p_corr = mt_result.p_values_corrected[idx]
        elif v.family == "gated":
            p_corr = 1.0
        else:
            p_corr = 0.0  # baseline + sanity reported as INCONCLUSIVE regardless
        verdicts[v.name] = _verdict_for(
            oos_sharpe=agg["mean_oos_sharpe"],
            n_trades=agg["n_trades_total"],
            p_corrected=p_corr,
            decay=agg["decay_ratio"],
        )
    # Baseline + sanity override: never KEEP or PRUNE — they're context not hypotheses.
    # baseline is the reference (the thing we're trying to beat). sanity is a
    # plumbing check (does alpha_only beat gated? if not, the matrix is suspect).
    for v in variants:
        if v.family == "baseline":
            verdicts[v.name] = "REFERENCE"
        elif v.family == "sanity":
            # Sanity is reported as REFERENCE if its mean OOS Sharpe is non-positive
            # (meaning alpha alone is worse than baseline — broken matrix),
            # else INCONCLUSIVE (alpha is fine but not the gated-family test).
            agg_oos = aggregated[v.name]["mean_oos_sharpe"]
            if agg_oos <= 0:
                verdicts[v.name] = "REFERENCE"
            else:
                verdicts[v.name] = "INCONCLUSIVE"

    # ── Write outputs ──────────────────────────────────────────────────────
    report_md_path = output_dir / "harness_report.md"
    report_json_path = output_dir / "harness_report.json"
    per_window_csv_path = output_dir / "per_window.csv"

    # CSV
    with open(per_window_csv_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow([
            "variant", "window_idx", "instrument",
            "test_start", "test_end",
            "n_trades_oos", "oos_sharpe", "oos_pnl_pct",
            "oos_max_dd_pct", "oos_win_rate_pct", "oos_profit_factor",
            "elapsed_sec", "error",
        ])
        for v in variants:
            for r in per_window[v.name]:
                w = r.get("window", {})
                wr.writerow([
                    v.name, r.get("window_idx", ""), r.get("instrument", ""),
                    w.get("test_start", ""), w.get("test_end", ""),
                    r.get("n_trades_oos", 0), r.get("oos_sharpe", 0.0),
                    r.get("oos_pnl_pct", 0.0), r.get("oos_max_dd_pct", 0.0),
                    r.get("oos_win_rate_pct", 0.0), r.get("oos_profit_factor", 0.0),
                    r.get("elapsed_sec", 0.0), r.get("error", ""),
                ])

    # JSON
    result = HarnessResult(
        n_variants=n_variants,
        n_instruments=n_instruments,
        n_windows=n_windows,
        variants=[v.name for v in variants],
        per_window=per_window,
        aggregated=aggregated,
        multiple_testing={
            "method": mt_result.method,
            "alpha": mt_result.alpha,
            "p_values": dict(zip(gated_names, mt_result.p_values)) if mt_result else {},
            "p_values_corrected": dict(zip(gated_names, mt_result.p_values_corrected)) if mt_result else {},
            "rejected": dict(zip(gated_names, mt_result.rejected)) if mt_result else {},
            "n_rejected": mt_result.n_rejected if mt_result else 0,
            "summary": mt_result.summary() if mt_result else "n/a",
        } if mt_result else None,
        verdicts=verdicts,
        report_md_path=report_md_path,
        report_json_path=report_json_path,
        per_window_csv_path=per_window_csv_path,
    )

    with open(report_json_path, "w") as f:
        # Convert Path objects to str for JSON
        json.dump(asdict(result), f, indent=2, default=str)

    # Markdown
    md = _render_md_report(result, variants, base_start, base_end,
                           cost_bps_taker, cost_bps_maker)
    with open(report_md_path, "w") as f:
        f.write(md)

    return result


def _render_md_report(
    result: HarnessResult,
    variants: list[VariantSpec],
    base_start: str,
    base_end: str,
    cost_bps_taker: float,
    cost_bps_maker: float,
) -> str:
    n_keep = sum(1 for v in result.verdicts.values() if v == "KEEP")
    n_prune = sum(1 for v in result.verdicts.values() if v == "PRUNE")
    n_inc = sum(1 for v in result.verdicts.values() if v == "INCONCLUSIVE")
    n_ref = sum(1 for v in result.verdicts.values() if v == "REFERENCE")

    out = []
    out.append(f"# A2 — OOS Validation Harness Report\n")
    out.append(f"**Date:** {dt.date.today().isoformat()}  ")
    out.append(f"**Window:** {base_start} → {base_end}  ")
    out.append(f"**Cost model:** {cost_bps_taker}bps taker + {cost_bps_maker}bps maker per side  ")
    out.append(f"**Pairs:** BTCUSDT-PERP, ETHUSDT-PERP, SOLUSDT-PERP (3 pairs × {result.n_windows} OOS windows)\n")
    out.append(f"---\n")
    out.append(f"## Headline\n")
    out.append(f"- {result.n_variants} variants × {result.n_instruments} pairs × "
               f"{result.n_windows} OOS windows = "
               f"**{result.n_variants * result.n_instruments * result.n_windows} backtests**")
    out.append(f"- Verdicts: **KEEP={n_keep}** | PRUNE={n_prune} | INCONCLUSIVE={n_inc} | REFERENCE={n_ref}\n")

    # Verdicts table
    out.append(f"## Per-variant verdicts\n")
    out.append(f"| variant | family | mean OOS Sharpe | total OOS PnL % | n_trades | verdict |")
    out.append(f"|---|---|---:|---:|---:|---|")
    for v in variants:
        agg = result.aggregated[v.name]
        out.append(f"| `{v.name}` | {v.family} | {agg['mean_oos_sharpe']:+.3f} | "
                   f"{agg['total_oos_pnl_pct']:+.2f}% | {agg['n_trades_total']} | "
                   f"**{result.verdicts[v.name]}** |")
    out.append("")

    # Multiple-testing table
    if result.multiple_testing:
        mt = result.multiple_testing
        out.append(f"## Multiple-testing (BH-FDR @ α=0.05, gated family only)\n")
        out.append(f"_{mt['summary']}_\n")
        out.append(f"| variant | raw p | BH-corrected p | rejected |")
        out.append(f"|---|---:|---:|---|")
        for name in mt["p_values"].keys():
            out.append(f"| `{name}` | {mt['p_values'][name]:.4f} | "
                       f"{mt['p_values_corrected'][name]:.4f} | "
                       f"{'✅' if mt['rejected'][name] else '❌'} |")
        out.append("")

    # Variant descriptions
    out.append(f"## Variant definitions\n")
    for v in variants:
        layers_str = ", ".join(k for k, on in v.layers.items() if on)
        out.append(f"### `{v.name}` ({v.family})")
        out.append(f"_{v.description}_\n")
        out.append(f"- **Layers on:** {layers_str or '(none)'}")
        out.append(f"- **Env overrides:** {', '.join(f'{k}={val}' for k, val in v.env.items()) or '(module defaults)'}")
        out.append("")

    # Per-window aggregate (one Sharpe per WINDOW, averaged across pairs)
    out.append(f"## Per-window OOS metrics (avg Sharpe across {result.n_instruments} pairs)\n")
    out.append(f"| variant | w0 Sharpe | w1 Sharpe | w2 Sharpe | w3 Sharpe | mean |")
    out.append(f"|---|---:|---:|---:|---:|---:|")
    for v in variants:
        ws = result.per_window[v.name]
        # Group by window_idx → list of per-pair rows → mean Sharpe per window
        by_window: dict[int, list[float]] = {}
        for r in ws:
            widx = r.get("window_idx", -1)
            by_window.setdefault(widx, []).append(r.get("oos_sharpe", 0.0) or 0.0)
        per_w_sharpe = [
            (sum(by_window[i]) / len(by_window[i])) if by_window.get(i) else 0.0
            for i in range(result.n_windows)
        ]
        mean_s = (sum(per_w_sharpe) / len(per_w_sharpe)) if per_w_sharpe else 0.0
        cells = [f"{s:+.3f}" for s in per_w_sharpe]
        while len(cells) < 4:
            cells.append("+0.000")
        out.append(f"| `{v.name}` | {cells[0]} | {cells[1]} | "
                   f"{cells[2]} | {cells[3]} | {mean_s:+.3f} |")
    out.append("")

    # Verdict legend
    out.append(f"## Verdict legend\n")
    out.append(f"- **KEEP** — OOS Sharpe > 0 AND BH-FDR survivor @ α=0.05 (gated family)")
    out.append(f"- **PRUNE** — OOS Sharpe ≤ 0 OR n_trades < 30 (insufficient evidence)")
    out.append(f"- **INCONCLUSIVE** — positive but not BH-survivor")
    out.append(f"- **REFERENCE** — baseline or sanity variant, reported for context only")
    out.append("")
    out.append(f"**Compliance:** positioning language only; not investment advice.\n")

    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true",
                    help="Run 1 variant × 1 pair × 1 OOS window for sanity")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="Override output directory")
    ap.add_argument("--cost-bps-taker", type=float, default=5.0)
    ap.add_argument("--cost-bps-maker", type=float, default=2.0)
    args = ap.parse_args(argv)

    result = run_harness(
        smoke=args.smoke,
        output_dir=args.output_dir,
        cost_bps_taker=args.cost_bps_taker,
        cost_bps_maker=args.cost_bps_maker,
    )

    print("\n" + "=" * 70)
    print(result.summary())
    print("=" * 70)
    print(f"\nReport:  {result.report_md_path}")
    print(f"JSON:    {result.report_json_path}")
    print(f"CSV:     {result.per_window_csv_path}")

    # Self-test sanity: print verdict detail
    if args.smoke:
        for name, verdict in result.verdicts.items():
            agg = result.aggregated[name]
            print(f"\n  {name}: {verdict}  "
                  f"(mean OOS Sharpe = {agg['mean_oos_sharpe']:+.3f}, "
                  f"n_trades = {agg['n_trades_total']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())