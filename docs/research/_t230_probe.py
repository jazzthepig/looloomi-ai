"""T-230 探针 v7:只读。① issuer_entities 全量(紧凑) ② treatment_daily / protocol_revenue_daily 口径
③ ohlcv_daily 最新收盘(给 scenarios 用) ④ symbol 撞名(STRK 等)对内部表的实际影响。
只读表,不改代码、不写库。改同一个文件再跑。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺少 SUPABASE_URL / SUPABASE_KEY 环境变量")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(path: str):
    req = urllib.request.Request(URL.rstrip("/") + "/rest/v1/" + path, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            b = r.read().decode()
            return r.status, (json.loads(b) if b else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)[:200]


SIX = ["AAVE", "LDO", "POL", "ARB", "OP", "STRK"]
STABLE3 = ["USDT", "USDC", "PYUSD", "USDG"]
CLOSE_SYMS = ["OP", "AAVE", "LDO", "POL", "ARB", "STRK", "UNI", "BTC", "ETH"]

print("=== A. issuer_entities 全量(紧凑) ===")
st, ent = get("issuer_entities?select=id,name,kind,confidence,instruments&order=id.asc&limit=100")
print("status:", st, "n:", len(ent) if isinstance(ent, list) else ent)
if isinstance(ent, list):
    from collections import Counter
    print("kind 分布:", dict(Counter(r.get("kind") for r in ent)))
    print("confidence 分布:", dict(Counter(r.get("confidence") for r in ent)))
    for r in ent:
        ins = r.get("instruments") or []
        if isinstance(ins, str):
            ins = json.loads(ins)
        syms = ",".join(f"{i.get('symbol')}:{i.get('cls')}" for i in ins)
        print(f"  {r.get('id')}|{r.get('kind')}|{r.get('confidence')}|{syms}")

print("")
print("=== B. treatment_daily 最新日:6 家 + 3 家稳定币发行方( holders_share 口径 ) ===")
st, td = get("treatment_daily?select=d,symbol,revenue_30d,holders_30d,holders_share,price&order=d.desc,symbol.asc&limit=400")
print("status:", st, "n:", len(td) if isinstance(td, list) else td)
if isinstance(td, list) and td:
    latest = td[0].get("d")
    print("最新日:", latest)
    print(f"{'symbol':<8}{'rev_30d':>16}{'hold_30d':>12}{'share':>10}{'price':>14}")
    for r in td:
        if r.get("d") != latest:
            continue
        sym = str(r.get("symbol"))
        if sym in SIX or sym in STABLE3:
            print(f"{sym:<8}{str(r.get('revenue_30d')):>16}{str(r.get('holders_30d')):>12}"
                  f"{str(r.get('holders_share')):>10}{str(r.get('price')):>14}")
    print("  最新日 holders_share 非空:", sum(1 for r in td if r.get("d") == latest and r.get("holders_share") is not None),
          "/", sum(1 for r in td if r.get("d") == latest))
    # 前一日的对比
    days = sorted({r.get("d") for r in td if r.get("d")}, reverse=True)
    if len(days) > 1:
        print("  前一日:", days[1])
        for r in td:
            if r.get("d") == days[1] and str(r.get("symbol")) in SIX:
                print("   ", r.get("symbol"), r.get("revenue_30d"), r.get("holders_30d"), r.get("holders_share"))

print("")
print("=== C. protocol_revenue_daily 原始行(gecko_id 口径) ===")
st, pr = get("protocol_revenue_daily?select=d,gecko_id,revenue_30d,holders_30d&d=eq.2026-11-03&order=gecko_id.asc&limit=500")
print("status:", st, "n:", len(pr) if isinstance(pr, list) else pr)
if isinstance(pr, list):
    keys = ("aave", "lido", "polygon", "arbitrum", "optimism", "starknet", "uniswap", "maker", "sky",
            "tether", "circle", "paxos")
    for r in pr:
        g = str(r.get("gecko_id"))
        if any(k in g for k in keys):
            print("  ", json.dumps(r, ensure_ascii=False, sort_keys=True))

print("")
print("=== D. issuer_fundamentals_quarterly: symbol 撞名检查 ===")
st, fq = get("issuer_fundamentals_quarterly?select=symbol,period,filed,buybacks,dividends,diluted_shares&order=symbol.asc,period.asc&limit=2000")
print("status:", st, "n:", len(fq) if isinstance(fq, list) else fq)
if isinstance(fq, list):
    syms = sorted({str(r.get("symbol")) for r in fq})
    print("表内 symbol:", ", ".join(syms))
    KEY = ("STRK", "CRCL", "HOOD", "GLXY", "BLSH", "FIGR", "GEMI", "COIN", "MSTR")
    for r in fq:
        if str(r.get("symbol")) in KEY:
            print("  ", json.dumps(r, ensure_ascii=False, sort_keys=True))
    print("  STRK 行数:", sum(1 for r in fq if str(r.get("symbol")) == "STRK"))

print("")
print("=== E. ohlcv_daily 最新收盘(scenarios 阈值用) ===")
st, one = get("ohlcv_daily?select=*&limit=1")
print("列探测 status:", st, "列:", sorted(one[0].keys()) if isinstance(one, list) and one else one)
DATE_COL = "date"
if isinstance(one, list) and one:
    for cand in ("date", "trade_date", "d"):
        if cand in one[0]:
            DATE_COL = cand
            break
for sym in CLOSE_SYMS:
    st, oc = get("ohlcv_daily?select=symbol," + DATE_COL + ",close&symbol=eq." + sym + "&order=" + DATE_COL + ".desc&limit=1")
    if isinstance(oc, list) and oc:
        print("  ", sym, oc[0].get(DATE_COL), oc[0].get("close"), "| n_rows_total:",
              get("ohlcv_daily?select=symbol&symbol=eq." + sym + "&order=" + DATE_COL + ".desc&limit=1")[1] is not None)
    else:
        print("  ", sym, "<no rows>", st)
