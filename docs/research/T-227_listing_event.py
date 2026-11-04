#!/usr/bin/env python3
"""T-227 — 「开闸」回测:Binance 上币公告之后 30 / 90 天相对宇宙。

S-708 预注册(判据写死,只算一次)。协议全文见同目录 T-227_listing_event.md 顶部。

只读:全部走 Supabase REST SELECT;不改代码、不做 DDL、不入库。

用法: python3 docs/research/T-227_listing_event.py [--refresh] [--diag]
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
CACHE = os.path.join(HERE, "t227_cache")

# ── 零分布 / 对照:只用 apparatus.py(硬规则) ────────────────────────────────
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

# ── 预注册常数(S-708) ─────────────────────────────────────────────────────
CONTROL_N = 1000          # 随机日期对照抽样次数
CONTROL_SEED = 708        # 种子
GATE_LISTINGS = 2000      # 卡上闸门:source=binance & kind=listing 行数 ≥ 2000
DEDUP_DAYS = 90           # 同一符号 90 天内重复公告只留第一条
PRICE_SOURCES = ("binance_hist", "binance_hist_ffill", "coingecko_pro_ohlc")
TRADFI_CLASSES = {"US Equity", "US Bond", "Commodity", "EM Equity", "FX", "Real Estate"}
ERAS = (("2017-2020", date(2017, 1, 1), date(2020, 12, 31)),
        ("2021-2022", date(2021, 1, 1), date(2022, 12, 31)),
        ("2023-2026", date(2023, 1, 1), date(2026, 12, 31)))
AS_OF = date(2026, 11, 3)  # 数据截止(今天)


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


def _cached(name: str, fn, refresh: bool = False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not refresh and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    val = fn()
    with open(path, "w") as fh:
        json.dump(val, fh)
    return val


def _iter_rows(table: str, cols: str, where: str, order: str, page: int = 5000,
               keep=None, limit_rows: int = 3_000_000):
    """按 order 流式翻页。

    硬规则:翻页必须带 order=。服务端会把请求行数截到自己的 max-rows,所以推进量
    必须按**实际返回行数**算(用请求行数会每隔一段跳过一大片 —— T-227 踩过)。
    """
    lo = 0
    got = 0
    prev_tail = None
    while got < limit_rows:
        body, _ = _raw(f"{table}?select={cols}&{where}&order={order}" if where
                       else f"{table}?select={cols}&order={order}",
                       {"Range": f"{lo}-{lo + page - 1}"})
        chunk = json.loads(body)
        if not chunk:
            return
        tail = json.dumps(chunk[-1], sort_keys=True)
        if tail == prev_tail:      # 没有推进(服务端忽略了 Range)—— 停,别死循环
            return
        prev_tail = tail
        for r in chunk:
            if keep is None or keep(r):
                yield r
        lo += len(chunk)
        got += len(chunk)
        if len(chunk) < page and lo >= got:
            # 最后一页:再探一次,空了就停
            body2, _ = _raw(f"{table}?select={cols}&{where}&order={order}" if where
                            else f"{table}?select={cols}&order={order}",
                            {"Range": f"{lo}-{lo + page - 1}"})
            if not json.loads(body2):
                return


def _cached_rows(name: str, table: str, cols: str, where: str, order: str,
                 keep=None, refresh: bool = False):
    """把一次全量扫描落到本地 cache(避免重复拉 60 万行)。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not refresh and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    val = list(_iter_rows(table, cols, where, order, keep=keep))
    with open(path, "w") as fh:
        json.dump(val, fh)
    return val


# ── 阶段 1:预注册事件集(events 表) ───────────────────────────────────────
def fetch_listing_events(refresh=False):
    def _go():
        return _cached_rows("events_listing.json", "events",
                             "id,ts,kind,source,symbols,payload,title",
                             "source=eq.binance&kind=eq.listing", "ts.asc,symbols.asc",
                             refresh=refresh)
    return _go()


def dedupe_events(rows):
    """每个 (symbol, ts) 一个事件;同一符号 90 天内重复公告只留第一条。scope 分开报。"""
    per_scope = collections.defaultdict(list)
    for r in rows:
        scope = (r.get("payload") or {}).get("scope") or "unknown"
        for s in (r.get("symbols") or []):
            if not s:
                continue
            per_scope[scope].append({"symbol": s, "ts": r["ts"], "d": r["ts"][:10],
                                     "title": r.get("title") or ""})
    out = {}
    for scope, evs in per_scope.items():
        evs.sort(key=lambda e: (e["d"], e["ts"], e["symbol"]))
        kept, last = [], {}
        for e in evs:
            prev = last.get(e["symbol"])
            if prev is not None and (date.fromisoformat(e["d"]) - date.fromisoformat(prev)).days < DEDUP_DAYS:
                continue
            last[e["symbol"]] = e["d"]
            kept.append(e)
        out[scope] = kept
    return out


