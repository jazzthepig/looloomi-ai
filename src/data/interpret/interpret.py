"""T-040 解读层 v0 —— 指标之后的那一步:今天像历史上哪几段 → 那几段之后各风格怎么走 → 几个角度是否一致。

Jazz 2026-09-30:「获得指标后没有立刻分析市场、获得归因 —— 单纯指标没有解释,就是 AI 前世纪的工程流。」

三个角度,各自找相似日,**并排给出,不合成一个分数**(相似度在不同空间里不可比,S-351):
- **风格相位**(style):各风格相对大币过去 30 / 90 / 180 天的对数收益 + 大币自身 —— 直接回答「现在在哪个风格周期」。2020 起。
- **宏观**(macro,5a):`market_state_vectors.vec_full`,2022 起。
- **横截面**(micro,5b):`regime_daily.features`(CIS 支柱等),2025-05 起。

**每个角度给出:** 相似日(只取早于 d−30 天的,前瞻窗口在 d 时已经走完;相似日之间至少隔 7 天,不让同一段行情占满名额)
→ 这些日子之后 30 天各风格、各风格相对大币的收益 → 中位数 / 四分位 / 上涨占比。
**30 天后**把实际结果写回同一行(`realized`),解释本身要能被对账(T-041 按预注册判读)。

**PIT:** 标准化只用 d 之前的日子(扩张窗口);相似日只能早于 d − 30 天。所以历史回放与每天实时是同一段代码,
回放不会看到当天之后的任何东西。(数据库里的 `similar_market_states()` 用全样本做标准化且允许取未来日,只适合看今天,不适合回放。)

**已知偏差:** 风格指数的回填段有幸存者偏差(见 `src/data/style/header.py`),前向 30 天的历史分布因此偏乐观。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

HORIZON = 30
MIN_GAP_DAYS = 30        # 相似日必须早于 d − 30 天
SPACING_DAYS = 7         # 相似日之间至少隔 7 天
K = 10
MIN_SHARED = 8
MIN_HISTORY = 120        # 某空间里 d 之前的可比日子少于这个就不出这个角度
START = "2023-01-01"     # 回放起点(宏观空间 2022 起,留出热身)
CODE_REF = "t040-v0"
TABLE = "market_interpretation_daily"
STYLE_WINDOWS = (30, 90, 180)
SPREAD_BASE = "majors"


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def style_state(levels: pd.DataFrame) -> pd.DataFrame:
    """风格相位向量:每个风格相对大币过去 30/90/180 天的对数收益,加上大币自身的。行 = 日期。"""
    lv = np.log(levels.sort_index())
    cols = {}
    for w in STYLE_WINDOWS:
        chg = lv - lv.shift(w)
        for s in levels.columns:
            if s == SPREAD_BASE:
                cols[f"{s}_{w}"] = chg[s]
            elif SPREAD_BASE in levels.columns:
                cols[f"{s}-{SPREAD_BASE}_{w}"] = chg[s] - chg[SPREAD_BASE]
    return pd.DataFrame(cols, index=levels.index)


def analogs(mat: pd.DataFrame, d: pd.Timestamp, *, k: int = K, min_shared: int = MIN_SHARED,
            gap: int = MIN_GAP_DAYS, spacing: int = SPACING_DAYS) -> list[tuple[str, float]]:
    """d 在空间 `mat` 里的相似日。标准化只用 d 之前的日子;候选只取 ≤ d − gap 的日子;彼此至少隔 spacing 天。"""
    if d not in mat.index:
        return []
    past = mat[mat.index < d]
    if len(past.dropna(how="all")) < MIN_HISTORY:
        return []
    mu, sd = past.mean(), past.std().replace(0, np.nan)
    z = (mat - mu) / sd
    t = z.loc[d]
    cand = z[z.index <= d - pd.Timedelta(days=gap)]
    shared = cand.notna() & t.notna()
    n_shared = shared.sum(axis=1)
    a = cand.where(shared).fillna(0.0)
    tv = t.where(t.notna(), 0.0)
    num = a.values @ tv.values
    den = np.sqrt((a.values ** 2).sum(axis=1)) * np.sqrt(((shared * tv) ** 2).sum(axis=1).values)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = pd.Series(num / den, index=cand.index)
    cos = cos[(n_shared >= min_shared) & cos.notna()].sort_values(ascending=False)
    picked: list[tuple[str, float]] = []
    for day, c in cos.items():
        if all(abs((day - pd.Timestamp(p)).days) >= spacing for p, _ in picked):
            picked.append((day.date().isoformat(), round(float(c), 4)))
        if len(picked) >= k:
            break
    return picked


def forward_returns(levels: pd.DataFrame, day: pd.Timestamp, h: int = HORIZON) -> dict[str, float]:
    """某一天之后 h 天:各风格收益、各风格相对大币的收益差。缺数据的键不出现。"""
    end = day + pd.Timedelta(days=h)
    if day not in levels.index or end not in levels.index:
        return {}
    r = levels.loc[end] / levels.loc[day] - 1
    out = {s: float(v) for s, v in r.items() if pd.notna(v)}
    if SPREAD_BASE in out:
        for s, v in list(out.items()):
            if s != SPREAD_BASE:
                out[f"{s}-{SPREAD_BASE}"] = v - out[SPREAD_BASE]
    return out


def summarize(fwds: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """多个相似日的前向结果 → 每个键的中位数 / 四分位 / 上涨占比 / 样本数。"""
    keys = sorted({k for f in fwds for k in f})
    out = {}
    for k in keys:
        v = np.array([f[k] for f in fwds if k in f], dtype=float)
        if len(v) == 0:
            continue
        out[k] = {"median": float(np.median(v)), "p25": float(np.percentile(v, 25)),
                  "p75": float(np.percentile(v, 75)), "p_up": float((v > 0).mean()), "n": int(len(v))}
    return out


def agreement(a: Mapping[str, dict], b: Mapping[str, dict]) -> Optional[float]:
    """两个角度对「各风格相对大币」中位数的方向一致比例。共同键少于 3 个 ⇒ None(不硬给)。"""
    keys = [k for k in a if k.endswith(f"-{SPREAD_BASE}") and k in b]
    if len(keys) < 3:
        return None
    return float(np.mean([np.sign(a[k]["median"]) == np.sign(b[k]["median"]) for k in keys]))


def narrative(d: str, angles: Mapping[str, dict], labels: Mapping[str, str]) -> str:
    """一段可追溯的说明。只描述「相似时段之后发生过什么」,不给仓位建议。"""
    names = {"style": "风格相位", "macro": "宏观", "micro": "横截面"}
    parts = [f"{d}:"]
    for ang, body in angles.items():
        if not body.get("analogs"):
            parts.append(f"{names[ang]}角度没有足够的可比历史;")
            continue
        top = "、".join(x[0] for x in body["analogs"][:3])
        spreads = {k: v for k, v in body["fwd"].items() if k.endswith(f"-{SPREAD_BASE}")}
        if spreads:
            k, v = max(spreads.items(), key=lambda kv: abs(kv[1]["median"]))
            s = k.split("-")[0]
            parts.append(f"{names[ang]}上最像 {top};这些时段之后 30 天,{labels.get(s, s)}相对大币的中位数 "
                         f"{v['median'] * 100:+.1f}%(四分位 {v['p25'] * 100:+.1f}% ~ {v['p75'] * 100:+.1f}%,"
                         f"{int(v['p_up'] * v['n'])}/{v['n']} 段为正);")
    return "".join(parts)


def interpret_day(d: pd.Timestamp, levels: pd.DataFrame, spaces: Mapping[str, pd.DataFrame],
                  labels: Mapping[str, str]) -> dict[str, Any]:
    """一天的解读行。`spaces`:角度名 → 该空间的日度矩阵(style / macro / micro)。"""
    angles: dict[str, dict] = {}
    for ang, mat in spaces.items():
        an = analogs(mat, d)
        fw = summarize([forward_returns(levels, pd.Timestamp(x)) for x, _ in an])
        angles[ang] = {"analogs": an, "fwd": fw}
    avail = [a for a in angles if angles[a]["analogs"]]
    pairs = {f"{a}~{b}": agreement(angles[a]["fwd"], angles[b]["fwd"])
             for i, a in enumerate(avail) for b in avail[i + 1:]}
    pooled = summarize([forward_returns(levels, pd.Timestamp(x))
                        for a in avail for x, _ in angles[a]["analogs"]])
    ds = d.date().isoformat()
    return {"d": ds, "angles": angles, "pooled": pooled,
            "agreement": {k: v for k, v in pairs.items() if v is not None},
            "realized": forward_returns(levels, d) or None,
            "narrative": narrative(ds, angles, labels), "code_ref": CODE_REF}


# ── I/O ─────────────────────────────────────────────────────────────────────

async def _load() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    from src.data.style.header import CODE_REF as STYLE_REF, _read_all
    rows = await _read_all("style_index_daily", {"select": "d,style,level", "weighting": "eq.cap",
                                                 "code_ref": f"eq.{STYLE_REF}", "order": "d.asc"})
    if not rows:
        raise RuntimeError("style_index_daily 当前口径 0 行 —— 风格表头还没重算完,不出解读")
    lv = pd.DataFrame(rows).pivot_table(index="d", columns="style", values="level")
    lv.index = pd.to_datetime(lv.index)
    lv = lv.reindex(pd.date_range(lv.index.min(), lv.index.max(), freq="D"))
    spaces: dict[str, pd.DataFrame] = {"style": style_state(lv)}
    msv = await _read_all("market_state_vectors", {"select": "d,vec_full", "order": "d.asc"})
    if msv:
        m = pd.DataFrame([r["vec_full"] or [] for r in msv], index=pd.to_datetime([r["d"] for r in msv]),
                         dtype=float)
        spaces["macro"] = m.reindex(lv.index)
    rd = await _read_all("regime_daily", {"select": "d,features", "order": "d.asc"})
    if rd:
        f = pd.DataFrame([r.get("features") or {} for r in rd], index=pd.to_datetime([r["d"] for r in rd]))
        f = f.apply(pd.to_numeric, errors="coerce")
        spaces["micro"] = f.reindex(lv.index)
    return lv, spaces


async def run_once() -> dict[str, Any]:
    """从 START 到最新一个有风格指数的日子,逐日整条重算并 upsert(无状态;历史回放 = 同一段代码)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.taxonomy import STYLES
    lv, spaces = await _load()
    last = lv["majors"].last_valid_index() if "majors" in lv else None
    if last is None:
        return {"ok": False, "reason": "大币指数没有数据"}
    days = pd.date_range(pd.Timestamp(START), last, freq="D")
    rows = await asyncio.to_thread(lambda: [interpret_day(d, lv, spaces, STYLES) for d in days])
    for i in range(0, len(rows), 500):
        res = await supabase_upsert_table(TABLE, rows[i:i + 500], on_conflict="d")
        if not res.ok:
            return {"ok": False, "reason": f"{TABLE} 写入失败:{res.why}"}
    today = rows[-1]
    stale = {a: (last - spaces[a].dropna(how="all").index.max()).days
             for a in spaces if len(spaces[a].dropna(how="all"))}
    return {"ok": True, "written": len(rows), "last": today["d"], "narrative": today["narrative"],
            "angles_today": [a for a, b in today["angles"].items() if b["analogs"]],
            "space_stale_days": stale,
            "reason": f"解读 {len(rows)} 天,至 {today['d']};今天可用角度 "
                      f"{[a for a, b in today['angles'].items() if b['analogs']]};各空间落后天数 {stale}"}
