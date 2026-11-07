#!/usr/bin/env python3
"""T-279 / S-758 —— S-740 复现:用补全后的代号映射重跑「永续上线 = 做空供给冲击」。

**只算、不改代码、不入库。** 判据一字不改照 REFUTATION_LEDGER §S-740(2026-11-06 06:55 UTC 预注册):

  样本: events kind='perp_listing'(Binance USDT 永续),代币在上线日之前 >= 60 天已有
        binance_hist 现货日线;d = 事件 ts 的 UTC 日(库里没有上线日字段);
        价 = binance_hist 现货收盘;结果 = d+30 / d+60 相对 BTC 的对数超额;窗口 2020-01 ->。
  判据(全满足才 OK):(a) 30 天超额中位数 <= -3% 且均值 < 0;
        (b) 零信号对照:同代币、同年份随机日期(apparatus.random_dates_like,1,000 次,种子 740),
           实际中位数 <= 对照 5 分位;
        (c) 两段(2020-01->2022-12 / 2023-01->)同号;
        (d) 去掉上线前 30 天已涨超 50% 的那批后仍同号。
  副(不判):60 天;按上线前市值三分位;上线后前 7 天资金费均值与超额的 Spearman。

**唯一的改动(S-758 写死):** 事件 -> 代币映射换成 T-277 补全后的解析
(`t277_rv2_perp_listing.py` 的 `extract_tickers_v2` + `_norm_tok`,原样搬过来),
对全部公告逐条重新解析、逐条落文件(t279_event_symbol_map.json),**先于取价格**。
同时保留 S-740 原映射作对照(期望复现 n=46 / 30 天中位 -17.42%),并把
「旧解析器能映射的那批」与「新增的那批」分开报中位数。

零分布/分位/随机日期一律用 src/data/evaluation/apparatus.py。
用法:python3 docs/research/t279_replication.py
     (写 t279_results.json + t279_event_symbol_map.json + T-279_perp_listing_replication.md)
"""

from __future__ import annotations

import bisect
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import (  # noqa: E402
    null_distribution,
    percentile_of,
    price_on_or_after,
    random_dates_like,
)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
SESSION = requests.Session()

RESEARCH = Path("/Volumes/CometCloudAI/cometcloud-local/research")
CACHE = RESEARCH / "t279_cache"
CACHE.mkdir(parents=True, exist_ok=True)
SEED_CACHE = RESEARCH / "t262_cache"   # T-262 的价格缓存:只读种子(价格源不变,只是复用)
OUT = Path(__file__).resolve().parent

HORIZONS = (30, 60)
WINDOW_START = "2020-01-01"
PX_START = "2019-11-01"
SEED = 740
N_NULL = 1000
EXCLUDE_DAYS = 30          # 卡:随机日期不在上线日前后 30 天内
PRE_MOVE_THRESHOLD = 0.50  # (d):上线前 30 天已涨超 50%
MAX_GAP = 5                # 价格对齐容忍(天)

# ── 标题规则:哪些 perp_listing 公告真的是「上线一个 USDT 永续」 ─────────────────
EXCLUDE_RULES = [
    ("copy_trading_add", re.compile(r"Copy Trading Adds")),
    ("tradfi_equity_index", re.compile(r"TradFi|Equity Perpetual|Index Perpetual")),
    ("coin_margined", re.compile(r"[Cc]oin-[Mm]argined")),
    ("busd_margined", re.compile(r"BUSD-Margined")),
    ("leverage_tier_update", re.compile(r"Leverage & Margin Tiers|Margin Tiers|margin tiers")),
    ("convert_to_standard", re.compile(r"\bConvert\b")),
    ("relaunch", re.compile(r"Relaunch")),
    ("roundup", re.compile(r"New Listings This Week")),
    ("pre_ipo", re.compile(r"Pre-IPO")),
    ("spot_listing", re.compile(r"Innovation Zone")),
]
INCLUDE_RULES = [
    ("not_a_launch", re.compile(r"(?i)will launch|launches|will list")),
    ("not_perpetual", re.compile(r"(?i)perpetual contract")),
]

# ── 公告标题里的代币代码 ────────────────────────────────────────────────────
# events.symbols 在 818 条里有 453 条是空的(抓取时只认 FOOUSDT 这种写法,认不出 ETH/USDT
# 或标题里夹在两个 <TICKET> 之间的情形)。代码就在标题里,自己解析出来。
TICKET_RX = re.compile(r"\b([A-Z0-9]{2,15})(?:USDT|USDC|BUSD)\b")
TICKET_SLASH_RX = re.compile(r"\b([A-Z0-9]{2,15})/USDT\b")
TICKET_STOPWORDS = {"USD", "USDT", "USDC", "BUSD", "PERPETUAL", "CONTRACT", "CONTRACTS",
                    "MARGINED", "MARGIN", "TRADING", "LEVERAGE", "FUTURES", "MULTIPLE"}


# ── 代号解析 v2(T-277 的那套,原样搬;S-758 指定) ────────────────────────────
# S-740 的解析器(extract_tickers)只认「FOOUSDT / ETH/USDT」两种写法,818 条公告里
# 漏了 571 条 —— 因为绝大多数公告写的是「USDT-Margined APE」「USDⓈ-M ARB」
# 「Launch a USDT-Margined Perpetual Contract … for 1INCH」。漏解析 =>「没上过永续」是假的。
V2_STOPWORDS = {"USD", "USDT", "USDC", "BUSD", "PERPETUAL", "PERPETUALS", "CONTRACT", "CONTRACTS",
                 "MARGINED", "MARGIN", "MARGINS", "TRADING", "LEVERAGE", "FUTURES", "MULTIPLE",
                 "CROSS", "ISOLATED", "BINANCE", "QUARTERLY", "COIN", "M", "ENABLE", "ENABLED",
                 "AND", "WITH", "UP", "TO", "LAUNCH", "LAUNCHES", "WILL", "TICKER", "PAIRS", "PAIR",
                 "AGAINST", "SETTLE", "SETTLEMENT", "CONTRAC", "FUTUR", "THE", "FOR", "A", "AN"}
