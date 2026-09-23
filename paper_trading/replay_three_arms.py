"""Replay orchestrator for the S-393 3-arm comparison (Jev vs baseline vs simple factor).

JAZZ 2026-09-21: compare three decision modes on the same panel over the same
historical window:
  - arm A: A-17 panel_long_only + Pattern A (MockJevRegimeBackend always_ok)
  - arm B: A-17 panel_long_only, no Jev (`--no-jev` equivalent)
  - arm C: A-17 panel_long_only_simple_factor (per-symbol SMA + mom + vol AND gate)

All three arms share:
  - The same universe (BTC/ETH/SOL/BNB/XRP — A-17 v1 spec)
  - The same panel (single Supabase source, 1196d backtest window)
  - The same rebalance cadence (7d)

They differ only in the decide() call. By construction, the period-returns
series differ ONLY because of the gate at step ⑦ — so the diff IS the value
of each gate.

## Output (per run_id dir)

    paper_trading/state/replay/<run_id>/
        a_jev_decisions.jsonl            # arm A: Jev-gated
        b_baseline_decisions.jsonl       # arm B: no Jev
        c_simple_factor_decisions.jsonl  # arm C: factor-gated
        _meta.json                       # panel source, n_entered, last_bar, etc

PnL semantics (per docs/SPINE.md + S-251): every ENTERED event is a rebalance
event. The strategy HOLDS the prior legs between ENTEREDs (per A-17 spec).
The period return from entry at d_entry to next ENTERED at d_next is:

    period_return = Σ_legs( weight[d_entry] × (close[d_next][s] / close[d_entry][s] − 1) )

If `d_next` doesn't exist in the panel (no rebalance by window end), we use the
panel's last_bar close for the unrealized tail. This is paper-trade mark-to-market,
NOT fill sim — costs are tracked separately at compute_metrics.

## How to run

    # 1. With pre-fetched panel (CI / deterministic test)
    python3 -m paper_trading.replay_three_arms \\
        --panel-json paper_trading/state/replay/_fixtures/panel_60d.json \\
        --start 2026-01-01 --end 2026-03-01 \\
        --out paper_trading/state/replay/run_test/

    # 2. With live Supabase fetch (Mac-side; binance_hist freshness gate)
    python3 -m paper_trading.replay_three_arms \\
        --start 2023-04-02 --end 2026-07-18 \\
        --source binance_hist \\
        --out paper_trading/state/replay/run_2026-09-21/

Live fetch needs SUPABASE_URL + SUPABASE_KEY in env (Mac-side inject).
A-17 v1 spec.json is hardcoded as arm A and arm B; Arm C spec is its sibling.
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

# Make src/ + paper_trading/ importable when run as `python3 -m paper_trading.replay_three_arms`
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent if _HERE.name == "paper_trading" else _HERE
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


SPEC_A17 = _ROOT / "paper_trading" / "specs" / "a17_panel_long_only.json"
SPEC_ARMC = _ROOT / "paper_trading" / "specs" / "a17_panel_long_only_simple_factor.json"


# ── Data load (mirror run_paper_a17.py:96-115) ───────────────────────────────

def _sb_env() -> tuple[str, str]:
    return (
        os.environ.get("SUPABASE_URL", "").rstrip("/"),
        os.environ.get("SUPABASE_KEY", ""),
    )


async def fetch_panel_rows(
    universe: list[str], source: str, start: str, end: str,
    *,
    page_size: int = 1000,
    max_pages: int = 50,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Paginated Supabase httpx fetch for the full replay window.

    **Why pagination (S-396 reader bug, 2026-09-23):** PostgREST's default
    `max-rows=1000` silently caps the response even when the URL says
    `limit=50000`. 1196d × 262 sym = ~262k rows; a single 50k-limit call
    returns the first 1k rows and the rest are silently dropped. Confirmed
    by §S-398 §二 that the DB actually holds 229,682 rows for the window.

    Bypass: set `Range-Unit: items` + `Range: offset-(offset+page_size-1)`
    AND `Prefer: count=exact` so PostgREST returns the full chunk (HTTP 200
    for full read, 206 Partial Content for ranged reads — both OK).

    Returns (rows, err). On network/empty failure, returns ([], err).
    `page_size=1000` matches the PostgREST default cap exactly so each
    request returns a full page. `max_pages=50` is a defensive ceiling
    (50 × 1000 = 50k rows — if a window blows past this, the universe/window
    combo is wrong and we want to know loudly rather than hang).
    """
    import httpx
    url, key = _sb_env()
    if not url or not key:
        return [], "SUPABASE_URL / SUPABASE_KEY empty in this process"
    syms = ",".join(f'"{s}"' for s in universe)
    all_rows: list[dict[str, Any]] = []
    offset = 0
    page_count = 0
    while True:
        endpoint = (
            f"{url}/rest/v1/ohlcv_daily"
            f"?select=symbol,trade_date,close,source"
            f"&source=eq.{source}"
            f"&symbol=in.({syms})"
            f"&trade_date=gte.{start}"
            f"&trade_date=lte.{end}"
            f"&order=trade_date.asc"
            f"&limit={page_size}"
            f"&offset={offset}"
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(
                    endpoint,
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                        "Range-Unit": "items",
                        "Range": f"{offset}-{offset + page_size - 1}",
                        "Prefer": "count=exact",
                    },
                )
                if r.status_code not in (200, 206):
                    return [], (
                        f"Supabase HTTP {r.status_code} at offset={offset}: "
                        f"{r.text[:140]}"
                    )
                rows = r.json() or []
                all_rows.extend(rows)
                page_count += 1
                # Last page: returned < page_size rows → stop.
                # Use len(rows) < page_size (not ==0) so empty final page
                # doesn't loop forever if server returns 0 rows but
                # Content-Range says more.
                if len(rows) < page_size:
                    break
                offset += page_size
                if page_count >= max_pages:
                    return [], (
                        f"fetch_panel_rows: hit max_pages={max_pages} "
                        f"(={max_pages * page_size} rows) at offset={offset}; "
                        f"universe/window likely too large"
                    )
        except Exception as e:                                  # noqa: BLE001
            return [], (
                f"Supabase request failed at offset={offset}: "
                f"{type(e).__name__}: {str(e)[:120]}"
            )
    return all_rows, None


