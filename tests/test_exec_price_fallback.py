"""T-426:执行计划的收盘价兜底(`EXEC_PRICE_FALLBACK`)。

**背景不是推演**:CoinGecko 订阅 2026-11-21 停了(12-01 恢复),`asset_mcap_daily` 从 11-20 起 0 行,
真钱执行计划(`host_plan.plan_core` → `tom_inputs`)从 11-20 起每轮都 `ok=False` ——
X1V 既不能回场、也拿不到新的止损线。兜底价源是库内的 `ohlcv_daily`(source=`binance_hist`)的日收盘。

**这个测试钉四件事**:
① **默认关 ⇒ 逐位相同** —— `EXEC_PRICE_FALLBACK` 不为 "1" 时,`tom_inputs` 的返回与 11-23 之前
   一模一样(逐位相同),而且**一次 `ohlcv_daily` 查询都不发**(不多打库、不多花时间)。
② **开 ⇒ 只补缺的那几天** —— 主源缺的日期用兜底源的真实 close 补上;主源已有的行**一个字节都不动**;
   补的值不是 0、不是前一日的值。每个日期的来源标在 `attrs["price_source_by_date"]` 里。
③ **变异测试必须红** —— 把兜底价乘 1.01,② 的"计划一致性"必须被打破(止损线差从 < 50bp 跳到 > 50bp)。
   一致性测试对兜底价敏感,才不是一句空话。
④ **不猜价** —— 兜底源自己缺的日子,宁可序列断在那里(下面 `test_gap_in_fallback_is_left_alone`)。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.execution import price_fallback as pf            # noqa: E402
from src.data.execution.host_plan import make_plan             # noqa: E402
from src.data.universe import forward_books as fb              # noqa: E402

# ── 假数据 ──────────────────────────────────────────────────────────────────
# 主源(CG)到 11-19 断;兜底源(binance_hist)到 11-22。crypto 7×24,每天都有行。
PRIMARY_LAST = "2026-11-19"
FALLBACK_LAST = "2026-11-22"
END = "2026-11-22"
HIST_FROM = "2026-03-01"


def _days(n: int) -> list[str]:
    d0 = pd.Timestamp(HIST_FROM)
    return [(d0 + pd.Timedelta(days=i)).date().isoformat() for i in range(n)]


def _price(d: str) -> float:
    """确定性价格:先涨后跌 —— 拐点 2026-11-11,最后几天是区间最低。

    形状是刻意的:灾难止损线 = 前 20 日最低收盘 × 0.92,要让它**落在兜底补上的那几天里**
    (11-20…11-22),一致性断言才对兜底价敏感(否则止损线取的是主源里的老价,变异杀不死)。
    """
    i = (pd.Timestamp(d) - pd.Timestamp(HIST_FROM)).days
    if i <= 255:
        return 100.0 + i * 0.1
    return 125.0 - (i - 255) * 1.0


class FakeDB:
    """替掉 `world50_book._get_all`。记录每个查询的 tail,便于断言"没有多打库"。"""

    def __init__(self, cg_last: str = PRIMARY_LAST, bh_last: str = FALLBACK_LAST,
                 bh_scale: float = 1.0, bh_gap: str | None = None):
        self.cg_last, self.bh_last, self.bh_scale, self.bh_gap = cg_last, bh_last, bh_scale, bh_gap
        self.calls: list[str] = []

    def _sym(self, tail: str) -> str:
        for part in tail.split("&"):
            if part.startswith("symbol=eq."):
                return part[len("symbol=eq."):]
        return ""

    def _le(self, tail: str, key: str) -> str | None:
        for part in tail.split("&"):
            if part.startswith(f"{key}=lte."):
                return part.split("=", 1)[1][len("lte."):]
        return None

    async def __call__(self, tail: str) -> list[dict]:
        self.calls.append(tail)
        le = self._le(tail, "d") or self._le(tail, "trade_date") or END
        sym = self._sym(tail)
        if "asset_mcap_daily" in tail:
            return [{"d": d, "price": _price(d)} for d in _days(400)
                    if d <= self.cg_last and d <= le]
        if "ohlcv_daily" in tail:
            out = []
            for d in _days(400):
                if d > self.bh_last or d > le:
                    continue
                if self.bh_gap and d == self.bh_gap:
                    continue
                out.append({"trade_date": d, "close": _price(d) * self.bh_scale})
            return out
        if "multiplier_daily" in tail:
            return [{"d": d, "nav": 1000.0} for d in _days(400) if d <= le]
        if "funding_history" in tail:
            return []
        return []


def _patch(monkeypatch, db: FakeDB):
    monkeypatch.setattr("src.data.universe.world50_book._get_all", db)


def _tom(end: str = END) -> tuple[dict, dict]:
    return asyncio.run(fb.tom_inputs(end))


def _closes_plan(closes: dict, asof: str) -> dict:
    """给 make_plan 用的 closes(截到 asof)。"""
    out = {}
    for k, s in closes.items():
        s2 = s[s.index <= pd.Timestamp(asof)]
        if len(s2):
            out[k] = s2
    return out


# ── ① 默认关 ────────────────────────────────────────────────────────────────

def test_off_by_default_returns_identical_and_asks_nothing_extra(monkeypatch):
    """关 ⇒ 与今天逐位相同,且不发一次 ohlcv_daily 查询。"""
    monkeypatch.delenv("EXEC_PRICE_FALLBACK", raising=False)
    db = FakeDB()
    _patch(monkeypatch, db)
    closes, _fund = _tom()
    assert db.calls, "根本没查到库 —— 测试自己坏了"
    assert not any("ohlcv_daily" in c for c in db.calls), "关着的时候不许多打一次库"
    assert closes["BTC"].index[-1].date().isoformat() == PRIMARY_LAST
    assert closes["ETH"].index[-1].date().isoformat() == PRIMARY_LAST
    # 逐位:每个值都等于主源的值
    for d, v in zip(closes["BTC"].index, closes["BTC"].values):
        assert v == pytest.approx(_price(d.date().isoformat()))
    assert "price_source_by_date" not in closes["BTC"].attrs


def test_off_is_the_default_even_when_env_is_garbage(monkeypatch):
    """值不等于 "1" 一律当关(不猜用户的意图)。"""
    for val in ("0", "", "true", "yes", "11"):
        monkeypatch.setenv("EXEC_PRICE_FALLBACK", val)
        assert pf.fallback_enabled() is False


# ── ② 开:只补缺的那几天 ─────────────────────────────────────────────────────

def test_on_takes_over_only_missing_days_and_marks_source(monkeypatch):
    monkeypatch.setenv("EXEC_PRICE_FALLBACK", "1")
    db = FakeDB()
    _patch(monkeypatch, db)
    closes, _fund = _tom()
    btc = closes["BTC"]
    assert btc.index[-1].date().isoformat() == FALLBACK_LAST, "序列没有连续到 end"
    src = btc.attrs["price_source_by_date"]
    for d in ("2026-11-20", "2026-11-21", "2026-11-22"):
        assert src[d] == "binance_hist"
    for d in ("2026-11-18", "2026-11-19"):
        assert src[d] == "asset_mcap_daily"
    # 主源有的行一个字节都没动
    for d in ("2026-11-18", "2026-11-19"):
        v = btc[pd.Timestamp(d)]
        assert float(v) == pytest.approx(_price(d))
    # 补上去的值是兜底源的真实 close —— 不是 0,不是前一日的值
    for d in ("2026-11-20", "2026-11-21", "2026-11-22"):
        v = float(btc[pd.Timestamp(d)])
        assert v == pytest.approx(_price(d))
        assert v != 0.0
        prev_day = (pd.Timestamp(d) - pd.Timedelta(days=1)).date().isoformat()
        assert float(btc[pd.Timestamp(prev_day)]) != v
    assert any("ohlcv_daily" in c for c in db.calls)


def test_on_leaves_alone_a_symbol_whose_primary_is_current(monkeypatch):
    """主源已经跟到 end 的币 —— 一个字节都不动(不接管)。"""
    monkeypatch.setenv("EXEC_PRICE_FALLBACK", "1")
    db = FakeDB(cg_last=FALLBACK_LAST, bh_last=FALLBACK_LAST)
    _patch(monkeypatch, db)
    closes, _fund = _tom()
    assert closes["BTC"].index[-1].date().isoformat() == FALLBACK_LAST
    assert "price_source_by_date" not in closes["BTC"].attrs


def test_gap_in_fallback_is_left_alone(monkeypatch):
    """兜底源自己缺的那天 —— 宁可序列断在那里,也不填 0、不填前一日。"""
    monkeypatch.setenv("EXEC_PRICE_FALLBACK", "1")
    db = FakeDB(bh_gap="2026-11-21")
    _patch(monkeypatch, db)
    closes, _fund = _tom()
    btc = closes["BTC"]
    days = [d.date().isoformat() for d in btc.index]
    assert "2026-11-21" not in days, "不该凭空多一天"
    assert "2026-11-20" in days and "2026-11-22" in days
    src = btc.attrs["price_source_by_date"]
    assert "2026-11-21" not in src
    assert float(btc[pd.Timestamp("2026-11-20")]) == pytest.approx(_price("2026-11-20"))


# ── ③ 计划一致性 + 变异必须红 ───────────────────────────────────────────────

def _plans(monkeypatch, bh_scale: float) -> dict:
    """跑两遍:一遍兜底价取真实 binance 值,一遍把兜底价换成'完美值'(= 主源曲线)。"""
    monkeypatch.setenv("EXEC_PRICE_FALLBACK", "1")
    db = FakeDB(bh_scale=bh_scale)
    _patch(monkeypatch, db)
    closes, _fund = _tom()
    real = make_plan(_closes_plan(closes, END), END)

    # 参照:同一批日期,但兜底价 = 主源曲线(= 兜底完全正确时的样子)
    ref_closes = {}
    for k, s in closes.items():
        if k == "CORE":
            ref_closes[k] = s
            continue
        vals = []
        for d in s.index:
            ds = d.date().isoformat()
            src = s.attrs.get("price_source_by_date", {}).get(ds)
            vals.append(_price(ds) if src == "binance_hist" else float(s[d]))
        ref_closes[k] = pd.Series(vals, index=s.index)
    ref = make_plan(_closes_plan(ref_closes, END), END)
    return {"real": real, "ref": ref}


def _stop_gap_bp(a: dict, b: dict) -> float:
    worst = 0.0
    for k in a["stop_px"]:
        x, y = a["stop_px"].get(k), b["stop_px"].get(k)
        if x is None or y is None:
            continue
        worst = max(worst, abs(x / y - 1.0) * 1e4)
    return worst


def test_fallback_plan_matches_perfect_fallback(monkeypatch):
    """兜底价取真实 binance close ⇒ 计划与'完美兜底'一致:目标逐位相同,止损线差 < 50bp。"""
    out = _plans(monkeypatch, bh_scale=1.0)
    real, ref = out["real"], out["ref"]
    assert real["targets"] == ref["targets"], "目标权重必须逐位相同"
    gap = _stop_gap_bp(real, ref)
    assert gap < 50.0, f"止损线差 {gap:.2f}bp 太大(阈值 50bp)"


def test_mutation_must_break_the_consistency_check(monkeypatch):
    """变异:兜底价 × 1.01 ⇒ 一致性必须被打破(否则 ③ 那个断言是空话)。"""
    out = _plans(monkeypatch, bh_scale=1.01)
    gap = _stop_gap_bp(out["real"], out["ref"])
    assert gap > 50.0, f"变异没被杀死:止损线只差 {gap:.2f}bp —— 一致性测试对兜底价不敏感"


# ── ④ 纯函数层 ──────────────────────────────────────────────────────────────

def test_merge_missing_never_overwrites_primary():
    merged, src = pf.merge_missing({"2026-11-19": 100.0}, {"2026-11-19": 999.0, "2026-11-20": 101.0})
    assert merged["2026-11-19"] == 100.0, "主源的值不许被覆盖"
    assert merged["2026-11-20"] == 101.0
    assert src["2026-11-19"] == "asset_mcap_daily"
    assert src["2026-11-20"] == "binance_hist"


def test_last_takeover_records_which_days():
    pf._LAST.update({"enabled": False, "symbols": {}})
    assert pf.last_takeover()["enabled"] is False
