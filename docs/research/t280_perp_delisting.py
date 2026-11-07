#!/usr/bin/env python3
"""T-280 — S-759:Binance USDT 永续下架公告之后 30 天,代币相对 BTC 跑输吗。

口径照 REFUTATION_LEDGER S-759(S-751 的价格 / d0 / 超额 / 对照口径全部复用 lane-b T-272 的
docs/research/t272_delisting.py):

  事件   = events(source=binance, kind=perp_delisting) 全表(78 条)
  映射   = T-277 补全解析器 extract_tickers_v2 ∪ T-272 extract_perp_symbols
  排除   = 季度 / 交割合约、COIN-M、延期 / 暂停、无法枚举的 "Multiple"
  名单   = 整币下架(S-751)已有的代号另列,不进主样本
  d0     = 公告 ts 所在 UTC 日;价格 = asset_mcap_daily(主)/ ohlcv_daily(交叉核对)
  超额   = 代币收益 − BTC 收益;H = 30 天(主)/ 7 天(副)
  对照   = 同一代币在 [d0−365, d0−60] 里随机取 200 个日子,同样算 30 天超额,
           事件中位数在对照中位数分布里的分位
  判据   = (a) 中位 ≤ −10% (b) ≥65% 为负 (c) 对照分位 ≤ 0.05 (d) 有价代币 ≥ 25
           (e) 按事件日期对半分两段,中位同号且每段 ≥ 8 个

**两个样本口径(解析阶段发现的必须区分,不是事后挑结果):**
  口径 A(台账写死的映射字面)= 除 COIN-M / 季度交割外全部合约代号,含 BUSD 计价合约
  口径 B(台账标题字面「USDT 永续」)= 只留 USDT 计价的合约
  2023 年那批公告写的是「USDⓈ-M XXXBUSD」—— BUSD 计价合约(Binance 退出 BUSD 抵押品的清理),
  同一代币的 USDT 永续当时仍在交易。把它们算进「USDT 永续下架」会把两种事件混在一起。
  两个口径都算、都报,判据各判一次;哪一个对应「硬规则该扩」由报告与 Jazz 定。

阶段(先落文件,再往下走):
  parse   逐条解析 78 条 → docs/research/t280_screening.json(纳入 / 排除理由 + 代号 + 计价币)
  prices  拉价格     → docs/research/t280_price_cache.json
  stats   算 + 判据  → docs/research/t280_results.json
  all     三段连跑

用法:python3 docs/research/t280_perp_delisting.py [parse|prices|stats|all]
"""
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
from data.evaluation.apparatus import (  # noqa: E402
    long_return,
    null_distribution,
    percentile_of,
    price_on_or_after,
    random_dates_like,
)

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
SCREEN_PATH = os.path.join(HERE, "t280_screening.json")
PRICE_PATH = os.path.join(HERE, "t280_price_cache.json")
RESULT_PATH = os.path.join(HERE, "t280_results.json")
PROBE_PATH = os.path.join(HERE, "t280_coverage_probe.json")
FILL_PATH = os.path.join(HERE, "t280_ohlcv_fill.json")
S751_PATH = os.path.join(HERE, "t272_screening.json")  # S-751 整币下架名单(主样本要避开)

SEED = 20261107
N_SAMP = 200

# ── 代号解析 ①:T-277 补全后的解析器(lane-b/T-277,docs/research/t277_rv2_perp_listing.py)──
# S-740 的老解析器只认「FOOUSDT / ETH/USDT」,818 条公告里 571 条解析不出代号;
# T-277 补齐了「USDT-Margined APE」「USDⓈ-M ARB」等写法。这里原样复用。
STOPWORDS = {"USD", "USDT", "USDC", "BUSD", "PERPETUAL", "PERPETUALS", "CONTRACT", "CONTRACTS",
             "MARGINED", "MARGIN", "MARGINS", "TRADING", "LEVERAGE", "FUTURES", "MULTIPLE",
             "CROSS", "ISOLATED", "BINANCE", "QUARTERLY", "COIN", "M", "ENABLE", "ENABLED",
             "AND", "WITH", "UP", "TO", "LAUNCH", "LAUNCHES", "WILL", "TICKER", "PAIRS", "PAIR",
             "AGAINST", "SETTLE", "SETTLEMENT", "CONTRAC", "FUTUR", "THE", "FOR", "A", "AN",
             "TIERS", "UPDATE", "DELIST", "NOTICE", "CHANGE", "DELISTING", "OF"}
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


def _norm_tok(t):
    t = (t or "").strip()
    for suf in ("USDT", "USDC", "BUSD"):
        if t.endswith(suf) and len(t) > len(suf):
            t = t[: -len(suf)]
    if t.endswith("USD") and len(t) > 3:
        t = t[:-3]
    if len(t) < 2 or t in STOPWORDS or t.isdigit():
        return None
    if not re.fullmatch(r"[A-Z0-9]+", t):
        return None
    return t


def extract_tickers_v2(title):
    """T-277 的补全解析器(逐字复用)。"""
    t = title or ""
    out = []

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


