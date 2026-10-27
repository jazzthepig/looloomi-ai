"""R-v2 的 Book of Truth —— 计划的是什么、交易所上实际发生的是什么,逐票对账(docs/TRADER_TOM_DOCTRINE.md §11)。

Trader Tom(Best Loser Wins)每笔交易都写进「真相之书」:不是记盈亏,是记**有没有照计划做**。系统交易里人性的
那一半换成了执行器,同样的问题换了问法:纸面账本 `r_tickets_paper` 要的票,交易所上进了没有、按什么价、
止损挂上没有、出场按什么价、有没有账本没要的单子。**过程与结果分开打分** —— 一张亏损票可以是干净的,
一张赚钱票可以是违规的。

## 对账口径

- 纸面:`r_tickets_paper`(进场 = 信号次日开盘,R 含 0.4% 来回成本)。按 `taken_ids` 的同一条先到先得规则
  决定「纸面取了哪些票」—— 主机执行的是它的子集,不替补。
- 交易所:`execution_intents` + `execution_outcomes`,按 sleeve(空跑 `r_v2_host_dry` / 真钱 `r_v2_live`)。
  `signal_ref = r_v2:<ticket_id>:<动作>[:<原因>]`,动作 ∈ enter / exit / stop_backup / stop_trigger / stop_virtual。
  空跑没有成交结果,按意图的决策中间价记虚拟成交(写明 virtual)。
- 主机自己说「不可执行」或「纸面满额跳过」的票,来自 `loop_attempt`(executor_host 的 r_v2 cycle 明细)。

## 违规(process breach,任何一条 ⇒ 这张票不干净)

- `no_record`:纸面已进场的票,主机既没下单也没说为什么;
- `unfilled`:下了进场单但没成交(IOC 没吃到 / 被拒);
- `no_stop`:真钱已进场但交易所上从没挂上止损触发单;
- `late_exit`:纸面已出场超过 1 天,交易所上还开着;
- `orphan`:交易所上有单子,纸面账本里没有这张票;
- `off_plan`:纸面按 10 张上限没取的票,主机却进了(选择偏离计划)。

## 杠杆阶梯(建议,不自动生效)

Tom:仓位大到一笔亏损会动摇你,就是太大了 —— 规模是**挣来的**。真钱、已平仓的票按数量上台阶:
< 20 张 1 倍 · ≥ 20 张 ≤ 2 倍 · ≥ 50 张 ≤ 3 倍 · ≥ 100 张 ≤ 5 倍;干净率 < 90% 或最近 20 张里有严重违规
(no_stop / orphan / no_record / late_exit / off_plan)⇒ 降一级。空跑不计入。`R_V2_PORTFOLIO_LEVERAGE` 仍是 Jazz 的开关。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Optional

from src.data.execution.ticket_plan import DEFAULT_CAP, TICKET_SLEEVE_FOR_MODE, taken_ids

REF = re.compile(r"^r_v2:(?P<tid>(?:J:)?[^:]+:\d{4}-\d{2}-\d{2}):(?P<act>[a-z_]+)(?::(?P<why>.*))?$")
EXIT_ACTS = ("exit", "stop_backup", "stop_trigger", "stop_virtual")
SERIOUS = ("no_stop", "orphan", "no_record", "late_exit", "off_plan")
LADDER = ((100, 5.0), (50, 3.0), (20, 2.0), (0, 1.0))
CLEAN_MIN = 0.90
RECENT_N = 20


def _d(x: Any) -> Optional[dt.date]:
    if x is None or x == "":
        return None
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_ref(ref: Any) -> Optional[tuple[str, str, str]]:
    """`r_v2:UNI:2026-10-19:exit:sma20` → ("UNI:2026-10-19", "exit", "sma20");不是 R-v2 的引用 ⇒ None。"""
    m = REF.match(str(ref or ""))
    return (m["tid"], m["act"], m["why"] or "") if m else None


def _fill(intent: dict, outcome: Optional[dict], virtual: bool) -> dict:
    """一张意图的成交:空跑按决策中间价虚拟成交;真钱看结果(没有结果 = 还没回报)。"""
    if virtual:
        return {"status": "virtual", "px": _f(intent.get("decision_mid")),
                "notional": _f(intent.get("target_notional_usd")) or 0.0, "fee": 0.0}
    if not outcome:
        return {"status": "pending", "px": None, "notional": 0.0, "fee": 0.0}
    st, px = outcome.get("status"), _f(outcome.get("avg_fill_price"))
    if st in ("filled", "partial") and px:
        return {"status": st, "px": px, "notional": _f(outcome.get("filled_notional_usd")) or 0.0,
                "fee": _f(outcome.get("fee_usd")) or 0.0}
    return {"status": st or "pending", "px": None, "notional": 0.0, "fee": 0.0}


def _bps(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """(a / b − 1) × 10⁴;任一缺 ⇒ None。"""
    return round((a / b - 1.0) * 1e4, 1) if a and b else None


def earned_leverage(n_closed: int, clean_share: Optional[float], recent_serious: int) -> tuple[float, str]:
    """纯函数。真钱已平仓票数 → 阶梯上限;干净率不够或最近有严重违规 ⇒ 降一级。"""
    rungs = [lv for _, lv in LADDER][::-1]                       # [1, 2, 3, 5]
    base = next(lv for n, lv in LADDER if n_closed >= n)
    i = rungs.index(base)
    why = f"真钱已平仓 {n_closed} 张 ⇒ 台阶 {base:g} 倍"
    if (clean_share is not None and clean_share < CLEAN_MIN) or recent_serious:
        i = max(0, i - 1)
        why += (f";干净率 {clean_share:.0%} < {CLEAN_MIN:.0%}" if clean_share is not None and clean_share < CLEAN_MIN
                else "") + (f";最近 {RECENT_N} 张有 {recent_serious} 次严重违规" if recent_serious else "") + " ⇒ 降一级"
    return rungs[i], why


def reconcile(paper: Iterable[dict], intents: Iterable[dict], outcomes: Iterable[dict], *, mode: str,
              asof: str, host_skips: Optional[dict[str, str]] = None, cap: int = DEFAULT_CAP) -> dict[str, Any]:
    """纯函数。纸面票 + 交易所意图 / 结果 → 逐票对账 + 汇总 + 杠杆阶梯。

    `asof` = 最后一个已收盘 UTC 日;`host_skips` = {ticket_id: 主机说的原因}(不可执行 / 纸面满额)。"""
    virtual = mode != "live"
    sleeve = TICKET_SLEEVE_FOR_MODE.get(mode)
    a = _d(asof)
    rows = [r for r in paper if r.get("status") in ("pending", "open", "closed")]
    by_id = {r["ticket_id"]: r for r in rows}
    # J 票(Jazz ⓪ 的战场票,ticket_id 以 J: 开头)不走 R-v2 的满额先到先得:人选了就是要进
    jazz = {r["ticket_id"] for r in rows if str(r["ticket_id"]).startswith("J:")}
    taken = (taken_ids([r for r in rows if r["ticket_id"] not in jazz], cap, a + dt.timedelta(days=1)) if a else set()) | jazz
    outs = {o["intent_id"]: o for o in outcomes if o.get("intent_id")}
    acts: dict[str, dict[str, list]] = {}
    orphans: list[dict] = []
    for i in sorted((x for x in intents if x.get("sleeve") == sleeve), key=lambda x: str(x.get("ts_decision"))):
        p = parse_ref(i.get("signal_ref"))
        if not p:
            continue
        tid, act, why = p
        rec = {"intent": i, "fill": _fill(i, outs.get(i.get("intent_id")), virtual), "why": why}
        if tid not in by_id:
            orphans.append({"ticket_id": tid, "act": act, "coin": i.get("symbol"), "at": i.get("ts_decision")})
        acts.setdefault(tid, {}).setdefault(act, []).append(rec)
    skips = host_skips or {}
    tickets: list[dict] = []
    for tid in sorted(set(by_id) | set(acts)):
        r = by_id.get(tid)
        if r is None:
            continue                                             # 只在 orphans 里报
        if tid not in taken and tid not in acts:
            continue                                             # 纸面满额没取,主机也没碰 —— 一致,不列
        tickets.append(_one(r, acts.get(tid, {}), tid in taken, skips.get(tid), a, virtual))
    return _summary(tickets, orphans, mode, asof)


def _one(r: dict, acts: dict[str, list], taken: bool, skip_why: Optional[str], asof: Optional[dt.date],
         virtual: bool) -> dict:
    pe, ps, px = _f(r.get("entry_px")), _f(r.get("stop_px")), _f(r.get("exit_px"))
    paper = {"status": r.get("status"), "entry_d": str(r.get("entry_d") or "")[:10] or None, "entry_px": pe,
             "stop_px": ps, "exit_d": str(r.get("exit_d") or "")[:10] or None, "exit_px": px,
             "exit_reason": r.get("exit_reason"), "r": _f(r.get("r_mult"))}
    out = {"ticket_id": r["ticket_id"], "symbol": r.get("symbol"), "signal_d": str(r.get("signal_d"))[:10],
           "paper": paper, "venue": None, "class": None, "breaches": [], "r_gap": None}
    enters = acts.get("enter") or []
    filled = [e for e in enters if e["fill"]["px"]]
    entry_d = _d(r.get("entry_d"))
    if not enters:
        if not taken:
            out["class"] = "skipped_cap"
        elif skip_why:
            out["class"] = "not_executable"
            out["why"] = skip_why
        elif r.get("status") == "pending" or not entry_d or (asof and entry_d > asof):
            out["class"] = "pending"
        else:
            out["class"] = "no_record"
            out["breaches"].append("no_record")
        return out
    if not filled:
        last = enters[-1]["fill"]["status"]
        out["class"] = "unfilled" if last != "pending" else "pending_fill"
        if last != "pending":
            out["breaches"].append("unfilled")
        return out
    e = filled[-1]
    ef, ei = e["fill"], e["intent"]
    v: dict[str, Any] = {"coin": ei.get("symbol"), "virtual": virtual, "entry_at": ei.get("ts_decision"),
                         "entry_px": ef["px"], "entry_notional": round(ef["notional"], 4),
                         "entry_vs_open_bps": _bps(ef["px"], pe), "entry_vs_decision_bps": _bps(ef["px"],
                                                                                                _f(ei.get("decision_mid")))}
    trig = acts.get("stop_trigger") or []
    v["stop_on_venue"] = bool(trig) if not virtual else None
    exits = [(k, x) for k in EXIT_ACTS for x in acts.get(k) or [] if x["fill"]["px"]]
    exits.sort(key=lambda kx: str(kx[1]["intent"].get("ts_decision")))
    fees = ef["fee"]
    if exits:
        kind, x = exits[-1]
        xf = x["fill"]
        line = _f(x["intent"].get("decision_mid")) if kind in ("stop_trigger", "stop_virtual") else None
        v.update({"exit_kind": kind, "exit_why": x["why"] or None, "exit_at": x["intent"].get("ts_decision"),
                  "exit_px": xf["px"], "exit_vs_plan_bps": _bps(xf["px"], px),
                  "stop_fill_vs_line_bps": _bps(xf["px"], line)})
        fees += xf["fee"]
        rf = (pe - ps) / pe if pe and ps and pe > ps else None
        if rf:
            vr = (xf["px"] / ef["px"] - 1.0) / rf - (fees / ef["notional"] / rf if ef["notional"] else 0.0)
            v["r"] = round(vr, 4)
            if paper["r"] is not None and r.get("status") == "closed":
                out["r_gap"] = round(vr - paper["r"], 4)
    v["fees"] = round(fees, 6)
    out["venue"], out["class"] = v, "venue"
    if not taken:
        out["breaches"].append("off_plan")
    if not virtual and not trig:
        out["breaches"].append("no_stop")
    pxd = _d(r.get("exit_d"))
    if r.get("status") == "closed" and not exits and pxd and asof and (asof - pxd).days > 1:
        out["breaches"].append("late_exit")
    return out


def _mean(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _summary(tickets: list[dict], orphans: list[dict], mode: str, asof: str) -> dict[str, Any]:
    cls: dict[str, int] = {}
    for t in tickets:
        cls[t["class"]] = cls.get(t["class"], 0) + 1
    ven = [t for t in tickets if t["class"] == "venue"]
    judged = [t for t in tickets if t["class"] in ("venue", "unfilled", "no_record")]
    clean = [t for t in judged if not t["breaches"]]
    closed = [t for t in ven if t["venue"].get("exit_px")]
    both = [t for t in closed if t["r_gap"] is not None]
    recent = sorted(judged, key=lambda t: t["signal_d"])[-RECENT_N:]
    serious = sum(1 for t in recent for b in t["breaches"] if b in SERIOUS) + len(orphans)
    clean_share = round(len(clean) / len(judged), 4) if judged else None
    stops = [t["venue"].get("stop_fill_vs_line_bps") for t in closed]
    summary = {
        "classes": cls, "orphans": len(orphans), "venue_tickets": len(ven), "closed_on_venue": len(closed),
        "clean": len(clean), "judged": len(judged), "clean_share": clean_share,
        "entry_vs_open_bps_mean": _mean([t["venue"]["entry_vs_open_bps"] for t in ven]),
        "entry_vs_decision_bps_mean": _mean([t["venue"]["entry_vs_decision_bps"] for t in ven]),
        "exit_vs_plan_bps_mean": _mean([t["venue"].get("exit_vs_plan_bps") for t in closed]),
        "stop_fill_vs_line_bps_mean": _mean(stops),
        "r_venue_sum": round(sum(t["venue"]["r"] for t in both), 3) if both else None,
        "r_paper_sum": round(sum(t["paper"]["r"] for t in both), 3) if both else None,
        "r_gap_mean": _mean([t["r_gap"] for t in both]),
    }
    if mode == "live":
        lev, why = earned_leverage(len(closed), clean_share, serious)
    else:
        lev, why = 1.0, "空跑不计入阶梯(规模只能用真钱的记录挣)"
    return {"mode": mode, "asof": asof, "summary": summary,
            "ladder": {"earned_max_leverage": lev, "why": why, "rungs": [{"closed_tickets": n, "max": lv}
                                                                       for n, lv in LADDER[::-1]],
                       "binding": False, "note": "建议,不自动生效;R_V2_PORTFOLIO_LEVERAGE 是 Jazz 的开关"},
            "tickets": tickets, "orphans": orphans}


def host_skips_from(details: Iterable[dict]) -> dict[str, str]:
    """纯函数。executor_host 的 r_v2 cycle 明细 → {ticket_id: 原因}(主机说不可执行的、纸面满额跳过的)。"""
    out: dict[str, str] = {}
    for d in details:
        if not isinstance(d, dict) or (d.get("book") or d.get("book_name")) != "r_v2":
            continue
        for n in d.get("not_executable") or []:
            if isinstance(n, dict) and n.get("ticket_id"):
                out[n["ticket_id"]] = f"不可执行:{n.get('why') or ''}".strip()
        for tid in d.get("skipped_cap_paper") or []:
            out.setdefault(str(tid), "纸面满额跳过")
    return out


async def load_book_of_truth(mode: str = "live", asof: Optional[str] = None) -> dict[str, Any]:
    """读纸面账本、交易所意图 / 结果、主机明细 → reconcile。读不到就抛,不当 0 行(S-180)。"""
    from src.data.style.header import _read_all
    if mode not in TICKET_SLEEVE_FOR_MODE:
        raise ValueError(f"mode 必须是 {sorted(TICKET_SLEEVE_FOR_MODE)}")
    asof = asof or (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    paper = await _read_all("r_tickets_paper", {
        "select": "ticket_id,symbol,signal_d,status,entry_d,entry_px,stop_px,exit_d,exit_px,exit_reason,r_mult",
        "status": "in.(pending,open,closed)", "order": "ticket_id.asc"})
    intents = await _read_all("execution_intents", {
        "select": "intent_id,ts_decision,symbol,side,target_notional_usd,decision_mid,sleeve,signal_ref,order_type,"
                  "limit_price", "sleeve": f"eq.{TICKET_SLEEVE_FOR_MODE[mode]}", "order": "intent_id.asc"})
    outcomes: list[dict] = []
    ids = [i["intent_id"] for i in intents]
    for k in range(0, len(ids), 80):
        outcomes += await _read_all("execution_outcomes", {
            "select": "intent_id,ts_resolved,status,filled_notional_usd,avg_fill_price,fee_usd",
            "intent_id": f"in.({','.join(ids[k:k + 80])})", "order": "intent_id.asc"})
    att = await _read_all("loop_attempt", {"select": "id,detail", "loop_name": "eq.executor_host",
                                           "detail->>book": "eq.r_v2", "detail->>mode": f"eq.{mode}",
                                           "detail->>phase": "eq.intents", "order": "id.asc"})
    skips = host_skips_from(a.get("detail") or {} for a in att)
    # Jazz ⓪:J 票并进纸面;off / flat 期间被挡下的 R-v2 票不是「主机没记录」,是人的决定(记分在 /internal/regime-call)
    from src.data.execution.regime_call import governing_call, read_calls, read_j_tickets
    calls, j_rows = await read_calls(), await read_j_tickets()
    paper += [{"ticket_id": j["ticket_id"], "symbol": j["coin"], "signal_d": j["signal_d"], "status": j["status"],
               "entry_d": j.get("entry_d"), "entry_px": j.get("entry_px"), "stop_px": j.get("stop_px"),
               "exit_d": j.get("exit_d"), "exit_px": j.get("exit_px"), "exit_reason": j.get("exit_reason"),
               "r_mult": j.get("r_mult")} for j in j_rows if j.get("status") in ("pending", "open", "closed")]
    for r in paper:
        c = governing_call(calls, r["signal_d"]) if r.get("signal_d") else None
        if c and c.get("state") in ("off", "flat") and not str(r["ticket_id"]).startswith("J:"):
            skips.setdefault(r["ticket_id"], f"Jazz ⓪ = {c['state']}(判断 #{c.get('id')})")
    # S-690(Jazz 10-27 真钱):开票日 OI/市值快照分位 ≥ 2/3 的票计划里不进 —— 规则挡的,不是「主机没记录」
    for t in await _read_all("r_ticket_oi_tags", {"select": "ticket_id,p_live", "high_live": "is.true"}):
        skips.setdefault(t["ticket_id"], f"S-690 过滤:开票日 OI/市值分位 {float(t['p_live']):.2f} ≥ 2/3")
    return reconcile(paper, intents, outcomes, mode=mode, asof=asof, host_skips=skips)
