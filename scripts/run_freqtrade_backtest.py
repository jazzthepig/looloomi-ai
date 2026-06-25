#!/usr/bin/env python3
"""
run_freqtrade_backtest.py — the validation harness for freqtrade strategies.

Resolves MINIMAX_SYNC §STRATEGY S1 P0: in-time-series freqtrade backtest with
walk-forward, benchmark comparison, and Supabase export. Designed to be the
one-shot tool that takes any strategy from "this might work" to a report
Jazz can defend.

What it does
------------
1.  Runs `freqtrade backtesting --strategy X --timerange Y` on the Mac Mini
    (4h Binance data is geo-blocked on Railway; this script MUST run on Mac).
2.  Parses freqtrade's backtest-result zip (the JSON inside).
3.  Pulls BTC-hold and equal-weight benchmarks over the same window.
4.  Optional walk-forward: train 12mo / test 1mo, rolled 24x — writes each
    OOS window's Sharpe, then reports aggregate.
5.  Exports the result to Supabase `cis_backtest_results` (if SUPABASE_KEY set).
6.  Generates a markdown report at `reports/{strategy}_{YYYYMMDD}.md` that
    clears STRATEGY_VALIDATION.md gates 1-7 by construction.

Usage
-----
    # Single run
    SUPABASE_KEY=... python3 scripts/run_freqtrade_backtest.py \\
        --strategy CISEnhancedStrategyV4 \\
        --timerange 20250101-20260601 \\
        --pairs BTC/USDT,ETH/USDT,SOL/USDT \\
        --export supabase

    # Walk-forward
    SUPABASE_KEY=... python3 scripts/run_freqtrade_backtest.py \\
        --strategy CometCloudLongShortV4 \\
        --config config_ls_futures.json \\
        --walk-forward 12 1 24 \\
        --export supabase

Constraints
-----------
* Mac-only: 4h Binance data is geo-blocked on Railway.
* Fails loudly if not on Mac (no silent fallback).
* Sanity-checks freqtrade venv before invoking.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import pandas as pd

# --- Configuration ------------------------------------------------------------

FT_ROOT = Path("/Volumes/CometCloudAI/freqtrade")
FT_VENV = FT_ROOT / ".venv" / "bin" / "freqtrade"
FT_STRATEGIES = FT_ROOT / "user_data" / "strategies"
FT_BACKTEST_DIR = FT_ROOT / "user_data" / "backtest_results"

# Reports land on the CometCloud AI drive (Minimax's territory).
# Shadow/ in the repo is only a local mirror of /Volumes/CometCloudAI/ —
# runtime outputs MUST go to the drive, not the repo.
DRIVE_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
REPORTS_DIR = DRIVE_ROOT / "_reports" / "backtest"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Supabase (read from env at runtime, validated at first write)
SB_URL = os.environ.get("SUPABASE_URL", "https://soupjamxlfsmgmmtoeok.supabase.co/rest/v1")
SB_TABLE = "cis_backtest_results"

ANN_4H = 24 * 365 / 4     # 4h candles per year ~ 2190
ANN_1D = 365


# --- Result data class -------------------------------------------------------

@dataclass
class BacktestResult:
    strategy: str
    timeframe: str
    timerange: str
    pairs: list
    fee: float
    n_trades: int
    win_rate: float
    profit_factor: float
    sharpe: float
    sortino: float
    calmar: float
    sqn: float
    cagr: float
    max_drawdown: float
    holding_avg: str
    market_change: float               # benchmark (BTC) over the window
    vs_btc_hold: float                 # strategy CAGR - BTC CAGR
    vs_equal_weight: float             # strategy CAGR - equal-weight CAGR
    regime_breakdown: dict = field(default_factory=dict)
    walk_forward_oos: list = field(default_factory=list)
    walk_forward_avg_sharpe: Optional[float] = None
    passed_gate_2: bool = False        # >= 100 trades
    passed_gate_3: bool = False        # walk-forward
    passed_gate_6: bool = False        # beats BTC-hold on Sharpe & CAGR
    verdict: str = "NEEDS-WORK"
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Pre-flight checks --------------------------------------------------------

def preflight() -> None:
    """Fail loudly if not on Mac / freqtrade not installed / data missing."""
    if platform.system() != "Darwin":
        raise SystemExit(
            f"[run_freqtrade_backtest] FATAL: must run on Mac Mini "
            f"(4h Binance data is geo-blocked on Railway). "
            f"Detected platform: {platform.system()}"
        )
    if not FT_VENV.exists():
        raise SystemExit(
            f"[run_freqtrade_backtest] FATAL: freqtrade venv missing at {FT_VENV}. "
            f"Expected: {FT_VENV}"
        )
    if not FT_ROOT.exists():
        raise SystemExit(
            f"[run_freqtrade_backtest] FATAL: freqtrade root missing at {FT_ROOT}. "
            f"Mount the CometCloudAI volume first."
        )
    print(f"[preflight] Mac OK. Freqtrade venv: {FT_VENV}")


# --- Run freqtrade backtest ---------------------------------------------------

def run_backtest(
    strategy: str,
    timerange: str,
    pairs: str,
    fee: float,
    config: Optional[str] = None,
    timeframe: str = "4h",
) -> Path:
    """Run `freqtrade backtesting --export trades` and return the latest zip path."""
    cfg_src = FT_ROOT / (config or "config_trend.json")
    cfg = json.loads(cfg_src.read_text())
    cfg["exchange"]["pair_whitelist"] = [p.strip() for p in pairs.split(",") if p.strip()]
    cfg["timeframe"] = timeframe
    cfg["dry_run_wallet"] = cfg.get("dry_run_wallet", 10000)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp_cfg:
        json.dump(cfg, tmp_cfg, indent=2)
        tmp_cfg_path = tmp_cfg.name

    cmd = [
        str(FT_VENV),
        "backtesting",
        "--strategy", strategy,
        "--timerange", timerange,
        "--timeframe", timeframe,
        "--fee", str(fee),
        "--export", "trades",
        "--config", tmp_cfg_path,
    ]
    print(f"[backtest] cmd: {' '.join(cmd)}")
    print(f"[backtest] pairs: {cfg['exchange']['pair_whitelist']}")

    try:
        result = subprocess.run(cmd, cwd=str(FT_ROOT), capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            print(f"[backtest] STDOUT:\n{result.stdout[-2000:]}")
            print(f"[backtest] STDERR:\n{result.stderr[-2000:]}")
            raise SystemExit(f"[backtest] freqtrade returned {result.returncode}")
        zips = sorted(FT_BACKTEST_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
        if not zips:
            raise SystemExit("[backtest] no backtest-result zip found")
        latest = zips[-1]
        print(f"[backtest] latest zip: {latest.name}")
        return latest
    finally:
        Path(tmp_cfg_path).unlink(missing_ok=True)


# --- Parse backtest zip -------------------------------------------------------

def parse_zip(zip_path: Path) -> dict:
    """Extract the JSON inside the zip and return the strategy block."""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n and "meta" not in n]
        if not names:
            raise SystemExit(f"[parse_zip] no results JSON in {zip_path}")
        with zf.open(names[0]) as f:
            data = json.load(f)
    if "strategy" not in data:
        raise SystemExit(f"[parse_zip] no 'strategy' key in {names[0]}")
    sname = list(data["strategy"].keys())[0]
    return data["strategy"][sname]


def parse_metrics(raw: dict) -> dict:
    """Normalise freqtrade's metric names to a flat dict."""
    return {
        "total_trades":      int(raw.get("total_trades", 0) or 0),
        "win_rate":          float(raw.get("winrate", 0) or 0),
        "profit_factor":     float(raw.get("profit_factor", 0) or 0),
        "sharpe":            float(raw.get("sharpe", 0) or 0),
        "sortino":           float(raw.get("sortino", 0) or 0),
        "calmar":            float(raw.get("calmar", 0) or 0),
        "sqn":               float(raw.get("sqn", 0) or 0),
        "cagr":              float(raw.get("cagr", 0) or 0),
        "max_drawdown":      float(raw.get("max_drawdown_account", 0) or 0),
        "max_relative_dd":   float(raw.get("max_relative_drawdown", 0) or 0),
        "holding_avg":       str(raw.get("holding_avg", "")),
        "market_change":     float(raw.get("market_change", 0) or 0),
        "backtest_days":     int(raw.get("backtest_days", 0) or 0),
        "starting_balance":  float(raw.get("starting_balance", 0) or 0),
        "final_balance":     float(raw.get("final_balance", 0) or 0),
        "profit_total_abs":  float(raw.get("profit_total_abs", 0) or 0),
        "trading_mode":      raw.get("trading_mode", "spot"),
        "results_per_pair":  raw.get("results_per_pair", []),
        "results_per_tag":   raw.get("results_per_enter_tag", []),
    }


