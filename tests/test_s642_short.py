"""T-412:S-642 熊市空头臂的生产纯函数(`src/data/signals/s642_short.py`)三块检验。

① **合成序列上手算的小例子**:指标 / 宇宙 / 信号 / 开平票 / 串链 / 逐日盯市,逐个数字手算写死
   (三个歧义点在这里钉死:stop 优先、进场当根打到 stop 按 stop 价、成本始终借记)。
② **历史一致性**:从研究产物导出的那一段(`tests/fixtures/s642_fixture.json`,导出脚本
   `docs/research/t412_s642_fixture.py`),生产函数重算的票本与逐日净值要和族曲线
   (`docs/research/t348_r3_families.csv` 的 family=S642)逐位相同(相对差 ≤ 1e-9)。
③ **语法树**:`src/data/execution/` 与 `src/api/routers/executor.py` 不许 import 本模块
   —— 本模块只提供纯函数,不建写入端、不接任何循环。
"""
from __future__ import annotations

import ast
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data.signals.s642_short import (CAP, COST, EXCL, MAX_BARS, RISK_FRAC, chain,
                                         gate_closed_by_day, indicators, nav, run_short,
                                         signal_short, universe_ok)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "s642_fixture.json"

D0 = date(2022, 1, 1)


def _day(i: int) -> str:
    return (D0 + timedelta(days=i)).isoformat()


def _row(i: int, o: float, h: float, l: float, c: float, v: float) -> dict:
    return {"trade_date": _day(i), "open": o, "high": h, "low": l, "close": c, "volume": v}


def _flat(n: int, price: float = 100.0, vol: float = 60_000.0) -> list[dict]:
    """n 根平盘:开高低收都是 price,币量 vol ⇒ 美元额 = price × vol。"""
    return [_row(i, price, price, price, price, vol) for i in range(n)]


def _series(tail: list[tuple]) -> list[dict]:
    """前 220 根平盘 100(信号日下标必须 ≥ 220),后面接 tail(元组 = 开高低收量)。"""
    rows = _flat(220)
    for k, (o, h, l, c, v) in enumerate(tail):
        rows.append(_row(220 + k, o, h, l, c, v))
    return rows


# 信号日那根的量放大 2 倍、跌到 100 以下;进场根 221。
SIG = (90.0, 95.0, 89.0, 90.0, 200_000.0)
# 手算:TR[207..219] = 0(平盘),TR[220] = max(95−89, |95−100|, |89−100|) = 11 ⇒ ATR14 = 11/14
ATR = 11.0 / 14.0
# 进场根开盘 88 ⇒ 止损 = 88 + 2.5 × ATR14
STOP = 88.0 + 2.5 * ATR


# ── ① 合成序列上手算 ──────────────────────────────────────────────────────────────────────────
def test_indicators_hand_computed():
    rows = [_row(0, 10.0, 12.0, 9.0, 11.0, 100.0),
            _row(1, 11.0, 15.0, 10.0, 14.0, 200.0),
            _row(2, 14.0, 16.0, 13.0, 13.0, 300.0),
            _row(3, 13.0, 14.0, 12.0, 12.0, 400.0)]
    ind = indicators(rows)
    # 美元额 = close × volume
    assert ind["dv"] == [1100.0, 2800.0, 3900.0, 4800.0]
    # sma20 在样本不足 20 根时 = 至今的均值(照研究口径,不是 None)
    assert ind["sma20"][0] == 11.0
    assert ind["sma20"][3] == (11.0 + 14.0 + 13.0 + 12.0) / 4
    # sma200 同理(不足 200 根时是至今均值)
    assert ind["sma200"][3] == (11.0 + 14.0 + 13.0 + 12.0) / 4
    # TR:pc[0] = 自身收盘,其余用前收
    #   TR0 = max(12−9, |12−11|, |9−11|) = 3
    #   TR1 = max(15−10, |15−11|, |10−11|) = 5
    #   TR2 = max(16−13, |16−14|, |13−14|) = 3
    #   TR3 = max(14−12, |14−13|, |12−13|) = 2
    # ATR14[3] = (3+5+3+2)/4
    assert ind["atr14"][3] == (3.0 + 5.0 + 3.0 + 2.0) / 4
    # adv30 = 至今美元额均值;adv40p = **不含当日**的 40 日均值(这里只有前 3 根)
    assert ind["adv30"][3] == (1100.0 + 2800.0 + 3900.0 + 4800.0) / 4
    assert ind["adv40p"][3] == (1100.0 + 2800.0 + 3900.0) / 3
    # hh40 / ll40 = **前 40 日**(不含当日)的高/低
    assert ind["hh40"][3] == 16.0
    assert ind["ll40"][3] == 9.0
    assert ind["d"] == [_day(0), _day(1), _day(2), _day(3)]


