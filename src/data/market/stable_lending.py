"""稳定币借贷池的日度 TVL 与存款 APY(T-066 / S-513)。

## 为什么

S-508:稳定币总量(USDT + USDC 30 日增长)在 2023–24 之后 30 天 +10%,在 2025–26 之后 30 天 −7% ——
**总量翻号**,链上美元在增长,却出现在下跌之前。总量混着支付、生息、避险;「有没有人借稳定币去加杠杆」
才是风险偏好本身。Aave 上 USDC / USDT 的存款 APY 由借款需求驱动(利用率越高 APY 越高),是这个需求最直接的读数。

## 取什么

DeFiLlama yields(免费、一次 `/pools` 找池子 + 每池一次 `/chart`,4 个池,不是扇出):
Aave v2 与 v3、以太坊、USDC 与 USDT,每组取 TVL 最大的那个池。v2 覆盖 2023 年初(v3 以太坊 2023-02 才有)。
d = 时间戳的 UTC 日期(DeFiLlama 每天约 23:00 UTC 取一次点)。读不到的池整轮报出来,不补 0。

## 判活判据(规则 5b ②)

    select max(d) from stable_lending_daily;   -- = 昨天或今天(UTC)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

TABLE = "stable_lending_daily"
WRITES_TABLES = (TABLE,)
SOURCE = "defillama_yields_chart"
PROJECTS = ("aave-v2", "aave-v3")
CHAIN = "Ethereum"
SYMBOLS = ("USDC", "USDT")


def pick_pools(pools: list[dict]) -> list[dict]:
    """纯函数。每个 (project, symbol) 取 TVL 最大的以太坊池。"""
    best: dict[tuple[str, str], dict] = {}
    for p in pools or []:
        if p.get("project") in PROJECTS and p.get("chain") == CHAIN and p.get("symbol") in SYMBOLS:
            k = (p["project"], p["symbol"])
            if k not in best or float(p.get("tvlUsd") or 0) > float(best[k].get("tvlUsd") or 0):
                best[k] = p
    return [best[k] for k in sorted(best)]


def chart_rows(pool: dict, points: list[dict]) -> list[dict]:
    """纯函数。同一天多个点取最后一个;apyBase 读不出的那天 apy_base 为空,不补 0。"""
    by_day: dict[str, dict] = {}
    for x in points or []:
        ts = str(x.get("timestamp") or "")
        if len(ts) < 10:
            continue
        by_day[ts[:10]] = x
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for d in sorted(by_day):
        x = by_day[d]
        out.append({"d": d, "pool_id": pool["pool"], "project": pool["project"], "chain": pool["chain"],
                    "symbol": pool["symbol"], "tvl_usd": _f(x.get("tvlUsd")), "apy_base": _f(x.get("apyBase")),
                    "source": SOURCE, "computed_at": now})
    return out


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_llama_pool_chart, get_llama_pools_raw
    pools = pick_pools(await get_llama_pools_raw())
    if len(pools) < 2:
        return {"ok": False, "refused": True, "written": 0, "reason": f"只找到 {len(pools)} 个池 —— 池子筛选或 DeFiLlama 变了"}
    rows: list[dict] = []
    failed: dict[str, str] = {}
    for p in pools:
        try:
            rows += chart_rows(p, await get_llama_pool_chart(p["pool"]))
        except Exception as e:                              # noqa: BLE001
            failed[f"{p['project']}:{p['symbol']}"] = f"{type(e).__name__}: {str(e)[:80]}"
    if failed and len(failed) >= len(pools) / 2:
        return {"ok": False, "refused": True, "written": 0, "reason": f"一半以上的池读不到:{failed}"}
    for i in range(0, len(rows), 2000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="d,pool_id")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    return {"ok": not failed, "refused": False, "written": len(rows),
            "pools": [f"{p['project']}:{p['symbol']}" for p in pools], "failed": failed,
            "reason": f"{len(pools)} 个池写 {len(rows)} 行" + (f";失败 {failed}" if failed else "")}
