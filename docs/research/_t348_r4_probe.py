"""T-348 第四轮探针(改写):ohlcv_daily 查询变体调试 + server count。"""
import json
import os
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def raw(table, qs, prefer_count=False):
    url = f"{URL}/rest/v1/{table}?{qs}"
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    if prefer_count:
        headers["Prefer"] = "count=exact"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
    return body[:300], cr


variants = [
    ("dict 风格", "select=trade_date,close,symbol&symbol=eq.ACWI&source=eq.eodhd&order=trade_date.asc&limit=3"),
    ("list 风格(少 symbol 列)", "select=trade_date,close&symbol=eq.ACWI&source=eq.eodhd&order=trade_date.asc&limit=3"),
    ("无 source", "select=trade_date,close&symbol=eq.ACWI&order=trade_date.asc&limit=3"),
    ("无 order", "select=trade_date,close&symbol=eq.ACWI&source=eq.eodhd&limit=3"),
    ("带日期下界", "select=trade_date,close&symbol=eq.ACWI&source=eq.eodhd&trade_date=gte.2020-08-10&trade_date=lte.2020-08-20&order=trade_date.asc&limit=20"),
    ("全表 count", "select=trade_date&symbol=eq.ACWI&source=eq.eodhd&order=trade_date.asc&limit=1"),
]
for name, qs in variants:
    try:
        b, cr = raw("ohlcv_daily", qs, prefer_count=True)
        print(f"[{name}] Content-Range={cr} body={b[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] ✗ {type(e).__name__} {str(e)[:200]}")
