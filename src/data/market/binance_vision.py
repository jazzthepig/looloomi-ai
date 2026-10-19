"""Binance 公开历史档 → 永续持仓结构的日度特征(T-133)。

## 为什么

Jazz 10-19:「交易要和当时的资金流、盘口结合,跟踪 smart money」,并且「先不买数据,在现有数据源想办法」。
data.binance.vision 的 U 本位永续 `metrics` 档免费、免账号:5 分钟一条的未平仓量、大户多空比(按账户 / 按持仓)、
全体多空比、主动买卖量比;BTC 从 2020-09-01 起,后上市的从上市日起,每天上传前一天。
这是「谁在买」的五年历史 —— S-610 的 R 臂下一层要用它把赢家和输家分开(预注册在数据落库之后写)。

## 落什么

`deriv_metrics_daily`:每个名字每个 UTC 日一行 ——
收盘未平仓量(张 / 美元)、大户持仓多空比(收盘、日均)、大户账户多空比(收盘)、全体账户多空比(收盘)、
主动买卖量比(日均、最后 4 小时均值)、点数 n_points。
**文件不存在的日子写一行 n_points = 0、其余为空**(只对 3 天前及更早的日子写:最近两天可能只是还没上传)——
「没有数据」被记下来,下一轮就不会再去取;它和「取数失败」(不写,下一轮重试)是两件事。

## 怎么取

宇宙 = `ohlcv_daily` binance_hist 在册名字(剔除 USDC / BTCDOM / DEFI),交易对 = 名字 + USDT。
每轮最多取 `BUDGET` 个文件:先补各名字最近缺的日子(新到旧),再按名字轮转往回补到 max(上市日, 2020-09-01)。
取数只经 `data_layer.get_binance_vision_um_daily`(取数入口只减不增)。半数以上请求失败 ⇒ 整轮拒写并写明
(Railway 的出口有时落在美国 —— egress probe 已在记)。

## 判活

    select count(*), max(d) from deriv_metrics_daily where n_points > 0 and symbol = 'BTC';   -- max(d) ≥ 前天
    select * from deriv_metrics_plan where min_d is null or min_d > target_start limit 20;      -- 回补进度
"""
from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

