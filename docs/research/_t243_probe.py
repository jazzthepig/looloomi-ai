"""T-243 探针 v6:tbqv 截止日 / 五币 perp 符号映射 / 资金费口径 / pairs 覆盖。"""
import json
import os
import time
import urllib.parse
import urllib.request

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(table, params, rng="0-4", extra=None):
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    h = dict(HEAD, Range=rng)
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else []), round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], round(time.time() - t0, 2)
    except Exception as e:  # noqa: BLE001
        return "ERR", f"{type(e).__name__}: {e}", round(time.time() - t0, 2)


out = {}

# 1) tbqv 截止日:逐日看非空数
for day in ["2025-06-01", "2025-09-01", "2025-10-06", "2025-11-01", "2025-12-01",
            "2026-01-01", "2026-03-01", "2026-06-01", "2026-09-01"]:
    st, rows, dt = get("perp_bv_daily", [("select", "d,qv,tbqv"), ("d", f"eq.{day}")], "0-9999")
    if isinstance(rows, list):
        out[f"tbqv_{day}"] = {"n": len(rows), "nonnull": sum(1 for r in rows if r.get("tbqv") is not None)}
    else:
        out[f"tbqv_{day}"] = {"err": rows}

# 2) 五币的 perp 符号:perp_bv_daily 里 symbol 含 BTC/ETH/SOL/BNB/XRP
st, rows, dt = get("perp_bv_daily", [("select", "d,pair,symbol,qv,tbqv"),
                                     ("symbol", "in.(BTC,ETH,SOL,BNB,XRP)"),
                                     ("d", "gte.2026-10-01"), ("d", "lte.2026-10-03"),
                                     ("order", "d.asc,pair.asc")], "0-999")
out["perp_five"] = {"st": st, "n": len(rows), "rows": rows[:14] if isinstance(rows, list) else rows}

# 3) perp_bv_pairs 中五币的映射
st, rows, dt = get("perp_bv_pairs", [("select", "pair,symbol,kind,first_d,dead_from,active"),
                                     ("symbol", "in.(BTC,ETH,SOL,BNB,XRP)"),
                                     ("order", "symbol.asc")], "0-99")
out["pairs_five"] = {"st": st, "rows": rows if isinstance(rows, list) else rows}

# 4) v_funding_daily 口径:BTC 近几日 + 一批合约的 rate 幅度
st, rows, dt = get("v_funding_daily", [("select", "d,symbol,funding_rate,n"),
                                        ("d", "gte.2026-10-25"), ("d", "lte.2026-10-27"),
                                        ("order", "d.asc,symbol.asc")], "0-1999")
if isinstance(rows, list) and rows:
    rates = [r["funding_rate"] for r in rows if r.get("funding_rate") is not None]
    ns = sorted({r["n"] for r in rows})
    btc = [r for r in rows if r["symbol"] in ("BTC", "BTCUSDT")]
    out["funding"] = {"st": st, "n": len(rows), "n_values": ns,
                      "rate_min": min(rates), "rate_max": max(rates),
                      "btc_rows": btc[:8], "sample": rows[:4]}
else:
    out["funding"] = {"st": st, "err": rows}

# 5) perp_bv_daily 的 pair 是否都在 pairs 表里(抽样)
st, rows, dt = get("perp_bv_daily", [("select", "pair"), ("d", "eq.2026-11-03"),
                                     ("order", "pair.asc")], "0-9999")
if isinstance(rows, list):
    out["n_pairs_2026_11_03"] = len(rows)
    out["pairs_sample"] = [r["pair"] for r in rows[:10]]
else:
    out["n_pairs_2026_11_03"] = rows

print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:9000])
