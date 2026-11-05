"""HL 已实现小时资金费率(S-733)—— `fundingHistory` 逐名分页,带回填,进 `hl_funding_hourly`。

## 为什么另起一张表,不写进 `funding_history`

`funding_history`(venue = hyperliquid)是 `metaAndAssetCtxs` 的**不定时快照**(每天 6–14 个,当下预测的费率);
这里是 HL 结算过的**已实现**小时费率(每小时一个,`fundingHistory`)。两个看着像同一个量、不是同一个量的序列
(S-273 / S-274 / S-275 那一类)不进同一张表。④ 套息的纸面账(`signals/carry_hl.py`)只读这张。

## 范围(S-296:成交场馆的扇出必须显式给名单)

名单 = ① 面板 24 名(`core_cap.panel_universe()`);回填起点 2023-05-01(HL 小时档从 2023-05-12 起)。
**每个名字每天最多取一次**(昨天的 24 个小时档齐了就跳过;Jazz 11-05 批准的免费源例外,`source_policy.FREE_BULK_EXCEPTIONS`);回填期间每轮最多 `MAX_PAGES_PER_RUN` 页、页间 `PAUSE_S` 秒(HL info 权重:fundingHistory 每页约 45,每分钟 1,200);
一轮没回填完下一轮接着从 `last_t` 往后取 —— 升序分页,所以只要每个名字的 `last_t` 往前走,就不会漏中间。

判活:`select coin, last_t, n from hl_funding_hourly_last order by last_t limit 3`(最旧的 last_t 应在 2 小时内);
回填进度看 `loop_attempt` 里 `_hl_funding_hourly_loop` 的 written / pages / behind。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Callable, Optional

TABLE = "hl_funding_hourly"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("coin", "t", "rate", "premium")}
LAST_VIEW = "hl_funding_hourly_last"
DAILY_VIEW = "hl_funding_daily"
LOOP_NAME = "_hl_funding_hourly_loop"
CODE_REF = "hl_funding_hourly v1 (11-05, S-733)"
BACKFILL_FROM = "2023-05-01"
PAGE = 500
MAX_PAGES_PER_RUN = 400
PAUSE_S = 2.5


def coins() -> tuple[str, ...]:
    from src.data.signals.core_cap import panel_universe
    return tuple(panel_universe())


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def parse_page(raw: Any, coin: str) -> list[dict]:
    """纯函数。fundingHistory 的一页 → 行。坏行(缺时间 / 费率非数 / 别的币)丢掉,不猜。"""
    out = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict) or (it.get("coin") not in (None, coin)):
            continue
        try:
            t = int(it["time"]); rate = float(it["fundingRate"])
        except (KeyError, TypeError, ValueError):
            continue
        if rate != rate:
            continue
        try:
            prem = float(it.get("premium")) if it.get("premium") is not None else None
        except (TypeError, ValueError):
            prem = None
        out.append({"coin": coin, "t": dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).isoformat(), "rate": rate, "premium": prem,
                    "_ms": t})
    return out


def next_start(rows: list[dict], start_ms: int) -> Optional[int]:
    """纯函数。下一页的 startTime = 本页最大时间 + 1 毫秒;没前进 ⇒ None(防死循环)。"""
    if not rows:
        return None
    nxt = max(r["_ms"] for r in rows) + 1
    return nxt if nxt > start_ms else None


def start_for(last_t: Optional[str]) -> int:
    """纯函数。库里有 ⇒ 从最后一条往后;没有 ⇒ 回填起点。"""
    if not last_t:
        return _ms(BACKFILL_FROM)
    return int(dt.datetime.fromisoformat(str(last_t).replace("Z", "+00:00")).timestamp() * 1000) + 1


def due(start_ms: int, day_start_ms: int) -> bool:
    """纯函数。这个名字今天还要不要取:昨天 23:00 那个小时档还没有 ⇒ 要(回填期间一直是「要」);有了 ⇒ 今天不再取。"""
    return start_ms <= day_start_ms - 3_600_000


async def run_once(now: Optional[dt.datetime] = None, post: Optional[Callable[[dict], Any]] = None,
                   max_pages: int = MAX_PAGES_PER_RUN, pause_s: float = PAUSE_S) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_free_bulk_exception
    from src.data.style.header import _read_all
    names = coins()
    # Jazz 11-05:免费场馆上的多资产作业逐条批准 —— 这一条登记在 source_policy.FREE_BULK_EXCEPTIONS(≤ 24 名;回填一次性,之后每名每天一次)
    assert_free_bulk_exception("hl_funding_hourly", "hyperliquid", n_assets=len(names))
    if post is None:
        from src.data.market.hyperliquid_collector import info_post_sync as post
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    last = {r["coin"]: r.get("last_t") for r in await _read_all(LAST_VIEW, {"select": "coin,last_t"})}
    pages = written = 0
    per: dict[str, int] = {}
    failed: dict[str, str] = {}
    day_start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    skipped = 0
    for c in names:
        start = start_for(last.get(c))
        if not due(start, day_start_ms):
            skipped += 1
            continue
        while pages < max_pages and start < now_ms - 3_600_000:
            try:
                raw = await asyncio.to_thread(post, {"type": "fundingHistory", "coin": c, "startTime": start})
            except Exception as e:                                         # noqa: BLE001 —— 一个名字不通不挡其余
                failed[c] = f"{type(e).__name__}: {str(e)[:120]}"
                break
            pages += 1
            rows = parse_page(raw, c)
            if not rows:
                break
            w = await supabase_upsert_table(TABLE, [{k: v for k, v in r.items() if k != "_ms"} for r in rows], on_conflict="coin,t")
            if not w:
                return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}", "written": written, "pages": pages}
            written += len(rows); per[c] = per.get(c, 0) + len(rows)
            nxt = next_start(rows, start)
            if nxt is None or len(rows) < PAGE:
                break
            start = nxt
            await asyncio.sleep(pause_s)
    behind = pages >= max_pages
    return {"ok": not failed, "written": written, "pages": pages, "per_coin": per, "failed": failed or None, "behind": behind,
            "skipped_today": skipped,
            "why": (f"写 {written} 行 / {pages} 页" + (" · 页数用完,下一轮接着回填" if behind else "")
                    + (f" · 不通:{', '.join(sorted(failed))}" if failed else ""))}