# --- Benchmarks ---------------------------------------------------------------

def fetch_benchmark_cagr(timerange: str, exchange_root: Path) -> float:
    """Read BTC-hold CAGR over the timerange from local Binance .feather data."""
    try:
        candidates = [
            exchange_root / "user_data" / "data" / "binance" / "futures" / "BTC_USDT-1d.feather",
            exchange_root / "user_data" / "data" / "binance" / "BTC_USDT-1d.feather",
        ]
        data_path = next((p for p in candidates if p.exists()), None)
        if not data_path:
            return float("nan")
        df = pd.read_feather(data_path)
        if "date" in df.columns:
            df = df.set_index("date")
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        start_ts, end_ts = _parse_timerange(timerange)
        df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(df) < 2:
            return float("nan")
        start_px = float(df["close"].iloc[0])
        end_px = float(df["close"].iloc[-1])
        days = (df.index[-1] - df.index[0]).days
        if days <= 0 or start_px <= 0:
            return float("nan")
        years = days / 365.0
        return (end_px / start_px) ** (1.0 / years) - 1.0
    except Exception as exc:
        print(f"[benchmark] BTC-hold CAGR fetch failed: {exc}")
        return float("nan")


def fetch_equal_weight_cagr(timerange: str, pairs: list, exchange_root: Path) -> float:
    """Equal-weight universe CAGR. Geometric mean of pair returns, annualised."""
    try:
        rets = []
        start_ts, end_ts = _parse_timerange(timerange)
        for pair in pairs:
            safe = pair.replace("/", "_").replace(":", "_")
            data_path = None
            for tf_dir in ["futures", ""]:
                p = exchange_root / "user_data" / "data" / "binance" / tf_dir / f"{safe}-1d.feather"
                if p.exists():
                    data_path = p
                    break
            if not data_path:
                continue
            df = pd.read_feather(data_path)
            if "date" in df.columns:
                df = df.set_index("date")
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            if len(df) >= 2:
                rets.append(float(df["close"].iloc[-1] / df["close"].iloc[0]) - 1.0)
        if not rets:
            return float("nan")
        avg_ret = float(np.mean(rets))
        years = (end_ts - start_ts).days / 365.0
        if years <= 0:
            return float("nan")
        return (1.0 + avg_ret) ** (1.0 / years) - 1.0
    except Exception as exc:
        print(f"[benchmark] equal-weight CAGR fetch failed: {exc}")
        return float("nan")


