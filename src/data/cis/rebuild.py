"""CIS 按时点重建 —— 统一标准 v1(T-079 / S-531,docs/CIS_STANDARD.md)。

## 为什么

Jazz 10-09:「先开始重建 …… 重建不是问题,问题是要数据和时序对上。有缺了维度的补上。」
我们手里的 CIS 历史是代理重建 + T2 + T1 + Railway 快照拼起来的(S-530)。这里用**实盘 T2 同一个纯函数**
(`calculate_cis_score` / `calculate_total_score` / `get_grade` / `get_signal` / `detect_regime`),
每天只喂 d 收盘时已知的输入,从 2023 起算出一条序列。不写 `cis_scores` —— 实盘历史原样保留。

## 每个输入从哪来(标准 §3)

加密:收盘 / 涨跌 / ATH / 市值 / 全市场成交额 = asset_mcap_daily(CG market_chart,同一时刻);日内高低 = binance_hist
(HYPE:coingecko_pro_ohlc);TVL:DeFi = protocol_tvl_daily,L2 = chain_activity_daily;资金费率 = binance_perp 当日均值;
总量 / 上限 = 今天的值(静态,标注)。传统资产:eodhd 复权日线,成交 = 股数 × 收盘。
宏观:恐惧贪婪 / VIX / 全市场市值 = macro_daily;BTC 占比 = BTC 市值 / 全市场市值。
不能复原的(CG 开发者分、热搜、叙事乘数、未平仓量、IC 反馈)一律中性 —— 记进每行的 `missing`。

## 标签

信号按状态调整后的分数(与实盘同);等级按原始分(与实盘同)。另出一列滞回信号:换档要越过门槛 ±2 分,
缓冲带内保持原档并标 `watch`(up / down)。

## 判活判据(规则 5b ②)

    select max(d) from cis_rebuild_daily where code_ref = 'cis-standard-v1';   -- = 昨天
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

TABLE = "cis_rebuild_daily"
WRITES_TABLES = (TABLE,)
CODE_REF = "cis-standard-v1"
START = pd.Timestamp("2023-01-01")
READ_FROM = "2019-12-01"
BAND = 2.0
#: 信号门槛(由高到低):≥85 STRONG OUTPERFORM … <35 UNDERWEIGHT。与 get_grade / get_signal 一致。
LEVELS = ("UNDERWEIGHT", "UNDERPERFORM", "NEUTRAL", "OUTPERFORM", "STRONG OUTPERFORM")
CUTS = (35.0, 45.0, 65.0, 85.0)
TRADFI = frozenset({"US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"})
#: L2 → DeFiLlama 链(chain_activity_daily.gecko_id = 币的 coingecko id)
L2_CHAIN = {"ARB": "arbitrum", "OP": "optimism", "POL": "polygon-ecosystem-token", "STRK": "starknet"}
NOT_RECONSTRUCTABLE = ("cg_dev_score", "trending_rank", "narrative_modifier", "open_interest", "ic_feedback",
                       "macro_beta")   # github_commits:有 52 周,更早的复原不了(按天判断,不整体排除)


def level_of(score: float) -> int:
    """纯函数。分数 → 档位 0..4(UNDERWEIGHT … STRONG OUTPERFORM)。"""
    return sum(1 for c in CUTS if score >= c)


def hysteresis(scores: list[Optional[float]], band: float = BAND) -> list[tuple[Optional[int], Optional[str]]]:
    """纯函数。按日的分数序列 → [(档位, watch)]。换档要越过门槛 ±band;缓冲带内保持原档,标 watch up / down。
    分数缺的那天档位不变、不标。第一天直接按分数定档。"""
    out: list[tuple[Optional[int], Optional[str]]] = []
    cur: Optional[int] = None
    for s in scores:
        if s is None or (isinstance(s, float) and math.isnan(s)):
            out.append((cur, None))
            continue
        if cur is None:
            cur = level_of(s)
            out.append((cur, None))
            continue
        up, down = level_of(s - band), level_of(s + band)
        if up > cur:
            cur = up
        elif down < cur:
            cur = down
        raw = level_of(s)
        out.append((cur, "up" if raw > cur else "down" if raw < cur else None))
    return out


def _num(v: Any) -> Optional[float]:
    """numpy / pandas 标量 → Python float;缺失 → None(写库的 JSON 只认原生类型)。"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b <= 0 or (isinstance(a, float) and math.isnan(a)) or math.isnan(b):
        return None
    return (a / b - 1) * 100


