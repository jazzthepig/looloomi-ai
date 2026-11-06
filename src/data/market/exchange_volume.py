"""各场所日成交量(CoinGecko Analyst `/exchanges/{id}/volume_chart/range`,BTC 计价,2021 起可回填 —— Jazz 11-06「先把 Analyst API 用足」)。

**为什么要它:** 「谁在买」是因,价格是果。同一份成交量按场所拆开就是三个我们没有的维度 ——
- **Coinbase 现货占比**:美国机构 / 合规资金的相对强弱(Coinbase 溢价的量版本);
- **韩国(Upbit + Bithumb)现货占比**:散户狂热的经典刻度;
- **衍生品 ÷ 现货**、**链上永续(HL / Aster / Lighter)占衍生品的份额**:投机杠杆与场所迁移。

**时点:** 一个点 `[ts, volume]` 记在 `d = ts 的 UTC 日期` —— 这个值在 ts 时刻已经可得(它是 ts 之前的量),
所以按 d 收盘使用不会看见未来;代价是最多晚一天。**口径:** CoinGecko 的场所量(BTC),含它的清洗;只比份额,不比绝对值。

**取法:** 每个场所每轮:先补最新一段(1 次);再从已有最早日往回走 30 天一段,直到 2021-01-01 或某段为空
(场所当时还不存在 —— 下一轮会再试一次,一个场所一次请求,可以接受)。每轮最多 `MAX_CALLS` 次(450);有积压时循环每小时一轮。
判活:`select exchange, min(d), max(d), count(*) from exchange_volume_daily group by 1 order by 1`。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Optional

TABLE = "exchange_volume_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "exchange", "kind", "volume_btc", "fetched_at")}
LOOP_NAME = "_exchange_volume_loop"

SPOT = ("binance", "gdax", "okex", "bybit_spot", "upbit", "bithumb", "kraken", "bitget", "gate", "kucoin", "huobi", "bitstamp",
        "crypto_com", "mxc")
DERIV = ("binance_futures", "bybit", "okex_swap", "hyperliquid", "bitget_futures", "gate_futures", "deribit", "bitmex", "cme_futures",
         "huobi_dm", "aster", "lighter")
START = dt.date(2021, 1, 1)
CHUNK_DAYS = 30            # 端点要求 from–to 在 31 天以内
MAX_CALLS = 450            # 11-06:Analyst 每分钟 500 次;回补约 2,000 次一次性,450/轮 ≈ 4 轮补完
PAUSE_S = 0.15


def kind_of(exchange: str) -> str:
    return "deriv" if exchange in DERIV else "spot"


def parse(points: Any, exchange: str, fetched_at: str) -> list[dict]:
    """纯函数。`[[ts_ms, "volume"], ...]` → 每天一行(同一天多个点取最后一个);非正 / 坏值丢掉。"""
    by_d: dict[str, tuple[float, float]] = {}
    for p in points if isinstance(points, list) else []:
        try:
            ts, v = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (v > 0) or v != v:
            continue
        d = dt.datetime.fromtimestamp(ts / 1000, tz=dt.timezone.utc).date().isoformat()
        if d not in by_d or ts >= by_d[d][0]:
            by_d[d] = (ts, v)
    return [{"d": d, "exchange": exchange, "kind": kind_of(exchange), "volume_btc": round(v, 4), "fetched_at": fetched_at}
            for d, (_, v) in sorted(by_d.items())]


def plan(have_min: Optional[str], have_max: Optional[str], today: dt.date) -> list[tuple[dt.date, dt.date, str]]:
    """纯函数。一个场所这一轮要取的段(新 → 旧):[(from, to, 'forward'|'back'), ...]。不含次数上限。"""
    if not have_max:
        segs, end = [], today
    else:
        lo = max(dt.date.fromisoformat(have_max) - dt.timedelta(days=2), START)
        segs, end = [(lo, today, "forward")], dt.date.fromisoformat(have_min or have_max) - dt.timedelta(days=1)
    while end >= START:
        start = max(end - dt.timedelta(days=CHUNK_DAYS - 1), START)
        segs.append((start, end, "back"))
        end = start - dt.timedelta(days=1)
    return segs


async def _bounds(exchange: str) -> tuple[Optional[str], Optional[str]]:
    from src.data.vector.market_state_writer import _sb_get
    out = []
    for order in ("d.asc", "d.desc"):
        rd = await _sb_get(TABLE, {"select": "d", "exchange": f"eq.{exchange}", "order": order, "limit": "1"})
        if not rd.ok:
            raise RuntimeError(f"{TABLE} 读不到:{rd.reason}")
        out.append(str(rd.rows[0]["d"])[:10] if rd.rows else None)
    return out[0], out[1]


async def run_once(now: Optional[dt.datetime] = None, fetch=None, bounds=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    real = fetch is None
    if fetch is None:
        from src.data.market.data_layer import CG_API_KEY, CG_PRO_BASE, _cg_headers, _get_cg_client
        if not CG_API_KEY:
            return {"ok": False, "refused": True, "why": "COINGECKO_API_KEY 没配"}

        async def fetch(ex: str, a: dt.date, b: dt.date):
            f = int(dt.datetime(a.year, a.month, a.day, tzinfo=dt.timezone.utc).timestamp())
            t = min(int(dt.datetime(b.year, b.month, b.day, 23, 59, 59, tzinfo=dt.timezone.utc).timestamp()), int(now.timestamp()))
            r = await _get_cg_client().get(f"{CG_PRO_BASE}/exchanges/{ex}/volume_chart/range", headers=_cg_headers(),
                                           params={"from": str(f), "to": str(t)}, timeout=30)
            if r.status_code != 200:                                      # 11-06 首轮 26 次全错、原因没留下 ⇒ 状态码 + 正文开头进 why
                raise RuntimeError(f"HTTP {r.status_code} {r.text[:160]}")
            return r.json()
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    bounds = bounds or _bounds
    calls, written, errors, backlog = 0, 0, [], False
    for ex in SPOT + DERIV:
        lo, hi = await bounds(ex)
        for a, b, kind in plan(lo, hi, today):
            if calls >= MAX_CALLS:
                backlog = True
                break
            calls += 1
            try:
                rows = parse(await fetch(ex, a, b), ex, now.isoformat())
            except Exception as e:                                        # noqa: BLE001
                errors.append(f"{ex} {a}: {type(e).__name__}: {str(e)[:200]}")
                break
            if rows:
                if not await upsert(TABLE, rows, on_conflict="d,exchange"):
                    return {"ok": False, "why": f"写 {TABLE} 失败({ex})", "calls": calls, "written": written}
                written += len(rows)
            elif kind == "back":
                break                                                      # 场所那时还不存在 —— 不往更早走
            if real:
                await asyncio.sleep(PAUSE_S)
        if calls >= MAX_CALLS:
            backlog = True
            break
    ok = written > 0 or (calls > 0 and not errors)
    return {"ok": ok, "calls": calls, "written": written, "backlog": backlog, "errors": errors[:8],
            "why": f"{calls} 次请求 · 写 {written} 行" + (" · 还有积压" if backlog else "") + (f" · 错 {len(errors)}:{errors[0]}" if errors else "")}
