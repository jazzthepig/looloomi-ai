#!/usr/bin/env python3
"""T-223 第二族(G1–G6)普查 —— 口径写死在 docs/research/T-223_factor_family_2.md §1 预注册段。

只读:全部 SELECT。产出 docs/research/t223_family2.json。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
from t223_run import pull  # noqa: E402
from src.data.evaluation.apparatus import newey_west_t  # noqa: E402

SEG = {"discovery": ("2023-01", "2024-11"), "holdout": ("2025-01", "2026-09")}
OUT = HERE / "t223_family2.json"


def count(path, params):
    """表存在与否的探针:404 / 400(表不存在、无权限)⇒ -1,不抛。"""
    from t223_run import _count
    import urllib.error
    try:
        return _count(path, params)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return -1
        raise


def g5_series() -> pd.DataFrame:
    df = pull("/rest/v1/state_daily",
              [("select", "d,value"), ("entity", "eq.panel"), ("feature", "eq.stable_supply_30d"),
               ("order", "d.asc")],
              "d.asc", "state_stable_supply_30d")
    df["d"] = df["d"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["m"] = df["d"].str[:7]
    g = df.groupby("m").agg(n_obs=("value", "size"), F=("value", "mean"),
                             first=("d", "min"), last=("d", "max")).reset_index()
    return df, g


def ols_slope(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(x)
    if n < 4:
        return None
    sxx = float(((x - x.mean()) ** 2).sum())
    if sxx <= 0:
        return None
    b = float(((x - x.mean()) * (y - y.mean())).sum() / sxx)
    a = float(y.mean() - b * x.mean())
    resid = y - (a + b * x)
    dof = n - 2
    s2 = float((resid ** 2).sum() / dof) if dof > 0 else float("nan")
    se = math.sqrt(s2 / sxx) if sxx > 0 and math.isfinite(s2) else float("nan")
    return {"n": n, "slope": b, "intercept": a, "se": se,
            "t": (b / se) if se and math.isfinite(se) and se > 0 else None,
            "corr": float(np.corrcoef(x, y)[0, 1]) if n > 2 else None}


def main() -> None:
    res = {"card": "T-223", "part": "B 第二族", "prereg": "docs/research/T-223_factor_family_2.md §1",
           "generated_at": datetime.now(timezone.utc).isoformat(), "factors": {}}

    # ---------------- G1 / G2 / G3:protocol_revenue_daily 的覆盖 ----------------
    rev_counts = {
        "all": count("/rest/v1/protocol_revenue_daily", []),
        "discovery_2023-01..2024-11": count("/rest/v1/protocol_revenue_daily",
                                            [("d", "gte.2023-01-01"), ("d", "lte.2024-11-30")]),
        "holdout_2025-01..2026-09": count("/rest/v1/protocol_revenue_daily",
                                          [("d", "gte.2025-01-01"), ("d", "lte.2026-09-26")]),
        "forward_2026-10-01..2026-10-07": count("/rest/v1/protocol_revenue_daily",
                                                 [("d", "gte.2026-10-01"), ("d", "lte.2026-10-07")]),
        "holders_24h_gt0": count("/rest/v1/protocol_revenue_daily", [("holders_24h", "gt.0")]),
        "gecko_id_notnull": count("/rest/v1/protocol_revenue_daily", [("gecko_id", "not.is.null")]),
    }
    days = pull("/rest/v1/protocol_revenue_daily", [("select", "d"), ("order", "d.asc")], "d.asc",
                "rev_days")
    dmin, dmax = days["d"].iloc[0], days["d"].iloc[-1]
    n_days = days["d"].nunique()
    sample = pull("/rest/v1/protocol_revenue_daily",
                  [("select", "d,name,gecko_id,revenue_24h,revenue_30d,holders_24h,holders_30d"),
                   ("revenue_30d", "gt.0"), ("order", "d.asc,name.asc"), ("limit", "400")],
                  "d.asc,name.asc", "rev_sample")
    for tag in ("G1", "G2", "G3"):
        res["factors"][tag] = {
            "source": "protocol_revenue_daily",
            "table_min_d": dmin, "table_max_d": dmax, "table_n_days": int(n_days),
            "row_counts": rev_counts,
            "readable": False,
            "verdict": "读不到",
            "why": (f"该表最早 {dmin}、最晚 {dmax}(共 {n_days} 天);发现段(2023-01 → 2024-11)与"
                    f"留出段(2025-01 → 2026-09)落在数据区间之外 ⇒ 两段里都没有 G1/G2/G3 的因子值。"
                    f"按预注册不替换、不缩短段。"),
        }
    res["factors"]["G1"]["note"] = (f"口径所需的 protocol↔token 对应靠 gecko_id;"
                                     f"表里 gecko_id 非空的行 {rev_counts['gecko_id_notnull']} 行。")
    res["factors"]["G3"]["note"] = (f"holders_24h>0 的行 {rev_counts['holders_24h_gt0']} 行;样本里 holders 与 "
                                    f"revenue 是两列独立量(holders 是持币人数,不是持币人分到的收入),"
                                    f"「holders 对 total 的占比」这个口径在表里拼不出来。")
    res["rev_sample_head"] = sample.head(5).to_dict(orient="records")

    # ---------------- G4:市值 / 完全稀释 ----------------
    fdv_cols = {}
    for t in ("asset_mcap_daily", "cg_coin_mcap_daily"):
        fdv_cols[t] = count("/rest/v1/" + t, [])
    cand = {}
    for t in ("fdv_daily", "coin_supply", "cg_supply", "supply_daily", "circulating_supply",
              "token_supply", "coin_unlocks", "unlock_calendar", "cg_coins", "coin_registry",
              "registry_coins"):
        cand[t] = count("/rest/v1/" + t, [])
    fm = pull("/rest/v1/feature_matrix_daily", [("select", "d,f,has"), ("order", "d.desc"),
                                                 ("limit", "5")], "d.desc", "fm_sample")
    keys = sorted({k for s in fm["f"].head(5) if isinstance(s, str)
                   for k in (json.loads(s).keys() if s.strip().startswith("{") else [])})
    res["factors"]["G4"] = {
        "source": "asset_mcap_daily / cg_coin_mcap_daily + 供给源",
        "readable": False, "verdict": "读不到",
        "why": ("库里没有完全稀释供给(FDV)源:候选供给表全部不存在(404/0 行);"
                "asset_mcap_daily 与 cg_coin_mcap_daily 只有 price 与 mcap(可推出流通量 = mcap ÷ price,"
                "但那是流通量不是完全稀释量);feature_matrix_daily 的特征键里也没有 fdv。"
                "按预注册:拼不出 ⇒ 写「读不到」,不拿流通量顶替。"),
        "candidate_supply_tables": cand,
        "feature_matrix_keys": keys,
        "asset_mcap_rows": fdv_cols.get("asset_mcap_daily"),
        "cg_coin_mcap_rows": fdv_cols.get("cg_coin_mcap_daily"),
    }

    # ---------------- G5:稳定币供给 30 天变化(时间因子) ----------------
    daily, monthly = g5_series()
    mk = json.loads((HERE / "t223_results.json").read_text())
    mkt = pd.DataFrame(mk["market_monthly"])
    mkt["m"] = mkt["m"].astype(str)
    df_m = monthly[(monthly["m"] >= "2023-01") & (monthly["m"] <= "2026-09")]
    df_m = df_m[df_m["n_obs"] >= 10]
    tbl = df_m.merge(mkt[["m", "uni_mean_y", "btc_ret30", "n_days"]], on="m", how="inner")
    tbl = tbl.sort_values("m").reset_index(drop=True)

    g5 = {"source": "state_daily(entity='panel', feature='stable_supply_30d')",
          "definition": "F_m = 该月该特征的月内均值(观测 ≥ 10 天);R_m = 宇宙均值 y 的月内平均",
          "series_range": [str(daily["d"].iloc[0]), str(daily["d"].iloc[-1])],
          "series_n": int(len(daily)), "segments": {}}
    for seg, (a, b) in SEG.items():
        t = tbl[(tbl["m"] >= a) & (tbl["m"] <= b)].copy()
        if t.empty:
            g5["segments"][seg] = {"n_months": 0}
            continue
        med = float(t["F"].median())
        t["s"] = np.where(t["F"] > med, 1.0, -1.0)
        t["signR"] = np.sign(t["uni_mean_y"])
        t["a"] = t["s"] * t["signR"]
        t = t[t["uni_mean_y"] != 0]
        agr = t["a"].to_numpy()
        rows = [{"m": r.m, "F": round(float(r.F), 6), "R_uni": round(float(r.uni_mean_y), 6),
                 "R_btc": round(float(r.btc_ret30), 6), "s": int(r.s), "a": int(r.a)}
                for r in t.itertuples()]
        nw5 = newey_west_t(agr.tolist(), lags=5)
        nw2 = newey_west_t(agr.tolist(), lags=2)
        nw1 = newey_west_t(agr.tolist(), lags=1)
        agree = float((agr > 0).mean()) if len(agr) else float("nan")
        ols = ols_slope(t["F"].to_numpy(), t["uni_mean_y"].to_numpy())
        # 稳健性(只报、不改判定):把因子整体往前挪一个月(F_{m-1} 配 R_m)—— 月内同期对齐 vs 事前一月
        lag = t.sort_values("m").copy()
        lag["F_prev"] = lag["F"].shift(1)
        lag = lag.dropna(subset=["F_prev"])
        lag1 = None
        if len(lag) >= 8:
            med_l = float(lag["F_prev"].median())
            lag["s"] = np.where(lag["F_prev"] > med_l, 1.0, -1.0)
            lag = lag[lag["uni_mean_y"] != 0]
            agr_l = (lag["s"] * np.sign(lag["uni_mean_y"])).to_numpy()
            lag1 = {"n_months": int(len(lag)), "F_prev_median": med_l,
                    "nw_t_lag5": newey_west_t(agr_l.tolist(), lags=5)[0],
                    "sign_agree_rate": float((agr_l > 0).mean()) if len(agr_l) else None}
        g5["segments"][seg] = {
            "months": f"{a}..{b}", "n_months": int(len(t)), "F_median": med,
            "nw_t_lag5": nw5[0], "nw_t_lag2": nw2[0], "nw_t_lag1": nw1[0],
            "mean_agreement": float(np.mean(agr)) if len(agr) else None,
            "sign_agree_rate": agree,
            "ols_R_on_F": ols,
            "lag1_Fprev": lag1,
            "table": rows,
        }
    disc = g5["segments"].get("discovery", {})
    hold = g5["segments"].get("holdout", {})
    t_d = disc.get("nw_t_lag5")
    t_h = hold.get("nw_t_lag5")
    shortlist = bool(t_d is not None and abs(t_d) >= 3)
    if not shortlist:
        verdict = "未过发现段(|NW t| < 3)⇒ 不进短名单,不判 ✅/❌"
    elif t_h is None:
        verdict = "进短名单,但留出段无值 ⇒ 读不到"
    else:
        same_sign = (t_d > 0) == (t_h > 0)
        ok = same_sign and abs(t_h) >= 2 and hold.get("sign_agree_rate", 0) >= 0.60
        verdict = ("✅ 留出段过" if ok else "❌ 留出段不过") + \
                  f"(同号={same_sign},|t|={abs(t_h):.2f},同号月份={hold.get('sign_agree_rate', 0):.0%})"
    g5["verdict"] = verdict
    g5["shortlisted_in_discovery"] = shortlist
    res["factors"]["G5"] = g5

    # ---------------- G6:交易所净流入 ----------------
    cand6 = {}
    for t in ("exchange_netflow_daily", "exchange_flows_daily", "exchange_balance_daily",
              "exchange_reserve_daily", "netflow_daily", "flows_daily", "flow_daily",
              "onchain_flows_daily", "chain_flow_daily", "exchange_inflow_daily"):
        cand6[t] = count("/rest/v1/" + t, [])
    feats = pull("/rest/v1/state_daily", [("select", "entity,feature"), ("limit", "2000")],
                 "entity.asc,feature.asc", "state_feats")
    feat_list = sorted({f for f in feats["feature"].astype(str)})
    res["factors"]["G6"] = {
        "source": "state_daily / 链上流表",
        "readable": False, "verdict": "读不到",
        "why": ("state_daily 只有 entity='panel' 一个实体、23 个特征,里面没有交易所净流入;"
                "候选的净流入表全部不存在。asset_flow_daily 是按币的 11 维资金面(crowd/dd90/doi7/"
                "fund7/mom30/mom7/taker7/turn/vol30/vratio 等),不是交易所净流入 —— 不替换。"),
        "state_daily_features": feat_list,
        "candidate_tables": cand6,
    }

    res["readable_cross_sectional_factors"] = 0
    res["trial_count"] = {"family": "第二族(链上 / 发行方)", "cross_sectional_added": 6,
                          "time_series_added": 1,
                          "note": "G1–G6 共 6 个(G5 为时间序列,单列);读不到的也计入试验计数"}
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"[out  ] {OUT}")
    for tag in ("G1", "G2", "G3", "G4", "G6"):
        print(f"  {tag}: {res['factors'][tag]['verdict']}")
    print(f"  G5: {g5['verdict']}")
    for seg in ("discovery", "holdout"):
        s = g5["segments"][seg]
        print(f"    {seg}: n_months={s.get('n_months')} NW t(lag5)={s.get('nw_t_lag5')} "
              f"同号月占比={s.get('sign_agree_rate')} ols_slope={s.get('ols_R_on_F', {}).get('slope')}")


if __name__ == "__main__":
    main()