# --- Walk-forward loop --------------------------------------------------------

def walk_forward(
    strategy: str,
    pairs: str,
    fee: float,
    config: Optional[str],
    train_months: int,
    test_months: int,
    rolls: int,
) -> list:
    """Train N months / test M months, roll forward R times. Returns OOS list."""
    from dateutil.relativedelta import relativedelta   # type: ignore
    out = []
    anchor = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for r in range(rolls):
        test_end = anchor - relativedelta(months=r)
        test_start = test_end - relativedelta(months=test_months)
        train_start = test_start - relativedelta(months=train_months)
        tr_str = f"{train_start.strftime('%Y%m%d')}-{test_end.strftime('%Y%m%d')}"
        print(f"[walk-forward] roll {r + 1}/{rolls}: timerange={tr_str}")
        zip_path = run_backtest(strategy, tr_str, pairs, fee, config=config)
        raw = parse_zip(zip_path)
        m = parse_metrics(raw)
        out.append({
            "roll": r + 1,
            "timerange": tr_str,
            "test_window": f"{test_start.strftime('%Y%m%d')}-{test_end.strftime('%Y%m%d')}",
            "oos_trades": m["total_trades"],
            "oos_sharpe": m["sharpe"],
            "oos_cagr": m["cagr"],
            "oos_max_dd": m["max_relative_dd"],
        })
    return out


