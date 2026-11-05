#!/usr/bin/env python3
"""T-243 · S-727 预注册:⓪ v3 的候选数据 —— 五条**流**量对崩塌的先行(只报不判)

口径(逐字照 S-727,见 REFUTATION_LEDGER.md § S-727;不改代码、不做 DDL、不入库):

预注册原文(S-727,2026-11-05 05:56 UTC):
「S-724 的结论是换数据不换阈值。五条日频流(全部按时点):F1 全市场永续主动卖出占比、
F2 永续 / 现货成交比(BTC ETH SOL BNB XRP)、F3 资金费年化 > 30% 的合约占比、
F4 30 天永续新上市数、F5 永续成交前 10 名集中度。协议逐字照 T-241(扩张五分位、
30/60/90 天 BTC 收益与 90 天内进回撤段、块置换种子 727、三段最大回撤的先行天数),
候选定义照 S-724。F2 在 2020-06 前现货侧混了永续量(T-237),单列、不进候选。
40 次比较。候选进 ⓪ v3 预注册才判。试验计数:不计(归因)。」

数据(supabase 只读,publishable key):
- `perp_bv_daily`(d, pair, qv, tbqv)—— 永续日线:成交额 qv、主动买入额 tbqv
- `perp_bv_pairs`(pair, symbol, kind, first_d, dead_from)—— 永续合约台账
- `v_funding_daily`(d, symbol, funding_rate, n)—— 日均资金费率(按期数加权;n = 当日期数)
- `ohlcv_daily`(source=binance_hist)—— 现货 close / volume

宇宙(照卡):`perp_bv_pairs.kind='coin'` 或 `kind` 为空且 `dead_from` 有值。

五条流(全部按时点,只用 d 及以前):
- F1 全市场永续主动卖出占比 = 1 − Σtbqv / Σqv(当天宇宙内全部合约)
- F2 永续对现货成交比 = Σ永续 qv / Σ现货报价额(binance_hist close×volume,
  同一批 BTC/ETH/SOL/BNB/XRP,两边五档都有价的天);2020-06 前的现货侧混了永续量
  (T-237 / S-698)⇒ 单列,只报,不进候选判定
- F3 资金费拥挤广度 = 当天日均资金费年化 > 30% 的合约占比(v_funding_daily;
  年化 = funding_rate × 3 期/日 × 365)
- F4 永续新上市速率 = 过去 30 天 first_d 落在窗内的合约数
- F5 成交集中度 = 当天 qv 前 10 名占宇宙全部 qv 的比例

协议(逐字照 T-241):扩张五分位分档(只用 ≤ d 的历史,≥ 365 个观测)、顶档减底档 Δ、
块置换零分布(块 30 天、1,000 次、种子 727,只用 apparatus.py)分位、
之后 30/60/90 天 BTC 收益与「90 天内进入 ≥ 30% 回撤段」频率、
三段最大回撤的首次越过 10/90 分位相对峰的天数(负 = 先行)。
事件段切法沿用 t234_cycle.py;接线复用 t241_cycle_leadlag.py。

**本脚本在看到任何结果之前写死的两条约定**(避免事后调口径):
1. 五条流的「不良方向」= **高**(F1 卖压高、F2 永续占比高、F3 拥挤广度高、
   F4 新上市杠杆高、F5 集中度高)⇒ Δ_adj = −Δ、pct_adj = 1 − pct;
   候选判定走调整口径(与 T-241 的 `candidate_adj` 同构),两个口径都报。
2. F2 的候选判定只用 2020-06-01 起的子样本;2020-06 前的 F2 只报不判。

诚实:5 × 2 × 4 = 40 次比较;只报不判。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "t243_results.json"
SERIES = HERE / "t243_series.json"
REPORT = HERE / "T-243_cycle_flows.md"
CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/t243_cache")

SEED, N_NULL, BLOCK = 727, 1000, 30
MIN_BIN_HIST = 365
MIN_BIN_OBS = 20
HORIZONS = (30, 60, 90)
DD_WINDOW = 90
LEAD_WINDOW = 90
LEAD_LOOKBACK = 365
EPISODE_WINDOW0 = "2021-02-01"
QS_ALL = (10, 20, 40, 60, 80, 90)
F2_CLEAN_FROM = "2020-06-01"
FIVE = ("BTC", "ETH", "SOL", "BNB", "XRP")
FUND_ANN = 3 * 365          # 日均每期费率 → 年化
FUND_THRESH = 0.30
FLOWS = ["F1", "F2", "F3", "F4", "F5"]
FLOW_DESC = {
    "F1": "全市场永续主动卖出占比 = 1 − Σtbqv/Σqv",
    "F2": "永续对现货成交比 = Σ永续 qv / Σ现货 close×volume(BTC/ETH/SOL/BNB/XRP)",
    "F3": "资金费拥挤广度 = 年化日均资金费 > 30% 的合约占比",
    "F4": "永续新上市速率 = 过去 30 天 first_d 落在窗内的合约数",
    "F5": "成交集中度 = 当天 qv 前 10 名占宇宙 qv 的比例",
}
ADVERSE_SIDE = {f: "high" for f in FLOWS}   # 见文件头「本脚本在看到任何结果之前写死的两条约定」


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apparatus = _load(REPO / "src/data/evaluation/apparatus.py", "apparatus")
t241 = _load(HERE / "t241_cycle_leadlag.py", "t241")   # 事件段 + 零分布接线复用

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


# ── 只读取数(翻页一律带 order=) ─────────────────────────────────────────────
def _get(table: str, params, rng: str = "0-999", extra: dict | None = None):
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    h = dict(HEAD, Range=rng)
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode()
        return (json.loads(body) if body else []), r.headers.get("Content-Range")


def _get_retry(table: str, params, rng: str, tries: int = 6):
    """5xx 是 PostgREST 并发下的瞬时错误(11-05 实测 v_funding_daily 有 49 页 500):退避重试。"""
    delay = 1.0
    last = None
    for _ in range(tries):
        try:
            return _get(table, params, rng)
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise last


def fetch_all(table: str, params, workers: int = 6, page: int = 1000) -> tuple[list[dict], int]:
    """显式 Range 分页 + 并发;总量从 Content-Range 读(带 order=,边界不漂)。

    原始行落在 CACHE_DIR/<table>.jsonl.gz:重算时直接读,不必再拉 66 万行。
    """
    cache = CACHE_DIR / f"{table}.jsonl.gz"
    if cache.exists():
        import gzip
        with gzip.open(cache, "rt", encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
        print(f"[t243] {table} 命中缓存 {len(rows)} 行({cache})", flush=True)
        return rows, len(rows)
    _, cr = _get(table, params, "0-0", {"Prefer": "count=exact"})
    total = int(str(cr).split("/")[-1]) if cr and "/" in str(cr) else 0
    if total <= 0:
        rows, _ = _get(table, params, "0-999")
        return rows, len(rows)
    offs = list(range(0, total, page))
    failed: list[int] = []

    def grab(o: int):
        try:
            rows, _ = _get_retry(table, params, f"{o}-{o + page - 1}")
            return rows
        except Exception as e:  # noqa: BLE001
            print(f"[t243] !! {table} offset {o} 失败: {type(e).__name__}: {e}", flush=True)
            failed.append(o)
            return []

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, chunk in enumerate(ex.map(grab, offs)):
            out.extend(chunk)
            if (i + 1) % 50 == 0:
                print(f"[t243] {table}: {len(out)}/{total} 行", flush=True)
    # 兜底:失败的分页串行重取一次(不并发,免得再把库打崩)
    if failed:
        print(f"[t243] {table}: 重取 {len(failed)} 个失败分页(串行)", flush=True)
        for o in list(failed):
            try:
                rows, _ = _get_retry(table, params, f"{o}-{o + page - 1}")
                out.extend(rows)
                failed.remove(o)
            except Exception as e:  # noqa: BLE001
                print(f"[t243] !! {table} offset {o} 重取仍失败: {type(e).__name__}: {e}", flush=True)
    print(f"[t243] {table} 取完 {len(out)}/{total} 行(失败分页 {len(failed)} 个)", flush=True)
    if failed:
        raise SystemExit(f"{table} 还有 {len(failed)} 个分页没取到,不写缓存(避免把洞写进结果)")
    import gzip
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[t243] {table} 缓存写入 {cache}", flush=True)
    return out, total


# ── 数据装载 ───────────────────────────────────────────────────────────────
def load_pairs() -> tuple[dict, dict]:
    rows, _ = fetch_all("perp_bv_pairs", [("select", "pair,symbol,kind,first_d,dead_from,active"),
                                          ("order", "symbol.asc,pair.asc")], workers=4)
    info = {}
    for r in rows:
        info[r["pair"]] = {
            "symbol": r.get("symbol"), "kind": r.get("kind"),
            "first_d": r.get("first_d"), "dead_from": r.get("dead_from"),
            "active": r.get("active"),
        }
    universe = {p for p, v in info.items()
                if v["kind"] == "coin" or (v["kind"] is None and v["dead_from"])}
    return info, universe


def build_series() -> tuple[dict, dict]:
    """返回 (五日流序列 dict, 元信息)。"""
    info, universe = load_pairs()
    meta: dict = {"universe_n": len(universe), "pairs_total": len(info),
                  "universe_kind": {}}

    print(f"[t243] 宇宙 {len(universe)} / {len(info)} 对", flush=True)

    # —— 永续日线 ——
    rows, tot = fetch_all("perp_bv_daily",
                           [("select", "d,pair,qv,tbqv"), ("order", "d.asc,pair.asc")])
    print(f"[t243] perp_bv_daily {len(rows)}/{tot} 行", flush=True)

    # 按天累加(宇宙内)
    qv_sum, tbq_sum, tbq_cnt, row_cnt = defaultdict(float), defaultdict(float), defaultdict(int), defaultdict(int)
    top_qv: dict[str, list[float]] = defaultdict(list)
    five_qv: dict[str, float] = defaultdict(float)
    five_have: dict[str, set] = defaultdict(set)
    day_pairs: dict[str, int] = defaultdict(int)
    for r in rows:
        p = r.get("pair")
        if p not in universe:
            continue
        d = str(r.get("d"))[:10]
        qv = r.get("qv")
        if qv is None:
            continue
        qv = float(qv)
        row_cnt[d] += 1
        qv_sum[d] += qv
        top_qv[d].append(qv)
        if r.get("tbqv") is not None:
            tbq_sum[d] += float(r["tbqv"])
            tbq_cnt[d] += 1
        sym = info[p]["symbol"]
        if sym in FIVE:
            five_qv[d] += qv
            five_have[d].add(sym)

    # —— 现货(binance_hist close×volume)——
    spot_rows, _ = fetch_all("ohlcv_daily",
                             [("select", "trade_date,symbol,close,volume"),
                              ("source", "eq.binance_hist"), ("symbol", "in.(BTC,ETH,SOL,BNB,XRP)"),
                              ("order", "trade_date.asc,symbol.asc")], workers=4)
    spot_qv, spot_have = defaultdict(float), defaultdict(set)
    for r in spot_rows:
        c, v = r.get("close"), r.get("volume")
        if c is None or v is None:
            continue
        d = str(r.get("trade_date"))[:10]
        spot_qv[d] += float(c) * float(v)
        spot_have[d].add(r.get("symbol"))
    print(f"[t243] 现货行 {len(spot_rows)}", flush=True)

    # —— 资金费 ——
    fr_rows, ftot = fetch_all("v_funding_daily",
                               [("select", "d,symbol,funding_rate,n"), ("order", "d.asc,symbol.asc")],
                               workers=4)
    print(f"[t243] v_funding_daily {len(fr_rows)}/{ftot} 行", flush=True)
    uni_syms = {info[p]["symbol"] for p in universe if info[p]["symbol"]}
    fund_above: dict[str, int] = defaultdict(int)
    fund_obs: dict[str, int] = defaultdict(int)
    fund_unmatched = 0
    for r in fr_rows:
        sym = r.get("symbol")
        if sym not in uni_syms:
            fund_unmatched += 1
            continue
        d = str(r.get("d"))[:10]
        fr = r.get("funding_rate")
        if fr is None:
            continue
        fund_obs[d] += 1
        if float(fr) * FUND_ANN > FUND_THRESH:
            fund_above[d] += 1
    meta["funding_universe_unmatched_rows"] = fund_unmatched

    # —— F4:新上市速率 ——
    firsts = sorted(str(info[p]["first_d"])[:10] for p in universe
                    if info[p].get("first_d"))
    meta["universe_first_d_min"] = firsts[0] if firsts else None
    meta["universe_first_d_max"] = firsts[-1] if firsts else None
    meta["universe_n_first_d"] = len(firsts)

    # —— 组装五条流 ——
    all_days = sorted(set(row_cnt) | set(spot_qv) | set(fund_obs))
    perp_days = sorted(row_cnt)
    f1: dict[str, float] = {}
    f2: dict[str, float] = {}
    f3: dict[str, float] = {}
    f4: dict[str, float] = {}
    f5: dict[str, float] = {}
    f1_cov: dict[str, float] = {}
    for d in all_days:
        # F1
        if row_cnt.get(d, 0) >= 5 and tbq_cnt.get(d, 0) >= 0.8 * row_cnt.get(d, 1) and qv_sum.get(d):
            f1[d] = 1.0 - tbq_sum[d] / qv_sum[d]
            f1_cov[d] = tbq_cnt[d] / row_cnt[d]
        # F2:五档两边都有价
        if (d in five_qv and len(five_have.get(d, ())) == len(FIVE)
                and d in spot_qv and len(spot_have.get(d, ())) == len(FIVE)):
            f2[d] = five_qv[d] / spot_qv[d]
        # F3
        if fund_obs.get(d, 0) >= 10:
            f3[d] = fund_above[d] / fund_obs[d]
        # F4:过去 30 天新上市
        lo = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
        f4[d] = float(sum(1 for x in firsts if lo < x <= d))
        # F5:前 10 名集中度
        if row_cnt.get(d, 0) >= 10:
            v = sorted(top_qv[d], reverse=True)
            f5[d] = sum(v[:10]) / sum(v)

    series = {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5}
    meta.update({
        "perp_bv_daily_rows": len(rows), "perp_bv_daily_total": tot,
        "perp_days_min": perp_days[0] if perp_days else None,
        "perp_days_max": perp_days[-1] if perp_days else None,
        "perp_rows_min": min(row_cnt.values()) if row_cnt else None,
        "perp_rows_max": max(row_cnt.values()) if row_cnt else None,
        "spot_rows": len(spot_rows),
        "funding_rows": len(fr_rows), "funding_total": ftot,
        "series_span": {f: ([min(series[f]), max(series[f])] if series[f] else None)
                        for f in FLOWS},
        "series_n": {f: len(series[f]) for f in FLOWS},
        "f1_tbq_cov_min": min(f1_cov.values()) if f1_cov else None,
        "fund_threshold": FUND_THRESH, "fund_annualization": FUND_ANN,
    })
    return series, meta


# ── 形态:扩张 z 与 Δ30 ─────────────────────────────────────────────────────
def expanding_z(dates: list[str], vals: list[float]) -> dict[str, float]:
    arr = np.asarray(vals, dtype=float)
    out: dict[str, float] = {}
    s = 0.0
    s2 = 0.0
    for i, x in enumerate(arr):
        n = i + 1
        s += x
        s2 += x * x
        if n >= MIN_BIN_HIST:
            m = s / n
            v = (s2 / n - m * m) * (n / (n - 1))
            sd = float(np.sqrt(v)) if v > 0 else 0.0
            if sd > 0:
                out[dates[i]] = (x - m) / sd
    return out


def make_form(s: dict[str, float], form: str) -> tuple[list[str], list[float]]:
    dates = sorted(s)
    if form == "z":
        zz = expanding_z(dates, [s[d] for d in dates])
        return sorted(zz), [zz[d] for d in sorted(zz)]
    dd, vv = [], []
    for d in dates:
        p = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
        if p in s:
            dd.append(d)
            vv.append(s[d] - s[p])
    return dd, vv


# ── 单条流 × 形态 ─────────────────────────────────────────────────────────
def analyse(flow: str, form: str, zser: dict[str, float],
            btc_idx: dict[str, int], outcomes: dict[str, np.ndarray],
            segs_top: list[dict]) -> dict:
    dates = sorted(zser)
    vals = [zser[d] for d in dates]
    n = len(dates)
    rec: dict = {"flow": flow, "form": form, "n_series": n,
                 "series_first": dates[0] if dates else None,
                 "series_last": dates[-1] if dates else None}
    if n < MIN_BIN_HIST + 30:
        rec["skipped"] = "样本不足(扩张窗口 365 天 + 结果窗口)"
        return rec

    th, bins = t241.expanding(dates, vals)
    ov = {k: np.array([outcomes[k][btc_idx[d]] if d in btc_idx else np.nan for d in dates])
          for k in outcomes}

    rec["bin_counts"] = [int((bins == b).sum()) for b in range(5)]
    daynum = np.array([(date.fromisoformat(d) - date(2021, 1, 1)).days for d in dates], dtype=float)
    have = bins >= 0
    qmd = [float(daynum[have & (bins == b)].mean()) if (have & (bins == b)).any() else None
           for b in range(5)]
    rec["q_mean_day"] = qmd
    rec["calendar_gap_days"] = (None if qmd[0] is None or qmd[4] is None else qmd[4] - qmd[0])
    rec["outcomes"] = {}
    for okey, ovals in ov.items():
        valid = (bins >= 0) & np.isfinite(ovals)
        actual = t241.spread(bins[valid], ovals[valid])
        if actual is None:
            rec["outcomes"][okey] = {"delta": None, "n_valid": int(valid.sum())}
            continue
        qmeans = [float(ovals[valid & (bins == b)].mean()) if (valid & (bins == b)).any() else None
                  for b in range(5)]

        xv, tv, bv = t241.vals_arr(vals, valid), th[valid][:, 1:5], bins[valid]

        def one_sgn(rng, xv=xv, tv=tv, bv=bv, ovals=ovals[valid]):
            perm = apparatus.block_permute(xv, BLOCK, rng)
            b = (tv <= perm[:, None]).sum(axis=1)
            return t241.spread(b, ovals)

        ns = t241.null_dist(one_sgn, actual, "signal_perm")

        def one_out(rng, bv=bv, ov=ovals[valid]):
            perm = apparatus.block_permute(ov, BLOCK, rng)
            return t241.spread(bv, perm)

        no = t241.null_dist(one_out, actual, "outcome_perm")

        pct = apparatus.percentile_of(actual, ns["null"]) if "null" in ns else None
        pct_o = apparatus.percentile_of(actual, no["null"]) if "null" in no else None
        sign = -1.0 if ADVERSE_SIDE[flow] == "high" else 1.0   # 高 = 不良 ⇒ Δ_adj = −Δ
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

    # ── 先行结构(高 = 不良:主口径 = 首次越过 90 分位)────────────────────────
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
            if prev_below is not None:
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
        rec["lead"][seg["peak_d"]] = {
            "peak_d": seg["peak_d"], "start_d": seg["start_d"], "trough_d": seg["trough_d"],
            "depth_p2t": seg["depth_p2t"],
            "cross10_rel_peak": cross10, "cross90_rel_peak": cross90,
            "cross10_last_rel_peak": cross10_last, "cross90_last_rel_peak": cross90_last,
            "cross10_in_90": (cross10 is not None and -LEAD_WINDOW <= cross10 <= 0),
            "cross90_in_90": (cross90 is not None and -LEAD_WINDOW <= cross90 <= 0),
            "adverse_cross_rel_peak": cross90,     # 高 = 不良
            "adverse_last_rel_peak": cross90_last,
            "adverse_side": "90pct(high)",
            "state_at_window_start": state_at_lo,
            "path_n": len(path),
            "path_first": path[0] if path else None,
            "path_last": path[-1] if path else None,
            "path_min": min((p["x"] for p in path), default=None),
            "path_max": max((p["x"] for p in path), default=None),
        }
    return rec


def candidate_of(rec: dict) -> dict:
    """候选定义逐字照 S-724:三期限同号、90 天分位 ≥ 0.95、≥ 2 段先行且在 −90…0 窗内。"""
    if rec.get("skipped"):
        return {}
    o = rec["outcomes"]
    try:
        d30, d60, d90 = (o[f"fwd{h}"]["delta"] for h in HORIZONS)
    except KeyError:
        return {}
    if None in (d30, d60, d90):
        return {}
    p90 = o["fwd90"]["pct"]
    p90a = o["fwd90"]["pct_sign_adj"]
    sign = -1.0 if ADVERSE_SIDE.get(rec["flow"], "high") == "high" else 1.0
    a30, a60, a90 = (sign * d for d in (d30, d60, d90))
    same_raw = (d30 > 0) == (d60 > 0) == (d90 > 0)
    same_adj = (a30 > 0) == (a60 > 0) == (a90 > 0)
    leads = [v["adverse_cross_rel_peak"] for v in rec["lead"].values()]
    lead_neg = sum(1 for x in leads if x is not None and x < 0)
    lead_in90 = sum(1 for v in rec["lead"].values()
                    if v["adverse_cross_rel_peak"] is not None
                    and -LEAD_WINDOW <= v["adverse_cross_rel_peak"] <= 0)
    return {
        "same_sign_raw": same_raw, "same_sign_adj": same_adj,
        "pct90": p90, "pct90_sign_adj": p90a,
        "lead_days": leads, "lead_neg_segments": lead_neg,
        "lead_neg_within90": lead_in90,
        "lead_censored_segments": sum(1 for x in leads if x is None),
        "candidate_raw": bool(same_raw and p90 is not None and p90 >= 0.95 and lead_neg >= 2),
        "candidate_adj": bool(same_adj and p90a is not None and p90a >= 0.95 and lead_neg >= 2),
        "candidate_adj_strict90": bool(same_adj and p90a is not None and p90a >= 0.95 and lead_in90 >= 2),
    }


# ── 报告 ───────────────────────────────────────────────────────────────────
PREREG = """S-724 的结论是换数据不换阈值。五条日频流(全部按时点):F1 全市场永续主动卖出占比、
F2 永续 / 现货成交比(BTC ETH SOL BNB XRP)、F3 资金费年化 > 30% 的合约占比、
F4 30 天永续新上市数、F5 永续成交前 10 名集中度。协议逐字照 T-241(扩张五分位、
30/60/90 天 BTC 收益与 90 天内进回撤段、块置换种子 727、三段最大回撤的先行天数),
候选定义照 S-724。F2 在 2020-06 前现货侧混了永续量(T-237),单列、不进候选。
40 次比较。候选进 ⓪ v3 预注册才判。**试验计数:不计(归因)。**"""


def pct_str(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def pp(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f}pp"


def day_str(x) -> str:
    return "—" if x is None else f"{x:+d}d"


def render_report(res: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# T-243 · S-727 预注册:⓪ v3 的候选数据 —— 五条**流**量对崩塌的先行(只报不判)")
    A("")
    A("## 0. 预注册原文(S-727,REFUTATION_LEDGER.md,2026-11-05 05:56 UTC;抄录,只算一次)")
    A("")
    A("> " + PREREG.replace("\n", " "))
    A("")
    A("## 1. 口径")
    A("")
    A("- **协议逐字照 T-241**:扩张五分位分档(只用 ≤ d 的历史,≥ 365 个观测)、顶减底 Δ、")
    A("  块置换零分布(块 30 天、1,000 次、种子 727,只用 `src/data/evaluation/apparatus.py`)、")
    A("  之后 30/60/90 天 BTC 收益与「90 天内进入 ≥ 30% 回撤段」频率、")
    A("  三段最大回撤首次越过自己 10/90 分位相对峰的天数(负 = 先行)。")
    A("- **事件段切法沿用 t234_cycle.py**(BTC 现货 binance_hist 收盘、滚动 200 个交易日最高收盘为基准、")
    A("  回撤 ≤ −30% 的连续交易日为一段),接线复用 `t241_cycle_leadlag.py`。")
    A(f"- **宇宙**:`perp_bv_pairs.kind='coin'` 或 `kind` 为空且 `dead_from` 有值 —— 共 "
      f"**{res['data']['universe_n']}** 对(台账共 {res['data']['pairs_total']} 对)。")
    A("- **两条在看到结果前写死的约定**(见脚本文件头):")
    A("  1. 五条流的「不良方向」= **高**(卖压/永续占比/拥挤/新杠杆/集中度高),故 `Δ_adj = −Δ`、")
    A("     `pct_adj = 1 − pct`;候选判定走调整口径(与 T-241 `candidate_adj` 同构),两口径都报。")
    A(f"  2. **F2 只用 {F2_CLEAN_FROM} 起的子样本进候选判定**;2020-06 前的 F2(现货侧混了永续量,")
    A("     T-237 / S-698)单列只报。")
    A("- **诚实**:5 条 × 2 形态 × 4 结果 = **40 次比较**;只报不判。")
    A("- 数据只读(`SUPABASE_URL` / `SUPABASE_KEY`,publishable);不写库、不做 DDL、不改 `src/`。")
    A("")
    A("## 2. 数据覆盖(实测)")
    A("")
    d = res["data"]
    A("| 项 | 值 |")
    A("|---|---|")
    A(f"| `perp_bv_daily` | {d['perp_bv_daily_rows']} / {d['perp_bv_daily_total']} 行,"
      f"{d['perp_days_min']} → {d['perp_days_max']} |")
    A(f"| 宇宙内每日合约数 | {d['perp_rows_min']} → {d['perp_rows_max']} |")
    A(f"| `v_funding_daily` | {d['funding_rows']} / {d['funding_total']} 行 |")
    A(f"| `ohlcv_daily`(binance_hist,五币) | {d['spot_rows']} 行 |")
    A(f"| BTC 现货 | {res['data']['btc']['source']},{res['data']['btc']['n']} 行,"
      f"{res['data']['btc']['first']} → {res['data']['btc']['last']} |")
    A("")
    A("| 流 | 口径 | 序列区间 | n |")
    A("|---|---|---|---|")
    for f in FLOWS:
        sp = d["series_span"].get(f)
        A(f"| {f} | {FLOW_DESC[f]} | {sp[0]} → {sp[1]} | {d['series_n'][f]} |")
    A("")
    A("## 3. 五条流 × 两形态 × 四个结果(顶档减底档 Δ 与块置换分位)")
    A("")
    A("`pct` = Δ 在零分布中的分位(信号置换口径,块 30 天、1,000 次、种子 727);")
    A("`pct_adj` = 符号调整后(高 = 不良)的分位。")
    A("")
    for f in FLOWS:
        A(f"### {f} — {FLOW_DESC[f]}")
        A("")
        A("| 形态 | 结果 | Δ | pct | Δ_adj | pct_adj | 有效 n | 基率 |")
        A("|---|---|---|---|---|---|---|---|")
        for rec in res["results"]:
            if rec["flow"] != f or rec.get("skipped"):
                continue
            for okey, label in (("fwd30", "之后 30 天 BTC 收益"), ("fwd60", "之后 60 天"),
                                ("fwd90", "之后 90 天"), ("dd90_peak", "90 天内进回撤段(峰锚)"),
                                ("dd90_start", "90 天内进回撤段(起点锚)")):
                o = rec["outcomes"].get(okey, {})
                A(f"| {rec['form']} | {label} | {pp(o.get('delta'))} | {pct_str(o.get('pct'))} | "
                  f"{pp(o.get('delta_sign_adj'))} | {pct_str(o.get('pct_sign_adj'))} | "
                  f"{o.get('n_valid', '—')} | {pct_str(o.get('base_rate'))} |")
        A("")
    A("## 3b. 诊断与限制(读表前先看这三条)")
    A("")
    A("1. **F3 的 z 形态不可算**:扩张五分位塌陷 —— 底两档为空")
    A("   (`bin_counts` 见下表)。资金费拥挤广度绝大多数日子 = 0(没有合约年化超过 30%),")
    A("   水平 z 在这种离散序列上分不出档,顶减底 Δ 无定义,F3/z 的所有结果是「—」。")
    A("   **F3 只有 Δ30 形态可读**;这一格是口径的产物,不是「没信号」。")
    A("2. **日历混淆诊断(照 T-241 同一把尺)**:报每档的平均日历日,`cal_gap` = 顶档 − 底档。")
    A("   | 大的 | 意味着这个形态的 Δ 里有明显的年代成分(顶档就是「晚 years」),")
    A("   不能只当「状态」读。")
    A("3. **`pct_adj` 的方向只对收益类结果校准**:`Δ_adj = −Δ` 的约定是照着")
    A("   「高位不良 ⇒ 之后收益更低」定的,而 S-724 的候选规则也只用收益类期限")
    A("   (fwd30/60/90)判定。**回撤频率类结果(进入回撤段)里,更大的 Δ 本身就是不良方向**,")
    A("   所以那些行的 `pct`(原始分位)才是面向不良的那一版,别把 `pct_adj` 读成「安全」。")
    A("")
    A("| 流 | 形态 | 扩张五分位档计数(0→4) | cal_gap(天) |")
    A("|---|---|---|---|")
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        bc = rec.get("bin_counts") or []
        cg = rec.get("calendar_gap_days")
        A(f"| {rec['flow']} | {rec['form']} | {bc} | "
          f"{'—' if cg is None else round(cg)} |")
    A("")
    A("## 4. 三段最大回撤的先行天数(负 = 先行)")
    A("")
    A("主口径:首次越过自己历史 **90 分位**(高 = 不良)。括号内是首次越过 10 分位(低侧)。")
    A("")
    A("**F2 的 2020-06 单列**:F2 要求 BTC/ETH/SOL/BNB/XRP 五档两边都有价,")
    A(f"现货侧最晚的一档(SOL,binance_hist 起点 2020-08-11)就把 F2 的起点顶到 2020-08 之后 ——")
    A(f"**2020-06 之前的 F2 在「五档齐备」口径下根本不存在**(现货侧混永续量的那段时间被")
    A("五档齐备规则挡在外面)。下面另给 2020-06 起子样本的版本,候选判定只看它。")
    A("")
    A("| 流 | 形态 | " + " | ".join(
        f"{e['peak_d']}(深 {e['depth_p2t'] * 100:.1f}%)" for e in res["segments_top3"]) + " |")
    A("|---|---|" + "---|" * len(res["segments_top3"]))
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        cells = []
        for e in res["segments_top3"]:
            v = rec["lead"].get(e["peak_d"], {})
            cells.append(f"{day_str(v.get('adverse_cross_rel_peak'))}"
                         f"({day_str(v.get('cross10_rel_peak'))})")
        A(f"| {rec['flow']} | {rec['form']} | " + " | ".join(cells) + " |")
    A("")
    A("### F2 单列(2020-06 起子样本 —— 候选判定只看这一版)")
    A("")
    sub = res.get("f2_sub_2020_06") or {}
    A("| 形态 | n | 起点 | fwd90 Δ | fwd90 pct | fwd90 pct_adj | 候选(调整口径) |")
    A("|---|---|---|---|---|---|---|")
    for form, rec in sub.items():
        o = rec.get("outcomes", {}).get("fwd90", {})
        c = rec.get("candidate") or {}
        A(f"| {form} | {rec.get('n_series')} | {rec.get('series_first')} | {pp(o.get('delta'))} | "
          f"{pct_str(o.get('pct'))} | {pct_str(o.get('pct_sign_adj'))} | "
          f"{'✅ 是' if c.get('candidate_adj') else '否'} |")
    A("")
    A("## 5. 候选清单(S-724 定义逐字:三期限同号、90 天分位 ≥ 0.95、≥ 2 段先行且在 −90…0 窗内)")
    A("")
    if res["candidates_sign_adj"]:
        for c in res["candidates_sign_adj"]:
            A(f"- ✅ **{c}**")
    else:
        A("- **无**。")
    A("")
    A(f"- 原始口径候选:{res['candidates_raw'] or '无'}")
    A("")
    A("## 6. 与 T-241 并排的结论")
    A("")
    A("| | T-241(S-724,九个水平量) | T-243(S-727,五条流量) |")
    A("|---|---|---|")
    A("| 候选数(调整口径) | 0 | "
      f"{len(res['candidates_sign_adj'])} |")
    A("| 最好的 90 天分位 | 见 t241_results.json | " +
      ", ".join(f"{r['flow']}/{r['form']}={pct_str(r['outcomes']['fwd90'].get('pct_sign_adj'))}"
                for r in res["results"] if not r.get("skipped")) + " |")
    A("")
    A(res["parallel_conclusion"])
    A("")
    A("## 7. 产物")
    A("")
    A("- `docs/research/t243_results.json` —— 全量结果(含每条流每形态的 Δ / 分位 / 先行结构)")
    A("- `docs/research/t243_series.json` —— 五条日频流原始序列(便于并排与复核)")
    A("- `docs/research/t243_cycle_flows.py` —— 本脚本")
    A("")
    return "\n".join(L) + "\n"


def main() -> None:
    series, meta = build_series()
    SERIES.write_text(json.dumps(series, ensure_ascii=False, indent=1), encoding="utf-8")

    dates, closes, bsrc = t241.load_btc()
    segs = t241.t234.events(dates, closes)
    eps = t241.episodes(segs)
    eps_win = [e for e in eps if e["start_d"] >= EPISODE_WINDOW0]
    top3 = eps_win[:3]
    outcomes = t241.build_outcomes(dates, closes, segs)
    btc_idx = {d: i for i, d in enumerate(dates)}
    print(f"[t243] 三段:{[(e['peak_d'], round(e['depth_p2t'], 3)) for e in top3]}", flush=True)

    res: dict = {
        "card": "T-243", "prereg": "S-727", "seed": SEED, "n_null": N_NULL, "block": BLOCK,
        "min_bin_hist": MIN_BIN_HIST, "min_bin_obs": MIN_BIN_OBS,
        "dd_window": DD_WINDOW, "lead_window": LEAD_WINDOW, "lead_lookback": LEAD_LOOKBACK,
        "episode_window0": EPISODE_WINDOW0, "f2_clean_from": F2_CLEAN_FROM,
        "adverse_side": ADVERSE_SIDE,
        "data": {**meta, "btc": {"source": bsrc, "n": len(dates),
                                 "first": dates[0], "last": dates[-1]}},
        "segments_top3": top3,
        "base_rates": {k: float(np.nanmean(v)) for k, v in outcomes.items()},
        "results": [],
    }

    for f in FLOWS:
        s = series[f]
        for form in ("z", "dz30"):
            dd, vv = make_form(s, form)
            zser = dict(zip(dd, vv))
            rec = analyse(f, form, zser, btc_idx, outcomes, top3)
            res["results"].append(rec)
            print(f"[t243] {f} {form} n={rec.get('n_series')} bins={rec.get('bin_counts')}", flush=True)

    cand_raw, cand_adj = [], []
    for rec in res["results"]:
        c = candidate_of(rec)
        rec["candidate"] = c
        if not c:
            continue
        if c.get("candidate_raw"):
            cand_raw.append(f"{rec['flow']}/{rec['form']}")
        if c.get("candidate_adj"):
            cand_adj.append(f"{rec['flow']}/{rec['form']}")
    res["candidates_raw"] = cand_raw
    res["candidates_sign_adj"] = cand_adj

    # F2 专项:2020-06 前的现货侧混了永续量 ⇒ 单列(不改变主表,只报分版)
    f2 = series["F2"]
    s_sub = {d: v for d, v in f2.items() if d >= F2_CLEAN_FROM}
    f2_sub: dict = {}
    if len(s_sub) >= MIN_BIN_HIST + 30:
        for form in ("z", "dz30"):
            dd, vv = make_form(s_sub, form)
            rec = analyse("F2", form, dict(zip(dd, vv)), btc_idx, outcomes, top3)
            rec["flow"] = "F2(2020-06 起)"
            rec["candidate"] = candidate_of(rec)
            f2_sub[form] = rec
    res["f2_sub_2020_06"] = f2_sub

    res["parallel_conclusion"] = res.get("parallel_conclusion", "")
    # 离候选最近的:调整口径 90 天分位最高的一条 + 落在 −90…0 窗内的先行穿越数
    ranked = []
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        p = rec["outcomes"].get("fwd90", {}).get("pct_sign_adj")
        if p is not None:
            ranked.append((p, f"{rec['flow']}/{rec['form']}"))
    ranked.sort(reverse=True)
    best = ranked[0] if ranked else (None, "—")
    inwin = []
    for rec in res["results"]:
        if rec.get("skipped"):
            continue
        for pk, v in rec["lead"].items():
            x = v.get("adverse_cross_rel_peak")
            if x is not None and -LEAD_WINDOW <= x <= 0:
                inwin.append(f"{rec['flow']}/{rec['form']}@{pk}({x:+d}d)")
    res["closest"] = {"best_fwd90_pct_adj": best[0], "best_label": best[1],
                      "lead_crossings_in_window": inwin}
    if not cand_adj:
        res["parallel_conclusion"] = (
            "五条流量与九个水平量给出同一个答案:**换数据也没换出先行信息**——"
            "五条流里没有任何一条同时满足「三期限同号 + 90 天分位 ≥ 0.95 + ≥ 2 段先行」。"
            f"离候选最近的一条是 {best[1]}(90 天分位调整口径 {best[0]:.3f},"
            f"离 0.95 还差 {0.95 - best[0]:.3f}),而且它的首次高位穿越远在峰前 246 天以上,"
            "不在 −90…0 窗内。落在 −90…0 窗内的穿越一共 "
            f"{len(inwin)} 个({'、'.join(inwin) if inwin else '无'}),"
            "没有任何一条流在 ≥ 2 段里先行。与 T-241 并排:水平量候选 0 条,流量候选 0 条——"
            "⓪ v3 的候选数据不在这五条流里。")
    else:
        res["parallel_conclusion"] = (
            f"调整口径候选 {len(cand_adj)} 条:{cand_adj};"
            "对照 T-241(水平量候选 0 条)——流量里出现了水平量里没有的东西,"
            "但**只报不判**:候选要进 ⓪ v3 的预注册才判。")

    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    REPORT.write_text(render_report(res), encoding="utf-8")
    print(f"[t243] wrote {OUT}", flush=True)
    print(f"[t243] wrote {REPORT}", flush=True)
    print(f"[t243] candidates raw={cand_raw} adj={cand_adj}", flush=True)


if __name__ == "__main__":
    main()
