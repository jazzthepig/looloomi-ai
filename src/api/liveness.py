"""Liveness SLO — surface silent failures within 24h, not 42 days.

THE PROBLEM THIS FIXES. A loop can be silently dead for weeks before someone
notices. The `_hyperliquid_loop` 234 持续一次请求 · 写入 0 行 funding entry
in M-119 was one such finding; the 9-job engine had multiple `last_run_at`
in the 10000-98524s range when S-323 was diagnosed. Every one of those was
someone noticing by accident, not by alarm. **A control that requires human
memory to fire is a control that does not fire.**

THE FIX. Every loop has a max-age budget. last_ok_at + last_run_at + age_s
together produce a 3-value liveness verdict:

    live   — within budget (last_ok_at < max_age_h ago OR loop is intentionally
             refusing as a defensive posture)
    stale  — over budget but recoverable (age > max_age_h, < 4×max_age_h)
    dead   — clearly gone (never_ran, no record, OR age > 4×max_age_h)

Three-valued on purpose (S-166 / S-180 shape). "Stale" is not the same as
"dead", and neither is the same as "actively refusing" — collapsing them
gives you a panel that says green when 3 loops have not produced a row in
18 hours. The shape that hid eleven missing tables for weeks is the same
shape this SLO exists to prevent.

USAGE. `compute_liveness_summary(loop_rows)` returns n_live/n_stale/n_dead
plus the per-loop breakdown. Wired into `/internal/data-freshness` (next
commit) so the same endpoint that reports loop verdicts now also reports
their liveness — one surface, no second thing to remember to look at.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Per-loop max-age budgets (hours). Marker loops (paper books) are most
# critical — they write the NAV. Fan-out loops (panel collection) run weekly
# by design. High-freq writers are 24h because they should fire hourly.
LIVENESS_SLOS: dict[str, dict] = {
    # Marker loops — 48h budget (must run daily; 48h = 2 missed days = stale)
    "_beta_core_loop":           {"max_age_h": 48, "kind": "marker"},
    "_hl_book_loop":             {"max_age_h": 48, "kind": "marker"},   # S-413
    "_tokenization_tilt_loop":   {"max_age_h": 48, "kind": "marker"},   # S-427
    "_beta_plus_loop":           {"max_age_h": 48, "kind": "marker"},   # S-429
    "_causal_paper_loop":        {"max_age_h": 48, "kind": "marker"},
    "_combined_book_loop":       {"max_age_h": 48, "kind": "marker"},
    "_dingge_paper_loop":        {"max_age_h": 48, "kind": "marker"},
    "_factor_tilt_loop":         {"max_age_h": 48, "kind": "marker"},
    "_fusion_paper_loop":        {"max_age_h": 48, "kind": "marker"},
    "_pod_aggregator_loop":      {"max_age_h": 48, "kind": "marker"},
    "_scalable_book_loop":       {"max_age_h": 48, "kind": "marker"},
    "_two_layer_paper_loop":     {"max_age_h": 48, "kind": "marker"},
    # High-freq — 24h budget
    "_forward_record_loop":      {"max_age_h": 24, "kind": "high_freq"},
    "_outcome_tracker_loop":     {"max_age_h": 24, "kind": "high_freq"},
    # S-361: 写者存在于 2026-08-27,零调用者,表停 42 天才被发现。
    # 48h 而非 24h —— 全量重算依赖 binance_hist 面板,那个源本身会有间隔。
    "_market_state_loop":        {"max_age_h": 48, "kind": "high_freq"},
    "_hyperliquid_loop":         {"max_age_h": 24, "kind": "high_freq"},
    "_metering_flush_loop":      {"max_age_h": 24, "kind": "high_freq"},
    # Fan-out — 168h (weekly) budget
    "_cg_panel_loop":            {"max_age_h": 168, "kind": "fanout"},
    "_deep_panel_loop":          {"max_age_h": 168, "kind": "fanout"},
    # A-21 · vault tick (per-minute mark-to-market). ETH ERC-20 vault,
    # not Drift. _vault_tick_<vault_id>_loop is the dynamic name per
    # vault_id; the liveness module accepts loop names not in this dict
    # via DEFAULT_MAX_AGE_H. We register the family-shape entry here so
    # the kind is correctly "vault" (not "unknown").
    "_vault_tick_loop":          {"max_age_h": 1, "kind": "vault"},  # family entry
}

DEFAULT_MAX_AGE_H = 48


@dataclass(frozen=True)
class LivenessVerdict:
    """Three-valued liveness verdict for one loop."""
    loop: str
    verdict: str           # "live" | "stale" | "dead"
    age_s: Optional[int]   # max(age since last_ok, age since last_run); None = no record
    last_ok_at: Optional[int]
    last_run_at: Optional[int]
    budget_remaining_h: float
    reason: str

    def as_dict(self) -> dict:
        return {
            "loop": self.loop,
            "verdict": self.verdict,
            "age_s": self.age_s,
            "last_ok_at": self.last_ok_at,
            "last_run_at": self.last_run_at,
            "budget_remaining_h": round(self.budget_remaining_h, 2),
            "reason": self.reason,
        }


def compute_liveness_for_loop(
    loop_name: str,
    last_ok_at: Optional[int],
    last_run_at: Optional[int],
    age_s: Optional[int],
    verdict: Optional[str],
) -> LivenessVerdict:
    """Compute one loop's liveness verdict.

    Args:
        loop_name:    loop identifier (e.g. "_beta_core_loop")
        last_ok_at:   Unix timestamp of last successful run, or None
        last_run_at:  Unix timestamp of last attempt (success or fail), or None
        age_s:        Seconds since the last attempt, or None
        verdict:      Loop verdict string ("ok" / "failing" / "refusing" /
                      "never_ran"), or None

    Two clocks drive liveness:
      1. `age_s` = time since last ATTEMPT. Small + failing = the loop is
         running but the work is wrong (e.g. breaker OPEN).
      2. time-since-last-ok = now - last_ok_at. Even if the loop fires every
         hour, if every fire fails, last_ok_at stays weeks old.

    A loop is `live` only when last_ok_at is within budget. `age_s` only
    matters when last_ok_at is recent — otherwise the loop is producing
    no useful output regardless of how often it tries.

    Returns:
        LivenessVerdict with verdict ∈ {"live", "stale", "dead"}.
    """
    slo = LIVENESS_SLOS.get(loop_name, {"max_age_h": DEFAULT_MAX_AGE_H, "kind": "unknown"})
    # Force-mark family — the 9 paper-book beat keys look like `_book_<name>_loop`
    # (set by POST /internal/force-mark/{book} on each call). Match by prefix
    # so we don't need 9 explicit entries and so future books inherit the same
    # budget. Same 48h / marker-kind as the daily cron beats — the cadence IS
    # 24h, the 48h is the operational tolerance (1 missed day = stale, not dead).
    if loop_name.startswith("_book_") and loop_name.endswith("_loop"):
        slo = {"max_age_h": 48, "kind": "marker"}
    max_age_h = slo["max_age_h"]
    max_age_s = max_age_h * 3600

    # dead: never_ran OR no record at all
    if verdict == "never_ran" or last_run_at is None or age_s is None:
        return LivenessVerdict(
            loop=loop_name, verdict="dead", age_s=age_s,
            last_ok_at=last_ok_at, last_run_at=last_run_at,
            budget_remaining_h=0.0,
            reason=f"never_ran / no record (kind={slo['kind']}, budget={max_age_h}h)"
        )

    # Compute the EFFECTIVE age: max of (age_s, time_since_last_ok).
    # A loop firing every hour but failing every fire has small age_s
    # but last_ok_at weeks old — that's still dead.
    if last_ok_at is None or last_ok_at == 0:
        effective_age_s = max_age_s * 1000          # effectively never
    else:
        # now = last_run_at + age_s. time_since_ok = now - last_ok_at.
        now_s = (last_run_at or 0) + (age_s or 0)
        time_since_ok_s = max(0, now_s - last_ok_at)
        effective_age_s = max(age_s or 0, time_since_ok_s)

    budget_remaining_h = (max_age_s - effective_age_s) / 3600

    if effective_age_s > 4 * max_age_s:
        return LivenessVerdict(
            loop=loop_name, verdict="dead", age_s=age_s,
            last_ok_at=last_ok_at, last_run_at=last_run_at,
            budget_remaining_h=budget_remaining_h,
            reason=(f"effective_age={effective_age_s/3600:.1f}h > 4× budget "
                    f"({max_age_h*4}h, kind={slo['kind']}) — "
                    f"last_ok_at={last_ok_at or 'never'}")
        )
    if effective_age_s > max_age_s:
        return LivenessVerdict(
            loop=loop_name, verdict="stale", age_s=age_s,
            last_ok_at=last_ok_at, last_run_at=last_run_at,
            budget_remaining_h=budget_remaining_h,
            reason=(f"effective_age={effective_age_s/3600:.1f}h > budget "
                    f"({max_age_h}h, kind={slo['kind']}) — "
                    f"last_ok_at={last_ok_at or 'never'}")
        )
    return LivenessVerdict(
        loop=loop_name, verdict="live", age_s=age_s,
        last_ok_at=last_ok_at, last_run_at=last_run_at,
        budget_remaining_h=budget_remaining_h,
        reason=f"age={age_s/3600:.1f}h within budget ({max_age_h}h, kind={slo['kind']})"
    )


def compute_liveness_summary(loop_rows: list[dict]) -> dict:
    """Compute liveness for all loops + summary counts.

    Args:
        loop_rows: list of dicts, each with keys:
            - "loop"        (str, required)
            - "last_ok_at"  (int | None)
            - "last_run_at" (int | None)
            - "age_s"       (int | None)
            - "verdict"     (str | None)

    Returns:
        {
            "n_total":   int,
            "n_live":    int,
            "n_stale":   int,
            "n_dead":    int,
            "dead_loops":   [str, ...],
            "stale_loops":  [str, ...],
            "per_loop":     {loop_name: LivenessVerdict.as_dict(), ...},
            "overall":       "healthy" | "degraded" | "critical",
        }
    """
    per_loop: dict[str, dict] = {}
    dead: list[str] = []
    stale: list[str] = []

    for row in loop_rows:
        loop = row.get("loop")
        if not loop:
            continue
        v = compute_liveness_for_loop(
            loop_name=loop,
            last_ok_at=row.get("last_ok_at"),
            last_run_at=row.get("last_run_at"),
            age_s=row.get("age_s"),
            verdict=row.get("verdict"),
        )
        per_loop[loop] = v.as_dict()
        if v.verdict == "dead":
            dead.append(loop)
        elif v.verdict == "stale":
            stale.append(loop)

    n_dead = len(dead)
    n_stale = len(stale)
    n_live = sum(1 for v in per_loop.values() if v["verdict"] == "live")

    # Overall verdict — the headline the operator reads first.
    # critical: any marker loop dead OR stale (the NAV books MUST run;
    #           stale marker = NAV hasn't been struck within 2 days = the
    #           same operational alarm as dead marker, just with hours
    #           of recoverability instead of days)
    # degraded: any non-marker dead or stale
    # healthy:  everything else
    marker_loops_problem = sorted(
        [l for l in (dead + stale)
         if LIVENESS_SLOS.get(l, {}).get("kind") == "marker"]
    )
    if marker_loops_problem:
        overall = "critical"
    elif n_dead > 0 or n_stale > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "n_total": len(per_loop),
        "n_live": n_live,
        "n_stale": n_stale,
        "n_dead": n_dead,
        "dead_loops": sorted(dead),
        "stale_loops": sorted(stale),
        "marker_loops_problem": marker_loops_problem,
        "per_loop": per_loop,
        "overall": overall,
    }


__all__ = [
    "LIVENESS_SLOS", "DEFAULT_MAX_AGE_H",
    "LivenessVerdict",
    "compute_liveness_for_loop", "compute_liveness_summary",
]
