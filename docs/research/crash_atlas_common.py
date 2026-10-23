"""崩盘图谱(crash atlas)共用内核 —— 台账 S-675,三道 T-184 / T-185 / T-186 都 import 这一份,不各写一版。

Jazz 10-23:「给每个市场崩盘(主流、EM、crypto)前的事件、迹象和情绪,还有对应的策略风格,做个挖掘」。

**这是挖掘,不是检验。** 崩盘之后回头找「崩之前都有什么」最容易自欺:每次崩盘前都能找到点什么。所以这里每个迹象都和
**基准率**比 —— 它在随便哪段时间里出现的频率 —— 并用**循环平移**(保留迹象自身的持续长度,只换时点)给出零分布。
挖出来的东西要当规则用,必须另立预注册、按前向判(S-675 原文)。

全部纯函数;数据由调用方读好传进来(FRED 快照在数据根 research/crash_atlas/fred/,`load_fred` 只是读文件)。
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
FRED_DIR = os.path.join(DATA_ROOT, "research", "crash_atlas", "fred")
SEED = 675


def load_fred(series_id: str, fred_dir: str = FRED_DIR) -> pd.Series:
    """FRED 快照 → 日期索引的浮点序列。FRED 的缺值是 '.' 或空,一律丢掉(不补 0)。"""
    df = pd.read_csv(os.path.join(fred_dir, f"{series_id}.csv"))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna().sort_index().rename(series_id)


# 经济数据的发布滞后(日历日):FRED 的日期是「所属期」,不是「哪天能看到」。S-675「低频序列按发布滞后后移」的唯一写法。
# 市场价格(指数、VIX、利率、汇率、利差)当天收盘就看得到 ⇒ 0。
#   NFCI    —— 日期是周五,下周三发布 ⇒ 5
#   STLFSI4 —— 日期是周五,下周四发布 ⇒ 6
#   WALCL   —— 日期是周三,周四发布 ⇒ 1
#   ICSA    —— 日期是周六(周末),下周四发布 ⇒ 5
#   UMCSENT —— 日期是当月 1 日,终值月底发布 ⇒ 31(协议:滞后 1 个月)
RELEASE_LAG_DAYS = {"NFCI": 5, "STLFSI4": 6, "WALCL": 1, "ICSA": 5, "UMCSENT": 31}


def available(s: pd.Series, series_id: Optional[str] = None) -> pd.Series:
    """把序列的日期从「所属期」挪到「能看到的那天」。不在表里的序列滞后 0(市场价格)。"""
    lag = RELEASE_LAG_DAYS.get(series_id or str(s.name), 0)
    out = s.copy()
    out.index = out.index + pd.Timedelta(days=lag)
    return out


def to_calendar(s: pd.Series, max_gap_days: int = 7) -> pd.Series:
    """非日频 / 只有交易日的序列 → 日历日序列,向前填,但最多填 max_gap_days 天(数据断了就是断了)。"""
    s = s.dropna().sort_index()
    idx = pd.date_range(s.index[0], s.index[-1], freq="D")
    return s.reindex(idx).ffill(limit=max_gap_days)


# ── 崩盘的定义(两档,S-675 写死)──────────────────────────────────────────────

def bear_episodes(price: pd.Series, threshold: float, rebound: Optional[float] = None) -> list[dict[str, Any]]:
    """熊市档 —— 牛 / 熊两态机(不是「创历史新高才算结束」:那样 NASDAQ 2000 年的高点 2015 年才回来,
    2007–09 就被吞进 2000 年那一段里了,10-23 实测)。
    牛市里盯「上一个谷底以来的最高点」;从它回撤 ≥ threshold ⇒ 熊市开始(peak_d = 那个最高点,break_d = 跌破门槛那天);
    熊市里盯最低点;从它反弹 ≥ rebound(默认 = threshold)⇒ 谷底确认(trough_d),回到牛市,最高点从这里重新算。平了高点也算新高(取最后一次)。
    depth = 谷底 / 前高 − 1;recover_d = 之后第一次回到前高的日子(没回到是 None);最后一段没确认谷底的 open = True;
    first_leg = 前高高于上一段的前高(新一轮的顶)—— 崩前迹象主要锚在这些段上,其余是熊市里反弹失败的后几段。"""
    rb = threshold if rebound is None else rebound
    p = price.dropna().sort_index()
    vals, idx = p.to_numpy(dtype=float), p.index
    out: list[dict[str, Any]] = []
    state, hi_i, lo_i, brk = "bull", 0, 0, None
    for i in range(1, len(vals)):
        v = vals[i]
        if state == "bull":
            if v >= vals[hi_i]:
                hi_i = i
            elif v / vals[hi_i] - 1.0 <= -threshold:
                state, lo_i, brk = "bear", i, i
        else:
            if v < vals[lo_i]:
                lo_i = i
            elif v / vals[lo_i] - 1.0 >= rb:
                out.append({"hi": hi_i, "lo": lo_i, "brk": brk, "open": False})
                state, hi_i = "bull", i
    if state == "bear":
        out.append({"hi": hi_i, "lo": lo_i, "brk": brk, "open": True})
    eps = []
    prev_peak = -np.inf
    for e in out:
        pk = vals[e["hi"]]
        first = bool(pk > prev_peak)          # 高于上一段的前高 = 新一轮的顶;否则是熊市里的反弹失败(2000–02 那几段)
        prev_peak = pk
        after = np.nonzero(vals[e["lo"]:] >= pk)[0]
        eps.append({"peak_d": idx[e["hi"]], "break_d": idx[e["brk"]], "trough_d": idx[e["lo"]],
                    "depth": vals[e["lo"]] / pk - 1.0,
                    "recover_d": idx[e["lo"] + after[0]] if len(after) else None, "open": e["open"],
                    "first_leg": first})
    return eps


def fast_crashes(price: pd.Series, window_days: int, threshold: float, decluster_days: int) -> list[dict[str, Any]]:
    """急跌档:日历日窗口 window_days 内跌 ≥ threshold。命中日 hit_d = 第一次满足的那天;
    之后 decluster_days 天内的命中算同一次(只留第一个)。start_d = hit_d − window_days(窗口起点,当作「急跌开始」)。"""
    p = price.dropna().sort_index()
    cal = to_calendar(p, max_gap_days=5)
    past = cal.shift(window_days)
    ret = cal / past - 1.0
    out: list[dict[str, Any]] = []
    last: Optional[pd.Timestamp] = None
    for d, r in ret.items():
        if pd.isna(r) or r > -threshold:
            continue
        if last is not None and (d - last).days <= decluster_days:
            continue
        out.append({"start_d": d - pd.Timedelta(days=window_days), "hit_d": d, "ret": float(r)})
        last = d
    return out


# ── 迹象:按时点的分位(不看未来)────────────────────────────────────────────

def expanding_pct(x: pd.Series, min_periods: int = 252) -> pd.Series:
    """当天的值在「到当天为止的全部历史」里的分位(0–1)。只用过去,不看未来。"""
    return x.expanding(min_periods=min_periods).rank(pct=True)


def _window_any(on: pd.Series, lookback_days: int) -> pd.Series:
    """日历日序列:d 这天之前 lookback_days 天(含 d)里迹象有没有亮过。缺值不算亮。"""
    b = pd.Series(on, dtype="boolean").fillna(False).astype(float)
    return b.rolling(lookback_days + 1, min_periods=1).max().astype(bool)


def sign_lift(on: pd.Series, anchors: Iterable[pd.Timestamp], lookback_days: int,
              n_shift: int = 2000, seed: int = SEED) -> dict[str, Any]:
    """一个迹象在崩盘锚点(前高日或破位日)之前 lookback_days 天内亮过的比例(命中率),
    对比它在随便哪一天之前 lookback_days 天内亮过的比例(基准率)。
    零分布:把迹象序列整体循环平移 k 天(k 在 [2L, N − 2L] 内随机),同样算命中率;分位 = 实际命中率在零分布里的位置。
    on:日历日布尔序列(先用 to_calendar 对齐);锚点早于迹象有数据 + lookback 的不算,单独报个数。"""
    on = on.sort_index()
    covered = on.notna()
    first_ok = on.index[covered.values.argmax()] + pd.Timedelta(days=lookback_days)
    win = _window_any(on, lookback_days)
    anc = [pd.Timestamp(a) for a in anchors]
    usable = [a for a in anc if first_ok <= a <= on.index[-1]]
    if not usable:
        return {"n_anchors": 0, "n_skipped": len(anc), "hit_rate": None, "base_rate": None, "lift": None,
                "null_p50": None, "pctile": None}
    pos = on.index.get_indexer(usable)
    if (pos < 0).any():  # 锚点不在序列索引上:get_indexer 给 −1,win.values[-1] 会静默读最后一格(T-185 发现)
        raise ValueError('sign_lift: 锚点不在迹象序列的索引上,先用 to_calendar 铺成日历日')
    hits = win.values[pos]
    hit_rate = float(hits.mean())
    base = win[win.index >= first_ok]
    base_rate = float(base.mean())
    vals = pd.Series(on, dtype="boolean").fillna(False).to_numpy(dtype=bool)
    n = len(vals)
    lo, hi = 2 * lookback_days, n - 2 * lookback_days
    rng = np.random.default_rng(seed)
    null = np.empty(n_shift)
    for i in range(n_shift):
        k = int(rng.integers(lo, hi)) if hi > lo else 0
        shifted = pd.Series(np.roll(vals, k), index=on.index)
        null[i] = _window_any(shifted, lookback_days).values[pos].mean()
    pctile = float((null < hit_rate).mean() + 0.5 * (null == hit_rate).mean())
    return {"n_anchors": len(usable), "n_skipped": len(anc) - len(usable), "hit_rate": hit_rate,
            "base_rate": base_rate, "lift": (hit_rate / base_rate) if base_rate > 0 else None,
            "null_p50": float(np.median(null)), "pctile": pctile}


# ── 策略风格:分阶段收益 ─────────────────────────────────────────────────────

def _at(level: pd.Series, d: pd.Timestamp) -> Optional[float]:
    s = level.dropna().sort_index()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if len(s) else None


def phase_returns(level: pd.Series, ep: dict[str, Any], pre_days: int = 60, post_days: int = 120) -> dict[str, Optional[float]]:
    """一条净值 / 价格序列在一次熊市里的三段收益:崩前(前高 − pre_days → 前高)、下跌(前高 → 谷底)、
    修复(谷底 → 谷底 + post_days)。数据不够的段是 None。"""
    pk, tr = pd.Timestamp(ep["peak_d"]), pd.Timestamp(ep["trough_d"])
    a, b, c = _at(level, pk - pd.Timedelta(days=pre_days)), _at(level, pk), _at(level, tr)
    e = _at(level, tr + pd.Timedelta(days=post_days)) if tr + pd.Timedelta(days=post_days) <= level.index.max() else None
    f = lambda x, y: (y / x - 1.0) if (x and y) else None  # noqa: E731
    return {"pre": f(a, b), "crash": f(b, c), "recovery": f(c, e)}


def trend_200_nav(price: pd.Series, cash_rate: Optional[pd.Series] = None) -> pd.Series:
    """趋势风格的参照:收盘 > 200 日均线就持有,否则持现金(cash_rate = 年化 %,按日计;没有就按 0)。
    t 天的仓位由 t−1 收盘决定,不看当天。返回净值(起点 1)。"""
    p = price.dropna().sort_index()
    ma = p.rolling(200, min_periods=200).mean()
    pos = (p > ma).shift(1, fill_value=False).astype(float)
    r = p.pct_change().fillna(0.0)
    cash = 0.0
    if cash_rate is not None:
        cr = cash_rate.reindex(p.index).ffill().fillna(0.0) / 100.0
        dt = p.index.to_series().diff().dt.days.fillna(1).values
        cash = (cr.values * dt / 365.0)
    nav_r = pos * r + (1 - pos) * cash
    return (1 + nav_r).cumprod()