def crypto_market_data(px: pd.Series, mcap: pd.Series, vol: pd.Series, hi: pd.Series, lo: pd.Series,
                       d: pd.Timestamp, static: Mapping[str, Any]) -> tuple[Optional[dict], list[str]]:
    """纯函数。一个加密名字在 d 的 market_data(只用 ≤ d 的值)。返回 (dict 或 None, 缺的维度)。"""
    p = px.get(d)
    if p is None or pd.isna(p) or p <= 0:
        return None, ["price"]
    miss: list[str] = []
    hist = px.loc[:d].dropna()
    m = mcap.get(d)
    m = float(m) if m is not None and pd.notna(m) else 0.0
    v = vol.get(d)
    if v is None or pd.isna(v):
        miss.append("volume")
        v = 0.0
    h, l = hi.get(d), lo.get(d)
    if h is None or l is None or pd.isna(h) or pd.isna(l):
        miss.append("high_low")
        h = l = 0.0
    circ = m / p if m > 0 else 0.0
    total = float(static.get("total_supply") or 0)
    mx = static.get("max_supply")
    fdv = p * total if total > 0 else 0.0
    ath = float(hist.max())
    md = {
        "price": float(p), "market_cap": m, "volume_24h": float(v), "circulating_supply": circ,
        "total_supply": total, "max_supply": float(mx) if mx else None, "fdv": fdv,
        "change_24h": _pct(p, px.get(d - pd.Timedelta(days=1))) or 0.0,
        "change_7d": _pct(p, px.get(d - pd.Timedelta(days=7))) or 0.0,
        "change_30d": _pct(p, px.get(d - pd.Timedelta(days=30))) or 0.0,
        "sparkline_return_7d": None,
        "ath_change_percentage": (p / ath - 1) * 100 if ath > 0 else 0.0,
        "high_24h": float(h), "low_24h": float(l),
    }
    if total <= 0:
        miss.append("total_supply")
    return md, miss


def tradfi_market_data(cl: pd.Series, hi: pd.Series, lo: pd.Series, vol: pd.Series,
                       d: pd.Timestamp, static: Optional[Mapping[str, Any]] = None) -> tuple[Optional[dict], list[str]]:
    """纯函数。传统资产在 d 的 market_data:d 当天或之前最近一个交易日(最多回看 4 天)。
    市值没有历史:用今天的市值 × (d 的价 / 今天的价)近似(股数 / 份额不变的假设,标 `tradfi_market_cap_static`)。
    不给市值时 A 支柱的规模项会从 −5 跳到 +20 —— 10-09 与实盘对照时 A 差 14 分就是这个。"""
    s = cl.loc[:d].dropna()
    if s.empty or (d - s.index[-1]).days > 4:
        return None, ["price"]
    t = s.index[-1]
    p = float(s.iloc[-1])

    def back(n: int) -> Optional[float]:
        z = cl.loc[:t - pd.Timedelta(days=n)].dropna()
        return float(z.iloc[-1]) if not z.empty else None

    win = s.loc[t - pd.Timedelta(days=50):]
    mc_now, px_now = (static or {}).get("market_cap"), (static or {}).get("price")
    mcap = float(mc_now) * p / float(px_now) if mc_now and px_now else 0.0
    md = {
        "price": p, "market_cap": mcap, "volume_24h": float(vol.get(t) or 0) * p,
        "change_24h": _pct(p, back(1)) or 0.0, "change_7d": _pct(p, back(7)) or 0.0, "change_30d": _pct(p, back(30)) or 0.0,
        "ath_change_percentage": (p / float(win.max()) - 1) * 100 if len(win) else 0.0,
        "high_24h": float(hi.get(t) or 0), "low_24h": float(lo.get(t) or 0),
    }
    return md, ["tradfi_market_cap_static"] if mcap else ["tradfi_market_cap"]


