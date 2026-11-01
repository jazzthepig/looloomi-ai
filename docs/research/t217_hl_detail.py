#!/usr/bin/env python3
"""T-217 ① 收尾: hl_book_daily 的 book 列到底是名字还是持仓 JSON + correction 列说了什么。只读。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def q(params):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/hl_book_daily?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def main() -> None:
    st, rows = q({"select": "d,book,decided,is_decision,n_coins,computed_at,correction,nav,ret",
                  "order": "d.asc", "limit": "50"})
    print("status", st, "n", len(rows) if isinstance(rows, list) else "n/a")
    if not isinstance(rows, list):
        return
    for r in rows:
        print(f"  d={r.get('d')} decided={r.get('decided')} is_decision={r.get('is_decision')} "
              f"n_coins={r.get('n_coins')} nav={r.get('nav')} ret={r.get('ret')} "
              f"ts={r.get('computed_at')} correction={str(r.get('correction'))[:90]}")
        print(f"      book={str(r.get('book'))[:150]}")
    # 按 decided 分组统计
    import collections
    g = collections.defaultdict(list)
    for r in rows:
        g[str(r.get("decided"))].append(r)
    print("\n按 decided 分组:")
    for k, v in sorted(g.items()):
        ds = sorted(str(x.get("d")) for x in v)
        tss = {str(x.get("computed_at")) for x in v}
        corr = sum(1 for x in v if x.get("correction") not in (None, "", [], {}))
        import datetime as dt
        dd = [dt.date.fromisoformat(x[:10]) for x in ds]
        exp = (dd[-1] - dd[0]).days + 1 if dd else 0
        gaps = [(str(a), str(b)) for a, b in zip(dd, dd[1:]) if (b - a).days > 1]
        print(f"  decided={k:12s} n={len(v):3d} {ds[0]}..{ds[-1]} exp={exp:3d} miss={exp-len(v):3d} "
              f"ts_distinct={len(tss)} corr_nonempty={corr} gaps={gaps}")
    (HERE / "t217_hl_detail.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
