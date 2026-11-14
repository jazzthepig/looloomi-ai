"""时序窗口向量(HIGH_DIM_ONTOLOGY §5 表里的「时序窗口 · shapelet / 窗口向量 · 相位检索:当前 60 天像历史哪段」;11-05)。

## 和 `market_state_vectors` 的分工

状态向量(24 维 z,按时点)答的是「今天的**状态**像哪天」;这里答的是「最近 60 天的**路径**像哪段」—— 同一个状态可以是刚跌出来的
也可以是涨上去的,路径分得开。向量是**尺度无关的形状**:12 个五日对数收益各除以窗口日波动,再加窗口内的回撤深度 / 收盘在窗口区间里的
位置 / 60 日总收益(按波动归一)/ 20 日对 60 日波动比 / 日收益一阶自相关。17 维,稠密,行数 ≈ 3,000 ⇒ Python 里直接算距离,不进 ANN。

## 检索(给 ③ 每日决定的第三条描述臂 `probs_window`)

与今天的窗口向量欧氏距离最近的 k = 50 个历史日(排除最近 31 天 —— 它们的 30 日结果还没出来),它们之后 30 日 BTC 的三档频率,
按独立段数(相邻近邻相差 ≥ 30 天才算新段)向无条件频率收缩 —— 与 `exposure_decision.knn_rates` 同一套收缩,只换了向量。
**只描述,不动钱**(S-709 的敞口仍只由规则给);前五个近邻的日期和它们之后 30 天发生了什么一起报,人能对着看。

表 `window_vectors`(d 主键;每天整条重算、整条 upsert,2018 起约 3,000 行)。判活:`select max(d), count(*) from window_vectors`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

TABLE = "window_vectors"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"window_vectors": ("d", "vec", "dims", "close", "code_ref")}
CODE_REF = "window_vectors v1 (11-05)"
LOOP_NAME = "_window_vectors_loop"
WINDOW = 60
STEP = 5
DIMS = tuple(f"r5_{i}" for i in range(WINDOW // STEP)) + ("dd", "pos", "r60_sig", "vol_ratio", "ac1")
K = 50
EXCLUDE_DAYS = 31
MIN_HISTORY = 400


def window_vector(closes: list[float]) -> Optional[list[float]]:
    """纯函数。最近 WINDOW+1 个收盘(旧 → 新)→ 17 维形状向量;长度不够或有非正价 ⇒ None。"""
    if len(closes) < WINDOW + 1 or any(c is None or c <= 0 for c in closes[-(WINDOW + 1):]):
        return None
    c = closes[-(WINDOW + 1):]
    lr = [math.log(c[i + 1] / c[i]) for i in range(WINDOW)]
    mu = sum(lr) / WINDOW
    sig = math.sqrt(sum((x - mu) ** 2 for x in lr) / (WINDOW - 1))
    if sig <= 1e-12:
        return None
    v = [sum(lr[i:i + STEP]) / (sig * math.sqrt(STEP)) for i in range(0, WINDOW, STEP)]
    peak, dd = c[0], 0.0
    for x in c:
        peak = max(peak, x)
        dd = min(dd, x / peak - 1.0)
    lo, hi = min(c), max(c)
    v.append(dd)
    v.append((c[-1] - lo) / (hi - lo) if hi > lo else 0.5)
    v.append(sum(lr) / (sig * math.sqrt(WINDOW)))
    lr20 = lr[-20:]
    mu20 = sum(lr20) / 20
    sig20 = math.sqrt(sum((x - mu20) ** 2 for x in lr20) / 19)
    v.append(sig20 / sig)
    num = sum((lr[i] - mu) * (lr[i + 1] - mu) for i in range(WINDOW - 1))
    den = sum((x - mu) ** 2 for x in lr)
    v.append(num / den if den > 0 else 0.0)
    return [round(x, 5) for x in v]


def vectors_by_day(closes: dict[str, float]) -> dict[str, list[float]]:
    """纯函数。{d: close}(日历日,缺的天跳过)→ {d: 向量};每个 d 用它之前(含)的 61 个有价日。"""
    days = sorted(k for k, x in closes.items() if x)
    out: dict[str, list[float]] = {}
    for i in range(WINDOW, len(days)):
        v = window_vector([closes[k] for k in days[i - WINDOW:i + 1]])
        if v:
            out[days[i]] = v
    return out


def nearest(vectors: dict[str, list[float]], today_vec: list[float], d: str, k: int = K) -> list[tuple[float, str]]:
    """纯函数。排除 d 前 EXCLUDE_DAYS 天及之后;返回 (距离, 日期) 升序前 k。"""
    cutoff = (dt.date.fromisoformat(d) - dt.timedelta(days=EXCLUDE_DAYS)).isoformat()
    dim = len(today_vec)
    cand = []
    for k2, v in vectors.items():
        if k2 > cutoff or len(v) != dim:
            continue
        cand.append((math.sqrt(sum((a - b) ** 2 for a, b in zip(v, today_vec))), k2))
    return sorted(cand)[:k]


def window_rates(vectors: dict[str, list[float]], fwd: dict[str, float], today_vec: list[float], d: str, k: int = K) -> dict[str, Any]:
    """纯函数。→ {probs, n, segments, matches:[{d, dist, fwd}] 前五}。样本不够 ⇒ 无条件频率、n=0。收缩同 exposure_decision.knn_rates。"""
    from src.data.execution.exposure_decision import SHRINK_K, outcome_bin
    allc = {"down": 0, "flat": 0, "up": 0}
    for r in fwd.values():
        allc[outcome_bin(r)] += 1
    tot_all = sum(allc.values()) or 1
    p_all = {kk: v / tot_all for kk, v in allc.items()}
    near = [(dist, k2) for dist, k2 in nearest({k2: v for k2, v in vectors.items() if k2 in fwd}, today_vec, d, k)]
    if len(near) < k:
        return {"probs": {kk: round(v, 3) for kk, v in p_all.items()}, "n": 0, "segments": 0, "matches": []}
    counts = {"down": 0, "flat": 0, "up": 0}
    for _, k2 in near:
        counts[outcome_bin(fwd[k2])] += 1
    dates = sorted(dt.date.fromisoformat(k2) for _, k2 in near)
    segs, last = 0, None
    for x in dates:
        if last is None or (x - last).days >= 30:
            segs += 1
        last = x
    p_k = {kk: v / k for kk, v in counts.items()}
    probs = {kk: (segs * p_k[kk] + SHRINK_K * p_all[kk]) / (segs + SHRINK_K) for kk in counts}
    tot = sum(probs.values()) or 1
    return {"probs": {kk: round(v / tot, 3) for kk, v in probs.items()}, "n": k, "segments": segs,
            "matches": [{"d": k2, "dist": round(dist, 3), "fwd_30d": round(fwd[k2], 4)} for dist, k2 in near[:5]]}


async def _closes() -> dict[str, float]:
    from src.data.style.header import _read_all
    px = await _read_all("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist", "order": "trade_date.asc"})
    out = {}
    for r in px:
        try:
            c = float(r.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if c > 0:
            out[str(r["trade_date"])[:10]] = c
    return out


async def load_vectors() -> dict[str, list[float]]:
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "d,vec", "order": "d.asc"})
    return {str(r["d"])[:10]: [float(x) for x in r["vec"]] for r in rows if r.get("vec")}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    have = await _read_all(TABLE, {"select": "d,code_ref", "d": f"eq.{d}", "limit": "1"})
    if have and (have[0].get("code_ref") or "") == CODE_REF:
        return {"ok": True, "status": "already_done", "why": f"{d} 已写"}
    closes = await _closes()
    if d not in closes:
        return {"ok": True, "status": "skipped", "why": f"{d} 的 BTC 收盘还没到"}
    vecs = vectors_by_day({k: v for k, v in closes.items() if k <= d})
    if len(vecs) < MIN_HISTORY:
        return {"ok": False, "why": f"只有 {len(vecs)} 个窗口,< {MIN_HISTORY}"}
    rows = [{"d": k, "vec": v, "dims": list(DIMS), "close": closes[k], "code_ref": CODE_REF} for k, v in vecs.items()]
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "d": d, "written": len(rows), "why": f"重算至 {d}:{len(rows)} 个窗口"}


async def query(d: Optional[str] = None) -> dict[str, Any]:
    """端点用:d(默认最新)的近邻与三档频率。"""
    from src.data.execution.exposure_decision import forward_returns
    vecs = await load_vectors()
    if not vecs:
        return {"d": None, "why": "window_vectors 还没有行"}
    d = d or max(vecs)
    if d not in vecs:
        return {"d": d, "why": "那天没有窗口向量"}
    closes = await _closes()
    fwd = forward_returns({k: v for k, v in closes.items() if k < d})
    return {"d": d, **window_rates(vecs, fwd, vecs[d], d), "vector": dict(zip(DIMS, vecs[d]))}
