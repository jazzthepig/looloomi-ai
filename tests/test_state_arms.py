"""T-406:状态敞口 R6(S-823)与闸门空头(S-819)的前向内核 —— 与研究逐日相同、夹具历史一致、
只追加不重写、输入不足说清缺哪条臂哪样输入、闸门是同一条序列、不进真钱路径。

三层证据:
(a) **合成序列上与研究函数逐日相同** —— R6 直接 import `docs/research/s823_three_state.py`
    (顶层不读库);闸门空头的 `short_ret` 研究脚本顶层读库、不能 import,按卡上的要求
    在测试里**另写一遍**公式手算小例子对。
(b) **真实数据的历史一致性** —— `tests/fixtures/state_arms_fixture.json` 的输入与期望净值
    来自 T-392 导出的 `s869_extra_panel_a.csv`(独立于生产内核);生产内核重算必须逐日相同
    (≤ 1e-9)。夹具另带研究闸门 vs 生产闸门的逐日位串(导出时核对过,不一致 0 天)。
(c) **写端纪律** —— 起算日之前不写、写过的不改、输入不足时说清是哪条臂哪样输入(假存取函数)。
(d) **不进真钱路径** —— `src/data/execution/` 与 `src/api/routers/executor.py` 的语法树里
    不许出现 `state_arms`;同时要确认它确实挂在 ③ 的每小时循环上。
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.signals.state_arms as sa  # noqa: E402
import src.data.universe.forward_books as fb  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/state_arms_fixture.json").read_text(encoding="utf-8"))
SEG0, SEG1 = FIX["segment"]
START = fb.STATE_ARMS_START


def _s823():
    """研究脚本(顶层不读库,可以 import)。"""
    spec = importlib.util.spec_from_file_location("s823_research", ROOT / "docs/research/s823_three_state.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _research_short_ret(basket: pd.Series, fnd: pd.Series, g: pd.Series, s: float):
    """`docs/research/s819_gate_short.py::short_ret` 的**手抄**(研究脚本顶层读库,不能 import)。

    研究里 `fnd` 在上游已经 `.fillna(0)` 过(`((fb.reindex(cal).fillna(0) + fe.reindex(cal).fillna(0)) / 2)`),
    所以这里不再填 —— 与生产核 `gate_short_returns` 的 `fillna(0.0)` 在同一输入下等价。
    """
    closed = (~g.astype(bool)).shift(1).fillna(False).astype(bool)
    flips = (closed != closed.shift(1).fillna(False)).astype(float)
    return (closed * (-s * basket.fillna(0) + s * fnd) - flips * 0.0005 * s), closed


def _synthetic(n_days: int = 620, seed: int = 406):
    """合成价格/资金费:先涨(明显向上)、再跌(明显向下)、再震荡(不明确)—— 三种状态都要走到。"""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2023-06-01", periods=n_days, freq="D")
    steps = np.concatenate([
        rng.normal(0.004, 0.004, n_days // 3),
        rng.normal(-0.005, 0.005, n_days // 3),
        rng.normal(0.0, 0.012, n_days - 2 * (n_days // 3)),
    ])
    px = 100.0 * np.exp(np.cumsum(steps))
    close = pd.Series(px, index=days)
    funding = pd.Series(rng.normal(0.0001, 0.00005, n_days), index=days)
    return close, funding


# ── (a) 与研究函数逐日相同 ──────────────────────────────────────────────────

def test_r6_kernel_equals_the_research_states_and_account_on_a_synthetic_series() -> None:
    m = _s823()
    p, f = _synthetic()
    e_prod = sa.r6_exposure(p)
    e_res = m.states(p)["R6"]
    assert list(e_prod.index) == list(e_res.index)
    np.testing.assert_array_equal(e_prod.to_numpy(), e_res.to_numpy())
    # 三种状态都真的走到了(否则这个对照是空的)
    vals = set(np.round(e_prod.to_numpy(), 6))
    assert {sa.E_DOWN, sa.E_MID, sa.E_UP} <= vals, f"合成序列没走到全部三态:{sorted(vals)}"

    a, b = str(p.index[300].date()), str(p.index[-1].date())
    r_prod, pos_prod, leg_prod = sa.r6_returns(p, e_prod, f, start=a, end=b)
    r_res, pos_res, leg_res = m.account(e_res, p, f, a, b)
    np.testing.assert_allclose(r_prod.to_numpy(), r_res.to_numpy(), rtol=0, atol=0)
    np.testing.assert_allclose(pos_prod.to_numpy(), pos_res.to_numpy(), rtol=0, atol=0)
    np.testing.assert_allclose(leg_prod.to_numpy(), leg_res.to_numpy(), rtol=0, atol=0)


def test_gate_short_equals_the_hand_copied_research_formula() -> None:
    rng = np.random.default_rng(819)
    days = pd.date_range("2024-01-01", periods=400, freq="D")
    basket = pd.Series(rng.normal(0, 0.02, len(days)), index=days)
    fnd = pd.Series(rng.normal(0, 0.0002, len(days)), index=days)
    g = pd.Series(rng.random(len(days)) > 0.4, index=days)
    for s in (0.15, 0.30):
        r_prod, closed_prod = sa.gate_short_returns(basket, fnd, g, s)
        r_res, closed_res = _research_short_ret(basket, fnd, g, s)
        np.testing.assert_array_equal(closed_prod.to_numpy(), closed_res.to_numpy())
        np.testing.assert_allclose(r_prod.to_numpy(), r_res.to_numpy(), rtol=0, atol=0)
    # 闸门用**前一天**的:今天的闸门关着,今天不空
    one = pd.Series([True, False], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    b0 = pd.Series([0.01, -0.02], index=one.index)
    f0 = pd.Series([0.0, 0.0], index=one.index)
    r, closed = sa.gate_short_returns(b0, f0, one, 0.30)
    assert bool(closed.iloc[0]) is False and bool(closed.iloc[1]) is False, "闸门当天关 ⇒ 次日才空"


# ── (b) 真实数据的历史一致性(夹具) ─────────────────────────────────────────

def test_r6_recomputes_the_export_day_by_day() -> None:
    r6 = FIX["r6"]
    close = pd.Series({pd.Timestamp(k): float(v) for k, v in r6["close"].items()}).sort_index()
    funding = pd.Series({pd.Timestamp(k): float(v) for k, v in r6["funding"].items()}).sort_index()
    e = sa.r6_exposure(close)
    ret, _, _ = sa.r6_returns(close, e, funding, start=SEG0, end=SEG1)
    nav = (1.0 + ret).cumprod()
    exp = r6["expected_nav"]
    assert len(exp) >= 120, "卡上要 ≥ 120 天"
    worst = 0.0
    for d, v in exp.items():
        assert d in nav.index, f"夹具里的 {d} 生产内核没算出来"
        worst = max(worst, abs(float(nav[pd.Timestamp(d)]) - float(v)))
    assert worst <= 1e-9, f"R6 与 T-392 导出最大差 {worst:.3e} > 1e-9"
    # 归一化值 = 原值 / 基点,两者必须自洽
    for d in list(exp)[:5]:
        assert abs(r6["expected_nav_abs"][d] - exp[d] * r6["base_nav"]) <= 1e-9


def test_gate_arms_recompute_the_export_day_by_day() -> None:
    g = FIX["gate"]
    basket = pd.Series({pd.Timestamp(k): float(v) for k, v in g["basket_ret"].items()}).sort_index()
    fnd = pd.Series({pd.Timestamp(k): float(v) for k, v in g["funding"].items()}).sort_index()
    gate = pd.Series({pd.Timestamp(k): bool(v) for k, v in g["gate_open"].items()}).sort_index()
    assert len(g["expected_nav"]["GATE_S15"]) >= 120, "卡上要 ≥ 120 天"
    base = pd.Timestamp(g["base_d"])
    for arm, s in g["arms"].items():
        sr, _ = sa.gate_short_returns(basket, fnd, gate, float(s))
        nav = (1.0 + sr).cumprod()
        assert base in nav.index, "夹具缺基点日"
        nav = nav / float(nav[base])            # 归一化到基点(与导出的 expected_nav 同一个口径)
        exp = g["expected_nav"][arm]
        worst = 0.0
        for d, v in exp.items():
            assert d in nav.index, f"{arm} 夹具里的 {d} 生产内核没算出来"
            worst = max(worst, abs(float(nav[pd.Timestamp(d)]) - float(v)))
        assert worst <= 1e-9, f"{arm} 与 T-392 导出最大差 {worst:.3e} > 1e-9"
        # 归一化值 = 原值 / 基点,两者必须自洽
        for d in list(exp)[:5]:
            assert abs(g["expected_nav_abs"][arm][d] - exp[d] * g["base_nav"][arm]) <= 1e-9


def test_the_production_gate_is_the_same_series_as_the_research_gate() -> None:
    """研究闸门(t156/_style.json)vs 生产闸门(style_index_pit_daily eq.majors / eq.cap)。
    夹具里存的是逐日位串(1 = 闸门开),导出时逐日核对过 —— 这里再核一遍,不许有差异。"""
    ge = FIX["gate_equality"]
    assert ge["overlap_days"] >= 2000, "重叠历史太短,证明不了「同一条序列」"
    assert ge["research"] == ge["production"], "研究闸门与生产闸门不是同一条序列"
    assert ge["mismatches"] == 0
    # 生产核自己重算一遍(style_index_pit_daily 的 ret → 水平 → 200 日均线)
    ret = pd.Series({pd.Timestamp(k): float(v) for k, v in ge["index_ret"].items()}).sort_index()
    gate = sa.majors_gate_from_ret(ret)
    bits = "".join("1" if bool(gate[pd.Timestamp(d)]) else "0" for d in ge["dates"])
    assert bits == ge["production"], "生产核重算的闸门与夹具里的位串不一致"


# ── (c) 写端纪律(假存取函数) ───────────────────────────────────────────────

def _fake_inputs(n_pre: int = 240, n_post: int = 6):
    """起算日之前 n_pre 个日历日 + 起算日之后 n_post 个日历日的价格/资金费/闸门。"""
    days = pd.date_range(pd.Timestamp(START) - pd.Timedelta(days=n_pre * 2),
                         pd.Timestamp(START) + pd.Timedelta(days=n_post), freq="D")
    rng = np.random.default_rng(11)
    px = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(days))))
    closes = {k: pd.Series(px * (1 + 0.1 * i), index=days) for i, k in enumerate(("BTC", "ETH"))}
    fund = {k: pd.Series(rng.normal(0.0001, 0.00005, len(days)), index=days) for k in ("BTC", "ETH")}
    gate = pd.Series(rng.random(len(days)) > 0.4, index=days)
    return closes, fund, gate


def _run(cutoff, *, loader=None, existing=None):
    """跑 `run_state_arms`,把写进去的行收回来。"""
    written: dict[str, list] = {}

    async def reader():
        return list(existing or [])

    async def writer(table, rows, on_conflict):
        written.setdefault(table, []).extend(rows)
        return True, ""

    r = asyncio.run(fb.run_state_arms(cutoff, loader=loader, reader=reader, writer=writer))
    return r, written


def test_run_state_arms_waits_before_the_start_day_and_writes_nothing() -> None:
    r, written = _run(START, loader=lambda c: asyncio.sleep(0, _fake_inputs()))
    assert r.get("waiting"), r
    assert not written, "起算日之前不该写任何行"


def test_run_state_arms_writes_from_the_start_day_and_never_rewrites() -> None:
    closes, fund, gate = _fake_inputs()

    async def loader(cutoff):
        return closes, fund, gate

    r, written = _run("2026-11-20", loader=loader)
    assert r["ok"], r
    nav_rows = written["forward_book_nav"]
    assert {x["arm"] for x in nav_rows} == {"R6", "GATE_S15", "GATE_S30"}
    for x in nav_rows:
        assert x["d"] >= START, f"写了起算日之前的行:{x['d']}"
        assert x["book"] == "state_arms" and x["rule"]
    seeds = [x for x in nav_rows if x["d"] == START]
    assert len(seeds) == 3 and all(x["nav"] == 1.0 for x in seeds), "起算日当天就该有第一行"
    # 再跑一次(库里已经有行)⇒ 不重写、写过的天不改
    have = [{"arm": x["arm"], "d": x["d"], "nav": x["nav"]} for x in nav_rows]
    r2, written2 = _run("2026-11-20", loader=loader, existing=have)
    assert not written2.get("forward_book_nav"), "写过的天不该再写"
    assert r2["ok"]


def test_run_state_arms_says_which_arm_is_missing_which_input() -> None:
    closes, fund, gate = _fake_inputs()

    async def loader_no_funding(cutoff):
        return closes, {}, gate

    r, written = _run("2026-11-20", loader=loader_no_funding)
    assert not r["ok"] and r.get("notes"), r
    joined = " ".join(r["notes"])
    assert "R6" in joined and "资金费" in joined, r["notes"]
    assert "GATE_S15" in joined and "GATE_S30" in joined, r["notes"]
    assert not written.get("forward_book_nav"), "输入不够就不该写"

    async def loader_no_gate(cutoff):
        return closes, fund, pd.Series(dtype=bool)

    r2, w2 = _run("2026-11-20", loader=loader_no_gate)
    joined2 = " ".join(r2.get("notes", []))
    assert "闸门" in joined2 and ("GATE_S15" in joined2 or "GATE_S30" in joined2), r2.get("notes")


def test_run_state_arms_warmup_shortfall_is_named() -> None:
    closes, fund, gate = _fake_inputs(n_pre=3)          # 起算日前只有几个观测

    async def loader(cutoff):
        return closes, fund, gate

    r, written = _run("2026-11-20", loader=loader)
    joined = " ".join(r.get("notes", []))
    assert "R6" in joined and "230" in joined, r.get("notes")
    assert not written.get("forward_book_nav")


def test_gate_arms_never_turn_a_missing_price_into_a_zero_return() -> None:
    """S-898:CG 停订后价格停在 11-19、资金费照常到 11-22 ⇒ 两条闸门臂 11-20 → 11-22 各写了三行只有资金费的假零
    (那三天篮子实际 −6.3% / +3.0% / +2.0%)。价缺 = 没测到:只写到 BTC、ETH 收盘都有、且前一天闸门有值的最后一天。"""
    closes, fund, gate = _fake_inputs()
    last_px = pd.Timestamp("2026-11-19")
    cut_closes = {k: v[v.index <= last_px] for k, v in closes.items()}

    async def loader(cutoff):
        return cut_closes, fund, gate                       # 资金费、闸门都到 11-22,价格只到 11-19

    r, written = _run("2026-11-22", loader=loader)
    nav_rows = written["forward_book_nav"]
    for arm in ("GATE_S15", "GATE_S30", "R6"):
        assert max(x["d"] for x in nav_rows if x["arm"] == arm) == "2026-11-19", arm
    assert any("等源" in w for w in r.get("waiting", [])), r
    assert r["ok"], "等源不是失败"
    # 闸门缺也一样:闸门只到 11-18 ⇒ 最多写到 11-19(用前一天的闸门)
    async def loader_gate_short(cutoff):
        return closes, fund, gate[gate.index <= pd.Timestamp("2026-11-18")]
    r2, w2 = _run("2026-11-22", loader=loader_gate_short)
    assert max(x["d"] for x in w2["forward_book_nav"] if x["arm"] == "GATE_S15") == "2026-11-19"
    assert max(x["d"] for x in w2["forward_book_nav"] if x["arm"] == "R6") == "2026-11-22", "R6 不看闸门"


# ── (d) 不进真钱路径,但挂在 ③ 的每小时循环上 ───────────────────────────────

def test_wired_into_the_hourly_loop_and_never_into_a_real_money_path() -> None:
    mult = (ROOT / "src/data/signals/multiplier.py").read_text(encoding="utf-8")
    assert "run_state_arms" in mult and "from src.data.universe.forward_books import run_state_arms" in mult
    paths = list((ROOT / "src/data/execution").rglob("*.py")) + [ROOT / "src/api/routers/executor.py"]
    for p in paths:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                assert "state_arms" not in mod and not any("state_arms" in n for n in names), f"{p} 不许读状态敞口账"