RX_TOKEN = re.compile(r"\b([A-Z0-9]{1,15})(?:USDT|USDC|BUSD)\b")
RX_SLASH = re.compile(r"\b([A-Z0-9]{1,15})/USDT\b")
RX_AFTER = re.compile(r"(?:USDT|USDC|BUSD|Coin)[- ]?Margined\s+([A-Z0-9]{1,15})\b")
RX_BEFORE = re.compile(r"\b([A-Z0-9]{1,15})\s+(?:USDT|USDC|BUSD|Coin)[- ]?Margined\b")
RX_USDM_AFTER = re.compile(r"USDⓈ-?M(?:argined)?\s+([A-Z0-9]{1,15})\b")
RX_USDM_BEFORE = re.compile(r"\b([A-Z0-9]{1,15})\s+USDⓈ-?M")
RX_FOR = re.compile(r"\bfor\s+([A-Z0-9]{1,15})\b")
RX_LIST = re.compile(r"(?:USDT|USDC|BUSD|Coin)[- ]?Margined\s+([A-Z0-9 ,&]{2,80}?)\s+Perpetual", re.I)
RX_LIST_BEFORE = re.compile(r"([A-Z0-9][A-Z0-9 ,&]{1,80}?)\s+(?:USDT|USDC|BUSD|Coin)[- ]?Margined")
RX_QUARTERLY = re.compile(r"\b([A-Z0-9]{1,15})USD\s+Quarterly\b", re.I)


def _norm_tok(t: str) -> str | None:
    t = (t or "").strip()
    for suf in ("USDT", "USDC", "BUSD"):
        if t.endswith(suf) and len(t) > len(suf):
            t = t[: -len(suf)]
    if t.endswith("USD") and len(t) > 3:
        t = t[:-3]
    if len(t) < 2 or t in V2_STOPWORDS or t.isdigit():
        return None
    if not re.fullmatch(r"[A-Z0-9]+", t):
        return None
    return t


def extract_tickers_v2(title: str) -> list[str]:
    """从公告标题解析代币代码(补齐 S-740 解析器漏掉的写法)。顺序去重。"""
    t = title or ""
    out: list[str] = []

    def add(x):
        n = _norm_tok(x)
        if n and n not in out:
            out.append(n)

    for m in RX_TOKEN.finditer(t):
        add(m.group(1))
    for m in RX_SLASH.finditer(t):
        add(m.group(1))
    for rx in (RX_AFTER, RX_USDM_AFTER, RX_BEFORE, RX_USDM_BEFORE):
        for m in rx.finditer(t):
            add(m.group(1))
    for m in RX_QUARTERLY.finditer(t):
        add(m.group(1))
    for m in RX_LIST.finditer(t):
        for piece in re.split(r",|&|\band\b", m.group(1)):
            add(piece.strip())
    for m in RX_LIST_BEFORE.finditer(t):
        for piece in re.split(r",|&|\band\b", m.group(1)):
            add(piece.strip())
    for m in RX_FOR.finditer(t):
        add(m.group(1))
    return out


def extract_tickers(title: str) -> list[str]:
    """从公告标题里解析代币代码(FOOUSDT → FOO;ETH/USDT → ETH)。顺序去重。"""
    out: list[str] = []
    for rx in (TICKET_RX, TICKET_SLASH_RX):
        for m in rx.finditer(title or ""):
            t = m.group(1)
            if t in TICKET_STOPWORDS:
                continue
            if t not in out:
                out.append(t)
    return out



def classify(title: str) -> tuple[str, str | None]:
    t = title or ""
    for name, rx in EXCLUDE_RULES:
        if rx.search(t):
            return "drop", name
    for name, rx in INCLUDE_RULES:
        if not rx.search(t):
            return "drop", name
    return "keep", None


# ── 数据层 ──────────────────────────────────────────────────────────────────
def pull(table: str, query: str, step: int = 1000) -> list[dict]:
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        r = SESSION.get(f"{URL}/rest/v1/{table}?{query}", headers={**H, "Prefer": "count=exact"},
                        params={"limit": step, "offset": off}, timeout=300)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{table}: HTTP {r.status_code} {r.text[:200]}")
        body = r.json()
        rows.extend(body)
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def cached_pull(name: str, table: str, query: str) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows", flush=True)
        return rows
    rows = pull(table, query)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows", flush=True)
    return rows


# ── 价格查找(bisect 版,与 apparatus.price_on_or_after 对拍过) ────────────────
def poa_fast(dates: list[str], closes: list[float], target: str, max_gap: int = MAX_GAP) -> float | None:
    """dates 已按升序;返回 target 当天或之后 max_gap 天内的第一个有效收盘。"""
    i = bisect.bisect_left(dates, target)
    if i >= len(dates):
        return None
    gap = (date.fromisoformat(dates[i]) - date.fromisoformat(target)).days
    if gap > max_gap:
        return None
    c = closes[i]
    if c is None or not math.isfinite(c) or c <= 0:
        return None
    return float(c)