def pit_fundamentals(q: list[dict], price: float, d: pd.Timestamp) -> Optional[dict]:
    """纯函数。按可得日复原 d 那天的 PE 与营收同比(百分比):只用 available_d ≤ d 的季度。
    PE = 价格 / 最近四季 EPS 之和(≤ 0 不给);营收同比 = 最近四季营收 / 再往前四季营收 − 1。"""
    known = sorted((r for r in q if str(r["available_d"]) <= d.date().isoformat()), key=lambda r: str(r["period_end"]))
    if len(known) < 4:
        return None
    last4 = known[-4:]
    eps = [r.get("eps") for r in last4]
    out: dict[str, Any] = {}
    if all(e is not None for e in eps) and sum(eps) > 0:
        out["pe_ratio"] = price / sum(eps)
    if len(known) >= 8:
        prev4 = known[-8:-4]
        a = [r.get("revenue") for r in last4]
        b = [r.get("revenue") for r in prev4]
        if all(x is not None for x in a + b) and sum(b) > 0:
            out["revenue_growth_yoy"] = (sum(a) / sum(b) - 1) * 100
    return out or None


def commits_4w(weeks: Mapping[str, int], d: pd.Timestamp) -> Optional[int]:
    """纯函数。d 之前 4 个**已完成**的周(周日开始)提交数之和;不满 4 周 ⇒ None(复原不了,不补 0)。"""
    this_sunday = d - pd.Timedelta(days=(d.weekday() + 1) % 7)
    want = [(this_sunday - pd.Timedelta(days=7 * k)).date().isoformat() for k in (1, 2, 3, 4)]
    vals = [weeks.get(w) for w in want]
    return int(sum(vals)) if all(v is not None for v in vals) else None


