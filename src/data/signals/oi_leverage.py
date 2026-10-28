"""开票日的规模中性 OI/市值分位 —— S-690 的前向记录(R-v2「去掉高杠杆三分之一」纸面臂)。

## 为什么

S-690(10-27,✅):R-v2 的历史票里,开票当天 OI/市值(控制规模)排在前三分之一的 302 张平均 +0.02R,
其余 354 张 +0.81R;每一年都是这样,大鱼也没有偏在高杠杆那边。按预注册,先上纸面前向,真钱规则 Jazz 定。

## 一个内核

每个信号日:截面 = Binance U 本位当日 OI(`deriv_metrics_daily.oi_value_close`)> 0、CG 市值 ≥ 2,000 万美元、
且过了映射校验的全部名字;r = OI 值 / 市值;当天 rank(r) 对 rank(ln 市值) 做最小二乘,取残差,
p = 残差的 percent_rank(与研究 SQL 的 `percent_rank()` 同一定义)。H = p ≥ 2/3。
研究版是 `docs/research/s690_rv2_oi_filter.sql`;两者在 2024-11-11 的截面上逐名一致(见 tests)。

映射校验:研究版用 2023-01 起的全部重叠日;前向版用信号日前 `CHECK_DAYS` 天(同一把尺子:中位相对误差 ≤ 5%、≥ 30 天)。

## 表

`r_ticket_oi_tags`:每张 R-v2 纸面票一行 —— p、截面名字数、H、缺失原因。OI 归档要隔天才有,当天打不上的票
记 why_missing,下一轮再试(`RETRY_DAYS` 内)。判活同 `ticket_tags`:
`select count(*) from r_tickets_paper p left join r_ticket_oi_tags t using (ticket_id) where t.ticket_id is null`。

## 真钱(Jazz 10-27「直接应用」)—— 用 d 收盘那一刻的截面,不用归档

d 的归档在 d+1 约 07:30 UTC 才落库,执行器 00:45 取计划。**滞后一天的截面检验不过**(台账 S-690 附记一:
差 −0.79R → −0.34R、p 0.004 → 0.063;d 当天才变 H 的 104 张票就是被挡的那批 —— 是开票当天涌进来的杠杆)。
所以 d+1 00:05 UTC 从 CoinGecko Pro 拍一张快照(`snapshot_once`:binance_futures 合约 `open_interest_usd` 一次 +
`/coins/markets` 市值一次;**不碰 Binance API**),宇宙 = 最新一天归档里的名字(与研究同一批),内核同 `size_neutral_pct`。
`oi_lev_snapshot_daily` 存整张截面;归档落库后 `audit_snapshots` 逐名回填 `p_archive`。

计划(`ticket_plan.load_ticket_plan` → `filter_enter`):p ≥ 2/3 的票**不进、不腾位置**;名字不在快照截面 ⇒ 照常进;
窗口内(d+1 02:00 UTC 前)还没有快照 ⇒ 这一轮不开新票、下一轮再看;过了窗口仍没有 ⇒ 不过滤照常进(标 unavailable)。
**快照对不上归档就自动停用**:最近 `AUDIT_DAYS` 天已核的名字对 ≥ `AUDIT_MIN_PAIRS` 时,H 一致率 < `AUDIT_MIN_AGREE`
或秩相关 < `AUDIT_MIN_RHO` ⇒ 过滤关掉(计划里写 disabled_by_audit)。判据写在台账 S-690 附记二,先于第一次核对。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable, Optional

TABLE = "r_ticket_oi_tags"
SNAP_TABLE = "oi_lev_snapshot_daily"
WRITES_TABLES = (TABLE, SNAP_TABLE)
RULE = "S-690"
H_CUT = 2 / 3
MIN_MCAP = 20_000_000
CHECK_DAYS = 120
RETRY_DAYS = 5
SNAP_WINDOW_H = 2                 # live 快照只在 d+1 的 [00:00, 02:00) UTC 拍;之后拍的就不是「d 收盘」了
MAX_PX_ERR = 0.05                 # 映射校验:CG 现货价 × 面值倍数 vs 合约最新价
AUDIT_DAYS = 14
AUDIT_MIN_PAIRS = 300
AUDIT_MIN_AGREE = 0.90
AUDIT_MIN_RHO = 0.90


def avg_ranks(values: list[float]) -> list[float]:
    """纯函数。平均名次(1 起),并列取平均 —— 与 SQL 的 rank() + (count − 1)/2 相同。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def size_neutral_pct(rows: Iterable[dict]) -> dict[str, float]:
    """纯函数。[{sym, oi, mcap}] → {sym: p}。p = rank(r) 对 rank(ln 市值) 的 OLS 残差的 percent_rank。"""
    xs = [r for r in rows if r.get("oi") and r.get("mcap") and float(r["oi"]) > 0 and float(r["mcap"]) >= MIN_MCAP]
    return size_neutral_pct_of([{"sym": r["sym"], "v": float(r["oi"]) / float(r["mcap"]), "mcap": r["mcap"]} for r in xs])


