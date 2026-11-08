#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-300 / S-782 —— S-770 在解析器 v2 之后重量一次(补回的 2018–2020 KRW 上币)。

预注册原文(S-782,REFUTATION_LEDGER.md)照抄在报告开头;本脚本只算,不改代码、不入库、不做 DDL。

口径(S-782 写死):
    事件 = events(source=upbit, kind=listing) 里解析器 v2 重写后 payload.krw = true 的每个代号第一次;
    篮子 = PIT 等权篮(asset_mcap_daily 全部代号),**先剔掉 asset_mcap_daily 单日价格比
          > 100 或 < 0.01 的币日**;同一条规则也报一次不剔的结果;
    d = 公告时刻(UTC)所在日;进场 d+1 收盘 → d+30 收盘(S-665:派生量挪一天);
    超额 = 代号 − 时点等权篮;对照 = 同代号、同年随机日 1,000 次,种子 770(apparatus);
    判 = **只看 2017–2021 段**:中位 < 0 且该段分位 ≤ 0.05 ⇒ 「早期段也站住」;
          全样本三条判据(中位 < 0、分位 ≤ 0.05、两段同号)重报。
    除中位外报均值与 p10 / p90;报新增事件数(相对 T-291 的 232 / 106)与按年分布。

纪律:零分布 / 盈亏 / 分位只用 src/data/evaluation/apparatus.py;翻页一律带 order=;
     事件清单先落 docs/research/t300_events.csv 再取价;探针改同一个文件再跑。

用法:
    python3 t300_upbit_v2.py --stage events     # 只落事件清单(先于取价)
    python3 t300_upbit_v2.py                     # 完整跑
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
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
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CACHE = os.path.join(HERE, "t300_cache")
OUT_EVENTS_CSV = os.path.join(HERE, "t300_events.csv")
OUT_EVENTS_JSON = os.path.join(HERE, "t300_events.json")
OUT_RESULTS = os.path.join(HERE, "t300_results.json")

SUPA_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPA_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPA_URL or not SUPA_KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY 未设置,退出。")

sys.path.insert(0, os.path.join(REPO, "src"))
from data.evaluation import apparatus  # noqa: E402

# ── 写死的口径常量(S-782 / S-770) ─────────────────────────────────────────
CONTROL_N = 1000
CONTROL_SEED = 770
ENTRY_OFF = 1
EXIT_OFF = 30
MAXGAP = 3
NO_PRICE_WINDOW = 10
PRE = (-30, 0)
ERAS = [("2017-2021", "2017-01-01", "2021-12-31"),
        ("2022-2026", "2022-01-01", "2026-12-31")]
PRIMARY_ERA = "2017-2021"
BINANCE_LOOKBACK = 30
SYM_RE = re.compile(r"^[A-Z0-9]{2,12}$")
MARKET_WORDS = {"KRW", "BTC", "USDT", "ETH", "BNB", "BTTC", "XRP", "USDC", "USDS",
                "TRY", "EUR", "JPY", "SUSD", "BUSD", "FDUSD", "DAI", "PAX"}
PAREN = re.compile(r"\(([^)]{1,100})\)")
TOK = re.compile(r"[A-Z][A-Z0-9]{1,11}")

# 篮子伪影规则(S-782):单日价格比 > 100 或 < 0.01 的币日剔掉
JUMP_HI = 100.0
JUMP_LO = 0.01
CHAIN_CAP = 10          # 连续剔最多 10 个币日(防止永久换算把整段历史剔光)


# ── HTTP(PostgREST,只读) ────────────────────────────────────────────────────
def _raw(path: str, extra: dict | None = None, retry: int = 3):
    url = SUPA_URL + "/rest/v1/" + path
    last = None
    for i in range(retry):
        try:
            h = {"apikey": SUPA_KEY, "Authorization": "Bearer " + SUPA_KEY}
            if extra:
                h.update(extra)
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=180) as f:
                body = f.read()
                cr = f.headers.get("Content-Range")
                return json.loads(body or b"null"), cr
        except Exception as exc:      # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {path[:120]} 失败: {last!r}")


