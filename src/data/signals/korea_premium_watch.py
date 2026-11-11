"""韩国人对一个币多付多少钱(S-771 P 读法 B / S-786,11-08)的前向记录 —— 对手盘族里「按币的散户溢价」。只描述,不进任何敞口。

## 研究说了什么

S-771(lane-a T-292):每周一按币的韩国溢价(扣掉 BTC 自己的溢价)对之后 4 周相对 BTC,301 周周 IC −0.027、NW t −2.58、
市值加权最高 − 最低五分位扣 20 bps 后 −2.18% / 4 周 —— 但 **S-784 盲复算(lane-c T-302)说它口径依赖**:预注册的「过去 7 天中位」
没写清作用在价格上还是比值上;先对价格取中位 ⇒ IC +0.005、打乱 0.749(全不过);每天先算溢价再取中位(= 这里的读法 B)⇒ 四条全过。
⇒ **P 不记 ✅;读法 B 只能前向判(S-786,2027-05 起、≥ 26 个到期周)。** 折价那一头(韩国人在割肉)之后也不跑赢。

## 口径(SQL 函数 `korea_premium_rows`,迁移 `2026-11-08_korea_premium_watch.sql`)

- P_i = ln(Upbit KRW 收盘_i / Binance 现货收盘_i) − ln(同上_BTC),周一 t 往前 7 天中位(≥ 5 天);截面 = 当天 Binance 现货有价、市值 ≥ 2,000 万。
- q = 截面五分位(5 = 多付最多);结果 x28 = t+1 收盘 → t+29 收盘相对 BTC,到期才有、没价空着。
- 每天一次:重算最近 `RECENT_D` 天(把到期的结算掉);历史按 8 周一段往回补(一轮 8 段,Redis 游标),补到 `HISTORY_FROM`。
  **每段必须 < 1,000 行**(PostgREST 单次上限;回满 1,000 行 ⇒ 当成被截、整轮报错,不写半段)。
- cohort:t ≥ `FORWARD_FROM` = forward;之前 = backfill(S-771 的样本,只作对照)。

判活:`select cohort, count(distinct d), count(*), count(x28), max(d) from korea_premium_watch group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "korea_premium_watch"
RPC = "korea_premium_rows"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "symbol", "p7", "n_days", "mcap", "q", "n_cs", "x28", "cohort", "code_ref", "settled_at")}
CODE_REF = "korea_premium_watch v1 (11-08, S-771 读法 B;前向判 S-786)"
FORWARD_FROM = dt.date(2026, 11, 9)
HISTORY_FROM = dt.date(2021, 1, 4)
RECENT_D = 42
CHUNK_D = 56            # 8 个周一 × ≤ 90 个币 < 1,000 行(PostgREST 的单次上限)
MAX_CHUNKS = 8          # 一轮补 8 段 ≈ 一年;约 6 轮补到 2021-01
PAGE_MAX = 1000
CURSOR_KEY = "korea_premium_watch:backfill_cursor:v2"   # v2:v1 一年一段被截,游标重新从最近往回全部重写一遍
RPC_TIMEOUT_S = 150.0
DONE_KEY = "korea_premium_watch:{d}"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def to_rows(raw: list[dict], now: dt.datetime) -> list[dict]:
    """纯函数。RPC 行 → 表行;p7 读不出来的行丢掉(表里非空);x28 有值才记结算时间。"""
    out = []
    for r in raw or []:
        d = str(r.get("d") or "")[:10]
        p7 = _f(r.get("p7"))
        if len(d) != 10 or not r.get("symbol") or p7 is None:
            continue
        x28 = _f(r.get("x28"))
        out.append({"d": d, "symbol": str(r["symbol"]).upper(), "p7": p7,
                    "n_days": int(r["n_days"]) if r.get("n_days") is not None else None, "mcap": _f(r.get("mcap")),
                    "q": int(r["q"]) if r.get("q") is not None else None,
                    "n_cs": int(r["n_cs"]) if r.get("n_cs") is not None else None, "x28": x28,
                    "cohort": "forward" if dt.date.fromisoformat(d) >= FORWARD_FROM else "backfill",
                    "code_ref": CODE_REF,
                    "settled_at": now.astimezone(dt.timezone.utc).isoformat() if x28 is not None else None})
    return out


def chunks(cursor: dt.date, n: int = MAX_CHUNKS) -> list[tuple[dt.date, dt.date]]:
    """纯函数。从游标往回切 n 段(每段 CHUNK_D 天,截在 HISTORY_FROM);游标已过 HISTORY_FROM ⇒ []。"""
    out, end = [], cursor
    while end >= HISTORY_FROM and len(out) < n:
        a = max(HISTORY_FROM, end - dt.timedelta(days=CHUNK_D - 1))
        out.append((a, end))
        end = a - dt.timedelta(days=1)
    return out


def truncated(rows: list) -> bool:
    """纯函数。PostgREST 一次最多回 1,000 行(11-08 首轮就被截了:一年一段 ≈ 3,900 行只回来 1,000,中间留了 37 周的洞)。"""
    return len(rows or []) >= PAGE_MAX


async def run_once(now: Optional[dt.datetime] = None, *, force: bool = False) -> dict[str, Any]:
    from src.api.store import redis_get_key_status, redis_set_key, supabase_rpc_write, supabase_upsert_table
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    key = DONE_KEY.format(d=today.isoformat())
    if not force:
        _, st = await redis_get_key_status(key)      # 返回 (payload, status) —— 11-11 之前写反了,当日闸从没生效
        if st == "hit":
            return {"ok": True, "skipped": True, "why": f"今天({today})已经跑过"}
    cur, _cst = await redis_get_key_status(CURSOR_KEY)
    cursor = dt.date.fromisoformat(cur["next_end"]) if cur and cur.get("next_end") else today - dt.timedelta(days=RECENT_D + 1)
    bfs = chunks(cursor)
    windows = [(today - dt.timedelta(days=RECENT_D), today)] + bfs
    written, settled, fwd = 0, 0, 0
    for a, b in windows:
        r = await supabase_rpc_write(RPC, {"p_from": a.isoformat(), "p_to": b.isoformat()}, timeout=RPC_TIMEOUT_S)
        if not r.ok:
            return {"ok": False, "why": f"{RPC}({a} → {b}) 失败:{(r.why or '')[:160]}", "written": written}
        raw = r.value if isinstance(r.value, list) else []
        if truncated(raw):
            return {"ok": False, "why": f"{RPC}({a} → {b}) 回了 {len(raw)} 行 = 上限,被截了 —— 段要再切短", "written": written}
        rows = to_rows(raw, now)
        for i in range(0, len(rows), 500):
            if not await supabase_upsert_table(TABLE, rows[i:i + 500], on_conflict="d,symbol"):
                return {"ok": False, "why": f"写 {TABLE} 失败({a} → {b},第 {i} 行起)", "written": written}
        written += len(rows)
        settled += sum(1 for x in rows if x["x28"] is not None)
        fwd += sum(1 for x in rows if x["cohort"] == "forward")
        if (a, b) in bfs:                     # 每补完一段就推游标(中途失败,下一轮从没补的那段接着来)
            await redis_set_key(CURSOR_KEY, {"next_end": (a - dt.timedelta(days=1)).isoformat(), "at": now.isoformat()},
                                ttl=400 * 86400)
    await redis_set_key(key, {"at": now.isoformat(), "rows": written}, ttl=2 * 86400)
    span = f"回补 {bfs[-1][0]} → {bfs[0][1]}" if bfs else f"历史已补到 {HISTORY_FROM}"
    return {"ok": True, "written": written, "settled": settled, "forward": fwd,
            "backfill": [bfs[-1][0].isoformat(), bfs[0][1].isoformat()] if bfs else "done",
            "why": f"韩国溢价 {written} 行(前向 {fwd},已结算 {settled});{span}"}
