"""T-348 第三轮 ②(lane-c,2026-11-12):长账本(2020-08-16 起)的 C0 与 S-681 H2 / H4,两个窗口并排。

为什么要有长账本:① 的基准账本从 2021-10-11 起(S-829 同窗),S-681 H2 / H4 的票源到 2020 年就
有 ⇒ 窗口 A 被基准卡住,和窗口 B 是同一段(这是第二轮 §Seth-1111l 之前那一版的毛病)。
这一轮把基准账本往前延到 2020-08-16(R-v2 票源 t197 tickets.A 的首票进场日)。

自洽重建(只读,不改任何既有产物):
- ①(crypto 腿的核内输入)= `core_variants_daily` 的 `cap_pit24` 单臂,**从 2019-01-01 起**
  (表头),喂 `src.data.signals.tom.trade_path/trade_returns`(核内建 WARM=200 ⇒ 2019-07 之后规则生效);
- 股 = ohlcv_daily eodhd ACWI;金 = eodhd XAUUSD;现金利率 = feature_matrix_daily 的
  `stable_lend_apy_7d` ÷ 100 ÷ 365(该字段 2023-02-10 之前没有 ⇒ 记 0);
- R-v2 叠加 = t353_engine 曲线(t348_r3.py 已缓存);
- **拼接**:2021-07-13(t342 house book 的 core 共同起点)起用官方 crypto 腿的**逐日收益**接在
  长账本的 crypto 腿上 ⇒ 2021-10-11 起的腿与 ① 完全一致,窗口 B 可与 ① 对账
  (残差只来自调仓相位:长账本从 2020-08-16 起数 21 日,① 从 2021-10-11 起数)。

用法: python3 t348_r3_long.py
产物: t348_r3_long_results.json + _t348_r3_long_tables.md
"""
from __future__ import annotations

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

import t348_graveyard as G  # noqa: E402
import t348_r3 as R3  # noqa: E402

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
LONG_START = "2020-08-16"
WIN_B = "2021-10-11"
WIN_END = "2026-10-30"
CORE_SPLICE = "2021-07-13"
FETCH_START = "2019-01-01"
OUT_JSON = os.path.join(HERE, "t348_r3_long_results.json")
OUT_MD = os.path.join(HERE, "_t348_r3_long_tables.md")
FAM_CACHE = os.path.join(HERE, "t348_r3_families.csv")


def log(msg: str) -> None:
    print(str(msg), flush=True)


def rest(table: str, params: dict) -> list:
    """只读;每页 ≤ 1000 行;一律带 order=(按主键排)。"""
    url = f"{URL}/rest/v1/{table}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def fetch_all(table: str, select: str, filters: dict, order_col: str) -> list[dict]:
    out: list[dict] = []
    off = 0
    while True:
        p = dict(filters)
        p.update({"select": select, "order": f"{order_col}.asc", "limit": 1000, "offset": off})
        rows = rest(table, p)
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
        if off > 40000:
            break
    log(f"  {table}: {len(out)} 行")
    return out


def fetch_series(table: str, select: str, filters: dict, dcol: str, vcol: str) -> pd.Series:
    rows = fetch_all(table, select, filters, dcol)
    s = pd.Series({pd.Timestamp(str(r[dcol])[:10]): float(r[vcol]) for r in rows if r.get(vcol) is not None})
    return s.sort_index()


