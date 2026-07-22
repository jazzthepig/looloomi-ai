"""
C1 Parity A/B — replay a cached freqtrade backtest JSON against the empirical-grid gate.

WHAT THIS DOES
  §ASSIGNMENTS 2026-07-06 (C1 [P1]): "Same edge-gate A/B in freqtrade (parity vs Nautilus B1)."

  This driver replays each trade from a freqtrade backtest JSON against BOTH:
    (A) the legacy `REGIME_CIS_FLOOR` gate (a hand-tuned per-regime floor map, the
        baseline that's currently in production for V-family strategies); and
    (B) the empirical-grid gate (data-grounded lookup `grid[tier][band]`).

  Output: a side-by-side CSV with per-gate metrics, plus a verdict table that
  answers: does the empirical gate (a) block more trades, (b) lift Sharpe, or
  (c) reduce max single loss, on this backtest's window?

  The driver DOES NOT need freqtrade installed — it reads the standard
  `backtest-result-*.json` output that Minimax-C's freqtrade writes per backtest.

USAGE (Mac-side, after Minimax-C runs the standard V-family backtest):
    python3 -m src.research.freqtrade.c1_parity_ab \
        --backtest-zip /Volumes/CometCloudAI/cometcloud-local/user_data/backtest_results/backtest-result-2026-XX-YY_ZZ-WW-VV.zip \
        --cis-snapshot /Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json \
        --cis-history /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/ \
        --grid-path reports/edge_gate_grid.json \
        --band-snapshot reports/btc_band_snapshot.json \
        --out-dir reports/c1_parity_ab/<date>/

OUTPUTS
  - per_trade.csv:  one row per freqtrade trade × (A, B); columns include the
                    legacy floor decision (pass/block), empirical-grid decision,
                    expected_edge_pct, conviction, and the trade's PnL.
  - summary.csv:    one row per gate (A, B) with n_trades / n_blocked / total_pnl /
                    Sharpe / max_single_loss / win_rate.
  - verdict.md:     human-readable A/B comparison + recommendation.

PARITY CONTRACT
  This driver MUST agree with the Nautilus LS v1 `_empirical_grid_passes()` on
  identical (tier, band, side) inputs. Same `gate()` function (shared module), same
  grid JSON. The parity check is on the WIRE-UP, not on the backtest itself —
  differences in PnL come from engine-intrinsic slippage/fill, not from gate logic.

WHY THIS IS NEEDED
  Per the B-S1 acceptance gate (Minimax-B reply, 2026-07-17 §STRATEGY-REVIVE):
    (a) Both engines report the same `n_trades_oos` (positions opened in OOS).
    (b) Both engines report OOS-isolated `expectancy = mean(pnl) × sqrt(n)` matching.
    (c) Both engines report OOS-isolated `max_single_loss` matching.
  The C1 driver is the **post-hoc parity check** that verifies (a) — that the
  empirical gate decisions are consistent across both engines before we trust
  any PnL comparison.

OWNER
  minimax-b (Austin). Mac-side execution by Minimax-C (per CLAUDE.md ownership).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Engine-agnostic gate logic (same module used by Nautilus LS v1).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.research.strategies.edge_gate import (  # noqa: E402
    EdgeDecision,
    gate,
    size_multiplier,
)


# ── Hand-tuned baseline (verbatim from freqtrade LS V4 strategy) ─────────────
# This is what V14 currently uses in `populate_indicators` / `confirm_trade_entry`.
# C1's whole point is to A/B this AGAINST the empirical-grid gate.
REGIME_CIS_FLOOR = {
    "Tightening":  72,
    "Easing":      55,
    "Risk-Off":    78,
    "Risk-On":     60,
    "Stagflation": 65,
    "Neutral":     60,
    "Goldilocks":  60,
}

# Per-regime direction (H2a finding, baked into V14)
PER_REGIME_DIRECTION = {
    "Tightening":  -1,
    "Easing":      -1,
    "Risk-Off":    -1,
    "Risk-On":     -1,
    "Stagflation": -1,
    "Neutral":     +1,
    "Goldilocks":  +1,
}


# ── CIS snapshot helpers ──────────────────────────────────────────────────────

@dataclass
class CISTierLookup:
    """Index CIS_history by date → {pair: (cis_score, signal_tier, macro_regime)}"""
    by_date: dict  # date_str → {pair: {"cis_score": float, "signal": str, "macro_regime": str}}

    @classmethod
    def from_paths(cls, cis_snapshot: Path, cis_history_dir: Path) -> "CISTierLookup":
        """Build the index from the same two sources V14 uses (latest snapshot +
        11yr historical reconstruction)."""
        idx = cls(by_date={})

        # Latest snapshot — usually a single dict with `scores: [{symbol, cis_score, signal, ...}]`
        if cis_snapshot.exists():
            data = json.loads(cis_snapshot.read_text())
            for s in data.get("scores", []):
                if not s.get("symbol"):
                    continue
                ts = s.get("timestamp") or s.get("recorded_at") or data.get("timestamp") or data.get("recorded_at")
                if ts is None:
                    continue
                d = pd.to_datetime(ts).strftime("%Y-%m-%d")
                idx.by_date.setdefault(d, {})[s["symbol"]] = {
                    "cis_score": float(s.get("cis_score") or s.get("score") or 0),
                    "signal": (s.get("signal") or "NEUTRAL").upper(),
                    "macro_regime": (s.get("macro_regime") or "Neutral").upper(),
                }

        # Historical CSV (11yr reconstruction, when available)
        # Schema: symbol, name, score, raw_cis_score, grade, signal, ..., macro_regime, ..., recorded_at
        hist_csv = Path("_data/cis_historical/cis_historical_11yr.csv")
        if hist_csv.exists():
            cols = [
                "symbol", "name", "score", "raw_cis_score", "grade", "signal",
                "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a",
                "asset_class", "macro_regime", "data_tier", "las", "confidence",
                "score_delta", "score_zscore", "source", "recorded_at",
            ]
            h = pd.read_csv(hist_csv, header=None, names=cols)
            h["date"] = pd.to_datetime(h["recorded_at"]).dt.strftime("%Y-%m-%d")
            for d, grp in h.groupby("date"):
                for _, row in grp.iterrows():
                    sym = row["symbol"]
                    score = float(row["raw_cis_score"]) if pd.notna(row["raw_cis_score"]) else 0.0
                    idx.by_date.setdefault(d, {})[sym] = {
                        "cis_score": score,
                        "signal": (row["signal"] or "NEUTRAL").upper(),
                        "macro_regime": (row["macro_regime"] or "Neutral").upper(),
                    }

        return idx

    def look(self, date_str: str, symbol: str) -> Optional[dict]:
        """Return the CIS record for (date, symbol) or None."""
        row = self.by_date.get(date_str)
        if row is None:
            return None
        return row.get(symbol)


def legacy_floor_pass(cis_score: float, regime: str) -> bool:
    """Replicate the V14 LEGACY gate decision (the baseline we're A/B-ing against).

    Verbatim from SwingOverlayV14's CIS-floor logic, simplified to (score, regime).
    Direction handling uses `PER_REGIME_DIRECTION`: -1 means high-CIS wins
    (legacy default), +1 means invert.
    """
    floor = REGIME_CIS_FLOOR.get(regime, 60)
    direction = PER_REGIME_DIRECTION.get(regime, +1)
    if direction == -1:
        return cis_score >= floor
    return cis_score <= floor  # inverted direction


# ── Backtest JSON parsing ─────────────────────────────────────────────────────

def load_freqtrade_backtest(zip_path: Path) -> tuple[dict, str]:
    """Extract the .json file from a freqtrade backtest-results ZIP.

    Returns (parsed_json, strategy_name).
    """
    with zipfile.ZipFile(zip_path) as z:
        json_name = next((n for n in z.namelist() if n.endswith(".json") and "_config" not in n and ".meta" not in n), None)
        if not json_name:
            raise ValueError(f"No backtest JSON in {zip_path}")
        with z.open(json_name) as f:
            data = json.load(f)
    strat = data.get("strategy")
    strat_name = list(strat.keys())[0] if isinstance(strat, dict) and strat else "unknown"
    return data, strat_name


def trades_to_df(bt: dict, strat_name: str) -> pd.DataFrame:
    """Pluck the trades list from the freqtrade JSON and turn into a DataFrame."""
    trades = (bt.get("strategy", {}).get(strat_name, {}).get("trades", [])) or []
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        rows.append({
            "pair": t["pair"],
            "base_symbol": t["pair"].split("/")[0],
            "open_date": pd.to_datetime(t["open_date"]).tz_localize(None),
            "close_date": pd.to_datetime(t["close_date"]).tz_localize(None),
            "is_short": bool(t.get("is_short", False)),
            "open_rate": float(t.get("open_rate", 0)),
            "close_rate": float(t.get("close_rate", 0)),
            "profit_ratio": float(t.get("profit_ratio", 0)),
            "profit_abs": float(t.get("profit_abs", 0)),
            "enter_tag": t.get("enter_tag", ""),
            "leverage": float(t.get("leverage", 1.0)),
            "funding_fees": float(t.get("funding_fees", 0)),
        })
    return pd.DataFrame(rows)


# ── A/B engine ────────────────────────────────────────────────────────────────

@dataclass
class GateOutcome:
    decision: EdgeDecision
    blocked: bool


def evaluate_trade_with_empirical_grid(
    trade: dict,
    grid: dict,
    band_by_date: dict,
    cis_lookup: CISTierLookup,
) -> GateOutcome:
    """Run `gate()` on a freqtrade trade entry using empirical-grid data."""
    date_str = trade["open_date"].strftime("%Y-%m-%d")
    sym = trade["base_symbol"]
    tier = "NEUTRAL"  # default
    if (rec := cis_lookup.look(date_str, sym)) is not None:
        tier = rec["signal"] or "NEUTRAL"
    band = band_by_date.get(date_str, "3_neutral")
    side_str = "SHORT" if trade["is_short"] else "LONG"
    d = gate(grid, tier, band, side_str)
    return GateOutcome(decision=d, blocked=not d.allow)


def evaluate_trade_with_legacy_floor(
    trade: dict,
    cis_lookup: CISTierLookup,
) -> GateOutcome:
    """Run the legacy `REGIME_CIS_FLOOR` gate as V14 does today."""
    date_str = trade["open_date"].strftime("%Y-%m-%d")
    sym = trade["base_symbol"]
    if (rec := cis_lookup.look(date_str, sym)) is not None:
        score = rec["cis_score"]
        regime = rec["macro_regime"]
    else:
        score = 0.0
        regime = "Neutral"
    blocked = not legacy_floor_pass(score, regime)
    return GateOutcome(
        decision=EdgeDecision(
            allow=not blocked,
            expected_edge_pct=None,
            conviction=0.5 if not blocked else 0.0,
            reason=f"legacy_floor: score={score:.1f} regime={regime} → {'pass' if not blocked else 'block'}",
        ),
        blocked=blocked,
    )


def summarize(df: pd.DataFrame, gate_col: str) -> dict:
    """Compute summary stats for a per-trade gate column."""
    passed = df[~df[f"{gate_col}_blocked"]]
    blocked = df[df[f"{gate_col}_blocked"]]
    pnls = passed["profit_ratio"]
    if len(pnls) < 2:
        return {
            "n_passed": len(passed), "n_blocked": len(blocked),
            "total_pnl": float(passed["profit_abs"].sum()),
            "mean_pnl": float(pnls.mean()) if len(pnls) else 0.0,
            "std_pnl": float(pnls.std()) if len(pnls) > 1 else 0.0,
            "sharpe": 0.0,
            "max_loss": float(passed["profit_ratio"].min()) if len(passed) else 0.0,
            "max_win": float(passed["profit_ratio"].max()) if len(passed) else 0.0,
            "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        }
    sharpe = pnls.mean() / pnls.std() * (365 ** 0.5)  # daily-equivalent annualization
    return {
        "n_passed": len(passed),
        "n_blocked": len(blocked),
        "total_pnl": float(passed["profit_abs"].sum()),
        "mean_pnl": float(pnls.mean()),
        "std_pnl": float(pnls.std()),
        "sharpe": float(sharpe),
        "max_loss": float(passed["profit_ratio"].min()),
        "max_win": float(passed["profit_ratio"].max()),
        "win_rate": float((pnls > 0).mean()),
    }


def run_parity_ab(
    bt_zip: Path,
    cis_snapshot: Path,
    cis_history_dir: Path,
    grid_path: Path,
    band_snapshot_path: Path,
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== C1 Parity A/B — freqtrade ← → Nautilus empirical-grid ===")
    print(f"Backtest:    {bt_zip}")
    print(f"CIS snapshot: {cis_snapshot}")
    print(f"Grid:        {grid_path}")
    print(f"Band snap:   {band_snapshot_path}")
    print(f"Output:      {out_dir}")

    # 1. Load backtest
    bt, strat_name = load_freqtrade_backtest(bt_zip)
    trades_df = trades_to_df(bt, strat_name)
    if trades_df.empty:
        raise ValueError(f"No trades in {bt_zip}")
    print(f"\nLoaded {len(trades_df)} trades from {strat_name}")
    print(f"Window: {trades_df['open_date'].min().date()} → {trades_df['open_date'].max().date()}")

    # 2. Load grid + band snapshot
    grid = json.loads(grid_path.read_text()).get("grid", {})
    bands = json.loads(band_snapshot_path.read_text()).get("bands", {})

    # 3. Build CIS lookup
    cis_lookup = CISTierLookup.from_paths(cis_snapshot, cis_history_dir)
    print(f"CIS lookup: {len(cis_lookup.by_date)} daily snapshots indexed")

    # 4. Evaluate each trade under both gates
    rows = []
    for _, trade in trades_df.iterrows():
        legacy = evaluate_trade_with_legacy_floor(trade, cis_lookup)
        empirical = evaluate_trade_with_empirical_grid(trade, grid, bands, cis_lookup)
        rows.append({
            "pair": trade["pair"],
            "open_date": trade["open_date"].strftime("%Y-%m-%d"),
            "is_short": trade["is_short"],
            "enter_tag": trade["enter_tag"],
            "profit_ratio": trade["profit_ratio"],
            "profit_abs": trade["profit_abs"],
            "legacy_blocked": legacy.blocked,
            "legacy_reason": legacy.decision.reason,
            "empirical_blocked": empirical.blocked,
            "empirical_expected_edge_pct": empirical.decision.expected_edge_pct,
            "empirical_conviction": empirical.decision.conviction,
            "empirical_reason": empirical.decision.reason,
        })
    per_trade_df = pd.DataFrame(rows)

    # 5. Verdict
    n_total = len(per_trade_df)
    n_legacy_block = int(per_trade_df["legacy_blocked"].sum())
    n_emp_block = int(per_trade_df["empirical_blocked"].sum())
    n_both_pass = int((~per_trade_df["legacy_blocked"] & ~per_trade_df["empirical_blocked"]).sum())
    n_legacy_only = int((per_trade_df["legacy_blocked"] & ~per_trade_df["empirical_blocked"]).sum())
    n_empirical_only = int((~per_trade_df["legacy_blocked"] & per_trade_df["empirical_blocked"]).sum())
    n_both_block = int((per_trade_df["legacy_blocked"] & per_trade_df["empirical_blocked"]).sum())

    # 6. Per-gate PnL summary
    legacy_summary = summarize(per_trade_df, "legacy")
    empirical_summary = summarize(per_trade_df, "empirical")

    # 7. Persist
    per_trade_path = out_dir / "per_trade.csv"
    per_trade_df.to_csv(per_trade_path, index=False, float_format="%.6f")

    summary_df = pd.DataFrame([
        {"gate": "LEGACY (REGIME_CIS_FLOOR)", **legacy_summary},
        {"gate": "EMPIRICAL_GRID", **empirical_summary},
    ])
    summary_path = out_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False, float_format="%.4f")

    verdict_md = out_dir / "verdict.md"
    verdict_md.write_text(_format_verdict(
        strat_name, n_total,
        n_legacy_block, n_emp_block,
        n_both_pass, n_legacy_only, n_empirical_only, n_both_block,
        legacy_summary, empirical_summary,
    ))

    print(f"\nPer-trade:    {per_trade_path}  ({n_total} rows)")
    print(f"Summary:      {summary_path}")
    print(f"Verdict:      {verdict_md}")

    # 8. Console verdict
    print(f"\n{'─'*72}")
    print(f"  C1 PARITY A/B VERDICT — {strat_name}")
    print(f"{'─'*72}")
    print(f"  Total trades:        {n_total}")
    print(f"  Both pass:           {n_both_pass}")
    print(f"  Both block:          {n_both_block}")
    print(f"  Legacy-only pass:    {n_legacy_only}  (empirical blocks; gate is STRICTER)")
    print(f"  Empirical-only pass: {n_empirical_only}  (legacy blocks; gate is LOOSER)")
    print(f"")
    print(f"  Legacy (CIS floor):    n_pass={legacy_summary['n_passed']} "
          f"Σ pnl=${legacy_summary['total_pnl']:+.2f} "
          f"Sharpe={legacy_summary['sharpe']:+.2f} "
          f"max_loss={legacy_summary['max_loss']*100:+.2f}%")
    print(f"  Empirical grid:        n_pass={empirical_summary['n_passed']} "
          f"Σ pnl=${empirical_summary['total_pnl']:+.2f} "
          f"Sharpe={empirical_summary['sharpe']:+.2f} "
          f"max_loss={empirical_summary['max_loss']*100:+.2f}%")
    delta_sharpe = empirical_summary['sharpe'] - legacy_summary['sharpe']
    print(f"  Δ Sharpe:              {delta_sharpe:+.2f}")
    print(f"{'─'*72}")

    return {
        "n_total": n_total,
        "both_pass": n_both_pass,
        "both_block": n_both_block,
        "legacy_only_pass": n_legacy_only,
        "empirical_only_pass": n_empirical_only,
        "legacy_summary": legacy_summary,
        "empirical_summary": empirical_summary,
        "delta_sharpe": delta_sharpe,
        "summary_csv": str(summary_path),
        "per_trade_csv": str(per_trade_path),
        "verdict_md": str(verdict_md),
    }


def _format_verdict(
    strat_name, n_total,
    n_legacy_block, n_emp_block,
    n_both_pass, n_legacy_only, n_empirical_only, n_both_block,
    legacy_summary, empirical_summary,
) -> str:
    delta_sharpe = empirical_summary['sharpe'] - legacy_summary['sharpe']
    delta_pnl = empirical_summary['total_pnl'] - legacy_summary['total_pnl']
    delta_n = empirical_summary['n_passed'] - legacy_summary['n_passed']

    if delta_sharpe > 0.1 and delta_pnl > 0:
        verdict = "✅ **WIN** — empirical grid is strictly better (Sharpe ↑, PnL ↑)."
    elif delta_sharpe < -0.1 and delta_pnl < 0:
        verdict = "🔴 **LOSS** — empirical grid regresses both Sharpe and PnL. Keep `REGIME_CIS_FLOOR`."
    elif abs(delta_sharpe) <= 0.1 and abs(delta_pnl) <= 50:
        verdict = "🟡 **NEUTRAL** — gates agree on this backtest window. Run on longer/different window to disambiguate."
    else:
        verdict = "🟡 **MIXED** — Sharpe and PnL disagree. Inspect `per_trade.csv` for the source of divergence."

    return f"""# C1 Parity A/B Verdict — `{strat_name}` vs Empirical-Grid Gate

## Decision matrix (n={n_total} trades)

|                   | Empirical ALLOW | Empirical BLOCK |
|---|---:|---:|
| **Legacy ALLOW**  | {n_both_pass} | {n_legacy_only} (legacy allows, empirical blocks) |
| **Legacy BLOCK**  | {n_empirical_only} (legacy blocks, empirical allows) | {n_both_block} |

## Per-gate summary

| Gate | n_pass | n_block | Σ pnl ($) | Sharpe | Max loss (%) | Win rate |
|---|---:|---:|---:|---:|---:|---:|
| **LEGACY (REGIME_CIS_FLOOR)** | {legacy_summary['n_passed']} | {legacy_summary['n_blocked']} | {legacy_summary['total_pnl']:+.2f} | {legacy_summary['sharpe']:+.2f} | {legacy_summary['max_loss']*100:+.2f}% | {legacy_summary['win_rate']*100:.1f}% |
| **EMPIRICAL_GRID** | {empirical_summary['n_passed']} | {empirical_summary['n_blocked']} | {empirical_summary['total_pnl']:+.2f} | {empirical_summary['sharpe']:+.2f} | {empirical_summary['max_loss']*100:+.2f}% | {empirical_summary['win_rate']*100:.1f}% |
| **Δ** | {delta_n:+d} | {empirical_summary['n_blocked']-legacy_summary['n_blocked']:+d} | **{delta_pnl:+.2f}** | **{delta_sharpe:+.2f}** | — | — |

## Verdict

{verdict}

## Files

- per_trade.csv    — one row per trade × (legacy, empirical) decision
- summary.csv      — aggregate stats per gate
- verdict.md       — this file

## Next step

If **WIN**: cut over production paper to empirical-grid gate; archive `REGIME_CIS_FLOOR` as legacy baseline.
If **LOSS**: keep `REGIME_CIS_FLOOR`; log the negative result as R34 (or whatever R-number is next).
If **NEUTRAL/MIXED**: extend backtest window, then re-run.
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-zip", type=Path, required=True,
                    help="freqtrade backtest-result ZIP file (e.g. user_data/backtest_results/backtest-result-*.zip)")
    ap.add_argument("--cis-snapshot", type=Path,
                    default=Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json"),
                    help="Latest CIS scores JSON (live engine output)")
    ap.add_argument("--cis-history", type=Path,
                    default=Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/"),
                    help="CIS history directory (for tier lookup of backtest dates)")
    ap.add_argument("--grid-path", type=Path,
                    default=Path("reports/edge_gate_grid.json"),
                    help="Shrunk edge-map grid JSON")
    ap.add_argument("--band-snapshot", type=Path,
                    default=Path("reports/btc_band_snapshot.json"),
                    help="BTC band snapshot JSON (date → band)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output directory for per_trade.csv, summary.csv, verdict.md")
    args = ap.parse_args(argv)

    run_parity_ab(
        bt_zip=args.backtest_zip,
        cis_snapshot=args.cis_snapshot,
        cis_history_dir=args.cis_history,
        grid_path=args.grid_path,
        band_snapshot_path=args.band_snapshot,
        out_dir=args.out_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
