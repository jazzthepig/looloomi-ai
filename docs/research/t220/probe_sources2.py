#!/usr/bin/env python3
"""T-220 ① 第二轮:钱包标签 / 解锁日程的具体端点(仍只 GET,不注册)。"""
import json
import re
import ssl
import urllib.request
import urllib.error

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (cometcloud research feasibility probe)"}
ADDR = "0x28C6c06298d514Db089934071355E5743bf21d60"  # Binance 14, 公开例子


def get(u, timeout=40):
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]
    except Exception as e:  # noqa: BLE001
        return -1, repr(e).encode()[:300]


PROBES = [
    ("nansen_holders", "https://api.nansen.ai/api/v2/tokeninfo/holders?apiKey="),
    ("nansen_pro", "https://pro-api.nansen.ai/api/beta/endpoint?apiKey="),
    ("arkham_addr", f"https://api.arkhamintelligence.com/intelligence/address/{ADDR}"),
    ("arkham_entity", "https://api.arkhamintelligence.com/intelligence/entity/ethereum"),
    ("ethplorer_freekey", "https://api.ethplorer.io/getInfo?apiKey=freekey"),
    ("ethplorer_address", f"https://api.ethplorer.io/api?module=account&action=balance&address={ADDR}&tag=latest&apiKey=freekey"),
    ("openchain_address", f"https://api.openchain.xyz/v1/address/{ADDR}"),
    ("openchain_label", "https://labels.openchain.xyz/"),
    ("blockchair_addr", f"https://api.blockchair.com/ethereum/dashboards/address/{ADDR}"),
    ("bitquery_free", "https://streaming.bitquery.io/eap"),
    ("covalent_addr", f"https://api.covalenthq.com/v1/1/addresses/{ADDR}/transactions_v2/"),
    ("tokenunlocks_xyz", "https://tokenunlocks.xyz/"),
    ("cryptorank_v2", "https://api.cryptorank.io/v2/token/aave"),
    ("coingecko_pro_trial", "https://pro-api.coingecko.com/api/v3/ping"),
    ("santiment_graph", "https://api.santiment.net/graphql"),
    ("llama_emissions_free_sub", "https://api.llama.fi/emissions?free=true"),
    ("defillama_pro_page", "https://defillama.com/pro"),
    ("defillama_emissions_page", "https://defillama.com/emissions"),
]
out = {}
for name, u in PROBES:
    st, b = get(u)
    txt = b[:200].decode("utf-8", "replace").replace("\n", " ")
    print(f"{name:24s} {st} :: {txt[:170]}", flush=True)
    out[name] = {"status": st, "head": txt[:500]}

# 从已存的 pro-api 页里提取价格上下文
try:
    raw = open(HERE + "_llama_pro_raw.html", "rb").read().decode("utf-8", "replace")
except FileNotFoundError:
    st, b = get("https://docs.llama.fi/pro-api")
    raw = b.decode("utf-8", "replace")
    open(HERE + "_llama_pro_raw.html", "w").write(raw)
plain = re.sub(r"<[^>]+>", " ", raw)
plain = re.sub(r"\s+", " ", plain)
for kw in ("$300", "$3,000", "$49", "$490", "$0.60", "per mo", "/mo", "year"):
    for m in re.finditer(re.escape(kw), plain):
        s = max(0, m.start() - 130)
        print("CTX", kw, "::", plain[s:m.end() + 130].strip()[:280], flush=True)
        break

json.dump(out, open(HERE + "_sources2.json", "w"), ensure_ascii=False, indent=1)
print("saved _sources2.json")