def build_long_legs() -> tuple[dict, pd.Series, dict]:
    """长账本的三条腿 + 现金利率。只读。"""
    log("=== 取数(长账本)===")
    # ① core(cap_pit24)—— 从表头起,给 tom 核 200 日 warm-up
    cv = fetch_all("core_variants_daily", "d,ret",
                   ["arm=eq.cap_pit24", f"d=gte.{FETCH_START}", f"d=lte.{WIN_END}"], "d")
    ret_map = {pd.Timestamp(str(r["d"])[:10]): float(r["ret"]) for r in cv if r.get("ret") is not None}
    d0, d1 = min(ret_map), max(ret_map)
    full = pd.date_range(d0, d1, freq="D")
    raw_rets = pd.Series({d: ret_map.get(d, np.nan) for d in full}, dtype=float)
    core = (1.0 + raw_rets.fillna(0.0)).cumprod()
    log(f"  ① core:表 {len(cv)} 行 {d0.date()} → {d1.date()}(无行 {int(raw_rets.isna().sum())} 天记 0 收益)")

    # 资金费(BTC/binance_perp)→ 年化
    fr = fetch_all("funding_history", "funding_time,funding_rate",
                   ["venue=eq.binance_perp", "symbol=eq.BTC",
                    f"funding_time=gte.{FETCH_START}", f"funding_time=lte.{WIN_END}"], "funding_time")
    fdf = pd.DataFrame(fr)
    fdf["d"] = pd.to_datetime(fdf["funding_time"].astype(str).str[:10])
    fund = fdf.groupby("d")["funding_rate"].sum().astype(float) * 365.0
    log(f"  资金费 BTC:{len(fund)} 天 {fund.index[0].date()} → {fund.index[-1].date()}")

    # crypto 腿(tom 核 CORE_X1V = ('CORE','rally',0.0,'l20',True))
    g = trade_path(core, "rally", 0.0, "l20", True)
    r = trade_returns(core, g, fund if len(fund) else None)
    crypto_long = pd.concat([pd.Series([1.0], index=[core.index[0]]), (1.0 + r).cumprod()]).sort_index()
    log(f"  crypto 腿(长重建):{len(crypto_long)} 行 {crypto_long.index[0].date()} → {crypto_long.index[-1].date()}")

    # 拼接:2021-07-13 起用官方 crypto 腿的逐日收益
    daily = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    off_nav = daily["crypto_leg_nav_x1v"].astype(float)
    crypto = crypto_long.copy()
    prev = None
    n_spliced = 0
    for d, v in off_nav.items():
        if d < pd.Timestamp(CORE_SPLICE):
            continue
        if prev is None:
            # 官方腿首日 = 1.0 ⇒ 当日收益 0
            ret = 0.0
        else:
            ret = float(off_nav[d] / off_nav[prev] - 1.0)
        lvl = float(crypto.loc[d - pd.Timedelta(days=1)]) if d - pd.Timedelta(days=1) in crypto.index else float(crypto.iloc[0])
        crypto[d] = lvl * (1.0 + ret)
        prev = d
        n_spliced += 1
    crypto = crypto.sort_index()
    log(f"  拼接:{CORE_SPLICE} 起换官方 crypto 腿收益({n_spliced} 天)")

    # 股 / 金
    equity = fetch_series("ohlcv_daily", "trade_date,close",
                           ["symbol=eq.ACWI", "source=eq.eodhd",
                            f"trade_date=gte.{FETCH_START}", f"trade_date=lte.{WIN_END}"],
                           "trade_date", "close")
    gold = fetch_series("ohlcv_daily", "trade_date,close",
                        ["symbol=eq.XAUUSD", "source=eq.eodhd",
                         f"trade_date=gte.{FETCH_START}", f"trade_date=lte.{WIN_END}"],
                        "trade_date", "close")
    log(f"  股 ACWI:{len(equity)} 行 {equity.index[0].date()} → {equity.index[-1].date()}")
    log(f"  金 XAUUSD:{len(gold)} 行 {gold.index[0].date()} → {gold.index[-1].date()}")

    # 现金利率
    fm = fetch_all("feature_matrix_daily", "d,f",
                   [f"d=gte.{FETCH_START}", f"d=lte.{WIN_END}"], "d")
    apy = {}
    for r_ in fm:
        f = r_.get("f") or {}
        if isinstance(f, dict) and f.get("stable_lend_apy_7d") is not None:
            apy[str(r_["d"])[:10]] = float(f["stable_lend_apy_7d"])
    log(f"  现金利率 stable_lend_apy_7d:{len(apy)} 天"
        + (f"({min(apy)} → {max(apy)})" if apy else ""))
    legs = {"crypto": crypto, "equity": equity, "gold": gold}
    return legs, apy, {"core_rows": len(cv), "fund_rows": len(fr), "fm_rows": len(fm),
                       "crypto_spliced_days": n_spliced, "core_d0": str(d0.date()), "core_d1": str(d1.date())}


