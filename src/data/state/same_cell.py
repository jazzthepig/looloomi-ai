"""今天这一格在历史上长什么样(台账 S-864;T-369 ⑫)—— 「状态 + 历史相似状态」的最低配。**只描述。**

每一天按四个轴分格(只用当天及以前的数据):

    R 利率        2 年期收益率 − 91 天前的读数 > 0 ⇒ 升,否则 降
    L 边际流动性   稳定币 30 日供应变化 < 0 ⇒ 抽,否则 注
    W 周线结构     周日收盘 < 10 周均线(含本周)且 < 4 周前 ⇒ 坏(下周一起生效)
    T 趋势        面板离 200 日线 < 0 ⇒ 线下,否则 线上

然后报今天这一格:历史上有几段、几天,之后 30 天 BTC 的中位与 ±10% 的占比,全样本的同一组数,以及**循环平移对照**的 p。

为什么有后两样:11-12 / 11-13 两次回看都把最大的权重给了「磨 / 收回」,用的锚不分利率与流动性状态;一张不带
独立段数与对照的「同格历史」表,是事后拟合的入口。S-864 实测(2026-11-13):今天这一格 12 段 / 257 天,
30 天中位 +0.3%、涨超 10% 的 14%(全样本 32%)、跌超 10% 的 28%(全样本 20%),p = 0.15 —— 是「不涨」,不是「必跌」,
而且与随机平移分不开。**所以这一栏进档案的规矩写死在 `summary` 里:不足 `MIN_EPISODES` 段不给数字;p 永远写出来。**

S-866(B 道盲复算,只按四条定义从零写):16 格的天数与段数逐格一致,BTC 的每个数对上。两处随之写进这里:
① **「双侧 p」有两种算法,落在同一条线的两边** —— 登记的那一种(离平移均值的距离)0.15,B 道用的(两倍较小的单尾)0.08。
   两个都报;「分得开」要两个都过 `P_LINE`(S-866 事前写的线:0.05)。只报顺眼的那一个,就是在挑。
② **同一批格子上的 ETH / SOL**(Jazz 11-13:这套读法不只看 BTC):并排列,各带自己的 p;不下「适用 / 不适用」的结论。

不进规则、不动敞口、不改 ③ 的概率臂。研究脚本 `docs/research/s864_same_cell.py` 与这里是同一套定义,
`tests/test_same_cell.py` 在合成数据上逐格对两边。
"""
from __future__ import annotations

import asyncio
import bisect
import datetime as dt
from typing import Any, Optional

import numpy as np

from src.data.evaluation.apparatus import p_two_sided_deviation, p_two_sided_tail

CODE_REF = "same_cell v1.1 (S-864 / S-866: 2y vs 91d ago × stable supply 30d × weekly structure × panel vs 200d; 30d forward for BTC + ETH / SOL on the same cells; circular-shift control, two two-sided p definitions)"
AXES = ("R", "L", "W", "T")
NAMES = {"R": ("升", "降"), "L": ("抽", "注"), "W": ("坏", "没坏"), "T": ("线下", "线上")}
WORDS = {"R升": "利率升", "R降": "利率降", "L抽": "稳定币抽", "L注": "稳定币注", "W坏": "周线坏", "W没坏": "周线没坏", "T线下": "线下", "T线上": "线上"}
HORIZON = 30
BIG = 0.10
GAP_MERGE_D = 5
HOLDOUT_D = 56                  # 与研究脚本一致:最后 56 天的结果还没发生,不进统计
RATE_LAG_D = 91
RATE_MAX_AGE_D = 7
N_SHIFT = 2000
MIN_SHIFT_D = 180
SEED = 864
MIN_EPISODES = 3
P_LINE = 0.05                   # S-866 事前写的线:p < 0.05 才许说「分得开」
OTHERS = ("ETH", "SOL")         # 同一批格子上并排看的资产(S-866 ②)
START = dt.date(2019, 1, 1)


def _asof(dates: list, vals: list, d: dt.date, max_age: int) -> Optional[float]:
    i = bisect.bisect_right(dates, d) - 1
    return vals[i] if i >= 0 and (d - dates[i]).days <= max_age else None


