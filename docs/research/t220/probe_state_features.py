"""T-220 补交的只读探针(可复跑):三部分

1) state_daily —— 可自动结算的 feature 清单 + panel(entity=panel)最新快照;
2) SPELL —— S-661 十八个开闸事件里唯一带热度峰值的一个(S-220 报告 §3),
   开闸日前后 + 最新收盘(ohlcv_daily, source=binance_hist);
3) SKY / MKR —— 遗留问题 4:查价守护源(symbol 撞名 / asset_id 定位)。

纪律:全程只读(SELECT),不写库、不改代码。
跑法:python3 docs/research/t220/probe_state_features.py > docs/research/t220/_skymkr_coverage.json
"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(path, params):
    url = BASE + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "body": e.read().decode()[:200]}


out = {}

# ── 1) state_daily:可结算 feature + panel 最新快照 ───────────────────────
rows = get("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                           "order": "d.desc,feature.asc", "limit": 200})
out["panel_latest_d"] = rows[0]["d"] if rows else None
out["panel_latest"] = {r["feature"]: r["value"] for r in rows if r["d"] == out["panel_latest_d"]}
out["n_state_features"] = len(out["panel_latest"])

# ── 2) SPELL:开闸日(2026-06-01)前后 + 最新收盘 ───────────────────────────
out["spell_open_window"] = get("ohlcv_daily", {
    "select": "trade_date,close,source", "symbol": "eq.SPELL", "source": "eq.binance_hist",
    "and": "(trade_date.gte.2026-05-28,trade_date.lte.2026-06-08)", "order": "trade_date.asc", "limit": 20})
out["spell_latest"] = get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.SPELL",
                                          "source": "eq.binance_hist", "order": "trade_date.desc", "limit": 1})

# ── 3) SKY / MKR:撞名与守护源 ─────────────────────────────────────────────
for label, key, pat in (
    ("asset_id_like_sky", "asset_id", "*sky*"),
    ("symbol_like_mkr", "symbol", "MKR"),
):
    rr = get("ohlcv_daily", {"select": "symbol,asset_id,source,trade_date,close",
                             key: "ilike." + pat, "order": "symbol.asc,source.asc,trade_date.asc", "limit": 60})
    per = {}
    if isinstance(rr, list):
        for r in rr:
            k = "|".join([r["symbol"], str(r["asset_id"]), r["source"]])
            d = per.setdefault(k, {"n": 0, "first": r["trade_date"], "last": r["trade_date"], "last_close": None})
            d["n"] += 1
            d["last"] = r["trade_date"]
            d["last_close"] = r["close"]
    out[label] = per if isinstance(rr, list) else rr

mkr = get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.MKR", "source": "eq.coingecko_pro_ohlc",
                          "order": "trade_date.asc", "limit": 100000})
if isinstance(mkr, list):
    out["mkr_cg"] = {"n": len(mkr), "first": mkr[0], "last": mkr[-1], "sample": mkr[::40][:14]}
else:
    out["mkr_cg"] = mkr

print(json.dumps(out, ensure_ascii=False, indent=1))
