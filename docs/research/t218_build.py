#!/usr/bin/env python3
"""T-218 主构建:2021Q1→2026Q3 季度表 —— 稳定币供应 / 发行方收入 / 公链持币人收入 /
代币季度收益对 BTC / 轨道公司股价季度收益。

数据源(每个都标注):
  A) Supabase ohlcv_daily(source=binance_hist 优先,否则 coingecko_pro_ohlc) —— 代币收盘
     只读,翻页带 order=;按 symbol 定点查(整表翻页会撞 offset 上限漏掉 N-Z 段)
  B) Supabase asset_mcap_daily —— 卡上指定的稳定币市值来源:**实测没有 USDT/USDC**(248 symbol)
     ⇒ 退回 CoinGecko 公开 market_chart(usd-coin / tether 的 market_caps),标注为替代源
  C) Mac 数据根 research/s661/_llama_rev.jsonl —— DeFiLlama 缓存:
     发行方收入 = dailyRevenue(tether / circle);公链持币人收入 = dailyHoldersRevenue(eth / sol / trx / hype)
  D) 轨道公司股价:ohlcv_daily source=eodhd **实测没有 COIN/HOOD/CRCL** ⇒ 卡上写「待 Seth 入库」;
     另取公开源(stooq CSV)作**探索性**对照,不作为结算口径。

纪律:只读;不写库;结果落 t218_quarterly.json。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent
S661 = Path("/Volumes/CometCloudAI/cometcloud-local/research/s661")
UA = {"User-Agent": "lane-a/T-218 research (read-only)"}
PAGE = 1000

QUARTERS = []
for y in range(2021, 2027):
    for q in (1, 2, 3, 4):
        if y == 2026 and q > 3:
            break
        QUARTERS.append((y, q))

TOKENS = ["BTC", "ETH", "SOL", "TRX", "HYPE"]
RAILS = ["COIN", "HOOD", "CRCL"]
RAIL_START = {"COIN": "2021-04-01", "HOOD": "2021-07-01", "CRCL": "2025-06-01"}


def sb_get(path, params):
    q = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else []
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:200]


def sb_fetch(path, params, order):
    rows, off = [], 0
    while True:
        p = dict(params)
        p.update({"order": order, "limit": str(PAGE), "offset": str(off)})
        st, chunk = sb_get(path, p)
        if st != 200:
            return st, rows, chunk
        if not isinstance(chunk, list) or not chunk:
            return st, rows, None
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return st, rows, None
        off += PAGE
        if off > 300000:
            return st, rows, "offset-cap"


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:200]


def http_text(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:200]


def q_of(d: dt.date):
    return (d.year, (d.month - 1) // 3 + 1)


def q_label(y, q):
    return f"{y}Q{q}"


def q_end_date(y, q):
    m = q * 3
    if m == 12:
        return dt.date(y, 12, 31)
    return dt.date(y, m + 1, 1) - dt.timedelta(days=1)


# ── A) 代币收盘(季度末)────────────────────────────────────────────────────
def token_quarter_closes():
    out, meta = {}, {}
    for sym in TOKENS:
        best = None
        for src in ("binance_hist", "coingecko_pro_ohlc", "coingecko", "hyperliquid"):
            st, rows, err = sb_fetch("ohlcv_daily", {"symbol": f"eq.{sym}", "source": f"eq.{src}"}, "trade_date.asc")
            if st == 200 and rows:
                best = (src, rows)
                break
            meta.setdefault(sym, {})[src] = {"status": st, "n": len(rows) if isinstance(rows, list) else 0}
        if best is None:
            meta.setdefault(sym, {})["picked"] = None
            continue
        src, rows = best
        per_q = {}
        for r in rows:
            d = r.get("trade_date")
            c = r.get("close")
            if not d or c is None:
                continue
            dd = dt.date.fromisoformat(str(d)[:10])
            per_q[q_of(dd)] = (dd.isoformat(), float(c))   # 同一季度内按日期升序覆盖 ⇒ 留季末
        out[sym] = {"source": src, "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
        meta.setdefault(sym, {})["picked"] = src
    return out, meta


# ── B) 稳定币供应 ─────────────────────────────────────────────────────────
def stable_supply_cg():
    """CoinGecko 公开 market_chart:tether / usd-coin 的 market_caps(季度末取值)。"""
    out = {}
    for cid, sym in (("tether", "USDT"), ("usd-coin", "USDC")):
        st, d = http_json(f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart?vs_currency=usd&days=max&interval=daily")
        if st != 200 or not isinstance(d, dict):
            out[sym] = {"status": st, "err": str(d)[:200]}
            continue
        mc = d.get("market_caps") or []
        per_q = {}
        for ts, val in mc:
            if val is None:
                continue
            dd = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
            per_q[q_of(dd)] = (dd, float(val))
        out[sym] = {"status": st, "n_points": len(mc),
                    "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
    return out


def stable_supply_amcap():
    """卡上指定的来源 asset_mcap_daily:按符号定点查(整表翻页会撞上限)。"""
    out = {}
    for sym in ("USDT", "USDC"):
        st, rows, err = sb_fetch("asset_mcap_daily", {"symbol": f"eq.{sym}"}, "d.asc")
        out[sym] = {"status": st, "n": len(rows) if isinstance(rows, list) else 0, "err": err}
    return out


# ── C) Mac s661 DeFiLlama 缓存:收入 ──────────────────────────────────────
def llama_revenue():
    path = S661 / "_llama_rev.jsonl"
    if not path.exists():
        return {"error": "no _llama_rev.jsonl"}
    want = {"tether": "issuer", "circle": "issuer",
            "ethereum": "chain", "solana": "chain", "tron": "chain", "hyperliquid": "chain"}
    got = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            slug = d.get("slug")
            if slug not in want:
                continue
            bucket = "dailyHoldersRevenue" if want[slug] == "chain" else "dailyRevenue"
            ser = d.get(bucket)
            if not isinstance(ser, list):
                got.setdefault(slug, {})["error"] = f"{bucket} 缺(缓存里是 {type(ser).__name__})"
                continue
            per_q = {}
            for ts, val in ser:
                if val is None:
                    continue
                dd = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
                k = q_of(dd)
                agg = per_q.setdefault(k, {"sum": 0.0, "n": 0, "last": (dd, float(val))})
                agg["sum"] += float(val)
                agg["n"] += 1
                agg["last"] = (dd, float(val))
            got[slug] = {
                "bucket": bucket,
                "first_day": dt.datetime.fromtimestamp(ser[0][0], dt.timezone.utc).date().isoformat(),
                "last_day": dt.datetime.fromtimestamp(ser[-1][0], dt.timezone.utc).date().isoformat(),
                "n_points": len(ser),
                "q": {q_label(*k): {"sum": v["sum"], "days": v["n"], "last_val": v["last"][1],
                                   "last_day": v["last"][0].isoformat()} for k, v in sorted(per_q.items())},
            }
    return got


# ── D) 轨道公司股价:DB(结算口径)+ 公开源(探索性对照)────────────────────
def rails_db():
    out = {}
    for sym in RAILS:
        st, rows, err = sb_fetch("ohlcv_daily", {"symbol": f"eq.{sym}", "source": "eq.eodhd"}, "trade_date.asc")
        out[sym] = {"status": st, "n": len(rows) if isinstance(rows, list) else 0, "err": err}
    return out


def rails_stooq():
    out = {}
    for sym in RAILS:
        st, txt = http_text(f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d")
        if st != 200 or not txt or "Date" not in txt:
            out[sym] = {"status": st, "err": str(txt)[:150]}
            continue
        rows = list(csv.DictReader(io.StringIO(txt)))
        per_q = {}
        for r in rows:
            try:
                dd = dt.date.fromisoformat(r["Date"])
                c = float(r["Close"])
            except Exception:  # noqa: BLE001
                continue
            per_q[q_of(dd)] = (dd.isoformat(), c)
        out[sym] = {"status": st, "n": len(rows),
                    "first": rows[0]["Date"] if rows else None, "last": rows[-1]["Date"] if rows else None,
                    "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
    return out


def main():
    out = {}
    out["built_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    out["quarters"] = [q_label(*q) for q in QUARTERS]

    tok, tok_meta = token_quarter_closes()
    out["tokens"] = tok
    out["tokens_meta"] = tok_meta

    out["stable_amcap"] = stable_supply_amcap()
    out["stable_cg"] = stable_supply_cg()

    out["llama"] = llama_revenue()

    out["rails_db"] = rails_db()
    out["rails_stooq"] = rails_stooq()

    # macro / state 的当前值(前向命题要用合法变量名,先看值域)
    st, rows, err = sb_fetch("macro_daily", {}, "d.asc")
    if st == 200 and rows:
        per = {}
        for r in rows:
            per.setdefault(str(r.get("series")), []).append((str(r.get("d"))[:10], r.get("value")))
        out["macro"] = {k: {"n": len(v), "last": v[-1], "first": v[0]} for k, v in per.items()}
    else:
        out["macro"] = {"error": str(err)}

    st, rows, err = sb_fetch("state_daily", {}, "d.asc")
    if st == 200 and rows:
        per = {}
        for r in rows:
            per.setdefault(str(r.get("feature")), []).append((str(r.get("d"))[:10], r.get("value")))
        out["state"] = {k: {"n": len(v), "last": v[-1], "first": v[0]} for k, v in per.items()}
    else:
        out["state"] = {"error": str(err)}

    (HERE / "t218_quarterly.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t218_quarterly.json")
    for sym in TOKENS:
        q = tok.get(sym, {}).get("q", {})
        print(sym, tok.get(sym, {}).get("source"), "quarters:", len(q), "first:", list(q)[:2], "last:", list(q)[-2:])
    print("stable amcap:", out["stable_amcap"])
    for s, v in out["stable_cg"].items():
        print("stable cg", s, v.get("status"), v.get("n_points"), list(v.get("q", {}))[:2], list(v.get("q", {}))[-2:])
    for s, v in out["llama"].items():
        print("llama", s, v.get("bucket"), v.get("first_day"), v.get("last_day"), len(v.get("q", {})))
    print("rails db:", out["rails_db"])
    for s, v in out["rails_stooq"].items():
        print("rails stooq", s, v.get("status"), v.get("n"), v.get("first"), v.get("last"), len(v.get("q", {})))
    print("macro:", {k: v.get("last") for k, v in out["macro"].items()} if isinstance(out["macro"], dict) else out["macro"])
    print("state:", {k: v.get("last") for k, v in out["state"].items()} if isinstance(out["state"], dict) else out["state"])


if __name__ == "__main__":
    main()