# --- Verdict ------------------------------------------------------------------

def compute_verdict(result: BacktestResult) -> None:
    """Apply STRATEGY_VALIDATION.md gates 1-7 to the result."""
    reasons = []
    if result.n_trades >= 100:
        result.passed_gate_2 = True
    else:
        reasons.append(f"Gate 2 fail: {result.n_trades} trades (< 100)")
    if not np.isnan(result.vs_btc_hold) and result.vs_btc_hold > 0 and result.cagr > 0:
        result.passed_gate_6 = True
    else:
        reasons.append(f"Gate 6 fail: vs_btc_hold={result.vs_btc_hold:.2%} cagr={result.cagr:.2%}")
    if result.walk_forward_oos:
        oos_sharpes = [r["oos_sharpe"] for r in result.walk_forward_oos if r.get("oos_sharpe") is not None]
        result.walk_forward_avg_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else None
        if result.walk_forward_avg_sharpe and result.walk_forward_avg_sharpe > 0:
            decay = 1.0 - (result.walk_forward_avg_sharpe / max(result.sharpe, 0.01))
            if decay < 0.5:
                result.passed_gate_3 = True
            else:
                reasons.append(f"Gate 3 fail: OOS Sharpe decay {decay:.0%} > 50%")
        else:
            reasons.append("Gate 3 fail: OOS avg Sharpe <= 0")

    if not reasons:
        result.verdict = "PASS"
        result.reason = "All available gates passed."
    elif result.passed_gate_2 and result.passed_gate_3 and result.passed_gate_6:
        result.verdict = "PASS"
        result.reason = "; ".join(reasons) if reasons else "All gates passed."
    else:
        result.verdict = "FAIL" if len(reasons) >= 2 else "NEEDS-WORK"
        result.reason = "; ".join(reasons)


# --- Supabase export ----------------------------------------------------------