def size_neutral_pct_of(rows: Iterable[dict]) -> dict[str, float]:
    """纯函数。[{sym, v, mcap}] → {sym: p}:任意因子 v 的规模中性分位(同一内核;v 为空或市值不够的名字不进)。"""
    xs = [r for r in rows if r.get("v") is not None and r.get("mcap") and float(r["mcap"]) >= MIN_MCAP]
    n = len(xs)
    if n < 3:
        return {}
    rr = avg_ranks([float(r["v"]) for r in xs])
    rs = avg_ranks([math.log(float(r["mcap"])) for r in xs])
    ms, mr = sum(rs) / n, sum(rr) / n
    sxx = sum((s - ms) ** 2 for s in rs)
    b = sum((s - ms) * (r - mr) for s, r in zip(rs, rr)) / sxx if sxx else 0.0
    a = mr - b * ms
    e = [r - (a + b * s) for r, s in zip(rr, rs)]
    # percent_rank = (rank − 1) / (n − 1),rank 为最小名次(并列同名次)
    order = sorted(range(n), key=lambda i: e[i])
    rank_min = [0] * n
    for pos, i in enumerate(order):
        rank_min[i] = pos + 1 if pos == 0 or e[order[pos - 1]] != e[i] else rank_min[order[pos - 1]]
    return {xs[i]["sym"]: (rank_min[i] - 1) / (n - 1) for i in range(n)}


def mapping_ok(points: dict[str, float], implied: dict[str, float], mult: int = 1) -> bool:
    """纯函数。{d: CG 价} 对 {d: 隐含价} —— 重叠 ≥ 30 天、中位相对误差 ≤ 5%(同 perp_mcap_backfill)。"""
    from src.data.market.perp_mcap_backfill import accept, price_check
    return accept(*price_check([{"d": d, "price": p} for d, p in points.items()], implied, mult))


