"""决策 → 结果(Outcome 层,HIGH_DIM_ONTOLOGY §5「Outcome:信号 → 30d 结果分布」的第一张表;11-04)。

## 为什么

内核的边是 Entity → Decision → Asset → Outcome。11-04 建了 `issuer_entities` / `issuer_decisions` —— 一张登记表和一条决策流,
**但没有一条边通到结果**:回购之后股价相对 SPY 怎么走、上币之后代币相对 BTC 怎么走、分利档位标上去之后 90 天怎么样,
全都没人记。没有结果的决策流只是新闻。这里按时点把每条决策的前向 7 / 30 / 90 天收益**和基准的差**记成一行,
到期才结、结了不改;聚合出来的「每类决策的结果分布」就是那一类决策的 Outcome 向量。**只记,不判、不动钱。**

## 口径

- 入场 = 决策日(`ts` 的 UTC 日期)当天或之后 ≤ 5 天内的**第一根**收盘(披露日才知道,不能用更早的价);
  出场 = 决策日 + h 当天或之前 ≤ 5 天内的**最后一根**收盘(周末 / 假日对齐);基准同规则同日期。
- 代币:`coingecko_pro_ohlc`,基准 BTC;股票:`eodhd`,基准 SPY。单源:资产和基准各自在自己的源里算收益,再相减。
  稳定币 / 场所类工具不记(没有「相对基准的价格结果」这回事)。
- `excess = ret − ret_bench`;`hit = excess > 0`。到期 = 决策日 + h ≤ 昨天;没到期不写、价缺了不写(留作 pending 计数,不是 0)。
- 主键 (decision_id, horizon_d);**只追加**:已结的行不重算 —— 收益口径哪天要改,就是新 code_ref 的新行,旧行留着。

表 `decision_outcomes`。判活:`select kind, horizon_d, count(*), round(avg(excess)::numeric, 4) from decision_outcomes group by 1,2 order by 1,2`。
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Iterable, Optional

TABLE = "decision_outcomes"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"decision_outcomes": ("decision_id", "horizon_d", "entity_id", "symbol", "cls", "kind", "d", "entry_d", "exit_d",
                                        "entry", "exit", "ret", "bench", "ret_bench", "excess", "hit", "source", "code_ref", "settled_at")}
CODE_REF = "decision_outcomes v1 (11-04)"
LOOP_NAME = "_decision_outcomes_loop"
HORIZONS = (7, 30, 90)
ALIGN_DAYS = 5
SOURCE_BY_CLS = {"token": "coingecko_pro_ohlc", "equity": "eodhd"}
BENCH_BY_CLS = {"token": "BTC", "equity": "SPY"}


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def cls_by_symbol() -> dict[str, str]:
    """登记表里每个工具的类别(token / equity;稳定币 / 场所不在里面)。"""
    from src.data.entity.issuers import ENTITIES
    out: dict[str, str] = {}
    for e in ENTITIES:
        for ins in e["instruments"]:
            if ins["cls"] in SOURCE_BY_CLS:
                out.setdefault(str(ins["symbol"]).upper(), ins["cls"])
    return out


def first_close_on_or_after(series: dict[str, float], d: dt.date) -> Optional[tuple[str, float]]:
    for k in range(ALIGN_DAYS + 1):
        key = (d + dt.timedelta(days=k)).isoformat()
        if key in series:
            return key, series[key]
    return None


def last_close_on_or_before(series: dict[str, float], d: dt.date) -> Optional[tuple[str, float]]:
    for k in range(ALIGN_DAYS + 1):
        key = (d - dt.timedelta(days=k)).isoformat()
        if key in series:
            return key, series[key]
    return None


def settle(decisions: Iterable[dict], closes: dict[tuple[str, str], dict[str, float]], today: dt.date,
           classes: dict[str, str], done: set[tuple[str, int]] = frozenset()) -> tuple[list[dict], dict[str, int]]:
    """纯函数。decisions = issuer_decisions 行(id, ts, kind, symbols, entity_id);closes = {(source, symbol): {d: close}}。
    返回 (新结的行, 计数 {settled, pending, no_price, skipped_cls})。到期 = d + h ≤ today − 1。"""
    yesterday = today - dt.timedelta(days=1)
    rows: list[dict] = []
    n = {"settled": 0, "pending": 0, "no_price": 0, "skipped_cls": 0}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for x in decisions:
        sym = str((x.get("symbols") or [""])[0] or "").upper()
        cls = classes.get(sym)
        if not cls:
            n["skipped_cls"] += 1
            continue
        d = dt.date.fromisoformat(str(x.get("ts"))[:10])
        src, bench = SOURCE_BY_CLS[cls], BENCH_BY_CLS[cls]
        a, b = closes.get((src, sym)) or {}, closes.get((src, bench)) or {}
        for h in HORIZONS:
            if (x["id"], h) in done:
                continue
            if d + dt.timedelta(days=h) > yesterday:
                n["pending"] += 1
                continue
            ea, xa = first_close_on_or_after(a, d), last_close_on_or_before(a, d + dt.timedelta(days=h))
            eb, xb = first_close_on_or_after(b, d), last_close_on_or_before(b, d + dt.timedelta(days=h))
            if not (ea and xa and eb and xb) or ea[1] <= 0 or eb[1] <= 0 or xa[0] <= ea[0]:
                n["no_price"] += 1
                continue
            ret, rb = xa[1] / ea[1] - 1.0, xb[1] / eb[1] - 1.0
            rows.append({"decision_id": x["id"], "horizon_d": h, "entity_id": x.get("entity_id"), "symbol": sym, "cls": cls,
                         "kind": x.get("kind"), "d": d.isoformat(), "entry_d": ea[0], "exit_d": xa[0], "entry": ea[1], "exit": xa[1],
                         "ret": round(ret, 6), "bench": bench, "ret_bench": round(rb, 6), "excess": round(ret - rb, 6),
                         "hit": ret - rb > 0, "source": src, "code_ref": CODE_REF, "settled_at": now})
            n["settled"] += 1
    return rows, n


def aggregate(rows: Iterable[dict]) -> list[dict]:
    """纯函数。每 (kind, horizon) 一行:n、均值 / 中位 / 四分位的超额、命中率。n < 5 标 thin(只报不判)。"""
    g: dict[tuple[str, int], list[float]] = {}
    for r in rows:
        v = _f(r.get("excess"))
        if v is not None:
            g.setdefault((str(r.get("kind")), int(r.get("horizon_d"))), []).append(v)
    out = []
    for (kind, h), xs in sorted(g.items()):
        xs = sorted(xs)
        q = statistics.quantiles(xs, n=4) if len(xs) >= 4 else [None, None, None]
        out.append({"kind": kind, "horizon_d": h, "n": len(xs), "mean_excess": round(statistics.fmean(xs), 5),
                    "median_excess": round(statistics.median(xs), 5), "q1": None if q[0] is None else round(q[0], 5),
                    "q3": None if q[2] is None else round(q[2], 5), "hit_rate": round(sum(1 for v in xs if v > 0) / len(xs), 3),
                    "thin": len(xs) < 5})
    return out


async def _closes(source: str, symbols: set[str], start: str) -> dict[tuple[str, str], dict[str, float]]:
    from src.data.style.header import _read_all
    if not symbols:
        return {}
    rows = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close", "source": f"eq.{source}",
                                           "symbol": "in.(" + ",".join(sorted(symbols)) + ")", "trade_date": f"gte.{start}",
                                           "order": "trade_date.asc"})
    out: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        c = _f(r.get("close"))
        if c is not None and c > 0:
            out.setdefault((source, str(r.get("symbol")).upper()), {})[str(r.get("trade_date"))[:10]] = c
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    classes = cls_by_symbol()
    decisions = await _read_all("issuer_decisions", {"select": "id,entity_id,ts,kind,symbols", "order": "ts.asc"})
    done_rows = await _read_all(TABLE, {"select": "decision_id,horizon_d"})
    done = {(r["decision_id"], int(r["horizon_d"])) for r in done_rows}
    todo = [x for x in decisions if any((x["id"], h) not in done for h in HORIZONS)
            and classes.get(str((x.get("symbols") or [""])[0] or "").upper())]
    if not todo:
        return {"ok": True, "status": "skipped", "written": 0, "why": f"{len(decisions)} 条决策都结过了"}
    need: dict[str, set[str]] = {}
    start = min(str(x["ts"])[:10] for x in todo)
    for x in todo:
        sym = str(x["symbols"][0]).upper()
        cls = classes[sym]
        need.setdefault(SOURCE_BY_CLS[cls], set()).update({sym, BENCH_BY_CLS[cls]})
    closes: dict[tuple[str, str], dict[str, float]] = {}
    for src, syms in need.items():
        closes.update(await _closes(src, syms, start))
    rows, n = settle(todo, closes, now.date(), classes, done)
    if rows:
        w = await supabase_upsert_table(TABLE, rows, on_conflict="decision_id,horizon_d")
        if not w:
            return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "written": len(rows), **n, "decisions": len(decisions),
            "why": f"结 {len(rows)} 行(未到期 {n['pending']} · 缺价 {n['no_price']} · 无类别 {n['skipped_cls']})"}


async def summary() -> dict[str, Any]:
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "kind,horizon_d,excess,symbol,d", "order": "d.desc", "limit": "5000"})
    return {"by_kind": aggregate(rows), "n": len(rows)}
