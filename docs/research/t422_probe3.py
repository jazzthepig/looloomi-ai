"""T-422 探针 3:官方 11-19 行的 inputs/missing(能不能复原 CG live 的 static)。"""
import json, os
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


rows = get("cis_official_daily", {"select": "symbol,d,inputs,missing,cis_score,grade,signal,regime,"
                                         "pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,asset_class",
                                   "d": "eq.2026-11-19", "order": "symbol.asc"})
out = {"n": len(rows)}
for r in rows[:4]:
    out.setdefault("sample", []).append(r)
out["keys_in_inputs"] = sorted({k for r in rows for k in (r.get("inputs") or {})})[:40]
out["missing_counter"] = {}
for r in rows:
    for m in (r.get("missing") or []):
        out["missing_counter"][m] = out["missing_counter"].get(m, 0) + 1
out["n_with_missing"] = sum(1 for r in rows if r.get("missing"))
out["all"] = rows
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "official_1119.json"), "w") as f:
    json.dump(rows, f, indent=1, ensure_ascii=False, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "all"}, indent=1, ensure_ascii=False, default=str))
