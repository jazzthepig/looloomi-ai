"""拉取 RWA 面板并落到本地研究面 (S-266).

**本地优先**,与 S-261 同一条纪律:Supabase 是免费版(实测 50.7% 已用),
而 CG Pro 是 Analyst 档 500,000 次/月、实测只用了 0.4%。约束在存储那边,
不在调用那边 —— 所以研究阶段的历史攒在本地 sqlite,确认有用再谈进生产库。

## 调用预算

    /rwas/markets     每天 1–2 次(per_page=250,翻页到取完)
    /rwas/issuers/list 每天 1 次

日频 ≤3 次 ⇒ 一个月 ~90 次 ⇒ **占 500,000 额度的 0.018%**。

## 为什么翻页要按「返回条数」停,不按预设页数

`per_page=250` 是**单页上限,不是总数**。2026-09-01 实测第 1 页返回 250 条 ——
一个恰好等于上限的返回值,是「还有更多」最典型的形状。按固定页数拉会静默截断,
而截断后的总量看起来完全正常:少了一半的面板,求和结果仍是一个像样的美元数。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from src.data.rwa.panel import RwaRow, parse_rows, snapshot

CG_BASE = "https://pro-api.coingecko.com/api/v3"
PER_PAGE = 250          # 单页上限
MAX_PAGES = 20          # 硬上限:5,000 条。超过它更可能是翻页逻辑坏了,不是面板变大
LOCAL_DB = "/tmp/cometcloud_data/rwa.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rwa_daily (
    d              TEXT NOT NULL,
    rwa_id         TEXT NOT NULL,
    name           TEXT,
    symbol         TEXT,
    asset_type     TEXT,
    issuer         TEXT,
    market_cap     REAL,          -- NULL = 未测,**不是 0**(I1)
    total_volume   REAL,
    mcap_change_24h REAL,
    turnover       REAL,
    PRIMARY KEY (d, rwa_id)
);
CREATE TABLE IF NOT EXISTS rwa_panel_daily (
    d                    TEXT PRIMARY KEY,
    n_rows               INTEGER,
    -- ⚠️ 这两列是**股票/ETF 口径**,不是 n_rows 那个全面板口径。
    -- 实测 2026-09-01:n_rows=646、equity 已测=644、商品 2 条不进这个口径。
    -- 不标注就会有人算 646−644=2 并以为有 2 条未测。
    equity_n_measured    INTEGER,
    equity_n_unmeasured  INTEGER,
    equity_like_total    REAL,
    equity_like_verdict  TEXT NOT NULL,   -- 裁决与数值同行落库(S-263 同一形状)
    equity_like_reason   TEXT,
    by_asset_type_json   TEXT,
    by_issuer_json       TEXT
);
"""


def _headers() -> dict:
    key = os.environ.get("COINGECKO_API_KEY", "")
    if not key:
        raise RuntimeError(
            "COINGECKO_API_KEY 未设置。这个仓库【没有任何代码加载 .env】(S-246)——"
            "Railway 上是真的环境变量,本地裸跑读到的是空。"
            "先:  set -a; source .env; set +a")
    return {"x-cg-pro-api-key": key}


async def fetch_markets(*, client=None) -> list[dict]:
    """拉全部 RWA。**按返回条数停,不按预设页数**(见模块 docstring)。"""
    import httpx
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    out: list[dict] = []
    try:
        for page in range(1, MAX_PAGES + 1):
            r = await client.get(
                f"{CG_BASE}/rwas/markets", headers=_headers(),
                params={"per_page": PER_PAGE, "page": page,
                        "order": "market_cap_desc"})
            r.raise_for_status()
            batch = r.json() or []
            out.extend(batch)
            if len(batch) < PER_PAGE:      # 不满一页 ⇒ 到底了
                break
        else:
            raise RuntimeError(
                f"翻到第 {MAX_PAGES} 页仍是满页 —— 更可能是翻页逻辑坏了而不是"
                f"面板真有 {MAX_PAGES * PER_PAGE}+ 条。**不静默截断。**")
    finally:
        if own:
            await client.aclose()
    return out


