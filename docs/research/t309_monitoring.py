#!/usr/bin/env python3
"""T-309 — S-789:S-753 在逐句解析之后重量(打上监控标签的代号 80 → 137)。

**只换事件,其余口径一字不改照 T-274 / S-753。**
唯一改动:事件集 = 每个代号**第一次**出现在某条公告的「打上」句里
(`src.data.market.events.monitoring_tag_changes(title)["add"]`,逐句解析,v2),
不再用 v1 的整行解析。价格源、对照([d0−365, d0−60] 随机 200 日)、种子、窗口、判据 (a)–(e) 全部照旧。

阶段(先落文件,再往下走):
  screen  事件清单 → docs/research/t309_events.csv + t309_screening.json
  prices  拉价格   → docs/research/t309_price_cache.json
  stats   算 + 判据 → docs/research/t309_results.json
  all     三段连跑

用法:python3 docs/research/t309_monitoring.py [screen|prices|stats|all]
"""
import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
from data.evaluation.apparatus import (  # noqa: E402
    long_return,
    null_distribution,
    percentile_of,
    price_on_or_after,
    random_dates_like,
)
from data.market.events import (  # noqa: E402  (生产解析器,v2 逐句)
    monitoring_tag as parse_monitoring_tag,
    monitoring_tag_changes,
)

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "t309_events.csv")
SCREEN_PATH = os.path.join(HERE, "t309_screening.json")
PRICE_PATH = os.path.join(HERE, "t309_price_cache.json")
RESULT_PATH = os.path.join(HERE, "t309_results.json")
# 旧事件集(v1 整行解析,T-274 那次跑的 80 个)—— 只用于报差,不参与统计
OLD_CSV_PATH = os.path.join(HERE, "t274_events.csv")

SEED = 20261108
N_SAMP = 200
H_MAIN, H_SUB = 30, 7
# 取价窗口:对照日最晚 d0−60,再加 30 天 ⇒ 往前 400 天、往后 40 天够用
BACK, FWD = 400, 40


# ── Supabase REST(只读)──────────────────────────────────────────────────────
def rest(path, timeout=180):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def rest_rows(path, page=1000):
    """order= 必带;每页 ≤ 1000;offset 分页。"""
    out, off = [], 0
    while True:
        got = json.loads(rest(f"{path}&limit={page}&offset={off}"))
        out.extend(got)
        if len(got) < page:
            break
        off += page
        if off > 20000:
            break
    return out


def fetch_series(sym, table, extra, dkey, lo, hi):
    """拉一个 symbol 在 [lo, hi] 区间内的日频序列(分页 ≤ 1000)。"""
    path = (f"{table}?symbol=eq.{sym}{extra}&{dkey}=gte.{lo}&{dkey}=lte.{hi}"
            f"&order={dkey}.asc")
    rows, off = [], 0
    while True:
        got = None
        for _ in range(3):
            try:
                got = json.loads(rest(f"{path}&limit=1000&offset={off}"))
                break
            except Exception:
                time.sleep(1.5)
        if got is None:
            print(f"   !! {table} {sym} 拉取失败(offset={off})")
            break
        rows.extend(got)
        if len(got) < 1000:
            break
        off += 1000
    return rows


