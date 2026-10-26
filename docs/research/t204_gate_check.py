#!/usr/bin/env python3
"""T-204 闸门检查:perp_cg_map 是否已无 verdict='pending' 的行。

开工条件(卡 T-204 acceptance):
  perp_cg_map 无 pending 行,或已过 2026-10-28 00:00 UTC。
只读 Supabase(publishable key)。
"""
import json
import os
import sys
import urllib.request
from collections import Counter

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
DEADLINE = "2026-10-28T00:00:00+00:00"


def q(path):
    req = urllib.request.Request(
        URL + "/rest/v1/" + path,
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY},
    )
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def main():
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    rows = q("perp_cg_map?select=coin_id,verdict,note,checked_at&order=coin_id.asc")
    counts = Counter(r["verdict"] for r in rows)
    pending = [r["coin_id"] for r in rows if r["verdict"] == "pending"]
    deadline = __import__("datetime").datetime.fromisoformat(DEADLINE)
    gate_ok = (len(pending) == 0) or (now >= deadline)
    print("now_utc:", now.isoformat())
    print("rows:", len(rows))
    print("verdicts:", dict(counts))
    print("pending_n:", len(pending))
    print("pending:", pending)
    print("checked_at present:", sum(1 for r in rows if r.get("checked_at")))
    last = sorted([r["checked_at"] for r in rows if r.get("checked_at")])
    print("last_checked_at:", last[-1] if last else None)
    print("gate_ok:", gate_ok)
    print("deadline_passed:", now >= deadline)
    return 0 if gate_ok else 3


if __name__ == "__main__":
    sys.exit(main())