def tag_row(ticket: dict, pmap: dict[str, float], n_cs: int, why: Optional[str] = None,
            live: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """纯函数。一张票 → 一行标签。`live` = 同一天快照截面的 {symbol: p}(真钱按它挡票)。"""
    sym = str(ticket["symbol"]).upper()
    p = pmap.get(sym)
    pl = (live or {}).get(sym)
    return {"ticket_id": ticket["ticket_id"], "symbol": ticket["symbol"], "signal_d": str(ticket["signal_d"])[:10],
            "p": round(p, 5) if p is not None else None, "n_cs": n_cs or None,
            "high": (p >= H_CUT) if p is not None else None,
            "why_missing": None if p is not None else (why or "名字不在当天截面(无 OI / 市值 < 2,000 万 / 映射校验不过)"),
            "p_live": round(pl, 5) if pl is not None else None, "high_live": (pl >= H_CUT) if pl is not None else None,
            "rule": RULE}


def extra_tags(ticket: dict, full: dict[str, Any]) -> dict[str, Any]:
    """纯函数。S-696 前向记录:同一截面上的 F3(ΔOI 30 天)与 F7(主动买卖比 7 天)分位。只记,不挡票。"""
    sym = str(ticket["symbol"]).upper()
    p3, p7 = full.get("p3", {}).get(sym), full.get("p7", {}).get(sym)
    return {"p_doi30": round(p3, 5) if p3 is not None else None, "high_doi30": (p3 >= H_CUT) if p3 is not None else None,
            "p_taker7": round(p7, 5) if p7 is not None else None}


# ── 真钱:d 收盘那一刻的快照 ─────────────────────────────────────────────────

def parse_mult(base: str) -> int:
    """纯函数。Binance 合约名的面值倍数:1000000MOG / 1MBABYDOGE → 10⁶,1000PEPE → 1000,1INCH → 1。"""
    b = str(base).upper()
    for pre, m in (("1000000", 1_000_000), ("1000", 1000), ("1M", 1_000_000)):
        if b.startswith(pre) and len(b) > len(pre) and b[len(pre)].isalpha():
            return m
    return 1


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def pick_tickers(tickers: Iterable[dict], universe: Iterable[str]) -> dict[str, dict]:
    """纯函数。CG `binance_futures` 行情 → {基础名: {coin_id, oi_usd, last_usd}},只要宇宙里的 USDT 永续。"""
    uni = {str(s).upper() for s in universe}
    out: dict[str, dict] = {}
    for t in tickers:
        sym = str(t.get("symbol") or "").upper()
        if not sym.endswith("USDT") or (t.get("contract_type") or "perpetual") != "perpetual":
            continue
        base = sym[:-4]
        if base not in uni:
            continue
        conv = t.get("converted_last") or {}
        last = _f(conv.get("usd") if isinstance(conv, dict) else None) or _f(t.get("last"))
        oi = _f(t.get("open_interest_usd"))
        if base in out and (out[base]["oi_usd"] or 0) >= (oi or 0):
            continue
        out[base] = {"coin_id": t.get("coin_id"), "oi_usd": oi, "last_usd": last}
    return out


def snapshot_rows(d: dt.date, universe: Iterable[str], tk: dict[str, dict], markets: Iterable[dict],
                  snap_at: str, kind: str = "live") -> list[dict]:
    """纯函数。宇宙 + 合约行情 + CG 市值 → 整张截面的行(含被排除的名字与原因)。内核同 `size_neutral_pct`。"""
    mk = {m.get("id"): m for m in markets if m.get("id")}
    rows, cand = [], []
    for s in sorted({str(x).upper() for x in universe}):
        t, why, m = tk.get(s), None, None
        mult = parse_mult(s)
        if not t or not t.get("coin_id"):
            why = "合约不在 CoinGecko 的 binance_futures 行情里(或没有 coin_id)"
        elif not t.get("oi_usd") or t["oi_usd"] <= 0:
            why = "没有 OI"
        else:
            m = mk.get(t["coin_id"])
            px, last = _f((m or {}).get("current_price")), t.get("last_usd")
            if not m or not px or not last:
                why = "CG 没有这个币的现价 / 市值"
            elif abs(px * mult / last - 1) > MAX_PX_ERR:
                why = f"映射校验不过(CG 价 × {mult} 与合约价差 {abs(px * mult / last - 1):.1%})"
            elif (_f(m.get("market_cap")) or 0) < MIN_MCAP:
                why = "市值 < 2,000 万"
        r = {"d": d.isoformat(), "symbol": s, "kind": kind, "coin_id": (t or {}).get("coin_id"),
             "oi_usd": (t or {}).get("oi_usd"), "mcap": _f((m or {}).get("market_cap")),
             "last_usd": (t or {}).get("last_usd"), "cg_px": _f((m or {}).get("current_price")), "mult": mult,
             "in_cs": why is None, "why_out": why, "p": None, "n_cs": None, "snap_at": snap_at,
             "p_archive": None, "n_archive": None, "audited_at": None}
        rows.append(r)
        if why is None:
            cand.append({"sym": s, "oi": r["oi_usd"], "mcap": r["mcap"]})
    pmap = size_neutral_pct(cand)
    for r in rows:
        if r["symbol"] in pmap:
            r["p"], r["n_cs"] = round(pmap[r["symbol"]], 5), len(pmap)
        elif r["in_cs"]:
            r["in_cs"], r["why_out"] = False, "截面不足 3 名"
    return rows


def in_window(d: dt.date, at: dt.datetime) -> bool:
    """纯函数。`at` 是否在 d+1 的 [00:00, SNAP_WINDOW_H) UTC 里 —— 只有这时拍的才算「d 收盘」。"""
    start = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc)
    return start <= at < start + dt.timedelta(hours=SNAP_WINDOW_H)


