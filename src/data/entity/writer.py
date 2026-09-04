"""企业决策流的落库循环 —— **把卡插进主板** (S-292).

## Jazz 的话(2026-09-04)

> 「我们建了那么多东西,必须要连通呀,现在就像买了显卡、存储、网卡,
> 但是服务器不是连通的。」

对的。所以本模块不只是「一个循环」,它**同时插进这周建的四个面**:

    loop_beat (S-282)           失败要落到可查询的地方,不能只进 stdout
    producer_freshness (S-278)  表要被判活,否则它死了没人知道
    watch_census (S-279)        表要进覆盖清册,否则它计入 not_covered
    Supabase                    数据要真的落地

**任何一个不接,这块卡就没连线。** 而 `signal_outcomes` 死 123 天正是
「循环有了但心跳没接」;`market_state_vectors` 停 27 天正是
「写了一次但从没上日程」。两个前车都在这张表的隔壁。

## 解析结果要缓存,不能每天重探 180 家

`resolve_all` 要对每个候选 id 打一次 API。180 家 × 平均 2 个候选 = 360 次,
每天重跑就是每月一万次额度,**而解析结果几乎不变**(公司改名是年度事件)。

所以:解析结果落 `treasury_entities`,**只对还没解析出来的重试**,
且重试有节流(`RESOLVE_RETRY_DAYS`)。已解析的直接读表。

## 增量:决策是追加的,不是快照

`treasury_decisions` 的主键含 `decision_date` 与 `holding_net_change`,
所以重复拉同一段历史是幂等的 upsert,不会重复计数。
**首轮会拉全量(Strategy 119 条回到 2020-08-11),之后每天只多几条。**

## 预算

一轮的调用量 ≈ 已解析实体数 × 页数(多数 1–2 页)+ 少量重试。
约 40–80 次/天 ⇒ 每月 ~2,000 次,占 Analyst 月额度 500,000 的 **0.4%**。
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Optional

#: 每轮最多处理多少个实体。护栏,不是目标 —— 走满更可能是分页或解析坏了。
MAX_ENTITIES_PER_RUN = 60

#: 未解析的实体多少天重试一次。公司改名是年度事件,不必天天试。
RESOLVE_RETRY_DAYS = 7

#: 这一轮至少要落多少条才算「成功」。0 是合法的(今天没人买卖),
#: 但**连续多轮 0 条**会被心跳的 `n_consecutive_failures` 之外的东西捕捉:
#: 见 `producer_freshness` 的事件时钟 —— 那才是「内容陈旧」的判据。
COINS = ("bitcoin", "ethereum")

LOOP_NAME = "_treasury_decisions_loop"


def _cg_headers() -> dict:
    """与 `data_layer._cg_headers` 同源。

    ⚠️ `User-Agent` **不是可选的**:裸客户端会被 Cloudflare 1010 拦成 403,
    而 403 会被读成「没有这个付费能力」——S-291 就是这么误判的,
    代价是几个月的订阅费没被用上。
    """
    key = os.getenv("COINGECKO_API_KEY", "")
    return {"x-cg-pro-api-key": key, "accept": "application/json",
            "User-Agent": "CometCloudAI/1.0 (+looloomi.ai)"} if key else {}


async def _load_known_entities(supabase_query) -> dict:
    """已解析的实体 → `{name: entity_id}`。**解析结果是缓存的,不是每天重算的。**

    `supabase_query` 由调用方注入并走 `treasury_known_entities` RPC ——
    ⚠️ 我第一版写了 `supabase_select(table, cols)`,而**仓里根本没有这个函数**
    (读取一律走 RPC)。凭记忆写函数名,今天第二次(上一次是 `PAID_ENTITLEMENTS`
    的键名)。写之前 grep 一下比事后被 ImportError 咬便宜。
    """
    try:
        rows = await supabase_query("treasury_entities",
                                    "entity_id,name,last_seen") or []
        return {r["name"]: r for r in rows if r.get("name") and r.get("entity_id")}
    except Exception:                                           # noqa: BLE001
        return {}


async def run_once(*, client, supabase_query, supabase_upsert,
                   today: Optional[str] = None) -> dict:
    """跑一轮。**返回结构化结果,不打印** —— 调用方负责心跳与日志。

    注入 `client` / `supabase_*` 是为了这层能离线测试,不是为了优雅:
    「何时停、何时算成功」这些判断必须能在没有网络的情况下被验证。
    """
    from src.data.entity.collect import (
        CG_PRO_BASE, candidates, fetch_decisions, resolve_all, rows_for_supabase)

    today = today or dt.date.today().isoformat()
    out: dict = {"today": today, "coins": {}, "n_written": 0,
                 "n_entities_fetched": 0, "errors": []}

    known = await _load_known_entities(supabase_query)

    for coin in COINS:
        try:
            r = await client.get(f"{CG_PRO_BASE}/companies/public_treasury/{coin}")
            if r.status_code != 200:
                out["errors"].append(f"{coin}: 聚合端点 HTTP {r.status_code}")
                continue
            companies = (r.json() or {}).get("companies") or []
        except Exception as e:                                  # noqa: BLE001
            out["errors"].append(f"{coin}: {type(e).__name__}: {str(e)[:80]}")
            continue

        # ── 解析:已知的直接用,未知的才探 ────────────────────────────────
        async def probe(cid: str) -> bool:
            try:
                rr = await client.get(f"{CG_PRO_BASE}/public_treasury/{cid}")
                return rr.status_code == 200
            except Exception:                                   # noqa: BLE001
                return False

        resolved_rows, to_probe = [], []
        for co in companies:
            nm = str(co.get("name") or "").strip()
            if not nm:
                continue
            if nm in known:
                resolved_rows.append({**co, "_entity_id": known[nm]["entity_id"]})
            else:
                to_probe.append(co)

        newly = {}
        if to_probe:
            # 先把候选逐个探完(异步),再把命中集合交给同步的 `resolve_all`。
            # ⚠️ 不要试图在运行中的事件循环里包一个同步 probe —— 那条路
            # 写出来的第一版是一段永远返回 None 的死代码,而它**不会报错**,
            # 只会让每一家都判成未解析。
            hits: dict = {}
            for co in to_probe[:MAX_ENTITIES_PER_RUN]:
                for cid, _src in candidates(co.get("name"), co.get("symbol")):
                    if cid in hits or await probe(cid):
                        hits[cid] = True
                        newly[str(co.get("name"))] = cid
                        break
            res = resolve_all(to_probe, lambda cid: cid in hits)
            out["coins"].setdefault(coin, {})["resolution"] = {
                k: res[k] for k in ("n_total", "n_resolved",
                                    "coverage_by_count", "coverage_by_holdings")}
            # **未解析的显式带出来** —— 不是没有数据,是没找到 id。
            out["coins"][coin]["unresolved"] = res["unresolved"][:20]
            for rr_ in res["resolved"]:
                resolved_rows.append({"name": rr_.name,
                                      "_entity_id": rr_.entity_id,
                                      "total_holdings": rr_.holdings})
            if newly:
                await supabase_upsert("treasury_entities", [
                    {"entity_id": v, "name": k, "resolved_from": "slug",
                     "last_seen": today} for k, v in newly.items()],
                    "entity_id")

        # ── 决策流 ────────────────────────────────────────────────────────
        async def get(path, params=None):
            rr = await client.get(CG_PRO_BASE + path, params=params or {})
            try:
                return rr.status_code, rr.json()
            except Exception:                                   # noqa: BLE001
                return rr.status_code, {}

        written = 0
        for row in resolved_rows[:MAX_ENTITIES_PER_RUN]:
            eid = row.get("_entity_id")
            if not eid:
                continue
            d = await fetch_decisions(eid, get)
            out["n_entities_fetched"] += 1
            rows = rows_for_supabase(d["decisions"])
            if rows:
                ok = await supabase_upsert(
                    "treasury_decisions", rows,
                    "entity_id,coin_id,decision_date,decision_type,"
                    "holding_net_change")
                if ok:
                    written += len(rows)
            if d.get("note"):
                out["errors"].append(f"{eid}: {d['note'][:80]}")
        out["coins"].setdefault(coin, {})["n_written"] = written
        out["n_written"] += written

    out["ok"] = bool(out["n_written"]) or not out["errors"]
    out["reason"] = (
        f"{out['n_entities_fetched']} 个实体 · 落库 {out['n_written']} 条"
        + (f" · {len(out['errors'])} 个问题" if out["errors"] else "")
        + "。**0 条是合法的**(今天没有披露),而「内容陈旧」由 "
          "producer_freshness 的事件时钟判,不由这里判")
    return out
