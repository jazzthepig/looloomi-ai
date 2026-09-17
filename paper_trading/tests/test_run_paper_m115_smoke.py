"""Smoke test for `run_paper_m115.py` — spec + runner pipeline.

Three claims worth testing (each = one realistic failure mode):
  1. M-115 spec loads via `Spec.load` without raising the retired-family error
  2. Runner exits 0 + logs a Decision JSON line on synthetic fallback
  3. `--no-fallback-synthetic` exits 1 + logs a BLOCKED Decision

Per the same discipline as `test_decide_survivors_book.py` (456 LoC, 12 mutation
tests): each assertion is paired with one mutation that should flip it.

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
SPEC_PATH = ROOT / "paper_trading" / "specs" / "m115_book_b_m93_r14.json"
LOG_PATH = ROOT / "paper_trading" / "state" / "m115_book_b_decisions.jsonl"
RUNNER = ROOT / "paper_trading" / "run_paper_m115.py"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the runner as a subprocess; capture stdout/stderr/rc."""
    e = os.environ.copy()
    # Force Supabase env to empty (test must not depend on host env)
    e["SUPABASE_URL"] = ""
    e["SUPABASE_KEY"] = ""
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "paper_trading.run_paper_m115", *args],
        cwd=str(ROOT), capture_output=True, text=True, env=e, timeout=30,
    )


def test_spec_loads_with_current_family_name():
    """Spec MUST use 'survivors_only_lag1_book' (not the retired '_bookB' suffix)."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["spec_family"] == "survivors_only_lag1_book", (
        "spec_family 必须用当前名,否则 spec_runner._RETIRED_FAMILIES (spec_runner.py:110-114) "
        "会在加载时抛 ValueError 拒绝。这条 mutation = 把 spec_family 改回 'survivors_only_lag1_book_bookB'"
    )
    assert "sleeve_R14-Lite" in spec["parameters"], (
        "Book B 必须带 R14-Lite sleeve(R14-Lite retention 0.614 PASS M-114 是它跟 Book A 的区别)。"
        "这条 mutation = 改 sleeve_R14-Lite → sleeve_R19-Lite"
    )


def test_synthetic_fallback_writes_entered_decision():
    """With Supabase env empty + default flags, runner should log ENTERED with synthetic_reason."""
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
        "synthetic_reason 必须说明是 fetch 失败,不是其它原因。这条 mutation = 删掉 fetch 失败信息"
    )
    assert payload["spec"] == "M115_BOOK_B_M93_R14"


def test_no_fallback_synthetic_blocks_and_exits_nonzero():
    """With Supabase env empty + --no-fallback-synthetic, runner should log BLOCKED + exit 1."""
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
        "BLOCKED reason 必须提到 fetch 失败原因(让看日志的人知道是哪条规则挡的)。"
        "这条 mutation = 把 reason 改成 'no data'"
    )