def score_day(d: pd.Timestamp, assets: Mapping[str, Mapping[str, Any]], data: Mapping[str, Any]) -> list[dict]:
    """纯函数(除了 cis_provider 的纯函数)。d 这一天全宇宙的分数行。"""
    from src.data.cis.cis_provider import (calculate_cis_score, calculate_total_score, canonical_regime_strict,
                                           detect_regime, get_grade, get_signal)
    mds: dict[str, tuple[dict, list[str]]] = {}
    for sym, cfg in assets.items():
        if cfg["class"] in TRADFI:
            t = data["tradfi"].get(sym)
            md, miss = tradfi_market_data(*t, d, data.get("static_tf", {}).get(sym)) if t else (None, ["price"])
        else:
            c = data["crypto"].get(sym)
            md, miss = crypto_market_data(*c, d, data["static"].get(sym, {})) if c else (None, ["price"])
        if md:
            mds[sym] = (md, miss)
    if "BTC" not in mds:
        return []
    btc30 = mds["BTC"][0]["change_30d"]
    spy30 = mds["SPY"][0]["change_30d"] if "SPY" in mds else None
    fng_v = _num(data["macro"].get("fng", {}).get(d))
    vix = _num(data["macro"].get("vix", {}).get(d))
    tot = _num(data["macro"].get("total_mcap", {}).get(d))
    btc_m = mds["BTC"][0]["market_cap"]
    bdom = btc_m / tot * 100 if tot and btc_m else None
    regime = detect_regime(btc30, int(fng_v) if fng_v is not None else 50, vix, bdom)
    fng = {"value": int(fng_v)} if fng_v is not None else None
    cat: dict[str, list[float]] = {}
    for sym, (md, _) in mds.items():
        cat.setdefault(assets[sym]["class"], []).append(md["change_30d"])
    cat_med = {k: sorted(v)[len(v) // 2] for k, v in cat.items()}
    rows = []
    for sym, (md, miss) in mds.items():
        cls = assets[sym]["class"]
        is_tf = cls in TRADFI
        tvl = 0.0
        if not is_tf:
            tv = data["tvl"].get(sym)
            if tv is not None:
                x = tv.get(d)
                tvl = float(x) if x is not None and pd.notna(x) else 0.0
                if not tvl:
                    miss = miss + ["tvl"]
        fr = _num(data["funding"].get(sym, {}).get(d)) if not is_tf else None
        gh = commits_4w(data["github"][sym], d) if sym in data.get("github", {}) else None
        fund = None
        if cls == "US Equity" and sym in data.get("fundamentals", {}):
            fund = pit_fundamentals(data["fundamentals"][sym], md["price"], d)
            if fund is None:
                miss = miss + ["eodhd_fundamentals"]
        deriv = {sym: {"funding_rate": fr, "funding_signal": "binance_perp_daily_mean"}} if fr is not None else {}
        pil = calculate_cis_score(
            md, tvl, fng, cls, asset_id=sym,
            btc_change_30d=btc30 if (sym != "BTC" and not is_tf) else None,
            github_commits_4w=gh, vix=vix if is_tf else None,
            spy_change_30d=spy30 if ((is_tf and sym != "SPY") or sym == "BTC") else None,
            asset_betas=None, category_median_30d=cat_med.get(cls, 0), dev_activity_score=None,
            eodhd_fundamentals=fund, regime=regime, _deriv_map=deriv, _trend_map={}, narrative_modifier=0.0)
        tot_r = calculate_total_score({k: pil[k] for k in "FMOSA"}, cls, regime=regime, ic_mult=None)
        if fng_v is None:
            miss = miss + ["fng"]
        if is_tf and vix is None:
            miss = miss + ["vix"]
        if not is_tf and fr is None:
            miss = miss + ["funding"]
        rows.append({
            "symbol": sym, "d": d.date().isoformat(), "asset_class": cls,
            "pillar_f": pil["F"], "pillar_m": pil["M"], "pillar_o": pil["O"], "pillar_s": pil["S"], "pillar_a": pil["A"],
            "raw_score": tot_r["raw_cis_score"], "score": tot_r["total_score"],
            "grade": get_grade(tot_r["raw_cis_score"]),
            "signal_raw": get_signal(tot_r["total_score"], get_grade(tot_r["total_score"])),
            "regime": canonical_regime_strict(regime),
            "inputs": {"price": round(md["price"], 8), "mcap": md.get("market_cap"), "volume": md.get("volume_24h"),
                       "chg30": round(md["change_30d"], 3), "fng": fng_v, "vix": vix, "btc_dom": round(bdom, 3) if bdom else None,
                       "tvl": tvl or None, "funding": fr},
            "missing": sorted(set(miss)),
        })
    return rows


#: 候选口径(S-531 ⑤,待 Jazz):同组当日分位 → 档位。由低到高:后 10% / 10–30% / 30–70% / 70–90% / 前 10%。
PCT_CUTS = (0.10, 0.30, 0.70, 0.90)
PCT_BAND = 0.05


def pct_level(p: float) -> int:
    """纯函数。分位 0..1 → 档位 0..4。"""
    return sum(1 for c in PCT_CUTS if p >= c)


def pct_hysteresis(ps: list[Optional[float]], band: float = PCT_BAND) -> list[tuple[Optional[int], Optional[str]]]:
    """纯函数。同 `hysteresis`,只是门槛在分位上(±band)。"""
    out: list[tuple[Optional[int], Optional[str]]] = []
    cur: Optional[int] = None
    for p in ps:
        if p is None:
            out.append((cur, None))
            continue
        if cur is None:
            cur = pct_level(p)
            out.append((cur, None))
            continue
        up, down = pct_level(p - band), pct_level(p + band)
        if up > cur:
            cur = up
        elif down < cur:
            cur = down
        raw = pct_level(p)
        out.append((cur, "up" if raw > cur else "down" if raw < cur else None))
    return out


def group_pct(rows: list[dict]) -> None:
    """就地。每天、每组(加密 / 传统资产)按分数排分位(平均名次 / 人数,0..1);同组当天 < 5 个名字不排。"""
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        g = "tradfi" if r["asset_class"] in TRADFI else "crypto"
        by.setdefault((r["d"], g), []).append(r)
    for rs in by.values():
        sc = [r for r in rs if r.get("score") is not None]
        if len(sc) < 5:
            for r in rs:
                r["pct"] = None
            continue
        s = pd.Series([r["score"] for r in sc]).rank(method="average")
        n = len(sc)
        for r, rk in zip(sc, s):
            r["pct"] = round(float((rk - 0.5) / n), 4)


def churn(levels: list[Optional[int]], days: list[str]) -> tuple[int, int]:
    """纯函数。一个名字的档位序列 → (换档次数, 其中 3 天内又变回原档的次数)。"""
    ch, back = 0, 0
    idx = [i for i in range(1, len(levels)) if levels[i] is not None and levels[i - 1] is not None and levels[i] != levels[i - 1]]
    for k, i in enumerate(idx):
        ch += 1
        if k + 1 < len(idx):
            j = idx[k + 1]
            if levels[j] == levels[i - 1] and (pd.Timestamp(days[j]) - pd.Timestamp(days[i])).days <= 3:
                back += 1
    return ch, back


def label_stats(rows: list[dict]) -> dict[str, Any]:
    """纯函数。候选口径的换档频率:每组、每个带宽,每名字每 30 天换档几次、3 天内变回的占比。供口径决定(S-531 ⑤)。"""
    by: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        g = "tradfi" if r["asset_class"] in TRADFI else "crypto"
        by.setdefault(g, {}).setdefault(r["symbol"], []).append(r)
    out: dict[str, Any] = {}
    for g, syms in by.items():
        n_days = sum(len(v) for v in syms.values()) or 1
        res = {}
        for name, fn in (("abs_2pt", lambda rs: [lv for lv, _ in hysteresis([r["score"] for r in rs])]),
                         *[(f"pct_{int(b * 100)}", (lambda b: lambda rs: [lv for lv, _ in pct_hysteresis([r.get("pct") for r in rs], b)])(b))
                           for b in (0.05, 0.10, 0.15)]):
            ch = back = 0
            for rs in syms.values():
                rs = sorted(rs, key=lambda r: r["d"])
                c, b_ = churn(fn(rs), [r["d"] for r in rs])
                ch += c
                back += b_
            res[name] = {"changes_per_name_30d": round(30 * ch / n_days, 2), "flip_back_3d": round(back / ch, 3) if ch else None}
        out[g] = res
    return out


def label_rows(rows: list[dict]) -> list[dict]:
    """纯函数。按名字、按日期给每行加滞回信号与 watch。"""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["symbol"], []).append(r)
    for rs in by.values():
        rs.sort(key=lambda r: r["d"])
        for r, (lv, w) in zip(rs, hysteresis([r["score"] for r in rs])):
            r["signal"] = LEVELS[lv] if lv is not None else None
            r["watch"] = w
        for r, (lv, w) in zip(rs, pct_hysteresis([r.get("pct") for r in rs])):
            r["signal_pct"] = LEVELS[lv] if lv is not None else None
            r["watch_pct"] = w
    return rows


def _series(rows: list[dict], key: str, val: str, keyval: str) -> pd.Series:
    xs = [(pd.Timestamp(r["d"] if "d" in r else str(r["trade_date"])[:10]), r[val]) for r in rows if r.get(key) == keyval]
    if not xs:
        return pd.Series(dtype=float)
    s = pd.Series({k: v for k, v in xs}, dtype=float).sort_index()
    return s


async def load_inputs(end: pd.Timestamp) -> tuple[dict, dict]:
    """从库里读全部输入。返回 (assets, data)。读不到抛异常 —— 不拿空表算分。"""
    from src.data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS
    from src.data.market.data_layer import get_cg_markets
    from src.data.style.header import SOURCE as CG_SOURCE, _read_all
    assets = {k: {"class": v["class"], "coingecko": v.get("coingecko")} for k, v in ASSETS_CONFIG.items()}
    cg_ids = {k: v["coingecko"] for k, v in CRYPTO_ASSETS.items() if v.get("coingecko")}
    mc = await _read_all("asset_mcap_daily", {"select": "coin_id,d,price,mcap,volume", "source": f"eq.{CG_SOURCE}",
                                              "coin_id": f"in.({','.join(cg_ids.values())})", "d": f"gte.{READ_FROM}"})
    if not mc:
        raise RuntimeError("asset_mcap_daily 读到 0 行")
    hl = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,high,low", "source": "eq.binance_hist",
                                         "symbol": f"in.({','.join(cg_ids)})", "trade_date": "gte.2022-11-01"})
    hl_hype = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,high,low", "source": "eq.coingecko_pro_ohlc",
                                              "symbol": "eq.HYPE", "trade_date": "gte.2022-11-01"})
    tf_syms = [s for s in ASSETS_CONFIG if s not in CRYPTO_ASSETS]
    tf = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close,high,low,volume", "source": "eq.eodhd",
                                         "symbol": f"in.({','.join(tf_syms)})", "trade_date": "gte.2022-08-01"})
    macro = await _read_all("macro_daily", {"select": "series,d,value"})
    ptvl = await _read_all("protocol_tvl_daily", {"select": "symbol,d,tvl_usd"})
    ctvl = await _read_all("chain_activity_daily", {"select": "gecko_id,d,tvl_usd",
                                                    "gecko_id": f"in.({','.join(L2_CHAIN.values())})"})
    fund = await _read_all("v_funding_daily", {"select": "symbol,d,funding_rate", "d": "gte.2022-11-01"})
    cur = await get_cg_markets(list(cg_ids.values()))
    static = {}
    by_cg = {x.get("id"): x for x in (cur or []) if isinstance(x, dict)}
    for sym, cg in cg_ids.items():
        x = by_cg.get(cg) or {}
        static[sym] = {"total_supply": x.get("total_supply"), "max_supply": x.get("max_supply")}

    def col(rows, key, kv, val):
        return _series(rows, key, val, kv)

    crypto = {}
    for sym, cg in cg_ids.items():
        hsrc = hl_hype if sym == "HYPE" else hl
        crypto[sym] = (col(mc, "coin_id", cg, "price"), col(mc, "coin_id", cg, "mcap"), col(mc, "coin_id", cg, "volume"),
                       col(hsrc, "symbol", sym, "high"), col(hsrc, "symbol", sym, "low"))
    tradfi = {s: (col(tf, "symbol", s, "close"), col(tf, "symbol", s, "high"), col(tf, "symbol", s, "low"),
                  col(tf, "symbol", s, "volume")) for s in tf_syms}
    tvl = {}
    for sym in ("UNI", "AAVE", "LDO", "PENDLE"):
        tvl[sym] = col(ptvl, "symbol", sym, "tvl_usd")
    for sym, g in L2_CHAIN.items():
        tvl[sym] = col(ctvl, "gecko_id", g, "tvl_usd")
    macro_s = {}
    for k in ("fng", "vix", "total_mcap"):
        s = col(macro, "series", k, "value")
        if k == "vix" and len(s):                          # 周末 / 假日用最近一个交易日(最多 4 天),标准 §2
            s = s.reindex(pd.date_range(s.index.min(), max(s.index.max(), end), freq="D")).ffill(limit=4)
        macro_s[k] = s.to_dict()
    funding = {s: col(fund, "symbol", s, "funding_rate").to_dict() for s in cg_ids}
    from src.data.market.data_layer import get_eodhd_eod_data
    static_tf = {}
    for s in tf_syms:
        try:
            x = await get_eodhd_eod_data(s, "US") or {}
        except Exception:                                   # noqa: BLE001
            x = {}
        if x.get("market_cap") and x.get("price"):
            static_tf[s] = {"market_cap": float(x["market_cap"]), "price": float(x["price"])}
    gq = await _read_all("github_commits_weekly", {"select": "symbol,week_start,commits"})
    github: dict[str, dict[str, int]] = {}
    for r in gq:
        github.setdefault(r["symbol"], {})[str(r["week_start"])[:10]] = int(r["commits"])
    fq = await _read_all("equity_fundamentals_q", {"select": "symbol,period_end,available_d,eps,revenue"})
    fundamentals: dict[str, list[dict]] = {}
    for r in fq:
        fundamentals.setdefault(r["symbol"], []).append(r)
    data = {"crypto": crypto, "tradfi": tradfi, "tvl": tvl, "macro": macro_s, "funding": funding, "static": static,
            "static_tf": static_tf, "fundamentals": fundamentals, "github": github}
    return assets, data