def on_or_before(dates: list[str], closes: list[float], target: str) -> float | None:
    i = bisect.bisect_right(dates, target)
    if i == 0:
        return None
    c = closes[i - 1]
    if c is None or not math.isfinite(c) or c <= 0:
        return None
    return float(c)


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    ax, ay = np.asarray(x, float), np.asarray(y, float)
    if ax.std() == 0 or ay.std() == 0:
        return None
    rx = np.argsort(np.argsort(ax)).astype(float)
    ry = np.argsort(np.argsort(ay)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def log_excess(entry, exit_, b_entry, b_exit):
    if not all(v and v > 0 and math.isfinite(v) for v in (entry, exit_, b_entry, b_exit)):
        return None
    return math.log(exit_ / entry) - math.log(b_exit / b_entry)


# ════════════════════════════════════════════════════════════════════════════
def main() -> None:
    res: dict = {"task": "T-279", "ledger": "S-758", "seed": SEED, "n_null": N_NULL,
                 "generated_at": datetime.utcnow().isoformat() + "Z"}

    # ── ① 事件库 ────────────────────────────────────────────────────────────
    ev_path = CACHE / "events.json"
    if ev_path.exists():
        events = json.loads(ev_path.read_text())
    else:
        events = pull("events", "kind=eq.perp_listing&select=id,ts,symbols,title,source,payload&order=ts.asc")
        ev_path.write_text(json.dumps(events))
    events = [e for e in events if (e.get("source") or "binance") == "binance"]
    print(f"perp_listing 总数: {len(events)}", flush=True)

    src_title_match = sum(
        1 for e in events
        if (m := re.search(r"\((\d{4}-\d{2}-\d{2})\)", e.get("title") or ""))
        and m.group(1) == str(e["ts"])[:10])
    src_payload_field = sum(
        1 for e in events
        if any(k in (e.get("payload") or {}) for k in ("launch_date", "listing_date", "date", "launch_date_utc")))
    res["listing_day_source"] = {
        "events_total": len(events),
        "payload_has_launch_date_field": src_payload_field,
        "title_paren_date_equals_ts": src_title_match,
        "used": "事件 ts 的 UTC 日(库里没有公告上线日字段)",
    }

    kept, drop_counter, drop_examples = [], Counter(), defaultdict(list)
    for e in events:
        dec, reason = classify(e.get("title") or "")
        if dec == "drop":
            drop_counter[reason] += 1
            if len(drop_examples[reason]) < 3:
                drop_examples[reason].append((e.get("title") or "")[:95])
            continue
        kept.append(e)
    res["title_filter"] = {"kept_announcements": len(kept), "dropped": dict(drop_counter),
                           "drop_examples": {k: v for k, v in drop_examples.items()}}
    print(f"标题过滤: {len(events)} → {len(kept)} 条公告", flush=True)

    # ── 逐条重新解析:全部公告(含被标题规则丢掉的)都落文件,先于取价格 ────────
    keep_ids = {e["id"] for e in kept}
    drop_reason = {}
    for e in events:
        dec, reason = classify(e.get("title") or "")
        if dec == "drop":
            drop_reason[e["id"]] = reason
    map_rows, token_events, token_events_old, prov, prov_old = [], [], [], Counter(), Counter()
    for e in events:
        d = str(e["ts"])[:10]
        title = e.get("title") or ""
        field = list(e.get("symbols") or [])
        old_parse = extract_tickers(title)
        new_parse = extract_tickers_v2(title)
        old_syms = list(field) if field else list(old_parse)
        new_syms = list(field) if field else list(new_parse)
        union_syms = []
        for x in list(field) + list(new_parse):
            if x not in union_syms:
                union_syms.append(x)
        kept_by_rule = e["id"] in keep_ids
        map_rows.append({
            "id": e["id"], "d": d, "kept_by_title_rule": kept_by_rule,
            "drop_reason": drop_reason.get(e["id"]),
            "symbols_field": field,
            "old_parse": old_parse, "new_parse": new_parse,
            "old_syms": old_syms, "new_syms": new_syms, "union_syms": union_syms,
            "origin": ("old" if set(old_syms) == set(new_syms) else "new"),
            "title": title[:160],
        })
        if not kept_by_rule:
            continue
        for sym in new_syms:
            origin = "old" if sym in old_syms else "new"
            token_events.append({"sym": sym, "d": d, "title": title, "id": e["id"],
                                 "src": "symbols_field" if field else "title_v2",
                                 "origin": origin})
            prov["symbols_field" if field else "title_v2"] += 1
            prov[f"origin_{origin}"] += 1
        for sym in old_syms:
            token_events_old.append({"sym": sym, "d": d, "title": title, "id": e["id"],
                                     "src": "symbols_field" if field else "title_parsed"})
            prov_old["symbols_field" if field else "title_parsed"] += 1
    res["mapping"] = {
        "announcements_total": len(events),
        "announcements_mapped_old": sum(1 for r in map_rows if r["old_syms"]),
        "announcements_mapped_new": sum(1 for r in map_rows if r["new_syms"]),
        "announcements_unmapped_old": sum(1 for r in map_rows if not r["old_syms"]),
        "announcements_unmapped_new": sum(1 for r in map_rows if not r["new_syms"]),
        "announcements_mapped_only_by_v2": sum(1 for r in map_rows
                                               if r["new_syms"] and not r["old_syms"]),
        "old_parse_hit": sum(1 for r in map_rows if r["old_parse"]),
        "new_parse_hit": sum(1 for r in map_rows if r["new_parse"]),
        "symbols_field_present": sum(1 for r in map_rows if r["symbols_field"]),
        "distinct_symbols_old": len({x for r in map_rows for x in r["old_syms"]}),
        "distinct_symbols_new": len({x for r in map_rows for x in r["new_syms"]}),
        "mapping_file": str(OUT / "t279_event_symbol_map.json"),
        "note": "逐条:旧解析(S-740)vs 新解析(T-277 v2);origin=old 表示旧解析器已经能映射到该代号",
    }
    (OUT / "t279_event_symbol_map.json").write_text(
        json.dumps(map_rows, ensure_ascii=False, indent=1, default=str))
    print(f"映射落盘 {OUT / 't279_event_symbol_map.json'}: {len(map_rows)} 条公告 "
          f"(旧能映射 {res['mapping']['announcements_mapped_old']} / 新 {res['mapping']['announcements_mapped_new']})",
          flush=True)
    res["expansion"] = {"announcements_kept": len(kept), "token_events_new": len(token_events),
                        "token_events_old_mapping": len(token_events_old),
                        "ticker_provenance_new": dict(prov),
                        "ticker_provenance_old": dict(prov_old)}
    print(f"展开成 {len(token_events)} 个(代币, 上线日)事件(新映射;旧映射 {len(token_events_old)})", flush=True)

    # ── ② 现货价(binance_hist) ─────────────────────────────────────────────
    rows = cached_pull("bhs_px", "ohlcv_daily",
                       "source=eq.binance_hist&select=symbol,trade_date,close"
                       f"&trade_date=gte.{PX_START}&order=symbol.asc,trade_date.asc")
    by_sym: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        try:
            by_sym[r["symbol"]].append((r["trade_date"], float(r["close"])))
        except (TypeError, ValueError, KeyError):
            continue
    px: dict[str, tuple[list[str], list[float]]] = {}
    for s, ser in by_sym.items():
        ser.sort()
        px[s] = ([d for d, _ in ser], [c for _, c in ser])
    print(f"现货价: {len(px)} 个符号 / {len(rows)} 行", flush=True)

    btc_dates, btc_closes = px.get("BTC", ([], []))
    if not btc_dates:
        sys.exit("BTC 现货价缺失,中止")

    # ── ③ 样本筛选(照预注册) ───────────────────────────────────────────────
    def make_sample(evs):
        smp, fn = [], Counter()
        for t in evs:
            s, d = t["sym"], t["d"]
            if d < WINDOW_START:
                fn["window_2020"] += 1
                continue
            if s not in px:
                if s.startswith("1000") and s[4:] in px:
                    s = s[4:]
                    fn["symbol_1000_alias"] += 1
                else:
                    fn["no_spot_data"] += 1
                    continue
            if len([x for x in px[s][0] if x < d]) < 60:
                fn["spot_lt_60d"] += 1
                continue
            fn["kept"] += 1
            t = dict(t)
            t["sym"] = s
            smp.append(t)
        return smp, fn

    sample, funnel = make_sample(token_events)
    sample_old, funnel_old = make_sample(token_events_old)
    res["funnel"] = dict(funnel)
    res["funnel_old_mapping"] = dict(funnel_old)
    res["sample_by_year"] = dict(sorted(Counter(t["d"][:4] for t in sample).items()))
    res["sample_by_year_old_mapping"] = dict(sorted(Counter(t["d"][:4] for t in sample_old).items()))
    print(f"样本(新映射): {len(sample)} 条(漏斗 {dict(funnel)})", flush=True)
    print(f"样本(旧映射对照): {len(sample_old)} 条(漏斗 {dict(funnel_old)})", flush=True)

    # ── 上线日交叉核对:永续第一根数据日(observable perp start) ─────────────
    lc_path = CACHE / "perp_launch_dates.json"
    if lc_path.exists():
        lc_raw = json.loads(lc_path.read_text())
    else:
        lc_raw = {}
        for t in sample:
            s = t["sym"]
            if s in lc_raw:
                continue
            q1 = f"select=d&symbol=eq.{s}&order=d.asc&limit=1"
            q2 = f"select=d&symbol=eq.{s}&order=d.asc&limit=1"
            bv = pull("perp_bv_daily", q1)
            fu0 = pull("v_funding_daily", q2)
            lc_raw[s] = {"perp_bv_first": (bv[0]["d"] if bv else None),
                         "funding_first": (fu0[0]["d"] if fu0 else None)}
        lc_path.write_text(json.dumps(lc_raw))
    diffs, rows_lc = [], []
    for t in sample:
        info = lc_raw.get(t["sym"], {})
        bv_first = info.get("perp_bv_first")
        rows_lc.append({"sym": t["sym"], "d": t["d"], "perp_bv_first": bv_first,
                        "funding_first": info.get("funding_first")})
        if bv_first:
            diffs.append((date.fromisoformat(bv_first) - date.fromisoformat(t["d"])).days)
    res["listing_day_crosscheck"] = {
        "perp_bv_first_minus_d": {"n": len(diffs),
                                  "median_days": (float(np.median(diffs)) if diffs else None),
                                  "mean_days": (float(np.mean(diffs)) if diffs else None),
                                  "same_day": sum(1 for x in diffs if x == 0),
                                  "before_d": sum(1 for x in diffs if x < 0),
                                  "after_d": sum(1 for x in diffs if x > 0),
                                  "min": (min(diffs) if diffs else None), "max": (max(diffs) if diffs else None)},
        "rows": rows_lc,
    }

    # ── 对拍:poa_fast vs apparatus.price_on_or_after ───────────────────────
    rng_chk = np.random.default_rng(1)
    mism = 0
    checked = 0
    for t in sample[:60]:
        s = t["sym"]
        dates, closes = px[s]
        if len(dates) < 5:
            continue
        for _ in range(40):
            tgt = dates[int(rng_chk.integers(0, len(dates)))]
            a = price_on_or_after(dates, closes, tgt, max_gap_days=MAX_GAP)
            b = poa_fast(dates, closes, tgt)
            checked += 1
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
                mism += 1
    res["poa_selfcheck"] = {"pairs_checked": checked, "mismatches": mism}
    print(f"poa_fast 对拍: {checked} 对 / 不一致 {mism}", flush=True)

    # ── ④ 每个事件的超额 ───────────────────────────────────────────────────
    def build_rows(evs, entry_offset: int, use_apparatus: bool) -> list[dict]:
        poa = (lambda ds, cs, t: price_on_or_after(ds, cs, t, max_gap_days=MAX_GAP)) if use_apparatus else poa_fast
        out = []
        for t in evs:
            s, d = t["sym"], t["d"]
            dates, closes = px[s]
            e_day = (date.fromisoformat(d) + timedelta(days=entry_offset)).isoformat()
            entry = poa(dates, closes, e_day)
            b_entry = poa(btc_dates, btc_closes, e_day)
            if entry is None or b_entry is None:
                continue
            row = {"sym": s, "d": d, "entry_day": e_day, "entry": entry,
                   "origin": t.get("origin", "old")}
            ok = True
            for h in HORIZONS:
                x_day = (date.fromisoformat(e_day) + timedelta(days=h)).isoformat()
                x = poa(dates, closes, x_day)
                bx = poa(btc_dates, btc_closes, x_day)
                ex = log_excess(entry, x, b_entry, bx) if (x is not None and bx is not None) else None
                row[f"ex{h}"] = ex
                if ex is None:
                    ok = False
            if not ok:
                continue
            c_prev = on_or_before(dates, closes, (date.fromisoformat(d) - timedelta(days=1)).isoformat())
            c_prev30 = on_or_before(dates, closes, (date.fromisoformat(d) - timedelta(days=31)).isoformat())
            row["pre30_ret"] = (c_prev / c_prev30 - 1.0) if (c_prev and c_prev30) else None
            out.append(row)
        return out

    rows0 = build_rows(sample, 0, True)   # 主口径:apparatus 原函数
    rows1 = build_rows(sample, 1, True)   # S-665:挪一天
    rows0_old = build_rows(sample_old, 0, True)   # 对照:S-740 原映射(期望 n=46 / -17.42%)
    rows1_old = build_rows(sample_old, 1, True)
    res["n_with_excess"] = {"entry_on_d": len(rows0), "entry_on_d_plus_1": len(rows1)}

    def summarize(rs, h=30):
        v = [r[f"ex{h}"] for r in rs if r.get(f"ex{h}") is not None]
        if not v:
            return {"n": 0}
        a = np.asarray(v, float)
        return {"n": int(a.size), "median_pct": float(np.median(a) * 100), "mean_pct": float(a.mean() * 100),
                "p25_pct": float(np.percentile(a, 25) * 100), "p75_pct": float(np.percentile(a, 75) * 100),
                "min_pct": float(a.min() * 100), "max_pct": float(a.max() * 100),
                "frac_negative": float((a < 0).mean()), "frac_le_-3": float((a <= -0.03).mean())}

    res["main"] = {"entry_on_d": {"h30": summarize(rows0, 30), "h60": summarize(rows0, 60)},
                   "entry_on_d_plus_1": {"h30": summarize(rows1, 30), "h60": summarize(rows1, 60)}}

    # ── ⑤ 判据 (a)(b)(c)(d) ────────────────────────────────────────────────
    def criteria(rs, label):
        out = {"label": label}
        s30 = summarize(rs, 30)
        out["a"] = {"n": s30.get("n"), "median_pct": s30.get("median_pct"), "mean_pct": s30.get("mean_pct"),
                    "pass": bool(s30.get("median_pct") is not None and s30["median_pct"] <= -3.0
                                 and s30.get("mean_pct", 0) < 0)}
        halves = []
        for lo, hi in (("2020-01-01", "2022-12-31"), ("2023-01-01", "9999-12-31")):
            v = [r["ex30"] for r in rs if r.get("ex30") is not None and lo <= r["d"] <= hi]
            halves.append({"window": f"{lo[:7]}→{hi[:7]}", "n": len(v),
                           "median_pct": (float(np.median(v) * 100) if v else None),
                           "mean_pct": (float(np.mean(v) * 100) if v else None)})
        out["halves"] = halves
        if halves[0]["median_pct"] is not None and halves[1]["median_pct"] is not None:
            s0 = np.sign(halves[0]["median_pct"])
            s1 = np.sign(halves[1]["median_pct"])
            out["c"] = {"same_sign": bool(s0 == s1), "sign": int(s0), "half2_sign": int(s1)}
        else:
            out["c"] = {"same_sign": None, "sign": None}
        keep = [r for r in rs if r.get("pre30_ret") is not None and r["pre30_ret"] <= PRE_MOVE_THRESHOLD]
        v_all = [r["ex30"] for r in rs if r.get("ex30") is not None]
        v_keep = [r["ex30"] for r in keep if r.get("ex30") is not None]
        out["d"] = {"n_excluded": len(v_all) - len(v_keep), "n_kept": len(v_keep),
                    "median_all_pct": (float(np.median(v_all) * 100) if v_all else None),
                    "median_kept_pct": (float(np.median(v_keep) * 100) if v_keep else None),
                    "mean_kept_pct": (float(np.mean(v_keep) * 100) if v_keep else None),
                    "same_sign": (bool(np.sign(np.median(v_keep)) == np.sign(np.median(v_all)))
                                  if v_all and v_keep else None)}
        return out

    res["criteria"] = {"entry_on_d": criteria(rows0, "entry on d"),
                       "entry_on_d_plus_1": criteria(rows1, "entry on d+1")}
    # 旧映射对照:同一套价格/窗口/判据,只换映射 ⇒ 期望复现 S-740 的 n=46 / 中位 -17.42%
    res["replication_control_old_mapping"] = {
        "note": "S-740 原映射(只用 extract_tickers)走同一套价格/窗口/判据,用来验证复现链路",
        "entry_on_d": criteria(rows0_old, "entry on d"),
        "main": {"entry_on_d": {"h30": summarize(rows0_old, 30), "h60": summarize(rows0_old, 60)}},
    }
    # 新旧子集分开报(S-758 要求)
    def subset_split(rs):
        out = {}
        for tag in ("old", "new"):
            v = [r["ex30"] for r in rs if r.get("origin") == tag and r.get("ex30") is not None]
            v60 = [r["ex60"] for r in rs if r.get("origin") == tag and r.get("ex60") is not None]
            out[tag] = {"n": len(v),
                        "median_pct": (float(np.median(v) * 100) if v else None),
                        "mean_pct": (float(np.mean(v) * 100) if v else None),
                        "frac_negative": (float((np.asarray(v) < 0).mean()) if v else None),
                        "h60_median_pct": (float(np.median(v60) * 100) if v60 else None)}
        return out

    res["subset_split"] = {"entry_on_d": subset_split(rows0),
                           "entry_on_d_plus_1": subset_split(rows1)}
    print(f"新旧子集(入场 d):旧 {res['subset_split']['entry_on_d']['old']} / "
          f"新 {res['subset_split']['entry_on_d']['new']}", flush=True)

    # ── (b) 零信号对照:同代币、同年份、避开上线日前后 30 天 ────────────────
    def listing_dates_of(evs):
        ld: dict[str, set[str]] = defaultdict(set)
        for t in evs:
            ld[t["sym"]].add(t["d"])
        return ld

    listing_dates = listing_dates_of(sample)
    listing_dates_old = listing_dates_of(sample_old)

    def build_eligible(rs, h, ld_map):
        elig = {}
        for r in rs:
            s = r["sym"]
            dates, closes = px[s]
            blocked = set()
            for ld in ld_map[s]:
                base = date.fromisoformat(ld)
                for k in range(-EXCLUDE_DAYS, EXCLUDE_DAYS + 1):
                    blocked.add((base + timedelta(days=k)).isoformat())
            ok = []
            for dd in dates:
                if dd in blocked or dd < WINDOW_START:
                    continue
                x_day = (date.fromisoformat(dd) + timedelta(days=h)).isoformat()
                if poa_fast(dates, closes, x_day) is None:
                    continue
                if poa_fast(btc_dates, btc_closes, dd) is None:
                    continue
                if poa_fast(btc_dates, btc_closes, x_day) is None:
                    continue
                ok.append(dd)
            elig[s] = ok
        return elig

    def run_null(rs, h, ld_map=None):
        elig = build_eligible(rs, h, ld_map or listing_dates)
        ev_list = [(r["sym"], r["d"]) for r in rs]
        vals_actual = [r[f"ex{h}"] for r in rs if r.get(f"ex{h}") is not None]
        actual = float(np.median(vals_actual) * 100)
        n_empty = sum(1 for v in elig.values() if not v)

        def one(rng):
            picks = random_dates_like(ev_list, elig, rng)
            vals = []
            for (sym, _), (_, dd) in zip(ev_list, picks):
                if dd is None:
                    continue
                dates, closes = px[sym]
                e = poa_fast(dates, closes, dd)
                be = poa_fast(btc_dates, btc_closes, dd)
                x_day = (date.fromisoformat(dd) + timedelta(days=h)).isoformat()
                x = poa_fast(dates, closes, x_day)
                bx = poa_fast(btc_dates, btc_closes, x_day)
                ex = log_excess(e, x, be, bx)
                if ex is not None:
                    vals.append(ex)
            if not vals:
                return float("nan")
            return float(np.median(vals) * 100)

        try:
            null = null_distribution(one, N_NULL, SEED, actual=actual)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "actual_median_pct": actual}
        p05 = float(np.percentile(null, 5))
        return {"actual_median_pct": actual, "n_null": int(null.size), "null_p05_pct": p05,
                "null_p50_pct": float(np.percentile(null, 50)), "null_mean_pct": float(null.mean()),
                "percentile_of_actual": percentile_of(actual, null),
                "pass_le_p05": bool(actual <= p05),
                "tokens_without_eligible_dates": n_empty,
                "median_eligible_dates_per_token": float(np.median([len(v) for v in elig.values()]))}

    res["null_control"] = {"entry_on_d": {f"h{h}": run_null(rows0, h) for h in HORIZONS},
                           "entry_on_d_plus_1": {f"h{h}": run_null(rows1, h) for h in HORIZONS}}
    res["null_control_old_mapping"] = {"entry_on_d": {f"h{h}": run_null(rows0_old, h, listing_dates_old) for h in HORIZONS}}
    for k, v in res["null_control"]["entry_on_d"].items():
        if "null_p05_pct" in v:
            print(f"  null {k}: 实际 {v['actual_median_pct']:.2f}% vs p05 {v['null_p05_pct']:.2f}% "
                  f"(分位 {v['percentile_of_actual']:.3f})", flush=True)

    # ── 副:上线前市值三分位(逐事件窄窗口拉,不用全表) ─────────────────────
    mc: dict[str, dict[str, float]] = defaultdict(dict)
    mc_cache = CACHE / "mcap_windows.json"
    seed = SEED_CACHE / "mcap_windows.json"
    raw = json.loads(seed.read_text()) if seed.exists() else {}
    todo = {}
    for t in sample:
        s, d = t["sym"], t["d"]
        lo = (date.fromisoformat(d) - timedelta(days=12)).isoformat()
        hi = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        key = f"{s}|{lo}|{hi}"
        if key not in raw:
            todo[key] = (s, lo, hi)
    for key, (s, lo, hi) in todo.items():
        q = f"select=symbol,d,mcap&symbol=eq.{s}&d=gte.{lo}&d=lte.{hi}&order=d.asc"
        raw[key] = pull("asset_mcap_daily", q)
    mc_cache.write_text(json.dumps(raw))
    mc = defaultdict(dict)
    if True:
        for key, rs_ in raw.items():
            s = key.split("|")[0]
            for r in rs_:
                try:
                    mc[s][r["d"]] = float(r["mcap"])
                except (TypeError, ValueError, KeyError):
                    pass
        print(f"  市值窗口: {len(raw)} 次查询", flush=True)

    def mcap_pre(sym, day):
        ser = mc.get(sym)
        if not ser:
            return None
        lo = (date.fromisoformat(day) - timedelta(days=12)).isoformat()
        cands = [(d, v) for d, v in ser.items() if d <= (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                 and d >= lo]
        if not cands:
            return None
        cands.sort()
        return float(cands[-1][1])

    def tertile_table(rs):
        vals = []
        for r in rs:
            m = mcap_pre(r["sym"], r["d"])
            r["mcap_pre"] = m
            if m is not None and r.get("ex30") is not None:
                vals.append((m, r))
        if not vals:
            return []
        ms = sorted(v[0] for v in vals)
        q1, q2 = np.percentile(ms, [33.3333, 66.6667])
        out = []
        for name, lo, hi in (("小", -1.0, q1), ("中", q1, q2), ("大", q2, float("inf"))):
            grp = [r["ex30"] for m, r in vals if lo < m <= hi]
            if not grp:
                out.append({"bucket": name, "n": 0})
                continue
            out.append({"bucket": name, "n": len(grp), "median_pct": float(np.median(grp) * 100),
                        "mean_pct": float(np.mean(grp) * 100),
                        "mcap_lo": (None if lo < 0 else float(lo)),
                        "mcap_hi": (None if hi == float("inf") else float(hi))})
        return out

    res["mcap_tertiles"] = {"entry_on_d": tertile_table(rows0), "entry_on_d_plus_1": tertile_table(rows1)}

    # ── 副:上线后 7 天资金费 vs 超额(逐事件窄窗口拉) ───────────────────────
    fu: dict[str, dict[str, float]] = defaultdict(dict)
    fu_cache = CACHE / "funding_windows.json"
    seed = SEED_CACHE / "funding_windows.json"
    raw = json.loads(seed.read_text()) if seed.exists() else {}
    todo = {}
    for t in sample:
        s, d = t["sym"], t["d"]
        lo = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        hi = (date.fromisoformat(d) + timedelta(days=7)).isoformat()
        key = f"{s}|{lo}|{hi}"
        if key not in raw:
            todo[key] = (s, lo, hi)
    for key, (s, lo, hi) in todo.items():
        q = (f"select=symbol,d,funding_rate,n&symbol=eq.{s}&d=gte.{lo}&d=lte.{hi}&order=d.asc")
        raw[key] = pull("v_funding_daily", q)
    fu_cache.write_text(json.dumps(raw))
    fu = defaultdict(dict)
    if True:
        for key, rs_ in raw.items():
            s = key.split("|")[0]
            for r in rs_:
                try:
                    fu[s][r["d"]] = float(r["funding_rate"])
                except (TypeError, ValueError, KeyError):
                    pass
        print(f"  资金费窗口: {len(raw)} 次查询", flush=True)

    def funding7(sym, d):
        ser = fu.get(sym)
        if not ser:
            return None
        base = date.fromisoformat(d)
        vals = [ser[(base + timedelta(days=k)).isoformat()]
                for k in range(1, 8) if (base + timedelta(days=k)).isoformat() in ser]
        if len(vals) < 3:
            return None
        return float(np.mean(vals))

    def funding_table(rs):
        xs, ys = [], []
        for r in rs:
            f = funding7(r["sym"], r["d"])
            if f is None or r.get("ex30") is None:
                continue
            xs.append(f)
            ys.append(r["ex30"])
        out = {"n": len(xs), "spearman_funding7_vs_ex30": spearman(xs, ys)}
        if xs:
            out["funding_mean"] = float(np.mean(xs))
            out["funding_median"] = float(np.median(xs))
        return out

    res["funding"] = {"entry_on_d": funding_table(rows0), "entry_on_d_plus_1": funding_table(rows1)}

    res["events_detail"] = [
        {"sym": r["sym"], "d": r["d"], "ex30_pct": (r["ex30"] * 100 if r.get("ex30") is not None else None),
         "ex60_pct": (r["ex60"] * 100 if r.get("ex60") is not None else None),
         "pre30_ret_pct": (r["pre30_ret"] * 100 if r.get("pre30_ret") is not None else None),
         "mcap_pre": r.get("mcap_pre")}
        for r in rows0
    ]

    (OUT / "t279_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print("写出 t279_results.json", flush=True)
    print(json.dumps({k: res[k] for k in ("funnel", "sample_by_year", "main", "criteria")},
                     ensure_ascii=False, indent=1, default=float)[:5000], flush=True)

    # ── 结论(照 S-758:✅ ⇒ S-740 站住;❌ ⇒ S-740 撤销) ─────────────────────
    c0 = res["criteria"]["entry_on_d"]
    n0 = res["null_control"]["entry_on_d"]["h30"]
    checks = {"a": bool(c0["a"]["pass"]),
              "b": bool(n0.get("pass_le_p05")),
              "c": bool(c0["c"].get("same_sign")),
              "d": bool(c0["d"].get("same_sign"))}
    res["judge"] = {"checks": checks, "all_pass": all(checks.values()),
                    "failed": [k for k, v in checks.items() if not v]}
    ctrl_n = res["replication_control_old_mapping"]["main"]["entry_on_d"]["h30"]["n"]
    ctrl_med = res["replication_control_old_mapping"]["main"]["entry_on_d"]["h30"]["median_pct"]
    sp = res["subset_split"]["entry_on_d"]
    res["verdict"] = (
        ("**✅ S-740 站住(样本扩大后判据全过)。**" if all(checks.values())
         else f"**❌ S-740 撤销。** 失败判据:{','.join(res['judge']['failed'])}。")
        + f"旧映射对照 n={ctrl_n}(S-740 原报 46)、30 天中位 {ctrl_med:.2f}%(原报 −17.42%)。"
        + f"新映射 n={res['main']['entry_on_d']['h30']['n']},"
        + f"旧子集 n={sp['old']['n']}(中位 {sp['old']['median_pct']:.2f}%) / "
        + f"新增部分 n={sp['new']['n']}(中位 {sp['new']['median_pct']:.2f}%)。"
        + ("原结果**不是**只靠旧子集。" if sp["new"]["n"] and sp["old"]["n"]
           and (sp["old"]["median_pct"] or 0) == (sp["new"]["median_pct"] or 0)
           and sp["old"]["median_pct"] is not None else ""))
    print(res["verdict"], flush=True)
    write_report(res)



def fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return f"{v:.{nd}f}"
    return str(v)


def write_report(res: dict) -> None:
    L = []
    A = L.append
    m = res["main"]["entry_on_d"]
    c = res["criteria"]["entry_on_d"]
    nc = res["null_control"]["entry_on_d"]["h30"]
    ctrl = res["replication_control_old_mapping"]
    cm = ctrl["main"]["entry_on_d"]["h30"]
    mp = res["mapping"]
    A("# T-279 / S-758 —— S-740 复现:用补全后的代号映射重跑「永续上线 = 做空供给冲击」")
    A("")
    A(f"- 生成:{res['generated_at']} · 种子 {res['seed']} · 零分布 {res['n_null']} 次 · 判据照 S-740 一字不改")
    A(f"- 公告总数 **{mp['announcements_total']}** 条(kind=perp_listing, source=binance)")
    A(f"- **旧解析器(S-740)能映射 {mp['announcements_mapped_old']} 条,漏 {mp['announcements_unmapped_old']} 条;"
      f"新解析(T-277 v2)能映射 {mp['announcements_mapped_new']} 条,漏 {mp['announcements_unmapped_new']} 条**")
    A(f"- 代号数:旧 {mp['distinct_symbols_old']} → 新 {mp['distinct_symbols_new']}"
      f"(只靠 v2 才解析出来的公告 {mp['announcements_mapped_only_by_v2']} 条)")
    A(f"- 逐条映射落盘:`docs/research/t279_event_symbol_map.json`({mp['announcements_total']} 条,取价格之前落盘)")
    A("")
    A("## 1. 复现对照(旧映射,同一套价格/窗口/判据)")
    A("")
    A(f"- 旧映射样本 n = **{cm['n']}**(S-740 原报 n = 46),30 天超额中位 **{fmt(cm['median_pct'])}%**"
      f"(S-740 原报 −17.42%)")
    A(f"- ⇒ 复现链路{'一致' if cm['n'] == 46 else '**不一致(n≠46)**'}")
    A("")
    A("## 2. 主口径(新映射)—— S-740 (a)–(d)")
    A("")
    A("| 判据 | 要求 | 实测 | 过? |")
    A("|---|---|---|---|")
    A(f"| (a) | 30 天超额中位 ≤ −3% 且均值 < 0 | n={m['h30']['n']},中位 {fmt(m['h30']['median_pct'])}%,"
      f"均值 {fmt(m['h30']['mean_pct'])}% | {'✅' if c['a']['pass'] else '❌'} |")
    A(f"| (b) | 实际中位 ≤ 对照 5 分位 | 实际 {fmt(nc.get('actual_median_pct'))}% vs p05 "
      f"{fmt(nc.get('null_p05_pct'))}%(分位 {fmt(nc.get('percentile_of_actual'), 3)}) | "
      f"{'✅' if nc.get('pass_le_p05') else '❌'} |")
    A(f"| (c) | 两段同号 | 2020-01→2022-12 中位 {fmt(c['halves'][0]['median_pct'])}%(n={c['halves'][0]['n']}) / "
      f"2023-01→ 中位 {fmt(c['halves'][1]['median_pct'])}%(n={c['halves'][1]['n']}) | "
      f"{'✅' if c['c'].get('same_sign') else '❌'} |")
    A(f"| (d) | 去掉上线前 30 天涨超 50% 的后仍同号 | 去掉 {c['d']['n_excluded']} 条,剩 {c['d']['n_kept']} 条,"
      f"中位 {fmt(c['d']['median_kept_pct'])}% | {'✅' if c['d'].get('same_sign') else '❌'} |")
    A("")
    sp = res["subset_split"]["entry_on_d"]
    A("## 3. 旧子集 vs 新增部分(S-758 要求分开报)")
    A("")
    A("| 子集 | n | 30 天中位 | 30 天均值 | 为负比例 | 60 天中位 |")
    A("|---|---|---|---|---|---|")
    for tag, label in (("old", "旧解析器能映射"), ("new", "只有 v2 能映射")):
        v = sp[tag]
        A(f"| {label} | {v['n']} | {fmt(v['median_pct'])}% | {fmt(v['mean_pct'])}% | "
          f"{fmt(100 * v['frac_negative'], 1) if v['frac_negative'] is not None else 'n/a'}% | "
          f"{fmt(v['h60_median_pct'])}% |")
    A("")
    A("## 4. 副项(只报不判)")
    A("")
    A(f"- 60 天超额:新映射 n={m['h60']['n']},中位 {fmt(m['h60']['median_pct'])}%,均值 {fmt(m['h60']['mean_pct'])}%")
    A(f"- 挪一天入场(S-665):n={res['main']['entry_on_d_plus_1']['h30']['n']},"
      f"中位 {fmt(res['main']['entry_on_d_plus_1']['h30']['median_pct'])}%")
    mt = res.get("mcap_tertiles", {}).get("entry_on_d", [])
    if mt:
        A("- 上线前市值三分位:" + " / ".join(
            f"{b['bucket']} n={b['n']} 中位 {fmt(b.get('median_pct'))}%" for b in mt))
    fg = res.get("funding", {}).get("entry_on_d", {})
    if fg:
        A(f"- 上线后 7 天资金费 vs 30 天超额:Spearman {fmt(fg.get('spearman_funding7_vs_ex30'), 4)}(n={fg.get('n')})")
    A("")
    A("## 5. 结论")
    A("")
    A(res["verdict"])
    A("")
    A("---")
    A("")
    A("*只算、不改代码、不入库。判据照 REFUTATION_LEDGER §S-740 / §S-758 预注册,未在见到结果后改动。*")
    (OUT / "T-279_perp_listing_replication.md").write_text("\n".join(L) + "\n")
    print(f"写 {OUT / 'T-279_perp_listing_replication.md'}", flush=True)


if __name__ == "__main__":
    main()