TABLE = "deriv_metrics_daily"
PLAN_VIEW = "deriv_metrics_plan"
WRITES_TABLES = (TABLE,)
KIND = "metrics"
SOURCE = "binance_vision_metrics"
BUDGET = 6000
CONCURRENCY = 16
FINAL_AFTER_DAYS = 3
BACKFILL_CHUNK = 20
FAIL_REFUSE_FRACTION = 0.5
REQUIRED = ("create_time", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def parse_metrics_zip(blob: bytes) -> list[dict]:
    """纯函数。metrics 日档(zip 里一个 csv)→ 行;缺必需列 ⇒ ValueError 写明缺哪几列(不猜列名)。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip 里没有 csv")
        text = z.read(names[0]).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"metrics 缺列 {missing};实际列 {reader.fieldnames}")
    return list(reader)


def daily_features(symbol: str, day: str, rows: list[dict]) -> dict:
    """纯函数。一天的 5 分钟行 → 一行日度特征。只收时间戳落在该 UTC 日的行;一行都没有 ⇒ n_points = 0。"""
    pts = sorted((r for r in rows if str(r.get("create_time", ""))[:10] == day), key=lambda r: r["create_time"])

    def last(col: str) -> Optional[float]:
        for r in reversed(pts):
            v = _f(r.get(col))
            if v is not None:
                return v
        return None

    def mean(col: str, rs: list[dict]) -> Optional[float]:
        vals = [v for v in (_f(r.get(col)) for r in rs) if v is not None]
        return round(sum(vals) / len(vals), 6) if vals else None

    tail = [r for r in pts if str(r["create_time"])[11:13] >= "20"]
    return {"symbol": symbol, "d": day, "oi_close": last("sum_open_interest"),
            "oi_value_close": last("sum_open_interest_value"),
            "top_pos_ratio_close": last("sum_toptrader_long_short_ratio"),
            "top_pos_ratio_mean": mean("sum_toptrader_long_short_ratio", pts),
            "top_acct_ratio_close": last("count_toptrader_long_short_ratio"),
            "global_acct_ratio_close": last("count_long_short_ratio"),
            "taker_ratio_mean": mean("sum_taker_long_short_vol_ratio", pts),
            "taker_ratio_last4h": mean("sum_taker_long_short_vol_ratio", tail),
            "n_points": len(pts), "source": SOURCE}


def absent_row(symbol: str, day: str) -> dict:
    """那天没有文件:记下来(n_points = 0,特征全空),不再重取。"""
    return {"symbol": symbol, "d": day, "oi_close": None, "oi_value_close": None, "top_pos_ratio_close": None,
            "top_pos_ratio_mean": None, "top_acct_ratio_close": None, "global_acct_ratio_close": None,
            "taker_ratio_mean": None, "taker_ratio_last4h": None, "n_points": 0, "source": SOURCE}


def _d(x: Any) -> Optional[date]:
    return date.fromisoformat(str(x)[:10]) if x else None


def plan(coverage: list[dict], today: date, budget: int = BUDGET, chunk: int = BACKFILL_CHUNK) -> list[tuple[str, str]]:
    """纯函数。覆盖情况 → 这一轮要取的 (名字, 日)。先补各名字最近缺的(新到旧),再按名字轮转往回补。
    coverage 每行:symbol / target_start(max(上市日, 2020-09-01))/ last_d(binance_hist 最后一根)/ min_d / max_d。"""
    fwd: list[tuple[str, str]] = []
    back: dict[str, list[str]] = {}
    for c in sorted(coverage, key=lambda r: r["symbol"]):
        sym, start, last = c["symbol"], _d(c.get("target_start")), _d(c.get("last_d"))
        if not start or not last:
            continue
        end = min(last, today - timedelta(days=1))
        lo, hi = _d(c.get("min_d")), _d(c.get("max_d"))
        if hi is None:
            back[sym] = [(end - timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
            continue
        d = end
        while d > hi:
            fwd.append((sym, d.isoformat()))
            d -= timedelta(days=1)
        if lo and lo > start:
            back[sym] = [(lo - timedelta(days=i)).isoformat() for i in range(1, (lo - start).days + 1)]
    out = sorted(fwd, key=lambda t: t[1], reverse=True)[:budget]
    while len(out) < budget and any(back.values()):
        for sym in list(back):
            take, back[sym] = back[sym][:chunk], back[sym][chunk:]
            out += [(sym, d) for d in take]
            if len(out) >= budget:
                break
    return out[:budget]


async def _fetch_one(sym: str, day: str, today: date, sem: asyncio.Semaphore) -> tuple[Optional[dict], Optional[str]]:
    from src.data.market.data_layer import get_binance_vision_um_daily
    async with sem:
        try:
            blob = await get_binance_vision_um_daily(KIND, f"{sym}USDT", day)
        except Exception as e:                                       # noqa: BLE001
            return None, f"{sym} {day}: {type(e).__name__}: {str(e)[:80]}"
    if blob is None:
        final = date.fromisoformat(day) <= today - timedelta(days=FINAL_AFTER_DAYS)
        return (absent_row(sym, day) if final else None), None
    try:
        return daily_features(sym, day, parse_metrics_zip(blob)), None
    except Exception as e:                                           # noqa: BLE001
        return None, f"{sym} {day}: parse {type(e).__name__}: {str(e)[:120]}"


async def run_once(today: Optional[date] = None, budget: int = BUDGET) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or datetime.now(timezone.utc).date()
    cov = await _read_all(PLAN_VIEW, {"select": "symbol,target_start,last_d,min_d,max_d"})
    tasks = plan(cov, today, budget)
    if not tasks:
        return {"ok": True, "refused": False, "reason": "全部已覆盖", "fetched": 0, "rows": 0}
    sem = asyncio.Semaphore(CONCURRENCY)
    res = await asyncio.gather(*[_fetch_one(s, d, today, sem) for s, d in tasks])
    rows = [r for r, _ in res if r]
    errors = [e for _, e in res if e]
    detail = {"planned": len(tasks), "rows": len(rows), "absent": sum(1 for r in rows if r["n_points"] == 0),
              "errors": len(errors), "error_sample": errors[:3],
              "oldest": min(d for _, d in tasks), "newest": max(d for _, d in tasks)}
    if len(errors) > FAIL_REFUSE_FRACTION * len(tasks):
        return {"ok": False, "refused": True, "reason": f"{len(errors)}/{len(tasks)} 个文件读不到 —— 整轮拒写:{errors[:2]}",
                **detail}
    for i in range(0, len(rows), 1000):
        r = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="symbol,d")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{TABLE} 写入失败:{r.why}", **detail}
    return {"ok": True, "refused": False, "reason": f"写入 {len(rows)} 行(缺档 {detail['absent']},失败 {len(errors)})",
            **detail}
