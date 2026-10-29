"""World50 前向账本 —— EW 与 EW×Mom 两条臂,**2026-10-28 收盘开账**(Jazz 10-29「好的」:不等 12-31;原定 S-581「下一个季末起」)。

季内开账:取开账日之前最近一个季末(09-30)按规则算出的权重,用价格漂移到开账日收盘,作为开账持仓(净值 = 1);
之后与回放逐日相同(季内漂移,下一个季末 12-31 照常调仓)。开账之前的日子**一行不写** —— 那段不是事前记录。

规则 = 回放(S-581 / S-583)照代码的那一套,调仓只走 `world50.rebalance`(与回放共用一个核,
tests/test_world50_book.py 逐个权重比对):每年 12 月按当时可知市值重选 50(缓冲 40 / 60),每季末重设权重,季内随价格漂移;
成本 = 换手 × 10 bp(加密 20 bp),开账那一次不收。**两处与回放不同、写在 S-583 里**:收益与动量按美元(本地上市 × 汇率),
动量口径照回放代码(到调仓当月月末)。

写什么:
  world50_book_holdings  每个调仓日 × 臂 × 成分的权重(调仓日收盘后的目标权重)
  world50_book_nav       每个工作日 × 臂的净值(开账 = 1),**写一次不再改**(d ≤ 今天 − 2 且所有成分在那天前都有价才写)
净值 = 上一个调仓日净值 × Σ 权重 × 价格(d) / 价格(调仓日),价格每次从当前的复权序列现读(分红随复权进来)。
OPEN_DATE 之前:不写任何一行,只把「如果今天是上一个季末,成分与权重会是什么」放进循环的 detail(核在真数据上跑得通的证据)。
"""
from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

OPEN_DATE = "2026-10-28"     # Jazz 10-29:不等季末;开账 = 这天收盘
FORWARD_START = OPEN_DATE   # 兼容旧名
ARMS = ("EW", "EWxMom")
RULE = "world50_book_v1:S-581 规则照回放代码(12 月重选 40/60、季末重设、季内漂移、动量到调仓当月月末);美元"
COST_BP = {"equity": 10, "metal": 10, "crypto": 20}
FREEZE_DAYS = 2
MOM_MONTHS = 40
WRITES_TABLES = ("world50_book_holdings", "world50_book_nav")
WRITES_COLUMNS = {
    "world50_book_holdings": ("as_of", "arm", "key", "weight", "rank", "mcap_usd", "neutral", "rule"),
    "world50_book_nav": ("d", "arm", "nav", "ret", "n_priced", "as_of", "rule"),
}


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def quarter_ends(first: str, last: str) -> list[str]:
    """first ≤ 季末 ≤ last 的日历季末日期。"""
    out, y = [], int(first[:4])
    while True:
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = date(y, m, d).isoformat()
            if q > last:
                return out
            if q >= first:
                out.append(q)
        y += 1


def last_quarter_end_before(d: str) -> str:
    y = int(d[:4])
    cands = [date(y - 1, 12, 31).isoformat()] + quarter_ends(f"{y}-01-01", d)
    return max(q for q in cands if q <= d)


def weekdays(after: str, upto: str) -> list[str]:
    a, b = date.fromisoformat(after) + timedelta(days=1), date.fromisoformat(upto)
    out = []
    while a <= b:
        if a.weekday() < 5:
            out.append(a.isoformat())
        a += timedelta(days=1)
    return out


def px_on_or_before(series: list[tuple[str, float]], d: str) -> Optional[float]:
    i = bisect.bisect_right([x for x, _ in series], d) - 1
    return series[i][1] if i >= 0 else None


def momentum_closes(series: list[tuple[str, float]], as_of: str, months: int = MOM_MONTHS) -> list[Optional[float]]:
    """日线(美元)→ 回放同口径的月末价格指数:月收益 = 本月最后收盘 / 上月最后收盘 − 1(任一缺 ⇒ None),
    再 `closes_from_returns`。截到 as_of 所在的月。"""
    from src.data.universe.world50 import closes_from_returns
    y, m = int(as_of[:4]), int(as_of[5:7])
    keys = []
    for _ in range(months + 1):
        keys.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    keys.reverse()
    last: dict[str, float] = {}
    for d, c in series:
        if d <= as_of and c and c > 0:
            last[d[:7]] = c
    rets = [(last[b] / last[a] - 1) if a in last and b in last else None for a, b in zip(keys, keys[1:])]
    return closes_from_returns(rets)


