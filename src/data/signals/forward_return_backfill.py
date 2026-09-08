"""Fill `trade_results.realized_return_7d` — the column the IC chain runs on (S-203).

WHY THIS RUNS EVERY DAY. Measured 2026-08-23: 234 of 234 rows had this column
NULL, and that single gap disabled the entire weighting mechanism:

    realized_return_7d NULL
      → compute_7d_returns finds nothing usable
      → compute_fitness returns []
      → cis_regime_fitness stays at 0 rows
      → the IC multiplier cannot load
      → CIS scores every asset on NEUTRAL weights

Four months, and the daily log line read `ok=True rows=0` the whole way. Nothing
about the inputs was missing — 234 closed fills across 40 symbols, 115,931
cis_scores rows in the window. One empty column, and the mechanism the "Simons
upgrade" was built around had never once been energised.

A one-off backfill would have cleared the backlog and left the same hole open
tomorrow. This is the loop, so the column fills as trades age past seven days.

WHAT IT WILL NOT DO.

  · NO CROSS-SOURCE RETURNS. Entry and exit prices must come from the SAME
    source. Twenty of the candidate rows would have spanned
    binance_hist → coingecko; a return computed across two bar conventions reads
    the splice as a move, which is S-106 on the date axis instead of the price
    axis. Those rows stay NULL.
  · NO COINGECKO. Its "daily close" is hourly sample points collapsed to a date
    — whichever hour landed last (S-195). It is barred from return series.
  · NO GUESSING A MISSING BAR. If the entry day or the +7 day has no price, the
    row stays NULL. Unmeasured stays unmeasured (I1); a filled-in return is
    indistinguishable downstream from a measured one, and this column feeds a
    weighting decision.

SO PARTIAL COVERAGE IS THE EXPECTED STEADY STATE, not a failure. 104 of 209
eligible trade-days were computable on the first run. The report says which and
why, because a backfill that silently covers half is how you get a correlation
computed on a biased half.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

_log = logging.getLogger("fwd_return_backfill")

#: Horizon. Matches the column name and `compute_regime_fitness`'s join.
HORIZON_DAYS = 7

#: Sources whose daily bar is a real close. CoinGecko is excluded on purpose —
#: see the module docstring. yfinance is excluded because it is 63 days stale.
TRUSTED_SOURCES = ("binance_hist", "hyperliquid", "eodhd")


# The computation lives in the `exec_backfill_forward_returns` RPC
# (scripts/supabase_forward_return_backfill.sql), not here. A Python copy of the
# same JOIN was written first and deleted: two implementations of one rule drift,
# and this session spent a day on exactly that failure — two prompts, two
# template generators, two mark-coverage guards. One place, or it will disagree
# with itself and nobody will know which half ran.

async def backfill_forward_returns(horizon: int = HORIZON_DAYS) -> dict[str, Any]:
    """Fill every row whose +N bar now exists. Idempotent; safe to run hourly."""
    from src.api.store import _SB_URL, _SB_KEY, supabase_rpc_write

    if not _SB_URL or not _SB_KEY:
        return {"ok": False, "reason": "no Supabase credentials"}

    started = datetime.now(timezone.utc)
    try:
        ok, payload = await supabase_rpc_write(
            "exec_backfill_forward_returns", {"horizon_days": horizon})
    except Exception as e:                                     # noqa: BLE001
        _log.warning("[FWD] backfill RPC unavailable (%s) — reporting, not guessing", e)
        return {"ok": False, "reason": f"rpc unavailable: {str(e)[:120]}",
                "note": "the RPC must exist server-side; see "
                        "scripts/supabase_forward_return_backfill.sql"}

    filled = len(payload) if isinstance(payload, list) else (payload or 0)
    out = {
        "ok": bool(ok),
        "filled": filled,
        "horizon_days": horizon,
        "trusted_sources": list(TRUSTED_SOURCES),
        "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
    }
    _log.info("[FWD] filled %s rows (horizon %sd)", filled, horizon)
    return out


async def coverage_report(horizon: int = HORIZON_DAYS) -> dict[str, Any]:
    """How much of the eligible history is measured, and why the rest is not.

    Reported because partial coverage here is not a bug but IS a bias: if the
    unfillable rows cluster in one asset class or one date range, the IC computed
    on the remainder is an IC of that subset. A number nobody can decompose is a
    number nobody should weight on.

    ⚠️ **S-323:这个函数原本自己把行拉回来再统计** ——
    `?select=...&entry_time=lte.X&limit=10000`。PostgREST 服务端 `max-rows`
    上限(默认 1000)会把响应截到 1000 行**并返回 200**。实测 2026-09-08:
    合格行 **1759**,所以 `coverage_pct` 一直是**在一个任意 1000 行切片上算出来、
    却当作总体在用的统计量** —— 而这正是决定「能不能报 IC」的那个数。
    真值当天 92.0%。

    比丢数据更糟的是:分子分母**同时**被同一次截断改写,所以比值看上去总是
    合理的,没有任何一个数会显得离谱。**一个被截断的样本不会说自己被截断了。**
    改为调 `forward_return_coverage(p_horizon)` RPC —— 计数在库里做,回来是
    一行聚合,结构上不可能被 max-rows 截断。
    """
    from src.api.store import supabase_rpc
    try:
        rows = await supabase_rpc("forward_return_coverage",
                                  {"p_horizon": int(horizon)})
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "reason": f"coverage rpc failed: {str(e)[:120]}"}
    # None = RPC 没通;[] = 通了但没有行。**「读不到」和「没有」是两个状态**,
    # 而 coverage_pct 的下游会把后者当成「确实 0% 覆盖」去封 IC。
    if rows is None:
        return {"ok": False, "reason": "coverage rpc unreachable (not: zero coverage)"}
    if not rows:
        return {"ok": False, "reason": "coverage rpc returned no row"}

    agg = rows[0] if isinstance(rows, list) else rows
    eligible = int(agg.get("eligible_rows") or 0)
    measured = int(agg.get("measured_rows") or 0)
    n_days = int(agg.get("measured_days") or 0)
    unmeasured_syms = sorted(agg.get("unmeasured_symbols") or [])
    return {
        "ok": True,
        "eligible_rows": eligible,
        "measured_rows": measured,
        "coverage_pct": round(100 * measured / eligible, 1) if eligible else 0.0,
        # THE number that decides whether an IC may be reported at all — see
        # MIN_INDEPENDENT_DAYS in compute_regime_fitness. Assets co-move, so the
        # row count overstates the sample by roughly the width of the panel.
        "independent_days": n_days,
        "unmeasured_symbols": unmeasured_syms[:20],
        "n_unmeasured_symbols": len(unmeasured_syms),
    }
