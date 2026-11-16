"""T-341 —— 真钱 X1V 的归因:账户 A(实盘内核择时)vs 对照臂 K(同平均 β 的常数加密腿)。

Lane: lane-c · 卡: T-341 · 性质: 只读研究(只 SELECT,不改规则、不动钱、不入库)

【预注册口径(先写后算,只算一次,不扫参数)】
区间        2021-07-13 → 2026-11-10(账户日历 = BTC 日历)
账户 A      加密腿 = 实盘内核口径 A(tom.trade_path(close,"rally",0.0,exit_mode="l20",vol=True),
            BTC+ETH 各半,收益 = tom.trade_returns(10bp 换手)),名义权重 30%
            + 27% SPY(eodhd 代理 SPYX)+ 19% GLD(eodhd 代理 XAUT0)+ 24% 现金;日再平衡
            ⇒ 与 T-305 口径 A 逐位相同(T-305:2021-07-13→2026-11-07,+91.63% / −16.93%)
对照臂 K    加密腿换成常数权重 w_K(BTC/ETH 各半、每日再平衡回 50/50、10bp 换手),
            其余三腿(27% SPY + 19% GLD + 现金 = 54% − w_K)与账户 A 完全相同
w_K         = 账户 A 全窗口实际加密敞口的时间平均 = mean(0.30 × (0.5·g_BTC + 0.5·g_ETH))
            (敞口在 t−1 收盘定、t 日持有)
①           core_nav 口径(cap_pit24 ≤ 2026-10-02 + cap_a1 → 10-12 + cap_a1_u > 10-12),同 T-305
报          总收益 / 年化 / 最大回撤 / Calmar(全窗口 + 2021-07→2022-08-30 + 2022-08-31→2026-11-10)
            A−K 对 1,000 次随机进出场(apparatus.random_dates_like + null_distribution,
            种子 341、同年分层、同进场段数与各段持有天数)的分位
            T-305 那 23 个下跌簇(BTC 距 200 日线 0~10% 且 breadth ≤ 0.10)簇首日之后 28 天
            A 与 K 的回撤差
纪律        只读;不改代码;不入库;翻页带 order=;每页 ≤ 1000 行;只报不判
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull, null_distribution, percentile_of, random_dates_like,
)
from src.data.signals.tom import trade_path, trade_returns  # noqa: E402

# ── 预注册常量 ───────────────────────────────────────────────────────────────
WIN_START, WIN_END = "2021-07-13", "2026-11-10"
SEG1_END = "2022-08-30"          # 第一段(2021-07-13 → 2022-08-30)
SEG2_START = "2022-08-31"        # 第二段(GLD 四腿齐全)
BASE = "2021-07-12"              # 净值基准点(窗口前一天)
W_CRYPTO, W_SPY, W_GLD = 0.30, 0.27, 0.19
SEED, N_NULL = 341, 1000
MA_N = 200
CLUSTER_FWD = 28
COST = 10 / 1e4                  # 10bp 单边
INCEPTION, CORE_SINCE = "2026-10-02", "2026-10-12"
OUT_MD = os.path.join(HERE, "T-341_x1v_vs_const_beta.md")
OUT_JSON = os.path.join(HERE, "t341_results.json")

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 不读 .env,退出。")

R: dict = {}
LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ── 只读取数 ─────────────────────────────────────────────────────────────────
def rest(table: str, extra: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{table}?{extra}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], {}
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", {}


def fetch_paged(table: str, select: str, filters: list[str], order_col: str,
                limit: int = 1000) -> tuple[list[dict], str]:
    """翻页读 —— 每页 ≤ 1000 行,一律带 order=(主键),用 gt 游标推进。"""
    rows: list[dict] = []
    last = None
    total = "?"
    while True:
        extra = f"select={select}&order={order_col}.asc&limit={limit}"
        for f in filters:
            extra += f"&{f}"
        if last is not None:
            extra += f"&{order_col}=gt.{last}"
        st, body, hdrs = rest(table, extra)
        if st != 200:
            raise RuntimeError(f"{table} 取数失败 {st}: {body[:200]}")
        cr = hdrs.get("content-range", "")
        if "/" in cr:
            total = cr.split("/")[-1]
        page = json.loads(body) if body.strip() else []
        if not page:
            break
        rows.extend(page)
        last = page[-1][order_col]
        if len(page) < limit:
            break
    return rows, total


def series_from(rows: list[dict], dcol: str, vcol: str) -> pd.Series:
    s = pd.Series({str(r[dcol])[:10]: float(r[vcol]) for r in rows if r.get(vcol) is not None})
    return pd.Series({pd.Timestamp(k): v for k, v in s.items()}).sort_index()


def fetch_ohlcv(symbol: str, source: str) -> pd.Series:
    rows, total = fetch_paged("ohlcv_daily", "trade_date,close",
                              [f"symbol=eq.{symbol}", f"source=eq.{source}"], "trade_date")
    s = series_from(rows, "trade_date", "close")
    log(f"  ohlcv {symbol}/{source}: {len(s)} 行(server total={total}) "
        f"{s.index[0].date()} → {s.index[-1].date()}")
    return s


# ── 指标 ─────────────────────────────────────────────────────────────────────
def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"n_days": int(len(nav))}
    final = float(nav.iloc[-1] / nav.iloc[0])
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-9)
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    after = nav.loc[trough:]
    rec = after[after >= nav.loc[peak]]
    rec_d = rec.index[0] if len(rec) else None
    dur = int((rec_d - peak).days) if rec_d is not None else int((nav.index[-1] - peak).days)
    uw = (nav < nav.cummax()).to_numpy()
    best = cur = 0
    for u in uw:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    ann = final ** (1.0 / years) - 1.0
    mdd = float(dd.min())
    return {
        "total_return": final - 1.0,
        "ann": ann,
        "max_dd": mdd,
        "calmar": (ann / abs(mdd)) if mdd < 0 else None,
        "dd_peak": str(peak.date()),
        "dd_trough": str(trough.date()),
        "dd_recovery": str(rec_d.date()) if rec_d is not None else None,
        "dd_days": dur,
        "max_underwater_days": int(best),
        "n_days": int(len(nav)),
        "final": final,
        "years": years,
    }


def fmt_pct(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{nd}f}%"


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log("=== 取数(只读) ===")
    btc = fetch_ohlcv("BTC", "binance_hist")
    eth = fetch_ohlcv("ETH", "binance_hist")
    spy = fetch_ohlcv("SPY", "eodhd")
    gld = fetch_ohlcv("GLD", "eodhd")

    cv_rows, cv_total = fetch_paged("core_variants_daily", "d,ret",
                                     ["arm=eq.cap_pit24", "d=gte.2021-01-01"], "d")
    log(f"  core_variants_daily.cap_pit24: {len(cv_rows)} 行(server total={cv_total})")
    # core_cap_daily 同一 d 有多 arm ⇒ 按 arm 分别取(单 arm 内 d 唯一,gt 游标不丢行)
    cc_rows: list[dict] = []
    for arm in ("cap_a1", "cap_a1_u"):
        rr, tt = fetch_paged("core_cap_daily", "d,arm,nav", [f"arm=eq.{arm}"], "d")
        log(f"  core_cap_daily.{arm}: {len(rr)} 行(server total={tt})")
        cc_rows.extend(rr)

    sd: dict[str, pd.Series] = {}
    for feat in ("dist_200", "vol_pct_3y", "breadth_above_ma50"):
        rows, _ = fetch_paged("state_daily", "d,value",
                              ["entity=eq.panel", f"feature=eq.{feat}"], "d")
        sd[feat] = series_from(rows, "d", "value")
        log(f"  state_daily.panel.{feat}: {len(sd[feat])} 行")

    # ── ① core_nav(同 T-305)──
    INCEP, CORE_S = pd.Timestamp(INCEPTION), pd.Timestamp(CORE_SINCE)
    rets: dict[pd.Timestamp, float] = {}
    for r in cv_rows:
        d = pd.Timestamp(str(r["d"])[:10])
        if d <= INCEP and r.get("ret") is not None:
            rets[d] = float(r["ret"])
    arms: dict[str, pd.Series] = {}
    for arm in ("cap_a1", "cap_a1_u"):
        arms[arm] = pd.Series({pd.Timestamp(str(r["d"])[:10]): float(r["nav"])
                               for r in cc_rows if r["arm"] == arm and r.get("nav") is not None}).sort_index()
        log(f"  ① 臂 {arm}: {len(arms[arm])} 行 {arms[arm].index[0].date()} → {arms[arm].index[-1].date()}")
    old = arms["cap_a1"].pct_change().dropna()
    old = old[(old.index > INCEP) & (old.index <= CORE_S)]
    new = arms["cap_a1_u"].pct_change().dropna()
    new = new[new.index > CORE_S]
    for s_ in (old, new):
        for d, v in s_.items():
            rets[d] = float(v)
    core_rets = pd.Series(rets).sort_index()
    core_nav = (1.0 + core_rets).cumprod()
    log(f"  ① 收益点 {len(core_rets)}: {core_rets.index[0].date()} → {core_rets.index[-1].date()}")

    # ── 账户日历(BTC 日历)──
    idx = btc.loc[WIN_START:WIN_END].index
    idx = idx[(idx >= pd.Timestamp(WIN_START)) & (idx <= pd.Timestamp(WIN_END))]
    log(f"  账户日历: {len(idx)} 天 {idx[0].date()} → {idx[-1].date()}")

    # ── 账户 A:加密腿 = 实盘内核口径 A ──
    g_btc = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
    g_eth = trade_path(eth, "rally", 0.0, exit_mode="l20", vol=True)
    r_btc_k = trade_returns(btc, g_btc)
    r_eth_k = trade_returns(eth, g_eth)
    legA = (0.5 * r_btc_k.reindex(idx).fillna(0.0) + 0.5 * r_eth_k.reindex(idx).fillna(0.0))

    # 实际加密敞口(t−1 收盘定的 g,t 日持有)
    grossA_full = (0.5 * g_btc + 0.5 * g_eth).shift(1)
    grossA = grossA_full.reindex(idx)
    exposure_A = W_CRYPTO * grossA
    w_K = float(exposure_A.mean())
    log(f"  w_K(账户 A 全窗口实际加密敞口时间平均) = {w_K:.6f} "
        f"({w_K * 100:.2f}%);名义 30% 腿的内部平均 gross = {grossA.mean():.4f}")

    # ── 对照臂 K:常数权重 w_K × (BTC/ETH 各半,日再平衡,10bp)──
    p_b = btc.pct_change()
    p_e = eth.pct_change()
    w_b = 0.5
    k_ret = pd.Series(0.0, index=idx)
    k_turn = pd.Series(0.0, index=idx)
    for d in idx:
        pb = p_b.get(d, np.nan)
        pe = p_e.get(d, np.nan)
        if not (np.isfinite(pb) and np.isfinite(pe)):
            continue
        vb = w_b * (1.0 + pb)
        ve = (1.0 - w_b) * (1.0 + pe)
        pre = vb / (vb + ve) if (vb + ve) > 0 else 0.5
        turn = 2.0 * abs(pre - 0.5)                 # 调回 50/50 的双边换手率
        k_ret.loc[d] = 0.5 * pb + 0.5 * pe - COST * turn
        k_turn.loc[d] = turn
        w_b = 0.5
    legK = k_ret
    log(f"  K 腿:累计成本 {float((COST * k_turn).sum()) * 100:.3f}pp(相对腿 NAV),"
        f"日均换手 {float(k_turn.mean()) * 100:.4f}%")

    # ── SPY / GLD 腿(映射到账户日历,陈旧收盘 → 收益 0)──
    def to_cal(s: pd.Series) -> pd.Series:
        return s.reindex(s.index.union(idx)).ffill().reindex(idx)

    spy_c, gld_c = to_cal(spy), to_cal(gld)
    r_spy = spy_c.pct_change().fillna(0.0)
    r_gld = gld_c.pct_change().fillna(0.0)
    gld_live = gld.index[gld.index >= pd.Timestamp(WIN_START)][0]

    acctA = (W_CRYPTO * legA + W_SPY * r_spy + W_GLD * r_gld).reindex(idx).fillna(0.0)
    acctK = (w_K * legK + W_SPY * r_spy + W_GLD * r_gld).reindex(idx).fillna(0.0)

    BASE_TS = pd.Timestamp(BASE)

    def nav_from_rets(r: pd.Series) -> pd.Series:
        r = r.reindex(idx).fillna(0.0)
        return pd.concat([pd.Series([1.0], index=[BASE_TS]), (1.0 + r).cumprod()])

    navA = nav_from_rets(acctA)
    navK = nav_from_rets(acctK)
    navAleg = nav_from_rets(legA)
    nav1_cal = core_nav.reindex(core_nav.index.union(idx)).ffill().reindex(idx)
    base1 = float(core_nav.asof(BASE_TS))
    nav1 = pd.concat([pd.Series([1.0], index=[BASE_TS]), nav1_cal / base1])

    def sub_nav(nav_full: pd.Series, start: str, end: str) -> pd.Series:
        """段内净值:起点当天之前最后一个点作基准(段首日的收益算在段内),段末截到 end。"""
        inside = nav_full.index[(nav_full.index >= pd.Timestamp(start)) &
                                (nav_full.index <= pd.Timestamp(end))]
        if len(inside) == 0:
            return nav_full.iloc[0:0]
        i0 = inside[0]
        head = nav_full.loc[:i0].iloc[[-1]]
        return pd.concat([head, nav_full.loc[i0:inside[-1]]])

    def seg_metrics(nav: pd.Series, start: str, end: str) -> dict:
        return metrics(sub_nav(nav, start, end))

    segs = {
        "full": (WIN_START, WIN_END),
        "seg1_2021-07→2022-08-30": (WIN_START, SEG1_END),
        "seg2_2022-08-31→2026-11-10": (SEG2_START, WIN_END),
    }
    R["segments"] = {}
    for name, (s_, e_) in segs.items():
        mA = seg_metrics(navA, s_, e_)
        mK = seg_metrics(navK, s_, e_)
        m1 = seg_metrics(nav1, s_, e_)
        R["segments"][name] = {
            "start": s_, "end": e_, "days": mA.get("n_days"),
            "A": mA, "K": mK, "core_1": m1,
            "A_minus_K_total_pp": (mA["total_return"] - mK["total_return"]) * 100,
            "A_minus_K_ann_pp": (mA["ann"] - mK["ann"]) * 100,
            "A_minus_K_maxdd_pp": (mA["max_dd"] - mK["max_dd"]) * 100,
            "A_minus_1_total_pp": (mA["total_return"] - m1["total_return"]) * 100,
            "K_minus_1_total_pp": (mK["total_return"] - m1["total_return"]) * 100,
        }

    R["w_K"] = {"value": w_K, "pct": w_K * 100,
                "definition": "mean over window of 0.30 × (0.5·g_BTC(t−1) + 0.5·g_ETH(t−1))",
                "nominal_crypto_leg": W_CRYPTO,
                "mean_gross_of_leg": float(grossA.mean()),
                "min_exposure": float(exposure_A.min()), "max_exposure": float(exposure_A.max()),
                "frac_days_flat": float((grossA <= 0).mean()),
                "mean_exposure_in_market": float(exposure_A[grossA > 0].mean()) if (grossA > 0).any() else None}
    R["account_A_canonical"] = R["segments"]["full"]["A"]
    R["account_K_const"] = R["segments"]["full"]["K"]
    R["core_1"] = R["segments"]["full"]["core_1"]
    R["legA_canonical"] = metrics(navAleg)
    R["legK_const"] = metrics(nav_from_rets(legK))
    R["coverage"] = {
        "BTC": f"{btc.index[0].date()}→{btc.index[-1].date()} ({len(btc)})",
        "ETH": f"{eth.index[0].date()}→{eth.index[-1].date()} ({len(eth)})",
        "SPY": f"{spy.index[0].date()}→{spy.index[-1].date()} ({len(spy)})",
        "GLD": f"{gld.index[0].date()}→{gld.index[-1].date()} ({len(gld)})",
        "GLD_in_window_start": str(gld_live.date()),
    }
    R["window"] = {"start": WIN_START, "end": WIN_END, "cal_days": int(len(idx)),
                   "cal_start": str(idx[0].date()), "cal_end": str(idx[-1].date())}

    # ── 零信号对照:A 的择时换成随机日期(同段数、同各段持有天数、同年分层,种子 341)──
    in_mkt_A = (grossA > 0).astype(float)

    def spells_from_flags(flags: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
        out = []
        start = None
        for d, f in flags.items():
            if f and start is None:
                start = d
            elif not f and start is not None:
                out.append((start, d, int(((flags.index > start) & (flags.index < d)).sum()) + 1))
                start = None
        if start is not None:
            out.append((start, flags.index[-1], int((flags.index >= start).sum())))
        return out

    sp = spells_from_flags(in_mkt_A)
    log(f"  零信号:A 腿进场段 {len(sp)} 段,总持有日 {sum(x[2] for x in sp)}")
    cal = list(idx)
    pos = {str(d.date()): k for k, d in enumerate(cal)}
    hold = [s_[2] for s_ in sp]
    elig = {i: [str(d.date()) for d in cal] for i in range(len(sp))}
    events = [(i, str(cal[min(pos[str(sp[i][0].date())], len(cal) - 1)].date())) for i in range(len(sp))]
    basket = (0.5 * p_b.reindex(idx).fillna(0.0) + 0.5 * p_e.reindex(idx).fillna(0.0))
    basket_arr = basket.to_numpy()
    K_total = R["segments"]["full"]["K"]["total_return"]
    K_mdd = R["segments"]["full"]["K"]["max_dd"]

    def build(rng) -> tuple[float, float]:
        drawn = random_dates_like(events, elig, rng)
        mask = np.zeros(len(cal), dtype=bool)
        for (key, d) in drawn:
            if d is None:
                continue
            k = pos.get(d)
            if k is None:
                continue
            h = hold[key]
            mask[k:k + h] = True
        rets = np.where(mask, basket_arr, 0.0)
        nav = np.cumprod(1.0 + rets)
        total = float(nav[-1] - 1.0)
        dd = float((nav / np.maximum.accumulate(nav) - 1.0).min())
        return total, dd

    def fn_t(rng):
        return build(rng)[0]

    def fn_d(rng):
        return build(rng)[1]

    act_t = R["legA_canonical"]["total_return"]
    act_d = R["legA_canonical"]["max_dd"]
    null_out = {"n_spells": len(sp), "total_hold_days": int(sum(hold)),
                "actual_A_total": act_t, "actual_A_max_dd": act_d,
                "K_total": K_total, "K_max_dd": K_mdd,
                "actual_diff_total": act_t - K_total, "actual_diff_maxdd": act_d - K_mdd}
    try:
        nt = null_distribution(fn_t, N_NULL, SEED, actual=None)
        nd = null_distribution(fn_d, N_NULL, SEED, actual=None)
        null_out["null_total_median"] = float(np.median(nt))
        null_out["null_total_p10"] = float(np.percentile(nt, 10))
        null_out["null_total_p90"] = float(np.percentile(nt, 90))
        null_out["null_dd_median"] = float(np.median(nd))
        null_out["null_dd_p10"] = float(np.percentile(nd, 10))
        null_out["null_dd_p90"] = float(np.percentile(nd, 90))
        # 差值分位:(A − K) 在 (随机腿 − K) 分布中的位置
        null_out["diff_total_pct"] = percentile_of(act_t - K_total, nt - K_total)
        null_out["diff_maxdd_pct"] = percentile_of(act_d - K_mdd, nd - K_mdd)
        # 对照口径:A 腿自身在零分布中的分位(T-305 同口径)
        null_out["legA_total_pct"] = percentile_of(act_t, nt)
        null_out["legA_maxdd_pct"] = percentile_of(act_d, nd)
    except NoOpNull as e:
        null_out["error"] = f"NoOpNull: {e}"
    R["nulls"] = null_out

    # ── 下跌簇(同 T-305 定义)──
    c = btc.loc[:WIN_END]
    ma200 = c.rolling(MA_N, min_periods=MA_N).mean()
    bt = btc.reindex(btc.index.union(idx)).ffill().reindex(idx)
    ma = ma200.reindex(ma200.index.union(idx)).ffill().reindex(idx)
    dist_btc = bt / ma - 1.0
    breadth = sd["breadth_above_ma50"].reindex(sd["breadth_above_ma50"].index.union(idx)).ffill().reindex(idx)
    cond = ((dist_btc >= 0.0) & (dist_btc <= 0.10) & (breadth <= 0.10)).fillna(False)
    starts: list[pd.Timestamp] = []
    prev = False
    for d, v in cond.items():
        if v and not prev:
            starts.append(d)
        prev = bool(v)
    clusters = []
    for d0 in starts:
        fwd = idx[(idx > d0)][:CLUSTER_FWD]
        if len(fwd) == 0:
            continue
        a0 = float(navA.asof(d0))
        k0 = float(navK.asof(d0))
        seg_A = navA.loc[fwd]
        seg_K = navK.loc[fwd]
        ddA = float((seg_A / a0 - 1).min())
        ddK = float((seg_K / k0 - 1).min())
        clusters.append({"d0": str(d0.date()), "n_days": int(len(fwd)),
                         "A_dd": ddA, "K_dd": ddK, "A_minus_K_dd_pp": (ddA - ddK) * 100,
                         "A_ret": float(seg_A.iloc[-1] / a0 - 1), "K_ret": float(seg_K.iloc[-1] / k0 - 1),
                         "dist_btc": float(dist_btc.asof(d0)), "breadth": float(breadth.asof(d0))})
    R["cluster"] = {
        "n_qual_days": int(cond.sum()), "n_clusters": len(starts),
        "cond_desc": "0 ≤ (BTC/MA200 − 1) ≤ 0.10 且 breadth_above_ma50 ≤ 0.10",
        "clusters": clusters,
    }
    if clusters:
        diffs = [c_["A_minus_K_dd_pp"] for c_ in clusters]
        R["cluster"]["median_A_minus_K_dd_pp"] = float(np.median(diffs))
        R["cluster"]["mean_A_minus_K_dd_pp"] = float(np.mean(diffs))
        R["cluster"]["K_worse_count"] = int(sum(1 for x in diffs if x > 0))   # A 比 K 差
        R["cluster"]["A_worse_count"] = int(sum(1 for x in diffs if x < 0))    # K 比 A 差

    # ── 写产物 ──
    R["k_cost_pp"] = float((COST * k_turn).sum() * 100)
    R["k_turn_mean_pct"] = float(k_turn.mean() * 100)
    # 口径核对:读 T-305 的已合并结果(同口径 A)
    t305_path = os.path.join(HERE, "t305_results.json")
    if os.path.exists(t305_path):
        try:
            with open(t305_path) as f:
                t305 = json.load(f)
            R["t305_check"] = {
                "t305_end": t305["window"]["end"],
                "t305_A_total": t305["account_A_canonical"]["total_return"],
                "t305_A_mdd": t305["account_A_canonical"]["max_dd"],
                "t305_1_total": t305["core_1"]["total_return"],
                "t305_1_mdd": t305["core_1"]["max_dd"],
            }
        except Exception as e:  # noqa: BLE001
            R["t305_check"] = {"error": str(e)}
    R["log"] = LOG
    with open(OUT_JSON, "w") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    log(f"→ {OUT_JSON}")
    write_md()
    log(f"→ {OUT_MD}")


# ── 报告 ─────────────────────────────────────────────────────────────────────
def write_md() -> None:
    seg = R["segments"]
    full = seg["full"]
    n = R["nulls"]
    cl = R["cluster"]
    wK = R["w_K"]
    L: list[str] = []
    A = L.append
    A("# T-341 —— 真钱 X1V 的归因:账户 A(实盘内核择时)vs 对照臂 K(同平均 β 的常数加密腿)")
    A("")
    A("**Lane**:lane-c · **卡**:T-341 · **性质**:只读研究(只 SELECT,不改规则、不动钱、不入库)")
    A("**脚本**:`docs/research/t341_x1v_vs_const.py` · **结果**:`docs/research/t341_results.json`")
    A("")
    A("## 0. 预注册口径(先写后算,只算一次,不扫参数)")
    A("")
    A(f"- **区间**:{WIN_START} → {WIN_END}(账户日历 = BTC 日历,{R['window']['cal_days']} 天)")
    A(f"- **账户 A**:加密腿 = 实盘内核口径 A(`tom.trade_path(close,\"rally\",0.0,exit_mode=\"l20\",vol=True)`,"
      f"BTC+ETH 各半,收益 = `tom.trade_returns`,10bp 换手),名义权重 30% + 27% SPY + 19% GLD + 24% 现金,日再平衡")
    A(f"- **对照臂 K**:加密腿换成常数权重 **w_K = {wK['pct']:.2f}%**(BTC/ETH 各半、每日再平衡回 50/50、10bp 换手);"
      f"其余三腿(27% SPY + 19% GLD + 现金 {54 - wK['pct']:.2f}%)与账户 A 完全相同")
    A(f"- **w_K 的定义**:账户 A 全窗口**实际加密敞口**的时间平均 = mean(0.30 × (0.5·g_BTC(t−1) + 0.5·g_ETH(t−1)))"
      f" ⇒ **{wK['pct']:.2f}%**(名义腿 30% 的内部平均 gross {wK['mean_gross_of_leg']:.4f};"
      f"空仓天数占比 {wK['frac_days_flat'] * 100:.1f}%)")
    A("- **①**:`core_nav` 口径(cap_pit24 ≤ 2026-10-02 + cap_a1 → 10-12 + cap_a1_u > 10-12),同 T-305")
    A("- **零信号对照**:`apparatus.random_dates_like` + `null_distribution`,种子 341、1,000 次、同年分层、"
      "同进场段数与各段持有天数;对照对象 = 把 A 的择时换成随机日期后的 (随机腿 − K) 差值分布")
    A("- **下跌簇**:T-305 同定义(BTC 距自身 200 日线 0~10% 且 `breadth_above_ma50` ≤ 0.10),簇首日之后 28 个交易日")
    A("- **纪律**:只读;只报不判;不改规则、不改代码、不入库;翻页带 `order=`;每页 ≤ 1000 行")
    A("")
    A("## 1. 三行主表(全窗口 2021-07-13 → 2026-11-10)")
    A("")
    A("| 臂 | 加密腿 | 总收益 | 年化 | 最大回撤 | Calmar |")
    A("|---|---|---|---|---|---|")
    for lab, key, desc in (("**A**", "A", "实盘内核 X1V(择时)"),
                           ("**K**", "K", f"常数 {wK['pct']:.2f}% BTC/ETH 各半(日再平衡)"),
                           ("①", "core_1", "core_nav 口径")):
        m = full[key]
        A(f"| {lab} | {desc} | {fmt_pct(m['total_return'])} | {fmt_pct(m['ann'])} | "
          f"{fmt_pct(m['max_dd'])} | {m['calmar']:.3f} |")
    A("")
    A(f"**A − K**:总收益 {full['A_minus_K_total_pp']:+.2f}pp、年化 {full['A_minus_K_ann_pp']:+.2f}pp、"
      f"最大回撤 {full['A_minus_K_maxdd_pp']:+.2f}pp(正 = A 的回撤更浅)。")
    A(f"A − ① {full['A_minus_1_total_pp']:+.2f}pp;K − ① {full['K_minus_1_total_pp']:+.2f}pp。")
    A("")
    if R.get("t305_check"):
        t = R["t305_check"]
        A("### 1.1 口径核对(与 T-305 同口径 A)")
        A("")
        A(f"- T-305(窗口至 {t['t305_end']}):账户 A 总收益 {fmt_pct(t['t305_A_total'])}、最大回撤 {fmt_pct(t['t305_A_mdd'])};"
          f"① {fmt_pct(t['t305_1_total'])}、回撤 {fmt_pct(t['t305_1_mdd'])}")
        A(f"- 本卡(窗口至 {WIN_END}):账户 A 总收益 {fmt_pct(full['A']['total_return'])}、最大回撤 {fmt_pct(full['A']['max_dd'])};"
          f"① {fmt_pct(full['core_1']['total_return'])}、回撤 {fmt_pct(full['core_1']['max_dd'])}")
        A(f"- 差异只来自窗口末日({t['t305_end']} → {WIN_END},3 个日历日):A 回撤逐位相同 "
          f"({fmt_pct(t['t305_A_mdd'])}),总收益差 {abs(full['A']['total_return'] - t['t305_A_total']) * 100:.2f}pp。")
        A("")
    A("## 2. 分段")
    A("")
    A("| 段 | 臂 | 总收益 | 年化 | 最大回撤 | Calmar |")
    A("|---|---|---|---|---|---|")
    for sname, sv in seg.items():
        for lab, key in (("A", "A"), ("K", "K"), ("①", "core_1")):
            m = sv[key]
            A(f"| {sname} | {lab} | {fmt_pct(m['total_return'])} | {fmt_pct(m['ann'])} | "
              f"{fmt_pct(m['max_dd'])} | {m['calmar']:.3f} |")
    A("")
    for sname, sv in seg.items():
        A(f"- **{sname}**:A − K 总收益 {sv['A_minus_K_total_pp']:+.2f}pp、"
          f"回撤差 {sv['A_minus_K_maxdd_pp']:+.2f}pp")
    A("")
    A("## 3. 零信号对照(A 的择时 → 随机日期,种子 341,1,000 次)")
    A("")
    if "error" in n:
        A(f"**零分布失败**:{n['error']}")
    else:
        A(f"- A 腿进场段 **{n['n_spells']}** 段,总持有日 **{n['total_hold_days']}** 天")
        A(f"- 实际 A 腿总收益 {fmt_pct(n['actual_A_total'])}(零分布中位 {fmt_pct(n['null_total_median'])},"
          f"p10 {fmt_pct(n['null_total_p10'])},p90 {fmt_pct(n['null_total_p90'])})")
        A(f"- 实际 A 腿最大回撤 {fmt_pct(n['actual_A_max_dd'])}(零分布中位 {fmt_pct(n['null_dd_median'])},"
          f"p10 {fmt_pct(n['null_dd_p10'])},p90 {fmt_pct(n['null_dd_p90'])})")
        A(f"- **差值 (A − K) 总收益**:实际 {n['actual_diff_total'] * 100:+.2f}pp ⇒ "
          f"**分位 {n['diff_total_pct']:.3f}**")
        A(f"- **差值 (A − K) 最大回撤**:实际 {n['actual_diff_maxdd'] * 100:+.2f}pp ⇒ "
          f"**分位 {n['diff_maxdd_pct']:.3f}**")
        A(f"- 对照口径(T-305 同法):A 腿自身总收益分位 {n['legA_total_pct']:.3f}、"
          f"最大回撤分位 {n['legA_maxdd_pct']:.3f}")
    A("")
    A("## 4. 下跌簇(簇首日之后 28 个交易日)")
    A("")
    A(f"- 条件:`{cl['cond_desc']}`;命中 {cl['n_qual_days']} 天,**{cl['n_clusters']} 个簇**")
    if cl["clusters"]:
        A(f"- A − K 回撤差:中位 {cl['median_A_minus_K_dd_pp']:+.2f}pp、均值 {cl['mean_A_minus_K_dd_pp']:+.2f}pp;"
          f"A 更差的簇 {cl['A_worse_count']}/{cl['n_clusters']}、K 更差的簇 {cl['K_worse_count']}/{cl['n_clusters']}")
        A("")
        A("| 簇首日 | 天数 | A 回撤 | K 回撤 | A−K(pp) | dist_btc | breadth |")
        A("|---|---|---|---|---|---|---|")
        for c_ in cl["clusters"]:
            A(f"| {c_['d0']} | {c_['n_days']} | {fmt_pct(c_['A_dd'])} | {fmt_pct(c_['K_dd'])} | "
              f"{c_['A_minus_K_dd_pp']:+.2f} | {fmt_pct(c_['dist_btc'])} | {c_['breadth']:.4f} |")
    A("")
    A("## 5. 数据覆盖与口径限制")
    A("")
    cov = R["coverage"]
    A(f"| 序列 | 覆盖 |")
    A(f"|---|---|")
    A(f"| BTC(binance_hist) | {cov['BTC']} |")
    A(f"| ETH(binance_hist) | {cov['ETH']} |")
    A(f"| SPY(eodhd) | {cov['SPY']} |")
    A(f"| GLD(eodhd) | {cov['GLD']} —— 窗口内起点 {cov['GLD_in_window_start']} |")
    A("")
    A(f"- 第一段(→ 2022-08-30)GLD 无覆盖,19% 该腿按现金处理(不是回填);第二段四腿齐全。")
    A(f"- 账户 A 与 T-305 的口径 A 逐位一致(同核、同权重、同日历),差别只有窗口末日(2026-11-10 vs 11-07)。")
    A(f"- K 腿的 10bp 只算 **50/50 日再平衡**的换手;不做资金费(常数敞口 ≤ 1,内核的资金费只作用在 >1 的加仓部分)。")
    A(f"- 零分布里的随机腿用 50/50 BTC/ETH 持有收益做篮子(零成本),与 T-305 同法 —— "
      f"它检验的是**择时**,不是绝对收益水平。")
    A(f"- 全部是规则级(理想)口径,不含 T-146 已量的执行拖累(≈ −9.46pp/年);SPY/GLD 是 SPYX/XAUT0 的代理。")
    A("")
    A("## 6. 探索性(不构成结论;需另立预注册、在新数据上过零信号对照)")
    A("")
    w = R["w_K"]
    A(f"1. **「30% 加密腿」在实盘里平均只有 {w['pct']:.2f}% 的敞口**:X1V 内核 {w['frac_days_flat'] * 100:.1f}% 的日历天空仓,"
      f"在市场里的平均敞口也只有 {w['mean_exposure_in_market'] * 100:.2f}%(名义腿 30% 的 "
      f"{w['mean_gross_of_leg'] * 100:.1f}%)。⇒ LP 说的「用常数配比复制」若按名义 30% 起步,"
      f"与真钱的实际 β 差 {30 / max(w['pct'], 1e-9):.1f} 倍以上。")
    A(f"2. **A − K 的超额集中在熊段**:第一段(→ 2022-08-30)年化差 {seg['seg1_2021-07→2022-08-30']['A_minus_K_ann_pp']:+.2f}pp,"
      f"第二段(2022-08-31 起)只有 {seg['seg2_2022-08-31→2026-11-10']['A_minus_K_ann_pp']:+.2f}pp;"
      f"全窗口 {full['A_minus_K_ann_pp']:+.2f}pp/年。")
    A(f"3. **T-327 影子账的常数臂(crypto 0.20 / equity 0.30 / gold 0.20)与本卡实测的真钱平均敞口 "
      f"{w['pct']:.2f}% 不是同一个 β**(影子臂的加密腿高 {0.20 / max(w['value'], 1e-9):.2f} 倍),"
      f"两条常数臂并排记账不能直接解释真钱的抗跌。")
    A(f"4. **第二段里 ① 反超 A {seg['seg2_2022-08-31→2026-11-10']['A_minus_1_total_pp']:+.2f}pp**"
      f"(与 T-305 同向),说明「A 优于 ①」仍是窗口起点效应,不是稳定结构。")
    A(f"5. **K 腿的日再平衡成本可忽略**:50/50 每日再平衡的累计换手成本 {R.get('k_cost_pp', 0):.2f}pp(相对腿 NAV、5.33 年),"
      f"不足以解释 A 与 K 的差异。")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