def _count(path: str, col: str = "id") -> int:
    sep = "&" if "?" in path else "?"
    _, cr = _raw(path + sep + f"select={col}")
    if not cr:
        return 0
    tail = cr.split("/")[-1]
    return int(tail) if tail.isdigit() else 0


def _fetch_all(table: str, cols: str, where: str, order: str, count_col: str,
               workers: int = 8, cache_name: str | None = None,
               refresh: bool = False) -> list[dict]:
    """整表读:每页 ≤ 1000 行,带 order=(页边界不漂),多线程按 offset 取页,最后核总行数。"""
    if cache_name:
        cp = os.path.join(CACHE, cache_name)
        if os.path.exists(cp) and not refresh:
            with open(cp) as f:
                d = json.load(f)
            print(f"[fetch] {cache_name}: 缓存 {len(d)} 行", flush=True)
            return d
    w = f"&{where}" if where else ""
    total = _count(f"{table}?{where}", count_col)
    pages = max(1, math.ceil(total / 1000))
    print(f"[fetch] {table}{w} → 期望 {total} 行 / {pages} 页", flush=True)
    t0 = time.time()

    def one(p: int):
        q = f"{table}?select={cols}{w}&order={order}&limit=1000&offset={p * 1000}"
        rows, _ = _raw(q)
        return rows

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, range(pages)), 1):
            rows.extend(r)
            if i % 200 == 0 or i == pages:
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


# ── 阶段 1:事件清单(先落文件,再取价) ──────────────────────────────────────
def symbols_from_title(title: str) -> list[str]:
    out: list[str] = []
    for g in PAREN.findall(title or ""):
        for t in TOK.findall(g):
            if t in MARKET_WORDS or not SYM_RE.match(t):
                continue
            if t not in out:
                out.append(t)
    return out[:5]


def fetch_upbit_events(refresh: bool = False) -> dict:
    kinds = ("listing", "delisting", "warning")
    out = {}
    for k in kinds:
        out[k] = _fetch_all("events", "id,ts,kind,source,symbols,title,url,payload",
                            f"source=eq.upbit&kind=eq.{k}", "ts.asc,symbols.asc", "id",
                            workers=4, cache_name=f"events_upbit_{k}.json", refresh=refresh)
    return out


def _event_rows(rows: list[dict], kind: str, arm: str) -> list[dict]:
    out = []
    for r in rows:
        p = r.get("payload") or {}
        krw = p.get("krw", "MISSING")
        field = [str(s).upper().strip() for s in (r.get("symbols") or []) if s]
        field = [s for s in field if SYM_RE.match(s) and any(c.isalpha() for c in s)]
        title_syms = symbols_from_title(r.get("title") or "")
        syms = field if field else title_syms
        src = "field" if field else ("title" if title_syms else "none")
        d = (r.get("ts") or "")[:10]
        for s in syms:
            out.append({"event_id": r["id"], "ts": r.get("ts") or "", "d": d,
                        "kind": kind, "arm": arm, "symbol": s, "sym_source": src,
                        "krw": krw, "markets": p.get("markets"),
                        "parser": p.get("parser"),
                        "title": (r.get("title") or "")[:160], "url": r.get("url") or ""})
    return out