def main() -> None:
    legs, apy, info = build_long_legs()
    cal = pd.date_range(pd.Timestamp(LONG_START), pd.Timestamp(WIN_END), freq="D")
    cash = pd.Series({d: (float(apy[str(d.date())]) / 100.0 / 365.0
                           if str(d.date()) in apy else 0.0) for d in cal}, dtype=float)
    rv2 = R3.rv2_curve().pct_change().dropna()
    nav, lg = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                 start=pd.Timestamp(LONG_START), overlay_ret=rv2, cash_ret=cash)
    nav = nav[nav.index <= pd.Timestamp(WIN_END)]
    log(f"  长账本 C0:{len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" · 终值 {float(nav.iloc[-1]):.4f} · 调仓 {len(lg)} 次")

    base = {"legs": legs, "cash": cash, "rv2": rv2, "nav": nav,
            "cal_idx": pd.date_range(pd.Timestamp(LONG_START), pd.Timestamp(WIN_END), freq="D"),
            "start": LONG_START, "end": WIN_END}

    m_long = G.metrics(nav)
    rec_long = R3.recovery_s829(nav)
    # 自检:长账本窗口 B 的 C0 与 ① 的官方 C0 对账(腿一致,只差调仓相位)
    b_long = R3.slice_win(nav, WIN_B, WIN_END)
    daily = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    cash_std = daily["cash_daily_rate"].astype(float).reindex(
        pd.date_range(daily.index[0], daily.index[-1], freq="D")).ffill().fillna(0.0)
    std_legs = {"crypto": daily["crypto_leg_nav_x1v"].astype(float),
                "equity": daily["equity_close_acwi"].astype(float),
                "gold": daily["gold_close_xauusd"].astype(float)}
    nav_std, _ = fa.dynamic_mix_nav(std_legs, lambda h, x: fa.rb_weights(h),
                                    start=pd.Timestamp(WIN_B), overlay_ret=rv2, cash_ret=cash_std)
    nav_std = nav_std[nav_std.index <= pd.Timestamp(WIN_END)]
    m_std = G.metrics(nav_std)
    rec_std = R3.recovery_s829(nav_std)
    log(f"  自检 窗口 B:长账本 CAGR {m_long['cagr']:+.4%} / UW {rec_long['longest_uw_d']} 日"
        f" / MDD {rec_long['mdd']:+.4%}  vs  ① 官方 C0 CAGR {m_std['cagr']:+.4%}"
        f" / UW {rec_std['longest_uw_d']} 日 / MDD {rec_std['mdd']:+.4%}")

    # 族:H2 / H4(用 ① 的缓存曲线)
    df = pd.read_csv(FAM_CACHE, parse_dates=["d"])
    meta = json.load(open(os.path.join(HERE, "t348_r3_families_meta.json")))
    fams = {}
    for k in ("S681_H2", "S681_H4"):
        nav_f = df[df["family"] == k].set_index("d")["nav"].astype(float)
        fams[k] = {"nav": nav_f, **meta[k]}

    res = {"card": "T-348", "part": "第三轮 ②:长账本(2020-08-16 起)C0 与 H2 / H4,两窗口并排",
           "generated": "lane-c 2026-11-12",
           "spec": {"ledger_start": LONG_START, "window_B": WIN_B, "end": WIN_END,
                    "core_fetch_start": FETCH_START, "core_splice": CORE_SPLICE,
                    "engine": "docs/research/t353_engine.py(f 0.005 / cap 0.40 / 名额 14 / exits_first / marked)"},
           "data": info,
           "base_long": {"C0_cagr": m_long["cagr"], "C0_total_return": m_long["total_return"],
                         "C0_max_dd": m_long["max_dd"], "C0_uw_G": G.underwater(nav),
                         "C0_recovery_S829": rec_long,
                         "windowB_cagr": G.metrics(b_long)["cagr"],
                         "windowB_uw": G.underwater(b_long)["length_d"],
                         "windowB_max_dd": G.metrics(b_long)["max_dd"]},
           "base_official_windowB": {"C0_cagr": m_std["cagr"], "C0_uw_S829": rec_std["longest_uw_d"],
                                     "C0_mdd": rec_std["mdd"]},
           "families": {}}

    for key, fam in fams.items():
        fam_ret = R3.fam_return_series(fam["nav"], base["cal_idx"])
        arm = R3.arm_with_family(base, fam_ret)
        out = {"meta": {k: v for k, v in fam.items() if k != "nav"},
               "family_standalone": G.metrics(fam["nav"]), "windows": {}}
        for wname, wstart in (("A_long_2020-08-16", LONG_START), ("B_2021-10-11", WIN_B)):
            c0 = R3.slice_win(nav, wstart, WIN_END)
            c0f = R3.slice_win(arm, wstart, WIN_END)
            m0, mf = G.metrics(c0), G.metrics(c0f)
            u0, uf = G.underwater(c0), G.underwater(c0f)
            sc = R3.selfcheck_family(fam["nav"], fam_ret, wstart, WIN_END)
            log(f"  [{key}/{wname}] {wstart} → {WIN_END}:C0 CAGR {m0['cagr']:+.4%}"
                f" / +族 {mf['cagr']:+.4%}(Δ {100*(mf['cagr']-m0['cagr']):+.3f}pp)"
                f" | UW {u0.get('length_d')} → {uf.get('length_d')} 日"
                f" | MDD {m0['max_dd']:+.4%} → {mf['max_dd']:+.4%} | 自检② {sc['abs_diff']:.2e}")
            out["windows"][wname] = {
                "start": wstart, "end": WIN_END,
                "C0": {"metrics": m0, "underwater": u0, "yearly": G.yearly(c0)},
                "C0_plus_family": {"metrics": mf, "underwater": uf, "yearly": G.yearly(c0f)},
                "diff": {"cagr_pp": 100.0 * (mf["cagr"] - m0["cagr"]),
                         "max_dd_pp": 100.0 * (mf["max_dd"] - m0["max_dd"]),
                         "total_return_pp": 100.0 * (mf["total_return"] - m0["total_return"]),
                         "underwater_days": (uf.get("length_d") or 0) - (u0.get("length_d") or 0),
                         "cagr_not_lower": bool(mf["cagr"] >= m0["cagr"]),
                         "underwater_shorter": bool((uf.get("length_d") or 0) < (u0.get("length_d") or 0))},
                "selfcheck_family": sc,
            }
        wins = out["windows"]
        a = wins["A_long_2020-08-16"]["diff"]
        b = wins["B_2021-10-11"]["diff"]
        a_pass = bool(a["underwater_shorter"] and a["cagr_not_lower"])
        b_pass = bool(b["underwater_shorter"] and b["cagr_not_lower"])
        if a_pass and b_pass:
            cls = "两个窗口都改善"
        elif a_pass or b_pass:
            cls = "只在一个窗口"
        else:
            cls = "都不"
        out["conclusion"] = {"class": cls, "window_A_pass": a_pass, "window_B_pass": b_pass,
                             "window_dependent": bool(a_pass != b_pass),
                             "one_liner": (f"{cls}:" +
                                          f"窗口 A ΔCAGR {a['cagr_pp']:+.3f}pp / 水下 {a['underwater_days']:+d} 天;"
                                          f"窗口 B ΔCAGR {b['cagr_pp']:+.3f}pp / 水下 {b['underwater_days']:+d} 天")}
        log(f"  {key} 结论:{out['conclusion']['one_liner']}")
        res["families"][key] = out
        json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)

    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