# ── 代号解析 ②:T-272 的 extract_perp_symbols(逐字复用)───────────────────────
def extract_perp_symbols(title):
    if "Multiple" in title:
        return []
    out = []
    for m in re.finditer(r"\b([A-Z0-9]{1,12})(?:USDT|USDC|BUSD|USD)\b", title):
        s = m.group(1)
        if s in ("USD", "USDT", "USDC", "BUSD", "M", "COIN", "PERPETUAL"):
            continue
        out.append(s)
    out = [s for s in out if len(s) >= 2]
    seen, keep = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            keep.append(s)
    return keep


# ── 计价币识别(口径 A / B 的分界)────────────────────────────────────────────
# 「XXXBUSD」是 BUSD 计价(Binance 退出 BUSD 抵押品的清理),不是 COIN-M 反向合约;
# 「XXXUSD」才是 COIN-M。计价币按**整段原文的后缀**判定,不按切分点。
RX_QUOTED = re.compile(r"\b([A-Z0-9]{1,15}?)(USDT|USDC|BUSD|USD)\b")
RX_LIST_AFTER_MARKER = re.compile(
    r"(?:USDⓈ-?M|USDT[- ]?Margined|USDC[- ]?Margined|BUSD[- ]?Margined)\s+(.{2,90}?)\s+Perpetual", re.I)
RX_LIST_BEFORE_MARKER = re.compile(
    r"(.{2,90}?)\s+(?:USDⓈ-?M|USDT[- ]?Margined|USDC[- ]?Margined|BUSD[- ]?Margined)", re.I)
RX_MARKER = re.compile(
    r"USDⓈ-?M(?:argined)?|USDT[- ]?Margined|USDC[- ]?Margined|BUSD[- ]?Margined|Coin-Margined|COIN-M", re.I)


def _split_list(seg):
    out = []
    for piece in re.split(r",|&|\band\b", seg):
        p = piece.strip().strip(".").strip()
        if p:
            out.append(p)
    return out


def _ticker_of_piece(piece):
    """列表片段 → 代号:整段是大写代号就取整段;否则取最后一个词(「… Will Delist LUNA」→ LUNA)。"""
    p = piece.strip()
    if re.fullmatch(r"[A-Za-z0-9]{1,15}", p):
        return p.upper()
    words = [w for w in p.split() if w]
    if not words:
        return None
    last = words[-1]
    return last.upper() if re.fullmatch(r"[A-Za-z0-9]{1,15}", last) else None


def parse_occurrences(title):
    """→ list of {raw, ticker, quote, pos, src}。ticker = 合约代码;quote = 计价币。
    同一段文字可能给出两个 ticker(T-277 剥掉计价币 / T-272 只剥 USD)—— 两个都记下来,
    取并集就是台账写死的映射。"""
    t = title or ""
    occ = []

    def push(raw, quote, pos, src):
        if raw is None:
            return
        n = _norm_tok(raw)
        if not n:
            return
        occ.append({"raw": raw, "ticker": n, "quote": quote, "pos": pos, "src": src})

    def push_quoted(raw, pos, src, push):
        """raw 形如 XXXUSDT / XXXUSDC / XXXBUSD / XXXUSD(COIN-M)"""
        if raw.endswith("USDT"):
            q, t277, t272 = "USDT", raw[:-4], raw[:-4]
        elif raw.endswith("USDC"):
            q, t277, t272 = "USDC", raw[:-4], raw[:-4]
        elif raw.endswith("BUSD"):
            q, t277, t272 = "BUSD", raw[:-4], raw[:-3]
        elif raw.endswith("USD"):
            q, t277, t272 = "USD", None, raw[:-3]
        else:
            return
        if t277:
            push(t277, q, pos, src)
        if t272 and t272 != t277:
            push(t272, q, pos, src)

    # ①带计价币的合约代码(两个解析器的切法都保留)
    for m in RX_QUOTED.finditer(t):
        push_quoted(m.group(0), m.start(), "quoted", push)
    # ②列表上下文里的裸代号(MEMEFI / YFII 这种不带计价币的写法)
    for rx, src in ((RX_LIST_AFTER_MARKER, "list_after_marker"),
                    (RX_LIST_BEFORE_MARKER, "list_before_marker")):
        for m in rx.finditer(t):
            seg = m.group(1)
            seg_start = m.start(1)
            if src == "list_before_marker":
                seg = seg[-90:]
                seg_start = m.end(1) - len(seg)
            cursor = 0
            for piece in _split_list(seg):
                idx = seg.find(piece, cursor)
                if idx < 0:
                    idx = cursor
                cursor = idx + len(piece)
                pos = seg_start + idx
                mm = RX_QUOTED.fullmatch(piece)
                if mm:
                    push_quoted(mm.group(0), pos, src, push)
                else:
                    words = [w for w in piece.split() if w]
                    last = words[-1] if words else None
                    if last and RX_QUOTED.fullmatch(last):
                        push_quoted(last, pos, src, push)
                    else:
                        push(_ticker_of_piece(piece), None, pos, src)
    # ③T-277 / T-272 的其余写法(X USDT-Margined / USDⓈ-M X / for X / X/USDT)
    for rx, src in ((RX_AFTER, "t277_after"), (RX_BEFORE, "t277_before"),
                    (RX_USDM_AFTER, "t277_usdm_after"),
                    (RX_USDM_BEFORE, "t277_usdm_before"), (RX_FOR, "t277_for")):
        for m in rx.finditer(t):
            raw = m.group(1)
            if raw.endswith("USDT") or raw.endswith("USDC") or raw.endswith("BUSD") or raw.endswith("USD"):
                push_quoted(raw, m.start(), src, push)
            else:
                push(raw, None, m.start(), src)
    for m in RX_SLASH.finditer(t):
        push(m.group(1), "USDT", m.start(), "t277_slash")
    return occ


