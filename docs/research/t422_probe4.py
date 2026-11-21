"""T-422 探针 4:CG live 到底通不通(只打印状态码,不打印 key)。"""
import asyncio, json, os, sys
import urllib.error, urllib.request

ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t422"
out = {}

KEY = os.environ.get("CG_API_KEY") or os.environ.get("COINGECKO_API_KEY") or ""
out["key_present"] = bool(KEY)
if KEY:
    for name, base in (("pro", "https://pro-api.coingecko.com/api/v3"),
                       ("public", "https://api.coingecko.com/api/v3")):
        url = f"{base}/coins/markets?vs_currency=usd&ids=bitcoin&per_page=1"
        req = urllib.request.Request(url, headers={"x-cg-pro-api-key": KEY, "x-cg-demo-api-key": KEY})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode())
                out[name] = {"status": r.status, "n": len(body),
                             "has_total_supply": bool(body and body[0].get("total_supply")),
                             "has_max_supply": bool(body and body[0].get("max_supply"))}
        except urllib.error.HTTPError as e:
            out[name] = {"status": e.code, "body": e.read().decode()[:150]}
        except Exception as e:
            out[name] = {"err": f"{type(e).__name__}: {str(e)[:150]}"}


async def cg_probe():
    r = {}
    try:
        from src.data.cis.cis_provider import CRYPTO_ASSETS
        ids = [v["coingecko"] for v in CRYPTO_ASSETS.values() if v.get("coingecko")]
        r["n_ids"] = len(ids)
    except Exception as e:
        r["ids_err"] = f"{type(e).__name__}: {str(e)[:200]}"
        return r
    try:
        from src.data.market.data_layer import get_cg_markets
        cur = await get_cg_markets(ids)
        r["cg_live_n"] = len(cur or [])
        r["with_total"] = sum(1 for x in (cur or []) if x.get("total_supply"))
        r["with_max"] = sum(1 for x in (cur or []) if x.get("max_supply"))
        r["sample"] = [{k: x.get(k) for k in ("id", "total_supply", "max_supply", "market_cap", "current_price")}
                        for x in (cur or [])[:3]]
    except Exception as e:
        r["cg_live_err"] = f"{type(e).__name__}: {str(e)[:300]}"
    return r


out.update(asyncio.run(cg_probe()))
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "probe4_cg.json"), "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=str)
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
