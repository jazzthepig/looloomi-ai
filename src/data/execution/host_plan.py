"""云主机执行器的每日计划(T-015 / TRADE_PATH §4–§5)—— Railway 这一侧。

## 分工:信号在 Railway,钥匙在主机

信号要读库里的收盘价(`forward_books.tom_inputs`,与 tom_trader 前向账本、Railway 空跑同一份价、同一个核),
而 Supabase 的写凭证只在 Railway 上;HL API 钱包的私钥只在东京主机上(TRADE_PATH §4:不经过 Seth、不经过任何 lane)。
所以计划在这里算,主机来取;主机读自己的真实余额和盘口,自己算订单、自己签名。**两边都不需要对方的秘密。**

## 计划里有什么

- `targets`:X1V 现货目标权重(`executor.target_weights`,与 `dry_run` 同一个函数);
- `stop_px`:盘中灾难止损线(`executor.stop_price`)—— 主机缓存它,盘中每分钟拿现价比,**Railway 掉线也照样能止损**;
- `portfolio`:组合层的两个上限(`portfolio_targets.plan_fields`,Jazz 10-29)—— X1V 记账净值 ≤ 加密腿额度、
  R-v2 名义合计 ≤ 净值 × 30%(后者也在 `tickets.gross_cap_frac`);
- `halted`:一键停(Redis `executor:halt`)。读不到(`halt_status = error`)不当作「没停」也不当作「停了」——
  原样告诉主机,由主机决定(主机侧:读不到 ⇒ 沿用上一次读到的值)。

收盘价没落库 ⇒ `ok = False` 并写明在等什么(与 `dry_run.run_dry_cycle` 同一条拒绝),主机 5 分钟后再来。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any, Optional

from src.data.execution.dry_run import SPOT_TOKENS

#: 主机空跑与真跑各自的 sleeve —— 与 Railway 纸面空跑(`x1v_spot_dry`)分开,三条记录互不覆盖
HOST_DRY_SLEEVE = "x1v_spot_host_dry"
LIVE_SLEEVE = "x1v_spot"
SLEEVE_FOR_MODE = {"dry_run": HOST_DRY_SLEEVE, "live": LIVE_SLEEVE}
HALT_KEY = "executor:halt"

#: 同一个 asof 的信号部分只算一次(主机每 15 分钟来取一次,只为刷新一键停)
_CORE_CACHE: dict[str, dict[str, Any]] = {}


async def read_halt() -> tuple[bool, str]:
    """(是否一键停, 读取状态 hit / miss / error / unconfigured)。miss ⇒ 没停。"""
    from src.api.store import redis_get_key_status
    payload, status = await redis_get_key_status(HALT_KEY)
    return bool(payload and payload.get("halted")), status


def make_plan(closes: dict, asof: str) -> dict[str, Any]:
    """纯函数。截至 asof 收盘(含)的收盘序列 → 计划(目标、止损线、限额)。
    **Railway 的 /plan 与历史回放(exec_host.replay,T-134)都只经这里** —— 回放出来的就是实盘会收到的计划。"""
    from src.data.execution import executor as ex
    return {"ok": True, "asof": asof,
            "targets": {s: round(w, 6) for s, w in ex.target_weights(closes).items()},
            "stop_px": {s: ex.stop_price(c) for s, c in closes.items()},
            "last_close": {s: float(c.iloc[-1]) for s, c in closes.items()},
            "spot_tokens": dict(SPOT_TOKENS), "signal_ref": ex.SIGNAL_REF,
            "catastrophe_factor": ex.CATASTROPHE, "limits": asdict(ex.Limits()),
            "sleeves": dict(SLEEVE_FOR_MODE)}


async def plan_core(asof: str) -> dict[str, Any]:
    """asof 这天收盘后定下的目标与止损线。收盘没齐 ⇒ ok False。"""
    from src.data.universe.forward_books import tom_inputs
    if asof in _CORE_CACHE:
        return _CORE_CACHE[asof]
    closes_all, _fund = await tom_inputs(asof)
    closes = {s: closes_all[s] for s in SPOT_TOKENS if s in closes_all}
    have = {s: c.index[-1].date().isoformat() for s, c in closes.items() if len(c)}
    if set(have) != set(SPOT_TOKENS) or any(d != asof for d in have.values()):
        return {"ok": False, "asof": asof, "why": f"{asof} 的收盘还没全部落库:{have}"}
    core = make_plan(closes, asof)
    _CORE_CACHE.clear()
    _CORE_CACHE[asof] = core
    return core


async def ticket_section(asof: str) -> dict[str, Any]:
    """R-v2 单票计划(`ticket_plan`)。与 X1V 的 `ok` 互不牵连:X1V 收盘没齐不挡单票,单票读不到也不挡 X1V。"""
    from src.data.execution.ticket_plan import load_ticket_plan
    try:
        return await load_ticket_plan(asof)
    except Exception as e:                                       # noqa: BLE001
        return {"asof": asof, "ready": False, "why": f"{type(e).__name__}: {str(e)[:300]}",
                "enter": [], "hold": [], "exit": [], "skipped_cap": []}


async def build_host_plan(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    asof = (now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    try:
        core = await plan_core(asof)
    except Exception as e:                                       # noqa: BLE001 — X1V 读不到不挡单票
        core = {"ok": False, "asof": asof, "why": f"X1V 计划读不到:{type(e).__name__}: {str(e)[:200]}"}
    halted, halt_status = await read_halt()
    from src.data.execution.portfolio_targets import plan_fields
    # 组合层(Jazz 10-29):X1V 只用加密腿的额度,R-v2 名义 ≤ 净值 30%。与 portfolio_targets_daily 同一个函数
    return {**core, "halted": halted, "halt_status": halt_status, "generated_at": now.isoformat(),
            "portfolio": plan_fields(now.astimezone(dt.timezone.utc).date().isoformat()),
            "tickets": await ticket_section(asof)}
