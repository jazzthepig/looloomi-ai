"""S-657 / S-658 数据:Hyperliquid 全部永续(含已下架)的日线 → 研究缓存(不入库)。

只取**已收盘**的日线(S-644:K 线的收盘时间 T 晚于现在的那根不要)。HL 的 `v` 是币数,美元成交额 = close × v。
可断点续跑:已抓过的币跳过。输出 `<root>/research/s657/_hl_daily.jsonl`(每行一个币)与 `_hl_meta.json`。
用法:python3 docs/research/s657_hl_fetch.py [--root /Volumes/CometCloudAI/cometcloud-local] [--max-s 160]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

URL = "https://api.hyperliquid.xyz/info"


def post(body: dict, timeout: float = 30.0):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    max_s = float(sys.argv[sys.argv.index("--max-s") + 1]) if "--max-s" in sys.argv else 160.0
    out_dir = os.path.join(root, "research", "s657")
    os.makedirs(out_dir, exist_ok=True)
    meta_fn, data_fn = os.path.join(out_dir, "_hl_meta.json"), os.path.join(out_dir, "_hl_daily.jsonl")
    if not os.path.exists(meta_fn):
        m, ctx = post({"type": "metaAndAssetCtxs"})
        json.dump({"universe": m["universe"], "ctx": ctx, "at": int(time.time())}, open(meta_fn, "w"))
    meta = json.load(open(meta_fn))
    done = set()
    if os.path.exists(data_fn):
        for line in open(data_fn):
            done.add(json.loads(line)["coin"])
    now_ms, t0 = int(time.time() * 1000), time.time()
    todo = [a["name"] for a in meta["universe"] if a["name"] not in done]
    with open(data_fn, "a") as fh:
        for coin in todo:
            if time.time() - t0 > max_s:
                break
            for attempt in range(3):
                try:
                    cs = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": 0,
                                                                  "endTime": now_ms}})
                    break
                except Exception as e:                                   # noqa: BLE001
                    cs = None
                    time.sleep(2.0 * (attempt + 1))
                    err = str(e)[:120]
            if cs is None:
                print(f"{coin}: failed {err}", file=sys.stderr)
                continue
            rows = [{"d": time.strftime("%Y-%m-%d", time.gmtime(int(c["t"]) / 1000)), "o": float(c["o"]),
                     "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"]), "v": float(c["v"])}
                    for c in cs or [] if int(c["T"]) < now_ms]
            delisted = any(a["name"] == coin and a.get("isDelisted") for a in meta["universe"])
            fh.write(json.dumps({"coin": coin, "delisted": delisted, "bars": rows}) + "\n")
            fh.flush()
            time.sleep(0.3)
    n_done = sum(1 for _ in open(data_fn))
    print(json.dumps({"universe": len(meta["universe"]), "fetched": n_done,
                      "remaining": len(meta["universe"]) - n_done}))


if __name__ == "__main__":
    main()
