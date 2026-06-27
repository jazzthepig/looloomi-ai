#!/usr/bin/env python3
"""
CometCloud — Paper Trading Weekly Digest (v1)
==============================================

Per 2026-06-27 user direction: keep the existing long-only CIS-gated paper
trading trigger in cis_scheduler.py untouched, but add a weekly observability
script so we can sanity-check the trigger's behaviour and accumulate honest
data for the 30-day record.

Pulls from Railway public API:
  - /api/v1/trading/metrics   (aggregate metrics, by_grade, by_regime)
  - /api/v1/trading/positions (open positions, mark-to-market)
  - /api/v1/cis/universe      (current top CIS scores + regime)

Output:
  /Volumes/CometCloudAI/cometcloud-local/_reports/paper_trading/weekly_YYYYMMDD.md

Also writes a JSON snapshot for diff tracking:
  weekly_YYYYMMDD.json

Honest framing (per MINIMAX_TRADING_TRIGGER.md): this is the daily-frequency
long-only CIS-gated strategy, NOT the headline edge. Expect weak / beta-like
returns. The job is to validate the *infrastructure* (orders flow, positions
tracked, P&L computed) more than the *strategy*.

Usage:
    python3 scripts/paper_trading_weekly.py
"""
from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAILWAY_BASE = "https://web-production-0cdf76.up.railway.app"
ALT_RAILWAY_BASE = "https://looloomi.ai"

REPORT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/paper_trading")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Endpoints
EP_METRICS = "/api/v1/trading/metrics"
EP_POSITIONS = "/api/v1/trading/positions"
EP_CIS = "/api/v1/cis/universe"