def build_event_list(refresh: bool = False) -> dict:
    raw_ev = fetch_upbit_events(refresh=refresh)
    counts: dict = {}
    arms: dict[str, list[dict]] = {}

    listing = _event_rows(raw_ev["listing"], "listing", "listing")
    krw_true = [e for e in listing if e["krw"] is True]
    krw_null = [e for e in listing if e["krw"] is None]
    krw_false = [e for e in listing if e["krw"] is False]
    kept: dict[str, dict] = {}
    dup = 0
    for e in sorted(krw_true, key=lambda x: (x["d"], x["symbol"])):
        if e["symbol"] in kept:
            dup += 1
            continue
        kept[e["symbol"]] = e
    arms["listing_krw"] = sorted(kept.values(), key=lambda e: (e["d"], e["symbol"]))
    arms["listing_krw_null"] = sorted(krw_null, key=lambda e: (e["d"], e["symbol"]))
    arms["delisting"] = sorted(_event_rows(raw_ev["delisting"], "delisting", "delisting"),
                                key=lambda e: (e["d"], e["symbol"]))
    arms["warning"] = sorted(_event_rows(raw_ev["warning"], "warning", "warning"),
                             key=lambda e: (e["d"], e["symbol"]))

    counts["listing_rows"] = len(raw_ev["listing"])
    counts["listing_symbol_rows_krw_true"] = len(krw_true)
    counts["listing_symbol_rows_krw_null"] = len(krw_null)
    counts["listing_symbol_rows_krw_false"] = len(krw_false)
    counts["listing_krw_events_kept"] = len(arms["listing_krw"])
    counts["listing_krw_dup_symbol_dropped"] = dup
    counts["listing_krw_null_symbol_rows"] = len(arms["listing_krw_null"])
    counts["listing_krw_null_events_kept"] = len(
        {e["symbol"] for e in arms["listing_krw_null"]})
    counts["delisting_rows"] = len(raw_ev["delisting"])
    counts["delisting_symbol_rows"] = len(arms["delisting"])
    counts["delisting_events_kept"] = len({e["symbol"] for e in arms["delisting"]})
    counts["warning_rows"] = len(raw_ev["warning"])
    counts["warning_symbol_rows"] = len(arms["warning"])
    counts["warning_events_kept"] = len({e["symbol"] for e in arms["warning"]})
    counts["parser_v2_rows"] = sum(1 for r in raw_ev["listing"]
                                   if (r.get("payload") or {}).get("parser"))
    counts["listing_by_year_krw_true"] = dict(sorted(collections.Counter(
        e["d"][:4] for e in arms["listing_krw"]).items()))

    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "task": "T-300", "ledger": "S-782",
           "rule": ("events(source=upbit, kind=listing, payload.krw=true);每个代号第一次 KRW 上币;"
                    "d = ts 的 UTC 日;krw 为空的单列只报;delisting / warning 同口径只报不判"),
           "counts": counts, "arms": arms}
    with open(OUT_EVENTS_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    rows_csv = []
    for arm, evs in arms.items():
        for e in evs:
            rows_csv.append([arm, e["kind"], e["symbol"], e["d"], e["ts"], e["sym_source"],
                             repr(e["krw"]), repr(e.get("markets")), repr(e.get("parser")),
                             e["event_id"], e["title"], e["url"]])
    with open(OUT_EVENTS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "kind", "symbol", "d", "ts", "sym_source", "krw", "markets",
                    "parser", "event_id", "title", "url"])
        w.writerows(rows_csv)
    print(f"[events] 落盘 {OUT_EVENTS_CSV}({len(rows_csv)} 行)/ {OUT_EVENTS_JSON}")
    print(f"[events] counts={counts}")
    return out


# ── 阶段 2:价格 + 篮子伪影过滤 ─────────────────────────────────────────────
class Series:
    """单符号的日期 / 收盘序列(取价口径同 apparatus.price_on_or_after)。"""

    def __init__(self, dates, closes):
        self.dates = dates
        self.closes = closes
        self._cl = [apparatus._price(c) for c in closes]
        self._ds64 = np.array(dates, dtype="datetime64[D]") if dates else None

    def price(self, d: str, max_gap: int = MAXGAP):
        if not self.dates:
            return None
        i = int(np.searchsorted(self._ds64, np.datetime64(d, "D"), side="left"))
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
    """PIT 加密等权篮(逐位复刻 S-708 / T-233 / S-763 / T-291 的算法)。"""

    def __init__(self, series: dict):
        self.syms = sorted(s for s, v in series.items() if v.get("dates"))
        self.ser = {s: Series(series[s]["dates"], series[s]["closes"]) for s in self.syms}
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
            F[ok, j] = np.array([apparatus._price(c) for c in self.ser[s].closes],
                                dtype=float)[idx[ok]]
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

    def selfcheck(self, n: int = 200, seed: int = 17) -> dict:
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
            if v is not None:
                basket.append(abs(v))
                nb_seen.append(nb)
        return {"n_windows": len(per_name),
                "max_abs_diff_per_name": max(per_name) if per_name else None,
                "nb_median": int(np.median(nb_seen)) if nb_seen else None}


