"""Render a human-readable markdown report from S-393 _diff.json.

Reads `compare_three_arms.py`'s output and writes a markdown table summarizing:
- Per-arm:     n_periods, cum_return, Sharpe, MaxDD
- Diff section: Jev veto days, factor skip days, agreement rates
- Sanity checks: A-vs-B agreement (should be ~100% under always_ok mode)

The report is the artifact JAZZ reads; the JSON is for the dashboard tab.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def render(diff: dict[str, Any]) -> str:
    meta = diff["meta"]
    arms = diff["arms"]
    agreement = diff["agreement"]
    summary = diff["summary"]

    lines: list[str] = []
    lines.append(f"# S-393 3-Arm Comparison Report — {meta.get('ts', 'unknown ts')}")
    lines.append("")
    lines.append("**Window:** "
                 f"{meta['start']} → {meta['end']} ({meta.get('n_dates_total', '?')} dates)  ")
    lines.append(f"**Panel source:** `{meta['source']}` (n_symbols={meta['panel_n_symbols']}, "
                 f"last_bar={meta['panel_last_bar']})  ")
    lines.append(f"**Universe:** {meta['universe']}  ")
    lines.append(f"**Cadence:** {meta['cadence_days']}d  ")
    lines.append("")
    lines.append("**PnL semantics:** paper-trade mark-to-market, NOT fill sim. "
                 "Costs NOT subtracted (5bps_rt/rebalance ≈ +0.02 SR annualized; "
                 "won't flip conclusions).")
    lines.append("")

    # T-057 v2: data-hole gate. Any leg-day pair missing close[d] OR
    # close[d-1] flips the whole report's evidence status. The panel-wide
    # `n_missing_legs` (sum across arms) is the single trigger — when > 0,
    # the header reads "含孔洞,不可作证据" and the Sharpe-arm-vs-arm
    # verdict below is suppressed. We do NOT silently substitute a
    # same-panel hold baseline verdict in its place: if there are holes,
    # we say so and stop.
    n_missing_legs = int(summary.get("n_missing_legs", 0))
    evidence_suppressed = bool(summary.get(
        "evidence_suppressed_by_missing_legs", n_missing_legs > 0))
    if evidence_suppressed:
        lines.append("> ⚠️ **含孔洞,不可作证据** — panel has "
                     f"`{n_missing_legs}` missing (leg, day) closes "
                     "(close[d] OR close[d-1] absent). The Sharpe-arm-vs-arm "
                     "comparison below is suppressed. Patch the panel and "
                     "re-run, or accept the raw per-arm numbers as "
                     "non-comparable directional evidence.")
        lines.append("")

    # Per-arm metrics
    lines.append("## Per-arm metrics")
    lines.append("")
    lines.append("| Arm | n_entered | n_skipped (cadence/factor/jev) | n_missing_legs | "
                 "cum_return | Sharpe | Sortino | MaxDD |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for key in ("A", "B", "C", "H_baseline"):
        a = arms[key]
        lines.append(
            f"| {a['name']} | {a['n_entered']} | "
            f"{a['n_skipped_cadence']}/{a['n_skipped_factor']}/{a['n_skipped_jev']} | "
            f"{a.get('n_missing_legs', -1)} | "
            f"{a['cum_return_pct']:+.2f}% | "
            f"{a['sharpe_annualized']:+.4f} | "
            f"{a['sortino_annualized']:+.4f} | "
            f"{a['max_dd_pct']:.2f}% |"
        )
    lines.append("")

    # Arm C vs Arm B (the comparison question)
    lines.append("## Arm C vs Arm B (the comparison question)")
    lines.append("")
    if evidence_suppressed:
        lines.append("> Sharpe-arm-vs-arm verdict **suppressed** "
                     "(see header). Per-arm numbers above are raw MTM, not "
                     "comparable. Fix the panel and re-run.")
        lines.append("")
        lines.append(f"- **Δ MaxDD (C − B):**  "
                     f"{summary['arm_c_maxdd_minus_arm_b']:+.2f}pp  "
                     "(informational only — NOT a verdict under hole)")
        lines.append(f"- **Factor skip days:** {summary['factor_skip_days']}  ")
        lines.append(f"  (= days where arm B entered and arm C skipped due to factor gate)")
        lines.append("")
    else:
        lines.append(f"- **Δ Sharpe (C − B):** "
                     f"{summary['arm_c_sharpe_minus_arm_b']:+.4f}")
        lines.append(f"- **Δ MaxDD (C − B):**  "
                     f"{summary['arm_c_maxdd_minus_arm_b']:+.2f}pp  "
                     "(negative = arm C has shallower drawdown)")
        lines.append(f"- **Factor skip days:** {summary['factor_skip_days']}  ")
        lines.append(f"  (= days where arm B entered and arm C skipped due to factor gate)")
        lines.append("")

    # Hold-the-panel baseline (T-057 acceptance #④) — pure passive hold
    # using arm B's first ENTERED legs and panel closes. If arm C can't
    # beat this, the factor gate is overhead, not alpha.
    lines.append("## Hold-the-panel baseline (T-057 acceptance #④)")
    lines.append("")
    lines.append("Buy the first ENTERED's legs ONCE and compound the resulting "
                 "shares to end-of-window (T-057 v3: real compound hold, not "
                 "constant-weight × daily-return). Daily MTM on panel closes.")
    lines.append("")
    lines.append(f"- **Arm B SR − Hold SR:** "
                 f"{summary['arm_b_sharpe_minus_hold']:+.4f}  "
                 "(negative = arm B's rebalances destroy value vs. holding)")
    lines.append(f"- **Arm C SR − Hold SR:** "
                 f"{summary['arm_c_sharpe_minus_hold']:+.4f}  "
                 "(arm C's gate, evaluated against passive hold)")
    if not summary.get("panel_closes_attached", False):
        lines.append("")
        lines.append("> ⚠️ **panel_closes.json not attached** to this run dir — "
                     "the daily MTM here falls back to the legacy period-flattening "
                     "path (T-057: known inflated Sharpe). Re-run "
                     "`replay_three_arms.py` to attach it.")
    if evidence_suppressed:
        # T-057 v2: under a panel hole, the SR−hold deltas are not
        # comparable. Render the raw numbers but flag them.
        lines.append("")
        lines.append("> Hold-baseline SR deltas shown below are **raw only**, "
                     "not verdicts. Under a hole they cannot be defended.")
        lines.append(f"- **Arm B SR − Hold SR (raw):** "
                     f"{summary['arm_b_sharpe_minus_hold']:+.4f}")
        lines.append(f"- **Arm C SR − Hold SR (raw):** "
                     f"{summary['arm_c_sharpe_minus_hold']:+.4f}")
    lines.append("")

    # Arm A vs Arm B (the Jev wire sanity)
    lines.append("## Arm A vs Arm B (Jev wire sanity check)")
    lines.append("")
    lines.append(f"- **Agreement rate:** "
                 f"{summary['windows_match_under_always_ok']:.2f}%  ")
    if summary['windows_match_under_always_ok'] < 99.99:
        lines.append("")
        lines.append("> ⚠️ **A and B disagree under always_ok mode.** Jev wire is "
                     "leaking behavior. Inspect `decide_panel_long_only` step ⓪ "
                     "(spec_runner.py:1029-1045) and JevRegimeDecision fields "
                     "(paper_trading/jev_regime.py:43-60).")
    else:
        lines.append("")
        lines.append("> ✓ Jev wire is a clean no-op when `always_ok` — arm A and arm "
                     "B produce identical decisions. **Future Jev modes "
                     "(always_veto / Typesafe real backend) will diverge here**.")
    lines.append("")
    lines.append(f"- **Other agreement rates:**")
    lines.append(f"  - A vs C: {agreement['agreement_a_c_pct']:.2f}%")
    lines.append(f"  - B vs C: {agreement['agreement_b_c_pct']:.2f}%")
    lines.append("")

    # Sanity checks / warnings
    lines.append("## Sanity checks")
    lines.append("")
    issues = []
    if summary['windows_match_under_always_ok'] < 99.99:
        issues.append("⚠️ Jev wire leaks under always_ok — fix before using Jev live.")
    if arms["B"]["n_entered"] < 5:
        issues.append(
            f"⚠️ Arm B entered only {arms['B']['n_entered']} times — window too short "
            f"or panel too stale for meaningful comparison.")
    if arms["C"]["n_entered"] == 0:
        issues.append(
            "⚠️ Arm C never entered — factor gate is too tight (vol_threshold "
            "or windows wrong). Check arm C SKIPPED reasons for factor pass counts.")
    panel_last = meta.get("panel_last_bar")
    if panel_last and panel_last < meta["end"]:
        lines.append(
            f"- **Panel freshness note:** last_bar={panel_last} < window end "
            f"{meta['end']}; tail of window may be unimputable. Affects all arms "
            f"equally so the diff is still fair, but absolute numbers under-report "
            f"the latest regime.")
        lines.append("")
    if issues:
        for it in issues:
            lines.append(f"- {it}")
        lines.append("")
    else:
        lines.append("- ✓ All sanity checks passed.")
        lines.append("")

    # Promote criteria
    lines.append("## Promote criteria (S-393 arm_c_spec.monitoring.promote_threshold)")
    lines.append("")
    if evidence_suppressed:
        lines.append("> Promote verdict **suppressed** (panel hole — see header). "
                     "The Sharpe-arm-vs-arm criterion is unresolved until the "
                     "panel is patched and the run is repeated.")
        lines.append("")
        lines.append("**JAZZ decides** based on this report + future weekly replays. "
                     "S-393 arm C is comparison-only; no live deployment without "
                     "explicit sign-off.")
        lines.append("")
        return "\n".join(lines)
    lines.append("Arm C is a candidate for production if:")
    lines.append("- Δ Sharpe (C − B) ≥ 0")
    lines.append("- MaxDD arm_C ≤ MaxDD arm_B + 5pp")
    lines.append("- Factor gate is interpretable (not curve-fit on this window)")
    lines.append("")
    lines.append("Currently:")
    delta_sharpe = summary['arm_c_sharpe_minus_arm_b']
    delta_dd = summary['arm_c_maxdd_minus_arm_b']
    verdict_pass_sharpe = "✓" if delta_sharpe >= 0 else "✗"
    verdict_pass_dd = "✓" if delta_dd <= 5.0 else "✗"
    lines.append(f"- Sharpe criterion (Δ ≥ 0): {verdict_pass_sharpe} "
                 f"(actual: {delta_sharpe:+.4f})")
    lines.append(f"- MaxDD criterion (Δ ≤ +5pp): {verdict_pass_dd} "
                 f"(actual: {delta_dd:+.2f}pp)")
    lines.append("")
    lines.append("**JAZZ decides** based on this report + future weekly replays. "
                 "S-393 arm C is comparison-only; no live deployment without "
                 "explicit sign-off.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="S-393 3-arm markdown report")
    p.add_argument("--diff", required=True, help="_diff.json path")
    p.add_argument("--out", required=True, help="output report.md path")
    args = p.parse_args()

    diff = json.loads(Path(args.diff).read_text(encoding="utf-8"))
    md = render(diff)
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"[report] wrote → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
