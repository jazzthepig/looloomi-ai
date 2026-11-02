"""T-219: enumerate readable tables in Supabase via the PostgREST OpenAPI root."""
import os, json, urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K, "Accept": "application/openapi+json"}

req = urllib.request.Request(U + "/rest/v1/", headers=HDR)
with urllib.request.urlopen(req, timeout=60) as r:
    spec = json.loads(r.read().decode())

paths = [p for p in spec.get("paths", {}) if p.startswith("/")]
rows = [p[1:] for p in paths]
rows = sorted(set(rows))
print("table count:", len(rows))
for r in rows:
    print(" ", r)
