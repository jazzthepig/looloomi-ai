"""T-187 · 崩盘图谱 C 道(加密)—— 台账 S-675,只 import 共用内核,不复制它的函数。

Jazz 10-23:「给每个市场崩盘(主流、EM、crypto)前的事件、迹象和情绪,还有对应的策略风格,做个挖掘」。

**这是挖掘,不是检验。** 每个迹象对基准率 + 循环平移零分布(内核 sign_lift,种子 675、2,000 次)。
「线索」只进候选,要当规则用必须另立预注册、按前向判。

跑法:python3 docs/research/t187_crash_atlas_crypto.py
出:docs/research/t187_results.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from docs.research.crash_atlas_common import (  # noqa: E402
    SEED,
    available,
    bear_episodes,
    expanding_pct,
    fast_crashes,
    load_fred,
    phase_returns,
    sign_lift,
    to_calendar,
    trend_200_nav,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t187_results.json")

# ── 取数(库只读 publishable key;翻页必带 order=)────────────────────────────────
SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
if not SUPA or not SUPK:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置,退出")

PAGE = 1000


def fetch(table: str, params: dict) -> list[dict]:
    """PostgREST 翻页读。**必须**带 order=(按主键排)—— 不带时翻页边界会漂(T-170 / T-173 实测)。"""
    q = dict(params)
    q["select"] = q.get("select", "*")
    q["limit"] = str(PAGE)
    rows: list[dict] = []
    off = 0
    while True:
        q["offset"] = str(off)
        url = SUPA + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(
            url, headers={"apikey": SUPK, "Authorization": "Bearer " + SUPK})
        chunk = json.loads(urllib.request.urlopen(req, timeout=90).read())
        if not isinstance(chunk, list):
            raise RuntimeError(table + ": " + str(chunk)[:200])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        off += PAGE


def srs(rows: list[dict], x: str, y: str, agg: str = "last") -> pd.Series:
    """行 → 日历日序列。funding_time 有混合格式(带 / 不带毫秒)且一天 3 行 ⇒ ISO8601 解析 + agg="sum"。
    价格 / 市值等一天一行(agg="last")。"""
    idx = pd.to_datetime([r[x] for r in rows], format="ISO8601", utc=True).tz_localize(None).normalize()
    s = pd.Series(pd.to_numeric([r[y] for r in rows], errors="coerce"), index=idx,
                  dtype="float64").dropna()
    g = s.groupby(level=0)
    return (g.sum() if agg == "sum" else g.last()).sort_index()


# ── 崩盘目录(S-675 写死:熊市 0.50 / 急跌 14 天 −30% 去簇 60 天)─────────────────
def load_prices() -> tuple[pd.Series, pd.Series]:
    out = {}
    for sym in ("BTC", "ETH"):
        rows = fetch("asset_mcap_daily",
                     {"symbol": "eq." + sym, "order": "d.asc",
                      "select": "symbol,d,price"})
        # 卡:只用 price 列,不用「市值 ÷ 价格」推
        out[sym] = srs(rows, "d", "price")
    return out["BTC"], out["ETH"]


def macro_series(name: str) -> pd.Series:
    rows = fetch("macro_daily", {"series": "eq." + name, "order": "d.asc", "select": "d,value"})
    return srs(rows, "d", "value")


# ── 迹象 C1–C6 ──────────────────────────────────────────────────────────────
def mk(cond: pd.Series, valid: pd.Series) -> pd.Series:
    """把「条件成立」变成可空布尔 —— **数据没到的日子必须留 NA,不能当成 False**。
    (否则 sign_lift 的 covered 会把没数据的锚点算成「用过」,跳过数就少报了。)"""
    v = valid if valid.dtype == bool else valid.notna()
    return cond.astype("boolean").where(v)


def sign_c1(fng: pd.Series) -> pd.Series:
    """C1 恐惧贪婪 ≥ 75 连续 ≥ 7 天 ⇒ 当天往前 7 个日历日全部 ≥ 75。"""
    cal = to_calendar(fng, 7)
    hot = cal >= 75
    return mk(hot.rolling(7, min_periods=7).sum() >= 7, cal)


def sign_c2_btc_funding(sym: str = "BTC", venue: str = "binance_perp") -> pd.Series:
    """C2 资金费 7 日均年化 ≥ 30%。每 8 小时一行;日内之和 × 365 = 年化。"""
    rows = fetch("funding_history", {"symbol": "eq." + sym, "venue": "eq." + venue,
                                     "order": "funding_time.asc", "select": "funding_time,funding_rate"})
    f = srs(rows, "funding_time", "funding_rate", agg="sum")   # 日内之和
    ann = to_calendar(f, 5) * 365.0          # 日内之和 → 年化
    m7 = to_calendar(ann, 10).rolling(7, min_periods=7).mean()
    return mk(m7 >= 0.30, m7)


def sign_c3_oi(sym: str = "BTC") -> pd.Series:
    """C3 持仓量 30 天增长,按 expanding_pct 的按时点分位 ≥ 0.9。"""
    rows = fetch("deriv_metrics_daily", {"symbol": "eq." + sym, "order": "d.asc",
                                         "select": "d,oi_value_close"})
    oi = to_calendar(srs(rows, "d", "oi_value_close"), 5)
    g = (oi / oi.shift(30) - 1.0).replace([np.inf, -np.inf], np.nan)
    p = expanding_pct(g)
    return mk(p >= 0.9, p)


def sign_c4_stables() -> pd.Series:
    """C4 USDT + USDC 市值 30 天增长 < 0(同 S-673)。"""
    tot = None
    for cid in ("tether", "usd-coin"):
        rows = fetch("cg_coin_mcap_daily", {"coin_id": "eq." + cid, "order": "d.asc",
                                            "select": "d,mcap"})
        m = to_calendar(srs(rows, "d", "mcap"), 5)
        tot = m if tot is None else tot.add(m, fill_value=0.0)
    g = (tot / tot.shift(30) - 1.0).replace([np.inf, -np.inf], np.nan)
    return mk(g < 0, g)


def sign_c5_btc_share(btc_mcap: pd.Series) -> pd.Series:
    """C5 BTC 市占 60 天降 ≥ 10pp。BTC 市值取 7 日中位数(T-183:单日端点会换档)。
    total_mcap 2018-01 起 ⇒ 2018 年前没有市占,那些锚点必须报成跳过。"""
    tc = to_calendar(macro_series("total_mcap"), 5)
    b = to_calendar(btc_mcap, 5).rolling(7, min_periods=7).median()
    share = b / tc
    d = (share - share.shift(60)).replace([np.inf, -np.inf], np.nan)
    return mk(d <= -0.10, d)


def sign_c6_volume() -> pd.Series:
    """C6 全市场成交额 30 天均值,按 expanding_pct 的按时点分位 ≥ 0.9。"""
    v = to_calendar(macro_series("total_volume"), 5)
    p = expanding_pct(v.rolling(30, min_periods=30).mean())
    return mk(p >= 0.9, p)


# ── 风格净值 ────────────────────────────────────────────────────────────────
ALT_STYLES = ["defi", "second_l1_l2", "infra_tokenization", "ai", "app"]


def alt_ew_nav() -> tuple[pd.Series, list[str]]:
    """山寨板块 EW 指数:五个板块(style_index_pit_daily,weighting=equal)日收益等权累积。"""
    rows = fetch("style_index_pit_daily",
                 {"dimension": "in.(sector,tier)", "style": "in.(" + ",".join(ALT_STYLES) + ")",
                  "weighting": "eq.equal", "order": "d.asc", "select": "d,style,ret"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    piv = df.pivot_table(index="d", columns="style", values="ret", aggfunc="last").sort_index()
    got = [s for s in ALT_STYLES if s in piv.columns]
    ew = piv[got].mean(axis=1)          # 缺的板块当天不参与(等权)
    return (1 + ew.fillna(0.0)).cumprod(), got


def btc_mcap_series() -> pd.Series:
    rows = fetch("asset_mcap_daily", {"symbol": "eq.BTC", "order": "d.asc",
                                      "select": "d,mcap"})
    return srs(rows, "d", "mcap")


def half_split(n: int) -> tuple[list, list]:
    """按时间前半 / 后半切锚点(前半 = 前 ceil(n/2) 个)。"""
    h = (n + 1) // 2
    return list(range(h)), list(range(h, n))


def main() -> None:
    res: dict = {"task": "T-187", "ledger": "S-675", "seed": SEED, "n_shift": 2000}

    btc, eth = load_prices()
    btc_ep = bear_episodes(btc, 0.50)
    btc_fc = fast_crashes(btc, 14, 0.30, 60)
    eth_ep = bear_episodes(eth, 0.50)
    eth_fc = fast_crashes(eth, 14, 0.30, 60)

    def dump_eps(eps, fc):
        return {
            "bear_episodes": [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                               for k, v in e.items()} for e in eps],
            "fast_crashes": [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                              for k, v in f.items()} for f in fc],
        }

    res["catalog"] = {"BTC": dump_eps(btc_ep, btc_fc), "ETH": dump_eps(eth_ep, eth_fc)}
    res["catalog"]["BTC"]["price_span"] = [str(btc.index[0].date()), str(btc.index[-1].date())]
    res["catalog"]["ETH"]["price_span"] = [str(eth.index[0].date()), str(eth.index[-1].date())]

    # 锚点(S-675 结构,三道同一套):主 = first_leg 前高回看 90 天;辅 = 全部破位日 / 急跌起点回看 30 天
    first_peaks = [e["peak_d"] for e in btc_ep if e["first_leg"]]
    break_d = [e["break_d"] for e in btc_ep]
    fc_start = [f["start_d"] for f in btc_fc]
    res["anchors"] = {
        "primary_first_leg_peaks": [str(d.date()) for d in first_peaks],
        "aux_breaks": [str(d.date()) for d in break_d],
        "aux_fast_crash_starts": [str(d.date()) for d in fc_start],
    }

    # ── 迹象表 ─────────────────────────────────────────────────────────────
    fng = macro_series("fng")
    bmc = btc_mcap_series()
    signs = {
        "C1_fng_ge75_7d": sign_c1(fng),
        "C2_btc_funding_ann_7d_ge30pct": sign_c2_btc_funding(),
        "C3_btc_oi_30d_growth_pct_ge90": sign_c3_oi(),
        "C4_stables_30d_growth_lt0": sign_c4_stables(),
        "C5_btc_share_60d_drop_ge10pp": sign_c5_btc_share(bmc),
        "C6_total_vol_30d_mean_pct_ge90": sign_c6_volume(),
    }
    anchor_sets = {"primary_90d": (first_peaks, 90),
                   "aux_break_30d": (break_d, 30),
                   "aux_fastcrash_30d": (fc_start, 30)}
    sign_res = {}
    for name, on in signs.items():
        on = on.sort_index()
        ok = on.dropna()
        entry = {"data_span": [str(ok.index[0].date()) if len(ok) else None,
                               str(ok.index[-1].date()) if len(ok) else None],
                 "n_valid_days": int(len(ok)),
                 "n_on_days": int(ok.fillna(False).sum())}
        for aset, (anchors, L) in anchor_sets.items():
            full = sign_lift(on, anchors, L)
            half = half_split(len(anchors))
            h1 = sign_lift(on, [anchors[i] for i in half[0]], L) if half[0] else {"hit_rate": None}
            h2 = sign_lift(on, [anchors[i] for i in half[1]], L) if half[1] else {"hit_rate": None}
            entry[aset] = {**full, "half1_hit_rate": h1.get("hit_rate"),
                           "half2_hit_rate": h2.get("hit_rate"),
                           "half1_n": len(half[0]), "half2_n": len(half[1])}
        sign_res[name] = entry
    res["signs"] = sign_res

    # 稳健性:锚点整体挪 ±1 天再判一次(S-665 的规矩 —— 只在当天成立的量不算)。
    # C3/C4/C5/C6 都是派生量(30/60 天变化、占比),核一遍 +1/−1 天命不命中还稳。
    robust = {}
    for name, on in signs.items():
        on = on.sort_index()
        row = {}
        for shift in (-1, 1):
            sh = [a + pd.Timedelta(days=shift) for a in first_peaks]
            r = sign_lift(on, sh, 90)
            row["shift%+d" % shift] = {"n_anchors": r["n_anchors"], "hit_rate": r["hit_rate"],
                                       "lift": r["lift"], "pctile": r["pctile"]}
        base = sign_res[name]["primary_90d"]
        row["hit_rate_stable"] = bool(base["hit_rate"] is not None and all(
            r["hit_rate"] is not None and abs(r["hit_rate"] - base["hit_rate"]) < 1e-9
            for r in row.values()))
        robust[name] = row
    res["robustness_anchor_shift_1d"] = robust

    # ── 风格:分阶段收益(只报不判)─────────────────────────────────────────────
    from src.data.signals.tom import trade_path  # 只读 import,不改
    x1_g = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
    x1v = (1 + x1_g.shift(1).fillna(0.0) * btc.pct_change().fillna(0.0)).cumprod()
    alt_nav, alt_got = alt_ew_nav()
    styles = {
        "BTC_hold": btc,
        "BTC_trend200_nav": trend_200_nav(btc),                      # 空仓 0 收益,不拿利率
        "X1V_trade_path_rally_l20": x1v,
        "ETH_hold": eth,
        "ALT_sector_EW_nav": alt_nav,
        "BTC_over_ALT": btc / alt_nav,
    }
    res["alt_styles_used"] = alt_got
    res["styles"] = {nm: [{"peak_d": str(e["peak_d"].date()), "trough_d": str(e["trough_d"].date()),
                           "depth": e["depth"], "first_leg": e["first_leg"],
                           **phase_returns(lv, e)} for e in btc_ep if not e["open"] or e["first_leg"]]
                     for nm, lv in styles.items()}

    # ── 情绪画像:顶前 90 天 / 30 天 / 顶 / 谷底,跨崩盘取中位 ────────────────────
    vix = load_fred("VIXCLS")
    f_btc = srs(fetch("funding_history",
                      {"symbol": "eq.BTC", "venue": "eq.binance_perp",
                       "order": "funding_time.asc", "select": "funding_time,funding_rate"}),
                "funding_time", "funding_rate", agg="sum")
    fund_ann = to_calendar(f_btc, 5) * 365.0
    senti = {"fng": to_calendar(fng, 7), "vix": to_calendar(vix, 5),
             "btc_funding_annualized": to_calendar(fund_ann, 10)}
    prof = {}
    for nm, lv in senti.items():
        rows = []
        for e in btc_ep:
            pk, tr = e["peak_d"], e["trough_d"]
            s = lv.dropna().sort_index()
            pts = {"peak_d": str(pk.date()), "trough_d": str(tr.date()),
                   "first_leg": e["first_leg"],
                   "d90": _val(s, pk - pd.Timedelta(days=90)), "d30": _val(s, pk - pd.Timedelta(days=30)),
                   "peak": _val(s, pk), "trough": _val(s, tr)}
            rows.append(pts)
        first = [r for r in rows if r["first_leg"]]
        med = lambda rr, k: (float(np.median([r[k] for r in rr if r[k] is not None]))
                             if any(r[k] is not None for r in rr) else None)  # noqa: E731
        prof[nm] = {"per_episode": rows, "median_first_leg": {k: med(first, k) for k in ("d90", "d30", "peak", "trough")},
                    "median_all": {k: med(rows, k) for k in ("d90", "d30", "peak", "trough")}}
    res["sentiment"] = prof

    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("wrote", OUT)
    print("BTC bear episodes:", len(btc_ep), "first_leg:", len(first_peaks),
          "fast crashes:", len(btc_fc))
    for k, v in sign_res.items():
        p = v["primary_90d"]
        print("%-34s n=%-3s skip=%-3s hit=%-6s base=%-6s lift=%-6s pct=%s" % (
            k, p["n_anchors"], p["n_skipped"],
            None if p["hit_rate"] is None else round(p["hit_rate"], 3),
            None if p["base_rate"] is None else round(p["base_rate"], 3),
            None if p["lift"] is None else round(p["lift"], 2),
            None if p["pctile"] is None else round(p["pctile"], 3)))


def _val(s: pd.Series, d: pd.Timestamp):
    s = s[s.index <= d]
    return None if not len(s) else float(s.iloc[-1])


if __name__ == "__main__":
    main()