def quote_of(occ, title, markers):
    """这个代号的计价币。带计价币的按后缀;裸代号看最近的标记(USDⓈ-M / USDT-Margined ⇒ USDT,
    COIN-M / Coin-Margined ⇒ USD)。"""
    if occ["quote"]:
        return occ["quote"]
    best, bestd = None, 10 ** 9
    for pos, kind in markers:
        d = abs(pos - occ["pos"])
        if d < bestd or (d == bestd and best is not None and pos < best[0]):
            best, bestd = (pos, kind), d
    if best is None:
        return None
    return "USD" if best[1] in ("coinm",) else "USDT"


def build_sample(title):
    """→ (口径A 代号表, 口径B 代号表, 全部 occurrence, 全部代号含 COIN-M)"""
    markers = []
    for m in RX_MARKER.finditer(title or ""):
        kind = "coinm" if re.match(r"coin", m.group(0), re.I) else "usdt"
        markers.append((m.start(), kind))
    occ = parse_occurrences(title)
    for o in occ:
        o["quote"] = quote_of(o, title, markers)
    a, b, allx, coinm = [], [], [], []
    for o in occ:
        if o["ticker"] not in allx:
            allx.append(o["ticker"])
        if o["quote"] == "USD":       # COIN-M 反向合约:台账明写排除
            if o["ticker"] not in coinm:
                coinm.append(o["ticker"])
            continue
        if o["ticker"] not in a:
            a.append(o["ticker"])
        if o["quote"] == "USDT" and o["ticker"] not in b:
            b.append(o["ticker"])
    return a, b, occ, allx, coinm


# ── 筛选规则(先写死,再对全表跑)──────────────────────────────────────────────
def screen_perp(title):
    """→ (include: bool, reason: str, flags: list)"""
    t = title or ""
    flags = []
    if re.search(r"Postpon", t, re.I) or re.search(r"Reschedul", t, re.I):
        flags.append("postponed")
        return False, "postponed_or_rescheduled", flags
    if re.search(r"to Suspend|Suspension of", t, re.I):
        flags.append("suspension")
        return False, "suspension_not_delisting", flags
    if "Delist" not in t:
        return False, "not_a_delisting", flags
    if re.search(r"\bMultiple\b", t):
        flags.append("multiple_not_enumerable")
        return False, "multiple_contracts_not_enumerable", flags
    if re.search(r"Quarterly|Delivery|Deliverable", t, re.I):
        flags.append("quarterly_or_delivery")
        return False, "quarterly_or_delivery", flags
    return True, "perp_delisting", flags


# ── Supabase REST(只读)──────────────────────────────────────────────────────
def rest(path, count=False, timeout=120):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    if count:
        h["Prefer"] = "count=exact"
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def rest_rows(path, page=1000, workers=8):
    """order= 必带;每页最多 1000 行;offset 分页 + 并发。"""
    hdr = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}
    req = urllib.request.Request(f"{URL}/rest/v1/{path}&limit=1", headers=hdr)
    with urllib.request.urlopen(req, timeout=120) as resp:
        cr = resp.headers.get("Content-Range") or resp.headers.get("content-range") or ""
    total = int(cr.split("/")[-1]) if "/" in cr else 0
    n_pages = max(1, math.ceil(total / page)) if total else 1

    def one(k):
        return json.loads(rest(f"{path}&limit={page}&offset={k * page}"))

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(one, range(n_pages)):
            rows.extend(part)
    return rows, total


