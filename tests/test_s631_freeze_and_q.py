"""S-631(Jazz 10-20「先冻结了,根据我们的研究重新给策略打分和开跑」):

冻结 —— 一处登记(accounting/frozen.py),四处生效:循环不起、登记表 status、L3 / 证据面不可选、判活器判「不适用」。
ⓠ —— 信号不改,改挂 ① 并在 ③ 的同一个记账函数里单独记 NAV;q_slow 在 majors 站上 200 日线时不许减仓。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.accounting import frozen as fz  # noqa: E402
from src.data.signals import multiplier as mx  # noqa: E402

SIX = {"causal_paper", "scalable_book", "combined_book", "dingge_paper", "fusion_paper", "two_layer_paper"}


def test_frozen_registry_is_the_one_source():
    assert set(fz.FROZEN) == SIX
    from src.data.accounting.registry import BOOKS
    status = {b.id: b.status for b in BOOKS}
    assert all(status[b] == "frozen" for b in SIX)
    assert status["core_cap"] == "paper" and status["tom_overlay"] == "paper", "①③ 不在这里冻结"
    assert {f.table for f in fz.FROZEN.values()} == set(fz.frozen_tables())


def test_main_does_not_start_frozen_loops_but_says_so():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    for f in fz.FROZEN.values():
        head = src.split(f"async def _start{f.loop}():", 1)[1][:400]
        assert f'_frozen_skip("{f.book_id}", "{f.loop}"' in head.split("_asyncio.create_task")[0], f.loop
    body = src.split("async def _frozen_skip", 1)[1].split("\n\n\n", 1)[0]
    assert "_record_loop_attempt(" in body and "_beat(" in body and "refused" in body


def test_freshness_reads_frozen_as_not_applicable_not_dead():
    from src.data.market.producer_freshness import NOT_APPLICABLE, assess, overall
    h = assess("causal_paper_nav", 86, "2026-10-20", "2026-10-20", today=pd.Timestamp("2026-11-30").date())
    assert h.verdict == NOT_APPLICABLE and "冻结" in h.reason
    assert overall([h])["n_dead_or_corrupt"] == 0


def test_proof_and_l3_treat_frozen_as_not_selectable():
    from src.data.accounting.proof import evidence_class
    assert evidence_class("frozen", "", 90) == "frozen"
    src = (ROOT / "src" / "data" / "accounting" / "combine.py").read_text(encoding="utf-8")
    assert 'not in ("retired_by_design", "frozen")' in src, "L3 的候选里不能有冻结的账本"


def test_q_exposure_alignment_and_slow_gate():
    days = pd.date_range("2026-09-01", periods=6, freq="D")
    q = pd.Series({pd.Timestamp("2026-09-02"): 0.5, pd.Timestamp("2026-09-05"): 1.3})
    gate = pd.Series({d: (i < 3) for i, d in enumerate(pd.date_range("2026-08-31", periods=7, freq="D"))})
    v2, slow = mx.q_exposures(q, gate, days)
    assert list(v2) == [1.0, 0.5, 0.5, 0.5, 1.3, 1.3], "q 取 mark_date ≤ d 的最近一条;还没有 q 的日子 = 1.0"
    # gate_up 08-31..09-02 = True;作用于 d 的是 d−1 收盘的状态 ⇒ 09-01..09-03 在线上(不许减),09-04 起在线下
    assert list(slow) == [1.0, 1.0, 1.0, 0.5, 1.3, 1.3]


def test_q_book_uses_the_same_kernel_and_can_go_to_zero():
    idx = pd.date_range("2026-10-10", periods=15, freq="D")
    core = pd.Series(np.full(15, 0.01), index=idx)
    q = pd.Series({pd.Timestamp("2026-10-10"): 0.0})
    gate = pd.Series(False, index=pd.date_range("2026-09-01", "2026-10-30", freq="D"))
    rows, ev = mx.build_rows_q(core, pd.DataFrame(), q, gate, idx[-1])
    rep = [r for r in rows if r["arm"] == mx.REPLAY_ARM_Q]
    assert all(r["m"] == 0.0 for r in rep[1:]), "ⓠ 可以到 0(③ 不行)"
    assert abs(rep[2]["ret"] - mx.CASH_ANN / 365.0) < 1e-9, "m = 0 时拿现金腿"
    fwd = [r for r in rows if r["arm"] == mx.ARM_Q]
    assert fwd and min(r["d"] for r in fwd) > mx.INCEPTION_Q.date().isoformat(), "前向只从 10-20 收盘之后"
    assert {r["arm"] for r in rows} == {mx.ARM_Q, mx.REPLAY_ARM_Q, mx.ARM_QS, mx.REPLAY_ARM_QS}
    assert mx.build_rows_q(core, pd.DataFrame(), pd.Series(dtype=float), gate, idx[-1])[0] == [], "读不到 q 不顶替"


def test_third_layer_still_clips_to_its_definition():
    idx = pd.date_range("2026-10-01", periods=3, freq="D")
    book = mx.apply_multiplier(pd.Series([0.0, 0.0, 0.0], index=idx), pd.Series(0.0, index=idx), pd.Series(dtype=float))
    assert (book["m"] == 0.7).all(), "③ 默认仍是 0.7–1.3,不被 ⓠ 的放宽带走"