def weekly_down(days: list, close: dict) -> dict:
    """每个周日判一次:收盘 < 10 周均线(含本周)且 < 4 周前;结论从下周一起生效到下一个周日。"""
    suns = [d for d in days if d.weekday() == 6 and d in close]
    flag, out = {}, {}
    for i, d in enumerate(suns):
        if i >= 9:
            w = [close[x] for x in suns[i - 9:i + 1]]
            flag[d] = bool(close[d] < sum(w) / 10 and close[d] < close[suns[i - 4]])
    cur = None
    for d in days:
        prev_sun = d - dt.timedelta(days=(d.weekday() + 1) % 7 or 7)      # 严格早于 d 的最近一个周日
        cur = flag.get(prev_sun, cur if prev_sun not in flag else None)
        out[d] = cur
    return out


def cells(days: list, close: dict, dist200: dict, stable: dict, y2_d: list, y2_v: list) -> dict:
    """每一天 → 'R升|L抽|W坏|T线下';任何一轴读不到 ⇒ 这一天没有格子。"""
    wd = weekly_down(days, close)
    out = {}
    for d in days:
        y_now = _asof(y2_d, y2_v, d, RATE_MAX_AGE_D)
        y_ago = _asof(y2_d, y2_v, d - dt.timedelta(days=RATE_LAG_D), RATE_MAX_AGE_D)
        st, di, w = stable.get(d), dist200.get(d), wd.get(d)
        if None in (y_now, y_ago, st, di, w):
            continue
        flags = {"R": y_now > y_ago, "L": st < 0, "W": bool(w), "T": di < 0}
        out[d] = "|".join(a + NAMES[a][0 if flags[a] else 1] for a in AXES)
    return out


def episodes(days_in: list) -> list[list]:
    eps, cur = [], []
    for d in days_in:
        if cur and (d - cur[-1]).days > GAP_MERGE_D:
            eps.append(cur)
            cur = []
        cur.append(d)
    return eps + ([cur] if cur else [])


def _describe(r: np.ndarray) -> dict:
    return {"n_days": int(len(r)), "median": round(float(np.median(r)), 4), "mean": round(float(r.mean()), 4),
            "p_down_big": round(float((r < -BIG).mean()), 3), "p_up_big": round(float((r > BIG).mean()), 3)}


def _shift_p(lab: np.ndarray, rets: np.ndarray, stat) -> Optional[dict]:
    """循环平移对照:标签整条平移 k 天(k ≥ 180),收益不动。返回两种双侧 p ——
    `dev` = 离平移均值至少这么远的占比(S-864 登记的那一种);`tail2` = 两倍较小的单尾(S-866 B 道独立选的那一种)。
    平移分布右偏时两者差得不小(BTC 今天这一格:0.15 对 0.08)⇒ 两个都报。

    11-17 T-388:两个 p 改调 apparatus 里各自有名的那两个函数(`p_two_sided_deviation` /
    `p_two_sided_tail`),算法与数字与之前逐位相同 —— 登记在台账里的 0.149 / 0.082 不许因为重构悄悄变。
    预注册以后写函数名,不写「双侧 p」。"""
    n = len(lab)
    if lab.sum() < 5 or n <= 2 * MIN_SHIFT_D + 1:
        return None
    rng = np.random.default_rng(SEED)
    obs = stat(rets[lab])
    sims = np.array([stat(rets[np.roll(lab, int(k))]) for k in rng.integers(MIN_SHIFT_D, n - MIN_SHIFT_D, N_SHIFT)])
    dev = p_two_sided_deviation(obs, sims)
    tail2 = p_two_sided_tail(obs, sims)
    return {"dev": None if dev is None else round(dev, 4), "tail2": None if tail2 is None else round(tail2, 4)}


