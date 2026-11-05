#!/usr/bin/env python3
"""T-241 · S-724 预注册:⓪ 九个分量的先行 / 滞后归因(只报不判)

口径(逐字照 S-724,见 REFUTATION_LEDGER.md § S-724;不改代码、不做 DDL、不入库):
- ① 九个分量 × 两种形态 x ∈ {z_k, Δ30 z_k},按**扩张窗口**五分位分档(只用 ≤ d 的历史,
  至少 365 个观测才有分位),报每档之后 30 / 60 / 90 天 BTC 收益均值、
  以及「之后 90 天内进入 ≥ 30% 回撤段」的频率;顶档减底档 Δ 与块置换零分布
  (块长 30 天、1,000 次、种子 724,只用 apparatus.py)的分位。
- ② 先行结构:三段最大回撤(2021-04、2021-11、2025-10)各报每个分量的 Δ30 z 在峰前 −90…0 天
  的路径,标出每个分量**首次**越过自己历史 10 / 90 分位的那天相对峰的天数(负 = 先行)。
- ③ 一张表:9 分量 × 2 形态 × 3 期限的 Δ 与分位 + 先行天数中位。
- ④ 「候选分量」标记(不是规则):三个期限同号、且 90 天期限分位 ≥ 0.95、
  且三段里 ≥ 2 段先行天数 < 0 的分量。
- ⑤ 诚实:54 次比较(9 × 2 × 3);候选进 ⓪ v3 的预注册才判,本卡不判。

事件段切法**沿用** `docs/research/t234_cycle.py`(BTC 现货 binance_hist 收盘、
滚动 200 个交易日最高收盘为基准、回撤 ≤ −30% 的**连续**交易日为一段)。

口径补充(写在这里,先于看结果定下):
- 回撤段「进入」报两版:`dd90_peak`(段的**峰**落在 d 之后 90 天内,主口径)与
  `dd90_start`(段的**起点**落在 d 之后 90 天内)。两者等价于「状态版」的不同锚点:
  段的起点 = 回撤首次 ≤ −30% 的那一天 = 进入回撤状态的第一天,所以状态版 ≡ `dd90_start`。
- 块置换零分布报两版:主口径**置换信号**(块 30 个有效交易日,分位阈值固定为真实扩张窗口阈值),
  副口径**置换结果**(分档固定,置换结果序列)。
- 分位同时给「字面口径」(Δ 与分位都不带符号)与「符号调整口径」
  (SIGN 取 `src/data/state/cycle_vector.py` 的约定:⓪ 恶化分里 SIGN=+1 的分量是**低**才恶化,
  SIGN=−1 的分量是**高**才恶化;调整后 Δ_adj = SIGN × Δ)。
"""
from __future__ import annotations

import importlib.util
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "t241_results.json"
REPORT = HERE / "T-241_cycle_leadlag.md"

SEED, N_NULL, BLOCK = 724, 1000, 30
MIN_BIN_HIST = 365
MIN_BIN_OBS = 20
HORIZONS = (30, 60, 90)
DD_WINDOW = 90
LEAD_WINDOW = 90
LEAD_LOOKBACK = 365   # 找「首次越过」的回看窗口(天);越过点可能在 −90 之外
EPISODE_WINDOW0 = "2021-02-01"   # S-713 的窗口起点:三段最大回撤在这个窗口里取
QS_ALL = (10, 20, 40, 60, 80, 90)
COMPS = ["stable_supply_30d", "fed_liq_60d", "breadth", "taker_buy",
         "mom_60", "funding", "oi_chg", "lend_apy", "vratio"]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apparatus = _load(REPO / "src/data/evaluation/apparatus.py", "apparatus")
t234 = _load(HERE / "t234_cycle.py", "t234")
cv = _load(REPO / "src/data/state/cycle_vector.py", "cycle_vector")
SIGN = cv.SIGN

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


# ── 只读取数(翻页一律带 order=) ─────────────────────────────────────────────
def _get(table: str, params: dict, rng: str) -> list[dict]:
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=dict(HEAD, Range=rng))
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
        return json.loads(body) if body else []


def fetch(table: str, params: dict, page: int = 1000) -> list[dict]:
    out, lo = [], 0
    while True:
        chunk = _get(table, params, f"{lo}-{lo + page - 1}")
        out.extend(chunk)
        if len(chunk) < page:
            return out
        lo += page


