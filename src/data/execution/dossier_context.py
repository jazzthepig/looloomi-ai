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
STATE_FEATURES = ("stable_supply_30d", "taker_buy_share_30d", "stable_lend_apy_7d", "dist_200", "funding_7d_ann_binance", "oi_chg_30d", "mom_20")
MACRO_SERIES = ("btc_mvrv", "btc_puell", "btc_hash_30d", "hy_oas", "vix", "vix3m", "ust_2y", "ust_10y", "ust_10y_real", "fed_funds", "usd_broad", "fng")
#: 只在 context() 里一并读出来、由 build 自己汇总的序列(不走逐条 put)
MACRO_EXTRA_SERIES = ("btc_etf_net_flow_usd", "btc_coinbase_premium")
MAX_AGE_D = 10
#: 美元指数周一才发布上一周的值,入库时又保守挪了 8 天 ⇒ 最新一条天然更旧,单独放宽
MAX_AGE_BY_SERIES = {"usd_broad": 20}
#: 这些序列另取 60 天前的读数(方向比水平有用)
CHANGE_60D = ("hy_oas", "ust_2y", "usd_broad")
LOOKBACK_D = 110
OPTION_FIELDS = ("skew_30d", "term_slope", "pc_vol_ratio")
WEEKLY_SMA_N, WEEKLY_LAG = 10, 4
#: 叙事(S-855):量与调都拿「最近 7 天」对「再之前 180 天」比;之前那段不足 60 个读数 ⇒ 不给;最新一条超过 4 天 ⇒ 不给(循环一天轮一遍)
NARRATIVE_RECENT_D, NARRATIVE_BASE_D, NARRATIVE_MIN_BASE, NARRATIVE_MAX_AGE_D = 7, 180, 60, 4
TONE_SUFFIX = ":tone"
#: 恐惧贪婪指数的公开分档:≥ 55 = 贪婪区(55–75 贪婪,76+ 极度贪婪)
FNG_GREED = 55
#: 吸筹清单里的 MVRV 上沿(前两次周期底在 0.69 / 0.78;1.0 = 全网成本)
MVRV_VALUE_ZONE = 1.2
WHALE_COIN = "BTC"
CODE_REF = "dossier_context v1.2 (11-13: + 叙事的量与调 / 情绪与资金费 / 大户净仓 / 盯盘·派发·吸筹三张清单,S-855)"


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
            "weekly_down": bool(closes[-1] < sma and closes[-1] < closes[-1 - WEEKLY_LAG]), "weekly_lower_closes": lower,
            "weekly_is_10w_high": bool(closes[-1] >= max(closes[-WEEKLY_SMA_N:]))}


def _age(d: str, at: str) -> int:
    return (dt.date.fromisoformat(d[:10]) - dt.date.fromisoformat(at[:10])).days


