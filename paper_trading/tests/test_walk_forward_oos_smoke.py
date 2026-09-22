"""Smoke test for `paper_trading.walk_forward_oos` — S-397 §5b ④ OOS harness.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md`: anchored walk-forward
(arXiv 2110.14914) is the OOS discipline. 6mo train / 2mo val / 6mo test
× 5 folds with monthly step.

What we test:
  1. `build_folds` produces N folds with correct date arithmetic
  2. Last fold doesn't exceed window end (partial fold rejected)
  3. Step parameter shifts test window forward by N months
  4. CLI runs end-to-end and writes expected JSON files
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.walk_forward_oos import build_folds   # noqa: E402


# ── build_folds date arithmetic ────────────────────────────────────────────


def test_build_folds_5_folds_default():
    """Default config (6/2/6, step=1) on 5-year window → 5 folds."""
    start = dt.date(2021, 1, 1)
    end = dt.date(2026, 1, 1)
    folds = build_folds(start, end)
    assert len(folds) == 5
    # First fold: train 6mo, val 2mo, test 6mo → ~14mo total
    f0 = folds[0]
    assert f0["train_start"] == "2021-01-01"
    assert f0["train_end"] == "2021-07-01"  # 6 months later
    assert f0["val_start"] == "2021-07-02"
    assert f0["val_end"] == "2021-09-01"   # 2 months later
    assert f0["test_start"] == "2021-09-02"
    assert f0["test_end"] == "2022-03-02"  # 6 months later
    print(f"✓ fold 0: train={f0['train_start']}→{f0['train_end']}, "
          f"val={f0['val_start']}→{f0['val_end']}, "
          f"test={f0['test_start']}→{f0['test_end']}")


def test_build_folds_step_months():
    """step_months=2 → test windows advance by 2 months each fold."""
    start = dt.date(2021, 1, 1)
    end = dt.date(2023, 1, 1)
    folds = build_folds(start, end, step_months=2)
    assert len(folds) >= 4
    # Verify test_start advances by 2 months between folds
    for i in range(1, len(folds)):
        prev = dt.date.fromisoformat(folds[i - 1]["test_start"])
        curr = dt.date.fromisoformat(folds[i]["test_start"])
        delta_months = (curr.year - prev.year) * 12 + (curr.month - prev.month)
        assert delta_months == 2, f"fold {i} test_start delta = {delta_months}m"
    print(f"✓ step_months=2 respected across {len(folds)} folds")


def test_build_folds_no_partial_folds():
    """Window too short for full test → fewer folds returned, not partial."""
    start = dt.date(2025, 1, 1)
    end = dt.date(2025, 6, 1)  # only 5 months — can't fit one full fold
    folds = build_folds(start, end)
    assert len(folds) == 0
    print(f"✓ too-short window → 0 folds (no partial)")


def test_build_folds_anchored_expanding_train():
    """Anchor = start (always), train window expands."""
    start = dt.date(2021, 1, 1)
    end = dt.date(2023, 1, 1)
    folds = build_folds(start, end)
    for f in folds:
        assert f["train_start"] == "2021-01-01"  # anchor fixed
    print(f"✓ train_start anchored to {start}")


# ── CLI end-to-end ─────────────────────────────────────────────────────────


def test_cli_end_to_end(tmp_path):
    """Run main() → produces _meta.json + folds/ + aggregate.json."""
    out_dir = tmp_path / "wf_test"
    cmd = [
        sys.executable, "-m", "paper_trading.walk_forward_oos",
        "--start", "2021-01-01",
        "--end", "2025-01-01",
        "--out", str(out_dir),
        "--n-folds", "5",
        "--train-months", "6", "--val-months", "2", "--test-months", "6",
        "--step-months", "1",
    ]
    result = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (out_dir / "_meta.json").exists()
    assert (out_dir / "aggregate.json").exists()
    folds_dir = out_dir / "folds"
    assert folds_dir.exists()
    fold_files = list(folds_dir.glob("fold_*.json"))
    assert len(fold_files) == 5
    meta = json.loads((out_dir / "_meta.json").read_text())
    assert meta["methodology"] == "anchored walk-forward (arXiv 2110.14914)"
    print(f"✓ CLI end-to-end: {len(fold_files)} fold files + meta + aggregate")
