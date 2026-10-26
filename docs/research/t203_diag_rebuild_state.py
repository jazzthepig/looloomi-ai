#!/usr/bin/env python3
"""T-203 诊断 3:重建是否还在跑?11:10 批与 12:32 批的 funding 值 / pillar_o / score 是否一致?
(若一致 ⇒ 12:32 批是同一份「含 funding」的重建,只是重跑一次)"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}


def get(table, params, page=1000):
    rows, off = [], 0
    while True:
        p = dict(params)
        p["limit"] = page
        p["offset"] = off
        ps = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe="(),.*:|+-=<>")) for k, v in p.items())
        req = urllib.request.Request(URL + "/rest/v1/" + table + "?" + ps, headers=HDR)
        last = None
        for i in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    last = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and i < 4:
                    continue
                raise
        rows.extend(last)
        if len(last) < page:
            break
        off += page
    return rows


def batch_counts():
    rb = get("cis_rebuild_daily", {"select": "symbol,d,computed_at,score,pillar_o,inputs",
                                   "code_ref": "eq.cis-standard-v1.3", "order": "symbol.asc,d.asc"})
    b = defaultdict(int)
    for r in rb:
        b[(r.get("computed_at") or "")[:19]] += 1
    return rb, dict(sorted(b.items()))


print("== A. 两次采样,看重建是否还在写 ==")
rb1, c1 = batch_counts()
print("   采样1:", json.dumps(c1))
time.sleep(25)
rb2, c2 = batch_counts()
print("   采样2:", json.dumps(c2))
print("   批次集合是否变化:", set(c1) != set(c2))

print("\n== B. 最新两批之间:funding 值 / pillar_o / score 是否一致 ==")
k = defaultdict(dict)
for r in rb2:
    k[(r.get("computed_at") or "")[:19]][(r["symbol"], r["d"][:10])] = r
bs = sorted(k)
if len(bs) >= 2:
    a, b = k[bs[-2]], k[bs[-1]]
    common = sorted(set(a) & set(b))
    fr_diff = 0
    po_diff = 0
    sc_diff = 0
    fr_ex = []
    for key in common:
        ra, rb_ = a[key], b[key]
        fa = (ra.get("inputs") or {}).get("funding")
        fb = (rb_.get("inputs") or {}).get("funding")
        if fa != fb:
            fr_diff += 1
            if len(fr_ex) < 5:
                fr_ex.append({"symbol": key[0], "d": key[1], "fr_a": fa, "fr_b": fb})
        if ra.get("pillar_o") != rb_.get("pillar_o"):
            po_diff += 1
        if ra.get("score") != rb_.get("score"):
            sc_diff += 1
    print("   %s vs %s: 共同 %d 行 | funding 值不同 %d | pillar_o 不同 %d | score 不同 %d"
          % (bs[-2], bs[-1], len(common), fr_diff, po_diff, sc_diff))
    for e in fr_ex:
        print("      例:", json.dumps(e, ensure_ascii=False))

print("\n== C. 最新批次的 crypto 行:funding 覆盖 + 是否含在分数里 ==")
newest = bs[-1]
rows = k[newest]
n_fr = sum(1 for r in rows.values() if (r.get("inputs") or {}).get("funding") is not None)
print("   最新批次 %s: %d 行,funding 有值 %d" % (newest, len(rows), n_fr))
out = {"batches_sample1": c1, "batches_sample2": c2,
       "newest_batch": newest, "rows_newest": len(rows), "fr_present_newest": n_fr}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "t203_diag_rebuild_state.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("\n写 t203_diag_rebuild_state.json")
