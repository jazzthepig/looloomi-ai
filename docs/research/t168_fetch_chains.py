"""S-663 数据:DeFiLlama 链级稳定币 daily 序列 + 链 TVL + 链 → gecko_id 映射 → 研究缓存(不入库)。

链 → gecko_id 用 `api.llama.fi/v2/chains`(只留有 gecko_id 的);每日稳定币用
`stablecoins.llama.fi/stablecoincharts/{chain}`(取 `totalCirculatingUSD.peggedUSD`);
TVL 备用(`api.llama.fi/v2/historicalChainTvl/{chain}`,留 t168_chain_flows.py
只报不判);市值与 S-661 同口径(`asset_mcap_daily`,publishable key)。
可断点续跑。输出 `<root>/research/t168/_llama_chain_stables.jsonl`、`_llama_chain_tvl.jsonl`、
`_chains_gecko.json`、`_mcap_chain.json`。
用法:python3 docs/research/t168_fetch_chains.py [--root /Volumes/CometCloudAI/cometcloud-local] [--max-s 240]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE_LLAMA = "https://api.llama.fi"
BASE_STABLE = "https://stablecoins.llama.fi"


def get(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def rest_postgrest(path: str, lo: int, hi: int):
    import urllib.parse
    u, k = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(u + "/rest/v1/" + path,
                                 headers={"apikey": k, "Authorization": "Bearer " + k,
                                          "Range": f"{lo}-{hi}"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def fetch_chain_map(out_dir: str):
    """v2/chains → {chain_name: gecko_id}。链名用 `name`。"""
    fn = os.path.join(out_dir, "_chains_gecko.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    chains = get(BASE_LLAMA + "/v2/chains")
    m = {c["name"]: c["gecko_id"] for c in chains if c.get("gecko_id")}
    json.dump(m, open(fn, "w"), indent=1)
    return m


def fetch_stables(out_dir: str, names: list[str], max_s: float):
    """`/stablecoincharts/{chain}` → [{date, totalCirculatingUSD: {peggedUSD: float}}]。
    每行 `{"chain": name, "data": [[unix_ts, stables_usd], ...]}`。
    """
    fn = os.path.join(out_dir, "_llama_chain_stables.jsonl")
    done = set()
    if os.path.exists(fn):
        done = {json.loads(line)["chain"] for line in open(fn)}
    if not names:
        names = []
    t0 = time.time()
    n_written = 0
    with open(fn, "a") as fh:
        for nm in names:
            if nm in done:
                continue
            if time.time() - t0 > max_s:
                break
            try:
                d = get(f"{BASE_STABLE}/stablecoincharts/{nm}")
            except Exception as e:                                    # noqa: BLE001
                fh.write(json.dumps({"chain": nm, "error": str(e)[:80]}) + "\n")
                fh.flush()
                continue
            # reshape to flat [[ts, usd]]
            flat = []
            for row in d:
                ts = int(row["date"])
                v = float((row.get("totalCirculatingUSD") or {}).get("peggedUSD") or 0.0)
                flat.append([ts, v])
            fh.write(json.dumps({"chain": nm, "data": flat}) + "\n")
            fh.flush()
            n_written += 1
            time.sleep(0.2)
    return n_written


def fetch_tvl(out_dir: str, names: list[str], max_s: float):
    """`/v2/historicalChainTvl/{chain}` → [{date, tvl}]。只报不判。"""
    fn = os.path.join(out_dir, "_llama_chain_tvl.jsonl")
    done = set()
    if os.path.exists(fn):
        done = {json.loads(line)["chain"] for line in open(fn) if "data" in json.loads(line)}
    t0 = time.time()
    n_written = 0
    with open(fn, "a") as fh:
        for nm in names:
            if nm in done:
                continue
            if time.time() - t0 > max_s:
                break
            try:
                d = get(f"{BASE_LLAMA}/v2/historicalChainTvl/{nm}")
            except Exception as e:                                    # noqa: BLE001
                fh.write(json.dumps({"chain": nm, "error": str(e)[:80]}) + "\n")
                fh.flush()
                continue
            flat = [[int(r["date"]), float(r.get("tvl") or 0.0)] for r in d if "date" in r]
            fh.write(json.dumps({"chain": nm, "data": flat}) + "\n")
            fh.flush()
            n_written += 1
            time.sleep(0.2)
    return n_written


def fetch_mcap(out_dir: str, gecko_ids: list[str]):
    """asset_mcap_daily 只接 gecko_id 在 set 里的币。"""
    fn = os.path.join(out_dir, "_mcap_chain.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    got: list = []
    for k in range(0, len(gecko_ids), 40):
        chunk = ",".join(gecko_ids[k:k + 40])
        q = (f"asset_mcap_daily?select=coin_id,d,price,mcap&coin_id=in.({chunk})"
             f"&d=gte.2020-06-01&price=not.is.null&order=coin_id.asc,d.asc")
        off = 0
        while True:
            b = rest_postgrest(q, off, off + 999)
            got += b
            if len(b) < 1000:
                break
            off += 1000
    json.dump(got, open(fn, "w"))
    return got


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    max_s = float(sys.argv[sys.argv.index("--max-s") + 1]) if "--max-s" in sys.argv else 240.0
    out = os.path.join(root, "research", "t168")
    os.makedirs(out, exist_ok=True)

    chain_map = fetch_chain_map(out)
    chain_names = sorted(chain_map.keys())
    gecko_ids = sorted(set(chain_map.values()))
    print(json.dumps({"step": "map", "chains_with_gecko": len(chain_names), "gecko_ids": len(gecko_ids)}))

    n_st = fetch_stables(out, chain_names, max_s / 2)
    print(json.dumps({"step": "stables", "wrote": n_st}))
    n_tv = fetch_tvl(out, chain_names, max_s / 2)
    print(json.dumps({"step": "tvl", "wrote": n_tv}))

    rows = fetch_mcap(out, gecko_ids)
    print(json.dumps({"step": "mcap", "rows": len(rows), "coins": len({r['coin_id'] for r in rows})}))


if __name__ == "__main__":
    main()
