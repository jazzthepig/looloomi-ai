"""
beta_core_q_hook.py — C2 ⓠ regime override layer hook for the ① book.

Per §C2-SHIP-SPEC 2026-08-12:
  gross_total[t] = beta_capture_gross[t] × q_override[t]
  q_override ∈ {0.0, 0.5, 1.0, 1.3}, default 1.0

This module is the THIN integration layer between the ① book (`beta_core_paper.py`)
and the ⓠ overlay helpers (`beta_core_q_overlay.py`). It does NOT compute the
VDB match itself — that is M-WO-7.1's match_regime_fingerprints RPC. The hook
calls the matcher, applies the dwell filter, and writes the resulting row to
`beta_core_nav_q`.

DEFAULT BEHAVIOR (first ship, 2026-09-15):
  - The VDB matcher is OPTIONAL but not yet wired to this hook.
  - Until the matcher is live, the hook returns q_override = 1.0 (baseline).
  - This means the first 60 days of the ⓠ overlay are IDENTICAL to the ①
    baseline — that is the correct safe ship state, since the C2 layer
    exists to verify the integration, not to immediately change behavior.
  - When the VDB matcher is wired (Mac-side D2), the hook activates and
    the ⓠ overlay begins to diverge from the ① baseline.

The C1 baseline is NEVER modified. The hook writes ONLY to:
  - beta_core_nav_q (the ⓠ overlay curve)
  - beta_core_nav_q_meta (event log)
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

from src.data.signals.beta_core_q_overlay import (
    INCEPTION_ID,
    default_thresholds,
    env_thresholds,
    is_vdb_failure,
    derive_q_override,
    QOverrideState,
)

_log = logging.getLogger("beta_core_q_hook")


# ── C2 ⓠ hook config (frozen for first ship; overridable by env) ─────────────
@dataclass
class QHookConfig:
    """Hook configuration. Frozen defaults; env overrides per beta_core_q_overlay."""
    enter_q_zero_thr: float
    exit_q_zero_thr: float
    vdb_matcher_live: bool                                       # False → always q_override=1.0
    inception_id: str = INCEPTION_ID


def q_hook_config() -> QHookConfig:
    """Read the current hook config (env overrides honored).

    `vdb_matcher_live` 从 2026-09-17 (S-378) 起**默认 True** —— matcher 接上了:
    `beta_core_paper` 现在调 `smoothed_phase_distance()`(§C2-SHIP-SPEC 的
    5 日中位 dwell filter)并把真值传进来。

    ⚠️ **留一个不用重新部署就能关的开关**:`VDB_MATCHER_LIVE=0`。
    此前这里写死 `False`、调用点又写死一次 `False` —— **同一个决定有两个定义点,
    翻其中一个不起作用**,而两处都长得像「开关」。这就是 S-371 那 36 处比较的小号版本。
    现在配置是唯一定义点,调用点读它。
    """
    import os
    enter, exit_ = env_thresholds()
    raw = (os.environ.get("VDB_MATCHER_LIVE") or "").strip().lower()
    live = raw not in ("0", "false", "no", "off")
    return QHookConfig(
        enter_q_zero_thr=enter,
        exit_q_zero_thr=exit_,
        vdb_matcher_live=live,
    )


# ── Pure-function hook (offline-testable) ────────────────────────────────────
def compute_q_hook_state(
    today: dt.date,
    gross: float,
    regime: str | None,
    smoothed_distance: float | None,
    enter_q_up_frac: float = 0.0,
    vdb_failure: bool = False,
    vdb_matcher_live: bool = False,
    vdb_distance: float | None = None,
) -> QOverrideState:
    """Compute the q_override state for today.

    Pure function — caller passes smoothed_distance, enter_q_up_frac, and
    vdb_failure explicitly. The hook does NOT call Supabase or any network.

    On any failure (or first-ship before VDB matcher is live), the result is
    q_override = 1.0 (baseline-equivalent). This is per §C2-SHIP-SPEC §4:
    freeze + fall back to 1.0, NEVER hardcode 0.
    """
    cfg = q_hook_config()
    enter, exit_ = cfg.enter_q_zero_thr, cfg.exit_q_zero_thr
    if not vdb_matcher_live:
        # First-ship behavior: no matcher = no override. Baseline strictly preserved.
        return QOverrideState(
            mark_date=today, q_override=1.0,
            vdb_distance=None, smoothed_distance=None,
            enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
            trigger="baseline_vdb_matcher_offline",
            vdb_failure=False,
        )
    if is_vdb_failure(smoothed_distance) or vdb_failure:
        return derive_q_override(
            mark_date=today, smoothed_distance=smoothed_distance,
            enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
            enter_q_up_frac=enter_q_up_frac, baseline=1.0,
            vdb_failure=True,
        )
    return derive_q_override(
        mark_date=today, vdb_distance=vdb_distance,
        smoothed_distance=smoothed_distance,
        enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
        enter_q_up_frac=enter_q_up_frac, baseline=1.0,
    )


def _fin(x: float | None) -> float | None:
    """有限的浮点才落库。**NaN 不是 0,也不是「在分布内」** —— 它是没算出来。

    `x != x` 是 NaN 的判据(NaN 不等于自己)。两个写入端各自展开过一遍这个表达式,
    改一处漏一处就是两套 NaN 语义;收成一个函数。
    """
    return None if x is None or x != x else round(float(x), 6)


# ── I/O wrapper (Supabase write, called by mark_and_rebalance) ───────────────
async def write_q_overlay_row(
    today: dt.date,
    q_state: QOverrideState,
    baseline_gross: float,
    nav: float,
    benchmark_nav: float,
    daily_return: float,
    excess_return: float,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Durable write to `beta_core_nav_q`. Mirrors `_write` shape from beta_core_paper.

    Returns True on success, False on failure. The C1 mark flow treats a False
    return as a transient failure (NOT a hard error) — the ① baseline is
    independent and keeps running.
    """
    from src.api.store import supabase_insert_table
    gross_total = round(baseline_gross * q_state.q_override, 6)
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "q_override": q_state.q_override,
        # S-378:**这两列曾经是同一列**。写入端落的是 smoothed,而 dataclass 注释
        # 写着 "raw distance",S-366 手工回填的 25 行又落的是 raw ——
        # 一列两个口径,而数值接近到在图上和查询里都分不出来(S-106 换了个轴)。
        # 现在:`vdb_distance` = 原始(与已回填的 25 行同口径,历史不用改),
        # `smoothed_distance` = **真正决定 zone 的那个数**。
        "vdb_distance": _fin(q_state.vdb_distance),
        "smoothed_distance": _fin(q_state.smoothed_distance),
        "enter_q_zero_thr": q_state.enter_q_zero_thr,
        "exit_q_zero_thr": q_state.exit_q_zero_thr,
        "baseline_gross": round(baseline_gross, 6),
        "gross_total": gross_total,
        "nav": round(nav, 6),
        "benchmark_nav": round(benchmark_nav, 6),
        "daily_return": round(daily_return, 6),
        "excess_return": round(excess_return, 6),
        "note": f"trigger={q_state.trigger}",
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_q", [row])
        # Same Lesson #107 / S-105 protection: a write that returns False is
        # NOT the same as a write that ran. The C1 baseline is independent,
        # but a missing q row is a silent delta that the next agent will not
        # see, so log it loudly.
        if not ok:
            _log.error("[beta_core_q] Q-OVERLAY WRITE REJECTED for %s — "
                       "supabase_insert_table returned False", today.isoformat())
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_q] Q-OVERLAY WRITE FAILED for %s: %s",
                    today.isoformat(), e)
        return False


async def log_q_meta_event(
    today: dt.date,
    event_type: str,                                             # vdb_failure | dwell_extension | q_override_fix
    q_state: QOverrideState,
    reason: str,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Append a row to `beta_core_nav_q_meta`. Loud failure on write reject."""
    from src.api.store import supabase_insert_table
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "event_type": event_type,
        "q_override": q_state.q_override,
        "vdb_distance": _fin(q_state.vdb_distance),
        "smoothed_distance": _fin(q_state.smoothed_distance),
        "reason": reason,
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_q_meta", [row])
        if not ok:
            _log.error("[beta_core_q] META EVENT WRITE REJECTED for %s/%s",
                       today.isoformat(), event_type)
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_q] META EVENT WRITE FAILED for %s/%s: %s",
                    today.isoformat(), event_type, e)
        return False