def build_series(rows: list[dict], dcol: str, ccol: str) -> dict:
    per = collections.defaultdict(list)
    seen = set()
    for r in rows:
        p = r.get(ccol)
        if p is None:
            continue
        key = (r["symbol"], r[dcol])
        if key in seen:
            continue
        seen.add(key)
        per[r["symbol"]].append((r[dcol], p))
    out = {}
    for s, lst in per.items():
        lst.sort(key=lambda x: x[0])
        out[s] = {"dates": [x[0] for x in lst], "closes": [x[1] for x in lst]}
    return out


def filter_jumps(series: dict, mode: str) -> tuple[dict, dict]:
    """S-782 的篮子伪影规则:asset_mcap_daily 单日价格比 > 100 或 < 0.01 的币日剔掉。

    mode = "none"    :不剔(预注册要求「也报一次不剔的结果」)
    mode = "literal" :与**上一条原始观测**比(间隔 ≤ MAXGAP 天),比值越界的那一个币日剔掉(逐字读法)
    mode = "chained" :与**上一个存活日**比(间隔 ≤ 30 天),比值越界就剔,连续剔最多 CHAIN_CAP 个,
                       防止永久换算把整段历史剔光(实测 SUN / PAAL 这类币链式剔会剔掉 88% / 97% 的行)
    返回 (过滤后的 series, 过滤统计)。
    """
    if mode == "none":
        return series, {"mode": "none", "dropped_rows": 0, "symbols": 0}
    out: dict = {}
    stats = {"mode": mode, "dropped_rows": 0, "symbols": 0, "per_symbol": {},
             "dropped_by_gap": {}}
    for s, v in series.items():
        ds, cs = v["dates"], v["closes"]
        keep_d, keep_c = [], []
        anchor = None            # (date, price) 上一个存活日(chained 用)
        prev_raw = None         # (date, price) 上一条原始观测(literal 用)
        chain = 0
        for d, p in zip(ds, cs):
            p = apparatus._price(p)
            if p is None or p <= 0:
                continue
            ref = prev_raw if mode == "literal" else anchor
            max_gap = MAXGAP if mode == "literal" else 30
            bad = False
            gap = None
            if ref is not None:
                gap = (date.fromisoformat(d) - date.fromisoformat(ref[0])).days
                if 0 < gap <= max_gap:
                    ratio = p / ref[1]
                    if ratio > JUMP_HI or ratio < JUMP_LO:
                        if mode == "literal":
                            bad = True
                        else:
                            chain += 1
                            if chain <= CHAIN_CAP:
                                bad = True
                            else:
                                chain = 0
            if bad:
                stats["dropped_rows"] += 1
                stats["dropped_by_gap"][str(gap)] = stats["dropped_by_gap"].get(str(gap), 0) + 1
                per = stats["per_symbol"].setdefault(s, {"dropped": 0, "rows": len(ds),
                                                        "first": [], "last": []})
                per["dropped"] += 1
                if len(per["first"]) < 6:
                    per["first"].append(d)
                per["last"] = [d]
                prev_raw = (d, p)
                continue
            keep_d.append(d)
            keep_c.append(p)
            anchor = (d, p)
            prev_raw = (d, p)
            chain = 0
        if len(keep_d) < len(ds):
            stats["symbols"] += 1
        out[s] = {"dates": keep_d, "closes": keep_c}
    return out, stats


# ── 阶段 3:窗口 / 随机日对照 / 判据 ───────────────────────────────────────
def compute_windows(series: dict, basket: PitBasket, evs: list[dict],
                    binance: dict | None = None) -> list[dict]:
    out = []
    for e in evs:
        d0 = date.fromisoformat(e["d"])
        row = dict(e)
        ser = basket.ser.get(e["symbol"])
        dd0 = (d0 + timedelta(days=ENTRY_OFF)).isoformat()
        dd1 = (d0 + timedelta(days=EXIT_OFF)).isoformat()
        a = ser.price(dd0) if ser else None
        b = ser.price(dd1) if ser else None
        absr = apparatus.long_return(a, b) if (a is not None and b is not None) else None
        bench, nb = basket.ret(dd0, dd1)
        row["abs30"] = absr
        row["bench30"] = bench
        row["nb"] = nb
        row["rel30"] = None if (absr is None or bench is None) else absr - bench
        pd0 = (d0 + timedelta(days=PRE[0])).isoformat()
        pd1 = (d0 + timedelta(days=PRE[1])).isoformat()
        pa = ser.price(pd0) if ser else None
        pb = ser.price(pd1) if ser else None
        row["pre30"] = apparatus.long_return(pa, pb) if (pa is not None and pb is not None) else None
        row["has_price_10d"] = bool(ser and ser.has_price_within(
            e["d"], (d0 + timedelta(days=NO_PRICE_WINDOW)).isoformat()))
        if binance is not None:
            bl = binance.get(e["symbol"]) or []
            prior = [x for x in bl if x <= e["d"]]
            row["binance_first"] = bl[0] if bl else None
            row["binance_last_prior"] = prior[-1] if prior else None
            row["binance_active"] = bool(prior and
                                         (date.fromisoformat(e["d"]) -
                                          date.fromisoformat(prior[-1])).days <= BINANCE_LOOKBACK)
            row["binance_ever_before"] = bool(prior)
        out.append(row)
    return out


