#!/usr/bin/env python3
"""T-217: what can the publishable key reach? Probe key endpoints + role."""
from __future__ import annotations

import os
import urllib.error
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}


def main() -> None:
    paths = ["/rest/v1/rpc/rls_status", "/auth/v1/user", "/rest/v1/"]
    for path in paths:
        try:
            req = urllib.request.Request(SB + path, headers=H)
            with urllib.request.urlopen(req, timeout=30) as r:
                print(path, r.status, r.read().decode()[:300])
        except urllib.error.HTTPError as e:
            print(path, "HTTP", e.code, e.read().decode()[:200])
        except Exception as e:  # noqa: BLE001
            print(path, type(e).__name__, str(e)[:120])


if __name__ == "__main__":
    main()
