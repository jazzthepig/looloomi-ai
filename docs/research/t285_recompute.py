#!/usr/bin/env python3
"""T-285 / S-764 —— S-758 盲复算。

只按台账文字(S-740 判据 + S-758 结果段 + S-756 结果段里对解析写法的描述)重写一遍:
自己解析 818 条 perp_listing 公告 → 自己取价(binance_hist 现货收盘)→ 自己做随机日期对照。
不看 lane-b 的 t277 / t279 脚本。

台账的样本规则(S-740「样本(写死)」)有几处措辞可以有多种读法(哪些公告算「USDT 永续上线」、
上线日取公告里的日期还是事件 ts、d+30 的价取当天还是最近有价的那天、同一代号多次公告怎么去重),
本脚本把读法做成可切换的开关并全量扫描,用来定位「与台账 n=142 差在哪一步」。

统计一律走 src/data/evaluation/apparatus.py。
输出:
  docs/research/t285_parse_list.json   —— 818 条公告逐条解析清单(先于取价落盘)
  docs/research/t285_results.json      —— 主口径数字 + (a)–(d) 判定 + 与台账逐项对照 + 读法敏感性
"""
import os
import re
import sys
import json
import math
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from src.data.evaluation.apparatus import (  # noqa: E402
    random_dates_like,
    null_distribution,
    percentile_of,
)

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = f"{HERE}/_t285_bars_cache.json"


def q(path):
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=HEAD)
    resp = urllib.request.urlopen(r, timeout=180)
    return json.loads(resp.read()), resp.headers.get("Content-Range")


# ────────────────────────────────────────────────────────────────────────────
# 1. 事件:events kind = perp_listing(818 条,全部 source = binance)
# ────────────────────────────────────────────────────────────────────────────
def fetch_events():
    rows, off = [], 0
    while True:
        d, cr = q(
            "events?kind=eq.perp_listing&select=id,ts,source,symbols,title,payload"
            f"&limit=1000&offset={off}&order=ts.asc,id.asc"
        )
        rows.extend(d)
        if len(d) < 1000:
            break
        off += 1000
    assert len(rows) == 818, f"expected 818 perp_listing events, got {len(rows)}"
    return rows


# ────────────────────────────────────────────────────────────────────────────
# 2. 解析器(自己写,不引用 lane-b 的代码)
# ────────────────────────────────────────────────────────────────────────────
STOP = {
    "UP", "TO", "WITH", "X", "LEVERAGE", "NEW", "LISTING", "LISTINGS", "THIS", "WEEK",
    "AND", "OR", "MARGIN", "COIN", "PERPETUAL", "PERPETUALS", "CONTRACT", "CONTRACTS",
    "USDT", "MULTIPLE", "MAXIMUM", "INCREASE", "INCREASES", "UPDATE", "UPDATES", "TIERS",
    "TRADING", "PRE", "MARKET", "LAUNCH", "LAUNCHES", "WILL", "BE", "AVAILABLE", "ON",
    "BINANCE", "FUTURES", "MARGINED", "COINM", "USDM", "PERP", "PERPS", "SPOT", "ISOLATED",
    "ENABLE", "FUTURE", "MARGINS", "TIER", "THE", "OF", "FOR", "ITS", "ALL", "BOTH",
}
DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")
M_USDT = re.compile(r"USDT[\s\-]Margined", re.I)
M_USDTS = re.compile(r"USDⓈ[\s\-]M(?:argined)?", re.I)
M_COINM = re.compile(r"Coin[\s\-]Margined|COIN-M|coin-m", re.I)
M_BUSD = re.compile(r"BUSD[\s\-]Margined", re.I)
M_USDC = re.compile(r"USDC[\s\-]Margined", re.I)
M_USDM = re.compile(r"USD[\s\-]Margined", re.I)
RE_LEVUP = re.compile(r"maximum leverage|margin tiers|leverage & margin|leverage and margin|copy trading", re.I)
RE_DELIV = re.compile(r"quarterly|delivery|dated futures|\b\d{4} Futures\b", re.I)
RE_ROUNDUP = re.compile(r"new listings this week", re.I)


def clean_tok(tk):
    tk = tk.strip().strip(".,;:()[]").upper()
    for suf in ("PERPETUALS", "PERPETUAL", "CONTRACTS", "CONTRACT", "MARGINED"):
        if len(tk) > len(suf) and tk.endswith(suf):
            tk = tk[: -len(suf)]
            break
    return tk


