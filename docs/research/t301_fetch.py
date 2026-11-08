#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-301 / S-783 ① — 今天重拉 perp_bv_daily / v_funding_daily / perp_bv_pairs + crowding_watch(backfill)。

口径(照抄 S-783「写死」①):
  - perp_bv_daily: d >= 2019-10-01 且 d <= 2026-11-04
  - v_funding_daily: d <= 2026-11-04(与面板对齐由 build_panels 做)
  - perp_bv_pairs: 全表
  - crowding_watch: cohort = 'backfill'
翻页:每页 <= 1000 行(limit>1000 会被 PostgREST 静默截到 1000),一律带 order=(按主键排),
      核总行数(Prefer: count=exact,读 Content-Range 头),大表并行 offset(8 线程)。

产物落在 Mac 数据根(规则 3a):
  /Volumes/CometCloudAI/cometcloud-local/research/t301/cache/
用法:
  python3 t301_fetch.py --probe     # 只打 schema + count(不拉数据)
  python3 t301_fetch.py             # 全量拉
只读:不写库、不读 .env、不打印 key。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SU = os.environ["SUPABASE_URL"].rstrip("/")
SK = os.environ["SUPABASE_KEY"]
HDR = {"apikey": SK, "Authorization": "Bearer " + SK, "Prefer": "count=exact"}

CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t301/cache"
PAGE = 1000
WORKERS = 8

D_FROM = "2019-10-01"
D_TO = "2026-11-04"


def log(*a):
    print(*a, flush=True)


def _get(url, hdr=None, timeout=180):
    req = urllib.request.Request(url, headers=hdr or HDR)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return r.status, dict(r.headers), body


def api(path, params, hdr=None):
    """一次 GET,返回 (rows, content_range)。"""
    q = dict(params)
    q.setdefault("limit", PAGE)
    url = SU + "/rest/v1/" + path + "?" + urllib.parse.urlencode(q, safe=".*(),")
    st, hs, body = _get(url, hdr)
    rows = json.loads(body) if body else []
    return rows, hs.get("Content-Range", "")


def count_of(path, params):
    _, cr = api(path, dict(params, limit=1))
    # Content-Range: 0-0/12345
    try:
        return int(cr.split("/")[-1])
    except Exception:
        return -1


def fetch_paged(path, params, out_jsonl, workers=WORKERS):
    """并行 offset 拉取。每页 <= 1000。写 jsonl(一行一个数组,省内存)。"""
    total = count_of(path, params)
    if total < 0:
        raise RuntimeError("count failed for " + path)
    n_pages = (total + PAGE - 1) // PAGE
    log("  %s: count=%d rows, %d pages" % (path, total, n_pages))
    chunks = {}

    def one(p):
        st = p * PAGE
        rows, _ = api(path, dict(params, limit=PAGE, offset=st))
        return p, rows

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, rows in ex.map(one, range(n_pages)):
            chunks[p] = rows
            done += 1
            if done % 50 == 0:
                log("    ...%d/%d pages %.0fs" % (done, n_pages, time.time() - t0))
    rows_all = []
    for p in range(n_pages):
        rows_all.extend(chunks.get(p, []))
    log("  %s: got %d rows in %.0fs" % (path, len(rows_all), time.time() - t0))
    if len(rows_all) != total:
        raise RuntimeError("row count mismatch %s: got %d want %d" % (path, len(rows_all), total))
    # 完整性抽查:key 集合无重复
    keys = [(r.get("symbol"), str(r.get("d"))[:10]) for r in rows_all]
    if len(set(keys)) != len(keys):
        log("  WARN: duplicate (symbol,d) keys present: %d" % (len(keys) - len(set(keys))))
    with open(out_jsonl, "w") as f:
        f.write(json.dumps({"_count": total, "rows": rows_all}, separators=(",", ":")))
    return rows_all