def _other(name: str, c2: dict, days: list, idx: dict, usable: list, cell: dict, target: str) -> dict:
    """同一批格子、换一只资产的收盘:这一格之后 30 天的分布 + 它自己的全样本 + 它自己的平移对照。"""
    f2 = {}
    for d in usable:
        a, b = c2.get(d), c2.get(days[idx[d] + HORIZON])
        if a and b:
            f2[d] = b / a - 1
    u2 = [d for d in usable if d in f2]
    in2 = [d for d in u2 if cell[d] == target]
    eps = episodes(in2)
    if len(eps) < MIN_EPISODES:
        return {"status": "thin", "n_days": len(in2), "n_episodes": len(eps)}
    r2 = np.array([f2[d] for d in u2])
    lab2 = np.array([cell[d] == target for d in u2])
    p = _shift_p(lab2, r2, lambda x: float(x.mean())) or {}
    return {"status": "ok", "n_days": len(in2), "n_episodes": len(eps), "d30": _describe(r2[lab2]), "uncond_d30": _describe(r2),
            "p_shift_mean": p.get("dev"), "p_shift_mean_tail2": p.get("tail2")}


def summary(days: list, close: dict, dist200: dict, stable: dict, y2_d: list, y2_v: list,
            others: Optional[dict] = None) -> dict[str, Any]:
    """纯函数。今天这一格的历史。读不出格子 / 样本不够 ⇒ 说清楚是哪一种,不给数字。
    `others` = {"ETH": {日: 收盘}, …}:格子不变(还是那四个轴),只把之后 30 天的收益换成这只资产的。"""
    days = [d for d in days if d >= START]
    cell = cells(days, close, dist200, stable, y2_d, y2_v)
    labelled = [d for d in days if d in cell]
    if not labelled:
        return {"status": "unreadable", "why": "四个轴没有一天同时读得到", "code_ref": CODE_REF}
    today = labelled[-1]
    idx = {d: i for i, d in enumerate(days)}
    fwd = {d: close[days[idx[d] + HORIZON]] / close[d] - 1 for d in days if idx[d] + HORIZON < len(days)}
    last_ok = days[len(days) - 1 - HOLDOUT_D] if len(days) > HOLDOUT_D else None
    usable = [d for d in labelled if last_ok is not None and d <= last_ok and d in fwd]
    target = cell[today]
    in_cell = [d for d in usable if cell[d] == target]
    eps = episodes(in_cell)
    out: dict[str, Any] = {"asof": today.isoformat(), "cell": target, "cell_words": "·".join(WORDS.get(x, x) for x in target.split("|")),
                           "n_days": len(in_cell), "n_episodes": len(eps), "horizon_d": HORIZON, "big_move": BIG,
                           "window": [usable[0].isoformat(), usable[-1].isoformat()] if usable else None, "code_ref": CODE_REF}
    if len(eps) < MIN_EPISODES:
        return {**out, "status": "thin", "why": f"这一格历史上只有 {len(eps)} 段,不足 {MIN_EPISODES} 段 —— 不给数字"}
    r_all = np.array([fwd[d] for d in usable])
    lab = np.array([cell[d] == target for d in usable])
    pm = _shift_p(lab, r_all, lambda x: float(x.mean())) or {}
    pd_ = _shift_p(lab, r_all, lambda x: float((x < -BIG).mean())) or {}
    both = [x for x in (pm.get("dev"), pm.get("tail2")) if x is not None]
    res = {**out, "status": "ok", "last_episode_start": eps[-1][0].isoformat(), "d30": _describe(r_all[lab]),
           "d30_by_episode_start": _describe(np.array([fwd[e[0]] for e in eps])), "uncond_d30": _describe(r_all),
           "p_shift_mean": pm.get("dev"), "p_shift_mean_tail2": pm.get("tail2"), "p_shift_down": pd_.get("dev"), "p_line": P_LINE,
           "separable": bool(len(both) == 2 and max(both) < P_LINE)}
    if others:
        res["others"] = {name: (_other(name, c2, days, idx, usable, cell, target) if c2 else {"status": "unreadable"})
                         for name, c2 in others.items()}
    return res


def _p(o: dict) -> str:
    """两种双侧 p 并排:登记的那一种在前。只有一种时只写一种。"""
    a, b = o.get("p_shift_mean"), o.get("p_shift_mean_tail2")
    return f"{a} / {b}" if b is not None else f"{a}"


