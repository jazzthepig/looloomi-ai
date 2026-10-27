"""R-v2 单票的执行计划(Railway 这一侧)—— 东京主机在 HL 永续上照着做(Jazz 10-21:永续执行、真钱、先空跑)。

## 一个内核

票是谁、什么时候进、什么时候出,全部由前向账本 `r_tickets_paper` 决定(Postgres 函数 `r_tickets_scan`,与回放
同一个;T-156 两个独立实现逐票对上)。这里**不重新判断任何信号**,只把账本翻译成主机能执行的三张单子:

- `enter`:`pending` 且信号日 = asof 的票 —— 回放在 asof + 1 日开盘进场,主机在今天 00:45 UTC 之后尽快进;
- `hold`:`open` 且没有出场标记 —— 主机继续拿着,保证交易所上挂着止损;
- 其余在主机账上的票一律出场:`open` 带 `exit_flag`(收盘破 SMA20 ⇒ 今天开盘出)、`closed`(止损 / 120 根到期 /
  停更)、或已不在账本里。`exit` 列出来只为报告写原因。

## 同时最多 10 张:按纸面账本的先到先得

`r_tickets_nav` 的规则原样搬过来(`taken_ids`):进场日 d 时,已占位 = 已取、进场早于 d、且没在 d 之前出场的票;
同一天按信号日、再按名字。**主机执行的是纸面账本取到的那些票的子集**(不在 HL 上的记「不可执行」,不拿别的票替补)——
这样主机与回放之间只差执行,不差选择。

## 止损按比例给,不按价格给

`stop_frac = 2.5 × ATR14[t] / close[t]`。回放的止损是「进场 − 2.5 × ATR14」;主机按自己的成交价算
`止损 = 成交 × (1 − stop_frac)`。比例与计价单位无关 —— HL 上 1000 倍面值的币(kPEPE)不用换算。

账本还没推进到 asof(`r_tickets_state.last_d < asof`)⇒ `ready = False`,主机只守止损,不开不平。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Optional

RULE_VERSION = "r_v2_k2.5_gate200"
STOP_ATR = 2.5
DEFAULT_RISK_FRAC = 0.005          # Jazz 10-21 真钱:每票风险 0.5% 净值(f★ = 1% 的一半,S-638)
DEFAULT_CAP = 10
#: Jazz 10-21:策略是 0–1 倍的底层参考,杠杆只在组合 / 选择层选,最多 5 倍。R-v2 这一腿的组合杠杆 L:
#: 每票风险 = 净值 × L × risk_frac,名义合计 ≤ 净值 × L。默认 1(不加);改它是 Jazz 的决定(Railway 环境变量)。
MAX_PORTFOLIO_LEVERAGE = 5.0
TICKET_SLEEVE_FOR_MODE = {"dry_run": "r_v2_host_dry", "live": "r_v2_live"}
_CLOSED_LOOKBACK_DAYS = 5          # 最近几天关掉的票都列进 exit(主机可能晚几天才看到)


def _d(x: Any) -> Optional[dt.date]:
    if x is None or x == "":
        return None
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def taken_ids(rows: Iterable[dict], cap: int, pending_entry: dt.date) -> set[str]:
    """纯函数。与 `r_tickets_nav` 同一条占位规则:按进场日走,已占位 = 已取 ∧ 进场早于 d ∧ (未出场 ∨ 出场 ≥ d);
    同一天按 (信号日, 名字) 先到先得。`pending` 的票按 `pending_entry`(asof + 1)进场。"""
    tk = []
    for r in rows:
        st = r.get("status")
        if st not in ("pending", "open", "closed"):
            continue
        e = pending_entry if st == "pending" else _d(r.get("entry_d"))
        if e is None:
            continue
        tk.append({"id": r["ticket_id"], "symbol": r["symbol"], "signal_d": _d(r.get("signal_d")), "e": e,
                   "x": None if st != "closed" else _d(r.get("exit_d"))})
    taken: dict[str, dict] = {}
    for e in sorted({t["e"] for t in tk}):
        occ = sum(1 for t in taken.values() if t["e"] < e and (t["x"] is None or t["x"] >= e))
        k = 0
        for t in sorted((t for t in tk if t["e"] == e), key=lambda t: (t["signal_d"] or dt.date.min, t["symbol"])):
            if occ + k < cap:
                taken[t["id"]] = t
                k += 1
    return set(taken)


def make_ticket_plan(rows: list[dict], last_d: Optional[str], asof: str, closes: dict[tuple[str, str], float],
                     risk_frac: float = DEFAULT_RISK_FRAC, cap: int = DEFAULT_CAP,
                     portfolio_leverage: float = 1.0) -> dict[str, Any]:
    """纯函数。账本行 + 账本推进到哪天 + 信号日收盘价 → 主机计划。"""
    a = _d(asof)
    base = {"asof": asof, "last_d": str(last_d)[:10] if last_d else None, "risk_frac": risk_frac, "cap": cap,
            "portfolio_leverage": portfolio_leverage,
            "stop_atr": STOP_ATR, "rule_version": RULE_VERSION, "sleeves": dict(TICKET_SLEEVE_FOR_MODE)}
    if not last_d or _d(last_d) < a:
        return {**base, "ready": False, "why": f"r_tickets_scan 还没推进到 {asof}(last_d = {last_d})",
                "enter": [], "hold": [], "exit": [], "skipped_cap": []}
    taken = taken_ids(rows, cap, a + dt.timedelta(days=1))
    enter, skipped, hold, exit_ = [], [], [], []
    for r in sorted(rows, key=lambda r: (str(r.get("signal_d")), r.get("symbol"))):
        st, tid = r.get("status"), r.get("ticket_id")
        if st == "pending" and _d(r.get("signal_d")) == a:
            c, atr = closes.get((r["symbol"], asof)), r.get("atr14")
            row = {"ticket_id": tid, "symbol": r["symbol"], "signal_d": asof, "atr14": atr, "ref_close": c,
                   "stop_frac": (STOP_ATR * float(atr) / float(c)) if (atr and c) else None}
            (enter if tid in taken else skipped).append(row)
        elif st == "open" and not r.get("exit_flag"):
            hold.append({"ticket_id": tid, "symbol": r["symbol"], "entry_d": str(r.get("entry_d"))[:10],
                         "paper_entry_px": r.get("entry_px"), "paper_stop_px": r.get("stop_px"),
                         "bars_held": r.get("bars_held"), "taken": tid in taken})
        elif st == "open" and r.get("exit_flag"):
            exit_.append({"ticket_id": tid, "symbol": r["symbol"], "why": "sma20", "at": "today_open"})
        elif st == "closed" and _d(r.get("exit_d")) and _d(r.get("exit_d")) >= a - dt.timedelta(days=_CLOSED_LOOKBACK_DAYS):
            exit_.append({"ticket_id": tid, "symbol": r["symbol"], "why": r.get("exit_reason"),
                          "at": str(r.get("exit_d"))[:10], "paper_exit_px": r.get("exit_px")})
    bad = [e["ticket_id"] for e in enter if not e["stop_frac"] or not (0 < e["stop_frac"] < 0.9)]
    return {**base, "ready": True, "enter": [e for e in enter if e["ticket_id"] not in bad], "hold": hold,
            "exit": exit_, "skipped_cap": skipped, "bad_stop": bad}


async def load_ticket_plan(asof: str, risk_frac: Optional[float] = None,
                           now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """读账本(`r_tickets_paper` 全部、`r_tickets_state.last_d`)+ 信号日收盘 → 计划。读不到就抛,不当 0 行。"""
    import os

    from src.data.style.header import _read_all
    rf = risk_frac if risk_frac is not None else float(os.environ.get("R_V2_RISK_FRAC", DEFAULT_RISK_FRAC))
    if not (0 < rf <= 0.02):
        raise ValueError(f"R_V2_RISK_FRAC = {rf} 不在 (0, 2%] —— 拒绝出计划")
    lev = float(os.environ.get("R_V2_PORTFOLIO_LEVERAGE", "1"))
    if not (1.0 <= lev <= MAX_PORTFOLIO_LEVERAGE):
        raise ValueError(f"R_V2_PORTFOLIO_LEVERAGE = {lev} 不在 [1, {MAX_PORTFOLIO_LEVERAGE:g}] —— 拒绝出计划")
    rows = await _read_all("r_tickets_paper", {
        "select": "ticket_id,symbol,signal_d,atr14,status,entry_d,entry_px,stop_px,bars_held,exit_flag,exit_d,exit_px,"
                  "exit_reason", "status": "in.(pending,open,closed)", "order": "ticket_id.asc"})
    st = await _read_all("r_tickets_state", {"select": "last_d", "id": "eq.1"})
    last_d = (st[0] or {}).get("last_d") if st else None
    syms = sorted({r["symbol"] for r in rows if r.get("status") == "pending" and str(r.get("signal_d"))[:10] == asof})
    closes: dict[tuple[str, str], float] = {}
    if syms:
        bars = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close", "source": "eq.binance_hist",
                                               "trade_date": f"eq.{asof}", "symbol": f"in.({','.join(syms)})"})
        closes = {(b["symbol"], str(b["trade_date"])[:10]): float(b["close"]) for b in bars if b.get("close")}
    plan = make_ticket_plan(rows, last_d, asof, closes, rf, DEFAULT_CAP, lev)
    # S-690(Jazz 10-27「直接应用」):开票日 d 收盘的 OI/市值(规模中性)分位 ≥ 2/3 的票不进、不腾位置。
    # 截面是 d+1 00:05 UTC 的 CoinGecko 快照(归档要到 07:30,滞后一天的版本检验不过 —— 台账 S-690 附记一)。
    # 读不到 ⇒ 这一轮不开新票(fail closed),持有与出场照常。规则与停用条件见 signals/oi_leverage 模块头。
    plan["skipped_oi"] = []
    if plan.get("ready") and plan.get("enter"):
        from src.data.signals.oi_leverage import filter_enter, load_filter_inputs
        try:
            snap, audit = await load_filter_inputs(asof)
        except Exception as e:                                   # noqa: BLE001
            plan.update({"skipped_oi": [{**x, "why": "OI 快照读不到 —— 这一轮不开新票"} for x in plan["enter"]],
                         "enter": [], "oi_filter": {"status": "read_error", "why": f"{type(e).__name__}: {str(e)[:200]}"}})
        else:
            kept, skipped, info = filter_enter(plan["enter"], asof, snap, audit,
                                                 now or dt.datetime.now(dt.timezone.utc))
            plan.update({"enter": kept, "skipped_oi": skipped, "oi_filter": info})
    else:
        plan["oi_filter"] = {"status": "nothing_to_enter"}
    # Jazz ⓪(regime_call):off / flat 挡新票、flat 平所有、信心档位放大每票风险、战场上的 J 票。
    # **读不到判断 ⇒ 不开不平(fail closed)**:一条「off」被当成「没有判断」,就会在 Jazz 说别进的时候进场。
    from src.data.execution.regime_call import governing_call, overlay, read_calls, read_j_tickets
    try:
        calls, j_rows = await read_calls(), await read_j_tickets()
    except Exception as e:                                       # noqa: BLE001
        return {**plan, "ready": False, "enter": [], "exit": [], "hold": plan.get("hold") or [],
                "why": f"Jazz ⓪(regime_calls / j_tickets)读不到 —— 这一轮不开不平:{type(e).__name__}: {str(e)[:200]}"}
    return overlay(plan, governing_call(calls, asof), j_rows)
