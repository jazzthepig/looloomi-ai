"""T-190 / S-679 —— X1V 的两种快回场(反弹不止盈 / 55 日新高即回场),在没用来设计它的资产上验。

照台账 S-679 一字不改(变体定义、资产分组与时间段、熊市门槛、判据门槛):
  基准 B = X1V = tom.trade_path(close, "rally", 0.0, exit_mode="l20", vol=True)
  V1 反弹不止盈 —— 熊市反弹仓去掉 +15% 止盈,只在收盘 < 前 10 日最低时出、或转成多头;其余与 B 逐字相同。
  V2 快多头     —— 多头进场从「收盘 > 200 日线 且 > 前 20 日最高」改成「收盘 > 前 55 日最高收盘」;其余与 B 逐字相同。

src/data/signals/tom.py 只读(不改 src);这里参数化重写 trade_path,**先证明 B 与原函数在 BTC 全史上逐日一致,
不一致就停、报差异**。

G1 NASDAQCOM(数据根 research/crash_atlas/fred/):1971-02 → 2014-12,熊市门槛 0.20。
G2 S-677 Binance USDT 现货对(数据根 research/s677/_bv_daily.jsonl):≥400 根日线的;
   S-601 看过的 12 个币只用 2019-05-31 之前;熊市门槛 0.50。
G3 World50 候选池个股(ohlcv_daily source=eodhd & asset_class=Equity,复权收盘):熊市门槛 0.20。
BTC / ETH 只报(asset_mcap_daily price)。

净值从第 201 天起算;成本 10 bp × |Δ 敞口|、现金 0(用 tom.trade_returns 的同一口径,funding 传 None 用它的默认 0.10)。
判据(每组单独判;一个变体 ≥ 2 组过 ⇒ 记「过」):
  ① 段中位「修复(变体)− 修复(B)」≥ +10pp
  ② 段中位「下跌(变体)− 下跌(B)」≥ −5pp
  ③ 资产中位 Calmar(年化 ÷ |最大回撤|)变化 > 0

用法:python3 docs/research/t190_s679_reentry.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import crash_atlas_common as K  # noqa: E402  (台账 S-675 内核,唯一一份)
from src.data.signals import tom  # noqa: E402  (只读,不改 src)

DATA_ROOT = Path(os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local"))
OUT_JSON = HERE / "t190_results.json"
CACHE_DIR = DATA_ROOT / "research" / "t190"

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

WARM, MA_N = tom.WARM, tom.MA_N
UNIT, STEP, CAP = tom.UNIT, tom.STEP, tom.CAP
RALLY_SIZE, RALLY_TP = tom.RALLY_SIZE, tom.RALLY_TP

BEAR_THR_EQ, BEAR_THR_CRYPTO = 0.20, 0.50
CUTOFF_CRYPTO = "2019-05-31"          # S-601 看过的 12 个币:这之前
S601_COINS = {"XRP", "BNB", "LTC", "BCH", "ADA", "LINK",
              "DOGE", "XLM", "TRX", "ETC", "XMR", "ATOM"}
MIN_BARS = 400
G1_END = "2014-12-31"
C1_RECOVERY_PP, C2_CRASH_PP, C3_CALMAR = 0.10, -0.05, 0.0

# ── DB(只读)────────────────────────────────────────────────────────────────────


def _get(path: str, rng: Optional[str] = None, tries: int = 4) -> list[dict]:
    last: Optional[Exception] = None
    for k in range(tries):
        try:
            req = urllib.request.Request(URL + "/rest/v1/" + path, headers=HDR)
            if rng:
                req.add_header("Range", rng)
                req.add_header("Range-Unit", "items")
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:                      # 网络抖动 / 超时:退避重试
            last = e
            time.sleep(1.5 * (k + 1))
    raise last if last else RuntimeError("fetch failed")


def _fetch_all(path: str, page: int = 1000) -> list[dict]:
    out, lo = [], 0
    while True:
        rows = _get(path, "%d-%d" % (lo, lo + page - 1))
        if not rows:
            return out
        out.extend(rows)
        lo += page


def _fetch_all_threaded(paths: list[str], workers: int = 10) -> list[list[dict]]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda p: _fetch_all(p), paths))


# ── 变体:trade_path 参数化重写(只读 import 原函数做对照)────────────────────────


def x1v_gross(close: pd.Series, variant: str = "B") -> pd.Series:
    """与 tom.trade_path(close, "rally", 0.0, exit_mode="l20", vol=True) 逐行同构,只多两个参数:
    variant="V1" ⇒ 反弹仓去掉 +15% 止盈;variant="V2" ⇒ 多头进场只要求收盘 > 前 55 日最高收盘。"""
    s = close.dropna().astype(float)
    c, n = s.to_numpy(), len(s)
    g = np.ones(n)
    mode, k, last_add, entry = "long", 0, None, None
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h20, l20 = c[t - 20:t].max(), c[t - 20:t].min()
        h55, l10 = c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = (x > h55) if variant == "V2" else (x > ma and x > h20)
        if mode == "long":
            if x < l20:                                  # exit_mode="l20":破前 20 日低即全平
                mode, k, last_add = "flat", 0, None
                g[t] = 0.0
                continue
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + UNIT <= CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                k, last_add = k + 1, x
            if x < ma and x < l20:
                k, last_add = 0, None
                mode, entry = "flat", None               # bear="rally" ⇒ 不开空
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
            elif x > h20:                               # bear="rally":反弹仓 0.5
                mode, entry = "rally", x
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
            elif (variant != "V1" and x >= entry * RALLY_TP) or x < l10:
                mode = "flat"
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": RALLY_SIZE}[mode]
    out = pd.Series(g, index=s.index)
    vs = tom.vol_scale(s)
    return out.where(np.arange(n) < WARM, out * vs)


def verify_btc(btc: pd.Series) -> dict[str, Any]:
    """先证明 B 与原函数在 BTC 全史上逐日一致;不一致 ⇒ 返回 mismatch 摘要(调用方停)。"""
    ref = tom.trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
    mine = x1v_gross(btc, "B")
    ref_v, mine_v = ref.to_numpy(), mine.to_numpy()
    eq = bool(np.array_equal(ref_v, mine_v))
    diff_idx = np.nonzero(~np.isclose(ref_v, mine_v, rtol=0, atol=1e-12))[0]
    out = {"n_days": int(len(ref_v)), "identical": eq, "n_diff": int(len(diff_idx))}
    if not eq:
        d = diff_idx[:20]
        out["diff_sample"] = [{"date": str(ref.index[i].date()), "ref": float(ref_v[i]),
                                "mine": float(mine_v[i])} for i in d]
        out["first_diff_date"] = str(ref.index[diff_idx[0]].date())
    return out


# ── 净值与指标 ───────────────────────────────────────────────────────────────


def build_nav(close: pd.Series, g: pd.Series) -> pd.Series:
    """净值从第 201 天起算(index = WARM = 200 那天 = 1.0)。收益口径 = tom.trade_returns(funding=None ⇒ 默认 0.10)。"""
    s = close.dropna().astype(float)
    r = tom.trade_returns(s, g, None).reindex(s.index)      # trade_returns 丢掉第 1 天 ⇒ 对齐回 s.index
    nav = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) <= WARM:
        return nav.dropna()
    nav.iloc[WARM] = 1.0
    for t in range(WARM + 1, len(s)):
        nav.iloc[t] = nav.iloc[t - 1] * (1.0 + r.iloc[t])
    return nav.dropna()


def metrics(nav: pd.Series, g: pd.Series) -> dict[str, Any]:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    span = (nav.index[-1] - nav.index[0]).days
    years = span / 365.0
    ann = float((nav.iloc[-1] / nav.iloc[0]) ** (365.0 / span) - 1.0) if span > 0 else None
    mdd = float((nav / nav.cummax() - 1.0).min())
    calmar = (ann / abs(mdd)) if (ann is not None and mdd < 0) else None
    gf = g.reindex(nav.index)
    avg_gross = float(gf.mean())
    prev = float(gf.iloc[0]) - 1.0
    turn = float(gf.diff().abs().sum() + abs(prev))
    return {"ann": ann, "max_dd": mdd, "calmar": calmar, "avg_gross": avg_gross,
            "turnover_total": turn, "turnover_ann": (turn / years) if years > 0 else None,
            "nav_end": float(nav.iloc[-1]), "n_days": int(len(nav))}


def false_reentries(g: pd.Series, horizon: int = 20) -> int:
    """假回场次数:回场(前一日空仓、当日有敞口)后 20 天内又出场(敞口归零)。"""
    v = g.to_numpy(dtype=float)
    cnt = 0
    for t in range(1, len(v)):
        if v[t - 1] == 0.0 and v[t] > 0.0:
            w = v[t + 1:t + 1 + horizon]
            if len(w) and bool(np.any(w == 0.0)):
                cnt += 1
    return cnt


def eval_asset(close: pd.Series, thr: float, name: str) -> dict[str, Any]:
    s = close.dropna().astype(float).sort_index()
    eps = K.bear_episodes(s, thr)
    rec: dict[str, Any] = {"name": name, "n_bars": int(len(s)),
                            "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
                            "n_episodes": len(eps), "n_open_episodes": int(sum(1 for e in eps if e.get("open"))),
                            "episodes": [{"peak_d": str(pd.Timestamp(e["peak_d"]).date()),
                                          "trough_d": str(pd.Timestamp(e["trough_d"]).date()),
                                          "open": bool(e.get("open")),
                                          "first_leg": bool(e.get("first_leg"))} for e in eps],
                            "variants": {}}
    hold = s / s.iloc[WARM] if len(s) > WARM else s * np.nan
    if len(s) > WARM:
        hold.iloc[:WARM] = np.nan
    rec["hold_phase"] = [K.phase_returns(hold, e) for e in eps]
    gs = {}
    for v in ("B", "V1", "V2"):
        g = x1v_gross(s, v)
        gs[v] = g
        nav = build_nav(s, g)
        ph = [K.phase_returns(nav, e) for e in eps]
        # 前高早于净值起点(第 201 天)的段:下跌段被截断(所有变体同样截断,差值仍可比)
        nav0 = nav.index[0] if len(nav) else None
        rec["variants"][v] = {"metrics": metrics(nav, g),
                              "phase": ph,
                              "false_reentries": false_reentries(g),
                              "n_segments_peak_before_nav": int(sum(
                                  1 for e in eps if nav0 is not None and pd.Timestamp(e["peak_d"]) < nav0)),
                              "n_segments_scored": int(sum(
                                  1 for p in ph if p["recovery"] is not None))}
    # B 的反弹 +15% 止盈触发次数(V1 去掉它):B 当日空仓而 V1 仍在反弹仓 ⇒ B 走的是止盈
    gb, g1, g2 = gs["B"].to_numpy(), gs["V1"].to_numpy(), gs["V2"].to_numpy()
    rec["diag"] = {
        "rally_tp_exits_B": int(np.sum((gb == 0.0) & (g1 > 0.0))),
        "diff_days_V1_vs_B": int(np.sum(g1 != gb)),
        "diff_days_V2_vs_B": int(np.sum(g2 != gb)),
        "mean_abs_exposure_diff_V1": float(np.mean(np.abs(g1 - gb))) if len(gb) else None,
        "mean_abs_exposure_diff_V2": float(np.mean(np.abs(g2 - gb))) if len(gb) else None,
    }
    return rec


def eval_asset_lagged(close: pd.Series, thr: float, lag: int = 1) -> dict[str, Any]:
    """「挪一天」:决定再晚一天生效(g 多挪 1 天)时的同一套指标。"""
    s = close.dropna().astype(float).sort_index()
    eps = K.bear_episodes(s, thr)
    out: dict[str, Any] = {"n_episodes": len(eps), "variants": {}}
    for v in ("B", "V1", "V2"):
        g = x1v_gross(s, v).shift(lag)
        nav = build_nav(s, g)
        out["variants"][v] = {"metrics": metrics(nav, g),
                              "phase": [K.phase_returns(nav, e) for e in eps]}
    return out


# ── 汇总 ─────────────────────────────────────────────────────────────────────


def _med(vals: list[float]) -> Optional[float]:
    v = [x for x in vals if x is not None and x == x]
    return float(np.median(v)) if v else None


def _f(x: Optional[float], fmt: str = "%.1f") -> str:
    """None ⇒ 'NA';0.0 必须显示成 0.0(不能用 `or nan`,那会把 0 变成 nan)。"""
    if x is None or x != x:
        return "NA"
    return fmt % x


def aggregate(assets: list[dict], lag: bool = False) -> dict[str, Any]:
    """一组内的判据与只报项。lag=True 用「挪一天」(决定再晚一天生效)的口径。

    判据口径(S-679 原文):① 段中位「修复差」;② 段中位「下跌差」;③ 资产中位 Calmar 变化。
    「段中位」= 逐段差的中位数(池化所有段);「资产中位」= 逐资产量再取中位数。
    另外并列报「资产等权」的修复差/下跌差(每资产先取中位再跨资产取中位)作稳健性参考。
    """
    def pick(a: dict, v: str, field: str):
        if lag:
            return a["_lag"]["variants"][v][field]
        return a["variants"][v][field]

    out: dict[str, Any] = {"n_assets": len(assets), "n_episodes": int(sum(a["n_episodes"] for a in assets)),
                           "n_assets_with_episodes": int(sum(1 for a in assets if a["n_episodes"])),
                           "variants": {}}
    base: dict[str, list] = {k: [] for k in ("ann", "max_dd", "calmar", "avg_gross", "turnover_ann")}
    cap_b, fre_b = [], []
    dg = {"rally_tp_exits_B": 0, "diff_days_V1_vs_B": 0, "diff_days_V2_vs_B": 0,
          "mad_V1": [], "mad_V2": [], "seg_peak_before_nav": 0}
    for a in assets:
        mb = pick(a, "B", "metrics")
        for k in base:
            if mb.get(k) is not None:
                base[k].append(mb[k])
        if not lag:
            fre_b.append(a["variants"]["B"]["false_reentries"])
            hp = a["hold_phase"]
            for i in range(len(hp)):
                hr = hp[i]["recovery"]
                br = a["variants"]["B"]["phase"][i]["recovery"]
                if hr is not None and hr > 0 and br is not None:
                    cap_b.append(br / hr)
            d = a.get("diag", {})
            dg["rally_tp_exits_B"] += int(d.get("rally_tp_exits_B", 0))
            dg["diff_days_V1_vs_B"] += int(d.get("diff_days_V1_vs_B", 0))
            dg["diff_days_V2_vs_B"] += int(d.get("diff_days_V2_vs_B", 0))
            if d.get("mean_abs_exposure_diff_V1") is not None:
                dg["mad_V1"].append(d["mean_abs_exposure_diff_V1"])
            if d.get("mean_abs_exposure_diff_V2") is not None:
                dg["mad_V2"].append(d["mean_abs_exposure_diff_V2"])
            dg["seg_peak_before_nav"] += int(a["variants"]["B"].get("n_segments_peak_before_nav", 0))

    for v in ("V1", "V2"):
        seg_r, seg_c = [], []
        asset_r, asset_c = [], []
        cdm, annm, mddm, gm, tm, fre_v, cap_v = [], [], [], [], [], [], []
        ann_v, mdd_v, calmar_v = [], [], []
        n_calmar = 0
        for a in assets:
            ph, phb = pick(a, v, "phase"), pick(a, "B", "phase")
            mt, mtb = pick(a, v, "metrics"), pick(a, "B", "metrics")
            a_r, a_c = [], []
            for i in range(len(ph)):
                if phb[i]["recovery"] is None or ph[i]["recovery"] is None:
                    continue
                a_r.append(ph[i]["recovery"] - phb[i]["recovery"])
                if phb[i]["crash"] is not None and ph[i]["crash"] is not None:
                    a_c.append(ph[i]["crash"] - phb[i]["crash"])
            if a_r:
                asset_r.append(float(np.median(a_r)))
            if a_c:
                asset_c.append(float(np.median(a_c)))
            seg_r.extend(a_r)
            seg_c.extend(a_c)
            if mt.get("calmar") is not None and mtb.get("calmar") is not None:
                cdm.append(mt["calmar"] - mtb["calmar"])
                n_calmar += 1
            if mt.get("ann") is not None and mtb.get("ann") is not None:
                annm.append(mt["ann"] - mtb["ann"])
                ann_v.append(mt["ann"])
            if mt.get("max_dd") is not None and mtb.get("max_dd") is not None:
                mddm.append(mt["max_dd"] - mtb["max_dd"])
                mdd_v.append(mt["max_dd"])
            if mt.get("calmar") is not None:
                calmar_v.append(mt["calmar"])
            if mt.get("avg_gross") is not None:
                gm.append(mt["avg_gross"])
            if mt.get("turnover_ann") is not None:
                tm.append(mt["turnover_ann"])
            if not lag:
                fre_v.append(a["variants"][v]["false_reentries"])
                hp = a["hold_phase"]
                for i in range(len(hp)):
                    hr = hp[i]["recovery"]
                    vr = a["variants"][v]["phase"][i]["recovery"]
                    if hr is not None and hr > 0 and vr is not None:
                        cap_v.append(vr / hr)
        rec_med, crash_med, calmar_med = _med(seg_r), _med(seg_c), _med(cdm)
        c1 = rec_med is not None and rec_med >= C1_RECOVERY_PP
        c2 = crash_med is not None and crash_med >= C2_CRASH_PP
        c3 = calmar_med is not None and calmar_med > C3_CALMAR

        def _sign(vals: list[float]) -> dict[str, int]:
            p = sum(1 for x in vals if x > 1e-12)
            n = sum(1 for x in vals if x < -1e-12)
            return {"pos": p, "neg": n, "zero": len(vals) - p - n}

        out["variants"][v] = {
            "criterion_1_recovery_diff_median_pp": (rec_med * 100) if rec_med is not None else None,
            "criterion_2_crash_diff_median_pp": (crash_med * 100) if crash_med is not None else None,
            "criterion_3_calmar_diff_median": calmar_med,
            "criterion_1_pass": bool(c1), "criterion_2_pass": bool(c2), "criterion_3_pass": bool(c3),
            "group_pass": bool(c1 and c2 and c3),
            "n_segments_scored": len(seg_r), "n_segments_crash_scored": len(seg_c), "n_calmar_pairs": n_calmar,
            "recovery_diff_sign_counts": _sign(seg_r),
            "crash_diff_sign_counts": _sign(seg_c),
            "recovery_diff_mean_pp": (float(np.mean(seg_r)) * 100) if seg_r else None,
            "recovery_diff_p25_pp": (float(np.percentile(seg_r, 25)) * 100) if seg_r else None,
            "recovery_diff_p75_pp": (float(np.percentile(seg_r, 75)) * 100) if seg_r else None,
            "recovery_diff_max_pp": (float(np.max(seg_r)) * 100) if seg_r else None,
            "recovery_diff_min_pp": (float(np.min(seg_r)) * 100) if seg_r else None,
            "rec_diff_asset_median_pp": (_med(asset_r) * 100) if _med(asset_r) is not None else None,
            "crash_diff_asset_median_pp": (_med(asset_c) * 100) if _med(asset_c) is not None else None,
            "ann_diff_median_pp": (_med(annm) * 100) if _med(annm) is not None else None,
            "maxdd_diff_median_pp": (_med(mddm) * 100) if _med(mddm) is not None else None,
            "ann_median": _med(ann_v),
            "max_dd_median": _med(mdd_v),
            "calmar_median": _med(calmar_v),
            "avg_gross_median": _med(gm),
            "turnover_ann_median": _med(tm),
            "recovery_capture_vs_hold_median": _med(cap_v),
            "false_reentries_total": int(sum(fre_v)),
            "false_reentries_median": _med(fre_v),
        }
    out["base_B"] = {
        "recovery_capture_vs_hold_median": _med(cap_b),
        "false_reentries_total": int(sum(fre_b)),
        "false_reentries_median": _med(fre_b),
        "ann_median": _med(base["ann"]), "max_dd_median": _med(base["max_dd"]),
        "calmar_median": _med(base["calmar"]), "avg_gross_median": _med(base["avg_gross"]),
        "turnover_ann_median": _med(base["turnover_ann"]),
    }
    out["diag"] = {"rally_tp_exits_B_total": dg["rally_tp_exits_B"],
                   "diff_days_V1_vs_B_total": dg["diff_days_V1_vs_B"],
                   "diff_days_V2_vs_B_total": dg["diff_days_V2_vs_B"],
                   "mean_abs_exposure_diff_V1_median": _med(dg["mad_V1"]),
                   "mean_abs_exposure_diff_V2_median": _med(dg["mad_V2"]),
                   "n_segments_peak_before_nav": dg["seg_peak_before_nav"]}
    return out


# ── 数据 ─────────────────────────────────────────────────────────────────────


def load_btc_eth() -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for sym in ("BTC", "ETH"):
        rows = _fetch_all("asset_mcap_daily?select=symbol,d,price&symbol=eq.%s&order=symbol.asc,d.asc" % sym)
        if not rows:
            continue
        s = pd.Series({pd.Timestamp(r["d"]): float(r["price"]) for r in rows})
        out[sym] = s.sort_index()
    return out


def load_equities() -> dict[str, pd.Series]:
    keys = sorted({r["key"] for r in _fetch_all("world50_mcap_weekly?select=key&order=key.asc,d.asc")})
    syms = [k for k in keys if "." not in k] + [k for k in keys if "." in k]
    cache_f = CACHE_DIR / "_cache_equity_eodhd.json"
    cache: dict[str, list] = {}
    if cache_f.exists():
        cache = json.loads(cache_f.read_text())
    todo = [s for s in syms if s not in cache]
    if todo:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        paths = {s: ("ohlcv_daily?select=symbol,trade_date,close&symbol=eq.%s&source=eq.eodhd"
                     "&asset_class=eq.Equity&order=symbol.asc,trade_date.asc" % s) for s in todo}
        done = 0
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_fetch_all, paths[s]): s for s in todo}
            for fut in as_completed(futs):
                s = futs[fut]
                cache[s] = [[r["trade_date"], r["close"]] for r in fut.result()]
                done += 1
                if done % 20 == 0:
                    cache_f.write_text(json.dumps(cache))
        cache_f.write_text(json.dumps(cache))
    out: dict[str, pd.Series] = {}
    for sym, rows in cache.items():
        if not rows:
            continue
        s = pd.Series({pd.Timestamp(d): float(c) for d, c in rows if c is not None})
        s = s.sort_index()
        s = s[~s.index.duplicated(keep="first")]
        out[sym] = s
    return out


def load_g1() -> pd.Series:
    s = K.load_fred("NASDAQCOM", str(DATA_ROOT / "research" / "crash_atlas" / "fred"))
    s = s["1971-02-01":"2014-12-31"]
    return s.dropna()


def load_g2() -> dict[str, pd.Series]:
    """S-677 的 Binance USDT 现货对。BTC / ETH 是设计 X1V 用的(S-601)⇒ 不进判据组,只报(台账 S-679:
    「资产(只用没用来设计 X1V 的…)… BTC / ETH 只报」)。"""
    out: dict[str, pd.Series] = {}
    p = DATA_ROOT / "research" / "s677" / "_bv_daily.jsonl"
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            sym = rec["symbol"]
            if sym in ("BTC", "ETH"):
                continue
            rows = rec["bars"]
            if sym in S601_COINS:
                rows = [b for b in rows if b[0] < CUTOFF_CRYPTO]
            if len(rows) < MIN_BARS:
                continue
            s = pd.Series({pd.Timestamp(b[0]): float(b[4]) for b in rows})
            s = s.sort_index()
            s = s[~s.index.duplicated(keep="first")]
            out[sym] = s
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────


def main() -> dict[str, Any]:
    t0 = datetime.now(timezone.utc)
    res: dict[str, Any] = {"task": "T-190", "protocol": "S-679",
                           "generated_at": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "definitions": {"bear_threshold_equity": BEAR_THR_EQ,
                                           "bear_threshold_crypto": BEAR_THR_CRYPTO,
                                           "rebound": "同门槛",
                                           "phase": "phase_returns(pre_days=60, post_days=120)",
                                           "nav_start": "第 201 天(index 200)",
                                           "cost": "10 bp × |Δ 敞口|,现金 0,tom.trade_returns 口径(funding=None ⇒ 默认 0.10)",
                                           "criterion_1": "段中位修复差 ≥ +10pp",
                                           "criterion_2": "段中位下跌差 ≥ −5pp",
                                           "criterion_3": "资产中位 Calmar 变化 > 0",
                                           "pass_rule": "一个变体 ≥ 2 组过 ⇒ 记「过」",
                                           "min_bars": MIN_BARS,
                                           "s601_cutoff_crypto": CUTOFF_CRYPTO,
                                           "g1_window": "1971-02 → 2014-12"}}

    btc_eth = load_btc_eth()
    btc = btc_eth["BTC"]
    ver = verify_btc(btc)
    res["verification"] = ver
    print("verify B == tom.trade_path on BTC: identical=%s n_days=%d n_diff=%d"
          % (ver["identical"], ver["n_days"], ver["n_diff"]))
    if not ver["identical"]:
        res["stopped"] = True
        OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        print("STOP: B 与原函数不一致 ⇒ 不继续。差异样本:", json.dumps(ver.get("diff_sample", [])[:5], ensure_ascii=False))
        return res

    groups: dict[str, list[dict]] = {}
    closes: dict[str, dict[str, pd.Series]] = {}
    thr_of: dict[str, float] = {}

    g1 = load_g1()
    groups["G1_NASDAQ_1971_2014"] = [eval_asset(g1, BEAR_THR_EQ, "NASDAQCOM")]
    closes["G1_NASDAQ_1971_2014"] = {"NASDAQCOM": g1}
    thr_of["G1_NASDAQ_1971_2014"] = BEAR_THR_EQ

    g2 = load_g2()
    groups["G2_S677_PAIRS"] = [eval_asset(s, BEAR_THR_CRYPTO, sym) for sym, s in sorted(g2.items())]
    closes["G2_S677_PAIRS"] = {sym: s for sym, s in sorted(g2.items())}
    thr_of["G2_S677_PAIRS"] = BEAR_THR_CRYPTO

    eq = load_equities()
    eq = {k: v for k, v in eq.items() if len(v) >= MIN_BARS}
    groups["G3_WORLD50_EQUITIES"] = [eval_asset(s, BEAR_THR_EQ, sym) for sym, s in sorted(eq.items())]
    closes["G3_WORLD50_EQUITIES"] = {sym: s for sym, s in sorted(eq.items())}
    thr_of["G3_WORLD50_EQUITIES"] = BEAR_THR_EQ

    res["groups"] = {}
    for gname, assets in groups.items():
        for a in assets:
            a["_lag"] = eval_asset_lagged(closes[gname][a["name"]], thr_of[gname], lag=1)
        res["groups"][gname] = {"n_assets": len(assets),
                                "n_assets_excluded_lt_min_bars": (
                                    len(closes[gname]) - len(assets) if gname == "G3_WORLD50_EQUITIES" else 0),
                                "aggregate": aggregate(assets, lag=False),
                                "aggregate_lag1": aggregate(assets, lag=True)}

    # 只报:BTC / ETH
    rep: dict[str, Any] = {}
    for sym, s in btc_eth.items():
        a = eval_asset(s, BEAR_THR_CRYPTO, sym)
        rep[sym] = {"n_bars": a["n_bars"], "start": a["start"], "end": a["end"],
                    "n_episodes": a["n_episodes"],
                    "variants": {v: {"metrics": a["variants"][v]["metrics"],
                                     "false_reentries": a["variants"][v]["false_reentries"],
                                     "phase_median": {"crash": _med([p["crash"] for p in a["variants"][v]["phase"]]),
                                                      "recovery": _med([p["recovery"] for p in a["variants"][v]["phase"]])}}
                                 for v in ("B", "V1", "V2")}}
    res["report_only_btc_eth"] = rep

    # 判定
    verdict: dict[str, Any] = {}
    for v in ("V1", "V2"):
        passed = [g for g, gg in res["groups"].items() if gg["aggregate"]["variants"][v]["group_pass"]]
        verdict[v] = {"groups_passed": passed, "n_groups_passed": len(passed),
                      "verdict": "过" if len(passed) >= 2 else "不过"}
    res["verdict"] = verdict

    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))

    # ── 汇总打印 ──
    print("\n=== 判据(组 × 变体):修复差pp / 下跌差pp / Calmar变化 | c1 c2 c3 → 组过 ===")
    for gname, gg in res["groups"].items():
        ag = gg["aggregate"]
        print("  %-24s assets=%-4d eps=%-4d | %s" % (gname, ag["n_assets"], ag["n_episodes"],
              "  ".join("[%s] %s/%s/%s %s%s%s → %s" % (
                  v, _f(ag["variants"][v]["criterion_1_recovery_diff_median_pp"], "%.1f"),
                  _f(ag["variants"][v]["criterion_2_crash_diff_median_pp"], "%.1f"),
                  _f(ag["variants"][v]["criterion_3_calmar_diff_median"], "%.3f"),
                  "Y" if ag["variants"][v]["criterion_1_pass"] else "n",
                  "Y" if ag["variants"][v]["criterion_2_pass"] else "n",
                  "Y" if ag["variants"][v]["criterion_3_pass"] else "n",
                  "PASS" if ag["variants"][v]["group_pass"] else "fail")
                  for v in ("V1", "V2"))))
    print("\n=== 挪一天(决定再晚一天生效) ===")
    for gname, gg in res["groups"].items():
        ag = gg["aggregate_lag1"]
        print("  %-24s | %s" % (gname, "  ".join("[%s] %s/%s/%s → %s" % (
            v, _f(ag["variants"][v]["criterion_1_recovery_diff_median_pp"], "%.1f"),
            _f(ag["variants"][v]["criterion_2_crash_diff_median_pp"], "%.1f"),
            _f(ag["variants"][v]["criterion_3_calmar_diff_median"], "%.3f"),
            "PASS" if ag["variants"][v]["group_pass"] else "fail") for v in ("V1", "V2"))))
    print("\n=== 只报(年化 / 回撤 / Calmar / 平均敞口 / 换手 / 修复抓到持有 / 假回场) ===")
    for gname, gg in res["groups"].items():
        ag = gg["aggregate"]
        b = ag["base_B"]
        print("  %-24s [B] ann=%s%% dd=%s%% calmar=%s gross=%s turn/yr=%s cap=%s 假回场=%d" % (
            gname, _f(100 * b["ann_median"] if b["ann_median"] is not None else None, "%.1f"),
            _f(100 * b["max_dd_median"] if b["max_dd_median"] is not None else None, "%.1f"),
            _f(b["calmar_median"], "%.2f"), _f(b["avg_gross_median"], "%.2f"),
            _f(b["turnover_ann_median"], "%.2f"),
            _f(b["recovery_capture_vs_hold_median"], "%.2f"), b["false_reentries_total"]))
        for v in ("V1", "V2"):
            av = ag["variants"][v]
            print("  %-24s [%s] ann=%s%% dd=%s%% calmar=%s gross=%s turn/yr=%s cap=%s 假回场=%d" % (
                gname, v,
                _f(100 * av["ann_median"] if av["ann_median"] is not None else None, "%.1f"),
                _f(100 * av["max_dd_median"] if av["max_dd_median"] is not None else None, "%.1f"),
                _f(av["calmar_median"], "%.2f"), _f(av["avg_gross_median"], "%.2f"),
                _f(av["turnover_ann_median"], "%.2f"),
                _f(av["recovery_capture_vs_hold_median"], "%.2f"), av["false_reentries_total"]))
    print("\n=== 诊断(V1 与 B 差在哪 / 前高早于净值起点的段) ===")
    for gname, gg in res["groups"].items():
        d = gg["aggregate"]["diag"]
        print("  %-24s 反弹+15%%止盈触发(B)=%d | 与 B 敞口不同的天数 V1=%d V2=%d | 敞口差中位 V1=%s V2=%s | 前高早于净值起点的段=%d" % (
            gname, d["rally_tp_exits_B_total"], d["diff_days_V1_vs_B_total"],
            d["diff_days_V2_vs_B_total"], _f(d["mean_abs_exposure_diff_V1_median"], "%.4f"),
            _f(d["mean_abs_exposure_diff_V2_median"], "%.4f"), d["n_segments_peak_before_nav"]))
    print("\n=== 修复差(变体 − B)的段级分布 ===")
    for gname, gg in res["groups"].items():
        for v in ("V1", "V2"):
            av = gg["aggregate"]["variants"][v]
            sc = av["recovery_diff_sign_counts"]
            print("  %-24s %s 段=%d 正=%d 负=%d 零=%d | 中位=%s 均值=%s p25=%s p75=%s 最大=%s 最小=%s" % (
                gname, v, av["n_segments_scored"], sc["pos"], sc["neg"], sc["zero"],
                _f(av["criterion_1_recovery_diff_median_pp"], "%.2f"),
                _f(av["recovery_diff_mean_pp"], "%.2f"), _f(av["recovery_diff_p25_pp"], "%.2f"),
                _f(av["recovery_diff_p75_pp"], "%.2f"), _f(av["recovery_diff_max_pp"], "%.1f"),
                _f(av["recovery_diff_min_pp"], "%.1f")))
    print("\n=== BTC / ETH(只报) ===")
    for sym, rr in rep.items():
        print("  %-4s eps=%-3d " % (sym, rr["n_episodes"]) + "  ".join(
            "[%s] ann=%s%% dd=%s%% calmar=%s rec=%s%% 假回场=%d" % (
                v, _f(100 * rr["variants"][v]["metrics"].get("ann")
                      if rr["variants"][v]["metrics"].get("ann") is not None else None, "%.1f"),
                _f(100 * rr["variants"][v]["metrics"].get("max_dd")
                   if rr["variants"][v]["metrics"].get("max_dd") is not None else None, "%.1f"),
                _f(rr["variants"][v]["metrics"].get("calmar"), "%.2f"),
                _f(100 * rr["variants"][v]["phase_median"]["recovery"]
                   if rr["variants"][v]["phase_median"]["recovery"] is not None else None, "%.1f"),
                rr["variants"][v]["false_reentries"]) for v in ("B", "V1", "V2")))
    print("\n=== 判定 ===")
    for v in ("V1", "V2"):
        print("  %s: 过 %d 组 %s ⇒ %s" % (v, verdict[v]["n_groups_passed"],
                                         verdict[v]["groups_passed"], verdict[v]["verdict"]))
    print("wrote %s" % OUT_JSON)
    return res


if __name__ == "__main__":
    main()
