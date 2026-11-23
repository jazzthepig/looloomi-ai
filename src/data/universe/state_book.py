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
**例外(S-898):已知的外部停供(`SOURCE_OUTAGES`,现在只有 CoinGecko 11-19 → 12-01)期间一直等、不落账** ——
一次停供不该被永久写成这本账的策略记录;恢复并回填之后,等着的那些天按同一条规则顺序写出。

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
#: S-898:已知的外部停供。输入日(状态看 d − 1、成员收益看 d)落在窗口里的那些天不触发「晚到 / 状态缺」,一直等;
#: 停供结束后再给 OUTAGE_BACKFILL_DAYS 天回填,过了仍没有才按原规则落账并写明。往这张表里加一行 = 改规则,先记台账。
SOURCE_OUTAGES: tuple[tuple[str, str, str], ...] = (
    ("2026-11-19", "2026-12-01", "CoinGecko 订阅停(Jazz 11-21;12-01 恢复)"),
)
OUTAGE_BACKFILL_DAYS = 7
HISTORY_DAYS = 200                   # σ 要 90 个日历日;多读一些
#: S-642 空头臂(T-412 的生产纯函数 `src/data/signals/s642_short.py`)接进这本账的**固定起点**(卡 T-428)。
#: 起点必须写死:每票 0.5% 净值风险 + 同时最多 10 张 ⇒ 今天的净值依赖更早开的票;起点一变,整段历史就变。
S642_FROM = "2025-01-01"
S642_WARMUP = 220                   # s642_short.WARMUP:信号日往前满 220 根
S642_BARS_LEAD = 230                # 往前多留 10 根余量(币安日线一天一根)
S642_BARS_FROM = (dt.date.fromisoformat(S642_FROM) - dt.timedelta(days=S642_BARS_LEAD)).isoformat()
S642_GATE_FROM = "2023-01-01"       # 闸门要 200 天 majors 才出值;起点写死 ⇒ 闸门值不随 cutoff 变
S642_SHARDS = 16                    # 并发分片读的片数(同一张表、同一个 `_get_all`)
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
    # S-898(T-406 的纯函数,在生产数据上整段重算;11-23 接,晚于 S-890 写的「合入那天」7 天 —— 已写的行不改)
    "s823_r6": ("state_arms.r6_exposure + r6_returns 作用于 asset_mcap_daily BTC、币安永续资金费按天求和", True),
    "s819_short_s015": ("state_arms.gate_short_returns(s = 0.15):BTC / ETH 等权篮子、majors 闸门前一天关着才空", False),
    "s819_short_s030": ("state_arms.gate_short_returns(s = 0.30)", False),
    # T-428:S-642 空头臂 = T-412 的生产纯函数在生产数据上整段重算(起点写死 S642_FROM);不扣现金(与研究族曲线同口径)
    "S642": ("s642_short.run_short + nav 整段重算(起点 S642_FROM;ohlcv_daily binance_hist 日线 + style_index_pit_daily majors/cap 闸门)", False),
}
GATE_SHORTS = {"s819_short_s015": 0.15, "s819_short_s030": 0.30}
#: 该拿、拿不到(S-890)。
UNAVAILABLE: dict[str, str] = {
    **{k: "只有研究回测" for k in ("S736_published", "S736_fixed", "S808", "S810", "S681_H2", "S681_H3", "S681_H4")},
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


def outage_reason(prev: dt.date, d: dt.date, cut: dt.date) -> Optional[str]:
    """S-898:d 这一天要的输入(状态看 prev、成员收益看 d)落在已知停供窗口里、且还在回填宽限内 ⇒ 返回停供的名字(等);否则 None。"""
    for a, b, why in SOURCE_OUTAGES:
        lo, hi = D(a), D(b)
        if (lo <= prev <= hi or lo <= d <= hi) and cut <= hi + dt.timedelta(days=OUTAGE_BACKFILL_DAYS):
            return why
    return None


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
    waiting: dict[str, str] = {}
    for arm in ARMS:
        last, nav = have.get(arm, (None, None))
        if last is None:
            rows_n.append({"book": BOOK, "arm": arm, "d": START, "nav": 1.0, "ret": None, "as_of": START, "rule": RULE})
            last, nav = start, 1.0
        d = last + dt.timedelta(days=1)
        while d <= cut:
            prev = d - dt.timedelta(days=1)
            held_by = outage_reason(prev, d, cut)
            late = (cut - d).days >= LAG_GRACE_DAYS and held_by is None    # 停供窗口里的日子不算晚到:等源,不落账(S-898)
            c = cell_of(arm, inputs["t"].get(prev), inputs["l"].get(prev), inputs["lead"].get(prev))
            if c is None and not late:
                if held_by:
                    waiting[arm] = f"{d} 等 {prev} 的状态:{held_by}"
                break                                            # 前一天的状态还没出:等
            roster = list(ROSTERS[arm].get(c, ())) if c else []
            members = [k for k in roster if k not in EXCLUDED and k not in missing]
            wait = [k for k in members if (known.get(k) is None or known[k] < d)
                    and sum(1 for x in inputs["rets"].get(k, {}) if x < d) >= VOL_MIN_OBS]
            if wait and not late:
                if held_by:
                    waiting[arm] = f"{d} 等成员 {','.join(wait)}:{held_by}"
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
    return {"nav": rows_n, "holdings": rows_h, "notes": notes, "now": now, "waiting": waiting}


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


def _state_arm_members(closes: dict, fund: dict, gate: Any) -> tuple[dict, dict]:
    """R6 与闸门空两档的逐日收益(同步;调用方放进线程)。返回 (收益, 读不到的原因)。

    **价缺不许变成 0**(S-898):研究脚本的闸门日历把篮子缺的日子按 0 计,那是给周末对齐用的;生产里价格缺 = 没测到。
    所以闸门空只算到「BTC、ETH 收盘都有、且前一天的闸门有值」的最后一天,之后的日子不给(等源)。"""
    import pandas as pd
    from src.data.signals.state_arms import (basket_funding, basket_returns, gate_calendar, gate_short_returns,
                                             r6_exposure, r6_returns)
    raw: dict[str, dict] = {}
    missing: dict[str, str] = {}
    btc, eth = closes.get("BTC"), closes.get("ETH")
    fb, fe = fund.get("BTC"), fund.get("ETH")
    if btc is None or len(btc) < 260 or fb is None or not len(fb):
        missing["s823_r6"] = "BTC 收盘不足 260 天或资金费读不到"
    else:
        ret, _, _ = r6_returns(btc, r6_exposure(btc), fb)
        raw["s823_r6"] = _series_to_dict(ret.iloc[1:])
    if btc is None or eth is None or fb is None or fe is None or gate is None or not len(gate) or len(gate) < 200:
        missing.update({k: "BTC / ETH 收盘、资金费或 majors 闸门读不到(闸门要 ≥ 200 天)" for k in GATE_SHORTS})
    else:
        known_to = min(btc.index.max(), eth.index.max(), gate.index.max() + pd.Timedelta(days=1))
        cal = gate_calendar(basket_returns({"BTC": btc, "ETH": eth}), basket_funding({"BTC": fb, "ETH": fe}), gate,
                            end=str(known_to.date()))
        for k, s in GATE_SHORTS.items():
            sr, _ = gate_short_returns(cal[0], cal[1], cal[2], s)
            raw[k] = _series_to_dict(sr[sr.index <= known_to].iloc[1:])
    return raw, missing


def _s642_known_to(bars: dict[str, list[dict]], gate: dict[str, bool]) -> Optional[str]:
    """最后一个「当天有日线的符号数 ≥ 前一天(按日历日)的 80%、且闸门有值」的日子。

    **价缺不许变成 0**(S-898 / I1):日历上**第一个**断点就截断(不是只截尾)—— 断点之后的盯市全是拿旧收盘
    记出来的假平盘,那是「没测到」不是「收益为 0」。所以那天之后一律不给,纸面账等源。"""
    cnt: dict[str, int] = {}
    for rows in bars.values():
        for r in rows:
            d = str(r["trade_date"])[:10]
            cnt[d] = cnt.get(d, 0) + 1
    if not cnt or not gate:
        return None
    days = sorted(cnt)
    gdays = sorted(gate)
    d = max(D(days[0]), D(gdays[0]))                        # 闸门还没值的日子发不出信号,不算断点
    end = D(days[-1])
    prev, known_to = 0, None
    while d <= end:
        k = d.isoformat()
        c = cnt.get(k, 0)
        if c <= 0 or c < 0.8 * prev or k not in gate:
            break                                            # 第一个断点就停
        known_to = k
        prev = c
        d += dt.timedelta(days=1)
    return known_to


def _s642_member(bars: dict[str, list[dict]], gate_rows: list[dict], cutoff: str,
                 d_from: str = S642_FROM, known_to: Optional[str] = None) -> dict:
    """S-642 空头臂(T-412 的生产纯函数 `src/data/signals/s642_short.py`)在生产数据上整段重算。

    `d_from` 写死成 `S642_FROM`:同时最多 10 张 ⇒ 今天的净值依赖更早开的票;起点一变,每天重算出来的历史就变。
    `known_to` = 覆盖规则的截断点;None = 按 `_s642_known_to` 算(生产路径)。给值 = 显式截断,
    只给复现/测试用(研究段导出的覆盖在段尾是「票开了就停」的形状,不是源停供)。
    返回 {"rets": {日: 日收益}, "nav": {日: 净值}, "known_to": 最后可给的一天, "reason": 给不出的原因}。
    同步纯函数;调用方放进线程。"""
    from src.data.signals.s642_short import nav, run_short
    from src.data.signals.short_paper import gate_closed_by_day
    out: dict = {"rets": {}, "nav": {}, "known_to": None, "reason": ""}
    if not bars or not gate_rows:
        out["reason"] = "S-642 输入读不到(ohlcv_daily binance_hist 或 style_index_pit_daily majors/cap)"
        return out
    gate = gate_closed_by_day(gate_rows)
    known_to = known_to or _s642_known_to(bars, gate)
    out["known_to"] = known_to
    if known_to is None:
        out["reason"] = "S-642 日线或闸门读不到"
        return out
    if known_to < d_from:
        out["reason"] = f"S-642 日线只到 {known_to}(还没到 {d_from})"
        return out
    bars = {s: [r for r in rows if str(r["trade_date"])[:10] <= known_to] for s, rows in bars.items()}
    bars = {s: rows for s, rows in bars.items() if rows}
    tk = run_short(bars, gate, d_from=d_from, d_to=known_to)
    curve = nav(tk, bars, d_to=known_to)
    if not curve:
        out["reason"] = "S-642 没开出票(闸门没关过或宇宙筛全灭)"
        return out
    eq = {D(r["d"]): float(r["equity"]) for r in curve}
    out["nav"] = eq
    out["rets"] = daily_from_nav(eq)
    return out


async def _s642_inputs(cutoff: str) -> tuple[dict[str, list[dict]], list[dict]]:
    """S-642 空头臂的输入:binance_hist 日线(`S642_BARS_FROM` → cutoff)+ majors/cap 闸门。

    整段一次读(生产里这本账没写到昨天时每 3 小时最多一次):按日历日分片并发走现有的 `_get_all`,
    每片显式 `order` —— 分片只改怎么取,不改取到哪些行。不新增取数入口、不出外网。"""
    d0, d1 = D(S642_BARS_FROM), D(cutoff)
    if d1 <= d0:
        return {}, []
    span = (d1 - d0).days
    step = max(1, -(-span // S642_SHARDS))
    tails: list[str] = []
    for i in range(0, span + 1, step):
        a = d0 + dt.timedelta(days=i)
        b = d0 + dt.timedelta(days=min(i + step - 1, span))
        tails.append(f"ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume"
                     f"&source=eq.binance_hist&trade_date=gte.{a.isoformat()}"
                     f"&trade_date=lte.{b.isoformat()}&order=symbol.asc,trade_date.asc")
    parts = await asyncio.gather(*[_get_all(t) for t in tails])
    bars: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for part in parts:
        for r in part or []:
            k = (r["symbol"], str(r["trade_date"])[:10])
            if k in seen:                       # 分片重叠(不该发生)也别把同一根日线算两遍
                continue
            seen.add(k)
            bars.setdefault(r["symbol"], []).append(r)
    for rows in bars.values():
        rows.sort(key=lambda r: str(r["trade_date"])[:10])
    gate_rows = await _get_all(f"style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap"
                                f"&d=gte.{S642_GATE_FROM}&d=lte.{cutoff}&order=d")
    return bars, gate_rows


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
    try:                                   # S-898:R6 / 闸门空 = T-406 的纯函数在生产数据上整段重算(与 state_arms 那本账同一来路)
        from src.data.universe.forward_books import state_arms_inputs
        sa_closes, sa_fund, sa_gate = await state_arms_inputs(cutoff)
        got, miss = await asyncio.to_thread(_state_arm_members, sa_closes, sa_fund, sa_gate)
        raw.update(got)
        missing.update(miss)
    except Exception as e:  # noqa: BLE001 —— 读不到 ≠ 收益为 0:写进 missing,当天按不可持有
        missing.update({k: f"state_arms 输入读不到:{type(e).__name__}" for k in ("s823_r6", *GATE_SHORTS)})
    try:                                   # T-428:S-642 空头臂 = T-412 的生产纯函数在生产数据上整段重算(起点写死 S642_FROM)
        s_bars, s_gate = await _s642_inputs(cutoff)
        m = await asyncio.to_thread(_s642_member, s_bars, s_gate, cutoff)
        if m["rets"]:
            raw["S642"] = m["rets"]
            known["S642"] = D(m["known_to"])
        else:
            missing["S642"] = m["reason"] or "S-642 这轮读不到"
    except Exception as e:  # noqa: BLE001 —— 读不到 ≠ 收益为 0
        missing["S642"] = f"S-642 输入读不到:{type(e).__name__}"
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
            **({"waiting": plan["waiting"]} if plan.get("waiting") else {}),
            "read_missing": inputs["missing"], **({"notes": plan["notes"][:6]} if plan["notes"] else {})}
