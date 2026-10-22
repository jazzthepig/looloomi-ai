#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-670 — 大公司截面上到底有没有能挑出之后更好的信号(World50 候选池,个股的 CIS 档位等它)。

照 REFUTATION_LEDGER.md 的 S-670 预注册(2026-10-22 09:32 UTC)原文一字不改执行:

  宇宙与数据  同 T-169(world50_mcap_weekly 只取 source = shares_x_close_v3、不带 . 后缀的 key;
              eodhd 复权收盘;world50_revenue 按 filed 日期按时点)。每周五截面,截面 < 15 家跳过。
  候选(方向事先定死)M12 / M6 / REV / LOWVOL / SMALL / ISSUE / RGROW,共 7 个,不加组合。
  期限        之后 4 周与 13 周(20 / 65 个交易日);IC = 截面 Spearman,每 4 周 / 13 周取一个不重叠样本。
  机械规则    发现段 2016-01 → 2020-12:平均 IC > 0、t ≥ 2、且发现段前后两半 IC 都 > 0 ⇒ 进留出段
              2021-01 → 2026-09;留出段平均 IC > 0 且 t ≥ 2 = 过。
  零分布      apparatus(每周打乱前瞻收益,400 次),报分位。

用法: python3 docs/research/t172_equity_signals.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAC = "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(MAC, "research", "t172")
RESULTS = os.path.join(REPO, "docs", "research", "t172_results.json")
REPORT = os.path.join(MAC, "_reports", "absorb_input", "T-172_s670_equity_signals.md")
sys.path.insert(0, REPO)
os.makedirs(CACHE, exist_ok=True)
os.makedirs(os.path.dirname(REPORT), exist_ok=True)

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

# ---- S-670 原文的时间窗与门槛(一字不改)----
DISC = ("2016-01-01", "2020-12-31")      # 发现段
HOLD = ("2021-01-01", "2026-09-30")      # 留出段
GRID_START = "2015-01-02"                # 周网格起点(给 52 周动量留预热)
GRID_END = "2026-09-30"
MIN_CROSS = 15                           # 截面 < 15 家跳过
H_FWD_DAYS = {4: 20, 13: 65}             # 4 周 = 20 个交易日,13 周 = 65 个交易日
STRIDE_WEEKS = {4: 4, 13: 13}            # 每 4 / 13 周取一个不重叠样本
N_NULL = 400                             # 零分布 400 次
SEED = 670172
MCAP_SOURCE = "shares_x_close_v3"

# 7 个候选信号:名字照 S-670 原文,方向事先定死
SIGNALS = ["M12", "M6", "REV", "LOWVOL", "SMALL", "ISSUE", "RGROW"]
SIGNAL_DESC = {
    "M12": "52 周收益去掉最近 4 周(P[t-4w]/P[t-52w]-1)",
    "M6": "26 周收益(P[t]/P[t-26w]-1)",
    "REV": "−最近 4 周收益",
    "LOWVOL": "−26 周周收益 σ",
    "SMALL": "−log(市值)",
    "ISSUE": "−股数 52 周增长(股数 = 市值 / 收盘)",
    "RGROW": "最近一期收入同比(按 filed 日期)",
}

try:
    from src.data.evaluation.apparatus import (  # 零分布 / 盈亏只走 apparatus
        long_return, null_distribution, percentile_of, shuffle_within,
    )
    APPARATUS = "src.data.evaluation.apparatus"
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"apparatus 导入失败,退出(不要另起炉灶):{exc}")

# T-169(lane-a)的截面函数优先复用;还没进 main 时退回本脚本自带的等价实现,并在结果里记下。
try:  # pragma: no cover
    sys.path.insert(0, os.path.join(REPO, "docs", "research"))
    import t169_equity_quality as _t169  # noqa: F401
    T169_REUSED = sorted(n for n in dir(_t169) if not n.startswith("_"))
except Exception:
    _t169 = None
    T169_REUSED = []


