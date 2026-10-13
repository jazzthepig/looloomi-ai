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
  - n_missing_days:  int           — days where MTM was impossible (panel hole)

Cross-arm:
  - agreement_a_b:    float        — % of days where A and B verdicts match
  - agreement_a_c:    float        — % of days where A and C verdicts match
  - agreement_b_c:    float        — % of days where B and C verdicts match
  - factor_skip_days: int         — days where C=SKIPPED(factor) and B=ENTERED
                                    (= how many days the factor gate blocked a trade)
  - arm_c_vs_b_excess_sharpe: float — arm C SR − arm B SR

Hold-the-panel baseline (T-057 acceptance #4):
  - buys the first ENTERED's legs and never rebalances
  - mark-to-market daily using panel closes
  - reported as arms["H_baseline"] with the same metric shape

PnL semantics (T-057 lane-c 2026-10-13 fix): paper-trade daily mark-to-market
using per-(sym, day) closes from the panel. Two prior bugs are fixed here:

  (1) Symbols that dropped out of the next ENTERED used to have their P/L
      silently zeroed (period return fell back to `entry_now.get(sym, …)[1]`
      which defaulted to the entry price). Now the dropped symbol is sold at
      close of the rebalance day that excluded it, and any loss is captured
      by the daily series on that day (using the OLD leg's weight, which is
      correct: that day's MTM belongs to the position that was held into
      the close of that day).

  (2) Previously a period return was flattened across its holding days as
      `(1+r)^(1/span) - 1`. That uniformly **under-states daily vol** →
      inflates Sharpe for every arm. Now each day's return is the actual
      sum of `weight × (close[d][s] / close[d-1][s] − 1)` over the active
      legs. No smoothing, no compounding tricks between rebalances.

Costs NOT subtracted (5bps_rt per rebalance from spec — would change SR by
~+0.02 annualized, not enough to flip conclusions on the rebalanced arms;
hold-the-panel is zero-rebalance so zero cost).

If panel closes are missing (no `panel_closes.json` next to the JSONLs, e.g.
on a run dir predating T-057), `_build_daily_returns` raises rather than
silently fall back to the broken period-flattening path. Re-run the replay.
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
    *,
    panel_closes: Optional[dict[str, dict[str, float]]] = None,
) -> list[float]:
    """Honest daily mark-to-market using per-(sym, day) closes from the panel.

    Algorithm (T-057 lane-c 2026-10-13):
      - Sort ENTERED events by date.
      - Walk each day d in [start, end] in order.
      - Day d's return uses `last_legs` (the legs from the most recent
        ENTERED with date <= d). It is computed as
            sum_sym (weight × (close[d][sym] / close[d-1][sym] − 1)).
      - After computing d's return, if d is an ENTERED day, replace
        `last_legs` with the new ENTERED's legs (effective from d+1).
        Rationale: rebalance happens at close[d], so the day's P/L belongs
        to the OLD position; the new position opens at close[d] and its
        first contribution is d+1.
      - Days BEFORE any ENTERED (no active position yet): return 0.
      - Days where the panel is missing close[d] OR close[d-1] for every
        active symbol (data hole, holiday, etc.): return 0 and increment
        `n_missing_days`. Detection is reported via the returned length
        being unchanged but the caller is expected to surface a stats block;
        for the comparison's day-series the zeros are honest gaps.

    Why the previous period-flattening was wrong:
      Old code computed a single period return between ENTERED events, then
      applied `(1+r)^(1/span) - 1` to each day in between. With a 7-day
      cadence and a 10% period return, every day got +1.37% even if the
      actual daily moves were volatile. That uniformly **shrinks observed
      daily vol** → inflates annualized Sharpe by ≈ √7 in steady-state.

    Bug ① fixed (dropped symbols):
      Old code:
          p_exit = entry_now.get(sym, (0.0, p_entry))[1]   # if sym dropped: p_exit = p_entry
          r += w * (p_exit / p_entry - 1.0)               # → forced 0 return
      New code: a dropped symbol stays in `last_legs` until close of d_next
      (the rebalance that excluded it). On d_next its daily MTM is computed
      normally against close[d_next] / close[d_next−1]. The cumulative loss
      (or gain) is realized on d_next and reflected in the daily series.
      From d_next+1 onwards the symbol is gone from `last_legs` → no further
      contribution, exactly as if it were sold at close[d_next].

    Bug ② fixed (period flattening): each day now carries its own
    contribution; no smoothing across the holding period.

    Args:
        decisions:    date-sorted (or unsorted; we sort by date) list of
                      decision payloads. Only ENTERED records participate.
        start, end:   inclusive window.
        panel_closes: {sym: {iso_day_str: close}} — required. Pass `None`
                      only if you want a loud error (no silent fallback to
                      the broken period-flattening path).

    Returns:
        list[float] of length (end - start).days + 1 — daily return series.
        Raises ValueError if panel_closes is None.
    """
    if panel_closes is None:
        raise ValueError(
            "_build_daily_returns requires panel_closes (T-057 fix). "
            "The period-flattening fallback silently inflated Sharpe; it "
            "has been removed. Re-run replay_three_arms to regenerate "
            "the run dir with panel_closes.json attached."
        )
    if end < start:
        return []

    n_days = (end - start).days + 1
    daily = [0.0] * n_days

    # 1. Build sorted ENTERED timeline.
    entered_by_date: dict[dt.date, dict[str, float]] = {}
    for d_rec in decisions:
        if d_rec.get("verdict") != "ENTERED":
            continue
        try:
            d = dt.date.fromisoformat(d_rec["date"])
        except Exception:                                  # noqa: BLE001
            continue
        legs = {l["symbol"]: float(l["weight"])
                for l in d_rec.get("legs", [])}
        # If multiple ENTERED on the same day (shouldn't happen in cadence
        # 7d, but defensively), the LAST one wins — match how a live system
        # would end the day with the latest rebalance.
        entered_by_date[d] = legs

    # 2. Walk days.
    last_legs: Optional[dict[str, float]] = None
    has_active = False
    for i in range(n_days):
        d = start + dt.timedelta(days=i)

        if has_active:
            d_prev = d - dt.timedelta(days=1)
            r = 0.0
            used_syms = 0
            for sym, w in last_legs.items():
                cs = panel_closes.get(sym, {})
                p_now = cs.get(d.isoformat())
                p_prev = cs.get(d_prev.isoformat())
                if p_now is not None and p_prev is not None and p_prev > 0:
                    r += w * (p_now / p_prev - 1.0)
                    used_syms += 1
            daily[i] = r  # 0 if no symbol had data for this day

        # Update last_legs AFTER computing d's return, so d's MTM uses OLD
        # legs (the position we held into close[d]).
        if d in entered_by_date:
            last_legs = entered_by_date[d]
            has_active = True
    return daily


