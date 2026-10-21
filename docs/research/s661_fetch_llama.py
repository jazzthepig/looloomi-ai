"""S-661 数据:DeFiLlama 协议收入(Revenue)与持币人收入(HoldersRevenue)的日序列 → 研究缓存(不入库)。

协议按「母协议」聚合(Uniswap = v2 + v3 + v4 …;`parentProtocol` 去掉 `parent#` 前缀,没有母协议的用自己的 slug),
`/summary/fees/{slug}` 返回整段日序列与 `gecko_id`。只留有 gecko_id 的(才能接到币的市值)。
可断点续跑。输出 `<root>/research/s661/_llama_rev.jsonl`(每行一个协议)。
用法:python3 docs/research/s661_fetch_llama.py [--root /Volumes/CometCloudAI/cometcloud-local] [--max-s 160]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = "https://api.llama.fi"


def get(path: str, timeout: float = 60.0):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "cometcloud-research"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    max_s = float(sys.argv[sys.argv.index("--max-s") + 1]) if "--max-s" in sys.argv else 160.0
    out = os.path.join(root, "research", "s661")
    os.makedirs(out, exist_ok=True)
    slugs_fn, data_fn = os.path.join(out, "_slugs.json"), os.path.join(out, "_llama_rev.jsonl")
    if not os.path.exists(slugs_fn):
        ov = get("/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyRevenue")
        slugs = set()
        for p in ov.get("protocols") or []:
            par = p.get("parentProtocol")
            slugs.add(par.split("#", 1)[1] if par and "#" in par else p.get("slug"))
        json.dump(sorted(s for s in slugs if s), open(slugs_fn, "w"))
    slugs = json.load(open(slugs_fn))
    done = set()
    if os.path.exists(data_fn):
        done = {json.loads(line)["slug"] for line in open(data_fn)}
    t0 = time.time()
    with open(data_fn, "a") as fh:
        for s in slugs:
            if s in done:
                continue
            if time.time() - t0 > max_s:
                break
            row = {"slug": s}
            for dtype in ("dailyRevenue", "dailyHoldersRevenue"):
                try:
                    d = get(f"/summary/fees/{s}?dataType={dtype}")
                except Exception as e:                                   # noqa: BLE001
                    row[dtype] = None
                    row.setdefault("errors", []).append(f"{dtype}: {str(e)[:80]}")
                    continue
                row.setdefault("gecko_id", d.get("gecko_id"))
                row.setdefault("name", d.get("name"))
                row.setdefault("category", d.get("category"))
                row[dtype] = [[int(t), float(v or 0.0)] for t, v in d.get("totalDataChart") or []]
                time.sleep(0.25)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    n = sum(1 for _ in open(data_fn))
    print(json.dumps({"slugs": len(slugs), "fetched": n, "remaining": len(slugs) - n}))


if __name__ == "__main__":
    main()