def _ind(**over) -> dict:
    """造一个只够 universe_ok / signal_short 用的指标包(下标 0..220,取 220)。"""
    def seq(v, n=221):
        return [v] * n
    base = {"atr14": seq(1.0), "adv30": seq(6e6), "hh40": seq(100.0), "ll40": seq(60.0),
            "adv40p": seq(5e6), "dv": seq(2e7), "c": seq(50.0), "sma200": seq(80.0),
            "d": [_day(i) for i in range(221)]}
    base.update(over)
    for k, v in over.items():                      # 覆盖值也补到 221 根,方便直接取下标 220
        if isinstance(v, list) and len(v) < 221:
            base[k] = list(v) + [v[-1]] * (221 - len(v))
    return base


def test_universe_ok_needs_all_five_conditions():
    ind = _ind()
    assert universe_ok(ind, 220) is True
    # ① 往前满 220 根
    assert universe_ok(ind, 219) is False
    # ② ATR14 > 0
    assert universe_ok(_ind(atr14=[0.0]), 220) is False
    assert universe_ok(_ind(atr14=[None]), 220) is False
    # ③ ADV30 ≥ 5e6
    assert universe_ok(_ind(adv30=[4_999_999.0]), 220) is False
    assert universe_ok(_ind(adv30=[None]), 220) is False
    # ④ (HH40−LL40)/HH40 ≤ 0.40
    assert universe_ok(_ind(hh40=[100.0], ll40=[59.0]), 220) is False
    assert universe_ok(_ind(hh40=[100.0], ll40=[60.0]), 220) is True
    assert universe_ok(_ind(hh40=[0.0]), 220) is False
    # ⑤ 当日美元额 ≥ 2 × 前 40 日均额(不含当日)
    assert universe_ok(_ind(dv=[2e7], adv40p=[1.1e7]), 220) is False
    assert universe_ok(_ind(dv=[2.2e7], adv40p=[1.1e7]), 220) is True


def test_signal_short_needs_closed_gate_below_ll40_and_sma200():
    ind = _ind()
    gate = {_day(220): True}
    assert signal_short(ind, 220, gate) is True
    # 闸门开 ⇒ 不做
    assert signal_short(ind, 220, {_day(220): False}) is False
    # 闸门当天没值 ⇒ 不做(研究默认 gate_closed 缺失 = 不做)
    assert signal_short(ind, 220, {}) is False
    # 收盘没破前 40 日低
    assert signal_short(_ind(c=[60.0]), 220, gate) is False
    # 收盘没收在 200 日线之下
    assert signal_short(_ind(c=[90.0]), 220, gate) is False


def _run(rows: list[dict], gate_days: set[str]) -> list[dict]:
    bars = {"TEST": rows}
    gate = {d: (d in gate_days) for d in {r["trade_date"] for r in rows}}
    return run_short(bars, gate, _day(0), _day(len(rows)))


def test_run_short_entry_bar_hitting_stop_fills_at_stop_price():
    """歧义点 ③:进场当根就打到 stop ⇒ 按 stop 价成交(不按开盘价)。"""
    rows = _series([SIG, (88.0, 95.0, 87.0, 88.0, 200_000.0)])
    tk = _run(rows, {_day(220)})
    assert len(tk) == 1
    t = tk[0]
    assert t["entry_d"] == _day(221) and t["entry_px"] == 88.0
    assert t["stop_px"] == STOP
    assert t["exit_reason"] == "stop" and t["exit_d"] == _day(221)
    assert t["exit_px"] == STOP          # 不是开盘 88
    assert t["bars_held"] == 1
    # R = (进场−出场)/(止损−进场) − 0.004 × 进场/(止损−进场)
    assert t["r"] == (88.0 - STOP) / (STOP - 88.0) - 0.004 * 88.0 / (STOP - 88.0)


def test_run_short_stop_wins_over_sma20():
    """歧义点 ①:同一根里 stop 与 sma20 都触发 ⇒ stop 优先。"""
    tail = [SIG, (88.0, 88.0, 59.0, 60.0, 200_000.0)]
    tail += [(60.0, 60.0, 60.0, 60.0, 200_000.0)] * 19          # 222..240
    tail += [(60.0, 95.0, 60.0, 70.0, 200_000.0)]                # 241:high ≥ stop 且 close > sma20
    tk = _run(_series(tail), {_day(220)})
    assert len(tk) == 1
    t = tk[0]
    assert t["exit_reason"] == "stop"
    assert t["exit_d"] == _day(241) and t["exit_px"] == STOP    # 开盘 60 < stop ⇒ 按 stop 成交
    assert t["bars_held"] == 21