def _build_hold_baseline(
    decisions: list[dict[str, Any]],
    start: dt.date, end: dt.date,
    *,
    panel_closes: dict[str, dict[str, float]],
) -> list[float]:
    """Buy the first ENTERED's legs and never rebalance. Pure passive hold.

    Floor for arm C's "outperformance": if the factor gate's complexity can't
    beat just sitting on the panel from day one, the gate is overhead, not
    alpha. Acceptance #④.

    Returns 0 returns for the day of entry (no prior close to compare), then
    daily sum of `weight × (close[d][sym] / close[d-1][sym] − 1)`.
    """
    if end < start:
        return []
    n_days = (end - start).days + 1
    daily = [0.0] * n_days

    first_legs: Optional[dict[str, float]] = None
    for d_rec in decisions:
        if d_rec.get("verdict") == "ENTERED":
            first_legs = {l["symbol"]: float(l["weight"])
                          for l in d_rec.get("legs", [])}
            break
    if first_legs is None:
        return daily

    for i in range(1, n_days):
        d = start + dt.timedelta(days=i)
        d_prev = d - dt.timedelta(days=1)
        r = 0.0
        for sym, w in first_legs.items():
            cs = panel_closes.get(sym, {})
            p_now = cs.get(d.isoformat())
            p_prev = cs.get(d_prev.isoformat())
            if p_now is not None and p_prev is not None and p_prev > 0:
                r += w * (p_now / p_prev - 1.0)
        daily[i] = r
    return daily