def eligible_dates(ser: Series) -> list[str]:
    out = []
    for d0 in ser.dates:
        a = ser.price((date.fromisoformat(d0) + timedelta(days=ENTRY_OFF)).isoformat())
        b = ser.price((date.fromisoformat(d0) + timedelta(days=EXIT_OFF)).isoformat())
        if a is not None and b is not None:
            out.append(d0)
    return out


def control(basket: PitBasket, evs: list[dict], eligible: dict,
            n: int = CONTROL_N, seed: int = CONTROL_SEED) -> np.ndarray:
    """随机日对照:同代号、同年随机日,1,000 次,种子 770;每次取各事件超额的中位数。"""
    pairs = [(e["symbol"], e["d"]) for e in evs]

    def _one(rng):
        draws = apparatus.random_dates_like(pairs, eligible, rng, stratum=lambda x: str(x)[:4])
        vals = []
        for (sym, _), (_, dd) in zip(pairs, draws):
            if dd is None:
                continue
            ser = basket.ser.get(sym)
            if ser is None:
                continue
            d0 = (date.fromisoformat(dd) + timedelta(days=ENTRY_OFF)).isoformat()
            d1 = (date.fromisoformat(dd) + timedelta(days=EXIT_OFF)).isoformat()
            a, b = ser.price(d0), ser.price(d1)
            if a is None or b is None:
                continue
            absr = apparatus.long_return(a, b)
            bench, _ = basket.ret(d0, d1)
            if absr is None or bench is None:
                continue
            vals.append(absr - bench)
        if not vals:
            return float("nan")
        return float(np.median(vals))

    return apparatus.null_distribution(_one, n, seed)


def summarize(rows: list[dict]) -> dict:
    vals = [r["rel30"] for r in rows if r.get("rel30") is not None]
    absv = [r["abs30"] for r in rows if r.get("rel30") is not None]
    nbs = [r["nb"] for r in rows if r.get("rel30") is not None]
    if not vals:
        return {"n": 0}
    v = np.array(vals, dtype=float)
    k = int(math.floor(len(v) * 0.10))
    vs = np.sort(v)
    trimmed = vs[k:len(vs) - k] if len(vs) - 2 * k >= 3 else vs
    return {"n": len(vals),
            "median_rel_pct": round(100 * float(np.median(v)), 3),
            "mean_rel_pct": round(100 * float(np.mean(v)), 3),
            "trimmed10_mean_rel_pct": round(100 * float(np.mean(trimmed)), 3),
            "p10_rel_pct": round(100 * float(np.percentile(v, 10)), 3),
            "p25_rel_pct": round(100 * float(np.percentile(v, 25)), 3),
            "p75_rel_pct": round(100 * float(np.percentile(v, 75)), 3),
            "p90_rel_pct": round(100 * float(np.percentile(v, 90)), 3),
            "median_abs_pct": round(100 * float(np.median(absv)), 3),
            "mean_abs_pct": round(100 * float(np.mean(absv)), 3),
            "neg_rate": round(float(np.mean(v < 0)), 3),
            "nb_median": int(np.median(nbs)) if nbs else None}


