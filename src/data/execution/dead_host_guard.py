"""主机死了的那一段(11-02,Jazz「1、5、3 这周我直接做」的第 3 条):Railway 看着真钱,主机不在时把该做的事说出来。

## 为什么需要它

X1V 现货的盘中灾难止损**只在东京主机上跑**(`runner.check_stops`,每 60 秒拿现价比计划里的止损线)。主机死了,
这条线就没人看 —— `_executor_host_watch_loop` 会报「主机 N 小时没回报」,但不会说**此刻有没有一条止损线已经被穿过**。
R-v2 单票的止损是 HL 上的减仓触发单(交易所侧,主机死了照样触发),但如果那张触发单没挂上(主机每 15 分钟重挂),
主机一死,那张票就是裸的。

HL 现货的触发单:**11-02 在真钱账户上验证过 —— HL 拒收**(`Placing trigger orders is not enabled on spot trading yet.`,
限价 / 市价触发两种都拒;探针 `exec_host/probe_spot_trigger`,每月 1 号的简报提醒重跑)。对冲空单又被 10-21 的裁定排除
(降敞口 = 卖现货 + 放贷)。所以 X1V 现货没有交易所侧的底,DECISIONS 11-02:现在只报警;第一笔外部钱或 T25 > $5 万时
上独立账户 + key + 第二台待命主机。这里做 Railway 能独立做的事:

1. **现货止损线被穿 + 主机沉默 ⇒ Telegram**(写明哪个币、现价、线、持有多少、约合多少美元、一键停是不是开着)。
   Railway 没有钥匙,**不下单**;这条是让 Jazz 在 HL 网页上手动处理或先把主机拉起来。
2. **永续仓位没有减仓触发单 ⇒ Telegram**:主机沉默时立刻报;主机在时要连续两次(≥ 10 分钟)都裸着才报
   (进场成交到挂触发单之间有几秒的正常空档,主机自己也每 15 分钟重挂)。

## 读什么

全部是 HL 公开接口(只要地址,地址取最后一次心跳的 `trade_account`,不进表):`spotClearinghouseState`、
`clearinghouseState`、`frontendOpenOrders` 经 `live_account.hl_info`;现货盘口经 `dry_run._spot_quotes_sync`(同一个
HlSpotClient);止损线经 `host_plan.plan_core`(主机收到的同一条线)。**不开新的取数路径**(S-302)。

## 不做什么

不下单、不撤单、不改一键停。报警同一天同一件事只发一次(Redis `exec:deadguard:sent:{d}`)。

判活:`select at, outcome, left(reason, 120) from loop_attempt where loop_name = '_dead_host_guard_loop' order by at desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

LOOP_NAME = "_dead_host_guard_loop"
HOST_SILENT_H = 2.0                 # 与 _executor_host_watch_loop 同一个口径(主机每小时心跳)
SENT_KEY = "exec:deadguard:sent:{d}"
NAKED_KEY = "exec:deadguard:naked"
MIN_NOTIONAL_USD = 10.0


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def spot_breaches(stop_px: dict, balances: dict[str, float], mids: dict[str, float],
                  spot_tokens: dict[str, str], min_notional: float = MIN_NOTIONAL_USD) -> list[dict[str, Any]]:
    """纯函数。与主机 `core.stop_hits` 同一条规则:持仓 ≥ 最小名义额 且 现价 < 止损线。balances = {代币: 数量}。"""
    out = []
    for sym, tok in sorted(spot_tokens.items()):
        line, mid, qty = _f((stop_px or {}).get(sym)), _f(mids.get(sym)), _f(balances.get(tok)) or 0.0
        if not line or not mid:
            continue
        if qty * mid >= min_notional and mid < line:
            out.append({"symbol": sym, "token": tok, "qty": qty, "mid": mid, "line": round(line, 4),
                        "usd": round(qty * mid, 2), "below_pct": round((mid / line - 1) * 100, 2)})
    return out


def naked_perps(ch_state: Any, open_orders: Any) -> list[dict[str, Any]]:
    """纯函数。`clearinghouseState` 里每个非零仓位,有没有一张同币、reduceOnly 的触发单挂着。没有 ⇒ 裸。"""
    protected = set()
    for o in open_orders if isinstance(open_orders, list) else []:
        if o.get("isTrigger") and o.get("reduceOnly"):
            protected.add(str(o.get("coin")))
    out = []
    for ap in (ch_state or {}).get("assetPositions") or [] if isinstance(ch_state, dict) else []:
        pos = (ap or {}).get("position") or {}
        szi = _f(pos.get("szi")) or 0.0
        if szi == 0 or str(pos.get("coin")) in protected:
            continue
        out.append({"coin": pos.get("coin"), "szi": szi, "entry_px": _f(pos.get("entryPx")),
                    "value_usd": _f(pos.get("positionValue")), "upnl": _f(pos.get("unrealizedPnl")),
                    "liq_px": _f(pos.get("liquidationPx"))})
    return out


def decide(host_age_h: Optional[float], breaches: list[dict], naked: list[dict], prev_naked: set[str],
           already_sent: set[str], halted: bool) -> list[dict[str, str]]:
    """纯函数。→ 这一轮要发的报警 [{key, text}]。主机在时现货越线不报(主机自己会止);裸仓位要连续两轮才报。"""
    silent = host_age_h is None or host_age_h > HOST_SILENT_H
    age = "从没回报过" if host_age_h is None else f"{host_age_h:.1f} 小时没有回报"
    out = []
    if silent:
        for b in breaches:
            key = f"spot:{b['symbol']}"
            if key in already_sent:
                continue
            out.append({"key": key, "text": (
                f"[dead-host guard] 主机 {age},而 {b['symbol']} 现价 {b['mid']:g} 已在灾难止损线 {b['line']:g} 之下 "
                f"({b['below_pct']:+.2f}%)。账上 {b['qty']:g} {b['token']} ≈ ${b['usd']:,.0f} 没人平。"
                + (" 一键停开着 —— 主机就算活着也不会提交。" if halted else "")
                + " Railway 没有钥匙、不会下单:请先把主机拉起来(Vultr 控制台),拉不起来就在 HL 网页上手动处理这部分现货。")})
    for n in naked:
        key = f"perp:{n['coin']}"
        if key in already_sent or not (silent or n["coin"] in prev_naked):
            continue
        out.append({"key": key, "text": (
            f"[dead-host guard] 永续 {n['coin']} 仓位 {n['szi']:g}(≈ ${abs(n['value_usd'] or 0):,.0f},"
            f"开仓价 {n['entry_px']}, 强平价 {n['liq_px']})**没有减仓触发单**"
            + (f",主机 {age}" if silent else ",已连续两轮(≥ 10 分钟)")
            + "。交易所侧没有止损,这张票是裸的。主机在 ⇒ 看 executor_host 回报里 trigger 的错误;主机不在 ⇒ 在 HL 网页上补一张止损或手动处理。")})
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    from src.api.store import redis_get_key_status, redis_set_key
    from src.data.accounting.live_account import hl_info
    from src.data.execution.dry_run import SPOT_TOKENS, _spot_quotes_sync
    from src.data.execution.host_plan import plan_core, read_halt
    from src.data.style.header import _read_all
    from src.data.venues.hl_spot import HlSpotClient
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    rows = await _read_all("loop_attempt", {"select": "at,detail", "loop_name": "eq.executor_host",
                                            "order": "at.desc", "limit": "40"})
    last_at = rows[0].get("at") if rows else None
    age_h = ((now - dt.datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))).total_seconds() / 3600
             if last_at else None)
    addr = next((str((r.get("detail") or {}).get("trade_account")) for r in rows
                 if (r.get("detail") or {}).get("trade_account")), None)
    if not addr:
        return {"ok": False, "why": "最近 40 条主机回报里没有账户地址 —— 无从独立看账"}
    # 现货:余额 + 盘口 + 止损线
    spot = await hl_info({"type": "spotClearinghouseState", "user": addr})
    bal = {str(b.get("coin")): float(b.get("total")) for b in (spot or {}).get("balances") or [] if _f(b.get("total")) is not None}
    asof = (now.date() - dt.timedelta(days=1)).isoformat()
    core = await plan_core(asof)
    if not core.get("ok"):                                   # 今天的收盘没齐 ⇒ 用前一天的线(主机缓存的也是它)
        core = await plan_core((now.date() - dt.timedelta(days=2)).isoformat())
    stop_px = core.get("stop_px") or {}
    quotes = await asyncio.to_thread(_spot_quotes_sync, HlSpotClient(), None)
    mids = {s: q.get("mid") for s, q in quotes.items()}
    breaches = spot_breaches(stop_px, bal, mids, SPOT_TOKENS)
    # 永续:仓位 + 挂着的触发单
    ch = await hl_info({"type": "clearinghouseState", "user": addr})
    oo = await hl_info({"type": "frontendOpenOrders", "user": addr})
    naked = naked_perps(ch, oo)
    prev, _st = await redis_get_key_status(NAKED_KEY)
    prev_naked = set((prev or {}).get("coins") or [])
    sent_key = SENT_KEY.format(d=now.date().isoformat())
    sent, _st2 = await redis_get_key_status(sent_key)
    already = set((sent or {}).get("keys") or [])
    halted, _hs = await read_halt()
    alerts = decide(age_h, breaches, naked, prev_naked, already, halted)
    await redis_set_key(NAKED_KEY, {"coins": [n["coin"] for n in naked], "at": now.isoformat()}, ttl=3600)
    delivered = []
    if alerts:
        from src.api.notify import notify_telegram
        for a in alerts:
            if await notify_telegram(a["text"]):
                delivered.append(a["key"])
        if delivered:
            await redis_set_key(sent_key, {"keys": sorted(already | set(delivered))}, ttl=2 * 86400)
    return {"ok": True, "host_age_h": None if age_h is None else round(age_h, 2), "stop_asof": core.get("asof"),
            "breaches": breaches, "naked": naked, "alerts": [a["key"] for a in alerts], "delivered": delivered,
            "why": (f"主机 {age_h:.1f}h" if age_h is not None else "主机无回报")
                   + f" · 越线 {len(breaches)} · 裸仓 {len(naked)} · 报 {len(delivered)}/{len(alerts)}"}
