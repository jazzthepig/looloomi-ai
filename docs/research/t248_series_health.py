#!/usr/bin/env python3
"""T-248 —— R-v2 真钱序列体检(只报,不判)。

perp_bv_daily 在 R-v2 宇宙(binance_hist 面板符号 ∩ perp_bv_pairs coin,+ 1000X ↔ X)
上 2025-06-01 → 昨天,逐名查:缺天 / 重复 / 价格跳变 / 成交额量纲断点 / 死期与 bar 矛盾 /
tbqv 空或 > qv / 与 HL 永续日线的收盘差。

## 口径(先写后算,只算一次)

- **宇宙** = `r_tickets_scan` 的 uni CTE,一字不差抄自
  `migrations/2026-11-05_r_tickets_universe_1000x.sql`:
  `perp_bv_pairs` 里 (kind='coin' 或 (kind is null 且 dead_from 有值)) 且
  (symbol ∈ ohlcv_daily(source='binance_hist') 的 symbol 集,或 symbol 是 '1000%' 且去掉前缀后 ∈ 该集)。
- **窗口** = 2025-06-01 → 2026-11-04(昨天,已完成的 UTC 日)。
- **序列** = `perp_bv_daily`(R-v2 读的那张表);HL 对照 = `ohlcv_daily(source='hyperliquid')`。
- **只报不判**:不产生买卖意见、不做 DDL、不入库、不改代码。

## 纪律

只读 SELECT;翻页一律带 `order=`(按 `symbol=in.(…)` 分片,每页 1000 行;服务端单页上限 1000,
`limit=10000` 会被静默截断)。探针与重跑都改同一个文件。交叉核对用 Binance 现货
(`ohlcv_daily(source='binance_hist')`),因为它覆盖整窗;HL 快照只有 2026-08-09 → 08-23。

## 用法

    python3 t248_series_health.py fetch 2025-06-01 2026-11-04   # 拉四张表到本地缓存
    python3 t248_series_health.py cross 2025-06-01 2026-11-04    # 跳变日的现货交叉核对
    python3 t248_series_health.py analyze 2025-06-01 2026-11-04 # 算 → t248_results.json
"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}

CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t248_cache"
D_FROM, D_TO = "2025-06-01", "2026-11-04"

# 预注册的阈值(不扫参)
JUMP_LN = 0.5           # |ln(c_t / c_{t−1})| > 0.5 = 跳变
QV_HI, QV_LO = 20.0, 0.05   # qv / 20 日中位数 的上下界
QV_WIN = 20
HL_REL = 0.02           # 收盘相对差 > 2% = 列出
SPOT_JUMP_LN = 0.3      # 现货同日跳变 ≥ 0.3 = 佐证
RV2_ADV_MIN = 5e6       # R-v2 的宇宙门:adv30 ≥ 500 万美元
RV2_ADV_WIN = 30         # R-v2 的 adv 是 30 行均值(rows between 29 preceding and current row)


# ── 取数 ────────────────────────────────────────────────────────────────────

def get(path: str, params: dict) -> list[dict]:
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{q}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
    return json.loads(body) if body else []


def fetch_all(table: str, filters: dict, order: str, columns: str = "*") -> list[dict]:
    """翻页读,一律带 order=(PostgREST 不带 order 时边界会漂);服务端行数上限 1000。"""
    rows: list[dict] = []
    offset = 0
    while True:
        params = dict(filters)
        params.update({"select": columns, "order": order, "limit": "1000", "offset": str(offset)})
        page = get(table, params)
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return rows


def count_rows(table: str, filters: dict) -> int | None:
    """Prefer: count=exact → Content-Range: 0-999/N,取 N。"""
    params = dict(filters)
    params.update({"select": "*", "limit": "1"})
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    h = dict(HEADERS)
    h["Prefer"] = "count=exact"
    req = urllib.request.Request(f"{BASE}/{table}?{q}", headers=h)
    with urllib.request.urlopen(req, timeout=180) as r:
        cr = r.headers.get("Content-Range", "")
    n = cr.rsplit("/", 1)[1].strip() if "/" in cr else ""
    return int(n) if n.isdigit() else None


def fetch_panel_symbols(src: str = "binance_hist") -> list[str]:
    """ohlcv_daily(source=src) 里出现过的 symbol 全集(不下载整列)。"""
    syms: list[str] = []
    last = None
    while True:
        f = {"source": f"eq.{src}", "select": "symbol", "order": "symbol.asc", "limit": "1"}
        if last is not None:
            f["symbol"] = f"gt.{last}"
        rows = get("ohlcv_daily", f)
        if not rows:
            break
        s = rows[0]["symbol"]
        syms.append(s)
        last = s
    return syms


def build_universe(pairs: list[dict], panel: list[str]) -> list[str]:
    """一字不差地照抄 r_tickets_scan 的 uni CTE。

      select p.symbol from perp_bv_pairs p
      where (p.kind = 'coin' or (p.kind is null and p.dead_from is not null))
        and (p.symbol in (select distinct o.symbol from ohlcv_daily o where o.source = 'binance_hist')
             or (p.symbol like '1000%' and substr(p.symbol, 5) in (select distinct o.symbol from ohlcv_daily o where o.source = 'binance_hist')))
    """
    ps = set(panel)
    uni: set[str] = set()
    for p in pairs:
        kind, dead = p.get("kind"), p.get("dead_from")
        if not (kind == "coin" or (kind is None and dead is not None)):
            continue
        sym = p["symbol"]
        if sym in ps:
            uni.add(sym)
        elif sym.startswith("1000") and len(sym) > 4 and sym[4:] in ps:
            uni.add(sym)
    return sorted(uni)


def hl_candidates(sym: str) -> list[str]:
    """永续符号 → HL 名字候选。Binance 的 1000X 对 HL 的 X 或 kX(面值差 1000 倍)。"""
    if sym.startswith("1000") and len(sym) > 4:
        base = sym[4:]
        return [base[1:] if base.startswith("k") and len(base) > 1 else base, "k" + base]
    return [sym]


def fetch_stage(d_from: str, d_to: str) -> None:
    """把原始表拉到本地缓存(下一步算,不重拉)。"""
    os.makedirs(CACHE, exist_ok=True)
    pairs = fetch_all("perp_bv_pairs", {}, "pair.asc",
                      "pair,symbol,first_d,active,dead_from,underlying_type,kind")
    json.dump(pairs, open(f"{CACHE}/perp_bv_pairs.json", "w"))
    print(f"perp_bv_pairs: {len(pairs)} rows", flush=True)

    panel = fetch_panel_symbols("binance_hist")
    json.dump(panel, open(f"{CACHE}/panel_symbols.json", "w"))
    print(f"panel(binance_hist) symbols: {len(panel)}", flush=True)

    uni = build_universe(pairs, panel)
    json.dump(uni, open(f"{CACHE}/universe.json", "w"))
    print(f"universe: {len(uni)} symbols", flush=True)

    n_perp = count_rows("perp_bv_daily", {"symbol": f"in.({','.join(uni)})",
                                          "d": f"gte.{d_from}", "or": f"(d.lte.{d_to})"})
    prow = fetch_perp_rows(uni, d_from, d_to)
    json.dump(prow, open(f"{CACHE}/perp_bv_daily.json", "w"))
    print(f"perp_bv_daily: count={n_perp} fetched={len(prow)}", flush=True)

    hl_syms = sorted({c for s in uni for c in hl_candidates(s)})
    hrow = fetch_hl_rows(hl_syms, d_from, d_to)
    json.dump(hrow, open(f"{CACHE}/hl_ohlcv.json", "w"))
    print(f"hyperliquid rows: {len(hrow)} over {len({r['symbol'] for r in hrow})} symbols", flush=True)
    print("FETCH DONE", flush=True)


def fetch_perp_rows(symbols: list[str], d_from: str, d_to: str) -> list[dict]:
    """perp_bv_daily:按 symbol=in.(…) 分片,片内 order=symbol.asc,d.asc,每页 1000 行。"""
    out: list[dict] = []
    cols = "pair,symbol,d,o,h,l,c,qv,tbqv"
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        out.extend(fetch_all("perp_bv_daily",
                             {"symbol": f"in.({','.join(chunk)})", "d": f"gte.{d_from}",
                              "or": f"(d.lte.{d_to})"},
                             "symbol.asc,d.asc", cols))
    return out


def fetch_hl_rows(symbols: list[str], d_from: str, d_to: str) -> list[dict]:
    """ohlcv_daily(source='hyperliquid'):按 symbol=in.(…) 分片。"""
    out: list[dict] = []
    cols = "symbol,trade_date,open,high,low,close,volume"
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        out.extend(fetch_all("ohlcv_daily",
                             {"symbol": f"in.({','.join(chunk)})", "source": "eq.hyperliquid",
                              "trade_date": f"gte.{d_from}", "or": f"(trade_date.lte.{d_to})"},
                             "symbol.asc,trade_date.asc", cols))
    return out


def cross_stage(d_from: str, d_to: str) -> None:
    """跳变日的现货交叉核对:现货(binance_hist)覆盖整窗,HL 只有 15 天。"""
    perp = json.load(open(f"{CACHE}/perp_bv_daily.json"))
    by = defaultdict(list)
    for r in perp:
        by[r["symbol"]].append(r)
    for s in by:
        by[s].sort(key=lambda r: r["d"])
    jsyms = sorted({s for s, rows in by.items()
                    if any(abs(math.log(float(rows[i]["c"]) / float(rows[i - 1]["c"]))) > JUMP_LN
                           for i in range(1, len(rows))
                           if float(rows[i]["c"]) > 0 and float(rows[i - 1]["c"]) > 0)})
    spot: list[dict] = []
    for i in range(0, len(jsyms), 30):
        ch = jsyms[i:i + 30]
        spot.extend(fetch_all("ohlcv_daily",
                              {"symbol": f"in.({','.join(ch)})", "source": "eq.binance_hist",
                               "trade_date": f"gte.{d_from}"},
                              "symbol.asc,trade_date.asc", "symbol,trade_date,close"))
    json.dump(spot, open(f"{CACHE}/spot_crosscheck.json", "w"))
    print(f"spot crosscheck: {len(spot)} rows over {len({r['symbol'] for r in spot})} symbols", flush=True)


# ── 小工具 ──────────────────────────────────────────────────────────────────

def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def pct(xs: list[float], q: float) -> float | None:
    """线性插值分位(与 numpy 一致)。"""
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def daterange(a: str, b: str) -> list[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def is_shell(r: dict) -> bool:
    """空壳行:量额为 0 且 o=h=l=c(挂盘后不再成交的合约,Binance Vision 每天补一行)。"""
    c = float(r["c"])
    return (float(r["qv"]) == 0 and float(r["o"]) == c and float(r["h"]) == c
            and float(r["l"]) == c)


# ── 分析 ────────────────────────────────────────────────────────────────────

def analyze(d_from: str, d_to: str) -> dict:
    pairs = json.load(open(f"{CACHE}/perp_bv_pairs.json"))
    perp = json.load(open(f"{CACHE}/perp_bv_daily.json"))
    hlrows = json.load(open(f"{CACHE}/hl_ohlcv.json"))
    uni = json.load(open(f"{CACHE}/universe.json"))
    unis = set(uni)
    pmeta = {p["symbol"]: p for p in pairs}

    by: dict[str, list[dict]] = defaultdict(list)
    for r in perp:
        by[r["symbol"]].append(r)
    for s in by:
        by[s].sort(key=lambda r: r["d"])

    res: dict = {"meta": {"window": [d_from, d_to], "n_universe": len(uni),
                           "n_perp_rows": len(perp), "n_hl_rows": len(hlrows),
                           "perp_min_d": min(r["d"] for r in perp),
                           "perp_max_d": max(r["d"] for r in perp),
                           "hl_min_d": min((r["trade_date"] for r in hlrows), default=None),
                           "hl_max_d": max((r["trade_date"] for r in hlrows), default=None)},
                 "universe": uni}

    # ── A. 重复 (symbol, d) ────────────────────────────────────────────────
    cnt = Counter((r["symbol"], r["d"]) for r in perp)
    dups = [{"symbol": k[0], "d": k[1], "n": v} for k, v in cnt.items() if v > 1]
    res["dups"] = sorted(dups, key=lambda x: (-x["n"], x["symbol"], x["d"]))

    # ── B. 缺天 ─────────────────────────────────────────────────────────────
    span = {s: (rows[0]["d"], rows[-1]["d"]) for s, rows in by.items()}
    cal = daterange(d_from, d_to)
    have: dict[str, set[str]] = {d: set() for d in cal}
    for s, rows in by.items():
        for r in rows:
            if r["d"] in have:
                have[r["d"]].add(s)
    day_report = []
    for d in cal:
        expected = [s for s, (a, b) in span.items() if a <= d <= b]
        act = len(have[d])
        day_report.append({"d": d, "expected": len(expected), "actual": act,
                           "missing": len(expected) - act,
                           "ratio": (act / len(expected)) if expected else None,
                           "missing_syms": sorted(set(expected) - have[d])})
    market_holes = [x for x in day_report if x["expected"] > 0 and x["actual"] == 0]
    partial = sorted([x for x in day_report if x["expected"] > 0 and 0 < x["actual"] < x["expected"]],
                     key=lambda x: (x["ratio"] if x["ratio"] is not None else 1))
    interior, tail = [], []
    for s, rows in by.items():
        ds = {r["d"] for r in rows}
        a, b = span[s]
        gaps = [d for d in daterange(a, b) if d not in ds]
        if gaps:
            interior.append({"symbol": s, "n_gap": len(gaps), "gap_days": gaps[:40], "first": a, "last": b})
        if b < d_to:
            tail.append({"symbol": s, "last_bar": b,
                         "tail_missing_days": (date.fromisoformat(d_to) - date.fromisoformat(b)).days,
                         "dead_from": pmeta.get(s, {}).get("dead_from")})
    interior.sort(key=lambda x: -x["n_gap"])
    tail.sort(key=lambda x: -x["tail_missing_days"])
    res["missing_days"] = {"market_holes": market_holes, "partial_days": partial,
                           "interior": interior, "tail_truncated": tail,
                           "day_report": day_report}

    # ── C. 空壳行(qv=0 且 o=h=l=c)—— 「行在,信息为空」 ─────────────────────
    shell_rows = [r for r in perp if is_shell(r)]
    shell_by = Counter(r["symbol"] for r in shell_rows)
    shell_info = []
    for s in sorted(shell_by):
        rows = by[s]
        i = next(k for k, r in enumerate(rows) if is_shell(r))
        last_real = rows[i - 1]["d"] if i > 0 else None
        shell_info.append({"symbol": s, "first_shell_d": rows[i]["d"], "last_real_d": last_real,
                           "n_shell_rows": shell_by[s], "n_rows": len(rows),
                           "shell_c": float(rows[i]["c"]),
                           "pair_active": pmeta.get(s, {}).get("active"),
                           "pair_kind": pmeta.get(s, {}).get("kind"),
                           "pair_dead_from": pmeta.get(s, {}).get("dead_from"),
                           "starts_at_window_start": rows[i]["d"] == d_from})
    res["shell_rows"] = {"n_rows": len(shell_rows),
                         "share_of_rows": round(len(shell_rows) / len(perp), 4),
                         "n_symbols": len(shell_by),
                         "symbols": shell_info}
    res["shell_summary"] = {
        "n_pairs_marked_dead_from": sum(1 for s in shell_by if pmeta.get(s, {}).get("dead_from")),
        "n_pairs_active_true": sum(1 for s in shell_by if pmeta.get(s, {}).get("active")),
        "n_shell_at_window_start": sum(1 for x in shell_info if x["starts_at_window_start"]),
        "shell_start_eq_last_real_plus_1": sum(
            1 for x in shell_info if x["last_real_d"] and
            (date.fromisoformat(x["first_shell_d"]) - date.fromisoformat(x["last_real_d"])).days == 1),
        "shell_start_by_month": dict(sorted(Counter(x["first_shell_d"][:7] for x in shell_info).items())),
    }

    # ── D. 价格跳变 |ln(c_t / c_{t−1})| > 0.5 ───────────────────────────────
    hl_by: dict[str, dict[str, float]] = defaultdict(dict)
    for r in hlrows:
        hl_by[r["symbol"]][r["trade_date"]] = float(r["close"])
    hl_map = {}
    for s in uni:
        for cand in hl_candidates(s):
            if cand in hl_by:
                hl_map[s] = (cand, 1000.0 if s.startswith("1000") and len(s) > 4 else 1.0)
                break
    res["hl_map"] = {k: list(v) for k, v in hl_map.items()}
    res["hl_missing_symbols"] = sorted(unis - set(hl_map))

    jumps = []
    for s, rows in by.items():
        for i in range(1, len(rows)):
            c0, c1 = float(rows[i - 1]["c"]), float(rows[i]["c"])
            if c0 <= 0 or c1 <= 0:
                continue
            lr = abs(math.log(c1 / c0))
            if lr > JUMP_LN:
                d = rows[i]["d"]
                hl_j = None
                if s in hl_map:
                    hn, _ = hl_map[s]
                    hd = hl_by.get(hn, {})
                    prev = None
                    for pd_ in sorted(hd):
                        if pd_ < d:
                            prev = hd[pd_]
                        else:
                            break
                    hl_j = abs(math.log(hd[d] / prev)) if prev and d in hd else None
                jumps.append({"symbol": s, "d": d, "prev_d": rows[i - 1]["d"], "c_prev": c0, "c": c1,
                              "abs_ln": round(lr, 4), "sign": 1 if c1 > c0 else -1,
                              "gap_days": (date.fromisoformat(d) - date.fromisoformat(rows[i - 1]["d"])).days,
                              "hl_abs_ln_same_day": hl_j,
                              "is_shell_row": is_shell(rows[i]) or is_shell(rows[i - 1]),
                              "is_last_real_bar": (i + 1 == len(rows)) or is_shell(rows[i + 1])})
    jumps.sort(key=lambda x: -x["abs_ln"])
    res["jumps"] = jumps

    # 现货交叉核对
    try:
        spot = json.load(open(f"{CACHE}/spot_crosscheck.json"))
    except FileNotFoundError:
        spot = []
    sb: dict[str, dict[str, float]] = defaultdict(dict)
    for r in spot:
        sb[r["symbol"]][r["trade_date"]] = float(r["close"])
    xc = []
    for j in jumps:
        sd = sb.get(j["symbol"], {})
        prev = None
        for pd_ in sorted(sd):
            if pd_ < j["d"]:
                prev = pd_
            else:
                break
        spot_lr = abs(math.log(sd[j["d"]] / sd[prev])) if prev and j["d"] in sd and sd[prev] > 0 else None
        j = dict(j)
        j["spot_abs_ln"] = round(spot_lr, 4) if spot_lr is not None else None
        j["spot_sign"] = (1 if sd[j["d"]] > sd[prev] else -1) if (prev and j["d"] in sd) else None
        j["spot_corroborated"] = bool(spot_lr is not None and spot_lr >= SPOT_JUMP_LN
                                      and j["spot_sign"] == j["sign"])
        xc.append(j)
    res["jump_crosscheck"] = {
        "n_jump_rows": len(xc), "n_names": len({x["symbol"] for x in xc}),
        "n_spot_corroborated": sum(1 for x in xc if x["spot_corroborated"]),
        "n_spot_opposite_sign": sum(1 for x in xc if x["spot_sign"] is not None
                                    and x["spot_sign"] != x["sign"]),
        "n_no_spot": sum(1 for x in xc if x["spot_abs_ln"] is None),
        "n_on_shell_rows": sum(1 for x in xc if x["is_shell_row"]),
        "n_on_last_real_bar": sum(1 for x in xc if x["is_last_real_bar"]),
        "not_corroborated": [x for x in xc if not x["spot_corroborated"]],
    }
    res["jumps"] = xc

    # ── E. 成交额量纲断点 ──────────────────────────────────────────────────
    qv_bad = []
    for s, rows in by.items():
        qvs = [float(r["qv"]) for r in rows]
        for i, r in enumerate(rows):
            m = median(qvs[max(0, i - QV_WIN + 1):i + 1])
            if not m or m <= 0:
                continue
            ratio = float(r["qv"]) / m
            if ratio > QV_HI or ratio < QV_LO:
                qv_bad.append({"symbol": s, "d": r["d"], "qv": float(r["qv"]), "med20": m,
                               "ratio": round(ratio, 4),
                               "side": "high" if ratio > QV_HI else "low",
                               "is_shell": is_shell(r),
                               "tbqv_over_qv": (float(r["tbqv"]) / float(r["qv"]))
                               if r.get("tbqv") and float(r["qv"]) > 0 else None})
    qv_bad.sort(key=lambda x: -abs(math.log(max(x["ratio"], 1e-9))))
    res["qv_breaks"] = {"n_rows": len(qv_bad),
                        "n_symbols": len({x["symbol"] for x in qv_bad}),
                        "n_shell_rows": sum(1 for x in qv_bad if x["is_shell"]),
                        "n_real_rows": sum(1 for x in qv_bad if not x["is_shell"]),
                        "n_real_symbols": len({x["symbol"] for x in qv_bad if not x["is_shell"]}),
                        "rows": qv_bad}
    tb_ratios = sorted(float(r["tbqv"]) / float(r["qv"]) for r in perp
                       if r.get("tbqv") and float(r["qv"]) > 0)
    res["qv_breaks"]["tbqv_over_qv"] = {
        "n": len(tb_ratios),
        "median": round(median(tb_ratios), 4) if tb_ratios else None,
        "p05": round(pct(tb_ratios, 0.05), 4) if tb_ratios else None,
        "p95": round(pct(tb_ratios, 0.95), 4) if tb_ratios else None}

    # ── F. 死期与 bar 的矛盾(两个方向) ─────────────────────────────────────
    dead_after, dead_unmarked = [], []
    for s in unis:
        df = pmeta.get(s, {}).get("dead_from")
        if df and any(r["d"] > df for r in by.get(s, [])):
            dead_after.append({"symbol": s, "dead_from": df,
                               "n_after": sum(1 for r in by[s] if r["d"] > df)})
    for x in shell_info:
        if not x["pair_dead_from"]:
            dead_unmarked.append(x["symbol"])
    res["dead_marks"] = {
        "n_pairs_with_dead_from": sum(1 for p in pairs if p.get("dead_from")),
        "pairs_with_dead_from": [{"symbol": p["symbol"], "dead_from": p["dead_from"],
                                  "kind": p.get("kind"), "in_universe": p["symbol"] in unis}
                                 for p in pairs if p.get("dead_from")],
        "n_universe_with_bars_after_dead_from": len(dead_after),
        "bars_after_dead_from": dead_after,
        "n_shell_but_unmarked_dead": len(dead_unmarked),
        "shell_but_unmarked_dead": sorted(dead_unmarked),
    }

    # ── G. tbqv 为空或 > qv ────────────────────────────────────────────────
    tb_bad = []
    for r in perp:
        tb = r.get("tbqv")
        qv = float(r["qv"])
        if tb is None:
            tb_bad.append({"symbol": r["symbol"], "d": r["d"], "tbqv": None, "qv": qv, "why": "null"})
        elif float(tb) > qv:
            tb_bad.append({"symbol": r["symbol"], "d": r["d"], "tbqv": float(tb), "qv": qv,
                           "why": "tbqv>qv"})
    tb_bad.sort(key=lambda x: (x["symbol"], x["d"]))
    res["tbqv_bad"] = {"n_rows": len(tb_bad), "n_symbols": len({x["symbol"] for x in tb_bad}),
                       "rows": tb_bad}

    # ── H. 与 HL 的收盘差 ──────────────────────────────────────────────────
    hl_cmp = []
    for s, (hn, mult) in sorted(hl_map.items()):
        live, shell = [], []
        for r in by.get(s, []):
            d = r["d"]
            if d not in hl_by.get(hn, {}):
                continue
            pc, hc = float(r["c"]) / mult, hl_by[hn][d]
            if hc <= 0:
                continue
            rel = abs((pc - hc) / hc)
            (shell if is_shell(r) else live).append({"d": d, "perp_c": pc, "hl_c": hc,
                                                     "rel": round((pc - hc) / hc, 6),
                                                     "abs_rel": round(rel, 6)})
        lv = [x["abs_rel"] for x in live]
        sh = [x["abs_rel"] for x in shell]
        hl_cmp.append({
            "symbol": s, "hl_symbol": hn, "mult": mult,
            "n_live": len(lv), "n_shell": len(sh),
            "live_median_abs_rel": round(median(lv), 6) if lv else None,
            "live_p99_abs_rel": round(pct(lv, 0.99), 6) if lv else None,
            "live_max_abs_rel": round(max(lv), 6) if lv else None,
            "n_live_gt2pct": sum(1 for x in lv if x > HL_REL),
            "live_gt2pct_days": sorted([x for x in live if x["abs_rel"] > HL_REL],
                                       key=lambda z: -z["abs_rel"])[:20],
            "shell_median_abs_rel": round(median(sh), 6) if sh else None,
            "shell_max_abs_rel": round(max(sh), 6) if sh else None,
        })
    hl_cmp.sort(key=lambda x: -(x["live_p99_abs_rel"] or 0))
    all_live = [x["abs_rel"] for c in hl_cmp for x in []]
    rels = []
    for s, (hn, mult) in hl_map.items():
        for r in by.get(s, []):
            if r["d"] in hl_by.get(hn, {}) and not is_shell(r):
                pc, hc = float(r["c"]) / mult, hl_by[hn][r["d"]]
                if hc > 0:
                    rels.append({"abs_rel": abs((pc - hc) / hc), "d": r["d"], "symbol": s})
    last_hl_day = max((r["trade_date"] for r in hlrows), default=None)
    excl = [x["abs_rel"] for x in rels if x["d"] != last_hl_day]
    res["hl_compare"] = {
        "n_comparable_symbols": len(hl_map),
        "n_universe_without_hl": len(res["hl_missing_symbols"]),
        "hl_first_d": res["meta"]["hl_min_d"], "hl_last_d": last_hl_day,
        "n_live_days": len(rels),
        "live_median_abs_rel": round(median([x["abs_rel"] for x in rels]), 6) if rels else None,
        "live_p99_abs_rel": round(pct([x["abs_rel"] for x in rels], 0.99), 6) if rels else None,
        "live_max_abs_rel": round(max((x["abs_rel"] for x in rels)), 6) if rels else None,
        "n_live_gt2pct": sum(1 for x in rels if x["abs_rel"] > HL_REL),
        "n_names_live_gt2pct": len({x["symbol"] for x in rels if x["abs_rel"] > HL_REL}),
        "by_date_gt2pct": dict(Counter(x["d"] for x in rels if x["abs_rel"] > HL_REL)),
        "excl_last_hl_day": {
            "n": len(excl),
            "median_abs_rel": round(median(excl), 6) if excl else None,
            "p99_abs_rel": round(pct(excl, 0.99), 6) if excl else None,
            "max_abs_rel": round(max(excl), 6) if excl else None,
            "n_gt1pct": sum(1 for x in excl if x > 0.01),
            "n_gt2pct": sum(1 for x in excl if x > HL_REL),
        },
        "per_symbol": hl_cmp,
        "shell_worst": sorted([c for c in hl_cmp if c["shell_max_abs_rel"]],
                               key=lambda x: -x["shell_max_abs_rel"])[:10],
    }

    # ── I. R-v2 的流动性门(逐日):最近 30 天会看到的 ──────────────────────
    gate = []
    for d in sorted({r["d"] for r in perp if d_from <= r["d"] <= d_to}):
        nb = ng = 0
        for s, rows in by.items():
            idx = next((i for i, r in enumerate(rows) if r["d"] == d), None)
            if idx is None or idx < RV2_ADV_WIN - 1:
                continue
            nb += 1
            w = [float(x["qv"]) for x in rows[idx - RV2_ADV_WIN + 1:idx + 1]]
            if sum(w) / RV2_ADV_WIN >= RV2_ADV_MIN:
                ng += 1
        gate.append({"d": d, "n_bars": nb, "n_pass_adv30": ng})
    res["rv2_gate"] = gate

    # 尖峰会不会把名字「顶过」R-v2 的流动性门(adv30 含当日行,尖峰直接进均值)
    def adv30_at(rows: list[dict], idx: int) -> float | None:
        if idx < RV2_ADV_WIN - 1:
            return None
        w = [float(x["qv"]) for x in rows[idx - RV2_ADV_WIN + 1:idx + 1]]
        return sum(w) / RV2_ADV_WIN

    spike_gate = []
    for x in qv_bad:
        if x["is_shell"]:
            continue
        rows = by[x["symbol"]]
        idx = next((i for i, r in enumerate(rows) if r["d"] == x["d"]), None)
        if idx is None:
            continue
        a_now = adv30_at(rows, idx)
        a_prev = adv30_at(rows, idx - 1) if idx > 0 else None
        if a_now is None or a_prev is None:
            continue
        spike_gate.append({"symbol": x["symbol"], "d": x["d"], "ratio": x["ratio"],
                           "adv30_on_day": a_now, "adv30_prev_day": a_prev,
                           "pass_before": a_prev >= RV2_ADV_MIN,
                           "pass_after": a_now >= RV2_ADV_MIN,
                           "flipped": (a_prev < RV2_ADV_MIN) and (a_now >= RV2_ADV_MIN)})
    res["spike_gate_effect"] = {
        "n_spike_rows_with_both_days": len(spike_gate),
        "n_flipped_into_pass": sum(1 for x in spike_gate if x["flipped"]),
        "flipped": [x for x in spike_gate if x["flipped"]],
        "n_pass_before": sum(1 for x in spike_gate if x["pass_before"]),
        "n_pass_after": sum(1 for x in spike_gate if x["pass_after"]),
    }

    # 空壳行还能不能凑出 R-v2 的信号条件?(`rn >= 220` 还要 pre-window 的历史,这里用窗口内行数代替)
    shell_sig = []
    for s, rows in by.items():
        shell_idx = [i for i, r in enumerate(rows) if is_shell(r)]
        if not shell_idx:
            continue
        for i in shell_idx:
            if i < 220:
                continue
            win30 = rows[i - 29:i + 1]
            win40p = rows[i - 40:i]
            win200 = rows[i - 199:i + 1]
            win120 = rows[i - 120:i + 1]
            if len(win40p) < 40 or len(win200) < 200:
                continue
            adv30 = sum(float(x["qv"]) for x in win30) / 30.0
            adv40p = sum(float(x["qv"]) for x in win40p) / 40.0
            hh40 = max(float(x["h"]) for x in win40p)
            ll40 = min(float(x["l"]) for x in win40p)
            sma200 = sum(float(x["c"]) for x in win200) / 200.0
            c = float(rows[i]["c"])
            mx365 = max(float(x["c"]) for x in rows[max(0, i - 365):i + 1])
            dd = c / mx365 if mx365 > 0 else None
            mindd120 = min((float(x["c"]) / max(float(y["c"]) for y in rows[max(0, j - 365):j + 1]))
                           for j, x in enumerate(rows[max(0, i - 120):i + 1], start=max(0, i - 120)))
            conds = {
                "adv30>=5e6": adv30 >= RV2_ADV_MIN,
                "dd<=0.5": dd is not None and dd <= 0.5,
                "range40<=0.40": hh40 > 0 and (hh40 - ll40) / hh40 <= 0.40,
                "c>hh40": c > hh40,
                "c>sma200": c > sma200,
                "dv>=2*adv40p": float(rows[i]["qv"]) >= 2 * adv40p,
            }
            if all(conds.values()):
                shell_sig.append({"symbol": s, "d": rows[i]["d"], "c": c, "adv30": adv30,
                                  "hh40": hh40, "sma200": sma200,
                                  "days_since_dead": (date.fromisoformat(rows[i]["d"])
                                                      - date.fromisoformat(shell_idx[0] and rows[shell_idx[0] - 1]["d"]
                                                                          if shell_idx[0] > 0 else rows[i]["d"])).days})
    res["shell_signal_risk"] = {
        "n_rows_all_conditions_hold": len(shell_sig),
        "n_symbols": len({x["symbol"] for x in shell_sig}),
        "rows": shell_sig[:40],
    }

    # ── J. 最近 30 天 ──────────────────────────────────────────────────────
    d30 = (date.fromisoformat(d_to) - timedelta(days=29)).isoformat()
    res["last30"] = {
        "from": d30, "to": d_to,
        "market_holes": [x for x in market_holes if x["d"] >= d30],
        "partial_days": [x for x in partial if x["d"] >= d30],
        "interior": [x for x in interior if any(g >= d30 for g in x["gap_days"])],
        "jumps": [x for x in res["jumps"] if x["d"] >= d30],
        "qv_breaks": [x for x in qv_bad if x["d"] >= d30],
        "shell_starts": [x for x in shell_info if x["first_shell_d"] >= d30],
        "tbqv_bad": [x for x in tb_bad if x["d"] >= d30],
        "hl_gt2pct": [x for x in rels if x["abs_rel"] > HL_REL and x["d"] >= d30],
        "rv2_gate": [x for x in gate if x["d"] >= d30],
    }

    # ── K. 总表 ────────────────────────────────────────────────────────────
    res["summary"] = {
        "universe": len(uni),
        "perp_rows": len(perp),
        "missing_market_hole_days": len(market_holes),
        "missing_market_hole_symbol_days": sum(x["missing"] for x in market_holes),
        "missing_partial_days": len(partial),
        "missing_partial_symbols": len({s for x in partial for s in x["missing_syms"]}),
        "missing_interior_symbols": len(interior),
        "missing_interior_gap_days": sum(x["n_gap"] for x in interior),
        "missing_tail_symbols": len(tail),
        "dup_symbols": len({x["symbol"] for x in dups}), "dup_rows": len(dups),
        "shell_rows": res["shell_rows"]["n_rows"],
        "shell_share_of_rows": res["shell_rows"]["share_of_rows"],
        "shell_symbols": res["shell_rows"]["n_symbols"],
        "shell_symbols_unmarked_dead": res["dead_marks"]["n_shell_but_unmarked_dead"],
        "jump_symbols": res["jump_crosscheck"]["n_names"], "jump_rows": len(res["jumps"]),
        "jump_spot_corroborated": res["jump_crosscheck"]["n_spot_corroborated"],
        "qv_break_rows": len(qv_bad), "qv_break_symbols": res["qv_breaks"]["n_symbols"],
        "qv_break_real_rows": res["qv_breaks"]["n_real_rows"],
        "qv_break_real_symbols": res["qv_breaks"]["n_real_symbols"],
        "qv_break_shell_rows": res["qv_breaks"]["n_shell_rows"],
        "tbqv_rows": len(tb_bad), "tbqv_symbols": len({x["symbol"] for x in tb_bad}),
        "hl_comparable_symbols": len(hl_map),
        "hl_universe_without_counterpart": len(res["hl_missing_symbols"]),
        "hl_live_days": len(rels),
        "hl_live_gt2pct_days": sum(1 for x in rels if x["abs_rel"] > HL_REL),
        "hl_live_gt2pct_names": len({x["symbol"] for x in rels if x["abs_rel"] > HL_REL}),
        "rv2_gate_pass_min": min(x["n_pass_adv30"] for x in gate),
        "rv2_gate_pass_max": max(x["n_pass_adv30"] for x in gate),
        "rv2_gate_pass_last": gate[-1]["n_pass_adv30"],
    }
    return res


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    d0 = sys.argv[2] if len(sys.argv) > 2 else D_FROM
    d1 = sys.argv[3] if len(sys.argv) > 3 else D_TO
    if mode == "fetch":
        fetch_stage(d0, d1)
    elif mode == "cross":
        cross_stage(d0, d1)
    elif mode == "analyze":
        r = analyze(d0, d1)
        os.makedirs(CACHE, exist_ok=True)
        with open(f"{CACHE}/t248_results.json", "w") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=1)
        print(json.dumps(r["summary"], ensure_ascii=False, indent=1))
    else:
        print("usage: fetch|cross|analyze [d_from d_to]")
