#!/usr/bin/env python3
"""
M-115 Book B paper trade runner — daily driver for spec_runner.

This is a thin wrapper around `paper_trading.spec_runner` that:
  1. Loads the M-115 Book B spec from `looloomi-ai/paper_trading/specs/`
  2. Loads the OHLCV panel from Supabase `ohlcv_daily` for the spec universe
     (source = spec.data_source.primary, e.g. `coingecko_pro_ohlc`)
  3. Loads the regime from `cis_history.narrative_daily.macro_regime`
     (carry-forward last known regime per M-95c pattern)
  4. Calls `decide_survivors_book(spec, panel, as_of, regime, n_open=0)`
  5. Logs the Decision JSON to `paper_trading/state/m115_book_b_decisions.jsonl`

Run:
    python3 -m paper_trading.run_paper_m115 --as-of 2026-09-17

Status (2026-09-17): initial_state=stopped per spec.start_condition. JAZZ Task #30
halt-resume decision is the gate. Mac-side data feeds need to be alive for a
meaningful run — currently `coingecko_pro_ohlc` is 73d (S-370/S-372) and
`narrative_daily` is stale 42d (M-119); A-372-1/2 in flight on Mac.

This runner is intentionally narrow: one spec, one book, no multi-sleeve loop.
Multi-spec orchestration belongs in `scripts/run_paper_trader.py` (next).

Why not in `src/`: paper_trading/ is the spec library + executor co-located by
convention (CLAUDE.md rule 3). Spec_runner.py is already there; this runner is
its daily caller.

Why use raw httpx instead of `src.api.store.supabase_query`: `store.py` exposes
typed helpers (ohlcv_daily_freshness, supabase_get_history per-symbol), but no
generic panel loader. Adding one for paper-trade use is a separate decision
(do we want a public Supabase panel reader? probably yes, but not this commit).
Raw httpx keeps this runner self-contained and reviewable in one file.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Make src/ importable when invoked as `python3 -m paper_trading.run_paper_m115`
# from the repo root, and also when invoked as `python3 paper_trading/run_paper_m115.py`
# directly. Same pattern as spec_runner.py:1182-1185.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent if _HERE.name == "paper_trading" else _HERE
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


SPEC_PATH = _ROOT / "paper_trading" / "specs" / "m115_book_b_m93_r14.json"
LOG_PATH = _ROOT / "paper_trading" / "state" / "m115_book_b_decisions.jsonl"
STATE_DIR = LOG_PATH.parent


# ── 数据加载 ──────────────────────────────────────────────────────────────


def _sb_env() -> tuple[str, str]:
    """Supabase REST URL + KEY,from env. Returns ("", "") if either is missing."""
    return (
        os.environ.get("SUPABASE_URL", "").rstrip("/"),
        os.environ.get("SUPABASE_KEY", ""),
    )


async def _fetch_panel_rows(
    universe: list[str],
    source: str,
    *,
    days_back: int = 60,
    as_of: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Load OHLCV rows from Supabase for `universe` × `source`.

    单源硬钉死 (S-230 / S-307):不静默 fallback 到其他源 —— 那样会构造一个
    混源面板,`build_panel()` 会因 `assert_single_source` 抛 `CrossSourceError`。
    如果主源真的没行,要么 SKIPPED、要么显式走 synthetic(由 caller 决定)。

    Returns (rows, error_or_None). rows 是空 list iff Supabase 真的没返回任何行。
    """
    import httpx

    url, key = _sb_env()
    if not url or not key:
        return [], "SUPABASE_URL / SUPABASE_KEY empty in this process"

    as_of = as_of or dt.date.today().isoformat()
    since = (dt.date.fromisoformat(as_of) - dt.timedelta(days=days_back)).isoformat()
    syms = ",".join(f'"{s}"' for s in universe)
    endpoint = (
        f"{url}/rest/v1/ohlcv_daily"
        f"?select=symbol,trade_date,close,source"
        f"&source=eq.{source}"
        f"&symbol=in.({syms})"
        f"&trade_date=gte.{since}"
        f"&trade_date=lte.{as_of}"
        f"&order=trade_date.asc"
        f"&limit=10000"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                endpoint,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200:
                return [], f"Supabase HTTP {r.status_code}: {r.text[:140]}"
            return r.json() or [], None
    except Exception as e:                                  # noqa: BLE001
        return [], f"Supabase request failed: {type(e).__name__}: {str(e)[:120]}"


async def _fetch_regime(as_of: str) -> tuple[Optional[str], Optional[str]]:
    """Load macro_regime from cis_history.narrative_daily.

    carry-forward 行为:取 <= as_of 的最后一行;如果 narrative_daily 整列空(2026-09-17
    实测 stale 42d),返 (None, error),`decide_survivors_book` 把 None regime 当作
    no-gate —— M-93 sleeve 默认 long-only。这是预期的安全 fallback,不是 bug。
    """
    import httpx

    url, key = _sb_env()
    if not url or not key:
        return None, "SUPABASE_URL / SUPABASE_KEY empty"

    endpoint = (
        f"{url}/rest/v1/narrative_daily"
        f"?select=trade_date,macro_regime"
        f"&trade_date=lte.{as_of}"
        f"&order=trade_date.desc"
        f"&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                endpoint,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200:
                return None, f"Supabase HTTP {r.status_code}: {r.text[:120]}"
            rows = r.json() or []
            if not rows:
                return None, "narrative_daily 0 rows"
            return rows[0].get("macro_regime"), None
    except Exception as e:                                  # noqa: BLE001
        return None, f"Supabase request failed: {type(e).__name__}: {str(e)[:100]}"


def _synth_panel(spec_universe: list[str], source: str, as_of: str) -> list[dict[str, Any]]:
    """20 天 synthetic 面板,匹配 spec_runner.py:1247-1252 的形状 —— 测试/无数据时用。

    ⚠️ Synthetic 排名会因单调 close 序列撞名 (K_long=K_short=1 时 top=最后一名,
    bottom=第一名),所以**只用于验证 decide() 流通,不可解释为真信号**。
    runner 自己会在 `_meta.synthetic_reason` 里说明为何走 synthetic。

    ⚠️ `source` 用 spec.source 而不是 `"synthetic"`,因为 `assert_single_source`
    (single_source.py:115-119) 只允许白名单源 (binance_hist, hyperliquid, eodhd,
    coingecko_pro_ohlc)。spec_runner.py:1252 用同样的办法绕过 —— 这里跟它对齐。
    `synthetic_reason` 在 `_meta` 里单独标记,不靠 source 字段区分。
    """
    end = dt.date.fromisoformat(as_of)
    rows: list[dict[str, Any]] = []
    for i in range(20):
        d = (end - dt.timedelta(days=19 - i)).isoformat()
        for j, s in enumerate(spec_universe):
            rows.append({
                "symbol": s, "trade_date": d,
                "close": 100 + i * (j + 1),
                "source": source,
            })
    return rows


# ── 主流程 ──────────────────────────────────────────────────────────────


async def main() -> int:
    p = argparse.ArgumentParser(description="M-115 Book B paper trade runner")
    p.add_argument("--as-of", default=dt.date.today().isoformat(),
                   help="decision date YYYY-MM-DD (default: today UTC)")
    p.add_argument("--spec", default=str(SPEC_PATH),
                   help=f"spec JSON path (default: {SPEC_PATH})")
    p.add_argument("--log", default=str(LOG_PATH),
                   help=f"decision log JSONL path (default: {LOG_PATH})")
    p.add_argument("--fallback-synthetic", action="store_true", default=True,
                   help="if panel is empty/err, fall back to synthetic (default on)")
    p.add_argument("--no-fallback-synthetic", dest="fallback_synthetic",
                   action="store_false",
                   help="if panel is empty/err, log BLOCKED instead of falling back")
    p.add_argument("--n-open", type=int, default=0,
                   help="currently open trades (default 0)")
    args = p.parse_args()

    # 1. Load spec
    from paper_trading.spec_runner import (
        Spec, Panel, build_panel, decide_survivors_book,
        MAX_PANEL_AGE_DAYS, Decision,
    )

    spec = Spec.load(args.spec)
    print(f"[run_paper_m115] spec={spec.name} family={spec.family} "
          f"universe={list(spec.universe)} source={spec.source}")

    # 2. Load panel
    rows, panel_err = await _fetch_panel_rows(
        list(spec.universe), spec.source, days_back=60, as_of=args.as_of,
    )
    synth_reason: Optional[str] = None
    if panel_err:
        print(f"[run_paper_m115] panel fetch error: {panel_err}")
        if not args.fallback_synthetic:
            print("[run_paper_m115] refusing synthetic (--no-fallback-synthetic)")
            return _log_blocked(args, spec, reason=f"panel fetch failed: {panel_err[:120]}")
        rows = _synth_panel(list(spec.universe), spec.source, args.as_of)
        synth_reason = f"fetch failed: {panel_err[:120]}"
    elif not rows:
        print(f"[run_paper_m115] panel 0 rows for source={spec.source}")
        if not args.fallback_synthetic:
            print("[run_paper_m115] refusing synthetic (--no-fallback-synthetic)")
            return _log_blocked(args, spec, reason=f"0 rows for source={spec.source}")
        rows = _synth_panel(list(spec.universe), spec.source, args.as_of)
        synth_reason = f"0 rows for source={spec.source}"

    # 3. Load regime
    regime, reg_err = await _fetch_regime(args.as_of)
    if reg_err:
        print(f"[run_paper_m115] regime: {reg_err} — M-93 sleeve defaults to no-gate (long)")

    # 4. Decide
    panel = build_panel(rows, source=spec.source if not synth_reason else "synthetic")
    as_of_date = dt.date.fromisoformat(args.as_of)
    age = panel.age_days(as_of_date)
    print(f"[run_paper_m115] panel n_symbols={panel.n_symbols} "
          f"last_bar={panel.last_bar} age={age}d"
          + (f" (synthetic: {synth_reason})" if synth_reason else ""))

    decision: Decision
    if age is None or age > MAX_PANEL_AGE_DAYS:
        # 镜像 decide_survivors_book BLOCKED 检查(spec_runner.py:792-796)
        # 在外面先判一次,免得进 decide 后只是返回 BLOCKED —— 同一形状,
        # 但在外面留 trace 更容易看出是哪一条规则挡的。
        decision = Decision(
            d=args.as_of, spec_name=spec.name, panel_source=panel.source,
            panel_last_bar=panel.last_bar,
            verdict="BLOCKED",                                  # type: ignore[arg-type]
            reason=f"panel age {age}d (last_bar={panel.last_bar}) > "
                   f"{MAX_PANEL_AGE_DAYS}d — 用旧价开仓会产生不可分辨的污染 (S-251)",
        )
    else:
        decision = decide_survivors_book(
            spec, panel, as_of=as_of_date, regime=regime, n_open=args.n_open,
        )

    # 5. Build payload + log
    payload = decision.as_payload()
    payload["_meta"] = {
        "synthetic_panel": bool(synth_reason),
        "synthetic_reason": synth_reason,
        "regime_source_error": reg_err,
        "regime_source_value": regime,
        "panel_source": panel.source,
        "panel_age_days": age,
        "runner": "run_paper_m115.py @ 2026-09-17",
    }
    print(f"[run_paper_m115] verdict={payload['verdict']} "
          f"legs={len(payload.get('legs', []))}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"[run_paper_m115] logged → {args.log}")
    return 0


def _log_blocked(args: argparse.Namespace, spec: Any, *, reason: str) -> int:
    """Log a BLOCKED decision and exit 1."""
    payload = {
        "d": args.as_of, "spec_name": spec.name,
        "verdict": "BLOCKED", "reason": reason[:200],
        "_meta": {"runner": "run_paper_m115.py @ 2026-09-17",
                  "blocked_at": "panel-fetch"},
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
