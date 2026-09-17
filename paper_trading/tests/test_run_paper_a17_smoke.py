"""Smoke test for `run_paper_a17.py` — A-17 panel_long_only spec + runner pipeline.

Three claims worth testing (each = one realistic failure mode):
  1. A-17 spec loads via `Spec.load` without raising the retired-family or
     invalid-allocation error (Spec.load REJECTS cis_weight / market_cap_weight
     in v1 ship per spec_runner.py:375-379)
  2. Runner exits 0 + logs an ENTERED Decision on synthetic fallback
     (verify exactly N=5 legs, 1/N weight, equal_weight, all long)
  3. `--no-fallback-synthetic` exits 1 + logs a BLOCKED Decision
  4. --last-rebalance within cadence → SKIPPED (rebalance discipline)
  5. regime_gate is empty (regime-blind ① benchmark) — verify the spec
     explicitly declares it so a future edit doesn't accidentally add a gate

Per the same discipline as `test_decide_survivors_book.py`: each assertion is
paired with one mutation that should flip it.

These run without Supabase env vars; the runner falls back to synthetic panel.
Real-data integration is the next concern (M-119: narrative_daily stale 42d +
S-370: coingecko_pro_ohlc 73d + A-372-1/2 in flight on Mac).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "paper_trading" / "specs" / "a17_panel_long_only.json"
LOG_PATH = ROOT / "paper_trading" / "state" / "a17_panel_long_only_decisions.jsonl"
RUNNER = ROOT / "paper_trading" / "run_paper_a17.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run the runner as a subprocess; force Supabase env to empty."""
    e = os.environ.copy()
    e["SUPABASE_URL"] = ""
    e["SUPABASE_KEY"] = ""
    return subprocess.run(
        [sys.executable, "-m", "paper_trading.run_paper_a17", *args],
        cwd=str(ROOT), capture_output=True, text=True, env=e, timeout=30,
    )


def test_spec_loads_with_v1_equal_weight():
    """Spec must use spec_family='panel_long_only' + allocation='equal_weight' (v1 ship)."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["spec_family"] == "panel_long_only", (
        "spec_family 必须 'panel_long_only',否则 Spec.load 走 UnwiredFamily "
        "(spec_runner.py:274-283)。mutation = 把 spec_family 改回 'btc_trend_regime_ladder'"
    )
    assert spec["parameters"]["allocation"] == "equal_weight", (
        "Spec.load 在 v1 ship 拒绝 cis_weight / market_cap_weight "
        "(spec_runner.py:375-379)。mutation = 改成 'cis_weight'"
    )
    assert spec["parameters"]["target_size"] == 0, (
        "target_size=0 = whole universe (spec_runner.py:380-383)。"
        "mutation = 改成 2 (top-2 by allocation)"
    )


def test_spec_regime_gate_empty_by_design():
    """§5b ① benchmark should be regime-blind. regime_gate MUST be empty."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    rg = spec["parameters"].get("regime_gate", {})
    assert rg == {}, (
        f"regime_gate 必须空 dict {{}} —— §5b ① benchmark 按设计 regime-blind。\n"
        f"ARCHITECTURE §5b ①: 'long-only hold of the panel — the FoF core; every "
        f"sleeve's benchmark is hold the panel, NEVER 0'。\n"
        f"Got: {rg}\n"
        f"mutation = 改成 {{'RISK_OFF': False}}"
    )


def test_synthetic_fallback_writes_entered_decision():
    """With Supabase env empty + first run (--last-rebalance None), ENTERED + N legs."""
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    cp = _run("--as-of", "2026-09-17")
    assert cp.returncode == 0, f"stdout={cp.stdout!r} stderr={cp.stderr!r}"
    assert LOG_PATH.exists(), f"runner should have created log file. stderr={cp.stderr!r}"
    line = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["verdict"] == "ENTERED", f"got verdict={payload['verdict']!r}"
    assert payload["_meta"]["synthetic_panel"] is True
    assert "SUPABASE_URL" in (payload["_meta"].get("synthetic_reason") or ""), (
        "synthetic_reason 必须说明是 fetch 失败,不是其它原因。"
        "mutation = 删掉 fetch 失败信息"
    )
    assert payload["spec"] == "A17_PANEL_LONG_ONLY", (
        f"as_payload() (spec_runner.py) 用 key 'spec'(不是 'spec_name')。"
        f"got {payload.get('spec')!r}"
    )
    # A-17 ① 形状:5 universe = 5 legs, 1/N = 0.2 each, all long
    assert len(payload["legs"]) == 5, f"expected 5 legs (BTC/ETH/SOL/BNB/XRP), got {len(payload['legs'])}"
    for leg in payload["legs"]:
        assert leg["side"] == "long"
        assert abs(leg["weight"] - 0.20) < 1e-9, (
            f"equal_weight spec → 1/N=0.20 each; got {leg['weight']}"
        )
        assert leg["price"] == 100.0, f"synthetic flat price=100; got {leg['price']}"


def test_no_fallback_synthetic_blocks_and_exits_nonzero():
    """With Supabase env empty + --no-fallback-synthetic, BLOCKED + exit 1."""
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    cp = _run("--as-of", "2026-09-17", "--no-fallback-synthetic")
    assert cp.returncode == 1, (
        f"BLOCKED should exit 1, got {cp.returncode}. stderr={cp.stderr!r}"
    )
    assert LOG_PATH.exists()
    line = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["verdict"] == "BLOCKED"
    assert "SUPABASE_URL" in payload.get("reason", ""), (
        "BLOCKED reason 必须提到 fetch 失败原因。"
        "mutation = 把 reason 改成 'no data'"
    )


def test_within_cadence_skipped():
    """--last-rebalance 3d ago + cadence=7d → SKIPPED (rebalance discipline)."""
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    cp = _run("--as-of", "2026-09-17", "--last-rebalance", "2026-09-14")  # 3d ago
    assert cp.returncode == 0, f"SKIPPED is not an error; stderr={cp.stderr!r}"
    line = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["verdict"] == "SKIPPED", (
        f"3d < cadence 7d → SKIPPED。got verdict={payload['verdict']!r}"
    )
    assert "3d" in payload["reason"] and "7d" in payload["reason"], (
        f"SKIPPED reason 必须含 '3d' and '7d' (cadence trace)。got: {payload['reason'][:80]!r}"
    )
