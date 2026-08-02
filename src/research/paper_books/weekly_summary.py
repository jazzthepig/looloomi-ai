"""Weekly summary — 60-day parallel paper phase.

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96").
This module is the forward-looking weekly aggregation over `daily_summary.csv`.
On the 60-day mark, the aggregated signal-trajectory stats + R77 NAV correlation
support the final verdict (Sharpe / maxDD / orthogonality).

Scope (honest limitations, anti-imposter):
  - This module operates on SIGNAL TRAJECTORIES, not mark-to-market P&L.
    A daily P&L ledger is NOT in scope here — sleeves log signals + sizes;
    actual P&L accrual requires a follow-up implementation with daily price
    evolution (queue: out-of-scope of the parallel-paper prototype).
  - Sharpe / maxDD on signal trajectories are PROXIES for "is the sleeve
    doing something useful" — they do NOT prove alpha. The 60d verdict
    requires real P&L tracking (next-phase work).
  - If < 7 days of daily_summary data exists, the module prints
    INSUFFICIENT_DATA and exits without fabricating metrics.

Output:
  /tmp/cometcloud_data/paper_books/weekly_summary.md
  Console: human-readable table

Usage:
  python3 src/research/paper_books/weekly_summary.py
  python3 src/research/paper_books/weekly_summary.py --min-days 14  # raise the floor

Cross-lane contract:
  R77 baseline fusion_paper_nav lives on Supabase; this module does NOT
  write to it (read-only if reachable). All 3 parallel sleeves write
  exclusively to local CSV.
"""
from __future__ import annotations

import csv
import os
import sys
import math
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src" / "research" / "paper_books"))

from ledger import LEDGER_DIR  # noqa: E402

DAILY_SUMMARY_PATH = LEDGER_DIR / "daily_summary.csv"
WEEKLY_SUMMARY_PATH = LEDGER_DIR / "weekly_summary.md"
DEFAULT_MIN_DAYS = 7

# Sleeve NAV CSVs (produced by nav_ledger.py)
SLEEVE_NAV_PATHS = {
    "vol_carry": LEDGER_DIR / "vol_carry_nav.csv",
    "regime_nowcast": LEDGER_DIR / "regime_nowcast_nav.csv",
    "macro_overlay": LEDGER_DIR / "macro_overlay_nav.csv",
}

# Supabase config for optional R77 NAV pull (read-only)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
R77_NAV_TABLE = "fusion_paper_nav"


def _read_daily_summary() -> list[dict]:
    """Read daily_summary.csv and dedupe by date_utc (keep last row per day)."""
    if not DAILY_SUMMARY_PATH.exists():
        return []
    with open(DAILY_SUMMARY_PATH) as f:
        rows = list(csv.DictReader(f))
    seen = {}
    for r in rows:
        d = r.get("date_utc", "")
        if d:
            seen[d] = r  # last write wins
    return [seen[d] for d in sorted(seen.keys())]


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _signal_trajectories(rows: list[dict]) -> dict[str, list[tuple[str, float | None]]]:
    """Extract per-sleeve (date, signal_value) trajectory from daily_summary rows."""
    out = {
        "vol_carry_term_premium": [(r["date_utc"], _safe_float(r.get("vol_carry_term_premium", ""))) for r in rows],
        "regime_nowcast_p": [(r["date_utc"], _safe_float(r.get("regime_nowcast_p", ""))) for r in rows],
        "regime_nowcast_tilt": [(r["date_utc"], _safe_float(r.get("regime_nowcast_tilt", ""))) for r in rows],
        "macro_overlay_imbalance": [],
    }
    # macro overlay imbalance = (long_count - short_count) / (long_count + short_count)
    for r in rows:
        lc = _safe_float(r.get("macro_overlay_long_count", ""))
        sc = _safe_float(r.get("macro_overlay_short_count", ""))
        if lc is None or sc is None or (lc + sc) == 0:
            out["macro_overlay_imbalance"].append((r["date_utc"], None))
        else:
            out["macro_overlay_imbalance"].append((r["date_utc"], (lc - sc) / (lc + sc)))
    return out


def _read_sleeve_nav(sleeve_id: str) -> list[dict]:
    """Read NAV CSV for a sleeve (sorted by date_utc asc). Empty list if not present."""
    path = SLEEVE_NAV_PATHS.get(sleeve_id)
    if path is None or not path.exists():
        return []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda r: r.get("date_utc", ""))


