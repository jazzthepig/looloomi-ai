"""T-264 —— S-742「谁在买」:场所成交份额对 BTC / 山寨之后 30 天 —— 预注册实现。

口径一字不改地照 REFUTATION_LEDGER.md 的 S-742 段(Seth,2026-11-06 08:36 UTC 预注册):

- **数据**:`exchange_volume_daily`(CoinGecko Analyst volume_chart/range,BTC 计价,d = 点的 UTC 日期)
  经 `feature_matrix_daily` 的 `venue:*`;样本 2021-03-01 → 回填末日。
- **前提**:gdax / binance / upbit / binance_futures 四个场所 2021-03 起逐日齐全(缺 > 5% 的天数 ⇒ 停,报覆盖,不跑)。
- **特征**:F1 = `venue:coinbase_share_spot30` 减它自己过去 180 天均值;
  F2 = `venue:korea_share_spot30` 在过去 365 天里的分位;
  F3 = `venue:deriv_to_spot30` 在过去 365 天里的分位(均只用 ≤ d 的数据)。
- **结果**:BTC 永续 d → d+30 对数收益(F1、F2、F3);山寨等权(① 面板除 BTC/ETH)减 BTC 的 30 天对数超额(F2);
  BTC d → d+30 的最大回撤(F3)。
- **预期方向**:F1 → BTC 收益 **正**;F2 → 山寨超额 **负**、BTC 收益 **负**;F3 → 最大回撤 **更深**(更负)。
- **判据**(每条单独判,BH q = 0.10 跨 5 个检验):(a) 全样本日度 Spearman IC 与预期同号且 |IC| ≥ 0.10;
  (b) 零分布 = 特征序列整体循环平移(平移量 ≥ 60 天,1,000 次,种子 742),实际 IC 在预期方向的分位 ≥ 0.95;
  (c) 两段(2021-03 → 2023-06 / 2023-07 →)同号;(d) 控制 BTC 过去 30 天收益后(秩回归残差)仍同号。
- **副(不判)**:同一特征对 7 天;链上永续份额(`venue:onchain_perp_share30`)只描述走势,不测。

零分布 / 分位只用 `src/data/evaluation/apparatus.py`(`null_distribution` 驱动循环平移、`percentile_of` 读分位);
本卡没有联合模型(单一因子 × 单一结果),故不碰 `joint_model.py` 的模型面。

**只读库,不写库,不改生产代码。** 产物:`docs/research/t264_results.json`(+ 标准输出摘要)。

用法:
    python3 docs/research/t264_venue.py            # 前提检查 + 5 个检验
    python3 docs/research/t264_venue.py --stage premise   # 只跑前提检查
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Callable, Optional

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
)

# ── 预注册常量(一字不改) ────────────────────────────────────────────────────────
START = "2021-03-01"
SEED = 742
N_NULL = 1000
MIN_SHIFT = 60
SEG1_END = "2023-06-30"
SEG2_START = "2023-07-01"
BH_Q = 0.10
IC_MIN = 0.10
PCT_MIN = 0.95
H30 = 30
H7 = 7
VENUES_REQUIRED = ["gdax", "binance", "upbit", "binance_futures"]
COINBASE = ["gdax", "coinbase"]
KOREA = ["upbit", "bithumb"]
FEATURE_KEYS = {
    "F1": "venue:coinbase_share_spot30",
    "F2": "venue:korea_share_spot30",
    "F3": "venue:deriv_to_spot30",
}
EXTRA_DESCRIBE = "venue:onchain_perp_share30"
# ① 面板(24 名,src/research/strategies/causal_positioning.py:222 DEFAULT_UNIVERSE),去掉 BTC / ETH ⇒ 22 名山寨
PANEL_24 = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
            "DOT", "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
            "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]
ALTS = [s for s in PANEL_24 if s not in ("BTC", "ETH")]
ALT_MIN_COVERAGE = 0.80           # 等权时至少 80% 的山寨两端都有价,否则该日记为缺失
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t264_results.json")
CACHE = os.environ.get("T264_CACHE", "/tmp/t264_cache")

PAGE = 1000


# ── 读库(只读;分页一律带 order=;每页 ≤ 1000) ────────────────────────────────

def _conn() -> tuple[str, dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY —— 退出")
    return url, {"apikey": key, "Authorization": "Bearer " + key}


def raw_get(path: str, params: str) -> tuple[list[dict], dict]:
    url, h = _conn()
    req = urllib_request(f"{url}/rest/v1/{path}?{params}", h)
    with req as resp:
        body = json.load(resp)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return body, hdrs


def urllib_request(url: str, headers: dict):
    import urllib.request
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180)


def fetch(table: str, query: str, order_col: str, extra: str = "") -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        params = f"select={query}&order={order_col}&limit={PAGE}&offset={off}"
        if extra:
            params += "&" + extra
        chunk, _ = raw_get(table, params)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        off += PAGE
    return rows


def cached(name: str, loader: Callable[[], list[dict]]) -> list[dict]:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return json.load(open(path))
    data = loader()
    json.dump(data, open(path, "w"))
    return data


def load_venue_table() -> list[dict]:
    return cached("exchange_volume_daily.json",
                  lambda: fetch("exchange_volume_daily", "d,exchange,kind,volume_btc", "d.asc"))


def load_fmd() -> list[dict]:
    return cached("fmd.json", lambda: fetch("feature_matrix_daily", "d,f", "d.asc"))


def load_perp_btc() -> list[dict]:
    return cached("perp_btc.json",
                  lambda: fetch("perp_bv_daily", "d,o,h,l,c", "d.asc", "symbol=eq.BTC"))


def load_ohlcv(symbols: list[str]) -> list[dict]:
    """① 面板的现货收盘。`ohlcv_daily` 同一个 symbol 有多个 source(例如 BTC 7806 行 ≈ 2 个来源 × 4100 天),
    这里只取 core_cap 的 PRICE_SOURCE(binance_hist),同日去重(留最后一条)。"""
    rows: list[dict] = []
    for s in symbols:
        rows.extend(cached(f"ohlcv_{s}.json",
                           lambda s=s: fetch("ohlcv_daily", "symbol,trade_date,close", "trade_date.asc",
                                             f"symbol=eq.{s}&source=eq.binance_hist")))
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[(r.get("symbol"), str(r.get("trade_date"))[:10])] = r
    return sorted(seen.values(), key=lambda r: (str(r.get("symbol")), str(r.get("trade_date"))))


# ── 统计小工具(秩相关、秩回归残差、分位、循环平移) ─────────────────────────────

def rankdata(a: np.ndarray) -> np.ndarray:
    """平均秩(并列取均值)。NaN 位置保持 NaN。"""
    out = np.full(a.shape, np.nan)
    ok = np.isfinite(a)
    if ok.sum() == 0:
        return out
    v = a[ok]
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(v.size)
    sv = v[order]
    i = 0
    while i < v.size:
        j = i
        while j + 1 < v.size and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    out[ok] = ranks
    return out


def pearson(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 5:
        return None
    xs, ys = x[ok], y[ok]
    sx, sy = xs.std(), ys.std()
    if sx <= 0 or sy <= 0:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


def spearman(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    return pearson(rankdata(x), rankdata(y))


def rank_resid(y: np.ndarray, ctrl: np.ndarray) -> np.ndarray:
    """秩回归残差:rank(y) 对 rank(ctrl) 做 OLS,返回残差(NaN 处 NaN)。"""
    ry, rc = rankdata(y), rankdata(ctrl)
    ok = np.isfinite(ry) & np.isfinite(rc)
    res = np.full(y.shape, np.nan)
    if ok.sum() < 10:
        return res
    X = np.column_stack([np.ones(ok.sum()), rc[ok]])
    beta, *_ = np.linalg.lstsq(X, ry[ok], rcond=None)
    res[ok] = ry[ok] - X @ beta
    return res


def trailing_percentile(series: np.ndarray, window: int) -> np.ndarray:
    """过去 window 天(含当天,只用 ≤ d)里的分位(0..1);历史不足 ⇒ NaN。"""
    n = series.size
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - window + 1)
        w = series[lo:i + 1]
        w = w[np.isfinite(w)]
        if w.size < max(30, window // 4):
            continue
        v = series[i]
        if not np.isfinite(v):
            continue
        out[i] = float((w < v).sum() + 0.5 * (w == v).sum()) / w.size
    return out


def trailing_mean(series: np.ndarray, window: int) -> np.ndarray:
    n = series.size
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - window + 1)
        w = series[lo:i + 1]
        w = w[np.isfinite(w)]
        if w.size < max(30, window // 4):
            continue
        out[i] = float(w.mean())
    return out


def bh_qvalues(pvals: list[Optional[float]], q: float) -> list[Optional[float]]:
    """Benjamini–Hochberg 调整后的 q 值(NaN 保持 NaN)。"""
    idx = [i for i, p in enumerate(pvals) if p is not None and math.isfinite(p)]
    m = len(idx)
    out: list[Optional[float]] = [None] * len(pvals)
    if m == 0:
        return out
    order = sorted(idx, key=lambda i: pvals[i])
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        val = min(prev, pvals[i] * m / rank)
        out[i] = val
        prev = val
    return out


# ── 阶段 0:前提检查(卡 acceptance ①) ─────────────────────────────────────────

def daterange(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def premise(venue_rows: list[dict], fmd: list[dict]) -> dict:
    """四个场所自 2021-03-01 起的逐日覆盖率 + 视图里 venue:* 键的覆盖。"""
    rep: dict[str, Any] = {"start": START, "venues_required": VENUES_REQUIRED}

    # (a) 原始表
    per: dict[str, set] = defaultdict(set)
    kinds: dict[str, set] = defaultdict(set)
    for r in venue_rows:
        ex, d = r.get("exchange"), r.get("d")
        if ex and d:
            per[ex].add(str(d)[:10])
            kinds[ex].add(r.get("kind"))
    all_days = sorted({str(r["d"])[:10] for r in venue_rows if r.get("d")})
    rep["table_rows"] = len(venue_rows)
    rep["table_date_range"] = [all_days[0], all_days[-1]] if all_days else None
    rep["table_exchanges"] = sorted(per)
    rep["table_kinds"] = {k: sorted(x for x in v if x) for k, v in sorted(kinds.items())}
    last = all_days[-1] if all_days else None
    cov: dict[str, Any] = {}
    if last:
        expect = (date.fromisoformat(last) - date.fromisoformat(START)).days + 1
        rep["expected_days"] = expect
        rep["last_day"] = last
        for v in VENUES_REQUIRED:
            got = per.get(v, set())
            miss = [d for d in daterange(START, last) if d not in got]
            cov[v] = {"days_present": len(got), "expected": expect,
                      "coverage": round(len(got) / expect, 6),
                      "missing_days": len(miss),
                      "missing_examples": miss[:5]}
        rep["venue_coverage"] = cov
        rep["all_required_ok"] = all(cov[v]["coverage"] >= 0.95 for v in VENUES_REQUIRED)
    else:
        rep["venue_coverage"] = {}
        rep["all_required_ok"] = False
        rep["why_empty"] = "exchange_volume_daily 读出来 0 行(表空,或该 key 无 SELECT 权限)"

    # (b) 视图里的 venue:* 键
    vkeys: dict[str, int] = defaultdict(int)
    has_venue = 0
    for r in fmd:
        f = r.get("f") or {}
        for k in f:
            if k.startswith("venue:"):
                vkeys[k] += 1
        if (r.get("has") or {}).get("venue"):
            has_venue += 1
    rep["fmd_rows"] = len(fmd)
    rep["fmd_range"] = [fmd[0]["d"], fmd[-1]["d"]] if fmd else None
    rep["fmd_venue_keys"] = dict(sorted(vkeys.items()))
    rep["fmd_has_venue_true"] = has_venue
    needed = {v: vkeys.get(k, 0) for k, v in FEATURE_KEYS.items()}
    rep["fmd_feature_counts"] = needed
    rep["features_available"] = all(c > 0 for c in needed.values())
    return rep


def derive_features_from_raw(venue_rows: list[dict]) -> dict[str, dict[str, float]]:
    """视图没有 venue:* 键时的**退化**路径:从原始表自己算(口径写在报告里,算偏离)。

    coinbase_share_spot30(d) = 近 30 天 gdax/coinbase 现货量 ÷ 全部现货量
    korea_share_spot30(d)     = 近 30 天 upbit+bithumb 现货量 ÷ 全部现货量
    deriv_to_spot30(d)        = 近 30 天全部衍生品量 ÷ 全部现货量
    """
    day: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in venue_rows:
        d, ex, kind = r.get("d"), r.get("exchange"), (r.get("kind") or "spot")
        v = r.get("volume_btc")
        if not d or not ex or v is None:
            continue
        day[str(d)[:10]][f"{ex}|{kind}"] += float(v)
    days = sorted(day)
    out = {"venue:coinbase_share_spot30": {}, "venue:korea_share_spot30": {}, "venue:deriv_to_spot30": {}}
    for i, d in enumerate(days):
        lo = max(0, i - 29)
        win = [day[x] for x in days[lo:i + 1]]
        spot = {k: sum(w.get(k, 0.0) for w in win) for k in {kk for w in win for kk in w}}
        spot_total = sum(v for k, v in spot.items() if k.endswith("|spot"))
        deriv_total = sum(v for k, v in spot.items() if not k.endswith("|spot"))
        cb = sum(v for k, v in spot.items() if k.split("|")[0] in COINBASE and k.endswith("|spot"))
        kr = sum(v for k, v in spot.items() if k.split("|")[0] in KOREA and k.endswith("|spot"))
        if spot_total > 0:
            out["venue:coinbase_share_spot30"][d] = cb / spot_total
            out["venue:korea_share_spot30"][d] = kr / spot_total
            out["venue:deriv_to_spot30"][d] = deriv_total / spot_total
    return out


def feature_series_from_view(fmd: list[dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {k: {} for k in list(FEATURE_KEYS.values()) + [EXTRA_DESCRIBE]}
    for r in fmd:
        f = r.get("f") or {}
        d = str(r.get("d"))[:10]
        for k in out:
            v = f.get(k)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                out[k][d] = float(v)
    return out


# ── 阶段 1:特征与结果 ─────────────────────────────────────────────────────────

def build_outcomes(perp: list[dict], ohlcv: list[dict]) -> dict[str, Any]:
    dates = [str(r["d"])[:10] for r in perp]
    close = {d: float(r["c"]) for d, r in zip(dates, perp) if r.get("c")}
    dts = sorted(close)
    px = np.array([close[d] for d in dts])

    # BTC 永续 d → d+30 对数收益(精确日期)
    idx = {d: i for i, d in enumerate(dts)}
    ret30: dict[str, float] = {}
    mdd30: dict[str, float] = {}
    ret7: dict[str, float] = {}
    mdd7: dict[str, float] = {}
    for d, i in idx.items():
        for h, rmap, mmap in ((H30, ret30, mdd30), (H7, ret7, mdd7)):
            j = i + h
            if j >= len(dts):
                continue
            rmap[d] = float(math.log(px[j] / px[i]))
            mmap[d] = float(px[i + 1:j + 1].min() / px[i] - 1.0)   # 入场后最深回撤(负数)

    # 山寨等权(① 面板除 BTC/ETH)减 BTC 的 30 天对数超额
    series: dict[str, dict[str, float]] = defaultdict(dict)
    for r in ohlcv:
        s, d, c = r.get("symbol"), str(r.get("trade_date"))[:10], r.get("close")
        if s and d and c is not None:
            series[s][d] = float(c)
    alt_exc30: dict[str, float] = {}
    alt_exc7: dict[str, float] = {}
    exc_cov: dict[str, tuple[int, int]] = {}
    btc_px = series.get("BTC", {})
    for d in sorted(set().union(*[set(series[s]) for s in ALTS if series.get(s)]) or []):
        for h, out_map in ((H30, alt_exc30), (H7, alt_exc7)):
            d2 = (date.fromisoformat(d) + timedelta(days=h)).isoformat()
            rets, nb = [], 0
            for s in ALTS:
                ps = series.get(s, {})
                if d in ps and d2 in ps and ps[d] > 0 and ps[d2] > 0:
                    rets.append(math.log(ps[d2] / ps[d]))
                    nb += 1
            if nb == 0 or d not in btc_px or d2 not in btc_px or btc_px[d] <= 0 or btc_px[d2] <= 0:
                continue
            if nb < ALT_MIN_COVERAGE * len(ALTS):
                continue
            ew = float(np.mean(rets))
            btc_ret = math.log(btc_px[d2] / btc_px[d])
            out_map[d] = ew - btc_ret
            if h == H30:
                exc_cov[d] = (nb, len(ALTS))
    return {"btc_ret30": ret30, "btc_ret7": ret7, "btc_mdd30": mdd30, "btc_mdd7": mdd7,
            "alt_exc30": alt_exc30, "alt_exc7": alt_exc7, "exc_cov": exc_cov,
            "perp_dates": dts, "btc_spot_dates": sorted(btc_px)}


# ── 阶段 2:检验 ───────────────────────────────────────────────────────────────

def segment_ics(dates: np.ndarray, feat: np.ndarray, out: np.ndarray) -> dict[str, Optional[float]]:
    res = {}
    for label, mask in (("seg1_2021-03_to_2023-06", (dates >= START) & (dates <= SEG1_END)),
                        ("seg2_2023-07_on", dates >= SEG2_START)):
        ic = spearman(feat[mask], out[mask])
        res[label] = None if ic is None else round(ic, 4)
    return res


def run_test(code: str, feat_name: str, feat: np.ndarray, dates: np.ndarray, outcome: np.ndarray,
             ctrl: np.ndarray, expect: str) -> dict[str, Any]:
    """一条检验:(a) IC 与符号、(b) 循环平移零分布分位、(c) 两段、(d) 控制 BTC 过去 30 天收益。"""
    ic = spearman(feat, outcome)
    out: dict[str, Any] = {"code": code, "feature": feat_name, "expect": expect,
                            "n_obs": int(np.isfinite(feat).sum()), "ic": None if ic is None else round(ic, 4)}
    if ic is None:
        out["verdict"] = "不可算(样本不足)"
        return out

    # (b) 零分布:特征序列整体循环平移(平移量 ≥ 60 天),1,000 次,种子 742
    n = feat.size
    valid = np.isfinite(feat)
    n_valid_shift = n - 2 * MIN_SHIFT
    if n_valid_shift <= 0:
        out["null"] = "不可算(序列太短)"
        out["verdict"] = "不可算"
        return out

    def one(rng: np.random.Generator) -> float:
        s = int(rng.integers(MIN_SHIFT, n_valid_shift + MIN_SHIFT))
        rot = np.roll(feat, s)
        v = spearman(rot[valid], outcome[valid])
        return float(v) if v is not None else float("nan")

    try:
        null = null_distribution(one, N_NULL, SEED, actual=ic)
        null = null[np.isfinite(null)]
    except NoOpNull as e:
        out["null_error"] = str(e)
        out["verdict"] = "零分布无效"
        return out

    if expect == "+":
        pct = percentile_of(ic, null)
        p = None if pct is None else 1.0 - pct
    elif expect == "-":
        pct = percentile_of(ic, null)
        p = None if pct is None else pct
        pct = None if pct is None else 1.0 - pct
    else:  # 方向未预注册 ⇒ 双侧(按量级)
        pct = percentile_of(abs(ic), np.abs(null))
        p = None if pct is None else 1.0 - pct

    out["null_pct_in_expected_direction"] = None if pct is None else round(pct, 4)
    out["p_one_sided"] = None if p is None else round(p, 5)
    out["null_abs_q95"] = round(float(np.quantile(np.abs(null), 0.95)), 4)

    # (c) 两段
    segs = segment_ics(dates, feat, outcome)
    out["segments"] = segs

    # (d) 控制 BTC 过去 30 天收益(秩回归残差)
    res = rank_resid(outcome, ctrl)
    ic_d = pearson(rankdata(feat), res)
    out["ic_resid"] = None if ic_d is None else round(ic_d, 4)

    # 判据
    same_sign = (expect == "+" and ic > 0) or (expect == "-" and ic < 0) or (expect == "0" and True)
    checks = {
        "a_ic_sign_and_size": bool(same_sign and abs(ic) >= IC_MIN),
        "b_null_pct": bool(pct is not None and pct >= PCT_MIN),
        "c_both_segments_same_sign": bool(
            segs["seg1_2021-03_to_2023-06"] is not None and segs["seg2_2023-07_on"] is not None
            and ((expect == "+" and segs["seg1_2021-03_to_2023-06"] > 0 and segs["seg2_2023-07_on"] > 0)
                 or (expect == "-" and segs["seg1_2021-03_to_2023-06"] < 0 and segs["seg2_2023-07_on"] < 0)
                 or (expect == "0" and np.sign(segs["seg1_2021-03_to_2023-06"]) == np.sign(segs["seg2_2023-07_on"])))),
        "d_resid_same_sign": bool(
            ic_d is not None and ((expect == "+" and ic_d > 0) or (expect == "-" and ic_d < 0)
                                   or (expect == "0" and np.sign(ic_d) == np.sign(ic)))),
    }
    out["checks"] = checks
    out["verdict_pre_bh"] = "PASS" if all(checks.values()) else "FAIL"
    out["p_for_bh"] = out["p_one_sided"]
    return out


# ── 自测(不碰市场数据:证明机器是通的,包括「没有信号时不乱拒」) ───────────────

def selftest() -> int:
    """两条人造序列:① 注入关系 ⇒ 判据应当通过;② 纯噪声 ⇒ 判据应当不通过。

    为什么必须做:10-14 那天的教训是「打乱是空操作 ⇒ 零分布 = 实际值 ⇒ 所有检验都过」。
    只跑「有信号」这一条证明不了机器没坏,必须同时跑「无信号」这一条。
    """
    rng = np.random.default_rng(20261106)
    n = 1740
    dates = np.array([(date(2021, 3, 1) + timedelta(days=i)).isoformat() for i in range(n)])
    ctrl = rng.normal(size=n)

    f_sig = rng.normal(size=n).cumsum()
    f_sig = (f_sig - f_sig.mean()) / f_sig.std()
    o_sig = 0.35 * f_sig + rng.normal(size=n)
    r_sig = run_test("SELF-signal", "F1", f_sig, dates, o_sig, ctrl, "+")

    f_noise = rng.normal(size=n)
    o_noise = rng.normal(size=n)
    r_noise = run_test("SELF-noise", "F1", f_noise, dates, o_noise, ctrl, "+")

    qs = bh_qvalues([r_sig.get("p_for_bh"), r_noise.get("p_for_bh")], BH_Q)
    for r, q in zip((r_sig, r_noise), qs):
        r["bh_q"] = None if q is None else round(q, 5)
        r["verdict"] = "PASS" if r.get("verdict_pre_bh") == "PASS" and q is not None and q <= BH_Q else "FAIL"

    ok_sig = r_sig["verdict"] == "PASS"
    ok_noise = r_noise["verdict"] == "FAIL"
    print("=== 自测 ===")
    print(f"  注入信号 : IC={r_sig['ic']} 分位={r_sig.get('null_pct_in_expected_direction')} "
          f"BH q={r_sig['bh_q']} ⇒ {r_sig['verdict']}  (期望 PASS: {ok_sig})")
    print(f"  纯噪声   : IC={r_noise['ic']} 分位={r_noise.get('null_pct_in_expected_direction')} "
          f"BH q={r_noise['bh_q']} ⇒ {r_noise['verdict']}  (期望 FAIL: {ok_noise})")
    print("  自测结论:", "✅ 机器通(既能发现信号,也不会对噪声乱拒)" if (ok_sig and ok_noise)
          else "❌ 机器有问题(先修机器,再谈数据)")
    json.dump({"selftest": {"signal": r_sig, "noise": r_noise, "ok": bool(ok_sig and ok_noise)}},
              open(OUT.replace("t264_results.json", "t264_selftest.json"), "w"),
              ensure_ascii=False, indent=2)
    return 0 if (ok_sig and ok_noise) else 1


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    stage = "all"
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]
    if "--selftest" in sys.argv:
        return selftest()

    venue_rows = load_venue_table()
    fmd = load_fmd()
    prem = premise(venue_rows, fmd)
    print("=== 阶段 0:前提 ===")
    print(json.dumps(prem, ensure_ascii=False, indent=2)[:4000])

    results: dict[str, Any] = {
        "card": "T-264", "ledger": "S-742", "seed": SEED, "n_null": N_NULL,
        "min_shift": MIN_SHIFT, "bh_q": BH_Q, "sample_start": START,
        "premise": prem, "ran": False,
    }

    if stage == "premise":
        results["status"] = "PREMISE_ONLY"
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
        return 0

    if not (prem.get("all_required_ok") and prem.get("features_available")):
        results["status"] = "STOPPED_PRECONDITION"
        results["stop_reason"] = ("exchange_volume_daily 四个场所自 2021-03-01 起的逐日覆盖不足 95%"
                                  if not prem.get("all_required_ok")
                                  else "feature_matrix_daily 里没有 venue:* 键")
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
        print(f"\n⛔ 前提不成立 ⇒ 不跑检验。已写 {OUT}")
        return 2

    # 特征
    fseries = feature_series_from_view(fmd)
    if not prem.get("features_available"):
        fseries = derive_features_from_raw(venue_rows)
        results["feature_source"] = "derived_from_raw(偏离:视图无 venue:* 键,自己按原始表算)"
    else:
        results["feature_source"] = "feature_matrix_daily.f['venue:*']"

    # 结果
    perp = load_perp_btc()
    ohlcv = load_ohlcv(list(PANEL_24))
    outs = build_outcomes(perp, ohlcv)
    results["outcome_coverage"] = {
        "btc_ret30_days": len(outs["btc_ret30"]), "btc_mdd30_days": len(outs["btc_mdd30"]),
        "alt_exc30_days": len(outs["alt_exc30"]), "btc_perp_range": [outs["perp_dates"][0], outs["perp_dates"][-1]],
        "alt_names_min_coverage": ALT_MIN_COVERAGE,
        "alt_exc_coverage_min": min([v[0] / v[1] for v in outs["exc_cov"].values()] or [0]),
    }

    # 对齐:共同日期轴(特征起点 → 末日−30)
    last_feature_day = max((d for k, s in fseries.items() if k in FEATURE_KEYS.values() for d in s), default=None)
    all_dates = sorted({d for k in FEATURE_KEYS.values() for d in fseries.get(k, {})})
    if not all_dates:
        results["status"] = "NO_FEATURES"
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
        return 2
    dates = np.array(all_dates)
    idx = {d: i for i, d in enumerate(all_dates)}

    def align(series: dict[str, float], horizon_days: int) -> np.ndarray:
        arr = np.full(len(all_dates), np.nan)
        for i, d in enumerate(all_dates):
            if d in series:
                arr[i] = series[d]
        return arr

    # 特征:F1 减过去 180 天均值;F2 / F3 过去 365 天分位
    raw_f = {k: align(fseries.get(k, {}), 0) for k in FEATURE_KEYS.values()}
    F = {
        "F1": raw_f[FEATURE_KEYS["F1"]] - trailing_mean(raw_f[FEATURE_KEYS["F1"]], 180),
        "F2": trailing_percentile(raw_f[FEATURE_KEYS["F2"]], 365),
        "F3": trailing_percentile(raw_f[FEATURE_KEYS["F3"]], 365),
    }
    # 结果向量(按同一日期轴)
    def outcome_vec(mapping: dict[str, float]) -> np.ndarray:
        arr = np.full(len(all_dates), np.nan)
        for i, d in enumerate(all_dates):
            v = mapping.get(d)
            if v is not None:
                arr[i] = v
        return arr

    o_ret30 = outcome_vec(outs["btc_ret30"])
    o_mdd30 = outcome_vec(outs["btc_mdd30"])
    o_exc30 = outcome_vec(outs["alt_exc30"])
    o_ret7 = outcome_vec(outs["btc_ret7"])
    o_exc7 = outcome_vec(outs["alt_exc7"])
    # 控制:BTC 过去 30 天收益(永续收盘,只用 ≤ d)
    ctrl = np.full(len(all_dates), np.nan)
    dts = outs["perp_dates"]
    close = {}
    for r in perp:
        close[str(r["d"])[:10]] = float(r["c"])
    for i, d in enumerate(all_dates):
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        d0 = (dd - timedelta(days=30)).isoformat()
        prev = [x for x in dts if x <= d0]
        if not prev or d not in close:
            continue
        p0 = close[prev[-1]]
        if p0 > 0:
            ctrl[i] = math.log(close[d] / p0)

    tests = [
        ("T1", "F1", F["F1"], o_ret30, "+", "F1 → BTC 永续 30 天对数收益(预期正)"),
        ("T2", "F2", F["F2"], o_ret30, "-", "F2 → BTC 永续 30 天对数收益(预期负)"),
        ("T3", "F2", F["F2"], o_exc30, "-", "F2 → 山寨等权减 BTC 的 30 天对数超额(预期负)"),
        ("T4", "F3", F["F3"], o_mdd30, "-", "F3 → BTC 30 天最大回撤(预期更深=更负)"),
        ("T5", "F3", F["F3"], o_ret30, "0", "F3 → BTC 永续 30 天对数收益(台账未写方向 ⇒ 双侧)"),
    ]
    results_list = []
    for code, fname, fvec, ovec, expect, desc in tests:
        r = run_test(code, fname, fvec, dates, ovec, ctrl, expect)
        r["description"] = desc
        results_list.append(r)
        print(f"  {code} {desc}: IC={r.get('ic')} pct={r.get('null_pct_in_expected_direction')} "
              f"segs={r.get('segments')} resid={r.get('ic_resid')} ⇒ {r.get('verdict_pre_bh')}")

    qs = bh_qvalues([r.get("p_for_bh") for r in results_list], BH_Q)
    for r, q in zip(results_list, qs):
        r["bh_q"] = None if q is None else round(q, 5)
        r["verdict"] = ("PASS" if r.get("verdict_pre_bh") == "PASS" and q is not None and q <= BH_Q
                        else "FAIL")
    results["tests"] = results_list
    results["ran"] = True
    results["status"] = "RAN"
    results["family_pass_count"] = sum(1 for r in results_list if r["verdict"] == "PASS")

    # 副项(只报不判):7 天
    subs = []
    for code, fname, fvec, ovec, desc in [
        ("S1", "F1", F["F1"], o_ret7, "F1 → BTC 7 天对数收益"),
        ("S2", "F2", F["F2"], o_ret7, "F2 → BTC 7 天对数收益"),
        ("S3", "F2", F["F2"], o_exc7, "F2 → 山寨 7 天超额"),
    ]:
        ic = spearman(fvec, ovec)
        subs.append({"code": code, "description": desc, "ic": None if ic is None else round(ic, 4),
                     "n_obs": int(np.isfinite(fvec).sum())})
    results["secondary_7d"] = subs

    # 副项:链上永续份额只描述走势
    if EXTRA_DESCRIBE in fseries and fseries[EXTRA_DESCRIBE]:
        s = fseries[EXTRA_DESCRIBE]
        ds = sorted(s)
        results["secondary_onchain_perp_share"] = {
            "n_days": len(ds), "first": ds[0], "last": ds[-1],
            "first_value": round(s[ds[0]], 6), "last_value": round(s[ds[-1]], 6),
            "note": "只描述走势,不测(台账:结构性趋势,没有周期)",
        }

    # 数据指纹
    h = hashlib.sha256()
    for k in sorted(FEATURE_KEYS.values()):
        for d in sorted(fseries.get(k, {})):
            h.update(f"{k}|{d}|{fseries[k][d]:.12g}\n".encode())
    for d in outs["perp_dates"]:
        h.update(f"perp|{d}|{close.get(d)}\n".encode())
    results["fingerprint"] = h.hexdigest()[:16]

    json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\n✅ 写 {OUT};通过 {results['family_pass_count']}/5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
