#!/usr/bin/env python3
"""T-320 — S-797 盲复算(lane-b)。

口径来源:**只读** `REFUTATION_LEDGER.md` 的 `## S-797` 原文(2026-11-09 15:46 UTC 预注册,Seth)。
禁读 lane-c 的 `docs/research/t318_*` / `T-318_*` / lane-c/T-318 分支 —— 本文件独立装配。

装配(原文「写死」段):
  腿(日收盘)   crypto = `forward_books.TOM_ARMS['CORE_X1V']` 同一规则作用于 ① 的 NAV(`signals/tom` 核)
               equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`
               天气   = `state_daily` entity=panel 的 `dist_200` / `vratio_30_180` → `flex_alloc.weather_of`
  区间        三条腿与天气共同日期第一天起,先空跑 252 个共同日作历史(不记 NAV),之后到 2026-10-31 记 NAV;两半按天数对半
  三条臂      全部 `flex_alloc.dynamic_mix_nav(legs, fn, reb=21, cost=20bp)`:
               T25_K(fn 恒返回 BASE_T25,对照)· RB(fn=rb_weights(hist))· STYLE(fn=style_weights(style_table(hist, weather_hist), weather_d))
               另报 ① 自己(持有面板)与 `mix_nav` 版 T25(记账时点差异的对照)
  判          (i) Calmar ≥ T25_K 的 1.15 倍 (ii) 总收益 ≥ T25_K (iii) 最大回撤不比 T25_K 差 2pp 以上
               (iv) 两半各自 Calmar ≥ 同半 T25_K (v) `apparatus.ab_test`(臂 vs T25_K,mean_block=20,n_boot=2000,seed=797)p(臂 ≤ T25_K) ≤ 0.10

除基线读法外,另跑一组「换读法」变体(口径歧义敏感性):每个变体重跑三条臂与 (i)–(v),只问「结论变不变」。
只读库、不入库、不改 `src/`。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.signals import tom as TOM                  # noqa: E402  交易层核
from src.data.universe import forward_books as FB         # noqa: E402  mix_nav / TOM_ARMS
from src.data.evaluation import apparatus as APP          # noqa: E402  ab_test

# 组合层核 `src/data/universe/flex_alloc.py`:Seth 写好但**尚未进 git**(2026-11-10 时它只存在于主目录的未跟踪工作副本)。
# 本分支不碰 src/ ⇒ 按字节复制到 docs/research/t320_flex_alloc_core.py,运行时核对 sha256(一字不改的证据)。
CORE_COPY = Path(__file__).resolve().parent / "t320_flex_alloc_core.py"
CORE_SRC = Path("/Users/sbb/Projects/looloomi-ai/src/data/universe/flex_alloc.py")
_spec = importlib.util.spec_from_file_location("t320_flex_alloc_core", CORE_COPY)
FA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FA)

OUT = Path(__file__).resolve().parent
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出")
URL = URL.rstrip("/")

END_CAP = "2026-10-31"      # 原文:「之后到 2026-10-31 记 NAV」
WARM_COMMON = 252           # 原文:「先空跑 252 个共同日作历史(不记 NAV)」
REB, COST = 21, 20 / 1e4    # 原文写死:reb=21, cost=20bp(与核默认一致)


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# ── 只读取库(分页,每页 ≤1000,带 order=)────────────────────────────────────────
def fetch(table: str, query: str, order: str) -> list[dict]:
    """读 PostgREST。Range 分页(每页 1000),order 必带;核总行数。"""
    rows, start = [], 0
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&order={order}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": f"{start}-{start + 999}"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            cr = r.headers.get("Content-Range", "")
            body = r.read().decode()
        page = json.loads(body)
        rows.extend(page)
        total = int(cr.split("/")[-1]) if "/" in cr else len(rows)
        if len(page) < 1000 or len(rows) >= total:
            break
        start += 1000
    assert len(rows) == total, f"{table}: 取到 {len(rows)} 行,核数 {total}"
    return rows


# ── 指标 ──────────────────────────────────────────────────────────────────────
def metrics(nav: pd.Series, year_basis: float = 365.0) -> dict:
    nav = nav.dropna()
    if len(nav) < 3:
        return {"n_days": int(len(nav))}
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / year_basis
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else None
    vol = float(r.std(ddof=1) * math.sqrt(year_basis)) if len(r) > 1 else None
    dd = nav / nav.cummax() - 1.0
    maxdd = float(dd.min())
    calmar = float(cagr / abs(maxdd)) if (cagr is not None and maxdd < 0) else None
    m = r.groupby([r.index.year, r.index.month]).apply(lambda x: float((1 + x).prod() - 1.0))
    worst_m = float(m.min()) if len(m) else None
    worst_mk = f"{int(m.idxmin()[0])}-{int(m.idxmin()[1]):02d}" if len(m) else None
    return {"n_days": int(len(nav)), "first": nav.index[0].date().isoformat(),
            "last": nav.index[-1].date().isoformat(), "years": round(yrs, 3),
            "total_return": round(total, 6), "cagr": round(cagr, 6) if cagr is not None else None,
            "vol_ann": round(vol, 6) if vol is not None else None,
            "max_drawdown": round(maxdd, 6), "calmar": round(calmar, 4) if calmar is not None else None,
            "worst_month": round(worst_m, 6) if worst_m is not None else None,
            "worst_month_key": worst_mk}


def halves(nav: pd.Series, extra_to: str = "first") -> tuple[pd.Series, pd.Series]:
    n = len(nav)
    cut = (n + 1) // 2 if extra_to == "first" else n // 2
    return nav.iloc[:cut], nav.iloc[cut:]


def judge(K: pd.Series, A: pd.Series, year_basis: float, extra_to: str) -> dict:
    """(i)–(v) 逐条。"""
    mA, mK = metrics(A, year_basis), metrics(K, year_basis)
    A_h1, A_h2 = halves(A, extra_to)
    K_h1, K_h2 = halves(K, extra_to)
    hA1, hA2 = metrics(A_h1, year_basis), metrics(A_h2, year_basis)
    hK1, hK2 = metrics(K_h1, year_basis), metrics(K_h2, year_basis)
    i_ok = (mA["calmar"] is not None and mK["calmar"] is not None and mA["calmar"] >= 1.15 * mK["calmar"])
    ii_ok = mA["total_return"] >= mK["total_return"]
    iii_ok = mA["max_drawdown"] >= mK["max_drawdown"] - 0.02
    iv_ok = all(h["calmar"] is not None and hk["calmar"] is not None and h["calmar"] >= hk["calmar"]
                for h, hk in ((hA1, hK1), (hA2, hK2)))
    ab = APP.ab_test(K.pct_change().dropna().values, A.pct_change().dropna().values,
                     mean_block=20.0, n_boot=2000, seed=797)
    v_ok = ab["p_b_le_a"] <= 0.10
    return {
        "i_calmar_ge_115pct": {"pass": bool(i_ok), "arm_calmar": mA["calmar"], "K_calmar": mK["calmar"],
                               "threshold": round(1.15 * mK["calmar"], 4)},
        "ii_total_return_ge_K": {"pass": bool(ii_ok), "arm": mA["total_return"], "K": mK["total_return"]},
        "iii_maxdd_not_worse_by_2pp": {"pass": bool(iii_ok), "arm": mA["max_drawdown"], "K": mK["max_drawdown"],
                                       "delta_pp": round((mA["max_drawdown"] - mK["max_drawdown"]) * 100, 3)},
        "iv_both_halves_calmar_ge_K": {"pass": bool(iv_ok),
                                       "h1": {"arm": hA1.get("calmar"), "K": hK1.get("calmar")},
                                       "h2": {"arm": hA2.get("calmar"), "K": hK2.get("calmar")}},
        "v_ab_test_p_le_010": {"pass": bool(v_ok), "p_b_le_a": ab["p_b_le_a"], "p_b_ge_a": ab["p_b_ge_a"],
                               "ci95_log_diff": ab["ci95_log_diff"], "n_days": ab["n_days"],
                               "verdict": ab["verdict"], "underpowered": ab["underpowered"],
                               "cum_K": ab["cum_a"], "cum_arm": ab["cum_b"]},
        "half_metrics": {"arm_h1": hA1, "arm_h2": hA2, "K_h1": hK1, "K_h2": hK2},
        "ALL_PASS": bool(i_ok and ii_ok and iii_ok and iv_ok and v_ok),
    }


def main() -> int:
    # ── 1. 取数(一次)─────────────────────────────────────────────────────────
    core_rows = fetch("multiplier_daily", "select=d,arm,nav&arm=in.(core_u_replay,core_replay)", "arm.asc,d.asc")
    core: dict[str, pd.Series] = {}
    for r in core_rows:
        core.setdefault(r["arm"], pd.Series(dtype=float))
    dfs = {}
    for r in core_rows:
        dfs.setdefault(r["arm"], []).append((pd.Timestamp(r["d"]), float(r["nav"])))
    for arm, pts in dfs.items():
        s = pd.Series(dict(pts)).sort_index()
        core[arm] = s[~s.index.duplicated(keep="last")]

    st_rows = fetch("state_daily", "select=d,feature,value&entity=eq.panel"
                                    "&feature=in.(dist_200,vratio_30_180)", "d.asc,feature.asc")
    feat: dict[str, dict[pd.Timestamp, float]] = {"dist_200": {}, "vratio_30_180": {}}
    for r in st_rows:
        v = r.get("value")
        if v is not None:
            feat[r["feature"]][pd.Timestamp(r["d"])] = float(v)
    dist = pd.Series(feat["dist_200"]).sort_index()
    vrat = pd.Series(feat["vratio_30_180"]).sort_index()

    tf_rows = fetch("ohlcv_daily", "select=trade_date,symbol,close&source=eq.eodhd"
                                    "&symbol=in.(ACWI,XAUUSD)", "symbol.asc,trade_date.asc")
    eq_s, gd_s = {}, {}
    for r in tf_rows:
        c = r.get("close")
        if c is None:
            continue
        (eq_s if r["symbol"] == "ACWI" else gd_s)[pd.Timestamp(r["trade_date"])] = float(c)
    equity, gold = pd.Series(eq_s).sort_index(), pd.Series(gd_s).sort_index()

    fund_rows = fetch("funding_history", "select=funding_time,funding_rate&venue=eq.binance_perp"
                                        "&symbol=eq.BTC", "funding_time.asc")
    fdf = pd.DataFrame(fund_rows)
    fdf["d"] = pd.to_datetime(fdf["funding_time"].str[:10])
    fund = fdf.groupby("d")["funding_rate"].sum().astype(float) * 365.0   # 年化(CORE 用 BTC 的)

    # ── 2. 天气(weather_of 纯函数)───────────────────────────────────────────
    weather = pd.Series({d: FA.weather_of(dist.get(d), vrat.get(d))
                         for d in dist.index.union(vrat.index)}, dtype=object)

    # ── 3. crypto 腿(CORE_X1V 规则作用于 ① 的 NAV)───────────────────────────
    key, bear, size, exit_mode, vol = FB.TOM_ARMS["CORE_X1V"]
    assert key == "CORE" and bear == "rally" and exit_mode == "l20" and vol is True
    g_x1v: dict[str, pd.Series] = {}
    crypto_x1v: dict[str, pd.Series] = {}
    for arm, s in core.items():
        g = TOM.trade_path(s, bear, size, exit_mode, vol)
        cr = TOM.trade_returns(s, g, fund)
        leg = pd.Series((1.0 + cr).cumprod(), index=cr.index)
        leg = pd.concat([pd.Series({s.index[0]: 1.0}), leg]).sort_index()
        g_x1v[arm], crypto_x1v[arm] = g, leg

    END = pd.Timestamp(END_CAP)

    # ── 4. 一个变体:装配 → 三条臂 → (i)–(v) ────────────────────────────────
    def run_variant(cfg: dict) -> dict:
        cnav = core[cfg["core_arm"]]
        cleg = crypto_x1v[cfg["core_arm"]] if cfg["crypto_leg"] == "x1v" else cnav
        legs = {"crypto": cleg, "equity": equity, "gold": gold}
        legs = {k: v[v.index <= END] for k, v in legs.items()}

        df_all = pd.concat(legs, axis=1).dropna()
        w_ok = np.asarray(df_all.index.map(lambda d: isinstance(weather.get(d), str)))
        df_all = df_all[w_ok]
        common = df_all.index
        if cfg["warm"] == "common":
            nav_start = common[WARM_COMMON]
        else:                                   # 备选读法:空跑 252 个**日历日**
            nav_start = common[common >= common[0] + pd.Timedelta(days=WARM_COMMON)][0]
        style_tables: list[tuple[str, dict]] = []

        def fn_t25(hist, d):
            return dict(FA.BASE_T25)

        def fn_rb(hist, d):
            return FA.rb_weights(hist)

        def fn_style(hist, d):
            h = hist if cfg["style_window"] is None else hist.tail(cfg["style_window"])
            wh = weather.reindex(h.index)
            tab = FA.style_table(h, wh)
            style_tables.append((d.date().isoformat(), tab))
            wn = weather.get(d - pd.Timedelta(days=cfg["style_weather_lag"])) if cfg["style_weather_lag"] else weather.get(d)
            return FA.style_weights(tab, wn)

        arms = {}
        for name, fn in (("T25_K", fn_t25), ("RB", fn_rb), ("STYLE", fn_style)):
            arms[name] = FA.dynamic_mix_nav(legs, fn, reb=REB, cost=COST, start=nav_start)
        navs = {k: v[0] for k, v in arms.items()}
        K = navs["T25_K"]
        out = {"cfg": cfg, "nav_start": nav_start.date().isoformat(),
               "n_common": int(len(common)), "common_first": common[0].date().isoformat(),
               "common_last": common[-1].date().isoformat(),
               "metrics": {k: metrics(v, cfg["year_basis"]) for k, v in navs.items()},
               "verdicts": {a: judge(K, navs[a], cfg["year_basis"], cfg["half_extra_to"])
                            for a in ("RB", "STYLE")}}
        for k, (nav, log) in arms.items():
            w = pd.DataFrame([{c: r[c] for c in ("crypto", "equity", "gold")} for r in log])
            m = out["metrics"][k]
            m["weights_mean"] = {c: round(float(w[c].mean()), 4) for c in w.columns}
            m["weights_q10"] = {c: round(float(w[c].quantile(0.10)), 4) for c in w.columns}
            m["weights_q90"] = {c: round(float(w[c].quantile(0.90)), 4) for c in w.columns}
            m["weights_min"] = {c: round(float(w[c].min()), 4) for c in w.columns}
            m["weights_max"] = {c: round(float(w[c].max()), 4) for c in w.columns}
            m["n_rebalances"] = int(len(log))
            m["n_rebalances_off_base"] = int(sum(
                1 for r in log if any(abs(float(r[c]) - FA.BASE_T25[c]) > 1e-9 for c in w.columns)))
            out.setdefault("rebalance_log", {})[k] = log
        if style_tables:
            out["style_table_final"] = {"as_of_rebalance": style_tables[-1][0], "table": style_tables[-1][1]}
            out["style_table_n_reestimates"] = len(style_tables)
        # 对照
        panel_hold = cnav.reindex(common)
        panel_hold = panel_hold[panel_hold.index >= nav_start]
        mix_full = FB.mix_nav(legs, dict(FA.BASE_T25), reb=REB, cost=COST)
        out["controls"] = {"panel_hold": metrics(panel_hold, cfg["year_basis"]),
                           "mix_nav_T25_full": metrics(mix_full, cfg["year_basis"]),
                           "mix_nav_T25_window": metrics(mix_full[mix_full.index >= nav_start], cfg["year_basis"]),
                           "crypto_leg": metrics(cleg[(cleg.index >= nav_start) & (cleg.index <= END)], cfg["year_basis"])}
        out["_navs"] = navs
        out["_common"] = common
        out["_legs"] = legs
        out["_cleg"] = cleg
        out["_cnav"] = cnav
        out["_g"] = g_x1v[cfg["core_arm"]]
        return out

    BASE = {"core_arm": "core_u_replay", "crypto_leg": "x1v", "style_weather_lag": 0,
            "style_window": None, "warm": "common", "year_basis": 365.0, "half_extra_to": "first"}
    VARIANTS = [
        ("V0 基线(原文读法)", BASE),
        ("V1 ① NAV 换成 core_replay", {**BASE, "core_arm": "core_replay"}),
        ("V2 crypto 腿 = ① 买持有(不做 X1V)", {**BASE, "crypto_leg": "hold"}),
        ("V3 STYLE 用 d−1 的天气", {**BASE, "style_weather_lag": 1}),
        ("V4 STYLE 风格表只用最近 252 共同日", {**BASE, "style_window": 252}),
        ("V5 两半切分:多一天给后半", {**BASE, "half_extra_to": "last"}),
        ("V6 年化按 252 日", {**BASE, "year_basis": 252.0}),
        ("V7 空跑按 252 个日历日(非共同日)", {**BASE, "warm": "calendar"}),
    ]
    runs = {name: run_variant(cfg) for name, cfg in VARIANTS}
    base = runs["V0 基线(原文读法)"]

    # ── 5. 落盘 ─────────────────────────────────────────────────────────────
    common, legs, cleg, cnav, gser = (base["_common"], base["_legs"], base["_cleg"],
                                      base["_cnav"], base["_g"])
    navs = base["_navs"]
    leg_df = pd.DataFrame({
        "crypto_leg_nav": cleg.reindex(common),
        "core_nav_hold": cnav.reindex(common),
        "exposure_X1V": gser.reindex(common),
        "equity_close": legs["equity"].reindex(common),
        "gold_close": legs["gold"].reindex(common),
        "dist_200": dist.reindex(common),
        "vratio_30_180": vrat.reindex(common),
        "weather": weather.reindex(common),
        "nav_T25_K": navs["T25_K"], "nav_RB": navs["RB"], "nav_STYLE": navs["STYLE"],
    })
    leg_df.index.name = "date"
    leg_df.to_csv(OUT / "t320_legs.csv")

    res = {
        "meta": {
            "card": "T-320", "ledger": "REFUTATION_LEDGER S-797 (2026-11-09 15:46 UTC)",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "core_arm": BASE["core_arm"], "core_first": cnav.index[0].date().isoformat(),
            "core_last": cnav.index[-1].date().isoformat(),
            "common_first": base["common_first"], "common_last": base["common_last"],
            "n_common": base["n_common"], "warm_common_days": WARM_COMMON,
            "nav_start": base["nav_start"], "end_cap": END_CAP,
            "reb": REB, "cost_bp": 20, "year_basis": 365,
            "base_t25": FA.BASE_T25, "bounds": {k: list(v) for k, v in FA.BOUNDS.items()},
            "tilt": FA.TILT, "vol_window": FA.VOL_WINDOW, "min_obs": FA.MIN_OBS,
            "min_bucket_days": FA.MIN_BUCKET_DAYS, "sig_floor": FA.SIGMA_FLOOR,
            "weather_counts": {k: int((weather.reindex(common) == k).sum()) for k in FA.WEATHERS},
            "n_weather_none_common": int((~np.asarray(common.map(lambda d: isinstance(weather.get(d), str)))).sum()),
            "flex_alloc_sha256_copy": _sha(CORE_COPY),
            "flex_alloc_sha256_src": _sha(CORE_SRC),
            "flex_alloc_in_git": False,
            "n_variants": len(runs),
        },
        "metrics": base["metrics"],
        "controls": base["controls"],
        "verdicts": base["verdicts"],
        "rebalance_log": base["rebalance_log"],
        "style_table_final": base.get("style_table_final"),
        "style_table_n_reestimates": base.get("style_table_n_reestimates"),
    }
    # 变体:结论变不变
    var_out = {}
    for name, r in runs.items():
        row = {"cfg": r["cfg"], "nav_start": r["nav_start"], "n_common": r["n_common"],
               "metrics": {a: {k: r["metrics"][a][k] for k in ("total_return", "cagr", "max_drawdown", "calmar")}
                           for a in r["metrics"]},
               "verdicts": {}}
        for a in ("RB", "STYLE"):
            v = r["verdicts"][a]
            row["verdicts"][a] = {"ALL_PASS": v["ALL_PASS"],
                                  "per_check": {k: v[k]["pass"] for k in
                                                ("i_calmar_ge_115pct", "ii_total_return_ge_K",
                                                 "iii_maxdd_not_worse_by_2pp", "iv_both_halves_calmar_ge_K",
                                                 "v_ab_test_p_le_010")},
                                  "p_b_le_a": v["v_ab_test_p_le_010"]["p_b_le_a"],
                                  "calmar": v["i_calmar_ge_115pct"]["arm_calmar"],
                                  "K_calmar": v["i_calmar_ge_115pct"]["K_calmar"],
                                  "total": v["ii_total_return_ge_K"]["arm"],
                                  "K_total": v["ii_total_return_ge_K"]["K"]}
        var_out[name] = row
    res["variants"] = var_out
    (OUT / "t320_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    print(json.dumps({"nav_start": base["nav_start"], "n_common": base["n_common"],
                      "weather_counts": res["meta"]["weather_counts"],
                      "metrics": base["metrics"], "controls": base["controls"],
                      "verdicts": {a: {k: v for k, v in base["verdicts"][a].items() if k != "half_metrics"}
                                   for a in base["verdicts"]},
                      "variants": {n: v["verdicts"] for n, v in var_out.items()}},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
