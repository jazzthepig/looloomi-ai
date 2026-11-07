"""Binance U 本位永续资金费率的历史,从公开月档补到整个 binance_hist 宇宙(S-638 后续)。

## 为什么

`funding_history`(venue = binance_perp)只有 36 个名字,由 `binance_hf_collector` 经 fapi 每天续。
交易层 v2 的单票(S-638)做的是约 180 个名字;在有数据的 36 个上,一张多头票平均付掉 0.08R 资金费 ——
其余的没量过,而山寨突破时资金费通常更高。**成本不知道,钱曲线就是偏乐观的。**

## 从哪里取

`data.binance.vision/data/futures/um/monthly/fundingRate/<PAIR>/<PAIR>-fundingRate-YYYY-MM.zip`:静态月档,
和 T-133 的 metrics 日档同一族、同一个取数入口(`data_layer.get_binance_vision_um_daily(..., monthly=True)`)。
不对 200 个名字每天打 fapi(Jazz 09-09:多资产不许反复打免费 API)。

## 取什么、不取什么

计划 = 视图 `funding_vision_plan`:每个名字从 max(2020-01, 它在 binance_hist 的第一根)到上一个完整 UTC 月,
**减去已经有任何 binance_perp 资金费行的月**(fapi 采集器已有的月一律不重取 —— 不会把它的 mark_price 覆盖成空),
再减去 `funding_vision_absent` 里记过「没有文件」的月。新月优先(前向成本最先要),每轮最多 BUDGET 个文件。

**没有文件 ≠ 取失败。** 404 ⇒ 写进 funding_vision_absent,以后不再取(那个月没上市 / 从来不是永续);
其他错误 ⇒ 不写,下一轮重试。半数以上取失败 ⇒ 整轮拒写。

## 判活

    select count(*) from funding_vision_plan;                                   -- 回补积压,应单调降到个位数
    select max(funding_time) from funding_history where venue = 'binance_perp' and symbol = 'CRV';
"""
from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

PLAN_VIEW = "funding_vision_plan"
TABLE = "funding_history"
ABSENT_TABLE = "funding_vision_absent"
WRITES_TABLES = (TABLE, ABSENT_TABLE)
KIND = "fundingRate"
VENUE = "binance_perp"
#: 11-07:宽宇宙的第一轮一次解析了 2,000 个月档(33 万行)、整批撞外键 —— 预算降到 400(约 6 万行),解析挪进线程。
BUDGET = 400
CONCURRENCY = 16
FAIL_REFUSE_FRACTION = 0.5
#: 11-07:月档在月末之后几天才上传。2026-10 那批在 11-01 取 ⇒ 404 ⇒ 225 个名字被记成「那个月没有文件」、永不再取
#: (GMXUSDT 2026-10 11-07 实测 200)。月末之后这么多天以内的 404 不记缺档,下一轮重试。
ABSENT_GRACE_DAYS = 10
_HOUR_MS = 3_600_000

#: 月档的表头(2020 年起的档都是这一套);旧格式 / 无表头的档按位置读:第一列时间、最后一列费率。
TIME_COLS = ("calc_time", "fundingTime", "funding_time")
RATE_COLS = ("last_funding_rate", "fundingRate", "funding_rate")


