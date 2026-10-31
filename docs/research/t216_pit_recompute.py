#!/usr/bin/env python3
"""T-216 · T-005 预注册台账返工 —— 价格 PIT 口径重算(F1/F3)+ β 带实测分布(F1)。

只读:Mac 数据根(research/vdb_tilt/*.csv、_cache/b1_daily_nav.json、data/ohlcv/*.parquet)
      + Supabase 守护库 ohlcv_daily(publishable 只读)。
不读 .env;不打印 key/token;不改任何对方文件;**不跑 24 格**(卡面:只读、不跑批)。

口径全部写死在脚本里(先写定、跑完不许改):
  regime PIT : RISK_OFF(d) := close_BTC(d-lag) < MA200_BTC(d-lag)
               MA200 = 200 根日线滚动均值(源各自的日历密度见输出)
               取值用 as-of(只取 ≤ d-lag 的最后一个观测),不用未来值
  窗口 W_sv  : state_vectors_1000d.csv ∩ phases_7d.csv(2023-12-26 → 2026-09-21)
  窗口 W_run : harness 口径(有 B1 NAV 且面板覆盖 ≥18/24)——实际可跑日历天
  有效日(预注册 §2.6 三条同时成立):
     ① d-lag 有 MA200 判据(预热期内记 NA,不静默当 False)
     ② 面板 24 币当日有行情的币数 ≥ K
     ③ phase 已知(phases_7d.csv 有该日且 final_phase 非空)
  split      : 按窗口下标切(IS = 前 p·N,OOS = 后段)
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pandas as pd

D = Path("/Volumes/CometCloudAI/cometcloud-local/research/vdb_tilt")
PARQ = Path("/Volumes/CometCloudAI/data/ohlcv")
OUT = Path(__file__).with_suffix(".json")

PANEL_24 = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "ADA", "AVAX", "DOGE", "ARB", "OP",
    "NEAR", "APT", "UNI", "AAVE", "MKR",
    "LINK", "ONDO", "DOT", "INJ", "ATOM",
    "CRV", "LDO", "COMP", "GRT",
]

REPORT: dict = {"meta": {}, "inputs": {}, "windows": {}, "v5": {}, "pit": {}, "beta": {}}


# ---------------------------------------------------------------- Supabase 只读
def supa(table: str, query: str) -> list[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY —— 退出")
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?{query}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode())


def supa_count(table: str, query: str) -> int:
    """Prefer: count=exact —— 拿服务端行数(分页完整性核对用)。"""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?{query}&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"},
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else -1


def supa_all(table: str, query: str, page: int = 1000) -> list[dict]:
    """翻页读全量(PostgREST db-max-rows 默认 1000 —— 一次 limit=200000 只拿到前 1000 行)。"""
    out: list[dict] = []
    offset = 0
    while True:
        rows = supa(table, f"{query}&limit={page}&offset={offset}")
        if not rows:
            break
        out.extend(rows)
        offset += len(rows)
        if len(rows) < page:
            break
    return out


def daily_from_parquet(sym: str) -> pd.Series:
    fp = PARQ / f"{sym}.parquet"
    if not fp.exists():
        return pd.Series(dtype="float64")
    raw = pd.read_parquet(fp)
    tcol = next((c for c in ("timestamp", "ts", "open_time", "time", "date") if c in keys_of(raw)), None)
    raw[tcol] = pd.to_datetime(raw[tcol], utc=True)
    s = raw.set_index(tcol)["close"].resample("1D").last().dropna()
    idx = s.index
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")]


def keys_of(df) -> list[str]:
    return list(df.columns)


# ---------------------------------------------------------------- 0. 输入清点
sv = pd.read_csv(D / "state_vectors_1000d.csv")
sv["date"] = sv["date"].astype(str).str[:10]
ph = pd.read_csv(D / "phases_7d.csv")
ph["date"] = ph["date"].astype(str).str[:10]

b1_raw = json.loads((D / "_cache" / "b1_daily_nav.json").read_text())
dn = b1_raw["daily_nav"] if isinstance(b1_raw, dict) and "daily_nav" in b1_raw else b1_raw
if isinstance(dn, list):
    k = "date" if "date" in dn[0] else list(dn[0].keys())[0]
    b1_dates = sorted({str(r.get(k))[:10] for r in dn})
else:
    b1_dates = sorted({str(k)[:10] for k in dn})

panel = {s: daily_from_parquet(s) for s in PANEL_24}
all_days = sorted(set().union(*[set(s.index) for s in panel.values() if len(s)]))
panel_cov = pd.Series(0, index=pd.Index(all_days, name="date"))
for s in panel.values():
    if len(s):
        panel_cov = panel_cov.add(pd.Series(1, index=s.index), fill_value=0)
panel_cov = panel_cov.astype(int)

REPORT["inputs"] = {
    "state_vectors_1000d.csv": {
        "rows": int(len(sv)), "first": sv["date"].min(), "last": sv["date"].max(),
        "data_status_counts": sv["data_status"].value_counts(dropna=False).to_dict(),
    },
    "phases_7d.csv": {
        "rows": int(len(ph)), "first": ph["date"].min(), "last": ph["date"].max(),
        "final_phase_counts": ph["final_phase"].value_counts(dropna=False).to_dict(),
    },
    "b1_daily_nav.json": {"rows": int(len(b1_dates)), "first": b1_dates[0], "last": b1_dates[-1]},
    "parquet_24": {
        s: ({"first": str(v.index[0].date()), "last": str(v.index[-1].date()), "n": int(len(v))}
            if len(v) else None)
        for s, v in panel.items()
    },
}

# ---------------------------------------------------------------- 1. 窗口
sv_ph = sorted(set(sv["date"]) & set(ph["date"]))
W_sv = sv_ph                                   # 状态向量 ∩ phases
W_b1 = sorted(set(W_sv) & set(b1_dates))        # 再交 B1
harness_like = [d for d in W_b1 if panel_cov.get(d, 0) >= 18]
REPORT["windows"] = {
    "W_sv": {"n": len(W_sv), "first": W_sv[0], "last": W_sv[-1]},
    "W_b1": {"n": len(W_b1), "first": W_b1[0], "last": W_b1[-1]},
    "harness_like_cov_ge_18": {"n": len(harness_like), "first": harness_like[0], "last": harness_like[-1]},
    "panel_cov_over_W_b1": {
        "mean": float(panel_cov.reindex(W_b1).mean()),
        "min": int(panel_cov.reindex(W_b1).min()), "max": int(panel_cov.reindex(W_b1).max()),
        "days_lt_19": int((panel_cov.reindex(W_b1) < 19).sum()),
    },
}

# ---------------------------------------------------------------- 1b. 守护库覆盖(选源三源)
SOURCES = ["coingecko", "binance_hist", "coingecko_pro_ohlc"]
cover = {}
for sym in PANEL_24:
    cover[sym] = {}
    for src in SOURCES:
        f = f"symbol=eq.{sym}&source=eq.{src}"
        n = supa_count("ohlcv_daily", f)
        if n <= 0:
            continue
        first = supa("ohlcv_daily", f"select=trade_date&{f}&order=trade_date.asc&limit=1")
        last = supa("ohlcv_daily", f"select=trade_date&{f}&order=trade_date.desc&limit=1")
        cover[sym][src] = {
            "n": n,
            "first": str(first[0]["trade_date"])[:10] if first else None,
            "last": str(last[0]["trade_date"])[:10] if last else None,
        }
REPORT["inputs"]["guard_db_panel_cover"] = cover
cut = "2021-01-05"
have = sorted(s for s, d in cover.items() if any(v["first"] <= cut for v in d.values()))
REPORT["inputs"]["guard_db_panel_from_2021_01_05"] = {
    "n_with_data": len(have), "missing": sorted(set(PANEL_24) - set(have)),
}
# 同键三源:BTC 三个源在同一交易日的收盘是否一致
btc_srcs = {k: v for k, v in cover.get("BTC", {}).items()}
if len(btc_srcs) >= 2:
    q = ("select=trade_date,close,source&symbol=eq.BTC"
         "&source=in.(%s)&order=trade_date.asc" % ",".join(f'"{s}"' for s in btc_srcs))
    rows = supa_all("ohlcv_daily", q)
    dfb = pd.DataFrame(rows)
    dfb["trade_date"] = dfb["trade_date"].astype(str).str[:10]
    piv = dfb.pivot_table(index="trade_date", columns="source", values="close", aggfunc="last")
    piv = piv.dropna(how="all")
    spread = {}
    for a in piv.columns:
        for b in piv.columns:
            if a >= b:
                continue
            both = piv[[a, b]].dropna()
            if len(both):
                rel = ((both[a] - both[b]) / both[b] * 100).abs()
                spread[f"{a}_vs_{b}"] = {
                    "n_both": int(len(both)),
                    "last_date": str(both.index[-1]), "max_rel_pct": float(rel.max()),
                    "mean_rel_pct": float(rel.mean()),
                    "last_rel_pct": float(rel.iloc[-1]),
                }
    REPORT["inputs"]["btc_three_source_spread"] = spread

# ---------------------------------------------------------------- 2. V5 现状基线(harness 现在读的那套)
m = sv.set_index("date")
p = ph.set_index("date")
regime_v5 = m["V5_macro_regime"].reindex(W_b1)
phase = p["final_phase"].reindex(W_b1)
risk_v5 = regime_v5.isin(["RISK_OFF", "STAGFLATION"])
cash_phase = phase.fillna("NA") == "CASH"
live_v5 = (~risk_v5) & (~cash_phase)

v5_splits = {}
for pct in (0.60, 0.50, 0.70):
    idx = int(len(W_b1) * pct)
    oos = W_b1[idx:]
    v5_splits[f"{int(pct*100)}/{100-int(pct*100)}"] = {
        "is_n": idx, "oos_n": len(oos),
        "v5_risk_days_total": int(risk_v5.sum()),
        "v5_risk_days_oos": int(risk_v5.reindex(oos).sum()),
        "v5_live_days_total": int(live_v5.sum()),
        "v5_live_days_oos": int(live_v5.reindex(oos).sum()),
        "phase_cash_days_oos": int(cash_phase.reindex(oos).sum()),
        "risk_and_cash_oos": int((risk_v5 & cash_phase).reindex(oos).sum()),
        "identity_1_minus_risk_over_oos": 1.0 - risk_v5.reindex(oos).sum() / len(oos),
    }
REPORT["v5"] = {
    "regime_counts_on_W_b1": regime_v5.value_counts(dropna=False).to_dict(),
    "phase_counts_on_W_b1": phase.value_counts(dropna=False).to_dict(),
    "risk_days_total": int(risk_v5.sum()), "live_days_total": int(live_v5.sum()),
    "splits": v5_splits,
}

# ---------------------------------------------------------------- 3. 价格 PIT 重算
btc_parq = daily_from_parquet("BTC")
ma_src: dict[str, pd.Series] = {"local_parquet": btc_parq}

probe = supa("ohlcv_daily", "select=*&symbol=eq.BTC&order=symbol.asc,trade_date.asc&limit=1")
keys = sorted(probe[0].keys()) if probe else []
src_col = next((c for c in ("source", "data_source", "provider", "feed") if c in keys), None)
close_col = next((c for c in ("close", "close_price", "c") if c in keys), None)
REPORT["inputs"]["ohlcv_daily_columns"] = keys
if src_col and close_col:
    q = (f"select=symbol,trade_date,{close_col},{src_col}"
         f"&symbol=eq.BTC&order=symbol.asc,trade_date.asc")
    n_total = supa_count("ohlcv_daily", f"symbol=eq.BTC")
    rows = supa_all("ohlcv_daily", q)
    REPORT["inputs"]["btc_guard_db_rows"] = {"server_count": n_total, "read": len(rows)}
    df = pd.DataFrame(rows)
    df["trade_date"] = df["trade_date"].astype(str).str[:10]
    for src, g in df.groupby(src_col):
        s = g.drop_duplicates("trade_date").set_index("trade_date")[close_col].astype(float).sort_index()
        s.index = pd.to_datetime(s.index)
        ma_src[f"guard_db:{src}"] = s
REPORT["inputs"]["ma_sources"] = {
    k: {"n": int(len(v)), "first": str(v.index[0].date()), "last": str(v.index[-1].date()),
        "rows_per_year": round(len(v) / max((v.index[-1] - v.index[0]).days / 365.25, 1e-9), 1)}
    for k, v in ma_src.items()
}

PHASE_KNOWN = phase.notna() & (phase.astype(str).str.strip() != "")


def pit_counts(series: pd.Series, dates: list[str], lag: int, K: int) -> dict:
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    ma = s.rolling(200).mean()
    probe_dates = pd.to_datetime(pd.Series(dates)) - pd.Timedelta(days=lag)
    left = pd.DataFrame({"d": probe_dates}).sort_values("d").reset_index(drop=True)
    left["d"] = left["d"].astype("datetime64[ns]")
    right = pd.DataFrame({"d": s.index, "close": s.values, "ma200": ma.values})
    right["d"] = right["d"].astype("datetime64[ns]")
    j = pd.merge_asof(left, right, on="d", direction="backward")
    crit = j["ma200"].notna()
    risk = crit & (j["close"] < j["ma200"])
    ex = pd.DataFrame({"date": dates, "crit": crit.values, "risk": risk.values})
    ex["cov"] = panel_cov.reindex(ex["date"]).fillna(0).astype(int).values
    ex["phase_known"] = PHASE_KNOWN.reindex(ex["date"]).fillna(False).values
    ex["phase_cash"] = cash_phase.reindex(ex["date"]).fillna(False).values
    ex["valid"] = ex["crit"] & (ex["cov"] >= K) & ex["phase_known"]
    ex["live"] = ex["crit"] & (~ex["risk"]) & (~ex["phase_cash"])
    out = {
        "lag": lag, "K": K, "days": int(len(ex)),
        "criterion_days": int(ex["crit"].sum()),
        "risk_off_days": int(ex["risk"].sum()),
        "valid_days": int(ex["valid"].sum()),
        "live_days": int(ex["live"].sum()),
        "risk_off_and_phase_not_cash": int((ex["risk"] & ~ex["phase_cash"]).sum()),
        "splits": {},
    }
    for pct in (0.60, 0.50, 0.70):
        idx = int(len(ex) * pct)
        oos = ex.iloc[idx:]
        out["splits"][f"{int(pct*100)}/{100-int(pct*100)}"] = {
            "is_n": idx, "oos_n": int(len(oos)),
            "valid_is": int(ex["valid"].iloc[:idx].sum()),
            "valid_oos": int(oos["valid"].sum()),
            "live_is": int(ex["live"].iloc[:idx].sum()),
            "live_oos": int(oos["live"].sum()),
            "risk_oos": int(oos["risk"].sum()),
            "phase_cash_oos": int(oos["phase_cash"].sum()),
            "risk_off_and_phase_not_cash_oos": int((oos["risk"] & ~oos["phase_cash"]).sum()),
        }
    return out


pit = {}
for src_name, series in ma_src.items():
    for K in (19, 18):
        for lag in (1, 3, 7):
            pit[f"{src_name}|K{K}|lag{lag}"] = pit_counts(series, W_b1, lag, K)
for src_name in ("guard_db:binance_hist", "local_parquet"):
    if src_name in ma_src:
        pit[f"{src_name}|K19|lag1|W_sv"] = pit_counts(ma_src[src_name], W_sv, 1, 19)
# harness 实际窗口:837 天里去掉首日(2024-06-07,NAV 首日无前值)⇒ 836 天,idx=501
W_run = [d for d in W_b1 if d >= "2024-06-08"]
REPORT["windows"]["W_run_836"] = {"n": len(W_run), "first": W_run[0], "last": W_run[-1]}
for src_name in ("guard_db:binance_hist", "local_parquet"):
    if src_name in ma_src:
        for lag in (1, 3, 7):
            pit[f"{src_name}|K19|lag{lag}|W_run836"] = pit_counts(ma_src[src_name], W_run, lag, 19)
REPORT["pit"] = pit

# ---------------------------------------------------------------- 3b. 90 vs 88 对齐
idx60 = int(len(W_b1) * 0.60)
oos60 = W_b1[idx60:]
oos_df = pd.DataFrame({"date": oos60})
oos_df["phase_cash"] = cash_phase.reindex(oos60).fillna(False).values
oos_df["risk_v5"] = risk_v5.reindex(oos60).fillna(False).values
oos_df["regime"] = regime_v5.reindex(oos60).values
gap_days = oos_df[(~oos_df["phase_cash"]) & oos_df["risk_v5"]]
REPORT["v5_vs_90_88"] = {
    "window_days": len(W_b1), "split_idx_60": idx60, "oos_days": len(oos60),
    "oos_phase_cash_days": int(oos_df["phase_cash"].sum()),
    "oos_phase_not_cash_days": int((~oos_df["phase_cash"]).sum()),
    "oos_risk_days": int(oos_df["risk_v5"].sum()),
    "oos_risk_and_cash_days": int((oos_df["risk_v5"] & oos_df["phase_cash"]).sum()),
    "oos_live_days": int((~oos_df["phase_cash"] & ~oos_df["risk_v5"]).sum()),
    "gap_days_phase_not_cash_but_risk": gap_days["date"].tolist(),
    "gap_days_regime": gap_days["regime"].tolist(),
    "identity_avg_cash_observed": 0.7313432835820896,
    "identity_245_over_335": 245 / 335,
    "identity_1_minus_90_over_335": 1 - 90 / 335,
    "identity_1_minus_88_over_335": 1 - 88 / 335,
    "identity_187_over_335_risk_only": 187 / 335,
}

# ---------------------------------------------------------------- 3c. 加仓机制 / lag 轴:代码里有没有
grep_hits = {}
for kw in ("w_add", "add_size", "add_w", "MA200", "ma200", "add_threshold"):
    n = 0
    files = []
    for fp in sorted(D.glob("*.py")):
        txt = fp.read_text(errors="ignore")
        c = txt.count(kw)
        if c:
            n += c
            files.append(f"{fp.name}:{c}")
    grep_hits[kw] = {"total": n, "files": files}
REPORT["code_grep"] = grep_hits

# ---------------------------------------------------------------- 4. β 带实测分布
res = pd.read_csv(D / "results_real_v2.tsv", sep="\t")
beta = {}
for pref, g in res.groupby("prefix"):
    b = g["beta_to_b1"]
    inband = int(((b >= 0.5) & (b <= 0.9)).sum())
    beta[str(pref)] = {
        "n": int(len(g)),
        "beta_min": float(b.min()), "beta_max": float(b.max()), "beta_mean": float(b.mean()),
        "avg_cash_pct_mean": float(g["avg_cash_pct"].mean()) if "avg_cash_pct" in g.columns else None,
        "in_band_0.5_0.9": inband, "in_band_frac": inband / len(g),
    }
REPORT["beta"] = {"total_rows": int(len(res)), "by_prefix": beta}

# ---------------------------------------------------------------- 输出
OUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=1))
print(json.dumps(REPORT, ensure_ascii=False, indent=1))