def _ts(x: Any) -> Optional[dt.datetime]:
    if not x:
        return None
    if isinstance(x, dt.datetime):
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)
    s = str(x).replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def agreement(rows: Iterable[dict]) -> dict[str, Any]:
    """纯函数。已核的快照行 → 名字对数、H 一致率、p 的秩相关(Spearman)。"""
    pr = [(float(r["p"]), float(r["p_archive"])) for r in rows
          if r.get("p") is not None and r.get("p_archive") is not None]
    n = len(pr)
    if n < 3:
        return {"n_pairs": n, "h_agree": None, "rho": None}
    agree = sum((a >= H_CUT) == (b >= H_CUT) for a, b in pr) / n
    ra, rb = avg_ranks([a for a, _ in pr]), avg_ranks([b for _, b in pr])
    ma, mb = sum(ra) / n, sum(rb) / n
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    rho = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / den if den else None
    return {"n_pairs": n, "h_agree": round(agree, 4), "rho": round(rho, 4) if rho is not None else None}


def audit_verdict(stats: dict[str, Any]) -> tuple[bool, str]:
    """纯函数。→ (过滤是否可用, 理由)。名字对不够时照用(Jazz 10-27 直接应用),够了就按判据。"""
    n = stats.get("n_pairs") or 0
    if n < AUDIT_MIN_PAIRS:
        return True, f"已核 {n} 对 < {AUDIT_MIN_PAIRS},先用"
    ok = (stats.get("h_agree") or 0) >= AUDIT_MIN_AGREE and (stats.get("rho") or 0) >= AUDIT_MIN_RHO
    return ok, (f"已核 {n} 对:H 一致 {stats.get('h_agree')}、秩相关 {stats.get('rho')}"
                + ("" if ok else f" —— 低于 {AUDIT_MIN_AGREE} / {AUDIT_MIN_RHO},停用"))


def filter_enter(enter: list[dict], asof: str, snap: list[dict], audit: dict[str, Any],
                 now: dt.datetime) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """纯函数。计划里要进的票 → (照进, 被挡, 说明)。规则见模块头;被挡的票不腾位置。"""
    d = dt.date.fromisoformat(asof[:10])
    usable, why_audit = audit_verdict(audit)
    info: dict[str, Any] = {"rule": RULE, "h_cut": round(H_CUT, 4), "audit": {**audit, "verdict": why_audit}}
    if not enter:
        return [], [], {**info, "status": "nothing_to_enter"}
    if not usable:
        return enter, [], {**info, "status": "disabled_by_audit"}
    live = [r for r in snap if r.get("kind") == "live" and str(r.get("d"))[:10] == d.isoformat()
            and (t := _ts(r.get("snap_at"))) is not None and in_window(d, t)]
    if not live:
        end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc) + dt.timedelta(hours=SNAP_WINDOW_H)
        if now < end:
            held = [{**e, "why": "d 收盘的 OI 快照还没有 —— 这一轮不开新票,下一轮再看"} for e in enter]
            return [], held, {**info, "status": "waiting_snapshot"}
        return enter, [], {**info, "status": "unavailable", "why": f"{d} 收盘的 OI 快照在窗口内没拍到 —— 不过滤,照常进"}
    pm = {r["symbol"]: r for r in live}
    kept, skipped = [], []
    for e in enter:
        r = pm.get(str(e["symbol"]).upper())
        p = r.get("p") if r else None
        if p is not None and float(p) >= H_CUT:
            skipped.append({**e, "oi_p": float(p), "why": f"S-690:开票日 OI/市值(规模中性)分位 {float(p):.2f} ≥ 2/3"})
        else:
            kept.append({**e, "oi_p": float(p) if p is not None else None,
                         "oi_note": None if p is not None else ((r or {}).get("why_out") or "不在快照截面")})
    return kept, skipped, {**info, "status": "applied", "n_cs": next((r.get("n_cs") for r in live if r.get("n_cs")), None),
                           "snap_at": str(live[0].get("snap_at"))}


