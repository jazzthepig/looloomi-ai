"""T-238 v2(S-719 重验 · 闸门已开):R-v2 在**同质永续序列** `perp_bv_daily` 上重生成票,
与 10-21 缓存(770 张)逐票对比,重报 S-638 的钱曲线与 S-677 的 OOS 切片,并报 10-19 起的信号数。

v2 变更(Jazz 11-05 闸门):v1 读 `ohlcv_daily(source=binance_um_hist)` —— 那是「现货历史 + 永续续写」的
拼接序列,历史有洞,v1 判 ❌。v2 直接读 `perp_bv_daily`(真永续,668,222 行,min(d)=2019-12-31),
宇宙 = `perp_bv_pairs.kind='coin'`(外加 kind 为空但 dead_from 有值的),成交额 dv = qv(quote volume)。

只读:不改代码、不做 DDL、不入库。DB 只读 perp_bv_daily / perp_bv_pairs / style_index_pit_daily。
用法:python3 docs/research/t238_rv2_um.py [--stage all|fetch]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local")
MAC_DIR = os.path.join(ROOT, "research", "t238")
PBV_JSONL = os.path.join(MAC_DIR, "_bars_pbv.jsonl")
PAIRS_JSONL = os.path.join(MAC_DIR, "_pairs_pbv.json")
PBV_UNI: dict = {}
DB_JSONL = os.path.join(ROOT, "research", "t237", "_bars_db.jsonl")
CACHE_TK = os.path.join(ROOT, "research", "t159", "_tickets_2020-03-01_2026-06-20.json")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

# ── 预注册常量(先写后算) ─────────────────────────────────────────────────────
SIG_FROM, SIG_TO = "2020-03-01", "2026-10-31"   # 票生成窗(卡上写死)
CURVE_TO = "2026-10-31"                          # 钱曲线终点
FETCH_FROM, FETCH_TO = "2019-10-01", "2026-11-04"   # DB 拉取窗(卡上写死;数据实际到 11-03)
COST = 0.004                                    # 来回成本(t159 逐字)
F_RISK = 0.01                                   # 钱曲线每笔 1%(S-638 的 f★)
CAP = 10                                        # 同时最多 10 张
SPLIT = "2026-08-08"                            # 量纲断点(T-237):断点前后分开计数
OOS_FROM, OOS_TO = "2018-01-01", "2020-02-29"   # S-677 的 OOS 年份口径(照 s677_rv2_oos.py 原文)
FWD_FROM = "2026-10-19"                         # 缓存的最后一天 = 前向起点
WARMUP = 220                                    # t159.run_long 的起始下标(200 日均 + ATR/adv 预热)


# ── DB 只读 ──────────────────────────────────────────────────────────────────
def _rest(q: str, lo: int, hi: int, count: bool = False):
    k = os.environ["SUPABASE_KEY"]
    h = {"apikey": k, "Authorization": "Bearer " + k, "Range": f"{lo}-{hi}"}
    if count:
        h["Prefer"] = "count=exact"
    r = urllib.request.Request(os.environ["SUPABASE_URL"] + "/rest/v1/" + q, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read()), resp.headers.get("Content-Range", "")
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return [], ""
        raise


def fetch_pbv() -> dict:
    """拉 `perp_bv_daily`(真永续日线)。分片并行:按 `perp_bv_pairs` 的符号表切片,每片一条
    `symbol=in.(...)` 查询,片内翻页带 order=symbol.asc,d.asc(卡上要求)。
    落 _bars_pbv.jsonl(每行一个 JSON),写明拉取时间与行数。
    覆盖校验:各片行数合计必须等于表的 count(=668,222),不等则报错退出(不落半份)。"""
    os.makedirs(MAC_DIR, exist_ok=True)
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    base = ("perp_bv_daily?select=symbol,d,o,h,l,c,qv,tbqv"
            f"&d=gte.{FETCH_FROM}&d=lte.{FETCH_TO}&order=symbol.asc,d.asc")
    _, cr = _rest(base, 0, 0, count=True)
    total = int(cr.split("/")[-1]) if "/" in cr else -1
    if total < 0:
        raise SystemExit("no Content-Range total; cannot page deterministically")
    pmeta = fetch_pairs()
    prows = json.load(open(PAIRS_JSONL)).get("rows", [])
    allsyms = sorted(set(r.get("symbol") for r in prows if r.get("symbol")))
    syms = [s for s in allsyms if not any(ch in s for ch in ",()'\"% ")]
    skipped = [s for s in allsyms if s not in set(syms)]
    chunk = 12
    chunks = [syms[i:i + chunk] for i in range(0, len(syms), chunk)]

    def pull(idx_ch):
        idx, ch = idx_ch
        sel = ",".join(ch)
        q = ("perp_bv_daily?select=symbol,d,o,h,l,c,qv,tbqv"
             f"&symbol=in.({sel})&d=gte.{FETCH_FROM}&d=lte.{FETCH_TO}&order=symbol.asc,d.asc")
        path = os.path.join(MAC_DIR, f"_pbv_part_{idx:03d}.jsonl")
        n = 0
        with open(path, "w") as f:
            lo = 0
            while True:
                rows, _ = _rest(q, lo, lo + 999)
                if not rows:
                    break
                f.write(json.dumps(rows) + "\n")
                n += len(rows)
                lo += len(rows)
        return idx, n

    with ThreadPoolExecutor(max_workers=10) as ex:
        got = list(ex.map(pull, list(enumerate(chunks))))
    n = sum(c for _, c in got)
    if n != total:
        raise SystemExit(f"parallel fetch rows {n} != table count {total} —— 不落半份(需补齐)")
    with open(PBV_JSONL, "w") as f:
        f.write(json.dumps({"_meta": {"fetched_at_utc": fetched_at, "query": base,
                                      "expected_rows": total, "page_step": 1000,
                                      "n_symbols": len(syms), "n_chunks": len(chunks),
                                      "note": "one JSON object per line: symbol,d,o,h,l,c,qv,tbqv"}}) + "\n")
        for idx, _ in sorted(got):
            part = os.path.join(MAC_DIR, f"_pbv_part_{idx:03d}.jsonl")
            for line in open(part):
                f.write(line)
            os.remove(part)
    meta = {"fetched_at_utc": fetched_at, "rows_written": n, "expected_rows": total,
            "file": PBV_JSONL, "query": base, "n_symbols": len(syms), "n_chunks": len(chunks),
            "parallel_workers": 10, "coverage_ok": True, "skipped_symbols": skipped}
    meta["pairs"] = pmeta
    print(json.dumps(meta), file=sys.stderr)
    return meta


def fetch_pairs() -> dict:
    """`perp_bv_pairs`:宇宙 = kind='coin' 或 (kind 为空 且 dead_from 有值)。
    先按窄 select 试;失败则 select=* 全列(列名以实际返回为准)。"""
    def page(q):
        rows, lo = [], 0
        while True:
            rr, _ = _rest(q, lo, lo + 999)
            rows += rr
            if len(rr) < 1000:
                break
            lo += 1000
        return rows
    q = "perp_bv_pairs?select=symbol,kind,dead_from&order=symbol.asc"
    try:
        rows, narrow = page(q), True
    except urllib.error.HTTPError as e:
        print(f"  pairs narrow select failed ({e.code}); fallback select=*", file=sys.stderr)
        q = "perp_bv_pairs?select=*&order=symbol.asc"
        rows, narrow = page(q), False
    meta = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "n_rows": len(rows), "query": q, "narrow_select": narrow,
            "columns": sorted(rows[0].keys()) if rows else [], "file": PAIRS_JSONL}
    json.dump({"meta": meta, "rows": rows}, open(PAIRS_JSONL, "w"))
    print(json.dumps(meta), file=sys.stderr)
    return meta

def load_style_gate_db() -> dict:
    """DB 的 style_index_pit_daily(majors / cap 权重)→ 与 t159.load_gate() 同口径的闸门字典。"""
    rows = []
    lo = 0
    while True:
        rr, _ = _rest("style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap"
                       "&order=d.asc", lo, lo + 999)
        rows += rr
        if len(rr) < 1000:
            break
        lo += 1000
    rows = [x for x in rows if x["ret"] is not None and x["ret"] > -0.95]
    rows.sort(key=lambda x: x["d"])
    lvl, cur = [], 1.0
    for x in rows:
        cur *= (1.0 + x["ret"])
        lvl.append(cur)
    g = {}
    for i, x in enumerate(rows):
        n = min(i + 1, 200)
        w = t159.win(lvl, i, 0, 199)
        g[x["d"]] = dict(n=n, lvl=lvl[i], ma200=w,
                         gate_open=bool(n < 200 or lvl[i] > w),
                         gate_closed=bool(n >= 200 and lvl[i] <= w))
    return {"gate": g, "n_rows": len(rows), "d0": rows[0]["d"] if rows else None,
            "d1": rows[-1]["d"] if rows else None}


# ── 序列读取 ────────────────────────────────────────────────────────────────
def _read_jsonl(path: str) -> dict[str, list]:
    """ohlcv_daily 口径行:(trade_date, o, h, l, c, volume)。"""
    by = defaultdict(list)
    with open(path) as f:
        for line in f:
            x = json.loads(line)
            if isinstance(x, dict) and "_meta" in x:
                continue
            for r in (x if isinstance(x, list) else [x]):
                by[r["symbol"]].append((r["trade_date"], float(r["open"]), float(r["high"]),
                                        float(r["low"]), float(r["close"]), float(r["volume"])))
    return {s: sorted(set(v)) for s, v in by.items() if v}


def _read_jsonl_pbv(path: str) -> dict[str, list]:
    """perp_bv_daily 行:(symbol, d, o, h, l, c, qv, tbqv)。
    第 6 位存 qv/close ⇒ 下游 `close × row[5]` 恒 = qv(成交额),与现货侧 close×volume 同量纲;
    dv = qv 就是卡上 v2 要求的口径。"""
    by = defaultdict(list)
    with open(path) as f:
        for line in f:
            x = json.loads(line)
            if isinstance(x, dict) and "_meta" in x:
                continue
            for r in (x if isinstance(x, list) else [x]):
                c = float(r["c"] or 0.0)
                qv = float(r["qv"] or 0.0)
                by[r["symbol"]].append((r["d"], float(r["o"] or 0.0), float(r["h"] or 0.0),
                                        float(r["l"] or 0.0), c, (qv / c) if c else 0.0))
    return {s: sorted(set(v)) for s, v in by.items() if v}


def load_pbv_universe() -> dict:
    """`perp_bv_pairs` 宇宙:kind='coin' 或 (kind 为空 且 dead_from 有值)。"""
    data = json.load(open(PAIRS_JSONL))
    rows = data.get("rows", [])
    keep, kinds = {}, defaultdict(int)
    for r in rows:
        s = (r.get("symbol") or r.get("base") or r.get("pair") or r.get("s"))
        k = (r.get("kind") or "").strip().lower()
        df = r.get("dead_from")
        kinds[k or "(null)"] += 1
        if s is None:
            continue
        if k == "coin" or (not k and df):
            keep[s] = r
    return {"n_rows": len(rows), "n_keep": len(keep), "kind_hist": dict(kinds),
            "keep_syms": set(keep),   # 供 load_pbv_raw 过滤;不进 PBV_UNI(结果 JSON 只留计数)
            "n_keep_null_kind_with_dead_from": sum(1 for r in keep.values()
                                                   if not (r.get("kind") or "").strip())}


def load_pbv_raw() -> dict[str, list]:
    raw = _read_jsonl_pbv(PBV_JSONL)
    uni = load_pbv_universe()
    keep_syms = uni.pop("keep_syms")
    kept = {s: v for s, v in raw.items() if s in keep_syms}
    PBV_UNI.clear()
    PBV_UNI.update(uni)
    PBV_UNI["n_symbols_before_filter"] = len(raw)
    PBV_UNI["n_symbols_after_filter"] = len(kept)
    PBV_UNI["n_symbols_dropped_by_filter"] = len(raw) - len(kept)
    return kept

def load_cache_raw() -> dict[str, list]:
    """本地缓存(t156/_bars{,_early}.jsonl + t159/_bars.jsonl)。"""
    by = defaultdict(list)
    for d in (t159.T156, t159.ENV):
        for fn in (f"{d}_bars_early.jsonl", f"{d}_bars.jsonl"):
            if not os.path.exists(fn):
                continue
            for line in open(fn):
                for x in json.loads(line):
                    by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                            float(x["low"]), float(x["close"]), float(x["volume"])))
    return {s: sorted(set(v)) for s, v in by.items() if v}


def to_bars(raw: dict[str, list]) -> dict[str, list]:
    """t159 行结构:(trade_date, o, h, l, c, 成交额 = close × volume);EXCL 过滤。"""
    out = {}
    for s, v in raw.items():
        if s in t159.EXCL:
            continue
        rows = sorted({(d, o, h, l, c, c * vol) for d, o, h, l, c, vol in v})
        if rows:
            out[s] = rows
    return out


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _median_str(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else s[n // 2 - 1]


def _quant(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


# ── ① 序列两两对比 ─────────────────────────────────────────────────────────
def compare_series(a_raw: dict[str, list], b_raw: dict[str, list], name_a: str, name_b: str) -> dict:
    """按 (symbol, d) 对齐:收盘相对差中位、成交额比值中位。断点 2026-08-08 前后分开。"""
    buckets = {"pre": {"px": [], "to": [], "n": 0}, "post": {"px": [], "to": [], "n": 0},
               "all": {"px": [], "to": [], "n": 0}}
    per_symbol = {}
    for s in set(a_raw) & set(b_raw):
        A = {r[0]: r for r in a_raw[s]}
        B = {r[0]: r for r in b_raw[s]}
        common = sorted(set(A) & set(B))
        if not common:
            continue
        px, to = [], []
        for d in common:
            a, b = A[d], B[d]
            if a[4] and b[4]:
                px.append(abs(a[4] - b[4]) / b[4])
            ta, tb = a[4] * a[5], b[4] * b[5]
            if ta and tb:
                to.append(ta / tb)
        per_symbol[s] = {"n": len(common), "px_med": round(_median(px), 8) if px else None,
                         "to_med": round(_median(to), 4) if to else None}
        for d in common:
            k = "post" if d >= SPLIT else "pre"
            a, b = A[d], B[d]
            if a[4] and b[4]:
                buckets[k]["px"].append(abs(a[4] - b[4]) / b[4])
                buckets["all"]["px"].append(abs(a[4] - b[4]) / b[4])
            ta, tb = a[4] * a[5], b[4] * b[5]
            if ta and tb:
                buckets[k]["to"].append(ta / tb)
                buckets["all"]["to"].append(ta / tb)
            buckets[k]["n"] += 1
            buckets["all"]["n"] += 1

    def agg(b):
        return {"n": b["n"],
                "close_rel_diff_median": round(_median(b["px"]), 8) if b["px"] else None,
                "close_rel_diff_p95": round(_quant(b["px"], 0.95), 8) if b["px"] else None,
                "turnover_ratio_median": round(_median(b["to"]), 4) if b["to"] else None,
                "turnover_ratio_p25": round(_quant(b["to"], 0.25), 4) if b["to"] else None,
                "turnover_ratio_p75": round(_quant(b["to"], 0.75), 4) if b["to"] else None}
    ratios = [v["to_med"] for v in per_symbol.values() if v["to_med"] is not None]
    # 月度中位比值(找量纲断点)
    monthly = defaultdict(lambda: {"to": [], "px": [], "n": 0})
    for s in set(a_raw) & set(b_raw):
        A = {r[0]: r for r in a_raw[s]}
        B = {r[0]: r for r in b_raw[s]}
        for d in set(A) & set(B):
            a, b = A[d], B[d]
            m = d[:7]
            ta, tb = a[4] * a[5], b[4] * b[5]
            if ta and tb:
                monthly[m]["to"].append(ta / tb)
            if a[4] and b[4]:
                monthly[m]["px"].append(abs(a[4] - b[4]) / b[4])
            monthly[m]["n"] += 1
    mtab = {m: {"n": v["n"], "turnover_ratio_median": round(_median(v["to"]), 4) if v["to"] else None,
                "close_rel_diff_median": round(_median(v["px"]), 8) if v["px"] else None}
            for m, v in sorted(monthly.items())}
    return {"pair": f"{name_a} vs {name_b}",
            "symbols_common": len(per_symbol),
            "pre_2026_08_08": agg(buckets["pre"]), "post_2026_08_08": agg(buckets["post"]),
            "all": agg(buckets["all"]),
            "by_month": mtab,
            "per_symbol_turnover_ratio_median": round(_median(ratios), 4) if ratios else None,
            "n_symbols_ratio_outside_0.5_2": sum(1 for r in ratios if r < 0.5 or r > 2),
            "n_symbols_ratio_exactly_1": sum(1 for r in ratios if r == 1.0)}


# ── ② 票生成与对比 ─────────────────────────────────────────────────────────
def gen_tickets(bars: dict[str, list], gate: dict, d_from: str, d_to: str) -> list:
    return t159.run_long(bars, gate, d_from, d_to)


def last_close_at(bars: dict, sym: str, d_to: str):
    rows = bars.get(sym) or []
    c = [r[4] for r in rows if r[0] <= d_to]
    return c[-1] if c else None


def mtm(tickets, bars, d_to=CURVE_TO):
    """仍持有的票按 d_to 前最后收盘盯市(两边同一 d_to,公平)。"""
    for t in tickets:
        if t.get("r") is None:
            c = last_close_at(bars, t["symbol"], d_to)
            if c is None:
                continue
            t["r"] = (c - t["entry_px"]) / (t["entry_px"] - t["stop_px"]) - COST * t["entry_px"] / (
                t["entry_px"] - t["stop_px"])
            t["still"] = True
    return tickets


def summarise(tickets, bars, d_to=CURVE_TO) -> dict:
    rs = [t["r"] for t in tickets if t.get("r") is not None]
    curve = list(t159.nav(tickets, bars, F_RISK, cap=CAP, d_to=d_to))
    st = t159.stats(curve) if curve else None
    out = {"n": len(tickets), "n_with_r": len(rs),
           "total_r": round(sum(rs), 4) if rs else 0.0,
           "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
           "win": round(sum(r > 0 for r in rs) / len(rs), 4) if rs else None,
           "still_open": sum(1 for t in tickets if t.get("still"))}
    if st:
        mdd = st["mdd"]
        out["nav"] = {"d0": st["d0"], "d1": st["d1"], "end": round(st["end"], 6),
                      "annualised": st["annualised"], "mdd": mdd,
                      "calmar": (st["annualised"] / abs(mdd)) if (st["annualised"] and mdd) else None,
                      "nominal_peak": st["peak_gross"],
                      "taken": st["taken"], "skipped": st["skipped"], "closed": st["closed"]}
    return out


def _key(t):
    return (t["symbol"], t["signal_d"])


def compare_tickets(tk_a: list, tk_b: list, name_a: str, name_b: str) -> dict:
    """键 = (symbol, signal_d)。断点 2026-08-08 前后分开计数。"""
    A = {_key(t): t for t in tk_a}
    B = {_key(t): t for t in tk_b}
    keys = sorted(set(A) | set(B))

    def agg(tks):
        rs = [t["r"] for t in tks if t.get("r") is not None]
        return {"n": len(tks), "total_r": round(sum(rs), 4) if rs else 0.0,
                "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
                "win": round(sum(r > 0 for r in rs) / len(rs), 4) if rs else None}

    def win_bucket(lo, hi):
        ks = [k for k in keys if lo <= k[1] <= hi]
        both = [k for k in ks if k in A and k in B]
        only_a = [k for k in ks if k in A and k not in B]
        only_b = [k for k in ks if k in B and k not in A]
        pa = [(A[k]["r"], B[k]["r"]) for k in both
              if A[k].get("r") is not None and B[k].get("r") is not None]
        rstat = {"n_pairs": len(pa)}
        if len(pa) >= 3:
            xs = [p[0] for p in pa]
            ys = [p[1] for p in pa]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            cov = sum((a - mx) * (b - my) for a, b in pa)
            vx = sum((a - mx) ** 2 for a in xs) ** 0.5
            vy = sum((b - my) ** 2 for b in ys) ** 0.5
            dr = [abs(b - a) for a, b in pa]
            rstat.update({"corr_r": round(cov / (vx * vy), 6) if (vx and vy) else None,
                          "mean_abs_diff": round(sum(dr) / len(dr), 4),
                          "median_abs_diff": round(_median(dr), 4),
                          "max_abs_diff": round(max(dr), 4),
                          "sign_flip": sum(1 for a, b in pa if (a > 0) != (b > 0)),
                          "total_a_r": round(sum(xs), 4), "total_b_r": round(sum(ys), 4),
                          "mean_a_r": round(mx, 4), "mean_b_r": round(my, 4)})
        return {"window": [lo, hi],
                "n_a": len([k for k in ks if k in A]), "n_b": len([k for k in ks if k in B]),
                "n_both": len(both), "n_only_a": len(only_a), "n_only_b": len(only_b),
                "a_only": agg([A[k] for k in only_a]), "b_only": agg([B[k] for k in only_b]),
                "both": agg([A[k] for k in both]), "r_pairing": rstat}

    only_a_all = sorted(set(A) - set(B))
    only_b_all = sorted(set(B) - set(A))
    # 月度:票数与总 R 的差(卡上要求列出差在哪些月)
    mo = defaultdict(lambda: {"n_a": 0, "n_b": 0, "n_both": 0, "r_a": 0.0, "r_b": 0.0,
                              "r_a_only": 0.0, "r_b_only": 0.0})
    for k in keys:
        m = k[1][:7]
        if k in A:
            mo[m]["n_a"] += 1
            mo[m]["r_a"] += (A[k].get("r") or 0.0)
        if k in B:
            mo[m]["n_b"] += 1
            mo[m]["r_b"] += (B[k].get("r") or 0.0)
        if k in A and k in B:
            mo[m]["n_both"] += 1
        elif k in A:
            mo[m]["r_a_only"] += (A[k].get("r") or 0.0)
        else:
            mo[m]["r_b_only"] += (B[k].get("r") or 0.0)
    by_month = {m: dict(v, r_a=round(v["r_a"], 3), r_b=round(v["r_b"], 3),
                         r_a_only=round(v["r_a_only"], 3), r_b_only=round(v["r_b_only"], 3),
                         d_n=v["n_a"] - v["n_b"], d_r=round(v["r_a"] - v["r_b"], 3))
                 for m, v in sorted(mo.items())}
    out = {"pair": f"{name_a} vs {name_b}",
           "all": win_bucket("0000-01-01", "9999-12-31"),
           "pre_split": win_bucket("0000-01-01", "2026-08-07"),
           "post_split": win_bucket("2026-08-08", "9999-12-31"),
           "by_month": by_month,
           "only_a_list": [{"symbol": k[0], "signal_d": k[1], "r": A[k]["r"]} for k in only_a_all[:400]],
           "only_b_list": [{"symbol": k[0], "signal_d": k[1], "r": B[k]["r"]} for k in only_b_all[:400]]}
    # 同键占比(卡上的判据):pre 分段里同键票 / a 侧票数
    for seg in ("pre_split", "post_split", "all"):
        s = out[seg]
        s["same_key_share_of_a"] = round(s["n_both"] / s["n_a"], 4) if s["n_a"] else None
    return out


def warmup_attribution(tk_cache, tk_pbv, pbv_bars, cache_bars) -> dict:
    """缓存有、pbv 没有的票:为什么没有?按 (a) 符号不在 pbv (b) pbv 里该符号历史不够 220 根
    (c) 信号日早于该符号在 pbv 上的第 220 根(预热不足) (d) 预热够了但仍缺(指标差异)分。"""
    pbv_keys = {_key(t) for t in tk_pbv}
    only_cache = [t for t in tk_cache if _key(t) not in pbv_keys]
    buckets = defaultdict(lambda: {"n": 0, "total_r": 0.0, "sample": []})
    for t in only_cache:
        s, d = t["symbol"], t["signal_d"]
        rows = pbv_bars.get(s)
        if rows is None:
            k = "symbol_absent_in_pbv"
        elif len(rows) <= WARMUP:
            k = "symbol_too_short_in_pbv"
        elif d < rows[WARMUP][0]:
            k = "warmup_window"
        else:
            k = "indicator_diff_after_warmup"
        buckets[k]["n"] += 1
        buckets[k]["total_r"] += (t.get("r") or 0.0)
        if len(buckets[k]["sample"]) < 12:
            buckets[k]["sample"].append({"symbol": s, "signal_d": d, "r": t.get("r")})
    out = {"n_only_cache": len(only_cache), "by_reason": {}}
    for k, v in sorted(buckets.items()):
        out["by_reason"][k] = {"n": v["n"], "total_r": round(v["total_r"], 4), "sample": v["sample"]}
    # 符号层面的历史长度对照
    def hist(bars):
        firsts = sorted(r[0][0] for r in bars.values())
        lens = sorted(len(r) for r in bars.values())
        return {"symbols": len(bars), "median_first_d": _median_str(firsts), "p95_first_d": firsts[int(0.95 * (len(firsts) - 1))],
                "median_rows": _median(lens), "n_le_220": sum(1 for x in lens if x <= WARMUP)}
    out["history_pbv"] = hist(pbv_bars)
    out["history_cache"] = hist(cache_bars)
    return out


def money_window(tickets, bars, lo, hi) -> dict:
    """票按 signal_d 落在 [lo, hi] 的子集的钱曲线。"""
    sub = [t for t in tickets if lo <= t["signal_d"] <= hi]
    rs = [t["r"] for t in sub if t.get("r") is not None]
    out = {"window": [lo, hi], "n": len(sub), "total_r": round(sum(rs), 4) if rs else 0.0,
           "mean_r": round(sum(rs) / len(rs), 6) if rs else None}
    curve = list(t159.nav(sub, bars, F_RISK, cap=CAP, d_to=CURVE_TO))
    st = t159.stats(curve) if curve else None
    if st:
        out["nav"] = {"d0": st["d0"], "d1": st["d1"], "end": round(st["end"], 6),
                      "annualised": st["annualised"], "mdd": st["mdd"],
                      "calmar": (st["annualised"] / abs(st["mdd"])) if (st["annualised"] and st["mdd"]) else None,
                      "nominal_peak": st["peak_gross"], "taken": st["taken"], "skipped": st["skipped"]}
    return out


# ── ④ 前向窗口(10-19 → 最后一天) ───────────────────────────────────────────
def forward_window(bars: dict[str, list], gate: dict, db_gate: dict, lo=FWD_FROM, hi=None) -> dict:
    last_d = max(r[-1][0] for r in bars.values())
    hi = hi or last_d
    days = defaultdict(lambda: [0, 0, 0, 0])
    signals = []
    for s, rows in bars.items():
        a = t159.indicators(rows)
        for i in range(WARMUP, len(a["d"])):
            d = a["d"][i]
            if not (lo <= d <= hi):
                continue
            u = a["adv30"][i] is not None and a["adv30"][i] >= 5e6
            v = a["adv40p"][i] is not None and a["dv"][i] >= 2 * a["adv40p"][i]
            full = t159.sig_long(a, i, gate)
            if full:
                signals.append({"symbol": s, "signal_d": d,
                                "close": a["c"][i], "sma200": a["sma200"][i], "hh40": a["hh40"][i],
                                "adv30": a["adv30"][i], "adv40p": a["adv40p"][i], "dv": a["dv"][i],
                                "has_entry_bar": (i + 1) < len(a["d"]),
                                "entry_d": a["d"][i + 1] if (i + 1) < len(a["d"]) else None})
            days[d][0] += 1
            days[d][1] += 1 if u else 0
            days[d][2] += 1 if (u and v) else 0
            days[d][3] += 1 if full else 0
    gate_rows = []
    for d in sorted(days):
        g_file = gate.get(d, {})
        g_db = db_gate.get(d, {})
        gate_rows.append({"d": d, "gate_open_file": g_file.get("gate_open"),
                          "gate_open_db": g_db.get("gate_open"),
                          "db_lvl": round(g_db["lvl"], 4) if "lvl" in g_db else None,
                          "db_ma200": round(g_db["ma200"], 4) if g_db.get("ma200") else None,
                          "symbols": days[d][0], "universe": days[d][1],
                          "universe_and_vol_gate": days[d][2], "full_signal": days[d][3]})
    tk = [t for t in gen_tickets(bars, gate, lo, hi)]
    return {"window": [lo, hi], "last_bar_d": last_d, "days": gate_rows,
            "n_full_signal_days": sum(1 for c in days.values() if c[3]),
            "total_full_signals": sum(c[3] for c in days.values()),
            "signals": signals,
            "tickets": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                         "exit_d": t["exit_d"], "entry_px": t["entry_px"], "stop_px": t["stop_px"],
                         "exit_px": t["exit_px"], "r": t["r"], "still": bool(t.get("still"))}
                        for t in tk]}


# ── main ────────────────────────────────────────────────────────────────────
def granularity_audit(raw: dict[str, list]) -> dict:
    """perp_bv_daily 是不是「同质日线」?逐符号看行距:1 天 = 日线,8~12 天 = 10 日聚合 K 线。"""
    daily, tenbar, other = [], [], []
    dup_syms = []
    daily_start = {}
    for s, v in raw.items():
        ds = sorted({r[0] for r in v})
        if len(v) != len(ds):
            dup_syms.append(s)
        dd = [dt.date.fromisoformat(x) for x in ds]
        gaps = [(b - a).days for a, b in zip(dd, dd[1:])]
        g1 = sum(1 for x in gaps if x == 1) / max(1, len(gaps))
        g10 = sum(1 for x in gaps if 8 <= x <= 12) / max(1, len(gaps))
        if g1 > 0.90:
            daily.append(s)
        elif g10 > 0.50:
            tenbar.append(s)
        else:
            other.append(s)
        # 连续日线的起点:从后往前,一路 1 天间隔的最早那一天
        st = ds[-1] if ds else None
        for i in range(len(dd) - 1, 0, -1):
            if (dd[i] - dd[i - 1]).days != 1:
                st = ds[i]
                break
        daily_start[s] = st
    ds_all = sorted(daily_start.values())
    usable = [s for s in raw if len(raw[s]) > WARMUP and s in daily]
    return {"n_symbols": len(raw),
            "n_symbols_duplicate_dates": len(dup_syms),
            "duplicate_symbols_sample": sorted(dup_syms)[:20],
            "n_daily_series": len(daily), "n_10day_bar_series": len(tenbar), "n_other": len(other),
            "tenbar_sample": sorted(tenbar)[:20],
            "daily_regime_start_median": _median_str(ds_all),
            "daily_regime_start_p25": ds_all[int(0.25 * (len(ds_all) - 1))],
            "daily_regime_start_p75": ds_all[int(0.75 * (len(ds_all) - 1))],
            "n_symbols_usable_for_rv2": len(usable),
            "usable_sample": sorted(usable)[:20]}


def coverage_audit(raw: dict[str, list]) -> dict:
    """最近 30 个有数据的日:每个日期有多少个符号有行(缺日会让前向账本的指标错位)。"""
    cnt = defaultdict(int)
    allrows = 0
    for v in raw.values():
        for r in v:
            cnt[r[0]] += 1
            allrows += 1
    ds = sorted(cnt)
    tail = ds[-30:]
    mx = max(cnt[d] for d in tail)
    thin = [{"d": d, "n_symbols": cnt[d]} for d in tail if cnt[d] < mx]
    # 每个符号在尾部窗口里缺的日子
    win = set(tail)
    miss = defaultdict(list)
    for s, v in raw.items():
        have = {r[0] for r in v} & win
        for d in win - have:
            miss[s].append(d)
    return {"n_symbols_max_recent": mx, "recent_dates": tail[-12:],
            "recent_counts": {d: cnt[d] for d in tail},
            "thin_dates": thin,
            "n_symbols_missing_at_least_one_recent_day": len(miss),
            "symbols_missing_2026_10_28": sum(1 for s, m in miss.items() if "2026-10-28" in m),
            "missing_sample": {s: m for s, m in list(sorted(miss.items()))[:5]}}


def _rename_1000(bars: dict[str, list], ref_syms=None):
    """Binance 微市值永续用 `1000X` 记号(如 1000PEPE),与现货缓存的 `X` 不同名。
    映射回 X 以便逐票对齐;价格是 1000 倍但 R 是比值、成交额 qv 本就是美元口径
    ⇒ 阈值(hh40/sma200/adv30/adv40p/dv)与 R 均不受影响。
    ref_syms = 缓存符号集时:只在缓存里写 `X`(不写 `1000X`)时才把 `1000X` 映成 `X`
    —— 缓存本身也有 1000LUNC/1000SHIB/1000WHY/1000X/1000XEC,那几只必须保持原名。"""
    out, renamed = {}, []
    for s, v in bars.items():
        tgt = None
        if s.startswith("1000"):
            base = s[4:]
            if ref_syms is None:
                if base not in bars:
                    tgt = base
            elif (base in ref_syms) and (s not in ref_syms):
                tgt = base
        if tgt:
            out[tgt] = v
            renamed.append([s, tgt])
        else:
            out[s] = v
    return out, renamed


def run_sensitivity(cache_bars: dict, gate: dict) -> dict:
    """【探索性】宇宙/命名变体下的 ⑤ 判据 —— 主结果(预注册宇宙)不变,这里只问:
    「同键占比不到 95%」与「R 差超出 ±10%」是不是被符号命名与宇宙差撑起来的。"""
    raw_all = _read_jsonl_pbv(PBV_JSONL)
    rows = json.load(open(PAIRS_JSONL)).get("rows", [])
    kinds = {}
    for r in rows:
        s = r.get("symbol")
        if not s:
            continue
        kinds[s] = ((r.get("kind") or "").strip().lower(), bool(r.get("dead_from")))
    U = {
        "V0_coin_prereg": {s for s, (k, d) in kinds.items() if k == "coin" or (not k and d)},
        "V1_nontradfi": {s for s, (k, d) in kinds.items() if k != "tradfi"},
        "V2_every_kind": set(kinds),
    }
    tk_cache = mtm(gen_tickets(cache_bars, gate, SIG_FROM, SIG_TO), cache_bars)
    r_cache_pre = sum(t["r"] for t in tk_cache
                      if t["signal_d"] <= "2026-08-07" and t.get("r") is not None)
    VARIANTS = [
        ("V0_coin_prereg", False, False),
        ("V0_coin_prereg", True, False),
        ("V0_coin_prereg", True, True),
        ("V0_coin_prereg", "to_cache", False),
        ("V0_coin_prereg", "to_cache", True),
        ("V1_nontradfi", "to_cache", False),
        ("V2_every_kind", "to_cache", False),
    ]
    out = {}
    for uni, mapped, aligned in VARIANTS:
        raw = {s: v for s, v in raw_all.items() if s in U[uni]}
        bars = to_bars(raw)
        ren = []
        if mapped:
            ref = set(cache_bars) if mapped == "to_cache" else None
            bars, ren = _rename_1000(bars, ref)
        if aligned:
            bars = {s: v for s, v in bars.items() if s in cache_bars}
        tk = mtm(gen_tickets(bars, gate, SIG_FROM, SIG_TO), bars)
        pre = compare_tickets(tk_cache, tk, "cache", uni)["pre_split"]
        r_pre = sum(t["r"] for t in tk if t["signal_d"] <= "2026-08-07" and t.get("r") is not None)
        share = pre["same_key_share_of_a"]
        diff = (r_pre / r_cache_pre - 1) if r_cache_pre else None
        key = (f"{uni}{'+map1000' if mapped is True else ''}"
               f"{'+map1000_to_cache' if mapped == 'to_cache' else ''}"
               f"{'+cache_univ' if aligned else ''}")
        out[key] = {
            "universe": uni, "map_1000": mapped, "cache_aligned": aligned,
            "n_symbols": len(bars), "n_renamed": len(ren), "renamed_sample": ren[:10],
            "n_tickets": len(tk),
            "total_r": round(sum(t["r"] for t in tk if t.get("r") is not None), 4),
            "pre_n_cache": pre["n_a"], "pre_n_pbv": pre["n_b"], "pre_n_both": pre["n_both"],
            "pre_only_cache": pre["n_only_a"], "pre_only_pbv": pre["n_only_b"],
            "pre_same_key_share_of_cache": share,
            "pre_total_r_cache": round(r_cache_pre, 4), "pre_total_r_pbv": round(r_pre, 4),
            "pre_total_r_rel_diff": round(diff, 4) if diff is not None else None,
            "pass_same_key": bool(share is not None and share >= 0.95),
            "pass_total_r": bool(diff is not None and abs(diff) <= 0.10),
            "nav": summarise(tk, bars).get("nav"),
        }
    return out


def _snap(a: dict, i: int) -> dict:
    """某个下标上的全部闸门判据(R-v2 长仓口径)。"""
    c, hh, ll = a["c"][i], a["hh40"][i], a["ll40"][i]
    sma = a["sma200"][i]
    adv30, adv40p, dv = a["adv30"][i], a["adv40p"][i], a["dv"][i]
    return {"c": c, "hh40": hh, "c_over_hh40": (c / hh - 1) if hh else None,
            "sma200": sma, "c_over_sma200": (c / sma - 1) if sma else None,
            "adv30": adv30, "dv": dv, "adv40p": adv40p,
            "dv_over_2adv40p": (dv / (2 * adv40p)) if adv40p else None,
            "mindd120": a["mindd120"][i],
            "range40": ((hh - ll) / hh) if hh else None}


def run_mechanism(cache_bars: dict, pbv_bars: dict, gate: dict) -> dict:
    """【探索性】缓存侧有票、永续侧没票的那些张:逐张列出两侧的闸门判据,
    看是哪一条把它挡掉的(主结果不变,这里只找机制)。"""
    tk_cache = mtm(gen_tickets(cache_bars, gate, SIG_FROM, SIG_TO), cache_bars)
    tk_pbv = mtm(gen_tickets(pbv_bars, gate, SIG_FROM, SIG_TO), pbv_bars)
    A = {_key(t): t for t in tk_cache}
    B = {_key(t): t for t in tk_pbv}
    only_a = sorted(k for k in A if k not in B)
    raw_all = to_bars(_read_jsonl_pbv(PBV_JSONL))       # 未过宇宙过滤的永续序列
    rows = []
    for (sym, d) in only_a:
        rec = {"symbol": sym, "signal_d": d, "r": A[(sym, d)]["r"],
               "pbv_symbol_used": None, "pbv_bars": 0, "pbv_first_d": None, "pbv_last_d": None}
        ca = t159.indicators(cache_bars[sym])
        ic = ca["d"].index(d)
        rec["cache"] = _snap(ca, ic)
        cand = None
        if sym in pbv_bars:
            cand = pbv_bars[sym]
        elif ("1000" + sym) in pbv_bars:
            cand = pbv_bars["1000" + sym]
            rec["pbv_symbol_used"] = "1000" + sym
        elif sym in raw_all:
            cand = raw_all[sym]
        if cand:
            rec["pbv_bars"] = len(cand)
            rec["pbv_first_d"], rec["pbv_last_d"] = cand[0][0], cand[-1][0]
            pa = t159.indicators(cand)
            if d in pa["d"]:
                ip = pa["d"].index(d)
                rec["pbv"] = _snap(pa, ip)
                rec["close_rel_diff"] = abs(pa["c"][ip] / ca["c"][ic] - 1)
                blockers = []
                if not (rec["pbv"]["c"] > rec["pbv"]["hh40"]):
                    blockers.append("c<=hh40")
                if rec["pbv"]["sma200"] is None or not (rec["pbv"]["c"] > rec["pbv"]["sma200"]):
                    blockers.append("c<=sma200")
                if rec["pbv"]["mindd120"] is None or rec["pbv"]["mindd120"] > 0.5:
                    blockers.append("mindd120>0.5")
                if rec["pbv"]["adv30"] is None or rec["pbv"]["adv30"] < 5e6:
                    blockers.append("adv30<5M")
                if rec["pbv"]["range40"] is None or rec["pbv"]["range40"] > 0.40:
                    blockers.append("range40>0.40")
                if rec["pbv"]["adv40p"] is None or rec["pbv"]["dv"] < 2 * rec["pbv"]["adv40p"]:
                    blockers.append("dv<2*adv40p")
                rec["blockers_on_pbv"] = blockers
        rows.append(rec)
    edge = [abs(r["cache"]["c_over_hh40"]) for r in rows
            if r.get("cache") and r["cache"]["c_over_hh40"] is not None]
    with_pb = [r for r in rows if r.get("pbv")]
    blocker_hist = defaultdict(int)
    for r in with_pb:
        for b in r.get("blockers_on_pbv", []):
            blocker_hist[b] += 1
    return {"n_only_cache": len(rows), "n_with_pbv_series": len(with_pb),
            "n_blocked_by_hh40": sum(1 for r in with_pb if "c<=hh40" in r.get("blockers_on_pbv", [])),
            "blocker_hist": dict(blocker_hist),
            "cache_edge_abs": {"median": _median(edge), "p75": _quant(edge, 0.75) if edge else None,
                                "max": max(edge) if edge else None,
                                "n_within_20bp": sum(1 for x in edge if x <= 0.002),
                                "n_within_50bp": sum(1 for x in edge if x <= 0.005)},
            "rows": rows}


def main() -> None:
    stage = "all"
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]
    if stage == "mech":
        cache_bars = to_bars(load_cache_raw())
        pbv_bars = to_bars(load_pbv_raw())
        gate = t159.load_gate()
        out = os.path.join(HERE, "t238_results_mech.json")
        res = run_mechanism(cache_bars, pbv_bars, gate)
        json.dump(res, open(out, "w"), indent=1, default=str)
        brief = {k: v for k, v in res.items() if k != "rows"}
        brief["sample_rows"] = res["rows"][:8]
        print(json.dumps(brief, indent=1, default=str))
        return
    if stage == "sens":
        cache_bars = to_bars(load_cache_raw())
        gate = t159.load_gate()
        out = os.path.join(HERE, "t238_results_sens.json")
        json.dump({"generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "cache_tickets": len(gen_tickets(cache_bars, gate, SIG_FROM, SIG_TO)),
                   "variants": run_sensitivity(cache_bars, gate)}, open(out, "w"), indent=1, default=str)
        print(json.dumps(json.load(open(out))["variants"], indent=1, default=str))
        return
    if stage == "fetch" or (stage == "all" and not os.path.exists(PBV_JSONL)):
        fetch_pbv()

    pbv_raw = load_pbv_raw()
    cache_raw = load_cache_raw()
    db_raw = _read_jsonl(DB_JSONL) if os.path.exists(DB_JSONL) else {}
    pbv_bars = to_bars(pbv_raw)
    cache_bars = to_bars(cache_raw)
    db_bars = to_bars(db_raw)

    res = {"meta": {"version": "v2:perp_bv_daily",
                    "source_table": "perp_bv_daily", "universe": "perp_bv_pairs.kind='coin' "
                    "(+ kind null & dead_from not null)", "dv": "qv",
                    "fetch_from": FETCH_FROM, "fetch_to": FETCH_TO,
                    "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}}
    # 0. 数据自检
    starts = sorted(r[0][0] for r in pbv_bars.values())
    warm_ok = sum(1 for r in pbv_bars.values() if len(r) > WARMUP)
    first_signal_dates = sorted(r[WARMUP][0] for r in pbv_bars.values() if len(r) > WARMUP)
    res["data"] = {
        "pbv": {"symbols": len(pbv_bars), "rows": sum(len(v) for v in pbv_bars.values()),
               "first_d": starts[0] if starts else None, "last_d": max(r[-1][0] for r in pbv_bars.values()),
               "n_symbols_with_>220_bars": warm_ok,
               "earliest_eligible_signal_d": first_signal_dates[0] if first_signal_dates else None,
               "median_eligible_signal_d": _median_str(first_signal_dates)},
        "cache": {"symbols": len(cache_bars), "rows": sum(len(v) for v in cache_bars.values()),
                  "first_d": min(r[0][0] for r in cache_bars.values()) if cache_bars else None,
                  "last_d": max(r[-1][0] for r in cache_bars.values()) if cache_bars else None},
        "db": {"symbols": len(db_bars), "rows": sum(len(v) for v in db_bars.values()),
               "first_d": min(r[0][0] for r in db_bars.values()) if db_bars else None,
               "last_d": max(r[-1][0] for r in db_bars.values()) if db_bars else None},
        "pbv_minus_cache_symbols": sorted(set(pbv_bars) - set(cache_bars)),
        "cache_minus_pbv_symbols": sorted(set(cache_bars) - set(pbv_bars)),
        "pbv_granularity": granularity_audit(pbv_raw),
        "pbv_universe": dict(PBV_UNI),
        "pbv_coverage": coverage_audit(pbv_raw),
    }

    # 1. ① 序列两两对比
    res["series"] = {"pbv_vs_cache": compare_series(pbv_raw, cache_raw, "pbv", "cache"),
                     "pbv_vs_db": compare_series(pbv_raw, db_raw, "pbv", "db"),
                     "cache_vs_db": compare_series(cache_raw, db_raw, "cache", "db")}

    # 闸门
    gate = t159.load_gate()
    dbg = load_style_gate_db()
    db_gate = dbg["gate"]
    res["gate"] = {"style_file": {"n": len(gate), "d0": min(gate) if gate else None,
                                  "d1": max(gate) if gate else None},
                   "style_db": {"n": dbg["n_rows"], "d0": dbg["d0"], "d1": dbg["d1"]}}

    # 2. ② 票生成 + 对比
    tk_pbv = gen_tickets(pbv_bars, gate, SIG_FROM, SIG_TO)
    tk_pbv = mtm(tk_pbv, pbv_bars)
    tk_cache = gen_tickets(cache_bars, gate, SIG_FROM, SIG_TO)
    tk_cache = mtm(tk_cache, cache_bars)
    # 自检:缓存侧生成必须复现 t159 落盘的 770 张
    f = json.load(open(CACHE_TK))
    file_long = f["long"]
    cm = {_key(t): t for t in tk_cache}
    fm = {_key(t): t for t in file_long}
    both = set(cm) & set(fm)
    diffs = [k for k in both if abs((cm[k]["r"] or 0) - (fm[k]["r"] or 0)) > 1e-9
             or cm[k]["exit_d"] != fm[k]["exit_d"] or cm[k]["entry_px"] != fm[k]["entry_px"]]
    res["selfcheck_cache"] = {"generated": len(tk_cache), "file": len(file_long),
                              "n_both": len(both), "n_diff": len(diffs),
                              "diff_sample": [{"symbol": k[0], "signal_d": k[1],
                                               "gen_r": cm[k]["r"], "file_r": fm[k]["r"],
                                               "gen_exit_d": cm[k]["exit_d"], "file_exit_d": fm[k]["exit_d"],
                                               "gen_entry_px": cm[k]["entry_px"], "file_entry_px": fm[k]["entry_px"]}
                                              for k in sorted(diffs)[:10]],
                              "only_generated": len(set(cm) - set(fm)), "only_file": len(set(fm) - set(cm))}

    res["tickets"] = {"pbv": summarise(tk_pbv, pbv_bars), "cache": summarise(tk_cache, cache_bars),
                      "compare": compare_tickets(tk_cache, tk_pbv, "cache", "pbv")}
    res["warmup"] = warmup_attribution(tk_cache, tk_pbv, pbv_bars, cache_bars)

    # 3. ③ 钱曲线 + S-677 切片
    res["money"] = {"pbv": summarise(tk_pbv, pbv_bars)["nav"], "cache": summarise(tk_cache, cache_bars)["nav"],
                    "s638_reference": {"annualised": 0.244, "mdd": -0.323, "calmar": 0.99,
                                       "note": "S-638: f=1%, 盯市 MDD −32.3%, 年化 +24.4%, 接 304 张"}}
    # S-677 的 OOS 切片(照 s677_rv2_oos.py 原文的年份口径)
    oos_pbv = gen_tickets(pbv_bars, gate, OOS_FROM, OOS_TO)
    oos_pbv = mtm(oos_pbv, pbv_bars, OOS_TO)
    oos_cache = gen_tickets(cache_bars, gate, OOS_FROM, OOS_TO)
    oos_cache = mtm(oos_cache, cache_bars, OOS_TO)
    res["oos_s677"] = {
        "window": [OOS_FROM, OOS_TO],
        "pbv": {"n": len(oos_pbv),
               "total_r": round(sum(t["r"] for t in oos_pbv if t.get("r") is not None), 4),
               "per_ticket_r": round(sum(t["r"] for t in oos_pbv if t.get("r") is not None) / len(oos_pbv), 6)
               if oos_pbv else None},
        "cache": {"n": len(oos_cache),
                  "total_r": round(sum(t["r"] for t in oos_cache if t.get("r") is not None), 4),
                  "per_ticket_r": round(sum(t["r"] for t in oos_cache if t.get("r") is not None) / len(oos_cache), 6)
                  if oos_cache else None},
        "tickets_pbv": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "r": t["r"]} for t in oos_pbv],
        "tickets_cache": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "r": t["r"]} for t in oos_cache],
    }

    # 4. ④ 前向窗口
    res["forward"] = forward_window(pbv_bars, gate, db_gate)

    # 5. ⑤ 判(S-719)
    cmp_pre = res["tickets"]["compare"]["pre_split"]
    a_r = cmp_pre["both"]["total_r"] + cmp_pre["a_only"]["total_r"]   # cache 侧 pre 全量
    b_r = cmp_pre["both"]["total_r"] + cmp_pre["b_only"]["total_r"]   # pbv 侧 pre 全量
    # 「2020-03 → 2026-08-08 总 R」两边各自的实际值(按各自生成的全部票)
    r_cache_pre = sum(t["r"] for t in tk_cache if t["signal_d"] <= "2026-08-07" and t.get("r") is not None)
    r_pbv_pre = sum(t["r"] for t in tk_pbv if t["signal_d"] <= "2026-08-07" and t.get("r") is not None)
    share = cmp_pre["same_key_share_of_a"]
    diff_pct = (r_pbv_pre / r_cache_pre - 1) if r_cache_pre else None
    res["judge"] = {
        "version": "v2:perp_bv_daily",
        "rule": "S-719:2026-08-08 前同键票占缓存的 ≥95% 且 2020-03→2026-08-08 总 R 与缓存差在 ±10% 内 ⇒ ✅",
        "pre_same_key_share_of_cache": share,
        "pre_total_r_cache": round(r_cache_pre, 4), "pre_total_r_pbv": round(r_pbv_pre, 4),
        "pre_total_r_rel_diff": round(diff_pct, 4) if diff_pct is not None else None,
        "pass_same_key": bool(share is not None and share >= 0.95),
        "pass_total_r": bool(diff_pct is not None and abs(diff_pct) <= 0.10),
        "verdict": None,
    }
    res["judge"]["verdict"] = "✅ 验证在永续序列上成立" if (
        res["judge"]["pass_same_key"] and res["judge"]["pass_total_r"]) else "❌"

    out = os.path.join(HERE, "t238_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str)
    brief = {
        "data": res["data"], "series": {k: {kk: vv for kk, vv in v.items() if kk != "per_symbol"}
                                        for k, v in res["series"].items()},
        "selfcheck_cache": res["selfcheck_cache"], "tickets": {k: v for k, v in res["tickets"].items()
                                                                if k != "compare"},
        "compare": {k: v for k, v in res["tickets"]["compare"].items() if not k.endswith("_list")},
        "money": res["money"], "oos_s677": {k: v for k, v in res["oos_s677"].items()
                                            if not k.startswith("tickets_")},
        "forward": {k: v for k, v in res["forward"].items() if k != "days"} | {"days": res["forward"]["days"]},
        "judge": res["judge"]}
    print(json.dumps(brief, indent=1, default=str))


if __name__ == "__main__":
    main()
