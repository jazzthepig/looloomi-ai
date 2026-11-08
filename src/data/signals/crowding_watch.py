"""被挤空头(squeeze)与被洗多头(flush)的前向记录(11-08,S-726 / S-777 / S-781)—— 对手盘族里「强制成交」那一支。

## 研究说了什么

事件(S-726 写死,S-777 加两条日级守卫):7 日均资金费落到自身扩张分位 ≤ 10%(空头拥挤)、当天涨 ≥ 2 ATR14、成交 ≥ 3 倍 20 日均
⇒ squeeze;镜像 ⇒ flush;同合约 10 天去重。内核 = 库里的 `crowding_events()`(lane-b T-295 的提案,Seth 审后落库,
迁移 `2026-11-08_crowding_events.sql`)。

**S-781(资金费补全之后重量):** 干净 squeeze 351 个(2019-12 → 2026-11),之后 30 天相对时点等权永续篮中位 **−16.4%**、
为负 74%、同币同年随机日对照分位 0.000(对照中位 −5.1%)、两半 −4.8% / −16.5%;**均值只有 −1.0%**(对照 +4.0%,
分位 0.056):典型的一次跑输,右尾(+100% 以上的几次)把均值拉回到零附近。按预注册只立前向记录,不进任何规则。

## 口径

- 结果:d+1 开盘 → d+1 / d+7 / d+30 收盘(窗口内最后一个收盘),减同一进出窗口的时点等权篮;没价就空着,不写 0。
- cohort:d ≥ `FORWARD_FROM`(S-781 用的数据止于 2026-11-04)= forward;之前 = backfill(= S-781 的样本,只作对照)。
- 一天一次(`crowding_events` 每次扫全史 ~30 秒);只重算最近 `LOOKBACK_D` 天的事件(更早的都已到期结算)。
  表是空的 ⇒ 第一次从 2019-12-31 起全量写(backfill)。

判活:`select cohort, kind, count(*), count(x30), max(d) from crowding_watch group by 1, 2`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "crowding_watch"
RPC = "crowding_watch_rows"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("kind", "symbol", "d", "fund_pct", "ret", "atr_thr", "qv_mult", "cohort", "x1", "x7", "x30",
                          "basket_n", "code_ref", "settled_at")}
CODE_REF = "crowding_watch v1 (11-08, S-777 clean kernel / S-781)"
FORWARD_FROM = dt.date(2026, 11, 5)
HISTORY_FROM = dt.date(2019, 12, 31)
LOOKBACK_D = 45
RPC_TIMEOUT_S = 330.0
DONE_KEY = "crowding_watch:{d}"
_NUM = ("fund_pct", "ret", "atr_thr", "qv_mult", "x1", "x7", "x30")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def to_rows(raw: list[dict], now: dt.datetime) -> list[dict]:
    """纯函数。RPC 行 → 表行:cohort 按事件日;x30 有值才记结算时间;数字一律转 float,NaN / 空 ⇒ None。"""
    out = []
    for r in raw or []:
        d = str(r.get("d") or "")[:10]
        kind = r.get("kind")
        if len(d) != 10 or kind not in ("squeeze", "flush") or not r.get("symbol"):
            continue
        row = {"kind": kind, "symbol": str(r["symbol"]).upper(), "d": d,
               **{k: _f(r.get(k)) for k in _NUM},
               "basket_n": int(r["basket_n"]) if r.get("basket_n") is not None else None,
               "cohort": "forward" if dt.date.fromisoformat(d) >= FORWARD_FROM else "backfill",
               "code_ref": CODE_REF, "settled_at": None}
        if row["x30"] is not None:
            row["settled_at"] = now.astimezone(dt.timezone.utc).isoformat()
        out.append(row)
    return out


def window_start(today: dt.date, table_empty: bool) -> dt.date:
    """纯函数。表空 ⇒ 全量;否则只重算最近 LOOKBACK_D 天(更早的事件 x30 都已到期)。"""
    return HISTORY_FROM if table_empty else today - dt.timedelta(days=LOOKBACK_D)


async def run_once(now: Optional[dt.datetime] = None, *, force: bool = False) -> dict[str, Any]:
    from src.api.store import redis_get_key_status, redis_set_key, supabase_rpc_write, supabase_upsert_table
    from src.data.vector.market_state_writer import _sb_get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    key = DONE_KEY.format(d=today.isoformat())
    if not force:
        st, _ = await redis_get_key_status(key)
        if st == "hit":
            return {"ok": True, "skipped": True, "why": f"今天({today})已经跑过"}
    have = await _sb_get(TABLE, {"select": "d", "order": "d.desc", "limit": "1"})
    if not have.ok:
        return {"ok": False, "why": f"读 {TABLE} 失败:{(have.why or '')[:120]}"}
    p_from = window_start(today, not have.rows)
    r = await supabase_rpc_write(RPC, {"p_from": p_from.isoformat()}, timeout=RPC_TIMEOUT_S)
    if not r.ok:
        return {"ok": False, "why": f"{RPC} 失败(客户端 {RPC_TIMEOUT_S:.0f} s):{(r.why or '')[:160]}"}
    raw = r.value if isinstance(r.value, list) else []
    if len(raw) >= 1000:                   # PostgREST 单次最多回 1,000 行;回满 = 被截(korea_premium_watch 11-08 首轮踩过)
        return {"ok": False, "why": f"{RPC}(自 {p_from})回了 {len(raw)} 行 = 上限,被截了 —— 要分段"}
    rows = to_rows(raw, now)
    for i in range(0, len(rows), 500):
        if not await supabase_upsert_table(TABLE, rows[i:i + 500], on_conflict="kind,symbol,d"):
            return {"ok": False, "why": f"写 {TABLE} 失败(第 {i} 行起)"}
    await redis_set_key(key, {"at": now.isoformat(), "rows": len(rows)}, ttl=2 * 86400)
    fwd = [x for x in rows if x["cohort"] == "forward"]
    tail = ", ".join("%s:%s@%s" % (x["kind"][0], x["symbol"], x["d"]) for x in fwd[-5:]) or "无"
    return {"ok": True, "written": len(rows), "forward": len(fwd), "from": p_from.isoformat(),
            "settled_30d": sum(1 for x in rows if x["x30"] is not None),
            "why": f"拥挤事件 {len(rows)} 条(自 {p_from},前向 {len(fwd)}:{tail})"}
