"""S-683 两条做空**纸面**前向臂(Jazz 10-25「开」;台账 S-683 预注册,写死,不调参)。

- 臂 L `short_listing_hedged`:Binance U 本位永续新合约,第 8 根日线开盘空(信号 = 第 7 根收盘),s = 50%,60 天;
  同时按 BTCUSDT 永续开盘价等名义多 BTC,空腿哪天出 BTC 腿就那天开盘出。判 **对冲 R**。
- 臂 H `short_h4_gate`:S-681 H4(熊市反弹失败)一字不改,加一条:信号日 majors 闸门关(与 `r_tickets_scan` 同一个闸门)。
- **宇宙(S-683 修订,inception 前):只做加密合约**(`perp_bv_pairs.kind` = 'coin')。Binance 2025-12 起上了 200 多个
  股票 / 商品 / 外汇永续,臂的原因(低流通、解锁卖压)对它们不成立;没分类的合约也不进。

**一个内核。** 单票的语义与研究的 `docs/research/short_lab_common.short_ticket` 逐行相同(次日开盘进;日内触及止损按止损价、
跳空开在止损上方按开盘;到期 = 第 ei + N 根开盘;规则出场 = 次日开盘;单边 0.10%),研究脚本能拿同一批日线逐张对
(A 道 T-199 的 2026 清单)。资金费:空头收正费率;`funding_history`(binance_perp)里有多少记多少,
月档到了由 `_binance_vision_funding` 补齐(视图 `funding_vision_plan` 已把本表的合约并进去),`funding_days` 报覆盖。

**前向。** 信号日 ≥ INCEPTION 才算。每轮从 inception 前 WARMUP_DAYS 天起把日线读进来,整段重算(确定性的:档是最终的);
已平仓的票**价格字段不再改**(重算出来不同 ⇒ 记 drift,不覆盖),只有资金费字段会随月档补齐而更新。
数据没到(最后一天的合约数 < 前一天的 90%,或闸门那天没值)⇒ 停在前一天,写明原因。

钱曲线(只报):每票风险 0.5%、最多同时 10 张、先到先得;名义 = 0.5% × 前一日权益 ÷ 止损距离;成本与 R 同一口径
(单边 0.10%);臂 L 的名义同时开在 BTC 腿上。经前向锁写 `short_paper_money`(前天及更早不再改)。

判活:`select arm, last_d from short_paper_state` ≥ 前天;`loop_attempt` 里 `_short_paper`;
      `select arm, max(d) from short_paper_money group by arm` = last_d。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

import numpy as np

ARM_L = "short_listing_hedged"
ARM_H = "short_h4_gate"
ARMS = (ARM_L, ARM_H)
INCEPTION = "2026-10-26"
RULE_VERSION = "s683_v1"
COST_SIDE = 0.001
L_S, L_N, L_SIGNAL_IDX = 0.50, 60, 6
H_N, H_STOP_CAP, H_MIN_ADV, H_MIN_I = 30, 0.30, 5e6, 220
MONEY_F, MONEY_CAP = 0.005, 10
WARMUP_DAYS = 280
HEDGE_PAIR = "BTCUSDT"
TICKETS, STATE, MONEY = "short_paper_tickets", "short_paper_state", "short_paper_money"
WRITES_TABLES = ("short_paper_tickets", "short_paper_state", "short_paper_money")   # 字面量:schema_manifest 只读字面量
#: 平仓后不再改的价格字段(资金费字段可随月档补齐而更新)
FROZEN_FIELDS = ("entry_d", "entry_px", "stop_px", "exit_d", "exit_px", "why")


# ── 指标(只用当天及以前)──────────────────────────────────────────────────────────────────────────
def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.r_[0.0, x])
    for i in range(n - 1, len(x)):
        out[i] = (cs[i + 1] - cs[i + 1 - n]) / n
    return out


def prep(a: dict) -> dict:
    return {"adv": rolling_mean(a["qv"], 30), "sma20": rolling_mean(a["c"], 20), "sma200": rolling_mean(a["c"], 200)}


# ── 单票(= short_lab_common.short_ticket,不含资金费)──────────────────────────────────────────────
def short_ticket(a: dict, i: int, s: float, n_hold: int, exit_rule: Optional[Callable[[dict, int], bool]] = None,
                 stop_px: Optional[float] = None) -> Optional[dict]:
    """信号下标 i(收盘定)。下一根还没到 ⇒ status pending。止损价无效(≤ 进场)⇒ None(研究里这张票不存在)。"""
    n = len(a["d"])
    ei = i + 1
    if ei >= n:
        return {"signal_d": a["d"][i], "status": "pending", "i": i}
    entry = float(a["o"][ei])
    stop = float(stop_px) if stop_px is not None else entry * (1 + s)
    if not (stop > entry > 0):
        return None
    risk = stop / entry - 1
    last = min(ei + n_hold, n - 1)
    xi = xp = why = None
    gap = False
    for j in range(ei, last + 1):
        if j > ei and a["o"][j] >= stop:
            xi, xp, why, gap = j, float(a["o"][j]), "stop_gap", True
            break
        if a["h"][j] >= stop:
            xi, xp, why = j, stop, "stop"
            break
        if j == ei + n_hold:
            xi, xp, why = j, float(a["o"][j]), "time"
            break
        if exit_rule is not None and exit_rule(a, j) and j + 1 <= n - 1:
            xi, xp, why = j + 1, float(a["o"][j + 1]), "rule"
            break
    still = xi is None
    if still:
        xi, xp, why = n - 1, float(a["c"][n - 1]), "open"
    gross = (entry - xp) / entry
    return {"signal_d": a["d"][i], "entry_d": a["d"][ei], "exit_d": a["d"][xi], "ei": ei, "xi": xi, "i": i,
            "entry_px": entry, "stop_px": stop, "exit_px": xp, "risk": risk, "gross": gross, "why": why, "gap": gap,
            "status": "open" if still else "closed", "hold_days": xi - ei}


def chain(tickets: list[dict]) -> list[dict]:
    """同币持仓期间不叠票:按进场先后贪心(pending 视为占位)。= 研究的 chain。"""
    by: dict[str, list[dict]] = {}
    for t in tickets:
        by.setdefault(t["pair"], []).append(t)
    out = []
    for _, ts in by.items():
        ts.sort(key=lambda t: t["i"])
        last_x = -1
        for t in ts:
            ei = t["i"] + 1
            if ei > last_x:
                out.append(t)
                last_x = t["xi"] if t.get("xi") is not None else 10 ** 9
    out.sort(key=lambda t: (t["signal_d"], t["pair"]))
    return out


# ── 两条臂的信号 ───────────────────────────────────────────────────────────────────────────────────
def h4_setup(a: dict, p: dict, i: int) -> bool:
    """S-681 H4 的状态 + 设置 + 成交额(研究 s681_h234_seth.h4_parts / run_h4 逐行)。"""
    c, l = a["c"], a["l"]
    s200, s20 = p["sma200"], p["sma20"]
    if i < H_MIN_I or not (np.isfinite(s200[i]) and np.isfinite(s200[i - 20]) and np.isfinite(s20[i])):
        return False
    if not (p["adv"][i] >= H_MIN_ADV):
        return False
    if not (c[i] < s200[i] and s200[i] < s200[i - 20]):
        return False
    return bool(c[i - 9:i + 1].max() >= c[i - 19:i + 1].min() * 1.15 and c[i] < l[i - 1] and c[i] < s20[i])


def h4_tickets(bars: dict[str, dict], gate_closed: dict[str, bool], d_from: str, d_to: str) -> tuple[list[dict], int]:
    """→ (票, 闸门开着而被挡下的信号数)。"""
    out, blocked = [], 0
    for pair, a in bars.items():
        p = prep(a)
        rule = (lambda s20: (lambda a_, j: bool(np.isfinite(s20[j]) and a_["c"][j] > s20[j])))(p["sma20"])
        for i, d in enumerate(a["d"]):
            if d < d_from or d > d_to or not h4_setup(a, p, i):
                continue
            if not gate_closed.get(d, False):
                blocked += 1
                continue
            entry_known = i + 1 < len(a["d"])
            stop = min(float(a["h"][i - 9:i + 1].max()), float(a["o"][i + 1]) * (1 + H_STOP_CAP)) if entry_known else None
            t = short_ticket(a, i, 0.0, H_N, exit_rule=rule, stop_px=stop)
            if t:
                out.append({**t, "pair": pair, "symbol": pair[:-4]})
    return chain(out), blocked


def listing_tickets(bars: dict[str, dict], first_d: dict[str, str], d_from: str, d_to: str) -> tuple[list[dict], list[str]]:
    """→ (票, 有问题的合约)。事件 = 合约第一份日档的日期;信号 = 第 7 根(下标 6)。日线开头缺天 ⇒ 不开,写明。"""
    out, problems = [], []
    for pair, a in bars.items():
        f = first_d.get(pair)
        if not f or len(a["d"]) <= L_SIGNAL_IDX or pair == HEDGE_PAIR:
            continue
        if a["d"][0] != f:
            if f >= d_from:
                problems.append(f"{pair}: 第一根 {a['d'][0]} ≠ 上市 {f}")
            continue
        sd = a["d"][L_SIGNAL_IDX]
        if d_from <= sd <= d_to:
            t = short_ticket(a, L_SIGNAL_IDX, L_S, L_N)
            if t:
                out.append({**t, "pair": pair, "symbol": pair[:-4], "listing_d": f})
    return chain(out), problems


def coin_universe(pairs: list[dict], d_from: str, d_to: str) -> tuple[set[str], list[str]]:
    """S-683 修订:臂只用 kind = 'coin' 的合约(股票 / 商品 / 外汇永续与还没分类的都不进)。
    → (可用的合约, 窗口里上市但被排除的合约及原因 —— 报告用)。"""
    coins = {r["pair"] for r in pairs if r.get("kind") == "coin"}
    lo = (date.fromisoformat(d_from) - timedelta(days=L_SIGNAL_IDX)).isoformat()
    excluded = [f"{r['pair']}:{r.get('kind') or '未分类'}" for r in pairs
                if r.get("kind") != "coin" and r.get("first_d") and lo <= str(r["first_d"])[:10] <= d_to]
    return coins, sorted(excluded)


# ── 资金费、对冲腿、R ───────────────────────────────────────────────────────────────────────────────
def daily_funding(rows: list[dict]) -> dict[str, dict[str, float]]:
    """funding_history 行 → symbol → {UTC 日: 当天结算费率之和}(= 研究 daily_funding)。"""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        try:
            out.setdefault(str(r["symbol"]), {})
            d = str(r["funding_time"])[:10]
            out[r["symbol"]][d] = out[r["symbol"]].get(d, 0.0) + float(r["funding_rate"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def funding_between(fund: dict[str, float], days: list[str]) -> tuple[float, int]:
    s, k = 0.0, 0
    for d in days:
        v = fund.get(d)
        if v is not None:
            s += v
            k += 1
    return s, k


def finish(t: dict, a: dict, fund: dict[str, dict[str, float]], btc: Optional[dict], arm: str) -> dict:
    """票 → 写库的行:价格 R、含资金费的 R;臂 L 加对冲腿。"""
    row = {"arm": arm, "ticket_id": f"{arm}:{t['symbol']}:{t['signal_d']}", "pair": t["pair"], "symbol": t["symbol"],
           "signal_d": t["signal_d"], "status": t["status"], "listing_d": t.get("listing_d"), "rule_version": RULE_VERSION}
    if t["status"] == "pending":
        return row
    days = a["d"][t["ei"]:t["xi"]]
    f, fdays = funding_between(fund.get(t["symbol"], {}), days)
    price = t["gross"] - 2 * COST_SIDE
    row.update({k: t[k] for k in ("entry_d", "entry_px", "stop_px", "risk", "exit_d", "exit_px", "why", "gap", "hold_days")})
    row.update({"r_price": price / t["risk"], "funding": f, "funding_days": fdays, "r_net": (price + f) / t["risk"]})
    if arm == ARM_L and btc is not None:
        bi = {d: k for k, d in enumerate(btc["d"])}
        e, x = bi.get(t["entry_d"]), bi.get(t["exit_d"])
        if e is not None and x is not None:
            bx = float(btc["c"][x]) if t["status"] == "open" else float(btc["o"][x])
            hb = bx / float(btc["o"][e]) - 1
            bf, _ = funding_between(fund.get("BTC", {}), btc["d"][e:x])
            hedge = hb - 2 * COST_SIDE - bf                              # 多头付正费率
            row.update({"hedge_ret": hedge, "btc_funding": bf, "r_hedged": (price + f + hedge) / t["risk"]})
    return row


# ── 闸门 ───────────────────────────────────────────────────────────────────────────────────────────
def gate_closed_by_day(style_rows: list[dict]) -> dict[str, bool]:
    """majors cap 指数 ≤ 自身 200 日均值 ⇒ 关(= r_tickets_scan 的 _rt_gate 取反;n < 200 视为开)。"""
    rows = sorted((r for r in style_rows if r.get("ret") is not None and float(r["ret"]) > -0.95), key=lambda r: str(r["d"]))
    lvl, cur, out = [], 1.0, {}
    for k, r in enumerate(rows):
        cur *= 1.0 + float(r["ret"])
        lvl.append(cur)
        w = lvl[max(0, k - 199):k + 1]
        out[str(r["d"])[:10]] = len(w) >= 200 and cur <= sum(w) / len(w)
    return out


# ── 数据到没到 ─────────────────────────────────────────────────────────────────────────────────────
def target_day(bars: dict[str, dict], gate: dict[str, bool], today: date) -> tuple[Optional[str], Optional[str]]:
    """→ (能处理到的最后一天, 停的原因)。最后一天 ≤ 昨天;合约数 ≥ 前一天的 90%;闸门有值。"""
    counts: dict[str, int] = {}
    for a in bars.values():
        for d in a["d"]:
            counts[d] = counts.get(d, 0) + 1
    d = today - timedelta(days=1)
    why = None
    for _ in range(10):
        ds, prev = d.isoformat(), (d - timedelta(days=1)).isoformat()
        n, np_ = counts.get(ds, 0), counts.get(prev, 0)
        if n and np_ and n >= 0.9 * np_ and ds in gate:
            return ds, why
        why = why or (f"{ds}:日线 {n} 个合约 < 前一天 {np_} 的 90%" if not (n and n >= 0.9 * np_)
                      else f"{ds}:majors 闸门没值")
        d -= timedelta(days=1)
    return None, why


# ── 钱曲线(只报)──────────────────────────────────────────────────────────────────────────────────
def money(rows: list[dict], bars: dict[str, dict], btc: Optional[dict], d_from: str, d_to: str, arm: str,
          f: float = MONEY_F, cap: int = MONEY_CAP) -> list[dict]:
    """每日权益。先到先得,最多同时 cap 张;名义 = f × 前一日权益 ÷ 止损距离;出场日按净收益(含资金费)记实,
    持仓中按收盘盯市(扣进场一侧成本)。臂 L 的 BTC 腿同名义。"""
    tk = sorted((r for r in rows if r.get("entry_d") and d_from <= r["entry_d"] <= d_to),
                key=lambda r: (r["entry_d"], r["signal_d"], r["symbol"]))
    marks = {p: dict(zip(a["d"], a["c"])) for p, a in bars.items()}
    bmark = dict(zip(btc["d"], btc["c"])) if btc else {}
    bopen = dict(zip(btc["d"], btc["o"])) if btc else {}

    def closed_by(b: dict, day: str) -> bool:                           # 出场那天按实现记
        return b["status"] == "closed" and b["exit_d"] <= day

    def occupies(b: dict, day: str) -> bool:                            # = t159.nav:出场当天仍占位
        return b["entry_d"] < day and (b["status"] != "closed" or b["exit_d"] >= day)

    out: list[dict] = []
    eq_prev = 1.0
    book: list[dict] = []
    taken = skipped = 0
    d, last = date.fromisoformat(d_from), date.fromisoformat(d_to)
    while d <= last:
        ds = d.isoformat()
        occ = sum(1 for b in book if occupies(b, ds))
        for r in (x for x in tk if x["entry_d"] == ds):
            if occ < cap:
                book.append({**r, "_n": f * eq_prev / r["risk"]})
                occ += 1
                taken += 1
            else:
                skipped += 1
        pnl = 0.0
        open_n = 0
        for b in book:
            hedge = arm == ARM_L and b.get("r_hedged") is not None
            if closed_by(b, ds):
                pnl += b["_n"] * (b["r_hedged"] if hedge else b["r_net"]) * b["risk"]
                continue
            open_n += 1
            m = marks.get(b["pair"], {}).get(ds)
            if m is None:
                continue
            u = (b["entry_px"] - m) / b["entry_px"] - COST_SIDE
            if hedge and ds in bmark and b["entry_d"] in bopen:
                u += bmark[ds] / bopen[b["entry_d"]] - 1 - COST_SIDE
            pnl += b["_n"] * u
        eq = 1.0 + pnl
        out.append({"arm": arm, "d": ds, "nav": round(eq, 8), "ret": round(eq / eq_prev - 1, 10) if out else round(eq - 1, 10),
                    "open_n": open_n, "taken": taken, "skipped": skipped, "f": f, "cap": cap,
                    "inception": INCEPTION, "rule_version": RULE_VERSION})
        eq_prev = eq
        d += timedelta(days=1)
    return out


# ── 写库:平仓票的价格字段不改 ─────────────────────────────────────────────────────────────────────
def merge_tickets(new: list[dict], stored: list[dict]) -> tuple[list[dict], list[str]]:
    """纯函数。→ (要 upsert 的行, drift 的票号)。已平仓的票:价格字段以库里为准(不同 ⇒ drift),只更新资金费字段。"""
    have = {r["ticket_id"]: r for r in stored}
    out, drift = [], []
    for r in new:
        old = have.get(r["ticket_id"])
        if old and old.get("status") == "closed":
            diff = [k for k in FROZEN_FIELDS if not _same(old.get(k), r.get(k), k)]
            if diff:
                drift.append(f"{r['ticket_id']}: {','.join(diff)}")
                continue
        out.append(r)
    return out, drift


def _same(a: Any, b: Any, k: str) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if k.endswith("_d"):
        return str(a)[:10] == str(b)[:10]
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return str(a) == str(b)


def summarize(rows: list[dict], arm: str) -> dict[str, Any]:
    key = "r_hedged" if arm == ARM_L else "r_net"
    closed = [r for r in rows if r.get("status") == "closed" and r.get(key) is not None]
    rs = [float(r[key]) for r in closed]
    return {"n_pending": sum(r.get("status") == "pending" for r in rows), "n_open": sum(r.get("status") == "open" for r in rows),
            "n_closed": len(closed), "mean_r_closed": (sum(rs) / len(rs)) if rs else None, "judge_on": key}


# ── 一轮 ───────────────────────────────────────────────────────────────────────────────────────────
async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.accounting.forward_lock import write_locked
    from src.data.style.header import _read_all
    today = today or datetime.now(timezone.utc).date()
    start = (date.fromisoformat(INCEPTION) - timedelta(days=WARMUP_DAYS)).isoformat()
    if today.isoformat() <= INCEPTION:
        return {"ok": True, "refused": True, "reason": f"inception {INCEPTION} 还没收盘,前向从 {INCEPTION} 收盘后的那一轮开始"}
    yday = (today - timedelta(days=1)).isoformat()
    st_rows = await _read_all(STATE, {"select": "arm,last_d"})
    if len(st_rows) == len(ARMS) and all(str(r["last_d"])[:10] >= yday for r in st_rows):
        return {"ok": True, "refused": False, "reason": f"两条臂都已推进到 {yday},这一轮没有新的一天", "skipped": True}
    raw = await _read_all("perp_bv_daily", {"select": "pair,d,o,h,l,c,qv", "d": f"gte.{start}", "order": "pair.asc,d.asc"})
    bars: dict[str, dict] = {}
    cur: dict[str, list] = {}
    for r in raw:
        cur.setdefault(r["pair"], []).append(r)
    for pair, rs in cur.items():
        bars[pair] = {"d": [str(x["d"])[:10] for x in rs], **{k: np.array([float(x[k]) for x in rs]) for k in ("o", "h", "l", "c", "qv")}}
    del raw, cur
    style = await _read_all("style_index_pit_daily", {"select": "d,ret", "style": "eq.majors", "weighting": "eq.cap",
                                                      "d": "gte.2025-01-01", "order": "d.asc"})
    gate = gate_closed_by_day(style)
    d_to, why = target_day(bars, gate, today)
    if d_to is None or d_to < INCEPTION:
        return {"ok": True, "refused": True, "reason": f"数据没到 inception 之后的完整一天:{why}"}
    bars_to = {p: _cut(a, d_to) for p, a in bars.items()}
    bars_to = {p: a for p, a in bars_to.items() if a["d"]}
    pairs = await _read_all("perp_bv_pairs", {"select": "pair,first_d,kind"})
    first_d = {r["pair"]: str(r["first_d"])[:10] for r in pairs if r.get("first_d")}
    coins, excluded = coin_universe(pairs, INCEPTION, d_to)
    signal_bars = {p: a for p, a in bars_to.items() if p in coins}
    tl, problems = listing_tickets(signal_bars, first_d, INCEPTION, d_to)
    th, blocked = h4_tickets(signal_bars, gate, INCEPTION, d_to)
    syms = sorted({t["symbol"] for t in tl + th} | {"BTC"})
    fund_rows = await _read_all("funding_history", {"select": "symbol,funding_time,funding_rate", "venue": "eq.binance_perp",
                                                    "symbol": f"in.({','.join(syms)})",
                                                    "funding_time": f"gte.{INCEPTION}T00:00:00Z", "order": "symbol.asc,funding_time.asc"})
    fund = daily_funding(fund_rows)
    btc = bars_to.get(HEDGE_PAIR)
    stamp = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {"d_to": d_to, "stopped_because": why, "listing_problems": problems[:5], "h_blocked_gate_open": blocked,
                              "universe_coin": len(coins), "new_listings_not_coin": excluded[:20]}
    for arm, tks in ((ARM_L, tl), (ARM_H, th)):
        rows = [{**finish(t, bars_to[t["pair"]], fund, btc, arm), "updated_at": stamp} for t in tks]
        stored = await _read_all(TICKETS, {"select": "ticket_id,status," + ",".join(FROZEN_FIELDS), "arm": f"eq.{arm}"})
        write, drift = merge_tickets(rows, stored)
        if write:
            r = await supabase_upsert_table(TICKETS, write, on_conflict="arm,ticket_id")
            if not r.ok:
                return {"ok": False, "refused": False, "reason": f"{TICKETS} 写入失败({arm}):{r.why}", **report}
        curve = money(rows, bars_to, btc, INCEPTION, d_to, arm)
        w = await write_locked(MONEY, curve, key="arm", on_conflict="arm,d", today=today)
        if not w.get("ok"):
            return {"ok": False, "refused": False, "reason": f"{MONEY} 写入失败({arm}):{w.get('why')}", **report}
        s = summarize(rows, arm)
        st = {"arm": arm, "last_d": d_to, "inception": INCEPTION, "rule_version": RULE_VERSION, **s,
              "drift": len(drift), "detail": {"drift_sample": drift[:5], "money_lock": w.get("lock")}, "updated_at": stamp}
        r = await supabase_upsert_table(STATE, [st], on_conflict="arm")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{STATE} 写入失败({arm}):{r.why}", **report}
        report[arm] = {**s, "drift": len(drift)}
    return {"ok": True, "refused": False,
            "reason": (f"推进到 {d_to}:L 票 {report[ARM_L]['n_pending'] + report[ARM_L]['n_open'] + report[ARM_L]['n_closed']}"
                       f"(平 {report[ARM_L]['n_closed']})· H 票 {report[ARM_H]['n_pending'] + report[ARM_H]['n_open'] + report[ARM_H]['n_closed']}"
                       f"(平 {report[ARM_H]['n_closed']},闸门开着挡下 {blocked})"),
            **report}


def _cut(a: dict, d_to: str) -> dict:
    k = sum(1 for d in a["d"] if d <= d_to)
    return {"d": a["d"][:k], **{x: a[x][:k] for x in ("o", "h", "l", "c", "qv")}}
