#!/usr/bin/env python3
"""T-233 — 「开闸」回测第二步:Binance 现货上币日事件源 + PIT 市场篮。

事件源 = ohlcv_daily(source=binance_hist) 每个加密符号的**首次出现日** d
(262 个;剔除 2017-08-17 的 BTC/ETH 行情起点 ⇒ 260 个事件)。

T-227 结论:events 表闸门没过(107 < 2000),且固定 25 名篮是**今天的**篮子,
2017–18 事件里只有 2–5 个成分有价 ⇒ 「高位」与「基准坏了」混在一起。
本卡换时点(PIT)市场等权篮重做,并补三个时代 / nb≥20 子集 / 公告前涨幅。

预注册全文见同目录 T-233_listing_event_v2.md 顶部。只读 SELECT:
不改代码、不做 DDL、不入库。零分布 / 盈亏只用 src/data/evaluation/apparatus.py。

用法: python3 docs/research/T-233_listing_event_v2.py [--refresh] [--diag]
"""
from __future__ import annotations

import argparse
import bisect
import collections
import importlib.util
import json
import os
import urllib.request
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CACHE = os.path.join(HERE, "t233_cache")
LEGACY = os.path.join(HERE, "t227_cache")          # T-227 留下的缓存,只读回退

# ── 零分布 / 盈亏:只用 apparatus.py(硬规则) ────────────────────────────────
_AP = os.path.join(REPO, "src", "data", "evaluation", "apparatus.py")
_spec = importlib.util.spec_from_file_location("cc_apparatus", _AP)
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)
long_return = apparatus.long_return
price_on_or_after = apparatus.price_on_or_after
null_distribution = apparatus.null_distribution
percentile_of = apparatus.percentile_of

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]

# ── 预注册常数 ────────────────────────────────────────────────────────────
CONTROL_N = 1000            # 随机日期对照抽样次数
CONTROL_SEED = 708          # 种子
ERA_MIN_N = 30              # 时代样本 < 30 ⇒ 只报不判
NB_MIN = 20                 # PIT 篮成分数下限(子集口径)
DROP_DAY = "2017-08-17"     # Binance 行情起点,不是上币日
DROP_SYMS = ("BTC", "ETH")
FWD = {"fwd30": (1, 30), "fwd30_shift_p1": (2, 31), "fwd30_shift_m1": (0, 29),
       "fwd90": (1, 90)}
PRE_SPAN = 30               # 公告前涨幅窗口
EARLY_DAYS = 365            # "上市后头一年"对照臂:把两侧的篮厚度拉平
ERAS = (("2017-2020", date(2017, 1, 1), date(2020, 12, 31)),
        ("2021-2022", date(2021, 1, 1), date(2022, 12, 31)),
        ("2023-2026", date(2023, 1, 1), date(2026, 12, 31)))


