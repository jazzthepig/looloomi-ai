#!/usr/bin/env python3
"""T-242 timing probe: 是 count=exact 贵,还是大 OFFSET 排序贵?"""
import json
import os
import time
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]


def t(label, url, hdr):
    req = urllib.request.Request(url, headers=hdr)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        n = len(r.read())
    print("%-52s %6.1fs  %d bytes" % (label, time.time() - t0, n), flush=True)


base = {"apikey": K, "Authorization": "Bearer " + K}
withc = dict(base, **{"Prefer": "count=exact"})
q = {"select": "symbol,d,funding_rate", "order": "symbol.asc,d.asc", "limit": "10000"}
url = U + "/rest/v1/v_funding_daily?" + urllib.parse.urlencode(q)
t("fund limit=10000 offset=0, count=exact", url, withc)
t("fund limit=10000 offset=0, no count", url, base)

q2 = dict(q, limit="10000")
url2 = U + "/rest/v1/v_funding_daily?" + urllib.parse.urlencode(q2)
req = urllib.request.Request(url2, headers=base)
r = urllib.request.urlopen(req, timeout=600)
rows = json.loads(r.read().decode())
last = rows[-1]["symbol"]
q3 = {"select": "symbol,d,funding_rate", "order": "symbol.asc,d.asc",
      "symbol": "gt." + last, "limit": "10000"}
url3 = U + "/rest/v1/v_funding_daily?" + urllib.parse.urlencode(q3)
t("fund keyset symbol.gt.%s limit=10000 no count" % last, url3, base)

q4 = {"select": "symbol,d,oi_close,oi_value_close", "order": "symbol.asc,d.asc", "limit": "10000"}
url4 = U + "/rest/v1/deriv_metrics_daily?" + urllib.parse.urlencode(q4)
t("deriv limit=10000 offset=0 no count", url4, base)
