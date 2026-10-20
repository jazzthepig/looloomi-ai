"""交易层 v2 纸面账本(docs/TRADING_LAYER_V2.md):凸性单票的前向时钟。

一个内核:票的状态机全部在 Postgres 函数 `r_tickets_scan(p_to, p_from)` 里
(migrations/2026-10-20_r_tickets_paper.sql)。前向就是每天用它推进一个已收盘的 UTC 日;回放就是在一个回滚的
事务里用它从 2020 走到今天 —— 2024 年的信号与研究 SQL(台账 S-620(a) + S-627 的闸门版)逐笔一致:266 张、267.68R。

规则:深跌筑底后放量突破(S-610)· majors 在 200 日线上才开票(否则记 blocked)· 止损 = 进场 − 2.5 × ATR14 ·
收盘破 SMA20 次日开盘出 / 120 根到期 / 停更 10 天按最后收盘出 · 同名不重叠。R 以止损距离为单位,含 0.4% 来回成本;
永续资金费没算进来(交易层 v2 §2 的已知缺口)。

判活:`select last_d from r_tickets_state` ≥ 前天;`loop_attempt` 里 `_r_tickets_paper_loop` 每小时一条;
      `select max(d) from r_money_daily` = last_d(钱曲线,S-638:f = 1%、最多 10 张,只读内核 r_tickets_nav_paper)。
函数在当天的 binance_hist 根数不到前一天的 80%、或 majors 风格指数还没写到那天时**停在前一天**并写明原因
(返回 ok = false、stopped = …)—— 数据没到就不推进,不是失败。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

RULE_VERSION = "r_v2_k2.5_gate200"

#: S-638:钱曲线的参数(f★ = 1%,盯市回撤 −35% 反推;最多同时 10 张)与前向起点(r_tickets_scan 处理的第一天)。
MONEY_F, MONEY_CAP, MONEY_INCEPTION = 0.01, 10, "2026-10-19"
MONEY_TABLE = "r_money_daily"
#: 票与状态(r_tickets_paper / r_tickets_state)由 Postgres 内核自己写;这里只写钱曲线。
WRITES_TABLES = ("r_money_daily",)


def target_day(now: Optional[datetime] = None) -> date:
    """最后一个**已收盘**的 UTC 日。函数自己也拒绝今天(未收盘的日线会改)。"""
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(timezone.utc).date() - timedelta(days=1))


def interpret(res: Any) -> tuple[str, str, dict]:
    """纯函数。RPC 返回 → (状态, 原因, 明细)。状态:ok / refused(数据没到,停在前一天)/ error。"""
    if not isinstance(res, dict):
        return "error", f"r_tickets_scan 返回了 {type(res).__name__},不是 json 对象", {}
    detail = {k: res.get(k) for k in ("from", "to", "last_done", "stopped", "new_pending", "blocked", "filled",
                                      "closed", "void", "open_now", "pending_now", "reason", "last_d") if k in res}
    if res.get("ok") is True:
        why = res.get("reason") or (f"推进到 {res.get('last_done')}:新票 {res.get('new_pending', 0)}、"
                                    f"闸门挡下 {res.get('blocked', 0)}、平仓 {res.get('closed', 0)};"
                                    f"持仓 {res.get('open_now', 0)}")
        return "ok", str(why), detail
    if res.get("busy"):
        return "refused", "另一次 r_tickets_scan 正在跑(咨询锁),这一轮让过", detail
    if res.get("stopped"):
        return "refused", f"数据没到,停在 {res.get('last_done')}:{res.get('stopped')}", detail
    return "error", f"r_tickets_scan 返回 ok = {res.get('ok')!r}", detail


def money_rows(curve: Any) -> list[dict]:
    """纯函数。r_tickets_nav_paper 返回的逐日行 → r_money_daily 行(nav = 权益,ret = 相邻两天之比 − 1)。"""
    out: list[dict] = []
    prev: Optional[float] = None
    for r in sorted((c for c in (curve or []) if isinstance(c, dict) and c.get("d") and c.get("equity") is not None),
                    key=lambda c: str(c["d"])):
        eq = float(r["equity"])
        out.append({"d": str(r["d"])[:10], "nav": round(eq, 8), "ret": round(eq / prev - 1, 10) if prev else 0.0,
                    "realized": r.get("realized"), "unrealized": r.get("unrealized"), "open_n": r.get("open_n"),
                    "gross": r.get("gross"), "taken": r.get("taken"), "skipped": r.get("skipped"),
                    "closed": r.get("closed"), "f": MONEY_F, "cap": MONEY_CAP, "inception": MONEY_INCEPTION,
                    "rule_version": RULE_VERSION})
        prev = eq
    return out


async def write_money() -> dict[str, Any]:
    """钱曲线:同一个只读内核(r_tickets_nav_paper)算出来,经前向锁写进 r_money_daily —— 前天及更早的行不再改。"""
    from src.api.store import supabase_rpc_write
    from src.data.accounting.forward_lock import write_locked
    r = await supabase_rpc_write("r_tickets_nav_paper", {"p_f": MONEY_F, "p_cap": MONEY_CAP}, timeout=60.0)
    if not r.ok:
        return {"ok": False, "why": f"r_tickets_nav_paper 调用失败:{r.why}"[:300]}
    rows = money_rows(r.value)
    if not rows:
        return {"ok": False, "why": "r_tickets_nav_paper 没有返回任何一天(r_tickets_state 读不到?)"}
    w = await write_locked(MONEY_TABLE, rows, key=None, on_conflict="d")
    return {**w, "last_d": rows[-1]["d"], "nav": rows[-1]["nav"], "open_n": rows[-1]["open_n"]}


async def run_once(now: Optional[datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_rpc_write
    p_to = target_day(now)
    # 单日约 8 秒;共享客户端 10 秒会超时重试 —— 给足 120 秒(函数内有咨询锁,重复调用只会拿到 busy)
    r = await supabase_rpc_write("r_tickets_scan", {"p_to": p_to.isoformat()}, timeout=120.0)
    if not r.ok:
        return {"status": "error", "reason": f"r_tickets_scan 调用失败:{r.why}"[:400], "detail": {"p_to": p_to.isoformat()}}
    status, reason, detail = interpret(r.value)
    # 票推进完(或数据没到、停在前一天)都把钱曲线写到 r_tickets_state.last_d;钱曲线写不进去 = 这一轮算失败
    money = await write_money()
    if not money.get("ok") and status != "error":
        status, reason = "error", f"{reason};钱曲线没写进 {MONEY_TABLE}:{money.get('why')}"
    return {"status": status, "reason": reason, "detail": {"p_to": p_to.isoformat(), **detail, "money": money}}
