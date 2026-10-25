"""T-200 · S-685 —— 崩盘图谱的压力线索当 ③ 减仓规则(亮 ⇒ 敞口 0.5)。

台账 S-685(2026-10-25 15:49 UTC,`date -u`):M5 信用利差走阔 / M7 VIX > 30 / M8 VIX 期限倒挂 /
任一,当 BTC 的每日敞口规则(亮 ⇒ 0.5,亮过后保持 10 个自然日,切换扣 0.10% × |变化|),
与「持有」比,并对循环平移随机减仓做零分布对照。

**照台账一字不改**(有问题写进报告「协议问题」,不自己改)。
零分布 / 分位一律走 `src/data/evaluation/apparatus.py`;FRED 读数一律走
`docs/research/crash_atlas_common.load_fred`(import,不复制)。

跑法:python3 docs/research/t200_stress_derisk.py
出:docs/research/t200_results.json
    /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-200_stress_derisk.md
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from docs.research.crash_atlas_common import load_fred, to_calendar  # noqa: E402
from src.data.evaluation import apparatus  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t200_results.json")
REPORT_DIR = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"
REPORT = os.path.join(REPORT_DIR, "T-200_stress_derisk.md")

# ── 台账 S-685 写死的参数 ──────────────────────────────────────────────────
SEED = 685                 # 循环平移种子
N_SHIFT = 1000             # 循环平移次数
HOLD_DAYS = 10             # 亮过之后再保持 10 个自然日
COST_RATE = 0.001          # 每次切换扣 0.10% × |敞口变化|
LIT_LEVEL = 0.5            # 亮 ⇒ 敞口 0.5(敞口 0 一档是对照档)
M5_LOOKBACK_OBS = 63       # 63 个交易日前(观测)
M5_RISE_PP = 0.50          # 升 ≥ 0.50pp
M7_VIX = 30.0              # VIXCLS > 30
M8_RATIO = 1.0             # VIXCLS / VXVCLS > 1
SHIFT_MARGIN = 60          # 平移量在 [60, 长度 − 60] 天
LEVELS = (0.5, 0.0)
RULES = ("M5", "M7", "M8", "M_any")
GRID_START, GRID_END = "1986-01-01", "2026-10-31"

# BTC 主判窗口(台账):2014-09-17 → 2026-09-30(起点库中没有,见报告「协议问题」)
BTC_END = "2026-09-30"
NASDAQ_START = "1990-01-01"

# 四段熊市(端点取自 T-187 存档的崩盘目录 bear_episodes)
BEAR_SEGMENTS = [
    ("2018", "2017-12-15", "2018-12-15"),
    ("2020-03", "2019-06-26", "2020-03-16"),
    ("2022", "2021-11-08", "2022-11-21"),
    ("2025-10 → 2026", "2025-10-06", "2026-06-30"),
]

# ── 取数(库只读 publishable key;翻页必带 order=)───────────────────────────
SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
if not SUPA or not SUPK:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置,退出")
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
    """行 → 日历日序列(一天多行取最后一个)。"""
    idx = pd.to_datetime([r[x] for r in rows], format="ISO8601", utc=True).tz_localize(None).normalize()
    s = pd.Series(pd.to_numeric([r[y] for r in rows], errors="coerce"), index=idx, dtype="float64").dropna()
    return s.groupby(level=0).last().sort_index()


def load_crypto(sym: str) -> pd.Series:
    """库 `asset_mcap_daily` 的 price 列(卡:不用「市值 ÷ 价格」推)。"""
    rows = fetch("asset_mcap_daily",
                 {"symbol": "eq." + sym, "order": "d.asc", "select": "symbol,d,price"})
    return srs(rows, "d", "price")


# ── 信号(全部在日历日网格上)─────────────────────────────────────────────────
GRID = pd.date_range(GRID_START, GRID_END, freq="D")


def to_grid(s: pd.Series, gap: int = 7) -> pd.Series:
    """FRED 观测(日频,只到有观测的那天)→ 日历日网格(休市日沿用最近一个交易日的读数)。"""
    return to_calendar(s.astype(float), gap).reindex(GRID)


def published_lag1(daily: pd.Series) -> pd.Series:
    """第 t 天用 **t−1 已发布** 的读数:out[t] = daily[t−1](daily[d] = 截至 d 的最新观测)。"""
    return daily.shift(1)


def build_signals() -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[str, Any]]:
    """返回 (亮灯序列, 信号「有定义」序列, 元信息)。"""
    baa = load_fred("BAA10Y")                       # Baa−10Y 利差(FRED 定义,不再减 DGS10)
    vix = load_fred("VIXCLS")
    vxv = load_fred("VXVCLS")

    d5 = baa - baa.shift(M5_LOOKBACK_OBS)           # 63 个交易日前
    m5_obs = (d5 >= M5_RISE_PP).astype(float).where(d5.notna())
    m7_obs = (vix > M7_VIX).astype(float)
    ratio = (vix / vxv.reindex(vix.index)).replace([np.inf, -np.inf], np.nan)
    after_vxv = vix.index >= vxv.index[0]
    n_vix_no_vxv = int(ratio.isna().sum())
    n_after_vxv_start = int(ratio.loc[after_vxv].isna().sum())
    m8_obs = (ratio > M8_RATIO).astype(float)
    m8_obs[~after_vxv] = 0.0            # VXV 之前「记不亮」(台账)
    m8_obs[after_vxv & ratio.isna()] = np.nan   # VXV 缺读数日 → 沿用最近交易日读数(休市规则)

    daily = {
        "M5": to_grid(m5_obs),
        "M7": to_grid(m7_obs),
        "M8": to_grid(m8_obs),
    }
    daily["M_any"] = pd.DataFrame({k: daily[k] for k in ("M5", "M7", "M8")}).max(axis=1, skipna=True)
    lit = {k: (published_lag1(v) > 0.5) for k, v in daily.items()}
    defined = {k: published_lag1(v.notna().astype(float)) > 0.5 for k, v in daily.items()}
    meta = {
        "m5_lookback_obs": M5_LOOKBACK_OBS,
        "m5_rise_pp": M5_RISE_PP,
        "m7_vix_gt": M7_VIX,
        "m8_ratio_gt": M8_RATIO,
        "publication_rule": "第 t 天用 t−1 已发布的读数(读数 dated d ⇒ d+1 才可用)",
        "baa_span": [str(baa.index[0].date()), str(baa.index[-1].date())],
        "vix_span": [str(vix.index[0].date()), str(vix.index[-1].date())],
        "vxv_span": [str(vxv.index[0].date()), str(vxv.index[-1].date())],
        "n_vix_dates_without_vxv": n_vix_no_vxv,
        "n_after_vxv_start_missing": n_after_vxv_start,
    }
    return lit, defined, meta


def signal_last_defined(defined: dict[str, pd.Series]) -> pd.Timestamp:
    """信号(有 t−1 读数可用)最后有定义的一天。"""
    last = None
    for s in defined.values():
        ok = s.index[s.to_numpy(dtype=bool)]
        if len(ok):
            last = ok[-1] if last is None else max(last, ok[-1])
    if last is None:
        raise SystemExit("没有任何信号有定义")
    return last


# ── 敞口与收益 ──────────────────────────────────────────────────────────────
def latch_array(lit: np.ndarray, hold: int = HOLD_DAYS) -> np.ndarray:
    """亮过之后再保持 hold 个自然日(防闪烁):t 亮 ⇒ t..t+hold 都是「减仓态」。"""
    idx = np.arange(len(lit))
    last = np.maximum.accumulate(np.where(lit, idx, -10 ** 9))
    return (idx - last) <= hold


def exposure_from_lit(lit: np.ndarray, level: float) -> np.ndarray:
    return np.where(latch_array(lit), level, 1.0)


def strat_returns(exposure: np.ndarray, rets: np.ndarray, charge_first: bool = False) -> np.ndarray:
    """日收益 = 敞口 × 当日价格收益 − 0.10% × |敞口变化|。

    `charge_first=False`:窗口第一天的建仓不算切换(窗口内没有前一次敞口,台账只说「每次切换」)。"""
    if charge_first:
        prev = np.concatenate(([1.0], exposure[:-1]))
    else:
        prev = np.concatenate(([exposure[0]], exposure[:-1]))
    return exposure * rets - COST_RATE * np.abs(exposure - prev)


def metrics(rets: np.ndarray, n_days: int) -> dict[str, Any]:
    eq = np.cumprod(1.0 + rets)
    years = n_days / 365.25
    total = float(eq[-1] - 1.0)
    ann = float(eq[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    dd = eq / np.maximum.accumulate(eq) - 1.0
    mdd = float(dd.min())
    calmar = float(ann / abs(mdd)) if mdd < 0 else float("inf")
    return {"total_return": total, "annualized": ann, "max_drawdown": mdd,
            "calmar": calmar, "n_days": int(n_days)}


def null_calmars(lit: np.ndarray, rets: np.ndarray, level: float,
                 actual: Optional[float]) -> tuple[Optional[np.ndarray], Optional[float], Optional[str]]:
    """循环平移的 Calmar 零分布(1,000 次,种子 685,平移量在 [60, N−60] 天均匀)。

    平移的是**原始亮灯序列**(亮的天数占比、亮段长度分布不变,只换时点);
    保持期与交易成本在平移后重新算。"""
    n = len(lit)
    lo, hi = SHIFT_MARGIN, n - SHIFT_MARGIN
    if hi <= lo:
        return None, None, "窗口太短,平移区间为空"

    def draw(rng: np.random.Generator) -> float:
        k = int(rng.integers(lo, hi + 1))
        e = exposure_from_lit(np.roll(lit, k), level)
        return metrics(strat_returns(e, rets), n)["calmar"]

    try:
        null = apparatus.null_distribution(draw, N_SHIFT, seed=SEED, actual=actual)
    except apparatus.NoOpNull as exc:
        return None, None, "apparatus.null_distribution 拒绝:" + repr(exc)
    return null, apparatus.percentile_of(actual, null), None


def criteria(rule: dict[str, Any], hold: dict[str, Any], pctile: Optional[float],
             null_p95: Optional[float]) -> dict[str, Any]:
    """台账 S-685 三条判据(BTC 上,每条规则单独判)。"""
    c1 = abs(rule["max_drawdown"]) <= 0.85 * abs(hold["max_drawdown"])
    c2 = bool(rule["annualized"] >= hold["annualized"] - 0.02 or rule["calmar"] > hold["calmar"])
    c3 = bool(pctile is not None and pctile >= 0.95)
    return {
        "c1_dd_15pct_shallower": bool(c1),
        "c2_annual_within_2pp_or_calmar_higher": c2,
        "c3_calmar_ge_null_p95": c3,
        "verdict": "过" if (c1 and c2 and c3) else "不过",
        "null_p95": null_p95,
        "percentile_of": pctile,
    }


# ── 资产窗口 ────────────────────────────────────────────────────────────────
def build_assets(sig_end: pd.Timestamp) -> dict[str, dict[str, Any]]:
    btc = load_crypto("BTC")
    eth = load_crypto("ETH")
    nasdaq = load_fred("NASDAQCOM")

    def window(px: pd.Series, start: Optional[str], end_cap: Optional[str]) -> tuple[pd.Series, list[str]]:
        p = px.sort_index()
        s = p.index[0] if start is None else max(p.index[0], pd.Timestamp(start))
        e = p.index[-1] if end_cap is None else min(p.index[-1], pd.Timestamp(end_cap))
        e = min(e, sig_end)
        p = p[(p.index >= s) & (p.index <= e)]
        return p, [str(p.index[0].date()), str(p.index[-1].date())]

    out = {}
    for name, px, start, end_cap in (
            ("BTC", btc, None, BTC_END),
            ("ETH", eth, None, None),
            ("NASDAQ", nasdaq, NASDAQ_START, None)):
        p, win = window(px, start, end_cap)
        out[name] = {"price": p, "window": win,
                     "price_full_span": [str(px.index[0].date()), str(px.index[-1].date())]}
    return out


def by_year(days: pd.DatetimeIndex, rets: np.ndarray, rule_rets: np.ndarray,
            lit: np.ndarray, exp: np.ndarray) -> list[dict[str, Any]]:
    df = pd.DataFrame({"hold": rets, "rule": rule_rets, "lit": lit.astype(float),
                       "exp": exp}, index=days)
    out = []
    for y, g in df.groupby(df.index.year):
        out.append({
            "year": int(y),
            "n_days": int(len(g)),
            "lit_days": int(g["lit"].sum()),
            "lit_share": float(g["lit"].mean()),
            "switches": int((np.diff(g["exp"].values) != 0).sum()),
            "hold_return": float(np.prod(1.0 + g["hold"].values) - 1.0),
            "rule_return": float(np.prod(1.0 + g["rule"].values) - 1.0),
        })
    return out


def bear_segments(days: pd.DatetimeIndex, price: pd.Series, rule_rets: np.ndarray) -> list[dict[str, Any]]:
    out = []
    for label, d0, d1 in BEAR_SEGMENTS:
        t0, t1 = pd.Timestamp(d0), pd.Timestamp(d1)
        m0, m1 = days[days <= t0], days[days <= t1]
        if not len(m0) or not len(m1):
            continue
        a, b = m0[-1], m1[-1]
        mask = np.asarray((days > a) & (days <= b))
        hold = float(price.loc[b] / price.loc[a] - 1.0)
        rule = float(np.prod(1.0 + rule_rets[mask]) - 1.0)
        out.append({"label": label, "start": str(a.date()), "end": str(b.date()),
                    "hold_return": hold, "rule_return": rule, "diff": rule - hold})
    return out


def fwd20(price: pd.Series, lit: np.ndarray, latched: np.ndarray) -> dict[str, Any]:
    """亮着时 BTC 之后 20 日的平均收益(错过的反弹)。"""
    px = price.to_numpy(dtype=float)
    n = len(px)
    fwd = np.full(n, np.nan)
    if n > 20:
        fwd[: n - 20] = px[20:] / px[: n - 20] - 1.0
    ok = np.isfinite(fwd)
    out: dict[str, Any] = {}
    for tag, mask in (("lit", lit), ("latched", latched), ("all", ok)):
        m = mask & ok
        out[tag] = {
            "n": int(m.sum()),
            "mean_20d_fwd_return": float(fwd[m].mean()) if m.sum() else None,
            "median_20d_fwd_return": float(np.median(fwd[m])) if m.sum() else None,
        }
    return out


def runs(mask: np.ndarray, days: pd.DatetimeIndex) -> list[list[str]]:
    """True 的连续段 → [[起, 止](含), ...](逐日序列的无损压缩,便于人看和复算)。"""
    out: list[list[str]] = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([str(days[start].date()), str(days[i - 1].date())])
            start = None
    if start is not None:
        out.append([str(days[start].date()), str(days[-1].date())])
    return out


def evaluate_asset(price: pd.Series, lit: dict[str, pd.Series]) -> dict[str, Any]:
    days = price.index
    rets = price.pct_change().to_numpy(dtype=float)
    rets = np.where(np.isfinite(rets), rets, 0.0)     # 首日无前收,记 0
    hold = metrics(rets, len(days))
    res: dict[str, Any] = {
        "n_days": int(len(days)),
        "hold": hold,
        "dates": [str(d.date()) for d in days],
        "rules": {},
    }
    for rule in RULES:
        la = lit[rule].reindex(days).to_numpy(dtype=bool)
        latched = latch_array(la)
        exp05 = exposure_from_lit(la, 0.5)
        exp00 = exposure_from_lit(la, 0.0)
        entry: dict[str, Any] = {
            "lit_days": int(la.sum()),
            "lit_share": float(la.mean()),
            "latched_days": int(latched.sum()),
            "latched_share": float(latched.mean()),
            "switches": {"0.5": int((np.diff(exp05) != 0).sum()),
                         "0": int((np.diff(exp00) != 0).sum())},
            "lit_spans": runs(la, days),
            "latched_spans": runs(latched, days),
            "exposure_0.5": exp05.tolist(),
            "exposure_0": exp00.tolist(),
            "levels": {},
        }
        for level, exp in ((0.5, exp05), (0.0, exp00)):
            r = strat_returns(exp, rets)
            m = metrics(r, len(days))
            null, pctile, err = null_calmars(la, rets, level, m["calmar"])
            crit = criteria(m, hold, pctile, float(np.percentile(null, 95)) if null is not None else None)
            entry["levels"][str(level)] = {
                "metrics": m,
                "null": [round(float(x), 6) for x in null] if null is not None else None,
                "null_p50": float(np.median(null)) if null is not None else None,
                "null_p95": float(np.percentile(null, 95)) if null is not None else None,
                "null_max": float(np.max(null)) if null is not None else None,
                "percentile_of": pctile,
                "criteria": crit,
                "error": err,
                "annualized_if_build_charged": metrics(
                    strat_returns(exp, rets, charge_first=True), len(days))["annualized"],
            }
        entry["by_year"] = by_year(days, rets, strat_returns(exp05, rets), la, exp05)
        entry["bear_segments"] = bear_segments(days, price, strat_returns(exp05, rets))
        entry["fwd20"] = fwd20(price, la, latched)
        res["rules"][rule] = entry
    return res


# ── 报告 ────────────────────────────────────────────────────────────────────
def pct(x: Optional[float], d: int = 2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x * 100:.{d}f}%"


def num(x: Optional[float], d: int = 2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{d}f}"


def build_report(R: dict[str, Any]) -> str:
    btc = R["assets"]["BTC"]
    L: list[str] = []
    L.append("# T-200 · S-685 —— 崩盘图谱的压力线索当 ③ 减仓规则(亮 ⇒ BTC 敞口 0.5)")
    L.append("")
    L.append(f"台账 S-685(2026-10-25 15:49 UTC)· 种子 {SEED} · 循环平移 {N_SHIFT} 次 · "
             f"亮过后保持 {HOLD_DAYS} 个自然日 · 切换扣 {COST_RATE * 100:.2f}% × |变化| · 空出部分收 0。")
    L.append("")
    L.append("## 判据表(BTC 主判,4 条规则 × 3 条判据)")
    L.append("")
    L.append("| 规则 | 亮天占比 | 切换次数 | 年化 | 最大回撤 | Calmar | ① 回撤浅 ≥15%(相对) | "
             "② 年化少 ≤2pp 或 Calmar > 持有 | ③ Calmar ≥ 平移零分布 95 分位 | 判定 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    hold = btc["hold"]
    for rule in RULES:
        e = btc["rules"][rule]
        lv = e["levels"]["0.5"]
        m, c = lv["metrics"], lv["criteria"]
        L.append(f"| {rule} | {pct(e['lit_share'], 1)} | {e['switches']['0.5']} | "
                 f"{pct(m['annualized'])} | {pct(m['max_drawdown'])} | {num(m['calmar'])} | "
                 f"{'过' if c['c1_dd_15pct_shallower'] else '不过'} | "
                 f"{'过' if c['c2_annual_within_2pp_or_calmar_higher'] else '不过'} | "
                 f"{'过' if c['c3_calmar_ge_null_p95'] else '不过'} "
                 f"(分位 {pct(c['percentile_of'], 1)}) | **{c['verdict']}** |")
    L.append(f"| 持有(对照) | — | 0 | {pct(hold['annualized'])} | {pct(hold['max_drawdown'])} | "
             f"{num(hold['calmar'])} | — | — | — | — |")
    L.append("")
    L.append(f"多重比较:**4 条规则**(台账 S-685「试验计数:③ 族,4 条」)。"
             f"①= 最大回撤相对持有浅 ≥15%;②= 年化少 ≤2pp **或** Calmar 高于持有;"
             f"③= 规则的 Calmar ≥ 循环平移零分布的 95 分位(零分布走 `apparatus.null_distribution`,"
             f"分位走 `apparatus.percentile_of`)。三条全过才记「过」。")
    L.append("")
    L.append("## 只报项")
    L.append("")
    L.append(f"### 亮的天数占比 / 切换次数(BTC {btc['window'][0]} → {btc['window'][1]},{btc['n_days']} 天)")
    L.append("")
    L.append("| 规则 | 原始亮灯天数 | 亮灯占比 | 减仓态天数(敞口 0.5) | 减仓态占比 | 切换次数 |")
    L.append("|---|---|---|---|---|---|")
    for rule in RULES:
        e = btc["rules"][rule]
        L.append(f"| {rule} | {e['lit_days']} | {pct(e['lit_share'], 1)} | {e['latched_days']} | "
                 f"{pct(e['latched_share'], 1)} | {e['switches']['0.5']} |")
    L.append("")
    L.append("### 按年(BTC,敞口 0.5 一档)")
    L.append("")
    L.append("| 年 | 天数 | 亮灯天数 M5/M7/M8/任一 | 切换 M5/M7/M8/任一 | 持有 | 规则 M5 | 规则 M7 | "
             "规则 M8 | 规则 任一 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    yrs = [y["year"] for y in btc["rules"]["M_any"]["by_year"]]
    for i, y in enumerate(yrs):
        cells = []
        for rule in RULES:
            row = btc["rules"][rule]["by_year"][i]
            cells.append(str(row["lit_days"]))
        sw = []
        for rule in RULES:
            row = btc["rules"][rule]["by_year"][i]
            sw.append(str(row["switches"]))
        rr = []
        for rule in RULES:
            row = btc["rules"][rule]["by_year"][i]
            rr.append(pct(row["rule_return"]))
        hb = btc["rules"]["M_any"]["by_year"][i]["hold_return"]
        L.append(f"| {y} | {btc['rules']['M_any']['by_year'][i]['n_days']} | "
                 f"{'/'.join(cells)} | {'/'.join(sw)} | {pct(hb)} | {' | '.join(rr)} |")
    L.append("")
    L.append("### 四段熊市各自少亏多少(BTC;差 = 规则 − 持有,正数 = 少亏)")
    L.append("")
    L.append("| 熊市段 | 起 → 止 | 持有 | M5 | M7 | M8 | 任一 |")
    L.append("|---|---|---|---|---|---|---|")
    segs = btc["rules"]["M_any"]["bear_segments"]
    for i, s in enumerate(segs):
        rr = []
        for rule in RULES:
            row = btc["rules"][rule]["bear_segments"][i]
            rr.append(pct(row["diff"]))
        L.append(f"| {s['label']} | {s['start']} → {s['end']} | {pct(s['hold_return'])} | "
                 f"{' | '.join(rr)} |")
    L.append("")
    L.append("### 亮着时 BTC 之后 20 日平均收益(错过的反弹)")
    L.append("")
    L.append("| 规则 | 亮灯天数 | 亮灯日平均 20 日后收益 | 中位数 | 减仓态天数 | 减仓态平均 | 中位数 |")
    L.append("|---|---|---|---|---|---|---|")
    for rule in RULES:
        f = btc["rules"][rule]["fwd20"]
        L.append(f"| {rule} | {f['lit']['n']} | {pct(f['lit']['mean_20d_fwd_return'])} | "
                 f"{pct(f['lit']['median_20d_fwd_return'])} | {f['latched']['n']} | "
                 f"{pct(f['latched']['mean_20d_fwd_return'])} | "
                 f"{pct(f['latched']['median_20d_fwd_return'])} |")
    f = btc["rules"]["M_any"]["fwd20"]
    L.append(f"| 全部有前视的交易日(对照) | {f['all']['n']} | "
             f"{pct(f['all']['mean_20d_fwd_return'])} | {pct(f['all']['median_20d_fwd_return'])} | — | — | — |")
    L.append("")
    for key in ("ETH", "NASDAQ"):
        a = R["assets"][key]
        L.append(f"### {key}(只报 · {a['window'][0]} → {a['window'][1]},{a['n_days']} 天)")
        L.append("")
        if key == "NASDAQ":
            L.append("**NASDAQ 不进判据**:图谱发现(T-185 / T-193)用过这段 NASDAQ 历史,不是样本外。")
            L.append("")
        L.append("| 规则 | 亮灯占比 | 年化 | 最大回撤 | Calmar | 持有年化 | 持有回撤 | 持有 Calmar |")
        L.append("|---|---|---|---|---|---|---|---|")
        for rule in RULES:
            m = a["rules"][rule]["levels"]["0.5"]["metrics"]
            L.append(f"| {rule} | {pct(a['rules'][rule]['lit_share'], 1)} | {pct(m['annualized'])} | "
                     f"{pct(m['max_drawdown'])} | {num(m['calmar'])} | {pct(a['hold']['annualized'])} | "
                     f"{pct(a['hold']['max_drawdown'])} | {num(a['hold']['calmar'])} |")
        L.append("")
    L.append("### 敞口 0 一档(亮 ⇒ 敞口 0,空出部分收 0;只报,同一三条判据口径)")
    L.append("")
    L.append("| 规则 | 亮灯占比 | 年化 | 最大回撤 | Calmar | ① | ② | ③ | 判定 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for rule in RULES:
        lv = btc["rules"][rule]["levels"]["0.0"]
        m, c = lv["metrics"], lv["criteria"]
        L.append(f"| {rule} | {pct(btc['rules'][rule]['lit_share'], 1)} | {pct(m['annualized'])} | "
                 f"{pct(m['max_drawdown'])} | {num(m['calmar'])} | "
                 f"{'过' if c['c1_dd_15pct_shallower'] else '不过'} | "
                 f"{'过' if c['c2_annual_within_2pp_or_calmar_higher'] else '不过'} | "
                 f"{'过' if c['c3_calmar_ge_null_p95'] else '不过'} | **{c['verdict']}** |")
    L.append("")
    L.append("## 协议问题(照台账做,没有自己改)")
    L.append("")
    for i, p in enumerate(R["protocol_issues"], 1):
        L.append(f"{i}. {p}")
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"复算:`python3 docs/research/t200_stress_derisk.py` → `docs/research/t200_results.json`"
             f"(逐日敞口序列 + 每条规则每档的零分布全在里面)。生成于 {R['generated_at_utc']}。")
    L.append("")
    return "\n".join(L)


# ── 主流程 ──────────────────────────────────────────────────────────────────
def dump_json(path: str, obj: Any) -> None:
    """JSON:结构用 indent=1 保持可读,超过 500 个元素的数组用紧凑写法(占位符换回)。"""
    holes: dict[str, str] = {}

    def repl(o: Any) -> Any:
        if isinstance(o, list) and len(o) > 500:
            key = f"__HOLE_{len(holes)}__"
            holes[key] = json.dumps(o, ensure_ascii=False, separators=(",", ":"))
            return key
        if isinstance(o, dict):
            return {k: repl(v) for k, v in o.items()}
        if isinstance(o, list):
            return [repl(v) for v in o]
        return o

    text = json.dumps(repl(obj), ensure_ascii=False, indent=1)
    for key, val in holes.items():
        text = text.replace(f'"{key}"', val)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    lit, defined, sig_meta = build_signals()
    sig_end = signal_last_defined(defined)
    sig_meta["signal_last_defined"] = str(sig_end.date())
    assets = build_assets(sig_end)

    results: dict[str, Any] = {
        "task": "T-200",
        "ledger": "S-685",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "seed": SEED,
        "n_shift": N_SHIFT,
        "hold_days": HOLD_DAYS,
        "cost_rate": COST_RATE,
        "lit_level": LIT_LEVEL,
        "levels_tested": list(LEVELS),
        "rules": list(RULES),
        "multiple_comparisons": 4,
        "signal_meta": sig_meta,
        "encoding": {
            "assets.*.dates": "该资产的逐日日期(窗口内全部交易日/日历日)",
            "assets.*.rules.*.exposure_0.5 / exposure_0": "逐日敞口序列(0.5 档 / 0 档)",
            "assets.*.rules.*.lit_spans / latched_spans": "亮灯 / 减仓态的连续段 [起, 止](含);"
            "lit 由它逐日展开,latched = 亮灯日起 10 个自然日内(台账 S-685)",
            "assets.*.rules.*.levels.*.null": "循环平移 Calmar 零分布(1,000 次,种子 685)",
        },
        "assets": {},
        "protocol_issues": [],
    }

    for name, a in assets.items():
        res = evaluate_asset(a["price"], lit)
        res["window"] = a["window"]
        res["price_full_span"] = a["price_full_span"]
        results["assets"][name] = res

    btc = results["assets"]["BTC"]
    eth = results["assets"]["ETH"]
    nas = results["assets"]["NASDAQ"]
    sens = results["m5_caliber_sensitivity_63_calendar_days"] = m5_sensitivity(lit, assets)

    results["protocol_issues"] = [
        f"**BTC 起点**:台账写 2014-09-17,但库 `asset_mcap_daily` 的 BTC `price` 最早只有 "
        f"{btc['price_full_span'][0]}(实测,库里没有更早的)⇒ 起点用实测 {btc['window'][0]};"
        f"终点照台账 {btc['window'][1]}。",
        f"**ETH 起点**:台账写 2016-03,实测最早 {eth['price_full_span'][0]} ⇒ 用实测起点;"
        f"终点取「信号有定义的最后一天」{eth['window'][1]}(FRED 快照到 {sig_meta['vix_span'][1]},"
        f"再往后没有 t−1 读数可用);ETH 价格本身到 {eth['price_full_span'][1]}。",
        f"**M5 的 63**:台账写「63 个交易日前」,本卡按 **63 个观测(=63 个交易日)** 算;"
        f"图谱(T-187)当时是 `to_calendar` 之后 `shift(63)`,即 **63 个日历日**(≈45 个交易日)。"
        f"两种口径给出的 M5 不是同一条:按图谱口径(63 个日历日)复算 ⇒ 年化 "
        f"{pct(sens['metrics']['annualized'])}、最大回撤 {pct(sens['metrics']['max_drawdown'])}、"
        f"Calmar {num(sens['metrics']['calmar'])}、判定 **{sens['criteria']['verdict']}**"
        f"(分位 {pct(sens['criteria']['percentile_of'], 1)})。**只作口径敏感性参考,"
        f"不计入 4 条试验计数、不作判定依据**。",
        f"**M8 在 VXV 之前**:台账写「VXV 2007-12 起,之前记不亮」⇒ 本卡按 **不亮(False)** 处理;"
        f"图谱口径里那一段是「无数据(NA)」。BTC 窗口 2014-12 起,实际不影响"
        f"(VXV 起点 {sig_meta['vxv_span'][0]})。",
        "**建仓算不算切换**:台账只说「每次切换扣 0.10% × |敞口变化|」,窗口第一天没有前一次敞口 ⇒ "
        "第一天不扣成本。若改成「建仓也算一次切换」,4 条规则的年化见 JSON 里 "
        "`assets.BTC.rules.*.levels.*.annualized_if_build_charged`(与主表差 ≤0.1pp 量级,判定不变)。",
        f"**循环平移**:平移量在 [60, 长度 − 60] 天均匀抽(整数,含端点),{N_SHIFT} 次,种子 {SEED};"
        f"平移的是**原始亮灯序列**,保持期与交易成本在平移后重算 ⇒ 亮天占比、亮段长度分布不变,只换时点。"
        f"零分布与分位走 `apparatus.null_distribution` / `apparatus.percentile_of`,没自己再写一遍。",
        "**四段熊市的端点**:台账只给了年份标签,端点取自 T-187 存档的崩盘目录 `bear_episodes`:"
        "2018 段取两腿合并(2017-12-15 峰 → 2018-12-15 谷);2020-03 / 2022 / 2025-10→2026 各取一段。"
        "目录里还有一段 2021-04-13 → 2021-07-20,不在台账的四段里,按台账不报。",
        "**敞口 0 一档**是台账「只报」里的对照档,不进判据、不计入 4 条试验计数;"
        "表里仍按同三条判据给结果,只为对照。",
        f"**NASDAQ 不进判据**:台账写明「图谱发现用过这段 ⇒ 不进判据」;"
        f"NASDAQ 窗口 {nas['window'][0]} → {nas['window'][1]}(价格全区间 "
        f"{nas['price_full_span'][0]} → {nas['price_full_span'][1]},按台账 1990 起)。",
    ]

    dump_json(OUT, results)

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(build_report(results))

    # ── 只打印汇总行 ────────────────────────────────────────────────────────
    for rule in RULES:
        lv = btc["rules"][rule]["levels"]["0.5"]
        c = lv["criteria"]
        print(f"[BTC] {rule:5s} lit={btc['rules'][rule]['lit_share']:.3f} "
              f"sw={btc['rules'][rule]['switches']['0.5']:3d} "
              f"ann={lv['metrics']['annualized']:.4f} mdd={lv['metrics']['max_drawdown']:.4f} "
              f"calmar={lv['metrics']['calmar']:.3f} nullp95={lv['null_p95']:.3f} "
              f"pct={c['percentile_of']:.4f} "
              f"c1={int(c['c1_dd_15pct_shallower'])} c2={int(c['c2_annual_within_2pp_or_calmar_higher'])} "
              f"c3={int(c['c3_calmar_ge_null_p95'])} -> {c['verdict']}")
    print(f"[BTC] hold ann={btc['hold']['annualized']:.4f} mdd={btc['hold']['max_drawdown']:.4f} "
          f"calmar={btc['hold']['calmar']:.3f}")
    for key in ("ETH", "NASDAQ"):
        a = results["assets"][key]
        print(f"[{key}] hold ann={a['hold']['annualized']:.4f} mdd={a['hold']['max_drawdown']:.4f} "
              f"calmar={a['hold']['calmar']:.3f} | " +
              " ".join(f"{r}:{a['rules'][r]['levels']['0.5']['metrics']['calmar']:.2f}" for r in RULES))
    for i, s in enumerate(btc["rules"]["M_any"]["bear_segments"]):
        print(f"[BTC/熊市] {s['label']:14s} hold={s['hold_return']:.4f} "
              + " ".join(f"{r}:{btc['rules'][r]['bear_segments'][i]['diff']:+.4f}" for r in RULES))
    print(f"[M5 敏感性 63 日历日] ann={sens['metrics']['annualized']:.4f} "
          f"mdd={sens['metrics']['max_drawdown']:.4f} calmar={sens['metrics']['calmar']:.3f} "
          f"-> {sens['criteria']['verdict']}")
    print(f"[输出] {OUT}")
    print(f"[输出] {REPORT}")
    return 0


def m5_sensitivity(lit: dict[str, pd.Series], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """口径敏感性:图谱的 M5(63 个**日历日**)在 BTC 上的同一口径复算。只报,不作判定依据。"""
    baa = load_fred("BAA10Y")
    cal_baa = to_grid(baa)                       # 日历日网格(和图谱 T-187 同口径)
    daily_alt = cal_baa - cal_baa.shift(63)      # 63 个**日历日**前
    la = (published_lag1(daily_alt) > 0.5).reindex(
        assets["BTC"]["price"].index).to_numpy(dtype=bool)
    px = assets["BTC"]["price"]
    rets = px.pct_change().to_numpy(dtype=float)
    rets = np.where(np.isfinite(rets), rets, 0.0)
    exp = exposure_from_lit(la, 0.5)
    m = metrics(strat_returns(exp, rets), len(px))
    hold = metrics(rets, len(px))
    null, pctile, err = null_calmars(la, rets, 0.5, m["calmar"])
    crit = criteria(m, hold, pctile, float(np.percentile(null, 95)) if null is not None else None)
    return {"note": "图谱口径(M5 用 63 个日历日);不是台账口径,不计入 4 条试验计数,不作判定依据",
            "metrics": m, "criteria": crit, "error": err,
            "lit_share": float(la.mean())}


if __name__ == "__main__":
    sys.exit(main())
