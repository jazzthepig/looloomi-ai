"""现货止损触发单的一次真钱验证(Jazz 11-02「先直接在这个主机做测试」)—— 只挂、读、撤,不成交。

## 要回答的三个问题

1. HL 收不收**现货**的止损触发单(order 动作的 `trigger` 类型,资产 = 现货币对)?文档只有永续的例子。
2. 挂着、还没触发的时候,代币会不会被 `hold` 住?会 ⇒ 现在的卖出路径(按 `total − hold` 算可卖量)要先撤再卖。
3. 撤单能不能撤掉、hold 能不能回来?

答案决定主机死了以后 X1V 现货有没有交易所侧的底(`dead_host_guard` 现在只能报警)。

## 怎么做(每一步都不会成交)

- 代币默认 XAUT0(账上有、T25 腿);卖出止损,**触发价 = 中间价 × 50%、限价 = 中间价 × 45%**。现价跌一半之前不会触发,
  而整个探针从挂到撤只有几秒。数量 = 按限价算刚过 $10 最小名义额,且不超过可卖量的一半。
- 两种各挂一次:限价触发(`isMarket = False`)、市价触发(`isMarket = True`,HL 的市价触发带 10% 滑点上限)——
  X1V 真用的时候要选一种,两种都要知道收不收。**一张一张来**(挂 → 读 → 撤 → 读),账上同一时刻最多一张。
- 读 `frontendOpenOrders`(挂上了没有、是不是 trigger)与现货余额的 hold;然后撤(`finally` 里撤,出错也撤);
  再读一次确认没了、hold 回来了。前一张撤不掉 ⇒ 不挂下一张。
- 一键停的本地文件在 ⇒ 不跑。UTC 00:00–01:00(每日一轮在跑)⇒ 不跑。
- 结果打印成 JSON,并以 `kind = probe` 报给 Railway(`loop_attempt` 里能看到)。

只调用交易所的 `order` 与 `cancel`(`tests/test_exec_host.py` 的 AST 守卫照样管这个文件)。
"""
from __future__ import annotations

if __name__ == "__main__" and not __package__:
    # 11-02:在 Mac 上直接 `python3 …/probe_spot_trigger.py` 会卡在 import —— 而且就算过了,Mac 上也没有私钥。说清楚该怎么跑
    raise SystemExit("这个探针只在东京主机上跑(私钥只在那台机器上)。\n"
                     "在 Mac 上双击 scripts/host_probe_spot_trigger.command,或在终端:\n"
                     "  bash ~/Projects/looloomi-ai/scripts/host_probe_spot_trigger.command")

import argparse
import datetime as dt
import json
import time
import uuid
from typing import Any, Optional

from src.exec_host import core

TRIGGER_FRAC = 0.50
LIMIT_FRAC = 0.45
TARGET_NOTIONAL_USD = 11.0            # 按限价算;HL 最小名义额 $10
MAX_SHARE_OF_FREE = 0.5
QUIET_HOURS_UTC = (0,)                 # 每日一轮在 00:05 起跑,别撞


def plan_probe(free_qty: float, mid: float, sz_decimals: int, n_orders: int = 2) -> dict[str, Any]:
    """纯函数。可卖量 + 中间价 → 每张的数量与两个价;做不了 ⇒ {"ok": False, "why": …}。"""
    if not mid or mid <= 0:
        return {"ok": False, "why": "没有中间价"}
    trigger = core.round_px_spot(mid * TRIGGER_FRAC, sz_decimals)
    limit = core.round_px_spot(mid * LIMIT_FRAC, sz_decimals)
    need = TARGET_NOTIONAL_USD / limit
    step = 10 ** -int(sz_decimals)
    qty = core.round_size(need + step, sz_decimals)          # 向上一格,保证取整后仍 ≥ $10
    if qty * limit < 10.0:
        qty = core.round_size(qty + step, sz_decimals)
    if qty * n_orders > free_qty * MAX_SHARE_OF_FREE + 1e-12:
        return {"ok": False, "why": f"每张要 {qty},{n_orders} 张超过可卖量 {free_qty} 的一半 —— 换一个余额更多的代币"}
    return {"ok": True, "qty": qty, "trigger_px": trigger, "limit_px": limit,
            "notional_at_limit": round(qty * limit, 4), "notional_at_mid": round(qty * mid, 4)}


def _cloid(h: str) -> Any:
    """SDK 的 Cloid;没装 SDK(Mac 上跑测试)⇒ None —— 主机上一定装着(deploy/executor/requirements.txt)。"""
    try:
        from hyperliquid.utils.types import Cloid
    except ImportError:
        return None
    return Cloid(h)


def _mine(open_orders: Any, oids: set[int]) -> list[dict]:
    return [o for o in open_orders or [] if isinstance(o, dict) and o.get("oid") in oids]


def _place(venue: Any, q: dict, plan: dict, is_market: bool) -> tuple[dict, dict]:
    cl = "0x" + uuid.uuid4().hex
    t0 = time.time()
    try:
        resp = venue.exchange().order(q["pair"], False, plan["qty"], plan["limit_px"],
                                      {"trigger": {"triggerPx": plan["trigger_px"], "isMarket": is_market, "tpsl": "sl"}},
                                      reduce_only=False, cloid=_cloid(cl))
    except Exception as e:                                               # noqa: BLE001
        resp = {"status": "exception", "error": f"{type(e).__name__}: {str(e)[:300]}"}
    parsed = core.parse_order_response(resp)
    return parsed, {"step": f"place isMarket={is_market}", "seconds": round(time.time() - t0, 3), "parsed": parsed,
                    "raw": str(resp)[:400]}