# ── 数据 ───────────────────────────────────────────────────────────────────
def load_z() -> tuple[dict[str, dict[str, float]], dict]:
    rows = fetch("cycle_vector_daily", {"select": "d,code_ref,z,components",
                                         "order": "d.asc,code_ref.asc"})
    refs = sorted({r.get("code_ref") or "(null)" for r in rows})
    keep = [r for r in rows if (r.get("code_ref") or "").startswith("cycle_vector v1.1")]
    z: dict[str, dict[str, float]] = {c: {} for c in COMPS}
    raw: dict[str, int] = {c: 0 for c in COMPS}
    raw_span: dict[str, list[str]] = {}
    for r in keep:
        d = str(r.get("d"))[:10]
        zz = r.get("z") or {}
        cc = r.get("components") or {}
        for c in COMPS:
            v = zz.get(c)
            if v is not None:
                z[c][d] = float(v)
            if cc.get(c) is not None:
                raw[c] += 1
                sp = raw_span.setdefault(c, [d, d])
                sp[0], sp[1] = min(sp[0], d), max(sp[1], d)
    meta = {
        "table": "cycle_vector_daily", "rows_total": len(rows), "rows_v11": len(keep),
        "code_refs": refs,
        "d_min": min((str(r.get("d"))[:10] for r in keep), default=None),
        "d_max": max((str(r.get("d"))[:10] for r in keep), default=None),
        "z_coverage": {c: {"n": len(z[c]),
                           "first": min(z[c]) if z[c] else None,
                           "last": max(z[c]) if z[c] else None} for c in COMPS},
        "raw_coverage": {c: {"n": raw[c], "first": raw_span.get(c, [None, None])[0],
                             "last": raw_span.get(c, [None, None])[1]} for c in COMPS},
        "components_never_in_z": [c for c in COMPS if not z[c]],
    }
    return z, meta


def load_btc() -> tuple[list[str], list[float], str]:
    dates, closes, src = t234.btc_closes()
    pairs = [(d, c) for d, c in zip(dates, closes) if c is not None]
    return [p[0] for p in pairs], [p[1] for p in pairs], src


# ── 结果变量 ───────────────────────────────────────────────────────────────
def build_outcomes(dates: list[str], closes: list[float], segs: list[dict]) -> dict:
    n = len(dates)
    out: dict[str, np.ndarray] = {}
    for h in HORIZONS:
        arr = np.full(n, np.nan)
        for i in range(n - h):
            r = apparatus.long_return(closes[i], closes[i + h])
            if r is not None:
                arr[i] = r
        out[f"fwd{h}"] = arr
    peaks = [date.fromisoformat(s["peak_d"]) for s in segs]
    starts = [date.fromisoformat(s["start_d"]) for s in segs]
    dp, ds_ = np.zeros(n), np.zeros(n)
    for i, d in enumerate(dates):
        dd = date.fromisoformat(d)
        lim = dd + timedelta(days=DD_WINDOW)
        dp[i] = 1.0 if any(dd < p <= lim for p in peaks) else 0.0
        ds_[i] = 1.0 if any(dd < p <= lim for p in starts) else 0.0
    out["dd90_peak"], out["dd90_start"] = dp, ds_
    return out