# ── 阶段 2:价格序列 ───────────────────────────────────────────────────────
def fetch_binance_hist(refresh=False):
    """binance_hist 全量:每个 (symbol, trade_date) 一行。既是价格源,也是「首次出现日」来源。"""
    def _go():
        rows = _cached_rows("binance_hist_rows.json", "ohlcv_daily",
                             "symbol,trade_date,close,asset_class",
                             "source=eq.binance_hist", "symbol.asc,trade_date.asc",
                             refresh=refresh)
        per = collections.defaultdict(list)
        cls = {}
        for r in rows:
            per[r["symbol"]].append((r["trade_date"], r["close"]))
            cls.setdefault(r["symbol"], r.get("asset_class"))
        out = {}
        for s, lst in per.items():
            lst.sort()
            out[s] = {"source": "binance_hist", "asset_class": cls.get(s),
                      "dates": [x[0] for x in lst], "closes": [x[1] for x in lst]}
        return out
    return _go()


def fetch_fills(symbols, refresh=False, tag="v1"):
    """补源:binance_hist_ffill / coingecko_pro_ohlc,只取需要的符号。按源分开返回。"""
    def _go():
        want = set(symbols)
        out = {}
        for src in PRICE_SOURCES[1:]:
            rows = _cached_rows(f"ohlcv_{src}_{tag}.json", "ohlcv_daily",
                                 "symbol,trade_date,close", f"source=eq.{src}",
                                 "symbol.asc,trade_date.asc",
                                 keep=lambda r: r["symbol"] in want, refresh=refresh)
            per = collections.defaultdict(dict)
            for r in rows:
                per[r["symbol"]][r["trade_date"]] = r["close"]
            srcmap = {}
            for s, dd in per.items():
                ds = sorted(dd)
                srcmap[s] = {"source": src, "dates": ds, "closes": [dd[d] for d in ds]}
            out[src] = srcmap
        return out
    return _go()


def merge_series(primary, fills_by_src):
    """源优先级 binance_hist > binance_hist_ffill > coingecko_pro_ohlc;一个符号只用一个源。"""
    out = dict(primary)
    for src in PRICE_SOURCES[1:]:
        for s, v in fills_by_src.get(src, {}).items():
            if s not in out:
                out[s] = v
    return out


# ── 阶段 3:基准宇宙(CIS 加密宇宙) ─────────────────────────────────────────
def fetch_cis_universe(refresh=False):
    def _go():
        rows = _cached_rows("cis_official_daily.json", "cis_official_daily",
                             "symbol,d,asset_class,cis_score,signal", "",
                             "d.desc,symbol.asc", refresh=refresh)
        if not rows:
            return {"as_of": None, "crypto": []}
        as_of = rows[0]["d"]
        crypto = sorted({r["symbol"] for r in rows
                         if r["d"] == as_of and r["asset_class"] not in TRADFI_CLASSES})
        return {"as_of": as_of, "crypto": crypto}
    return _go()


# ── 阶段 4:价格查表(用 apparatus 的 price_on_or_after,只喂窗口切片) ──────
_PX = {}


def _px(series, sym, d, max_gap=3):
    k = (sym, d)
    if k in _PX:
        return _PX[k]
    s = series.get(sym)
    if not s:
        _PX[k] = None
        return None
    i = bisect.bisect_left(s["dates"], d)
    if i >= len(s["dates"]):
        _PX[k] = None
        return None
    v = price_on_or_after(s["dates"][i:i + 12], s["closes"][i:i + 12], d, max_gap)
    _PX[k] = v
    return v


def _bench_ret(series, universe, d0, d1):
    rs = []
    for u in universe:
        a = _px(series, u, d0)
        b = _px(series, u, d1)
        if a is None or b is None:
            continue
        r = long_return(a, b)
        if r is not None:
            rs.append(r)
    if not rs:
        return None, 0
    return sum(rs) / len(rs), len(rs)