def _cancel(venue: Any, pair: str, oid: Any) -> dict:
    try:
        r = venue.exchange().cancel(pair, oid)
        return {"oid": oid, "ok": isinstance(r, dict) and r.get("status") == "ok", "raw": str(r)[:300]}
    except Exception as e:                                               # noqa: BLE001
        return {"oid": oid, "ok": False, "raw": f"{type(e).__name__}: {str(e)[:200]}"}


def run(venue: Any, token: str, now: Optional[dt.datetime] = None, wait_s: float = 3.0) -> dict[str, Any]:
    """两种触发(限价 / 市价)**一张一张来**:挂 → 读 → 撤 → 读,同一时刻账上最多一张(11-02 第一次跑:XAUT0 szDecimals = 2,
    一张最少 0.01,两张同时挂超过可卖量 0.029979 的一半,探针按规则拒了 —— 改成逐张,一张只占三分之一)。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    out: dict[str, Any] = {"token": token, "at": now.isoformat(), "steps": [], "orders": []}
    if now.hour in QUIET_HOURS_UTC:
        return {**out, "ok": False, "why": "UTC 00:00–01:00 每日一轮在跑 —— 换个时间"}
    if venue.cfg.halt_file.exists():
        return {**out, "ok": False, "why": f"本地一键停 {venue.cfg.halt_file} 在 —— 不跑"}
    bal0 = venue.balances()
    q = venue.quotes({token: token}).get(token)
    if not q:
        return {**out, "ok": False, "why": f"{token} 没有现货盘口"}
    b0 = bal0.get(token) or {}
    hold0 = float(b0.get("hold", 0.0))
    free = max(0.0, round(float(b0.get("total", 0.0)) - hold0, 10))
    plan = plan_probe(free, float(q["mid"]), int(q["sz_decimals"]), n_orders=1)
    out.update(pair=q["pair"], mid=q["mid"], sz_decimals=q["sz_decimals"], balance_before=b0, plan=plan)
    if not plan["ok"]:
        return {**out, "ok": False, "why": plan["why"]}
    left: list = []
    for is_market in (False, True):
        rec: dict[str, Any] = {"is_market": is_market}
        parsed, step = _place(venue, q, plan, is_market)
        out["steps"].append(step)
        rec["placed"] = parsed["kind"]
        oid = parsed.get("oid")
        try:
            if oid is not None:
                time.sleep(wait_s)
                mine = _mine(venue._poster({"type": "frontendOpenOrders", "user": venue.cfg.trade_account}), {oid})
                b1 = venue.balances().get(token) or {}
                rec["resting"] = [{k: o.get(k) for k in ("oid", "coin", "side", "sz", "limitPx", "isTrigger", "triggerPx",
                                                         "triggerCondition", "orderType", "reduceOnly")} for o in mine]
                rec["hold_delta"] = round(float(b1.get("hold", 0.0)) - hold0, 10)
        finally:
            if oid is not None:
                rec["cancel"] = _cancel(venue, q["pair"], oid)
        if oid is not None:
            time.sleep(wait_s)
            still = _mine(venue._poster({"type": "frontendOpenOrders", "user": venue.cfg.trade_account}), {oid})
            rec["left_open"] = [o.get("oid") for o in still]
            left += rec["left_open"]
            rec["hold_back"] = abs(float((venue.balances().get(token) or {}).get("hold", 0.0)) - hold0) < 1e-9
        out["orders"].append(rec)
        if oid is not None and rec.get("left_open"):
            break                                                        # 撤不掉就不挂第二张
    out["left_open"] = left
    placed = [r for r in out["orders"] if r.get("placed") == "resting"]
    out["answers"] = {
        "spot_trigger_accepted": {f"isMarket={r['is_market']}": r.get("placed") == "resting" for r in out["orders"]},
        "rests_as_trigger": bool(placed) and all(r.get("resting") and all(o.get("isTrigger") for o in r["resting"])
                                                 for r in placed),
        "locks_tokens_while_untriggered": None if not placed else any((r.get("hold_delta") or 0) > 0 for r in placed),
        "cancel_works": bool(placed) and all((r.get("cancel") or {}).get("ok") and not r.get("left_open") for r in placed),
    }
    out["ok"] = not left
    if left:
        out["why"] = f"还挂着 {left} —— 去 HL 网页「Open Orders」手动撤掉"
    return out


def main(argv: Optional[list[str]] = None) -> None:
    from src.exec_host.runner import Config, Railway, Venue
    ap = argparse.ArgumentParser(description="现货止损触发单探针:挂两张远离市价的卖出止损、读、撤 —— 不成交")
    ap.add_argument("--token", default="XAUT0")
    ap.add_argument("--yes", action="store_true", help="确认:会在真钱账户上挂两张(远离市价、几秒后撤掉)的触发单")
    args = ap.parse_args(argv)
    if not args.yes:
        raise SystemExit("要加 --yes(会在真钱账户上挂两张远离市价的触发单,几秒后撤掉)")
    cfg = Config()
    venue = Venue(cfg)
    res = run(venue, args.token)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    try:
        mode = cfg.t25_mode if cfg.t25_mode in ("dry_run", "live") else "dry_run"
        Railway(cfg.api, cfg.token).report({"mode": mode, "book": "t25", "kind": "probe", "host": cfg.host,
                                            "detail": {"probe": "spot_trigger", **{k: res.get(k) for k in
                                                       ("token", "ok", "why", "answers", "plan", "orders", "left_open",
                                                        "steps")}},
                                            "alert": f"现货触发单探针 {args.token}: {json.dumps(res.get('answers'), ensure_ascii=False)}"
                                                     + (f" · {res['why']}" if res.get("why") else "")})
    except Exception as e:                                               # noqa: BLE001 — 报不上去不影响结果,屏幕上有
        print(f"(没报到 Railway:{type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
