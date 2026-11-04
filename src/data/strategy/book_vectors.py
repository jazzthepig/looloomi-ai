"""Strategy 空间的向量(HIGH_DIM_ONTOLOGY §5 表里的「Strategy · 30d 稀疏 · jsonb + Python 余弦 · 不进 ANN」;11-04)。

## 为什么从前向账本算,不从回测算

登记表里每本账(`accounting/registry.BOOKS`)每天都在记真实前向 NAV。一本账「像什么」「在哪种天气里挣钱」「谁和谁其实是同一个赌注」,
答案全在那条前向曲线和它基准的差里 —— 不需要再回测一次。这里每天把每本账的**超额日收益**(账本 − 它登记的基准)折成一个
稀疏向量存起来;**没测到的维度不写(NaN ≠ 0,守恒律 I1)**;账本之间的相似度只在**共享维**上算余弦(§5 存储法则:稀疏少量 →
jsonb + 共享维余弦,**不**做 0 补齐进 ANN)。

## 维度(全部来自账本起点到 d 的前向记录;≥ MIN_DAYS 天才算)

    n_days · excess_ann(超额年化)· vol_ann(超额日收益年化波动)· max_dd(账本自己的最大回撤)· beta_core / corr_core(对 ① 日收益)
    hit_daily(超额 > 0 的天数占比)· skew · tail_ratio(超额最好 5% 的均值 / 最差 5% 的均值的绝对值)· ac1(超额一阶自相关)
    按天气分桶的超额年化(桶 ≥ MIN_BUCKET 天才写):
        trend_up / trend_down(面板 dist_200 正 / 负)· vol_hot / vol_cold(vratio_30_180 > 1 / ≤ 1)· cycle_turning / cycle_normal(⓪ 相位)

表 `book_vectors`(d, book_id);每天一行、整段重算(向量会随着账本变长而漂,历史行就是漂移的记录)。
读:`GET /internal/book-vectors?book=` → 最新向量、共享维余弦最近的三本、以及「没有一本账在里面挣钱」的桶(覆盖空洞)。
判活:`select d, count(*) from book_vectors group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

TABLE = "book_vectors"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"book_vectors": ("d", "book_id", "layer", "status", "vector", "n_days", "start", "code_ref")}
CODE_REF = "book_vectors v1 (11-04)"
LOOP_NAME = "_book_vectors_loop"
MIN_DAYS = 60
MIN_BUCKET = 20
MIN_SHARED = 6
BUCKETS = ("trend_up", "trend_down", "vol_hot", "vol_cold", "cycle_turning", "cycle_normal")
#: 共享维余弦前按维度做跨账本 z;这些维度只是计数 / 日期,不进相似度
NOT_SIMILARITY_DIMS = ("n_days",)


def _ann(mean_daily: float) -> float:
    return float(mean_daily * 365.0)


def regime_frame(state_rows: list[dict], cycle_rows: list[dict]) -> pd.DataFrame:
    """纯函数。state_daily(panel 的 dist_200 / vratio_30_180)+ cycle_vector_daily(phase)→ 每天一行的天气标签(布尔列,缺就 NaN)。"""
    rec: dict[str, dict] = {}
    for r in state_rows:
        d, f, v = str(r.get("d"))[:10], r.get("feature"), r.get("value")
        if v is None:
            continue
        if f == "dist_200":
            rec.setdefault(d, {})["trend_up"] = float(v) > 0
        elif f == "vratio_30_180":
            rec.setdefault(d, {})["vol_hot"] = float(v) > 1.0
    for r in cycle_rows:
        if r.get("phase"):
            rec.setdefault(str(r.get("d"))[:10], {})["cycle_turning"] = r["phase"] == "turning"
    if not rec:
        return pd.DataFrame(columns=["trend_up", "vol_hot", "cycle_turning"])
    df = pd.DataFrame.from_dict(rec, orient="index")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def vector_for(nav: pd.Series, bench: Optional[pd.Series], core: Optional[pd.Series], regime: pd.DataFrame) -> Optional[dict[str, float]]:
    """纯函数。一本账的前向 NAV + 基准 + ① → 稀疏向量;不够 MIN_DAYS 天 ⇒ None;没测到的维度不出现。"""
    nav = nav.dropna().sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    if len(nav) < MIN_DAYS + 1:
        return None
    r = nav.pct_change().dropna()
    if bench is None or bench.dropna().empty:
        return None
    b = bench.dropna().sort_index()
    b = b[~b.index.duplicated(keep="last")].pct_change().dropna()
    ex = (r - b.reindex(r.index)).dropna()
    if len(ex) < MIN_DAYS:
        return None
    v: dict[str, float] = {"n_days": float(len(ex)), "excess_ann": _ann(ex.mean()), "vol_ann": float(ex.std(ddof=1) * math.sqrt(365.0)),
                           "max_dd": float((nav / nav.cummax() - 1.0).min()), "hit_daily": float((ex > 0).mean())}
    if ex.std(ddof=1) > 0:
        v["skew"] = float(ex.skew())
        v["ac1"] = float(ex.autocorr(1)) if len(ex) > 3 else float("nan")
        k = max(3, int(len(ex) * 0.05))
        top, bot = ex.nlargest(k).mean(), ex.nsmallest(k).mean()
        if bot < 0:
            v["tail_ratio"] = float(top / abs(bot))
    if core is not None and not core.dropna().empty:
        c = core.dropna().sort_index()
        c = c[~c.index.duplicated(keep="last")].pct_change().dropna().reindex(r.index)
        both = pd.concat([r, c], axis=1).dropna()
        if len(both) >= MIN_DAYS and both.iloc[:, 1].var() > 0:
            cov = both.cov().iloc[0, 1]
            v["beta_core"] = float(cov / both.iloc[:, 1].var())
            v["corr_core"] = float(both.corr().iloc[0, 1])
    if len(regime):
        rg = regime.reindex(ex.index)
        for col, name_t, name_f in (("trend_up", "trend_up", "trend_down"), ("vol_hot", "vol_hot", "vol_cold"),
                                    ("cycle_turning", "cycle_turning", "cycle_normal")):
            if col not in rg:
                continue
            m = rg[col]
            for name, mask in ((name_t, m == True), (name_f, m == False)):             # noqa: E712  (NaN 两边都不算)
                sub = ex[mask.fillna(False).values]
                if len(sub) >= MIN_BUCKET:
                    v[name] = _ann(sub.mean())
    return {k: round(x, 6) for k, x in v.items() if x == x and math.isfinite(x)}


def cosine_shared(a: dict[str, float], b: dict[str, float], scale: dict[str, tuple[float, float]], min_shared: int = MIN_SHARED) -> Optional[float]:
    """纯函数。共享维余弦:两本账都有的维度,各按跨账本 (均值, 标准差) 标准化后算余弦;共享维 < min_shared ⇒ None(不是 0)。"""
    keys = [k for k in a if k in b and k in scale and k not in NOT_SIMILARITY_DIMS and scale[k][1] > 0]
    if len(keys) < min_shared:
        return None
    x = np.array([(a[k] - scale[k][0]) / scale[k][1] for k in keys])
    y = np.array([(b[k] - scale[k][0]) / scale[k][1] for k in keys])
    nx, ny = np.linalg.norm(x), np.linalg.norm(y)
    if nx == 0 or ny == 0:
        return None
    return float(np.dot(x, y) / (nx * ny))


def scales(vectors: dict[str, dict[str, float]]) -> dict[str, tuple[float, float]]:
    """每个维度的跨账本均值 / 标准差(只用有该维的账本)。"""
    dims: dict[str, list[float]] = {}
    for v in vectors.values():
        for k, x in v.items():
            dims.setdefault(k, []).append(x)
    return {k: (float(np.mean(xs)), float(np.std(xs)) if len(xs) > 1 else 0.0) for k, xs in dims.items()}


def neighbours(vectors: dict[str, dict[str, float]], book: str, k: int = 3) -> list[dict]:
    sc = scales(vectors)
    out = []
    for other, v in vectors.items():
        if other == book:
            continue
        c = cosine_shared(vectors[book], v, sc)
        if c is not None:
            out.append({"book": other, "cosine": round(c, 4), "shared_dims": len([d for d in vectors[book] if d in v])})
    return sorted(out, key=lambda r: -r["cosine"])[:k]


def uncovered(vectors: dict[str, dict[str, float]]) -> list[dict]:
    """没有一本账在里面挣到正超额的天气桶 —— 这是「什么没覆盖」的向量答案。"""
    out = []
    for bk in BUCKETS:
        have = {b: v[bk] for b, v in vectors.items() if bk in v}
        if not have:
            out.append({"bucket": bk, "why": "没有一本账在这个桶里有 ≥ 20 天记录"})
        elif max(have.values()) <= 0:
            out.append({"bucket": bk, "why": f"{len(have)} 本账都是负超额;最好的 {max(have, key=have.get)} {max(have.values()):+.3f}/yr"})
    return out


async def _regime(start: str) -> pd.DataFrame:
    from src.data.style.header import _read_all
    state = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel", "feature": "in.(dist_200,vratio_30_180)",
                                            "d": f"gte.{start}", "order": "d.asc,feature.asc"})
    cycle = await _read_all("cycle_vector_daily", {"select": "d,phase", "d": f"gte.{start}", "order": "d.asc"})
    return regime_frame(state, cycle)


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.accounting.registry import BOOKS, core_nav, load_navs
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    have = await _read_all(TABLE, {"select": "book_id", "d": f"eq.{d}", "limit": "1"})
    if have:
        return {"ok": True, "status": "skipped", "why": f"{d} 已写"}
    navs, bench = await load_navs()
    core = await core_nav()
    starts = [s.dropna().index.min() for s in navs.values() if s is not None and not s.dropna().empty]
    if not starts:
        return {"ok": False, "why": "没有一本账有 NAV"}
    regime = await _regime(min(starts).date().isoformat())
    cut = pd.Timestamp(d)
    rows, skipped = [], {}
    for b in BOOKS:
        s = navs.get(b.id)
        if s is None:
            skipped[b.id] = "no_nav"
            continue
        s = s[s.index <= cut]
        bs = bench.get(b.id)
        v = vector_for(s, None if bs is None else bs[bs.index <= cut], None if core is None else core[core.index <= cut], regime)
        if not v:
            skipped[b.id] = f"< {MIN_DAYS} 天或无基准"
            continue
        rows.append({"d": d, "book_id": b.id, "layer": b.layer, "status": b.status, "vector": v, "n_days": int(v["n_days"]),
                     "start": s.dropna().index.min().date().isoformat(), "code_ref": CODE_REF})
    if not rows:
        return {"ok": False, "why": f"没有一本账够 {MIN_DAYS} 天", "skipped": skipped}
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,book_id")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    vecs = {r["book_id"]: r["vector"] for r in rows}
    return {"ok": True, "d": d, "written": len(rows), "skipped": skipped, "uncovered": uncovered(vecs),
            "why": f"{d} 写 {len(rows)} 本账的向量;跳过 {len(skipped)};未覆盖桶 {[u['bucket'] for u in uncovered(vecs)]}"}


async def latest(book: str = "") -> dict[str, Any]:
    from src.data.style.header import _read_all
    last = await _read_all(TABLE, {"select": "d", "order": "d.desc", "limit": "1"})
    if not last:
        return {"d": None, "vectors": {}, "neighbours": [], "uncovered": []}
    d = str(last[0]["d"])[:10]
    rows = await _read_all(TABLE, {"select": "book_id,layer,status,vector,n_days,start", "d": f"eq.{d}", "order": "book_id.asc"})
    vecs = {r["book_id"]: r["vector"] for r in rows}
    return {"d": d, "vectors": rows if not book else [r for r in rows if r["book_id"] == book],
            "neighbours": neighbours(vecs, book) if book in vecs else [], "uncovered": uncovered(vecs)}