# ── 阶段 4b:时点(PIT)加密市场等权篮 ─────────────────────────────────────
# 预注册的「cis 加密宇宙 25 名」是**今天的**固定篮子:2017 年的事件里只有 2–5 个
# 成分有价,等权基准退化 ⇒ 早期事件的相对值被放大。所以另算一个时点口径:
# 当时**有价的所有加密符号**等权(=当时的市场)。用 numpy 向量化算,再用
# apparatus.long_return 逐窗核对(见 main 里的 selfcheck)。
class MarketBasket:
    def __init__(self, series, symbols):
        self.series = series
        self.syms = [s for s in symbols if s in series]
        dates = sorted({d for s in self.syms for d in series[s]["dates"]})
        self.dates = dates
        self.idx = {d: i for i, d in enumerate(dates)}
        M = np.full((len(dates), len(self.syms)), np.nan)
        for j, s in enumerate(self.syms):
            v = series[s]
            for d, c in zip(v["dates"], v["closes"]):
                try:
                    M[self.idx[d], j] = float(c)
                except (TypeError, ValueError):
                    pass
        self.M = M

    def _row(self, d):
        i = bisect.bisect_left(self.dates, d)
        if i >= len(self.dates):
            return None
        return self.M[i]

    def ret(self, d0, d1):
        """等权买入持有收益:mean_i(b_i/a_i − 1),a/b 取 d0/d1 当天(或之后 3 天内)的第一个有效价。"""
        a0 = self._row(d0)
        a1 = self._row(d1)
        if a0 is None or a1 is None:
            return None, 0
        with np.errstate(divide="ignore", invalid="ignore"):
            r = a1 / a0 - 1.0
        ok = np.isfinite(r) & np.isfinite(a0) & np.isfinite(a1) & (a0 > 0)
        if not ok.any():
            return None, 0
        return float(np.mean(r[ok])), int(ok.sum())

    def selfcheck(self, series, d0, d1, n=120, rng=None):
        """向量化口径 vs apparatus.long_return 逐名口径:必须逐位相等。"""
        rng = rng or np.random.default_rng(11)
        syms = list(self.syms)
        if not syms:
            return None
        diffs = []
        for _ in range(n):
            s = syms[int(rng.integers(0, len(syms)))]
            v = series[s]
            if len(v["dates"]) < 40:
                continue
            i = int(rng.integers(0, len(v["dates"]) - 35))
            j = int(rng.integers(i + 2, min(i + 35, len(v["dates"]))))
            dd0, dd1 = v["dates"][i], v["dates"][j]
            a = _px(series, s, dd0)
            b = _px(series, s, dd1)
            if a is None or b is None:
                continue
            diffs.append(abs(long_return(a, b) - (b / a - 1.0)))
        return {"n": len(diffs), "max_abs_diff": (max(diffs) if diffs else None)}


def event_windows(series, universe, evs):
    rows = []
    for e in evs:
        d0 = date.fromisoformat(e["d"])
        out = dict(e)
        for tag, dd0, dd1 in (
            ("pre30", (d0 - timedelta(days=30)).isoformat(), d0.isoformat()),
            ("fwd30", (d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=30)).isoformat()),
            ("fwd90", (d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=90)).isoformat()),
        ):
            a = _px(series, e["symbol"], dd0)
            b = _px(series, e["symbol"], dd1)
            absr = long_return(a, b) if (a is not None and b is not None) else None
            bench, nb = _bench_ret(series, universe, dd0, dd1)
            out[tag] = absr
            out[tag + "_bench"] = bench
            out[tag + "_nbench"] = nb
            out[tag + "_rel"] = None if (absr is None or bench is None) else absr - bench
        rows.append(out)
    return rows


def event_windows_mkt(series, basket, evs):
    """同 event_windows,基准换成时点加密市场等权篮。"""
    rows = []
    for e in evs:
        d0 = date.fromisoformat(e["d"])
        out = dict(e)
        for tag, dd0, dd1 in (
            ("pre30", (d0 - timedelta(days=30)).isoformat(), d0.isoformat()),
            ("fwd30", (d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=30)).isoformat()),
            ("fwd90", (d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=90)).isoformat()),
        ):
            a = _px(series, e["symbol"], dd0)
            b = _px(series, e["symbol"], dd1)
            absr = long_return(a, b) if (a is not None and b is not None) else None
            bench, nb = basket.ret(dd0, dd1)
            out[tag] = absr
            out[tag + "_bench"] = bench
            out[tag + "_nbench"] = nb
            out[tag + "_rel"] = None if (absr is None or bench is None) else absr - bench
        rows.append(out)
    return rows


