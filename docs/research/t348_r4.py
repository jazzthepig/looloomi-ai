"""T-348 第四轮(lane-c,2026-11-12):只做 S-681 H4 一族 —— ① 长账本(2020-08-16 起)两窗口并排 ② 零分布。

① 长账本:基准账本从 2021-10-11 往前延到 2020-08-16(R-v2 用 t353_engine 的曲线、腿全部从库里重取、
   现金利率 2023-02-10 之前记 0),报 C0 与 C0+H4 的年化 / 最长水下 / 最大回撤 / 逐年,两个窗口并排
   (A = 2020-08-16 起,B = 2021-10-11 起)。
② 零分布:把 H4 族的逐日收益序列用 `src.data.evaluation.apparatus.circular_shift`(block 1)整体平移
   500 次(seed 348)后再叠到 C0 上,统计量 = 账户最长水下的缩短天数 + 年化差,各给 apparatus.p_upper。

用法: python3 t348_r4.py [--quick]   (--quick: 零分布只抽 20 次,用于冒烟)
产物: t348_r4_results.json + _t348_r4_tables.md + t348_r4_legs.csv(腿缓存)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO_ROOT)

from src.data.universe import flex_alloc as fa  # noqa: E402
from src.data.signals.tom import trade_path, trade_returns  # noqa: E402
from src.data.evaluation import apparatus  # noqa: E402

import t348_graveyard as G  # noqa: E402
import t348_r3 as R3  # noqa: E402

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

LONG_START = "2020-08-16"
WIN_B = "2021-10-11"
WIN_END = "2026-10-30"
CORE_SPLICE = "2021-07-13"        # 长账本的 crypto 腿从这天起换官方腿的逐日收益
FETCH_START = "2019-01-01"        # tom 核 200 日 warm-up 的起点
CASH_ZERO_BEFORE = "2023-02-10"  # stable_lend_apy_7d 在这天之前没有 ⇒ 记 0
N_NULL = 500
NULL_SEED = 348
NULL_BLOCK = 1

LEGS_CACHE = os.path.join(HERE, "t348_r4_legs.csv")
OUT_JSON = os.path.join(HERE, "t348_r4_results.json")
OUT_MD = os.path.join(HERE, "_t348_r4_tables.md")
FAM_CACHE = os.path.join(HERE, "t348_r3_families.csv")
FAM_META = os.path.join(HERE, "t348_r3_families_meta.json")

WINDOWS = (("A_long_2020-08-16", LONG_START), ("B_2021-10-11", WIN_B))


def log(msg: str) -> None:
    print(str(msg), flush=True)


# ── 只读取数(每页 ≤ 1000 行;一律带 order=)────────────────────────────────
def rest(table: str, params: list[tuple[str, str]]) -> list:
    url = f"{URL}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else []


def fetch_paged(table: str, select: str, filters: list[tuple[str, str]], order_col: str) -> list[dict]:
    out: list[dict] = []
    off = 0
    while True:
        params = list(filters) + [("select", select), ("order", f"{order_col}.asc"),
                                  ("limit", "1000"), ("offset", str(off))]
        rows = rest(table, params)
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
        if off > 80000:
            break
    log(f"  {table}: {len(out)} 行")
    return out


def fetch_series(table: str, select: str, filters: list[tuple[str, str]],
                 dcol: str, vcol: str) -> pd.Series:
    rows = fetch_paged(table, select, filters, dcol)
    s = pd.Series({pd.Timestamp(str(r[dcol])[:10]): float(r[vcol])
                   for r in rows if r.get(vcol) is not None}, dtype=float)
    return s.sort_index()


# ── 腿(全部从库里重取)────────────────────────────────────────────────────
def build_legs() -> tuple[dict, pd.Series, dict]:
    log("=== 取数(长账本的腿) ===")
    # ① core = core_variants_daily 的 cap_pit24 单臂(S-799 的同一条),用表里的 nav 列
    cv = fetch_paged("core_variants_daily", "d,nav",
                     [("arm", "eq.cap_pit24"), ("d", f"gte.{FETCH_START}"), ("d", f"lte.{WIN_END}")], "d")
    core_map = {pd.Timestamp(str(r["d"])[:10]): float(r["nav"])
                for r in cv if r.get("nav") is not None}
    core = pd.Series(core_map, dtype=float).sort_index()
    core = core.reindex(pd.date_range(core.index[0], core.index[-1], freq="D")).ffill().bfill()
    log(f"  ① core nav:{len(core)} 天 {core.index[0].date()} → {core.index[-1].date()}")

    # 资金费(BTC/binance_perp)→ 年化(多头超过 1 的那部分付资金费)
    fr = fetch_paged("funding_history", "funding_time,funding_rate",
                     [("venue", "eq.binance_perp"), ("symbol", "eq.BTC"),
                      ("funding_time", f"gte.{FETCH_START}"), ("funding_time", f"lte.{WIN_END}")],
                     "funding_time")
    fdf = pd.DataFrame(fr)
    fund = pd.Series(dtype=float)
    if len(fdf):
        fdf["d"] = pd.to_datetime(fdf["funding_time"].astype(str).str[:10])
        fund = fdf.groupby("d")["funding_rate"].sum().astype(float) * 365.0
    log(f"  资金费 BTC:{len(fund)} 天" + (f" {fund.index[0].date()} → {fund.index[-1].date()}" if len(fund) else ""))

    # crypto 腿 = tom 核(TOM_ARMS['CORE_X1V'] = ('CORE','rally',0.0,'l20',True))作用于 core nav
    g = trade_path(core, "rally", 0.0, "l20", True)
    r = trade_returns(core, g, fund if len(fund) else None).dropna()
    crypto = (1.0 + r).cumprod()
    crypto.index.name = "d"
    log(f"  crypto 腿(重建):{len(crypto)} 天 {crypto.index[0].date()} → {crypto.index[-1].date()}"
        f" · 终值 {float(crypto.iloc[-1]):.4f}")

    # 尺度不变性自检:核的规则全是相对比较(MA / 前高前低 / 比值)⇒ 换个水平不该改路径
    k = float(core.iloc[-1])
    g2 = trade_path(core / k, "rally", 0.0, "l20", True)
    scale_diff = float((g - g2).abs().max())
    log(f"  尺度不变性自检(核除以 {k:.4f} 再跑):|Δg|max = {scale_diff:.2e}")

    # 股 / 金(eodhd 日收盘,只有工作日)
    equity = fetch_series("ohlcv_daily", "trade_date,close",
                          [("symbol", "eq.ACWI"), ("source", "eq.eodhd"),
                           ("trade_date", f"gte.{FETCH_START}"), ("trade_date", f"lte.{WIN_END}")],
                          "trade_date", "close")
    gold = fetch_series("ohlcv_daily", "trade_date,close",
                        [("symbol", "eq.XAUUSD"), ("source", "eq.eodhd"),
                         ("trade_date", f"gte.{FETCH_START}"), ("trade_date", f"lte.{WIN_END}")],
                        "trade_date", "close")
    log(f"  股 ACWI:{len(equity)} 天 {equity.index[0].date()} → {equity.index[-1].date()}")
    log(f"  金 XAUUSD:{len(gold)} 天 {gold.index[0].date()} → {gold.index[-1].date()}")

    # 拼接:{CORE_SPLICE} 起换官方 crypto 腿的逐日收益(t342_daily.csv)⇒ 窗口 B 与 ① 逐位可比
    # ⚠️ 链必须接在**上一个官方工作日**上(不是上一个日历日):官方腿只有工作日,接日历日会把
    #    周末的重建腿值混进链里(第四轮首跑实测逐日收益最大差 0.24)。
    daily = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    off_nav = daily["crypto_leg_nav_x1v"].astype(float)
    crypto = crypto.copy()
    prev = None
    prev_level = None
    n_spliced = 0
    for d, v in off_nav.items():
        if d < pd.Timestamp(CORE_SPLICE):
            continue
        ret = 0.0 if prev is None else float(off_nav[d] / off_nav[prev] - 1.0)
        if prev_level is None:
            prev_cal = d - pd.Timedelta(days=1)
            base_lvl = float(crypto.loc[prev_cal]) if prev_cal in crypto.index else float(crypto.iloc[0])
        else:
            base_lvl = prev_level
        new_lvl = base_lvl * (1.0 + ret)
        crypto[d] = new_lvl
        prev_level = new_lvl
        prev = d
        n_spliced += 1
    crypto = crypto.sort_index()
    log(f"  拼接:{CORE_SPLICE} 起换官方 crypto 腿收益({n_spliced} 天)")

    # 自检:拼接段与官方 crypto 腿逐位一致(收益口径)
    bd = sorted(set(d for d in off_nav.index if d >= pd.Timestamp(CORE_SPLICE)))
    my = pd.Series({d: float(crypto.loc[d]) for d in bd})
    off = off_nav.loc[bd]
    mine_ret = my.pct_change()
    off_ret = off.pct_change()
    splice_diff = float((mine_ret.fillna(0.0) - off_ret.fillna(0.0)).abs().max())
    log(f"  拼接自检:与官方 crypto 腿逐日收益最大差 {splice_diff:.2e}")

    # 现金利率 = feature_matrix_daily 的 stable_lend_apy_7d ÷ 100 ÷ 365;2023-02-10 之前记 0
    fm = fetch_paged("feature_matrix_daily", "d,f",
                     [("d", f"gte.{FETCH_START}"), ("d", f"lte.{WIN_END}")], "d")
    apy: dict[str, float] = {}
    for r_ in fm:
        f = r_.get("f") or {}
        if isinstance(f, dict) and f.get("stable_lend_apy_7d") is not None:
            apy[str(r_["d"])[:10]] = float(f["stable_lend_apy_7d"])
    cal = pd.date_range(pd.Timestamp(LONG_START), pd.Timestamp(WIN_END), freq="D")
    cash = pd.Series({d: (float(apy[str(d.date())]) / 100.0 / 365.0
                           if str(d.date()) in apy and str(d.date()) >= CASH_ZERO_BEFORE else 0.0)
                      for d in cal}, dtype=float)
    n_zero = int((cash == 0).sum())
    log(f"  现金利率 stable_lend_apy_7d 非空 {len(apy)}/{len(fm)} 天"
        f" · 记 0 的日 {n_zero}({CASH_ZERO_BEFORE} 之前一律 0)")

    legs = {"crypto": crypto, "equity": equity, "gold": gold}
    info = {"core_rows": len(cv), "core_d0": str(core.index[0].date()), "core_d1": str(core.index[-1].date()),
            "fund_rows": len(fr), "fm_rows": len(fm), "apy_days": len(apy),
            "crypto_spliced_days": n_spliced, "scale_invariance_max_diff": scale_diff,
            "splice_max_ret_diff": splice_diff,
            "cash_zero_days": n_zero, "equity_days": len(equity), "gold_days": len(gold)}
    return legs, cash, info


def splice_check(crypto: pd.Series) -> float:
    """拼接段与官方 crypto 腿逐位一致?返回逐日收益最大差。"""
    daily = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    off_nav = daily["crypto_leg_nav_x1v"].astype(float)
    bd = sorted(set(d for d in off_nav.index if d >= pd.Timestamp(CORE_SPLICE)))
    my = pd.Series({d: float(crypto.loc[d]) for d in bd})
    mine_ret = my.pct_change().fillna(0.0)
    off_ret = off_nav.loc[bd].pct_change().fillna(0.0)
    return float((mine_ret - off_ret).abs().max())


def load_or_build_legs() -> tuple[dict, pd.Series, dict]:
    if os.path.exists(LEGS_CACHE):
        df = pd.read_csv(LEGS_CACHE, parse_dates=["d"]).set_index("d")
        legs = {"crypto": df["crypto_nav"].astype(float),
                "equity": df["equity_close"].astype(float),
                "gold": df["gold_close"].astype(float)}
        cash = df["cash_daily_rate"].astype(float)
        sd = splice_check(legs["crypto"])
        log(f"=== 腿(缓存):{LEGS_CACHE} · {len(df)} 行 · 拼接自检 {sd:.2e} ===")
        return legs, cash, {"from_cache": True, "splice_max_ret_diff": sd}
    return build_legs()


def save_legs_cache(legs: dict, cash: pd.Series) -> None:
    df = pd.concat({"crypto_nav": legs["crypto"], "equity_close": legs["equity"],
                    "gold_close": legs["gold"], "cash_daily_rate": cash}, axis=1)
    df.to_csv(LEGS_CACHE, index_label="d")
    log(f"  → 腿缓存 {LEGS_CACHE}({len(df)} 行)")


# ── 长账本 C0 ─────────────────────────────────────────────────────────────
def build_base(legs: dict, cash: pd.Series) -> dict:
    rv2 = R3.rv2_curve().pct_change().dropna()
    nav, lg = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                 start=pd.Timestamp(LONG_START), overlay_ret=rv2, cash_ret=cash)
    nav = nav[nav.index <= pd.Timestamp(WIN_END)]
    log(f"  长账本 C0:{len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" · 终值 {float(nav.iloc[-1]):.4f} · 调仓 {len(lg)} 次")
    cal = pd.date_range(pd.Timestamp(LONG_START), pd.Timestamp(WIN_END), freq="D")
    return {"legs": legs, "cash": cash, "rv2": rv2, "nav": nav, "cal_idx": cal,
            "log": lg, "start": LONG_START, "end": WIN_END}


def official_base(rv2: pd.Series) -> pd.Series:
    """① 的官方 C0(2021-10-11 起,腿 = t342_daily.csv)—— 长账本窗口 B 的对账参照。"""
    daily = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    cal = pd.date_range(daily.index[0], daily.index[-1], freq="D")
    cash = daily["cash_daily_rate"].astype(float).reindex(cal).ffill().fillna(0.0)
    legs = {"crypto": daily["crypto_leg_nav_x1v"].astype(float),
            "equity": daily["equity_close_acwi"].astype(float),
            "gold": daily["gold_close_xauusd"].astype(float)}
    nav, _ = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                start=pd.Timestamp(WIN_B), overlay_ret=rv2, cash_ret=cash)
    return nav[nav.index <= pd.Timestamp(WIN_END)]


def load_family(key: str) -> dict:
    df = pd.read_csv(FAM_CACHE, parse_dates=["d"])
    meta = json.load(open(FAM_META))
    nav = df[df["family"] == key].set_index("d")["nav"].astype(float)
    return {"nav": nav, **meta[key]}


def window_stats(base_nav: pd.Series, arm_nav: pd.Series, wstart: str) -> dict:
    c0 = R3.slice_win(base_nav, wstart, WIN_END)
    c0f = R3.slice_win(arm_nav, wstart, WIN_END)
    m0, mf = G.metrics(c0), G.metrics(c0f)
    u0, uf = G.underwater(c0), G.underwater(c0f)
    return {
        "start": wstart, "end": WIN_END,
        "C0": {"metrics": m0, "underwater": u0, "yearly": G.yearly(c0),
               "underwater_S829": R3.recovery_s829(c0)},
        "C0_plus_family": {"metrics": mf, "underwater": uf, "yearly": G.yearly(c0f),
                           "underwater_S829": R3.recovery_s829(c0f)},
        "diff": {
            "cagr_pp": 100.0 * (mf["cagr"] - m0["cagr"]),
            "max_dd_pp": 100.0 * (mf["max_dd"] - m0["max_dd"]),
            "total_return_pp": 100.0 * (mf["total_return"] - m0["total_return"]),
            "underwater_days": (uf.get("length_d") or 0) - (u0.get("length_d") or 0),
            "underwater_days_S829": (R3.recovery_s829(c0f)["longest_uw_d"]
                                     - R3.recovery_s829(c0)["longest_uw_d"]),
            "cagr_not_lower": bool(mf["cagr"] >= m0["cagr"]),
            "underwater_shorter": bool((uf.get("length_d") or 0) < (u0.get("length_d") or 0)),
        },
    }


# ── 零分布(circular_shift)────────────────────────────────────────────────
class ArmMemo:
    """平移后的族收益 → 叠加臂净值。平移序列相同就复用(4 个统计量共用同一批抽样)。"""

    def __init__(self, base: dict, cal: pd.DatetimeIndex):
        self.base = base
        self.cal = cal
        self.memo: dict[bytes, pd.Series] = {}

    def nav(self, values: np.ndarray) -> pd.Series:
        key = hashlib.blake2b(np.ascontiguousarray(values).tobytes(), digest_size=16).digest()
        if key not in self.memo:
            fr = pd.Series(values, index=self.cal, dtype=float)
            self.memo[key] = R3.arm_with_family(self.base, fr)
        return self.memo[key]


def main() -> None:
    quick = "--quick" in sys.argv
    n_null = 20 if quick else N_NULL
    log(f"=== T-348 第四轮(H4 族)· 零分布 {n_null} 次 · seed {NULL_SEED} · block {NULL_BLOCK} ===")

    legs, cash, info = load_or_build_legs()
    if not info.get("from_cache"):
        save_legs_cache(legs, cash)
    base = build_base(legs, cash)
    cal = base["cal_idx"]

    # ① 长账本:两窗口并排
    fam = load_family("S681_H4")
    fam_ret = R3.fam_return_series(fam["nav"], cal)
    arm = R3.arm_with_family(base, fam_ret)
    fam_vals = fam_ret.reindex(cal).fillna(0.0).to_numpy(dtype=float)
    log(f"  H4 族:{len(fam['nav'])} 天 {fam['nav'].index[0].date()} → {fam['nav'].index[-1].date()}"
        f" · 票 {fam.get('n_tickets')} · f {fam.get('risk_frac')} · cap {fam.get('cap')}")

    res: dict = {"card": "T-348", "part": "第四轮:只做 S-681 H4 —— ① 长账本两窗口并排 ② 零分布",
                 "generated": "lane-c 2026-11-12",
                 "spec": {"ledger_start": LONG_START, "window_B": WIN_B, "end": WIN_END,
                          "core_fetch_start": FETCH_START, "core_splice": CORE_SPLICE,
                          "cash_zero_before": CASH_ZERO_BEFORE,
                          "rv2_engine": "docs/research/t353_engine.py(f 0.005 / cap 0.40 / 名额 14 / exits_first / marked)",
                          "kernel": "src/data.universe.flex_alloc.dynamic_mix_nav(reb 21 / cost 20bp / rb_weights)",
                          "null": {"fn": "src.data.evaluation.apparatus.circular_shift",
                                   "block": NULL_BLOCK, "n": n_null, "seed": NULL_SEED},
                          "family": "S-681 H4(熊市反弹失败),票与规则一字不动"},
                 "data": info, "base_long": {}, "family": {}, "null": {}, "checks": {}}

    m_long = G.metrics(base["nav"])
    rec_long = R3.recovery_s829(base["nav"])
    res["base_long"] = {"C0_cagr": m_long["cagr"], "C0_total_return": m_long["total_return"],
                        "C0_max_dd": m_long["max_dd"], "C0_uw_G": G.underwater(base["nav"]),
                        "C0_uw_S829": rec_long, "n_days": m_long["n_days"],
                        "d0": m_long["d0"], "d1": m_long["d1"]}
    log(f"  长账本 C0:年化 {m_long['cagr']:+.4%} · 总收益 {m_long['total_return']:+.4%}"
        f" · 最长水下 {rec_long['longest_uw_d']} 日(S-829)/ {G.underwater(base['nav']).get('length_d')} 日(G)"
        f" · 最大回撤 {m_long['max_dd']:+.4%}")

    # 对账:窗口 B 的长账本 C0 vs ① 的官方 C0(腿一致,只差调仓相位)
    nav_off = official_base(base["rv2"])
    bo = R3.slice_win(nav_off, WIN_B, WIN_END)
    bl = R3.slice_win(base["nav"], WIN_B, WIN_END)
    # 归因:同一套长腿、但从 2021-10-11 起记 ⇒ 若与 ① 逐位一致,则残差纯是「从 2020-08-16 起数 21 日」的调仓相位
    nav_same_legs, _ = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                          start=pd.Timestamp(WIN_B), overlay_ret=base["rv2"],
                                          cash_ret=cash)
    nav_same_legs = nav_same_legs[nav_same_legs.index <= pd.Timestamp(WIN_END)]
    bs = R3.slice_win(nav_same_legs, WIN_B, WIN_END)
    res["checks"]["windowB_vs_official"] = {
        "long": {"cagr": G.metrics(bl)["cagr"], "uw_G": G.underwater(bl).get("length_d"),
                 "uw_S829": R3.recovery_s829(bl)["longest_uw_d"], "mdd": G.metrics(bl)["max_dd"]},
        "official": {"cagr": G.metrics(bo)["cagr"], "uw_G": G.underwater(bo).get("length_d"),
                     "uw_S829": R3.recovery_s829(bo)["longest_uw_d"], "mdd": G.metrics(bo)["max_dd"]},
        "same_legs_from_2021-10-11": {"cagr": G.metrics(bs)["cagr"], "uw_G": G.underwater(bs).get("length_d"),
                                      "uw_S829": R3.recovery_s829(bs)["longest_uw_d"], "mdd": G.metrics(bs)["max_dd"],
                                      "nav_max_abs_diff": float((bs - bo).abs().max())},
        "note": "长账本从 2020-08-16 起数 21 日调仓相位 ⇒ 窗口 B 与 ① 有残差;同腿同起点的核自比见 same_legs_from_2021-10-11"}
    log(f"  窗口 B 对账:长账本 {G.metrics(bl)['cagr']:+.4%} / UW {R3.recovery_s829(bl)['longest_uw_d']} 日"
        f" / MDD {G.metrics(bl)['max_dd']:+.4%}  vs  ① 官方 {G.metrics(bo)['cagr']:+.4%}"
        f" / UW {R3.recovery_s829(bo)['longest_uw_d']} 日 / MDD {G.metrics(bo)['max_dd']:+.4%}")
    log(f"  归因(同腿、从 2021-10-11 起记):CAGR {G.metrics(bs)['cagr']:+.4%} / UW "
        f"{R3.recovery_s829(bs)['longest_uw_d']} 日 / MDD {G.metrics(bs)['max_dd']:+.4%}"
        f" · 与 ① 逐位最大差 {float((bs - bo).abs().max()):.2e}")

    fam_out = {"meta": {k: v for k, v in fam.items() if k != "nav"},
               "family_standalone": G.metrics(fam["nav"]),
               "family_standalone_yearly": G.yearly(fam["nav"]),
               "windows": {}}
    for wname, wstart in WINDOWS:
        w = window_stats(base["nav"], arm, wstart)
        sc = R3.selfcheck_family(fam["nav"], fam_ret, wstart, WIN_END)
        w["selfcheck_family"] = sc
        fam_out["windows"][wname] = w
        d = w["diff"]
        log(f"  [{wname}] {wstart} → {WIN_END}:C0 CAGR {w['C0']['metrics']['cagr']:+.4%}"
            f" / +H4 {w['C0_plus_family']['metrics']['cagr']:+.4%}(Δ {d['cagr_pp']:+.3f}pp)"
            f" | UW {w['C0']['underwater'].get('length_d')} → {w['C0_plus_family']['underwater'].get('length_d')} 日"
            f" | MDD {w['C0']['metrics']['max_dd']:+.4%} → {w['C0_plus_family']['metrics']['max_dd']:+.4%}"
            f" | 自检② {sc['abs_diff']:.2e}")
    a = fam_out["windows"]["A_long_2020-08-16"]["diff"]
    b = fam_out["windows"]["B_2021-10-11"]["diff"]
    a_pass = bool(a["underwater_shorter"] and a["cagr_not_lower"])
    b_pass = bool(b["underwater_shorter"] and b["cagr_not_lower"])
    fam_out["conclusion"] = {"class": ("两个窗口都让最长水下变短且年化不降" if (a_pass and b_pass)
                                        else ("只在一个窗口" if (a_pass or b_pass) else "都不")),
                              "window_A_pass": a_pass, "window_B_pass": b_pass,
                              "window_dependent": bool(a_pass != b_pass)}
    res["family"] = fam_out
    log(f"  ① 结论:{fam_out['conclusion']['class']}(A {a_pass} / B {b_pass})"
        + ("—— 窗口依赖" if a_pass != b_pass else ""))

    # ② 零分布
    memo = ArmMemo(base, cal)

    def arm_stats(values: np.ndarray, wstart: str) -> dict:
        nav = memo.nav(values)
        c0 = R3.slice_win(base["nav"], wstart, WIN_END)
        c0f = R3.slice_win(nav, wstart, WIN_END)
        m0, mf = G.metrics(c0), G.metrics(c0f)
        u0, uf = G.underwater(c0), G.underwater(c0f)
        return {"uw_shorten_d": (u0.get("length_d") or 0) - (uf.get("length_d") or 0),
                "cagr_diff_pp": 100.0 * (mf["cagr"] - m0["cagr"])}

    actual = {w: arm_stats(fam_vals, s) for w, s in WINDOWS}
    log(f"  实际值:A {actual['A_long_2020-08-16']} · B {actual['B_2021-10-11']}")

    for wname, wstart in WINDOWS:
        entry = {"window": wname, "start": wstart, "actual": actual[wname]}
        for stat in ("uw_shorten_d", "cagr_diff_pp"):
            def fn(rng, _stat=stat, _w=wstart):
                shifted = apparatus.circular_shift(fam_vals, rng, block=NULL_BLOCK)
                return arm_stats(shifted, _w)[_stat]
            try:
                null = apparatus.null_distribution(fn, n_null, NULL_SEED,
                                                   actual=actual[wname][stat])
                p = apparatus.p_upper(actual[wname][stat], null)
                entry[stat] = {"p_upper": p, "null_n": int(len(null)),
                               "null_mean": float(np.mean(null)), "null_std": float(np.std(null)),
                               "null_min": float(np.min(null)), "null_max": float(np.max(null)),
                               "null_q": [float(np.quantile(null, q)) for q in (0.05, 0.5, 0.95)],
                               "actual_pct": apparatus.percentile_of(actual[wname][stat], null)}
                log(f"  [{wname}/{stat}] 实际 {actual[wname][stat]:+.4f} · p_upper {p:.4f}"
                    f" · 零分布均值 {np.mean(null):+.4f} 跨度 [{np.min(null):+.4f}, {np.max(null):+.4f}]")
            except apparatus.NoOpNull as e:
                entry[stat] = {"p_upper": None, "error": f"NoOpNull: {e}"}
                log(f"  [{wname}/{stat}] ✗ {e}")
        res["null"][wname] = entry

    # 一句话结论(三类:两窗口都改善且 p<0.10 / 窗口依赖 / 过不了零分布)
    pa = res["null"].get("A_long_2020-08-16", {})
    pb = res["null"].get("B_2021-10-11", {})
    p_uw = [x.get("uw_shorten_d", {}).get("p_upper") for x in (pa, pb)]
    p_cagr = [x.get("cagr_diff_pp", {}).get("p_upper") for x in (pa, pb)]
    both = bool(a_pass and b_pass)
    one = bool(a_pass != b_pass)
    sig_uw = all(p is not None and p < 0.10 for p in p_uw)
    sig_cagr = all(p is not None and p < 0.10 for p in p_cagr)
    sig_all = bool(sig_uw and sig_cagr)
    if one:
        one_liner = "窗口依赖(只在一个窗口改善)"
        cls = "窗口依赖"
    elif both and sig_all:
        one_liner = "两个窗口都改善且过零分布(p < 0.10)"
        cls = "两个窗口都改善且 p<0.10"
    elif both:
        bits = []
        if not sig_uw:
            bits.append(f"最长水下缩短 p = {p_uw[0]:.3f}/{p_uw[1]:.3f} ≥ 0.10")
        if not sig_cagr:
            bits.append(f"年化差 p = {p_cagr[0]:.3f}/{p_cagr[1]:.3f} ≥ 0.10")
        one_liner = "两个窗口都改善但过不了零分布(" + ";".join(bits) + ")"
        cls = "两个窗口都改善但过不了零分布"
        if len(set(p_uw)) > 1 or len(set(p_cagr)) > 1:
            one_liner += "—— p 值本身窗口依赖"
    else:
        one_liner = "两个窗口都不改善"
        cls = "都不"
    res["one_liner"] = {"text": one_liner, "class": cls, "both_windows_improve": both,
                        "p_uw": p_uw, "p_cagr": p_cagr,
                        "sig_uw": bool(sig_uw), "sig_cagr": bool(sig_cagr), "sig_all_lt_010": sig_all}
    log(f"  ② 一句话结论:{one_liner}")

    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


def write_md(res: dict) -> None:
    b = res["base_long"]
    L: list[str] = []
    A = L.append
    A("## T-348 第四轮:H4 族 —— 长账本(2020-08-16 起)两窗口并排 + 零分布\n")
    A(f"长账本 C0(R-v2 用 t353_engine;腿全部从库里重取;现金利率 {res['spec']['cash_zero_before']} 之前记 0;"
      f"core {res['spec']['core_fetch_start']} 起、{res['spec']['core_splice']} 起换官方腿):"
      f"年化 **{b['C0_cagr']:+.4%}** · 最长水下 **{b['C0_uw_S829']['longest_uw_d']} 日**(S-829 口径)/ "
      f"{b['C0_uw_G'].get('length_d')} 日(G.underwater)· 最大回撤 **{b['C0_max_dd']:+.4%}**。")
    ck = res["checks"]["windowB_vs_official"]
    A(f"窗口 B 对账(长账本 vs ① 官方):{ck['long']['cagr']:+.4%} / {ck['long']['uw_S829']} 日 / "
      f"{ck['long']['mdd']:+.4%} vs {ck['official']['cagr']:+.4%} / {ck['official']['uw_S829']} 日 / "
      f"{ck['official']['mdd']:+.4%}(残差 = 调仓相位)。\n")
    A("| 窗口 | C0 CAGR | +H4 CAGR | Δ(pp) | C0 最长水下 | +H4 最长水下 | Δ(天) | C0 最大回撤 | +H4 最大回撤 | 自检② |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for wn, w in res["family"]["windows"].items():
        d = w["diff"]
        A(f"| {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
          f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {d['cagr_pp']:+.3f} | "
          f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
          f"{d['underwater_days']:+d} | {w['C0']['metrics']['max_dd']:+.4%} | "
          f"{w['C0_plus_family']['metrics']['max_dd']:+.4%} | {w['selfcheck_family']['abs_diff']:.1e} |")
    A("")
    A("| 窗口 | 逐年 | C0 | +H4 |")
    A("|---|---|---|---|")
    for wn, w in res["family"]["windows"].items():
        ys = sorted({int(y) for y in list(w["C0"]["yearly"].keys()) + list(w["C0_plus_family"]["yearly"].keys())})
        for y in ys:
            c0y = w["C0"]["yearly"].get(y)
            fy = w["C0_plus_family"]["yearly"].get(y)
            A(f"| {wn} | {y} | {'—' if c0y is None else f'{c0y:+.2%}'} | "
              f"{'—' if fy is None else f'{fy:+.2%}'} |")
    A("")
    A("| 窗口 | 统计量 | 实际 | p_upper | 零分布均值 | 零分布 5%–95% |")
    A("|---|---|---|---|---|---|")
    for wn, e in res["null"].items():
        for stat, lab in (("uw_shorten_d", "最长水下缩短(天)"), ("cagr_diff_pp", "年化差(pp)")):
            s = e.get(stat, {})
            if s.get("p_upper") is None:
                A(f"| {wn} | {lab} | {e['actual'][stat]:+.4f} | — | {s.get('error', '')} | — |")
            else:
                A(f"| {wn} | {lab} | {e['actual'][stat]:+.4f} | **{s['p_upper']:.4f}** | "
                  f"{s['null_mean']:+.4f} | {s['null_q'][0]:+.4f} … {s['null_q'][2]:+.4f} |")
    A("")
    A(f"**一句话结论:{res['one_liner']['text']}**")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
