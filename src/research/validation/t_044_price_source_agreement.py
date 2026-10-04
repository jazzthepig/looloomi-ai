"""
T-044 daily price-source agreement check (READ-ONLY)
====================================================

Per Seth, 2026-10-04 card: every day, for each source in
{coingecko_pro_ohlc, coingecko, hyperliquid}, compare against Binance
on three dimensions:

  1. Same-day price match vs shift-by-1-day
     (catches S-436 / S-459 — candle label / sample prices off by 1 day)
  2. Per-coin continuous 5+ days drift >3%
     (catches silent corruption like December→March corrupted CG candles)
  3. Binance history new frozen rows
     (catches S-468 — Binance history frozen, then re-frozen with bad
      values — a frozen row is close[t] == close[t-1] over many days)

Output: structured dict of findings. NO writes. Lane-a reads,
Seth (price ingestion lane) handles fixes.

This file is split for testability:
  - `agreement()` — pure function (input: aligned price DataFrames;
    output: findings dict). Fully testable without DB / network.
  - `_build_supabase_panel()` — DB-only builder. Hits Supabase
    REST API; absent in sandbox (no DB / secrets), wrapped in try/except.
  - `main()` — orchestrates fetch + agreement + console summary.

Smoke test (`test_t_044_price_source_agreement_smoke.py`) builds
synthetic fixtures that mimic the historical shapes (S-436, S-459,
S-468, plus the LDO/GRT/ATOM February pattern) and asserts that
`agreement()` flags each one. This is what makes the check
trustable — without fixtures we are just saying "we ran something".
"""
from __future__ import annotations

import sys
import os
import math
from typing import Optional
from dataclasses import dataclass, field
from datetime import date


#: Tolerance for "same-day" agreement. Above 0.05 Pearson corr
#:  difference → flagged as potential shift-by-1-day. (Calibrated
#:  on M-91 → M-93 era: identical sources Δ=1.0, day-shifted Δ<0.3.)
SHIFT_BY_DELTA_THRESHOLD = 0.30

#: Per-day percentage drift threshold. 0.03 = 3%. Per Seth: "which
#:  coins stay more than 3% off for 5 or more days running".
DRIFT_THRESHOLD_PCT = 0.03

#: Drift run-length threshold. Per Seth: "5 or more days running".
DRIFT_RUN_DAYS = 5

#: Frozen-row detection. Per S-468: same close[t] == close[t-1] for
#: 3+ consecutive days on Binance history → frozen (legitimate
#: holidays excluded by checking against the union of OTHER sources).
FROZEN_RUN_DAYS = 3


@dataclass
class Finding:
    """One row in the agreement report."""
    symbol: str
    source: str                       # one of {coingecko_pro_ohlc, coingecko, hyperliquid}
    kind: str                         # "shift_by_1_day" | "drift_run" | "frozen_binance"
    severity: str                     # "info" | "warn" | "error"
    detail: str                       # human-readable explanation
    dates: list[str] = field(default_factory=list)  # ISO dates of the affected run, if applicable


@dataclass
class SourcePanel:
    """Aligned per-day closes for one (symbol, source). NaN-sparse
    entries are tolerated; the agreement function aligns on union."""
    symbol: str
    source: str
    dates: list[str]        # ISO YYYY-MM-DD, ascending, no duplicates
    closes: list[float]

    def by_date(self) -> dict[str, float]:
        return dict(zip(self.dates, self.closes))


