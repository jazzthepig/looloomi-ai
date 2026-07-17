"""
Multi-Window Baseline Sweep (Minimax-B, 2026-07-15)

Rolling OOS walk-forward across the available 4h bar history. The first
step toward validating whether LS v1 baseline is stable — isolated from
any Phase B gate alternative.

What's running:
    For a fixed IS length (default 240 days ≈ 1.4k 4h bars) and a fixed OOS
    length (default 70 days ≈ 420 4h bars), step forward by OOS length and
    run the baseline variant (no empirical-grid gate, REGIME_CIS_FLOOR only).
    Output: per-window PnL, order count, trade-by-trade Sharpe proxy.

Two data sources supported via --data-source flag:
    --data-source futures (default): the existing 2.5-year futures feather
        in /Volumes/CometCloudAI/freqtrade/.../-futures.feather — uses the
        existing data_adapter + catalog. Read-only against the current
        sweeper. ~13 OOS windows.
    --data-source spot: the 9-year spot feather pulled 2026-07-15, lives in
        /Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/. Requires
        the temporary 9y catalog (built into the helper script).
        ~46 OOS windows.

The CIS history is the same in both cases — Minimax's CIS pipeline started
2024-06-07. Pre-2024 windows run with sparse CIS (soft floor bypass).
Post-2024 windows run with full CIS gating.

Usage:
    python3 -m src.research.cis_regime_studies.multi_window_baseline
    python3 -m src.research.cis_regime_studies.multi_window_baseline --data-source spot --oos-days 70
    python3 -m src.research.cis_regime_studies.multi_window_baseline --skip-existing

Output:
    reports/multi_window_baseline/<date>/{full_results.json, comparison.json, summary.md, raw/}
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

from common.nautilus_runner import run_with_config, summarise_run  # noqa: E402


logger = logging.getLogger(__name__)


# ── Window configuration ────────────────────────────────────────────────────

# Defaults — derived from the existing 2.5y data span (2024-01..2026-07).
# With 240d IS / 70d OOS we get ~13 independent OOS windows.
DEFAULT_IS_DAYS = 240
DEFAULT_OOS_DAYS = 70
DEFAULT_DATA_SOURCE = "futures"

# Spot data starts 2017-08-17 (BTC/ETH), 2020-08-11 (SOL).
SPOT_DATA_START = {
    "BTC": "2017-08-17T00:00:00Z",
    "ETH": "2017-08-17T00:00:00Z",
    "SOL": "2020-08-11T00:00:00Z",
}

# Futures data starts 2024-01-01 (BTC/ETH/SOL).
FUTURES_DATA_START = "2024-01-01T00:00:00Z"

# CIS pipeline starts 2024-06-07 — earlier windows use bypass (soft floor).
CIS_PIPELINE_START = "2024-06-07T00:00:00Z"


# ── Window generation ───────────────────────────────────────────────────────

def generate_windows(
    data_start: str,
    data_end: str,
    is_days: int,
    oos_days: int,
) -> list[tuple[str, str, str]]:
    """Generate (label, is_start, oos_end) tuples for rolling walk-forward.

    oos_start = data_start + IS_days + (i * OOS_days)
    oos_end   = oos_start + OOS_days

    All windows clamped to data_end.
    """
    start = datetime.fromisoformat(data_start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(data_end.replace("Z", "+00:00"))

    windows = []
    i = 0
    while True:
        is_start = start + timedelta(days=i * oos_days)
        is_end = is_start + timedelta(days=is_days)
        oos_start = is_end
        oos_end = oos_start + timedelta(days=oos_days)
        if oos_end > end:
            break
        label = f"w{i:02d}_oos{is_start.strftime('%Y%m%d')}-{oos_end.strftime('%Y%m%d')}"
        windows.append((label, is_start.isoformat(), oos_end.isoformat()))
        i += 1
    return windows


# ── Sweep driver ────────────────────────────────────────────────────────────

def run_sweep(
    data_source: str = DEFAULT_DATA_SOURCE,
    is_days: int = DEFAULT_IS_DAYS,
    oos_days: int = DEFAULT_OOS_DAYS,
    skip_existing: bool = True,
    out_dir: Optional[Path] = None,
    cis_history_dir: Optional[str] = None,
) -> dict:
    """Run rolling walk-forward OOS for the baseline variant."""
    # Map data source to start date
    if data_source == "futures":
        # Take the latest start across instruments (all 3 are aligned in the
        # current 2.5y futures archive — same feather start date).
        data_start = FUTURES_DATA_START
        # End = today
        data_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    elif data_source == "spot":
        # Take the earliest (BTC/ETH), which gives the most windows
        data_start = min(SPOT_DATA_START.values())
        data_end = "2026-07-15T00:00:00Z"  # last spot bar fetched 2026-07-15
    else:
        raise ValueError(f"Unknown data_source: {data_source}")

    cis_history_dir = cis_history_dir or os.getenv(
        "CIS_HISTORY_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    )

    windows = generate_windows(data_start, data_end, is_days, oos_days)
    logger.info(f"Generated {len(windows)} rolling windows "
                f"(IS={is_days}d, OOS={oos_days}d, data={data_source})")

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Distinguish CIS-on vs CIS-off via a tag in the output dir
    cis_tag = "cis_off" if os.getenv("LSV1_ENABLE_CIS_GATE", "0") == "0" else "cis_on"
    out_dir = Path(out_dir) if out_dir else Path(f"reports/multi_window_baseline_{data_source}_{cis_tag}") / date_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "sweep_config.json").write_text(json.dumps({
        "data_source": data_source,
        "data_start": data_start,
        "data_end": data_end,
        "is_days": is_days,
        "oos_days": oos_days,
        "cis_history_dir": cis_history_dir,
        "n_windows": len(windows),
        "cis_pipeline_start": CIS_PIPELINE_START,
    }, indent=2))

    runs = {}
    n_done = 0
    n_total = len(windows)
    started = time.monotonic()

    for label, _, oos_end_iso in windows:
        cache_path = raw_dir / f"{label}.json"
        if skip_existing and cache_path.exists():
            runs[label] = json.loads(cache_path.read_text())
            logger.info(f"  [cached] {label}")
            n_done += 1
            continue

        n_done += 1
        # IS end = oos_start; oos_start = oos_end - OOS_days
        oos_end_dt = datetime.fromisoformat(oos_end_iso.replace("Z", "+00:00"))
        oos_start_dt = oos_end_dt - timedelta(days=oos_days)
        is_end_iso = oos_start_dt.isoformat()
        is_start_dt = oos_start_dt - timedelta(days=is_days)
        is_start_iso = is_start_dt.isoformat()

        logger.info(f"  [{n_done}/{n_total}] {label} IS={is_start_dt.date()}:{is_end_dt[10:19] if False else ''} ..."
                    f" OOS={oos_start_dt.date()}:{oos_end_dt.date()}")
        # Cleaner log line:
        logger.info(f"    IS: {is_start_dt.date()} → {oos_start_dt.date()}, OOS: {oos_start_dt.date()} → {oos_end_dt.date()}")

        try:
            # CIS pipeline cutover — window is "post-CIS" if oos_start > CIS_PIPELINE_START
            cis_post = oos_start_dt >= datetime.fromisoformat(CIS_PIPELINE_START.replace("Z", "+00:00"))

            extra_env = {
                "NAUTILUS_LS_V1_START": is_start_iso,
                "NAUTILUS_LS_V1_END": oos_end_iso,
                "CIS_HISTORY_DIR": cis_history_dir,
                "LSV1_USE_EMPIRICAL_GRID_GATE": "0",  # baseline only — gate disabled
                "LSV1_USE_GRID_SIZE_MULTIPLIER": "0",
                "LSV1_USE_H32_SIZING": "0",
                # Tech-only baseline when env LSV1_ENABLE_CIS_GATE=0 (default).
                # Default OFF for the 9-year sweep because CIS history only
                # starts 2024-06-07 — without this, pre-2024 windows have
                # no signal and never trade.
                "LSV1_ENABLE_CIS_GATE": os.getenv("LSV1_ENABLE_CIS_GATE", "0"),
                # Explicitly baseline direction (all "high")
                "LSV1_GATE_DIRECTION_TIGHTENING": "high",
                "LSV1_GATE_DIRECTION_RISK_OFF": "high",
                "LSV1_GATE_DIRECTION_RISK_ON": "high",
                "LSV1_GATE_DIRECTION_STAGFLATION": "high",
                "LSV1_GATE_DIRECTION_EASING": "high",
                "LSV1_GATE_DIRECTION_NEUTRAL": "high",
                "LSV1_GATE_DIRECTION_GOLDILOCKS": "high",
            }
            result = run_with_config(
                gate_directions={},
                out_dir=out_dir / "runs",
                extra_env=extra_env,
            )
            summary = summarise_run(result)
            summary["per_instrument"] = result["per_instrument"]
            summary["skip_summary"] = result["skip_summary"]
            summary["window_label"] = label
            summary["window_dates"] = {
                "is_start": is_start_iso,
                "is_end": is_end_iso,
                "oos_start": is_start_iso,  # placeholder
                "oos_end": oos_end_iso,
            }
            # Fix field naming
            summary["window_dates"]["is_start"] = is_start_iso
            summary["window_dates"]["is_end"] = is_end_iso
            summary["window_dates"]["oos_start"] = oos_start_dt.isoformat()
            summary["window_dates"]["oos_end"] = oos_end_iso
            summary["cis_post_pipeline"] = cis_post
            runs[label] = summary
            cache_path.write_text(json.dumps(summary, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.error(f"    FAIL: {exc!r}")
            runs[label] = {"error": repr(exc)}

    elapsed = round(time.monotonic() - started, 2)

    # Summary stats
    pnl_list = []
    for label, r in runs.items():
        if "error" in r:
            continue
        pnl = r.get("pnl_usd", 0)
        orders = r.get("n_orders", 0)
        pnl_list.append({
            "label": label,
            "pnl": pnl,
            "orders": orders,
        })

    (out_dir / "full_results.json").write_text(json.dumps(runs, indent=2, default=str))
    (out_dir / "summary.md").write_text(_render_summary(runs, pnl_list, data_source, is_days, oos_days, elapsed))
    (out_dir / "summary.json").write_text(json.dumps({
        "data_source": data_source,
        "is_days": is_days,
        "oos_days": oos_days,
        "n_windows": len(windows),
        "n_succeeded": sum(1 for r in runs.values() if "error" not in r),
        "n_failed": sum(1 for r in runs.values() if "error" in r),
        "elapsed_sec": elapsed,
        "out_dir": str(out_dir),
    }, indent=2))

    logger.info(f"\nwrote {out_dir}/")
    logger.info(f"  n_windows: {len(windows)}, n_succeeded: "
                f"{sum(1 for r in runs.values() if 'error' not in r)}")
    logger.info(f"  elapsed: {elapsed}s")
    return {"runs": runs, "out_dir": str(out_dir)}


# ── Summary rendering ───────────────────────────────────────────────────────

def _render_summary(runs: dict, pnl_list: list, data_source: str,
                    is_days: int, oos_days: int, elapsed: float) -> str:
    valid_pnls = [p["pnl"] for p in pnl_list if p["orders"] > 0]
    if not valid_pnls:
        return f"# Multi-Window Baseline ({data_source}) — NO DATA\n"

    import statistics
    md = []
    md.append(f"# Multi-Window Baseline — {data_source} (LS v1, IS={is_days}d / OOS={oos_days}d)\n")
    md.append(f"_Elapsed: {elapsed}s, windows: {len(pnl_list)}_\n")

    valid_count = len(valid_pnls)
    positives = sum(1 for p in valid_pnls if p > 0)
    win_rate = positives / valid_count if valid_count else 0
    md.append("## Summary statistics\n")
    md.append(f"- Valid windows (n_orders > 0): {valid_count} / {len(pnl_list)}")
    md.append(f"- Win rate (P&L > 0): {win_rate:.1%} ({positives}/{valid_count})")
    md.append(f"- Median P&L: ${statistics.median(valid_pnls):+.2f}")
    md.append(f"- Mean P&L: ${statistics.mean(valid_pnls):+.2f}")
    md.append(f"- Stdev P&L: ${statistics.stdev(valid_pnls) if valid_count > 1 else 0:.2f}")
    md.append(f"- Best window: ${max(valid_pnls):+.2f}")
    md.append(f"- Worst window: ${min(valid_pnls):+.2f}")

    md.append("\n## Per-window P&L\n")
    md.append("| window | orders | P&L ($) |")
    md.append("|---|---:|---:|")
    for p in pnl_list:
        md.append(f"| `{p['label']}` | {p['orders']} | {p['pnl']:+.2f} |")

    md.append("\n## Interpretation guide\n")
    md.append("- **Win rate** = % of windows where P&L > 0. A stable strategy should have > 50%.")
    md.append("- **Stdev / |Mean|** = coefficient of variation. < 1.0 = stable; > 2.0 = unstable.")
    md.append("- **Worst window** = left-tail risk. If this is < -$300 (large negative), the strategy has bad-tail risk in some regime.")
    md.append("\n## Caveats\n")
    md.append("- Pre-CIS-pipeline windows (before 2024-06-07) use soft-floor bypass — those windows test the tech-only path, NOT the gate-filtered path.")
    md.append("- Spot data is exchange-agnostic for the LS v1 signal layer (no funding-rate dependency); futures data is the live-trade instrument.")
    return "\n".join(md) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Multi-window rolling OOS baseline sweep")
    parser.add_argument("--data-source", choices=["futures", "spot"], default=DEFAULT_DATA_SOURCE)
    parser.add_argument("--is-days", type=int, default=DEFAULT_IS_DAYS)
    parser.add_argument("--oos-days", type=int, default=DEFAULT_OOS_DAYS)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--cis-history-dir", type=str, default=None)
    args = parser.parse_args()

    result = run_sweep(
        data_source=args.data_source,
        is_days=args.is_days,
        oos_days=args.oos_days,
        skip_existing=not args.no_skip_existing,
        out_dir=args.out_dir,
        cis_history_dir=args.cis_history_dir,
    )
    print(f"\nMulti-window baseline complete → {result['out_dir']}")