def line(s: Optional[dict]) -> Optional[str]:
    """纯函数。⓪ 简报 / ③ 档案里的那一行。数字旁边永远带段数与对照的 p;样本不够就说不够。"""
    if not s:
        return None
    if s.get("status") == "unreadable":
        return f"  同格历史  读不到({s.get('why')})"
    # 这一格是哪一天的,必须印出来(11-17 T-388):档案头写的是「截至 <请求日>」,格子本身却可能是前一天的
    # —— 第一行真实数据(d = 11-14)就是 11-13 的格子(当时 stable_supply_30d 还没有 11-14 的值)。
    asof = s.get("asof")
    head = f"  同格历史  {s.get('cell_words')}:{s.get('n_episodes')} 段 / {s.get('n_days')} 天" + (f"(格子日 {asof})" if asof else "")
    if s.get("status") != "ok":
        return head + " —— 样本不足,不给数字"
    a, u = s["d30"], s["uncond_d30"]
    tail = ("与随机平移分得开" if s.get("separable") else "**与随机平移分不开**") + f"(p {_p(s)})"
    t = (head + f";之后 30 天 BTC 中位 {a['median'] * 100:+.1f}%、跌超 10% {a['p_down_big'] * 100:.0f}%、涨超 10% {a['p_up_big'] * 100:.0f}%"
         f"(全样本 {u['p_down_big'] * 100:.0f}% / {u['p_up_big'] * 100:.0f}%);" + tail)
    for name, o in (s.get("others") or {}).items():
        if o.get("status") != "ok":
            t += f";{name} " + ("读不到" if o.get("status") == "unreadable" else "样本不足")
            continue
        oa, ou = o["d30"], o["uncond_d30"]
        t += (f";{name} 中位 {oa['median'] * 100:+.1f}%、跌超 10% {oa['p_down_big'] * 100:.0f}%、涨超 10% {oa['p_up_big'] * 100:.0f}%"
              f"(全样本 {ou['p_down_big'] * 100:.0f}% / {ou['p_up_big'] * 100:.0f}%,p {_p(o)})")
    return t + ";只描述,不是预测"


async def read_and_summarise(d: str) -> dict[str, Any]:
    """读库(BTC + 两个状态特征 + 2 年期 + ETH / SOL)+ 在线程里算(平移是纯计算,不占事件循环)。
    BTC 或状态读不到 ⇒ 抛,由调用方记进 missing;ETH / SOL 读不到 ⇒ 只少那一只,不挡 BTC。"""
    from src.data.style.header import _read_all
    hi = d[:10]
    px = await _read_all("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                                         "and": f"(trade_date.gte.2018-09-01,trade_date.lte.{hi})", "order": "trade_date.asc"})
    feats: dict[str, dict] = {}
    for f in ("dist_200", "stable_supply_30d"):
        rows = await _read_all("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": f"eq.{f}",
                                               "and": f"(d.gte.{START.isoformat()},d.lte.{hi})", "order": "d.asc"})
        feats[f] = {dt.date.fromisoformat(str(r["d"])[:10]): float(r["value"]) for r in rows if r.get("value") is not None}
    y = await _read_all("macro_daily", {"select": "d,value", "series": "eq.ust_2y", "and": f"(d.gte.2018-06-01,d.lte.{hi})", "order": "d.asc"})
    y = [r for r in y if r.get("value") is not None]
    close = {dt.date.fromisoformat(str(r["trade_date"])[:10]): float(r["close"]) for r in px if r.get("close")}
    days = sorted(close)
    others: dict[str, dict] = {}
    for sym in OTHERS:
        try:
            rows = await _read_all("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{sym}", "source": "eq.binance_hist",
                                                   "and": f"(trade_date.gte.2018-09-01,trade_date.lte.{hi})", "order": "trade_date.asc"})
            others[sym] = {dt.date.fromisoformat(str(r["trade_date"])[:10]): float(r["close"]) for r in rows if r.get("close")}
        except Exception:                                                 # noqa: BLE001
            others[sym] = {}
    return await asyncio.to_thread(summary, days, close, feats["dist_200"], feats["stable_supply_30d"],
                                   [dt.date.fromisoformat(str(r["d"])[:10]) for r in y], [float(r["value"]) for r in y], others)