def fetch_by_symbol(path, select, symbols, out_jsonl, workers=WORKERS):
    """按 symbol 分片拉(避免深 offset 触发 PostgREST 超时)。每个 symbol 内部再分页。"""
    def one(s):
        rows = []
        off = 0
        while True:
            try:
                r, cr = api(path, {"select": select, "symbol": "eq.%s" % s, "order": "symbol.asc,d.asc",
                                   "limit": PAGE, "offset": off})
            except Exception as e:
                time.sleep(1.5)
                r, cr = [], ""
            if not r:
                break
            rows.extend(r)
            if len(r) < PAGE:
                break
            off += PAGE
        return s, rows

    t0 = time.time()
    out = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for s, rows in ex.map(one, symbols):
            out[s] = rows
            done += 1
            if done % 100 == 0:
                log("    ...%d/%d symbols %.0fs" % (done, len(symbols), time.time() - t0))
    rows_all = []
    for s in symbols:
        rows_all.extend(out.get(s, []))
    log("  %s by-symbol: got %d rows over %d symbols in %.0fs" % (path, len(rows_all), len(symbols), time.time() - t0))
    with open(out_jsonl, "w") as f:
        f.write(json.dumps({"rows": rows_all}, separators=(",", ":")))
    return rows_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dates", action="store_true")
    ap.add_argument("--funding", action="store_true")
    ap.add_argument("--rest", action="store_true")
    ap.add_argument("--funding-tail", action="store_true")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)

    if args.funding_tail:
        # 资金费尾巴:d > D_TO(与 perp_bv_daily 的尾巴同两天)——
        # k_fund = 该合约面板里有资金费观测的天数,缺尾巴会与库内内核的 k_fund 不一致。
        rows = fetch_paged("v_funding_daily",
                           {"select": "symbol,d,funding_rate", "d": "gt.%s" % D_TO,
                            "order": "symbol.asc,d.asc"},
                           os.path.join(CACHE, "v_funding_daily_tail.json"), workers=2)
        ds = sorted(set(str(r["d"])[:10] for r in rows))
        log("funding tail rows=%d dates=%s symbols=%d"
            % (len(rows), ds, len(set(r["symbol"] for r in rows))))
        return
    os.makedirs(CACHE, exist_ok=True)

    if args.rest:
        # perp_bv_pairs(全表) + crowding_watch(backfill) + perp_bv_daily 的面板尾巴
        # (d > 2026-11-04:库内内核 crowding_events() 的面板没有上限,尾巴影响 k_fund 与去重)
        rows = fetch_paged("perp_bv_pairs", {"select": "*", "order": "symbol.asc"},
                            os.path.join(CACHE, "perp_bv_pairs.json"), workers=2)
        rows = fetch_paged("crowding_watch",
                            {"select": "kind,symbol,d,cohort,fund_pct,ret,atr_thr,qv_mult,x1,x7,x30,basket_n",
                             "cohort": "eq.backfill", "order": "kind.asc,symbol.asc,d.asc"},
                            os.path.join(CACHE, "crowding_watch_backfill.json"), workers=2)
        tail = fetch_paged("perp_bv_daily",
                           {"select": "symbol,d,o,h,l,c,qv,tbqv", "d": "gt.%s" % D_TO,
                            "order": "symbol.asc,d.asc"},
                           os.path.join(CACHE, "perp_bv_daily_tail.json"), workers=4)
        log("tail d-range: %s .. %s" % (min(str(r["d"])[:10] for r in tail),
                                        max(str(r["d"])[:10] for r in tail)))
        # 核 funding 的总行数(按 symbol 抽样 + 全表 count)
        fund = json.load(open(os.path.join(CACHE, "v_funding_daily.json")))["rows"]
        got = {}
        for r in fund:
            got[r["symbol"]] = got.get(r["symbol"], 0) + 1
        bad = 0
        for s in list(got)[:6]:
            _, cr = api("v_funding_daily", {"select": "symbol", "symbol": "eq.%s" % s, "order": "symbol.asc", "limit": 1})
            want = int(cr.split("/")[-1])
            if want != got[s]:
                bad += 1
                log("  WARN funding %s: got %d want %d" % (s, got[s], want))
        log("funding spot-check: %d symbols, %d mismatches" % (min(6, len(got)), bad))
        return

    if args.funding:
        # 面板符号 = perp_bv_daily 里出现过的 symbol(资金费只要这些)
        pbv_syms = set()
        with open(os.path.join(CACHE, "perp_bv_daily.json")) as f:
            for r in json.load(f)["rows"]:
                pbv_syms.add(r["symbol"])
        syms = sorted(pbv_syms)
        log("funding: %d panel symbols" % len(syms))
        rows = fetch_by_symbol("v_funding_daily", "symbol,d,funding_rate", syms,
                               os.path.join(CACHE, "v_funding_daily.json"))
        ds = [str(r["d"])[:10] for r in rows]
        log("funding rows=%d  d-range=%s .. %s" % (len(rows), min(ds), max(ds)))
        return

    if args.dates:
        for lbl, path, par in (
            ("pbv_after", "perp_bv_daily", {"select": "symbol,d,o,c", "d": "gt.%s" % D_TO, "order": "d.desc"}),
            ("fund_after", "v_funding_daily", {"select": "symbol,d", "d": "gt.%s" % D_TO, "order": "d.desc"}),
            ("cw_max", "crowding_watch", {"select": "kind,symbol,d,cohort,x30,basket_n", "order": "d.desc"}),
            ("cw_kind", "crowding_watch", {"select": "kind", "cohort": "eq.backfill", "order": "kind.asc"}),
        ):
            rows, cr = api(path, dict(par, limit=3))
            log("%-9s count=%-16s sample=%s" % (lbl, cr, json.dumps(rows[:2])[:300]))
        return

    if args.probe:
        for path, params in (
            ("perp_bv_daily", {"select": "symbol,d,o,h,l,c,qv,tbqv", "d": "gte.%s" % D_FROM,
                                "and": "(d.lte.%s)" % D_TO, "order": "symbol.asc,d.asc"}),
            ("v_funding_daily", {"select": "symbol,d,funding_rate", "d": "lte.%s" % D_TO,
                                  "order": "symbol.asc,d.asc"}),
            ("perp_bv_pairs", {"select": "*", "order": "symbol.asc"}),
            ("crowding_watch", {"select": "kind,symbol,d,cohort,fund_pct,ret,atr_thr,qv_mult,x1,x7,x30,basket_n",
                                "cohort": "eq.backfill", "order": "kind.asc,symbol.asc,d.asc"}),
        ):
            try:
                rows, cr = api(path, dict(params, limit=2))
                log("%-20s count=%s keys=%s" % (path, cr, sorted(rows[0].keys()) if rows else "NONE"))
                if rows:
                    log("    sample:", json.dumps(rows[0])[:300])
            except Exception as e:
                log("%-20s ERROR %r" % (path, e))
        return

    t0 = time.time()
    log("=== T-301 fetch ===")
    pbv = fetch_paged("perp_bv_daily",
                      {"select": "symbol,d,o,h,l,c,qv,tbqv", "d": "gte.%s" % D_FROM,
                       "and": "(d.lte.%s)" % D_TO, "order": "symbol.asc,d.asc"},
                      os.path.join(CACHE, "perp_bv_daily.json"))
    fund = fetch_paged("v_funding_daily",
                       {"select": "symbol,d,funding_rate", "d": "lte.%s" % D_TO,
                        "order": "symbol.asc,d.asc"},
                       os.path.join(CACHE, "v_funding_daily.json"))
    pairs = fetch_paged("perp_bv_pairs", {"select": "*", "order": "symbol.asc"},
                        os.path.join(CACHE, "perp_bv_pairs.json"))
    cw = fetch_paged("crowding_watch",
                     {"select": "kind,symbol,d,cohort,fund_pct,ret,atr_thr,qv_mult,x1,x7,x30,basket_n",
                      "cohort": "eq.backfill", "order": "kind.asc,symbol.asc,d.asc"},
                     os.path.join(CACHE, "crowding_watch_backfill.json"))
    log("=== done %.0fs: pbv=%d fund=%d pairs=%d cw=%d ===" % (time.time() - t0, len(pbv), len(fund), len(pairs), len(cw)))
    kc = {}
    for r in cw:
        kc[(r["kind"], r["symbol"], str(r["d"])[:10])] = r
    log("crowding_watch backfill by kind:",
        {k: sum(1 for x in cw if x["kind"] == k) for k in set(x["kind"] for x in cw)})


if __name__ == "__main__":
    sys.exit(main())
