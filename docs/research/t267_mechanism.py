#!/usr/bin/env python3
"""
T-267 / S-744 —— 永续上线之后的跑输:「做空供给」vs「上线前追高的均值回归」。

判据一字不改照 S-744 预注册(REFUTATION_LEDGER §S-744,Seth 2026-11-06 08:51 UTC):
  宇宙: events kind='perp_listing'、source='binance',按 T-262 标题过滤口径只留「上线一个 USDT 本位永续」;
        代币 → CoinGecko id(cg_coin_map 发布版 key 读不到 ⇒ 用 asset_mcap_daily 的 (symbol, coin_id) 对);
        价格 = CoinGecko 日线(卡上写的 cg_coin_mcap_daily 里没有 bitcoin/ethereum/solana 等主流币,
        连「BTC 同源」都给不出来 ⇒ 改用同上游 source=coingecko_pro_market_chart 的 asset_mcap_daily,
        并对两表共有的 coin_id 逐日对拍,不一致数写进结果);
        要求上线日 d 之前 ≥ 60 天已有价格;d = 事件 ts 的 UTC 日;窗口 2020-01 →。
  结果: d → d+30 相对 BTC 的对数超额(主),d+60(副)。
  机制检验(主,全满足才 ✅「做空供给」):
        对每个事件,在同一代币、d ± 365 天内、避开 [d−60, d+60] 的日子里,
        取「之前 30 天收益与事件的之前 30 天收益相差 ≤ 10 个百分点」的对照日;
        不足 20 个 ⇒ 该事件不进本检验(报数);
        匹配后的差 = 事件超额 − 对照日平均超额。
        (a) 匹配后差的中位数 ≤ −3%;
        (b) 事件间符号翻转检验(10,000 次,种子 744)单侧 p ≤ 0.05;
        (c) 两段(2020–2022 / 2023 →)同号;
        (d) 进入检验的事件 ≥ 40 个。
  副(不判):S-740 原判据 (a)–(d) 在新价格源/新宇宙上的数字;上线前市值三分位;上线后 7 天资金费与超额的关系。
  S-665:入场挪一天(d → d+1)判一次。

零分布 / 分位 / 随机日期 / 多空盈亏一律用 src/data/evaluation/apparatus.py。
只算、不改代码、不入库。
"""
from __future__ import annotations

import bisect
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

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
CACHE = RESEARCH / "t267_cache"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = HERE

HORIZONS = (30, 60)
WINDOW_START = "2020-01-01"
SEED = 740           # S-740 的零分布种子
SEED_FLIP = 744      # S-744 的符号翻转种子
N_NULL = 1000        # S-740 随机日期对照
N_FLIP = 10_000      # S-744 符号翻转
MAX_GAP = 5          # 价格对齐容忍(天)
CTRL_WINDOW = 365    # 对照日搜索窗口:d ± 365
CTRL_EXCLUDE = 60    # 避开 [d−60, d+60]
CTRL_TOL = 0.10      # 「之前 30 天收益」相差 ≤ 10 个百分点
CTRL_MIN = 20        # 对照日不足 20 个 ⇒ 不进检验
PRE_MOVE_THRESHOLD = 0.50
BTC_COIN = "bitcoin"

# ── 标题过滤口径:逐字照抄 T-262(t262_perp_listing.py §「标题规则」,S-740 预注册口径) ──
# 复制而不是 import:origin/main 上还没有 t262_perp_listing.py(T-262 还在 lane-b 分支上),
# 脚本必须自足。改动时两边同步。
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
TICKET_RX = re.compile(r"\b([A-Z0-9]{2,15})(?:USDT|USDC|BUSD)\b")
TICKET_SLASH_RX = re.compile(r"\b([A-Z0-9]{2,15})/USDT\b")
TICKET_STOPWORDS = {"USD", "USDT", "USDC", "BUSD", "PERPETUAL", "CONTRACT", "CONTRACTS",
                    "MARGINED", "MARGIN", "TRADING", "LEVERAGE", "FUTURES", "MULTIPLE"}


def classify(title: str) -> tuple[str, str | None]:
    t = title or ""
    for name, rx in EXCLUDE_RULES:
        if rx.search(t):
            return "drop", name
    for name, rx in INCLUDE_RULES:
        if not rx.search(t):
            return "drop", name
    return "keep", None