def split_tokens(seg):
    out = []
    for p in re.split(r"\s*(?:,|;|&|\band\b|\bor\b|\+)\s*", seg):
        p = p.strip().strip(".,;:()[]")
        if p:
            out.append(p)
    return out


def parse_announcement(ev):
    """公告 → {tokens:[{sym,quote,src}], margin, kind, excl, title_date}"""
    t = ev["title"]
    res = {"tokens": [], "margin": None, "kind": None, "excl": None, "title_date": None}
    m = DATE_RE.search(t)
    if m:
        res["title_date"] = m.group(1)
    if RE_ROUNDUP.search(t):
        res.update(kind="roundup", excl="weekly_roundup_no_symbols_in_title")
        return res
    if RE_LEVUP.search(t):
        res.update(kind="leverage_or_copy_update", excl="not_a_new_listing")
        return res
    if RE_DELIV.search(t):
        res.update(kind="quarterly_or_delivery", excl="dated_contract_not_perpetual")
        return res

    margin = None
    if M_COINM.search(t):
        margin = "coinm"
    elif M_BUSD.search(t):
        margin = "busd"
    elif M_USDC.search(t):
        margin = "usdc"
    elif M_USDM.search(t):
        margin = "usdm"
    elif M_USDT.search(t) or M_USDTS.search(t):
        margin = "usdt"
    res.update(margin=margin, kind="launch")

    toks = []
    for mm in re.finditer(r"\b([A-Z0-9]{1,15})/USDT\b", t):
        toks.append((mm.group(1).upper(), "usdt", "pair"))
    for pat in (M_USDT, M_USDTS):
        for mm in pat.finditer(t):
            seg = t[mm.end():]
            mm2 = re.search(r"(.{0,90}?)\s+Perpetual", seg, re.I)
            if not mm2:
                continue
            for tk in split_tokens(mm2.group(1)):
                tk = clean_tok(tk)
                if not tk or tk in STOP or tk.isdigit():
                    continue
                if re.fullmatch(r"\d+[Xx]", tk):
                    continue
                toks.append((tk, None, "margin"))
    for mm in re.finditer(r"\(([A-Za-z0-9]{2,14})\)", t):
        s = mm.group(1).upper()
        if s not in STOP and not s.isdigit():
            toks.append((s, None, "paren"))
    for mm in re.finditer(r"\bfor\s+([A-Z0-9]{2,14})\b", t):
        s = mm.group(1).upper()
        if s not in STOP:
            toks.append((s, None, "for"))

    seen, out = set(), []
    for sym, mk, src in toks:
        sym2 = sym
        for suf in ("USDT", "USDC", "BUSD"):
            if sym2.endswith(suf) and len(sym2) > len(suf):
                sym2 = sym2[: -len(suf)]
                break
        if not sym2 or sym2 in STOP or sym2.isdigit() or (sym2, src) in seen:
            continue
        seen.add((sym2, src))
        quote = None
        if sym.endswith("USDC"):
            quote = "usdc"
        elif sym.endswith("BUSD"):
            quote = "busd"
        elif sym.endswith("USD"):
            quote = "usd"
        elif sym.endswith("USDT"):
            quote = "usdt"
        if mk == "usdt" and quote is None:
            quote = "usdt"
        out.append({"sym": sym2, "quote": quote, "src": src})
    res["tokens"] = out
    return res


# ────────────────────────────────────────────────────────────────────────────
# 3. 取价:binance_hist 现货日线(收盘),带本地缓存
# ────────────────────────────────────────────────────────────────────────────
def fetch_bars(sym):
    bars, off = [], 0
    enc = urllib.parse.quote(sym, safe="")
    while True:
        d, _ = q(
            "ohlcv_daily?source=eq.binance_hist&symbol=eq." + enc +
            "&select=trade_date,close&limit=1000&offset=%d&order=trade_date.asc" % off
        )
        bars.extend(d)
        if len(d) < 1000:
            break
        off += 1000
    out = {}
    for b in bars:
        try:
            out[b["trade_date"]] = float(b["close"])
        except (TypeError, ValueError):
            pass
    return out


