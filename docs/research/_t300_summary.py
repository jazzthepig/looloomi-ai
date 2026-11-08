#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-300 汇总:从 t300_results.json 里挑出报告要用的数。同一个文件反复改。"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "t300_results.json")))
EV = json.load(open(os.path.join(HERE, "t300_events.json")))

print("== 事件计数 ==")
c = R["event_counts"]
for k in ("listing_rows", "listing_symbol_rows_krw_true", "listing_symbol_rows_krw_null",
          "listing_symbol_rows_krw_false", "listing_krw_events_kept",
          "listing_krw_dup_symbol_dropped", "parser_v2_rows"):
    print(f"   {k}: {c[k]}")
print("   listing_by_year_krw_true:", c["listing_by_year_krw_true"])

print("\n== 与 T-291 对比 ==")
print(json.dumps(R["t291_comparison"], ensure_ascii=False, indent=1))

for v in ("chained", "literal", "none"):
    V = R["variants"][v]
    a = V["arms"]["listing_krw"]
    print(f"\n===== 变体 {v} ({V['label']}) =====")
    print("   过滤:", {k: V["filter"].get(k) for k in ("dropped_rows", "symbols")})
    print(f"   n={a['n']} median={a['median_rel_pct']} mean={a['mean_rel_pct']} "
          f"trim10={a['trimmed10_mean_rel_pct']} p10={a['p10_rel_pct']} "
          f"p25={a['p25_rel_pct']} p75={a['p75_rel_pct']} p90={a['p90_rel_pct']}")
    print(f"   为负比例={a['neg_rate']} nb中位={a['nb_median']} 对照中位={a['control_median_pct']}"
          f" 对照pct={a['control_percentile']} 对照n={a['control_n']}")
    for name, s in a["eras"].items():
        print(f"   [{name}] n={s.get('n')} median={s.get('median_rel_pct')} "
              f"mean={s.get('mean_rel_pct')} p10={s.get('p10_rel_pct')} "
              f"p90={s.get('p90_rel_pct')} pct={s.get('control_percentile')} "
              f"对照中位={s.get('control_median_pct')}")
    print("   全样本三条:", a.get("full_sample_criteria"), "→", a.get("verdict_full_sample"))
    print("   主判 2017-2021:", a.get("primary_era_criteria"), "→", a.get("verdict_primary_era"))
    print("   事件分段计数:", V["eras_event_counts"]["listing_krw"])
    print("   覆盖:", V["coverage"]["listing_krw"])
    st = V["strata"]["listing_krw"]
    print("   Binance 分组:", {k: (v.get("n"), v.get("median_rel_pct")) for k, v in st["binance_spot"].items()})
    print("   前 30 天三分位:", {k: (v.get("n"), v.get("median_rel_pct"))
                                 for k, v in st["pre30_tercile"]["groups"].items()})
    print("   其余臂:", {arm: (V["arms"][arm].get("n"), V["arms"][arm].get("median_rel_pct"),
                              V["arms"][arm].get("mean_rel_pct"), V["arms"][arm].get("control_percentile"))
                          for arm in ("listing_krw_null", "delisting", "warning")})

# ── 有价事件按年分布(主口径) ─────────────────────────────────────────────
print("\n== 有价事件按年(变体 chained)==")
pe = R["variants"]["chained"]["per_event"]["listing_krw"]
by = collections.defaultdict(lambda: [0, 0])
for r in pe:
    y = r["d"][:4]
    by[y][0] += 1
    if r["rel30"] is not None:
        by[y][1] += 1
for y in sorted(by):
    print(f"   {y}: 事件 {by[y][0]:>3}  有价 {by[y][1]:>3}")