def test_run_short_sma20_exit_fills_at_next_bar_open():
    tail = [SIG, (88.0, 88.0, 59.0, 60.0, 200_000.0)]
    tail += [(60.0, 60.0, 60.0, 60.0, 200_000.0)] * 19          # 222..240
    tail += [(60.0, 61.0, 60.0, 70.0, 200_000.0)]                # 241:close 70 > sma20 60.5
    tail += [(72.0, 73.0, 71.0, 72.0, 200_000.0)]                # 242:次日开盘出场
    tk = _run(_series(tail), {_day(220)})
    assert len(tk) == 1
    t = tk[0]
    assert t["exit_reason"] == "sma20"
    assert t["exit_d"] == _day(242) and t["exit_px"] == 72.0     # 次日开盘,不是当日收盘
    assert t["bars_held"] == 22


def test_run_short_time_exit_after_120_bars():
    tail = [SIG, (88.0, 88.0, 59.0, 60.0, 200_000.0)]
    tail += [(60.0, 60.0, 60.0, 60.0, 200_000.0)] * 119         # 222..340
    rows = _series(tail)
    tk = _run(rows, {_day(220)})
    assert len(tk) == 1
    t = tk[0]
    assert t["exit_reason"] == "time"
    assert t["exit_d"] == _day(340) and t["exit_px"] == 60.0
    assert t["bars_held"] == MAX_BARS
    assert t["still"] is False


def test_chain_drops_overlapping_tickets_of_the_same_symbol():
    a = {"symbol": "X", "signal_d": "2022-01-01", "ei": 10, "xi": 20}
    b = {"symbol": "X", "signal_d": "2022-01-02", "ei": 15, "xi": 25}   # 与 a 重叠 ⇒ 丢
    c = {"symbol": "X", "signal_d": "2022-01-03", "ei": 21, "xi": 30}   # 在 a 出场之后 ⇒ 留
    d = {"symbol": "Y", "signal_d": "2022-01-01", "ei": 11, "xi": 12}   # 别的 symbol ⇒ 不受串链影响
    got = chain([a, b, c, d])
    # 结果按 (signal_d, symbol) 排序(照研究口径)
    assert [(t["symbol"], t["signal_d"]) for t in got] == [
        ("X", "2022-01-01"), ("Y", "2022-01-01"), ("X", "2022-01-03")]


def test_nav_single_ticket_hand_computed():
    """一张空票:逐日盯市 + 复利 + 成本**借记**(abs(units))。"""
    tail = [SIG, (88.0, 88.0, 59.0, 60.0, 200_000.0)]
    tail += [(60.0, 60.0, 60.0, 60.0, 200_000.0)] * 19
    tail += [(60.0, 61.0, 60.0, 70.0, 200_000.0)]
    tail += [(72.0, 73.0, 71.0, 72.0, 200_000.0)]
    rows = _series(tail)
    tk = _run(rows, {_day(220)})
    assert len(tk) == 1
    curve = nav(tk, {"TEST": rows}, f=RISK_FRAC, cap=CAP, d_to=_day(242))
    by_d = {r["d"]: r for r in curve}
    # 手算:空头 units 为负(f × 前一日权益 ÷ (进场−止损),分母为负)
    units = RISK_FRAC * 1.0 / (88.0 - STOP)
    assert units < 0
    # 进场当天:盯市到收盘 60,成本先记一半(0.004/2 × 进场)
    eq_entry = 1.0 + units * (60.0 - 88.0) - abs(units) * (COST / 2) * 88.0
    row = by_d[_day(221)]
    assert row["equity"] == pytest.approx(eq_entry, abs=1e-12)
    assert row["open_n"] == 1
    assert row["realized"] == pytest.approx(-abs(units) * (COST / 2) * 88.0, abs=1e-12)
    # 出场当天:按出场价 72 结算,双边成本 0.004 一次记完
    rv = units * (72.0 - 88.0) - abs(units) * COST * 88.0
    row = by_d[_day(242)]
    assert row["equity"] == pytest.approx(1.0 + rv, abs=1e-12)
    assert row["open_n"] == 0
    assert row["closed"] == 1
    # 成本是借记:若写成贷记(空头 units<0 会翻正),进场当天权益会高 2× 半场成本
    credit = 1.0 + units * (60.0 - 88.0) + abs(units) * (COST / 2) * 88.0
    assert row["equity"] < credit


