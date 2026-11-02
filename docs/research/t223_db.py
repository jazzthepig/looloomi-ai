"""T-223 REST helper for the read-only Supabase research DB.

Self-contained copy of the T-219 helper (docs/research/t219_db.py lives on the
lane-b/T-219 branch, not on origin/main), so the T-223 pull/probe scripts stay
reproducible from this branch alone.

Rules baked in:
  - always paginate WITH order= (PostgREST range boundaries drift without it)
  - never print credentials
  - read-only: GET only
"""
import os, json, urllib.request, urllib.parse

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
if not U or not K:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY missing from environment")


def _hdrs(extra=None):
    h = {"apikey": K, "Authorization": "Bearer " + K}
    if extra:
        h.update(extra)
    return h


def _stable_order(select, order):
    """S-532: 翻页读必须有确定的顺序 —— 没给 order 时按 select 里的列全部升序排。"""
    if order:
        return order
    cols = [c.strip() for c in str(select or "*").split(",")
            if c.strip() and c.strip() != "*" and not any(ch in c for ch in "():!*")]
    return ",".join(c + ".asc" for c in cols) or None


class DB:
    def get(self, path, params=None, extra=None):
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = U + "/rest/v1/" + path + ("?" + q if q else "")
        req = urllib.request.Request(url, headers=_hdrs(extra))
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode()
            cr = r.headers.get("Content-Range")
        return json.loads(body) if body else [], cr

    def exists(self, table):
        try:
            rows, cr = self.get(table, {"select": "*", "limit": 1, "order": _stable_order("*", None)})
            return True, cr
        except urllib.error.HTTPError as e:
            return False, "HTTP %s" % e.code

    def page(self, table, select="*", order=None, filters=None, limit=1000):
        params = {"select": select, "limit": limit, "order": _stable_order(select, order)}
        for col, val in (filters or {}).items():
            params[col] = val
        rows, cr = self.get(table, params, extra={"Range": "0-%d" % (limit - 1)})
        nxt = None
        if cr and "/" in cr:
            tail = cr.split("/")[-1]
            if tail != "*":
                nxt = int(cr.split("-")[0]) + len(rows)
        return rows, nxt

    def count(self, table, filters=None):
        params = {"select": "*", "limit": 1, "order": _stable_order("*", None)}
        for col, val in (filters or {}).items():
            params[col] = val
        rows, cr = self.get(table, params, extra={"Prefer": "count=exact"})
        if cr and "/" in cr:
            tail = cr.split("/")[-1]
            return int(tail) if tail != "*" else None
        return len(rows)

    def all(self, table, select="*", order=None, filters=None, limit=1000, max_rows=None):
        """Full paginated read. order is MANDATORY for stable paging."""
        out, off = [], 0
        while True:
            params = {"select": select, "limit": limit, "offset": off,
                      "order": _stable_order(select, order)}
            for col, val in (filters or {}).items():
                params[col] = val
            rows, cr = self.get(table, params)
            if not rows:
                break
            out.extend(rows)
            if max_rows and len(out) >= max_rows:
                return out[:max_rows]
            if len(rows) < limit:
                break
            off += len(rows)
        return out

    def symbols(self, table, order="symbol.asc", **kw):
        rows = self.all(table, select="symbol", order=order, **kw)
        return sorted(set(r["symbol"] for r in rows))