def parse_funding_zip(blob: bytes) -> list[tuple[int, float]]:
    """月档 zip → [(毫秒时间, 费率)]。读不出的行跳过,不补 0。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip 里没有 csv")
        text = z.read(names[0]).decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    ti = next((head.index(c) for c in TIME_COLS if c in head), None)
    ri = next((head.index(c) for c in RATE_COLS if c in head), None)
    body = rows[1:]
    if ti is None or ri is None:
        if any(ch.isalpha() for ch in "".join(head)):
            raise ValueError(f"认不出的表头 {head} —— 期望时间列 {TIME_COLS} 之一、费率列 {RATE_COLS} 之一")
        ti, ri, body = 0, len(head) - 1, rows                     # 无表头
    out: list[tuple[int, float]] = []
    for r in body:
        try:
            t, rate = int(float(r[ti])), float(r[ri])
        except (IndexError, TypeError, ValueError):
            continue
        if rate == rate:                                           # 去 NaN
            out.append((t, rate))
    return out


def funding_rows(symbol: str, items: list[tuple[int, float]]) -> list[dict]:
    """与 binance_hf_collector.funding_rows 同一形状(PK 含时间,所以取整到小时)。
    取**最近的**整点而不是向下取整:月档的 calc_time 若落在整点前几毫秒,向下取整会差出一小时。"""
    out = []
    for t, rate in items:
        h = (t + _HOUR_MS // 2) // _HOUR_MS * _HOUR_MS
        ts = datetime.fromtimestamp(h / 1000, tz=timezone.utc).isoformat()
        out.append({"symbol": symbol, "funding_time": ts, "funding_rate": rate, "mark_price": None,
                    "venue": VENUE, "asset_id": symbol})
    return out


def plan(rows: list[dict], budget: int = BUDGET) -> list[tuple[str, str]]:
    """纯函数。视图行 → 这一轮要取的 (名字, 'YYYY-MM'),新月优先,同月按名字。"""
    todo = {(str(r["symbol"]), str(r["month"])[:7]) for r in rows if r.get("symbol") and r.get("month")}
    by_month: dict[str, list[str]] = {}
    for sym, m in todo:
        by_month.setdefault(m, []).append(sym)
    out = [(sym, m) for m in sorted(by_month, reverse=True) for sym in sorted(by_month[m])]
    return out[:budget]


async def _fetch_one(sym: str, month: str, sem: asyncio.Semaphore) -> tuple[Optional[list[dict]], Optional[dict], Optional[str]]:
    """→ (资金费行, 缺档行, 错误)。三者至多一个非空。"""
    from src.data.market.data_layer import get_binance_vision_um_daily
    async with sem:
        try:
            blob = await get_binance_vision_um_daily(KIND, f"{sym}USDT", month, monthly=True)
        except Exception as e:                                       # noqa: BLE001
            return None, None, f"{sym} {month}: {type(e).__name__}: {str(e)[:80]}"
    if blob is None:
        return None, {"symbol": sym, "month": f"{month}-01"}, None
    try:
        rows = await asyncio.to_thread(lambda: funding_rows(sym, parse_funding_zip(blob)))
    except Exception as e:                                           # noqa: BLE001
        return None, None, f"{sym} {month}: parse {type(e).__name__}: {str(e)[:120]}"
    if not rows:
        return None, {"symbol": sym, "month": f"{month}-01"}, None   # 有文件但没有一行可读 —— 同「没有」
    return rows, None, None


def can_mark_absent(month: str, today) -> bool:
    """纯函数。'YYYY-MM' 的月末 + ABSENT_GRACE_DAYS 天已经过去 ⇒ 404 才算「没有文件」;否则只是还没上传。"""
    from datetime import date, timedelta
    y, m = int(month[:4]), int(month[5:7])
    first_next = date(y + (m == 12), m % 12 + 1, 1)
    return today >= first_next + timedelta(days=ABSENT_GRACE_DAYS)


async def _known_assets(read) -> Optional[set[str]]:
    """assets 里登记过的 asset_id;读不到 ⇒ None(不滤,让外键自己说话)。"""
    try:
        return {str(r["asset_id"]) for r in await read("assets", {"select": "asset_id", "order": "asset_id.asc"})}
    except Exception:                                                # noqa: BLE001
        return None


def _dedupe(rows: list[dict]) -> list[dict]:
    """同一小时两条(取整后)只留最后一条 —— 一次 upsert 里 PK 重复会整批失败。"""
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[(r["symbol"], r["funding_time"], r["venue"])] = r
    return list(seen.values())


async def run_once(budget: int = BUDGET) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import MARKET_DATA, assert_purpose_source
    from src.data.style.header import _read_all
    cov = await _read_all(PLAN_VIEW, {"select": "symbol,month"})
    tasks = plan(cov, budget)
    if not tasks:
        return {"ok": True, "refused": False, "reason": "全部已覆盖", "planned": 0, "backlog": 0}
    assert_purpose_source(MARKET_DATA, VENUE, n_assets=len({s for s, _ in tasks}),
                          job="binance perp funding history (monthly archive)", secondary_ok=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    res = await asyncio.gather(*[_fetch_one(s, m, sem) for s, m in tasks])
    rows = _dedupe([r for got, _, _ in res if got for r in got])
    # 11-07:funding_history.asset_id → assets 外键。不在 assets 里的名字(未登记的永续)整批 upsert 会一起失败 ——
    # 先按名字滤掉、报个数,其余照写;登记由 migrations 做,这里不偷偷建 assets 行。
    known = await _known_assets(_read_all)
    unknown = sorted({r["symbol"] for r in rows if known is not None and r["asset_id"] not in known})
    if unknown:
        rows = [r for r in rows if r["asset_id"] in known]
    today = datetime.now(timezone.utc).date()
    absent_all = [a for _, a, _ in res if a]
    absent = [a for a in absent_all if can_mark_absent(str(a["month"])[:7], today)]
    errors = [e for _, _, e in res if e]
    detail = {"planned": len(tasks), "backlog": len(cov), "rows": len(rows), "absent": len(absent),
              "not_yet_published": len(absent_all) - len(absent), "skipped_not_in_assets": unknown[:20],
              "n_skipped_not_in_assets": len(unknown),
              "errors": len(errors), "error_sample": errors[:3],
              "oldest": min(m for _, m in tasks), "newest": max(m for _, m in tasks)}
    if len(errors) > FAIL_REFUSE_FRACTION * len(tasks):
        return {"ok": False, "refused": True, "reason": f"{len(errors)}/{len(tasks)} 个月档读不到 —— 整轮拒写:{errors[:2]}",
                **detail}
    for i in range(0, len(rows), 2000):
        r = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="symbol,funding_time,venue")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{TABLE} 写入失败:{r.why}", **detail}
    if absent:
        r = await supabase_upsert_table(ABSENT_TABLE, absent, on_conflict="symbol,month")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{ABSENT_TABLE} 写入失败:{r.why}", **detail}
    return {"ok": True, "refused": False,
            "reason": f"写入 {len(rows)} 行资金费(缺档 {len(absent)} 个月,失败 {len(errors)};积压 {len(cov)} → 约 {len(cov) - len(tasks) + len(errors)})",
            **detail}