TIMEOUT_SECONDS = 15


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_json(path: str, base: str = RAILWAY_BASE) -> dict | None:
    url = f"{base}{path}"
    try:
        r = httpx.get(url, timeout=TIMEOUT_SECONDS)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if base == RAILWAY_BASE:
            # try alt
            try:
                r = httpx.get(f"{ALT_RAILWAY_BASE}{path}", timeout=TIMEOUT_SECONDS)
                r.raise_for_status()
                return r.json()
            except Exception as e2:
                print(f"[WARN] fetch {path} failed on both endpoints: {e} / {e2}")
                return None
        print(f"[WARN] fetch {path} failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Digest builders
# ---------------------------------------------------------------------------

def build_metrics_section(m: dict | None) -> list[str]:
    if not m:
        return ["## Metrics", "", "_(unavailable)_", ""]
    lines = [
        "## Aggregate metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Total trades | {m.get('total_trades', '?')} |",
        f"| Win rate | {m.get('win_rate', 0):.1f}% |",
        f"| Avg return / trade | {m.get('avg_return_pct', 0):.2f}% |",
        f"| Total P&L (USD) | ${m.get('total_pnl_usd', 0):.2f} |",
        f"| Total P&L (%) | {m.get('total_pnl_pct', 0):.2f}% |",
        f"| Sharpe (approx) | {m.get('sharpe_approx', 0):.3f} |",
        f"| Cash (USD) | ${m.get('cash_usd', 0):.2f} |",
        f"| Open positions | {m.get('open_positions', 0)} |",
        f"| Open value (USD) | ${m.get('open_value_usd', 0):.2f} |",
        f"| Portfolio (USD) | ${m.get('portfolio_usd', 0):.2f} |",
        f"| Starting balance | ${m.get('starting_balance', 0):.2f} |",
        "",
    ]
    by_grade = m.get("by_grade", {})
    if by_grade:
        lines.extend([
            "### By grade",
            "",
            "| grade | avg return % |",
            "|---|---|",
        ])
        for g, v in sorted(by_grade.items(), key=lambda x: -abs(x[1]) if x[1] is not None else 0):
            lines.append(f"| {g} | {v:+.2f}% |")
        lines.append("")
    by_regime = m.get("by_regime", {})
    if by_regime:
        lines.extend([
            "### By regime",
            "",
            "| regime | avg return % |",
            "|---|---|",
        ])
        for r, v in sorted(by_regime.items(), key=lambda x: -abs(x[1]) if x[1] is not None else 0):
            lines.append(f"| {r} | {v:+.2f}% |")
        lines.append("")
    best = m.get("best_trade", {})
    worst = m.get("worst_trade", {})
    if best and worst:
        lines.extend([
            "### Best / worst closed",
            "",
            f"- **Best:** {best.get('symbol')} {best.get('pnl_pct', 0):+.2f}% (${best.get('pnl_usd', 0):+.2f})",
            f"- **Worst:** {worst.get('symbol')} {worst.get('pnl_pct', 0):+.2f}% (${worst.get('pnl_usd', 0):+.2f})",
            "",
        ])
    return lines


def build_positions_section(p: dict | None) -> list[str]:
    if not p:
        return ["## Open positions", "", "_(unavailable)_", ""]
    positions = p.get("positions", [])
    lines = [
        f"## Open positions ({len(positions)})",
        "",
        "| symbol | side | size $ | entry $ | current $ | P&L $ | P&L % | CIS | grade | signal | SL hit |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for pos in positions:
        lines.append(
            f"| {pos.get('symbol', '?')} | {pos.get('side', '?')} | "
            f"${pos.get('size_usd', 0):.0f} | ${pos.get('entry_price', 0):.2f} | "
            f"${pos.get('current_price', 0):.2f} | ${pos.get('unrealized_pnl', 0):+.2f} | "
            f"{pos.get('unrealized_pct', 0):+.2f}% | {pos.get('cis_score', 0):.1f} | "
            f"{pos.get('cis_grade', '?')} | {pos.get('cis_signal', '?')} | "
            f"{'✓' if pos.get('sl_triggered') else '—'} |"
        )
    lines.append("")
    return lines


def build_cis_section(c: dict | None) -> list[str]:
    if not c:
        return ["## Current CIS top 10", "", "_(unavailable)_", ""]
    scores = c.get("universe", c.get("scores", c.get("assets", [])))
    if not isinstance(scores, list):
        return ["## Current CIS top 10", "", "_(unavailable)_", ""]
    # Sort by CIS descending
    try:
        scores = sorted(scores, key=lambda x: -(x.get("cis_score") or 0))
    except Exception:
        pass
    regime = c.get("macro_regime", c.get("regime", "?"))
    confidence = c.get("regime_confidence")
    lines = [
        f"## CIS top 10 (current regime: {regime}"
        + (f", confidence: {confidence:.2f}" if confidence is not None else "")
        + ")",
        "",
        "| symbol | CIS | grade | signal | class | tier | confidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores[:10]:
        lines.append(
            f"| {s.get('symbol') or s.get('asset', '?')} | "
            f"{s.get('cis_score', 0):.1f} | {s.get('grade', s.get('cis_grade', '?'))} | "
            f"{s.get('signal', '?')} | {s.get('asset_class', '?')} | "
            f"T{s.get('data_tier', '?')} | "
            f"{s.get('regime_confidence', '—') if s.get('regime_confidence') is not None else '—'} |"
        )
    lines.append("")
    return lines


def build_honest_assessment_section(metrics: dict | None, positions: dict | None,
                                    cis: dict | None, snapshot_prev: dict | None) -> list[str]:
    """Honest weekly assessment — what does this week's data say?"""
    lines = ["## Honest assessment", ""]
    if not metrics:
        lines.append("- Unable to fetch metrics; cannot assess")
        return lines
    n_trades = metrics.get("total_trades", 0)
    regime = (cis or {}).get("macro_regime", "?") if cis else "?"
    confidence = (cis or {}).get("regime_confidence") if cis else None
    lines.extend([
        f"- This week's total trades (cumulative): {n_trades}",
        f"- Current regime: {regime}" + (f" (confidence {confidence:.2f})" if confidence is not None else ""),
        f"- This is the daily-frequency long-only CIS-gated strategy. NOT headline edge.",
        f"- 30-day target: ≥ 10 closed trades, ≥ 3 distinct regime transitions",
    ])
    # Regime gate observation
    if regime in ("Tightening", "Risk-Off") and n_trades < 12:
        lines.append(
            f"- ⚠️ Regime is `{regime}` — CIS threshold (52) blocks most crypto "
            "orders, only TradFi clears. Expected behaviour, not a regression."
        )
    # Win rate
    win_rate = metrics.get("win_rate")
    if win_rate is not None:
        if win_rate < 45:
            lines.append(f"- Win rate {win_rate:.1f}% is weak — honest data point, not failure")
        elif win_rate > 55:
            lines.append(f"- Win rate {win_rate:.1f}% is healthy for a daily-frequency long-only")
    return lines


def build_diff_section(curr: dict, prev: dict | None) -> list[str]:
    """Show diff from last week's snapshot if available."""
    if not prev:
        return ["## Δ vs last week", "", "_(no prior snapshot)_", ""]
    lines = ["## Δ vs last week", ""]
    m_curr = curr.get("metrics") or {}
    m_prev = prev.get("metrics") or {}
    fields = ["total_trades", "win_rate", "total_pnl_usd", "open_positions"]
    for f in fields:
        a = m_curr.get(f)
        b = m_prev.get(f)
        if a is None or b is None:
            continue
        delta = a - b
        sign = "+" if delta >= 0 else ""
        lines.append(f"- {f}: {b} → {a} (Δ {sign}{delta:.2f})")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_snapshot() -> dict:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "metrics": fetch_json(EP_METRICS),
        "positions": fetch_json(EP_POSITIONS),
        "cis": fetch_json(EP_CIS),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true",
                    help="Print to stdout but don't write to disk")
    args = ap.parse_args()

    snap = collect_snapshot()
    metrics = snap.get("metrics")
    positions = snap.get("positions")
    cis = snap.get("cis")

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_human = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Find most recent prior snapshot for diff
    prior = None
    if not args.no_write:
        snaps = sorted(REPORT_DIR.glob("weekly_*.json"))
        if snaps:
            try:
                prior = json.loads(snaps[-1].read_text())
            except Exception:
                prior = None

    # Build markdown
    md_lines = [
        f"# Paper Trading Weekly Digest — {today_human}",
        "",
        f"Railway: `{RAILWAY_BASE}`",
        "",
        "## Framing reminder",
        "",
        "Per `MINIMAX_TRADING_TRIGGER.md`, this is the **daily-frequency long-only",
        "CIS-gated** strategy, NOT the headline edge. Expected profile is weak /",
        "beta-like. The job here is to validate the *infrastructure* (orders flow,",
        "positions tracked, P&L computed) more than the *strategy*.",
        "",
        "Real alpha lives in S1 / v3 rebalance (per STRATEGY_VALIDATION.md).",
        "",
    ]
    md_lines.extend(build_metrics_section(metrics))
    md_lines.extend(build_positions_section(positions))
    md_lines.extend(build_cis_section(cis))
    md_lines.extend(build_honest_assessment_section(metrics, positions, cis, prior))
    md_lines.extend(build_diff_section(snap, prior))
    md = "\n".join(md_lines)

    if args.no_write:
        print(md)
        return 0

    md_path = REPORT_DIR / f"weekly_{today}.md"
    md_path.write_text(md)
    print(f"[weekly] wrote {md_path}")

    json_path = REPORT_DIR / f"weekly_{today}.json"
    json_path.write_text(json.dumps(snap, indent=2, default=str))
    print(f"[weekly] wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())