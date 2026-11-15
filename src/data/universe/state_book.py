"""T-395 / 台账 S-890:「状态取长处 v2」纸面前向账 —— 每天看前一天收盘的状态,只拿在这个状态下是长处的策略。

Jazz 11-15:「策略不需要全局高效,在特定矢量下 2–3 个月适用跑出超额就可以。主要发挥优势,而不是补短板。」
「这两个都不用等我,我们之前的最优解可以开始实验了。向前开始了。」

**只记账,不下单,不进任何真钱路径**(`tests/test_state_book.py` 用语法树钉住:执行层不 import 本模块)。

做法 = `docs/research/s869_strategy_state.py` 的 `walk`,名单固定(S-890 冻结 2026-11-01 月初那一份,v1 整个窗口不重算):
  - d − 1 收盘的状态 ⇒ d 的收益。T = `state_daily` panel `dist_200` < 0 线下;谁在领 = `style_rel_majors_30d` 当天 > 严格更早
    (2019-01-01 起)全部值的均值且更早的值 ≥ 365 个 ⇒ 主流领;L = `stable_supply_30d` < 0 抽。
  - 该格名单里当天可持有的成员等权平均「缩放后收益」:当天收益 × min(3, (0.10 / √365) / σ),σ = 此前 90 个日历日收益的
    标准差(≥ 60 个观测、σ > 0,否则当天不可持有);一个都没有 ⇒ 0。
  - 口径 = 对现金的超额:占本金的成员扣 `stable_lend_apy_7d` / 100 / 365(按日历日,向前沿用);R-v2 / 闸门空不扣。
四条臂:TxLEAD(主臂)、TxL、T_ONLY、HOLD_ALL(全拿等风险)。各成员的前向来源见 `SOURCES`;拿不到的写在 `UNAVAILABLE`,
当天按不可持有处理(同研究里「不足 60 个观测」),每天在持仓行里写明缺谁。成员的源晚到最多等 `LAG_GRACE_DAYS` 天。

写什么:`forward_book_nav`(book = state_strength_v2;开账日 NAV = 1,之后每天一行,写一次不再改)与
`forward_book_holdings`(as_of = 决定那天 = d − 1;每个持有成员一行 + `_state` 一行写格子与缺谁)。
调度:`multiplier.py` 的 ③ 每小时循环,紧跟 `run_flex_x1v`(那里先把股 / 金的收盘补齐);已写到昨天就只花一次查询。
判活:`select arm, min(d), max(d), count(*) from forward_book_nav where book = 'state_strength_v2' group by arm`。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Optional

import numpy as np

BOOK = "state_strength_v2"
START = "2026-11-15"                 # 这天收盘开账(NAV = 1);第一天收益 = 11-16
READ_ON = "2027-02-15"               # 判读日(S-890)
ROSTER_MONTH = "2026-11-01"
LEAD_FROM, LEAD_MIN_PRIOR = "2019-01-01", 365
VOL_WIN, VOL_MIN_OBS, TARGET_VOL, MAX_SCALE, ANN = 90, 60, 0.10, 3.0, 365
LAG_GRACE_DAYS = 3
HISTORY_DAYS = 200                   # σ 要 90 个日历日;多读一些
RULE = ("state_strength_v2:S-890(名单冻结 2026-11-01、26 条面板、判据 v2;d−1 收盘的状态;等权平均缩放后收益,"
        "缩放 min(3, 10%/σ90);对现金的超额)")
WRITES_TABLES = ("forward_book_nav", "forward_book_holdings")

ARMS = ("TxLEAD", "TxL", "T_ONLY", "HOLD_ALL")

#: S-890:T-405 盲复算 `s869_blind_book_results.json` 2026-11-01 一行(主臂与 S-877 我那份逐格相同)。
ROSTERS: dict[str, dict[str, tuple[str, ...]]] = {
    "TxLEAD": {
        "线上·主流领": ("X1V", "R-v2", "carry_b_top_rc"),
        "线上·二线领": ("carry_b_top_rc", "style_ai", "style_defi", "style_second_l1_l2", "style_top_l1", "tom_pd13_eth"),
        "线下·主流领": ("s823_r6",),
        "线下·二线领": ("S642", "S736_published", "s819_short_s015", "s819_short_s030"),
    },
    "TxL": {
        "线上·抽": ("S681_H3",),
        "线上·注": ("核心", "X1V", "R-v2", "ACWI", "carry_b_top_rc", "style_ai", "style_app", "style_defi",
                  "style_infra_tokenization", "style_second_l1_l2", "style_top_l1", "tom_pd13_btc", "tom_pd13_eth"),
        "线下·抽": ("S642", "s819_short_s015", "s819_short_s030"),
        "线下·注": ("tom_pd13_btc",),
    },
    "T_ONLY": {
        "线上": ("核心", "X1V", "R-v2", "ACWI", "carry_b_top_rc", "style_ai", "style_defi", "style_infra_tokenization",
               "style_second_l1_l2", "style_top_l1", "tom_pd13_btc", "tom_pd13_eth"),
        "线下": ("XAUUSD",),
    },
}
PANEL = ("核心", "X1V", "ACWI", "XAUUSD", "R-v2", "S642", "S736_published", "S736_fixed", "S808", "S810", "S681_H2",
         "S681_H3", "S681_H4", "carry_b_top_rc", "s819_short_s015", "s819_short_s030", "s823_r6", "style_ai", "style_app",
         "style_defi", "style_infra_tokenization", "style_meme", "style_second_l1_l2", "style_top_l1", "tom_pd13_btc",
         "tom_pd13_eth")
ROSTERS["HOLD_ALL"] = {"全部": PANEL}

STYLES = ("ai", "app", "defi", "infra_tokenization", "meme", "second_l1_l2", "top_l1")
#: 成员 → (来源, 是否扣现金)。来源的读法在 `load_inputs`。
SOURCES: dict[str, tuple[str, bool]] = {
    "X1V": ("TOM_ARMS['CORE_X1V'] 作用于 multiplier_daily core_u_replay(= tom_trader/CORE_X1V 的核)", True),
    "核心": ("multiplier_daily core_u_replay 净值", True),
    "R-v2": ("r_money_daily 净值(10-19 起;满 60 个观测前不可持有)", False),
    "ACWI": ("ohlcv_daily eodhd ACWI 收盘(周末收益 0)", True),
    "XAUUSD": ("ohlcv_daily eodhd XAUUSD 收盘(周末收益 0)", True),
    "tom_pd13_btc": ("tom.tom_gross + trade_returns 作用于 asset_mcap_daily BTC(生产核)", True),
    "tom_pd13_eth": ("tom.tom_gross + trade_returns 作用于 asset_mcap_daily ETH(生产核)", True),
    **{f"style_{s}": (f"style_index_pit_daily {s} / cap 的 ret", True) for s in STYLES},
}
#: 该拿、拿不到(S-890)。T-406 合入后 R6 / 闸门空改成它的纯函数整段重算,从合入那天起可持有。
UNAVAILABLE: dict[str, str] = {
    "s823_r6": "等 T-406(三态敞口 R6 的生产内核)",
    "s819_short_s015": "等 T-406(闸门关时空大盘 s = 0.15 的生产内核)",
    "s819_short_s030": "等 T-406(闸门关时空大盘 s = 0.30 的生产内核)",
    **{k: "只有研究回测" for k in ("S642", "S736_published", "S736_fixed", "S808", "S810", "S681_H2", "S681_H3", "S681_H4")},
}
EXCLUDED: dict[str, str] = {"carry_b_top_rc": "套息不进(S-835 没过准入)"}
assert set(SOURCES) | set(UNAVAILABLE) | set(EXCLUDED) == set(PANEL), "每个面板成员都要有来源、或写明为什么拿不到"


def D(s: Any) -> dt.date:
    return s if isinstance(s, dt.date) and not isinstance(s, dt.datetime) else dt.date.fromisoformat(str(s)[:10])


# ── 纯函数 ──────────────────────────────────────────────────────────────────────

def daily_from_nav(nav: dict) -> dict:
    """净值 → 逐日收益;首末日之间缺的日子按净值不变(收益 0)。与研究脚本 `_daily_from_nav` 同一写法。"""
    ds = sorted(nav)
    if not ds:
        return {}
    out, prev, d = {}, nav[ds[0]], ds[0] + dt.timedelta(days=1)
    while d <= ds[-1]:
        cur = nav.get(d, prev)
        out[d] = cur / prev - 1 if prev else 0.0
        prev, d = cur, d + dt.timedelta(days=1)
    return out


def lead_labels(vals: dict, min_prior: int = LEAD_MIN_PRIOR) -> dict:
    """{日: 值} → {日: True(主流领)/ False(二线领)};更早的非空值不足 min_prior 个的日子不给(没有状态)。只看严格更早的值。"""
    out, s, n = {}, 0.0, 0
    for d in sorted(vals):
        v = vals[d]
        if v is None:
            continue
        if n >= min_prior:
            out[d] = bool(v > s / n)
        s, n = s + float(v), n + 1
    return out


def cell_of(arm: str, t: Optional[float], l: Optional[float], lead: Optional[bool]) -> Optional[str]:
    """一天的格子;需要的轴缺了 ⇒ None。"""
    if arm == "HOLD_ALL":
        return "全部"
    if t is None:
        return None
    tt = "线下" if t < 0 else "线上"
    if arm == "T_ONLY":
        return tt
    if arm == "TxL":
        return None if l is None else f"{tt}·{'抽' if l < 0 else '注'}"
    if arm == "TxLEAD":
        return None if lead is None else f"{tt}·{'主流领' if lead else '二线领'}"
    raise ValueError(arm)


def scaled(rets: dict) -> dict:
    """{日: 收益} → {日: (缩放后收益, 倍数)}。与研究脚本 `_scaled` 同一写法(只用前一天及以前的 VOL_WIN 个观测)。"""
    tgt = TARGET_VOL / np.sqrt(ANN)
    ds = sorted(rets)
    v = np.array([rets[d] for d in ds], dtype=float)
    out = {}
    for i, d in enumerate(ds):
        w = v[max(0, i - VOL_WIN):i]
        if len(w) >= VOL_MIN_OBS and w.std() > 0:
            k = float(min(MAX_SCALE, tgt / w.std()))
            out[d] = (float(v[i] * k), k)
    return out


def step(members: list[str], sc: dict, d: dt.date) -> tuple[float, dict]:
    """一天:成员里当天可持有的等权平均缩放后收益;返回 (收益, {成员: 有效权重 = 倍数 / 持有数})。没有 ⇒ (0, {})。"""
    held = [k for k in members if d in sc.get(k, {})]
    if not held:
        return 0.0, {}
    return float(np.mean([sc[k][d][0] for k in held])), {k: sc[k][d][1] / len(held) for k in held}


def excess(raw: dict, cash: dict, funded: bool) -> dict:
    """占本金的扣现金日利率(cash:{日: 日利率},按日历日向前沿用;最早一天之前 = 0)。"""
    if not funded:
        return dict(raw)
    cs = sorted(cash)
    out, j, last = {}, 0, 0.0
    for d in sorted(raw):
        while j < len(cs) and cs[j] <= d:
            last, j = cash[cs[j]], j + 1
        out[d] = raw[d] - last
    return out


def extend_weekend(rets: dict) -> tuple[dict, Optional[dt.date]]:
    """只在工作日有收盘的腿:最后一根是周五 ⇒ 周六、周日收益 = 0 已经确定(研究里补齐也是 0)。返回 (收益, 已知到哪天)。"""
    if not rets:
        return {}, None
    last = max(rets)
    out = dict(rets)
    if last.weekday() == 4:
        for k in (1, 2):
            out[last + dt.timedelta(days=k)] = 0.0
        return out, last + dt.timedelta(days=2)
    return out, last


def plan_rows(inputs: dict, have: dict, cutoff: str) -> dict:
    """纯函数:由输入与已写的行决定这一轮要写的 NAV / 持仓行。

    inputs:{"t": {日: dist_200}, "l": {日: stable_supply_30d}, "lead": {日: bool}, "rets": {成员: {日: 对现金的超额}},
            "known": {成员: 已知到哪天}, "missing": {成员: 为什么这一轮读不到}}
    have:{臂: (最后写的日, 那天的 NAV)}。返回 {"nav": [...], "holdings": [...], "notes": [...], "now": {...}}。"""
    cut = D(cutoff)
    start = D(START)
    sc = {k: scaled(v) for k, v in inputs["rets"].items()}
    known = inputs.get("known", {})
    missing = {**UNAVAILABLE, **inputs.get("missing", {})}
    rows_n, rows_h, notes, now = [], [], [], {}
    for arm in ARMS:
        last, nav = have.get(arm, (None, None))
        if last is None:
            rows_n.append({"book": BOOK, "arm": arm, "d": START, "nav": 1.0, "ret": None, "as_of": START, "rule": RULE})
            last, nav = start, 1.0
        d = last + dt.timedelta(days=1)
        while d <= cut:
            prev = d - dt.timedelta(days=1)
            late = (cut - d).days >= LAG_GRACE_DAYS
            c = cell_of(arm, inputs["t"].get(prev), inputs["l"].get(prev), inputs["lead"].get(prev))
            if c is None and not late:
                break                                            # 前一天的状态还没出:等
            roster = list(ROSTERS[arm].get(c, ())) if c else []
            members = [k for k in roster if k not in EXCLUDED and k not in missing]
            wait = [k for k in members if (known.get(k) is None or known[k] < d)
                    and sum(1 for x in inputs["rets"].get(k, {}) if x < d) >= VOL_MIN_OBS]
            if wait and not late:
                break                                            # 名单里有成员的源还没到 d:等(最多 LAG_GRACE_DAYS 天)
            usable = [k for k in members if k not in wait]
            r, w = step(usable, sc, d)
            nav = nav * (1 + r)
            rows_n.append({"book": BOOK, "arm": arm, "d": d.isoformat(), "nav": nav, "ret": r, "as_of": START, "rule": RULE})
            note = (f"{c or '状态缺'};持有 {len(w)} / 名单 {len(roster)}"
                    + (f";拿不到 {','.join(k for k in roster if k in missing)}" if any(k in missing for k in roster) else "")
                    + (f";晚到按不可持有 {','.join(wait)}" if wait else ""))
            rows_h.append({"book": BOOK, "arm": arm, "as_of": prev.isoformat(), "key": "_state", "weight": float(len(w)),
                           "note": note[:500], "rule": RULE})
            rows_h += [{"book": BOOK, "arm": arm, "as_of": prev.isoformat(), "key": k, "weight": float(x),
                        "note": f"{c};d−1 收盘定、作用于 {d.isoformat()}", "rule": RULE} for k, x in w.items()]
            if wait:
                notes.append(f"{arm} {d}: {','.join(wait)} 晚到 ≥ {LAG_GRACE_DAYS} 天,按不可持有记")
            d += dt.timedelta(days=1)
        # 现在(cutoff 收盘)定下的、作用于明天的持仓 —— 只进 detail,不写行
        c = cell_of(arm, inputs["t"].get(cut), inputs["l"].get(cut), inputs["lead"].get(cut))
        roster = list(ROSTERS[arm].get(c, ())) if c else []
        now[arm] = {"cell": c, "roster": roster,
                    "cannot_hold": {k: (missing.get(k) or EXCLUDED.get(k)) for k in roster if k in missing or k in EXCLUDED}}
    return {"nav": rows_n, "holdings": rows_h, "notes": notes, "now": now}


# ── 读库 ────────────────────────────────────────────────────────────────────────

async def _get_all(tail: str) -> list[dict]:
    from src.data.universe.world50_book import _get_all as g
    return await g(tail)


def _shift(d: str, days: int) -> str:
    return (D(d) + dt.timedelta(days=days)).isoformat()


def _series_to_dict(s: Any) -> dict:
    return {ts.date(): float(v) for ts, v in s.items() if v == v}


def _kernel_members(closes: dict, fund: dict, missing: dict) -> dict:
    """X1V / 核心 / Tom PD13 的逐日收益(同步;调用方放进线程)。读不到的写进 missing。"""
    from src.data.signals.tom import tom_gross, trade_path, trade_returns
    from src.data.universe.forward_books import TOM_ARMS
    raw: dict[str, dict] = {}
    core = closes.get("CORE")
    if core is not None and len(core) >= 260:
        _, bear, size, exit_mode, vol = TOM_ARMS["CORE_X1V"]
        raw["X1V"] = _series_to_dict(trade_returns(core, trade_path(core, bear, size, exit_mode, vol), fund.get("CORE")))
        raw["核心"] = daily_from_nav(_series_to_dict(core))
    else:
        missing.update({"X1V": "① 回放净值不足 260 天", "核心": "① 回放净值不足 260 天"})
    for sym, name in (("BTC", "tom_pd13_btc"), ("ETH", "tom_pd13_eth")):
        c = closes.get(sym)
        if c is None or len(c) < 260:
            missing[name] = f"{sym} 收盘不足 260 天"
            continue
        raw[name] = _series_to_dict(trade_returns(c, tom_gross(c), fund.get(sym)))
    return raw


async def load_inputs(cutoff: str) -> dict:
    """各成员对现金的超额日收益 + 三条状态轴。读不到的成员写进 missing(读不到 ≠ 收益为 0)。"""
    from src.data.universe.forward_books import tom_inputs
    since = _shift(START, -HISTORY_DAYS)
    st = await _get_all("state_daily?select=d,feature,value&entity=eq.panel"
                        "&feature=in.(dist_200,stable_supply_30d,stable_lend_apy_7d)"
                        f"&d=gte.{since}&d=lte.{cutoff}&order=d")
    ax: dict[str, dict] = {}
    for r in st:
        if r.get("value") is not None:
            ax.setdefault(r["feature"], {})[D(r["d"])] = float(r["value"])
    lead_raw = await _get_all(f"state_daily?select=d,value&entity=eq.panel&feature=eq.style_rel_majors_30d"
                              f"&d=gte.{LEAD_FROM}&d=lte.{cutoff}&order=d")
    lead = lead_labels({D(r["d"]): (float(r["value"]) if r.get("value") is not None else None) for r in lead_raw})
    cash = {d: v / 100.0 / ANN for d, v in ax.get("stable_lend_apy_7d", {}).items()}
    raw: dict[str, dict] = {}
    known: dict[str, Optional[dt.date]] = {}
    missing: dict[str, str] = {}

    closes, fund = await tom_inputs(cutoff)
    raw.update(await asyncio.to_thread(_kernel_members, closes, fund, missing))     # 逐日循环的核不占事件循环(S-862)
    rv = await _get_all(f"r_money_daily?select=d,nav&d=lte.{cutoff}&order=d")
    if rv:
        raw["R-v2"] = daily_from_nav({D(r["d"]): float(r["nav"]) for r in rv if r.get("nav") is not None})
    else:
        missing["R-v2"] = "r_money_daily 读不到"
    for sym in ("ACWI", "XAUUSD"):
        rows = await _get_all(f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{sym}"
                              f"&trade_date=gte.{since}&trade_date=lte.{cutoff}&order=trade_date")
        px = {D(r["trade_date"]): float(r["close"]) for r in rows if r.get("close")}
        if not px:
            missing[sym] = f"ohlcv_daily eodhd {sym} 读不到"
            continue
        raw[sym], known[sym] = extend_weekend(daily_from_nav(px))
    sty = await _get_all(f"style_index_pit_daily?select=d,style,ret&weighting=eq.cap&d=gte.{since}&d=lte.{cutoff}&order=d")
    by: dict[str, dict] = {}
    for r in sty:
        if r.get("ret") is not None:
            by.setdefault(r["style"], {})[D(r["d"])] = float(r["ret"])
    for s in STYLES:
        rr = by.get(s)
        if not rr:
            missing[f"style_{s}"] = f"style_index_pit_daily {s} 读不到"
            continue
        nav, v = {}, 1.0
        for d in sorted(rr):
            v *= 1 + rr[d]
            nav[d] = v
        raw[f"style_{s}"] = daily_from_nav(nav)
    rets: dict[str, dict] = {}
    for k, r in raw.items():
        r = {d: x for d, x in r.items() if D(since) <= d <= D(cutoff)}
        rets[k] = excess(r, cash, SOURCES[k][1])
        known.setdefault(k, max(r) if r else None)
    return {"t": ax.get("dist_200", {}), "l": ax.get("stable_supply_30d", {}), "lead": lead, "rets": rets,
            "known": known, "missing": missing}


#: 每小时被 ③ 的循环叫一次。成员的源晚到时某条臂会落后 1–2 天,那几个小时不必每次都整段重读:同一个 cutoff 3 小时内只读一次。
_LAST_FULL: dict[str, Any] = {}
THROTTLE_S = 3 * 3600


async def run_state_book(cutoff: str, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """每次整段重算(纯函数、可复现),只写开账日之后还没写过的天;写过的不改。cutoff = 最后一个可以记收益的日子(昨天)。"""
    from src.api.store import supabase_upsert_table
    if cutoff < START:
        return {"ok": True, "waiting": f"从 {START} 收盘开账"}
    navs = await _get_all(f"forward_book_nav?select=arm,d,nav&book=eq.{BOOK}&order=d")
    have: dict[str, tuple] = {}
    for r in navs:
        have[r["arm"]] = (D(r["d"]), float(r["nav"]))
    if set(have) >= set(ARMS) and min(v[0] for v in have.values()) >= D(cutoff):
        return {"ok": True, "up_to_date": cutoff}
    now = now or dt.datetime.now(dt.timezone.utc)
    if _LAST_FULL.get("cutoff") == cutoff and (now - _LAST_FULL["at"]).total_seconds() < THROTTLE_S:
        return {"ok": True, "throttled": f"{cutoff} 已在 {_LAST_FULL['at'].isoformat()[:16]} 整段算过;落后的臂在等成员的源",
                "last_d": {a: v[0].isoformat() for a, v in have.items()}}
    inputs = await load_inputs(cutoff)
    plan = await asyncio.to_thread(plan_rows, inputs, have, cutoff)
    for t, rows, oc in (("forward_book_nav", plan["nav"], "book,arm,d"),
                        ("forward_book_holdings", plan["holdings"], "book,arm,as_of,key")):
        if rows:
            w = await supabase_upsert_table(t, rows, on_conflict=oc)
            if not w.ok:
                return {"ok": False, "why": f"写 {t} 失败:{(w.why or '')[:160]}"}
    _LAST_FULL.update({"cutoff": cutoff, "at": now})
    last = {a: v[0].isoformat() for a, v in have.items()}
    for r in plan["nav"]:
        last[r["arm"]] = max(last.get(r["arm"], ""), r["d"])
    return {"ok": True, "nav_written": len(plan["nav"]), "last_d": last, "now": plan["now"],
            "read_missing": inputs["missing"], **({"notes": plan["notes"][:6]} if plan["notes"] else {})}