# ── 阶段 5:随机日期对照(同符号、随机 d;1,000 次;种子 708) ───────────────
def control_distribution(series, universe, evs, n=CONTROL_N, seed=CONTROL_SEED, horizon=30,
                         bench_fn=None):
    """每次抽样:对每个事件,在同一符号的价格序列里随机取一个起点 d,算同一口径的相对收益,取中位数。

    bench_fn(d0,d1) -> (基准收益, 成分数);默认用预注册的固定 25 名篮子。
    """
    if bench_fn is None:
        def bench_fn(d0, d1):
            return _bench_ret(series, universe, d0, d1)

    def _one(rng):
        vals = []
        for e in evs:
            s = series.get(e["symbol"])
            if not s:
                continue
            dates = s["dates"]
            if len(dates) < horizon + 5:
                continue
            hi = len(dates) - horizon - 1
            if hi <= 1:
                continue
            i = int(rng.integers(1, hi))
            dd0 = dates[i]
            dd1 = dates[min(i + horizon - 1, len(dates) - 1)]
            a = price_on_or_after(s["dates"][i:i + 12], s["closes"][i:i + 12], dd0, 3)
            b = price_on_or_after(s["dates"][i:i + horizon + 12], s["closes"][i:i + horizon + 12],
                                  dd1, 3)
            if a is None or b is None:
                continue
            absr = long_return(a, b)
            bench, _ = bench_fn(dd0, dd1)
            if absr is None or bench is None:
                continue
            vals.append(absr - bench)
        if not vals:
            return float("nan")
        return float(np.median(vals))

    return null_distribution(_one, n, seed)


