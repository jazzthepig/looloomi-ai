"""散户投机热度(11-07,对手盘族):Meme 发射台 + Telegram 交易机器人 + 散户交易 App 的每日手续费。

## 为什么

「疯狂的散户」在全市场层面最直接的痕迹不是价格,而是**他们付的手续费**:pump.fun / four.meme 这类发射台、Trojan / BONKbot /
Banana Gun 这类 Telegram 机器人、Axiom / Photon / GMGN 这类 meme 交易终端 —— 用户几乎全是散户投机者,机构不用。它们一天收多少钱,
就是散户一天往赌桌上推了多少。我们之前没有任何一条这样的序列(`protocol_revenue_daily` 只有 10-21 起的快照、而且是收入不是费用)。

## 口径

- 协议 = DeFiLlama 费用概览里 category ∈ {Launchpad, Telegram Bot, Trading App},按**累计费用**取前 `TOP_N` 个(今天的前 25 个占这三类
  累计费用约 93%)。按今天的排名选 ⇒ 2023 年那批(Unibot、BullX)仍在里面(DeFiLlama 保留已停的协议),但今天还不存在的将来的
  协议当然不在;历史上的「全部」会被略低估,**不是前视**(每一天的值只用那一天的费用)。
- 每个协议 `/summary/fees/{slug}?dataType=dailyFees` 的整段日序列(UTC 日;今天那一格不落)。一天一次(Redis 记)。
- 免费源请求量(登记):每天 1 + `TOP_N` = 26 次,间隔 0.5 秒。

判活:`select count(distinct slug), min(d), max(d), sum(fees_usd) filter (where d = current_date - 1) from degen_fees_daily`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "degen_fees_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("slug", "name", "category", "d", "fees_usd")}
CATEGORIES = ("Launchpad", "Telegram Bot", "Trading App")
TOP_N = 25
OVERVIEW = "https://api.llama.fi/overview/fees"
SUMMARY = "https://api.llama.fi/summary/fees/{slug}"
DONE_KEY = "degen:fees_refresh:{d}"
SLEEP_S = 0.5


def pick(protocols: list[dict], n: int = TOP_N) -> list[dict]:
    """纯函数。概览 → 这三类里累计费用最高的 n 个(slug、名字、类别)。"""
    c = [p for p in protocols or [] if p.get("category") in CATEGORIES and p.get("slug")]
    c.sort(key=lambda p: -(p.get("totalAllTime") or 0))
    return [{"slug": p["slug"], "name": p.get("name") or p["slug"], "category": p["category"]} for p in c[:n]]


def rows(proto: dict, chart: list, today: dt.date) -> list[dict]:
    """纯函数。[[unix, 费用], …] → 行;今天(没收完)那一格丢掉,负数 / 空值丢掉。"""
    out = []
    for pt in chart or []:
        try:
            d = dt.datetime.fromtimestamp(int(pt[0]), tz=dt.timezone.utc).date()
            v = float(pt[1])
        except (TypeError, ValueError, IndexError, OSError):
            continue
        if d >= today or v != v or v < 0:
            continue
        out.append({"slug": proto["slug"], "name": proto["name"], "category": proto["category"], "d": d.isoformat(), "fees_usd": v})
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    import httpx
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    key = DONE_KEY.format(d=today.isoformat())
    st, _ = await redis_get_key_status(key)
    if st:
        return {"ok": True, "skipped": True, "why": f"今天已取过({st.get('at')})"}
    errors: list[str] = []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=40, headers={"User-Agent": "CometCloud-degen/1.0"}) as client:
        r = await client.get(OVERVIEW, params={"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true",
                                               "dataType": "dailyFees"})
        if r.status_code != 200:
            return {"ok": False, "why": f"DeFiLlama 费用概览 HTTP {r.status_code}"}
        protos = pick((r.json() or {}).get("protocols") or [])
        for p in protos:
            await asyncio.sleep(SLEEP_S)
            try:
                rr = await client.get(SUMMARY.format(slug=p["slug"]), params={"dataType": "dailyFees"})
                if rr.status_code != 200:
                    errors.append(f"{p['slug']}: HTTP {rr.status_code}")
                    continue
                out += rows(p, (rr.json() or {}).get("totalDataChart") or [], today)
            except Exception as e:                                        # noqa: BLE001
                errors.append(f"{p['slug']}: {type(e).__name__}")
    for i in range(0, len(out), 1000):
        if not await supabase_upsert_table(TABLE, out[i:i + 1000], on_conflict="slug,d"):
            return {"ok": False, "why": f"写 {TABLE} 失败", "errors": errors}
    ok = len(protos) > 0 and len(errors) <= len(protos) // 5
    if ok:
        await redis_set_key(key, {"at": now.isoformat(), "rows": len(out)}, ttl=2 * 86400)
    y = (today - dt.timedelta(days=1)).isoformat()
    tot_y = sum(x["fees_usd"] for x in out if x["d"] == y)
    return {"ok": ok, "protocols": len(protos), "rows": len(out), "errors": errors[:10],
            "why": f"{len(protos)} 个协议、{len(out)} 行;昨天合计 ${tot_y / 1e6:.2f}M" + (f" · 错 {len(errors)}" if errors else "")}