def get_bars(syms):
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE))
    todo = [s for s in syms if s not in cache]
    if todo:
        print("fetching bars for %d symbols" % len(todo), flush=True)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for s, b in zip(todo, ex.map(fetch_bars, todo)):
                cache[s] = b
        json.dump(cache, open(CACHE, "w"))
    return {s: cache.get(s, {}) for s in syms}


def dparse(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


# ── 交易所符号 ↔ 现货库符号:binance_hist 用的是 Binance 上架名(1000LUNC / 1000000BOB),
#    公告里的代号可能带也可能不带倍率前缀,解析后要对齐。
UNIVERSE = json.load(open(f"{HERE}/_t285_universe.json"))
UNIV_SET = set(UNIVERSE)


def resolve_sym(sym):
    """把公告代号对齐到 binance_hist 的符号;对不上返回 None。"""
    if sym in UNIV_SET:
        return sym
    cands = []
    for p in ("1000000", "1000"):
        if sym.startswith(p):
            base = sym[len(p):]
            cands += [base, base + "B", p + base]
        else:
            cands += [p + sym, p + sym + "B"]
    for c in cands:
        if c in UNIV_SET:
            return c
    return None


def price_at(bb, target, mode):
    """target 那天的收盘;mode='exact' 只认当天;'on_after' 取当天或之后 3 天内第一个有价日。"""
    if mode == "exact":
        return bb.get(target)
    t = dparse(target)
    for k in sorted(bb):
        if dparse(k) >= t:
            return bb[k] if (dparse(k) - t).days <= 3 else None
    return None


# ────────────────────────────────────────────────────────────────────────────
# 4. 事件构造 + 读法扫描
# ────────────────────────────────────────────────────────────────────────────
MARGIN_SETS = {
    "usdt": {"usdt"},
    "usdt+busd": {"usdt", "busd"},
    "usdt+busd+usdc": {"usdt", "busd", "usdc"},
    "usdt+busd+usdc+coinm": {"usdt", "busd", "usdc", "coinm"},
    "usdt+busd+usdc+coinm+none": {"usdt", "busd", "usdc", "coinm", None},
}
KIND_SETS = {
    "launch": {"launch"},
    "launch+lev": {"launch", "leverage_or_copy_update"},
    "launch+lev+quarterly": {"launch", "leverage_or_copy_update", "quarterly_or_delivery"},
    "all": {"launch", "leverage_or_copy_update", "quarterly_or_delivery", "roundup"},
}
MAP_MODES = ("title", "db", "union")
DATE_MODES = ("title", "ts")
PRICE_MODES = ("exact", "on_after")
SPOT_MODES = ("bars+span", "bars", "span")
DEDUP_MODES = ("none", "sym", "sym_year")


def tokens_for(r, map_mode):
    """事件 → 代号候选。title = 我的标题解析;db = events.symbols(台账说 11-06 回填过);union = 两者并集。"""
    out = []
    if map_mode in ("title", "union"):
        for tk in r["tokens"]:
            out.append({"sym": tk["sym"], "quote": tk["quote"], "src": "title"})
    if map_mode in ("db", "union"):
        for s in (r["db_symbols"] or []):
            s = s.upper()
            if s not in {x["sym"] for x in out}:
                out.append({"sym": s, "quote": None, "src": "db"})
    return out


def build_events(parse_rows, bars, btc, margin_set, kind_set, map_mode, date_mode,
                 price_mode, spot_mode, dedup_mode):
    rows = []
    for r in parse_rows:
        if r["kind"] not in kind_set:
            continue
        m = r["margin"]
        if m is not None and m not in margin_set:
            continue
        if m is None and None not in margin_set:
            continue
        d = r["d_title"] if (date_mode == "title" and r["d_title"]) else r["d_ts"]
        if d < "2020-01-01":
            continue
        for tk in tokens_for(r, map_mode):
            quote = tk["quote"] or (m if m else None)
            if m == "usdt" and quote not in (None, "usdt"):
                continue
            if m is None and quote not in (None, "usdt"):
                continue
            sym = tk["sym"]
            rsym = resolve_sym(sym)
            if rsym is None:
                continue
            bb = bars.get(rsym) or {}
            if not bb:
                continue
            ds = sorted(bb)
            before = [x for x in ds if x < d]
            if not before:
                continue
            span = (dparse(d) - dparse(before[0])).days
            if spot_mode == "bars+span" and (len(before) < 60 or span < 60):
                continue
            if spot_mode == "bars" and len(before) < 60:
                continue
            if spot_mode == "span" and span < 60:
                continue
            p0 = price_at(bb, d, price_mode)
            if p0 is None:
                continue
            d30 = (dparse(d) + timedelta(days=30)).isoformat()
            d60 = (dparse(d) + timedelta(days=60)).isoformat()
            p30 = price_at(bb, d30, price_mode)
            b0 = price_at(btc, d, price_mode)
            b30 = price_at(btc, d30, price_mode)
            if p30 is None or b0 is None or b30 is None:
                continue
            ex30 = math.log(p30 / p0) - math.log(b30 / b0)
            ex60 = None
            p60, b60 = price_at(bb, d60, price_mode), price_at(btc, d60, price_mode)
            if p60 is not None and b60 is not None:
                ex60 = math.log(p60 / p0) - math.log(b60 / b0)
            dpre = (dparse(d) - timedelta(days=30)).isoformat()
            prev = [x for x in ds if x <= dpre]
            pre30 = (p0 / bb[prev[-1]] - 1.0) if prev else None
            rows.append({
                "id": r["id"], "sym": rsym, "sym_raw": sym, "d": d, "d_ts": r["d_ts"], "d_title": r["d_title"],
                "ex30": ex30, "ex60": ex60, "pre30": pre30, "margin": m,
                "quote": quote, "src": tk["src"], "kind": r["kind"],
                "db_has": sym in (r["db_symbols"] or []), "title": r["title"],
            })
    if dedup_mode != "none":
        seen, keep = set(), []
        for e in sorted(rows, key=lambda x: (x["d"], x["id"])):
            key = e["sym"] if dedup_mode == "sym" else (e["sym"], e["d"][:4])
            if key in seen:
                continue
            seen.add(key)
            keep.append(e)
        rows = keep
    return rows


def main():
    print("== fetch events ==", flush=True)
    events = fetch_events()
    print("events:", len(events))

    parse_rows = []
    for ev in events:
        p = parse_announcement(ev)
        parse_rows.append({
            "id": ev["id"], "ts": ev["ts"], "d_ts": ev["ts"][:10], "d_title": p["title_date"],
            "d_used": p["title_date"] or ev["ts"][:10], "title": ev["title"],
            "scope": (ev["payload"] or {}).get("scope"), "db_symbols": ev["symbols"],
            "margin": p["margin"], "kind": p["kind"], "excl": p["excl"], "tokens": p["tokens"],
        })
    json.dump(parse_rows, open(f"{HERE}/t285_parse_list.json", "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("parse rows:", len(parse_rows), "| tokens:", sum(len(r["tokens"]) for r in parse_rows))
    print("margin:", Counter(r["margin"] for r in parse_rows).most_common())
    print("kind:", Counter(r["kind"] for r in parse_rows).most_common())
    print("d_title != d_ts:", sum(1 for r in parse_rows if r["d_title"] and r["d_title"] != r["d_ts"]))

    raw_syms = {t["sym"] for r in parse_rows for t in r["tokens"]}
    res_syms = {resolve_sym(s) for s in raw_syms} - {None}
    syms = sorted(raw_syms | res_syms | {"BTC"})
    bars = get_bars(syms)
    btc = bars["BTC"]
    print("bars: BTC %d | no-bar symbols %d/%d"
          % (len(btc), sum(1 for s in syms if not bars.get(s)), len(syms)))

    # ── 读法扫描 ────────────────────────────────────────────────────────
    scan = []
    for mname, mset in MARGIN_SETS.items():
        for kname, kset in KIND_SETS.items():
            for map_mode in MAP_MODES:
                for date_mode in DATE_MODES:
                    for price_mode in PRICE_MODES:
                        for spot_mode in SPOT_MODES:
                            for dedup_mode in DEDUP_MODES:
                                rows = build_events(parse_rows, bars, btc, mset, kset, map_mode,
                                                    date_mode, price_mode, spot_mode, dedup_mode)
                                if not rows:
                                    continue
                                med = float(np.median([r["ex30"] for r in rows]))
                                scan.append({
                                    "margin": mname, "kind": kname, "map": map_mode,
                                    "date": date_mode, "price": price_mode,
                                    "spot": spot_mode, "dedup": dedup_mode,
                                    "n": len(rows), "median": med,
                                    "mean": float(np.mean([r["ex30"] for r in rows])),
                                    "dn": len(rows) - 142, "dm": med - (-0.219),
                                })
    json.dump(scan, open(f"{HERE}/_t285_variant_scan.json", "w"), indent=1)
    close = [s for s in scan if abs(s["n"] - 142) <= 7 and abs(s["dm"]) <= 0.015]
    close.sort(key=lambda s: (abs(s["dn"]) + abs(s["dm"]) * 100))
    print("variants scanned:", len(scan), "| n range %d-%d | matching n&median: %d"
          % (min(s['n'] for s in scan), max(s['n'] for s in scan), len(close)))
    for s in close[:14]:
        print("   n=%3d (d%+3d) med=%+.4f (d%+.4f)  %s" %
              (s["n"], s["dn"], s["median"], s["dm"],
               f"{s['margin']}|{s['kind']}|map={s['map']}|date={s['date']}|price={s['price']}|spot={s['spot']}|dedup={s['dedup']}"))
    if not close:
        print("--- n closest ---")
        for s in sorted(scan, key=lambda s: abs(s["dn"]))[:10]:
            print("   n=%3d (d%+3d) med=%+.4f  %s" % (s["n"], s["dn"], s["median"],
                  f"{s['margin']}|{s['kind']}|map={s['map']}|date={s['date']}|price={s['price']}|spot={s['spot']}|dedup={s['dedup']}"))
    best = close[0] if close else None
    print("BEST:", json.dumps(best, ensure_ascii=False))
    json.dump(best, open(f"{HERE}/_t285_best_variant.json", "w"), indent=1)

    # ── 两个读法各跑一遍完整统计 ────────────────────────────────────────
    # A = 我自己写的标题解析(margin=usdt 永续 + 上新类公告)
    # B = 用 events.symbols(库里 11-06 回填过的那一列)走同一套判据
    readings = {
        "A_own_title_parser": dict(margin_set=MARGIN_SETS["usdt"], kind_set=KIND_SETS["launch"],
                                    map_mode="title", date_mode="title", price_mode="exact",
                                    spot_mode="bars+span", dedup_mode="none"),
        "B_db_symbols": dict(margin_set=MARGIN_SETS["usdt+busd+usdc+coinm+none"],
                             kind_set=KIND_SETS["launch"], map_mode="db", date_mode="title",
                             price_mode="exact", spot_mode="bars+span", dedup_mode="none"),
    }
    out = {"card": "T-285", "ledger": "S-764 blind recompute of S-758",
           "n_announcements": len(parse_rows), "readings": {}}
    sets = {}
    for name, cfg in readings.items():
        rows = build_events(parse_rows, bars, btc, **cfg)
        sets[name] = rows
        out["readings"][name] = full_stats(rows, bars, btc)
        out["readings"][name]["config"] = {k: (sorted(v, key=str) if isinstance(v, set) else v)
                                           for k, v in cfg.items()}
        out["readings"][name]["events"] = rows
        print(name, "n=%d median=%.4f mean=%.4f" % (
            len(rows), out["readings"][name]["median_30d"],
            out["readings"][name]["mean_30d"]))

    # 差在哪一步:A 缺、B 有的事件
    keya = {(r["id"], r["sym"]) for r in sets["A_own_title_parser"]}
    keyb = {(r["id"], r["sym"]) for r in sets["B_db_symbols"]}
    only_b = [r for r in sets["B_db_symbols"] if (r["id"], r["sym"]) not in keya]
    only_a = [r for r in sets["A_own_title_parser"] if (r["id"], r["sym"]) not in keyb]
    out["diff"] = {
        "n_only_in_B": len(only_b), "n_only_in_A": len(only_a),
        "only_B": [{"id": r["id"], "sym": r["sym"], "d": r["d"], "margin": r["margin"],
                    "kind": r["kind"], "src": r["src"], "ex30": r["ex30"],
                    "title": r["title"][:150]} for r in only_b],
        "only_A": [{"id": r["id"], "sym": r["sym"], "d": r["d"], "margin": r["margin"],
                    "kind": r["kind"], "src": r["src"], "ex30": r["ex30"],
                    "title": r["title"][:150]} for r in only_a],
    }
    print("diff: only_in_B %d | only_in_A %d" % (len(only_b), len(only_a)))
    out["ledger_reference"] = {
        "n": 142, "median_30d": -0.219, "mean_30d": -0.169, "null_p05": -0.096,
        "percentile": 0.0, "seg_2020_2022": {"n": 69, "median": -0.150},
        "seg_2023_plus": {"n": 73, "median": -0.243},
        "d_filter": {"n_dropped": 66, "n_kept": 76, "median": -0.227}, "sub_60d": -0.321,
    }
    out["variant_scan_best"] = best
    out["variant_scan_n"] = len(scan)
    json.dump(out, open(f"{HERE}/t285_results.json", "w"), ensure_ascii=False, indent=1)
    print("results written ->", f"{HERE}/t285_results.json")


def full_stats(rows, bars, btc, seed=740):
    """主口径统计:(a) 中位/均值 (b) 随机日期对照 (c) 两段 (d) 去掉上线前涨超 50% 的那批 + 副项。"""
    ex30 = [r["ex30"] for r in rows]
    med = float(np.median(ex30))
    mean = float(np.mean(ex30))

    elig = {}
    for r in rows:
        sym = r["sym"]
        if sym not in elig:
            bb = bars.get(sym) or {}
            elig[sym] = [x for x in sorted(bb)
                         if (dparse(x) + timedelta(days=30)).isoformat() in bb]
    ev_list = [(r["sym"], r["d"]) for r in rows]

    def control_median(rng):
        pick = random_dates_like(ev_list, elig, rng)
        vals = []
        for (sym, _), (_, dr) in zip(ev_list, pick):
            if dr is None:
                continue
            bb = bars.get(sym) or {}
            d30 = (dparse(dr) + timedelta(days=30)).isoformat()
            p0, p30 = bb.get(dr), bb.get(d30)
            b0, b30 = btc.get(dr), btc.get(d30)
            if None in (p0, p30, b0, b30) or p0 <= 0 or b0 <= 0:
                continue
            vals.append(math.log(p30 / p0) - math.log(b30 / b0))
        return float("nan") if not vals else float(np.median(vals))

    null = null_distribution(control_median, 1000, seed, actual=med)
    pctl = percentile_of(med, null)

    s1 = [r["ex30"] for r in rows if r["d"] < "2023-01-01"]
    s2 = [r["ex30"] for r in rows if r["d"] >= "2023-01-01"]
    keep = [r for r in rows if not (r["pre30"] is not None and r["pre30"] > 0.5)]
    drop = [r for r in rows if (r["pre30"] is not None and r["pre30"] > 0.5)]
    ex60 = [r["ex60"] for r in rows if r["ex60"] is not None]
    known = [r["ex30"] for r in rows if r["db_has"]]
    titleonly = [r["ex30"] for r in rows if not r["db_has"]]

    def verdict_a():
        return bool(med <= -0.03 and mean < 0)

    def verdict_b():
        return bool(pctl is not None and pctl <= 0.05)

    def verdict_c():
        m1 = float(np.median(s1)) if s1 else None
        m2 = float(np.median(s2)) if s2 else None
        return bool(m1 is not None and m2 is not None and m1 < 0 and m2 < 0)

    def verdict_d():
        mk = float(np.median([r["ex30"] for r in keep])) if keep else None
        return bool(mk is not None and mk < 0)

    return {
        "n": len(rows), "median_30d": med, "mean_30d": mean,
        "null_p05": float(np.percentile(null, 5)), "null_median": float(np.median(null)),
        "percentile": pctl, "n_null": int(len(null)),
        "seg_2020_2022": {"n": len(s1), "median": float(np.median(s1)) if s1 else None},
        "seg_2023_plus": {"n": len(s2), "median": float(np.median(s2)) if s2 else None},
        "d_filter": {"n_dropped": len(drop), "n_kept": len(keep),
                     "median": float(np.median([r["ex30"] for r in keep])) if keep else None},
        "sub_60d": {"n": len(ex60), "median": float(np.median(ex60)) if ex60 else None},
        "sub_db_known": {"n": len(known), "median": float(np.median(known)) if known else None},
        "sub_title_only": {"n": len(titleonly), "median": float(np.median(titleonly)) if titleonly else None},
        "verdicts": {"a": verdict_a(), "b": verdict_b(), "c": verdict_c(), "d": verdict_d()},
        "all_pass": bool(verdict_a() and verdict_b() and verdict_c() and verdict_d()),
    }


if __name__ == "__main__":
    main()