def narratives(d: str, rows: list[dict]) -> dict[str, Any]:
    """纯函数。rows:`political_intensity_daily` 里叙事的行 [{d, topic, value}](d = 可得日;只用 ≤ d 的)。
    每条叙事给四个数,都是它对**自己**历史的相对读数(不同叙事的查询词宽窄不同,绝对量不能互相比):
      vol_x180     最近 7 天量的均值 ÷ 再之前 180 天的均值(> 1 = 比它自己半年的常态更响)
      vol_chg_7d   最近 7 天量的均值 ÷ 上一个 7 天 − 1(在变响还是在退)
      tone_7d      最近 7 天调的均值(GDELT 的语气分,负 = 负面)
      tone_vs_180  tone_7d 减再之前 180 天调的均值(负 = 比它自己的常态更负面)
    另给 `loudest`:按 vol_x180 从高到低的名字。只描述:哪条是真因、哪条是替罪羊,是人的判断。"""
    day = dt.date.fromisoformat(d[:10])
    by: dict[str, list[tuple[dt.date, float]]] = {}
    for r in rows:
        try:
            at, v = dt.date.fromisoformat(str(r["d"])[:10]), float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if at <= day and v == v:
            by.setdefault(str(r.get("topic")), []).append((at, v))

    def split(name: str) -> Optional[tuple[list[float], list[float], list[float]]]:
        xs = sorted(by.get(name) or [])
        if not xs or (day - xs[-1][0]).days > NARRATIVE_MAX_AGE_D:
            return None
        end = xs[-1][0]
        cut, cut2 = end - dt.timedelta(days=NARRATIVE_RECENT_D), end - dt.timedelta(days=2 * NARRATIVE_RECENT_D)
        lo = cut - dt.timedelta(days=NARRATIVE_BASE_D)
        recent = [v for at, v in xs if at > cut]
        prior = [v for at, v in xs if cut2 < at <= cut]
        base = [v for at, v in xs if lo < at <= cut]
        return (recent, prior, base) if len(recent) >= NARRATIVE_RECENT_D - 2 and len(base) >= NARRATIVE_MIN_BASE else None

    items: dict[str, dict] = {}
    missing: list[str] = []
    names = sorted({t[:-len(TONE_SUFFIX)] if t.endswith(TONE_SUFFIX) else t for t in by})
    for n in names:
        it: dict[str, Any] = {}
        vol, tone = split(n), split(n + TONE_SUFFIX)
        if vol is not None and sum(vol[2]) > 0:
            m7, m180 = sum(vol[0]) / len(vol[0]), sum(vol[2]) / len(vol[2])
            it["vol_x180"] = round(m7 / m180, 2)
            if vol[1] and sum(vol[1]) > 0:
                it["vol_chg_7d"] = round(m7 / (sum(vol[1]) / len(vol[1])) - 1, 3)
        else:
            missing.append(n)
        if tone is not None:
            t7 = sum(tone[0]) / len(tone[0])
            it["tone_7d"], it["tone_vs_180"] = round(t7, 2), round(t7 - sum(tone[2]) / len(tone[2]), 2)
        else:
            missing.append(n + TONE_SUFFIX)
        if it:
            items[n] = it
    out: dict[str, Any] = {}
    if items:
        out["items"] = items
        out["loudest"] = sorted((n for n in items if "vol_x180" in items[n]), key=lambda n: -items[n]["vol_x180"])
    if missing:
        out["missing"] = missing
    return out


def whales(d: str, rows: list[dict]) -> dict[str, Any]:
    """纯函数。`hl_whale_positioning_hourly` 的一个币的行 [{ts, long_usd, short_usd}] → 最近一个有 ≥ 12 个小时读数的 UTC 日的日均,
    以及正好 7 天前那一天的净仓(有才给)。被跟踪的是 HL 上一批大账户;净仓的**水平**混着对冲盘,只有**变化**可读。"""
    day = dt.date.fromisoformat(d[:10])
    by: dict[dt.date, list[tuple[float, float]]] = {}
    for r in rows:
        try:
            at = dt.date.fromisoformat(str(r["ts"])[:10])
            by.setdefault(at, []).append((float(r["long_usd"]), float(r["short_usd"])))
        except (KeyError, TypeError, ValueError):
            continue
    full = sorted(a for a, xs in by.items() if a <= day and len(xs) >= 12)
    if not full or (day - full[-1]).days > 2:
        return {}
    last = full[-1]
    lg, sh = (sum(x[i] for x in by[last]) / len(by[last]) for i in (0, 1))
    out = {"whale_d": last.isoformat(), "whale_long_usd": round(lg, 0), "whale_short_usd": round(sh, 0), "whale_net_usd": round(lg - sh, 0)}
    ago = last - dt.timedelta(days=7)
    if ago in full:
        out["whale_net_usd_7d_ago"] = round(sum(x[0] - x[1] for x in by[ago]) / len(by[ago]), 0)
    return out


def _yn(v: Optional[bool]) -> str:
    return "unreadable" if v is None else "yes" if v else "no"


def _all(*xs: Any) -> bool:
    return all(x is not None for x in xs)


def _tally(items: dict[str, Optional[bool]]) -> dict[str, Any]:
    r = {k: _yn(v) for k, v in items.items()}
    return {"items": r, "yes": sum(1 for v in r.values() if v == "yes"), "no": sum(1 for v in r.values() if v == "no"),
            "unreadable": sum(1 for v in r.values() if v == "unreadable")}


