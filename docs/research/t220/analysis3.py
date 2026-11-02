#!/usr/bin/env python3
"""T-220 ②③ 终版:营销强度事件(metric 分开)+ S-661 开闸事件热度标记。只读、带缓存。"""
import datetime as dt
import json
import os
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_cache")
os.makedirs(CACHE, exist_ok=True)

CIS_CRYPTO = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "INJ",
              "LDO", "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI",
              "TIA", "UNI", "XRP"]
METRICS = ["sentiment_weighted_total", "social_volume_total"]


def page(path, params, rng):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                                              "Accept": "application/json", "Range": rng})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode() or "null")


def fetch_all(path, params, tag=None):
    if tag:
        fp = os.path.join(CACHE, tag + ".json")
        if os.path.exists(fp):
            return json.load(open(fp))
    out, off = [], 0
    while True:
        body = page(path, params, f"{off}-{off+999}")
        if not isinstance(body, list) or not body:
            break
        out.extend(body)
        if len(body) < 1000:
            break
        off += 1000
    if tag:
        json.dump(out, open(os.path.join(CACHE, tag + ".json"), "w"))
    return out


def dstr(x):
    return str(x)[:10]


def zseries(series, win=180, min_obs=60):
    """series: [(date_str, value)] 升序。z = (v_t − mean(前 win 个)) / sd(前 win 个)。"""
    out = {}
    vals = [v for _, v in series]
    for i in range(len(vals)):
        hist = vals[max(0, i - win):i]
        if len(hist) < min_obs:
            continue
        sd = statistics.pstdev(hist) if len(hist) > 1 else 0.0
        if sd <= 0:
            continue
        out[series[i][0]] = (vals[i] - sum(hist) / len(hist)) / sd
    return out


def z30mean(series, win=180, min_obs=60):
    """30 日滚动均值的 z:与「先验窗内所有 30 日滚动均值」比。"""
    out = {}
    n = len(series)
    if n < min_obs + 30:
        return out
    pre = [0.0]
    for _, v in series:
        pre.append(pre[-1] + v)
    roll = [(series[i][0], (pre[i + 1] - pre[i - 29]) / 30.0) for i in range(29, n)]
    for i, (d, m30) in enumerate(roll):
        hist = [m for _, m in roll[max(0, i - win):i]]
        if len(hist) < min_obs:
            continue
        sd = statistics.pstdev(hist)
        if sd <= 0:
            continue
        out[d] = (m30 - sum(hist) / len(hist)) / sd
    return out


def episodes(z, thr=2.0):
    ev, prev = [], False
    for d in sorted(z):
        hot = z[d] > thr
        if hot and not prev:
            ev.append(d)
        prev = hot
    return ev


def build(rows, sym_key, date_key, val_key):
    """-> {sym: [(date, value)]} 按日期升序去重。"""
    d = defaultdict(dict)
    for r in rows:
        try:
            d[r[sym_key]][dstr(r[date_key])] = float(r[val_key])
        except (KeyError, TypeError, ValueError):
            continue
    return {s: sorted(v.items()) for s, v in d.items()}


# ── 取数 ─────────────────────────────────────────────────────────────────────
sym_in = "(" + ",".join(CIS_CRYPTO) + ")"
social = {}
for m in METRICS:
    rows = fetch_all("social_daily", {"select": "symbol,d,value,slug,source", "metric": f"eq.{m}",
                                     "symbol": f"in.{sym_in}", "order": "symbol.asc,d.asc"},
                     f"social25_{m}")
    social[m] = build(rows, "symbol", "d", "value")
    print(m, "rows", len(rows), "symbols", len(social[m]), flush=True)

trend_rows = fetch_all("trending_log", {"select": "symbol,recorded_at,attention_score",
                                         "symbol": f"in.{sym_in}", "order": "symbol.asc,recorded_at.asc"},
                        "trend25")
trend = build(trend_rows, "symbol", "recorded_at", "attention_score")

# 全库(任意币)的 social / trending,供开闸事件查覆盖
all_social_rows = fetch_all("social_daily", {"select": "symbol,d,value,metric",
                                              "order": "symbol.asc,metric.asc,d.asc"}, "social_all_m")
all_social = {m: defaultdict(dict) for m in METRICS}
for r in all_social_rows:
    m = r.get("metric")
    if m in all_social:
        try:
            all_social[m][r["symbol"]][dstr(r["d"])] = float(r["value"])
        except (TypeError, ValueError, KeyError):
            pass
all_trend_rows = fetch_all("trending_log", {"select": "symbol,recorded_at,attention_score",
                                             "order": "symbol.asc,recorded_at.asc"}, "trend_all_m")
all_trend = defaultdict(dict)
for r in all_trend_rows:
    try:
        all_trend[r["symbol"]][dstr(r["recorded_at"])] = float(r["attention_score"])
    except (TypeError, ValueError, KeyError):
        pass
print("all_social symbols per metric:", {m: len(v) for m, v in all_social.items()},
      "all_trend symbols:", len(all_trend), flush=True)

