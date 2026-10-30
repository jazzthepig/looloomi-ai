"""执行器的每日空跑(T-122,TRADE_PATH §5 第 1–2 天)—— 现在就在 Railway 上跑,不等钱包。

## 为什么现在就跑

X1V 的降回撤靠**及时出场**(S-602 模拟五:出场推迟 3 天 BTC 回撤 −39% → −64%)。规则要求 UTC 收盘后 1 小时内出单,
而信号要等收盘价落库(CoinGecko 的前一日收盘 00:06–00:54 UTC 才到)。**这条时间线能不能守住,不需要私钥就能量** ——
空跑每天记下「收盘 → 计划就绪」用了几分钟、订单多大、按真实盘口估的滑点多少。钱包与云主机(T-015)到位时,
这里已经有一段记录,真下单只是在同一份计划后面接签名与提交。

## 一轮做什么

1. 前一个 UTC 日的收盘必须已在库(`forward_books.tom_inputs`,与 tom_trader 前向账本同一份价)—— 没到 ⇒ `refused`,等下一次。
2. 目标 = `executor.target_weights`(与前向账本同一个核);纸面账户 3,000 USDC,持仓 = 前一天收盘定下的目标 × 账户净值
   (空跑不记盈亏,量的是计划、尺寸与时效)。**有了 HL 主账户地址(公开信息)就改读真实余额。**
3. 价格 = HL 现货 UBTC / UETH 的盘口中间价(`hl_spot`,只读;一轮 4 个请求),过期即拒(`plan_orders`)。
4. 订单按 szDecimals 向下取整、查最小名义额、按真实盘口估滑点;**超出快照可见深度 = 未知,拒单,不当数值用**(T-123 更正)。
5. 灾难止损判定(当前价 < 前 20 日最低收盘 × 0.92)一并记下。
6. 意图写 `execution_intents`(`sleeve = x1v_spot_dry`),整轮结果进 `loop_attempt`。**不下单。**
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Optional

PAPER_ACCOUNT_USD = 3_000.0
SPOT_TOKENS = {"BTC": "UBTC", "ETH": "UETH"}
SLEEVE = "x1v_spot_dry"
#: 收盘后多久之内算「及时」(TRADE_PATH §3c)
ON_TIME_MIN = 60


def minutes_after_close(now: dt.datetime) -> float:
    """纯函数。距最近一次 UTC 00:00 收盘的分钟数。"""
    close = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - close).total_seconds() / 60.0


def size_orders(orders: list[dict], quotes: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """纯函数。计划里的名义额 → 现货数量(向下取整到 szDecimals)、最小名义额、按盘口估滑点。
    返回 (sized, refused)。超出可见深度(inf)或缺报价 ⇒ 拒,写明原因。"""
    from src.data.venues.hl_spot import estimate_slippage_bps, min_notional_ok, round_size
    sized, refused = [], []
    for o in orders:
        q = quotes.get(o["symbol"])
        if not q or not q.get("mid"):
            refused.append(f"{o['symbol']}:没有盘口报价")
            continue
        qty = round_size(o["notional_usd"] / q["mid"], int(q["sz_decimals"]))
        notional = qty * q["mid"]
        if not min_notional_ok(notional):
            refused.append(f"{o['symbol']}:取整后 {notional:.2f} USDC 低于最小名义额")
            continue
        slip = estimate_slippage_bps(q["book"], o["side"], qty, q["mid"]) if qty > 0 else float("nan")
        if slip == float("inf"):
            refused.append(f"{o['symbol']}:{qty} 超出快照可见深度 —— 深度未知,不估")
            continue
        sized.append({**o, "pair": q["pair"], "qty_base": qty, "notional_rounded": round(notional, 2),
                      "est_slippage_bps": round(slip, 3), "bid": q.get("bid"), "ask": q.get("ask")})
    return sized, refused


def _spot_quotes_sync(client=None, tokens: Optional[dict[str, str]] = None) -> dict[str, dict]:
    """HL 现货的盘口(默认 UBTC / UETH,4 个只读请求;`tokens` = {记账名: 代币名},10-30 起 T25 的 XAUT0 / SPYX 也走这里)。
    同步,由调用方放进线程。"""
    from src.data.venues.hl_spot import HlSpotClient, HlSpotFixture, parse_l2_book
    c = client or HlSpotClient()
    fx = HlSpotFixture(c.spot_meta(), c.spot_meta_and_asset_ctxs(), {}, {})
    out = {}
    for sym, base in (tokens or SPOT_TOKENS).items():
        pair = fx.find_pair_by_token(base)
        if pair is None:
            continue
        book = parse_l2_book(c.l2_book(pair.name))
        mid = book.mid_px or pair.mid_px
        out[sym] = {"pair": pair.name, "mid": mid, "bid": book.best_bid, "ask": book.best_ask,
                    "sz_decimals": pair.sz_decimals, "book": book}
    return out


async def run_dry_cycle(now: Optional[dt.datetime] = None, write: bool = True,
                        quotes: Optional[dict] = None) -> dict[str, Any]:
    """一轮空跑。返回本轮全部中间量;`refused` 时说明在等什么。"""
    from src.data.execution import executor as ex
    from src.data.universe.forward_books import tom_inputs
    now = now or dt.datetime.now(dt.timezone.utc)
    yday = (now.date() - dt.timedelta(days=1)).isoformat()
    closes_all, _fund = await tom_inputs(yday)
    closes = {s: closes_all[s] for s in SPOT_TOKENS if s in closes_all}
    have = {s: c.index[-1].date().isoformat() for s, c in closes.items() if len(c)}
    if set(have) != set(SPOT_TOKENS) or any(d != yday for d in have.values()):
        return {"ok": False, "refused": True, "why": f"{yday} 的收盘还没全部落库:{have}", "asof": yday}
    targets = ex.target_weights(closes)
    prev = ex.target_weights({s: c.iloc[:-1] for s, c in closes.items()})
    holdings = {s: w * PAPER_ACCOUNT_USD for s, w in prev.items() if w > 0}
    cash = PAPER_ACCOUNT_USD - sum(holdings.values())
    if quotes is None:
        quotes = await asyncio.to_thread(_spot_quotes_sync)
    ts = now.timestamp()
    prices = {s: (q["mid"], ts) for s, q in quotes.items() if q.get("mid")}
    plan = ex.plan_orders(targets, holdings, cash, prices, ts, ex.Limits())
    sized, refused_size = size_orders(plan.orders, quotes)
    catastrophe = {s: ex.catastrophe_hit(prices[s][0], closes[s]) for s in closes if s in prices}
    mins = minutes_after_close(now)
    written = 0
    if write and sized:
        from src.data.execution.fill_log import write_intent
        plan_sized = ex.Plan(orders=[{**o, "notional_usd": o["notional_rounded"]} for o in sized])
        for i in ex.intents_from_plan(plan_sized, decided_at=now, sleeve=SLEEVE):
            q = quotes.get(i.symbol) or {}
            i.decision_bid, i.decision_ask = q.get("bid"), q.get("ask")
            written += int(await write_intent(i))
    return {"ok": True, "asof": yday, "minutes_after_close": round(mins, 1), "on_time": mins <= ON_TIME_MIN,
            "targets": {s: round(v, 4) for s, v in targets.items()}, "prev": {s: round(v, 4) for s, v in prev.items()},
            "mids": {s: q.get("mid") for s, q in quotes.items()}, "orders": sized,
            "refused": plan.refused + refused_size, "catastrophe": catastrophe,
            "intents_written": written, "account_usd": PAPER_ACCOUNT_USD}


async def already_ran_today(now: Optional[dt.datetime] = None) -> bool:
    """今天(UTC)这一档已经写过意图 ⇒ True。部署会重启循环,同一天的意图不能写两批。
    没有订单的日子不写意图,重跑一次也不留重复 —— 那一天的记录在 loop_attempt 里。"""
    from src.data.style.header import _read_all
    now = now or dt.datetime.now(dt.timezone.utc)
    day0 = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = await _read_all("execution_intents", {"select": "intent_id", "sleeve": f"eq.{SLEEVE}",
                                                 "ts_decision": f"gte.{day0}"})
    if rows:
        return True
    # 没有订单的日子:今天已有一条 ok 的 loop_attempt 就算跑过 —— 否则部署后的重跑会在记录里留一条「迟到」的轮次
    ok = await _read_all("loop_attempt", {"select": "id", "loop_name": "eq._executor_dry_run_loop",
                                          "outcome": "eq.ok", "at": f"gte.{day0}"})
    return bool(ok)