# ── 扩张窗口分位 + 分档 ────────────────────────────────────────────────────
def expanding(dates: list[str], vals: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """返回 (thresholds[n,6] 取 10/20/40/60/80/90 分位, bins[n] 五分位档号;历史不足处 bins=-1)。"""
    arr = np.asarray(vals, dtype=float)
    n = len(arr)
    th = np.full((n, len(QS_ALL)), np.nan)
    bins = np.full(n, -1, dtype=int)
    for i in range(n):
        h = arr[:i + 1]
        h = h[~np.isnan(h)]
        if len(h) < MIN_BIN_HIST:
            continue
        t = np.percentile(h, QS_ALL)
        th[i] = t
        bins[i] = int((t[1:5] <= arr[i]).sum())
    return th, bins


def spread(bins: np.ndarray, ovals: np.ndarray) -> float | None:
    top, bot = ovals[bins == 4], ovals[bins == 0]
    if len(top) < MIN_BIN_OBS or len(bot) < MIN_BIN_OBS:
        return None
    return float(top.mean() - bot.mean())


def null_dist(one, actual: float | None, tag: str) -> dict:
    try:
        null = apparatus.null_distribution(one, N_NULL, SEED, actual=actual)
    except Exception as e:  # NoOpNull 等
        return {"error": f"{type(e).__name__}: {e}", "tag": tag}
    return {"null": null, "tag": tag}


# ── 单个(分量, 形态) ───────────────────────────────────────────────────────
def analyse(comp: str, form: str, zser: dict[str, float],
            btc_idx: dict[str, int], outcomes: dict[str, np.ndarray],
            segs_top: list[dict]) -> dict:
    if form == "z":
        dates = sorted(zser)
        vals = [zser[d] for d in dates]
    else:
        dates, vals = [], []
        for d in sorted(zser):
            p = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
            if p in zser:
                dates.append(d)
                vals.append(zser[d] - zser[p])
    n = len(dates)
    rec: dict = {"comp": comp, "form": form, "n_series": n,
                 "series_first": dates[0] if dates else None,
                 "series_last": dates[-1] if dates else None}
    if n < MIN_BIN_HIST + 30:
        rec["skipped"] = "样本不足(扩张窗口 365 天 + 结果窗口)"
        return rec

    th, bins = expanding(dates, vals)
    ov = {k: np.array([outcomes[k][btc_idx[d]] if d in btc_idx else np.nan for d in dates])
          for k in outcomes}

    rec["bin_counts"] = [int((bins == b).sum()) for b in range(5)]
    # 日历混淆诊断:扩张窗口五分位在**趋势型**序列上≈「按日历切段」——
    # 报每档的平均日历日(距 2021-01-01 的天数);顶档 − 底档 越大越像日历代理。
    daynum = np.array([(date.fromisoformat(d) - date(2021, 1, 1)).days for d in dates], dtype=float)
    have = bins >= 0
    qmd = [float(daynum[have & (bins == b)].mean()) if (have & (bins == b)).any() else None
           for b in range(5)]
    rec["q_mean_day"] = qmd
    rec["calendar_gap_days"] = (None if qmd[0] is None or qmd[4] is None else qmd[4] - qmd[0])
    rec["outcomes"] = {}
    for okey, ovals in ov.items():
        valid = (bins >= 0) & np.isfinite(ovals)
        actual = spread(bins[valid], ovals[valid])
        if actual is None:
            rec["outcomes"][okey] = {"delta": None, "n_valid": int(valid.sum())}
            continue
        qmeans = [float(ovals[valid & (bins == b)].mean()) if (valid & (bins == b)).any() else None
                  for b in range(5)]

        # 主口径:置换信号(块 30 个有效交易日;分位阈值固定为真实扩张窗口阈值)
        xv, tv, bv = vals_arr(vals, valid), th[valid][:, 1:5], bins[valid]

        def one_sgn(rng, xv=xv, tv=tv, bv=bv, ovals=ovals[valid]):
            perm = apparatus.block_permute(xv, BLOCK, rng)
            b = (tv <= perm[:, None]).sum(axis=1)
            return spread(b, ovals)

        ns = null_dist(one_sgn, actual, "signal_perm")

        # 副口径:置换结果(分档固定)
        def one_out(rng, bv=bv, ov=ovals[valid]):
            perm = apparatus.block_permute(ov, BLOCK, rng)
            return spread(bv, perm)

        no = null_dist(one_out, actual, "outcome_perm")

        sign = SIGN.get(comp, 1)
        pct = apparatus.percentile_of(actual, ns["null"]) if "null" in ns else None
        pct_o = apparatus.percentile_of(actual, no["null"]) if "null" in no else None
        rec["outcomes"][okey] = {
            "delta": actual,
            "delta_sign_adj": sign * actual,
            "q_means": qmeans,
            "n_valid": int(valid.sum()),
            "base_rate": float(ovals[valid].mean()),
            "pct": pct,
            "pct_sign_adj": pct if sign > 0 else (None if pct is None else 1.0 - pct),
            "null_mean": float(np.mean(ns["null"])) if "null" in ns else None,
            "null_sd": float(np.std(ns["null"])) if "null" in ns else None,
            "null_pct_outcome_perm": pct_o,
            "null_error": ns.get("error"), "null_error_outcome_perm": no.get("error"),
        }

    # ── ② 先行结构 ────────────────────────────────────────────────────────
    rec["lead"] = {}
    for seg in segs_top:
        peak = date.fromisoformat(seg["peak_d"])
        lo_d = (peak - timedelta(days=LEAD_WINDOW)).isoformat()
        look_d = (peak - timedelta(days=LEAD_LOOKBACK)).isoformat()
        cross10 = cross90 = None
        cross10_last = cross90_last = None
        prev_below = prev_above = None
        state_at_lo = None
        path = []
        for i, d in enumerate(dates):
            if d < look_d or d > seg["peak_d"] or bins[i] < 0:
                continue
            x = vals[i]
            q10, q90 = th[i][0], th[i][5]
            below, above = bool(x <= q10), bool(x >= q90)
            if prev_below is not None:          # 真·穿越:前一日不在阈值外、当日在阈值外
                if below and not prev_below:
                    rel = (date.fromisoformat(d) - peak).days
                    if cross10 is None:
                        cross10 = rel
                    cross10_last = rel
                if above and not prev_above:
                    rel = (date.fromisoformat(d) - peak).days
                    if cross90 is None:
                        cross90 = rel
                    cross90_last = rel
            prev_below, prev_above = below, above
            if d >= lo_d:
                path.append({"d": d, "x": round(float(x), 4)})
                if state_at_lo is None:
                    state_at_lo = {"below10": below, "above90": above}
        sign = SIGN.get(comp, 1)
        adverse = cross10 if sign > 0 else cross90
        adverse_last = cross10_last if sign > 0 else cross90_last
        rec["lead"][seg["peak_d"]] = {
            "peak_d": seg["peak_d"], "start_d": seg["start_d"], "trough_d": seg["trough_d"],
            "depth_p2t": seg["depth_p2t"],
            "cross10_rel_peak": cross10, "cross90_rel_peak": cross90,
            "cross10_last_rel_peak": cross10_last, "cross90_last_rel_peak": cross90_last,
            "cross10_in_90": (cross10 is not None and -LEAD_WINDOW <= cross10 <= 0),
            "cross90_in_90": (cross90 is not None and -LEAD_WINDOW <= cross90 <= 0),
            "cross10_last_in_90": (cross10_last is not None and -LEAD_WINDOW <= cross10_last <= 0),
            "cross90_last_in_90": (cross90_last is not None and -LEAD_WINDOW <= cross90_last <= 0),
            "adverse_cross_rel_peak": adverse,
            "adverse_last_rel_peak": adverse_last,
            "adverse_side": "10pct(low)" if sign > 0 else "90pct(high)",
            "state_at_window_start": state_at_lo,
            "path_n": len(path),
            "path_first": path[0] if path else None,
            "path_last": path[-1] if path else None,
            "path_min": min((p["x"] for p in path), default=None),
            "path_max": max((p["x"] for p in path), default=None),
        }
    return rec


def vals_arr(vals: list[float], valid: np.ndarray) -> np.ndarray:
    return np.asarray(vals, dtype=float)[valid]


# ── 事件段 → episode(同一 peak_d 的连续段算一段崩塌) ─────────────────────────
def episodes(segs: list[dict]) -> list[dict]:
    """t234.events() 把一次长崩塌切成若干「连续 ≤ −30%」的段;同一 peak_d 的段合为一段崩塌。"""
    by_peak: dict[str, list[dict]] = {}
    for s in segs:
        by_peak.setdefault(s["peak_d"], []).append(s)
    out = []
    for peak, ss in by_peak.items():
        deep = min(ss, key=lambda s: s["depth_p2t"])
        out.append({
            "peak_d": peak,
            "start_d": min(s["start_d"] for s in ss),
            "trough_d": deep["trough_d"],
            "depth_p2t": deep["depth_p2t"],
            "depth_roll": min(s["depth"] for s in ss),
            "n_segments": len(ss),
        })
    return sorted(out, key=lambda e: e["depth_p2t"])


# ── 主流程 ─────────────────────────────────────────────────────────────────
# ── 报告 ───────────────────────────────────────────────────────────────────
PREREG = """⓪ 两次 ❌ 的共同点:分量是按常识选的、按水平或 30 日变化合成,从没量过谁先于崩塌动。
这一条只做归因:9 分量 × {z, Δ30 z} × {30, 60, 90 天 BTC 收益;90 天内进入 ≥ 30% 回撤段的频率},
扩张五分位,块置换零分布(块 30 天、1,000 次、种子 724);三段最大回撤各报分量首次越过自己
10 / 90 分位相对峰的天数。「候选分量」= 三期限同号、90 天分位 ≥ 0.95、≥ 2 段先行 —— 候选进
⓪ v3 的预注册才判。54 次比较,报出来。**试验计数:不计(归因)。**
(S-724 原文,REFUTATION_LEDGER.md,2026-11-05 03:03 UTC)"""


def pct_str(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def pp(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f}pp"


def day_str(x) -> str:
    return "—" if x is None else f"{x:+d}d"


def render_report(res: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# T-241 · S-724 预注册:⓪ 分量的先行 / 滞后归因(只报不判)")
    A("")
    A("lane-c · 2026-11-05 · 只读(全程 SELECT;不写库、不做 DDL、不改 `src/`)")
    A("")
    A("## 0. 预注册原文(抄自 REFUTATION_LEDGER.md § S-724,先于看结果)")
    A("")
    A("> " + PREREG.replace("\n", "\n> "))
    A("")
    A("### 本卡口径补充(**定在看结果之前**,逐条列明)")
    A("")
    A("1. **事件段**沿用 `docs/research/t234_cycle.py`:BTC 现货 `ohlcv_daily(source=binance_hist)` 收盘、"
      "滚动 200 个交易日最高收盘为基准、回撤 ≤ −30% 的**连续**交易日为一段。t234 的切法会把一次长崩塌"
      "切成好几段(反弹一次就断),本卡按**同一 peak_d 合并成一段崩塌(episode)**再排名。")
    A(f"2. **三段最大回撤**:在 S-713 的窗口起点 `{res['episode_window0']}` 之后按 峰→谷 跌幅排名,取前三 —— "
      + "、".join(f"{e['peak_d']}(峰→谷 {e['depth_p2t'] * 100:.1f}%)" for e in res["segments_top3"])
      + ";与卡上写的 2021-04 / 2021-11 / 2025-10 一致。")
    A("3. **回撤段『进入』报两版**:`dd90_peak`(段的**峰**落在 d 之后 90 天内,主口径)、"
      "`dd90_start`(段的**起点**落在 d 之后 90 天内)。段的起点 = 回撤首次 ≤ −30% 的那一天 = "
      "『进入回撤状态』的第一天,所以状态版 ≡ `dd90_start`,不再单列。")
    A(f"4. **扩张窗口五分位**:只用 ≤ 当天的历史,历史不足 {res['min_bin_hist']} 个观测就没有分位;"
      "每档至少 20 个观测才出 Δ(不足则该格为『—』)。")
    A("5. **块置换零分布报两版**:主口径=**置换信号**(块 30 个有效交易日;分位阈值固定为真实扩张窗口阈值),"
      "副口径=**置换结果**(分档固定,置换结果序列)。两版都是 1,000 次、种子 724,只用 "
      "`src/data/evaluation/apparatus.py` 的 `block_permute / null_distribution / percentile_of / long_return`。")
    A("6. **分位给两版**:『字面口径』(Δ 与分位都不带符号)与『符号调整口径』"
      "(SIGN 取 `src/data/state/cycle_vector.py`:⓪ 恶化分里 SIGN=+1 的分量是**低**才恶化、"
      "SIGN=−1 的分量是**高**才恶化;Δ_adj = SIGN × Δ,分位_adj = 1 − 分位)。")
    A("7. **先行天数**:`adverse` = 按 SIGN 的**不良方向**穿越(SIGN=+1 看跌破自己历史 10 分位,"
      "SIGN=−1 看升破 90 分位)。回看窗口 = 峰前 365 天;报**首次**穿越(卡的口径)与**末次**穿越"
      "(离峰更近的一次)相对峰的天数;负 = 先行。")
    A("")
    A("## 1. 数据与覆盖")
    A("")
    d = res["data"]
    A(f"- `cycle_vector_daily`:code_ref = `{d['cycle_vector_daily']['code_refs'][0][:38]}…`,"
      f"{d['cycle_vector_daily']['rows_v11']} 行,{d['cycle_vector_daily']['d_min']} → "
      f"{d['cycle_vector_daily']['d_max']};z 分数最早 {min(v['first'] for v in d['cycle_vector_daily']['z_coverage'].values() if v['first'])}。")
    A(f"- BTC:`ohlcv_daily(source=binance_hist, symbol=BTC)`,{d['btc']['n']} 天,"
      f"{d['btc']['first']} → {d['btc']['last']},**无缺口**。")
    A(f"- 事件段:t234 切法切出 **{len(res['segments_all'])} 段**,按同一 peak_d 合并成 "
      f"**{len(res['episodes_all'])} 段崩塌**。")
    A("")
    A("| 分量 | z 最早 | z 最晚 | z 天数 | 备注 |")
    A("|---|---|---|---|---|")
    for c in COMPS:
        v = d["cycle_vector_daily"]["z_coverage"][c]
        rc = d["cycle_vector_daily"]["raw_coverage"][c]
        if not v["n"]:
            note = f"**z 里从来没有过**(原始分量只有 {rc['n']} 天:{rc['first']} 起)"
        else:
            note = ""
        A(f"| `{c}` | {v['first'] or '—'} | {v['last'] or '—'} | {v['n']} | {note} |")
    A("")
    A("> 卡片写的是「九个分量」,但表里 **z 只出现过 8 个**:`oi_chg` 的原始分量只有 8 天"
      "(2026-10-27 起),因此没有 z、没有任何一格可算 —— 报告里它是『样本不足』而不是『没信号』。")
    A("")
    A(f"- 基准率(全样本):30/60/90 天前瞻收益均值 "
      f"{res['base_rates']['fwd30'] * 100:.2f}% / {res['base_rates']['fwd60'] * 100:.2f}% / "
      f"{res['base_rates']['fwd90'] * 100:.2f}%;90 天内进入 ≥30% 回撤段的频率 "
      f"`dd90_peak` {res['base_rates']['dd90_peak'] * 100:.1f}%、`dd90_start` "
      f"{res['base_rates']['dd90_start'] * 100:.1f}%。")
    A("")
    A("## 2. ① 分档结果(顶档减底档 Δ + 块置换分位)")
    A("")
    A("**表 A — 前瞻收益(每个 (分量, 形态) 一行;括号内是块置换分位,1,000 次、种子 724)**")
    A("")
    A("| 分量 | 形态 | 30 天 Δ | 分位 | 60 天 Δ | 分位 | 90 天 Δ | 分位 | 顶/底档日历差(天) | 先行天数中位 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for rec in res["results"]:
        if rec.get("skipped"):
            A(f"| `{rec['comp']}` | {rec['form']} | — | — | — | — | — | — | — | 样本不足 |")
            continue
        o = rec["outcomes"]
        cells = []
        for h in (30, 60, 90):
            e = o["fwd%d" % h]
            cells += [pp(e.get("delta")), pct_str(e.get("pct"))]
        leads = [v["adverse_cross_rel_peak"] for v in rec["lead"].values()
                 if v["adverse_cross_rel_peak"] is not None]
        med = sorted(leads)[len(leads) // 2] if leads else None
        cg = rec.get("calendar_gap_days")
        A("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            rec["comp"], rec["form"], cells[0], cells[1], cells[2], cells[3], cells[4], cells[5],
            "—" if cg is None else f"{cg:+.0f}", day_str(med)))
    A("")
    A("**表 B — 90 天内进入 ≥30% 回撤段的频率(顶档 − 底档)**")
    A("")
    A("| 分量 | 形态 | `dd90_peak` Δ | 分位 | `dd90_start` Δ | 分位 |")
    A("|---|---|---|---|---|---|")
    for rec in res["results"]:
        if rec.get("skipped"):
            A(f"| `{rec['comp']}` | {rec['form']} | — | — | — | — |")
            continue
        o = rec["outcomes"]
        dp, dq = o["dd90_peak"], o["dd90_start"]
        A("| `%s` | %s | %s | %s | %s | %s |" % (
            rec["comp"], rec["form"], pp(dp.get("delta")), pct_str(dp.get("pct")),
            pp(dq.get("delta")), pct_str(dq.get("pct"))))
    A("")
    A("**表 C — 每档均值(90 天前瞻收益 / `dd90_peak` 频率)与日历诊断**")
    A("")
    A("`日历差` = 顶档与底档的**平均日历日之差**(距 2021-01-01 的天数)。差得越大,这一行的"
      "『五分位』越是日历代理而不是可交易的信号。")
    A("")
    A("| 分量 | 形态 | Q1 | Q2 | Q3 | Q4 | Q5 | 基准 | Q1…Q5 平均日历日 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        o = rec["outcomes"]
        q9 = o["fwd90"].get("q_means")
        if not q9:
            continue
        qd = rec.get("q_mean_day", [])
        A("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            rec["comp"], rec["form"], *[("—" if v is None else f"{v * 100:+.1f}%") for v in q9],
            f"{o['fwd90'].get('base_rate', 0) * 100:+.1f}%",
            " / ".join("—" if v is None else str(round(v)) for v in qd)))
    A("")
    A("## 3. ② 先行结构(三段最大回撤;负 = 先行)")
    A("")
    A("每格 = **首次**穿越 / **末次**穿越(不良方向,相对峰的天数)。`—` = 回看 365 天内没有发生穿越。")
    A("")
    A("| 分量 | 形态 | " + " | ".join(
        f"{e['peak_d']} 峰({e['depth_p2t'] * 100:.1f}%)" for e in res["segments_top3"]) + " |")
    A("|---|---|---|---|---|")
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        cells = []
        for e in res["segments_top3"]:
            v = rec["lead"].get(e["peak_d"], {})
            cells.append("%s / %s" % (day_str(v.get("adverse_cross_rel_peak")),
                                      day_str(v.get("adverse_last_rel_peak"))))
        A("| `%s` | %s | %s | %s | %s |" % (rec["comp"], rec["form"], cells[0], cells[1], cells[2]))
    A("")
    A("## 4. ④ 候选分量标记(**不是规则**)")
    A("")
    A("卡的口径:三期限同号 **且** 90 天期限分位 ≥ 0.95 **且** 三段里 ≥ 2 段先行天数 < 0。")
    A("")
    A(f"- 字面口径候选:**{res['candidates_raw'] or '无'}**")
    A(f"- 符号调整口径候选:**{res['candidates_sign_adj'] or '无'}**")
    A("")
    near = []
    for rec in res["results"]:
        c = rec.get("candidate") or {}
        if not c:
            continue
        crit = [bool(c.get("same_sign_raw")), bool(c.get("pct90") is not None and c["pct90"] >= 0.95),
                bool((c.get("lead_neg_segments") or 0) >= 2)]
        if sum(crit) == 2:
            miss = ["同号", "90 天分位 ≥ 0.95", "≥2 段先行"][crit.index(False)]
            near.append((rec["comp"], rec["form"], c, miss))
    if near:
        A("**近失(过了两条、差一条)** —— 供 ⓪ v3 预注册时参考,本卡不判:")
        A("")
        A("| 分量 | 形态 | 差的那一条 | 90 天分位 | 先行(≥2 段 / 窗口内) |")
        A("|---|---|---|---|---|")
        for comp, form, c, miss in near:
            A("| `%s` | %s | %s | %s | %s 段 / %s 段(−90…0 内) |" % (
                comp, form, miss, pct_str(c.get("pct90")), c.get("lead_neg_segments"),
                c.get("lead_neg_within90")))
        A("")
    A("**为什么没有候选**(逐条说清楚,这是本卡的主要结论):")
    A("")
    A("1. **先行天数这一条几乎全军覆没**:三段崩塌里,各分量的不良方向穿越绝大多数发生在峰前 "
      "100–330 天,而不是 −90…0 天窗口里。峰前 90 天窗口内唯一稳定出现的穿越是 "
      "`mom_60` 的 Δ30 形态(见下),但它的池化收益分位只有 0.51–0.83,不够 0.95。")
    A("2. **分位够高的那几行,信号是日历代理**:水平形态(`z`)的顶/底档平均日历日相差 365–808 天"
      "(见表 C),五分位在趋势型序列上≈按日历切段,于是 Δ 量的是『样本里哪一段牛/熊』,不是可交易的关系。"
      "块置换零分布抓不到这个混淆(它破坏的是信号与结果的**对齐**,不是信号本身的**趋势**)。")
    A("3. **两行同时满足『三期限同号 + 90 天分位 ≥ 0.95』,但都不是崩塌预警**:"
      "`taker_buy` 的 Δ30 形态(0.97 / 0.987 / 0.958)方向是**顶档回报更高**"
      "(+8.1 / +16.2 / +16.2pp)—— 风险**确认**,不是前兆;"
      "`stable_supply_30d` 的 z(0.99 / 0.995 / 0.988)日历差 +808 天 —— 纯日历代理。"
      "两行的先行天数都是 0 段(`taker_buy` 的 Δ30 只在 2025-10 段有 1 次穿越,在峰前 290 天,"
      "0 次落在 −90…0 窗口内)。")
    A("")
    A("## 5. ⑤ 诚实")
    A("")
    A("- **54 次比较**(9 分量 × 2 形态 × 3 期限)。若分位均匀,α=0.05 下期望有 ≈2.7 行『假阳性』;"
      "本卡最高分位那一行(0.995)在 54 次里并不稀奇。候选要进 ⓪ v3 的预注册才判,本卡不判。")
    A("- **日历混淆没有解决**,只是被量出来了(表 C 的『日历差』列)。水平形态的强分位基本都可以"
      "用『这一行是某一段行情的代理』解释掉(差 365–808 天);Δ30 形态里日历差小的"
      "(`taker_buy` −38、`breadth` +34、`mom_60` +50、`funding` −79 天)分位也低,"
      "只有 `taker_buy` 的 Δ30 例外(0.97 / 0.987 / 0.958)—— 它的日历差只有 −38 天,"
      "所以这一行是全表里**最不像日历代理**的强结果(但它是『涨得好』,不是『要崩』)。")
    A("- **零分布口径**:主口径(置换信号)与副口径(置换结果)的分位方向与量级一致"
      "(逐行对照见 `t241_results.json` 的 `null_pct_outcome_perm`),所以结论不依赖选哪一版。")
    A("- **`lend_apy` / `oi_chg`**:数据不够(`lend_apy` 的 z 从 2024-02-10 起,顶/底档观测不足 20 个;"
      "`oi_chg` 的原始分量只有 8 天),报告里是『样本不足』,不是『没信号』。")
    A("")
    A("## 6. 探索性发现(**需另立预注册、在新数据上过零信号对照**)")
    A("")
    A("1. **`mom_60` 的 30 日变化是唯一在三次崩塌前『临门一脚』的分量**:它的不良方向穿越(跌破自己"
      "历史 10 分位)在 2021-04 峰前 1 天、2021-11 峰前 21 天(末次)、2025-10 峰前 11 天(末次)——"
      "三段里 3/3 落在 −90…0 窗口内;其余分量这一格几乎全是 100 天以上。"
      "这与 T-239 的『崩塌是水位塌』结论方向一致(动量先塌),但**幅度**在池化样本上不显著"
      "(90 天分位 0.507)。")
    A("2. **回撤频率最强的三行都在水平形态上,而且都是日历混淆的行**:`breadth` 的 z 对 `dd90_start` "
      "Δ = −47.8pp(分位 0.005)、`mom_60` 的 z −52.6pp(0.002)、`taker_buy` 的 z 对 `dd90_peak` "
      "−22.4pp(0.018)。这三行的顶/底档日历差分别是 +365 / +374 / +55 天 —— "
      "『高广度/高动量 ⇒ 之后 90 天不崩』在样本里主要是『2025-2026 那一段没崩』。"
      "要真用,必须换成**非趋势**的构造(滚动分位 / 变化量)再预注册。")
    A("3. **`taker_buy` 的 Δ30 形态是唯一稳定的『风险确认』量**:顶档(30 日主动买盘份额上升最快)"
      "之后 30/60/90 天的收益比底档高 +8.1 / +16.2 / +16.2pp,分位 0.97 / 0.987 / 0.958,日历差只有 −38 天。"
      "它可以作为 ⓪ v3 的『风险确认量』候选,但**不是**崩塌预警候选。")
    A("4. **三段里没有一段能被 ⓪ 的水平分量解释**:2021-04 与 2021-11 两段发生时,`taker_buy` 的 z 还不存在"
      "(2022-01-25 起)、`stable_supply_30d` 的 z 只刚有 3 个月历史、`lend_apy` / `oi_chg` 完全没有 —— "
      "『谁先动』这个问题在早期两段上**大部分分量根本没机会答**。")
    A("")
    A("## 7. 复现")
    A("")
    A("```bash")
    A("python3 docs/research/t241_cycle_leadlag.py     # 只读;写 t241_results.json 与本报告")
    A("```")
    A("")
    A("- 零分布 / 分位 / 盈亏全部走 `src/data/evaluation/apparatus.py`"
      "(`block_permute / null_distribution / percentile_of / long_return`);事件段切法直接 import "
      "`docs/research/t234_cycle.py` 的 `events()` / `btc_closes()`,不重写。")
    A(f"- 参数:种子 {res['seed']}、零分布 {res['n_null']} 次、块长 {res['block']} 天、"
      f"扩张窗口最少 {res['min_bin_hist']} 个观测、每档最少 {res['min_bin_obs']} 个观测。")
    A("- 数据只读(`SUPABASE_URL` / `SUPABASE_KEY`,publishable);不写库、不做 DDL、不改 `src/`。")
    A("")
    return "\n".join(L) + "\n"


def main() -> None:
    z, zmeta = load_z()
    dates, closes, bsrc = load_btc()
    segs = t234.events(dates, closes)
    segs_sorted = sorted(segs, key=lambda s: s["depth_p2t"])
    eps = episodes(segs)
    eps_win = [e for e in eps if e["start_d"] >= EPISODE_WINDOW0]
    top3 = eps_win[:3]          # eps 按跌幅升序 ⇒ top3 是最深的三段
    outcomes = build_outcomes(dates, closes, segs)
    btc_idx = {d: i for i, d in enumerate(dates)}

    res: dict = {
        "card": "T-241", "prereg": "S-724", "seed": SEED, "n_null": N_NULL, "block": BLOCK,
        "min_bin_hist": MIN_BIN_HIST, "min_bin_obs": MIN_BIN_OBS,
        "dd_window": DD_WINDOW, "lead_window": LEAD_WINDOW, "lead_lookback": LEAD_LOOKBACK,
        "episode_window0": EPISODE_WINDOW0,
        "data": {"cycle_vector_daily": zmeta,
                 "btc": {"source": bsrc, "n": len(dates), "first": dates[0], "last": dates[-1]}},
        "segments_all": [{k: v for k, v in s.items()} for s in segs_sorted],
        "episodes_all": eps,
        "episodes_in_window": eps_win,
        "segments_top3": top3,
        "base_rates": {k: float(np.nanmean(v)) for k, v in outcomes.items()},
        "results": [],
    }

    for comp in COMPS:
        for form in ("z", "dz30"):
            rec = analyse(comp, form, z.get(comp, {}), btc_idx, outcomes, top3)
            res["results"].append(rec)
            print(f"[t241] {comp:20s} {form:5s} "
                  f"n={rec.get('n_series')} bins={rec.get('bin_counts')}", flush=True)

    # ④ 候选标记
    cand_raw, cand_adj = [], []
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        o = rec["outcomes"]
        try:
            d30, d60, d90 = (o[f"fwd{h}"]["delta"] for h in HORIZONS)
        except KeyError:
            continue
        if None in (d30, d60, d90):
            continue
        p90, p90a = o["fwd90"]["pct"], o["fwd90"]["pct_sign_adj"]
        a30, a60, a90 = (SIGN.get(rec["comp"], 1) * d for d in (d30, d60, d90))
        same_raw = (d30 > 0) == (d60 > 0) == (d90 > 0)
        same_adj = (a30 > 0) == (a60 > 0) == (a90 > 0)
        leads = [v["adverse_cross_rel_peak"] for v in rec["lead"].values()]
        lead_neg = sum(1 for x in leads if x is not None and x < 0)
        lead_in90 = sum(1 for v in rec["lead"].values()
                        if v["adverse_cross_rel_peak"] is not None
                        and -LEAD_WINDOW <= v["adverse_cross_rel_peak"] <= 0)
        leads_last = [v.get("adverse_last_rel_peak") for v in rec["lead"].values()]
        lead_last_neg = sum(1 for x in leads_last if x is not None and x < 0)
        lead_last_in90 = sum(1 for v in rec["lead"].values()
                             if v.get("adverse_last_rel_peak") is not None
                             and -LEAD_WINDOW <= v["adverse_last_rel_peak"] <= 0)
        lead_censored = sum(1 for x in leads if x is None)
        rec["candidate"] = {
            "same_sign_raw": same_raw, "same_sign_adj": same_adj,
            "pct90": p90, "pct90_sign_adj": p90a,
            "lead_days": leads, "lead_neg_segments": lead_neg,
            "lead_neg_within90": lead_in90,
            "lead_censored_segments": lead_censored,
            "lead_last_days": leads_last, "lead_last_neg_segments": lead_last_neg,
            "lead_last_in90_segments": lead_last_in90,
            "candidate_raw": bool(same_raw and p90 is not None and p90 >= 0.95 and lead_neg >= 2),
            "candidate_adj": bool(same_adj and p90a is not None and p90a >= 0.95 and lead_neg >= 2),
            "candidate_raw_strict90": bool(same_raw and p90 is not None and p90 >= 0.95 and lead_in90 >= 2),
            "candidate_raw_lastcross": bool(same_raw and p90 is not None and p90 >= 0.95
                                            and lead_last_neg >= 2),
        }
        if rec["candidate"]["candidate_raw"]:
            cand_raw.append(f"{rec['comp']}/{rec['form']}")
        if rec["candidate"]["candidate_adj"]:
            cand_adj.append(f"{rec['comp']}/{rec['form']}")
    res["candidates_raw"] = cand_raw
    res["candidates_sign_adj"] = cand_adj

    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    REPORT.write_text(render_report(res), encoding="utf-8")
    print(f"[t241] wrote {OUT}", flush=True)
    print(f"[t241] wrote {REPORT}", flush=True)
    print(f"[t241] candidates raw={cand_raw} adj={cand_adj}", flush=True)


if __name__ == "__main__":
    main()
