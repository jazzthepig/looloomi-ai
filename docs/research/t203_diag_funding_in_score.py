#!/usr/bin/env python3
"""T-203 诊断 2:funding 项到底在不在**分数**里(卡片 12:00 UTC 门槛的实质检查)。

方法:同一 (symbol, d),对比「事故批次」(computed_at=04:28:14,无 funding 写入)与
「修复后批次」(computed_at=11:56:42,带 funding)的 pillar_o 与 score:
  若 pillar_o 有差异 ⇒ funding 项确实进了 O 支柱 ⇒ 该批次的 score 是含 funding 的版本。
另:检验 PostgREST 别名 `inputs->>funding as fr` 为什么取不到(避免误判 funding 缺失)。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t203"


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


print("== A. 别名取法对比(inputs->>funding as fr) ==")
try:
    a = get("cis_rebuild_daily", {"select": "symbol,d,inputs->>funding as fr", "code_ref": "eq.cis-standard-v1.3",
                                   "order": "symbol.asc,d.asc", "limit": 3})
    print("   别名法:", json.dumps(a, ensure_ascii=False)[:300])
except urllib.error.HTTPError as e:
    print("   别名法 HTTP %s: %s" % (e.code, e.read().decode()[:200]))
b = get("cis_rebuild_daily", {"select": "symbol,d,inputs", "code_ref": "eq.cis-standard-v1.3",
                              "order": "symbol.asc,d.asc", "limit": 3})
print("   整取法:", json.dumps([{"symbol": r["symbol"], "d": r["d"][:10],
                               "funding": (r.get("inputs") or {}).get("funding")} for r in b], ensure_ascii=False)[:300])

print("\n== B. 事故批次 vs 修复后批次:pillar_o / score 是否不同 ==")
stale_path = os.path.join(CACHE, "_stale_1110", "rb_v13.json")
stale = json.load(open(stale_path))
stale_key = {(r["symbol"], r["d"][:10]): r for r in stale}
live = get("cis_rebuild_daily", {"select": "symbol,d,score,pillar_o,pillar_f,pillar_m,pillar_s,pillar_a,"
                                         "raw_score,computed_at,inputs",
                                 "code_ref": "eq.cis-standard-v1.3", "order": "symbol.asc,d.asc"})
live_key = {(r["symbol"], r["d"][:10]): r for r in live}
common = sorted(set(stale_key) & set(live_key))
print("   共同 (symbol,d): %d 行" % len(common))
diff_o = 0
diff_score = 0
examples = []
for k in common:
    s, l = stale_key[k], live_key[k]
    if s.get("pillar_o") is None or l.get("pillar_o") is None:
        continue
    if abs(float(s["pillar_o"]) - float(l["pillar_o"])) > 1e-9:
        diff_o += 1
        if len(examples) < 6:
            fr = (l.get("inputs") or {}).get("funding")
            examples.append({"symbol": k[0], "d": k[1], "pillar_o_stale": s["pillar_o"],
                             "pillar_o_live": l["pillar_o"], "score_stale": s.get("score"),
                             "score_live": l.get("score"), "funding_live": fr})
    if s.get("score") is not None and l.get("score") is not None:
        if abs(float(s["score"]) - float(l["score"])) > 1e-9:
            diff_score += 1
print("   pillar_o 有差异: %d/%d 行" % (diff_o, len(common)))
print("   score    有差异: %d/%d 行" % (diff_score, len(common)))
for e in examples:
    print("   例:", json.dumps(e, ensure_ascii=False))

print("\n== C. 修复后批次里 funding 非空行的 pillar_o 是否随 funding 变(回归) ==")
# 若 funding 项进了 O 支柱,则同一 symbol 的 pillar_o 应随 fr 变化;用同一 symbol 的不同 fr 分档看
by_sym = defaultdict(list)
for k, l in live_key.items():
    fr = (l.get("inputs") or {}).get("funding")
    if fr is None or l.get("pillar_o") is None:
        continue
    by_sym[k[0]].append((float(fr), float(l["pillar_o"])))
for sym in ("BTC", "ETH", "SOL"):
    xs = by_sym.get(sym, [])
    if not xs:
        print("   %s: 无" % sym)
        continue
    lo = [p for f, p in xs if abs(f) <= 0.0001]
    hi = [p for f, p in xs if f > 0.0005]
    neg = [p for f, p in xs if f <= -0.0005]
    print("   %s: n=%d |fr|<=1e-4 平均 pillar_o=%.3f (n=%d) | fr>5e-4 平均 pillar_o=%.3f (n=%d) "
          "| fr<=-5e-4 平均 pillar_o=%.3f (n=%d)" %
          (sym, len(xs), sum(lo) / len(lo) if lo else float("nan"), len(lo),
           sum(hi) / len(hi) if hi else float("nan"), len(hi),
           sum(neg) / len(neg) if neg else float("nan"), len(neg)))

out = {"common_rows": len(common), "pillar_o_diff_rows": diff_o, "score_diff_rows": diff_score,
       "examples": examples}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "t203_diag_funding_in_score.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("\n写 t203_diag_funding_in_score.json")