def _count_missing_days(
    decisions: list[dict[str, Any]],
    start: dt.date, end: dt.date,
    *,
    panel_closes: dict[str, dict[str, float]],
) -> int:
    """Count days in [start, end] where the active position couldn't be MTM'd.

    "Couldn't" = at least one active leg but none of (close[d], close[d-1])
    are present in the panel for every active leg. Used as a data-quality
    signal in the per-arm stats block.
    """
    n_days = (end - start).days + 1
    entered_by_date: dict[dt.date, dict[str, float]] = {}
    for d_rec in decisions:
        if d_rec.get("verdict") != "ENTERED":
            continue
        try:
            d = dt.date.fromisoformat(d_rec["date"])
        except Exception:                                  # noqa: BLE001
            continue
        entered_by_date[d] = {l["symbol"]: float(l["weight"])
                              for l in d_rec.get("legs", [])}

    last_legs: Optional[dict[str, float]] = None
    has_active = False
    n_missing = 0
    for i in range(n_days):
        d = start + dt.timedelta(days=i)
        if has_active:
            d_prev = d - dt.timedelta(days=1)
            used = 0
            for sym in last_legs:
                cs = panel_closes.get(sym, {})
                p_now = cs.get(d.isoformat())
                p_prev = cs.get(d_prev.isoformat())
                if p_now is not None and p_prev is not None and p_prev > 0:
                    used += 1
            if not used and last_legs:
                n_missing += 1
        if d in entered_by_date:
            last_legs = entered_by_date[d]
            has_active = True
    return n_missing


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

    # Load panel closes (T-057). Absent → loud error (see _build_daily_returns).
    panel_path = in_dir / "panel_closes.json"
    if panel_path.exists():
        panel_closes: Optional[dict[str, dict[str, float]]] = json.loads(
            panel_path.read_text(encoding="utf-8"))
    else:
        panel_closes = None
        print(
            f"[compare] WARNING: {panel_path} not found — daily MTM requires "
            f"panel_closes (T-057). Re-run replay_three_arms to regenerate "
            f"this run dir. Falling through to raise inside _build_daily_returns.",
            file=sys.stderr,
        )

    daily_a = _build_daily_returns(arm_a, start, end, panel_closes=panel_closes)
    daily_b = _build_daily_returns(arm_b, start, end, panel_closes=panel_closes)
    daily_c = _build_daily_returns(arm_c, start, end, panel_closes=panel_closes)
    daily_h = _build_hold_baseline(arm_b, start, end,
                                   panel_closes=panel_closes or {})

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
        n_missing = _count_missing_days(
            decisions, start, end, panel_closes=panel_closes or {},
        ) if panel_closes is not None else -1
        return {
            "name": name,
            "n_entered": n_entered,
            "n_skipped_cadence": n_skipped_cadence,
            "n_skipped_factor": n_skipped_factor,
            "n_skipped_jev": n_skipped_jev,
            "n_blocked": n_blocked,
            "n_days_total": len(decisions),
            "n_missing_days": n_missing,
            "cum_return_pct": cum * 100.0,
            "sharpe_annualized": _sharpe_daily(daily),
            "sortino_annualized": _sortino_daily(daily),
            "max_dd_pct": _max_dd_pct(equity),
        }

    stats_a = stats("A_jev_always_ok", arm_a, daily_a)
    stats_b = stats("B_baseline_no_jev", arm_b, daily_b)
    stats_c = stats("C_simple_factor", arm_c, daily_c)
    stats_h = stats("H_hold_baseline", arm_b, daily_h)

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
        "arm_c_sharpe_minus_hold": stats_c["sharpe_annualized"] - stats_h["sharpe_annualized"],
        "arm_b_sharpe_minus_hold": stats_b["sharpe_annualized"] - stats_h["sharpe_annualized"],
        "factor_skip_days": factor_skip_days,
        "windows_match_under_always_ok": agreement["agreement_a_b_pct"],
        "panel_closes_attached": panel_closes is not None,
    }

    return {
        "meta": meta,
        "arms": {"A": stats_a, "B": stats_b, "C": stats_c,
                 "H_baseline": stats_h},
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
