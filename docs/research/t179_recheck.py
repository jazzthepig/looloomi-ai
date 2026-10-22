"""T-179 re-check — dei 概念拉不到的(DELL / WELL / CMCSA / ADBE / BKNG / VLO / 非美 ADR 比例)。

dei:EntityCommonStockSharesOutstanding 只在 10-Q/10-K/20-F 封面出现,有的申报人
按多个类别分别报、或只用 us-gaap 概念。这轮改拉 companyfacts 全量,在 dei /
us-gaap 两个 namespace 里找 shares outstanding 类概念。
"""
from __future__ import annotations

import json
import time
import urllib.request

UA = "CometCloud research (seth@looloomi.ai; institutional research contact)"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CIKS = {"DELL": 1571996, "WELL": 766704, "CMCSA": 1166691, "ADBE": 796343,
        "BKNG": 1075531, "VLO": 1035002}
_last = [0.0]
WANT = ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding",
        "CommonStockSharesIssued")


def get(url):
    gap = time.time() - _last[0]
    if gap < 0.25:
        time.sleep(0.25 - gap)
    import gzip
    import io
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    raw = urllib.request.urlopen(req, timeout=180).read()
    _last[0] = time.time()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return json.loads(raw.decode())


out = {}
for tk, cik in CIKS.items():
    try:
        j = get(FACTS.format(cik=cik))
    except Exception as e:                       # noqa: BLE001
        out[tk] = {"error": str(e)}
        print(tk, "ERR", e)
        continue
    hits = []
    for ns, concepts in j.get("facts", {}).items():
        for name, body in concepts.items():
            if not any(w in name for w in WANT):
                continue
            for unit, facts in body.get("units", {}).items():
                if unit != "shares":
                    continue
                rows = [f for f in facts if f.get("end", "") >= "2025-09-01"]
                if rows:
                    hits.append({"ns": ns, "concept": name,
                                 "rows": sorted(rows, key=lambda f: (f["end"], f.get("filed") or ""))})
    out[tk] = {"entity": j.get("entityName"), "hits": hits}
    print("=", tk, j.get("entityName"))
    for h in hits:
        print("   ", h["ns"], h["concept"])
        for f in h["rows"]:
            print(f"      end={f['end']} filed={f.get('filed')} {f.get('form'):8s} {f.get('accn')}  val={f['val']:,}")
    time.sleep(0.3)

with open("/Volumes/CometCloudAI/cometcloud-local/research/t179/edgar_facts_recheck.json", "w") as f:
    json.dump(out, f, indent=1)
print("written")