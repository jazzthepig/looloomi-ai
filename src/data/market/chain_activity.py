"""链的景气读数:每条链每天的 TVL、手续费、DEX 成交量(T-076 / S-526)。

## 为什么

Jazz 10-09:「STRK 是一个很好的案例 —— 类似景气轮动;很多机会是市场普遍没有观察到的,有非常强的预期差」。
景气 = 基本面在变好;预期差 = 基本面变好了、价格还没跟上。链的基本面最直接的三个读数:
锁了多少钱(TVL)、用户付了多少费(fees)、换了多少手(DEX volume)。STRK 个案里 TVL 是平的,
DEX 成交量从 8 月中到 9 月初翻了三倍 —— 先于价格(只是一个个案;横截面检验见 S-526)。

## 取什么

DeFiLlama(免费、无 key):`/v2/chains` 选链(有 gecko_id 且当前 TVL ≥ 1,000 万美元)→ 每条链三次请求
(historicalChainTvl、overview/fees、overview/dexs)。d = 时间戳的 UTC 日期;**今天(UTC)的点不收**(当天未完,
DeFiLlama 会先放一个复制昨天的占位值)。某类数据这条链没有 ⇒ 那一列为空,不补 0。
首次全量回填;之后每天只写最近 10 天(DeFiLlama 会修订近几天),新出现的链全量。

## 判活判据(规则 5b ②)

    select max(d) from chain_activity_daily;   -- = 昨天(UTC)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

TABLE = "chain_activity_daily"
WRITES_TABLES = (TABLE,)
SOURCE = "defillama"
MIN_TVL = 1e7
RECENT_DAYS = 10


def pick_chains(chains: list[dict], min_tvl: float = MIN_TVL) -> list[dict]:
    """纯函数。有 gecko_id(能对上币价)且当前 TVL ≥ min_tvl 的链,按名字排序。"""
    out = [c for c in chains or [] if c.get("gecko_id") and c.get("name") and _f(c.get("tvl")) and _f(c.get("tvl")) >= min_tvl]
    return sorted(out, key=lambda c: c["name"])


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def by_day(points: list[list], today: date) -> dict[str, float]:
    """纯函数。[[unix_ts, 值]] → {UTC 日期: 值};同一天取最后一个;今天及以后丢掉;读不出的值丢掉。"""
    out: dict[str, float] = {}
    for p in points or []:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        try:
            d = datetime.fromtimestamp(int(p[0]), tz=timezone.utc).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        v = _f(p[1])
        if v is None or d >= today:
            continue
        out[d.isoformat()] = v
    return out


def merge_rows(chain: dict, tvl: dict, fees: dict, dex: dict, since: Optional[str] = None) -> list[dict]:
    """纯函数。三条序列按日期合并;since 给定则只留 d ≥ since。"""
    days = sorted(set(tvl) | set(fees) | set(dex))
    if since:
        days = [d for d in days if d >= since]
    now = datetime.now(timezone.utc).isoformat()
    return [{"chain": chain["name"], "d": d, "gecko_id": chain["gecko_id"], "symbol": chain.get("tokenSymbol"),
             "tvl_usd": tvl.get(d), "fees_usd": fees.get(d), "dex_volume_usd": dex.get(d),
             "source": SOURCE, "computed_at": now} for d in days]


async def _known_chains() -> tuple[Optional[str], set[str]]:
    """表里最新的日期,以及那一天出现过的链。空表 ⇒ (None, 空集)。"""
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    rd = await _sb_get(TABLE, {"select": "d", "order": "d.desc", "limit": "1"})
    if not rd.ok:
        raise RuntimeError(f"{TABLE} 读不到:{rd.reason}")
    if not rd.rows:
        return None, set()
    d = rd.rows[0]["d"]
    rows = await _read_all(TABLE, {"select": "chain", "d": f"eq.{d}"})
    return d, {r["chain"] for r in rows}


async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_llama_chain_overview, get_llama_chain_tvl, get_llama_chains_raw
    today = today or datetime.now(timezone.utc).date()
    chains = pick_chains(await get_llama_chains_raw())
    if len(chains) < 20:
        return {"ok": False, "refused": True, "written": 0, "reason": f"只选出 {len(chains)} 条链 —— DeFiLlama /v2/chains 变了?"}
    last_d, known = await _known_chains()
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    written, failed, full = 0, {}, []
    for c in chains:
        try:
            tvl = by_day(await get_llama_chain_tvl(c["name"]), today)
            fees = by_day(await get_llama_chain_overview("fees", c["name"]), today)
            dex = by_day(await get_llama_chain_overview("dexs", c["name"]), today)
        except Exception as e:                              # noqa: BLE001
            failed[c["name"]] = f"{type(e).__name__}: {str(e)[:60]}"
            continue
        since = recent if (last_d and c["name"] in known) else None
        if since is None:
            full.append(c["name"])
        rows = merge_rows(c, tvl, fees, dex, since)
        for i in range(0, len(rows), 2000):
            res = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="chain,d")
            if not res.ok:
                return {"ok": False, "refused": False, "written": written,
                        "reason": f"写入失败({c['name']}):{res.why}"}
            written += len(rows[i:i + 2000])
    if len(failed) >= len(chains) / 2:
        return {"ok": False, "refused": True, "written": written, "reason": f"一半以上的链读不到:{list(failed)[:8]}"}
    return {"ok": not failed, "refused": False, "written": written, "chains": len(chains),
            "full_backfill": full[:60], "failed": failed,
            "reason": f"{len(chains)} 条链写 {written} 行(全量 {len(full)} 条)" + (f";失败 {len(failed)} 条" if failed else "")}