async def fetch_issuer_map(*, client=None) -> dict[str, str]:
    """rwa_id → issuer_id。**按发行方反查,不是从一个清单里读出来。**

    ⚠️ 第一版猜错了形状:我假设 `/rwas/issuers/list` 会带每个发行方的资产清单,
    去读 `it["rwas"]`。实测 2026-09-01 返回 `issuer_map_size: 0` —— 因为该端点
    **只返回 `[{id, name}]`**,没有资产清单。文档写明它的用途是:
    「get issuer IDs for endpoints that require an `issuer` parameter」。

    所以正确路径是拿到 id 之后,用 `/rwas/markets?issuer=<id>` 逐个过滤反查。

    **这次猜错没有造成脏数据**,因为第一版在形状不符时返回空 dict 而不是猜 ——
    于是所有行落进可见的 `unknown` 桶,`issuer_map_size: 0` 直接把问题报了出来。
    一个诚实的空值比一个编出来的映射便宜得多:错的映射会把某个发行方的集中度
    算到另一家头上,而曲线看起来完全正常。

    调用成本:发行方数 N 次(+1 次拿清单)。N 约几十 ⇒ 日频 ~30 次
    ⇒ 月 ~900 次 ⇒ 占 500,000 额度的 0.18%。
    """
    import httpx
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    out: dict[str, str] = {}
    try:
        r = await client.get(f"{CG_BASE}/rwas/issuers/list", headers=_headers())
        r.raise_for_status()
        issuers = r.json() or []
        if not isinstance(issuers, list):
            return {}
        for it in issuers:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id") or "").strip()
            if not iid:
                continue
            try:
                m = await client.get(
                    f"{CG_BASE}/rwas/markets", headers=_headers(),
                    params={"issuer": iid, "per_page": PER_PAGE})
                m.raise_for_status()
                for row in m.json() or []:
                    rid = str((row or {}).get("id") or "").strip()
                    if not rid:
                        continue
                    # 一只资产可能被多家发行方代币化。**先到先得 + 记冲突**,
                    # 而不是后写覆盖 —— 覆盖会让集中度悄悄归到最后遍历到的那家。
                    if rid in out and out[rid] != iid:
                        out[f"__conflict__{rid}"] = f"{out[rid]}|{iid}"
                        continue
                    out[rid] = iid
            except Exception:                                  # noqa: BLE001
                continue        # 单个发行方失败不拖垮整张映射
    except Exception:                                          # noqa: BLE001
        return {}
    finally:
        if own:
            await client.aclose()
    return out


def write_local(rows: list[RwaRow], snap: dict, *, db_path: str = LOCAL_DB) -> int:
    """落本地研究面。裁决与数值**同行**写入,不拆到两张表。"""
    import json
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        d = snap["d"]
        con.executemany(
            "INSERT OR REPLACE INTO rwa_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(d, r.rwa_id, r.name, r.symbol, r.asset_type, r.issuer,
              r.market_cap, r.total_volume, r.mcap_change_24h, r.turnover)
             for r in rows])
        con.execute(
            "INSERT OR REPLACE INTO rwa_panel_daily VALUES (?,?,?,?,?,?,?,?,?)",
            (d, snap["n_rows"], snap["equity_like_n_measured"],
             snap["equity_like_n_unmeasured"],
             snap["equity_like_total"], snap["equity_like_verdict"],
             snap["equity_like_reason"],
             json.dumps(snap["by_asset_type"], ensure_ascii=False),
             json.dumps(snap["by_issuer"], ensure_ascii=False)))
        con.commit()
        return len(rows)
    finally:
        con.close()


async def collect(*, dry_run: bool = True, db_path: str = LOCAL_DB) -> dict:
    """一次采集。`dry_run=True` 默认 —— 看过再写。"""
    payload = await fetch_markets()
    issuer_of = await fetch_issuer_map()
    rows = parse_rows(payload, issuer_of=issuer_of)
    snap = snapshot(rows)
    # 冲突键不是映射,单独计数 —— 一只资产被多家代币化是真实现象,
    # 而把它混进 map 大小会让「覆盖率」虚高。
    conflicts = [k for k in issuer_of if k.startswith("__conflict__")]
    snap["issuer_map_size"] = len(issuer_of) - len(conflicts)
    snap["issuer_conflicts"] = len(conflicts)
    snap["issuer_coverage"] = (
        round(snap["issuer_map_size"] / snap["n_rows"], 3) if snap["n_rows"] else None)
    snap["dry_run"] = dry_run
    if not dry_run:
        snap["rows_written"] = write_local(rows, snap, db_path=db_path)
    return snap