def judge(rows: list[dict], basket: PitBasket, eligible: dict, label: str,
          report_only: bool = False, era_controls: bool = True) -> dict:
    """判据(S-782):**主判 = 2017–2021 段**:该段中位 < 0 且该段分位 ≤ 0.05。
    全样本三条判据(中位 < 0、分位 ≤ 0.05、两段同号)重报。"""
    have = [r for r in rows if r.get("rel30") is not None]
    s = summarize(rows)
    out = {"label": label, **s}
    if not have:
        out["verdict"] = "NO_DATA"
        return out
    med = float(np.median([r["rel30"] for r in have]))
    out["median_rel_pct_exact"] = med
    try:
        null = control(basket, have, eligible)
        pct = apparatus.percentile_of(med, null)
        out["control_percentile"] = pct
        out["control_n"] = int(len(null))
        out["control_median_pct"] = round(100 * float(np.median(null)), 3)
        out["control_p05_pct"] = round(100 * float(np.percentile(null, 5)), 3)
        out["control_p95_pct"] = round(100 * float(np.percentile(null, 95)), 3)
        out["control_mean_pct"] = round(100 * float(np.mean(null)), 3)
        out["control_p10_pct"] = round(100 * float(np.percentile(null, 10)), 3)
        out["control_p90_pct"] = round(100 * float(np.percentile(null, 90)), 3)
        out["_pct"] = pct
    except apparatus.NoOpNull as exc:
        out["control_error"] = str(exc)
        out["_pct"] = None

    # 两段 + 每段自己的对照分位(S-782 主判要看 2017–2021 段的分位)
    segs = {}
    for name, lo, hi in ERAS:
        sub = [r for r in have if lo <= r["d"] <= hi]
        sm = summarize(sub)
        if sm.get("n") and era_controls:
            try:
                med_sub = float(np.median([r["rel30"] for r in sub]))
                nsub = control(basket, sub, eligible)
                sm["control_percentile"] = apparatus.percentile_of(med_sub, nsub)
                sm["control_n"] = int(len(nsub))
                sm["control_median_pct"] = round(100 * float(np.median(nsub)), 3)
            except apparatus.NoOpNull as exc:
                sm["control_error"] = str(exc)
        segs[name] = sm
    out["eras"] = segs
    seg_medians = [segs[n]["median_rel_pct"] for n, _, _ in ERAS if segs[n].get("n")]
    same_sign = len(seg_medians) == len(ERAS) and (all(m < 0 for m in seg_medians)
                                                   or all(m > 0 for m in seg_medians))
    out["eras_same_sign_negative"] = bool(same_sign and all(m < 0 for m in seg_medians))
    pct = out.pop("_pct", None)
    prim = segs.get(PRIMARY_ERA, {})
    prim_med = prim.get("median_rel_pct")
    prim_pct = prim.get("control_percentile")
    out["primary_era"] = PRIMARY_ERA
    out["primary_criterion"] = "该段中位 < 0 且该段随机日对照分位 ≤ 0.05"
    if report_only:
        out["verdict"] = "REPORT_ONLY(预注册:另报不判)"
    else:
        full_ok = (med < 0 and pct is not None and pct <= 0.05
                   and out["eras_same_sign_negative"])
        prim_ok = (prim_med is not None and prim_med < 0
                   and prim_pct is not None and prim_pct <= 0.05)
        out["full_sample_criteria"] = {
            "median_lt_0": bool(med < 0), "percentile_le_0.05": bool(
                pct is not None and pct <= 0.05),
            "eras_same_sign_negative": out["eras_same_sign_negative"]}
        out["primary_era_criteria"] = {
            "median_lt_0": bool(prim_med is not None and prim_med < 0),
            "percentile_le_0.05": bool(prim_pct is not None and prim_pct <= 0.05)}
        out["verdict_full_sample"] = "CONFIRMED" if full_ok else "NOT_CONFIRMED"
        out["verdict_primary_era"] = "CONFIRMED" if prim_ok else "NOT_CONFIRMED"
        out["verdict"] = out["verdict_primary_era"]
    return out


