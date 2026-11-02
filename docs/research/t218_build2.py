#!/usr/bin/env python3
"""T-218 主构建 v2:把 ① 的季度表拼齐,并给 ③ 前向命题取当前变量值。

数据源(逐项标注;DB 一律 paginate + order=):
  A) cg_coin_mcap_daily (DB, coingecko_pro_market_chart) —— USDT / USDC 市值日序列
     卡上写的 asset_mcap_daily 实测没有 USDT/USDC(该表 symbol 只有 0G),
     cg_coin_mcap_daily 才是 DB 内的稳定币市值序列(2019-12-31 起)。
  B) ohlcv_daily (DB, source=binance_hist 等) —— 代币季末收盘(BTC/ETH/SOL/TRX/HYPE)
  C) /Volumes/CometCloudAI/cometcloud-local/research/s661/_llama_rev.jsonl ——
     DeFiLlama 缓存:发行方收入 dailyRevenue(tether/circle)、公链持币人收入
     dailyHoldersRevenue(ethereum/solana/tron/hyperliquid)
  D) ohlcv_daily source=eodhd —— 轨道公司(COIN/HOOD/CRCL):11-02 18:40 JST 起 DB 里已入库
     (COIN 1395 行 / HOOD 1321 / CRCL 355,截至 2026-10-30)⇒ 轨道侧季度收益改用
     **结算口径(DB eq.eodhd)**;Nasdaq 公开接口保留为**独立交叉核对**(不用于出数)。
  E) state_daily / macro_daily —— ③ 命题的变量值域。

纪律:只读(SELECT / 公开 GET);不写库;不打印任何 key;结果落 t218_table.json。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
import t218_build as B  # noqa: E402  (复用已验证的分页/季度聚合函数)

SB = B.SB
KEY = B.KEY
H = B.H
UA = B.UA
PAGE = B.PAGE

QUARTERS = B.QUARTERS
TOKENS = ["BTC", "ETH", "SOL", "TRX", "HYPE"]
RAILS = ["COIN", "HOOD", "CRCL"]
Q_LABELS = [B.q_label(*q) for q in QUARTERS]


def q_of(d: dt.date):
    return (d.year, (d.month - 1) // 3 + 1)


def q_label(y, q):
    return f"{y}Q{q}"


# ── A) 稳定币市值(cg_coin_mcap_daily)───────────────────────────────────────
def stable_mcap_db():
    out = {}
    for cid, sym in (("tether", "USDT"), ("usd-coin", "USDC")):
        st, rows, err = B.sb_fetch("cg_coin_mcap_daily", {"coin_id": f"eq.{cid}"},
                                   "coin_id.asc,d.asc")
        if st != 200 or not rows:
            out[sym] = {"status": st, "n": 0, "err": str(err)[:200]}
            continue
        per_q, nn = {}, 0
        for r in rows:
            mc = r.get("mcap")
            if mc is None:
                continue
            nn += 1
            dd = dt.date.fromisoformat(str(r.get("d"))[:10])
            per_q[q_of(dd)] = (dd.isoformat(), float(mc))
        out[sym] = {"status": st, "n": len(rows), "n_mcap": nn,
                    "first": rows[0].get("d"), "last": rows[-1].get("d"),
                    "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
    return out


# ── D1) 轨道公司:DB 结算口径(eq.eodhd)───────────────────────────────────
def rails_db_q():
    """COIN/HOOD/CRCL 的 DB 季末收盘(eq.<SYM> / eq.eodhd)—— 台账结算用的就是这一路。"""
    out = {}
    for sym in RAILS:
        st, rows, err = B.sb_fetch("ohlcv_daily", {"symbol": f"eq.{sym}", "source": "eq.eodhd"},
                                   "trade_date.asc")
        if st != 200 or not isinstance(rows, list) or not rows:
            out[sym] = {"status": st, "n": 0, "err": str(err)[:200], "q": {}}
            continue
        per_q = {}
        for r in rows:
            d = r.get("trade_date")
            c = r.get("close")
            if not d or c is None:
                continue
            dd = dt.date.fromisoformat(str(d)[:10])
            per_q[q_of(dd)] = (dd.isoformat(), float(c))   # 季内按日期升序覆盖 ⇒ 留季末
        out[sym] = {"status": st, "n": len(rows),
                    "first": str(rows[0].get("trade_date"))[:10],
                    "last": str(rows[-1].get("trade_date"))[:10],
                    "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
    return out


# ── D2) 轨道公司:公开源(Nasdaq)—— 只做独立交叉核对 ───────────────────────
def rails_nasdaq():
    out = {}
    for sym in RAILS:
        url = ("https://api.nasdaq.com/api/quote/%s/historical?assetclass=stocks"
               "&fromdate=2021-04-01&todate=2026-10-31&limit=2000" % sym)
        st, body = B.http_text(url)
        if st != 200 or not body or '"rows"' not in body:
            out[sym] = {"status": st, "err": body[:150] if body else "empty"}
            continue
        d = json.loads(body)
        rows = (((d.get("data") or {}).get("tradesTable") or {}).get("rows")) or []
        # Nasdaq 的 rows 是**日期倒序**的:不排序就按季覆盖,留下的是「季初」而不是「季末」
        # (11-02 首版就是踩了这个坑:轨道侧整列季度收益算的是季初对季初)。
        rows = sorted(rows, key=lambda r: dt.datetime.strptime(r["date"], "%m/%d/%Y").date())
        per_q = {}
        for r in rows:
            try:
                dd = dt.datetime.strptime(r["date"], "%m/%d/%Y").date()
                c = float(str(r["close"]).replace("$", "").replace(",", ""))
            except Exception:  # noqa: BLE001
                continue
            per_q[q_of(dd)] = (dd.isoformat(), c)   # 季内升序覆盖 ⇒ 留季末
        out[sym] = {"status": st, "n": len(rows),
                    "total_records": (d.get("data") or {}).get("totalRecords"),
                    "q": {q_label(*k): v for k, v in sorted(per_q.items())}}
    return out


# ── E) 命题变量当前值 ─────────────────────────────────────────────────────
def variable_snapshot():
    snap = {}
    for sym in TOKENS + RAILS:
        rows = None
        for src in ("binance_hist", "coingecko_pro_ohlc", "eodhd"):
            st, rr, err = B.sb_fetch("ohlcv_daily", {"symbol": f"eq.{sym}", "source": f"eq.{src}"},
                                     "trade_date.asc")
            if st == 200 and rr:
                rows = rr
                snap[sym] = {"source": src, "last": [str(rr[-1].get("trade_date"))[:10],
                                                     rr[-1].get("close")]}
                break
        if rows is None:
            snap[sym] = {"source": None, "last": None}
    for feat in ("stable_supply_30d", "funding_7d_ann", "mom_20", "mom_200", "breadth_above_ma50",
                 "vol_30", "taker_buy_share_30d", "spy_ret_21", "vratio_30_180", "style_rel_majors_30d"):
        st, rr, err = B.sb_fetch("state_daily", {"feature": f"eq.{feat}"}, "d.asc")
        if st == 200 and rr:
            vals = [r for r in rr if r.get("value") is not None]
            snap["state:" + feat] = {"n": len(rr), "last": [str(vals[-1].get("d"))[:10],
                                                            vals[-1].get("value")] if vals else None}
        else:
            snap["state:" + feat] = {"n": 0, "last": None, "err": str(err)[:120]}
    for ser in ("vix", "fng", "total_mcap", "fed_rrp", "total_volume", "fed_tga"):
        st, rr, err = B.sb_fetch("macro_daily", {"series": f"eq.{ser}"}, "d.asc")
        if st == 200 and rr:
            vals = [r for r in rr if r.get("value") is not None]
            snap["macro:" + ser] = {"n": len(rr), "last": [str(vals[-1].get("d"))[:10],
                                                           vals[-1].get("value")] if vals else None}
        else:
            snap["macro:" + ser] = {"n": 0, "last": None, "err": str(err)[:120]}
    return snap


def pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b / a - 1.0) * 100.0


def prev_q_label(y, q):
    """上一季度的标签(跨年:Q1 → 上一年的 Q4)。"""
    if q > 1:
        return q_label(y, q - 1)
    return q_label(y - 1, 4)


def compute_table(out):
    rows = []
    # 稳定币合计序列(全历史,含表格窗口之前),用于环比
    usdt_q = out["stable_db"].get("USDT", {}).get("q", {})
    usdc_q = out["stable_db"].get("USDC", {}).get("q", {})
    stable_series = {}
    for k in set(usdt_q) | set(usdc_q):
        a = usdt_q.get(k)
        b = usdc_q.get(k)
        if a or b:
            stable_series[k] = (a[1] if a else 0) + (b[1] if b else 0)
    for q in QUARTERS:
        lab = q_label(*q)
        usdt = usdt_q.get(lab)
        usdc = usdc_q.get(lab)
        tot = stable_series.get(lab)
        row = {"quarter": lab,
               "usdt_mcap": usdt[1] if usdt else None,
               "usdc_mcap": usdc[1] if usdc else None,
               "stable_total": tot,
               "stable_qoq_pct": pct(stable_series.get(prev_q_label(*q)), tot)}
        # 收入(季度合计,$)
        for name, slug in (("tether_rev", "tether"), ("circle_rev", "circle")):
            cell = out["llama"].get(slug, {}).get("q", {}).get(lab)
            row[name] = cell["sum"] if cell else None
            row[name + "_days"] = cell["days"] if cell else 0
        for name, slug in (("eth_holders_rev", "ethereum"), ("sol_holders_rev", "solana"),
                           ("trx_holders_rev", "tron"), ("hype_holders_rev", "hyperliquid")):
            cell = out["llama"].get(slug, {}).get("q", {}).get(lab)
            row[name] = cell["sum"] if cell else None
            row[name + "_days"] = cell["days"] if cell else 0
        # 代币季度收益
        for sym in TOKENS:
            qd = out["tokens"].get(sym, {}).get("q", {})
            cur = qd.get(lab)
            prv = qd.get(prev_q_label(*q))
            row[f"{sym}_ret_pct"] = pct(prv[1], cur[1]) if (cur and prv) else None
        btc = row.get("BTC_ret_pct")
        for sym in TOKENS:
            r = row.get(f"{sym}_ret_pct")
            row[f"{sym}_excess_pct"] = (r - btc) if (r is not None and btc is not None) else None
        # 轨道公司季度收益(DB 结算口径为主,Nasdaq 只做交叉核对)
        for sym in RAILS:
            qd = out["rails_db_q"].get(sym, {}).get("q", {})
            cur = qd.get(lab)
            prv = qd.get(prev_q_label(*q))
            row[f"{sym}_ret_pct"] = pct(prv[1], cur[1]) if (cur and prv) else None
            qn = out["rails_nasdaq"].get(sym, {}).get("q", {})
            curn = qn.get(lab)
            prvn = qn.get(prev_q_label(*q))
            row[f"{sym}_ret_pct_nasdaq"] = pct(prvn[1], curn[1]) if (curn and prvn) else None
            a, b = row[f"{sym}_ret_pct"], row[f"{sym}_ret_pct_nasdaq"]
            row[f"{sym}_ret_diff_pp"] = (a - b) if (a is not None and b is not None) else None
        rows.append(row)
    return rows


def main():
    import sys
    out = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    if "--recompute" in sys.argv and (HERE / "t218_table.json").exists():
        prev = json.loads((HERE / "t218_table.json").read_text())
        for k in ("tokens", "tokens_meta", "stable_db", "llama", "rails_db",
                  "rails_db_q", "rails_nasdaq", "snapshot"):
            out[k] = prev.get(k)
        print("[recompute] 复用 t218_table.json 里已抓取的源,不重新请求")
    else:
        tok, tok_meta = B.token_quarter_closes()
        out["tokens"] = tok
        out["tokens_meta"] = tok_meta
        out["stable_db"] = stable_mcap_db()
        out["llama"] = B.llama_revenue()
        out["rails_db"] = B.rails_db()
        out["rails_db_q"] = rails_db_q()
        out["rails_nasdaq"] = rails_nasdaq()
        out["snapshot"] = variable_snapshot()

    rows = compute_table(out)
    out["table"] = rows

    (HERE / "t218_table.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    # ── 打印核对摘要 ──────────────────────────────────────────────────────
    print("== 代币收盘来源 ==")
    for s in TOKENS:
        print(" ", s, out["tokens"].get(s, {}).get("source"),
              "nq", len(out["tokens"].get(s, {}).get("q", {})))
    print("== 稳定币市值(DB cg_coin_mcap_daily)==")
    for s, v in out["stable_db"].items():
        print(" ", s, v.get("status"), "rows", v.get("n"), "mcap_nonnull", v.get("n_mcap"),
              v.get("first"), "→", v.get("last"))
    print("== 收入(DeFiLlama s661)==")
    for s, v in out["llama"].items():
        print(" ", s, v.get("bucket"), v.get("first_day"), "→", v.get("last_day"), "nq", len(v.get("q", {})))
    print("== 轨道公司 ==")
    print("  db(eodhd):", {k: v.get("n") for k, v in out["rails_db"].items()})
    for k, v in out.get("rails_db_q", {}).items():
        qs = v.get("q", {})
        diffs = [abs(r[f"{k}_ret_diff_pp"]) for r in out["table"]
                 if r.get(f"{k}_ret_diff_pp") is not None]
        print("  dbq", k, "rows", v.get("n"), v.get("first"), "→", v.get("last"),
              "nq", len(qs), "| vs Nasdaq 最大差 %.3f pp (n=%d)" % (max(diffs), len(diffs)) if diffs else "")
    for k, v in out["rails_nasdaq"].items():
        qs = v.get("q", {})
        print("  nasdaq", k, v.get("status"), "rows", v.get("n"), "nq", len(qs),
              list(qs)[:2], list(qs)[-2:])
    print("== 季度表(选列)==")
    hdr = ("quarter", "stable_total($B)", "qoq%", "tether_rev($M)", "circle_rev($M)",
           "eth_holders($M)", "sol_holders($M)", "BTC%", "ETH%", "SOL%", "TRX%", "HYPE%",
           "COIN%", "HOOD%", "CRCL%")
    print(" | ".join(hdr))
    for r in rows:
        def f(v, s=1e6, d=1):
            return "—" if v is None else f"{v / s:,.{d}f}"
        print(" | ".join([r["quarter"], f(r["stable_total"], 1e9, 2),
                          "—" if r["stable_qoq_pct"] is None else f"{r['stable_qoq_pct']:.1f}",
                          f(r["tether_rev"]), f(r["circle_rev"]), f(r["eth_holders_rev"]),
                          f(r["sol_holders_rev"]),
                          "—" if r["BTC_ret_pct"] is None else f"{r['BTC_ret_pct']:.1f}",
                          "—" if r["ETH_ret_pct"] is None else f"{r['ETH_ret_pct']:.1f}",
                          "—" if r["SOL_ret_pct"] is None else f"{r['SOL_ret_pct']:.1f}",
                          "—" if r["TRX_ret_pct"] is None else f"{r['TRX_ret_pct']:.1f}",
                          "—" if r["HYPE_ret_pct"] is None else f"{r['HYPE_ret_pct']:.1f}",
                          "—" if r["COIN_ret_pct"] is None else f"{r['COIN_ret_pct']:.1f}",
                          "—" if r["HOOD_ret_pct"] is None else f"{r['HOOD_ret_pct']:.1f}",
                          "—" if r["CRCL_ret_pct"] is None else f"{r['CRCL_ret_pct']:.1f}"]))
    print("== 命题变量快照 ==")
    print(json.dumps(out["snapshot"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