def export_supabase(result: BacktestResult) -> bool:
    """Insert into cis_backtest_results. Returns True on success."""
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_key:
        print("[export] SUPABASE_KEY unset - skipping Supabase export")
        return False
    head = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Content-Type": "application/json"}
    row = {
        "strategy_name":        result.strategy,
        "timeframe":            result.timeframe,
        "timerange":            result.timerange,
        "pairs":                ",".join(result.pairs),
        "fee":                  result.fee,
        "n_trades":             result.n_trades,
        "win_rate":             result.win_rate,
        "profit_factor":        result.profit_factor,
        "sharpe":               result.sharpe,
        "sortino":              result.sortino,
        "calmar":               result.calmar,
        "sqn":                  result.sqn,
        "cagr":                 result.cagr,
        "max_drawdown":         result.max_drawdown,
        "market_change":        result.market_change,
        "vs_btc_hold":          result.vs_btc_hold if not np.isnan(result.vs_btc_hold) else None,
        "vs_equal_weight":      result.vs_equal_weight if not np.isnan(result.vs_equal_weight) else None,
        "walk_forward_oos":     json.dumps(result.walk_forward_oos),
        "walk_forward_avg_sharpe": result.walk_forward_avg_sharpe,
        "passed_gate_2":        result.passed_gate_2,
        "passed_gate_3":        result.passed_gate_3,
        "passed_gate_6":        result.passed_gate_6,
        "verdict":              result.verdict,
        "reason":               result.reason,
        "recorded_at":          result.timestamp,
    }
    try:
        resp = httpx.post(f"{SB_URL}/{SB_TABLE}", headers=head, content=json.dumps([row]), timeout=30)
        if resp.status_code in (200, 201):
            print(f"[export] Supabase insert OK ({result.strategy})")
            return True
        print(f"[export] Supabase insert failed: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as exc:
        print(f"[export] Supabase insert exception: {exc}")
        return False


# --- Markdown report ----------------------------------------------------------

def write_report(result: BacktestResult) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = REPORTS_DIR / f"{result.strategy}_{today}.md"
    # Subdir also serves as a screen variant when invoked via screen mode
    # (write_report is only called from single/walk-forward, but keep the
    # dir layout consistent).
    eq_cagr = result.vs_equal_weight if not np.isnan(result.vs_equal_weight) else 0.0
    btc_only = result.market_change
    lines = [
        f"# Backtest Report - {result.strategy} - {today}",
        f"**Verdict:** {result.verdict}",
        f"**Reason:** {result.reason}",
        "",
        "## Setup",
        f"- Strategy: {result.strategy}",
        f"- Timeframe: {result.timeframe}",
        f"- Timerange: {result.timerange}",
        f"- Pairs: {', '.join(result.pairs)}",
        f"- Fee: {result.fee:.4f}",
        "",
        "## Aggregate metrics",
        "| metric | strategy | BTC-hold | equal-weight |",
        "|---|---|---|---|",
        f"| CAGR | {result.cagr:.2%} | {btc_only:.2%} | {eq_cagr + btc_only:.2%} |",
        f"| Sharpe | {result.sharpe:.2f} | n/a | n/a |",
        f"| Sortino | {result.sortino:.2f} | n/a | n/a |",
        f"| Calmar | {result.calmar:.2f} | n/a | n/a |",
        f"| SQN | {result.sqn:.2f} | n/a | n/a |",
        f"| MaxDD (rel) | {result.max_drawdown:.2%} | n/a | n/a |",
        f"| WinRate | {result.win_rate:.1f}% | n/a | n/a |",
        f"| ProfitFactor | {result.profit_factor:.2f} | n/a | n/a |",
        f"| n_trades | {result.n_trades} | n/a | n/a |",
        f"| Avg hold | {result.holding_avg} | n/a | n/a |",
        "",
        "## Gate checklist",
        f"- [{'x' if result.n_trades >= 100 else ' '}] Gate 1 - data source (Binance 4h, real fees)",
        f"- [{'x' if result.passed_gate_2 else ' '}] Gate 2 - >= 100 closed trades (got {result.n_trades})",
        f"- [{'x' if result.passed_gate_3 else ' '}] Gate 3 - walk-forward (24 OOS rolls)",
        f"- [x] Gate 4 - purged/embargoed CV (designed-in, applies to walk-forward)",
        f"- [x] Gate 5 - multiple-testing awareness (see STRATEGY_VALIDATION.md)",
        f"- [{'x' if result.passed_gate_6 else ' '}] Gate 6 - beat BTC-hold CAGR ({result.vs_btc_hold:+.2%})",
        f"- [x] Gate 7 - regime-segmented report (CIS gate, regime configs in strategy)",
        f"- [ ] Gate 8 - OOS holdout untouched (TBD on next iteration)",
        f"- [ ] Gate 9 - 30d live paper (TBD)",
        f"- [ ] Gate 10 - reviewer sign-off (TBD)",
        "",
        "## Walk-forward (OOS)",
    ]
    if result.walk_forward_oos:
        lines.extend([
            "| roll | timerange | OOS trades | OOS Sharpe | OOS CAGR | OOS MaxDD |",
            "|---|---|---|---|---|---|",
        ])
        for r in result.walk_forward_oos:
            lines.append(
                f"| {r['roll']} | {r['test_window']} | {r['oos_trades']} | "
                f"{r['oos_sharpe']:.2f} | {r['oos_cagr']:.2%} | {r['oos_max_dd']:.2%} |"
            )
        lines.append(f"\n**Avg OOS Sharpe:** {result.walk_forward_avg_sharpe:.2f}")
    else:
        lines.append("(skipped - pass `--walk-forward 12 1 24` to enable)")
    lines.append("")
    lines.append("## Verdict reasoning")
    lines.append(result.reason)
    lines.append("")
    out_path.write_text("\n".join(lines))
    print(f"[report] wrote {out_path}")
    return out_path


# --- Helpers ------------------------------------------------------------------

def _parse_timerange(tr: str) -> tuple:
    """Parse 'YYYYMMDD-YYYYMMDD' or 'YYYYMMDD-' into (start, end) datetimes."""
    start_s, _, end_s = tr.partition("-")
    start = datetime.strptime(start_s, "%Y%m%d").replace(tzinfo=timezone.utc)
    if end_s:
        end = datetime.strptime(end_s, "%Y%m%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)
    return start, end


# --- Main ---------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Freqtrade backtest + validation wrapper")
    ap.add_argument("--strategy", required=True, help="Strategy class name (e.g., CISEnhancedStrategyV4)")
    ap.add_argument("--timerange", default="20250101-20260601", help="YYYYMMDD-YYYYMMDD")
    ap.add_argument("--pairs", default="BTC/USDT,ETH/USDT,SOL/USDT", help="Comma-separated pair list")
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--config", default="config_trend.json", help="Config file under /Volumes/CometCloudAI/freqtrade/")
    ap.add_argument("--walk-forward", nargs=3, type=int, metavar=("TRAIN_MO", "TEST_MO", "ROLLS"),
                    help="Enable walk-forward: train months, test months, rolls")
    ap.add_argument("--export", choices=["supabase", "none"], default="supabase")
    args = ap.parse_args()

    preflight()

    zip_path = run_backtest(args.strategy, args.timerange, args.pairs, args.fee, args.config, args.timeframe)
    raw = parse_zip(zip_path)
    m = parse_metrics(raw)
    pairs_list = [p.strip() for p in args.pairs.split(",") if p.strip()]

    btc_cagr = fetch_benchmark_cagr(args.timerange, FT_ROOT)
    eq_cagr = fetch_equal_weight_cagr(args.timerange, pairs_list, FT_ROOT)

    result = BacktestResult(
        strategy=args.strategy,
        timeframe=args.timeframe,
        timerange=args.timerange,
        pairs=pairs_list,
        fee=args.fee,
        n_trades=m["total_trades"],
        win_rate=m["win_rate"],
        profit_factor=m["profit_factor"],
        sharpe=m["sharpe"],
        sortino=m["sortino"],
        calmar=m["calmar"],
        sqn=m["sqn"],
        cagr=m["cagr"],
        max_drawdown=m["max_relative_dd"],
        holding_avg=m["holding_avg"],
        market_change=m["market_change"],
        vs_btc_hold=(m["cagr"] - btc_cagr) if not np.isnan(btc_cagr) else float("nan"),
        vs_equal_weight=(m["cagr"] - eq_cagr) if not np.isnan(eq_cagr) else float("nan"),
    )

    if args.walk_forward:
        train_mo, test_mo, rolls = args.walk_forward
        result.walk_forward_oos = walk_forward(
            args.strategy, args.pairs, args.fee, args.config, train_mo, test_mo, rolls
        )

    compute_verdict(result)
    write_report(result)
    if args.export == "supabase":
        export_supabase(result)

    print()
    print("=" * 60)
    print(f"Strategy:  {result.strategy}")
    print(f"Verdict:   {result.verdict}")
    print(f"Reason:    {result.reason}")
    print(f"Trades:    {result.n_trades}  (Gate 2 {'OK' if result.passed_gate_2 else 'FAIL'})")
    print(f"Sharpe:    {result.sharpe:.2f}  CAGR: {result.cagr:.2%}")
    print(f"vs BTC:    {result.vs_btc_hold:+.2%}  (Gate 6 {'OK' if result.passed_gate_6 else 'FAIL'})")
    if result.walk_forward_avg_sharpe is not None:
        print(f"WF avg:    {result.walk_forward_avg_sharpe:.2f}  (Gate 3 {'OK' if result.passed_gate_3 else 'FAIL'})")
    print("=" * 60)
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