def test_nav_skips_tickets_beyond_the_cap():
    """同时最多 10 张:先到先得,超额的记 skipped。"""
    tail = [SIG, (88.0, 95.0, 87.0, 88.0, 200_000.0)]
    rows = _series(tail)
    gate = {r["trade_date"]: (r["trade_date"] == _day(220)) for r in rows}
    bars = {f"S{i}": rows for i in range(12)}
    tk = run_short(bars, gate, _day(0), _day(len(rows)))
    assert len(tk) == 12
    curve = nav(tk, bars, f=RISK_FRAC, cap=CAP, d_to=_day(221))
    last = curve[-1]
    assert last["taken"] == 10 and last["skipped"] == 2


# ── ② 历史一致性(研究产物导出的那一段)─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def fx() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def fx_bars(fx) -> dict[str, list[dict]]:
    keys = ("trade_date", "open", "high", "low", "close", "volume")
    return {s: [dict(zip(keys, r)) for r in rows] for s, rows in fx["bars"].items()}


@pytest.fixture(scope="module")
def fx_gate(fx) -> dict[str, bool]:
    return gate_closed_by_day([{"d": d, "ret": r} for d, r in fx["gate"]])


@pytest.fixture(scope="module")
def fx_tickets(fx, fx_bars, fx_gate) -> list[dict]:
    return run_short(fx_bars, fx_gate, fx["meta"]["signal_from"], fx["meta"]["signal_to"])


def test_fixture_segment_is_big_enough(fx):
    """卡上验收:≥ 120 天、至少 10 张票。"""
    assert fx["meta"]["n_days"] >= 120
    assert fx["meta"]["n_tickets"] >= 10
    assert fx["meta"]["family"] == "S642"


def test_historical_tickets_match_the_research_book(fx, fx_tickets):
    got = fx_tickets
    want = fx["tickets"]
    assert len(got) == len(want), f"票数不同:{len(got)} vs {len(want)}"
    fields = ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px", "exit_px",
              "exit_reason", "bars_held")
    for g, w in zip(sorted(got, key=lambda t: (t["entry_d"], t["symbol"])),
                    sorted(want, key=lambda t: (t["entry_d"], t["symbol"]))):
        for f in fields:
            assert g[f] == w[f], f"{g['symbol']} {g['signal_d']} 字段 {f} 不同"


def test_historical_daily_nav_matches_the_family_curve(fx, fx_tickets, fx_bars):
    """逐日净值与族曲线(S642 段)逐位相同:相对差 ≤ 1e-9。"""
    curve = nav(fx_tickets, fx_bars, f=RISK_FRAC, cap=CAP, d_to=fx["meta"]["signal_to"])
    by_d = {r["d"]: r["equity"] for r in curve}
    assert len(fx["expected"]) >= 120
    worst = 0.0
    for d, expect in fx["expected"]:
        assert d in by_d, f"缺这一天:{d}"
        rel = abs(by_d[d] - expect) / max(1.0, abs(expect))
        worst = max(worst, rel)
    assert worst <= 1e-9, f"逐日净值最大相对差 {worst:.3e}"


def test_historical_cap_is_actually_binding(fx, fx_tickets, fx_bars):
    """这一段里有 cap 触顶日(同日进场超过 10 张 ⇒ 跳过),否则这段检验不到「跳过」口径。"""
    curve = nav(fx_tickets, fx_bars, f=RISK_FRAC, cap=CAP, d_to=fx["meta"]["signal_to"])
    assert max(r["open_n"] for r in curve) == CAP
    assert curve[-1]["skipped"] >= 1


# ── ③ 语法树:执行层不许 import 本模块 ────────────────────────────────────────────────────────
def test_execution_layer_does_not_import_this_module():
    targets = sorted((ROOT / "src" / "data" / "execution").rglob("*.py"))
    targets.append(ROOT / "src" / "api" / "routers" / "executor.py")
    assert targets, "找不到执行层的文件"
    for path in targets:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "s642_short" not in alias.name, f"{path} import 了本模块"
            elif isinstance(node, ast.ImportFrom):
                assert "s642_short" not in (node.module or ""), f"{path} import 了本模块"


def test_excluded_symbols_are_not_traded():
    assert EXCL == {"USDC", "BTCDOM", "DEFI"}