def drift(weights: dict[str, float], px: dict[str, list[tuple[str, float]]], as_of: str, d: str
          ) -> tuple[Optional[float], dict[str, float], int]:
    """从 as_of 的权重漂到 d:返回 (增长倍数, 漂移后的权重, 有价的成分数)。as_of 没有价的成分按回放做法在其余成分间重归一。"""
    grown: dict[str, float] = {}
    for k, w in weights.items():
        p0, p1 = px_on_or_before(px.get(k, []), as_of), px_on_or_before(px.get(k, []), d)
        if p0 and p1:
            grown[k] = w * p1 / p0
    base = sum(weights[k] for k in grown)
    if base <= 0:
        return None, {}, 0
    g = sum(grown.values())
    return g / base, {k: v / g for k, v in grown.items()}, len(grown)


def turnover_cost(old: dict[str, float], new: dict[str, float], cls: dict[str, str]) -> float:
    keys = set(old) | set(new)
    return sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) * COST_BP.get(cls.get(k, "equity"), 10) / 1e4 for k in keys)


# ── 读库 ────────────────────────────────────────────────────────────────────

async def _get_all(tail: str, page: int = 1000) -> list[dict]:
    from src.data.signals.hl_book_daily import _supabase_get
    out: list[dict] = []
    while True:
        rows = await _supabase_get(f"{tail}&limit={page}&offset={len(out)}")
        out += rows or []
        if len(rows or []) < page:
            return out