def checklists(c: dict) -> dict[str, Any]:
    """纯函数。三张清单,逐项「yes / no / unreadable」。**条件成立 = 开始盯,不是下单(Jazz 11-13,S-849);清单不给结论、不给分数线。**
    定义照登记时写的,没有调过:盯盘三条 = S-851 的 `conditions`(只在价格还在 200 日线上方时有意义);派发六条 = S-849;吸筹八条 = 11-13 周信。
    读不到的项就是 unreadable,不当 no。"""
    g = c.get
    s, s4, t, t4 = g("stable_supply_30d"), g("stable_supply_30d_4w_ago"), g("taker_buy_share_30d"), g("taker_buy_share_30d_4w_ago")
    y2, y2o, f, fmin = g("ust_2y"), g("ust_2y_91d_ago"), g("funding_7d_ann_binance"), g("funding_min_60d")
    oi, m20, d200 = g("oi_chg_30d"), g("mom_20"), g("dist_200")
    watch = _tally({"taker_below_half": None if t is None else t < 0.5,
                    "stable_supply_not_growing": None if s is None else s <= 0,
                    "ust_2y_above_91d_ago": (y2 > y2o) if _all(y2, y2o) else None})
    watch["applies"] = _yn(None if d200 is None else d200 > 0)          # 价格不在 200 日线上方 ⇒ 这三条不再是「先行」,该看的是另外两张
    dist = _tally({
        "price_10w_high_taker_falling": (bool(g("weekly_is_10w_high")) and t < t4) if _all(g("weekly_is_10w_high"), t, t4) else None,
        "cex_net_inflow_1w": None if g("cex_inflow_1w_usd") is None else g("cex_inflow_1w_usd") > 0,
        "whales_net_long_falling_7d": (g("whale_net_usd") < g("whale_net_usd_7d_ago")) if _all(g("whale_net_usd"), g("whale_net_usd_7d_ago")) else None,
        "oi_up_price_not": (oi > 0 and m20 <= 0) if _all(oi, m20) else None,
        "sentiment_in_greed": None if g("fng") is None else g("fng") >= FNG_GREED,
        "funding_positive": None if f is None else f > 0})
    acc = _tally({
        "stable_supply_turning_up": (s > s4) if _all(s, s4) else None,
        "etf_inflow_two_weeks": (g("btc_etf_flow_5d_bn") > 0 and g("btc_etf_flow_prev5d_bn") > 0) if _all(g("btc_etf_flow_5d_bn"), g("btc_etf_flow_prev5d_bn")) else None,
        "coinbase_premium_positive": None if g("btc_coinbase_premium_7d_bp") is None else g("btc_coinbase_premium_7d_bp") > 0,
        "funding_went_negative_then_positive": (f > 0 and fmin < 0) if _all(f, fmin) else None,
        "mvrv_at_or_below_value_zone": None if g("btc_mvrv") is None else g("btc_mvrv") <= MVRV_VALUE_ZONE,
        "hashrate_30d_not_falling": None if g("btc_hash_30d") is None else g("btc_hash_30d") >= 0,
        "ust_2y_below_91d_ago": (y2 < y2o) if _all(y2, y2o) else None,
        "hy_spread_narrowing": (g("hy_oas") < g("hy_oas_60d_ago")) if _all(g("hy_oas"), g("hy_oas_60d_ago")) else None})
    return {"watch": watch, "distribution": dist, "accumulation": acc}