# ── 逐事件:chained vs none 差多少 ───────────────────────────────────────
print("\n== 变体 chained vs none 的逐事件差(主口径 listing_krw)==")
a = {r["symbol"] + "|" + r["d"]: r for r in R["variants"]["chained"]["per_event"]["listing_krw"]}
b = {r["symbol"] + "|" + r["d"]: r for r in R["variants"]["none"]["per_event"]["listing_krw"]}
diff = [(k, a[k]["rel30"], b[k]["rel30"]) for k in a
        if (a[k]["rel30"] is None) != (b[k]["rel30"] is None)
        or (a[k]["rel30"] is not None and abs(a[k]["rel30"] - b[k]["rel30"]) > 1e-9)]
print(f"   逐事件 rel30 有差异的条数 = {len(diff)} / {len(a)}")
for k, x, y in sorted(diff, key=lambda z: -(abs(z[1] - z[2]) if (z[1] is not None and z[2] is not None) else 9e9))[:15]:
    print(f"     {k:>24} chained={x} none={y}")

print("\n== 新增的 53 个代号:v1 缓存 vs 现在 DB(机制:krw 标志变?还是 symbols 字段变?)==")
old_rows = json.load(open(os.path.join(HERE, "t291_cache", "events_upbit_listing.json")))
old_map = {r["id"]: r for r in old_rows}
new_rows = json.load(open(os.path.join(HERE, "t300_cache", "events_upbit_listing.json")))
new_map = {r["id"]: r for r in new_rows}
krw_flag_only = sym_field_only = both = 0
examples = []
for e in EV["arms"]["listing_krw"]:
    pass
# 重新算:按现在的事件清单,逐个代号找它第一条事件所在的公告
first_ev = {}
for e in sorted(EV["arms"]["listing_krw"], key=lambda z: (z["d"], z["symbol"])):
    first_ev.setdefault(e["symbol"], e)
old_first = {}
for r in sorted(old_rows, key=lambda z: (z.get("ts") or "")):
    p = r.get("payload") or {}
    if p.get("krw") is not True:
        continue
    for s in (r.get("symbols") or []):
        s = str(s).upper().strip()
        if s and s not in old_first:
            old_first[s] = r
new_syms = set(first_ev) - set(old_first)
print(f"   新增代号 = {len(new_syms)}")
for s in sorted(new_syms):
    e = first_ev[s]
    o = old_map.get(e["event_id"])
    n = new_map.get(e["event_id"])
    ok = (o.get("payload") or {}).get("krw", "MISSING") if o else "NO_ROW"
    nk = (n.get("payload") or {}).get("krw", "MISSING") if n else "NO_ROW"
    osyms = set(str(x).upper() for x in (o.get("symbols") or [])) if o else set()
    nsyms = set(str(x).upper() for x in (n.get("symbols") or [])) if n else set()
    in_old_syms = s in osyms
    in_new_syms = s in nsyms
    if in_new_syms and not in_old_syms and ok is not True:
        krw_flag_only += 1
        tag = "krw标志"
    elif in_new_syms and not in_old_syms:
        sym_field_only += 1
        tag = "symbols字段"
    elif in_old_syms and ok is not True:
        both += 1
        tag = "两者都变"
    else:
        tag = "其它"
    if len(examples) < 8:
        examples.append((s, e["d"], tag, ok, nk, sorted(osyms)[:4], sorted(nsyms)[:4]))
print(f"   其中:只因 krw 标志变 = {krw_flag_only};只因 symbols 字段扩 = {sym_field_only};"
      f"两者都变 = {both}")
for x in examples:
    print("   ", x)
print("   v1 有公告但当时不在 symbols 里的新代号数 =",
      sum(1 for s in new_syms if first_ev[s]["event_id"] in old_map
          and s not in set(str(x).upper() for x in (old_map[first_ev[s]["event_id"]].get("symbols") or []))))

for r in sorted([r for r in pe if r["d"] <= "2021-12-31"], key=lambda z: z["d"]):
    print(f"   {r['d']} {r['symbol']:<12} abs30={r['abs30']} bench={r['bench30']} rel30={r['rel30']}")