async def load_filter_inputs(asof: str) -> tuple[list[dict], dict[str, Any]]:
    """读当天的 live 快照与最近 `AUDIT_DAYS` 天的核对行。读不到就抛(调用方 fail closed)。"""
    from src.data.style.header import _read_all
    d = dt.date.fromisoformat(asof[:10])
    snap = await _read_all(SNAP_TABLE, {"select": "d,symbol,kind,p,n_cs,in_cs,why_out,snap_at",
                                        "d": f"eq.{d.isoformat()}", "kind": "eq.live"})
    hist = await _read_all(SNAP_TABLE, {"select": "d,p,p_archive", "kind": "eq.live", "audited_at": "not.is.null",
                                        "d": f"gte.{(d - dt.timedelta(days=AUDIT_DAYS)).isoformat()}"})
    return snap, agreement(hist)


async def snapshot_once(now: Optional[dt.datetime] = None, kind: str = "live") -> dict[str, Any]:
    """拍一张截面。live:只在 d+1 的窗口里拍、每天一次(已有就不重拍);probe:对最新一天归档拍,给部署后的对照。
    请求:CoinGecko Pro 两到三次(合约行情一次、市值按 250 个一页)。读不到就抛。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_derivatives_exchange_tickers, get_cg_markets_strict
    from src.data.style.header import _read_all
    now = now or dt.datetime.now(dt.timezone.utc)
    recent = await _read_all("deriv_metrics_daily", {"select": "symbol,d", "n_points": "gt.0",
                                                     "d": f"gte.{(now.date() - dt.timedelta(days=4)).isoformat()}"})
    if not recent:
        return {"status": "refused", "reason": "最近 4 天没有 Binance 归档 —— 不知道宇宙是谁"}
    last_d = max(str(r["d"])[:10] for r in recent)
    universe = sorted({r["symbol"] for r in recent if str(r["d"])[:10] == last_d})
    if kind == "live":
        d = now.date() - dt.timedelta(days=1)
        if not in_window(d, now):
            return {"status": "refused", "reason": f"不在 {d} 收盘的快照窗口里(d+1 00:00–0{SNAP_WINDOW_H}:00 UTC)"}
        have = await _read_all(SNAP_TABLE, {"select": "symbol", "d": f"eq.{d.isoformat()}", "kind": "eq.live"})
        if have:
            return {"status": "ok", "reason": f"{d} 已拍过", "detail": {"d": d.isoformat(), "skipped": True}}
    else:
        d = dt.date.fromisoformat(last_d)
        have = await _read_all(SNAP_TABLE, {"select": "symbol", "d": f"eq.{d.isoformat()}", "kind": f"eq.{kind}"})
        if have:
            return {"status": "ok", "reason": f"{kind} {d} 已拍过", "detail": {"d": d.isoformat(), "skipped": True}}
    tk = pick_tickers(await get_cg_derivatives_exchange_tickers("binance_futures"), universe)
    markets = await get_cg_markets_strict(sorted({t["coin_id"] for t in tk.values() if t.get("coin_id")}))
    rows = snapshot_rows(d, universe, tk, markets, now.isoformat(), kind)
    w = await supabase_upsert_table(SNAP_TABLE, rows, on_conflict="d,symbol,kind")
    if not w:
        return {"status": "error", "reason": f"{SNAP_TABLE} 写不进去:{getattr(w, 'why', '')}"}
    n_cs = sum(1 for r in rows if r["p"] is not None)
    return {"status": "ok", "reason": f"{kind} {d}:宇宙 {len(universe)}(归档 {last_d}),截面 {n_cs}",
            "detail": {"d": d.isoformat(), "kind": kind, "universe": len(universe), "n_cs": n_cs,
                       "high": sum(1 for r in rows if r["p"] is not None and r["p"] >= H_CUT)}}


async def audit_snapshots(today: Optional[dt.date] = None) -> dict[str, Any]:
    """归档落库后,给还没核的快照日逐名回填 `p_archive`(研究口径的 `cross_section`)。读不到就抛。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or dt.datetime.now(dt.timezone.utc).date()
    todo = await _read_all(SNAP_TABLE, {"select": "*", "audited_at": "is.null",
                                        "d": f"gte.{(today - dt.timedelta(days=AUDIT_DAYS)).isoformat()}"})
    days = sorted({str(r["d"])[:10] for r in todo})
    done = []
    for d in days:
        if not await _read_all("deriv_metrics_daily", {"select": "symbol", "d": f"eq.{d}", "n_points": "gt.0"}):
            continue                                             # 归档还没落库(d+1 约 07:30 UTC)—— 不做大读
        pmap, n = await cross_section(dt.date.fromisoformat(d))
        if not n:
            continue
        at = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [{**r, "p_archive": round(pmap[r["symbol"]], 5) if r["symbol"] in pmap else None, "n_archive": n,
                 "audited_at": at} for r in todo if str(r["d"])[:10] == d]
        w = await supabase_upsert_table(SNAP_TABLE, rows, on_conflict="d,symbol,kind")
        if not w:
            return {"status": "error", "reason": f"{SNAP_TABLE} 核对写不进去:{getattr(w, 'why', '')}"}
        done.append({"d": d, **agreement(rows)})
    return {"status": "ok", "audited": done}