def build(d: str, state_rows: list[dict], macro_rows: list[dict], sunday_closes: Optional[list] = None,
          option_rows: Optional[list[dict]] = None, cex_rows: Optional[list[dict]] = None,
          narrative_rows: Optional[list[dict]] = None, whale_rows: Optional[list[dict]] = None) -> dict[str, Any]:
    """纯函数。state_rows:[{d, feature, value}](面板,≤ d 的近 110 天);macro_rows:[{d, series, value}](≤ d 的近 110 天);
    sunday_closes:[(日期, BTC 收盘)];option_rows:`options_surface_daily` 的 BTC 行;cex_rows:`cex_reserves_daily` 的行(各交易所);
    narrative_rows:`political_intensity_daily` 里叙事的行;whale_rows:`hl_whale_positioning_hourly` 的 BTC 行。"""
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
    prev_t = asof([r for r in state_rows if r.get("feature") == "taker_buy_share_30d"], prev_d)
    if prev_t is not None and "taker_buy_share_30d" in out and _age(prev_d, str(prev_t["d"])[:10]) <= MAX_AGE_D:
        out["taker_buy_share_30d_4w_ago"] = round(float(prev_t["value"]), 4)
    # 资金费最近 60 天的最低点(吸筹清单要的是「先转负、再回正」:杠杆多头被洗出去过)。读数不足 30 个 ⇒ 不给。
    lo60 = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=60)).isoformat()
    fund = [float(r["value"]) for r in state_rows if r.get("feature") == "funding_7d_ann_binance" and r.get("value") is not None
            and lo60 < str(r.get("d"))[:10] <= d[:10]]
    if "funding_7d_ann_binance" in out and len(fund) >= 30:
        out["funding_min_60d"] = round(min(fund), 4)
    for s in MACRO_SERIES:
        put(s, [r for r in macro_rows if r.get("series") == s], 3)
    old_d = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=60)).isoformat()
    for name in CHANGE_60D:
        old = asof([r for r in macro_rows if r.get("series") == name], old_d)
        if old is not None and name in out and _age(old_d, str(old["d"])[:10]) <= MAX_AGE_BY_SERIES.get(name, MAX_AGE_D):
            out[f"{name}_60d_ago"] = round(float(old["value"]), 3)
    d91 = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=91)).isoformat()      # S-851 的盯盘条件用的是 91 天,和上面的 60 天各是各的定义
    y91 = asof([r for r in macro_rows if r.get("series") == "ust_2y"], d91)
    if y91 is not None and "ust_2y" in out and _age(d91, str(y91["d"])[:10]) <= MAX_AGE_D:
        out["ust_2y_91d_ago"] = round(float(y91["value"]), 3)
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
    # 现货比特币 ETF 净流入(按可得日):最近 5 个与 20 个交易日的合计,十亿美元。只有 BTC;没有就不写。
    etf = sorted((str(r["d"])[:10], float(r["value"])) for r in macro_rows
                 if r.get("series") == "btc_etf_net_flow_usd" and r.get("value") is not None and str(r.get("d"))[:10] <= d[:10])
    if etf and _age(d, etf[-1][0]) <= MAX_AGE_D:
        out["btc_etf_flow_5d_bn"] = round(sum(v for _, v in etf[-5:]) / 1e9, 3)
        if len(etf) >= 10:
            out["btc_etf_flow_prev5d_bn"] = round(sum(v for _, v in etf[-10:-5]) / 1e9, 3)
        if len(etf) >= 20:
            out["btc_etf_flow_20d_bn"] = round(sum(v for _, v in etf[-20:]) / 1e9, 3)
        out["btc_etf_flow_d"] = etf[-1][0]
    else:
        missing.append("btc_etf_flow")
    # Coinbase 溢价(Coinbase BTC-USD ÷ Binance BTCUSDT − 1;d = 已收盘的那一天):最近 7 天的均值,基点。正 = 美国现货在抬价。
    cbp = sorted((str(r["d"])[:10], float(r["value"])) for r in macro_rows
                 if r.get("series") == "btc_coinbase_premium" and r.get("value") is not None and str(r.get("d"))[:10] <= d[:10])
    if len(cbp) >= 7 and _age(d, cbp[-1][0]) <= 3:
        out["btc_coinbase_premium_7d_bp"] = round(sum(v for _, v in cbp[-7:]) / 7 * 1e4, 1)
        out["btc_coinbase_premium_d"] = cbp[-1][0]
    else:
        missing.append("btc_coinbase_premium")
    if whale_rows is not None:
        w = whales(d, whale_rows)
        if w:
            out.update(w)
        else:
            missing.append("whale_positioning")
    if narrative_rows is not None:
        nv = narratives(d, narrative_rows)
        if nv.get("items"):
            out["narratives"], out["narrative_loudest"] = nv["items"], nv["loudest"]
        else:
            missing.append("narratives")
        missing.extend(f"narrative:{m}" for m in nv.get("missing") or [] if nv.get("items"))
    out["reads"] = reads(out)
    out["conflicts"] = conflicts(out)
    out["checklists"] = checklists(out)
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
    if c.get("btc_coinbase_premium_7d_bp") is not None:
        r["us_spot"] = "premium" if c["btc_coinbase_premium_7d_bp"] > 0 else "discount"
    if c.get("btc_etf_flow_5d_bn") is not None:
        r["btc_etf_flow"] = "inflow" if c["btc_etf_flow_5d_bn"] > 0 else "outflow"
    if c.get("halving_phase"):
        r["halving"] = c["halving_phase"]
    if c.get("weekly_down") is not None:
        r["weekly"] = "down" if c["weekly_down"] else "ok"
    if c.get("dist_200") is not None:
        r["trend_200d"] = "above" if c["dist_200"] > 0 else "below"
    if c.get("fng") is not None:                                          # 公开分档:0–24 极度恐惧 · 25–46 恐惧 · 47–54 中性 · 55–75 贪婪 · 76+ 极度贪婪
        f = c["fng"]
        r["sentiment"] = "extreme_fear" if f < 25 else "fear" if f < 47 else "neutral" if f < FNG_GREED else "greed" if f < 76 else "extreme_greed"
    if c.get("funding_7d_ann_binance") is not None:
        r["funding"] = "longs_pay" if c["funding_7d_ann_binance"] > 0 else "shorts_pay"
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
    if r.get("sentiment") in ("extreme_fear", "fear") and r.get("funding") == "longs_pay":
        out.append("情绪在恐惧区,资金费仍为正(嘴上怕、杠杆多头还没走)")
    if r.get("sentiment") in ("greed", "extreme_greed") and r.get("stable_supply") == "draining":
        out.append("情绪在贪婪区,稳定币供应在收缩")
    if r.get("trend_200d") == "below" and r.get("taker") == "buyers_aggressive":
        out.append("价格在 200 日线下方,但主动买盘占比 ≥ 0.5(有人在接,或空头在平)")
    return out


