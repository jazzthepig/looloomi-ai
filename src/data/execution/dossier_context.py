"""③ 决策档案的「背景」栏:边际流动性 · 周期与估值 · 传统市场的信用与波动(11-13,S-844 / S-848)。

## 为什么

Jazz 11-13:「周线指标不可以只看指标和价格,还要和背景信息和宏观 cross reference;我们看起来很直接的东西,可能在低维决策下就看不到了」
「需要观察边际流动性的变化,市场往往随之转向而形成量价和技术指标」「还要和减半周期的影响做交叉比较」。

S-848 量到:这些序列库里早就有(`state_daily` 的稳定币供应与主动买盘、`macro_daily` 的 MVRV / Puell / 算力 / 高收益债利差 / VIX),
但 ③ 的档案(`exposure_decision_daily.inputs`)一条都没读。这里把它们按时点取出来,放进档案的 `context` 一栏。

## 纪律

- **只描述,不进规则、不动钱。** 规则敞口、基率臂与近邻臂的概率都不读这一栏;读它的是人、周信,和 LLM 判断臂(换了档案所以换了版本号)。
- **按时点:** 每个值都是 ≤ d 的最近一条,并写明它是哪一天的(`*_d`);太旧(超过 `MAX_AGE_D` 天)⇒ 不给值、写 stale。
- **没测到就是没有,不是 0。** 读不到的键不出现,另在 `missing` 里列名字。
- **维度打架要显式列出**(`conflicts`),不许只留一个结论 —— 11-13 一天之内,单看周线、单看流动性、单看减半日历各下过一次结论,三次都被下一维改掉。

减半日期是协议事实(区块高度 210,000 的整数倍),不是抓来的数。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

HALVINGS = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")
STATE_FEATURES = ("stable_supply_30d", "taker_buy_share_30d", "stable_lend_apy_7d")
MACRO_SERIES = ("btc_mvrv", "btc_puell", "btc_hash_30d", "hy_oas", "vix", "vix3m", "ust_2y", "ust_10y", "ust_10y_real", "fed_funds", "usd_broad")
MAX_AGE_D = 10
#: 美元指数周一才发布上一周的值,入库时又保守挪了 8 天 ⇒ 最新一条天然更旧,单独放宽
MAX_AGE_BY_SERIES = {"usd_broad": 20}
#: 这些序列另取 60 天前的读数(方向比水平有用)
CHANGE_60D = ("hy_oas", "ust_2y", "usd_broad")
LOOKBACK_D = 100
OPTION_FIELDS = ("skew_30d", "term_slope", "pc_vol_ratio")
WEEKLY_SMA_N, WEEKLY_LAG = 10, 4
CODE_REF = "dossier_context v1.1 (11-13: + 周线结构 / 期权偏斜 / 交易所一周流入)"


def halving_month(d: str) -> Optional[float]:
    """纯函数。d 距上一次减半的月数(30.44 天一个月);早于第一次减半 ⇒ None。"""
    day = dt.date.fromisoformat(d[:10])
    past = [dt.date.fromisoformat(h) for h in HALVINGS if dt.date.fromisoformat(h) <= day]
    return round((day - max(past)).days / 30.44, 1) if past else None


def halving_phase(m: Optional[float]) -> Optional[str]:
    """纯函数。S-844 补四用的四段(照「减半后一年多见顶、两年半见底」的常识分,没有调过)。"""
    if m is None:
        return None
    return "0-12m" if m < 12 else "12-18m" if m < 18 else "18-30m" if m < 30 else "30-48m"


def asof(rows: list[dict], d: str, key: str = "d") -> Optional[dict]:
    """纯函数。rows 里日期 ≤ d 的最近一条(绝不取 d 之后的);没有 ⇒ None。"""
    ok = [r for r in rows if r.get(key) and str(r[key])[:10] <= d[:10] and r.get("value") is not None]
    return max(ok, key=lambda r: str(r[key])[:10]) if ok else None


def weekly_structure(d: str, sunday_closes: list[tuple[str, float]]) -> dict[str, Any]:
    """纯函数。BTC 周日收盘(只用 ≤ d 的)→ 周线标志:收盘 < 10 周均线 且 < 4 周前收盘(S-844 补 / S-845 的同一个定义,没有调过);
    另报连续走低的周数。不够 10 根 ⇒ 空 dict。**单看它是低维读数(T-368 ❌),只在背景栏里和别的维度并排用。**"""
    w = sorted((str(a)[:10], float(c)) for a, c in sunday_closes if str(a)[:10] <= d[:10] and c)
    if len(w) < WEEKLY_SMA_N:
        return {}
    closes = [c for _, c in w]
    sma = sum(closes[-WEEKLY_SMA_N:]) / WEEKLY_SMA_N
    lower = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            lower += 1
        else:
            break
    return {"weekly_d": w[-1][0], "weekly_close": round(closes[-1], 2), "weekly_sma10": round(sma, 2),
            "weekly_down": bool(closes[-1] < sma and closes[-1] < closes[-1 - WEEKLY_LAG]), "weekly_lower_closes": lower}


def _age(d: str, at: str) -> int:
    return (dt.date.fromisoformat(d[:10]) - dt.date.fromisoformat(at[:10])).days


def build(d: str, state_rows: list[dict], macro_rows: list[dict], sunday_closes: Optional[list] = None,
          option_rows: Optional[list[dict]] = None, cex_rows: Optional[list[dict]] = None) -> dict[str, Any]:
    """纯函数。state_rows:[{d, feature, value}](面板,d 与 d−28 附近);macro_rows:[{d, series, value}](≤ d 的近 100 天);
    sunday_closes:[(日期, BTC 收盘)];option_rows:`options_surface_daily` 的 BTC 行;cex_rows:`cex_reserves_daily` 的行(各交易所)。"""
    out: dict[str, Any] = {"asof": d[:10], "code_ref": CODE_REF}
    missing: list[str] = []
    m = halving_month(d)
    out["halving_month"], out["halving_phase"] = m, halving_phase(m)

    def put(name: str, rows: list[dict], digits: int) -> Optional[float]:
        r = asof(rows, d)
        if r is None:
            missing.append(name)
            return None
        at = str(r["d"])[:10]
        if _age(d, at) > MAX_AGE_BY_SERIES.get(name, MAX_AGE_D):
            missing.append(f"{name}(stale {at})")
            return None
        out[name], out[f"{name}_d"] = round(float(r["value"]), digits), at
        return float(r["value"])

    for f in STATE_FEATURES:
        put(f, [r for r in state_rows if r.get("feature") == f], 4)
    prev_d = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=28)).isoformat()
    prev = asof([r for r in state_rows if r.get("feature") == "stable_supply_30d"], prev_d)
    if prev is not None and "stable_supply_30d" in out and _age(prev_d, str(prev["d"])[:10]) <= MAX_AGE_D:
        out["stable_supply_30d_4w_ago"] = round(float(prev["value"]), 4)
    for s in MACRO_SERIES:
        put(s, [r for r in macro_rows if r.get("series") == s], 3)
    old_d = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=60)).isoformat()
    for name in CHANGE_60D:
        old = asof([r for r in macro_rows if r.get("series") == name], old_d)
        if old is not None and name in out and _age(old_d, str(old["d"])[:10]) <= MAX_AGE_BY_SERIES.get(name, MAX_AGE_D):
            out[f"{name}_60d_ago"] = round(float(old["value"]), 3)
    ws = weekly_structure(d, sunday_closes or [])
    if ws and _age(d, ws["weekly_d"]) <= MAX_AGE_D:
        out.update(ws)
    elif sunday_closes is not None:
        missing.append("weekly_structure")
    if option_rows is not None:
        ok = [r for r in option_rows if r.get("d") and str(r["d"])[:10] <= d[:10]]
        o = max(ok, key=lambda r: str(r["d"])[:10]) if ok else None
        if o is None or _age(d, str(o["d"])[:10]) > MAX_AGE_D:
            missing.append("options_btc")
        else:
            out["options_d"] = str(o["d"])[:10]
            for f in OPTION_FIELDS:
                if o.get(f) is not None:
                    out[f"options_{f}"] = round(float(o[f]), 4)
    if cex_rows is not None:
        ok = [r for r in cex_rows if r.get("d") and str(r["d"])[:10] <= d[:10] and r.get("inflow_1w_usd") is not None]
        last = max((str(r["d"])[:10] for r in ok), default=None)
        if last is None or _age(d, last) > MAX_AGE_D:
            missing.append("cex_inflow_1w_usd")
        else:                                                             # 各交易所一周净流入之和;正 = 资产流进交易所。只给数,不给读数(方向的含义因场所而异)
            day = [r for r in ok if str(r["d"])[:10] == last]
            out["cex_inflow_1w_usd"], out["cex_inflow_d"], out["cex_inflow_n_exchanges"] = round(sum(float(r["inflow_1w_usd"]) for r in day), 0), last, len(day)
    out["reads"] = reads(out)
    out["conflicts"] = conflicts(out)
    if missing:
        out["missing"] = missing
    return out


def reads(c: dict) -> dict[str, str]:
    """纯函数。每一栏一句定性读数(只按正负号与公开阈值,不含任何拟合出来的线)。没值的栏不出现。"""
    r: dict[str, str] = {}
    s, t = c.get("stable_supply_30d"), c.get("taker_buy_share_30d")
    if s is not None:
        r["stable_supply"] = "adding" if s > 0 else "draining"
    if t is not None:
        r["taker"] = "buyers_aggressive" if t >= 0.5 else "sellers_aggressive"
    if c.get("btc_mvrv") is not None:
        r["valuation"] = "below_cost_basis" if c["btc_mvrv"] < 1.0 else "above_cost_basis"
    if c.get("hy_oas") is not None and c.get("hy_oas_60d_ago") is not None:
        r["credit"] = "widening" if c["hy_oas"] > c["hy_oas_60d_ago"] else "tightening_or_flat"
    if c.get("ust_2y") is not None and c.get("ust_2y_60d_ago") is not None:
        r["rates_2y"] = "rising" if c["ust_2y"] > c["ust_2y_60d_ago"] else "falling_or_flat"
    if c.get("ust_2y") is not None and c.get("fed_funds") is not None:
        r["policy_path"] = "market_prices_hikes" if c["ust_2y"] > c["fed_funds"] else "market_prices_cuts"
    if c.get("usd_broad") is not None and c.get("usd_broad_60d_ago") is not None:
        r["usd"] = "stronger" if c["usd_broad"] > c["usd_broad_60d_ago"] else "weaker_or_flat"
    if c.get("vix") is not None and c.get("vix3m") is not None:
        r["vix_term"] = "backwardation" if c["vix"] > c["vix3m"] else "contango"
    if c.get("halving_phase"):
        r["halving"] = c["halving_phase"]
    if c.get("weekly_down") is not None:
        r["weekly"] = "down" if c["weekly_down"] else "ok"
    return r


def conflicts(c: dict) -> list[str]:
    """纯函数。维度之间互相不同意的地方,原样列出(不裁决)。"""
    r, out = c.get("reads") or reads(c), []
    if r.get("halving") == "30-48m" and r.get("valuation") == "above_cost_basis":
        out.append("halving_phase 进了历史上的筑底段,但 MVRV > 1(前两次周期底在 0.69 / 0.78)")
    if r.get("halving") == "30-48m" and r.get("stable_supply") == "draining":
        out.append("halving_phase 偏多,稳定币供应在收缩")
    if r.get("stable_supply") == "adding" and r.get("taker") == "sellers_aggressive":
        out.append("稳定币在增加,但主动买盘占比 < 0.5(钱进来了、没有人追)")
    if r.get("stable_supply") == "draining" and r.get("taker") == "buyers_aggressive":
        out.append("稳定币在收缩,但主动买盘占比 ≥ 0.5")
    if r.get("weekly") == "ok" and r.get("stable_supply") == "draining":
        out.append("周线结构完好,但稳定币供应在收缩(价格好看、钱在走)")
    if r.get("weekly") == "ok" and r.get("taker") == "sellers_aggressive":
        out.append("周线结构完好,但主动买盘占比 < 0.5(没有主动买盘的上涨)")
    if r.get("weekly") == "down" and r.get("stable_supply") == "adding":
        out.append("周线坏了,但稳定币供应在增加")
    if r.get("rates_2y") == "rising" and r.get("stable_supply") == "adding":
        out.append("2 年期利率在升,稳定币供应仍在增加")
    if r.get("rates_2y") == "falling_or_flat" and r.get("stable_supply") == "draining":
        out.append("2 年期利率没有在升,稳定币供应却在收缩(钱走的原因不在利率)")
    if r.get("credit") == "widening" and r.get("vix_term") == "contango":
        out.append("信用利差在走阔,VIX 期限结构仍是正向(股市还没定价压力)")
    return out


async def context(d: str) -> dict[str, Any]:
    """读库 + build。读不到的那一半照样返回另一半;整个读失败由调用方兜。"""
    from src.data.style.header import _read_all
    lo28 = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=28 + MAX_AGE_D)).isoformat()
    lo = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=LOOKBACK_D)).isoformat()
    state = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel", "feature": f"in.({','.join(STATE_FEATURES)})",
                                            "and": f"(d.gte.{lo28},d.lte.{d[:10]})", "order": "d.asc,feature.asc"})
    macro = await _read_all("macro_daily", {"select": "d,series,value", "series": f"in.({','.join(MACRO_SERIES)})",
                                            "and": f"(d.gte.{lo},d.lte.{d[:10]})", "order": "d.asc,series.asc"})
    extra: dict[str, Any] = {}
    lo_w = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=7 * (WEEKLY_SMA_N + WEEKLY_LAG + 4))).isoformat()
    lo_s = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=MAX_AGE_D + 2)).isoformat()
    for key, table, params in (
            ("sunday_closes", "ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                                              "and": f"(trade_date.gte.{lo_w},trade_date.lte.{d[:10]})", "order": "trade_date.asc"}),
            ("option_rows", "options_surface_daily", {"select": "d," + ",".join(OPTION_FIELDS), "currency": "eq.BTC",
                                                      "and": f"(d.gte.{lo_s},d.lte.{d[:10]})", "order": "d.asc"}),
            ("cex_rows", "cex_reserves_daily", {"select": "d,exchange,inflow_1w_usd", "and": f"(d.gte.{lo_s},d.lte.{d[:10]})", "order": "d.asc,exchange.asc"})):
        try:
            extra[key] = await _read_all(table, params)
        except Exception:                                                 # noqa: BLE001 —— 这一栏读不到 ⇒ 记进 missing,不挡其余
            extra[key] = []
    sundays = [(r["trade_date"], r["close"]) for r in extra["sunday_closes"]
               if r.get("close") and dt.date.fromisoformat(str(r["trade_date"])[:10]).weekday() == 6]
    return build(d, state or [], macro or [], sundays, extra["option_rows"], extra["cex_rows"])