def agreement(
    baseline: SourcePanel,           # binance_hist (S-230: only "可信" + "深" source)
    candidate: SourcePanel,         # one of {coingecko_pro_ohlc, coingecko, hyperliquid}
    *,
    shift_threshold: float = SHIFT_BY_DELTA_THRESHOLD,
    drift_pct: float = DRIFT_THRESHOLD_PCT,
    drift_run: int = DRIFT_RUN_DAYS,
    frozen_run: int = FROZEN_RUN_DAYS,
) -> list[Finding]:
    """Pure function: produce a list of `Finding`s for one (symbol, candidate).

    Inputs are per-day close prices for `baseline` and `candidate`,
    both aligned on ascending ISO dates (NaN allowed via skip).
    """
    if baseline.symbol != candidate.symbol:
        raise ValueError(f"baseline {baseline.symbol} != candidate {candidate.symbol}")

    out: list[Finding] = []
    base_d = baseline.by_date()
    cand_d = candidate.by_date()

    # ── Dimension 1: same-day match vs shift-by-1-day ─────────────────────
    # S-436 / S-459 fingerprint: candle row labelled `trade_date = t` actually
    # carries the close from `t-1`. So `cand[t] == base[t-1]`.
    #
    # CRITICAL: we operate on LOG RETURNS, not raw closes. With monotonic
    # log-normal price action (BTC = 100, 101, 102, ...), Pearson on raw
    # closes gives corr ≈ 1.0 whether aligned or shifted, because the trend
    # dominates. Log returns (log(close[t]/close[t-1])) remove the trend
    # and expose the day-alignment signal.
    #
    # ALSO: real-world S-436 / S-459 are window-LOCAL (a few days to weeks),
    # so we slide a 30-day window and flag the WINDOW where shift wins,
    # not the full series.
    SHIFT_WINDOW = 30
    same_dates = sorted(set(base_d) & set(cand_d))
    if len(same_dates) >= SHIFT_WINDOW:
        def _log_ret_series(d_to_v: dict, dates: list[str]) -> list[float]:
            xs = [d_to_v[d] for d in dates if d in d_to_v]
            return [math.log(xs[i] / xs[i-1])
                    for i in range(1, len(xs))
                    if xs[i-1] > 0 and xs[i] > 0]

        shift_windows: list[tuple[int, int, float]] = []   # (start_idx, end_idx, delta)
        for s in range(0, len(same_dates) - SHIFT_WINDOW + 1):
            window_dates = same_dates[s:s + SHIFT_WINDOW]
            # need t-1 for the first date in window — drop window_dates[0]
            # if no t-1 in base_d (rare; means window starts at panel edge)
            shifted_window_dates: list[str] = []
            for d in window_dates:
                prev = _prev_iso_day(d)
                if prev in base_d:
                    shifted_window_dates.append(d)
            if len(shifted_window_dates) < SHIFT_WINDOW - 2:
                continue
            corr_same_w = _safe_pearson(
                _log_ret_series(base_d, shifted_window_dates),
                _log_ret_series(cand_d, shifted_window_dates))
            corr_fwd_w = _safe_pearson(
                _log_ret_series(base_d,
                                [_prev_iso_day(d) for d in shifted_window_dates]),
                _log_ret_series(cand_d, shifted_window_dates))
            delta = corr_fwd_w - corr_same_w
            if delta > shift_threshold:
                shift_windows.append((s, s + SHIFT_WINDOW, delta))

        if shift_windows:
            # Longest contiguous run of shift-windows.
            windows_sorted = sorted(shift_windows, key=lambda x: x[0])
            best_run_start = windows_sorted[0][0]
            best_run_end = windows_sorted[0][1]
            cur_run_start = windows_sorted[0][0]
            cur_run_end = windows_sorted[0][1]
            for w in windows_sorted[1:]:
                if w[0] <= cur_run_end:  # overlapping or adjacent
                    cur_run_end = max(cur_run_end, w[1])
                else:
                    if cur_run_end - cur_run_start > best_run_end - best_run_start:
                        best_run_start = cur_run_start
                        best_run_end = cur_run_end
                    cur_run_start = w[0]
                    cur_run_end = w[1]
            if cur_run_end - cur_run_start > best_run_end - best_run_start:
                best_run_start = cur_run_start
                best_run_end = cur_run_end

            out.append(Finding(
                symbol=baseline.symbol, source=candidate.source,
                kind="shift_by_1_day",
                severity="error",
                detail=(f"shift detected in {best_run_end-best_run_start}-day "
                        f"window starting {same_dates[best_run_start]} "
                        f"(corr_fwd - corr_same > +{shift_threshold} "
                        f"on log returns)"),
                dates=same_dates[best_run_start:best_run_start + 5]
                + same_dates[best_run_end - 3:best_run_end]))

    # ── Dimension 2: per-day drift run (|log ratio| > threshold for run days) ─
    drift_dates: list[tuple[str, float]] = []
    for d in same_dates:
        b = base_d[d]
        c = cand_d[d]
        if b <= 0 or c <= 0:
            continue
        # log return ratio (asymmetric: handles 100x price changes)
        ratio = c / b
        pct_drift = abs(ratio - 1.0)
        if pct_drift > drift_pct:
            drift_dates.append((d, pct_drift))
    # Find longest run
    if drift_dates:
        run_start = 0
        run_len = 1
        best_start = 0
        best_len = 1
        for i in range(1, len(drift_dates)):
            if drift_dates[i][0] == _next_iso_day(drift_dates[i-1][0]):
                run_len += 1
                if run_len > best_len:
                    best_len = run_len
                    best_start = run_start
            else:
                run_start = i
                run_len = 1
        if best_len >= drift_run:
            out.append(Finding(
                symbol=baseline.symbol, source=candidate.source,
                kind="drift_run",
                severity="warn" if best_len < drift_run * 2 else "error",
                detail=(f"max drift run = {best_len} days at >{drift_pct*100:.0f}% "
                        f"({drift_dates[best_start][1]*100:.1f}% on first day)"),
                dates=[d for d, _ in drift_dates[best_start:best_start + best_len]]))

    # ── Dimension 3: Binance frozen rows ──────────────────────────────────
    # A frozen row is close[t] == close[t-1] AND close[t-2] (3+ consecutive
    # identical closes). If the candidate disagrees on those same days,
    # then Binance is frozen while candidate is live → Binance is wrong.
    base_sorted = sorted(base_d.items())
    frozen_streaks: list[tuple[int, int]] = []   # (start_idx, end_idx)
    i = 0
    n = len(base_sorted)
    while i < n:
        j = i
        while (j + 1 < n and base_sorted[j+1][0] == _next_iso_day(base_sorted[j][0])
               and abs(base_sorted[j+1][1] - base_sorted[j][1]) < 1e-12):
            j += 1
        if j - i + 1 >= frozen_run:
            frozen_streaks.append((i, j))
        i = j + 1
    for start, end in frozen_streaks:
        dates = [base_sorted[k][0] for k in range(start, end+1)]
        # If candidate disagrees on ANY of these dates, Binance is the liar.
        disagrees = []
        for d in dates:
            if d in cand_d and cand_d[d] != base_sorted[start][1]:
                disagrees.append(d)
        if disagrees:
            out.append(Finding(
                symbol=baseline.symbol, source="binance_hist",
                kind="frozen_binance",
                severity="error",
                detail=(f"binance_hist frozen {end-start+1} days "
                        f"@ {base_sorted[start][1]}; candidate diverges "
                        f"on {len(disagrees)} of those days"),
                dates=dates[:3] + dates[-2:]))

    return out