async def cross_section(d: dt.date) -> tuple[dict[str, float], int]:
    """d 当天的 {symbol: p} 与截面名字数。只读本库(Binance Vision 归档 + CoinGecko 日线),不打任何交易所。"""
    full = await cross_section_full(d)
    return full["p"], full["n"]


def factor_values(rs: list[dict], d: dt.date) -> dict[str, Optional[float]]:
    """纯函数。一个名字按日期排好的归档行 → S-691 的 F3、F7(d 收盘已知):
    q3 = ln(oi_close_d / oi_close_{d−30})(张数,不含价格);f7 = d−6 … d 的 taker_ratio_mean 平均(≥ 5 天)。"""
    by_d = {str(r["d"])[:10]: r for r in rs}
    t, b = by_d.get(d.isoformat()), by_d.get((d - dt.timedelta(days=30)).isoformat())
    q3 = None
    if t and b and _f(t.get("oi_close")) and _f(b.get("oi_close")) and float(t["oi_close"]) > 0 and float(b["oi_close"]) > 0:
        q3 = math.log(float(t["oi_close"]) / float(b["oi_close"]))
    tk = [_f(by_d[k].get("taker_ratio_mean")) for k in ((d - dt.timedelta(days=i)).isoformat() for i in range(7)) if k in by_d]
    tk = [x for x in tk if x is not None]
    return {"q3": q3, "f7": sum(tk) / len(tk) if len(tk) >= 5 else None}


