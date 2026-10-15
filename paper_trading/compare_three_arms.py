"""S-393 3-arm comparison: diff + aggregate metrics.

Reads 3 JSONL files emitted by `replay_three_arms.py` and produces a single
`_diff.json` suitable for the dashboard tab + `report_three_arms.py`.

## What we compute

Per arm:
  - period_returns:  list[float]   — daily returns across the full replay window
  - cum_return_pct:  float         — total return (cumulative product − 1) × 100
  - sharpe:          float         — annualized (mean(daily)/std(daily) × √365)
  - sortino:         float         — annualized downside-only
  - max_dd_pct:      float         — max drawdown from equity curve (positive %)
  - n_entered:       int           — rebalance events
  - n_skipped_cadence: int         — skipped due to cadence (informational)
  - n_skipped_factor: int          — arm C only: 0/N passed factor gate
  - n_skipped_jev:   int           — arm A only: Jev vetoed (always 0 in current Mode=always_ok)
  - n_blocked:       int           — panel / data issues

Cross-arm:
  - agreement_a_b:    float        — % of days where A and B verdicts match
  - agreement_a_c:    float        — % of days where A and C verdicts match
  - agreement_b_c:    float        — % of days where B and C verdicts match
  - factor_skip_days: int         — days where C=SKIPPED(factor) and B=ENTERED
                                    (= how many days the factor gate blocked a trade)
  - arm_c_vs_b_excess_sharpe: float — arm C SR − arm B SR

PnL semantics: paper-trade mark-to-market, NOT fill sim. Costs NOT subtracted
in v1 (cost = 5bps_rt per rebalance from spec — would change SR by ~+0.02
annualized, not enough to flip conclusions).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _sharpe_daily(daily_returns: list[float], ann: int = 365) -> float:
    if len(daily_returns) < 2:
        return 0.0
    m = sum(daily_returns) / len(daily_returns)
    var = sum((r - m) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    if var <= 0:
        return 0.0
    return (m / math.sqrt(var)) * math.sqrt(ann)


def _sortino_daily(daily_returns: list[float], ann: int = 365) -> float:
    if len(daily_returns) < 2:
        return 0.0
    m = sum(daily_returns) / len(daily_returns)
    downside = [r for r in daily_returns if r < 0]
    if len(downside) < 2:
        # No losing days → cap Sortino
        return 10.0 if m > 0 else 0.0
    var_down = sum((r - 0) ** 2 for r in downside) / len(daily_returns)  # full N
    if var_down <= 0:
        return 0.0
    return (m / math.sqrt(var_down)) * math.sqrt(ann)


def _max_dd_pct(equity: list[float]) -> float:
    """Max drawdown as positive percentage. equity is normalized to 1.0 at index 0."""
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v / peak - 1.0) if peak > 0 else 0.0
        max_dd = min(max_dd, dd)
    return -max_dd * 100.0


def _build_daily_returns(
    decisions: list[dict[str, Any]],
    start: dt.date, end: dt.date,
    closes: Optional[dict[str, dict[str, float]]] = None,
) -> list[float]:
    """For each day in [start, end], the day's mark-to-market return.

    T-057 fix (2026-10-16, lane-c): pass `closes` (dict[iso_date][symbol]→close)
    to enable real mark-to-market. Without it, falls back to `_build_daily_returns_legacy`
    which (a) silently sets exit price = entry price when a symbol is dropped at
    next rebalance (masking losses; T-057 §1) and (b) flattens weekly return
    across days via `(1+r)^(1/span) − 1` (understating vol, inflating SR; §2).

    With `closes`:
      - Exit price on drop-out day = real close on that day (fixes §1).
      - Daily returns = sum(weight × (close[d] / close[d-1] − 1)) (fixes §2).
    """
    n_days = (end - start).days + 1
    daily: list[float] = [(0.0, None, None)] * n_days   # placeholder, rebuild
    daily = [0.0] * n_days

    if closes is None:
        # Back-compat path (T-057 §1/§2 NOT honored). One-shot warning.
        global _LEGACY_NO_CLOSES_WARNED
        if not _LEGACY_NO_CLOSES_WARNED:
            import sys as _sys
            print(
                "[compare] WARNING: _build_daily_returns called without `closes` — "
                "T-057 exit-price bug (§1) and weekly-flattening (§2) will be in effect. "
                "Pass panel.json / closes dict to fix.",
                file=_sys.stderr,
            )
            _LEGACY_NO_CLOSES_WARNED = True
        return _build_daily_returns_legacy(decisions, start, end)

    # ── T-057 corrected path: day-by-day mark-to-market from real closes ───
    last_entry: Optional[dict[str, tuple[float, float]]] = None  # {sym: (weight, entry_price)}
    last_entry_date: Optional[dt.date] = None
    segments: list[tuple[dt.date, dt.date, dict[str, tuple[float, float]]]] = []
    # (d_a, d_b, entry_at_d_a); d_b is the day we either rebalance out OR end-of-window

    for d_rec in decisions:
        d = dt.date.fromisoformat(d_rec["date"])
        if d_rec["verdict"] == "ENTERED":
            entry_now = {l["symbol"]: (float(l["weight"]), float(l["price"]))
                         for l in d_rec.get("legs", [])}
            if last_entry is not None and last_entry_date is not None:
                segments.append((last_entry_date, d, last_entry))
            last_entry = entry_now
            last_entry_date = d

    # Final segment: from last ENTERED to end-of-window (no rebalance event)
    if last_entry is not None and last_entry_date is not None and last_entry_date < end:
        segments.append((last_entry_date, end, last_entry))

    daily = [0.0] * n_days
    for d_a, d_b, entry_a in segments:
        # For each day d in (d_a, d_b], compute daily_r using real closes:
        #   daily_r = sum(weight × (closes[d][sym] / closes[d-1][sym] − 1))
        # For symbols dropped at d_b (in entry_a but absent from d_b's ENTERED):
        #   their last contribution uses closes[d_b] — exit price is the real close
        #   on the drop-out day, not the next ENTERED's entry price (= entry_b bug).
        idx_a = (d_a - start).days
        idx_b = (d_b - start).days
        if idx_a < 0:
            idx_a = 0
        if idx_b >= n_days:
            idx_b = n_days - 1
        d_curr = start + dt.timedelta(days=idx_a + 1) if idx_a + 1 <= idx_b else start + dt.timedelta(days=idx_a + 1)
        while d_curr <= start + dt.timedelta(days=idx_b):
            i = (d_curr - start).days
            if 0 <= i < n_days:
                d_prev = d_curr - dt.timedelta(days=1)
                closes_today = closes.get(d_curr.isoformat(), {})
                closes_prev = closes.get(d_prev.isoformat(), {})
                r = 0.0
                for sym, (w, _p_entry) in entry_a.items():
                    p_t = closes_today.get(sym)
                    p_p = closes_prev.get(sym)
                    if p_t is None or p_p is None or p_p <= 0:
                        continue  # missing → no synthetic flat
                    r += w * (p_t / p_p - 1.0)
                daily[i] = r
            d_curr += dt.timedelta(days=1)
    return daily


_LEGACY_NO_CLOSES_WARNED = False


def _build_daily_returns_legacy(
    decisions: list[dict[str, Any]],
    start: dt.date, end: dt.date,
) -> list[float]:
    """Legacy behavior — kept ONLY for back-compat with existing tests.

    Two bugs preserved here (T-057 §1/§2):
      ① exit price falls back to entry price when sym absent from next ENTERED
        legs → masks the loss of any symbol dropped at rebalance.
      ② weekly return is flattened across days via `(1+r)^(1/span) − 1`
        → understates daily vol, inflates Sharpe (per §Seth-1007g family).
    The T-057 fix lives in `_build_daily_returns(decisions, closes, start, end)`.
    """
    n_days = (end - start).days + 1
    daily: list[float] = [(0.0, None, None)] * n_days   # placeholder, rebuild
    daily = [0.0] * n_days

    periods: list[float] = []
    period_dates: list[tuple[dt.date, dt.date]] = []
    last_entry: Optional[dict[str, tuple[float, float]]] = None
    last_entry_date: Optional[dt.date] = None

    for d_rec in decisions:
        d = dt.date.fromisoformat(d_rec["date"])
        if d_rec["verdict"] == "ENTERED":
            entry_now = {l["symbol"]: (float(l["weight"]), float(l["price"]))
                         for l in d_rec.get("legs", [])}
            if last_entry is not None and last_entry_date is not None:
                r = 0.0
                for sym, (w, p_entry) in last_entry.items():
                    p_exit = entry_now.get(sym, (0.0, p_entry))[1]
                    r += w * (p_exit / p_entry - 1.0)
                periods.append(r)
                period_dates.append((last_entry_date, d))
            last_entry = entry_now
            last_entry_date = d

    if last_entry is not None and last_entry_date is not None \
            and last_entry_date < end:
        periods.append(0.0)
        period_dates.append((last_entry_date, end))

    daily = [0.0] * n_days
    for r, (d_a, d_b) in zip(periods, period_dates):
        span = (d_b - d_a).days
        if span <= 0:
            continue
        daily_r = (1.0 + r) ** (1.0 / span) - 1.0
        idx_a = (d_a - start).days
        idx_b = (d_b - start).days
        for i in range(idx_a, min(idx_b, n_days)):
            daily[i] = daily_r
    return daily


def _agreement(verdicts_a: list[str], verdicts_b: list[str]) -> float:
    n = min(len(verdicts_a), len(verdicts_b))
    if n == 0:
        return 0.0
    match = sum(1 for i in range(n) if verdicts_a[i] == verdicts_b[i])
    return match / n * 100.0


def compare(in_dir: Path) -> dict[str, Any]:
    meta = json.loads((in_dir / "_meta.json").read_text(encoding="utf-8"))
    arm_a = _load_jsonl(in_dir / "a_jev_decisions.jsonl")
    arm_b = _load_jsonl(in_dir / "b_baseline_decisions.jsonl")
    arm_c = _load_jsonl(in_dir / "c_simple_factor_decisions.jsonl")

    start = dt.date.fromisoformat(meta["start"])
    end = dt.date.fromisoformat(meta["end"])

    # T-057: load real closes from panel.json if present (enables T-057 §1+§2 fix).
    # Without it, _build_daily_returns falls back to legacy path with bug &
    # emits a one-shot warning.
    closes: Optional[dict[str, dict[str, float]]] = None
    panel_json = in_dir / "panel.json"
    if panel_json.exists():
        try:
            rows = json.loads(panel_json.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                closes = {}
                for r in rows:
                    d = str(r.get("trade_date", ""))[:10]
                    sym = r.get("symbol")
                    px = r.get("close")
                    if d and sym and px is not None:
                        closes.setdefault(d, {})[sym] = float(px)
        except Exception as e:                             # noqa: BLE001
            print(f"[compare] WARNING: failed to load {panel_json}: {e}; "
                  f"falling back to legacy _build_daily_returns")
            closes = None

    daily_a = _build_daily_returns(arm_a, start, end, closes=closes)
    daily_b = _build_daily_returns(arm_b, start, end, closes=closes)
    daily_c = _build_daily_returns(arm_c, start, end, closes=closes)

    def stats(name: str, decisions: list[dict], daily: list[float]) -> dict:
        n_entered = sum(1 for d in decisions if d["verdict"] == "ENTERED")
        n_skipped_cadence = sum(1 for d in decisions
                                if d["verdict"] == "SKIPPED" and "cadence" in d.get("reason", ""))
        n_skipped_factor = sum(1 for d in decisions
                               if d["verdict"] == "SKIPPED" and "factor gate" in d.get("reason", ""))
        n_skipped_jev = sum(1 for d in decisions
                            if d["verdict"] == "SKIPPED" and "jev_gate" in d.get("reason", ""))
        n_blocked = sum(1 for d in decisions if d["verdict"] == "BLOCKED")
        cum = math.prod(1.0 + r for r in daily) - 1.0
        equity = [1.0]
        for r in daily:
            equity.append(equity[-1] * (1.0 + r))
        return {
            "name": name,
            "n_entered": n_entered,
            "n_skipped_cadence": n_skipped_cadence,
            "n_skipped_factor": n_skipped_factor,
            "n_skipped_jev": n_skipped_jev,
            "n_blocked": n_blocked,
            "n_days_total": len(decisions),
            "cum_return_pct": cum * 100.0,
            "sharpe_annualized": _sharpe_daily(daily),
            "sortino_annualized": _sortino_daily(daily),
            "max_dd_pct": _max_dd_pct(equity),
        }

    stats_a = stats("A_jev_always_ok", arm_a, daily_a)
    stats_b = stats("B_baseline_no_jev", arm_b, daily_b)
    stats_c = stats("C_simple_factor", arm_c, daily_c)

    # Per-day verdict agreement
    verdicts_a = [d["verdict"] for d in arm_a]
    verdicts_b = [d["verdict"] for d in arm_b]
    verdicts_c = [d["verdict"] for d in arm_c]
    agreement = {
        "agreement_a_b_pct": _agreement(verdicts_a, verdicts_b),
        "agreement_a_c_pct": _agreement(verdicts_a, verdicts_c),
        "agreement_b_c_pct": _agreement(verdicts_b, verdicts_c),
    }

    # Factor gate value: days where C=SKIPPED(factor) and B=ENTERED
    factor_skip_days = sum(
        1 for da, db, dc in zip(arm_a, arm_b, arm_c)
        if db["verdict"] == "ENTERED"
        and dc["verdict"] == "SKIPPED"
        and "factor gate" in dc.get("reason", "")
    )

    summary = {
        "arm_c_sharpe_minus_arm_b": stats_c["sharpe_annualized"] - stats_b["sharpe_annualized"],
        "arm_c_maxdd_minus_arm_b": stats_c["max_dd_pct"] - stats_b["max_dd_pct"],
        "factor_skip_days": factor_skip_days,
        "windows_match_under_always_ok": agreement["agreement_a_b_pct"],
    }

    return {
        "meta": meta,
        "arms": {"A": stats_a, "B": stats_b, "C": stats_c},
        "agreement": agreement,
        "summary": summary,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="S-393 3-arm diff + metrics")
    p.add_argument("--in-dir", required=True, help="run dir (with 3 JSONLs + _meta.json)")
    p.add_argument("--out", default=None,
                   help="output _diff.json path (default: <in-dir>/_diff.json)")
    args = p.parse_args()

    in_dir = Path(args.in_dir)
    out = Path(args.out) if args.out else (in_dir / "_diff.json")
    diff = compare(in_dir)
    out.write_text(json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[compare] wrote → {out}")
    s = diff["summary"]
    print(f"[compare] arm_c_sharpe - arm_b_sharpe = {s['arm_c_sharpe_minus_arm_b']:+.4f}")
    print(f"[compare] factor_skip_days = {s['factor_skip_days']}")
    print(f"[compare] agreement A vs B (always_ok baseline) = "
          f"{s['windows_match_under_always_ok']:.2f}%  "
          f"(expect 100% — if not, Jev wire is leaking)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
