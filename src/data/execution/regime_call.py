"""Jazz ⓪ 开关 —— 人的「何时在场 / 在哪」判断,被记录、被执行、被记分(docs/HIGH_DIM_ONTOLOGY.md §5b-bis;Jazz 10-21)。

## 为什么

S-658 / S-659(10-21):R-v2 的钱在「山寨走趋势的月份拿着走趋势的币」;进场形态与系统自身战绩都分不开好坏月份。
⓪ 层(何时在场 + 在哪)决定输赢,而系统化的 ⓪ 还没建成(T-167 在测)。Jazz 能给出这个判断(HYPE / UNI 第二段)。
**高维选战场,低维集中火力:** 人给判断,执行器按规则执行(止损、上限、杠杆阶梯不变),每一次判断都被记分,
与系统化的 ⓪ 并排 —— 中心风险台据此决定哪一边拿更多资本。

## 一条判断(`regime_calls`,只追加;每条是完整状态,不是增量)

- `state`:**on** = 照常,战场名单上的币各开一张 J 票,信心档位放大每票风险;**off** = 不开任何新票
  (R-v2 与 J 票),在持的照规则走完;**flat** = 不开新票,且所有在持的票下一轮出场。
- `conviction` 1 / 2 / 3 ⇒ 每票风险 × 1 / 1.5 / 2(主机再守 2 倍上限)。只在 on 时生效。
- `battlefield`:HL 永续币名(PEPE 自动认成 kPEPE),最多 5 个;只在 on 时允许。
- `close_coins`:这些币的 J 票下一轮出场(人的提前离场,记分单列)。
- `effective_d` = 提交时的 UTC 日期:管 asof ≥ effective_d 的计划(主机 effective_d + 1 日 00:45 后执行)。
  **主机一天只执行一次** —— 下午说 flat,第二天 00:45 才平;要立刻停,用一键停(halt)。
- 默认 14 天到期,最长 60 天。到期 / 没有判断 ⇒ 系统默认(on、1 档、无战场)。

## J 票(`j_tickets`)= 人选战场、系统管票

信号日 D = 判断生效后的那个 asof;进场 = D + 1 日开盘;止损 = 进场 − 2.5 × ATR14[D](HL 日线);
收盘破 SMA20 ⇒ 次日开盘出;120 根到期;10 天没有日线 ⇒ 按最后收盘出。与 R-v2 内核(r_tickets_scan)逐步同序,
R 同口径(含 0.4% 来回成本)。**唯一的不同:** SMA20 离场要等这张票第一次收盘站上 SMA20 之后才生效(`sma_armed`)——
R-v2 只在突破时进场(必在 SMA20 之上),人却可能在回调里进(如 10-20 的 HYPE 收 80.3、SMA20 84.6);
不这样,人在回调里选的票第二天就会被 SMA20 打出去。之前只有 2.5 ATR 止损。日线 = HL `candleSnapshot`(场馆自己的 K 线;只用已收盘的)。
**S-657:** HL 独有币不在 binance_hist 面板里,所以 J 票不能读面板。

判活:`select last_d from j_tickets_state` ≥ 前天;`loop_attempt` 里 `_j_tickets_scan` 每小时一条。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

STATES = ("on", "off", "flat")
RISK_MULT = {1: 1.0, 2: 1.5, 3: 2.0}
MAX_RISK_MULT = 2.0
DEFAULT_DAYS, MAX_DAYS = 14, 60
MAX_BATTLEFIELD = 5
STOP_ATR, COST, TIME_BARS, NO_DATA_DAYS = 2.5, 0.004, 120, 10
MIN_BARS = 20
J_PREFIX = "J:"
_CLOSED_LOOKBACK_DAYS = 5
HL_INFO = "https://api.hyperliquid.xyz/info"
WRITES_TABLES = ("regime_calls", "j_tickets", "j_tickets_state")


def _d(x: Any) -> Optional[dt.date]:
    if x is None or x == "":
        return None
    return x if isinstance(x, dt.date) and not isinstance(x, dt.datetime) else dt.date.fromisoformat(str(x)[:10])


def _ts(x: Any) -> dt.datetime:
    v = x if isinstance(x, dt.datetime) else dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


def hl_name(coin: str, names: Iterable[str]) -> Optional[str]:
    """Jazz 写的名字 → HL 永续名(大小写不敏感;PEPE ↔ kPEPE)。"""
    by_upper = {n.upper(): n for n in names}
    c = str(coin or "").strip().upper()
    if c in by_upper:
        return by_upper[c]
    if "K" + c in by_upper:
        return by_upper["K" + c]
    return None


# ── 一条判断 ────────────────────────────────────────────────────────────────────────────────────────────
def validate_call(body: Any, hl_names: Optional[Iterable[str]], now: dt.datetime) -> tuple[Optional[dict], list[str]]:
    """纯函数。POST 的 body → 一行 regime_calls(或拒绝理由)。HL 挂牌读不到 ⇒ 拒绝(不收认不出的币名)。"""
    why: list[str] = []
    if not isinstance(body, dict):
        return None, ["body 必须是 JSON 对象"]
    extra = set(body) - {"state", "conviction", "battlefield", "close", "note", "days"}
    if extra:
        why.append(f"未知字段 {sorted(extra)}")
    state = str(body.get("state") or "").strip().lower()
    if state not in STATES:
        why.append(f"state 必须是 {list(STATES)}")
    try:
        conviction = int(body.get("conviction", 1))
    except (TypeError, ValueError):
        conviction = 0
    if conviction not in RISK_MULT:
        why.append("conviction 必须是 1 / 2 / 3")
    try:
        days = int(body.get("days", DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = 0
    if not (1 <= days <= MAX_DAYS):
        why.append(f"days 必须在 1–{MAX_DAYS}")
    note = str(body.get("note") or "")
    if len(note) > 500:
        why.append("note 最多 500 字")
    raw_bf = body.get("battlefield") or []
    raw_close = body.get("close") or []
    if not isinstance(raw_bf, list) or not isinstance(raw_close, list):
        return None, why + ["battlefield / close 必须是列表"]
    if raw_bf and state != "on":
        why.append("战场名单只在 state = on 时有意义")
    if len(raw_bf) > MAX_BATTLEFIELD:
        why.append(f"战场最多 {MAX_BATTLEFIELD} 个币")
    names = list(hl_names) if hl_names is not None else None
    if names is None and (raw_bf or raw_close):
        why.append("HL 挂牌读不到 —— 认不出币名,这次不收")
    bf, close = [], []
    for lst, out in ((raw_bf, bf), (raw_close, close)):
        for c in lst:
            n = hl_name(c, names or [])
            if n is None and names is not None:
                why.append(f"{c!r} 不是 HL 上的永续")
            elif n and n not in out:
                out.append(n)
    both = sorted(set(bf) & set(close))
    if both:
        why.append(f"{both} 同时在战场和离场名单里")
    if why:
        return None, why
    now = now.astimezone(dt.timezone.utc)
    return {"at": now.isoformat(), "state": state, "conviction": conviction if state == "on" else 1,
            "battlefield": bf, "close_coins": close, "note": note, "effective_d": now.date().isoformat(),
            "expires_at": (now + dt.timedelta(days=days)).isoformat(), "source": "jazz"}, []


def governing_call(calls: Iterable[dict], asof: Any) -> Optional[dict]:
    """纯函数。管 asof 这一天计划的那条判断:effective_d ≤ asof、到期时间晚于 asof + 1 日 00:00 UTC,取最新提交的。"""
    a = _d(asof)
    cutoff = dt.datetime.combine(a + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc)
    live = [c for c in calls if _d(c.get("effective_d")) and _d(c["effective_d"]) <= a and _ts(c["expires_at"]) > cutoff]
    return max(live, key=lambda c: _ts(c["at"])) if live else None


def call_view(call: Optional[dict]) -> dict:
    if not call:
        return {"state": "on", "conviction": 1, "battlefield": [], "source": "system_default",
                "why": "没有生效的 Jazz 判断(或已到期)⇒ 系统默认"}
    return {k: call.get(k) for k in ("id", "at", "state", "conviction", "battlefield", "close_coins", "note",
                                       "effective_d", "expires_at")} | {"source": "jazz"}


# ── 计划叠加(Railway 出计划时)───────────────────────────────────────────────────────────────────────────
def overlay(tplan: dict, call: Optional[dict], j_rows: Iterable[dict]) -> dict:
    """纯函数。R-v2 计划 + 生效的判断 + J 票账本 → 主机计划。主机对不在 hold 里的票一律出场,所以 J 票每天都要列进 hold。"""
    out = dict(tplan)
    out["regime_call"] = call_view(call)
    if not tplan.get("ready"):
        return out
    state = (call or {}).get("state") or "on"
    mult = RISK_MULT.get(int((call or {}).get("conviction") or 1), 1.0) if state == "on" else 1.0
    a = _d(tplan["asof"])
    enter = [dict(e) for e in tplan.get("enter") or []]
    hold = [dict(h) for h in tplan.get("hold") or []]
    exit_ = [dict(x) for x in tplan.get("exit") or []]
    blocked: list[dict] = []
    if state in ("off", "flat"):
        blocked = [{**e, "why": f"Jazz ⓪ = {state}"} for e in enter]
        enter = []
    else:
        for e in enter:
            e["risk_mult"] = mult
    if state == "flat":
        exit_ += [{"ticket_id": h["ticket_id"], "symbol": h.get("symbol"), "why": "flat: Jazz ⓪", "at": "today_open"}
                  for h in hold]
        hold = []
    for r in sorted(j_rows, key=lambda r: r["ticket_id"]):
        st, tid = r.get("status"), r["ticket_id"]
        if st == "pending" and _d(r.get("signal_d")) == a and state == "on":
            sf = STOP_ATR * float(r["atr14"]) / float(r["ref_close"]) if r.get("atr14") and r.get("ref_close") else None
            if sf and 0 < sf < 0.9:
                enter.append({"ticket_id": tid, "symbol": r["coin"], "signal_d": str(r["signal_d"])[:10],
                              "atr14": r["atr14"], "ref_close": r["ref_close"], "stop_frac": sf,
                              "risk_mult": min(float(r.get("risk_mult") or 1.0), MAX_RISK_MULT), "book": "jazz"})
        elif st == "open" and not r.get("exit_flag") and state != "flat":
            hold.append({"ticket_id": tid, "symbol": r["coin"], "entry_d": str(r.get("entry_d"))[:10],
                         "paper_entry_px": r.get("entry_px"), "paper_stop_px": r.get("stop_px"),
                         "bars_held": r.get("bars_held"), "book": "jazz"})
        elif st == "open":
            exit_.append({"ticket_id": tid, "symbol": r["coin"], "at": "today_open", "book": "jazz",
                          "why": "flat: Jazz ⓪" if state == "flat" and not r.get("exit_flag") else r.get("exit_why") or "sma20"})
        elif st == "closed" and _d(r.get("exit_d")) and _d(r["exit_d"]) >= a - dt.timedelta(days=_CLOSED_LOOKBACK_DAYS):
            exit_.append({"ticket_id": tid, "symbol": r["coin"], "why": r.get("exit_reason"), "book": "jazz",
                          "at": str(r.get("exit_d"))[:10], "paper_exit_px": r.get("exit_px")})
    out.update(enter=enter, hold=hold, exit=exit_, blocked_by_call=blocked)
    return out


# ── J 票状态机(与 r_tickets_scan 逐步同序)──────────────────────────────────────────────────────────────
def indicators(bars: list[tuple]) -> dict[str, dict]:
    """纯函数。[(d, o, h, l, c)] 按日期 → {d: {o,h,l,c,sma20,atr14}}。SMA20 / ATR14 与内核同窗(含当天,不足按已有的)。"""
    out: dict[str, dict] = {}
    closes, trs = [], []
    pc = None
    for d, o, h, l, c in sorted(bars):
        closes.append(c)
        prev = pc if pc is not None else c
        trs.append(max(h - l, abs(h - prev), abs(l - prev)))
        out[str(d)[:10]] = {"o": o, "h": h, "l": l, "c": c, "sma20": sum(closes[-20:]) / len(closes[-20:]),
                            "atr14": sum(trs[-14:]) / len(trs[-14:]), "n": len(closes)}
        pc = c
    return out


def _r(exit_px: float, t: dict) -> float:
    e, s = float(t["entry_px"]), float(t["stop_px"])
    return (exit_px - e) / (e - s) - COST * e / (e - s)


def _close(t: dict, d: str, px: float, reason: str) -> dict:
    return {**t, "status": "closed", "exit_d": d, "exit_px": px, "exit_reason": reason, "r_mult": _r(px, t)}


def j_day(tickets: dict[str, dict], ind: dict[str, dict[str, dict]], day: dt.date, call: Optional[dict]) -> dict[str, dict]:
    """纯函数。推进一天:ticket_id → 行;ind = {coin: indicators()}。返回改过的票(含新开的 pending)。"""
    d = day.isoformat()
    changed: dict[str, dict] = {}
    cur = {k: dict(v) for k, v in tickets.items()}

    def put(t):
        cur[t["ticket_id"]] = t
        changed[t["ticket_id"]] = t

    # 1. 昨天打了出场标记的,今天开盘出
    for t in list(cur.values()):
        b = ind.get(t["coin"], {}).get(d)
        if t["status"] == "open" and t.get("exit_flag") and b:
            why = t.get("exit_why") or "sma20"
            put(_close(t, d, b["o"], why if why in ("human", "flat") else "sma20"))
    # 2. pending 今天开盘成交
    for t in list(cur.values()):
        b = ind.get(t["coin"], {}).get(d)
        if t["status"] == "pending" and b and _d(t["signal_d"]) < day:
            stop = b["o"] - STOP_ATR * float(t["atr14"])
            put({**t, "status": "open" if stop > 0 else "void", "entry_d": d, "entry_px": b["o"], "stop_px": stop})
    # 3. 在持的:计根数 → 止损 → SMA20 标记 → 到期
    for t in list(cur.values()):
        b = ind.get(t["coin"], {}).get(d)
        if t["status"] != "open" or t.get("exit_flag") or not b:
            continue
        t = {**t, "bars_held": int(t.get("bars_held") or 0) + 1}
        if b["l"] <= float(t["stop_px"]):
            px = b["o"] if (d > str(t["entry_d"])[:10] and b["o"] <= float(t["stop_px"])) else float(t["stop_px"])
            put(_close(t, d, px, "stop"))
        elif b["c"] < b["sma20"] and t.get("sma_armed"):
            put({**t, "exit_flag": True, "exit_why": "sma20"})
        elif t["bars_held"] >= TIME_BARS:
            put(_close(t, d, b["c"], "time"))
        else:
            put({**t, "sma_armed": bool(t.get("sma_armed")) or b["c"] > b["sma20"]})
    # 3b. 10 天没有日线 ⇒ 按最后收盘出
    for t in list(cur.values()):
        if t["status"] != "open":
            continue
        days = sorted(k for k in ind.get(t["coin"], {}) if k <= d)
        if days and _d(days[-1]) < day - dt.timedelta(days=NO_DATA_DAYS - 1):
            put(_close(t, days[-1], ind[t["coin"]][days[-1]]["c"], "no_data"))
    # 3c. 人的离场:flat ⇒ 全部;close_coins ⇒ 这些币(开盘出,与 SMA20 标记同一条路)
    state = (call or {}).get("state") or "on"
    closing = set((call or {}).get("close_coins") or [])
    for t in list(cur.values()):
        if t["status"] == "open" and not t.get("exit_flag") and (state == "flat" or t["coin"] in closing):
            put({**t, "exit_flag": True, "exit_why": "flat" if state == "flat" else "human"})
    # 4. 战场:on 时,没有 pending / open J 票的币开一张(信号日 = 今天,明天开盘进)
    if call and state == "on":
        busy = {t["coin"] for t in cur.values() if t["status"] in ("pending", "open")}
        for coin in call.get("battlefield") or []:
            b = ind.get(coin, {}).get(d)
            if coin in busy or not b or b["n"] < MIN_BARS or b["atr14"] <= 0:
                continue
            put({"ticket_id": f"{J_PREFIX}{coin}:{d}", "coin": coin, "call_id": call["id"], "signal_d": d,
                 "atr14": b["atr14"], "ref_close": b["c"], "risk_mult": RISK_MULT[int(call.get("conviction") or 1)],
                 "status": "pending", "bars_held": 0, "exit_flag": False, "sma_armed": False})
    return changed


def j_scan_days(tickets: dict[str, dict], ind: dict[str, dict[str, dict]], calls: list[dict], d_from: dt.date,
                d_to: dt.date) -> tuple[dict[str, dict], dt.date]:
    """纯函数。从 d_from 推到 d_to(含);返回 (改过的票, 推进到的最后一天)。"""
    cur = {k: dict(v) for k, v in tickets.items()}
    changed: dict[str, dict] = {}
    day, last = d_from, d_from - dt.timedelta(days=1)
    while day <= d_to:
        ch = j_day(cur, ind, day, governing_call(calls, day))
        cur.update(ch)
        changed.update(ch)
        last = day
        day += dt.timedelta(days=1)
    return changed, last


# ── 记分(纸面口径;交易所口径见 book_of_truth)────────────────────────────────────────────────────────────
def scorecard(calls: list[dict], j_rows: list[dict], rv2_rows: list[dict],
              flat_opens: Optional[dict[tuple[str, str], float]] = None) -> dict[str, Any]:
    """纯函数。每条判断的账:J 票 R、off / flat 期间被挡下的 R-v2 票(它们的纸面 R = 这个判断的机会成本,负数 = 躲过的)、
    信心档位多拿 / 多亏的 R、flat 提前平掉的 R-v2 票(按平仓那天开盘算的 R − 纸面 R,正数 = 平对了)。"""
    flat_opens = flat_opens or {}
    out = []
    for c in sorted(calls, key=lambda c: _ts(c["at"])):
        cid = c["id"]
        js = [j for j in j_rows if j.get("call_id") == cid]
        governed = [r for r in rv2_rows if r.get("status") in ("pending", "open", "closed") and r.get("signal_d")
                    and (governing_call(calls, r["signal_d"]) or {}).get("id") == cid]
        closed = [r for r in governed if r.get("r_mult") is not None]
        row: dict[str, Any] = {**call_view(c), "j_tickets": len(js),
                               "j_r": round(sum(float(j["r_mult"]) * float(j.get("risk_mult") or 1.0)
                                                for j in js if j.get("r_mult") is not None), 3),
                               "j_open": sum(1 for j in js if j.get("status") in ("pending", "open"))}
        if c["state"] in ("off", "flat"):
            row["blocked_rv2"] = len(governed)
            row["blocked_rv2_r"] = round(sum(float(r["r_mult"]) for r in closed), 3)
        elif int(c.get("conviction") or 1) > 1:
            m = RISK_MULT[int(c["conviction"])] - 1.0
            row["conviction_extra_r"] = round(m * sum(float(r["r_mult"]) for r in closed), 3)
        if c["state"] == "flat":
            eff = _d(c["effective_d"])
            saved = []
            for r in rv2_rows:
                ed, xd = _d(r.get("entry_d")), _d(r.get("exit_d"))
                if r.get("status") not in ("open", "closed") or not ed or ed > eff or (xd and xd <= eff):
                    continue
                o = flat_opens.get((r["symbol"], (eff + dt.timedelta(days=1)).isoformat()))
                if o is None or r.get("r_mult") is None:
                    continue
                e, s = float(r["entry_px"]), float(r["stop_px"])
                saved.append((o - e) / (e - s) - COST * e / (e - s) - float(r["r_mult"]))
            row["flat_saved_r"] = round(sum(saved), 3)
            row["flat_tickets"] = len(saved)
        out.append(row)
    tot = {"calls": len(out), "j_r": round(sum(r["j_r"] for r in out), 3),
           "blocked_rv2_r": round(sum(r.get("blocked_rv2_r", 0.0) for r in out), 3),
           "conviction_extra_r": round(sum(r.get("conviction_extra_r", 0.0) for r in out), 3),
           "flat_saved_r": round(sum(r.get("flat_saved_r", 0.0) for r in out), 3)}
    tot["human_edge_r"] = round(tot["j_r"] - tot["blocked_rv2_r"] + tot["conviction_extra_r"] + tot["flat_saved_r"], 3)
    return {"totals": tot, "calls": out[::-1],
            "note": "单位 B(一张票的风险,纸面 R 与 R-v2 同口径;J 票按自己的风险倍数加权);"
                    "人的边 = J 票 + 信心档位多拿的 − 被挡下的 R-v2 + flat 躲过的。"
                    "J 票的 R 是人的选择本身;交易所成交另见 /internal/executor/book-of-truth"}


# ── IO ───────────────────────────────────────────────────────────────────────────────────────────────────
async def _hl_post(body: dict, timeout: float = 20.0) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(HL_INFO, json=body)
        r.raise_for_status()
        return r.json()


async def hl_perp_names() -> Optional[list[str]]:
    """HL 在挂的永续名(不含已下架);读不到 ⇒ None(调用方拒绝,不猜)。"""
    try:
        meta = await _hl_post({"type": "meta"})
        return [a["name"] for a in meta.get("universe") or [] if not a.get("isDelisted")]
    except Exception as e:                                       # noqa: BLE001
        log.warning("[REGIME] HL meta unreachable: %s", e)
        return None


async def hl_daily(coins: Iterable[str], start: dt.date) -> dict[str, list[tuple]]:
    """显式名单的 HL 日线(只取已收盘的,S-644)。执行用途、名单 ≤ 战场 + 在持,不是挂牌扇出(source_policy)。"""
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    start_ms = int(dt.datetime.combine(start, dt.time(0), tzinfo=dt.timezone.utc).timestamp() * 1000)
    out: dict[str, list[tuple]] = {}
    for coin in sorted(set(coins)):
        cs = await _hl_post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": start_ms,
                                                                "endTime": now_ms}})
        out[coin] = [(dt.datetime.fromtimestamp(int(k["t"]) / 1000, dt.timezone.utc).date().isoformat(),
                      float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]))
                     for k in cs or [] if int(k["T"]) < now_ms]
    return out


async def read_calls() -> list[dict]:
    from src.data.style.header import _read_all
    return await _read_all("regime_calls", {"select": "id,at,state,conviction,battlefield,close_coins,note,"
                                                      "effective_d,expires_at,source", "order": "id.asc"})


async def read_j_tickets() -> list[dict]:
    from src.data.style.header import _read_all
    return await _read_all("j_tickets", {"select": "*", "order": "ticket_id.asc"})


async def post_call(body: Any, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """校验 → 写一行 regime_calls → 读回(带 id)。"""
    from src.api.store import supabase_insert_table
    now = now or dt.datetime.now(dt.timezone.utc)
    needs_names = bool(isinstance(body, dict) and (body.get("battlefield") or body.get("close")))
    names = await hl_perp_names() if needs_names else []
    row, why = validate_call(body, names, now)
    if row is None:
        return {"ok": False, "rejected": why}
    w = await supabase_insert_table("regime_calls", [row])
    if not w:
        return {"ok": False, "rejected": [f"写不进 regime_calls:{getattr(w, 'why', '')}"]}
    calls = await read_calls()
    mine = [c for c in calls if _ts(c["at"]) == _ts(row["at"])]
    return {"ok": True, "call": call_view(mine[-1] if mine else row),
            "governs_from_asof": row["effective_d"],
            "executes": f"主机在 {(_d(row['effective_d']) + dt.timedelta(days=1)).isoformat()} 00:45 UTC 之后的那一轮执行"}


async def run_j_scan(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """每小时(R-v2 扫描之前):把 J 票推进到最后一个已收盘的 UTC 日。没有判断也没有 J 票 ⇒ 只推进日期。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = now or dt.datetime.now(dt.timezone.utc)
    d_to = now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)
    st = await _read_all("j_tickets_state", {"select": "last_d", "id": "eq.1"})
    last = _d(st[0]["last_d"]) if st else None
    d_from = (last + dt.timedelta(days=1)) if last else d_to
    if d_from > d_to:
        return {"status": "ok", "reason": "up to date", "last_d": d_to.isoformat()}
    calls = await read_calls()
    rows = await read_j_tickets()
    live = {r["ticket_id"]: r for r in rows if r.get("status") in ("pending", "open")}
    coins = {r["coin"] for r in live.values()}
    for day in (d_from + dt.timedelta(days=k) for k in range((d_to - d_from).days + 1)):
        c = governing_call(calls, day)
        if c and c.get("state") == "on":
            coins |= set(c.get("battlefield") or [])
    ind: dict[str, dict] = {}
    if coins:
        try:
            bars = await hl_daily(coins, d_from - dt.timedelta(days=60))
        except Exception as e:                                   # noqa: BLE001
            return {"status": "refused", "reason": f"HL 日线读不到,停在 {last}:{type(e).__name__}: {str(e)[:160]}"}
        ind = {k: indicators(v) for k, v in bars.items()}
        missing = sorted(k for k in coins if not ind.get(k) or d_to.isoformat() not in ind[k])
        if missing and live and any(live[t]["coin"] in missing for t in live):
            return {"status": "refused", "reason": f"在持 J 票的币 {missing} 在 {d_to} 没有日线,停在 {last}"}
    changed, done = j_scan_days(live, ind, calls, d_from, d_to)
    if changed:
        cols = ("ticket_id", "coin", "call_id", "signal_d", "atr14", "ref_close", "risk_mult", "status", "entry_d",
                "entry_px", "stop_px", "bars_held", "exit_flag", "sma_armed", "exit_why", "exit_d", "exit_px",
                "exit_reason", "r_mult")
        up = [{k: t.get(k) for k in cols} | {"updated_at": now.isoformat()} for t in changed.values()]
        w = await supabase_upsert_table("j_tickets", up, on_conflict="ticket_id")
        if not w:
            return {"status": "error", "reason": f"j_tickets 写不进去:{getattr(w, 'why', '')}"}
    res = {"from": d_from.isoformat(), "to": done.isoformat(), "changed": len(changed), "coins": sorted(coins),
           "open_now": sum(1 for t in {**live, **changed}.values() if t.get("status") == "open"),
           "pending_now": sum(1 for t in {**live, **changed}.values() if t.get("status") == "pending")}
    w = await supabase_upsert_table("j_tickets_state", [{"id": 1, "last_d": done.isoformat(), "last_run_at": now.isoformat(),
                                                         "last_result": json.loads(json.dumps(res, default=str))}],
                                    on_conflict="id")
    if not w:
        return {"status": "error", "reason": f"j_tickets_state 写不进去:{getattr(w, 'why', '')}", "detail": res}
    return {"status": "ok", "reason": f"推进到 {done}:改了 {len(changed)} 张", "detail": res}


async def load_scorecard() -> dict[str, Any]:
    from src.data.style.header import _read_all
    calls, js = await read_calls(), await read_j_tickets()
    rv2 = await _read_all("r_tickets_paper", {"select": "ticket_id,symbol,signal_d,status,entry_d,entry_px,stop_px,"
                                                        "exit_d,exit_px,r_mult", "order": "ticket_id.asc"})
    opens: dict[tuple[str, str], float] = {}
    for c in calls:
        if c["state"] != "flat":
            continue
        eff = _d(c["effective_d"])
        day = (eff + dt.timedelta(days=1)).isoformat()
        syms = sorted({r["symbol"] for r in rv2 if _d(r.get("entry_d")) and _d(r["entry_d"]) <= eff
                       and not (_d(r.get("exit_d")) and _d(r["exit_d"]) <= eff)})
        if syms:
            bars = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,open", "source": "eq.binance_hist",
                                                   "trade_date": f"eq.{day}", "symbol": f"in.({','.join(syms)})"})
            opens.update({(b["symbol"], day): float(b["open"]) for b in bars if b.get("open")})
    return scorecard(calls, js, rv2, opens)