def build(assets: Mapping[str, Mapping[str, Any]], data: Mapping[str, Any], end: pd.Timestamp,
          start: pd.Timestamp = START) -> list[dict]:
    """纯函数。start → end 每天全宇宙一行,再加滞回标签。"""
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for d in pd.date_range(start, end, freq="D"):
        rows += score_day(d, assets, data)
    group_pct(rows)
    rows = label_rows(rows)
    for r in rows:
        r["code_ref"] = CODE_REF
        r["computed_at"] = now
        for k in ("pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a", "raw_score", "score"):
            v = r.get(k)
            r[k] = None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 2)
    return rows


async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.vector.market_state_writer import _sb_get
    today = today or datetime.now(timezone.utc).date()
    end = pd.Timestamp(today - timedelta(days=1))
    assets, data = await load_inputs(end)
    rows = await asyncio.to_thread(build, assets, data, end)
    if not rows:
        return {"ok": False, "refused": True, "written": 0, "reason": "一行都没算出来(BTC 没有价格?)"}
    rd = await _sb_get(TABLE, {"select": "d", "code_ref": f"eq.{CODE_REF}", "order": "d.asc", "limit": "1"})
    # 全量重写:表里还没有这一版 / 周一 / 库里还有「补维度之前」算的行(成交额或恐惧贪婪缺)—— 输入补齐后整条重算
    stale = await _sb_get(TABLE, {"select": "d", "code_ref": f"eq.{CODE_REF}", "missing": "ov.{volume,fng,tradfi_market_cap,eodhd_fundamentals}",
                                  "d": f"gte.{START.date().isoformat()}", "limit": "1"})
    no_pct = await _sb_get(TABLE, {"select": "d", "code_ref": f"eq.{CODE_REF}", "signal_pct": "is.null",
                                   "d": f"gte.{START.date().isoformat()}", "limit": "1"})
    full = ((not rd.ok) or (not rd.rows) or today.weekday() == 0 or (stale.ok and bool(stale.rows))
            or (no_pct.ok and bool(no_pct.rows)))
    cut = (today - timedelta(days=10)).isoformat()
    out = rows if full else [r for r in rows if r["d"] >= cut]
    for i in range(0, len(out), 1000):
        res = await supabase_upsert_table(TABLE, out[i:i + 1000], on_conflict="symbol,d,code_ref")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    miss: dict[str, int] = {}
    for r in rows:
        if r["d"] >= cut:
            for m in r["missing"]:
                miss[m] = miss.get(m, 0) + 1
    try:
        stats = label_stats(rows)
    except Exception as e:                                  # noqa: BLE001
        stats = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    return {"ok": True, "refused": False, "written": len(out), "full": full, "rows_total": len(rows),
            "missing_last_10d": miss, "label_stats": stats,
            "reason": f"{len(rows)} 行({'全量' if full else '近 10 天'}写入 {len(out)})"}