async def cross_section_full(d: dt.date) -> dict[str, Any]:
    """d 当天的截面:p(OI/市值,S-690)、p3(ΔOI 30 天,S-691 F3)、p7(主动买卖比 7 天,S-691 F7),都是规模中性分位;
    n = OI/市值截面的名字数。p3 / p7 只作前向记录(S-696),不进任何规则。"""
    from src.data.style.header import _read_all
    lo = (d - dt.timedelta(days=CHECK_DAYS)).isoformat()
    oi = await _read_all("deriv_metrics_daily", {"select": "symbol,d,oi_value_close,oi_close,taker_ratio_mean", "d": f"gte.{lo}",
                                                 "order": "symbol.asc,d.asc"})
    oi = [r for r in oi if str(r["d"])[:10] <= d.isoformat()]
    if not any(str(r["d"])[:10] == d.isoformat() for r in oi):
        return {"p": {}, "p3": {}, "p7": {}, "n": 0}
    syms = sorted({r["symbol"] for r in oi})
    am = await _read_all("asset_mcap_daily", {"select": "symbol,d,price,mcap", "source": "eq.coingecko_pro_market_chart",
                                              "symbol": f"in.({','.join(syms)})", "d": f"gte.{lo}",
                                              "order": "symbol.asc,d.asc"})
    px: dict[str, dict[str, tuple[float, float, int]]] = {}
    for r in am:
        s = str(r.get("symbol") or "").upper()
        if s in syms and str(r["d"])[:10] <= d.isoformat() and r.get("price"):
            px.setdefault(s, {})[str(r["d"])[:10]] = (float(r["price"]), float(r.get("mcap") or 0), 1)
    cgmap = await _read_all("perp_cg_map", {"select": "symbol,coin_id,mult", "verdict": "eq.resolved"})
    extra = {m["symbol"]: m for m in cgmap if m["symbol"] not in px}
    if extra:
        cg = await _read_all("cg_coin_mcap_daily", {"select": "coin_id,d,price,mcap",
                                                    "coin_id": f"in.({','.join(sorted({m['coin_id'] for m in extra.values()}))})",
                                                    "d": f"gte.{lo}", "order": "coin_id.asc,d.asc"})
        by_coin: dict[str, list[dict]] = {}
        for r in cg:
            by_coin.setdefault(r["coin_id"], []).append(r)
        for s, m in extra.items():
            for r in by_coin.get(m["coin_id"], []):
                if str(r["d"])[:10] <= d.isoformat() and r.get("price"):
                    px.setdefault(s, {})[str(r["d"])[:10]] = (float(r["price"]), float(r.get("mcap") or 0), int(m.get("mult") or 1))
    rows = []
    by_sym: dict[str, list[dict]] = {}
    for r in oi:
        by_sym.setdefault(r["symbol"], []).append(r)
    for s, rs in by_sym.items():
        p = px.get(s)
        today = next((r for r in rs if str(r["d"])[:10] == d.isoformat()), None)
        if not p or not today or d.isoformat() not in p:
            continue
        implied = {str(r["d"])[:10]: float(r["oi_value_close"]) / float(r["oi_close"])
                   for r in rs if r.get("oi_close") and r.get("oi_value_close") and float(r["oi_close"]) > 0}
        mult = next(iter(p.values()))[2]
        if not mapping_ok({k: v[0] for k, v in p.items()}, implied, mult):
            continue
        rows.append({"sym": s, "oi": today.get("oi_value_close"), "mcap": p[d.isoformat()][1], **factor_values(rs, d)})
    pmap = size_neutral_pct(rows)
    inside = [r for r in rows if r["sym"] in pmap]                # F3 / F7 在同一个截面里排
    return {"p": pmap, "n": len(pmap),
            "p3": size_neutral_pct_of([{"sym": r["sym"], "v": r["q3"], "mcap": r["mcap"]} for r in inside]),
            "p7": size_neutral_pct_of([{"sym": r["sym"], "v": r["f7"], "mcap": r["mcap"]} for r in inside])}


async def tag_oi_new_tickets(today: Optional[dt.date] = None) -> dict[str, Any]:
    """给还没有 OI 标签(或之前缺数、仍在重试窗口内)的 R-v2 纸面票打标签。读不到就抛。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or dt.datetime.now(dt.timezone.utc).date()
    tickets = await _read_all("r_tickets_paper", {"select": "ticket_id,symbol,signal_d", "order": "ticket_id.asc"})
    have = {r["ticket_id"]: r for r in await _read_all(TABLE, {"select": "ticket_id,p,p_live,signal_d", "order": "ticket_id.asc"})}
    todo = [t for t in tickets if t["ticket_id"] not in have
            or ((have[t["ticket_id"]].get("p") is None or have[t["ticket_id"]].get("p_live") is None)
                and (today - dt.date.fromisoformat(str(t["signal_d"])[:10])).days <= RETRY_DAYS)]
    if not todo:
        return {"status": "ok", "tagged": 0}
    out = []
    for d in sorted({str(t["signal_d"])[:10] for t in todo}):
        full = await cross_section_full(dt.date.fromisoformat(d))
        why = None if full["n"] else "当天的 Binance OI 归档还没落库(隔天才有)"
        live = {r["symbol"]: float(r["p"]) for r in await _read_all(SNAP_TABLE, {
            "select": "symbol,p", "d": f"eq.{d}", "kind": "eq.live", "p": "not.is.null"})}
        out += [{**tag_row(t, full["p"], full["n"], why, live), **extra_tags(t, full)}
                for t in todo if str(t["signal_d"])[:10] == d]
    w = await supabase_upsert_table(TABLE, out, on_conflict="ticket_id")
    if not w:
        return {"status": "error", "reason": f"{TABLE} 写不进去:{getattr(w, 'why', '')}"}
    return {"status": "ok", "tagged": len(out), "high": sum(1 for r in out if r["high"]),
            "missing": sum(1 for r in out if r["p"] is None)}