def stratify(rows: list[dict], basket: PitBasket, eligible: dict) -> dict:
    out: dict = {}
    bin_grp = {}
    for flag, name in ((True, "已在Binance现货"), (False, "不在Binance现货")):
        sub = [r for r in rows if r.get("binance_active") is flag]
        bin_grp[name] = summarize(sub)
    out["binance_spot"] = bin_grp
    pre = [(r["pre30"], r) for r in rows if r.get("pre30") is not None]
    if pre:
        vals = np.array([p for p, _ in pre], dtype=float)
        q1, q2 = float(np.percentile(vals, 33.333)), float(np.percentile(vals, 66.667))
        buckets = {"低(前33%)": [], "中(33-67%)": [], "高(后33%)": []}
        for p, r in pre:
            k = "低(前33%)" if p <= q1 else ("中(33-67%)" if p <= q2 else "高(后33%)")
            buckets[k].append(r)
        out["pre30_tercile"] = {"cuts_pct": [round(100 * q1, 2), round(100 * q2, 2)],
                                "groups": {k: summarize(v) for k, v in buckets.items()}}
    return out


def coverage(rows: list[dict]) -> dict:
    n = len(rows)
    priced = [r for r in rows if r.get("rel30") is not None]
    return {"events": n, "priced": len(priced),
            "no_price_10d": sum(1 for r in rows if not r.get("has_price_10d")),
            "priced_share": round(len(priced) / n, 3) if n else None}