# ── A: CIS 25 的热度事件 ────────────────────────────────────────────────────
res = {}
for m in METRICS:
    res[m] = {}
    for s in CIS_CRYPTO:
        ser = social[m].get(s, [])
        if not ser:
            res[m][s] = {"n_days": 0}
            continue
        z, z30 = zseries(ser), z30mean(ser)
        ev, ev30 = episodes(z), episodes(z30)
        res[m][s] = {"n_days": len(ser), "start": ser[0][0], "end": ser[-1][0],
                     "n_z_gt2_days": sum(1 for v in z.values() if v > 2),
                     "n_events_z_gt2": len(ev), "events": ev,
                     "n_events_z30_gt2": len(ev30), "events_z30": ev30,
                     "max_z": round(max(z.values()), 3) if z else None,
                     "max_z30": round(max(z30.values()), 3) if z30 else None}
    tot_ev = sum(v.get("n_events_z_gt2", 0) for v in res[m].values())
    tot_ev30 = sum(v.get("n_events_z30_gt2", 0) for v in res[m].values())
    ncov = sum(1 for v in res[m].values() if v.get("n_days"))
    print(f"[{m}] 覆盖 {ncov}/25 | 点值 z>2 事件合计 {tot_ev} | 30日均值 z>2 事件合计 {tot_ev30}", flush=True)
    for s in CIS_CRYPTO:
        v = res[m][s]
        if v.get("n_days"):
            print(f"   {s:6s} n={v['n_days']:4d} {v['start']}..{v['end']} "
                  f"ev_z>2={v['n_events_z_gt2']:3d} ev_z30>2={v['n_events_z30_gt2']:3d} "
                  f"max_z={v['max_z']}", flush=True)

tres = {}
for s in CIS_CRYPTO:
    ser = trend.get(s, [])
    if not ser:
        tres[s] = {"n_days": 0}
        continue
    z = zseries(ser, win=60, min_obs=20)
    ev = episodes(z)
    tres[s] = {"n_days": len(ser), "start": ser[0][0], "end": ser[-1][0],
               "n_events_z_gt2": len(ev), "events": ev,
               "max_z": round(max(z.values()), 3) if z else None}
print("[trending_log attention_score] 事件合计:",
      sum(v.get("n_events_z_gt2", 0) for v in tres.values()), flush=True)
json.dump({"social": res, "trend": tres}, open(os.path.join(HERE, "_a_events.json"), "w"),
          ensure_ascii=False, indent=1)

# ── B: S-661 开闸事件 ────────────────────────────────────────────────────────
ONSET = json.load(open(os.path.join(HERE, "_s661_onset.json")))
mcap = fetch_all("asset_mcap_daily", {"select": "coin_id,symbol,d",
                                      "coin_id": f"in.{({e['g'] for e in ONSET} and ','.join(e['g'] for e in ONSET))})",
                                      "order": "coin_id.asc,symbol.asc,d.asc"}, "mcap_onset")
gid2sym = defaultdict(set)
for r in mcap:
    if r.get("coin_id") and r.get("symbol"):
        gid2sym[r["coin_id"]].add(r["symbol"])
slug2sym = {}
for sym, slugs in json.load(open(os.path.join(HERE, "_social_slug_map.json"))).items():
    for sl in slugs:
        slug2sym.setdefault(sl, sym)

zs = {m: {s: zseries(sorted(v.items())) for s, v in d.items()} for m, d in all_social.items()}
z30s = {m: {s: z30mean(sorted(v.items())) for s, v in d.items()} for m, d in all_social.items()}
tz = {s: zseries(sorted(v.items()), win=60, min_obs=20) for s, v in all_trend.items()}

rows_out = []
for ev in ONSET:
    g = ev["g"]
    on = dt.date.fromisoformat(ev["onset"])
    lo, hi = on - dt.timedelta(days=30), on + dt.timedelta(days=30)
    cand = list(dict.fromkeys(sorted(gid2sym.get(g, set())) +
                              ([slug2sym[g]] if g in slug2sym else [])))
    row = {"g": g, "onset": ev["onset"], "sym_candidates": cand, "mcap_usd_m": ev.get("mcap"),
           "rel_1m": ev.get("rel_1m"), "rel_3m": ev.get("rel_3m"), "rel_6m": ev.get("rel_6m")}
    for m in METRICS:
        sym = next((c for c in cand if c in zs[m] and zs[m][c]), None)
        row[f"{m}_symbol"] = sym
        if not sym:
            row[f"{m}_pre30_z_max"] = None
            row[f"{m}_pre30_covered"] = False
            row[f"{m}_peak_pre30"] = None
            continue
        z = zs[m][sym]
        pre = {d: v for d, v in z.items() if lo <= dt.date.fromisoformat(d) < on}
        pre30 = {d: v for d, v in z30s[m][sym].items() if lo <= dt.date.fromisoformat(d) < on}
        post = {d: v for d, v in z.items() if on <= dt.date.fromisoformat(d) <= hi}
        row[f"{m}_series"] = [min(z), max(z)]
        row[f"{m}_pre30_n"] = len(pre)
        row[f"{m}_pre30_z_max"] = round(max(pre.values()), 3) if pre else None
        row[f"{m}_pre30_z30_max"] = round(max(pre30.values()), 3) if pre30 else None
        row[f"{m}_pre30_covered"] = len(pre) >= 20
        row[f"{m}_peak_pre30"] = bool(pre and max(pre.values()) > 2)
        row[f"{m}_peak_pre30_z30"] = bool(pre30 and max(pre30.values()) > 2)
        row[f"{m}_post30_z_max"] = round(max(post.values()), 3) if post else None
    tsym = next((c for c in cand if c in tz and tz[c]), None)
    row["trend_symbol"] = tsym
    if tsym:
        pre = {d: v for d, v in tz[tsym].items() if lo <= dt.date.fromisoformat(d) < on}
        row["trend_series"] = [min(tz[tsym]), max(tz[tsym])]
        row["trend_pre30_n"] = len(pre)
        row["trend_pre30_z_max"] = round(max(pre.values()), 3) if pre else None
        row["trend_peak_pre30"] = bool(pre and max(pre.values()) > 2)
    rows_out.append(row)
    print("onset", json.dumps(row, ensure_ascii=False)[:520], flush=True)
json.dump(rows_out, open(os.path.join(HERE, "_b_onset.json"), "w"), ensure_ascii=False, indent=1)
print("saved _a_events.json / _b_onset.json")
