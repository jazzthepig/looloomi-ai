"""T-422 探针 2:CG live 现状 + 官方 11-19 行(只读)。"""
import asyncio, json, os
import urllib.parse, urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t422"


def get(path, params=None):
    q = dict(params or {})
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in q.items())
    req = urllib.request.Request(f"{URL}/rest/v1/{path}?{qs}", headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        return json.loads(body) if body.strip() else []


out = {}

# 1. 官方档 11-19 / 11-20
for d in ("2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"):
    try:
        rows = get("cis_official_daily", {"select": "symbol,d,cis_score,grade,signal,regime",
                                          "d": f"eq.{d}", "order": "symbol.asc"})
        out[f"official_{d}_n"] = len(rows)
        if d == "2026-11-19":
            out["official_1119_sample"] = rows[:3]
            out["official_1119_regimes"] = sorted({r.get("regime") for r in rows})
    except Exception as e:
        out[f"official_{d}_err"] = f"{type(e).__name__}: {e}"

# 2. 官方表列
try:
    rows = get("cis_official_daily", {"select": "*", "limit": "1"})
    out["official_cols"] = sorted(rows[0].keys()) if rows else []
except Exception as e:
    out["official_cols_err"] = f"{type(e).__name__}: {e}"


async def cg_probe():
    r = {"cg_api_key_present": bool(os.environ.get("CG_API_KEY") or os.environ.get("COINGECKO_API_KEY"))}
    try:
        from src.data.cis.cis_provider import CRYPTO_ASSETS
        ids = [v["coingecko"] for v in CRYPTO_ASSETS.values() if v.get("coingecko")]
        r["n_ids"] = len(ids)
    except Exception as e:
        r["ids_err"] = f"{type(e).__name__}: {e}"
        return r
    try:
        from src.data.market.data_layer import get_cg_markets
        cur = await get_cg_markets(ids)
        r["cg_live_n"] = len(cur or [])
        r["cg_live_with_total"] = sum(1 for x in (cur or []) if x.get("total_supply"))
        r["cg_live_with_max"] = sum(1 for x in (cur or []) if x.get("max_supply"))
        r["cg_live_sample"] = [{k: x.get(k) for k in ("id", "total_supply", "max_supply",
                                                       "market_cap", "current_price")}
                               for x in (cur or [])[:3]]
    except Exception as e:
        r["cg_live_err"] = f"{type(e).__name__}: {str(e)[:300]}"
    return r


out.update(asyncio.run(cg_probe()))

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "probe2.json"), "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=str)
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
