"""T-045 评估层 rr_matrix:B 的 13 个用例逐个断言(原来返回 (ok, msg),pytest 不会因 False 失败)+ S-496 的三处修正。"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.rr_matrix_cases as cases
from src.data.evaluation import rr_matrix as rr

_CASES = sorted(n for n in dir(cases) if n.startswith("test_") and callable(getattr(cases, n)))


def test_all_thirteen_cases_are_wired():
    assert len(_CASES) == 13


@pytest.mark.parametrize("name", _CASES)
def test_lane_b_case(name):
    ok, msg = getattr(cases, name)()
    assert ok, msg


def test_fomc_dates_are_the_decision_days():
    d = set(rr.FOMC_DECISION_DATES)
    assert date(2025, 12, 10) in d and date(2025, 12, 17) not in d
    assert date(2026, 10, 28) in d and date(2026, 11, 4) not in d
    assert date(2026, 12, 9) in d and date(2026, 12, 16) not in d
    assert len(d) == 40


def test_rel_maxdd_uses_the_books_own_window():
    """① 在账本开始之前跌了 60%:账本窗口里的相对回撤不该被那一段拖成 +0.5。"""
    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    bench = pd.Series(np.r_[np.linspace(1, 0.4, 200), np.linspace(0.4, 0.5, 100)], index=idx)
    book = bench.iloc[200:] * 1.0
    df = rr.compute_rr_matrix({"x": book}, bench, None, rr.FOMC_DECISION_DATES, idx[-1], n_bootstrap=50)
    assert abs(df["rel_maxdd"].iloc[0]) < 1e-9


_SNIPPET = """
import json, numpy as np, pandas as pd
from src.data.evaluation import rr_matrix as rr
idx = pd.date_range("2026-01-01", periods=120, freq="D")
rng = np.random.default_rng(0)
bench = pd.Series(np.cumprod(1 + rng.normal(0, 0.02, 120)), index=idx)
book = bench * np.cumprod(1 + rng.normal(0.001, 0.01, 120))
df = rr.compute_rr_matrix({"x": book}, bench, None, rr.FOMC_DECISION_DATES, idx[-1], n_bootstrap=200)
print(json.dumps(df[["cell", "ci_lo", "ci_hi", "p_pos"]].round(12).to_dict("records")))
"""


def test_bootstrap_is_reproducible_across_processes():
    """B 版用 hash() 做种子:字符串 hash 每个进程随机,跨天重算的区间会抖。改 crc32 后两种 PYTHONHASHSEED 结果一致。"""
    root = Path(__file__).resolve().parents[1]
    outs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
        r = subprocess.run([sys.executable, "-c", _SNIPPET], cwd=root, env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-500:]
        outs.append(json.loads(r.stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1]


def test_rows_for_db_are_strict_json():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    bench = pd.Series(np.linspace(1, 1.2, 60), index=idx)
    df = rr.compute_rr_matrix({"x": bench * 1.01}, bench, None, rr.FOMC_DECISION_DATES, idx[-1], n_bootstrap=50)
    rows = rr.rows_for_db(df, idx[-1])
    json.dumps(rows, allow_nan=False)
    assert all(r["d"] == "2026-03-01" for r in rows)
