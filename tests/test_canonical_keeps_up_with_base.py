"""`ohlcv_daily_canonical` 不许落后于 `ohlcv_daily`(S-361 P0)。

为什么需要这条
==============
2026-09-16 实测:

    ohlcv_daily            基表   最新 2026-09-16
    ohlcv_daily_canonical  视图   最新 2026-08-08     ← 落后 39 天

**视图不会自己陈旧** —— 它在读取时计算。机制:近 7 天写入的 1,770 行
`asset_id` 全是 NULL,而视图是 `JOIN assets`(INNER),整批被丢掉。
所有源在同一周停写 asset_id(binance_hist 08-08 / coingecko 08-07 / eodhd 08-06;
`coingecko_pro_ohlc` 与 `hyperliquid` 从来没写过)。

**这 39 天里没有任何东西报错。** 视图照常返回 485,352 行 —— 只是旧的。
`vdb_health.py` 早就写过这句话:「The read path then returns rows — just old
ones — so no consumer errors either.」同一个形状,换了一张表。

而它被放大了一层:**唯一「守规矩」读 canonical 的 `outcome_tracker` 拿到的是
39 天前的世界,23 处直读基表的代码拿到的是今天的。规矩把守规矩的人害了。**
`docs/SPINE.md` 当时还建议把那 23 处迁到 canonical —— 一份方向基准
把所有人指向了断掉的那一边。

这条守卫查什么
==============
**只查一件事:视图的最新日不许比基表的最新日落后超过 1 天。**

刻意不查原因。已修的两处(LEFT JOIN + coalesce、写入触发器)都是**机制**,
而机制会被下一次重构删掉、绕过、或被第六个写入端忽略。
这条查的是**后果**,所以无论机制怎么变,后果一出现就红。

顺带查第二件:`asset_class` 不许为 NULL。
因为 LEFT JOIN 单独做不够 —— 行回来了但 `asset_class` 变 NULL 的话,
下游普遍写 `where asset_class='Crypto'`,**丢失会从 join 移到 filter,同样静默**。
`coalesce(a.class, o.asset_class)` 是这一条的落实,这里钉住它。

没有凭据时
==========
明确打印 **NOT CHECKED**,不算通过。一个在没凭据时静默变绿的联网守卫,
就是「带绿勾的散文」—— 它会在最需要它的环境里正好不生效。
"""
from __future__ import annotations

import os
import sys

WINDOW_DAYS = 60          # 11-05:只读基表最新日往前 60 天(见 newest 的说明)
MAX_LAG_DAYS = 1


def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not (url and key):
        print("  ⓘ NOT CHECKED — 没有 SUPABASE_URL / SUPABASE_KEY")
        print("    **这不是通过。** 这条守卫只在有凭据的环境(Mac 侧 preflight)生效。")
        return 0

    import httpx

    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}

    def newest(table: str, since: str | None = None) -> str | None:
        """读不到就返回 None ⇒ 判失败。**不许退化成「那就算一致」** ——
        那正是 S-166/S-168 里「读不到被当成没问题」的同一个坑。
        11-05:canonical 是对全表 DISTINCT ON 的视图,基表 153 万行时全量排序 9.3 秒,REST 的语句超时(8 秒)一天红三次;
        带 `trade_date >= since` 时条件下推进 DISTINCT ON(trade_date 是它的键),1.3 秒。窗口外没有行 ⇒ 当作落后超过窗口,照样判失败。"""
        params = {"select": "trade_date", "order": "trade_date.desc", "limit": "1"}
        if since:
            params["trade_date"] = f"gte.{since}"
        try:
            with httpx.Client(timeout=20) as c:
                r = c.get(f"{url}/rest/v1/{table}", params=params, headers=hdr)
        except Exception as e:                      # noqa: BLE001
            print(f"  ✗ 读 {table} 不可达: {type(e).__name__}: {e}")
            return None
        if r.status_code != 200:
            print(f"  ✗ 读 {table} 失败: HTTP {r.status_code} {r.text[:160]}")
            return None
        rows = r.json()
        return rows[0]["trade_date"] if rows else None

    import datetime as dt

    base = newest("ohlcv_daily")
    if base is None:
        print("  ✗ 读不到基表 —— **读不到 ≠ 一致**,判失败")
        return 1
    since = (dt.date.fromisoformat(base) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    canon = newest("ohlcv_daily_canonical", since)
    if canon is None:
        print(f"  ✗ canonical 在 {since} 之后一行都没有(落后超过 {WINDOW_DAYS} 天,或读不到)—— 判失败")
        return 1

    lag = (dt.date.fromisoformat(base) - dt.date.fromisoformat(canon)).days
    ok = lag <= MAX_LAG_DAYS
    print(f"  {'✓' if ok else '✗'} canonical 跟得上基表 :: base={base} canonical={canon} 落后 {lag} 天")
    if not ok:
        print(f"    上限 {MAX_LAG_DAYS} 天。**视图不会自己陈旧,是有行被 join 丢掉了。**")
        print("    先查:select count(*) from ohlcv_daily")
        print("          where trade_date >= current_date-7 and asset_id is null;")

    # 第二条:LEFT JOIN 把行救回来了,但 asset_class 不许因此变 NULL
    with httpx.Client(timeout=20) as c:
        r = c.get(f"{url}/rest/v1/ohlcv_daily_canonical",
                  params={"select": "symbol", "asset_class": "is.null", "trade_date": f"gte.{since}", "limit": "1"},
                  headers={**hdr, "Prefer": "count=exact", "Range": "0-0"})
    n_null = r.headers.get("content-range", "*/0").split("/")[-1]
    ok2 = n_null in ("0", "*")
    print(f"  {'✓' if ok2 else '✗'} canonical.asset_class 无 NULL :: {n_null} 行")
    if not ok2:
        print("    LEFT JOIN 把行救回来了,但 asset_class 丢了 ——")
        print("    **丢失只是从 join 移到了下游的 where asset_class='Crypto'**,同样静默。")

    return 0 if (ok and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