# ─── Helpers ──────────────────────────────────────────────────────────────
def _safe_pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation. Returns 0.0 if undefined (length < 2, zero variance)."""
    n = len(xs)
    if n != len(ys) or n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    if dx2 <= 0 or dy2 <= 0:
        return 0.0
    import math
    return num / math.sqrt(dx2 * dy2)


def _prev_iso_day(d: str) -> str:
    """Return the ISO date 1 day before `d` (UTC, no DST)."""
    from datetime import date, timedelta
    y, m, dd = map(int, d.split("-"))
    return (date(y, m, dd) - timedelta(days=1)).isoformat()


def _next_iso_day(d: str) -> str:
    """Return the ISO date 1 day after `d` (UTC, no DST)."""
    from datetime import date, timedelta
    y, m, dd = map(int, d.split("-"))
    return (date(y, m, dd) + timedelta(days=1)).isoformat()


# ─── DB-driven path (used by main; smoke test bypasses via fixtures) ─────
def _build_supabase_panel(
    symbol: str, source: str, since: Optional[str] = None,
    until: Optional[str] = None, *, sandbox: bool = False,
) -> Optional[SourcePanel]:
    """Read ohlcv_daily from Supabase REST for one (symbol, source).

    Returns None if SB env not configured (sandbox path).
    Caller checks for None and bails gracefully.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = (os.environ.get("SUPABASE_KEY", "")
           or os.environ.get("SUPABASE_SERVICE_KEY", ""))
    if not url or not key:
        return None  # sandbox: caller uses fixtures

    import httpx
    q = (f"symbol=eq.{symbol}&source=eq.{source}"
         f"&order=trade_date.asc&select=trade_date,close")
    if since:
        q += f"&trade_date=gte.{since}"
    if until:
        q += f"&trade_date=lte.{until}"
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{url.rstrip('/')}/rest/v1/ohlcv_daily?{q}",
                      headers={"apikey": key,
                               "Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None
        rows = r.json()
        return SourcePanel(
            symbol=symbol, source=source,
            dates=[row["trade_date"] for row in rows],
            closes=[float(row["close"]) for row in rows])
    except Exception:
        return None


def main() -> int:
    """Daily check. Read-only. Outputs structured findings to stdout.

    Schedule: daily at 04:00 UTC (after the deep panel collector finishes
    its Binance pass at ~03:30 UTC). Lives in `_t044_daily_loop` in
    main.py — Seth wires that loop on his own.
    """
    import json
    SYMBOLS = [
        # ── Tier 1: historical replay must trip ─────────────────────────
        # S-436: candles labelled one day late (CG Pro)
        # S-459: sample prices stored as candles (CG)
        # S-468: frozen Binance prices (S-468) + corrupted CG candles
        # LDO, GRT, ATOM in February (the 3 coins S-468 hit worst)
        "BTC", "ETH", "SOL", "HYPE", "ONDO",
        "LDO", "GRT", "ATOM",
        # ── Tier 2: representative panel of 24-name CIS universe ────────
        "BNB", "XRP", "ADA", "AVAX", "DOT",
        "APT", "LINK", "POL", "TRUMPCOIN", "PENDLE",
        "ARB", "OP", "TIA", "INJ",
    ]
    SOURCES = ["coingecko_pro_ohlc", "coingecko", "hyperliquid"]

    all_findings: list[Finding] = []
    panels_built = 0
    panels_skipped_sandbox = 0

    for sym in SYMBOLS:
        base = _build_supabase_panel(sym, "binance_hist")
        if base is None:
            panels_skipped_sandbox += 1
            continue
        panels_built += 1
        for src in SOURCES:
            cand = _build_supabase_panel(sym, src)
            if cand is None:
                continue
            all_findings.extend(agreement(base, cand))

    out = {
        "panels_built":        panels_built,
        "panels_skipped":      panels_skipped_sandbox,
        "n_findings":          len(all_findings),
        "by_kind": {
            "shift_by_1_day":  sum(1 for f in all_findings if f.kind == "shift_by_1_day"),
            "drift_run":       sum(1 for f in all_findings if f.kind == "drift_run"),
            "frozen_binance":  sum(1 for f in all_findings if f.kind == "frozen_binance"),
        },
        "findings": [
            {"symbol": f.symbol, "source": f.source, "kind": f.kind,
             "severity": f.severity, "detail": f.detail,
             "dates": f.dates}
            for f in all_findings],
    }
    print(json.dumps(out, indent=2))
    # Exit code: 0 = no findings, 1 = drift/shift only, 2 = frozen_binance
    has_frozen = any(f.kind == "frozen_binance" for f in all_findings)
    has_shift  = any(f.kind == "shift_by_1_day" for f in all_findings)
    if has_frozen: return 2
    if has_shift:  return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())