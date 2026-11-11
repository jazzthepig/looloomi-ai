"""投机仓(手动交易的 HL 子账户)的记分账 —— 只读、只记、不下单(11-12,Jazz)。

## 为什么

Jazz 11-12:「the speculative part should be more agile … our books and systems are based on mid-long term asset
management」。系统账本(T25 / RBv2 / R-v2)是中长期资管;投机仓要敏捷、盯少数资产 —— 他选的做法是
**在一个单独的 HL 子账户里手动交易,系统只读成交结果并记分**(不走执行器:⓪ 判断从提交到成仓要 1–24 小时)。
S-817:把系统票开大不是投机的办法(12 格没有一格过「去掉一张票」)。这张表回答的只有一件事:
**这只手,相对于什么都不做的核心账户,挣没挣到钱** —— 每天一行,写下就是前向记录。

## 从哪来(只要地址,不要 key)

Railway 环境变量 `HL_SPEC_ADDRESS` = 那个子账户的地址(公开地址;**没配 ⇒ 不读不写,不算错**)。地址不进表。
每小时读一次 HL 公开 `/info` 的 `portfolio`:`allTime` 桶最后一个点的账户净值(`accountValueHistory`)与
累计盈亏(`pnlHistory`,HL 自己算的,**不含出入金**)。

## 净值(收益口径)

    ret_d = (cum_pnl_d − cum_pnl_{d−1}) ÷ equity_{d−1}        nav_d = nav_{d−1} × (1 + ret_d);第一行 nav = 1

用累计盈亏的差而不是净值的差 ⇒ 入金、出金不会被当成收益。d = 读到那一刻的 UTC 日期;当天的行每小时覆盖,
过了 UTC 0 点就不再动(当天最后一次读到午夜之间的盈亏落在第二天,累计口径不丢)。上一天净值 ≤ 0 或读不到 ⇒
`ret` / `nav` 留空、`note` 写明(规则 9:不猜)。

判活:`select d, equity_usd, cum_pnl_usd, ret, nav, n_reads, note from spec_account_daily order by d desc limit 3`
(配了地址之后,每小时 `n_reads` + 1)。
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any, Optional

TABLE = "spec_account_daily"
ENV = "HL_SPEC_ADDRESS"
RULE = "spec_account_v1:HL portfolio allTime(净值 = accountValueHistory 末点;收益 = 累计盈亏之差 ÷ 上一天净值;当天每小时覆盖)"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "equity_usd", "cum_pnl_usd", "ret", "nav", "n_reads", "read_at", "note", "rule")}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def last_point(resp: Any, bucket: str = "allTime") -> tuple[Optional[float], Optional[float]]:
    """纯函数。HL `portfolio` 的回包 [[桶名, {accountValueHistory, pnlHistory, vlm}], …] → (账户净值, 累计盈亏) 的最后一个点。
    形状不对 / 桶不在 / 序列为空 ⇒ (None, None) —— 读不到 ≠ 0。"""
    try:
        body = dict(resp).get(bucket) if isinstance(resp, dict) else next((b for name, b in resp if name == bucket), None)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(body, dict):
        return None, None

    def tail(key: str) -> Optional[float]:
        seq = body.get(key) or []
        return _f(seq[-1][1]) if seq and isinstance(seq[-1], (list, tuple)) and len(seq[-1]) >= 2 else None
    return tail("accountValueHistory"), tail("pnlHistory")


def day_row(d: str, equity: Optional[float], cum_pnl: Optional[float], prev: Optional[dict], today: Optional[dict],
            read_at: str) -> dict[str, Any]:
    """纯函数。今天这次读数 + 上一天的行(prev,d 之前最近的一行)+ 今天已有的行(today,只取 n_reads)→ 今天的行。"""
    row: dict[str, Any] = {"d": d, "equity_usd": equity, "cum_pnl_usd": cum_pnl, "ret": None, "nav": None,
                           "n_reads": int((today or {}).get("n_reads") or 0) + 1, "read_at": read_at, "note": None, "rule": RULE}
    if equity is None or cum_pnl is None:
        row["note"] = "HL portfolio 读不到净值或累计盈亏"
        return row
    if not prev:
        row["ret"], row["nav"], row["note"] = 0.0, 1.0, "开账日"
        return row
    pe, pp, pn = _f(prev.get("equity_usd")), _f(prev.get("cum_pnl_usd")), _f(prev.get("nav"))
    if pe is None or pe <= 0 or pp is None:
        row["note"] = f"上一天({str(prev.get('d'))[:10]})净值 ≤ 0 或缺 ⇒ 收益不算"
        return row
    row["ret"] = (cum_pnl - pp) / pe
    if pn is None:
        row["note"] = f"上一天({str(prev.get('d'))[:10]})没有 nav ⇒ 只记当天收益"
    else:
        row["nav"] = pn * (1.0 + row["ret"])
    return row


def scorecard(rows: list[dict], core: list[dict]) -> dict[str, Any]:
    """纯函数。投机仓 nav 与核心账户 nav(`live_account_daily`)在**同一批日期**上的比较;没有共同日 ⇒ 不给数。"""
    s = {str(r["d"])[:10]: _f(r.get("nav")) for r in rows if _f(r.get("nav")) is not None}
    c = {str(r["d"])[:10]: _f(r.get("nav")) for r in core if _f(r.get("nav")) is not None}
    days = sorted(set(s) & set(c))
    if len(days) < 2:
        return {"days": len(days), "why": "共同日不足两天"}
    a, b = days[0], days[-1]
    spec, cor = s[b] / s[a] - 1.0, c[b] / c[a] - 1.0
    peak, peak_d = s[a], a                           # Jazz 11-11:判据是回本时间 —— 现在离上一个高点多少天
    for d in days:
        if s[d] >= peak:
            peak, peak_d = s[d], d
    under = (dt.date.fromisoformat(b) - dt.date.fromisoformat(peak_d)).days
    return {"days": len(days), "from": a, "to": b, "spec_return": spec, "core_return": cor, "excess": spec - cor,
            "days_under_water": under}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.accounting.live_account import hl_info
    from src.data.vector.market_state_writer import _sb_get
    addr = (os.environ.get(ENV) or "").strip()
    if not addr:
        return {"ok": True, "skipped": True, "why": f"{ENV} 没配 —— 投机仓还没开"}
    if not (addr.startswith("0x") and len(addr) == 42):
        return {"ok": False, "why": f"{ENV} 不是 0x + 40 位的地址"}
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = now.date().isoformat()
    equity, cum = last_point(await hl_info({"type": "portfolio", "user": addr}))
    have = await _sb_get(TABLE, {"select": "d,equity_usd,cum_pnl_usd,nav,n_reads", "d": f"lte.{d}", "order": "d.desc", "limit": "2"})
    if not have.ok:
        return {"ok": False, "why": f"读 {TABLE} 失败:{(have.why or '')[:120]}"}
    today = next((r for r in have.rows if str(r["d"])[:10] == d), None)
    prev = next((r for r in have.rows if str(r["d"])[:10] < d), None)
    row = day_row(d, equity, cum, prev, today, now.isoformat())
    if not await supabase_upsert_table(TABLE, [row], on_conflict="d"):
        return {"ok": False, "why": f"写 {TABLE} 失败"}
    return {"ok": row["note"] != "HL portfolio 读不到净值或累计盈亏", "written": d, "ret": row["ret"], "nav": row["nav"],
            "n_reads": row["n_reads"], "why": row["note"]}


async def view() -> dict[str, Any]:
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "d,ret,nav,n_reads,note", "order": "d.asc"})
    core = await _read_all("live_account_daily", {"select": "d,nav", "order": "d.asc"})
    return {"ok": True, "configured": bool((os.environ.get(ENV) or "").strip()), "rule": RULE,
            "scorecard": scorecard(rows or [], core or []), "last": (rows or [])[-5:]}