# ── 阶段 1:screen ───────────────────────────────────────────────────────────
def removed_monitoring_tokens(title):
    """从「Remove the Monitoring Tag for X, Y」里取出被移除监控标签的代币。"""
    m = re.search(r"Remove\s+the\s+Monitoring\s+Tag\s+for\s+(.*)", title or "", re.IGNORECASE)
    if not m:
        return []
    seg = m.group(1)
    seg = re.split(r"and\s+Remove|and\s+the\s+Seed|,?\s*and\s+the\s+Seed", seg, maxsplit=1, flags=re.IGNORECASE)[0]
    seg = re.sub(r"\(?\d{4}-\d{2}-\d{2}\)?", " ", seg)
    out, seen = [], set()
    for s in re.findall(r"\b[A-Z0-9]{2,12}\b", seg):
        if s.isdigit() or s in ("AND", "THE", "FOR", "OF") or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def phase_screen():
    """v2 逐句:事件 = 每个代号第一次出现在某条公告的「打上」句里。"""
    rows = rest_rows("events?kind=eq.monitoring_tag&source=eq.binance&order=id.asc")
    rem_rows = rest_rows("events?kind=eq.monitoring_tag_removed&source=eq.binance&order=id.asc")
    print(f"[screen] monitoring_tag {len(rows)} 条 / monitoring_tag_removed {len(rem_rows)} 条")

    anns = []
    for r in rows + rem_rows:
        ch = monitoring_tag_changes(r.get("title"))
        anns.append({"id": r["id"], "ts": r["ts"], "title": r["title"],
                     "kind_db": r.get("kind"), "symbols_db": r.get("symbols"),
                     "add": ch["add"], "rem_mon": ch["rem_mon"], "rem_seed": ch["rem_seed"],
                     "n_add": len(ch["add"])})
    anns.sort(key=lambda a: a["ts"])

    # 每个代号取第一次「出现在打上句里」
    first = {}
    for a in anns:
        for s in a["add"]:
            if s not in first or a["ts"] < first[s]["ts"]:
                first[s] = a
    launch = [a for a in anns if a["n_add"] == 0]
    print(f"[screen] 公告 {len(anns)} 条;有「打上」句的 {len(anns) - len(launch)} 条;"
          f"打上代币行 {sum(a['n_add'] for a in anns)};**首次打标签的代币 {len(first)} 个**")
    print(f"[screen] 无「打上」句的公告:",
          [(a["ts"][:10], a["kind_db"], a["title"][:60]) for a in launch])
    print(f"[screen] 库里的 kind 与实际是否含「打上」句不一致的公告:",
          [(a["ts"][:10], a["kind_db"], a["n_add"], a["title"][:70])
           for a in anns if (a["n_add"] > 0) != (a["kind_db"] == "monitoring_tag")])

    # 前提核对(台账 S-753 前提更正):代币数 ≥ 30 ∧ 最早一条 = 标签推出日
    earliest_event = anns[0]["ts"][:10]
    pre_ok = len(first) >= 30 and earliest_event == "2023-07-26"

    # 副项:监控标签被移除(口径照 t274 —— 正则从整行取,只报不判)
    removed = []
    for r in rem_rows:
        toks = removed_monitoring_tokens(r.get("title"))
        if toks:
            removed.append({"id": r["id"], "ts": r["ts"], "title": r["title"], "symbols": toks})
    print(f"[screen] 「Remove the Monitoring Tag」公告 {len(removed)} 条,涉及代币",
          sorted({s for x in removed for s in x['symbols']}))

    # CSV(先落文件,再取价)
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "d0", "ts", "event_id", "n_add_in_ann", "kind_db", "title"])
        for s in sorted(first, key=lambda x: (first[x]["ts"], x)):
            a = first[s]
            w.writerow([s, a["ts"][:10], a["ts"], a["id"], a["n_add"], a["kind_db"], a["title"]])
    print(f"[screen] 落 {CSV_PATH} ({len(first)} 行)")

    # ── 新旧事件集的差(v1 的 t274_events.csv 是旧事件集的唯一记录)──────────
    old = {}
    if os.path.exists(OLD_CSV_PATH):
        with open(OLD_CSV_PATH, newline="") as f:
            for r in csv.DictReader(f):
                old[r["symbol"]] = r
    new_syms = set(first)
    old_syms = set(old)
    added = sorted(new_syms - old_syms)
    dropped = sorted(old_syms - new_syms)
    d0_changed = sorted(s for s in new_syms & old_syms
                        if old[s]["d0"] != first[s]["ts"][:10])
    print(f"[screen] 旧事件集 {len(old_syms)} 个 / 新事件集 {len(new_syms)} 个;"
          f"新增 {len(added)} / 只在旧集 {len(dropped)} / d0 变了 {len(d0_changed)}")
    print(f"[screen] 新增: {added}")
    if dropped:
        print(f"[screen] 只在旧集: {dropped}")
    if d0_changed:
        print(f"[screen] d0 变了: {[(s, old[s]['d0'], first[s]['ts'][:10]) for s in d0_changed]}")

    out = {
        "task": "T-309", "ledger": "S-789", "run_utc": "2026-11-09",
        "screen_rule": {
            "events": "events where source=binance and kind in (monitoring_tag, monitoring_tag_removed)",
            "symbol_parser": "src/data/market/events.py::monitoring_tag_changes(title)['add'] (v2 逐句)",
            "one_event_per_token": "同一代号多次出现在「打上」句里取最早一次(ts)",
            "d0": "公告 ts 的 UTC 日期(asset_mcap_daily 的 d 是当日收盘)",
            "changed_vs_T274": "只换事件;价格源 / 对照 / 种子 / 窗口 / 判据 (a)–(e) 一字未改",
        },
        "precondition": {
            "n_tokens_first_tag": len(first),
            "n_tokens_ge_30": len(first) >= 30,
            "earliest_event_date": earliest_event,
            "earliest_is_tag_launch_day": earliest_event == "2023-07-26",
            "earliest_token_first_tag": min(first[s]["ts"] for s in first)[:10] if first else None,
            "pass": pre_ok,
        },
        "diff_vs_old": {
            "n_old": len(old_syms), "n_new": len(new_syms),
            "added": added, "dropped": dropped,
            "d0_changed": [{"symbol": s, "old_d0": old[s]["d0"], "new_d0": first[s]["ts"][:10]}
                           for s in d0_changed],
            "old_d0": {s: old[s]["d0"] for s in sorted(old_syms)},
        },
        "launch_announcements_no_symbols": launch,
        "announcements": anns,
        "removed_monitoring_tag_announcements": removed,
        "tokens": {s: {"ts": first[s]["ts"], "d0": first[s]["ts"][:10], "id": first[s]["id"],
                       "title": first[s]["title"]} for s in sorted(first)},
        "old_tokens": sorted(old_syms),
        "new_tokens": added,
    }
    with open(SCREEN_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[screen] 落 {SCREEN_PATH}")
    return out


# ── 阶段 2:prices ───────────────────────────────────────────────────────────
def phase_prices():
    sc = json.load(open(SCREEN_PATH))
    cache = {"asset_mcap_daily": {}, "ohlcv_daily": {}}
    if os.path.exists(PRICE_PATH):
        cache = json.load(open(PRICE_PATH))

    btc_lo, btc_hi = "2019-01-01", "2026-11-30"
    windows = {}

    def want(sym, d0):
        lo = (d0 - timedelta(days=BACK)).isoformat()
        hi = (d0 + timedelta(days=FWD)).isoformat()
        cur = windows.get(sym)
        if cur is None:
            windows[sym] = (lo, hi)
        else:
            windows[sym] = (min(cur[0], lo), max(cur[1], hi))

    for s, ev in sc["tokens"].items():
        want(s, date.fromisoformat(ev["d0"]))
    # 下架公告日可能远在打标签之后(中位 62 天)—— 窗口要够到公告日,否则「前移规则吃到多少」算不出来
    try:
        dw = rest_rows("delisting_watch?order=symbol.asc")
        for r in dw:
            s, a = r.get("symbol"), r.get("announced_at")
            if s and a and s in sc["tokens"]:
                want(s, date.fromisoformat(a[:10]))
    except Exception as e:
        print("   !! delisting_watch 读取失败:", e)
    # 副项:监控标签被移除的代币 —— 移除日附近也要有价(不在打标签窗口里)
    for rr in sc.get("removed_monitoring_tag_announcements", []):
        d0 = date.fromisoformat(rr["ts"][:10])
        for s in rr["symbols"]:
            want(s, d0)
    btc_job = ("BTC", btc_lo, btc_hi)
    jobs = [(s, lo, hi) for s, (lo, hi) in sorted(windows.items())]

    def cached_covers(sym, lo, hi):
        rows = cache["asset_mcap_daily"].get(sym)
        if not rows:
            return False
        ds = [str(r.get("d") or "")[:10] for r in rows if r.get("d")]
        if not ds:
            return False
        return min(ds) <= lo and max(ds) >= hi

    todo = [j for j in jobs if not cached_covers(j[0], j[1], j[2])]
    if "BTC" not in cache["asset_mcap_daily"]:
        todo.append(btc_job)
    print(f"[prices] {len(todo)} 个 symbol 待拉(缓存窗口不够的也要重拉)")

    def job(j):
        sym, lo, hi = j
        return (sym,
                fetch_series(sym, "asset_mcap_daily", "", "d", lo, hi),
                fetch_series(sym, "ohlcv_daily", "&source=eq.coingecko_pro_ohlc", "trade_date", lo, hi))

    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, m, o in ex.map(job, todo):
            cache["asset_mcap_daily"][sym] = m
            cache["ohlcv_daily"][sym] = o
            done += 1
            if done % 20 == 0:
                with open(PRICE_PATH, "w") as f:
                    json.dump(cache, f)
                print(f"   .. {done}/{len(todo)}")

    with open(PRICE_PATH, "w") as f:
        json.dump(cache, f)
    nm = sum(len(v) for v in cache["asset_mcap_daily"].values())
    no = sum(len(v) for v in cache["ohlcv_daily"].values())
    srcs = Counter(r.get("source") for rows in cache["asset_mcap_daily"].values() for r in rows)
    print(f"[prices] asset_mcap_daily {nm} 行 / ohlcv_daily {no} 行;asset_mcap source 分布 {dict(srcs)}")
    cov = sum(1 for s in sc["tokens"] if cache["asset_mcap_daily"].get(s))
    print(f"[prices] 覆盖率:asset_mcap_daily 命中 {cov}/{len(sc['tokens'])} 个代币")
    return cache


# ── 阶段 3:stats ────────────────────────────────────────────────────────────
def build(rows, dkey, pkey, src_pref="coingecko_pro_market_chart"):
    """symbol → {date: price};同一 (symbol,date) 多来源时优先 src_pref。"""
    tmp = defaultdict(dict)
    prio = defaultdict(dict)
    for r in rows:
        v = r.get(pkey)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not (fv > 0 and math.isfinite(fv)):
            continue
        dd = str(r[dkey])[:10]
        s = r["symbol"]
        p = 0 if r.get("source") == src_pref else 1
        if dd not in tmp[s] or p < prio[s][dd]:
            tmp[s][dd] = fv
            prio[s][dd] = p
    return tmp


def before_price(dates, closes, d, max_gap_days=3):
    """d 当天或之前 max_gap_days 天内的最后一个有效收盘(apparatus 只有向后版本)。
    只做取价,统计一律走 apparatus。"""
    tgt = date.fromisoformat(str(d)[:10])
    best = None
    for dd, c in zip(dates, closes):
        dd_ = date.fromisoformat(str(dd)[:10])
        if dd_ > tgt:
            continue
        if (tgt - dd_).days > max_gap_days:
            continue
        try:
            fv = float(c)
        except (TypeError, ValueError):
            continue
        if fv > 0 and math.isfinite(fv):
            best = fv
    return best


def quant(vals, q):
    """分位数(线性插值,不用 numpy 以免多依赖)。"""
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return float(v[0])
    pos = q * (len(v) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(v[lo])
    return float(v[lo] + (v[hi] - v[lo]) * (pos - lo))


def stats_block(vals):
    if not vals:
        return None
    v = sorted(vals)
    return {"n": len(v), "median": quant(v, 0.5), "mean": sum(v) / len(v),
            "p10": quant(v, 0.10), "p90": quant(v, 0.90),
            "pct_negative": sum(1 for x in v if x < 0) / len(v)}


def phase_stats():
    sc = json.load(open(SCREEN_PATH))
    px = json.load(open(PRICE_PATH))
    mcap_rows = [r for rows in px["asset_mcap_daily"].values() for r in rows]
    ohlc_rows = [r for rows in px["ohlcv_daily"].values() for r in rows]
    MCAPV = build(mcap_rows, "d", "mcap")
    SRC = {"mcap": build(mcap_rows, "d", "price"), "ohlc": build(ohlc_rows, "trade_date", "close")}

    def anchors(tbl, s, d0):
        dates = sorted(tbl.get(s, {}))
        closes = [tbl[s][x] for x in dates]
        g = lambda t: price_on_or_after(dates, closes, t, 3)  # noqa: E731
        return {"m1": before_price(dates, closes, (d0 - timedelta(days=1)).isoformat(), 3),
                "m30": before_price(dates, closes, (d0 - timedelta(days=30)).isoformat(), 3),
                "d0": g(d0.isoformat()),
                "p7": g((d0 + timedelta(days=H_SUB)).isoformat()),
                "p30": g((d0 + timedelta(days=H_MAIN)).isoformat())}

    def run_source(name):
        tbl = SRC[name]
        btc = tbl.get("BTC", {})
        bdates, bcloses = sorted(btc), [btc[x] for x in sorted(btc)]
        btc_g = lambda t: price_on_or_after(bdates, bcloses, t, 3)  # noqa: E731
        per_token = {}
        for sym, ev in sc["tokens"].items():
            d0 = date.fromisoformat(ev["d0"])
            if sym not in tbl:
                per_token[sym] = {"status": "no_price_source", "d0": d0.isoformat(),
                                  "ts": ev["ts"], "title": ev["title"]}
                continue
            a = anchors(tbl, sym, d0)
            b = {"m1": before_price(bdates, bcloses, (d0 - timedelta(days=1)).isoformat(), 3),
                 "m30": before_price(bdates, bcloses, (d0 - timedelta(days=30)).isoformat(), 3),
                 "d0": btc_g(d0.isoformat()),
                 "p7": btc_g((d0 + timedelta(days=H_SUB)).isoformat()),
                 "p30": btc_g((d0 + timedelta(days=H_MAIN)).isoformat())}
            r = {"status": "ok", "ts": ev["ts"], "d0": d0.isoformat(), "title": ev["title"],
                 "token": a, "btc": b}
            for tag, (k0, k1) in {"ret30": ("d0", "p30"), "ret7": ("d0", "p7"),
                                  "jump": ("m1", "d0"), "pre30": ("m30", "d0")}.items():
                tr, br = long_return(a[k0], a[k1]), long_return(b[k0], b[k1])
                r[tag] = None if (tr is None or br is None) else tr - br
                r[tag + "_tok"] = tr
                r[tag + "_btc"] = br
            per_token[sym] = r

        usable = {s: r for s, r in per_token.items() if r.get("status") == "ok" and r.get("ret30") is not None}
        vals = [r["ret30"] for r in usable.values()]
        med = quant(sorted(vals), 0.5) if vals else None
        neg = sum(1 for v in vals if v < 0)

        # (d) 按事件日期对半分两段(台账 S-753 的写法,不是固定年份切分)
        seg = {}
        if usable:
            order = sorted(usable.values(), key=lambda r: (r["d0"], r["ts"]))
            half = len(order) // 2
            parts = {"early": order[:half], "late": order[half:]}
            for nm, part in parts.items():
                vv = sorted(r["ret30"] for r in part)
                seg[nm] = {"n": len(vv), "median": quant(vv, 0.5) if vv else None,
                           "mean": (sum(vv) / len(vv)) if vv else None,
                           "d0_range": [part[0]["d0"], part[-1]["d0"]] if part else None}
            # 按日期排序时可能把同一天的代币切在两半 —— 记一份边界
            seg["boundary_d0"] = parts["early"][-1]["d0"] if parts["early"] else None

        # 对照:同一代币 [d0−365, d0−60] 里随机取日子(口径同 T-272)
        eligible = {}
        for s, r in usable.items():
            d0 = date.fromisoformat(r["d0"])
            lo, hi = d0 - timedelta(days=365), d0 - timedelta(days=60)
            cand = [dd for dd in sorted(tbl.get(s, {}))
                    if lo <= date.fromisoformat(dd) <= hi]
            eligible[s] = cand
        usable_pairs = [(s, usable[s]["d0"]) for s in sorted(usable) if eligible.get(s)]

        def one_draw(rng):
            picks = random_dates_like(usable_pairs, eligible, rng, stratum=lambda x: "all")
            vs = []
            for s, d in picks:
                if d is None:
                    continue
                dd = date.fromisoformat(d)
                ds = sorted(tbl.get(s, {}))
                cs = [tbl[s][x] for x in ds]
                p0 = price_on_or_after(ds, cs, d, 3)
                p1 = price_on_or_after(ds, cs, (dd + timedelta(days=H_MAIN)).isoformat(), 3)
                b0 = btc_g(d)
                b1 = btc_g((dd + timedelta(days=H_MAIN)).isoformat())
                tr, br = long_return(p0, p1), long_return(b0, b1)
                if tr is None or br is None:
                    continue
                vs.append(tr - br)
            if not vs:
                return None
            return quant(sorted(vs), 0.5)

        null = null_distribution(one_draw, N_SAMP, seed=SEED, actual=med)
        null_f = [x for x in null if x is not None]
        pctl = percentile_of(med, null_f)
        return {"source": name, "n_tokens_total": len(per_token),
                "n_tokens_with_price": sum(1 for r in per_token.values() if r.get("status") == "ok"),
                "n_exc30_computable": len(usable),
                "exc30": stats_block(vals),
                "median_exc30": med, "pct_negative_exc30": (neg / len(vals)) if vals else None,
                "n_negative": neg,
                "segments": seg,
                "control": {"n_samples": N_SAMP, "seed": SEED,
                            "null_median_q": {"q05": quant(null_f, 0.05), "q50": quant(null_f, 0.5),
                                              "q95": quant(null_f, 0.95)} if null_f else None,
                            "percentile_of_actual": pctl, "n_draws_used": len(null_f)},
                "per_token": per_token}

    res = {name: run_source(name) for name in SRC}
    primary = res["mcap"]

    # ── 判据(照 S-753 (a)–(e),主源 asset_mcap_daily)────────────────────────
    a_ok = primary["median_exc30"] is not None and primary["median_exc30"] <= -0.05
    b_ok = primary["pct_negative_exc30"] is not None and primary["pct_negative_exc30"] >= 0.60
    c_ok = (primary["control"]["percentile_of_actual"] is not None
            and primary["control"]["percentile_of_actual"] <= 0.05)
    e_ok = primary["n_exc30_computable"] >= 30
    s1 = primary["segments"].get("early", {}).get("median")
    s2 = primary["segments"].get("late", {}).get("median")
    n1 = primary["segments"].get("early", {}).get("n")
    n2 = primary["segments"].get("late", {}).get("n")
    d_ok = (s1 is not None and s2 is not None and (s1 < 0) == (s2 < 0)
            and n1 is not None and n2 is not None and n1 >= 10 and n2 >= 10)
    verdict = "PASS" if all([a_ok, b_ok, c_ok, d_ok, e_ok]) else "FAIL"
    primary["criteria"] = {
        "(a) 30天超额中位数 ≤ −5%": {"value": primary["median_exc30"], "pass": a_ok},
        "(b) ≥60% 事件超额为负": {"value": primary["pct_negative_exc30"], "pass": b_ok},
        "(c) 对照分位 ≤ 0.05": {"value": primary["control"]["percentile_of_actual"], "pass": c_ok},
        "(d) 按事件日期对半分两段,中位同号且每段 ≥ 10 个有价代币": {
            "value": {"early": {"n": n1, "median": s1}, "late": {"n": n2, "median": s2}}, "pass": d_ok},
        "(e) 有价代币 ≥ 30": {"value": primary["n_exc30_computable"], "pass": e_ok},
    }
    primary["verdict"] = verdict

    # ── 副项(只报不判)─────────────────────────────────────────────────────
    prim = primary["per_token"]
    # ① 180 天内被宣布整币下架的比例(delisting_watch)
    dw = rest_rows("delisting_watch?order=symbol.asc")
    ann_at = {}
    for r in dw:
        a = r.get("announced_at")
        if a:
            ann_at.setdefault(r["symbol"], []).append(a[:10])
    within180, anytime, n_tag = [], [], 0
    detail = []
    for s, ev in sc["tokens"].items():
        n_tag += 1
        d0 = date.fromisoformat(ev["d0"])
        anns = ann_at.get(s, [])
        hit180 = [a for a in anns if 0 <= (date.fromisoformat(a) - d0).days <= 180]
        if hit180:
            within180.append(s)
        if anns:
            anytime.append(s)
        detail.append({"symbol": s, "d0": ev["d0"], "announced_at": sorted(anns),
                       "within_180d": bool(hit180)})
    secondary_delist = {
        "n_tagged": n_tag,
        "n_in_delisting_watch_anytime": len(anytime),
        "pct_delisted_anytime": len(anytime) / n_tag if n_tag else None,
        "n_delisted_within_180d": len(within180),
        "pct_delisted_within_180d": len(within180) / n_tag if n_tag else None,
        "symbols_within_180d": sorted(within180),
        "detail": detail,
    }
    # 副项:把硬规则从「下架公告」前移到「打标签」实际吃到的那一段(只报,不判)
    tbl_m = SRC["mcap"]
    btc_m = tbl_m.get("BTC", {})
    bdm = sorted(btc_m)
    bcm = [btc_m[x] for x in bdm]
    gain_rows = []
    for s, ev in sc["tokens"].items():
        r = prim.get(s)
        if not r or r.get("status") != "ok" or r.get("ret30") is None:
            continue
        d0 = date.fromisoformat(ev["d0"])
        anns = sorted(a for a in ann_at.get(s, []) if date.fromisoformat(a) > d0)
        if not anns:
            continue
        a = anns[0]
        ad = date.fromisoformat(a)
        ds = sorted(tbl_m.get(s, {}))
        cs = [tbl_m[s][x] for x in ds]
        p0 = price_on_or_after(ds, cs, d0.isoformat(), 3)
        p1 = price_on_or_after(ds, cs, a, 3)
        b0 = price_on_or_after(bdm, bcm, d0.isoformat(), 3)
        b1 = price_on_or_after(bdm, bcm, a, 3)
        tr, br = long_return(p0, p1), long_return(b0, b1)
        gain_rows.append({"symbol": s, "tag_d0": ev["d0"], "announced_at": a,
                          "days_gained": (ad - d0).days,
                          "exc_tag_to_ann": None if (tr is None or br is None) else tr - br})
    gex = [g["exc_tag_to_ann"] for g in gain_rows if g.get("exc_tag_to_ann") is not None]
    gdays = [g["days_gained"] for g in gain_rows]
    secondary_gain = {"note": "把『下架公告即剔除』前移到『打标签即剔除』,中间这一段的超额(只报,不判)",
                      "n_rows": len(gain_rows), "n_computable": len(gex),
                      "exc_tag_to_ann": stats_block(gex),
                      "days_gained": stats_block(gdays),
                      "rows": gain_rows}
    # ② 标签被移除之后 30 天(同一口径)
    removed_rows = []
    for rr in sc.get("removed_monitoring_tag_announcements", []):
        d0 = date.fromisoformat(rr["ts"][:10])
        tbl = SRC["mcap"]
        btc = tbl.get("BTC", {})
        bd, bc = sorted(btc), [btc[x] for x in sorted(btc)]
        for s in rr["symbols"]:
            row = {"symbol": s, "ts": rr["ts"], "d0": d0.isoformat()}
            if s not in tbl:
                row["status"] = "no_price_source"
                removed_rows.append(row)
                continue
            a = anchors(tbl, s, d0)
            b0 = price_on_or_after(bd, bc, d0.isoformat(), 3)
            b1 = price_on_or_after(bd, bc, (d0 + timedelta(days=H_MAIN)).isoformat(), 3)
            tr, br = long_return(a["d0"], a["p30"]), long_return(b0, b1)
            row["exc30"] = None if (tr is None or br is None) else tr - br
            row["status"] = "ok"
            removed_rows.append(row)
    rexc = [x["exc30"] for x in removed_rows if x.get("exc30") is not None]
    secondary_removed = {"n_rows": len(removed_rows), "n_computable": len(rexc),
                         "exc30": stats_block(rexc), "rows": removed_rows}
    # ③ 按标签前市值三分位
    mv = {}
    for s, r in prim.items():
        if r.get("status") != "ok":
            continue
        t = MCAPV.get(s, {})
        ds = sorted(t)
        cs = [t[x] for x in ds]
        v = before_price(ds, cs, (date.fromisoformat(r["d0"]) - timedelta(days=1)).isoformat(), 3)
        if v is not None:
            mv[s] = v
    tert = {}
    if len(mv) >= 6:
        srt = sorted(mv, key=lambda x: mv[x])
        k = len(srt) // 3
        for nm, mem in {"low": srt[:k], "mid": srt[k:2 * k], "high": srt[2 * k:]}.items():
            vv = [prim[s]["ret30"] for s in mem if prim[s].get("ret30") is not None]
            tert[nm] = {"n": len(vv), "exc30": stats_block(vv),
                        "mcap_lo": min(mv[s] for s in mem), "mcap_hi": max(mv[s] for s in mem)}
    # ④ 副项:公告前 30 天超额 / 公告当天跳空 / 7 天超额
    def sub(tag):
        vv = [v[tag] for v in prim.values() if v.get("status") == "ok" and v.get(tag) is not None]
        return stats_block(vv)
    secondary_extras = {"pre30_exc": sub("pre30"), "announce_day_jump": sub("jump"), "exc7": sub("ret7")}

    # ── 新旧事件集的分组统计(S-789 要求:新增那批单独的中位)──────────────────
    def subset_stats(sym_set, per_tok):
        rows = [per_tok[s] for s in sorted(sym_set) if s in per_tok
                and per_tok[s].get("status") == "ok" and per_tok[s].get("ret30") is not None]
        vals = [r["ret30"] for r in rows]
        blk = stats_block(vals)
        blk["n_symbols"] = len(sym_set)
        blk["n_no_price"] = len(sym_set) - len(rows)
        blk["d0_range"] = [min(r["d0"] for r in rows), max(r["d0"] for r in rows)] if rows else None
        return blk

    new_syms = set(sc.get("new_tokens", []))
    old_syms = set(sc.get("old_tokens", []))
    subsets = {
        "note": "同一套口径(主源 asset_mcap_daily)下的分组统计",
        "new_only": subset_stats(new_syms, primary["per_token"]),
        "old_only": subset_stats(old_syms - new_syms, primary["per_token"]),
        "old_set": subset_stats(old_syms, primary["per_token"]),
        "all": subset_stats(set(sc["tokens"]), primary["per_token"]),
        "new_only_ohlc": subset_stats(new_syms, res["ohlc"]["per_token"]),
        "old_set_ohlc": subset_stats(old_syms, res["ohlc"]["per_token"]),
    }
    print("[stats] 分组:", json.dumps({k: v for k, v in subsets.items() if k != "note"},
                                     ensure_ascii=False, default=str)[:1500])

    out = {"task": "T-309", "ledger": "S-789", "run_utc": "2026-11-09",
           "seed": SEED, "primary_source": "asset_mcap_daily",
           "precondition": sc["precondition"],
           "n_tokens_first_tag": len(sc["tokens"]),
           "diff_vs_old": sc.get("diff_vs_old"),
           "sources": res, "verdict": verdict, "criteria": primary["criteria"],
           "subsets": subsets,
           "secondary": {"note": "副项只报不判",
                         "delisting_180d": secondary_delist,
                         "monitoring_tag_removed_30d": secondary_removed,
                         "rule_advance_gain": secondary_gain,
                         "mcap_tertile": tert,
                         "extras": secondary_extras}}
    with open(RESULT_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[stats] 落 {RESULT_PATH}")
    print(json.dumps({"verdict": verdict, "criteria": primary["criteria"],
                      "exc30": primary["exc30"], "segments": primary["segments"],
                      "control": primary["control"]}, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    ph = sys.argv[1] if len(sys.argv) > 1 else "all"
    if ph in ("screen", "all"):
        phase_screen()
    if ph in ("prices", "all"):
        phase_prices()
    if ph in ("stats", "all"):
        phase_stats()