def _shift(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


async def snapshot(as_of: str) -> dict[str, float]:
    """as_of 当时可知的美元市值:公司 = world50_mcap_weekly 14 天内最后一个周点;加密 = asset_mcap_daily 7 天内;
    黄金 = 金价 × 可投资存量。白银 / 铂金没有存量数据,不参与(与回放同)。"""
    from src.data.universe.world50 import CANDIDATES
    from src.data.universe.world50_data import MCAP_SOURCE, metal_mcap_usd
    out: dict[str, float] = {}
    for r in await _get_all(f"world50_mcap_weekly?select=key,d,mcap_usd&source=eq.{MCAP_SOURCE}"
                            f"&d=gte.{_shift(as_of, -14)}&d=lte.{as_of}&order=d"):
        if r.get("mcap_usd"):
            out[r["key"]] = float(r["mcap_usd"])
    crypto = [c.key for c in CANDIDATES if c.cls == "crypto"]
    for r in await _get_all(f"asset_mcap_daily?select=symbol,d,mcap&symbol=in.({','.join(crypto)})"
                            f"&d=gte.{_shift(as_of, -7)}&d=lte.{as_of}&order=d"):
        if r.get("mcap"):
            out[r["symbol"]] = float(r["mcap"])
    gold = await _get_all(f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.XAUUSD"
                          f"&trade_date=gte.{_shift(as_of, -7)}&trade_date=lte.{as_of}&order=trade_date")
    if gold and gold[-1].get("close"):
        v = metal_mcap_usd("XAUUSD", float(gold[-1]["close"]))
        if v:
            out["XAUUSD"] = v
    return out


async def usd_prices(keys: list[str], start: str, end: str) -> dict[str, list[tuple[str, float]]]:
    """日线美元价:股票 / 黄金 = ohlcv_daily eodhd(复权收盘;本地上市 × 当天或之前 7 天内的汇率),加密 = asset_mcap_daily 的价格。"""
    from src.data.market import data_layer as dl
    from src.data.universe.world50 import CANDIDATES
    from src.data.universe.world50_data import EXCHANGE_SHARES, _usd_per_local, fx_series
    cls = {c.key: c.cls for c in CANDIDATES}
    fx: dict[str, Any] = {}
    out: dict[str, list[tuple[str, float]]] = {}
    for k in keys:
        if cls.get(k) == "crypto":
            rows = await _get_all(f"asset_mcap_daily?select=d,price&symbol=eq.{k}&d=gte.{start}&d=lte.{end}&order=d")
            out[k] = [(r["d"], float(r["price"])) for r in rows if r.get("price")]
            continue
        rows = await _get_all(f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{k}"
                              f"&trade_date=gte.{start}&trade_date=lte.{end}&order=trade_date")
        s = [(r["trade_date"], float(r["close"])) for r in rows if r.get("close")]
        if k in EXCHANGE_SHARES:
            ccy = EXCHANGE_SHARES[k]["ccy"]
            if ccy not in fx:
                fx[ccy] = fx_series(await dl.get_eodhd_eod_range(f"USD{ccy}", "FOREX", _shift(start, -10)))
            conv = [(d, _usd_per_local(fx[ccy], d)) for d, _ in s]
            s = [(d, c * u) for (d, c), (_, u) in zip(s, conv) if u]
        out[k] = s
    return out


async def compute(as_of: str, previous: list[str]) -> dict[str, Any]:
    """as_of 的一次调仓(不写库)。"""
    from src.data.universe.world50 import rebalance, rank_by_mcap
    snap = await snapshot(as_of)
    if not snap:
        return {"ok": False, "why": f"{as_of} 没有可用市值"}
    ranked = rank_by_mcap(snap)
    pre = rebalance(snap, previous, {}, reconstitute=as_of[5:7] == "12")    # 先定成分,只取这些的价格
    px = await usd_prices(pre["members"], _shift(as_of, -31 * (MOM_MONTHS + 1)), as_of)
    closes = {k: momentum_closes(px.get(k, []), as_of) for k in pre["members"]}
    res = rebalance(snap, previous, closes, reconstitute=as_of[5:7] == "12")
    rank = {k: i + 1 for i, k in enumerate(ranked)}
    return {"ok": True, "as_of": as_of, "members": res["members"], "EW": res["EW"], "EWxMom": res["EWxMom"],
            "neutral": res["neutral"], "rank": rank, "mcap": snap, "ranked": len(ranked)}


def _preview(c: dict[str, Any]) -> dict[str, Any]:
    if not c.get("ok"):
        return {"ok": False, "why": c.get("why")}
    top = sorted(c["EWxMom"].items(), key=lambda kv: -kv[1])[:5]
    return {"as_of": c["as_of"], "ranked": c["ranked"], "members": len(c["members"]), "neutral": len(c["neutral"]),
            "max_w_EWxMom": round(max(c["EWxMom"].values()), 4), "top_EWxMom": [[k, round(w, 4)] for k, w in top]}


# ── 一轮 ────────────────────────────────────────────────────────────────────

async def run_book(today: Optional[str] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.universe.world50 import CANDIDATES
    today = today or datetime.now(timezone.utc).date().isoformat()
    cutoff = _shift(today, -FREEZE_DAYS)
    if cutoff < OPEN_DATE:
        prev_q = last_quarter_end_before(cutoff)
        return {"ok": True, "waiting": f"前向账本 {OPEN_DATE} 收盘开账", "preview": _preview(await compute(prev_q, []))}
    qs = [OPEN_DATE] + quarter_ends(_shift(OPEN_DATE, 1), cutoff)
    cls = {c.key: c.cls for c in CANDIDATES}
    held = await _get_all("world50_book_holdings?select=as_of,arm,key,weight&order=as_of")
    navs = await _get_all("world50_book_nav?select=d,arm,nav,as_of&order=d")
    book: dict[str, dict[str, dict[str, float]]] = {a: {} for a in ARMS}       # 臂 → 调仓日 → 权重
    for r in held:
        book.setdefault(r["arm"], {}).setdefault(r["as_of"], {})[r["key"]] = float(r["weight"])
    last_nav: dict[str, tuple[str, float]] = {}
    for r in navs:
        last_nav[r["arm"]] = (r["d"], float(r["nav"]))
    wrote_h, wrote_n, notes, notes_info = 0, 0, [], []
    for q in qs:
        if all(q in book[a] for a in ARMS):
            continue
        prev_dates = sorted(d for d in book["EW"] if d < q)
        previous = list(book["EW"][prev_dates[-1]]) if prev_dates else []
        mid_open = q == OPEN_DATE and q not in quarter_ends(q, q)
        c = await compute(last_quarter_end_before(q) if mid_open else q, previous)
        if not c.get("ok"):
            notes.append(f"{q}: {c.get('why')}")
            break
        if mid_open:                                         # 季内开账:季末权重漂移到开账日收盘
            for a in ARMS:
                px0 = await usd_prices(sorted(c[a]), _shift(c["as_of"], -10), q)
                g0, drifted0, _ = drift(c[a], px0, c["as_of"], q)
                if g0 is None:
                    return {"ok": False, "why": f"{a} {q}: 季末权重漂不到开账日(没有价)"}
                c[a] = drifted0
        rows_h, rows_n = [], []
        for a in ARMS:
            new = c[a]
            if prev_dates:                                   # 先把上一段净值标到 q,再按 q 的漂移权重算换手成本
                p = prev_dates[-1]
                px = await usd_prices(sorted(book[a][p]), _shift(p, -10), q)
                g, drifted, _ = drift(book[a][p], px, p, q)
                if g is None:
                    notes.append(f"{a} {q}: 上一段没有价,停")
                    return {"ok": False, "why": "; ".join(notes)}
                nav_q = _nav_at(navs, a, p) * g * (1 - turnover_cost(drifted, new, cls))
            else:
                nav_q = 1.0                                  # 开账:不收成本(与回放同)
            rule_q = RULE + (f" · 季内开账:{c['as_of']} 季末权重漂移到 {q} 收盘" if mid_open else "")
            rows_h += [{"as_of": q, "arm": a, "key": k, "weight": w, "rank": c["rank"].get(k), "mcap_usd": c["mcap"].get(k),
                        "neutral": k in c["neutral"], "rule": rule_q} for k, w in new.items()]
            rows_n.append({"d": q, "arm": a, "nav": nav_q, "ret": None, "n_priced": len(new), "as_of": q, "rule": rule_q})
            book[a][q] = new
            navs.append({"d": q, "arm": a, "nav": nav_q, "as_of": q})
            last_nav[a] = (q, nav_q)
        w1 = await supabase_upsert_table("world50_book_holdings", rows_h, on_conflict="as_of,arm,key")
        w2 = await supabase_upsert_table("world50_book_nav", rows_n, on_conflict="d,arm")
        if not (w1.ok and w2.ok):
            return {"ok": False, "why": f"写 {q} 失败:{(w1.why or w2.why or '')[:160]}"}
        wrote_h, wrote_n = wrote_h + len(rows_h), wrote_n + len(rows_n)
    # 最近一个调仓日之后的工作日:每个成分在那天前都有价才写,写过的不再改
    for a in ARMS:
        if not book[a]:
            continue
        p = max(book[a])
        done = {r["d"] for r in navs if r["arm"] == a}
        days = [d for d in weekdays(p, cutoff) if d not in done]
        if not days:
            continue
        px = await usd_prices(sorted(book[a][p]), _shift(p, -10), cutoff)
        ends = {k: s[-1][0] for k, s in px.items() if s}
        newest = max(ends.values(), default=p)
        stale = sorted(k for k, e in ends.items() if e < _shift(newest, -7))     # 停牌 / 退市:沿用最后价,不让它卡住全账本
        if stale:
            notes_info.append(f"{a}: {', '.join(stale)} 一周以上没有新价,沿用最后价")
        last_common = min((e for k, e in ends.items() if k not in stale), default=p)
        rows, nav_p = [], _nav_at(navs, a, p)
        prev_nav = last_nav.get(a, (p, nav_p))[1]
        for d in days:
            if d > last_common:
                break
            g, _, n = drift(book[a][p], px, p, d)
            if g is None:
                break
            nav = nav_p * g
            rows.append({"d": d, "arm": a, "nav": nav, "ret": nav / prev_nav - 1, "n_priced": n, "as_of": p, "rule": RULE})
            prev_nav = nav
        if rows:
            w = await supabase_upsert_table("world50_book_nav", rows, on_conflict="d,arm")
            if not w.ok:
                return {"ok": False, "why": f"写 {a} 净值失败:{(w.why or '')[:160]}"}
            wrote_n += len(rows)
            last_nav[a] = (rows[-1]["d"], rows[-1]["nav"])
    return {"ok": not notes, "holdings_written": wrote_h, "nav_written": wrote_n,
            "last": {a: last_nav.get(a) for a in ARMS}, **({"notes": notes + notes_info} if notes or notes_info else {})}


def _nav_at(navs: list[dict], arm: str, d: str) -> float:
    for r in reversed(navs):
        if r["arm"] == arm and r["d"] == d:
            return float(r["nav"])
    raise ValueError(f"{arm} 在 {d} 没有净值")