# ── 读库 ──────────────────────────────────────────────────────────────────
def _raw(path: str, extra: dict | None = None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode(), r.headers.get("Content-Range")


def _count(path: str) -> int:
    try:
        cr = _raw(path, {"Range": "0-0", "Prefer": "count=exact"})[1]
        return int(cr.split("/")[-1])
    except Exception:
        return -1


def _iter_rows(table: str, cols: str, where: str, order: str, page: int = 5000):
    """按 order 流式翻页。硬规则:翻页必须带 order=。
    服务端把请求行数截到自己的 max-rows,所以推进量按**实际返回行数**算。"""
    lo = 0
    got = 0
    prev_tail = None
    while True:
        q = f"{table}?select={cols}&" + (f"{where}&" if where else "") + f"order={order}"
        body, _ = _raw(q, {"Range": f"{lo}-{lo + page - 1}"})
        chunk = json.loads(body)
        if not chunk:
            return
        tail = json.dumps(chunk[-1], sort_keys=True)
        if tail == prev_tail:          # 没有推进(服务端忽略了 Range)—— 停
            return
        prev_tail = tail
        for r in chunk:
            yield r
        lo += len(chunk)
        got += len(chunk)
        if len(chunk) < page:
            body2, _ = _raw(q, {"Range": f"{lo}-{lo + page - 1}"})
            if not json.loads(body2):
                return


def _cache_file(name: str) -> str | None:
    """t233_cache 优先;回退到 T-227 的缓存(只读,不留副本)。"""
    for d in (CACHE, LEGACY):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _cached_rows(name: str, table: str, cols: str, where: str, order: str,
                 refresh: bool = False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not refresh and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    rows = list(_iter_rows(table, cols, where, order))
    with open(path, "w") as fh:
        json.dump(rows, fh)
    return rows


def fetch_binance_hist(refresh=False):
    """source=binance_hist 全量:既是价格源,也是「上币日」来源。"""
    rows = _cached_rows("binance_hist_rows.json", "ohlcv_daily",
                        "symbol,trade_date,close,asset_class",
                        "source=eq.binance_hist", "symbol.asc,trade_date.asc",
                        refresh=refresh)
    series, cls = {}, {}
    for r in rows:
        s = r["symbol"]
        series.setdefault(s, []).append((r["trade_date"], r["close"]))
        cls.setdefault(s, r.get("asset_class"))
    out = {}
    for s, lst in series.items():
        lst.sort()
        out[s] = {"source": "binance_hist", "asset_class": cls.get(s),
                  "dates": [x[0] for x in lst], "closes": [x[1] for x in lst]}
    return out


def fetch_coingecko(refresh=False):
    """source=coingecko_pro_ohlc:公告前涨幅用(每股历史窗口有限,单独一路)。"""
    rows = _cached_rows("ohlcv_coingecko_pro_ohlc.json", "ohlcv_daily",
                        "symbol,trade_date,close", "source=eq.coingecko_pro_ohlc",
                        "symbol.asc,trade_date.asc", refresh=refresh)
    per = collections.defaultdict(dict)
    for r in rows:
        per[r["symbol"]][r["trade_date"]] = r["close"]
    out = {}
    for s, dd in per.items():
        ds = sorted(dd)
        out[s] = {"source": "coingecko_pro_ohlc", "asset_class": None,
                  "dates": ds, "closes": [dd[d] for d in ds]}
    return out


# ── 价格查表(语义 = apparatus.price_on_or_after) ─────────────────────────
def _clean(v):
    """只留正且有限的收盘;price_on_or_after 遇到无效收盘会往后找,等价于先剔除。"""
    out = []
    for c in v:
        try:
            f = float(c)
        except (TypeError, ValueError):
            continue
        if np.isfinite(f) and f > 0:
            out.append(f)
    return out


class Series:
    """单个符号的价格序列;price() 走 apparatus.price_on_or_after。"""

    def __init__(self, v):
        self.dates = []
        self.closes = []
        for d, c in zip(v["dates"], v["closes"]):
            cc = _clean([c])
            if cc:
                self.dates.append(d)
                self.closes.append(cc[0])

    def price(self, d):
        if not self.dates:
            return None
        i = bisect.bisect_left(self.dates, d)
        if i >= len(self.dates):
            return None
        return price_on_or_after(self.dates[i:i + 12], self.closes[i:i + 12], d, 3)


# ── PIT 加密市场等权篮 ───────────────────────────────────────────────────
class PitBasket:
    """成分 = 当时有价的全部加密符号(本口径取 binance_hist 的 Crypto 集,
    262 个;每个成分从自己的首次出现日才有价 ⇒ 篮天然是 PIT)。

    价格语义与 apparatus.price_on_or_after 完全一致:d 当天或之后 3 天内第一个有效收盘。
    网格 = 整个日历(不是交易日并集),保证任意日历日都能精确查价。
    """

    def __init__(self, series: dict):
        self.syms = sorted(s for s, v in series.items()
                           if v.get("asset_class") == "Crypto")
        self.ser = {s: Series(series[s]) for s in self.syms}
        self.col = {s: j for j, s in enumerate(self.syms)}
        firsts = [self.ser[s].dates[0] for s in self.syms if self.ser[s].dates]
        lasts = [self.ser[s].dates[-1] for s in self.syms if self.ser[s].dates]
        self.g0 = date.fromisoformat(min(firsts))
        self.g1 = date.fromisoformat(max(lasts)) + timedelta(days=200)
        ndays = (self.g1 - self.g0).days + 1
        self.grid = [(self.g0 + timedelta(days=i)).isoformat() for i in range(ndays)]
        grid64 = np.array(self.grid, dtype="datetime64[D]")
        F = np.full((ndays, len(self.syms)), np.nan)
        for s in self.syms:
            ds = self.ser[s].dates
            if not ds:
                continue
            j = self.col[s]
            ds64 = np.array(ds, dtype="datetime64[D]")
            i = np.searchsorted(ds64, grid64, side="left")
            valid = i < len(ds)
            idx = np.clip(i, 0, len(ds) - 1)
            # gap = 网格日之后多少天才等到这个符号的下一个收盘(必须 ≤ 3 天,
            # 与 apparatus.price_on_or_after 的 max_gap_days 同义)。
            # ⚠️ 11-04 初版这里把减法写反(grid - ds ⇒ 恒 ≤ 0 ⇒ 全部通过),
            # 结果每个符号在它上市之前的每一天都被塞进了"下一个价",
            # 篮成分恒为 262。mandated selfcheck 抓到后修正;见 §0.9。
            gap = (ds64[idx] - grid64).astype("timedelta64[D]").astype(int)
            ok = valid & (gap <= 3)
            F[ok, j] = np.array(self.ser[s].closes, dtype=float)[idx[ok]]
        self.F = F

    def _row(self, d):
        i = (date.fromisoformat(d) - self.g0).days
        return i if 0 <= i < len(self.grid) else None

    def prices(self, d):
        i = self._row(d)
        return None if i is None else self.F[i]

    def ret(self, d0, d1):
        """等权买入持有收益 + 成分数(nb)。成分 = 两个时点都有价的名字。"""
        i0, i1 = self._row(d0), self._row(d1)
        if i0 is None or i1 is None:
            return None, 0
        a, b = self.F[i0], self.F[i1]
        with np.errstate(divide="ignore", invalid="ignore"):
            r = b / a - 1.0
        ok = np.isfinite(r) & np.isfinite(a) & np.isfinite(b) & (a > 0)
        if not ok.any():
            return None, 0
        return float(np.mean(r[ok])), int(ok.sum())

    def ret_apparatus(self, d0, d1):
        """逐名用 apparatus.long_return 重算(自检用,慢)。"""
        rs = []
        for s in self.syms:
            ser = self.ser[s]
            a = ser.price(d0)
            b = ser.price(d1)
            if a is None or b is None:
                continue
            r = long_return(a, b)
            if r is not None:
                rs.append(r)
        if not rs:
            return None, 0
        return float(np.mean(rs)), len(rs)

    def selfcheck(self, n=200, seed=17):
        """向量化口径 vs 逐名 apparatus.long_return:逐位比较。"""
        rng = np.random.default_rng(seed)
        per_name_diffs, basket_diffs, nb_seen = [], [], []
        for _ in range(n):
            s = self.syms[int(rng.integers(0, len(self.syms)))]
            ser = self.ser[s]
            if len(ser.dates) < 40:
                continue
            i = int(rng.integers(0, len(ser.dates) - 35))
            j = int(rng.integers(i + 2, min(i + 35, len(ser.dates))))
            d0, d1 = ser.dates[i], ser.dates[j]
            a_app, b_app = ser.price(d0), ser.price(d1)
            if a_app is None or b_app is None:
                continue
            r_app = long_return(a_app, b_app)
            j0, j1 = self._row(d0), self._row(d1)
            a_vec, b_vec = self.F[j0, self.col[s]], self.F[j1, self.col[s]]
            r_vec = long_return(a_vec, b_vec)
            if r_app is None or r_vec is None:
                continue
            per_name_diffs.append(abs(r_app - r_vec))
            v, nb = self.ret(d0, d1)
            a2, nb2 = self.ret_apparatus(d0, d1)
            if v is not None and a2 is not None:
                basket_diffs.append(abs(v - a2))
                nb_seen.append((nb, nb2))
        return {
            "n_windows": len(per_name_diffs),
            "max_abs_diff_per_name": max(per_name_diffs) if per_name_diffs else None,
            "max_abs_diff_basket_mean": max(basket_diffs) if basket_diffs else None,
            "nb_mismatch_count": sum(1 for a, b in nb_seen if a != b),
            "nb_median": int(np.median([a for a, _ in nb_seen])) if nb_seen else None,
        }


# ── 事件集 ────────────────────────────────────────────────────────────────
def build_events(series):
    """每个加密符号在 binance_hist 的首次出现日 = 它的 Binance 上币日代理。"""
    evs = []
    for s in sorted(series):
        v = series[s]
        if v.get("asset_class") != "Crypto" or not v["dates"]:
            continue
        evs.append({"symbol": s, "d": v["dates"][0], "n_hist": len(v["dates"])})
    evs.sort(key=lambda e: (e["d"], e["symbol"]))
    kept = [e for e in evs
            if not (e["d"] == DROP_DAY and e["symbol"] in DROP_SYMS)]
    return evs, kept


def windows(series, basket, evs):
    """每个事件的四组窗口 + PIT 篮。"""
    out = []
    for e in evs:
        d0 = date.fromisoformat(e["d"])
        row = dict(e)
        for tag, (off_in, off_out) in FWD.items():
            dd0 = (d0 + timedelta(days=off_in)).isoformat()
            dd1 = (d0 + timedelta(days=off_out)).isoformat()
            ser = series.get(e["symbol"])
            a = ser.price(dd0) if ser else None
            b = ser.price(dd1) if ser else None
            absr = long_return(a, b) if (a is not None and b is not None) else None
            bench, nb = basket.ret(dd0, dd1)
            row[tag] = absr
            row[tag + "_bench"] = bench
            row[tag + "_nb"] = nb
            row[tag + "_rel"] = None if (absr is None or bench is None) else absr - bench
        out.append(row)
    return out


# ── 随机日期对照(同一符号、随机 d;1,000 次;种子 708) ───────────────────
def control(series, basket, evs, tag="fwd30", span=29, min_nb=0,
            n=CONTROL_N, seed=CONTROL_SEED, exclude_event_window=False,
            mode="free", abs_only=False):
    """每次抽样:每个事件在同一符号的序列里随机取起点 d,算同口径相对收益,取中位数。

    span = 出口日 − 入口日(与事件的 d+1→d+30 同为 29 天,口径一致)。
    min_nb: 控制里篮成分数也要 ≥ 该值(否则与被检验的子集不同口径)。
    exclude_event_window: 排除落在事件窗口内的抽样(稳健性对照,非预注册主口径)。
    mode="early": 起点只在该符号**上市后的头 EARLY_DAYS 个交易日**里抽
        —— 事件窗口的篮很薄(2017–19 只有 2–20 个成分),而自由抽样的起点多半很晚
        (篮 200+ 个成分),两侧篮厚度不同 = 口径不对等。这条把两侧拉到同一厚度。
    abs_only: 统计量只用绝对收益(不减篮)⇒ 完全绕开基准厚薄的问题。
    """
    ev_days = {e["symbol"]: date.fromisoformat(e["d"]) for e in evs}

    def _one(rng):
        vals = []
        for e in evs:
            ser = series.get(e["symbol"])
            if ser is None or len(ser.dates) < 5:
                continue
            hi = len(ser.dates) if mode == "free" else min(len(ser.dates), EARLY_DAYS)
            if hi < 2:
                continue
            i = int(rng.integers(0, hi))
            dd0 = ser.dates[i]
            dd1 = (date.fromisoformat(dd0) + timedelta(days=span)).isoformat()
            if exclude_event_window:
                ed = ev_days.get(e["symbol"])
                if ed is not None and abs((date.fromisoformat(dd0) - ed).days) <= span + 1:
                    continue
            a = ser.price(dd0)
            b = ser.price(dd1)
            if a is None or b is None:
                continue
            absr = long_return(a, b)
            if absr is None:
                continue
            if abs_only:
                vals.append(absr)
                continue
            bench, nb = basket.ret(dd0, dd1)
            if bench is None:
                continue
            if min_nb and nb < min_nb:
                continue
            vals.append(absr - bench)
        if not vals:
            return float("nan")
        return float(np.median(vals))

    null = null_distribution(_one, n, seed)
    return null


# ── 汇总 ──────────────────────────────────────────────────────────────────
def summarize(rows, tag):
    vals = [r[tag + "_rel"] for r in rows if r.get(tag + "_rel") is not None]
    absv = [r[tag] for r in rows if r.get(tag + "_rel") is not None]
    nbs = [r[tag + "_nb"] for r in rows if r.get(tag + "_rel") is not None]
    if not vals:
        return {"n": 0, "median_rel_pct": None, "median_abs_pct": None,
                "mean_rel_pct": None, "win_rate_rel": None, "nb_median": None,
                "nb_min": None, "nb_max": None}
    return {
        "n": len(vals),
        "median_rel_pct": round(100 * float(np.median(vals)), 3),
        "median_abs_pct": round(100 * float(np.median(absv)), 3),
        "mean_rel_pct": round(100 * float(np.mean(vals)), 3),
        "win_rate_rel": round(float(np.mean([v > 0 for v in vals])), 3),
        "nb_median": int(np.median(nbs)), "nb_min": int(np.min(nbs)), "nb_max": int(np.max(nbs)),
    }


def judge(rows, tag, series, basket, min_nb=0, label=""):
    """主口径:中位数 < 0 且在随机日期对照里 ≤ 5 分位 ⇒ ✅「开闸是高位」。"""
    have = [r for r in rows if r.get(tag + "_rel") is not None]
    s = summarize(rows, tag)
    out = {"label": label, **s}
    if not have:
        out["verdict"] = "NO_DATA"
        return out
    med = float(np.median([r[tag + "_rel"] for r in have]))
    out["median_rel_pct_exact"] = med
    span = (FWD[tag][1] - FWD[tag][0]) if tag in FWD else 29
    try:
        null = control(series, basket, have, tag=tag, span=span, min_nb=min_nb)
        pct = percentile_of(med, null)
        out["control_percentile"] = pct
        out["control_n"] = int(len(null))
        out["control_median_pct"] = round(100 * float(np.median(null)), 3)
        out["control_p05_pct"] = round(100 * float(np.percentile(null, 5)), 3)
        out["verdict"] = ("CONFIRMED" if (med < 0 and pct is not None and pct <= 0.05)
                          else "NOT_CONFIRMED")
    except apparatus.NoOpNull as exc:
        out["control_error"] = str(exc)
        out["verdict"] = "NO_DATA" if med is None else "REPORT_ONLY"
    return out


def era_splits(rows, series, basket, tag="fwd30"):
    out = {}
    for name, lo, hi in ERAS:
        sub = [r for r in rows if r.get(tag + "_rel") is not None
               and lo <= date.fromisoformat(r["d"]) <= hi]
        s = summarize(sub, tag)
        entry = {"n": s["n"], "median_rel_pct": s["median_rel_pct"],
                 "median_abs_pct": s["median_abs_pct"], "nb_median": s["nb_median"]}
        if s["n"] == 0:
            entry["verdict"] = "NO_DATA"
        elif s["n"] < ERA_MIN_N:
            entry["verdict"] = "REPORT_ONLY_SAMPLE_TOO_SMALL"
            entry["note"] = f"n < {ERA_MIN_N} ⇒ 只报不判"
        else:
            j = judge(sub, tag, series, basket, label=name)
            entry.update({k: j[k] for k in
                          ("control_percentile", "control_n", "control_median_pct",
                           "control_p05_pct", "verdict") if k in j})
        out[name] = entry
    return out


# ── 公告前涨幅(公告前 d−30 → d) ──────────────────────────────────────────
def pre_runup(events, cg: dict):
    """用 coingecko_pro_ohlc 算 d−30 → d 的涨幅(同一源两端,不跨源拼接)。
    CoinGecko 每股历史窗口有限 ⇒ 只有近一年上币的标的够用,n 单独报。"""
    out = []
    for e in events:
        ser = cg.get(e["symbol"])
        if ser is None or not ser.dates:
            continue
        d0 = date.fromisoformat(e["d"])
        dd0 = (d0 - timedelta(days=PRE_SPAN)).isoformat()
        a = ser.price(dd0)
        b = ser.price(e["d"])
        if a is None or b is None:
            continue
        out.append({"symbol": e["symbol"], "d": e["d"], "pre30": long_return(a, b),
                    "cg_first": ser.dates[0], "cg_last": ser.dates[-1]})
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--diag", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "T-233_results.json"))
    args = ap.parse_args()

    gate_total = _count("events?select=id&source=eq.binance&kind=eq.listing")
    print(f"[gate] events(source=binance,kind=listing) = {gate_total} (T-227 闸门需 ≥2000 ⇒ 仍未过)")

    series_raw = fetch_binance_hist(args.refresh)
    crypto_syms = sorted(s for s, v in series_raw.items()
                          if v.get("asset_class") == "Crypto")
    print(f"[prices] binance_hist symbols: {len(series_raw)} "
          f"(crypto {len(crypto_syms)})")

    series = {s: Series(v) for s, v in series_raw.items()}
    evs_all, events = build_events(series_raw)
    dropped = [e for e in evs_all if e not in events]
    print(f"[events] crypto symbols {len(evs_all)} → 事件 {len(events)} "
          f"(剔除 {[(e['symbol'], e['d']) for e in dropped]})")
    by_year = dict(sorted(collections.Counter(e["d"][:4] for e in events).items()))
    print("[events] by year:", by_year)

    basket = PitBasket(series_raw)
    sc = basket.selfcheck()
    print("[mkt] PIT 篮成分", len(basket.syms), "selfcheck:", sc)

    rows = windows(series, basket, events)
    results = {
        "prereg": {"control_n": CONTROL_N, "control_seed": CONTROL_SEED,
                   "era_min_n": ERA_MIN_N, "nb_min": NB_MIN,
                   "dropped": [{"symbol": e["symbol"], "d": e["d"]} for e in dropped],
                   "windows": {k: {"entry_offset_days": v[0], "exit_offset_days": v[1]}
                               for k, v in FWD.items()}},
        "gate": {"events_binance_listing_rows": gate_total},
        "events": {"n_symbols_crypto": len(evs_all), "n_events": len(events),
                   "by_year": by_year},
        "basket": {"n_components": len(basket.syms),
                   "grid_start": basket.grid[0], "grid_end": basket.grid[-1],
                   "selfcheck": sc},
        "arms": {},
    }

    # 主口径 + 挪一天(S-665)+ 副口径
    for tag in ("fwd30", "fwd30_shift_p1", "fwd30_shift_m1", "fwd90"):
        span = FWD[tag][1] - FWD[tag][0]
        j = judge(rows, tag, series, basket, label=tag)
        results["arms"][tag] = j
        print(f"[{tag}] n={j['n']} median_rel={j.get('median_rel_pct')}% "
              f"nb_med={j.get('nb_median')} pct={j.get('control_percentile')} "
              f"verdict={j.get('verdict')}")

    # 稳健性对照:排除落在事件窗口内的抽样(非预注册主口径,单独报)
    have = [r for r in rows if r.get("fwd30_rel") is not None]
    if have:
        med = float(np.median([r["fwd30_rel"] for r in have]))
        try:
            null = control(series, basket, have, tag="fwd30", exclude_event_window=True)
            results["arms"]["fwd30_control_excl_event_window"] = {
                "control_percentile": percentile_of(med, null),
                "control_n": int(len(null)),
                "control_median_pct": round(100 * float(np.median(null)), 3),
                "note": "稳健性对照(非预注册主口径):抽样排除落在事件窗口内",
            }
            print("[fwd30 excl-window] pct=",
                  results["arms"]["fwd30_control_excl_event_window"]["control_percentile"])
        except apparatus.NoOpNull as exc:
            results["arms"]["fwd30_control_excl_event_window"] = {"control_error": str(exc)}

    # 诊断臂(不是预注册主口径,单独报):
    #  A) 绝对收益对照:统计量不用篮 ⇒ 绕开「事件窗篮薄 / 对照篮厚」的口径不对等。
    #  B) 起点只抽在上市后头一年:两侧篮厚度拉平。
    for label, kw, stat_key, stat_vals in (
        ("fwd30_abs_control", dict(abs_only=True), "abs",
         [r["fwd30"] for r in have if r.get("fwd30") is not None]),
        ("fwd30_early_control", dict(mode="early"), "rel",
         [r["fwd30_rel"] for r in have if r.get("fwd30_rel") is not None]),
    ):
        if not stat_vals:
            continue
        med = float(np.median(stat_vals))
        try:
            null = control(series, basket, have, tag="fwd30", **kw)
            results["arms"][label] = {
                "actual_median_pct": round(100 * med, 3),
                "control_percentile": percentile_of(med, null),
                "control_n": int(len(null)),
                "control_median_pct": round(100 * float(np.median(null)), 3),
                "statistic": stat_key,
                "note": ("诊断臂(非预注册主口径):"
                         + ("统计量=绝对收益,不含篮" if stat_key == "abs"
                            else "随机起点只抽在上市后头 365 个交易日,两侧篮厚度拉平")),
            }
            print(f"[{label}] median={round(100*med,3)}% "
                  f"pct={results['arms'][label]['control_percentile']}")
        except apparatus.NoOpNull as exc:
            results["arms"][label] = {"control_error": str(exc)}

    # nb≥20 子集
    sub20 = [r for r in rows if r.get("fwd30_rel") is not None and r["fwd30_nb"] >= NB_MIN]
    j20 = judge(sub20, "fwd30", series, basket, min_nb=NB_MIN, label="nb>=20")
    results["arms"]["fwd30_nb_ge_20"] = j20
    print(f"[fwd30 nb>=20] n={j20['n']} median_rel={j20.get('median_rel_pct')}% "
          f"pct={j20.get('control_percentile')} verdict={j20.get('verdict')}")

    # 三个时代
    results["eras_fwd30"] = era_splits(rows, series, basket, "fwd30")
    for name, e in results["eras_fwd30"].items():
        print(f"[era {name}] n={e['n']} median_rel={e.get('median_rel_pct')}% "
              f"pct={e.get('control_percentile')} verdict={e.get('verdict')}")

    # 公告前涨幅
    cg_raw = fetch_coingecko(args.refresh)
    cg = {s: Series(v) for s, v in cg_raw.items()}
    pre = pre_runup(events, cg)
    if pre:
        vals = [p["pre30"] for p in pre]
        results["pre_runup"] = {
            "n": len(vals),
            "median_pct": round(100 * float(np.median(vals)), 3),
            "mean_pct": round(100 * float(np.mean(vals)), 3),
            "win_rate_pos": round(float(np.mean([v > 0 for v in vals])), 3),
            "cg_symbols_total": len(cg),
            "cg_date_min": min(p["cg_first"] for p in pre),
            "cg_date_max": max(p["cg_last"] for p in pre),
            "events_listed": sorted({p["d"][:7] for p in pre}),
            "detail": pre,
        }
        print(f"[pre30] n={len(vals)} median={results['pre_runup']['median_pct']}% "
              f"win_pos={results['pre_runup']['win_rate_pos']}")
    else:
        results["pre_runup"] = {"n": 0}

    if args.diag:
        for r in rows[:12]:
            print("   ", r["d"], r["symbol"], "abs30=", r.get("fwd30"),
                  "bench=", r.get("fwd30_bench"), "nb=", r.get("fwd30_nb"),
                  "rel=", r.get("fwd30_rel"))

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False, default=str)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