async def context(d: str) -> dict[str, Any]:
    """读库 + build。读不到的那一半照样返回另一半;整个读失败由调用方兜。"""
    from src.data.style.header import _read_all
    lo = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=LOOKBACK_D)).isoformat()
    state = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel", "feature": f"in.({','.join(STATE_FEATURES)})",
                                            "and": f"(d.gte.{lo},d.lte.{d[:10]})", "order": "d.asc,feature.asc"})
    macro = await _read_all("macro_daily", {"select": "d,series,value", "series": f"in.({','.join(MACRO_SERIES + MACRO_EXTRA_SERIES)})",
                                            "and": f"(d.gte.{lo},d.lte.{d[:10]})", "order": "d.asc,series.asc"})
    extra: dict[str, Any] = {}
    lo_w = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=7 * (WEEKLY_SMA_N + WEEKLY_LAG + 4))).isoformat()
    lo_s = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=MAX_AGE_D + 2)).isoformat()
    lo_n = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=NARRATIVE_BASE_D + NARRATIVE_RECENT_D + NARRATIVE_MAX_AGE_D + 2)).isoformat()
    lo_wh = (dt.date.fromisoformat(d[:10]) - dt.timedelta(days=10)).isoformat()
    hi_wh = (dt.date.fromisoformat(d[:10]) + dt.timedelta(days=1)).isoformat()
    for key, table, params in (
            ("sunday_closes", "ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                                              "and": f"(trade_date.gte.{lo_w},trade_date.lte.{d[:10]})", "order": "trade_date.asc"}),
            ("option_rows", "options_surface_daily", {"select": "d," + ",".join(OPTION_FIELDS), "currency": "eq.BTC",
                                                      "and": f"(d.gte.{lo_s},d.lte.{d[:10]})", "order": "d.asc"}),
            ("cex_rows", "cex_reserves_daily", {"select": "d,exchange,inflow_1w_usd", "and": f"(d.gte.{lo_s},d.lte.{d[:10]})", "order": "d.asc,exchange.asc"}),
            ("narrative_rows", "political_intensity_daily", {"select": "d,topic,value", "topic": "in.(" + ",".join(f'"{t}"' for t in _narrative_series()) + ")",
                                                             "and": f"(d.gte.{lo_n},d.lte.{d[:10]})", "order": "d.asc,topic.asc"}),
            ("whale_rows", "hl_whale_positioning_hourly", {"select": "ts,long_usd,short_usd", "coin": f"eq.{WHALE_COIN}",
                                                           "and": f"(ts.gte.{lo_wh}T00:00:00Z,ts.lt.{hi_wh}T00:00:00Z)", "order": "ts.asc"})):
        try:
            extra[key] = await _read_all(table, params)
        except Exception:                                                 # noqa: BLE001 —— 这一栏读不到 ⇒ 记进 missing,不挡其余
            extra[key] = []
    sundays = [(r["trade_date"], r["close"]) for r in extra["sunday_closes"]
               if r.get("close") and dt.date.fromisoformat(str(r["trade_date"])[:10]).weekday() == 6]
    return build(d, state or [], macro or [], sundays, extra["option_rows"], extra["cex_rows"], extra["narrative_rows"], extra["whale_rows"])


LABELS = {
    "taker_below_half": "主动买盘占比 < 0.5", "stable_supply_not_growing": "稳定币 30 日增量 ≤ 0", "ust_2y_above_91d_ago": "2 年期高于 91 天前",
    "price_10w_high_taker_falling": "周线创 10 周新高而主动买盘在降", "cex_net_inflow_1w": "交易所一周净流入为正",
    "whales_net_long_falling_7d": "大户净仓较 7 天前下降", "oi_up_price_not": "未平仓升而价格不涨", "sentiment_in_greed": "情绪在贪婪区",
    "funding_positive": "资金费仍为正", "stable_supply_turning_up": "稳定币 30 日变化好于 4 周前", "etf_inflow_two_weeks": "ETF 连续两个 5 日净流入",
    "coinbase_premium_positive": "Coinbase 溢价为正", "funding_went_negative_then_positive": "资金费 60 天内转负过、现已回正",
    "mvrv_at_or_below_value_zone": "MVRV ≤ 1.2", "hashrate_30d_not_falling": "算力 30 日变化不为负", "ust_2y_below_91d_ago": "2 年期低于 91 天前",
    "hy_spread_narrowing": "高收益债利差较 60 天前收窄"}


def lines(c: dict) -> list[str]:
    """纯函数。背景栏 → ⓪ 简报第一屏的几行字(S-849 第 4 条:状态读法与清单进简报第一屏)。只排版,不加任何新判断;没有的数不写、不写成 0。"""
    if not c or "error" in c:
        return [f"状态读法:读不到({(c or {}).get('error', '空')})"]
    g = c.get

    def pc(k: str, nd: int = 1) -> Optional[str]:
        return None if g(k) is None else f"{g(k) * 100:+.{nd}f}%"

    def num(k: str, fmt: str = "{:.2f}") -> Optional[str]:
        return None if g(k) is None else fmt.format(g(k))

    def row(title: str, parts: list[Optional[str]]) -> Optional[str]:
        got = [x for x in parts if x]
        return f"  {title}  " + " · ".join(got) if got else None

    def ago(v: Optional[str], k: str, label: str, fmt: str = "{:.2f}", scale: float = 1.0) -> Optional[str]:
        return v if v is None or g(k) is None else f"{v}({label} {fmt.format(g(k) * scale)})"

    out = [f"状态读法(截至 {g('asof')};只描述,条件成立 = 开始盯,不是指令)"]
    out.append(row("流动性", [
        ago(None if pc("stable_supply_30d", 2) is None else "稳定币 30 日 " + pc("stable_supply_30d", 2), "stable_supply_30d_4w_ago", "4 周前", "{:+.2f}%", 100),
        ago(None if g("taker_buy_share_30d") is None else f"主动买盘 {g('taker_buy_share_30d'):.3f}", "taker_buy_share_30d_4w_ago", "4 周前", "{:.3f}"),
        ago(None if g("btc_etf_flow_5d_bn") is None else f"ETF 5 日 {g('btc_etf_flow_5d_bn'):+.2f}bn", "btc_etf_flow_prev5d_bn", "前 5 日", "{:+.2f}"),
        None if g("btc_coinbase_premium_7d_bp") is None else f"Coinbase 溢价 {g('btc_coinbase_premium_7d_bp'):+.1f}bp",
        None if g("cex_inflow_1w_usd") is None else f"交易所一周净流入 {g('cex_inflow_1w_usd') / 1e6:+,.0f}M"]))
    y = None if g("ust_2y") is None else f"2Y {g('ust_2y'):.2f}"
    if y and (g("ust_2y_60d_ago") is not None or g("ust_2y_91d_ago") is not None):
        y += "(" + " / ".join(x for x in (num("ust_2y_60d_ago", "60 天前 {:.2f}"), num("ust_2y_91d_ago", "91 天前 {:.2f}")) if x) + ")"
    out.append(row("宏观  ", [y, num("fed_funds", "联邦基金 {:.2f}"), num("ust_10y_real", "10Y 实际 {:.2f}"),
                              ago(num("hy_oas", "高收益利差 {:.2f}"), "hy_oas_60d_ago", "60 天前"),
                              ago(num("usd_broad", "美元 {:.1f}"), "usd_broad_60d_ago", "60 天前", "{:.1f}"),
                              None if g("vix") is None else f"VIX {g('vix'):.1f}" + ("" if g("vix3m") is None else f" / 3 个月 {g('vix3m'):.1f}")]))
    out.append(row("周期  ", [None if g("halving_month") is None else f"减半后 {g('halving_month')} 月({g('halving_phase')})",
                              num("btc_mvrv", "MVRV {:.2f}"), num("btc_puell", "Puell {:.2f}"),
                              None if pc("btc_hash_30d") is None else "算力 30 日 " + pc("btc_hash_30d")]))
    wh = None if g("whale_net_usd") is None else f"HL 大户净仓 {g('whale_net_usd') / 1e6:+,.0f}M"
    out.append(row("仓位  ", [ago(None if pc("funding_7d_ann_binance") is None else "资金费 " + pc("funding_7d_ann_binance") + "/年", "funding_min_60d", "60 天最低", "{:+.1f}%", 100),
                              None if pc("oi_chg_30d", 0) is None else "未平仓 30 日 " + pc("oi_chg_30d", 0),
                              None if g("fng") is None else f"恐惧贪婪 {g('fng'):.0f}",
                              ago(wh, "whale_net_usd_7d_ago", "7 天前", "{:+,.0f}M", 1e-6),
                              num("options_skew_30d", "期权 30 日偏斜 {:+.2f}")]))
    wk = None
    if g("weekly_down") is not None:
        wk = f"周线{'坏' if g('weekly_down') else '完好'}(收 {g('weekly_close'):,.0f} / 10 周均线 {g('weekly_sma10'):,.0f},连续走低 {g('weekly_lower_closes')} 周)"
    out.append(row("价格  ", [wk, None if pc("dist_200") is None else "距 200 日线 " + pc("dist_200"), None if pc("mom_20") is None else "20 日 " + pc("mom_20")]))
    nar = g("narratives") or {}
    if nar:
        def one(n: str) -> str:
            it = nar[n]
            t = "" if it.get("tone_7d") is None else f",调 {it['tone_7d']:+.1f}(较常态 {it['tone_vs_180']:+.1f})"
            ch = "" if it.get("vol_chg_7d") is None else f",周环比 {it['vol_chg_7d'] * 100:+.0f}%"
            return f"{n} {it['vol_x180']:.1f}×{ch}{t}"
        out.append("  叙事    " + " · ".join(one(n) for n in (g("narrative_loudest") or [])[:4]) + "(× = 对它自己半年均值)")
    for x in g("conflicts") or []:
        out.append("  打架    " + x)
    k = g("checklists") or {}
    for key, title in (("watch", "盯盘"), ("distribution", "派发"), ("accumulation", "吸筹")):
        b = k.get(key)
        if not b:
            continue
        head = f"  {title}清单  {b['yes']} 成立 / {b['no']} 没有" + (f" / {b['unreadable']} 读不到" if b["unreadable"] else "")
        if key == "watch":
            head += {"yes": "", "no": "(价格已在 200 日线下方:这三条不再是先行条件)", "unreadable": "(200 日线位置读不到)"}[b.get("applies", "unreadable")]
        yes = [LABELS.get(n, n) for n, v in b["items"].items() if v == "yes"]
        unr = [LABELS.get(n, n) for n, v in b["items"].items() if v == "unreadable"]
        out.append(head + (" —— 成立:" + ";".join(yes) if yes else "") + (" —— 读不到:" + ";".join(unr) if unr else ""))
    if g("missing"):
        out.append("  没读到  " + ", ".join(g("missing")))
    return [x for x in out if x]


def _narrative_series() -> list[str]:
    """叙事清单只有一份,在写入端(`political_intensity.NARRATIVE_TOPICS`);这里只读它,不另抄一份。"""
    from src.data.market.political_intensity import NARRATIVE_TOPICS
    from src.data.market.political_intensity import TONE_SUFFIX as suffix
    return [x for t in NARRATIVE_TOPICS for x in (t, t + suffix)]