def write_md(res: dict) -> None:
    b = res["base_long"]
    bo = res["base_official_windowB"]
    L: list[str] = []
    A = L.append
    A("## T-348 第三轮 ②:长账本(2020-08-16 起)的 C0 与 S-681 H2 / H4\n")
    A(f"长账本 C0(自洽重建:R-v2 用 t353_engine;crypto 腿 core 从 {res['spec']['core_fetch_start']} 起、"
      f"{res['spec']['core_splice']} 起拼接官方腿):年化 **{b['C0_cagr']:+.4%}** · 最长水下 "
      f"**{b['C0_recovery_S829']['longest_uw_d']} 日**(S-829 口径)/ {b['C0_uw_G'].get('length_d')} 日(G.underwater)"
      f" · 最大回撤 **{b['C0_max_dd']:+.4%}**。")
    A(f"窗口 B(2021-10-11 起)自检:长账本 {b['windowB_cagr']:+.4%} / {b['windowB_uw']} 日 / "
      f"{b['windowB_max_dd']:+.4%}  vs  ① 官方 C0 {bo['C0_cagr']:+.4%} / {bo['C0_uw_S829']} 日 / "
      f"{bo['C0_mdd']:+.4%}(残差来自调仓相位:长账本从 2020-08-16 起数 21 日)。\n")
    A("| 族 | 窗口 | C0 CAGR | +族 CAGR | Δ(pp) | C0 最长水下 | +族 最长水下 | C0 最大回撤 | +族 最大回撤 | 自检② 差 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for key, r in res["families"].items():
        for wn, w in r["windows"].items():
            A(f"| {key} | {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
              f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {w['diff']['cagr_pp']:+.3f} | "
              f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
              f"{w['C0']['metrics']['max_dd']:+.4%} | {w['C0_plus_family']['metrics']['max_dd']:+.4%} | "
              f"{w['selfcheck_family']['abs_diff']:.1e} |")
    A("")
    A("| 族 | 一句话结论 |")
    A("|---|---|")
    for key, r in res["families"].items():
        A(f"| {key} | {r['conclusion']['one_liner']} |")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