def era_splits(rows: list[dict]) -> dict:
    out = {}
    for name, lo, hi in ERAS:
        out[name] = sum(1 for r in rows if lo <= r["d"] <= hi)
    return out


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["events", "all"], default="all")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    ev = build_event_list(refresh=args.refresh)
    if args.stage == "events":
        return

    print("[prices] asset_mcap_daily(全球价) …", flush=True)
    mcap_rows = _fetch_all("asset_mcap_daily", "symbol,d,price", "",
                            "symbol.asc,d.asc", "symbol", workers=8,
                            cache_name="asset_mcap_daily.json", refresh=args.refresh)
    series_raw = build_series(mcap_rows, "d", "price")
    print(f"[prices] asset_mcap_daily: {len(mcap_rows)} 行 / {len(series_raw)} 个代号")
    dup = len(mcap_rows) - sum(len(v["dates"]) for v in series_raw.values())
    print(f"[prices] 同一 (symbol,d) 多源而被去掉的行: {dup}")

    print("[prices] ohlcv_daily(binance_hist,只为「公告时是否已在 Binance 现货」) …", flush=True)
    bh_rows = _fetch_all("ohlcv_daily", "symbol,trade_date,close", "source=eq.binance_hist",
                          "symbol.asc,trade_date.asc", "id", workers=8,
                          cache_name="ohlcv_binance_hist.json", refresh=args.refresh)
    binance: dict[str, list[str]] = collections.defaultdict(list)
    bh_dates = collections.defaultdict(set)
    for r in bh_rows:
        if r.get("close") is None:
            continue
        bh_dates[r["symbol"]].add(r["trade_date"])
    for s, ds in bh_dates.items():
        binance[s] = sorted(ds)
    print(f"[prices] binance_hist: {len(bh_rows)} 行 / {len(binance)} 个代号")

    res = {"meta": {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "task": "T-300", "ledger": "S-782",
                    "criterion_primary": ("只看 2017–2021 段:该段 30 天超额中位 < 0 且该段随机日对照"
                                          "分位 ≤ 0.05 ⇒ 「早期段也站住」"),
                    "criterion_full": ("全样本三条:中位 < 0、分位 ≤ 0.05、两段同号"),
                    "control": {"n": CONTROL_N, "seed": CONTROL_SEED,
                                "mode": "同代号、同年随机日(apparatus.random_dates_like),每次取各事件超额的中位数"},
                    "price_source": "asset_mcap_daily(全球价)",
                    "basket_filter": {"rule": "单日价格比 > 100 或 < 0.01 的币日剔掉",
                                      "jump_hi": JUMP_HI, "jump_lo": JUMP_LO,
                                      "chain_cap": CHAIN_CAP, "maxgap": MAXGAP},
                    "entry_exit": f"d+{ENTRY_OFF} 收盘 → d+{EXIT_OFF} 收盘"},
           "event_counts": ev["counts"],
           "sources": {"asset_mcap_daily": {"rows": len(mcap_rows), "symbols": len(series_raw),
                                            "dup_dropped": dup},
                       "binance_hist": {"rows": len(bh_rows), "symbols": len(binance)}},
           "variants": {}}

    # ── 三个篮变体:chained(主,判)/ literal(逐字读法)/ none(预注册要求的不剔) ──
    for vmode, vlabel in (("chained", "主口径(链式剔币日)"),
                           ("literal", "逐字读法(只剔比值越界的那一个币日)"),
                           ("none", "不剔(S-782 要求也报一次)")):
        t0 = time.time()
        series_basket, fstats = filter_jumps(series_raw, vmode)
        basket = PitBasket(series_basket)
        sc = basket.selfcheck()
        print(f"[basket:{vmode}] 自检 {sc} / 剔掉 {fstats.get('dropped_rows')} 币日"
              f" / {fstats.get('symbols')} 个代号 / {time.time() - t0:.0f}s", flush=True)

        eligible: dict[str, list[str]] = {}
        for arm in ("listing_krw", "listing_krw_null", "delisting", "warning"):
            for e in ev["arms"][arm]:
                ser = basket.ser.get(e["symbol"])
                if ser is None:
                    continue
                if e["symbol"] not in eligible:
                    eligible[e["symbol"]] = eligible_dates(ser)
        print(f"[control:{vmode}] 抽样池: {len(eligible)} 个代号", flush=True)

        vres = {"label": vlabel, "filter": fstats, "basket_selfcheck": sc,
                "arms": {}, "coverage": {}, "strata": {}, "eras_event_counts": {}}
        for arm, label, ro in (("listing_krw", "Upbit KRW 首次上币(判)", False),
                                ("listing_krw_null", "Upbit krw 为空的公告(单列只报)", True),
                                ("delisting", "Upbit 下架(只报不判)", True),
                                ("warning", "Upbit 유의 종목 지정(只报不判)", True)):
            rows = compute_windows(series_basket, basket, ev["arms"][arm], binance=binance)
            j = judge(rows, basket, eligible, label, report_only=ro,
                      era_controls=(arm == "listing_krw"))
            vres["arms"][arm] = j
            vres["coverage"][arm] = coverage(rows)
            vres["strata"][arm] = stratify(rows, basket, eligible)
            vres["eras_event_counts"][arm] = era_splits(rows)
            print(f"[arm:{vmode}] {arm}: n={j.get('n')} median={j.get('median_rel_pct')} "
                  f"mean={j.get('mean_rel_pct')} p10={j.get('p10_rel_pct')} "
                  f"p90={j.get('p90_rel_pct')} pct={j.get('control_percentile')} "
                  f"prim={j.get('eras', {}).get(PRIMARY_ERA, {}).get('control_percentile')} "
                  f"verdict={j.get('verdict')}", flush=True)
            vres.setdefault("per_event", {})[arm] = [
                {k: r.get(k) for k in ("symbol", "d", "abs30", "bench30", "rel30", "pre30",
                                       "has_price_10d", "binance_active", "sym_source")}
                for r in rows]
        res["variants"][vmode] = vres

    # ── 与 T-291 的对比 ───────────────────────────────────────────────────
    try:
        old = json.load(open(os.path.join(HERE, "t291_results.json")))
        old_krw = old["arms"]["listing_krw"]
        res["t291_comparison"] = {
            "t291_events": old["event_counts"]["listing_krw_events_kept"],
            "t291_priced_n": old_krw["n"],
            "t291_median_rel_pct": old_krw["median_rel_pct"],
            "t291_mean_rel_pct": old_krw["mean_rel_pct"],
            "t291_p10_rel_pct": old_krw["p10_rel_pct"],
            "t291_p90_rel_pct": old_krw["p90_rel_pct"],
            "t291_control_percentile": old_krw["control_percentile"],
            "t291_eras": {k: v.get("median_rel_pct") for k, v in old_krw.get("eras", {}).items()},
            "t291_eras_n": {k: v.get("n") for k, v in old_krw.get("eras", {}).items()}}
    except Exception as exc:      # noqa: BLE001
        res["t291_comparison"] = {"error": repr(exc)}

    with open(OUT_RESULTS, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"[out] {OUT_RESULTS}")


if __name__ == "__main__":
    main()
