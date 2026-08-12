"""
Experiment Recorder — Qlib-style run memory (Seth, 2026-07-10).
================================================================

The positive-results twin of REFUTATION_LEDGER.md. Per LOOP_VS_OSS_2026-07-10.md, our
loop lacked a per-run recorder — the thing Qlib gets from MLflow and FreqAI gets from
historic_predictions. Without it, every backtest is a throwaway: metrics scroll past in a
terminal and the search history evaporates. This makes every run PERMANENT and QUERYABLE.

One row per run: what we tested, on what, with what costs, what came out (Sharpe / IC /
DSR / correlation-to-book / drawdown), and the verdict. Refuted runs additionally get a
REFUTATION_LEDGER entry; certified runs are the shortlist for capital.

Storage: Supabase `experiment_runs` when creds are set; a local JSONL
(`reports/experiment_runs.jsonl`) always, so it works from any research script in the
sandbox with no dependencies. Idempotent on run_id.

Pure stdlib + httpx.
"""
from __future__ import annotations
from src.api.runtime_role import note_refusal, refuse_write

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

_JSONL = Path(__file__).resolve().parents[3] / "reports" / "experiment_runs.jsonl"

# verdict vocabulary — mirrors the ledger legend
VERDICTS = {"certified", "candidate", "null", "refuted", "false_alarm", "exploratory"}


@dataclass
class ExperimentRun:
    kind: str                       # "backtest" | "sleeve" | "signal" | "portfolio" | "audit"
    hypothesis: str                 # one sentence: what we tested
    universe: str                   # e.g. "24 majors" / "SwingOverlayV7" / "50 perps"
    verdict: str                    # one of VERDICTS
    # metrics (all optional — fill what the run produced)
    sharpe: Optional[float] = None
    ic: Optional[float] = None
    dsr: Optional[float] = None
    corr_to_book: Optional[float] = None
    max_dd_pct: Optional[float] = None
    total_return_pct: Optional[float] = None
    n_obs: Optional[int] = None
    # provenance
    cost_bps: Optional[float] = None
    window: Optional[str] = None            # e.g. "2024-01→2025-10"
    params: dict = field(default_factory=dict)
    notes: str = ""
    ledger_ref: Optional[str] = None        # e.g. "R7" when also in REFUTATION_LEDGER
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict {self.verdict!r} not in {VERDICTS}")


def _supabase_insert(row: dict) -> bool:
    # RECORD GATE (2026-08-12, S-150). This module writes a FORWARD-RECORD table
    # and bypasses store.py, so the S-149 gate did not reach it. The claim made
    # yesterday — "the write side of the record has one owner" — was broader than
    # the implementation: the gate covered two functions while five record writers
    # went around them. That is the exact defect this session has been naming,
    # committed inside the fix for it, and endorsed by a guard that only checked
    # the two functions it knew about.
    _refusal = refuse_write("experiment_runs")
    if _refusal:
        note_refusal("experiment_runs", _refusal)
        return False

    url = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_REST_URL")
    key = (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY"))
    if not url or not key:
        return False
    try:
        import httpx
        r = httpx.post(f"{url.rstrip('/')}/rest/v1/experiment_runs",
                       headers={"apikey": key, "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json", "Prefer": "return=minimal"},
                       json=row, timeout=20)
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


def _jsonl_append(row: dict) -> None:
    _JSONL.parent.mkdir(parents=True, exist_ok=True)
    with _JSONL.open("a") as f:
        f.write(json.dumps(row) + "\n")


def record(run: ExperimentRun) -> dict:
    """Persist one run. Always JSONL; Supabase too when creds present. Returns the row."""
    row = asdict(run)
    _jsonl_append(row)
    row["_supabase"] = _supabase_insert(row)
    return row


def record_run(**kwargs) -> dict:
    """Convenience: record(ExperimentRun(**kwargs))."""
    return record(ExperimentRun(**kwargs))


def load_all() -> list[dict]:
    if not _JSONL.exists():
        return []
    return [json.loads(l) for l in _JSONL.read_text().splitlines() if l.strip()]


def shortlist(min_dsr: float = 0.95, min_sharpe: float = 0.0) -> list[dict]:
    """The capital shortlist: certified runs clearing the bars."""
    out = []
    for r in load_all():
        if r.get("verdict") == "certified" and (r.get("dsr") or 0) >= min_dsr \
                and (r.get("sharpe") or -9) >= min_sharpe:
            out.append(r)
    return sorted(out, key=lambda r: (r.get("dsr") or 0), reverse=True)


# ── Backfill: this session's real runs (so the recorder starts with truth) ───

_SESSION_2026_07_10 = [
    dict(kind="audit", hypothesis="SwingOverlay lineage survives DSR after 50-way selection",
         universe="9 candidates", verdict="certified", dsr=0.999, sharpe=6.3,
         notes="V8_Regime .999, V7 .998, V9 .994, V10 .994, V10-FA .981", ledger_ref=None,
         window="freqtrade backtests", params={"trials": 9}),
    dict(kind="sleeve", hypothesis="Funding-crowding market-neutral sleeve (positioning cause)",
         universe="24 majors", verdict="candidate", sharpe=1.34, max_dd_pct=10.0,
         total_return_pct=43.0, corr_to_book=0.002, cost_bps=5, window="2024-01→2025-10",
         notes="OOS Sharpe +1.02, orthogonal to swing (corr +0.002)", params={"Kwin": 10}),
    dict(kind="sleeve", hypothesis="Expanding causal sleeve 24→50 perps improves it",
         universe="50 perps", verdict="refuted", sharpe=0.12, max_dd_pct=30.0,
         cost_bps=5, ledger_ref="R7", notes="large-cap signal; thin names = noise", params={"Kwin": 10}),
    dict(kind="signal", hypothesis="Funding acceleration improves the positioning sleeve",
         universe="24 majors", verdict="refuted", sharpe=0.76, ledger_ref="R8",
         notes="monotonic degradation vs level-only 1.34", params={"accel_w": 1.0}),
    dict(kind="backtest", hypothesis="Empirical edge-map direction generalizes OOS (edge gate)",
         universe="Nautilus LS v1", verdict="refuted", notes="p=0.867, catastrophic BTC longs",
         ledger_ref="R1", params={}),
]


def backfill_session():
    existing = {(r.get("hypothesis"), r.get("universe")) for r in load_all()}
    n = 0
    for r in _SESSION_2026_07_10:
        if (r["hypothesis"], r["universe"]) not in existing:
            record_run(**r); n += 1
    return n


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        print(f"[recorder] backfilled {backfill_session()} session runs")
    runs = load_all()
    print(f"[recorder] {len(runs)} runs in {_JSONL}")
    print(f"[recorder] capital shortlist (certified, DSR≥0.95): "
          f"{[r['hypothesis'][:40] for r in shortlist()]}")
    for r in runs[-6:]:
        print(f"  {r['ts']} [{r['verdict']:<9}] {r['kind']:<9} "
              f"Sharpe={r.get('sharpe')} DSR={r.get('dsr')} — {r['hypothesis'][:50]}")
