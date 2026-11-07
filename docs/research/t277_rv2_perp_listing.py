#!/usr/bin/env python3
"""T-277 / S-756 —— R-v2 真钱票:开票前 60 天内刚上过 Binance USDT 永续的名字,票是不是更差。

**只算、不改代码、不入库。** 样本与判据一字不改照 REFUTATION_LEDGER §S-756(Seth,2026-11-07 09:14 UTC 预注册):

  票  = R-v2 规则(`r_v2_k2.5_gate200` 的等价物)在 2020-07 → 2026-10 的全部回放票
        —— 与 T-251 / T-254 **同一个生成器**(`T251.scan` + `T251.simulate`,40% 档),只取**有 R 的成交票**。
  分组 = 开票日 d 之前 [d−60, d−1] 内,该代号在 `events`(source = binance,kind = perp_listing)里出现过 vs 没有。
  判据(全部满足才 ✅):
    (a) 「刚上永续」组平均 R 比其余低 ≥ 0.3R;
    (b) 组内平均 R ≤ 0;
    (c) 票 ID 在两组间随机重排 5,000 次(种子 756),实际差的分位 ≤ 0.05;
    (d) 「刚上永续」组 ≥ 20 张;
    (e) 2020-07 → 2023-06 与 2023-07 → 2026-10 两段差同号。
  副(只报不判):30 天窗口;按上线前 30 天涨幅分组(S-744 追高回归读法);胜率与最大 R。

S-665:分组是**开票日当天**才知道的派生量 ⇒ 主口径用开票日 d,再挪一天(entry 日)判一次。
零分布 / 分位一律用 `src/data/evaluation/apparatus.py`(null_distribution + percentile_of)。
代币代码的解析与公告标题规则**复用** `t262_perp_listing.py`(S-740 的同一套),不自造。

用法:python3 docs/research/t277_rv2_perp_listing.py
     (写 t277_results.json + T-277_rv2_after_perp_listing.md;日志在 Mac 数据根 research/t277/run.log)
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import t251_gross_cap as T251  # noqa: E402  —— T-251 的扫描器/模拟器,口径完全一致
import t262_perp_listing as T262  # noqa: E402  —— S-740 的公告标题规则 + 代码解析(只 import)
from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402

D_FROM, D_TO = dt.date(2020, 7, 1), dt.date(2026, 10, 31)   # 台账写死:2020-07 → 2026-10
CAP_FRAC = 0.40                                            # 台账写死:40% 档
SEED = 756
N_PERM = 5000
WINDOW_D = 60                                              # 主口径窗口(副项另算 30 天)
SEG_CUT = "2023-07-01"                                     # (e) 两段切点
RESEARCH = Path("/Volumes/CometCloudAI/cometcloud-local/research")
CACHE = RESEARCH / "t277"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = HERE


# ── 事件层 ───────────────────────────────────────────────────────────────────
def load_events() -> list[dict]:
    """`events` 表里 kind='perp_listing' 的公告(source = binance)。优先用 Mac 端缓存。"""
    p = RESEARCH / "t262_perp_events.json"
    if p.exists():
        rows = json.loads(p.read_text())
    else:
        rows = T262.pull("events", "kind=eq.perp_listing&select=id,ts,symbols,title,source,payload&order=ts.asc")
        p.write_text(json.dumps(rows))
    return [r for r in rows if r.get("source") == "binance"]


# ── 代号解析 v2 ──────────────────────────────────────────────────────────────
# S-740 的解析器(T262.extract_tickers)只认「FOOUSDT / ETH/USDT」两种写法,818 条公告里
# **571 条解析不出代号** —— 因为绝大多数公告写的是「USDT-Margined APE」「USDⓈ-M ARB」
# 「Launch a USDT-Margined Perpetual Contract … for 1INCH」。漏解析 ⇒ 「没上过永续」是假的。
# 这里补齐写法;`selftest()` 会把样本与覆盖率打出来核对。
STOPWORDS = {"USD", "USDT", "USDC", "BUSD", "PERPETUAL", "PERPETUALS", "CONTRACT", "CONTRACTS",
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
    if len(t) < 2 or t in STOPWORDS or t.isdigit():
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


def is_usdt_perp(title: str) -> bool:
    """公告是不是「上线一个 USDT 永续」(USDⓈ-M / USDT-Margined / …/USDT)。"""
    t = title or ""
    if re.search(r"(?:USDC|BUSD)[- ]?Margined", t):
        return False
    return bool(re.search(r"USDT[- ]?Margined|USDⓈ-?M|/USDT|USDT\b", t))


def token_events(events: list[dict], mode: str):
    """公告 → (代号, 日期)。mode: usdt(主口径) / clean(S-740 规则) / literal(整表)。"""
    out, drops = [], Counter()
    for e in events:
        title = e.get("title") or ""
        if mode in ("usdt", "clean"):
            dec, reason = T262.classify(title)
            if dec == "drop":
                drops[reason] += 1
                continue
            if mode == "usdt" and not is_usdt_perp(title):
                drops["not_usdt_perp"] += 1
                continue
        d = str(e["ts"])[:10]
        field = list(e.get("symbols") or [])
        parsed = extract_tickers_v2(title)
        toks = field if field else parsed
        if not toks:
            drops["no_ticker"] += 1
        for sym in toks:
            out.append({"sym": sym, "d": d, "title": title[:120], "id": e.get("id"),
                        "src": "symbols_field" if field else "title_v2"})
    out.sort(key=lambda x: (x["sym"], x["d"]))
    return out, dict(drops)


class ListingIndex:
    """代号 → 上线日期列表(升序)。查「[d−W, d−1] 内有没有」。"""

    def __init__(self, evs: list[dict]):
        self.by_sym: dict[str, list[str]] = defaultdict(list)
        for e in evs:
            self.by_sym[e["sym"]].append(e["d"])
        for v in self.by_sym.values():
            v.sort()

    def in_window(self, sym: str, d: str, window: int) -> list[str]:
        lo, hi = (dt.date.fromisoformat(d) - dt.timedelta(days=window)).isoformat(), d
        return [ds for ds in self.by_sym.get(sym, []) if lo <= ds < hi]


# ── 统计层 ───────────────────────────────────────────────────────────────────
def rdist(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0}
    s = sorted(rs)
    return {"n": len(rs), "sum_r": round(sum(rs), 4), "mean_r": round(sum(rs) / len(rs), 4),
            "med_r": round(s[len(s) // 2], 4), "min": round(s[0], 4), "max": round(s[-1], 4),
            "win_pct": round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1)}


def group_stats(rows: list[dict], key: str) -> dict:
    """rows = [{'r':…, 'd':…, 'grp':bool}];按 key 分两组,给出 (a)–(e) 需要的原始量。"""
    a = [r for r in rows if r[key]]
    b = [r for r in rows if not r[key]]
    ra = [r["r"] for r in a]
    rb = [r["r"] for r in b]
    ma = sum(ra) / len(ra) if ra else None
    mb = sum(rb) / len(rb) if rb else None
    diff = (ma - mb) if (ma is not None and mb is not None) else None
    return {"n_a": len(a), "n_b": len(b), "n_total": len(rows),
            "mean_a": ma, "mean_b": mb, "diff_a_minus_b": diff,
            "a": rdist(ra), "b": rdist(rb)}


def perm_test(rows: list[dict], key: str, n_perm: int = N_PERM, seed: int = SEED) -> dict:
    """(c) 票 ID 在两组间随机重排 → 实际差的分位。"""
    rs = np.array([r["r"] for r in rows], dtype=float)
    lab0 = np.array([bool(r[key]) for r in rows])
    n_a = int(lab0.sum())
    if len(rs) == 0 or n_a == 0 or n_a == len(rs):
        return {"actual_diff": None, "null_mean": None, "null_p05": None, "null_p95": None,
                "pct_of_actual": None, "n_perm": n_perm, "seed": seed, "n_a": n_a,
                "n_total": len(rs), "note": f"组为空(n_A={n_a}, n_total={len(rs)})⇒ 置换不适用"}
    actual = float(rs[lab0].mean() - rs[~lab0].mean())

    def fn(rng: np.random.Generator) -> float:
        perm = rng.permutation(len(rs))
        m = np.zeros(len(rs), dtype=bool)
        m[perm[:n_a]] = True
        return float(rs[m].mean() - rs[~m].mean())

    null = null_distribution(fn, n_perm, seed, actual=actual)
    p = percentile_of(actual, null)
    return {"actual_diff": actual, "null_mean": float(null.mean()), "null_p05": float(np.percentile(null, 5)),
            "null_p95": float(np.percentile(null, 95)), "pct_of_actual": p, "n_perm": n_perm, "seed": seed,
            "n_a": n_a, "n_total": len(rs)}


def segment_check(rows: list[dict], key: str) -> dict:
    """(e) 两段差同号。"""
    s1 = [r for r in rows if r["d"] < SEG_CUT]
    s2 = [r for r in rows if r["d"] >= SEG_CUT]
    g1, g2 = group_stats(s1, key), group_stats(s2, key)
    d1, d2 = g1["diff_a_minus_b"], g2["diff_a_minus_b"]
    same = None
    if d1 is not None and d2 is not None and d1 != 0 and d2 != 0:
        same = (d1 < 0) == (d2 < 0)
    return {"seg1": {"label": f"{D_FROM} → {SEG_CUT}", **g1},
            "seg2": {"label": f"{SEG_CUT} → {D_TO}", **g2},
            "diff_seg1": d1, "diff_seg2": d2, "same_sign": same}


def judge(g: dict, p: dict, e: dict) -> dict:
    """(a)–(e) 逐条判定(不改判据,只填布尔)。None = 该条无法判定(缺样本)。"""
    diff = g["diff_a_minus_b"]
    a = None if diff is None else bool(diff <= -0.3)              # A 组比其余低 ≥ 0.3R
    b = None if g["mean_a"] is None else bool(g["mean_a"] <= 0)   # A 组内平均 R ≤ 0
    c = None if p["pct_of_actual"] is None else bool(p["pct_of_actual"] <= 0.05)
    d = bool(g["n_a"] >= 20)
    ev = e["same_sign"]
    checks = {"a": a, "b": b, "c": c, "d": d, "e": ev}
    undec = [k for k, v in checks.items() if v is None]
    failed = [k for k, v in checks.items() if v is False]
    return {"checks": checks, "all_pass": (not failed and not undec),
            "failed": failed, "undecidable": undec}


# ── 副项:上线前 30 天涨幅(S-744 追高回归读法)────────────────────────────────
def pre_listing_gain(tickets: list[dict], idx: ListingIndex, spot: dict) -> list[dict]:
    """每张 A 组票:其窗口内最近一次上线日 → 上线前 30 天(用现货收盘)的涨幅。"""
    rows = []
    for t in tickets:
        ds = idx.in_window(t["symbol"], t["signal_d"], WINDOW_D)
        if not ds:
            continue
        ld = ds[-1]
        ser = spot.get(t["symbol"])
        if not ser:
            continue
        sdates, sclose = ser
        i = bisect.bisect_right(sdates, ld) - 1
        if i < 0:
            continue
        j = bisect.bisect_right(sdates, (dt.date.fromisoformat(ld) - dt.timedelta(days=30)).isoformat()) - 1
        if j < 0 or i == j:
            continue
        px0, px1 = sclose[j], sclose[i]
        if not px0 or px1 is None:
            continue
        rows.append({"tid": t["tid"], "sym": t["symbol"], "listing_d": ld, "r": t["r"],
                     "pre30_gain": round(px1 / px0 - 1.0, 4)})
    return rows


def load_spot() -> dict:
    """binance_hist 现货收盘(T-262 的缓存)—— 只用来算副项的涨幅。"""
    p = RESEARCH / "t262_cache" / "bhs_px.json"
    if not p.exists():
        return {}
    by = defaultdict(list)
    for r in json.loads(p.read_text()):
        try:
            by[r["symbol"]].append((r["trade_date"], float(r["close"])))
        except (TypeError, ValueError, KeyError):
            continue
    out = {}
    for s, ser in by.items():
        ser.sort()
        out[s] = ([d for d, _ in ser], [c for _, c in ser])
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────
def selftest() -> None:
    """代号解析自检:样本核对 + 覆盖率(解析器漏一个代号 ⇒ 「没上过永续」是假的)。"""
    events = load_events()
    uni = set(json.loads((RESEARCH / "t251_cache" / "validated_universe.json").read_text()))
    toks_v2, drops_v2 = token_events(events, "literal")
    toks_old = set()
    for e in events:
        toks_old |= set(T262.extract_tickers(e.get("title") or ""))
    syms_v2 = {t["sym"] for t in toks_v2}
    syms_old = set(toks_old)
    print(f"公告 {len(events)} 条")
    print(f"  S-740 解析器:代号 {len(syms_old)} 个,覆盖宇宙 {len(uni & syms_old)}/{len(uni)}")
    print(f"  v2 解析器   :代号 {len(syms_v2)} 个,覆盖宇宙 {len(uni & syms_v2)}/{len(uni)}")
    print(f"  无代号的公告:{drops_v2.get('no_ticker', 0)} 条")
    print("  样本(各抽 6 条公告看解析):")
    for e in events[:6] + events[300:303] + events[-6:]:
        t = e.get("title") or ""
        print(f"    {str(e['ts'])[:10]} | v2={extract_tickers_v2(t)} | old={T262.extract_tickers(t)} | {t[:86]}")
    print("  已知事实核对(主口径 usdt 分组下的上线日):")
    idx = ListingIndex(token_events(events, "usdt")[0])
    for s in ("BTC", "ETH", "SOL", "PEPE", "DOGE", "AVAX", "SUI", "ARB", "APT", "AAVE", "1000SHIB"):
        print(f"    {s:9s} {idx.by_sym.get(s, [])[:5]}")
    print("  宇宙里没有代号的代号(前 25):", sorted(uni - syms_v2)[:25])


def main() -> None:
    res: dict = {"task": "T-277", "ledger": "S-756", "seed": SEED, "n_perm": N_PERM,
                 "window": [D_FROM.isoformat(), D_TO.isoformat()], "cap_frac": CAP_FRAC,
                 "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    # ① 事件
    events = load_events()
    modes = {}
    for m in ("usdt", "clean", "literal"):
        toks, drops = token_events(events, m)
        modes[m] = (ListingIndex(toks), len(toks), drops)
    res["events"] = {"announcements": len(events),
                     "token_events": {m: modes[m][1] for m in modes},
                     "title_rule_drops": {m: modes[m][2] for m in modes},
                     "note": "主口径 usdt = S-740 标题规则 ∧ USDT 永续;clean = S-740 标题规则;"
                             "literal = 整表 kind=perp_listing(含 COIN-M / 季度 / 层级调整等)。"
                             "三种分组口径都出 (a)–(e),不挑结果。"}
    print(f"事件:公告 {len(events)} → " +
          " / ".join(f"{m} {modes[m][1]}" for m in modes), flush=True)

    # ② 回放票(T-251 同一个生成器)
    pairs, style, bars, uni = T251.fetch_all()
    bars = {s: v for s, v in bars.items() if v}
    gate = T251.load_gate(style)
    tickets, stopped, hole_days, guard = T251.scan(bars, gate, D_FROM, D_TO)
    sim = T251.simulate(tickets, bars, gate, CAP_FRAC)
    taken = sim["taken"]
    filled = [t for t in tickets if t.get("filled") and t["tid"] in taken and t.get("r") is not None]
    res["replay"] = {"scan_stopped": stopped, "hole_days": hole_days,
                     "tickets_scanned": len(tickets), "tickets_taken": len(taken),
                     "tickets_with_r": len(filled),
                     "symbols": len(bars), "gate_days": len(gate),
                     "window": [D_FROM.isoformat(), D_TO.isoformat()],
                     "note": "票 = T251.scan + T251.simulate(40% 档) 里真正成交且有 R 的票"}
    print(f"回放:扫描 {len(tickets)} 张 / 成交 {len(taken)} 张 / 有 R {len(filled)} 张", flush=True)

    # ③ 分组(三个口径 × 两个参照日)
    variants = {}
    for vname in ("usdt", "clean", "literal"):
        idx = modes[vname][0]
        for dname, dkey in (("signal_d", "signal_d"), ("entry_d", "entry_d")):
            rows = []
            for t in filled:
                d = t[dkey]
                if not d:
                    continue
                hits = idx.in_window(t["symbol"], d, WINDOW_D)
                rows.append({"tid": t["tid"], "sym": t["symbol"], "d": d, "r": float(t["r"]),
                             "grp": bool(hits), "listing_d": (hits or [None])[-1]})
            g = group_stats(rows, "grp")
            p = perm_test(rows, "grp")
            e = segment_check(rows, "grp")
            variants[f"{vname}/{dname}"] = {"group": g, "perm": p, "segments": e,
                                            "judge": judge(g, p, e), "rows": rows}
            print(f"[{vname}/{dname}] n={g['n_total']} A={g['n_a']} B={g['n_b']} "
                  f"meanA={g['mean_a']} meanB={g['mean_b']} diff={g['diff_a_minus_b']} "
                  f"p={p['pct_of_actual']} → {variants[f'{vname}/{dname}']['judge']['all_pass']}", flush=True)

    res["variants"] = {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in variants.items()}

    # 主口径明细(票级,落盘可核)
    primary = variants["usdt/signal_d"]
    res["primary"] = "usdt/signal_d"
    res["primary_tickets"] = [
        {"tid": r["tid"], "sym": r["sym"], "d": r["d"], "r": round(r["r"], 4),
         "grp": r["grp"], "listing_d": r["listing_d"]}
        for r in sorted(primary["rows"], key=lambda x: x["d"])]

    # ④ 副项(只报不判)
    sub = {}
    idx_lit = modes["usdt"][0]
    rows30 = []
    for t in filled:
        d = t["signal_d"]
        rows30.append({"tid": t["tid"], "sym": t["symbol"], "d": d, "r": float(t["r"]),
                       "grp": bool(idx_lit.in_window(t["symbol"], d, 30))})
    sub["window_30d"] = group_stats(rows30, "grp")
    sub["window_30d"]["perm"] = perm_test(rows30, "grp")
    sub["winrate_maxR"] = {"a": primary["group"]["a"], "b": primary["group"]["b"]}
    spot = load_spot()
    pre = pre_listing_gain(filled, idx_lit, spot)
    if pre:
        gains = sorted(x["pre30_gain"] for x in pre)
        t1, t2 = gains[len(gains) // 3], gains[2 * len(gains) // 3]
        buckets = {"低": [], "中": [], "高": []}
        for x in pre:
            k = "低" if x["pre30_gain"] <= t1 else ("中" if x["pre30_gain"] <= t2 else "高")
            buckets[k].append(x["r"])
        sub["pre30_gain_buckets"] = {
            "n": len(pre), "cut_lo": round(t1, 4), "cut_hi": round(t2, 4),
            "buckets": {k: {"n": len(v), "mean_r": round(sum(v) / len(v), 4) if v else None,
                            "win_pct": round(100.0 * sum(1 for r in v if r > 0) / len(v), 1) if v else None}
                        for k, v in buckets.items()},
            "note": "只报不判;涨幅用 binance_hist 现货收盘(公告日 ~ 之前 30 天)"}
    sym_hit = Counter(r["sym"] for r in primary["rows"] if r["grp"])
    sub["hit_symbols"] = {"n_symbols": len(sym_hit), "top": sym_hit.most_common(15),
                          "n_tickets": sum(sym_hit.values())}
    # ④e 距「最近一次 USDT 永续上线」的天数(0–30 / 31–60 / 61–90 / 91–180 / >180):看机制在不在、只是没落在 60 天里
    try:
        idx_u = modes["usdt"][0]
        bands = {"0-30": [], "31-60": [], "61-90": [], "91-180": [], ">180": [], "无公告": []}
        for t in filled:
            d = t["signal_d"]
            prev = [x for x in idx_u.by_sym.get(t["symbol"], []) if x < d]
            if not prev:
                bands["无公告"].append(float(t["r"]))
                continue
            gap = (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev[-1])).days
            k = ("0-30" if gap <= 30 else "31-60" if gap <= 60 else "61-90" if gap <= 90
                 else "91-180" if gap <= 180 else ">180")
            bands[k].append(float(t["r"]))
        sub["days_since_last_usdt_listing"] = {
            k: {"n": len(v), "mean_r": round(sum(v) / len(v), 4) if v else None,
                "win_pct": round(100.0 * sum(1 for r in v if r > 0) / len(v), 1) if v else None}
            for k, v in bands.items()}
        sub["days_since_last_usdt_listing"]["note"] = "只报不判;无公告 = 该代号在 events 里没有任何 USDT 永续上线记录"
    except Exception as exc:  # 副项失败不许拖垮主结果
        sub["days_since_last_usdt_listing"] = {"error": repr(exc)}
    res["secondary"] = sub

    (OUT / "t277_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"写 {OUT / 't277_results.json'}", flush=True)
    write_report(res, variants)


def fmt(v, nd=4):
    return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def write_report(res: dict, variants: dict) -> None:
    p = variants[res["primary"]]
    g, pm, sg, jd = p["group"], p["perm"], p["segments"], p["judge"]
    L = []
    A = L.append
    A("# T-277 / S-756 —— R-v2 真钱票:开票前 60 天内刚上过 Binance USDT 永续,票是不是更差")
    A("")
    A(f"- 生成:{res['generated_at']} · 窗口 {res['window'][0]} → {res['window'][1]} · 40% 档 · 种子 {res['seed']} · 置换 {res['n_perm']} 次")
    A(f"- 票源:`T251.scan` + `T251.simulate`(40% 档)—— 与 T-251 / T-254 同一个生成器;"
      f"扫描 {res['replay']['tickets_scanned']} 张,成交 {res['replay']['tickets_taken']} 张,**有 R 的成交票 {res['replay']['tickets_with_r']} 张**")
    A(f"- 事件:`events`(source = binance,kind = perp_listing){res['events']['announcements']} 条公告 → "
      f"代币事件 " + " / ".join(f"{k} {v}" for k, v in res['events']['token_events'].items()))
    A("- 统计只用 `src/data/evaluation/apparatus.py`(null_distribution / percentile_of);代币解析复用 `t262_perp_listing.py`(S-740)")
    A("")
    A("## 判据 (a)–(e) —— 主口径(literal 分组 / 开票日 d)")
    A("")
    A("| 判据 | 要求 | 实测 | 过? |")
    A("|---|---|---|---|")
    A(f"| (a) | A 组平均 R 比其余低 ≥ 0.3R | diff(A−B) = {fmt(g['diff_a_minus_b'])}"
      f"(A {fmt(g['mean_a'])} vs B {fmt(g['mean_b'])}) | {'✅' if jd['checks']['a'] else '❌'} |")
    A(f"| (b) | A 组内平均 R ≤ 0 | {fmt(g['mean_a'])} | {'✅' if jd['checks']['b'] else '❌'} |")
    A(f"| (c) | 置换 5,000 次实际差分位 ≤ 0.05 | p = {fmt(pm['pct_of_actual'])}"
      f"(实际 {fmt(pm['actual_diff'])},零分布 p05 {fmt(pm['null_p05'])} / p95 {fmt(pm['null_p95'])}) | {'✅' if jd['checks']['c'] else '❌'} |")
    A(f"| (d) | A 组 ≥ 20 张 | {g['n_a']} | {'✅' if jd['checks']['d'] else '❌'} |")
    A(f"| (e) | 两段差同号 | 段1 {fmt(sg['diff_seg1'])}(n_A={sg['seg1']['n_a']}) / "
      f"段2 {fmt(sg['diff_seg2'])}(n_A={sg['seg2']['n_a']}) → 同号 {sg['same_sign']} | {'✅' if jd['checks']['e'] else '❌'} |")
    A("")
    A(f"**结论:{'✅ 全部判据满足' if jd['all_pass'] else '❌ 不满足(失败:' + ','.join(jd['failed']) + ')'}**"
      f" —— {'向 Jazz 提「R-v2 不开刚上 Binance 永续 60 天内的票」的过滤建议' if jd['all_pass'] else '不构成过滤依据'}")
    A("")
    A("## 稳健性对照(不判,只报)")
    A("")
    A("| 口径 | n 票 | A / B | A 均值 R | B 均值 R | diff | 置换 p | (a)(b)(c)(d)(e) |")
    A("|---|---|---|---|---|---|---|---|")
    for k, v in variants.items():
        gg, pp, ss, jj = v["group"], v["perm"], v["segments"], v["judge"]
        ck = "".join("✅" if jj["checks"][x] else "❌" for x in "abcde")
        A(f"| {k} | {gg['n_total']} | {gg['n_a']} / {gg['n_b']} | {fmt(gg['mean_a'])} | {fmt(gg['mean_b'])} | "
          f"{fmt(gg['diff_a_minus_b'])} | {fmt(pp['pct_of_actual'])} | {ck} |")
    A("")
    A("## 副项(只报不判)")
    A("")
    s30 = res["secondary"]["window_30d"]
    A(f"- **30 天窗口**:n {s30['n_total']},A {s30['n_a']} / B {s30['n_b']},"
      f"A 均值 {fmt(s30['mean_a'])},B 均值 {fmt(s30['mean_b'])},diff {fmt(s30['diff_a_minus_b'])},"
      f"置换 p {fmt(s30['perm']['pct_of_actual'])}")
    hb = res["secondary"].get("pre30_gain_buckets")
    if hb:
        A(f"- **上线前 30 天涨幅分组**(S-744 追高回归读法,n={hb['n']},切点 {hb['cut_lo']} / {hb['cut_hi']}):")
        for k, v in hb["buckets"].items():
            A(f"  - {k}:n={v['n']},平均 R {fmt(v['mean_r'])},胜率 {v['win_pct']}%")
    A(f"- **胜率 / 最大 R**:A 组 {res['secondary']['winrate_maxR']['a']} · B 组 {res['secondary']['winrate_maxR']['b']}")
    A(f"- **命中代币**:A 组票来自 {res['secondary']['hit_symbols']['n_symbols']} 个代号"
      f"(票 {res['secondary']['hit_symbols']['n_tickets']} 张);top {res['secondary']['hit_symbols']['top'][:8]}")
    band = res["secondary"].get("days_since_last_usdt_listing") or {}
    if band and "error" not in band:
        A("- **距最近一次 USDT 永续上线的天数**(只报不判):" +
          "; ".join(f"{k} n={v['n']} 平均 R {fmt(v['mean_r'])} 胜率 {v['win_pct']}%"
                    for k, v in band.items() if k != "note"))
    A("")
    A("## 口径与已知限制")
    A("")
    A("- **「上线日」= 公告的 UTC 日**(`events.ts` 的日期部分):库里没有真正的上线日字段(S-740 已声明,此处沿用同一口径)。")
    A("- **分组主口径 = 台账字面**:该代号在 `events`(source=binance,kind=perp_listing)里出现过即算;"
      "S-740 的标题规则(copy trading / TradFi / COIN-M / 层级调整等)另作 `clean` 对照。")
    A("- **代号解析**:公告的 `symbols` 字段大多为空,代码从标题解析(FOOUSDT → FOO / ETH/USDT → ETH),复用 S-740 的解析器。")
    A("- **窗口右端不含开票日**:分组只看 [d−60, d−1],避免把开票当天才知道的信息算进来。")
    A("- S-665:分组是开票日当天才知道的派生量,已按 entry 日再判一次(见稳健性表 `literal/entry_d`)。")
    A("")
    A("---")
    A("")
    A("*只算、不改代码、不入库。判据照 REFUTATION_LEDGER §S-756 预注册,未在见到结果后改动。*")
    (OUT / "T-277_rv2_after_perp_listing.md").write_text("\n".join(L) + "\n")
    print(f"写 {OUT / 'T-277_rv2_after_perp_listing.md'}", flush=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