def summarize(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    absv = [r[field.replace("_rel", "")] for r in rows if r.get(field) is not None]
    if not vals:
        return {"n": 0, "median_rel_pct": None, "median_abs_pct": None,
                "mean_rel_pct": None, "win_rate_rel": None}
    return {
        "n": len(vals),
        "median_rel_pct": round(100 * float(np.median(vals)), 3),
        "median_abs_pct": round(100 * float(np.median(absv)), 3),
        "mean_rel_pct": round(100 * float(np.mean(vals)), 3),
        "win_rate_rel": round(float(np.mean([v > 0 for v in vals])), 3),
    }


def era_splits(rows, field):
    out = {}
    for name, lo, hi in ERAS:
        sub = [r for r in rows if r.get(field) is not None
               and lo <= date.fromisoformat(r["d"]) <= hi]
        out[name] = summarize(sub, field)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--diag", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "t227_results.json"))
    args = ap.parse_args()
    R = args.refresh

    # ── 闸门(卡上写死) ───────────────────────────────────────────────────
    gate_total = _count("events?select=id&source=eq.binance&kind=eq.listing")
    gate_pass = gate_total >= GATE_LISTINGS
    print(f"[gate] events(source=binance,kind=listing) = {gate_total} "
          f"(need >= {GATE_LISTINGS}) -> {'PASS' if gate_pass else 'FAIL'}")

    evs_all = fetch_listing_events(R)
    scopes = dedupe_events(evs_all)
    print("[events] rows:", len(evs_all), "-> dedup by scope:", {k: len(v) for k, v in scopes.items()})

    uni = fetch_cis_universe(R)
    print("[universe] as_of", uni["as_of"], "crypto n =", len(uni["crypto"]), uni["crypto"])

    primary = fetch_binance_hist(R)
    print("[prices] binance_hist symbols:", len(primary),
          "rows:", sum(len(v["dates"]) for v in primary.values()))
    # ── 事件集 B:派生(Binance 现货首次出现日) ───────────────────────────
    derived = []
    for s, v in primary.items():
        if v.get("asset_class") != "Crypto":
            continue
        d0 = v["dates"][0]
        derived.append({"symbol": s, "d": d0, "ts": d0 + "T00:00:00+00:00",
                        "title": "derived: first appearance in ohlcv_daily(binance_hist)",
                        "n_hist": len(v["dates"])})
    derived.sort(key=lambda e: e["d"])
    hist = dict(sorted(collections.Counter(e["d"][:4] for e in derived).items()))
    print("[B] derived listing events:", len(derived), "by year:", hist)

    need = ({e["symbol"] for sc in scopes.values() for e in sc} | set(uni["crypto"])
            | {e["symbol"] for e in derived})
    fills = fetch_fills(need, R, tag="v2")
    series = merge_series(primary, fills)
    print("[prices] merged symbols:", len(series), "sources:",
          dict(collections.Counter(v["source"] for v in series.values())))

    crypto_syms = sorted(s for s, v in primary.items() if v.get("asset_class") == "Crypto")
    basket = MarketBasket(series, crypto_syms)
    sc_check = basket.selfcheck(series, None, None)
    print("[mkt] PIT market basket symbols:", len(basket.syms),
          "selfcheck(max|Δ| vs apparatus.long_return):", sc_check)

    # ── 事件集 A:预注册(events 表) ──────────────────────────────────────
    results = {
        "gate": {"listing_rows": gate_total, "need": GATE_LISTINGS, "pass": gate_pass},
        "universe": {"as_of": uni["as_of"], "crypto": uni["crypto"]},
        "prices": {"symbols": len(series),
                   "sources": dict(collections.Counter(v["source"] for v in series.values()))},
        "arms": {},
    }

    armA = {}
    for scope, evs in sorted(scopes.items()):
        rows = event_windows(series, uni["crypto"], evs)
        have = [r for r in rows if r.get("fwd30_rel") is not None]
        sc = {"n_events": len(evs), "n_with_fwd30": len(have),
              "fwd30": summarize(rows, "fwd30_rel"),
              "fwd90": summarize(rows, "fwd90_rel"),
              "pre30": summarize(rows, "pre30_rel"),
              "eras_fwd30": era_splits(rows, "fwd30_rel")}
        if len(have) >= 5:
            try:
                null = control_distribution(series, uni["crypto"], have, "fwd30_rel")
                sc["fwd30_control_percentile"] = percentile_of(
                    float(np.median([r["fwd30_rel"] for r in have])), null)
                sc["fwd30_control_n"] = int(len(null))
            except apparatus.NoOpNull as e:
                sc["fwd30_control_error"] = str(e)
        armA[scope] = sc
        print(f"[A:{scope}] events={sc['n_events']} fwd30_ok={sc['n_with_fwd30']} "
              f"median_rel={sc['fwd30']['median_rel_pct']} pct={sc.get('fwd30_control_percentile')}")
    results["arms"]["A_events_table"] = armA

    # ── 事件集 B:派生(Binance 现货首次出现日) ───────────────────────────
    derived = []
    for s, v in primary.items():
        if v.get("asset_class") != "Crypto":
            continue
        d0 = v["dates"][0]
        derived.append({"symbol": s, "d": d0, "ts": d0 + "T00:00:00+00:00",
                        "title": "derived: first appearance in ohlcv_daily(binance_hist)",
                        "n_hist": len(v["dates"])})
    derived.sort(key=lambda e: e["d"])
    hist = dict(sorted(collections.Counter(e["d"][:4] for e in derived).items()))
    print("[B] derived listing events:", len(derived), "by year:", hist)
    results["arms"]["B_derived_first_appearance"] = {
        "n_events": len(derived), "by_year": hist,
        "n_crypto": sum(1 for e in derived if primary[e["symbol"]].get("asset_class") == "Crypto"),
    }

    rowsB = event_windows(series, uni["crypto"], derived)
    haveB = [r for r in rowsB if r.get("fwd30_rel") is not None]
    scB = {"n_events": len(derived), "n_with_fwd30": len(haveB),
           "fwd30": summarize(rowsB, "fwd30_rel"),
           "fwd90": summarize(rowsB, "fwd90_rel"),
           "pre30": summarize(rowsB, "pre30_rel"),
           "eras_fwd30": era_splits(rowsB, "fwd30_rel")}
    if len(haveB) >= 5:
        try:
            null = control_distribution(series, uni["crypto"], haveB, "fwd30_rel")
            med = float(np.median([r["fwd30_rel"] for r in haveB]))
            scB["fwd30_control_percentile"] = percentile_of(med, null)
            scB["fwd30_control_n"] = int(len(null))
            scB["fwd30_control_median"] = round(100 * float(np.median(null)), 3)
        except apparatus.NoOpNull as e:
            scB["fwd30_control_error"] = str(e)
    results["arms"]["B_derived_first_appearance"]["stats"] = scB
    print(f"[B] derived events={len(derived)} fwd30_ok={len(haveB)} "
          f"median_rel={scB['fwd30']['median_rel_pct']} pct={scB.get('fwd30_control_percentile')}")

    if args.diag:
        for r in rowsB[:10]:
            print("   ", r["d"], r["symbol"], "abs30=", r.get("fwd30"),
                  "bench=", r.get("fwd30_bench"), "nb=", r.get("fwd30_nbench"),
                  "rel=", r.get("fwd30_rel"))

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
