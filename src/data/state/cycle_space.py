"""周期位置空间(11-11,S-814)—— 「过热 / 过冷」不用两三个阈值判,放回向量空间里问:今天在周期的哪里,历史上最像今天的那些日子之后怎么走。

## 为什么(Jazz 11-11「we should keep in high dimension to work things out」)

同一天交回来的三份阈值规则说明了低维的毛病:S-811 / S-812(离 200 日线 + 资金费的扩张分位)七年只触发 **1 轮**过热;
S-813 修订(恐惧贪婪 ≥ 95 武装 + 动量扳机)也只有 1 轮,而且那一轮在 3.1 万做空、涨到 6.4 万。阈值把「有多像」压成 0 / 1,
稀有事件就只剩一两个样本。向量空间给每一天一个**分级的相似度**:十五年、四轮周期里的每一天都参与回答。

## 空间(8 维,全部只用 ≤ d 的数据;没测到 = None,**不补 0**,距离只在两天都有的维上算)

    mvrv      ln(市值 / 已实现市值)                  puell     ln(矿工日收入 / 其 365 日均值)
    hash_30d  算力 30 天变化                           dist_200  ln(价格 / 200 日均价)
    ret_365   过去 365 天对数收益                       dd_ath    距历史最高价的回撤
    vol_90    90 天已实现波动(日对数收益标准差)        fng_30    恐惧贪婪 30 日均值(2018-02 起;之前这一维不存在)

来源:`macro_daily` 的 btc_mvrv / btc_puell / btc_hash_30d / btc_price_usd(`market/btc_cycle`,2011 起)与 fng。
每一维按时点标准化:只用**严格更早**的值算均值 / 标准差(至少 `MIN_HIST` 天),截到 ±6。

## 读法

`analogs`:结果已经出来的历史日(≤ d − 181 天)里距离最近的 `K` 个;`read`:它们之后 180 天的涨跌分布(跌超 20% / 涨超 25% 的比例),
按**独立段数**(相邻近邻相差 ≥ 90 天才算新一段)向无条件频率收缩;`stance`:相对无条件频率的倾斜够大、且至少 3 段独立历史 ⇒
add(过冷,加现货)/ trim(过热,减现货)/ hold。**只描述**:S-814 判它值不值得进配置;在那之前不进任何敞口。

## 回路(decision → scenario → score)

`run_once` 每周一次把今天的三档概率写进 `scenario_ledger`(作者 `seth:cycle-space`,`close:BTC`,结算日 d + 180),到期按 Brier 结算 ——
和 ③ 每日决定的三条臂同一本记分账。读面 `/internal/cycle-space`。
判活:`select d, statement, prob from scenario_ledger where author = 'seth:cycle-space' order by d desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import deque
from typing import Any, Optional

DIMS = ("mvrv", "puell", "hash_30d", "dist_200", "ret_365", "dd_ath", "vol_90", "fng_30")
SERIES = ("btc_price_usd", "btc_mvrv", "btc_puell", "btc_hash_30d", "fng")
MIN_HIST = 730
MIN_SHARED = 5
K = 60
HORIZON_D = 180
EPISODE_GAP_D = 90
DOWN, UP = -0.20, 0.25              # 对数上对称:ln 0.8 = −ln 1.25
SHRINK_M = 3.0                      # 向无条件频率收缩:权重 = 段数 /(段数 + 3)
TILT_ON = 0.25                      # 相对无条件频率的倾斜(p_up − p_down 之差)
MIN_EPISODES = 3
W_BASE, W_ADD, W_TRIM = 0.70, 1.00, 0.35
AUTHOR = "seth:cycle-space"
CODE_REF = "cycle_space v1 (11-11, S-814)"
WEEK_KEY = "cycle_space:last_scenario_d"
WRITES_TABLES = ("scenario_ledger",)


def _shift(d: str, days: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=days)).isoformat()


def features(price: dict[str, float], mvrv: dict[str, float], puell: dict[str, float], hash30: dict[str, float],
             fng: dict[str, float]) -> dict[str, list[Optional[float]]]:
    """纯函数。{d: 值} 的五条序列 → {d: 8 维原始特征};每一天只用它当天及以前的值。价格有缺口的窗口 ⇒ 该维 None。"""
    days = sorted(d for d, p in price.items() if p and p > 0)
    out: dict[str, list[Optional[float]]] = {}
    last200: deque = deque(maxlen=200)
    lr90: deque = deque(maxlen=90)
    fng30: deque = deque(maxlen=30)
    run_max, prev_d, prev_p = 0.0, None, None
    for d in days:
        p = float(price[d])
        cont = prev_d is not None and _shift(prev_d, 1) == d
        if not cont:                                   # 日历断了 ⇒ 滚动窗口重来(不拿跨缺口的值凑数)
            last200.clear()
            lr90.clear()
        elif prev_p:
            lr90.append(math.log(p / prev_p))
        last200.append(p)
        run_max = max(run_max, p)
        f = fng.get(d)
        if f is not None:
            fng30.append((d, float(f)))
        recent_f = [v for (x, v) in fng30 if x > _shift(d, -30)]
        p365 = price.get(_shift(d, -365))
        m, pu = mvrv.get(d), puell.get(d)
        out[d] = [math.log(m) if m and m > 0 else None,
                  math.log(pu) if pu and pu > 0 else None,
                  hash30.get(d),
                  math.log(p / (sum(last200) / 200)) if len(last200) == 200 else None,
                  math.log(p / p365) if p365 and p365 > 0 else None,
                  p / run_max - 1.0,
                  statistics.pstdev(lr90) if len(lr90) == 90 else None,
                  sum(recent_f) / len(recent_f) if len(recent_f) >= 20 else None]
        prev_d, prev_p = d, p
    return out


def pit_vectors(feats: dict[str, list[Optional[float]]]) -> dict[str, list[Optional[float]]]:
    """纯函数。原始特征 → 按时点 z:每一维只用严格更早的值(Welford),不足 MIN_HIST 天 ⇒ None;截到 ±6。"""
    stats = [[0, 0.0, 0.0] for _ in DIMS]
    out: dict[str, list[Optional[float]]] = {}
    for d in sorted(feats):
        vec: list[Optional[float]] = []
        for i, x in enumerate(feats[d]):
            n, mu, m2 = stats[i]
            z = None
            if x is not None and math.isfinite(x) and n >= MIN_HIST:
                sd = math.sqrt(m2 / (n - 1)) if n > 1 else 0.0
                z = (x - mu) / sd if sd > 0 else None
            vec.append(None if z is None else round(max(-6.0, min(6.0, z)), 4))
            if x is not None and math.isfinite(x):          # 当天的值在算完当天的 z 之后才进统计
                n += 1
                d1 = x - mu
                mu += d1 / n
                m2 += d1 * (x - mu)
                stats[i] = [n, mu, m2]
        out[d] = vec
    return out


def distance(a: list[Optional[float]], b: list[Optional[float]]) -> Optional[float]:
    """纯函数。两天都有值的维上的欧氏距离,按 √(D / 共有维数) 放大;共有维 < MIN_SHARED ⇒ None(不比)。"""
    sq, n = 0.0, 0
    for x, y in zip(a, b):
        if x is not None and y is not None:
            sq += (x - y) ** 2
            n += 1
    return math.sqrt(sq * len(DIMS) / n) if n >= MIN_SHARED else None


def analogs(vectors: dict[str, list[Optional[float]]], d: str, k: int = K, horizon: int = HORIZON_D) -> list[tuple[float, str]]:
    """纯函数。结果已出的历史日(≤ d − horizon − 1)里最近的 k 个:(距离, 日期) 升序。今天的向量不够维 ⇒ []。"""
    today = vectors.get(d)
    if not today or sum(x is not None for x in today) < MIN_SHARED:
        return []
    cutoff = _shift(d, -(horizon + 1))
    cand = []
    for s, v in vectors.items():
        if s > cutoff:
            continue
        dist = distance(today, v)
        if dist is not None:
            cand.append((dist, s))
    return sorted(cand)[:k]


def episodes(dates: list[str], gap: int = EPISODE_GAP_D) -> int:
    """纯函数。近邻日期里的独立段数:排序后与上一个相差 ≥ gap 天才算新一段(150 个挤在同一个月的近邻 = 1 个样本)。"""
    n, prev = 0, None
    for s in sorted(dates):
        if prev is None or (dt.date.fromisoformat(s) - dt.date.fromisoformat(prev)).days >= gap:
            n += 1
        prev = s
    return n


def _fwd(price: dict[str, float], s: str, horizon: int) -> Optional[float]:
    a, b = price.get(s), price.get(_shift(s, horizon))
    return b / a - 1.0 if a and b and a > 0 else None


def read(vectors: dict[str, list[Optional[float]]], price: dict[str, float], d: str, k: int = K,
         horizon: int = HORIZON_D) -> dict[str, Any]:
    """纯函数。今天的周期读数:近邻之后 horizon 天的分布、无条件频率(同样只用结果已出的日子)、收缩后的三档概率与倾斜。"""
    near = analogs(vectors, d, k, horizon)
    cutoff = _shift(d, -(horizon + 1))
    allf = [f for s in vectors if s <= cutoff and (f := _fwd(price, s, horizon)) is not None]
    if not allf:
        return {"ok": False, "why": "还没有结果已出的历史日"}
    base = {"down": sum(f <= DOWN for f in allf) / len(allf), "up": sum(f >= UP for f in allf) / len(allf)}
    fw = [(s, f) for _, s in near if (f := _fwd(price, s, horizon)) is not None]
    if not fw:
        return {"ok": False, "why": "今天的向量不够维,或没有可比的历史日", "base": base}
    vals = sorted(f for _, f in fw)
    raw = {"down": sum(f <= DOWN for f in vals) / len(vals), "up": sum(f >= UP for f in vals) / len(vals)}
    ep = episodes([s for s, _ in fw])
    w = ep / (ep + SHRINK_M)
    p = {kk: w * raw[kk] + (1 - w) * base[kk] for kk in ("down", "up")}
    p["flat"] = max(0.0, 1.0 - p["down"] - p["up"])
    return {"ok": True, "d": d, "n": len(vals), "episodes": ep, "median": vals[len(vals) // 2],
            "p20": vals[int(0.2 * (len(vals) - 1))], "p80": vals[int(0.8 * (len(vals) - 1))],
            "raw": raw, "base": base, "probs": p,
            "tilt_excess": (p["up"] - p["down"]) - (base["up"] - base["down"]),
            "nearest": [{"d": s, "dist": round(dist, 3), "fwd": _fwd(price, s, horizon)} for dist, s in near[:5]],
            "span": [min(s for s, _ in fw), max(s for s, _ in fw)]}


def stance(r: dict[str, Any]) -> str:
    """纯函数。add(过冷:历史上像今天的日子之后明显好于平常)/ trim(过热)/ hold。段数不够 ⇒ hold。"""
    if not r.get("ok") or r.get("episodes", 0) < MIN_EPISODES:
        return "hold"
    t = r["tilt_excess"]
    return "add" if t >= TILT_ON else "trim" if t <= -TILT_ON else "hold"


def target_weight(s: str) -> float:
    return {"add": W_ADD, "trim": W_TRIM}.get(s, W_BASE)


def scenario_entries(d: str, close: float, probs: dict[str, float]) -> list[dict]:
    """纯函数。三条 180 天情景(与 ③ 日决定同一本记分账;阈值 = 当天参考价的 0.8 / 1.25 倍)。"""
    h = _shift(d, HORIZON_D)
    lo, hi = round(close * (1 + DOWN), 2), round(close * (1 + UP), 2)
    base = {"scenario": f"周期位置空间 {d}", "variable": "close:BTC", "horizon_d": h, "code_ref": CODE_REF}
    return [{**base, "id": f"C-{d}-down", "statement": f"BTC {h} 收盘 < {lo}(较 {d} 跌超 20%)", "op": "lt", "hi": lo, "prob": round(probs["down"], 4)},
            {**base, "id": f"C-{d}-flat", "statement": f"BTC {h} 收盘在 {lo}–{hi}", "op": "between", "lo": lo, "hi": hi, "prob": round(probs["flat"], 4)},
            {**base, "id": f"C-{d}-up", "statement": f"BTC {h} 收盘 > {hi}(较 {d} 涨超 25%)", "op": "gt", "lo": hi, "prob": round(probs["up"], 4)}]


async def load(read_all=None) -> tuple[dict[str, list[Optional[float]]], dict[str, float]]:
    """读五条序列 → (按时点向量, 价格)。读不到就抛(读不到 ≠ 没有)。"""
    if read_all is None:
        from src.data.style.header import _read_all as read_all
    rows = await read_all("macro_daily", {"select": "series,d,value", "series": f"in.({','.join(SERIES)})", "order": "d.asc,series.asc"})
    by: dict[str, dict[str, float]] = {s: {} for s in SERIES}
    for r in rows or []:
        if r.get("value") is not None and r.get("series") in by:
            by[r["series"]][str(r["d"])[:10]] = float(r["value"])
    price = by["btc_price_usd"]
    if len(price) < MIN_HIST + HORIZON_D:
        raise RuntimeError(f"btc_price_usd 只有 {len(price)} 天 —— btc_cycle 还没回填?")
    feats = features(price, by["btc_mvrv"], by["btc_puell"], by["btc_hash_30d"], by["fng"])
    return pit_vectors(feats), price


async def view(read_all=None) -> dict[str, Any]:
    """今天的周期读数(`/internal/cycle-space`)。"""
    vectors, price = await load(read_all)
    d = max(price)
    r = read(vectors, price, d)
    s = stance(r)
    return {**r, "d": d, "close": price[d], "stance": s, "target_weight": target_weight(s), "vector": dict(zip(DIMS, vectors.get(d) or [])),
            "caveat": "只描述:历史相似日之后 180 天的分布,不是预测;S-814 判定前不进任何敞口"}


async def run_once(now: Optional[dt.datetime] = None, *, force: bool = False) -> dict[str, Any]:
    """每周一次把今天的三档概率写进情景记分账(第一次立刻写)。读数算不出 ⇒ 不写,说明原因。"""
    from src.api.store import redis_get_key_status, redis_set_key
    from src.data.evaluation.scenario_ledger import submit
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    v = await view()
    out = {"ok": True, "d": v.get("d"), "stance": v.get("stance"), "episodes": v.get("episodes"),
           "tilt_excess": round(v["tilt_excess"], 4) if v.get("ok") else None, "probs": v.get("probs")}
    if not v.get("ok"):
        return {**out, "written": 0, "why": v.get("why")}
    last, _st = await redis_get_key_status(WEEK_KEY)
    last_d = (last or {}).get("d")
    if not force and last_d and (dt.date.fromisoformat(v["d"]) - dt.date.fromisoformat(last_d)).days < 7:
        return {**out, "written": 0, "why": f"本周已记({last_d})"}
    sub = await submit(scenario_entries(v["d"], float(v["close"]), v["probs"]), AUTHOR, now)
    if not sub.get("ok"):
        return {**out, "ok": False, "written": 0, "why": f"情景没写进去:{str(sub.get('why'))[:160]}"}
    await redis_set_key(WEEK_KEY, {"d": v["d"]}, ttl=400 * 86400)
    return {**out, "written": 3, "why": f"周期读数 {v['d']}:{v['stance']}(倾斜 {v['tilt_excess']:+.2f},{v['episodes']} 段)"}
