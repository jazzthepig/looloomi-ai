#!/usr/bin/env python3
"""T-305 探针 v2(可反复覆盖运行)—— 只读 Supabase,查表可读性与覆盖。

输出:/Volumes/CometCloudAI/cometcloud-local/research/_t305_probe.json
"""
import json
import os
import sys
import urllib.request
import urllib.error

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/_t305_probe.json"


def get(path: str, extra: str = "") -> tuple[int, str, dict]:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}?{extra}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = r.read().decode()
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return r.status, body, hdrs
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], {}
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", {}


def probe(label, path, extra="", n=3):
    st, body, hdrs = get(path, extra)
    out = {"label": label, "status": st, "content_range": hdrs.get("content-range", "")}
    if st == 200:
        rows = json.loads(body) if body else []
        out["n_rows"] = len(rows)
        out["sample"] = rows[:n]
        out["tail"] = rows[-1:] if rows else []
    else:
        out["err"] = body
    return out


def main():
    res = []
    res.append(probe("core_variants_daily head", "core_variants_daily",
                      "select=d,arm,ret&arm=eq.cap_pit24&order=d.asc&limit=5"))
    res.append(probe("core_variants_daily tail", "core_variants_daily",
                      "select=d,arm,ret&arm=eq.cap_pit24&order=d.desc&limit=5"))
    res.append(probe("core_variants_daily range", "core_variants_daily",
                      "select=d,arm,ret&arm=eq.cap_pit24&d=gte.2021-07-13&order=d.asc&limit=1000"))
    res.append(probe("core_cap arms", "core_cap_daily",
                      "select=d,arm,nav,ret&order=d.asc&limit=200"))
    # state_daily 特征
    res.append(probe("state features", "state_daily",
                      "select=entity,feature&order=entity.asc,feature.asc&limit=200"))
    res.append(probe("state panel dist_200", "state_daily",
                      "select=d,entity,feature,value&entity=eq.panel"
                      "&feature=in.(dist_200,vol_pct_3y,breadth_above_ma50)&order=d.asc&limit=1000"))
    res.append(probe("state panel tail", "state_daily",
                      "select=d,entity,feature,value&entity=eq.panel"
                      "&feature=in.(dist_200,vol_pct_3y,breadth_above_ma50)&order=d.desc&limit=10"))
    # ohlcv 覆盖
    for sym, src in [("BTC", "binance_hist"), ("BTC", "coingecko_pro_ohlc"), ("BTC", "coingecko"),
                     ("ETH", "binance_hist"), ("ETH", "coingecko_pro_ohlc"),
                     ("SPY", "eodhd"), ("GLD", "eodhd"), ("SPY", "binance_hist"), ("GLD", "binance_hist")]:
        res.append(probe(f"ohlcv {sym}/{src} head", "ohlcv_daily",
                          f"select=symbol,trade_date,close,source&symbol=eq.{sym}&source=eq.{src}"
                          "&order=trade_date.asc&limit=3"))
        res.append(probe(f"ohlcv {sym}/{src} tail", "ohlcv_daily",
                          f"select=symbol,trade_date,close,source&symbol=eq.{sym}&source=eq.{src}"
                          "&order=trade_date.desc&limit=3"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in res:
        line = f"{r['status']:>4}  {r['label']:<34} rows={r.get('n_rows','-')}  range={r.get('content_range','')}"
        if r["status"] != 200:
            line += f"  ERR={str(r.get('err'))[:120]}"
        else:
            line += f"  first={json.dumps(r.get('sample',[])[:1],ensure_ascii=False)[:150]}"
        print(line)


if __name__ == "__main__":
    main()
