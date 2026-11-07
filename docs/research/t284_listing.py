#!/usr/bin/env python3
"""T-284 / S-763 —— S-708「开闸是高位」在真实 Binance 现货上币公告日(`events` 表)上的复现。

判据一字不改(照 S-708 / S-763):
    中位数 < 0 且随机日对照 ≤ 5 分位 ⇒ ✅

口径(S-763 写死):
    事件 = `events` source=binance、kind=listing、payload.scope=spot;代号用 `events.symbols`
          (空则补 src/data/market/events.py 的 `symbols_from_title`,= T-277 那套解析);
          同一代号 90 天内重复取第一条;
    d = 公告时刻所在 UTC 日;收益 d+1 → d+30(派生量挪一天,S-665);
    基准 = 同期 PIT 加密篮(照 S-708 / T-233 的算法与自检);
    对照 = 同一符号随机日 1,000 次,种子 708(走 src/data/evaluation/apparatus.py);
    价格 = `asset_mcap_daily`(主)、`coingecko_pro_ohlc`(副),另跑 binance_hist(S-708 同源对照);
    公告后 10 天内没有价 ⇒ 无价。

纪律:① 事件清单先落文件(`t284_events.json`),再取价;② 零分布 / 多空盈亏 / 分位只用 apparatus.py;
     ③ 只算,不改代码,不入库。

用法:
    python3 t284_listing.py --probe          # schema / 覆盖探测
    python3 t284_listing.py --events         # 只落事件清单(先于取价)
    python3 t284_listing.py --prices         # 只取价(缓存)
    python3 t284_listing.py                  # 完整复现
    python3 t284_listing.py --refresh        # 忽略缓存重取
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "t284_cache")
OUT_EVENTS = os.path.join(HERE, "t284_events.json")
OUT_RESULTS = os.path.join(HERE, "t284_results.json")
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

SUPA_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPA_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPA_URL or not SUPA_KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY 未设置,退出。")

sys.path.insert(0, os.path.join(REPO, "src"))
from data.evaluation import apparatus  # noqa: E402

DEDUP_DAYS = 90           # 同一代号 90 天内重复公告只留第一条
CONTROL_N = 1000          # 随机日对照次数
CONTROL_SEED = 708        # 种子 708
FWD = {"fwd30": (1, 30), "fwd90": (1, 90)}   # 主 / 副
PRE = (-30, 0)            # 副:公告前涨幅 d−30 → d
MAXGAP = 3                # 与 S-708(T-233)一致:取价窗口 3 天
NO_PRICE_WINDOW = 10      # S-763:公告后 10 天内没有价 ⇒ 无价
ERAS_763 = [("2017-2022", "2017-01-01", "2022-12-31"), ("2023-2026", "2023-01-01", "2026-12-31")]
ERAS_708 = [("2017-2020", "2017-01-01", "2020-12-31"),
            ("2021-2022", "2021-01-01", "2022-12-31"),
            ("2023-2026", "2023-01-01", "2026-12-31")]
SYM_RE = re.compile(r"^[A-Z0-9]{2,12}$")


# ── HTTP(PostgREST,只读) ───────────────────────────────────────────────────
def _raw(path: str, extra: dict | None = None, retry: int = 3):
    url = SUPA_URL + "/rest/v1/" + path
    h = {"apikey": SUPA_KEY, "Authorization": "Bearer " + SUPA_KEY,
         "Prefer": "count=exact"}
    if extra:
        h.update(extra)
    last = None
    for k in range(retry):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=180) as f:
                return f.status, f.headers.get("Content-Range"), json.loads(f.read() or b"null")
        except Exception as exc:  # 网络抖动 / 连接池满
            last = exc
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"REST 失败 {path[:120]}: {last}")


def _count(path: str, col: str = "id") -> int:
    sep = "&" if "?" in path else "?"
    _, cr, _ = _raw(path + sep + f"select={col}")
    if not cr:
        return 0
    tail = cr.split("/")[-1]
    return int(tail) if tail.isdigit() else 0


def _fetch_all(table: str, cols: str, where: str, order: str, count_col: str,
               workers: int = 6, cache_name: str | None = None,
               refresh: bool = False) -> list[dict]:
    """整表读:每页 ≤1000 行,带 order=(页边界不漂),多线程按 offset 取页,最后核总行数。"""
    if cache_name:
        cp = os.path.join(CACHE, cache_name)
        if os.path.exists(cp) and not refresh:
            with open(cp) as f:
                d = json.load(f)
            print(f"[fetch] {cache_name}: 缓存 {len(d)} 行")
            return d
    w = f"&{where}" if where else ""
    total = _count(f"{table}?{where}", count_col)
    pages = max(1, math.ceil(total / 1000))
    print(f"[fetch] {table}{w} → 期望 {total} 行 / {pages} 页,workers={workers}", flush=True)
    t0 = time.time()

    def one(p: int):
        q = (f"{table}?select={cols}{w}&order={order}"
             f"&limit=1000&offset={p * 1000}")
        _, _, rows = _raw(q)
        return rows

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, range(pages)), 1):
            rows.extend(r)
            if i % 50 == 0 or i == pages:
                print(f"[fetch] {table}: {i}/{pages} 页,累计 {len(rows)} 行,"
                      f" {time.time() - t0:.0f}s", flush=True)
    if total and len(rows) != total:
        raise RuntimeError(f"{table} 行数不符: 取到 {len(rows)},期望 {total}(分页有洞)")
    if cache_name:
        os.makedirs(CACHE, exist_ok=True)
        with open(os.path.join(CACHE, cache_name), "w") as f:
            json.dump(rows, f)
    print(f"[fetch] {table}: 完成 {len(rows)} 行, {time.time() - t0:.0f}s", flush=True)
    return rows


# ── 阶段 1:事件(先落文件,再取价) ─────────────────────────────────────────
def probe():
    """schema / 覆盖探测(只读)。"""
    print("[probe] events listing count:", _count("events?source=eq.binance&kind=eq.listing"))
    for name, (tbl, where, cols, order, ccol, dcol, pcol, keep_cls) in PRICE_SOURCES.items():
        w = f"&{where}" if where else ""
        n = _count(f"{tbl}?{where}", ccol)
        _, _, r1 = _raw(f"{tbl}?select={dcol}{w}&order={dcol}.asc&limit=1")
        _, _, r2 = _raw(f"{tbl}?select={dcol}{w}&order={dcol}.desc&limit=1")
        print(f"[probe] {name}: rows={n} d-range=",
              r1[0][dcol] if r1 else None, "→", r2[0][dcol] if r2 else None)


_PARSER = None


def _parser_mod():
    global _PARSER
    if _PARSER is None:
        p = os.path.join(REPO, "src", "data", "market", "events.py")
        spec = importlib.util.spec_from_file_location("cc_events_parser", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PARSER = mod
    return _PARSER


def _symbols_from_title(title: str) -> list[str]:
    """用 src/data/market/events.py 的官方解析(= T-277 那套)。"""
    return _parser_mod().symbols_from_title(title or "")


def fetch_events(refresh: bool = False) -> list[dict]:
    return _fetch_all("events", "id,ts,kind,source,symbols,payload,title",
                      "source=eq.binance&kind=eq.listing", "ts.asc,symbols.asc",
                      "id", workers=4, cache_name="events_listing.json", refresh=refresh)


def build_event_list(refresh: bool = False) -> dict:
    """事件清单:纳入 / 排除 / 代号来源,逐条落文件 —— 在取价之前。"""
    rows = fetch_events(refresh)
    kept: dict[str, dict] = {}          # symbol → 事件(同一代号 90 天内只留第一条)
    last_seen: dict[str, str] = {}
    excluded: list[dict] = []
    n_scope_margin = n_scope_alpha = n_scope_spot = 0
    n_sym_field = n_sym_title = 0
    for r in sorted(rows, key=lambda x: (x["ts"], x.get("title") or "")):
        scope = (r.get("payload") or {}).get("scope") or "unknown"
        if scope == "spot":
            n_scope_spot += 1
        elif scope == "margin":
            n_scope_margin += 1
        elif scope == "alpha":
            n_scope_alpha += 1
        else:
            excluded.append({"id": r["id"], "ts": r["ts"], "title": r.get("title"),
                             "code": f"scope_{scope}", "scope": scope})
            continue
        if scope != "spot":
            excluded.append({"id": r["id"], "ts": r["ts"], "title": r.get("title"),
                             "code": f"scope_{scope}_not_spot", "scope": scope,
                             "symbols_field": r.get("symbols") or []})
            continue
        raw_syms = [str(s).upper().strip() for s in (r.get("symbols") or []) if s]
        raw_syms = [s for s in raw_syms if SYM_RE.match(s)]
        if raw_syms:
            syms, src = raw_syms, "field"
            n_sym_field += 1
        else:
            try:
                syms = [s for s in _symbols_from_title(r.get("title") or "") if SYM_RE.match(s)]
            except Exception:
                syms = []
            src = "title"
            n_sym_title += 1
        if not syms:
            excluded.append({"id": r["id"], "ts": r["ts"], "title": r.get("title"),
                             "code": "no_symbol", "scope": scope})
            continue
        d = r["ts"][:10]
        for s in syms:
            prev = last_seen.get(s)
            if prev is not None and (date.fromisoformat(d) - date.fromisoformat(prev)).days < DEDUP_DAYS:
                excluded.append({"id": r["id"], "ts": r["ts"], "symbol": s,
                                 "code": "dup_within_90d", "scope": scope,
                                 "kept_d": prev})
                continue
            last_seen[s] = d
            if s not in kept:
                kept[s] = {"symbol": s, "d": d, "ts": r["ts"], "id": r["id"],
                           "title": r.get("title") or "", "sym_source": src,
                           "scope": scope}
    events = sorted(kept.values(), key=lambda e: (e["d"], e["symbol"]))
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rule": "events(source=binance, kind=listing, payload.scope=spot);代号 = events.symbols,"
                "空则 src/data/market/events.py:symbols_from_title;同一代号 90 天内重复取第一条;d = ts 的 UTC 日",
        "counts": {
            "events_rows_total": len(rows),
            "scope_spot": n_scope_spot, "scope_margin": n_scope_margin, "scope_alpha": n_scope_alpha,
            "symbol_from_field": n_sym_field, "symbol_from_title": n_sym_title,
            "kept_events": len(events), "excluded": len(excluded),
            "excluded_by_code": dict(collections.Counter(e["code"] for e in excluded)),
        },
        "events": events,
        "excluded": excluded,
    }
    with open(OUT_EVENTS, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[events] 清单落盘 {OUT_EVENTS}: 纳入 {len(events)} 条,排除 {len(excluded)} 条 "
          f"({out['counts']['excluded_by_code']})")
    print(f"[events] 代号来源: field={n_sym_field} title={n_sym_title};"
          f"scope: spot={n_scope_spot} margin={n_scope_margin} alpha={n_scope_alpha}")
    return out


# ── 阶段 2:价格 ───────────────────────────────────────────────────────────
def build_series(rows: list[dict], dcol: str, ccol: str, keep_cls: bool = False):
    per = collections.defaultdict(list)
    cls = {}
    for r in rows:
        p = r.get(ccol)
        if p is None:
            continue
        per[r["symbol"]].append((r[dcol], p))
        if keep_cls:
            cls.setdefault(r["symbol"], r.get("asset_class"))
    out = {}
    for s, lst in per.items():
        lst.sort(key=lambda x: x[0])
        out[s] = {"dates": [x[0] for x in lst], "closes": [x[1] for x in lst],
                  "asset_class": cls.get(s)}
    return out


class Series:
    """单个符号的日期 / 收盘序列(取价口径同 apparatus.price_on_or_after)。"""

    def __init__(self, rec):
        self.dates = rec["dates"]
        self.closes = rec["closes"]
        self._cl = [apparatus._price(c) for c in self.closes]

    def price(self, d: str, max_gap: int = MAXGAP):
        if not self.dates:
            return None
        i = int(np.searchsorted(np.array(self.dates, dtype="datetime64[D]"),
                                np.datetime64(d, "D"), side="left"))
        if i >= len(self.dates):
            return None
        j = i
        while j < len(self.dates):
            gap = (date.fromisoformat(self.dates[j]) - date.fromisoformat(d)).days
            if gap > max_gap:
                return None
            if self._cl[j] is not None:
                return self._cl[j]
            j += 1
        return None

    def has_price_within(self, d0: str, d1: str) -> bool:
        return self.price(d0, (date.fromisoformat(d1) - date.fromisoformat(d0)).days) is not None


class PitBasket:
    """PIT 加密等权篮 —— 与 S-708 / T-233 的算法一致(逐位复刻):
    成分 = 该价格源里当时有价的全部加密符号;价格语义 = d 当天或之后 3 天内第一个有效收盘;
    网格 = 整个日历;成分数 nb = 两个时点都有价的名字数。
    """

    def __init__(self, series: dict, crypto_only: bool = True):
        self.syms = sorted(s for s, v in series.items()
                           if (not crypto_only or v.get("asset_class") in (None, "Crypto"))
                           and v.get("dates"))
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
            gap = (ds64[idx] - grid64).astype("timedelta64[D]").astype(int)
            ok = valid & (gap <= MAXGAP)
            F[ok, j] = np.array(self.ser[s].closes, dtype=float)[idx[ok]]
        self.F = F

    def _row(self, d):
        i = (date.fromisoformat(d) - self.g0).days
        return i if 0 <= i < len(self.grid) else None

    def ret(self, d0, d1):
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
            a, b = ser.price(d0), ser.price(d1)
            if a is None or b is None:
                continue
            r = apparatus.long_return(a, b)
            if r is not None:
                rs.append(r)
        if not rs:
            return None, 0
        return float(np.mean(rs)), len(rs)

    def selfcheck(self, n: int = 200, seed: int = 17) -> dict:
        """向量化口径 vs 逐名 apparatus.long_return:逐位比较(T-233 的强制自检)。"""
        rng = np.random.default_rng(seed)
        per_name, basket, nb_seen = [], [], []
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
            r_app = apparatus.long_return(a_app, b_app)
            j0, j1 = self._row(d0), self._row(d1)
            a_vec, b_vec = self.F[j0, self.col[s]], self.F[j1, self.col[s]]
            r_vec = apparatus.long_return(a_vec, b_vec)
            if r_app is None or r_vec is None:
                continue
            per_name.append(abs(r_app - r_vec))
            v, nb = self.ret(d0, d1)
            a2, nb2 = self.ret_apparatus(d0, d1)
            if v is not None and a2 is not None:
                basket.append(abs(v - a2))
                nb_seen.append((nb, nb2))
        return {"n_windows": len(per_name),
                "max_abs_diff_per_name": max(per_name) if per_name else None,
                "max_abs_diff_basket_mean": max(basket) if basket else None,
                "nb_mismatch_count": sum(1 for a, b in nb_seen if a != b),
                "nb_median": int(np.median([a for a, _ in nb_seen])) if nb_seen else None}


# ── 阶段 3:窗口 / 随机日对照 / 判据 ──────────────────────────────────────
def windows(series: dict, basket: PitBasket, evs: list[dict], maxgap: int = MAXGAP):
    out = []
    for e in evs:
        d0 = date.fromisoformat(e["d"])
        row = dict(e)
        ser = series.get(e["symbol"])
        for tag, (off_in, off_out) in FWD.items():
            dd0 = (d0 + timedelta(days=off_in)).isoformat()
            dd1 = (d0 + timedelta(days=off_out)).isoformat()
            a = ser.price(dd0, maxgap) if ser else None
            b = ser.price(dd1, maxgap) if ser else None
            absr = apparatus.long_return(a, b) if (a is not None and b is not None) else None
            bench, nb = basket.ret(dd0, dd1)
            row[tag] = absr
            row[tag + "_bench"] = bench
            row[tag + "_nb"] = nb
            row[tag + "_rel"] = None if (absr is None or bench is None) else absr - bench
        # 副:公告前涨幅 d−30 → d(同一价格源)
        pd0 = (d0 + timedelta(days=PRE[0])).isoformat()
        pd1 = (d0 + timedelta(days=PRE[1])).isoformat()
        a = ser.price(pd0, maxgap) if ser else None
        b = ser.price(pd1, maxgap) if ser else None
        row["pre30"] = apparatus.long_return(a, b) if (a is not None and b is not None) else None
        # 无价判据:公告后 10 天内没有价
        row["has_price_10d"] = bool(ser and ser.has_price_within(
            e["d"], (d0 + timedelta(days=NO_PRICE_WINDOW)).isoformat()))
        out.append(row)
    return out


def control(series: dict, basket: PitBasket, evs: list[dict], tag: str = "fwd30",
            span: int = 29, n: int = CONTROL_N, seed: int = CONTROL_SEED):
    """随机日对照(同一符号、随机 d、1,000 次、种子 708):每抽样取各事件超额的**中位数**。"""

    def _one(rng):
        vals = []
        for e in evs:
            ser = series.get(e["symbol"])
            if ser is None or len(ser.dates) < 5:
                continue
            i = int(rng.integers(0, len(ser.dates)))
            dd0 = ser.dates[i]
            dd1 = (date.fromisoformat(dd0) + timedelta(days=span)).isoformat()
            a, b = ser.price(dd0), ser.price(dd1)
            if a is None or b is None:
                continue
            absr = apparatus.long_return(a, b)
            if absr is None:
                continue
            bench, _ = basket.ret(dd0, dd1)
            if bench is None:
                continue
            vals.append(absr - bench)
        if not vals:
            return float("nan")
        return float(np.median(vals))

    return apparatus.null_distribution(_one, n, seed)


def summarize(rows: list[dict], tag: str) -> dict:
    vals = [r[tag + "_rel"] for r in rows if r.get(tag + "_rel") is not None]
    absv = [r[tag] for r in rows if r.get(tag + "_rel") is not None]
    nbs = [r[tag + "_nb"] for r in rows if r.get(tag + "_rel") is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals),
            "median_rel_pct": round(100 * float(np.median(vals)), 3),
            "median_abs_pct": round(100 * float(np.median(absv)), 3),
            "mean_rel_pct": round(100 * float(np.mean(vals)), 3),
            "win_rate_rel": round(float(np.mean([v > 0 for v in vals])), 3),
            "q25_rel_pct": round(100 * float(np.percentile(vals, 25)), 3),
            "q75_rel_pct": round(100 * float(np.percentile(vals, 75)), 3),
            "nb_median": int(np.median(nbs)), "nb_min": int(np.min(nbs)), "nb_max": int(np.max(nbs))}


def judge(rows: list[dict], tag: str, series: dict, basket: PitBasket, label: str) -> dict:
    """判据(照 S-708):中位数 < 0 且随机日对照 ≤ 5 分位 ⇒ CONFIRMED(✅)。"""
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
        null = control(series, basket, have, tag=tag, span=span)
        pct = apparatus.percentile_of(med, null)
        out["control_percentile"] = pct
        out["control_n"] = int(len(null))
        out["control_median_pct"] = round(100 * float(np.median(null)), 3)
        out["control_p05_pct"] = round(100 * float(np.percentile(null, 5)), 3)
        out["verdict"] = ("CONFIRMED" if (med < 0 and pct is not None and pct <= 0.05)
                          else "NOT_CONFIRMED")
    except apparatus.NoOpNull as exc:
        out["control_error"] = str(exc)
        out["verdict"] = "REPORT_ONLY"
    return out


def era_splits(rows: list[dict], tag: str, eras) -> dict:
    out = {}
    for name, lo, hi in eras:
        sub = [r for r in rows if r.get(tag + "_rel") is not None and lo <= r["d"] <= hi]
        out[name] = summarize(sub, tag)
    return out


def coverage_report(ev: dict) -> dict:
    """清单覆盖:年代分布 + 代号来源 + 排除原因(报告用)。"""
    evs = ev["events"]
    by_year = collections.Counter(e["d"][:4] for e in evs)
    no_sym_year = collections.Counter(e["ts"][:4] for e in ev["excluded"]
                                      if e["code"] == "no_symbol")
    return {"kept_by_year": dict(sorted(by_year.items())),
            "no_symbol_by_year": dict(sorted(no_sym_year.items())),
            "kept_first_last": [evs[0]["d"], evs[-1]["d"]] if evs else None,
            "symbol_source": dict(collections.Counter(e["sym_source"] for e in evs)),
            "n_titles_sample_no_symbol": [e["title"] for e in ev["excluded"]
                                          if e["code"] == "no_symbol"][:20]}


# ── 阶段 2:取三个价格源 ───────────────────────────────────────────────────
PRICE_SOURCES = {
    # 名字: (table, where, cols, order, count_col, 日期列, 价格列, 是否带 asset_class)
    "asset_mcap_daily": ("asset_mcap_daily", "", "symbol,d,price", "symbol.asc,d.asc",
                         "symbol", "d", "price", False),
    "coingecko_pro_ohlc": ("ohlcv_daily", "source=eq.coingecko_pro_ohlc",
                            "symbol,trade_date,close,asset_class", "symbol.asc,trade_date.asc",
                            "id", "trade_date", "close", True),
    "binance_hist": ("ohlcv_daily", "source=eq.binance_hist",
                      "symbol,trade_date,close,asset_class", "symbol.asc,trade_date.asc",
                      "id", "trade_date", "close", True),
}


def fetch_prices(refresh: bool = False) -> dict:
    out = {}
    for name, (tbl, where, cols, order, ccol, dcol, pcol, keep_cls) in PRICE_SOURCES.items():
        rows = _fetch_all(tbl, cols, where, order, ccol, workers=6,
                          cache_name=f"{name}.json", refresh=refresh)
        ser = build_series(rows, dcol, pcol, keep_cls=keep_cls)
        out[name] = {"series": ser, "rows": len(rows), "symbols": len(ser)}
        print(f"[prices] {name}: {len(rows)} 行 / {len(ser)} 符号", flush=True)
    return out


def proxy_events(series: dict) -> list[dict]:
    """S-708 的代理事件源:每个加密符号在 binance_hist 的首次出现日。"""
    evs = []
    for s, v in series.items():
        if v.get("asset_class") != "Crypto" or not v["dates"]:
            continue
        evs.append({"symbol": s, "d": v["dates"][0], "ts": v["dates"][0] + "T00:00:00+00:00",
                    "title": "proxy: first appearance in ohlcv_daily(binance_hist)",
                    "sym_source": "proxy", "scope": "spot"})
    evs.sort(key=lambda e: (e["d"], e["symbol"]))
    return evs


# ── 主流程 ────────────────────────────────────────────────────────────────
def run_arm(name: str, series: dict, basket: PitBasket, evs: list[dict],
            maxgap: int = MAXGAP, with_control: bool = True) -> dict:
    rows = windows(series, basket, evs, maxgap=maxgap)
    no_px = [r for r in rows if not r.get("has_price_10d")]
    kept = [r for r in rows if r.get("has_price_10d")]
    out = {"arm": name, "price_source": name,
           "basket_symbols": len(basket.syms),
           "events_in": len(evs), "events_no_price_10d": len(no_px),
           "fwd30": judge(kept, "fwd30", series, basket, label=f"{name}/fwd30") if with_control else
                    summarize(kept, "fwd30"),
           "fwd90_副": summarize(kept, "fwd90"),
           "pre30_副": summarize_abs(kept, "pre30"),
           "eras_763": era_splits(kept, "fwd30", ERAS_763),
           "eras_708": era_splits(kept, "fwd30", ERAS_708),
           "basket_selfcheck": basket.selfcheck(),
           }
    if not with_control:
        out["fwd30"]["verdict"] = "REPORT_ONLY"
    return out, rows


def summarize_abs(rows: list[dict], field: str) -> dict:
    vals = [r[field] for r in rows if r.get(field) is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "median_pct": round(100 * float(np.median(vals)), 3),
            "mean_pct": round(100 * float(np.mean(vals)), 3),
            "win_rate": round(float(np.mean([v > 0 for v in vals])), 3)}


def gap_distribution(events: list[dict], series_bh: dict) -> dict:
    """与 S-708 代理事件逐个配对的日期差(真实公告日 − binance_hist 首现日)。"""
    gaps = []
    for e in events:
        rec = series_bh.get(e["symbol"])
        if not rec or not rec["dates"]:
            continue
        gaps.append((date.fromisoformat(e["d"]) - date.fromisoformat(rec["dates"][0])).days)
    if not gaps:
        return {"n": 0}
    arr = np.array(gaps, dtype=float)
    return {"n": len(gaps),
            "median_days": float(np.median(arr)),
            "mean_days": float(np.mean(arr)),
            "q10": float(np.percentile(arr, 10)), "q25": float(np.percentile(arr, 25)),
            "q75": float(np.percentile(arr, 75)), "q90": float(np.percentile(arr, 90)),
            "min": float(arr.min()), "max": float(arr.max()),
            "pct_negative": round(float(np.mean(arr < 0)), 4),
            "pct_zero": round(float(np.mean(arr == 0)), 4),
            "pct_gt_30": round(float(np.mean(arr > 30)), 4),
            "pct_gt_90": round(float(np.mean(arr > 90)), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--events", action="store_true")
    ap.add_argument("--titles", action="store_true")
    ap.add_argument("--prices", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default=OUT_RESULTS)
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    # ① 事件清单先落文件(在取价之前)
    ev = build_event_list(args.refresh)
    events = ev["events"]
    cov = coverage_report(ev)
    print(f"[coverage] 纳入年代分布: {cov['kept_by_year']}")
    print(f"[coverage] 无代号(被排除)年代分布: {cov['no_symbol_by_year']}")
    print(f"[coverage] 无代号标题样例: {cov['n_titles_sample_no_symbol'][:8]}")
    if args.events:
        return
    if args.titles:
        for y in sorted({e["ts"][:4] for e in ev["excluded"] if e["code"] == "no_symbol"}):
            ts = [e["title"] for e in ev["excluded"]
                  if e["code"] == "no_symbol" and e["ts"][:4] == y][:12]
            print(f"--- {y} 未解析标题({sum(1 for e in ev['excluded'] if e['code'] == 'no_symbol' and e['ts'][:4] == y)} 条) ---")
            for t in ts:
                print("   ", t)
        return

    # ② 取价
    prices = fetch_prices(args.refresh)
    if args.prices:
        return

    # ③ 三条臂
    results = {"meta": {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "task": "T-284", "ledger": "S-763", "replicates": "S-708",
        "criterion": "中位数 < 0 且随机日对照 ≤ 5 分位 ⇒ CONFIRMED(判据一字不改)",
        "control": {"n": CONTROL_N, "seed": CONTROL_SEED,
                    "mode": "同一符号随机起点 d,取各事件超额的中位数"},
        "events_file": os.path.basename(OUT_EVENTS),
        "event_counts": ev["counts"],
        "coverage": cov,
        "sources": {k: {"rows": v["rows"], "symbols": v["symbols"]}
                    for k, v in prices.items()},
    }, "arms": {}, "gap_vs_proxy": {}}

    for name in ["asset_mcap_daily", "coingecko_pro_ohlc", "binance_hist"]:
        series = prices[name]["series"]
        basket = PitBasket(series)
        arm, rows = run_arm(name, series, basket, events)
        results["arms"][name] = arm
        results["arms"][name]["rows_sample"] = [
            {"symbol": r["symbol"], "d": r["d"], "fwd30_rel_pct": None if r.get("fwd30_rel") is None
             else round(100 * r["fwd30_rel"], 3),
             "fwd30_abs_pct": None if r.get("fwd30") is None else round(100 * r["fwd30"], 3),
             "bench_pct": None if r.get("fwd30_bench") is None else round(100 * r["fwd30_bench"], 3),
             "nb": r.get("fwd30_nb"), "sym_source": r.get("sym_source")}
            for r in rows if r.get("has_price_10d")]
        print(f"[arm:{name}] fwd30 n={arm['fwd30']['n']} "
              f"median_rel={arm['fwd30'].get('median_rel_pct')}% "
              f"pct={arm['fwd30'].get('control_percentile')} "
              f"verdict={arm['fwd30'].get('verdict')}", flush=True)

    # ④ 校准:同一套机器 + S-708 的代理事件日(binance_hist 源)⇒ 应复现 S-708 的 −18.03%
    series_bh = prices["binance_hist"]["series"]
    basket_bh = PitBasket(series_bh)
    prox = proxy_events(series_bh)
    arm_p, _ = run_arm("calibration_proxy_events", series_bh, basket_bh, prox)
    results["arms"]["calibration_proxy_events"] = arm_p
    print(f"[calib] 代理事件(照 S-708 口径) fwd30 n={arm_p['fwd30']['n']} "
          f"median_rel={arm_p['fwd30'].get('median_rel_pct')}% "
          f"pct={arm_p['fwd30'].get('control_percentile')}", flush=True)

    # ⑤ 日期差分布(真实公告日 vs S-708 代理事件)
    results["gap_vs_proxy"] = gap_distribution(events, series_bh)

    with open(args.out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()

