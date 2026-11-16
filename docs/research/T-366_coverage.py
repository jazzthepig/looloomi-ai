"""T-366(lane-b,2026-11-13)—— R-v2 真钱票源币 vs 三套资产描述(资产向量 / 资金面向量 / CIS)的逐币对账。

**卡**:T-366(台账 S-842)。问的是:「真钱在交易的币有没有向量」。
S-842 实测:`asset_embeddings` 只覆盖 59 个在更新的资产(24 加密 + 35 传统),而 R-v2 真钱票开在
几百个永续合约上;`asset_flow_daily`(11 维资金面)有 652 个币。本卡把这两句话**逐币量化**:
票源币里有多少真的能被向量/评分描述,三种权重各是多少。

**口径(全部沿用上游,一字不改)**:
  票源  `docs/research/t197_results.json` → `tickets.A`(与 `t310_slots.load_tickets` 同源同路径:
         t310_slots.py 第 62-64 行 `load_tickets()` 读的就是这个文件、这个 key)。
  窗口  `signal_d >= 2024-11-01`(卡上指定「2024-11 以来开过票」)。
  盈亏  名义 = min(净值 × 0.5% ÷ 止损距离, 净值 × 50%);止损距离 = (entry_px − stop_px) ÷ entry_px;
         美元 P&L = 名义 × r。r 取票源 t197 的 r(已扣止损/出场);`still` 票(r 为空)用 Mac 数据根
         永续日线最后一根收盘算 mtm(同 t310 的 bars 源)。净值恒取 $630(t310 的 equity0,
         逐票独立口径,不做复利 —— 覆盖统计要的是「每张票的钱」,不是净值曲线)。

**只读**:不写库、不改 src、不新建抓取器。所有 DB 读走 PostgREST(读 key),每页 ≤1000 行、
一律带 `order=`。

**用法**:`python3 docs/research/T-366_coverage.py`
  → 写 `docs/research/T-366_traded_universe_coverage.json`
  → 写 `docs/research/T-366_traded_universe_coverage.md`
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

T197 = os.path.join(HERE, "t197_results.json")
UM = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
OUT_JSON = os.path.join(HERE, "T-366_traded_universe_coverage.json")
OUT_MD = os.path.join(HERE, "T-366_traded_universe_coverage.md")

SINCE = "2024-11-01"
EQUITY0 = 630.0
RISK_FRAC = 0.005
MAX_FRAC = 0.5
FRESH_DAYS = 7          # 「最近更新过」的判定窗
PRICE_HIST_DAYS = 60    # 算 30d 涨跌 / 检查历史深度用
CHUNK = 30              # symbol=in.(...) 每片大小

NOW = dt.datetime.now(dt.timezone.utc)


# ── PostgREST ───────────────────────────────────────────────────────────────────────────────────────
def q(table, qs, count=False):
    url = URL + "/rest/v1/" + table + "?" + qs
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if count:
        headers["Prefer"] = "count=exact"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
            return r.headers.get("Content-Range"), r.read().decode()
    except Exception as e:  # noqa: BLE001
        return "ERR", type(e).__name__ + ": " + str(e)[:200]


def page_all(table, qs_base, order):
    """翻页取全表(每页 1000,带 order=,不带 order 边界会漂)。"""
    out, off = [], 0
    while True:
        cr, body = q(table, qs_base + "&order=" + order + "&limit=1000&offset=" + str(off))
        if body.startswith("ERR"):
            print("ERR", table, qs_base, body[:120])
            break
        rows = json.loads(body)
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
        if off > 200000:
            break
    return out


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def in_list(syms):
    return "(" + ",".join(syms) + ")"


# ── 票源 ───────────────────────────────────────────────────────────────────────────────────────────
def load_tickets():
    """t310_slots.load_tickets 同源同路径:docs/research/t197_results.json → tickets.A。"""
    d = json.load(open(T197))
    return d["tickets"]["A"], d


def load_um():
    """Mac 数据根的永续日线(只取我们要的聚合量,不留全量)。"""
    bars = {}
    with open(UM) as f:
        for line in f:
            x = json.loads(line)
            sym = str(x.get("symbol") or x.get("s") or "").upper()
            rows = x.get("bars") or x.get("b") or x.get("rows") or x.get("data") or []
            out = []
            for r in rows:
                if isinstance(r, dict):
                    d = r.get("d") or r.get("date")
                    c = r.get("c")
                    if d is None or c is None:
                        continue
                    out.append((str(d)[:10], float(c)))
                elif isinstance(r, (list, tuple)) and len(r) >= 5:
                    out.append((str(r[0])[:10], float(r[4])))
            if out:
                bars[sym] = sorted(out)
    return bars


# ── 27 维定义(只读自 src/data/vector/embedder.py,不改 src)────────────────────────────────────────
# dim: (序号, 名称, 含义/公式, 数据来源, 只有「永续日线+资金费+OI、没有 CIS」能不能算, 原因)
DIMS = [
    (0, "F/100", "Fundamental 支柱", "CIS 引擎 pillar_F(cis_official_daily.pillar_f)",
     "否", "支柱是打分结果,不是永续数据能推出的量"),
    (1, "M/100", "Momentum 支柱", "CIS 引擎 pillar_M(cis_official_daily.pillar_m)",
     "否", "同上"),
    (2, "O/100", "On-chain/风险调整支柱", "CIS 引擎 pillar_O(cis_official_daily.pillar_o)",
     "否", "同上"),
    (3, "S/100", "Sentiment 支柱", "CIS 引擎 pillar_S(cis_official_daily.pillar_s)",
     "否", "同上"),
    (4, "A/100", "Alpha 支柱", "CIS 引擎 pillar_A(cis_official_daily.pillar_a)",
     "否", "同上"),
    (5, "cis_score/100", "CIS 总分", "cis_official_daily.cis_score",
     "否", "总分的定义就是五支柱的加总"),
    (6, "log10(mcap)/15", "市值(log 归一)", "asset_mcap_daily.mcap(CoinGecko 市值)",
     "部分", "永续合约本身没有市值;CoinGecko 有该币市值才能算 —— 库里是 market_chart 的历史市值"),
    (7, "chg_24h/20", "24h 涨跌", "日收盘(asset_mcap_daily.price / ohlcv_daily.close)",
     "是", "永续日线收盘即可算(口径与现货收盘略有差)"),
    (8, "chg_7d/50", "7d 涨跌", "同上", "是", "需要 ≥8 根日线"),
    (9, "chg_30d/100", "30d 涨跌", "同上", "是", "需要 ≥31 根日线"),
    (10, "min(vol/mcap×10,1)", "成交额/市值", "asset_mcap_daily.volume ÷ .mcap",
     "部分", "永续有成交额(um_daily 的 qv)但库里这一维的分子是现货 24h 成交额,口径不同"),
    (11, "clamp(funding×1000)", "资金费率", "funding_history(venue=binance_perp).funding_rate",
     "是", "资金费是永续原生量;库里 funding_history 280 万行覆盖多币"),
    (12, "oi/mcap×5", "OI/市值 杠杆比", "OI 存量(CoinGecko derivatives,只在 CIS universe 内)÷ mcap",
     "部分", "有 OI 存量 + 有市值才能算;我们库里只有 ΔOI(flow 表 doi7),没有 OI 存量"),
    (13, "(100−ath)/100", "距历史高点", "ath_distance_pct(现货 ATH;永续代理=历史最高价)",
     "是(代理)", "永续日线可算历史最高价,但与现货 ATH 口径不同,只能当代理"),
    (14, "las/100", "流动性调整分", "CIS 引擎 las",
     "否", "LAS 是打分产物"),
    (15, "confidence", "数据置信度", "CIS 引擎 confidence",
     "否", "CIS 引擎自评的数据完整度"),
    (16, "class_enc/10", "资产类别编码", "资产清单映射(_CLASS_ENC)",
     "部分", "加密默认 Crypto=0.8 可填;L1/L2/DeFi/… 子类要外部映射"),
    (17, "regime_alignment", "宏观 regime 对齐", "全局 macro regime(_REGIME_ALIGN)",
     "是", "全局量,任何资产都能填 —— 非 CIS 依赖"),
    (18, "d_F", "F 支柱一日变化", "连续两天的 pillar_F",
     "否", "需要 CIS 支柱历史"),
    (19, "d_M", "M 支柱一日变化", "连续两天的 pillar_M", "否", "同上"),
    (20, "d_O", "O 支柱一日变化", "连续两天的 pillar_O", "否", "同上"),
    (21, "d_S", "S 支柱一日变化", "连续两天的 pillar_S", "否", "同上"),
    (22, "d_A", "A 支柱一日变化", "连续两天的 pillar_A", "否", "同上"),
    (23, "stability_O", "O 支柱窗口波动", "pillar_O 历史序列 std",
     "否", "需要 CIS 支柱历史(≥3 obs)"),
    (24, "stability_S", "S 支柱窗口波动", "pillar_S 历史序列 std", "否", "同上"),
    (25, "edge_vol", "β 调整后边际的波动", "asset_edge_moments 视图",
     "否", "**该视图实测 0 行** —— 连 CIS 资产也填不上"),
    (26, "edge_p10", "β 调整后边际的左尾", "asset_edge_moments 视图",
     "否", "**该视图实测 0 行**"),
]

NON_CIS_DIMS = [d[0] for d in DIMS if d[0] not in list(range(0, 6)) + [14, 15] + list(range(18, 27))]
MIN_MEASURED_DIMS = 10   # embedder.py:584 —— 少于 10/27 维实测就不写这一行


def main():
    res = {"card": "T-366", "lane": "lane-b", "ran_utc": NOW.isoformat()}

    # ── 1. 票源 ──────────────────────────────────────────────────────────────────────────────
    all_tickets, raw = load_tickets()
    tickets = [t for t in all_tickets if t["signal_d"] >= SINCE]
    bars = load_um()
    last_close = {s: v[-1][1] for s, v in bars.items()}
    last_date = {s: v[-1][0] for s, v in bars.items()}
    ath_close = {s: max(c for _, c in v) for s, v in bars.items()}
    bar_span = {s: (v[0][0], v[-1][0], len(v)) for s, v in bars.items()}

    per_ticket = []
    for t in tickets:
        sym = t["symbol"].upper()
        r = t.get("r")
        mtm = None
        if r is None:
            lc = last_close.get(sym)
            if lc and t.get("entry_px"):
                mtm = lc / t["entry_px"] - 1.0
            r = mtm
        stop_frac = None
        if t.get("entry_px") and t.get("stop_px") and t["entry_px"] != t["stop_px"]:
            stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
        notional = pnl = None
        if stop_frac and 0 < stop_frac < 0.9 and r is not None:
            notional = min(EQUITY0 * RISK_FRAC / stop_frac, EQUITY0 * MAX_FRAC)
            pnl = notional * r
        per_ticket.append({
            "symbol": sym, "signal_d": t["signal_d"], "entry_d": t.get("entry_d"),
            "r": r, "mtm": mtm, "notional_usd": notional, "pnl_usd": pnl,
        })

    syms = sorted({t["symbol"] for t in per_ticket})
    n_tickets = len(per_ticket)
    res["ticket_source"] = {
        "file": "docs/research/t197_results.json → tickets.A(与 t310_slots.load_tickets 同源)",
        "all_tickets": len(all_tickets), "window_since": SINCE,
        "n_tickets": n_tickets, "n_symbols": len(syms),
        "signal_range": [min(t["signal_d"] for t in per_ticket), max(t["signal_d"] for t in per_ticket)],
        "n_tickets_no_r": sum(1 for t in per_ticket if t["r"] is None),
        "n_tickets_mtm_from_um": sum(1 for t in per_ticket if t.get("mtm") is not None),
        "n_tickets_no_notional": sum(1 for t in per_ticket if t["notional_usd"] is None),
        "equity0": EQUITY0, "risk_frac": RISK_FRAC, "max_frac": MAX_FRAC,
    }

    # ── 2. 三套覆盖 ──────────────────────────────────────────────────────────────────────────
    # 2a. asset_embeddings
    emb_rows = page_all("asset_embeddings", "select=symbol,asset_class,schema_version,computed_at,dims",
                        "symbol.asc")
    cut = NOW - dt.timedelta(days=FRESH_DAYS)
    emb = {}
    for r in emb_rows:
        ca = r.get("computed_at")
        ca_d = dt.datetime.fromisoformat(ca) if ca else None
        emb[r["symbol"]] = {
            "schema_version": r.get("schema_version"), "asset_class": r.get("asset_class"),
            "computed_at": ca, "fresh": bool(ca_d and ca_d >= cut),
            "v3": r.get("schema_version") == 3,
        }
    emb_ok = {s for s, v in emb.items() if v["v3"] and v["fresh"]}
    emb_classes = defaultdict(list)
    for s, v in emb.items():
        if s in emb_ok:
            emb_classes[v["asset_class"]].append(s)
    res["asset_embeddings"] = {
        "rows": len(emb_rows),
        "n_v3": sum(1 for v in emb.values() if v["v3"]),
        "n_fresh": sum(1 for v in emb.values() if v["fresh"]),
        "n_v3_and_fresh": len(emb_ok),
        "asset_class_breakdown": {k: len(v) for k, v in sorted(emb_classes.items())},
        "crypto_symbols": sorted(s for k, v in emb_classes.items()
                                 if k not in ("US Equity", "US Bond", "Commodity", "FX")
                                 for s in v),
        "max_computed_at": max((v["computed_at"] for v in emb.values() if v["computed_at"]), default=None),
        "stale_symbols": sorted(s for s, v in emb.items() if not (v["v3"] and v["fresh"])),
    }

    # 2b. asset_flow_daily
    cr, body = q("asset_flow_daily", "select=d&order=d.desc&limit=1")
    flow_max_d = json.loads(body)[0]["d"]
    flow_fresh_cut = (dt.date.fromisoformat(flow_max_d) - dt.timedelta(days=FRESH_DAYS)).isoformat()
    flow_latest = page_all("asset_flow_daily",
                           "select=symbol,d&d=eq." + flow_max_d + "&vec=not.is.null", "symbol.asc")
    flow_latest_syms = {r["symbol"] for r in flow_latest}
    cr, body = q("asset_flow_daily", "select=symbol&d=eq." + flow_max_d + "&limit=1", count=True)
    flow_rows_latest_day = cr
    cr_all, _ = q("asset_flow_daily", "select=symbol&limit=1", count=True)
    flow_rows_total = cr_all
    # 逐币取「该币自己最新的一行」——flow 表每天只更新几十个币,用全表 max_d 当分母会低估
    flow_by_sym = {}
    for s in syms:
        cr, body = q("asset_flow_daily",
                     "select=symbol,d,vec&symbol=eq." + s + "&order=d.desc&limit=1")
        if body.startswith("ERR"):
            continue
        rows = json.loads(body)
        if rows:
            r = rows[0]
            flow_by_sym[s] = {
                "d": r["d"],
                "vec": r.get("vec") not in (None, "", "null"),
                "stale_days": (dt.date.fromisoformat(flow_max_d) - dt.date.fromisoformat(r["d"])).days,
            }
    flow_ok = {s for s, v in flow_by_sym.items() if v["vec"]}
    flow_ok_fresh = {s for s, v in flow_by_sym.items() if v["vec"] and v["stale_days"] <= FRESH_DAYS}
    res["asset_flow_daily"] = {
        "max_d": flow_max_d, "rows_total": flow_rows_total, "rows_on_latest_day": flow_rows_latest_day,
        "n_symbols_with_vec_on_latest_day": len(flow_latest_syms),
        "fresh_cut": flow_fresh_cut,
        "n_ticket_symbols_present": len(flow_by_sym),
        "n_ticket_symbols_with_vec": len(flow_ok),
        "n_ticket_symbols_with_vec_fresh7d": len(flow_ok_fresh),
        "median_stale_days": sorted(v["stale_days"] for v in flow_by_sym.values())[len(flow_by_sym) // 2]
        if flow_by_sym else None,
        "ticket_symbols_no_vec": sorted(s for s, v in flow_by_sym.items() if not v["vec"]),
        "ticket_symbols_absent": sorted(s for s in syms if s not in flow_by_sym),
    }

    # 2c. cis_official_daily
    cis_rows = page_all("cis_official_daily", "select=symbol,d,cis_score,grade,signal", "symbol.asc,d.asc")
    cis_latest = {}
    for r in cis_rows:
        cur = cis_latest.get(r["symbol"])
        if cur is None or r["d"] > cur["d"]:
            cis_latest[r["symbol"]] = r
    cis_max_d = max((r["d"] for r in cis_rows), default=None)
    cis_ok = {s for s, r in cis_latest.items() if r.get("cis_score") is not None}
    res["cis_official_daily"] = {
        "rows": len(cis_rows), "n_symbols": len(cis_latest), "max_d": cis_max_d,
        "n_symbols_with_score": len(cis_ok),
        "grades": sorted({r.get("grade") for r in cis_latest.values() if r.get("grade")}),
    }

    # ── 3. 覆盖:三种权重 ───────────────────────────────────────────────────────────────────
    tickets_by_sym = defaultdict(list)
    for t in per_ticket:
        tickets_by_sym[t["symbol"]].append(t)

    rows_out = []
    for s in syms:
        ts = tickets_by_sym[s]
        pnl_abs = sum(abs(t["pnl_usd"]) for t in ts if t["pnl_usd"] is not None)
        pnl_net = sum(t["pnl_usd"] for t in ts if t["pnl_usd"] is not None)
        rows_out.append({
            "symbol": s,
            "n_tickets": len(ts),
            "pnl_abs_usd": round(pnl_abs, 4),
            "pnl_net_usd": round(pnl_net, 4),
            "in_asset_embeddings_v3_fresh": s in emb_ok,
            "in_asset_flow_daily_vec": s in flow_ok,
            "in_cis_official_daily": s in cis_ok,
            "um_bars": bar_span.get(s),
            "um_last_close": last_close.get(s),
        })

    def cov(pred):
        c_syms = [r for r in rows_out if pred(r)]
        n_coin = len(c_syms)
        n_tk = sum(r["n_tickets"] for r in c_syms)
        abs_pnl = sum(r["pnl_abs_usd"] for r in c_syms)
        net_pnl = sum(r["pnl_net_usd"] for r in c_syms)
        tot_abs = sum(r["pnl_abs_usd"] for r in rows_out)
        tot_net = sum(r["pnl_net_usd"] for r in rows_out)
        tot_tk = sum(r["n_tickets"] for r in rows_out)
        return {
            "n_coins": n_coin, "coins_total": len(rows_out),
            "coin_pct": round(100.0 * n_coin / max(1, len(rows_out)), 1),
            "n_tickets": n_tk, "tickets_total": tot_tk,
            "ticket_pct": round(100.0 * n_tk / max(1, tot_tk), 1),
            "abs_pnl_usd": round(abs_pnl, 2),
            "abs_pnl_total_usd": round(tot_abs, 2),
            "abs_pnl_pct": round(100.0 * abs_pnl / tot_abs, 1) if tot_abs else None,
            "net_pnl_usd": round(net_pnl, 2), "net_pnl_total_usd": round(tot_net, 2),
            "net_pnl_pct": round(100.0 * net_pnl / tot_net, 1) if tot_net else None,
        }

    res["coverage"] = {
        "asset_embeddings_v3_fresh": cov(lambda r: r["in_asset_embeddings_v3_fresh"]),
        "asset_flow_daily_vec": cov(lambda r: r["in_asset_flow_daily_vec"]),
        "cis_official_daily": cov(lambda r: r["in_cis_official_daily"]),
        "all_three": cov(lambda r: r["in_asset_embeddings_v3_fresh"] and r["in_asset_flow_daily_vec"]
                         and r["in_cis_official_daily"]),
        "any_one": cov(lambda r: r["in_asset_embeddings_v3_fresh"] or r["in_asset_flow_daily_vec"]
                        or r["in_cis_official_daily"]),
        "none_of_three": cov(lambda r: not (r["in_asset_embeddings_v3_fresh"] or r["in_asset_flow_daily_vec"]
                                            or r["in_cis_official_daily"])),
    }
    res["per_coin"] = rows_out

    # ── 4. 最小方案:只用库里已有的数据,能对多少票源币算哪些维度 ────────────────────────────
    mcap_syms = set()
    mcap_last = {}
    px_hist = defaultdict(list)
    for ch in chunks(syms, CHUNK):
        rows = page_all("asset_mcap_daily",
                        "select=symbol,d,price,mcap,volume&symbol=in." + in_list(ch)
                        + "&d=gte." + (NOW.date() - dt.timedelta(days=PRICE_HIST_DAYS)).isoformat(),
                        "symbol.asc,d.asc")
        for r in rows:
            mcap_syms.add(r["symbol"])
            mcap_last[r["symbol"]] = r["d"]
            if r.get("price") is not None:
                px_hist[r["symbol"]].append((r["d"], float(r["price"])))
    ohlcv_syms = set()
    ohlcv_last = {}
    for ch in chunks(syms, CHUNK):
        rows = page_all("ohlcv_daily",
                        "select=symbol,trade_date,close,source&symbol=in." + in_list(ch)
                        + "&trade_date=gte." + (NOW.date() - dt.timedelta(days=PRICE_HIST_DAYS)).isoformat(),
                        "symbol.asc,trade_date.asc")
        for r in rows:
            ohlcv_syms.add(r["symbol"])
            ohlcv_last[r["symbol"]] = r["trade_date"]
    fund_syms = set()
    fund_last = {}
    fund_cut = (NOW - dt.timedelta(days=FRESH_DAYS)).date().isoformat()
    for ch in chunks(syms, CHUNK):
        rows = page_all("funding_history",
                        "select=symbol,funding_time,funding_rate&symbol=in." + in_list(ch)
                        + "&funding_time=gte." + fund_cut,
                        "symbol.asc,funding_time.asc")
        for r in rows:
            fund_syms.add(r["symbol"])
            fund_last[r["symbol"]] = r["funding_time"]

    def latest_row(table, order_col, sel, sym):
        cr, body = q(table, "select=" + sel + "&symbol=eq." + sym + "&order=" + order_col + ".desc&limit=1")
        if body.startswith("ERR"):
            return None
        rows = json.loads(body)
        return rows[0] if rows else None

    def row_count(table, sym):
        cr, body = q(table, "select=d&symbol=eq." + sym + "&limit=1", count=True)
        try:
            return int(str(cr).split("/")[-1])
        except Exception:  # noqa: BLE001
            return 0

    # 窗口切分只看得到 60 天内的行;窗口外的币要逐币问一次「你最后一行是什么时候」
    for s in syms:
        if s not in mcap_syms:
            r = latest_row("asset_mcap_daily", "d", "symbol,d,mcap,price,volume", s)
            if r:
                mcap_syms.add(s)
                mcap_last[s] = r["d"]
        if s not in ohlcv_syms:
            r = latest_row("ohlcv_daily", "trade_date", "symbol,trade_date,close,source", s)
            if r:
                ohlcv_syms.add(s)
                ohlcv_last[s] = r["trade_date"]
        if s not in fund_syms:
            r = latest_row("funding_history", "funding_time", "symbol,funding_time,funding_rate", s)
            if r:
                fund_syms.add(s)
                fund_last[s] = r["funding_time"]
    # 每币历史深度(count=exact,不用窗口切片)
    mcap_hist = {s: row_count("asset_mcap_daily", s) for s in syms}
    ohlcv_hist = {s: row_count("ohlcv_daily", s) for s in syms}

    # 每币可测维度(严格按 embedder 的输入)。两个场景:
    #   A = 只用 Supabase 库(零新抓取);B = 库 + Mac 数据根永续日线面板(也不新建抓取器)
    dim_plan = {}
    for s in syms:
        panel = bar_span.get(s)
        n_panel = panel[2] if panel else 0
        n_db_px = max(ohlcv_hist.get(s, 0), mcap_hist.get(s, 0))
        can_db, can_ab, reasons = set(), set(), []
        # [7][8][9] 涨跌 —— 需要 ≥31 根日线
        if n_db_px >= 31:
            can_db.update([7, 8, 9])
        if n_panel >= 31:
            can_ab.update([7, 8, 9])
        if not can_ab:
            reasons.append("[7][8][9] 无 ≥31 根日线")
        # [13] ATH 距离 —— 用该币自己的历史最高价做代理
        if mcap_hist.get(s, 0) >= 31:
            can_db.add(13)
        if n_panel >= 31:
            can_ab.add(13)
        # [11] 资金费(库里有的最后一条 funding)
        if s in fund_syms or s in flow_ok:
            can_db.add(11)
            can_ab.add(11)
        else:
            reasons.append("[11] 库里无资金费记录")
        # [16] 资产类别(加密默认 Crypto=0.8)/[17] 宏观 regime(全局量)—— 都不依赖 CIS
        can_db.update([16, 17])
        can_ab.update([16, 17])
        # [6][10] 市值 / 量市值比
        if s in mcap_syms:
            can_db.update([6, 10])
            can_ab.update([6, 10])
        else:
            reasons.append("[6][10] 无 asset_mcap_daily 市值")
        # [12] OI/市值 —— 库里没有 OI 存量(只有 flow.doi7 的 ΔOI)
        reasons.append("[12] 库里无 OI 存量(只有 flow.doi7 的 ΔOI);若把已有 CoinGecko "
                       "derivatives 抓取器的 universe 扩到票源币,[12] 才可算")
        dim_plan[s] = {
            "n_db": len(can_db), "dims_db": sorted(can_db),
            "n_ab": len(can_ab), "dims_ab": sorted(can_ab),
            "n_ab_plus_oi": len(can_ab) + 1,
            "reasons": reasons,
            "reaches_floor_db": len(can_db) >= MIN_MEASURED_DIMS,
            "reaches_floor_ab": len(can_ab) >= MIN_MEASURED_DIMS,
            "reaches_floor_ab_plus_oi": (len(can_ab) + 1) >= MIN_MEASURED_DIMS,
            "panel_bars": n_panel, "db_mcap_rows": mcap_hist.get(s, 0),
            "db_ohlcv_rows": ohlcv_hist.get(s, 0),
        }

    dist_db, dist_ab = defaultdict(int), defaultdict(int)
    for v in dim_plan.values():
        dist_db[v["n_db"]] += 1
        dist_ab[v["n_ab"]] += 1
    res["minimal_plan"] = {
        "write_floor_dims": MIN_MEASURED_DIMS,
        "non_cis_dims": NON_CIS_DIMS,
        "n_cis_dependent_dims": 27 - len(NON_CIS_DIMS),
        "n_symbols": len(syms),
        "n_reaching_floor_db_only": sum(1 for v in dim_plan.values() if v["reaches_floor_db"]),
        "n_reaching_floor_db_plus_panel": sum(1 for v in dim_plan.values() if v["reaches_floor_ab"]),
        "n_reaching_floor_db_plus_panel_plus_oi": sum(
            1 for v in dim_plan.values() if v["reaches_floor_ab_plus_oi"]),
        "measured_dim_histogram_db_only": {str(k): v for k, v in sorted(dist_db.items())},
        "measured_dim_histogram_db_plus_panel": {str(k): v for k, v in sorted(dist_ab.items())},
        "sources": {
            "um_daily(永续日线,Mac 数据根)": {"n_symbols": sum(1 for s in syms if s in bars)},
            "ohlcv_daily(DB)": {"n_symbols": len(ohlcv_syms & set(syms)),
                                "latest_date_max": max(ohlcv_last.values()) if ohlcv_last else None},
            "asset_mcap_daily": {"n_symbols": len(mcap_syms & set(syms)),
                                 "latest_date_max": max(mcap_last.values()) if mcap_last else None},
            "funding_history(任意时刻)": {"n_symbols": len(fund_syms & set(syms)),
                                         "latest_max": max(fund_last.values()) if fund_last else None},
            "asset_flow_daily(vec)": {"n_symbols": len(flow_ok)},
        },
        "per_symbol": dim_plan,
    }

    res["dims"] = [list(d) for d in DIMS]

    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    print("wrote", OUT_JSON)
    print(json.dumps({k: res[k] for k in ("ticket_source", "asset_embeddings", "asset_flow_daily",
                                          "cis_official_daily", "coverage")},
                     ensure_ascii=False, indent=1)[:4000])
    print(json.dumps(res["minimal_plan"]["sources"], ensure_ascii=False))
    print("floor reached db-only:", res["minimal_plan"]["n_reaching_floor_db_only"],
          "db+panel:", res["minimal_plan"]["n_reaching_floor_db_plus_panel"],
          "db+panel+OI:", res["minimal_plan"]["n_reaching_floor_db_plus_panel_plus_oi"],
          "/", len(syms))
    print("hist db-only:", res["minimal_plan"]["measured_dim_histogram_db_only"])
    print("hist db+panel:", res["minimal_plan"]["measured_dim_histogram_db_plus_panel"])


if __name__ == "__main__":
    main()