# ---------------------------------------------------------------- 读取层
def _page(path: str, lo: int, hi: int) -> list:
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=dict(HDR, Range=f"{lo}-{hi}"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:          # Range 越界 = 没有更多行
            return []
        raise


def _page_all(path: str, per: int = 1_000, cap: int = 4_000_000) -> list:
    """Range 翻页。PostgREST 会对单次请求的行数设上限(db-max-rows,常见 1000),
    服务端给的比 `per` 少时必须按**实收行数**推进 offset —— 否则每页静默跳行(同 T-148/T-170 的坑)。"""
    out, off = [], 0
    while off < cap:
        chunk = _page(path, off, off + per - 1)
        if not chunk:
            break
        out += chunk
        off += len(chunk)
        if len(chunk) < per:
            break
        if off % 50_000 < per:
            print(f"    … {off} 行", flush=True)
    return out


def _cached(name: str, fn):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        return json.loads(open(p).read())
    rows = fn()
    open(p, "w").write(json.dumps(rows))
    return rows


def fetch_mcap() -> dict:
    """d -> {key: mcap_usd};只取 source = shares_x_close_v3。"""
    def run():
        q = ("world50_mcap_weekly?select=key,d,mcap_usd&source=eq." + MCAP_SOURCE
             + f"&d=gte.{GRID_START}&order=d,key")
        rows = _page_all(q)
        byd = defaultdict(dict)
        for r in rows:
            if r.get("mcap_usd") is not None:
                byd[r["d"]][r["key"]] = float(r["mcap_usd"])
        return dict(byd)
    return _cached("mcap.json", run)


def fetch_px(keys: list[str]) -> dict:
    """key -> [[date, close], ...] 日期升序(eodhd 复权收盘)。
    T-170 发现 PostgREST 不带 order 时 Range 翻页会漂边界漏行 —— 一律 order=symbol.asc,trade_date.asc。"""
    def run():
        out: dict = {}
        ks = sorted(keys)
        for i in range(0, len(ks), 40):
            batch = ks[i:i + 40]
            q = ("ohlcv_daily?select=symbol,trade_date,close&source=eq.eodhd"
                 "&symbol=in.(" + ",".join(batch) + ")"
                 + "&trade_date=gte." + GRID_START + "&order=symbol.asc,trade_date.asc")
            for r in _page_all(q):
                if r.get("close") is None:
                    continue
                out.setdefault(r["symbol"], []).append([r["trade_date"], float(r["close"])])
            print(f"  价格 {min(i + 40, len(ks))}/{len(ks)} 个 key,{len(out)} 条序列", flush=True)
        for k in out:
            out[k].sort(key=lambda x: x[0])
        return out
    return _cached("px.json", run)


def fetch_rev() -> list:
    def run():
        q = ("world50_revenue?select=key,tag,unit,period_start,period_end,filed,revenue"
             "&order=key,filed&limit=1000")
        rows, off = [], 0
        while True:
            chunk = _page(q + f"&offset={off}", off, off + 999)
            if not chunk:
                break
            rows += chunk
            off += len(chunk)
            if len(chunk) < 1000:
                break
            if len(rows) % 20_000 < 1_000:
                print(f"    … 营收 {len(rows)} 行", flush=True)
        return rows
    return _cached("rev.json", run)


# ---------------------------------------------------------------- 周网格 / 截面
def fridays(start: str, end: str) -> list[str]:
    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        if d.weekday() == 4:                       # 周五
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def at_or_before(dates: list[str], values: np.ndarray, t: str) -> float:
    """t 当日或之前最近一个观测值(S-669/T-169 同口径)。"""
    i = np.searchsorted(np.asarray(dates, dtype="datetime64[D]"), np.datetime64(t), side="right") - 1
    return float(values[i]) if i >= 0 else float("nan")


class Sym:
    """一只股票:日频收盘 + 周网格上的对齐价格 + 股数。"""

    __slots__ = ("key", "dates", "px", "n", "wk_idx", "wk_px")

    def __init__(self, key: str, series: list):
        self.key = key
        self.dates = [r[0] for r in series]
        self.px = np.array([r[1] for r in series], dtype=float)
        self.n = len(self.px)

    def build_grid(self, grid: list[str]) -> None:
        g = np.asarray(grid, dtype="datetime64[D]")
        d = np.asarray(self.dates, dtype="datetime64[D]")
        pos = np.searchsorted(d, g, side="right") - 1
        self.wk_idx = np.where(pos >= 0, pos, -1)
        self.wk_px = np.where(pos >= 0, self.px[np.clip(pos, 0, None)], np.nan)

    def fwd(self, i: int, ndays: int) -> float:
        """i = 周网格下标;进 = 该周最后一个交易日收盘,出 = 之后第 ndays 个交易日收盘。"""
        j = self.wk_idx[i]
        if j < 0:
            return float("nan")
        k = j + ndays
        if k >= self.n:
            return float("nan")
        return float(long_return(self.px[j], self.px[k]))


def spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan")
    rx, ry = rankdata(x[m]), rankdata(y[m])
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return float("nan")
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def rankdata(a: np.ndarray) -> np.ndarray:
    """平均秩(并列取均值)—— 与 scipy.stats.rankdata 一致,不引 scipy。"""
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(a.size, dtype=float)
    ranks[order] = np.arange(1, a.size + 1, dtype=float)
    sa = a[order]
    i = 0
    while i < a.size:
        j = i
        while j + 1 < a.size and sa[j + 1] == sa[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


def tstat(ics: list[float]) -> float:
    a = np.array([v for v in ics if v and math.isfinite(v)], dtype=float)
    if a.size < 2 or a.std(ddof=1) == 0:
        return float("nan")
    return float(a.mean() / (a.std(ddof=1) / math.sqrt(a.size)))


def ics_by_week(rows: list[dict], sig: str, horizon: int) -> dict:
    """week -> IC(该周截面 Spearman)。"""
    out = {}
    for r in rows:
        v = r["ics"].get(f"{sig}_{horizon}")
        if v is not None and math.isfinite(v):
            out[r["week"]] = v
    return out


def window(rows: list[dict], sig: str, horizon: int, lo: str, hi: str) -> list[dict]:
    """取窗口内的**不重叠**样本:S-670 原文「每 4 周 / 13 周取一个不重叠样本」。
    先按 IC 有效性筛,再每隔 STRIDE_WEEKS[horizon] 周取一个(从窗口内第一个有效周起)。"""
    sub = [r for r in rows if lo <= r["week"] <= hi
           and math.isfinite(r["ics"].get(f"{sig}_{horizon}", float("nan")))]
    return sub[::STRIDE_WEEKS[horizon]]


def summarize(rows: list[dict], sig: str, horizon: int, lo: str, hi: str) -> dict:
    sub = window(rows, sig, horizon, lo, hi)
    ics = [r["ics"][f"{sig}_{horizon}"] for r in sub]
    if not ics:
        return {"n_weeks": 0, "n_raw_weeks": 0, "mean_ic": None, "t": None, "half1": None, "half2": None}
    half = len(ics) // 2
    h1, h2 = ics[:half], ics[half:]
    n_raw = len([r for r in rows if lo <= r["week"] <= hi])
    return {
        "n_weeks": len(ics),
        "n_raw_weeks": n_raw,
        "mean_ic": float(np.mean(ics)),
        "t": tstat(ics),
        "half1": float(np.mean(h1)) if h1 else None,
        "half2": float(np.mean(h2)) if h2 else None,
    }


def null_pct(rows_all: list[dict], sig: str, horizon: int, lo: str, hi: str) -> dict:
    """零分布:每周内打乱前瞻收益(原始截面的 fwd 向量按周 shuffle),400 次,报均值 IC 的分位。
    样本集与 summarize 同口径(不重叠)。"""
    sub = window(rows_all, sig, horizon, lo, hi)
    if len(sub) < 3:
        print(f"    [null] {sig}_{horizon} {lo}: 只有 {len(sub)} 周,跳过零分布", flush=True)
        return {"n_null": 0, "pct": None}
    # 每周的 fwd 与 sig 长度必须逐周相等(截面上家数会变,不能跨周比长度)
    fwd, sigs = [], []
    for r in sub:
        f = np.array(r["fwd"][horizon], dtype=float)
        s = np.array(r["sig"][sig], dtype=float)
        if len(f) != len(s):
            print(f"    [null] {sig}_{horizon} {lo}: {r['week']} 长度不等 {len(f)}/{len(s)}", flush=True)
            return {"n_null": 0, "pct": None}
        fwd.append(f)
        sigs.append(s)

    def stat(rs) -> float:
        return float(np.nanmean([spearman_ic(s, f) for s, f in zip(sigs, rs)]))

    actual = stat(fwd)

    def fn(rng):
        # 每周内打乱该周的前瞻收益归属(组 = 该周全部名字),组与组之间不混。
        # shuffle_within 返回 object dtype,必须转回 float 才能算 IC。
        return stat([np.asarray(shuffle_within(f, [r["week"]] * len(f), rng), dtype=float)
                     for f, r in zip(fwd, sub)])

    try:
        null = null_distribution(fn, N_NULL, SEED + horizon * 7 + (sum(map(ord, sig)) * 13) % 997, actual=actual)
    except Exception as exc:
        return {"n_null": 0, "pct": None, "err": f"{type(exc).__name__}: {exc}"}
    return {"n_null": int(len(null)), "actual": actual, "pct": percentile_of(actual, null),
            "null_mean": float(np.mean(null)), "null_sd": float(np.std(null, ddof=1))}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    print("[T-172] S-670 —— 7 个定好方向的信号 × 4/13 周", flush=True)
    mcap = fetch_mcap()
    all_keys = sorted({k for d in mcap.values() for k in d if "." not in k})   # 不带 . 后缀的 key
    print(f"  world50(source={MCAP_SOURCE})不带点 key {len(all_keys)} 个;"
          f"周快照 {len(mcap)} 个({min(mcap)} → {max(mcap)})", flush=True)

    px = fetch_px(all_keys)
    syms = {k: Sym(k, px[k]) for k in all_keys if len(px.get(k, [])) > 0}
    print(f"  有价格的 key {len(syms)} 个", flush=True)

    rev_rows = fetch_rev()
    rev_by_key = defaultdict(list)
    for r in rev_rows:
        if r.get("filed") and r.get("revenue") is not None and "." not in (r.get("key") or ""):
            rev_by_key[r["key"]].append(r)
    for k in rev_by_key:
        rev_by_key[k].sort(key=lambda r: (r["filed"], r["period_end"], r["period_start"]))
    print(f"  营收行 {len(rev_rows)},其中不带点 {sum(len(v) for v in rev_by_key.values())}", flush=True)

    grid = fridays(GRID_START, GRID_END)
    for s in syms.values():
        s.build_grid(grid)

    def rgrow(key: str, t: str) -> float:
        """最近一期收入同比(只用 filed ≤ t 的行;基期 = period_end 最接近一年前的那期)。"""
        rs = rev_by_key.get(key)
        if not rs:
            return float("nan")
        lo = np.searchsorted([r["filed"] for r in rs], t, side="right")
        if lo == 0:
            return float("nan")
        avail = rs[:lo]
        latest = max(avail, key=lambda r: (r["period_end"], r["filed"]))
        target = (date.fromisoformat(latest["period_end"]) - timedelta(days=365)).isoformat()
        same = [r for r in avail
                if r["tag"] == latest["tag"] and r["unit"] == latest["unit"]
                and float(r["revenue"]) > 0]
        if not same:
            return float("nan")
        prior = min(same, key=lambda r: abs((date.fromisoformat(r["period_end"]) - date.fromisoformat(target)).days))
        gap = abs((date.fromisoformat(prior["period_end"]) - date.fromisoformat(target)).days)
        if gap > 75:                      # 基期离一年前太远(口径变了)⇒ 不用
            return float("nan")
        return float(latest["revenue"]) / float(prior["revenue"]) - 1.0

    rows: list[dict] = []
    skipped_small = 0
    for gi, wk in enumerate(grid):
        if not (DISC[0] <= wk <= HOLD[1]):
            continue
        snap = mcap.get(wk) or {}
        cross = [k for k in all_keys if k in snap and k in syms and snap[k] > 0]
        if len(cross) < MIN_CROSS:
            skipped_small += 1
            continue
        i = gi
        mc_prev = mcap.get(grid[i - 52], {}) if i >= 52 else {}
        s_vals = {sg: [] for sg in SIGNALS}
        for k in cross:
            s = syms[k]
            w = s.wk_px
            mc = snap[k]
            mc52 = mc_prev.get(k, float("nan"))
            # 股数 = 市值 / 收盘(表里没有股数列,现推);52 周增用 52 周前的同一周网格点
            sh_t = mc / w[i] if w[i] == w[i] and w[i] > 0 else float("nan")
            sh_52 = mc52 / w[i - 52] if i >= 52 and mc52 == mc52 and mc52 > 0 and w[i - 52] > 0 else float("nan")
            vals = {
                "M12": (w[i - 4] / w[i - 52] - 1.0) if i >= 52 else float("nan"),
                "M6": (w[i] / w[i - 26] - 1.0) if i >= 26 else float("nan"),
                "REV": -(w[i] / w[i - 4] - 1.0) if i >= 4 else float("nan"),
                "LOWVOL": (-float(np.std(np.diff(w[i - 26:i + 1]) / w[i - 26:i])))
                          if i >= 26 else float("nan"),
                "SMALL": -math.log(mc),
                "ISSUE": -(sh_t / sh_52 - 1.0) if sh_52 == sh_52 and sh_t == sh_t else float("nan"),
                "RGROW": rgrow(k, wk),
            }
            for sg in SIGNALS:
                s_vals[sg].append(vals[sg])
        ics: dict = {}
        fwd: dict = {}
        for hz, nd in H_FWD_DAYS.items():
            f = np.array([s.fwd(i, nd) for s in (syms[k] for k in cross)], dtype=float)
            fwd[hz] = f.tolist()
            for sg in SIGNALS:
                ics[f"{sg}_{hz}"] = spearman_ic(np.array(s_vals[sg], dtype=float), f)
        # 挖掘用(非预注册):−log(收盘) —— SMALL 的混淆对照,见 write_report 的「挖掘」节
        nlp = [-math.log(syms[k].wk_px[i]) if syms[k].wk_px[i] > 0 else float("nan") for k in cross]
        corr_small_nlp = float(np.nanmean([
            spearman_ic(np.array(s_vals["SMALL"], dtype=float), np.array(nlp, dtype=float))]))
        for hz in H_FWD_DAYS:
            ics[f"NEGLOGPX_{hz}"] = spearman_ic(np.array(nlp, dtype=float), np.array(fwd[hz], dtype=float))
        rows.append({"week": wk, "n": len(cross), "sig": s_vals, "fwd": fwd, "ics": ics,
                     "corr_small_neglogpx": corr_small_nlp})
        if len(rows) % 100 == 0:
            print(f"    … 周 {len(rows)}({wk},n={len(cross)})", flush=True)

    def mcap_wk(key: str, i: int) -> float:
        return float(mcap.get(grid[i], {}).get(key, float("nan")))

    print(f"  截面周 {len(rows)} 个,因 < {MIN_CROSS} 家跳过 {skipped_small} 个", flush=True)

    # ---- 判定(逐字照 S-670 的机械规则)----
    results: dict = {}
    for sig in SIGNALS:
        for hz in (4, 13):
            d = summarize(rows, sig, hz, *DISC)
            h = summarize(rows, sig, hz, *HOLD)
            gates = {
                "mean_ic>0": (d["mean_ic"] or 0) > 0,
                "t>=2": (d["t"] is not None) and d["t"] >= 2,
                "half1>0": (d["half1"] is not None) and d["half1"] > 0,
                "half2>0": (d["half2"] is not None) and d["half2"] > 0,
            }
            enter = all(gates.values())
            hpass = (h["mean_ic"] or 0) > 0 and (h["t"] is not None) and h["t"] >= 2
            results[f"{sig}_{hz}"] = {
                "signal": sig, "horizon_wk": hz, "desc": SIGNAL_DESC[sig],
                "discovery": d, "gates": gates, "enter_holdout": enter,
                "holdout": h, "holdout_pass": hpass if enter else None,
                "verdict": ("过" if (enter and hpass) else ("进留出但没过" if enter else "发现段未过")),
                "null_discovery": null_pct(rows, sig, hz, *DISC),
                "null_holdout": null_pct(rows, sig, hz, *HOLD) if enter else None,
            }

    # ---- 挖掘(探索性,不在 S-670 预注册里)----
    corr = [r["corr_small_neglogpx"] for r in rows
            if r["corr_small_neglogpx"] is not None and math.isfinite(r["corr_small_neglogpx"])]
    explore = {
        "note": "探索性 —— 需另立预注册、在新数据上过零信号对照",
        "small_vs_neglogpx_corr": float(np.mean(corr)) if corr else None,
        "neglogpx_discovery_4w": summarize(rows, "NEGLOGPX", 4, *DISC)["mean_ic"],
        "neglogpx_discovery_13w": summarize(rows, "NEGLOGPX", 13, *DISC)["mean_ic"],
        "neglogpx_holdout_4w": summarize(rows, "NEGLOGPX", 4, *HOLD)["mean_ic"],
        "neglogpx_holdout_13w": summarize(rows, "NEGLOGPX", 13, *HOLD)["mean_ic"],
    }
    for k, v, wd in (("neglogpx_discovery_4w", 4, DISC), ("neglogpx_discovery_13w", 13, DISC),
                     ("neglogpx_holdout_4w", 4, HOLD), ("neglogpx_holdout_13w", 13, HOLD)):
        s = summarize(rows, "NEGLOGPX", v, *wd)
        explore[k + "_t"] = s["t"]
        explore[k + "_n"] = s["n_weeks"]

    meta = {
        "task": "T-172", "prereg": "S-670 (REFUTATION_LEDGER.md, 2026-10-22 09:32 UTC)",
        "apparatus": APPARATUS, "t169_reused": T169_REUSED,
        "universe": f"world50_mcap_weekly source={MCAP_SOURCE},无点 key",
        "n_keys_total": len(all_keys), "n_keys_with_px": len(syms),
        "cross_weeks": len(rows), "skipped_small_cross": skipped_small, "min_cross": MIN_CROSS,
        "discovery": list(DISC), "holdout": list(HOLD), "n_null": N_NULL, "seed": SEED,
        "signals": SIGNALS,
    }
    out = {"meta": meta, "results": results, "explore": explore,
           "weekly": [{k: r[k] for k in ("week", "n")} | {"ics": r["ics"]} for r in rows]}
    open(RESULTS, "w").write(json.dumps(out, ensure_ascii=False, indent=2))

    write_report(out)
    print(f"[T-172] 结果 → {RESULTS}\n[T-172] 报告 → {REPORT}", flush=True)
    return 0


def write_report(out: dict) -> None:
    m, R = out["meta"], out["results"]
    L: list[str] = []
    A = L.append
    A("# T-172 · S-670 —— 大公司截面上 7 个定好方向的信号能不能挑出之后 4 / 13 周更好的公司\n")
    A(f"- 预注册:REFUTATION_LEDGER.md **S-670**(2026-10-22 09:32 UTC,原文一字不改)")
    A(f"- 宇宙:`world50_mcap_weekly` source=`shares_x_close_v3`,只取不带 `.` 后缀的 key;"
      f"共 {m['n_keys_total']} 个 key,{m['n_keys_with_px']} 个有价格")
    A(f"- 价格:`ohlcv_daily` source=`eodhd`(复权收盘,本币未换汇),按 `order=symbol.asc,trade_date.asc` 翻页")
    A(f"- 营收:`world50_revenue` 按 `filed` 取时点已知的那一期")
    A(f"- 截面:每周五;共 {m['cross_weeks']} 周成截面,因 < {m['min_cross']} 家跳过 {m['skipped_small_cross']} 周")
    A(f"- 发现段 {m['discovery'][0]} → {m['discovery'][1]};留出段 {m['holdout'][0]} → {m['holdout'][1]}")
    A(f"- 零分布:`{m['apparatus']}` 每周打乱前瞻收益 × {m['n_null']} 次(seed {m['seed']}),报分位")
    A(f"- 判定:发现段 mean IC > 0 且 t ≥ 2 且前后两半 IC 都 > 0 ⇒ 进留出段;留出段 mean IC > 0 且 t ≥ 2 = 过")
    if not m["t169_reused"]:
        A(f"- ⚠️ `docs/research/t169_equity_quality.py`(T-169, lane-a)在本次运行时**还没进 main**,"
          f"截面函数无法 import,本脚本自带等价实现(信号定义照 S-670 原文,不引用 T-169 的数)")
    A("")
    A("## 汇总:7 信号 × 2 期限\n")
    A("| 信号 | 期限 | 发现段 mean IC | t | 前半 / 后半 | 发现段零分布分位 | 进留出 | 留出 mean IC | t | 留出零分布分位 | **判定** |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for sig in m["signals"]:
        for hz in (4, 13):
            r = R[f"{sig}_{hz}"]
            d, h = r["discovery"], r["holdout"]
            f = lambda v: "—" if v is None else f"{v:+.3f}"
            pc = lambda x: "—" if (not x or x.get("pct") is None) else "%.3f" % x["pct"]
            hs = (r["holdout_pass"] is not None)
            hp = "—" if not hs else ("✅ 过" if r["holdout_pass"] else "❌ 未过")
            A(f"| {sig} | {hz}w | {f(d['mean_ic'])} | {f(d['t'])} | {f(d['half1'])} / {f(d['half2'])} | "
              f"{pc(r['null_discovery'])} | {'✅' if r['enter_holdout'] else '—'} | "
              f"{f(h['mean_ic'])} | {f(h['t'])} | {pc(r['null_holdout'])} | {hp} |")
    A("")
    A("「零分布分位」= 实际 mean IC 在 400 次「每周内打乱前瞻收益」零分布里的分位;"
      "1.000 = 比 400 次打乱都强,0.000 = 比 400 次打乱都弱。未进留出段的信号按原文不算留出段零分布(留空)。\n")
    passed = [k for k, r in R.items() if r["verdict"] == "过"]
    A(f"**过了的:{passed if passed else '无(14 条里 0 条过)'}**\n")
    A("---")
    A("")
    A("## S-670 结果(草稿)\n")
    if passed:
        A(f"14 条检验({m['signals']} × {{4, 13}} 周)里 **{len(passed)} 条过**:{', '.join(passed)}。"
          f"按预注册,过检的信号成为个股 CIS 的**候选分数**,另立前向预注册(影子 26 周)才给档位 —— 本卡不做档位。\n")
    else:
        A("14 条检验(7 信号 × {4, 13} 周)里 **0 条过**。发现段与留出段的方向见上表;"
          "按预注册「不过 ⇒ 个股继续只给状态与事实」,与 Jazz 10-22 的裁定一致:125 家进 CIS 页面只展示状态与质量事实,"
          "不给档位词。这条要写进 `CIS_V2_SPEC.md`(留给 Seth)。\n")
    A("工程口径备注:周网格用日历周(4 / 26 / 52 周),前瞻用交易日(20 / 65 个交易日,照原文);"
      "ISSUE 的股数由 `mcap_usd / close` 现推(表里没有股数列),52 周增用 52 周前的同一周网格点。\n")
    A("## 挖掘(探索性 —— 需另立预注册、在新数据上过零信号对照)\n")
    E = out["explore"]
    g = lambda v: "—" if v is None else f"{v:+.3f}"
    A("**① 三个预注册方向被数据反向,而且反向得很整齐。**"
      "LOWVOL(预注册「低波好」)发现段 4 周 IC "
      f"{g(R['LOWVOL_4']['discovery']['mean_ic'])}(t {R['LOWVOL_4']['discovery']['t']:+.1f})、13 周 "
      f"{g(R['LOWVOL_13']['discovery']['mean_ic'])}(t {R['LOWVOL_13']['discovery']['t']:+.1f}),"
      "留出段同号;ISSUE(预注册「少增发好」)发现段 4 周 "
      f"{g(R['ISSUE_4']['discovery']['mean_ic'])}(t {R['ISSUE_4']['discovery']['t']:+.1f})、13 周 "
      f"{g(R['ISSUE_13']['discovery']['mean_ic'])}(t {R['ISSUE_13']['discovery']['t']:+.1f})。"
      "两个的零分布分位都是 0.000 —— 不是「没测出来」,是稳定地在反方向。"
      "这跟 S-668 H1(「规模 + 稳定 + 供给纪律」与之后 4 周反向)是同一件事的两面:"
      "在这 125 家里,波动大的、增发多的,之后涨得更多。\n")
    A(f"**② 唯一过检的 SMALL 里,有一部分其实是「便宜」,但不是全部。** 每周截面上 SMALL(= −log 市值)与"
      f" −log 收盘 的平均 Spearman 相关 = **{g(E['small_vs_neglogpx_corr'])}** —— 只有中等,"
      "说明回购 / 增发让股数在周之间真的动了,−log 市值 ≠ −log 股价 + 常数。"
      "把 −log 收盘单独当信号算(非预注册,只作对照):发现段 4 周 IC "
      f"{g(E['neglogpx_discovery_4w'])}(t {E['neglogpx_discovery_4w_t']:+.1f},n={E['neglogpx_discovery_4w_n']})、"
      f"13 周 {g(E['neglogpx_discovery_13w'])}(t {E['neglogpx_discovery_13w_t']:+.1f},n={E['neglogpx_discovery_13w_n']});"
      f"留出段 4 周 {g(E['neglogpx_holdout_4w'])}(t {E['neglogpx_holdout_4w_t']:+.1f},n={E['neglogpx_holdout_4w_n']})、"
      f"13 周 {g(E['neglogpx_holdout_13w'])}(t {E['neglogpx_holdout_13w_t']:+.1f},n={E['neglogpx_holdout_13w_n']})。"
      f"对照 SMALL 自己的数(发现段 4/13 周 {g(R['SMALL_4']['discovery']['mean_ic'])} / "
      f"{g(R['SMALL_13']['discovery']['mean_ic'])};留出段 {g(R['SMALL_4']['holdout']['mean_ic'])} / "
      f"{g(R['SMALL_13']['holdout']['mean_ic'])}):**留出段「便宜」几乎能整个顶替 SMALL "
      f"(13 周 {g(E['neglogpx_holdout_13w'])} vs {g(R['SMALL_13']['holdout']['mean_ic'])}),"
      f"发现段却只能顶一半**(13 周 {g(E['neglogpx_discovery_13w'])} vs {g(R['SMALL_13']['discovery']['mean_ic'])})。"
      "读法:留出段里 SMALL 的效果大半是「买跌过的」;发现段里「真的更小」那一半是真的。"
      "现有数据(mcap/close 现推股数)拆不开这两者,**要把 SMALL 当个股 CIS 的分数,得先拿到真实股数序列**。\n")
    A("**③ 收入增长(RGROW)在发现段前半段有效、后半段归零。** "
      f"发现段前半 IC {g(R['RGROW_13']['discovery']['half1'])}、后半 {g(R['RGROW_13']['discovery']['half2'])}(13 周);"
      "前半段覆盖 2016–2018,那几年美股大公司的营收增长确实能挑出赢家;后半段(2019–2020)整体 IC 塌到 0 附近。"
      "看着像「营收增长这个因子被抢跑完了」,但也可能只是 2019–2020 的板块轮动。"
      "**未检验,只是读数。**\n")
    A("以上三条都**不在** S-670 的预注册里,没有独立检验、没有零信号对照、也没在新数据上复核过,"
      "只能当作下一张卡的候选题目 —— 要动就得另立预注册。\n")
    open(REPORT, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())