def _sharpe_annualized(daily_pnls: list[float], periods_per_year: int = 365) -> float | None:
    """Annualized Sharpe from daily P&L. Assumes 0 risk-free rate."""
    if len(daily_pnls) < 3:
        return None
    mean = sum(daily_pnls) / len(daily_pnls)
    sd = _std(daily_pnls)
    if sd is None or sd == 0:
        return None
    return (mean / sd) * (periods_per_year ** 0.5)


def _max_drawdown(cumulative_navs: list[float]) -> float | None:
    """Max drawdown as a fraction of peak (negative number, e.g. -0.15 = -15%)."""
    if len(cumulative_navs) < 2:
        return None
    peak = cumulative_navs[0]
    max_dd = 0.0
    for nav in cumulative_navs:
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, ignoring pairs where either is None."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx2 = sum((x - mx) ** 2 for x, _ in pairs)
    dy2 = sum((y - my) ** 2 for _, y in pairs)
    if dx2 == 0 or dy2 == 0:
        return None
    return num / (dx2 * dy2) ** 0.5


def _std(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return var ** 0.5


def _diffs(xs: list[float]) -> list[float]:
    """First differences (day-over-day change), dropping None pairs."""
    pairs = [(xs[i - 1], xs[i]) for i in range(1, len(xs)) if xs[i - 1] is not None and xs[i] is not None]
    return [b - a for a, b in pairs]


def _try_fetch_r77_nav() -> list[tuple[str, float]] | None:
    """Optional R77 baseline NAV pull. Returns [(date, nav), ...] sorted by date, or None on failure."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        import urllib.request
        import json
        url = (
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/{R77_NAV_TABLE}"
            f"?select=date_utc,nav&order=date_utc.asc&limit=200"
        )
        req = urllib.request.Request(
            url,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not isinstance(data, list):
            return None
        out = []
        for row in data:
            d = row.get("date_utc")
            nav = row.get("nav")
            if d and nav is not None:
                try:
                    out.append((d, float(nav)))
                except (TypeError, ValueError):
                    pass
        return out
    except Exception as e:
        print(f"  [INFO] R77 NAV fetch skipped: {type(e).__name__}: {str(e)[:120]}")
        return None


def _format_section_header(title: str) -> str:
    return f"\n## {title}\n"


def main() -> int:
    print("=" * 72)
    print("Weekly summary — 3-sleeve parallel paper phase")
    print("=" * 72)
    print(f"  source: {DAILY_SUMMARY_PATH}")
    print(f"  threshold: ≥{DEFAULT_MIN_DAYS} days for verdict-eligible metrics")
    print()

    rows = _read_daily_summary()
    n_days = len(rows)
    print(f"  daily summary rows: {n_days}")
    if n_days == 0:
        print(f"  INSUFFICIENT_DATA: daily_summary.csv is empty")
        print(f"  → run `python3 src/research/paper_books/daily_runner.py` first")
        return 0

    last_date = rows[-1]["date_utc"]
    first_date = rows[0]["date_utc"]
    print(f"  window:  {first_date} → {last_date}  ({n_days} day(s))")
    print()

    trajectories = _signal_trajectories(rows)
    sleeve_keys = list(trajectories.keys())

    # Per-sleeve trajectory stats
    print(_format_section_header("Per-sleeve signal trajectory"))
    print(f"{'sleeve':30s} {'n':>4s} {'mean':>10s} {'std':>10s} {'min':>10s} {'max':>10s}  {'Δ_today':>10s}")
    print("-" * 92)
    summary_lines = []
    for k in sleeve_keys:
        vals = [v for _, v in trajectories[k]]
        n_valid = sum(1 for v in vals if v is not None)
        clean = [v for v in vals if v is not None]
        if not clean:
            print(f"{k:30s} {n_valid:>4d}    {'n/a':>10s}    {'n/a':>10s}    {'n/a':>10s}    {'n/a':>10s}    {'n/a':>10s}")
            continue
        m = sum(clean) / len(clean)
        s = _std(clean)
        lo = min(clean)
        hi = max(clean)
        delta_today = clean[-1] - clean[-2] if len(clean) >= 2 else None
        m_s = f"{m:+.4f}"
        s_s = f"{s:.4f}" if s is not None else "n/a"
        lo_s = f"{lo:+.4f}"
        hi_s = f"{hi:+.4f}"
        d_s = f"{delta_today:+.4f}" if delta_today is not None else "n/a"
        print(f"{k:30s} {n_valid:>4d} {m_s:>10s} {s_s:>10s} {lo_s:>10s} {hi_s:>10s}  {d_s:>10s}")
        summary_lines.append((k, n_valid, m, s, lo, hi, delta_today))

    # Vol-carry day-over-day Δterm_premium proxy ("pseudo-P&L" of short-vol position)
    diffs_tp = _diffs([v for _, v in trajectories["vol_carry_term_premium"]])
    if diffs_tp:
        dmean = sum(diffs_tp) / len(diffs_tp)
        dstd = _std(diffs_tp)
        print()
        print(f"  vol_carry day-over-day Δterm_premium (n={len(diffs_tp)}):  mean={dmean:+.3f}  std={dstd:.3f}" if dstd is not None else
              f"  vol_carry day-over-day Δterm_premium (n={len(diffs_tp)}):  mean={dmean:+.3f}")

    # Per-sleeve NAV-based metrics (Sharpe / maxDD) — the 60d verdict primary inputs
    print(_format_section_header("Per-sleeve NAV metrics (60d verdict inputs)"))
    nav_summaries = []
    for sleeve_id in ["vol_carry", "regime_nowcast", "macro_overlay"]:
        nav_rows = _read_sleeve_nav(sleeve_id)
        if not nav_rows:
            print(f"  {sleeve_id:20s}  no NAV data (run nav_ledger.py daily to accumulate)")
            nav_summaries.append((sleeve_id, 0, None, None, None, None))
            continue
        daily_pnls = [_safe_float(r.get("daily_pnl_usd", "")) or 0.0 for r in nav_rows]
        cum_navs = [_safe_float(r.get("cumulative_nav_usd", "")) or 0.0 for r in nav_rows]
        sharpe = _sharpe_annualized([p for p in daily_pnls if p is not None])
        max_dd = _max_drawdown([n for n in cum_navs if n is not None])
        n = len(nav_rows)
        last_cum = cum_navs[-1] if cum_navs else None
        sharpe_s = f"{sharpe:+.3f}" if sharpe is not None else "n/a"
        dd_s = f"{max_dd * 100:+.2f}%" if max_dd is not None else "n/a"
        last_s = f"${last_cum:,.0f}" if last_cum is not None else "n/a"
        # For sleeve_2, NAV is "cumulative excess" not absolute — note this
        note = "" if sleeve_id != "regime_nowcast" else " (cumulative excess)"
        print(f"  {sleeve_id:20s}  n={n:>3d}  Sharpe(ann)={sharpe_s:>8s}  maxDD={dd_s:>10s}  cumNAV={last_s}{note}")
        nav_summaries.append((sleeve_id, n, sharpe, max_dd, last_cum, note))

    # Pairwise correlation (signal trajectories)
    print(_format_section_header("Pairwise signal correlation"))
    if n_days < 3:
        print(f"  INSUFFICIENT: need ≥3 days for stable correlation")
    else:
        for i, ki in enumerate(sleeve_keys):
            for kj in sleeve_keys[i + 1:]:
                xs = [v for _, v in trajectories[ki]]
                ys = [v for _, v in trajectories[kj]]
                rho = _pearson(xs, ys)
                if rho is None:
                    print(f"  {ki:30s} × {kj:30s}  n/a (insufficient overlap or zero variance)")
                else:
                    bar = "█" * max(1, min(40, int(abs(rho) * 40)))
                    sign = "+" if rho >= 0 else "-"
                    print(f"  {ki:30s} × {kj:30s}  ρ = {rho:+.3f} {sign}{bar}")

    # R77 baseline comparison (optional, no fail if missing)
    print(_format_section_header("R77 baseline (Supabase fusion_paper_nav)"))
    r77 = _try_fetch_r77_nav()
    if r77 is None:
        print(f"  R77 NAV not fetched (SUPABASE_URL/KEY not set, or fetch failed)")
        print(f"  → set SUPABASE_URL and SUPABASE_KEY env vars to enable orthogonal comparison")
    else:
        print(f"  R77 NAV rows: {len(r77)}  ({r77[0][0]} → {r77[-1][0]})")
        # Compute R77 daily return, correlate with vol_carry Δterm_premium
        r77_returns = []
        for i in range(1, len(r77)):
            prev_d, prev_v = r77[i - 1]
            cur_d, cur_v = r77[i]
            if prev_v != 0:
                r77_returns.append((cur_d, (cur_v - prev_v) / prev_v))
        # Match on overlapping dates
        sleeve1_dates = {d for d, _ in trajectories["vol_carry_term_premium"]}
        overlap = [(d, r) for d, r in r77_returns if d in sleeve1_dates]
        # Build paired sleeve1 returns (Δterm_premium normalized) and r77 returns
        sleeve1_paired = []
        s1_vals = [v for _, v in trajectories["vol_carry_term_premium"]]
        s1_dates = [d for d, _ in trajectories["vol_carry_term_premium"]]
        for j in range(1, len(s1_dates)):
            if s1_vals[j - 1] is None or s1_vals[j] is None:
                continue
            sleeve1_paired.append((s1_dates[j], s1_vals[j] - s1_vals[j - 1]))
        # Correlation on overlap
        overlap_dict = dict(overlap)
        sleeve1_xs = [r for d, r in sleeve1_paired if d in overlap_dict]
        r77_ys = [overlap_dict[d] for d, _ in sleeve1_paired if d in overlap_dict]
        if len(sleeve1_xs) >= 3:
            rho_r77 = _pearson(sleeve1_xs, r77_ys)
            if rho_r77 is not None:
                print(f"  vol_carry Δterm_premium vs R77 daily return  ρ = {rho_r77:+.3f}  (n={len(sleeve1_xs)})")
            else:
                print(f"  ρ = n/a (zero variance)")

    # Action banner
    print(_format_section_header("Action"))
    if n_days < DEFAULT_MIN_DAYS:
        days_left = max(0, 60 - n_days)
        print(f"  ⏳  in-flight — need {DEFAULT_MIN_DAYS - n_days} more day(s) for first weekly verdict")
        print(f"  ⏳  60-day final verdict window: ~{days_left} day(s) remaining")
    else:
        print(f"  ✅  verdict-eligible window reached ({n_days} ≥ {DEFAULT_MIN_DAYS})")
        print(f"  → next phase: implement daily mark-to-market ledger (out of scope of prototype)")

    # Persist markdown
    md_lines = []
    md_lines.append(f"# Weekly summary — 3-sleeve parallel paper phase")
    md_lines.append(f"\n_Generated: {datetime.now(timezone.utc).isoformat()}_")
    md_lines.append(f"\n- Source: `{DAILY_SUMMARY_PATH}`")
    md_lines.append(f"- Window: {first_date} → {last_date} ({n_days} day(s))")
    md_lines.append(f"- Threshold for verdict: ≥{DEFAULT_MIN_DAYS} days (Sharpe/maxDD/correlations)")
    md_lines.append(f"\n## Honest scope\n")
    md_lines.append(
        "This module operates on SIGNAL TRAJECTORIES (term_premium, P(RISK_ON), "
        "long-short imbalance), NOT on mark-to-market P&L. Sharpe/maxDD here are PROXIES "
        "for sleeve activity, not alpha evidence. The 60-day final verdict requires a "
        "daily NAV ledger (next-phase work; out of scope for this prototype)."
    )
    md_lines.append(f"\n## Per-sleeve trajectory\n")
    md_lines.append("| Sleeve | n | mean | std | min | max | Δ_today |")
    md_lines.append("|---|---|---|---|---|---|---|")
    for k, n, m, s, lo, hi, d in summary_lines:
        s_s = f"{s:.4f}" if s is not None else "n/a"
        d_s = f"{d:+.4f}" if d is not None else "n/a"
        md_lines.append(f"| `{k}` | {n} | {m:+.4f} | {s_s} | {lo:+.4f} | {hi:+.4f} | {d_s} |")
    md_lines.append(f"\n## Per-sleeve NAV metrics (60d verdict primary inputs)\n")
    md_lines.append("| Sleeve | n | Sharpe (ann) | maxDD | cumNAV |")
    md_lines.append("|---|---|---|---|---|")
    for sleeve_id, n, sharpe, max_dd, last_cum, note in nav_summaries:
        sharpe_s = f"{sharpe:+.3f}" if sharpe is not None else "n/a"
        dd_s = f"{max_dd * 100:+.2f}%" if max_dd is not None else "n/a"
        last_s = f"${last_cum:,.0f}" if last_cum is not None else "n/a"
        md_lines.append(f"| `{sleeve_id}`{note} | {n} | {sharpe_s} | {dd_s} | {last_s} |")
    md_lines.append(f"\n## Status\n")
    if n_days < DEFAULT_MIN_DAYS:
        md_lines.append(f"- ⏳ IN-FLIGHT ({DEFAULT_MIN_DAYS - n_days} more day(s) needed for verdict)")
    else:
        md_lines.append(f"- ✅ VERDICT-ELIGIBLE (n={n_days} ≥ {DEFAULT_MIN_DAYS})")
    with open(WEEKLY_SUMMARY_PATH, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print()
    print(f"  ✓ weekly summary written: {WEEKLY_SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())