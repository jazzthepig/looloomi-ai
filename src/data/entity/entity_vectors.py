"""Entity 空间的向量:每个发行方每个季度一行(HIGH_DIM_ONTOLOGY §5 表「Entity/Decision · 待定义 · frontier」;11-05)。

## 为什么是季度

发行方的「待遇」是慢变量(Jazz 11-02:CIS 的核心维度是小股东待遇):分利档位、稀释、回购、上下币 —— 按天看是噪声,按季看才是决策。
这里把三张已有的表按 (entity, 季度) 折成一个稀疏向量,**没测到的维不写(I1)**:
- `treatment_daily`(代币,2026-10-21 起):季内均值 payout_share / revenue_yield_ann / holder_yield_ann / supply_growth_30d
- `issuer_decisions`(回购 / 分红 / 股数稀释 2016 起;上下币;每周一 payout_class / token_dilution):季内各类决策计数 + 回购 / 分红金额合计
- `decision_outcomes`:季内决策之后 30 天超额的均值(已结的才算)
CIS v2.1 要读的就是这张表;配置决策不从这里走。表 `entity_vectors`(entity_id, quarter);每天重算最近两个季度 + 首次整段。
判活:`select quarter, count(*) from entity_vectors group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Iterable, Optional

TABLE = "entity_vectors"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"entity_vectors": ("entity_id", "quarter", "vector", "n_days", "n_decisions", "code_ref")}
CODE_REF = "entity_vectors v1 (11-05)"
LOOP_NAME = "_entity_vectors_loop"
DECISION_KINDS = ("buyback", "dividend", "share_dilution", "token_dilution", "venue_listing", "venue_delisting", "payout_class")


def quarter_of(d: str) -> str:
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def _mean(xs: list[float]) -> Optional[float]:
    return round(statistics.fmean(xs), 6) if xs else None


def vectors(treatment: Iterable[dict], decisions: Iterable[dict], outcomes: Iterable[dict], by_symbol: dict[str, str],
            quarters: Optional[set[str]] = None) -> list[dict]:
    """纯函数。→ 每 (entity, quarter) 一行;quarters 给了就只算那些季度。"""
    acc: dict[tuple[str, str], dict[str, list[float]]] = {}
    days: dict[tuple[str, str], set[str]] = {}
    ndec: dict[tuple[str, str], int] = {}

    def slot(ent: str, q: str) -> dict[str, list[float]]:
        return acc.setdefault((ent, q), {})

    for r in treatment:
        ent = by_symbol.get(str(r.get("symbol") or "").upper())
        if not ent:
            continue
        q = quarter_of(str(r["d"]))
        if quarters and q not in quarters:
            continue
        s = slot(ent, q)
        days.setdefault((ent, q), set()).add(str(r["d"])[:10])
        for src, dim in (("holders_share", "payout_share"), ("revenue_yield_ann", "revenue_yield"), ("holder_yield_ann", "holder_yield"),
                         ("supply_growth_30d", "supply_growth")):
            v = _f(r.get(src))
            if v is not None:
                s.setdefault(dim, []).append(v)
    for x in decisions:
        ent, q, kind = x.get("entity_id"), quarter_of(str(x.get("ts"))), str(x.get("kind") or "")
        if not ent or kind not in DECISION_KINDS or (quarters and q not in quarters):
            continue
        s = slot(ent, q)
        s.setdefault(f"n_{kind}", []).append(1.0)
        ndec[(ent, q)] = ndec.get((ent, q), 0) + 1
        v = _f(x.get("value"))
        if kind in ("buyback", "dividend") and v is not None:
            s.setdefault(f"{kind}_usd", []).append(v)
    for o in outcomes:
        ent, q = o.get("entity_id"), quarter_of(str(o.get("d")))
        v = _f(o.get("excess"))
        if not ent or v is None or int(o.get("horizon_d") or 0) != 30 or (quarters and q not in quarters):
            continue
        slot(ent, q).setdefault("outcome_excess_30d", []).append(v)
    out = []
    for (ent, q), s in sorted(acc.items()):
        vec: dict[str, float] = {}
        for k, xs in s.items():
            if k.startswith("n_"):
                vec[k] = float(len(xs))
            elif k.endswith("_usd"):
                vec[k] = round(sum(xs), 2)
            else:
                m = _mean(xs)
                if m is not None:
                    vec[k] = m
        out.append({"entity_id": ent, "quarter": q, "vector": vec, "n_days": len(days.get((ent, q), ())),
                    "n_decisions": ndec.get((ent, q), 0), "code_ref": CODE_REF})
    return out


async def run_once(now: Optional[dt.datetime] = None, full: bool = False) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.entity.issuers import entity_by_symbol
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date().isoformat()
    have = await _read_all(TABLE, {"select": "quarter", "limit": "1"})
    full = full or not have
    qs: Optional[set[str]] = None
    if not full:
        prev = (now.date().replace(day=1) - dt.timedelta(days=1)).isoformat()
        qs = {quarter_of(today), quarter_of(prev), quarter_of((dt.date.fromisoformat(prev).replace(day=1) - dt.timedelta(days=1)).isoformat())}
        since = min(f"{q[:4]}-{(int(q[-1]) - 1) * 3 + 1:02d}-01" for q in qs)
    else:
        since = "2015-01-01"
    by_symbol = entity_by_symbol()
    treatment = await _read_all("treatment_daily", {"select": "symbol,d,holders_share,revenue_yield_ann,holder_yield_ann,supply_growth_30d",
                                                    "d": f"gte.{since}", "order": "d.asc,symbol.asc"})
    decisions = await _read_all("issuer_decisions", {"select": "entity_id,ts,kind,value", "ts": f"gte.{since}", "order": "ts.asc"})
    outcomes = await _read_all("decision_outcomes", {"select": "entity_id,d,horizon_d,excess", "d": f"gte.{since}", "horizon_d": "eq.30",
                                                     "order": "d.asc"})
    rows = vectors(treatment, decisions, outcomes, by_symbol, qs)
    if not rows:
        return {"ok": True, "status": "skipped", "why": "没有可折的季度"}
    w = await supabase_upsert_table(TABLE, rows, on_conflict="entity_id,quarter")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "written": len(rows), "quarters": sorted({r["quarter"] for r in rows})[-3:], "full": full,
            "why": f"{'整段' if full else '最近三季'} {len(rows)} 行"}


async def read(entity: str = "", quarter: str = "") -> list[dict]:
    from src.data.style.header import _read_all
    params = {"select": "entity_id,quarter,vector,n_days,n_decisions", "order": "quarter.desc,entity_id.asc", "limit": "400"}
    if entity:
        params["entity_id"] = f"eq.{entity}"
    if quarter:
        params["quarter"] = f"eq.{quarter}"
    return await _read_all(TABLE, params)
