#!/usr/bin/env python3
"""
A-17 panel_long_only paper trade runner — daily driver for spec_runner.

This is a thin wrapper around `paper_trading.spec_runner.decide_panel_long_only`:
  1. Loads the A-17 spec from `looloomi-ai/paper_trading/specs/`
  2. Loads the OHLCV panel from Supabase `ohlcv_daily` for the spec universe
     (source = spec.data_source.primary — single-source hard pin per S-230/S-307)
  3. Loads the regime from `cis_history.narrative_daily.macro_regime`
     (regime_gate is empty by design — A-17 ① benchmark holds through everything;
      we log regime for the weekly digest regardless)
  4. Calls `decide_panel_long_only(spec, panel, as_of, regime, n_open, last_rebalance)`
  5. Logs the Decision JSON to `paper_trading/state/a17_panel_long_only_decisions.jsonl`

Run:
    python3 -m paper_trading.run_paper_a17 --as-of 2026-09-17

Status (2026-09-17): initial_state=stopped per spec.execution.start_condition.
JAZZ Task #30 halt-resume is the gate. Mac-side data feeds need to be alive for
a meaningful run — `coingecko_pro_ohlc` only 73d (S-370/S-372) and `narrative_daily`
stale 42d (M-119); A-372-1/2 in flight on Mac.

Why not in `src/`: paper_trading/ is the spec library + executor co-located by
convention (CLAUDE.md rule 3). spec_runner.py is there; this runner is its daily caller.
Why not fold into run_paper_m115.py: A-17 uses `decide_panel_long_only` (single-pass
panel-wide equal-weight), M-115 uses `decide_survivors_book` (2-sleeve book composition
with regime gate + cross-section rank). Different deciders → different runners. Multi-spec
orchestration belongs in `scripts/run_paper_trader.py` (next).

Why use raw httpx instead of `src.api.store.supabase_query`: store.py exposes typed helpers
(ohlcv_daily_freshness, supabase_get_history per-symbol) but no generic panel loader.
Raw httpx keeps this runner self-contained and reviewable in one file. Same reasoning as
run_paper_m115.py.
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

# Make src/ importable when invoked as `python3 -m paper_trading.run_paper_a17`
# from the repo root, and also when invoked as `python3 paper_trading/run_paper_a17.py`
# directly. Same pattern as spec_runner.py:1182-1185.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent if _HERE.name == "paper_trading" else _HERE
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


SPEC_PATH = _ROOT / "paper_trading" / "specs" / "a17_panel_long_only.json"
LOG_PATH = _ROOT / "paper_trading" / "state" / "a17_panel_long_only_decisions.jsonl"
JEV_LOG_PATH = _ROOT / "paper_trading" / "state" / "a17_jev_regime_decisions.jsonl"
STATE_DIR = LOG_PATH.parent


# ── 数据加载 (mirror of run_paper_m115 for consistency) ─────────────────────


def _sb_env() -> tuple[str, str]:
    """Supabase REST URL + KEY, from env. Returns ("", "") if either is missing."""
    return (
        os.environ.get("SUPABASE_URL", "").rstrip("/"),
        os.environ.get("SUPABASE_KEY", ""),
    )


async def _fetch_panel_rows(
    universe: list[str],
    source: str,
    *,
    days_back: int = 120,           # A-17 needs min_history_days=60 + buffer for max-age
    as_of: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Load OHLCV rows from Supabase for `universe` × `source`.

    单源硬钉死 (S-230 / S-307):不静默 fallback 到其他源 —— 那样会构造一个
    混源面板,`build_panel()` 会因 `assert_single_source` 抛 `CrossSourceError`。
    days_back defaults to 120 — over the 60d spec floor with 60d buffer so if
    data has small gaps we still meet min_history_days per symbol.
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

    A-17 ① benchmark has empty regime_gate (regime-blind by design), so this is
    only used for the weekly digest log line. Real gate not needed for correctness.
    carry-forward:取 <= as_of 的最后一行;空 (M-119 stale 42d 2026-09-17) → (None, error)
    不影响 decide() — regime_gate=空 path,None 不被检视。
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


def _synth_panel(spec_universe: list[str], source: str, as_of: str,
                 *, min_history_days: int = 60) -> list[dict[str, Any]]:
    """Synthetic 面板 (A-17 needs min_history_days≥60d per symbol),matches build_panel 形状。

    n_days = min_history_days + 30 buffer —— threshold check (spec_runner.py:1041-1050)
    用 `sorted_dates[0] > threshold_date` 即「最早一根 bar 必须 ≤ as_of - min_history_days」
    判 too_short。配 **恰好** min_history_days 不够(只剩 59 根 bar 就 over threshold),
    +30 buffer 给 MIN_UNIVERSE_FOR_RANK=3 / 数据 gap / 测试容错留余地。

    ⚠️ Synthetic 价格是常数 100 (跟 test fixture 同),所以 panel_long_only v1
    equal_weight 1/N 出来的所有 leg entry price 都是 100,**只能验证 decide()
    流通,不可解释为真信号**。

    ⚠️ `source` 用 spec.source 而不是 `"synthetic"`,因为 `assert_single_source`
    (single_source.py:115-119) 只允许白名单源 (binance_hist, hyperliquid, eodhd,
    coingecko_pro_ohlc)。spec_runner.py:1252 用同样的办法绕过 —— 这里跟它对齐。
    `synthetic_reason` 在 `_meta` 里单独标记,不靠 source 字段区分。
    """
    n_days = min_history_days + 30
    end = dt.date.fromisoformat(as_of)
    rows: list[dict[str, Any]] = []
    for i in range(n_days):
        d = (end - dt.timedelta(days=n_days - 1 - i)).isoformat()
        for sym in spec_universe:
            rows.append({
                "symbol": sym, "trade_date": d,
                "close": 100.0,
                "source": source,
            })
    return rows


# ── 主流程 ──────────────────────────────────────────────────────────────


async def main() -> int:
    p = argparse.ArgumentParser(description="A-17 panel_long_only paper trade runner")
    p.add_argument("--as-of", default=dt.date.today().isoformat(),
                   help="decision date YYYY-MM-DD (default: today UTC)")
    p.add_argument("--spec", default=str(SPEC_PATH),
                   help=f"spec JSON path (default: {SPEC_PATH})")
    p.add_argument("--log", default=str(LOG_PATH),
                   help=f"decision log JSONL path (default: {LOG_PATH})")
    p.add_argument("--last-rebalance", default=None,
                   help="ISO date of last rebalance; None = first run (always ENTERED)")
    p.add_argument("--fallback-synthetic", action="store_true", default=True,
                   help="if panel is empty/err, fall back to synthetic (default on)")
    p.add_argument("--no-fallback-synthetic", dest="fallback_synthetic",
                   action="store_false",
                   help="if panel is empty/err, log BLOCKED instead of falling back")
    p.add_argument("--n-open", type=int, default=0,
                   help="currently open trades (default 0)")
    p.add_argument("--no-jev", action="store_true", default=False,
                   help="disable Jev gate entirely (Pattern A off); default on "
                        "with mock always_ok backend")
    p.add_argument("--jev-mode", default="always_ok",
                   choices=("always_ok", "always_veto"),
                   help="MockJevRegimeBackend mode (default: always_ok = no-op "
                        "gate). always_veto is for veto-path testing only.")
    p.add_argument("--jev-log", default=str(JEV_LOG_PATH),
                   help=f"Jev decision log JSONL path (default: {JEV_LOG_PATH})")
    args = p.parse_args()

    # 1. Load spec
    from paper_trading.spec_runner import (
        Spec, Panel, build_panel, decide_panel_long_only,
        MAX_PANEL_AGE_DAYS, Decision,
    )
    from paper_trading.jev_regime import (
        JevRegimeActor, MockJevRegimeBackend, build_state_payload,
    )

    spec = Spec.load(args.spec)
    # spec.min_history_days is mapped from spec.parameters.min_history_days in
    # Spec.load (spec_runner.py:394,403). Pull it for synth-buffer math.
    min_history_days = int(
        spec.raw.get("parameters", {}).get("min_history_days", 60)
    )
    print(f"[run_paper_a17] spec={spec.name} family={spec.family} "
          f"universe={list(spec.universe)} source={spec.source} "
          f"min_history_days={min_history_days}")

    # 2. Load panel — A-17 needs min_history_days + buffer, so fetch 120d not 60d
    rows, panel_err = await _fetch_panel_rows(
        list(spec.universe), spec.source, days_back=120, as_of=args.as_of,
    )
    synth_reason: Optional[str] = None
    if panel_err:
        print(f"[run_paper_a17] panel fetch error: {panel_err}")
        if not args.fallback_synthetic:
            print("[run_paper_a17] refusing synthetic (--no-fallback-synthetic)")
            return _log_blocked(args, spec, reason=f"panel fetch failed: {panel_err[:120]}")
        rows = _synth_panel(list(spec.universe), spec.source, args.as_of,
                            min_history_days=min_history_days)
        synth_reason = f"fetch failed: {panel_err[:120]}"
    elif not rows:
        print(f"[run_paper_a17] panel 0 rows for source={spec.source}")
        if not args.fallback_synthetic:
            print("[run_paper_a17] refusing synthetic (--no-fallback-synthetic)")
            return _log_blocked(args, spec, reason=f"0 rows for source={spec.source}")
        rows = _synth_panel(list(spec.universe), spec.source, args.as_of,
                            min_history_days=min_history_days)
        synth_reason = f"0 rows for source={spec.source}"

    # 3. Load regime (logged only — A-17 has empty regime_gate by design)
    regime, reg_err = await _fetch_regime(args.as_of)
    if reg_err:
        print(f"[run_paper_a17] regime (log only, not gated): {reg_err}")

    # 4. Decide
    panel = build_panel(rows, source=spec.source if not synth_reason else "synthetic")
    as_of_date = dt.date.fromisoformat(args.as_of)
    age = panel.age_days(as_of_date)
    print(f"[run_paper_a17] panel n_symbols={panel.n_symbols} "
          f"last_bar={panel.last_bar} age={age}d"
          + (f" (synthetic: {synth_reason})" if synth_reason else ""))

    last_rebalance: Optional[dt.date] = (
        dt.date.fromisoformat(args.last_rebalance) if args.last_rebalance else None
    )

    # 3.5 Jev regime gate (Pattern A pre-filter — optional, default ON with mock)
    # Per docs/jev_nautilus_integration_plan_2026-09-21.md: Jev says yes/no to
    # "is this regime tradeable?" BEFORE the strategy fires. Default backend is
    # MockJevRegimeBackend(mode="always_ok") which never vetoes — paper track
    # continues to produce baseline decisions until a real TypesafeBackend ships
    # (BLOCKED on JEV_API_KEY arriving in Seth lane). `--jev-mode always_veto`
    # is the diagnostic for the veto path; `--no-jev` disables the gate entirely.
    jev_decision = None
    jev_meta: dict[str, Any] = {"wired": not args.no_jev, "mode": args.jev_mode}
    if not args.no_jev:
        jev_actor = JevRegimeActor(
            backend=MockJevRegimeBackend(mode=args.jev_mode),
        )
        jev_state = build_state_payload(
            bar_ts=args.as_of,
            regime=regime,
            panel_age_days=age,
            panel_n_symbols=panel.n_symbols,
        )
        jev_decision = jev_actor.decide(jev_state)
        # Log the Jev decision to its own JSONL so the 60d validation framework
        # (Gate 1 Brier / Gate 3 frequency) can replay without re-reading the
        # strategy decision log. One row per call.
        jev_payload = {
            "date": args.as_of,
            "spec": spec.name,
            "decision": {
                "bar_ts": jev_decision.bar_ts,
                "regime_ok": jev_decision.regime_ok,
                "direction_bias": jev_decision.direction_bias,
                "confidence": jev_decision.confidence,
                "latency_ms": jev_decision.jev_latency_ms,
                "input_tokens": jev_decision.jev_input_tokens,
                "backend": jev_decision.backend_name,
                "mock": jev_decision.mock,
            },
            "state": {
                "regime": regime,
                "panel_age_days": age,
                "panel_n_symbols": panel.n_symbols,
            },
            "actor_stats": jev_actor.stats(),
            "_meta": {"runner": "run_paper_a17.py @ 2026-09-21"},
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.jev_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(jev_payload, ensure_ascii=False) + "\n")
        jev_meta["regime_ok"] = jev_decision.regime_ok
        jev_meta["direction_bias"] = jev_decision.direction_bias
        jev_meta["backend"] = jev_decision.backend_name
        print(f"[run_paper_a17] jev: regime_ok={jev_decision.regime_ok} "
              f"bias={jev_decision.direction_bias} backend={jev_decision.backend_name} "
              f"latency={jev_decision.jev_latency_ms}ms")

    decision: Decision
    if age is None or age > MAX_PANEL_AGE_DAYS:
        # 镜像 decide_survivors_book BLOCKED 检查 (spec_runner.py:792-796):
        # 在外面先判一次,免得进 decide 后只是返回 BLOCKED —— 同一形状,
        # 但在外面留 trace 更容易看出是哪一条规则挡的。
        decision = Decision(
            d=args.as_of, spec_name=spec.name, panel_source=panel.source,
            panel_last_bar=panel.last_bar,
            verdict="BLOCKED",                                  # type: ignore[arg-type]
            reason=f"panel age {age}d (last_bar={panel.last_bar}) > "
                   f"{MAX_PANEL_AGE_DAYS}d — 用旧价 rebalance 会污染 §5b ① "
                   f"基准 (S-251)",
        )
    else:
        decision = decide_panel_long_only(
            spec, panel, as_of=as_of_date, regime=regime,
            n_open=args.n_open, last_rebalance=last_rebalance,
            jev_regime=jev_decision,
        )

    # 5. Build payload + log
    payload = decision.as_payload()
    payload["_meta"] = {
        "synthetic_panel": bool(synth_reason),
        "synthetic_reason": synth_reason,
        "regime_log_only": True,                     # A-17 ① regime_gate=空 by design
        "regime_source_error": reg_err,
        "regime_source_value": regime,
        "last_rebalance_input": args.last_rebalance,
        "panel_source": panel.source,
        "panel_age_days": age,
        "runner": "run_paper_a17.py @ 2026-09-21",
        "jev": jev_meta,
    }
    print(f"[run_paper_a17] verdict={payload['verdict']} "
          f"legs={len(payload.get('legs', []))}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"[run_paper_a17] logged → {args.log}")
    return 0


def _log_blocked(args: argparse.Namespace, spec: Any, *, reason: str) -> int:
    """Log a BLOCKED decision and exit 1."""
    payload = {
        "d": args.as_of, "spec_name": spec.name,
        "verdict": "BLOCKED", "reason": reason[:200],
        "_meta": {"runner": "run_paper_a17.py @ 2026-09-17",
                  "blocked_at": "panel-fetch"},
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
