"""T-191 —— 崩盘图谱三道补判(S-675):三套锚点(primary / 破位日 / 急跌起点)各判一次线索。

起因(Seth 10-24 开卡,lane-b 10-24 §B-auto-1024-1213 ③-1):T-185(发达市场)/ T-186(EM)/ T-187(crypto)
三道都只对**主锚点**判了线索;协议 S-675 的锚点 = 主 + 辅(破位日 30 天、急跌起点 30 天)。
三道的 json 里其实已经记了辅锚点的读数(pctile / lift / 锚点数 / 前后两半命中率),只是没按线索判据重判。
lane-b 在 T-187 上发现 M8(VIX/VXV 倒挂)在「急跌起点」这套锚点上四项全过。

**只读三道的结果 json**(`t185_results.json` / `t186_results.json` / `t187_results.json`),
**不重抓数据、不改三道的原脚本**。本脚本只有两处新增的外部读取:
  1. FRED 本地快照(Mac 数据根 `research/crash_atlas/fred/`)里的 UMCSENT —— 情绪画像口径(a)要;
  2. Supabase 只读(`asset_mcap_daily` / `style_index_pit_daily`)—— 风格表的「同 5 锚点随机 5 天」对照(c)要重建风格净值。

零分布 / 分位一律走 `src/data/evaluation/apparatus.py`(不自己再写一遍)。

判据(S-675 写死,四同时成立才算线索):
  分位(pctile) ≥ 0.95 · 提升(lift) ≥ 1.5 · 锚点数 ≥ 6 · 前后两半命中率都 > 基准率。
与崩盘定义同源的迹象照报读数,但标「同源,不算线索」。

**本脚本不产生任何可交易规则;线索只进候选名单。**
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from docs.research.crash_atlas_common import (  # noqa: E402
    available,
    load_fred,
    phase_returns,
    to_calendar,
    trend_200_nav,
)

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
FRED_DIR = os.path.join(DATA_ROOT, "research", "crash_atlas", "fred")
REPORT_PATH = os.path.join(DATA_ROOT, "_reports", "absorb_input", "T-191_anchor_rejudge.md")
OUT_JSON = os.path.join(HERE, "t191_results.json")

SEED = 675
N_SHIFT_NOTE = "pctile 来自三道各自跑好的零分布(n_shift=2000),本脚本不重算"

# ── 线索判据(S-675)──────────────────────────────────────────────────────────
CRIT_PCTILE = 0.95
CRIT_LIFT = 1.5
CRIT_MIN_ANCHORS = 6

# ── 三套锚点(统一命名)───────────────────────────────────────────────────────
FAMILIES = ("primary_90d", "aux_break_30d", "aux_fastcrash_30d")
FAMILY_CN = {
    "primary_90d": "主锚点(前高,回看 90 天)",
    "aux_break_30d": "辅锚点一(破位日,回看 30 天)",
    "aux_fastcrash_30d": "辅锚点二(急跌起点,回看 30 天)",
}
# 每道自己的锚点集名 → 统一三套
FAMILY_MAP = {
    "T-185": {"main": "primary_90d", "aux_break": "aux_break_30d", "aux_fast": "aux_fastcrash_30d"},
    "T-186": {"eem_peak_first_leg_90d": "primary_90d", "eem_break_30d": "aux_break_30d",
              "eem_fast_30d": "aux_fastcrash_30d"},
    "T-187": {"primary_90d": "primary_90d", "aux_break_30d": "aux_break_30d",
              "aux_fastcrash_30d": "aux_fastcrash_30d"},
}

T187_LABELS = {
    "P1_ret252_pct_ge90": "过去 252 天收益分位 ≥ 0.9(亢奋)",
    "P2_px_over_ma200_pct_ge90": "价格/MA200−1 分位 ≥ 0.9",
    "P3_rv20_pct_le10": "20 日实现波动分位 ≤ 0.1",
    "P4_rv20_pct_ge90": "20 日实现波动分位 ≥ 0.9(动荡)",
    "P5_dd52w_ge5pct_above_ma200": "距 52 周高点 ≥ 5% 但仍在 200 日线上(初裂)",
    "M1_ffr_12m_up_ge1pp": "联邦基金利率 12 个月升 ≥ 1pp",
    "M2_10y2y_lt0": "10Y−2Y < 0(倒挂)",
    "M3_10y2y_gt0_after_inversion": "10Y−2Y > 0 且过去 365 天倒挂过(解除倒挂)",
    "M4_nfci_gt0": "NFCI > 0",
    "M5_baa10y_63d_up_ge0p5pp": "Baa−10Y 利差 63 天升 ≥ 0.5pp",
    "M6_vix_lt13": "VIX < 13",
    "M7_vix_gt30": "VIX > 30",
    "M8_vix_over_vxv_gt1": "VIX / VXV > 1(期限结构倒挂)",
    "M9_usd_broad_63d_chg_pct_ge90": "美元广义指数 63 天变化分位 ≥ 0.9",
    "M10_wti_126d_up_ge50pct": "WTI 126 天涨 ≥ 50%",
    "M11_fed_balance_91d_shrink": "美联储资产负债表 91 天缩",
    "M12_umcsent_pct_ge80": "密歇根消费者信心分位 ≥ 0.8",
    "M13_icsa_ma4_13w_up_ge15pct": "初请 4 周均值 13 周升 ≥ 15%",
    "C1_fng_ge75_7d": "恐惧贪婪 ≥ 75 连续 ≥ 7 天",
    "C2_btc_funding_ann_7d_ge30pct": "BTC 资金费 7 日均年化 ≥ 30%",
    "C3_btc_oi_30d_growth_pct_ge90": "BTC 持仓量 30 天增长分位 ≥ 0.9",
    "C4_stables_30d_growth_lt0": "USDT+USDC 市值 30 天增长 < 0",
    "C5_btc_share_60d_drop_ge10pp": "BTC 市值份额 60 天降 ≥ 10pp",
    "C6_total_vol_30d_mean_pct_ge90": "总成交量 30 天均值分位 ≥ 0.9",
}

ALT_STYLES = ["defi", "second_l1_l2", "infra_tokenization", "ai", "app"]
STYLE_CN = {
    "BTC_hold": "BTC 持有",
    "BTC_trend200_nav": "BTC 200 日趋势(未触发时持现金)",
    "X1V_trade_path_rally_l20": "X1V(信号引擎,只读 import)",
    "ETH_hold": "ETH 持有",
    "ALT_sector_EW_nav": "山寨板块 EW 指数(五板块等权)",
    "BTC_over_ALT": "BTC 相对山寨",
}

SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
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


def srs(rows: list[dict], x: str, y: str) -> pd.Series:
    idx = pd.to_datetime([r[x] for r in rows], format="ISO8601", utc=True).tz_localize(None).normalize()
    s = pd.Series(pd.to_numeric([r[y] for r in rows], errors="coerce"), index=idx, dtype="float64").dropna()
    return s.groupby(level=0).last().sort_index()


def load_json(name: str) -> dict:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


# ── 判定 ────────────────────────────────────────────────────────────────────
def judge(task: str, sign: str, label: str, family: str, anchor_set: str, lookback: int,
          r: dict, half1: Optional[float], half2: Optional[float], same_source: bool) -> dict:
    pctile, lift, n = r.get("pctile"), r.get("lift"), r.get("n_anchors")
    base = r.get("base_rate")
    c_pctile = bool(pctile is not None and pctile >= CRIT_PCTILE)
    c_lift = bool(lift is not None and lift >= CRIT_LIFT)
    c_n = bool(n is not None and n >= CRIT_MIN_ANCHORS)
    c_halves = bool(half1 is not None and half2 is not None and base is not None
                    and half1 > base and half2 > base)
    passed = bool(c_pctile and c_lift and c_n and c_halves)
    return {
        "task": task, "sign": sign, "label": label, "family": family, "anchor_set": anchor_set,
        "lookback": lookback, "n_anchors": n, "n_skipped": r.get("n_skipped"),
        "hit_rate": r.get("hit_rate"), "base_rate": base, "lift": lift,
        "null_p50": r.get("null_p50"), "pctile": pctile,
        "half1_hit_rate": half1, "half2_hit_rate": half2,
        "c_pctile": c_pctile, "c_lift": c_lift, "c_n_anchors": c_n, "c_halves": c_halves,
        "pass_raw": passed, "same_source": bool(same_source),
        "is_clue": bool(passed and not same_source),
    }


def rows_t185(d: dict) -> list[dict]:
    out = []
    for r in d["signals"]:
        fam = FAMILY_MAP["T-185"][r["anchor_set"]]
        out.append(judge("T-185", r["signal"], r.get("label", r["signal"]), fam, r["anchor_set"],
                         r["lookback"], r, r.get("hit_first"), r.get("hit_second"),
                         bool(r.get("same_source"))))
    return out


def rows_t186(d: dict) -> list[dict]:
    out = []
    meta = d["signals_meta"]
    for aname, rows in d["signal_table"].items():
        fam = FAMILY_MAP["T-186"].get(aname, "extra:" + aname)
        for sname, r in rows.items():
            out.append(judge("T-186", sname, meta.get(sname, {}).get("src", sname), fam, aname,
                             90 if "90d" in aname else 30, r, r.get("half1"), r.get("half2"),
                             bool(r.get("same_source"))))
    return out


def rows_t187(d: dict) -> list[dict]:
    out = []
    for sname, v in d["signs"].items():
        for fam in FAMILIES:
            r = v.get(fam)
            if not r:
                continue
            # T-187 的 json 没带 same_source 字段,按 T-185 / T-186 的同一口径补:
            # P4(动荡) / P5(初裂)在「破位日」「急跌起点」这两套锚点上就是崩点本身 ⇒ 同源
            same = sname.startswith(("P4", "P5")) and fam in ("aux_break_30d", "aux_fastcrash_30d")
            out.append(judge("T-187", sname, T187_LABELS.get(sname, sname), fam, fam,
                             90 if fam == "primary_90d" else 30, r,
                             r.get("half1_hit_rate"), r.get("half2_hit_rate"), same))
    return out


def per_sign_rollup(rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[(r["task"], r["sign"])].append(r)
    out = []
    for (task, sign), rs in by.items():
        fam_rows = [r for r in rs if r["family"] in FAMILIES]
        passed = [r["family"] for r in fam_rows if r["is_clue"]]
        raw = [r["family"] for r in fam_rows if r["pass_raw"]]
        out.append({
            "task": task, "sign": sign, "label": rs[0]["label"],
            "n_families_judged": len(fam_rows),
            "n_families_pass_raw": len(raw),
            "n_families_clue": len(passed),
            "families_pass_raw": raw, "families_clue": passed,
            "same_source_families": [r["family"] for r in fam_rows if r["same_source"]],
            "best_pctile": max((r["pctile"] for r in fam_rows if r["pctile"] is not None),
                               default=None),
            "best_lift": max((r["lift"] for r in fam_rows if r["lift"] is not None), default=None),
        })
    return out


# ── (a) 情绪画像口径:补 UMCSENT ────────────────────────────────────────────
def umcsent_profile(t187: dict) -> dict:
    """T-187 的情绪画像第三行报的是 BTC 资金费,协议(S-675)写的是消费者信心 UMCSENT。
    这里用本地 FRED 快照经 available()(UMCSENT 属期是月初、终值月底发布 ⇒ 滞后 31 天)补上 UMCSENT,
    口径与 T-187 的 fng / vix 一致:每个崩盘段的 顶前 90 / 顶前 30 / 顶 / 谷底 读数,跨段取中位。"""
    umc_raw = load_fred("UMCSENT", FRED_DIR)
    umc = to_calendar(available(umc_raw, "UMCSENT"), 40)
    s = umc.dropna().sort_index()

    def at(d: pd.Timestamp) -> Optional[float]:
        sub = s[s.index <= d]
        return float(sub.iloc[-1]) if len(sub) else None

    eps = t187["sentiment"]["fng"]["per_episode"]
    rows = []
    for e in eps:
        pk, tr = pd.Timestamp(e["peak_d"]), pd.Timestamp(e["trough_d"])
        rows.append({"peak_d": e["peak_d"], "trough_d": e["trough_d"], "first_leg": e["first_leg"],
                     "d90": at(pk - pd.Timedelta(days=90)), "d30": at(pk - pd.Timedelta(days=30)),
                     "peak": at(pk), "trough": at(tr)})
    first = [r for r in rows if r["first_leg"]]

    def med(rr, k):
        vals = [r[k] for r in rr if r[k] is not None]
        return float(np.median(vals)) if vals else None

    return {
        "series": "UMCSENT(密歇根消费者信心;FRED 属期月初、终值月底发布 ⇒ available() 滞后 31 天;"
                   "to_calendar 上限 40 天)",
        "raw_monthly_span": [str(umc_raw.index.min().date()), str(umc_raw.index.max().date())],
        "raw_monthly_obs": int(len(umc_raw)),
        "raw_monthly_nonnull": int(umc_raw.notna().sum()),
        "daily_expanded_span": [str(s.index.min().date()), str(s.index.max().date())],
        "daily_expanded_nonnull": int(len(s)),
        "release_lag_days": 31,
        "data_span": [str(s.index.min().date()), str(s.index.max().date())],
        "n_obs": int(len(umc_raw)),
        "per_episode": rows,
        "median_first_leg": {k: med(first, k) for k in ("d90", "d30", "peak", "trough")},
        "median_all": {k: med(rows, k) for k in ("d90", "d30", "peak", "trough")},
        "t187_reported_rows": {k: v["median_first_leg"] for k, v in t187["sentiment"].items()},
        "t187_sentiment_labels": {"fng": "恐惧贪婪指数(fng)", "vix": "VIX",
                                  "btc_funding_annualized": "BTC 资金费(年化)"},
    }


# ── (b) 事件计数:去重后重算 ────────────────────────────────────────────────
def events_recompute(t187: dict) -> dict:
    ev = t187["events"]
    cat = ev["catalog"]
    wins = ev["windows"]
    rows_total = sum(w["n_events"] for w in wins)
    per_url = defaultdict(list)
    for w in wins:
        for e in w["events"]:
            per_url[e["url"]].append({"window": w["window"], "anchor_d": w["anchor_d"],
                                      "anchor_kind": w["anchor_kind"], "date": e["date"]})
    uniq_in = {u: v for u, v in per_url.items()}
    by_url = {e["url"]: e for e in cat}
    dup = {u: v for u, v in uniq_in.items() if len(v) > 1}
    cat_uniq = Counter(e["cat"] for e in cat)
    cat_in_window = Counter(by_url[u]["cat"] for u in uniq_in if u in by_url)
    cat_out_window = Counter(by_url[u]["cat"] for u in by_url if u not in uniq_in)
    # 窗口行数 → 去重事件数 的桥:跨窗口重复 + 同窗口重复(两个窗口边界相同 ⇒ 同一段事件算了两遍)
    pairs = Counter()
    for w in wins:
        for e in w["events"]:
            pairs[(w["anchor_kind"], w["anchor_d"], w["window"][0], w["window"][1], e["url"])] += 1
    same_win_dup = {k: n for k, n in pairs.items() if n > 1}
    win_bounds = Counter((w["anchor_kind"], w["anchor_d"], w["window"][0], w["window"][1])
                          for w in wins)
    dup_bounds = [{"anchor_kind": k[0], "anchor_d": k[1], "window": [k[2], k[3]],
                   "n_windows_with_same_bounds": n} for k, n in win_bounds.items() if n > 1]
    cross_window_repeats = sum(len(v) - 1 for v in uniq_in.values())
    # 边界相同但锚点类型不同(如同一根锚点既是 first_leg_peak 又是 fast_crash_start)⇒ 是两个不同的窗口
    _by_bounds: dict = defaultdict(list)
    for w in wins:
        _by_bounds[(w["anchor_d"], w["window"][0], w["window"][1])].append(
            {"anchor_kind": w["anchor_kind"]})
    return {
        "n_catalog": ev["n_catalog"], "n_catalog_recomputed": len(cat),
        "n_distinct_urls_in_catalog": len({e["url"] for e in cat}),
        "n_windows": len(wins), "window_rows_total": rows_total,
        "distinct_window_url_pairs": len(pairs),
        "same_window_duplicate_rows": sum(n - 1 for n in same_win_dup.values()),
        "n_events_in_multiple_windows": len(dup),
        "cross_window_repeat_rows": cross_window_repeats,
        "duplicate_window_bounds": dup_bounds,
        "unique_events_in_windows": len(uniq_in),
        "duplicate_rows": rows_total - len(uniq_in),
        "multi_window_events": [
            {"date": by_url[u]["date"], "cat": by_url[u]["cat"], "title": by_url[u]["title"],
             "in_windows": [{"kind": x["anchor_kind"], "anchor_d": x["anchor_d"],
                             "window": x["window"]} for x in v], "n_windows": len(v)}
            for u, v in sorted(dup.items(), key=lambda kv: by_url[kv[0]]["date"])],
        "same_bounds_diff_kind": sorted(
            [{"anchor_d": k[0], "window": [k[1], k[2]], "kinds": sorted({x["anchor_kind"] for x in v})}
             for k, v in _by_bounds.items() if len({x["anchor_kind"] for x in v}) > 1],
            key=lambda d: d["anchor_d"]),
        "n_unassigned_recomputed": len(cat) - len(uniq_in),
        "by_category_catalog": dict(cat_uniq),
        "by_category_in_window_dedup": dict(cat_in_window),
        "by_category_outside_window": dict(cat_out_window),
        "t187_reported": {"n_catalog": ev["n_catalog"], "n_in_some_window": ev["n_in_some_window"],
                          "n_unassigned": ev["n_unassigned"], "by_category": ev["by_category"]},
    }


# ── (c) 风格表:逐段离散度 + 同 5 锚点随机 5 天对照 ─────────────────────────
def style_levels() -> dict:
    """重建 T-187 的六条风格净值(与 t187 同一数据源、同一算法)。只读 Supabase。"""
    if not SUPA or not SUPK:
        return {}
    rows = fetch("asset_mcap_daily",
                 {"symbol": "in.(BTC,ETH)", "order": "d.asc", "select": "symbol,d,price"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    out: dict[str, pd.Series] = {}
    for sym in ("BTC", "ETH"):
        sub = df[df["symbol"] == sym].dropna(subset=["price"]).sort_values("d")
        if len(sub):
            s = pd.Series(sub["price"].to_numpy(dtype=float),
                          index=pd.DatetimeIndex(sub["d"])).sort_index()
            out[sym + "_hold"] = s[~s.index.duplicated(keep="last")]
    if "BTC_hold" not in out:
        return out
    btc = out["BTC_hold"]
    out["BTC_trend200_nav"] = trend_200_nav(btc)
    arows = fetch("style_index_pit_daily",
                  {"dimension": "in.(sector,tier)", "style": "in.(" + ",".join(ALT_STYLES) + ")",
                   "weighting": "eq.equal", "order": "d.asc", "select": "d,style,ret"})
    adf = pd.DataFrame(arows)
    if len(adf):
        adf["d"] = pd.to_datetime(adf["d"])
        adf["ret"] = pd.to_numeric(adf["ret"], errors="coerce")
        piv = adf.pivot_table(index="d", columns="style", values="ret", aggfunc="last").sort_index()
        got = [s for s in ALT_STYLES if s in piv.columns]
        if got:
            alt = (1 + piv[got].mean(axis=1).fillna(0.0)).cumprod()
            out["ALT_sector_EW_nav"] = alt
            out["BTC_over_ALT"] = btc / alt
            out["_alt_styles_used"] = pd.Series(got)
    try:
        from src.data.signals.tom import trade_path
        x1_g = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
        out["X1V_trade_path_rally_l20"] = (1 + x1_g.shift(1).fillna(0.0) * btc.pct_change().fillna(0.0)).cumprod()
    except Exception as exc:  # noqa: BLE001
        out["_x1v_error"] = repr(exc)  # type: ignore[assignment]
    return out


def styles_dispersion(t187: dict) -> dict:
    disp = {}
    for nm, eps in t187["styles"].items():
        fl = [e for e in eps if e.get("first_leg")]
        al = eps
        row = {}
        for scope, rr in (("first_leg", fl), ("all", al)):
            legs = {}
            for k in ("pre", "crash", "recovery"):
                vals = [e[k] for e in rr if e.get(k) is not None]
                legs[k] = {"n": len(vals),
                           "min": float(np.min(vals)) if vals else None,
                           "median": float(np.median(vals)) if vals else None,
                           "max": float(np.max(vals)) if vals else None}
            row[scope] = legs
        disp[nm] = row
    return disp



def control_percentiles(t187: dict, levels: dict, n_draw: int = 200, seed: int = SEED) -> dict:
    """真正的零分布对照(走 apparatus.null_distribution / percentile_of):
    每次抽样 = 随机 5 个日子的三段中位;实际值 = 真实 5 个崩盘锚点的三段中位。"""
    from src.data.evaluation import apparatus

    btc = levels.get("BTC_hold")
    if btc is None or btc.empty:
        return {"error": "BTC 价格序列没重建成功,随机对照没做"}
    eps = [e for e in t187["styles"]["BTC_hold"] if e.get("first_leg")]
    real = [{"peak_d": pd.Timestamp(e["peak_d"]), "trough_d": pd.Timestamp(e["trough_d"])}
            for e in eps]
    H = int(np.median([(e["trough_d"] - e["peak_d"]).days for e in real]))
    cal = btc
    legs = ("pre", "crash", "recovery")
    out: dict[str, Any] = {"n_draw": n_draw, "H_days_median_crash_len": H,
                           "n_eligible_days_btc": int(len(cal.index)),
                           "pseudo_episode_rule": "随机日 d;谷底 = d 之后 H 天内 BTC 最低点;"
                                                  "三段口径与真实锚点相同(顶前 60 / 顶→谷底 / 谷底→+120)",
                           "styles": {}}
    for nm in t187["styles"]:
        lv = levels.get(nm)
        if not isinstance(lv, pd.Series) or lv.empty:
            continue
        # 每条风格用自己的**有效**数据跨度定可用随机日(风格净值短 ⇒ 可用随机日少)
        lv_valid = lv.dropna()
        if lv_valid.empty:
            continue
        first_ok = lv_valid.index.min() + pd.Timedelta(days=60)
        last_ok = lv_valid.index.max() - pd.Timedelta(days=H + 120)
        eligible = cal.index[(cal.index >= first_ok) & (cal.index <= last_ok)]
        real_vals = {k: [] for k in legs}
        for e in real:
            pr = phase_returns(lv, e)
            for k in legs:
                if pr.get(k) is not None:
                    real_vals[k].append(pr[k])
        actual = {k: (float(np.median(real_vals[k])) if real_vals[k] else None) for k in legs}

        def draw(rng: np.random.Generator, _nm=nm, _lv=lv) -> dict:
            pick = rng.choice(len(eligible), size=min(5, len(eligible)), replace=False)
            out_l = {"pre": [], "crash": [], "recovery": []}
            for i in sorted(pick):
                d = eligible[i]
                win = cal[(cal.index > d) & (cal.index <= d + pd.Timedelta(days=H))]
                tr = win.index[win.values.argmin()] if len(win) else d
                pr = phase_returns(_lv, {"peak_d": d, "trough_d": tr})
                for k in legs:
                    if pr.get(k) is not None:
                        out_l[k].append(pr[k])
            return {k: (float(np.median(out_l[k])) if out_l[k] else np.nan) for k in legs}

        leg_out = {"n_eligible_days": int(len(eligible)), "legs": {}}
        for k in legs:
            try:
                null = apparatus.null_distribution(
                    lambda rng_, _k=k: draw(rng_)[_k], n_draw, seed=seed, actual=actual[k])
            except Exception as exc:  # noqa: BLE001
                leg_out["legs"][k] = {"actual_median": actual[k], "error": repr(exc)}
                continue
            leg_out["legs"][k] = {"actual_median": actual[k],
                                  "null_median": float(np.median(null)),
                                  "null_p05": float(np.percentile(null, 5)),
                                  "null_p95": float(np.percentile(null, 95)),
                                  "n_null_finite": int(np.isfinite(null).sum()),
                                  "percentile_of_actual": apparatus.percentile_of(actual[k], null)}
        out["styles"][nm] = leg_out
    return out


# ── M8 展开 ────────────────────────────────────────────────────────────────
def anchor_offset_audit(t185: dict, t187: dict) -> dict:
    """锚点当天自亮检查 —— 线索是不是「锚点当天才亮」的定义性假象。

    锚点回看窗口**含锚点当天**(内核 _window_any 是 rolling(lookback+1))。破位日本身就是一根 −20% 的破位阴线、
    急跌起点又紧邻急跌,所以波动类迹象(VIX > 30、VIX/VXV 倒挂)有可能只是「锚点当天自己亮」。
    这里对能本地重建的 M7 / M8 重算:每个锚点命中时,离锚点最近的那个亮灯日差几天(0 = 锚点当天),
    并另算「严格早于锚点」的命中 —— 后者才是真正的「崩之前就有」。

    序列口径与 T-185 / T-187 完全一致:available() + to_calendar(gap=7),本地 FRED 快照,不重抓。"""
    vix = to_calendar(available(load_fred("VIXCLS", FRED_DIR), "VIXCLS"), 7)
    vxv = to_calendar(available(load_fred("VXVCLS", FRED_DIR), "VXVCLS"), 7)
    ratio = (vix / vxv).replace([np.inf, -np.inf], np.nan)
    # 有效性语义跟三道的 mk() 一致:数据没到的日子是 NA,不是 False
    # (否则 VXV 起点之前会被当成「用过」,锚点跳过数就少报了)
    signs = {"M7_vix_gt30": (vix > 30).where(vix.notna()),
             "M8_vix_over_vxv_gt1": (ratio > 1).where(ratio.notna())}

    def offsets(on: pd.Series, anchors: list, L: int) -> dict:
        # 与内核 sign_lift 同一口径:锚点早于「迹象首个可用日 + L」的不算(跳过)
        covered = on.notna()
        if not covered.any():
            return {"rows": [], "n_anchors": 0, "n_skipped": len(anchors)}
        first_ok = on.index[covered.values.argmax()] + pd.Timedelta(days=L)
        rows = []
        n_skip = 0
        for a in anchors:
            a = pd.Timestamp(a)
            if not (first_ok <= a <= on.index[-1]):
                n_skip += 1
                continue
            win = on.loc[(on.index >= a - pd.Timedelta(days=L)) & (on.index <= a)]
            on_days = win.index[win.fillna(False).astype(bool)]
            if len(on_days) == 0:
                rows.append({"anchor": str(a.date()), "hit": 0, "offset_days": None,
                             "on_anchor_day": 0, "strictly_before": 0})
                continue
            last = on_days.max()
            off = int((a - last).days)
            before = on_days[on_days < a]
            rows.append({"anchor": str(a.date()), "hit": 1, "offset_days": off,
                         "on_anchor_day": int(off == 0),
                         "strictly_before": int(len(before) > 0)})
        n = len(rows)
        if not n:
            return {"rows": rows, "n_anchors": 0, "n_skipped": n_skip}
        hit = [r for r in rows if r["hit"]]
        strict = [r for r in rows if r["strictly_before"]]
        return {
            "rows": rows, "n_anchors": n, "n_skipped": n_skip,
            "hit_rate": len(hit) / n, "n_hit": len(hit),
            "n_hit_on_anchor_day": sum(r["on_anchor_day"] for r in hit),
            "hit_rate_strictly_before": len(strict) / n, "n_strictly_before": len(strict),
            "n_hit_but_only_on_anchor_day": sum(1 for r in hit if r["strictly_before"] == 0),
            "offset_days_list": [r["offset_days"] for r in hit],
        }

    out: dict[str, Any] = {"note": "0 = 亮灯日就是锚点当天;负的偏移不存在(窗口只含当天及以前)",
                            "series_note": "VIXCLS / VXVCLS 本地 FRED 快照,available() + to_calendar(7)",
                            "cases": {}}
    # T-187:三套锚点
    t187_anchor_key = {"primary_90d": "primary_first_leg_peaks", "aux_break_30d": "aux_breaks",
                        "aux_fastcrash_30d": "aux_fast_crash_starts"}
    for fam, L in (("primary_90d", 90), ("aux_break_30d", 30), ("aux_fastcrash_30d", 30)):
        anchors = t187["anchors"][t187_anchor_key[fam]]
        for sname, on in signs.items():
            out["cases"]["T-187|%s|%s" % (sname, fam)] = offsets(on, anchors, L)
    # T-185:破位日 30 天(主锚点 90 天也一并算)
    for ak, L in (("aux_break", 30), ("main", 90)):
        anchors = t185["anchors"][ak]
        for sname, on in signs.items():
            out["cases"]["T-185|%s|%s" % (sname, ak)] = offsets(on, anchors, L)
    return out


def m8_deep_dive(t187: dict, rows: list[dict]) -> dict:
    v = t187["signs"].get("M8_vix_over_vxv_gt1")
    if not v:
        return {"error": "T-187 json 里没有 M8"}
    out = {"sign": "M8_vix_over_vxv_gt1", "definition": "VIX / VXV > 1(期限结构倒挂:VIX 高于 VXV)",
           "data_span": v["data_span"], "n_on_days": v["n_on_days"],
           "families": {}}
    for fam in FAMILIES:
        r = v.get(fam)
        if not r:
            continue
        hits = r.get("hits", {})
        hit_d = [d for d, h in hits.items() if h == 1]
        miss_d = [d for d, h in hits.items() if h == 0]
        hy = Counter(d[:4] for d in hit_d)
        ay = Counter(d[:4] for d in hits)
        out["families"][fam] = {
            "n_anchors": r.get("n_anchors"), "n_skipped": r.get("n_skipped"),
            "hit_rate": r.get("hit_rate"), "base_rate": r.get("base_rate"),
            "lift": r.get("lift"), "pctile": r.get("pctile"), "null_p50": r.get("null_p50"),
            "half1_hit_rate": r.get("half1_hit_rate"), "half2_hit_rate": r.get("half2_hit_rate"),
            "hit_dates": hit_d, "miss_dates": miss_d,
            "hits_per_year": dict(sorted(hy.items())),
            "anchors_per_year": dict(sorted(ay.items())),
            "max_hits_in_one_year": max(hy.values()) if hy else 0,
            "years_with_hits": len(hy),
        }
    # 跨道同源对照:M8 在三道各自的读数
    out["cross_task"] = [{"task": r["task"], "family": r["family"], "hit_rate": r["hit_rate"],
                          "base_rate": r["base_rate"], "lift": r["lift"], "pctile": r["pctile"],
                          "n_anchors": r["n_anchors"], "pass_raw": r["pass_raw"]}
                         for r in rows if r["sign"].startswith("M8")
                         or (r["task"] == "T-186" and r["sign"] == "M8")]
    return out


# ── 线索 × 锚点当天自亮(把锚点当天从命中里剔掉,线索还剩多少)───────────────
T185_SIGN_LONG = {"M7": "M7_vix_gt30", "M8": "M8_vix_over_vxv_gt1"}


def _pctile_by_sign(fam_rows: list[dict]) -> dict:
    """(道, 迹象) → 过了分位这一条的锚点集数。"""
    out: dict = defaultdict(int)
    for r in fam_rows:
        if r["c_pctile"]:
            out[(r["task"], r["sign"])] += 1
    return out


def clue_offset_crosscheck(rows: list[dict], offsets: dict) -> list[dict]:
    """线索的命中里有多少是「锚点当天自己亮」。

    §2.1 的审计已经给出每个锚点的「严格早于锚点」命中率。这里把 6 条线索逐条接上:
    剔掉锚点当天之后,提升还过没过 1.5、命中率还过没过基准率。
    只重算了 M7 / M8(波动类);其余线索在本轮没有本地重建的亮灯序列 ⇒ 标「没查」,不假装查过。"""
    out = []
    for r in rows:
        if not r["is_clue"]:
            continue
        key = None
        if r["task"] == "T-187":
            key = "T-187|%s|%s" % (r["sign"], r["family"])
        elif r["task"] == "T-185":
            long = T185_SIGN_LONG.get(r["sign"])
            if long:
                key = "T-185|%s|%s" % (long, r["anchor_set"])
        c = (offsets.get("cases") or {}).get(key) if key else None
        rec = {"task": r["task"], "sign": r["sign"], "label": r["label"], "family": r["family"],
               "anchor_set": r["anchor_set"], "n_anchors": r["n_anchors"],
               "hit_rate": r["hit_rate"], "base_rate": r["base_rate"], "lift": r["lift"],
               "pctile": r["pctile"], "offset_case": key,
               # 只有三套锚点的判定才进卡上的 180 次口径;T-186 独有的 FX / 稳健性锚点另算。
               "counted_in_multcomp": r["family"] in FAMILIES}
        if not c or not c.get("n_anchors"):
            rec["checked"] = False
            rec["note"] = "本轮只重算了 M7 / M8(波动类)的亮灯序列,这条线索没查锚点自亮"
            out.append(rec)
            continue
        strict = c.get("hit_rate_strictly_before")
        base = r["base_rate"]
        rec.update({
            "checked": True,
            "n_anchors_audited": c.get("n_anchors"), "n_skipped_audited": c.get("n_skipped"),
            "n_hit_on_anchor_day": c.get("n_hit_on_anchor_day"),
            "n_hit_but_only_on_anchor_day": c.get("n_hit_but_only_on_anchor_day"),
            "hit_rate_strictly_before": strict,
            "strict_lift": (strict / base) if (strict is not None and base) else None,
            "strict_survives_lift": bool(strict is not None and base and strict / base >= CRIT_LIFT),
            "strict_survives_beats_base": bool(strict is not None and base and strict > base),
        })
        out.append(rec)
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    t185, t186, t187 = load_json("t185_results.json"), load_json("t186_results.json"), \
        load_json("t187_results.json")

    rows = rows_t185(t185) + rows_t186(t186) + rows_t187(t187)
    rollup = per_sign_rollup(rows)

    fam_rows = [r for r in rows if r["family"] in FAMILIES]
    n_judge = len(fam_rows)
    n_pctile_only = sum(1 for r in fam_rows if r["c_pctile"])
    n_pass_raw = sum(1 for r in fam_rows if r["pass_raw"])
    n_clue = sum(1 for r in fam_rows if r["is_clue"])
    same_src_pass = [r for r in fam_rows if r["pass_raw"] and r["same_source"]]

    multi = {
        "n_judgments_three_families": n_judge,
        "n_signs_per_task": {t: len({r["sign"] for r in fam_rows if r["task"] == t})
                             for t in ("T-185", "T-186", "T-187")},
        "n_judgments_per_task": {t: sum(1 for r in fam_rows if r["task"] == t)
                                 for t in ("T-185", "T-186", "T-187")},
        "expected_by_chance_pctile_only": round(0.05 * n_judge, 2),
        "observed_pass_pctile_only": n_pctile_only,
        "observed_pass_all_four": n_pass_raw,
        "observed_clue_after_same_source": n_clue,
        # 卡上口径只数三套锚点;但本轮实际还判了 T-186 独有的 FX / 稳健性锚点 —— 一并报出来,
        # 不然「偶然期望 9 个」会拿一个偏小的分母去比一个更大的分子。
        "n_judgments_all_families": len(rows),
        "expected_by_chance_all_families": round(0.05 * len(rows), 2),
        "observed_pass_all_four_all_families": sum(1 for r in rows if r["pass_raw"]),
        "observed_clue_all_families": sum(1 for r in rows if r["is_clue"]),
        "extra_families": sorted({r["family"] for r in rows if r["family"] not in FAMILIES}),
        # 分锚点集分解:同一迹象在三套锚点上不是三个独立试验(共用同一条迹象序列),
        # 分解能看出「多出来的分位通过」落在哪一套锚点上。
        "by_family": {f: {
            "n_judgments": sum(1 for r in fam_rows if r["family"] == f),
            "pctile_only": sum(1 for r in fam_rows if r["family"] == f
                               and r["c_pctile"] and not r["pass_raw"]),
            "pass_all_four": sum(1 for r in fam_rows if r["family"] == f and r["pass_raw"]),
            "clue": sum(1 for r in fam_rows if r["family"] == f and r["is_clue"]),
        } for f in FAMILIES},
        # 「同一个迹象在几套锚点上都过分位」:如果一条迹象在三套上都过,那是同一个故事被数了三遍。
        "n_signs_passing_pctile_on_ge2_families": sum(
            1 for k, v in _pctile_by_sign(fam_rows).items() if v >= 2),
        "n_signs_passing_pctile_any": len(_pctile_by_sign(fam_rows)),
        "note": "卡上的口径:三道 × 约 20 迹象 × 3 套锚点 ≈ 180 次判定,纯偶然约冒 9 个"
                "(分位 ≥ 0.95 单条判据的偶然通过率 ≈ 5%);四条同时成立还要再叠提升 ≥ 1.5、"
                "锚点 ≥ 6、前后两半都 > 基准率三道筛子,偶然通过率严格低于 5%。",
        "pctile_source": N_SHIFT_NOTE,
    }

    calib_a = umcsent_profile(t187)
    calib_b = events_recompute(t187)
    disp = styles_dispersion(t187)
    levels = style_levels()
    ctrl = control_percentiles(t187, levels)
    # 重建的净值与 T-187 原 json 的核对(同一 pipeline 重建 ⇒ 读数应一致)
    xcheck = {}
    for nm in t187["styles"]:
        lv = levels.get(nm)
        if not isinstance(lv, pd.Series) or lv.empty:
            xcheck[nm] = "没重建成功"
            continue
        diffs = []
        for e in t187["styles"][nm]:
            if not e.get("first_leg"):
                continue
            pr = phase_returns(lv, {"peak_d": pd.Timestamp(e["peak_d"]),
                                     "trough_d": pd.Timestamp(e["trough_d"])})
            for k in ("pre", "crash", "recovery"):
                a, b = e.get(k), pr.get(k)
                if a is not None and b is not None:
                    diffs.append(abs(float(a) - float(b)))
        xcheck[nm] = {"max_abs_diff_vs_t187_json": float(max(diffs)) if diffs else None,
                      "n_compared": len(diffs)}
    calib_c = {"dispersion": disp, "random_control": ctrl, "rebuild_crosscheck": xcheck,
               "level_rebuilt": sorted(k for k in levels if not k.startswith("_")),
               "notes": "随机对照的「谷底」口径与真实锚点不同(随机日的谷底只是 H 天内最低点,"
                        "不含 20% 熊市门槛)—— 这是对照本身的局限,已在正文写明。"}

    m8 = m8_deep_dive(t187, rows)
    offsets = anchor_offset_audit(t185, t187)
    clue_off = clue_offset_crosscheck(rows, offsets)

    res = {
        "task": "T-191", "ledger": "S-675", "seed": SEED,
        "criteria": {"pctile_ge": CRIT_PCTILE, "lift_ge": CRIT_LIFT,
                     "min_anchors": CRIT_MIN_ANCHORS, "halves": "前后两半命中率都 > 基准率"},
        "families": {f: FAMILY_CN[f] for f in FAMILIES},
        "rows": rows, "per_sign": rollup,
        "multiple_comparisons": multi,
        "m8_deep_dive": m8,
        "anchor_offset_audit": offsets,
        "clue_offset_crosscheck": clue_off,
        "caliber_a_umcsent": calib_a,
        "caliber_b_events": calib_b,
        "caliber_c_styles": calib_c,
        "not_done": [
            "没有改三道的原脚本、没有重抓 FRED / 事件数据;三道 json 只读。",
            "没有把任何线索变成可交易规则;线索只进候选名单。",
            "T-186 的 FX 锚点(fx_start_30d / fx_hit_30d)与 eem_peak_all_90d 稳健性锚点"
            "没有算进三套锚点的多重比较计数(它们是 EM 独有的第四/第五类锚点);"
            "它们的额外通过项在 §2.2 与 §4 照报读数,但没单独做锚点自亮审计。",
            "锚点自亮审计只重建了 M7 / M8(波动类)的亮灯序列 ⇒ 6 条线索里有 3 条"
            "(T-185 M3 / M5 / M9)的「剔掉锚点当天后还剩多少」本轮查不了。",
            "没有为任何一条线索另立预注册、没有在新数据上过零信号对照 —— "
            "本轮所有读数都是探索性的。",
            "T-185 / T-186 的风格表只补了逐段离散度(min/中位/max),随机 5 天对照只在 T-187 上做。",
        ],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    write_report(res, t185, t186, t187)
    print("rows:", len(rows), "| 三套锚点判定次数:", n_judge,
          "| 分位过:", n_pctile_only, "| 四条全过:", n_pass_raw, "| 同源剔除后线索:", n_clue)
    for r in fam_rows:
        if r["is_clue"]:
            print("  CLUE", r["task"], r["sign"], r["family"], "pctile=%.3f lift=%.2f n=%d"
                  % (r["pctile"], r["lift"], r["n_anchors"]))


# ── 报告 ────────────────────────────────────────────────────────────────────
def _f(x, nd=3, dash="—"):
    if x is None:
        return dash
    try:
        return ("%%.%df" % nd) % float(x)
    except (TypeError, ValueError):
        return dash


def _pc(x, nd=1, dash="—"):
    if x is None:
        return dash
    try:
        return ("%." + str(nd) + "f%%") % (float(x) * 100.0)
    except (TypeError, ValueError):
        return dash


def write_report(res: dict, t185: dict, t186: dict, t187: dict) -> None:
    W: list[str] = []
    w = W.append
    fam_rows = [r for r in res["rows"] if r["family"] in res["families"]]

    w("# T-191 崩盘图谱三道补判(S-675):三套锚点各判一次线索")
    w("")
    w("**生成**:docs/research/t191_anchor_rejudge.py · seed %d · %s" % (SEED, N_SHIFT_NOTE))
    w("")
    w("**性质**:挖掘,不是检验。崩盘之后回头找「崩之前都有什么」最容易自欺,所以每条迹象都跟"
      "**基准率**比,并用循环平移给出零分布。本轮所有读数都是**探索性 —— 需另立预注册、在新数据上过零信号对照**;"
      "**不做任何可交易规则**,线索只进候选名单。")
    w("")
    w("**判据(S-675 写死,四条同时成立才算线索)**:分位 ≥ 0.95 · 提升 ≥ 1.5 · 锚点 ≥ 6 · "
      "前后两半命中率都 > 基准率。与崩盘定义同源的迹象照报读数,但标「同源,不算线索」。")
    w("")
    w("**三套锚点**:主锚点(前高,回看 90 天)· 辅锚点一(破位日,回看 30 天)· 辅锚点二(急跌起点,回看 30 天)。"
      "三道原本都只对主锚点判过线索,本轮把三套都判一遍。")
    w("")

    # ── 1 判定表 ──
    w("## 1 判定表(每道 × 每迹象 × 每套锚点)")
    w("")
    w("| 道 | 迹象 | 锚点 | 锚点数 | 命中率 | 基准率 | 提升 | 分位 | 前半 | 后半 | 分位✓ | 提升✓ | 锚点✓ | 两半✓ | 四条全过 | 同源 | 线索 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for t in ("T-185", "T-186", "T-187"):
        for r in [x for x in fam_rows if x["task"] == t]:
            w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                t, r["sign"], r["family"], r["n_anchors"], _pc(r["hit_rate"]), _pc(r["base_rate"]),
                _f(r["lift"], 2), _f(r["pctile"]), _pc(r["half1_hit_rate"]), _pc(r["half2_hit_rate"]),
                "✓" if r["c_pctile"] else "✗", "✓" if r["c_lift"] else "✗",
                "✓" if r["c_n_anchors"] else "✗", "✓" if r["c_halves"] else "✗",
                "**是**" if r["pass_raw"] else "否", "是" if r["same_source"] else "否",
                "**是**" if r["is_clue"] else "否"))
    w("")

    # ── 1.1 每迹象汇总 ──
    w("### 1.1 每迹象:判了几套锚点 / 过了几套")
    w("")
    w("| 道 | 迹象 | 含义 | 判了几套 | 四条全过几套 | 过的是哪套 | 同源(不算线索) |")
    w("|---|---|---|---|---|---|---|")
    for r in res["per_sign"]:
        if r["task"] not in ("T-185", "T-186", "T-187"):
            continue
        w("| %s | %s | %s | %d | %d | %s | %s |" % (
            r["task"], r["sign"], r["label"], r["n_families_judged"], r["n_families_clue"],
            "、".join(r["families_clue"]) or "—",
            "、".join(r["same_source_families"]) or "—"))
    w("")

    # ── 2 M8 ──
    m8 = res["m8_deep_dive"]
    w("## 2 M8 展开(VIX / VXV 倒挂)")
    w("")
    w("**定义**:%s。数据区间 %s → %s,亮灯 %d 天。" % (
        m8["definition"], m8["data_span"][0], m8["data_span"][1], m8["n_on_days"]))
    w("")
    w("**基准率怎么算**:迹象序列铺成日历日,对每个可用日 d 取「d 往前 30 天(含当天)内有没有亮过」这一个 0/1;"
      "锚点命中率 = 锚点所在的那些 0/1 的均值;**基准率 = 全部可用日(从首个可用日 + 30 天起)的这些 0/1 的均值** —— "
      "也就是「随便哪天,往前 30 天里这个迹象亮过的概率」。分位来自把迹象整体循环平移 2000 次的零分布"
      "(平移保留迹象自身的持续长度,只换时点)。")
    w("")
    for fam, v in m8["families"].items():
        w("**%s(%s)** —— 锚点 %d 个(跳过 %s),命中率 %s,基准率 %s,提升 %s,分位 %s,前后两半 %s / %s"
          % (fam, res["families"][fam], v["n_anchors"], v["n_skipped"], _pc(v["hit_rate"]),
             _pc(v["base_rate"]), _f(v["lift"], 2), _f(v["pctile"]),
             _pc(v["half1_hit_rate"]), _pc(v["half2_hit_rate"])))
        w("")
        w("- 逐个命中的日期:%s" % ("、".join(v["hit_dates"]) or "无"))
        w("- 未命中的日期:%s" % ("、".join(v["miss_dates"]) or "无"))
        w("- 命中年份分布:%s(同一年最多 %d 个);锚点本身的年份分布:%s"
          % ("、".join("%s×%d" % (k, n) for k, n in v["hits_per_year"].items()) or "无",
             v["max_hits_in_one_year"],
             "、".join("%s×%d" % (k, n) for k, n in v["anchors_per_year"].items()) or "无"))
        w("")
    w("**命中是否集中在同一年**:")
    for fam, v in m8["families"].items():
        yrs = v["years_with_hits"]
        w("- %s:命中分布在 %d 个不同年份,同一年最多 %d 个 ⇒ %s"
          % (fam, yrs, v["max_hits_in_one_year"],
             "**集中在同一年**(要担心)" if v["max_hits_in_one_year"] >= 3 else "没有集中在同一年"))
    w("")
    # ── 2.1 锚点当天自亮检查 ──
    off = res["anchor_offset_audit"]
    w("### 2.1 锚点当天自亮检查(波动类迹象是不是定义性假象)")
    w("")
    w("锚点的回看窗口**含锚点当天**。破位日本身是一根 −20% 的破位阴线,急跌起点又紧邻急跌 —"
      "波动类迹象(VIX > 30、VIX/VXV 倒挂)有可能只是「锚点当天自己亮」。"
      "这里本地重算 M7 / M8(同一 FRED 快照、同一口径),对每个锚点记「离锚点最近的亮灯日差几天」"
      "(0 = 就是锚点当天),并另算「严格早于锚点」的命中 —— 后者才是真正的「崩之前就有」。")
    w("")
    w("| 道 | 迹象 | 锚点 | 锚点数(可用) | 跳过 | 命中率 | 其中锚点当天亮 | 严格早于锚点的命中率 | 只在锚点当天亮 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for key, v in off["cases"].items():
        if not v.get("n_anchors"):
            continue
        task, sname, fam = key.split("|")
        w("| %s | %s | %s | %d | %s | %s | %d | %s | %d |" % (
            task, sname, fam, v["n_anchors"], v.get("n_skipped", 0), _pc(v["hit_rate"]),
            v["n_hit_on_anchor_day"], _pc(v["hit_rate_strictly_before"]),
            v["n_hit_but_only_on_anchor_day"]))
    w("")
    w("(锚点口径与判定表一致:早于「迹象首个可用日 + 回看天数」的锚点跳过,不计入命中率。)")
    w("")
    w("逐锚点明细在 `t191_results.json` 的 `anchor_offset_audit.cases.*.rows`。")
    w("")

    w("**跨道对照(M8 在三道上的读数)** —— 同一个宏观迹象在发达 / EM / crypto 三道上的表现:")
    w("")
    w("| 道 | 锚点 | 锚点数 | 命中率 | 基准率 | 提升 | 分位 | 四条全过 |")
    w("|---|---|---|---|---|---|---|---|")
    for r in m8["cross_task"]:
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["task"], r["family"], r["n_anchors"], _pc(r["hit_rate"]), _pc(r["base_rate"]),
            _f(r["lift"], 2), _f(r["pctile"]), "**是**" if r["pass_raw"] else "否"))
    w("")

    # ── 2.2 线索 × 锚点自亮 ──
    w("### 2.2 线索 × 锚点当天自亮:把锚点当天剔掉,线索还剩多少")
    w("")
    w("§2.1 说明了「锚点当天自亮」这个假象存在。下面把它接到本轮找到的线索上:命中率里如果混着"
      "「锚点当天自己亮」的那部分,提升就是被崩盘本身抬起来的。表里「严格早于锚点的命中率」= "
      "把锚点当天从回看窗口里去掉后的命中率;「严格提升」= 该命中率 ÷ 基准率。")
    w("")
    w("| 道 | 迹象 | 锚点 | 命中率(含锚点当天) | 严格早于锚点 | 只在锚点当天亮 | 锚点当天亮(次) | 提升 | 严格提升 | 剔掉锚点当天后还过 ≥1.5 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    counted = [c for c in res["clue_offset_crosscheck"] if c.get("counted_in_multcomp")]
    extra = [c for c in res["clue_offset_crosscheck"] if not c.get("counted_in_multcomp")]
    for c in counted:
        if not c.get("checked"):
            w("| %s | %s | %s | %s | — | — | — | %s | — | %s |" % (
                c["task"], c["sign"], c["family"], _pc(c["hit_rate"]), _f(c["lift"], 2),
                "**没查**"))
            continue
        w("| %s | %s | %s | %s | %s | %d | %d | %s | %s | %s |" % (
            c["task"], c["sign"], c["family"], _pc(c["hit_rate"]),
            _pc(c["hit_rate_strictly_before"]), c["n_hit_but_only_on_anchor_day"],
            c["n_hit_on_anchor_day"], _f(c["lift"], 2), _f(c["strict_lift"], 2),
            "**是**" if c["strict_survives_lift"] else "否"))
    w("")
    checked = [c for c in counted if c.get("checked")]
    if checked:
        surv = [c for c in checked if c["strict_survives_lift"] and c["strict_survives_beats_base"]]
        w("**读法**(只算三套锚点的 %d 条线索):查得了的 %d 条里,%d 条在剔掉锚点当天之后**仍然**同时过"
          "「提升 ≥ 1.5」与「命中率 > 基准率」;其余的要么没查(本轮只重建了 M7 / M8 的亮灯序列),"
          "要么剔掉锚点当天后提升掉到 1.5 以下 —— 后者说明它的原始提升是崩盘当天自己贡献的,"
          "**不能当独立证据**。"
          % (len(counted), len(checked), len(surv)))
        w("")
        for c in checked:
            if not (c["strict_survives_lift"] and c["strict_survives_beats_base"]):
                w("- %s %s(%s)严格提升 %s < 1.5(原始提升 %s)⇒ 原始提升里混着锚点当天的成分,"
                  "本轮**降级为待查**,不当线索。" % (
                      c["task"], c["sign"], c["family"], _f(c["strict_lift"], 2), _f(c["lift"], 2)))
        w("")
    if extra:
        w("**不计入卡上 180 次口径的额外通过项**(T-186 独有的 FX 锚点 / 稳健性锚点,照报读数,"
          "但不算本卡线索 —— 理由见 §4 的分母说明):")
        w("")
        w("| 道 | 迹象 | 锚点 | 锚点数 | 命中率 | 基准率 | 提升 | 分位 |")
        w("|---|---|---|---|---|---|---|---|")
        for c in extra:
            w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                c["task"], c["sign"], c["family"], c["n_anchors"], _pc(c["hit_rate"]),
                _pc(c["base_rate"]), _f(c["lift"], 2), _f(c["pctile"])))
        w("")

    # ── 3 三项口径 ──
    w("## 3 三项口径")
    w("")
    a = res["caliber_a_umcsent"]
    w("### (a) 情绪画像第三行:协议写消费者信心(UMCSENT),T-187 报的是 BTC 资金费")
    w("")
    w("T-187 的情绪画像三行是 fng / VIX / **BTC 资金费(年化)**;S-675 协议的第三行是**消费者信心 UMCSENT**。"
      "这里用本地 FRED 快照补上 UMCSENT(经 available():UMCSENT 的日期是所属月月初、终值月底发布 ⇒ 滞后 31 天;"
      "to_calendar 的 ffill 上限 40 天),口径与 T-187 其它行一致:每段崩盘的 顶前 90 / 顶前 30 / 顶 / 谷底 读数,跨段取中位。")
    w("")
    w("| 行 | 顶前 90 天 | 顶前 30 天 | 顶 | 谷底 |")
    w("|---|---|---|---|---|")
    for k, lbl in (("fng", "恐惧贪婪指数(fng)(T-187 原报)"), ("vix", "VIX(T-187 原报)"),
                   ("btc_funding_annualized", "BTC 资金费(年化)(T-187 原报)"),
                   ("umcsent", "**UMCSENT 消费者信心(本轮补)**")):
        if k == "umcsent":
            m = a["median_first_leg"]
        else:
            m = a["t187_reported_rows"][k]
        w("| %s | %s | %s | %s | %s |" % (lbl, _f(m["d90"], 1), _f(m["d30"], 1),
                                          _f(m["peak"], 1), _f(m["trough"], 1)))
    w("")
    w("**差异说明**:")
    w("")
    w("1. **口径不同**:UMCSENT 是**月度**宏观调查(%s → %s,原始 %d 个观测、%d 个非空),"
      "BTC 资金费是**8 小时**频率的永续合约持仓成本(年化),两者不是同一个量。"
      "T-187 把协议第三行换成了 crypto 独有的 carry 指标 —— **这是偏离协议**,本轮补回。"
      % (a["raw_monthly_span"][0], a["raw_monthly_span"][1], a["raw_monthly_obs"],
         a["raw_monthly_nonnull"]))
    # 「相邻两段读到同一次月度发布」的例子:从逐段读数里找,不手写
    _ex = ""
    _pe = a.get("per_episode", [])
    for _i in range(len(_pe) - 1):
        _r1, _r2 = _pe[_i], _pe[_i + 1]
        if (_r1.get("trough") is not None and _r2.get("d30") is not None
                and abs(_r1["trough"] - _r2["d30"]) < 1e-9):
            _ex = ("本轮 %s 段的谷底与紧邻的 %s 段的顶前 30 天就是同一次月度发布(%.1f)"
                   % (_r1["peak_d"], _r2["peak_d"], _r1["trough"]))
            break
    _fl = [r for r in _pe if r.get("first_leg")]
    _dupcols = [k for k in ("d90", "d30", "peak", "trough")
                if len({r[k] for r in _fl if r.get(k) is not None})
                < len([r for r in _fl if r.get(k) is not None])]
    _same_col = ("本轮 %d 段 first_leg 在四列里都没有同值(段与段之间没撞上同一个月度值)" % len(_fl)
                 if not _dupcols else
                 "本轮 %d 段 first_leg 在 %s 列上出现了同值" % (len(_fl), "、".join(_dupcols)))
    w("2. **新鲜度不同(口径上的坑)**:UMCSENT 经 available() 滞后 31 天(属期是当月 1 日、终值月底发布),"
      "所以「顶」这一列读到的其实是**顶前约一个月**那次发布;「顶前 30 天」读到的是顶前约两个月那次发布 —— "
      "**相邻两段崩盘可能读到同一次月度发布** —— %s;%s。"
      "BTC 资金费是日频、当天就能看到,没有这个问题。所以 UMCSENT 的「顶前 30 天」不能当高频信号用。"
      % (_ex, _same_col))
    w("3. **方向可读性不同**:UMCSENT 在本轮 5 段 first_leg 崩盘上是「顶前 90 天 %.1f → 顶前 30 天 %.1f → 顶 %.1f → 谷底 %.1f」"
      "(消费者信心在顶附近仍高、到谷底才塌),与 fng / VIX 的「顶附近最乐观、谷底最恐慌」不是同一种形状 —— "
      "**UMCSENT 变慢**,它是慢变量,不能替代 VIX 那一行做情绪画像的快读数。"
      % (a["median_first_leg"]["d90"], a["median_first_leg"]["d30"],
         a["median_first_leg"]["peak"], a["median_first_leg"]["trough"]))
    w("")
    w("逐段读数在 `docs/research/t191_results.json` 的 `caliber_a_umcsent.per_episode`。")
    w("")

    b = res["caliber_b_events"]
    w("### (b) 事件计数 59 与 13 窗口表 67 行的差")
    w("")
    w("T-187 报的「八类事件计数」用的是**去重后的事件目录**(%d 条),而 13 个窗口表里的行数是 **%d 行** —— "
      "差的不是「多算了事件」,而是**同一条事件落进了不止一个窗口**(窗口之间有重叠)。按去重重算一遍:"
      % (b["n_catalog"], b["window_rows_total"]))
    w("")
    w("| 口径 | 数值 |")
    w("|---|---|")
    w("| 事件目录条目 | %d 条(其中不重复 url %d 个 ⇒ 目录本身没有重复条目) |" % (
        b["n_catalog_recomputed"], b["n_distinct_urls_in_catalog"]))
    w("| 13 个窗口的行数合计 | %d 行 |" % b["window_rows_total"])
    w("| 窗口里 (窗口,url) 不重复的行 | %d 行 |" % b["distinct_window_url_pairs"])
    w("| 落在至少一个窗口内的**去重**事件 | %d 条 |" % b["unique_events_in_windows"])
    w("| 重复行数(窗口行数 − 去重事件数) | %d 行 |" % b["duplicate_rows"])
    w("| ├ 跨窗口重复(同一条事件落进 2 个不同窗口) | %d 行 |" % b["cross_window_repeat_rows"])
    w("| └ 同窗口重复(两个窗口边界完全相同,同一段事件算了两遍) | %d 行 |" % b["same_window_duplicate_rows"])
    w("| 落进 **2 个及以上**窗口的事件 | %d 条 |" % b["n_events_in_multiple_windows"])
    w("| 目录里没落进任何窗口的事件 | %d 条 |" % b["n_unassigned_recomputed"])
    w("")
    if b["duplicate_window_bounds"]:
        w("**边界完全相同的窗口(重复窗口)**:")
        w("")
        for d in b["duplicate_window_bounds"]:
            w("- %s / 锚点 %s / 窗口 %s → %s:同样的边界出现了 %d 次" % (
                d["anchor_kind"], d["anchor_d"], d["window"][0], d["window"][1],
                d["n_windows_with_same_bounds"]))
        w("")
        w("  ⇒ **同一条事件在这一对窗口里被数了两遍**,这是 67 行里 %d 行重复的直接来源。"
          % b["same_window_duplicate_rows"])
        w("")
    if b["multi_window_events"]:
        w("**落进多个窗口的事件(这就是 59 vs 67 的来源)**:")
        w("")
        w("| 日期 | 类别 | 事件 | 落进的窗口(锚点类型 / 锚点日 / 窗口边界) |")
        w("|---|---|---|---|")
        for e in b["multi_window_events"]:
            w("| %s | %s | %s | %s |" % (e["date"], e["cat"], e["title"],
                                        "、".join("%s %s(%s→%s)" % (x["kind"], x["anchor_d"],
                                                                   x["window"][0], x["window"][1])
                                                  for x in e["in_windows"])))
        w("")
        if b.get("same_bounds_diff_kind"):
            w("其中 **边界完全一样、但锚点类型不同**的窗口(同一根锚点既是「第一腿顶」又是「急跌起点」):")
            w("")
            for d in b["same_bounds_diff_kind"]:
                w("- 锚点 %s / 窗口 %s→%s:%s" % (d["anchor_d"], d["window"][0], d["window"][1],
                                                "、".join(d["kinds"])))
            w("")
            w("  ⇒ 这是**两个不同的窗口**(协议把「顶」和「急跌起点」各算一遍),不是同一个窗口被数了两次;"
              "但因为两根锚点日期相同、回看长度相同,边界一模一样,读表时容易看成重复行。")
            w("")
    w("**去重后各类别计数(落在至少一个窗口内)** —— 这才是能跟窗口表对上的口径:")
    w("")
    w("| 类别 | 目录总数 | 落在窗口内(去重) | 窗口外 |")
    w("|---|---|---|---|")
    for c in sorted(set(list(b["by_category_catalog"].keys()) +
                         list(b["by_category_in_window_dedup"].keys()))):
        w("| %s | %d | %d | %d |" % (c, b["by_category_catalog"].get(c, 0),
                                     b["by_category_in_window_dedup"].get(c, 0),
                                     b["by_category_outside_window"].get(c, 0)))
    w("| **合计** | **%d** | **%d** | **%d** |" % (
        sum(b["by_category_catalog"].values()), sum(b["by_category_in_window_dedup"].values()),
        sum(b["by_category_outside_window"].values())))
    w("")
    w("**结论**:59 = 目录条目数(不重复 url);67 = 窗口表行数;两者的桥是 **%d 行重复 = %d 行跨窗口重复 "
      "+ %d 行同窗口重复(重复窗口)**。报「某类别有几条」时应一律用**去重后**的数"
      "(%d 条落在窗口内 + %d 条窗口外 = %d);窗口表的 67 行**不能**当事件条数引用。"
      % (b["duplicate_rows"], b["cross_window_repeat_rows"], b["same_window_duplicate_rows"],
         b["unique_events_in_windows"], b["n_unassigned_recomputed"], b["n_catalog_recomputed"]))
    w("")

    c = res["caliber_c_styles"]
    w("### (c) 风格表:逐段离散度 + 「同 5 锚点随机 5 天」对照")
    w("")
    w("T-187 的风格表只给 first_leg 段的**中位**,看不出离散度 —— 中位 5 个数不知道是齐的还是有极端值。"
      "这里补 min / 中位 / max,并加一个对照:**同样 5 个「顶」,换成同一段历史里随机取的 5 天**,"
      "其余口径完全一样(顶前 60 天 / 顶 → 谷底 / 谷底 → +120 天)。")
    w("")
    w("**逐段离散度(first_leg 段,n=%d)**:" % c["dispersion"].get("BTC_hold", {}).get("first_leg", {})
      .get("pre", {}).get("n", 0))
    w("")
    w("| 风格 | 段 | n | min | 中位 | max |")
    w("|---|---|---|---|---|---|")
    for nm, row in c["dispersion"].items():
        for k, lbl in (("pre", "顶前 60 天"), ("crash", "顶 → 谷底"), ("recovery", "谷底 → +120 天")):
            v = row["first_leg"][k]
            w("| %s | %s | %s | %s | %s | %s |" % (STYLE_CN.get(nm, nm), lbl, v["n"],
                                                   _pc(v["min"]), _pc(v["median"]), _pc(v["max"])))
    w("")
    rc = c["random_control"]
    if "error" not in rc:
        w("**同 5 锚点随机 5 天对照**(零分布走 `src/data/evaluation/apparatus.py`;"
          "每次抽样抽 5 个随机日,各自按同一口径算三段中位;%d 次抽样):" % rc["n_draw"])
        w("")
        w("对照口径:%s。随机「顶」的谷底定义:H = 真实 first_leg 崩盘段长中位数 = %d 天;"
          "可用随机日数按各风格自己的数据跨度定(见最后一列)。**这条对照有局限**:随机日的谷底只是"
          "「H 天内最低点」,不含 20%% 熊市门槛,所以随机对照的 crash 段天然更浅 —— "
          "读数要按「真实锚点 vs 随机日」的分位看,不是看绝对值。"
          % (rc["pseudo_episode_rule"], rc["H_days_median_crash_len"]))
        w("")
        w("| 风格 | 段 | 真实 5 锚点中位 | 随机日中位 | 随机 5% | 随机 95% | 实际值在零分布里的分位 | 可用随机日 |")
        w("|---|---|---|---|---|---|---|---|")
        n_crash_out, n_rec_mid, n_rec_bad, n_rec_good = 0, 0, 0, 0
        for nm, row in rc["styles"].items():
            for k, lbl in (("pre", "顶前 60 天"), ("crash", "顶 → 谷底"), ("recovery", "谷底 → +120 天")):
                v = row["legs"][k]
                w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    STYLE_CN.get(nm, nm), lbl, _pc(v["actual_median"]), _pc(v["null_median"]),
                    _pc(v["null_p05"]), _pc(v["null_p95"]), _f(v["percentile_of_actual"], 3),
                    row.get("n_eligible_days", "—")))
            cp = row["legs"].get("crash", {}).get("percentile_of_actual")
            rp = row["legs"].get("recovery", {}).get("percentile_of_actual")
            if cp is not None and cp <= 0.05:
                n_crash_out += 1
            if rp is not None:
                if 0.2 <= rp <= 0.8:
                    n_rec_mid += 1
                elif rp < 0.2:
                    n_rec_bad += 1
                else:
                    n_rec_good += 1
        w("")
        w("**怎么读这张表** —— 随机对照把「风格净值在崩盘锚点上的读数」和「同一条净值在随机日子上的读数」放在一起比:")
        w("")
        w("- **崩段(顶 → 谷底)**:%d / %d 条风格的真实锚点中位落在随机分布的 5%% 尾部之外(分位 ≤ 0.05)—— "
          "崩段确实是**锚点特有**的,不是随便哪天都这样。唯一的例外是 BTC_over_ALT(相对指标,"
          "崩的时候 BTC 和山寨一起跌,比值不比随机日更差)。" % (n_crash_out, len(rc["styles"])))
        w("- **修复段(谷底 → +120 天)**:%d 条风格与随机日**分不开**(分位 0.2–0.8),%d 条**比随机日还差**"
          "(分位 < 0.2),%d 条**比随机日还好**(分位 > 0.8)。**修复段没有证据表明崩盘锚点特殊** —— "
          "风格表里被当成「崩后修复」的那一列,目前看大部分是「随便哪天都这样」;"
          "唯一有信号的例外是山寨板块 EW 指数(修复段 +%.0f%% vs 随机日中位 +%.0f%%)与它对应的 "
          "BTC 相对山寨(真实锚点后 BTC 跑输山寨)。"
          % (n_rec_mid, n_rec_bad, n_rec_good,
             100 * rc["styles"].get("ALT_sector_EW_nav", {}).get("legs", {})
             .get("recovery", {}).get("actual_median", float("nan")),
             100 * rc["styles"].get("ALT_sector_EW_nav", {}).get("legs", {})
             .get("recovery", {}).get("null_median", float("nan"))))
        w("")
        w("**重建核对**:风格净值是本轮用同一数据源重建的,与 T-187 原 json 的逐段读数最大绝对差 ——")
        w("")
        for nm, v in c["rebuild_crosscheck"].items():
            if isinstance(v, dict):
                w("- %s:最大差 %s(%d 个读数)" % (STYLE_CN.get(nm, nm),
                                               _f(v["max_abs_diff_vs_t187_json"], 8),
                                               v["n_compared"]))
            else:
                w("- %s:%s" % (STYLE_CN.get(nm, nm), v))
        w("")
    else:
        w("**随机对照没做**:%s" % rc["error"])
        w("")

    # ── 4 多重比较 ──
    m = res["multiple_comparisons"]
    w("## 4 多重比较")
    w("")
    w("本轮一共做了 **%d 次判定**(三道 × 每迹象 × 三套锚点 = %s)。" % (
        m["n_judgments_three_families"],
        "、".join("%s %d 次" % (t, n) for t, n in m["n_judgments_per_task"].items())))
    w("")
    w("| 口径 | 数量 |")
    w("|---|---|")
    w("| 判定次数(只数三套锚点 = 卡上口径) | %d |" % m["n_judgments_three_families"])
    w("| 只过「分位 ≥ 0.95」这一条 | %d |" % m["observed_pass_pctile_only"])
    w("| 四条判据全过 | %d |" % m["observed_pass_all_four"])
    w("| 剔除同源后算线索 | %d |" % m["observed_clue_after_same_source"])
    w("| 纯偶然期望(分位单条 ≈ 5%%) | %s |" % m["expected_by_chance_pctile_only"])
    w("| —— 下面三行把 T-186 独有的锚点也算进来 —— | |")
    w("| 判定次数(全部锚点集) | %d |" % m["n_judgments_all_families"])
    w("| 四条判据全过(全部锚点集) | %d |" % m["observed_pass_all_four_all_families"])
    w("| 纯偶然期望(全部锚点集) | %s |" % m["expected_by_chance_all_families"])
    w("")
    if m["extra_families"]:
        w("**分母说明**:卡上的「≈ 180 次判定、纯偶然约冒 9 个」只对应三套锚点。本轮实际还判了 T-186 "
          "独有的锚点集(%s),合计 **%d 次判定** —— 按同一 5%% 口径,纯偶然期望是 **%s** 个,"
          "实测四条全过 **%d** 个(其中 %d 个是本卡线索)。把分母摆在这里是为了不让「9 vs 6」这种"
          "只挑分母的比较变成结论。"
          % ("、".join(m["extra_families"]), m["n_judgments_all_families"],
             m["expected_by_chance_all_families"], m["observed_pass_all_four_all_families"],
             m["observed_clue_after_same_source"]))
        w("")
    w("**卡上的口径**:三道 × 约 20 迹象 × 3 套锚点 ≈ 180 次判定,纯偶然约冒 9 个 —— 实测 %d 次判定。"
      "分位这一条过了 %d 个(期望 %s 个);四条判据全过的 %d 个(每一条都要再叠「提升 ≥ 1.5」"
      "「锚点 ≥ 6」「前后两半都 > 基准率」三道筛子,偶然通过率**严格低于** 5%%)。"
      % (m["n_judgments_three_families"], m["observed_pass_pctile_only"],
         m["expected_by_chance_pctile_only"], m["observed_pass_all_four"]))
    w("")
    bf = m["by_family"]
    w("**分锚点集分解**(判定次数 / 只过分位这一条 / 四条全过 / 剔同源后算线索):")
    w("")
    w("| 锚点集 | 判定次数 | 只过分位(其余三条没过) | 四条全过 | 线索 |")
    w("|---|---|---|---|---|")
    for f in FAMILIES:
        v = bf[f]
        w("| %s | %d | %d | %d | %d |" % (FAMILY_CN[f], v["n_judgments"], v["pctile_only"],
                                           v["pass_all_four"], v["clue"]))
    w("")
    w("**怎么读这张分解表** —— 两条都要说清,不能只报一条:")
    w("")
    w("1. **过了分位这一条的共 %d 个**(其中 %d 个只过分位、其余三条没过):只过分位的这 %d 个里,"
      "%d 个落在主锚点(辅锚点两套合计 %d 个)。若把 %d 次判定当独立二项看,%d 比期望 %s 高约 %.1f "
      "个标准差(σ = %.1f);但这 %d 次**不独立** —— 同一条迹象在三套锚点上共用同一条亮灯序列,"
      "同一套锚点又被二十多条迹象共用 ⇒ 有效独立试验数远小于 %d,标准差被低估,这个「超出」"
      "不能当成证据。"
      % (m["observed_pass_pctile_only"], sum(v["pctile_only"] for v in bf.values()),
         sum(v["pctile_only"] for v in bf.values()), bf["primary_90d"]["pctile_only"],
         bf["aux_break_30d"]["pctile_only"] + bf["aux_fastcrash_30d"]["pctile_only"],
         m["n_judgments_three_families"], m["observed_pass_pctile_only"],
         m["expected_by_chance_pctile_only"],
         (m["observed_pass_pctile_only"] - m["expected_by_chance_pctile_only"])
         / (m["n_judgments_three_families"] * 0.05 * 0.95) ** 0.5,
         (m["n_judgments_three_families"] * 0.05 * 0.95) ** 0.5,
         m["n_judgments_three_families"], m["n_judgments_three_families"]))
    w("2. **四条全过的 %d 个里,%d 个落在两套辅锚点**(破位日 / 急跌起点)。辅锚点与崩盘定义重叠"
      "(锚点当天就在崩盘里),所以这 %d 个里有多少是「锚点当天自己亮」抬起来的,要看 §2.1 的自亮审计"
      "与 §2.2 的线索级核对 —— 不是看分位就能定的。"
      % (m["observed_pass_all_four"],
         bf["aux_break_30d"]["pass_all_four"] + bf["aux_fastcrash_30d"]["pass_all_four"],
         m["observed_pass_all_four"]))
    w("")
    w("**重复计数检查**:过了分位的 %d 个迹象里,只有 %d 个在**两套及以上**锚点上都过分位 ⇒ "
      "本轮没有「同一条故事被数三遍」的情况。"
      % (m["n_signs_passing_pctile_any"], m["n_signs_passing_pctile_on_ge2_families"]))
    w("")
    w("**也就是说:本轮找到的每一条线索,都必须放在「%d 次判定里约 %s 个偶然也会冒出来」的背景下读** —— "
      "少于这个数不说明问题,接近或超过才需要另立预注册去追。" % (
          m["n_judgments_three_families"], m["expected_by_chance_pctile_only"]))
    w("")
    same_src = [r for r in fam_rows if r["pass_raw"] and r["same_source"]]
    if same_src:
        w("**同源(照报读数,不算线索)**:")
        w("")
        for r in same_src:
            w("- %s %s %s:命中率 %s,基准率 %s,提升 %s,分位 %s —— 同源,不算线索"
              % (r["task"], r["sign"], r["family"], _pc(r["hit_rate"]), _pc(r["base_rate"]),
                 _f(r["lift"], 2), _f(r["pctile"])))
        w("")

    # ── 5 未做 ──
    w("## 5 未做")
    w("")
    for x in res["not_done"]:
        w("- %s" % x)
    w("")
    w("---")
    w("")
    w("*本报告只做候选线索挖掘,不构成任何可交易规则,也不构成投资建议。*")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(W) + "\n")
    print("report:", REPORT_PATH)


if __name__ == "__main__":
    main()