# ── 阶段 1:parse(逐条落文件,先于取价)────────────────────────────────────────
def phase_parse():
    rows, total = rest_rows("events?kind=eq.perp_delisting&order=id.asc")
    print(f"[parse] events(kind=perp_delisting) 抓到 {len(rows)} 行(表内共 {total})")
    assert len(rows) == total, "分页没抓全"
    rows.sort(key=lambda r: r["ts"])

    s751 = set(json.load(open(S751_PATH))["tokens"].keys())

    decisions = []
    for r in rows:
        inc, reason, flags = screen_perp(r["title"])
        a_syms, b_syms, occ, all_syms, coinm_syms = build_sample(r["title"])
        if inc and all_syms and not a_syms:
            inc, reason = False, "coin_m_only"
        elif inc and not all_syms:
            inc, reason = False, "unresolvable_symbols"
        d = {
            "id": r["id"], "ts": r["ts"], "title": r["title"], "source": r["source"],
            "kind": r["kind"], "include": inc, "reason": reason, "flags": flags,
            "symbols_A": a_syms, "symbols_B": b_syms,
            "symbols_all": all_syms, "symbols_coin_m": coinm_syms,
            "occurrences": occ,
            "quotes": sorted({o["quote"] for o in occ if o["quote"]}),
            "also_in_s751": sorted(set(a_syms) & s751),
        }
        decisions.append(d)

    inc_ann = [d for d in decisions if d["include"]]

    def first_by(key):
        first = {}
        for d in inc_ann:
            for s in d[key]:
                if s not in first or d["ts"] < first[s]["ts"]:
                    first[s] = d
        return first

    first_a = first_by("symbols_A")
    first_b = first_by("symbols_B")
    main_a = {s: first_a[s] for s in sorted(first_a) if s not in s751}
    main_b = {s: first_b[s] for s in sorted(first_b) if s not in s751}
    also_a = {s: first_a[s] for s in sorted(first_a) if s in s751}
    also_b = {s: first_b[s] for s in sorted(first_b) if s in s751}

    print(f"[parse] 78 条 → 纳入 {len(inc_ann)} 条 / 排除 {len(decisions) - len(inc_ann)} 条")
    print("[parse] 排除理由分布:", dict(Counter(d["reason"] for d in decisions if not d["include"]).most_common()))
    print(f"[parse] 口径A 代号 {len(first_a)}(主 {len(main_a)}/S751 重叠 {len(also_a)})")
    print(f"[parse] 口径B 代号 {len(first_b)}(主 {len(main_b)}/S751 重叠 {len(also_b)})")

    out = {
        "task": "T-280", "ledger": "S-759", "run_utc": "2026-11-07",
        "screen_rule": {
            "event": "events(source=binance, kind=perp_delisting), 78 条全表",
            "include": '标题含 "Delist";排除延期 / 暂停 / Multiple / 季度交割',
            "mapping": "T-277 extract_tickers_v2 ∪ T-272 extract_perp_symbols(+ 列表上下文补全)",
            "sample_A": "台账写死的映射字面:除 COIN-M / 季度交割外全部代号(含 BUSD 计价合约)",
            "sample_B": "台账标题字面「USDT 永续」:只留 USDT 计价的代号",
            "one_event_per_symbol": "同一代号多次公告取最早一次(ts)",
            "d0": "公告 ts 所在 UTC 日",
            "s751_overlap": "整币下架(S-751)名单里的代号另列,不进主样本",
        },
        "events_total": total,
        "decisions": decisions,
        "included_announcements": inc_ann,
        "tokens_main_A": main_a,
        "tokens_main_B": main_b,
        "tokens_also_in_s751_A": also_a,
        "tokens_also_in_s751_B": also_b,
        "s751_token_count": len(s751),
    }
    with open(SCREEN_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[parse] 落 {SCREEN_PATH}")
    return out


# ── 阶段 2:prices ───────────────────────────────────────────────────────────
def phase_prices():
    sc = json.load(open(SCREEN_PATH))
    syms = sorted(set(sc["tokens_main_A"]) | set(sc["tokens_main_B"])
                  | set(sc["tokens_also_in_s751_A"]) | set(sc["tokens_also_in_s751_B"]) | {"BTC"})
    cache = {"asset_mcap_daily": {}, "ohlcv_daily": {}}
    if os.path.exists(PRICE_PATH):
        cache = json.load(open(PRICE_PATH))
    todo = [s for s in syms if s not in cache["asset_mcap_daily"] or s not in cache["ohlcv_daily"]]
    print(f"[prices] {len(syms)} 个 symbol,待拉 {len(todo)}")

    def fetch(sym, table, extra, dkey):
        rows, off = [], 0
        while True:
            path = f"{table}?symbol=eq.{sym}{extra}&order={dkey}.asc&limit=1000&offset={off}"
            got = None
            for _ in range(3):
                try:
                    got = json.loads(rest(path, timeout=180))
                    break
                except Exception:
                    time.sleep(1.5)
            if got is None:
                print(f"   !! {table} {sym} 拉取失败(offset={off})")
                break
            rows.extend(got)
            if len(got) < 1000:
                break
            off += 1000
            if off > 12000:
                break
        return rows

    def job(sym):
        return (sym,
                fetch(sym, "asset_mcap_daily", "", "d"),
                fetch(sym, "ohlcv_daily", "&source=eq.coingecko_pro_ohlc", "trade_date"))

    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, m, o in ex.map(job, todo):
            cache["asset_mcap_daily"][sym] = m
            cache["ohlcv_daily"][sym] = o
            done += 1
            if done % 20 == 0:
                with open(PRICE_PATH, "w") as f:
                    json.dump(cache, f)
                print(f"   .. {done}/{len(todo)}")

    with open(PRICE_PATH, "w") as f:
        json.dump(cache, f)
    nm = sum(len(v) for v in cache["asset_mcap_daily"].values())
    no = sum(len(v) for v in cache["ohlcv_daily"].values())
    print(f"[prices] asset_mcap_daily {nm} 行 / ohlcv_daily {no} 行 → {PRICE_PATH}")
    return cache


# ── 阶段 3:stats ────────────────────────────────────────────────────────────
def before_price(dates, closes, d, max_gap_days=3):
    """d 当天或之前 max_gap_days 天内的最后一个有效收盘(与 T-272 同一写法)。"""
    tgt = date.fromisoformat(str(d)[:10])
    best = None
    for dd, c in zip(dates, closes):
        dd_ = date.fromisoformat(str(dd)[:10])
        if dd_ > tgt:
            continue
        if (tgt - dd_).days > max_gap_days:
            continue
        try:
            fv = float(c)
        except (TypeError, ValueError):
            continue
        if fv > 0 and math.isfinite(fv):
            best = fv
    return best


def phase_stats():
    sc = json.load(open(SCREEN_PATH))
    px = json.load(open(PRICE_PATH))
    mcap_rows = [r for rows in px["asset_mcap_daily"].values() for r in rows]
    ohlc_rows = [r for rows in px["ohlcv_daily"].values() for r in rows]

    def build(rows, dkey, pkey):
        out = defaultdict(dict)
        for r in rows:
            v = r.get(pkey)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0 and math.isfinite(fv):
                out[r["symbol"]][str(r[dkey])[:10]] = fv
        return out

    SRC = {
        "mcap": build(mcap_rows, "d", "price"),
        "ohlc": build(ohlc_rows, "trade_date", "close"),
    }
    # 合并源(敏感性,不作判据):asset_mcap_daily 优先,缺价的代号用 ohlcv_daily 补。
    if os.path.exists(FILL_PATH):
        fill = json.load(open(FILL_PATH))
        SRC["union"] = {k: dict(v) for k, v in SRC["mcap"].items()}
        fb = build([r for rows in fill.values() for r in rows], "trade_date", "close")
        for sym, tbl_s in fb.items():
            if sym not in SRC["union"]:
                SRC["union"][sym] = tbl_s
    else:
        SRC["union"] = SRC["mcap"]

    def anchors(tbl, s, d0):
        dates = sorted(tbl.get(s, {}))
        closes = [tbl[s][x] for x in dates]
        g = lambda tgt: price_on_or_after(dates, closes, tgt, 3)  # noqa: E731
        return {
            "m1": before_price(dates, closes, (d0 - timedelta(days=1)).isoformat(), 3),
            "m30": before_price(dates, closes, (d0 - timedelta(days=30)).isoformat(), 3),
            "d0": g(d0.isoformat()),
            "p7": g((d0 + timedelta(days=7)).isoformat()),
            "p30": g((d0 + timedelta(days=30)).isoformat()),
        }

    def run_sample(name, tokens, src="mcap"):
        tbl = SRC[src]
        btc = tbl.get("BTC", {})
        bdates = sorted(btc)
        bcloses = [btc[x] for x in bdates]
        btc_g = lambda tgt: price_on_or_after(bdates, bcloses, tgt, 3)  # noqa: E731

        per_token = {}
        for sym, ev in tokens.items():
            if sym not in tbl:
                per_token[sym] = {"status": "no_price_source", "title": ev["title"], "ts": ev["ts"]}
                continue
            d0 = date.fromisoformat(ev["ts"][:10])
            a = anchors(tbl, sym, d0)
            b = {"m1": before_price(bdates, bcloses, (d0 - timedelta(days=1)).isoformat(), 3),
                 "m30": before_price(bdates, bcloses, (d0 - timedelta(days=30)).isoformat(), 3),
                 "d0": btc_g(d0.isoformat()),
                 "p7": btc_g((d0 + timedelta(days=7)).isoformat()),
                 "p30": btc_g((d0 + timedelta(days=30)).isoformat())}
            r = {"status": "ok", "title": ev["title"], "ts": ev["ts"], "d0": d0.isoformat(),
                 "token": a, "btc": b}
            for tag, (k0, k1) in {"ret30": ("d0", "p30"), "ret7": ("d0", "p7"),
                                  "jump": ("m1", "d0"), "pre30": ("m30", "d0")}.items():
                tr = long_return(a[k0], a[k1])
                br = long_return(b[k0], b[k1])
                r[tag] = None if (tr is None or br is None) else tr - br
                r[tag + "_tok"] = tr
                r[tag + "_btc"] = br
            per_token[sym] = r

        usable = {s: r for s, r in per_token.items() if r.get("status") == "ok" and r.get("ret30") is not None}
        exc30 = sorted(r["ret30"] for r in usable.values())
        med = float(exc30[len(exc30) // 2]) if exc30 else None
        neg = sum(1 for v in exc30 if v < 0)
        # (e) 按事件日期对半分两段
        seg = {}
        ordered = sorted(usable.items(), key=lambda kv: kv[1]["d0"])
        if ordered:
            half = len(ordered) // 2
            for nm, part in (("early", ordered[:half]), ("late", ordered[half:])):
                vals = sorted(r["ret30"] for _, r in part)
                seg[nm] = {"n": len(vals),
                           "median": float(vals[len(vals) // 2]) if vals else None,
                           "d0_range": [part[0][1]["d0"], part[-1][1]["d0"]] if part else None}
        # 对照:同一代币在 [d0−365, d0−60] 里随机取日子
        eligible = {}
        for s, r in usable.items():
            d0 = date.fromisoformat(r["d0"])
            lo, hi = d0 - timedelta(days=365), d0 - timedelta(days=60)
            cand = [dd for dd in sorted(tbl.get(s, {}))
                    if lo <= date.fromisoformat(dd) <= hi]
            eligible[s] = cand
        ev_pairs = [(s, usable[s]["d0"]) for s in sorted(usable)]
        usable_pairs = [(s, d) for s, d in ev_pairs if eligible.get(s)]

        def one_draw(rng):
            picks = random_dates_like(usable_pairs, eligible, rng, stratum=lambda x: "all")
            vals = []
            for s, d in picks:
                if d is None:
                    continue
                dd = date.fromisoformat(d)
                ds = sorted(tbl.get(s, {}))
                cs = [tbl[s][x] for x in ds]
                p0 = price_on_or_after(ds, cs, d, 3)
                p1 = price_on_or_after(ds, cs, (dd + timedelta(days=30)).isoformat(), 3)
                b0 = btc_g(d)
                b1 = btc_g((dd + timedelta(days=30)).isoformat())
                tr, br = long_return(p0, p1), long_return(b0, b1)
                if tr is None or br is None:
                    continue
                vals.append(tr - br)
            if not vals:
                return None
            vals.sort()
            return float(vals[len(vals) // 2])

        null = null_distribution(one_draw, N_SAMP, seed=SEED, actual=med)
        null_f = [x for x in null if x is not None]
        pctl = percentile_of(med, null_f)
        n_priced = sum(1 for r in per_token.values() if r.get("status") == "ok")
        return {
            "sample": name,
            "n_symbols": len(tokens),
            "n_tokens_with_price": n_priced,
            "n_exc30_computable": len(usable),
            "median_exc30": med,
            "pct_negative_exc30": (neg / len(exc30)) if exc30 else None,
            "n_negative": neg,
            "segments": seg,
            "control": {"n_samples": N_SAMP, "null_median_q": {
                "q05": float(sorted(null_f)[int(0.05 * len(null_f))]) if null_f else None,
                "q50": float(sorted(null_f)[len(null_f) // 2]) if null_f else None,
                "q95": float(sorted(null_f)[int(0.95 * len(null_f))]) if null_f else None},
                "percentile_of_actual": pctl,
                "n_draws_used": len(null_f)},
            "per_token": per_token,
        }

    def judge(s):
        a_ok = s["median_exc30"] is not None and s["median_exc30"] <= -0.10
        b_ok = s["pct_negative_exc30"] is not None and s["pct_negative_exc30"] >= 0.65
        c_ok = s["control"]["percentile_of_actual"] is not None and s["control"]["percentile_of_actual"] <= 0.05
        d_ok = s["n_exc30_computable"] >= 25
        s1 = s["segments"].get("early", {}).get("median")
        s2 = s["segments"].get("late", {}).get("median")
        n1 = s["segments"].get("early", {}).get("n") or 0
        n2 = s["segments"].get("late", {}).get("n") or 0
        e_ok = (s1 is not None and s2 is not None and (s1 < 0) == (s2 < 0) and n1 >= 8 and n2 >= 8)
        s["criteria"] = {
            "(a) 30天超额中位数 ≤ −10%": {"value": s["median_exc30"], "pass": a_ok},
            "(b) ≥65% 事件超额为负": {"value": s["pct_negative_exc30"], "pass": b_ok},
            "(c) 对照分位 ≤ 0.05": {"value": s["control"]["percentile_of_actual"], "pass": c_ok},
            "(d) 有价代币 ≥ 25": {"value": s["n_exc30_computable"], "pass": d_ok,
                                   "n_tokens_with_price": s["n_tokens_with_price"]},
            "(e) 按事件日期对半分两段:中位同号且每段 ≥ 8": {
                "value": {"early": {"n": n1, "median": s1}, "late": {"n": n2, "median": s2}},
                "pass": e_ok},
        }
        s["verdict"] = "PASS" if all([a_ok, b_ok, c_ok, d_ok, e_ok]) else "FAIL"
        return s

    sample_a = judge(run_sample("A_card_literal", sc["tokens_main_A"]))
    sample_b = judge(run_sample("B_usdt_only", sc["tokens_main_B"]))
    also_a = run_sample("A_also_in_s751", sc["tokens_also_in_s751_A"])
    also_b = run_sample("B_also_in_s751", sc["tokens_also_in_s751_B"])

    # 交叉核对:同一套口径改用 coingecko_pro_ohlc 的 close 重算(主源 = asset_mcap_daily)。
    # 注意 ohlcv_daily 只从 2025-08 起有历史 —— 早于那天的公告在交叉核对里没有 BTC 对照。
    cross = {}
    for nm, tk in (("A_card_literal", sc["tokens_main_A"]), ("B_usdt_only", sc["tokens_main_B"])):
        c = run_sample(nm + "_ohlc", tk, src="ohlc")
        cross[nm] = {k: v for k, v in c.items() if k != "per_token"}
        cross[nm]["d0_min"] = min((r["d0"] for r in c["per_token"].values()
                                   if r.get("status") == "ok"), default=None)

    # 合并源(敏感性):主源缺价的代号用 ohlcv_daily 补 —— 口径/样本没变,只多几行价格。
    union = {}
    for nm, tk in (("A_card_literal", sc["tokens_main_A"]), ("B_usdt_only", sc["tokens_main_B"])):
        u = judge(run_sample(nm + "_union", tk, src="union"))
        union[nm] = {k: v for k, v in u.items() if k != "per_token"}
    union["note"] = ("敏感性:价格源 = asset_mcap_daily(主)∪ ohlcv_daily(补);"
                     "口径与台账一致,只多补了几行价格 —— 仍按台账判据判一次,只作参照。")

    # 副项(只报不判)—— 口径 B
    def stat(prim, key):
        vals = sorted(v[key] for v in prim.values() if v.get("status") == "ok" and v.get(key) is not None)
        return {"n": len(vals),
                "median": float(vals[len(vals) // 2]) if vals else None,
                "pct_negative": (sum(1 for x in vals if x < 0) / len(vals)) if vals else None}
    prim_b = sample_b["per_token"]
    secondary = {
        "note": "副项只报不判(口径 B 主样本)",
        "pre30_exc": stat(prim_b, "pre30"),
        "announce_day_jump": stat(prim_b, "jump"),
        "exc7": stat(prim_b, "ret7"),
    }
    secondary["A_口径副项"] = {
        "pre30_exc": stat(sample_a["per_token"], "pre30"),
        "announce_day_jump": stat(sample_a["per_token"], "jump"),
        "exc7": stat(sample_a["per_token"], "ret7"),
    }
    # 敏感性(事后、口径变了 ⇒ 只报不判):把「合约代号」读成「现货代号」后的同一套统计。
    # 映射从公告原文的 raw+quote 反推,不看价格表(不按「有价」倒推):
    #   AGIXBUSD→AGIX(BUSD 计价合约)、1000PEPEUSDT→PEPE(1000x 代号)、XXXUSD→XXX(COIN-M)。
    # 台账写死的映射字面是「合约代号并集」,所以这不是主样本。
    def alias_base(sym, ev):
        """合约代号 → 现货代号。BUSD 计价时合约名恒为「<TICKER>BUSD」,T-272 只剥 USD ⇒
        代号尾部多一个 B(AGIXB→AGIX、GALAB→GALA);1000x 合约(1000SHIB)对应现货 SHIB。"""
        for occ in ev.get("occurrences", []):
            if occ.get("ticker") != sym:
                continue
            t = (occ.get("ticker") or "").upper()
            q = occ.get("quote")
            if q == "BUSD":
                return t[:-1] if len(t) > 1 and t.endswith("B") else t
            if q in ("USDT", "USDC") and t.startswith("1000") and len(t) > 4:
                return t[4:]
            return t
        return None

    def alias_tokens(tokens):
        out, pairs = {}, {}
        for sym, ev in sorted(tokens.items(), key=lambda kv: kv[1]["ts"]):
            base = alias_base(sym, ev) or sym
            if base in SRC["mcap"] and base not in out:
                out[base] = ev
                pairs[base] = sym
        return out, pairs

    alias_out = {}
    for nm, tk in (("A", sc["tokens_main_A"]), ("B", sc["tokens_main_B"])):
        at, pairs = alias_tokens(tk)
        s = run_sample(nm + "_underlying_alias", at)
        s["contract_of_base"] = pairs
        alias_out[nm] = s
    secondary["underlying_alias_sample"] = {
        "note": "事后敏感性:代号读成现货代号后的同一套统计;口径变了 ⇒ 只报不判(S-759 判据不作数)",
        "A": {k: v for k, v in alias_out["A"].items() if k != "per_token"},
        "B": {k: v for k, v in alias_out["B"].items() if k != "per_token"},
    }
    coverage = {}
    for nm, s in (("A", sample_a), ("B", sample_b)):
        prim = s["per_token"]
        coverage[nm] = {
            "n_symbols": s["n_symbols"],
            "n_with_price": s["n_tokens_with_price"],
            "n_exc30_computable": s["n_exc30_computable"],
            "symbols_no_price_source": sorted(x for x, r in prim.items() if r.get("status") != "ok"),
            "symbols_price_but_no_30d_forward": sorted(x for x, r in prim.items()
                                                       if r.get("status") == "ok" and r.get("ret30") is None),
            "d0_min": min((r["d0"] for r in prim.values() if r.get("status") == "ok"), default=None),
            "d0_max": max((r["d0"] for r in prim.values() if r.get("status") == "ok"), default=None),
        }

    out = {
        "task": "T-280", "ledger": "S-759", "run_utc": "2026-11-07",
        "primary_source": "asset_mcap_daily",
        "samples": {"A_card_literal": sample_a, "B_usdt_only": sample_b},
        "also_in_s751": {"A": also_a, "B": also_b},
        "cross_source_ohlc": cross,
        "union_source": union,
        "coverage": coverage,
        "secondary": secondary,
    }
    with open(RESULT_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[stats] 落 {RESULT_PATH}")
    for nm, s in (("A", sample_a), ("B", sample_b)):
        print(f"[stats] 口径 {nm}: verdict={s['verdict']} n={s['n_exc30_computable']} "
              f"median={s['median_exc30']} neg%={s['pct_negative_exc30']} "
              f"pctl={s['control']['percentile_of_actual']}")
    return out


def _count_rows(path):
    """count=exact 读 Content-Range 的总数。"""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}
    req = urllib.request.Request(f"{URL}/rest/v1/{path}&limit=1", headers=h)
    with urllib.request.urlopen(req, timeout=90) as resp:
        cr = resp.headers.get("Content-Range") or resp.headers.get("content-range") or ""
    return int(cr.split("/")[-1]) if "/" in cr else -1


def _scan_symbols(table, col, max_pages=1600):
    """扫 symbol 列(按 symbol 升序、每页 1000、并发)→ 去重代号集合 + 总行数。"""
    total = _count_rows(f"{table}?select=symbol")
    n_pages = min(max(1, math.ceil(total / 1000)), max_pages) if total > 0 else 1
    offsets = list(range(n_pages))

    def one(off):
        return json.loads(rest(f"{table}?select=symbol&order=symbol.asc&limit=1000&offset={off * 1000}"))

    seen = set()
    with ThreadPoolExecutor(max_workers=12) as ex:
        for rows in ex.map(one, offsets):
            seen.update(r.get("symbol") for r in rows)
    return sorted(x for x in seen if x), total, n_pages


def phase_fill():
    """补价(只读):asset_mcap_daily 里没有的代号,去 ohlcv_daily 取(不过滤 source)。
    起因:coverage probe 发现 9 个「缺价」代号在 ohlcv_daily 里其实有行 —— 上一轮抓取时
    带了 source=eq.coingecko_pro_ohlc 过滤,把它们滤掉了。产物 → docs/research/t280_ohlcv_fill.json。"""
    res = json.load(open(RESULT_PATH))
    sc = json.load(open(SCREEN_PATH))
    miss = set()
    for nm in ("A", "B"):
        miss.update(res["coverage"][nm]["symbols_no_price_source"])
    miss |= set(res["coverage"]["A"]["symbols_price_but_no_30d_forward"])
    syms = sorted(miss)

    def one(s):
        rows, total = rest_rows(f"ohlcv_daily?symbol=eq.{s}&order=trade_date.asc")
        return s, rows, total

    out, tot = {}, 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for s, rows, total in ex.map(one, syms):
            if rows:
                out[s] = rows
                tot += len(rows)
    with open(FILL_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"[fill] {len(out)}/{len(syms)} 个代号在 ohlcv_daily 取到行,共 {tot} 行 → {FILL_PATH}")
    return out


def phase_probe():
    """覆盖率核对(只读):缺价代号是不是真的在价格表里没有行;价格表本身覆盖多少代号;
    delisting_watch(S-751 名单来源)的规模。产物 → docs/research/t280_coverage_probe.json。"""
    res = json.load(open(RESULT_PATH))
    miss = set()
    for nm in ("A", "B"):
        miss.update(res["coverage"][nm]["symbols_no_price_source"])
    miss = sorted(miss)

    def present(table, syms):
        def one(s):
            return s, _count_rows(f"{table}?symbol=eq.{s}&select=symbol") > 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            return dict(ex.map(one, syms))

    p_mcap = present("asset_mcap_daily", miss)
    p_ohlc = present("ohlcv_daily", miss)
    out = {
        "task": "T-280", "ledger": "S-759", "run_utc": "2026-11-07",
        "missing_symbols_checked": len(miss),
        "missing_present_in_asset_mcap_daily": sorted(s for s in miss if p_mcap.get(s)),
        "missing_present_in_ohlcv_daily": sorted(s for s in miss if p_ohlc.get(s)),
        "note": "缺价代号在两张价格表里都没有行 ⇒ 缺的是「表里没有这个代号」,不是抓取漏页。",
    }
    with open(PROBE_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[probe] 缺价代号复查: asset_mcap_daily 命中 {len(out['missing_present_in_asset_mcap_daily'])} / "
          f"ohlcv_daily 命中 {len(out['missing_present_in_ohlcv_daily'])} (共查 {len(miss)})", flush=True)
    for tbl, dcol in (("asset_mcap_daily", "d"), ("ohlcv_daily", "trade_date")):
        syms, total, pages = _scan_symbols(tbl, dcol)
        out[f"{tbl}_universe"] = {
            "distinct_symbols": len(syms),
            "total_rows": total,
            "pages_scanned": pages,
            "min_date": (json.loads(rest(f"{tbl}?select={dcol}&order={dcol}.asc&limit=1")) or [{}])[0].get(dcol),
            "max_date": (json.loads(rest(f"{tbl}?select={dcol}&order={dcol}.desc&limit=1")) or [{}])[0].get(dcol),
            "has_BTC": "BTC" in syms,
        }
    dw_total = _count_rows("delisting_watch?select=*&order=symbol.asc")   # Seth 合并时补 order(静态检查)
    out["delisting_watch_rows"] = dw_total
    try:
        dw_cols = json.loads(rest("delisting_watch?select=*&order=symbol.asc&limit=2"))
        out["delisting_watch_sample"] = dw_cols
        out["delisting_watch_columns"] = sorted(dw_cols[0].keys()) if dw_cols else []
    except Exception as e:  # noqa: BLE001
        out["delisting_watch_sample_error"] = str(e)
    with open(PROBE_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[probe] 落 {PROBE_PATH}")
    for k, v in out.items():
        if k.endswith("_universe"):
            print(f"[probe] {k}: {v['distinct_symbols']} 代号 / {v['total_rows']} 行 / {v['min_date']}..{v['max_date']}")
    print(f"[probe] 缺价代号复查: asset_mcap_daily 命中 {len(out['missing_present_in_asset_mcap_daily'])} / "
          f"ohlcv_daily 命中 {len(out['missing_present_in_ohlcv_daily'])} (共查 {len(miss)})")
    print(f"[probe] delisting_watch 行数 {dw_total}")
    return out


if __name__ == "__main__":
    ph = sys.argv[1] if len(sys.argv) > 1 else "all"
    if ph in ("parse", "all"):
        phase_parse()
    if ph in ("prices", "all"):
        phase_prices()
    if ph in ("stats", "all"):
        phase_stats()
    if ph in ("probe", "all"):
        phase_probe()
    if ph in ("fill", "all"):
        phase_fill()