def extract_tickers(title: str) -> list[str]:
    out: list[str] = []
    for rx in (TICKET_RX, TICKET_SLASH_RX):
        for m in rx.finditer(title or ""):
            t = m.group(1)
            if t in TICKET_STOPWORDS:
                continue
            if t not in out:
                out.append(t)
    return out


# ── 取数(只读) ──────────────────────────────────────────────────────────────
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


def pull_one(table: str, query: str, limit: int = 200) -> list[dict]:
    """单页取数(不分页)。只在结果 ≤ limit 行时用(例如取一个 symbol 的 coin_id 集合)。"""
    r = SESSION.get(f"{URL}/rest/v1/{table}?{query}", headers={**H, "Prefer": "count=exact"},
                    params={"limit": limit}, timeout=180)
    if r.status_code not in (200, 206):
        raise RuntimeError(f"{table}: HTTP {r.status_code} {r.text[:200]}")
    body = r.json()
    return body if isinstance(body, list) else []


def cached(name: str, fn):
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)}", flush=True)
        return rows
    rows = fn()
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)}", flush=True)
    return rows


# ── 价格序列 ────────────────────────────────────────────────────────────────
class Series:
    """某 coin_id 的日线:日期升序、收盘价、mcap。"""

    __slots__ = ("coin", "dates", "closes", "mcap", "idx")

    def __init__(self, coin: str, rows: list[dict]):
        rs = []
        for r in rows:
            try:
                px = float(r["price"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (px > 0) or not math.isfinite(px):
                continue
            mc = None
            try:
                mc = float(r.get("mcap"))
                if not math.isfinite(mc):
                    mc = None
            except (TypeError, ValueError):
                mc = None
            rs.append((str(r["d"])[:10], px, mc))
        rs.sort()
        self.coin = coin
        self.dates = [x[0] for x in rs]
        self.closes = [x[1] for x in rs]
        self.mcap = [x[2] for x in rs]
        self.idx = {d: i for i, d in enumerate(self.dates)}

    def __len__(self) -> int:
        return len(self.dates)

    def poa(self, target: str) -> float | None:
        """target 当天或之后 MAX_GAP 天内的第一个有效收盘(bisect 版,与 apparatus 对拍过)。"""
        i = bisect.bisect_left(self.dates, target)
        if i >= len(self.dates):
            return None
        if (date.fromisoformat(self.dates[i]) - date.fromisoformat(target)).days > MAX_GAP:
            return None
        return self.closes[i]

    def oob(self, target: str) -> float | None:
        """target 当天或之前的最后一个有效收盘。"""
        i = bisect.bisect_right(self.dates, target)
        if i == 0:
            return None
        return self.closes[i - 1]

    def mcap_oob(self, target: str) -> float | None:
        i = bisect.bisect_right(self.dates, target)
        if i == 0:
            return None
        return self.mcap[i - 1]

    def n_before(self, day: str) -> int:
        return bisect.bisect_left(self.dates, day)


def load_series(coin: str) -> Series:
    rows = cached(f"px2_{coin}", lambda: pull(
        "asset_mcap_daily",
        f"select=d,price,mcap&coin_id=eq.{quote(coin, safe='')}&order=d.asc"))
    return Series(coin, rows)


# ── 统计小工具 ──────────────────────────────────────────────────────────────
def summarize(vals, scale: float = 100.0) -> dict:
    if not vals:
        return {"n": 0}
    a = np.asarray(vals, float)
    return {"n": int(a.size), "median_pct": float(np.median(a) * scale),
            "mean_pct": float(a.mean() * scale),
            "p25_pct": float(np.percentile(a, 25) * scale),
            "p75_pct": float(np.percentile(a, 75) * scale),
            "min_pct": float(a.min() * scale), "max_pct": float(a.max() * scale),
            "frac_negative": float((a < 0).mean()), "frac_le_-3": float((a <= -0.03).mean())}


def log_excess(entry, exit_, b_entry, b_exit):
    if not all(v and v > 0 and math.isfinite(v) for v in (entry, exit_, b_entry, b_exit)):
        return None
    return math.log(exit_ / entry) - math.log(b_exit / b_entry)


def spearman(x, y):
    if len(x) != len(y) or len(x) < 3:
        return None
    ax, ay = np.asarray(x, float), np.asarray(y, float)
    if ax.std() == 0 or ay.std() == 0:
        return None
    rx = np.argsort(np.argsort(ax)).astype(float)
    ry = np.argsort(np.argsort(ay)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def d2iso(d: date) -> str:
    return d.isoformat()


# ════════════════════════════════════════════════════════════════════════════
def main() -> None:
    res: dict = {"task": "T-267", "ledger": "S-744", "seed": SEED, "seed_flip": SEED_FLIP,
                 "n_null": N_NULL, "n_flip": N_FLIP,
                 "generated_at": date.today().isoformat()}

    # ── ① 事件与标题过滤(口径照 T-262) ─────────────────────────────────────
    events = cached("perp_events", lambda: pull(
        "events", "kind=eq.perp_listing&select=id,ts,symbols,title,source&order=ts.asc"))
    kept, drop_counter = [], Counter()
    for e in events:
        dec, reason = classify(e.get("title") or "")
        if dec == "drop":
            drop_counter[reason] += 1
            continue
        kept.append(e)

    token_events, prov = [], Counter()
    for e in kept:
        d = str(e["ts"])[:10]
        field = list(e.get("symbols") or [])
        parsed = extract_tickers(e.get("title") or "")
        toks = field if field else parsed
        if field:
            prov["symbols_field"] += len(field)
        else:
            prov["title_parsed"] += len(parsed)
        for sym in toks:
            token_events.append({"sym": sym, "d": d, "src": "symbols_field" if field else "title_parsed"})

    res["funnel_1_events"] = {
        "perp_listing_total": len(events),
        "kept_after_title_filter": len(kept),
        "dropped_by_rule": dict(drop_counter),
        "token_events": len(token_events),
        "ticker_provenance": dict(prov),
    }
    print(f"① 公告 {len(events)} → 过滤后 {len(kept)} → 事件 {len(token_events)}", flush=True)

    # ── ② 代币 → CoinGecko id(cg_coin_map 用发布版 key 读不到 ⇒ 用 asset_mcap_daily 的
    #    (symbol, coin_id) 对;下面用同 coin_id 的两个表价格对拍,不一致数写进结果) ──
    syms = sorted({t["sym"] for t in token_events})

    def coins_for_symbol(s: str) -> list[str]:
        for cand in (s, s.upper(), s.lower()):
            rs = pull_one("asset_mcap_daily",
                          f"select=coin_id&symbol=eq.{quote(cand, safe='')}&order=d.desc", limit=200)
            ids = sorted({r["coin_id"] for r in rs if r.get("coin_id")})
            if ids:
                return ids
        return []

    map_rows = cached("sym2coin", lambda: [
        {"symbol": s, "coin_ids": coins_for_symbol(s)} for s in syms])
    sym2coin = {}
    for r in map_rows:
        ids = r["coin_ids"]
        if len(ids) == 1:
            sym2coin[r["symbol"]] = ids[0]
        elif len(ids) > 1:
            sym2coin[r["symbol"]] = ids[0]  # 多个 ⇒ 取字典序第一个,并在报告里点名
    multi = {r["symbol"]: r["coin_ids"] for r in map_rows if len(r["coin_ids"]) > 1}

    def coin_of(sym: str):
        if sym in sym2coin:
            return sym2coin[sym]
        if sym.startswith("1000") and sym[4:] in sym2coin:
            return sym2coin[sym[4:]]
        return None

    unmapped = Counter()
    for t in token_events:
        t["coin_id"] = coin_of(t["sym"])
        if t["coin_id"] is None:
            unmapped[t["sym"]] += 1
    res["funnel_2_mapping"] = {
        "distinct_symbols": len(syms),
        "mapped_symbols": len({t["sym"] for t in token_events if t["coin_id"]}),
        "unmapped_symbols": len(unmapped),
        "unmapped_list": [{"symbol": s, "events": n} for s, n in unmapped.most_common()],
        "symbols_with_multiple_coin_ids": multi,
        "note": "cg_coin_map 用发布版 publishable key 读不到(HTTP 401 permission denied);映射取自 asset_mcap_daily 的 (symbol, coin_id) 对",
    }
    print(f"② 映射: {len(syms)} 个代码 → {len(sym2coin)} 个可映射;不可映射 {len(unmapped)}", flush=True)

    # ── ③ 价格(CoinGecko) ─────────────────────────────────────────────────
    # 卡上写的是 cg_coin_mcap_daily(coin_id, d, price) + cg_coin_map(symbol → coin_id)。
    # 实测:cg_coin_map 用发布版 key 读不到(HTTP 401 permission denied);
    #       cg_coin_mcap_daily 里 **没有 'bitcoin' / 'ethereum' / 'solana' / 'elrond-erd-2'**
    #       (HTTP 200、content-range */0)⇒ 它连卡上自己要求的「BTC 同源」都给不出来。
    #       asset_mcap_daily(symbol, coin_id, d, price, mcap, source=coingecko_pro_market_chart)
    #       是同一个上游源、带 symbol 主键、含 bitcoin 的全历史 ⇒ 本轮用它,
    #       并对两个表在都有的 coin_id 上逐日对拍(不一致数写进结果)。
    need = sorted({t["coin_id"] for t in token_events if t["coin_id"]} | {BTC_COIN})
    series: dict[str, Series] = {}
    for c in need:
        series[c] = load_series(c)
    btc = series.get(BTC_COIN)
    if not btc or len(btc) == 0:
        sys.exit("BTC(CoinGecko) 价格缺失,中止")
    res["price_source"] = {
        "table_used": "asset_mcap_daily",
        "table_preregistered": "cg_coin_mcap_daily",
        "deviation_reason": ("cg_coin_map 发布版 key 401;cg_coin_mcap_daily 无 bitcoin/ethereum/solana 等主流币"
                             "(HTTP 200、*/0),无法提供卡上要求的『BTC 同源』基准;"
                             "asset_mcap_daily 是同一上游 source=coingecko_pro_market_chart、带 symbol 主键、含 bitcoin 全历史"),
        "coins_pulled": len(need),
        "rows_total": int(sum(len(s) for s in series.values())),
        "btc_coin_id": BTC_COIN,
        "btc_rows": len(btc),
        "btc_first": btc.dates[0] if len(btc) else None,
        "btc_last": btc.dates[-1] if len(btc) else None,
    }
    print(f"③ 价格: {len(need)} 个 coin_id / {sum(len(s) for s in series.values())} 行", flush=True)

    # 对拍:cg_coin_mcap_daily vs asset_mcap_daily(同 coin_id 同日的价格)
    chk_coins = [c for c in need if c != BTC_COIN][:20] + [BTC_COIN]
    mism, chk_pairs, chk_coins_hit = 0, 0, 0
    for c in chk_coins:
        other = cached(f"cg_{c}", lambda c=c: pull(
            "cg_coin_mcap_daily",
            f"select=d,price&coin_id=eq.{quote(c, safe='')}&order=d.asc"))
        if not other:
            continue
        chk_coins_hit += 1
        o = {str(r["d"])[:10]: float(r["price"]) for r in other
             if r.get("price") not in (None, "") and str(r.get("d") or "")[:10]}
        s = series[c]
        for d, px in zip(s.dates, s.closes):
            if d in o:
                chk_pairs += 1
                if abs(o[d] - px) > 1e-8 * max(1.0, abs(o[d])):
                    mism += 1
    res["price_source"]["crosscheck_cg_coin_mcap_daily"] = {
        "coins_probed": len(chk_coins), "coins_present_in_cg_table": chk_coins_hit,
        "pairs": chk_pairs, "mismatches": mism}
    print(f"③ 对拍 cg_coin_mcap_daily: {chk_coins_hit} 个币有数据 / {chk_pairs} 对 / 不一致 {mism}", flush=True)

    # poa_fast 对拍(apparatus.price_on_or_after)
    rng_chk = np.random.default_rng(11)
    mism2, chk2 = 0, 0
    for c in chk_coins:
        s = series[c]
        if len(s) < 5:
            continue
        for _ in range(30):
            tgt = s.dates[int(rng_chk.integers(0, len(s)))]
            a = price_on_or_after(s.dates, s.closes, tgt, max_gap_days=MAX_GAP)
            b = s.poa(tgt)
            chk2 += 1
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
                mism2 += 1
    res["price_source"]["poa_selfcheck"] = {"pairs": chk2, "mismatches": mism2}

    # ── ④ 样本筛选 ──────────────────────────────────────────────────────────
    sample, funnel = [], Counter()
    for t in token_events:
        d = t["d"]
        if d < WINDOW_START:
            funnel["window_2020"] += 1
            continue
        if t["coin_id"] is None:
            funnel["no_cg_coin_id"] += 1
            continue
        s = series.get(t["coin_id"])
        if s is None or len(s) == 0:
            funnel["no_cg_price"] += 1
            continue
        if s.n_before(d) < 60:
            funnel["cg_lt_60d"] += 1
            continue
        if s.poa(d) is None or btc.poa(d) is None:
            funnel["no_entry_price"] += 1
            continue
        if s.poa(d2iso(date.fromisoformat(d) + timedelta(days=30))) is None:
            funnel["no_exit_price_30d"] += 1
            continue
        funnel["kept"] += 1
        t["series"] = s
        sample.append(t)
    res["funnel_3_sample"] = dict(funnel)
    res["sample_by_year"] = dict(sorted(Counter(t["d"][:4] for t in sample).items()))
    print(f"④ 样本 {len(sample)} 条(漏斗 {dict(funnel)})", flush=True)

    # ── ⑤ 事件级超额(主口径 d / 挪一天 d+1) ───────────────────────────────
    def build_rows(entry_offset: int) -> list[dict]:
        out = []
        for t in sample:
            s, d = t["series"], t["d"]
            e_day = d2iso(date.fromisoformat(d) + timedelta(days=entry_offset))
            entry = s.poa(e_day)
            b_entry = btc.poa(e_day)
            if entry is None or b_entry is None:
                continue
            row = {"sym": t["sym"], "coin": t["coin_id"], "d": d, "entry_day": e_day,
                   "entry": entry, "mcap_pre": s.mcap_oob(d2iso(date.fromisoformat(d) - timedelta(days=1)))}
            ok = True
            for h in HORIZONS:
                x_day = d2iso(date.fromisoformat(e_day) + timedelta(days=h))
                x, bx = s.poa(x_day), btc.poa(x_day)
                ex = log_excess(entry, x, b_entry, bx) if (x is not None and bx is not None) else None
                row[f"ex{h}"] = ex
                if ex is None:
                    ok = False
            if not ok:
                continue
            # 「之前 30 天收益」:事件与对照日用同一个口径(d−1 收盘 / d−31 收盘)
            c1, c2 = s.oob(d2iso(date.fromisoformat(d) - timedelta(days=1))), \
                s.oob(d2iso(date.fromisoformat(d) - timedelta(days=31)))
            row["pre30_ret"] = (c1 / c2 - 1.0) if (c1 and c2) else None
            out.append(row)
        return out

    rows0 = build_rows(0)
    rows1 = build_rows(1)
    res["main"] = {"entry_on_d": {f"h{h}": summarize([r[f"ex{h}"] for r in rows0 if r.get(f"ex{h}") is not None])
                                  for h in HORIZONS},
                   "entry_on_d_plus_1": {f"h{h}": summarize([r[f"ex{h}"] for r in rows1 if r.get(f"ex{h}") is not None])
                                         for h in HORIZONS}}
    print(f"⑤ 30 天超额中位数(entry d): {res['main']['entry_on_d']['h30'].get('median_pct')}%", flush=True)

    # ── ⑥ S-740 原判据(副:新价格源 / 新宇宙上的数字) ──────────────────────
    def criteria(rs, label):
        out = {"label": label}
        s30 = summarize([r["ex30"] for r in rs if r.get("ex30") is not None])
        out["a"] = {"n": s30.get("n"), "median_pct": s30.get("median_pct"), "mean_pct": s30.get("mean_pct"),
                    "pass": bool(s30.get("median_pct") is not None and s30["median_pct"] <= -3.0
                                 and (s30.get("mean_pct") or 0) < 0)}
        halves = []
        for lo, hi in (("2020-01-01", "2022-12-31"), ("2023-01-01", "9999-12-31")):
            v = [r["ex30"] for r in rs if r.get("ex30") is not None and lo <= r["d"] <= hi]
            halves.append({"window": f"{lo[:7]}→{hi[:7]}", "n": len(v),
                           "median_pct": (float(np.median(v) * 100) if v else None),
                           "mean_pct": (float(np.mean(v) * 100) if v else None)})
        out["halves"] = halves
        if halves[0]["median_pct"] is not None and halves[1]["median_pct"] is not None:
            s0, s1 = np.sign(halves[0]["median_pct"]), np.sign(halves[1]["median_pct"])
            out["c"] = {"same_sign": bool(s0 == s1), "sign": int(s0), "half2_sign": int(s1)}
        else:
            out["c"] = {"same_sign": None}
        v_all = [r["ex30"] for r in rs if r.get("ex30") is not None]
        keep = [r["ex30"] for r in rs if r.get("ex30") is not None
                and r.get("pre30_ret") is not None and r["pre30_ret"] <= PRE_MOVE_THRESHOLD]
        out["d"] = {"n_excluded": len(v_all) - len(keep), "n_kept": len(keep),
                    "median_all_pct": (float(np.median(v_all) * 100) if v_all else None),
                    "median_kept_pct": (float(np.median(keep) * 100) if keep else None),
                    "mean_kept_pct": (float(np.mean(keep) * 100) if keep else None),
                    "same_sign": (bool(np.sign(np.median(keep)) == np.sign(np.median(v_all)))
                                  if v_all and keep else None)}
        return out

    res["s740_criteria"] = {"entry_on_d": criteria(rows0, "entry on d"),
                            "entry_on_d_plus_1": criteria(rows1, "entry on d+1")}

    # (b) 随机日期对照(同代币、同年份、避开上线日前后 30 天)—— S-740 原口径
    listing_dates: dict[str, set[str]] = defaultdict(set)
    for t in sample:
        listing_dates[t["sym"]].add(t["d"])

    def build_eligible(rs, h, entry_offset=0):
        elig = {}
        for r in rs:
            s = r["series"] if "series" in r else series[r["coin"]]
            blocked = set()
            for ld in listing_dates.get(r["sym"], ()):  # 上线日前后 30 天不用
                base = date.fromisoformat(ld)
                for k in range(-30, 31):
                    blocked.add(d2iso(base + timedelta(days=k)))
            ok = []
            for dd in s.dates:
                if dd in blocked or dd < WINDOW_START:
                    continue
                x_day = d2iso(date.fromisoformat(dd) + timedelta(days=entry_offset + h))
                if s.poa(x_day) is None or btc.poa(dd) is None or btc.poa(x_day) is None:
                    continue
                ok.append(dd)
            elig[r["sym"]] = ok
        return elig

    def run_null(rs, h, entry_offset=0):
        elig = build_eligible(rs, h, entry_offset)
        ev_list = [(r["sym"], r["d"]) for r in rs]
        vals_actual = [r[f"ex{h}"] for r in rs if r.get(f"ex{h}") is not None]
        actual = float(np.median(vals_actual) * 100)
        n_empty = sum(1 for v in elig.values() if not v)

        def one(rng):
            return _one_null(rng, ev_list, rs, elig, h, series, btc, entry_offset)

        try:
            null = null_distribution(one, N_NULL, SEED, actual=actual)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}", "actual_median_pct": actual}
        p05 = float(np.percentile(null, 5))
        return {"actual_median_pct": actual, "n_null": int(null.size), "null_p05_pct": p05,
                "null_p50_pct": float(np.percentile(null, 50)), "null_mean_pct": float(null.mean()),
                "percentile_of_actual": percentile_of(actual, null),
                "pass_le_p05": bool(actual <= p05),
                "tokens_without_eligible_dates": n_empty,
                "median_eligible_dates_per_token": float(np.median([len(v) for v in elig.values()]))}

    res["s740_null_control"] = {"entry_on_d": {f"h{h}": run_null(rows0, h, 0) for h in HORIZONS},
                                "entry_on_d_plus_1": {f"h{h}": run_null(rows1, h, 1) for h in HORIZONS}}

    # ── ⑦ S-744 机制检验:按「之前 30 天收益」匹配的对照日 ──────────────────
    def mechanism(rs, entry_offset: int) -> dict:
        """返回匹配后的差 + 四条判据。"""
        # 对照日的候选:同代币、d ± 365、避开 [d−60, d+60]
        per_event = []
        for r in rs:
            s = series[r["coin"]]
            d = date.fromisoformat(r["d"])
            ev_pre = r.get("pre30_ret")
            if ev_pre is None:
                per_event.append({"r": r, "controls": [], "ok": False, "why": "no_pre30"})
                continue
            ctrls = []
            c = d - timedelta(days=CTRL_WINDOW)
            end = d + timedelta(days=CTRL_WINDOW)
            while c <= end:
                if not (d - timedelta(days=CTRL_EXCLUDE) <= c <= d + timedelta(days=CTRL_EXCLUDE)):
                    cd = c.isoformat()
                    if cd in s.idx:
                        p1 = s.oob(d2iso(c - timedelta(days=1)))
                        p2 = s.oob(d2iso(c - timedelta(days=31)))
                        if p1 and p2:
                            cpre = p1 / p2 - 1.0
                            if abs(cpre - ev_pre) <= CTRL_TOL:
                                x_day = d2iso(c + timedelta(days=30))
                                px_c, px_x = s.poa(cd), s.poa(x_day)
                                bx_c, bx_x = btc.poa(cd), btc.poa(x_day)
                                ex = log_excess(px_c, px_x, bx_c, bx_x)
                                if ex is not None:
                                    ctrls.append({"c": cd, "pre30": cpre, "ex30": ex})
                c += timedelta(days=1)
            per_event.append({"r": r, "controls": ctrls, "ok": len(ctrls) >= CTRL_MIN,
                              "why": "ok" if len(ctrls) >= CTRL_MIN else "lt20_controls"})
        entered = [p for p in per_event if p["ok"]]
        excluded = [{"sym": p["r"]["sym"], "d": p["r"]["d"], "n_controls": len(p["controls"]),
                     "why": p["why"]} for p in per_event if not p["ok"]]
        out = {
            "n_events_total": len(per_event),
            "n_entered": len(entered),
            "n_excluded_lt20_controls": len(excluded),
            "excluded_detail": excluded,
            "controls_per_event": summarize([len(p["controls"]) for p in per_event], scale=1.0),
            "n_controls_total": int(sum(len(p["controls"]) for p in per_event)),
        }
        if not entered:
            return out
        diffs, ev_ex, ctrl_ex, ev_pre = [], [], [], []
        for p in entered:
            r = p["r"]
            ev = r["ex30"]
            cm = float(np.mean([c["ex30"] for c in p["controls"]]))
            diffs.append(ev - cm)
            ev_ex.append(ev)
            ctrl_ex.append(cm)
            ev_pre.append(r.get("pre30_ret"))
        out["event_excess"] = summarize(ev_ex)
        out["matched_control_excess"] = summarize(ctrl_ex)
        out["matched_diff"] = summarize(diffs)
        # (a)
        med = float(np.median(diffs) * 100)
        out["a"] = {"median_pct": med, "mean_pct": float(np.mean(diffs) * 100),
                    "threshold_pct": -3.0, "pass": bool(med <= -3.0)}
        # (b) 事件间符号翻转检验:每次随机翻转每个事件的差,统计量 = 中位数
        arr = np.asarray(diffs, float)

        def one_flip(rng):
            signs = rng.choice(np.array([-1.0, 1.0]), size=arr.size)
            return float(np.median(arr * signs) * 100)

        try:
            null = null_distribution(one_flip, N_FLIP, SEED_FLIP, actual=med)
            out["b"] = {"n_flip": int(null.size), "statistic": "median of sign-flipped matched diffs",
                        "observed_median_pct": med,
                        "null_p05_pct": float(np.percentile(null, 5)),
                        "null_p50_pct": float(np.percentile(null, 50)),
                        "one_sided_p": percentile_of(med, null),
                        "pass": bool(percentile_of(med, null) is not None and percentile_of(med, null) <= 0.05)}
        except Exception as exc:  # noqa: BLE001
            out["b"] = {"error": f"{type(exc).__name__}: {exc}"}
        # (c) 两段同号
        halves = []
        for lo, hi in (("2020-01-01", "2022-12-31"), ("2023-01-01", "9999-12-31")):
            v = [d for p, d in zip(entered, diffs) if lo <= p["r"]["d"] <= hi]
            halves.append({"window": f"{lo[:7]}→{hi[:7]}", "n": len(v),
                           "median_pct": (float(np.median(v) * 100) if v else None),
                           "mean_pct": (float(np.mean(v) * 100) if v else None),
                           "frac_negative": (float((np.asarray(v) < 0).mean()) if v else None)})
        out["halves"] = halves
        out["halves"] = halves
        # 探索性(不是预注册判据,只报不判):按「上线前 30 天涨没涨」分组
        groups = {}
        for tag, sel in (("pre30>0", lambda r: (r.get("pre30_ret") or 0) > 0),
                         ("pre30<=0", lambda r: (r.get("pre30_ret") or 0) <= 0)):
            v = [d for p, d in zip(entered, diffs) if sel(p["r"])]
            ev = [p["r"]["ex30"] for p in entered if sel(p["r"])]
            groups[tag] = {
                "n": len(v),
                "matched_diff_median_pct": (float(np.median(v) * 100) if v else None),
                "matched_diff_mean_pct": (float(np.mean(v) * 100) if v else None),
                "matched_diff_frac_negative": (float((np.asarray(v) < 0).mean()) if v else None),
                "raw_event_ex30_median_pct": (float(np.median(ev) * 100) if ev else None),
            }
        out["exploratory_pre30_split"] = groups
        if halves[0]["median_pct"] is not None and halves[1]["median_pct"] is not None:
            s0, s1 = np.sign(halves[0]["median_pct"]), np.sign(halves[1]["median_pct"])
            out["c"] = {"same_sign": bool(s0 == s1), "sign": int(s0), "half2_sign": int(s1),
                        "pass": bool(s0 == s1)}
        else:
            out["c"] = {"same_sign": None, "pass": False}
        # (d)
        out["d"] = {"n_entered": len(entered), "threshold": 40, "pass": bool(len(entered) >= 40)}
        out["all_pass"] = bool(out["a"]["pass"] and out.get("b", {}).get("pass")
                               and out["c"].get("pass") and out["d"]["pass"])
        out["per_event"] = [{"sym": p["r"]["sym"], "coin": p["r"]["coin"], "d": p["r"]["d"],
                             "pre30_ret_pct": (p["r"].get("pre30_ret") * 100
                                               if p["r"].get("pre30_ret") is not None else None),
                             "event_ex30_pct": (p["r"]["ex30"] * 100 if p["r"].get("ex30") is not None else None),
                             "control_ex30_mean_pct": (float(np.mean([c["ex30"] for c in p["controls"]])) * 100),
                             "matched_diff_pct": (d * 100), "n_controls": len(p["controls"])}
                            for p, d in zip(entered, diffs)]
        return out

    res["mechanism"] = {"entry_on_d": mechanism(rows0, 0),
                        "entry_on_d_plus_1": mechanism(rows1, 1)}

    # ── ⑧ 副:上线前市值三分位 ─────────────────────────────────────────────
    def tertile_table(rs):
        vals = [(r["mcap_pre"], r) for r in rs if r.get("mcap_pre") and r.get("ex30") is not None]
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

    # ── ⑨ 副:上线后 7 天资金费 vs 30 天超额 ────────────────────────────────
    fu_rows = cached("funding_windows", lambda: [
        {"sym": r["sym"], "d": r["d"],
         "rows": pull("v_funding_daily",
                      f"select=symbol,d,funding_rate,n&symbol=eq.{quote(r['sym'], safe='')}"
                      f"&d=gte.{d2iso(date.fromisoformat(r['d']) + timedelta(days=1))}"
                      f"&d=lte.{d2iso(date.fromisoformat(r['d']) + timedelta(days=7))}&order=d.asc")}
        for r in rows0])
    fu_by_sym: dict[str, dict[str, float]] = defaultdict(dict)
    for blob in fu_rows:
        for rr in blob["rows"]:
            try:
                fu_by_sym[blob["sym"]][str(rr["d"])[:10]] = float(rr["funding_rate"])
            except (TypeError, ValueError, KeyError):
                pass

    def funding7(sym: str, d: str):
        ser = fu_by_sym.get(sym) or {}
        base = date.fromisoformat(d)
        vals = [ser[d2iso(base + timedelta(days=k))] for k in range(1, 8)
                if d2iso(base + timedelta(days=k)) in ser]
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

    res["events_detail"] = [{"sym": r["sym"], "coin": r["coin"], "d": r["d"],
                             "ex30_pct": (r["ex30"] * 100 if r.get("ex30") is not None else None),
                             "ex60_pct": (r["ex60"] * 100 if r.get("ex60") is not None else None),
                             "pre30_ret_pct": (r["pre30_ret"] * 100 if r.get("pre30_ret") is not None else None),
                             "mcap_pre": r.get("mcap_pre")}
                            for r in rows0]

    (OUT / "t267_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print("写出 t267_results.json", flush=True)
    print(json.dumps({k: res[k] for k in ("funnel_1_events", "funnel_3_sample", "main", "s740_criteria")},
                     ensure_ascii=False, indent=1, default=float)[:3000], flush=True)


def _one_null(rng, ev_list, rs, elig, h, series, btc, entry_offset=0):
    """S-740 随机日期对照的一次抽样(返回中位数,单位 %)。entry_offset = S-665 的挪一天口径。"""
    picks = random_dates_like(ev_list, elig, rng)
    vals = []
    for (sym, _), (_, dd), r in zip(ev_list, picks, rs):
        if dd is None:
            continue
        s = series[r["coin"]]
        e_day = d2iso(date.fromisoformat(dd) + timedelta(days=entry_offset))
        e, be = s.poa(e_day), btc.poa(e_day)
        x_day = d2iso(date.fromisoformat(dd) + timedelta(days=entry_offset + h))
        x, bx = s.poa(x_day), btc.poa(x_day)
        ex = log_excess(e, x, be, bx)
        if ex is not None:
            vals.append(ex)
    if not vals:
        return float("nan")
    return float(np.median(vals) * 100)


if __name__ == "__main__":
    main()