def load_panel_json(path: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Load panel rows from a JSON file. Used for CI/deterministic replay."""
    p = Path(path)
    if not p.exists():
        return [], f"panel-json not found: {path}"
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return [], f"panel-json must be a list of {{symbol, trade_date, close, source}}"
        return rows, None
    except Exception as e:                                  # noqa: BLE001
        return [], f"panel-json parse failed: {type(e).__name__}: {str(e)[:120]}"


# ── Replay per arm ──────────────────────────────────────────────────────────

def replay_one_arm(
    spec, panel, start: dt.date, end: dt.date, *,
    cadence_days: int = 7,
    jev_decision_fn=None,
) -> list[dict[str, Any]]:
    """Walk the date range at `cadence_days` increments; emit one Decision record per date.

    `jev_decision_fn(as_of: dt.date) -> Optional[JevRegimeDecision]`:
      - None → arm runs without Jev (arm B / C)
      - callable → called per date; if it returns a JevRegimeDecision with
        regime_ok=False, the decide call sees a Jev veto (arm A).

    Returns a list of decision payload dicts, one per date in [start, end].
    Period returns are NOT computed here — compare_three_arms.py does that
    from the consecutive ENTERED legs (separation of concerns: replay emits
    decisions, compare emits PnL).
    """
    from paper_trading.spec_runner import (
        decide_panel_long_only,
        decide_panel_long_only_simple_factor,
    )

    is_arm_c = spec.family == "panel_long_only_simple_factor"

    out: list[dict[str, Any]] = []
    last_rebalance: Optional[dt.date] = None
    d = start
    while d <= end:
        # Cadence: only call decide() on cadence days OR first run.
        # Calling on every date would produce SKIPPED (cadence) noise.
        if last_rebalance is not None and (d - last_rebalance).days < cadence_days:
            # Emit a SKIPPED (cadence) record so the per-day diff is complete
            payload = {
                "date": d.isoformat(), "spec": spec.name, "spec_family": spec.family,
                "verdict": "SKIPPED", "verdict_kind": "skipped",
                "reason": (f"cadence skip — last rebalance {last_rebalance.isoformat()},"
                           f" {(d - last_rebalance).days}d < cadence {cadence_days}d"),
                "panel_source": panel.source, "panel_last_bar": panel.last_bar,
                "_meta": {"arm": "C" if is_arm_c else "B-or-A", "cadence": cadence_days},
            }
            out.append(payload)
            d += dt.timedelta(days=1)
            continue

        jev_decision = jev_decision_fn(d) if jev_decision_fn else None
        if is_arm_c:
            decision = decide_panel_long_only_simple_factor(
                spec, panel, as_of=d, regime=None, n_open=0,
                last_rebalance=last_rebalance,
            )
        else:
            decision = decide_panel_long_only(
                spec, panel, as_of=d, regime=None, n_open=0,
                last_rebalance=last_rebalance, jev_regime=jev_decision,
            )
        payload = decision.as_payload()
        payload["_meta"] = {
            "arm": "C" if is_arm_c else ("A-jev" if jev_decision_fn else "B-baseline"),
            "cadence": cadence_days,
            "last_rebalance": last_rebalance.isoformat() if last_rebalance else None,
        }
        out.append(payload)

        if decision.verdict == "ENTERED":
            last_rebalance = d
        d += dt.timedelta(days=1)

    return out


# ── Freshness probe (Mac-side gate per S-393 risk #1) ────────────────────────

async def probe_supabase_freshness(source: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (last_bar_iso, err). Used as a pre-flight gate before live replay."""
    import httpx
    url, key = _sb_env()
    if not url or not key:
        return None, "SUPABASE_URL / SUPABASE_KEY empty"
    endpoint = (
        f"{url}/rest/v1/ohlcv_daily"
        f"?select=trade_date"
        f"&source=eq.{source}"
        f"&order=trade_date.desc"
        f"&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                endpoint,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200:
                return None, f"Supabase HTTP {r.status_code}: {r.text[:140]}"
            rows = r.json() or []
            if not rows:
                return None, f"0 rows for source={source}"
            return str(rows[0].get("trade_date", ""))[:10], None
    except Exception as e:                                  # noqa: BLE001
        return None, f"Supabase probe failed: {type(e).__name__}: {str(e)[:120]}"


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    p = argparse.ArgumentParser(description="S-393 3-arm replay orchestrator")
    p.add_argument("--start", required=True, help="start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="end date YYYY-MM-DD")
    p.add_argument("--source", default="binance_hist",
                   help="ohlcv_daily source (default: binance_hist)")
    p.add_argument("--out", required=True,
                   help="output dir (will be created)")
    p.add_argument("--spec-a", default=str(SPEC_A17),
                   help=f"arm A spec (default: A-17 = {SPEC_A17.name})")
    p.add_argument("--spec-b", default=str(SPEC_A17),
                   help=f"arm B spec (default: A-17 same as A)")
    p.add_argument("--spec-c", default=str(SPEC_ARMC),
                   help=f"arm C spec (default: {SPEC_ARMC.name})")
    p.add_argument("--panel-json", default=None,
                   help="optional: pre-fetched panel rows (skips Supabase)")
    p.add_argument("--require-freshness", default=None,
                   help="require last_bar >= this date (YYYY-MM-DD); else BLOCKED")
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    from paper_trading.spec_runner import Spec, build_panel

    spec_a = Spec.load(args.spec_a)
    spec_b = Spec.load(args.spec_b)
    spec_c = Spec.load(args.spec_c)
    assert spec_a.family == "panel_long_only"
    assert spec_b.family == "panel_long_only"
    assert spec_c.family == "panel_long_only_simple_factor", \
        f"arm C spec must be panel_long_only_simple_factor, got {spec_c.family}"
    universe = list(spec_a.universe)
    assert set(universe) == set(spec_c.universe), (
        f"arm A/B universe {universe} != arm C universe {list(spec_c.universe)} — "
        f"comparison arms MUST share universe"
    )

    # 1. Load panel
    if args.panel_json:
        rows, err = load_panel_json(args.panel_json)
        source_in_rows = args.source
    else:
        rows, err = await fetch_panel_rows(universe, args.source, args.start, args.end)
        source_in_rows = args.source
    if err:
        print(f"[replay] panel fetch failed: {err}")
        (out_dir / "_meta.json").write_text(json.dumps({
            "blocked_reason": f"panel fetch failed: {err}",
            "ts": dt.datetime.utcnow().isoformat() + "Z",
        }, indent=2))
        return 2
    if not rows:
        print(f"[replay] 0 rows for source={args.source}, window=[{args.start},{args.end}]")
        return 2

    panel = build_panel(rows, source=source_in_rows)
    age_start = panel.age_days(dt.date.fromisoformat(args.start))
    print(f"[replay] panel n_symbols={panel.n_symbols} "
          f"last_bar={panel.last_bar} age_at_start={age_start}d "
          f"n_rows={len(rows)}")

    # Freshness gate (S-393 risk #1)
    if args.require_freshness and panel.last_bar:
        if panel.last_bar < args.require_freshness:
            print(f"[replay] BLOCKED: panel last_bar={panel.last_bar} < "
                  f"required {args.require_freshness}. Run date check: "
                  f"`bash -c 'set -a; . .env; set +a; curl ...'`")
            (out_dir / "_meta.json").write_text(json.dumps({
                "blocked_reason": f"panel last_bar={panel.last_bar} < required "
                                  f"{args.require_freshness}",
                "ts": dt.datetime.utcnow().isoformat() + "Z",
            }, indent=2))
            return 2

    # 2. Replay each arm. For arm A, the Jev decision fn returns
    # MockJevRegimeBackend(mode="always_ok") → regime_ok=True → no veto.
    # This is the baseline-of-wire-path: arm A and arm B should produce the
    # SAME decisions in this comparison (verifies the Jev wire is a no-op
    # when always_ok; if they differ, that's a bug).
    from paper_trading.jev_regime import (
        JevRegimeActor, MockJevRegimeBackend, build_state_payload,
    )
    jev_actor = JevRegimeActor(backend=MockJevRegimeBackend(mode="always_ok"))

    def jev_for_arm_a(as_of: dt.date):
        state = build_state_payload(
            bar_ts=as_of.isoformat(), regime=None,
            panel_age_days=panel.age_days(as_of), panel_n_symbols=panel.n_symbols,
        )
        return jev_actor.decide(state)

    start_date = dt.date.fromisoformat(args.start)
    end_date = dt.date.fromisoformat(args.end)
    cadence = int(spec_a.raw.get("parameters", {}).get("rebalance_cadence", 7))

    print(f"[replay] arm A (Jev always_ok)…")
    arm_a = replay_one_arm(spec_a, panel, start_date, end_date,
                            cadence_days=cadence, jev_decision_fn=jev_for_arm_a)
    print(f"[replay] arm B (no Jev)…")
    arm_b = replay_one_arm(spec_b, panel, start_date, end_date,
                            cadence_days=cadence, jev_decision_fn=None)
    print(f"[replay] arm C (simple factor)…")
    arm_c = replay_one_arm(spec_c, panel, start_date, end_date,
                            cadence_days=cadence, jev_decision_fn=None)

    # 3. Write JSONLs
    (out_dir / "a_jev_decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in arm_a) + "\n",
        encoding="utf-8")
    (out_dir / "b_baseline_decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in arm_b) + "\n",
        encoding="utf-8")
    (out_dir / "c_simple_factor_decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in arm_c) + "\n",
        encoding="utf-8")

    # 4. _meta.json
    n_a = sum(1 for r in arm_a if r["verdict"] == "ENTERED")
    n_b = sum(1 for r in arm_b if r["verdict"] == "ENTERED")
    n_c = sum(1 for r in arm_c if r["verdict"] == "ENTERED")
    (out_dir / "_meta.json").write_text(json.dumps({
        "start": args.start, "end": args.end, "source": args.source,
        "panel_n_symbols": panel.n_symbols,
        "panel_last_bar": panel.last_bar,
        "panel_age_at_start_days": age_start,
        "n_rows": len(rows),
        "universe": universe,
        "cadence_days": cadence,
        "n_entered_arm_a_jev": n_a,
        "n_entered_arm_b_baseline": n_b,
        "n_entered_arm_c_simple_factor": n_c,
        "n_dates_total": len(arm_a),
        "spec_a_path": args.spec_a,
        "spec_b_path": args.spec_b,
        "spec_c_path": args.spec_c,
        "ts": dt.datetime.utcnow().isoformat() + "Z",
        "runner": "paper_trading.replay_three_arms @ 2026-09-21",
    }, indent=2, ensure_ascii=False))

    print(f"[replay] ENTERED counts: A={n_a} B={n_b} C={n_c}")
    print(f"[replay] wrote → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
