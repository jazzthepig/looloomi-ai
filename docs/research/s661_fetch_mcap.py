"""S-661 数据:asset_mcap_daily(CoinGecko 价格 / 市值)里与 DeFiLlama gecko_id 对得上的币 → 研究缓存。
只用 publishable key(lane_read);读 os.environ['SUPABASE_URL'] / ['SUPABASE_KEY'],不打印。
用法:set -a; source .env; set +a; python3 docs/research/s661_fetch_mcap.py [--root …]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"


def rest(path: str, lo: int, hi: int) -> list:
    u, k = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(u + "/rest/v1/" + path, headers={"apikey": k, "Authorization": "Bearer " + k,
                                                                    "Range": f"{lo}-{hi}"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def main():
    out = os.path.join(ROOT, "research", "s661")
    rows = [json.loads(line) for line in open(os.path.join(out, "_llama_rev.jsonl"))]
    ids = sorted({r["gecko_id"] for r in rows if r.get("gecko_id")})
    got: list = []
    for k in range(0, len(ids), 40):
        chunk = ",".join(ids[k:k + 40])
        q = (f"asset_mcap_daily?select=coin_id,d,price,mcap,volume&coin_id=in.({chunk})&d=gte.2020-06-01"
             f"&price=not.is.null&order=coin_id.asc,d.asc")
        off = 0
        while True:
            b = rest(q, off, off + 999)
            got += b
            if len(b) < 1000:
                break
            off += 1000
    with open(os.path.join(out, "_mcap_daily.json"), "w") as fh:
        json.dump(got, fh)
    print(json.dumps({"ids_requested": len(ids), "rows": len(got), "coins": len({g['coin_id'] for g in got})}))


if __name__ == "__main__":
    main()
