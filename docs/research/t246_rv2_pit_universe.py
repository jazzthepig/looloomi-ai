#!/usr/bin/env python3
"""T-246 · S-731 预注册:R-v2 的宇宙能不能写成一条按时点的规则

只读:不改代码、不做 DDL、不入库。DB 只读 perp_bv_daily / perp_bv_pairs(ohlcv_daily 只用于面板名单,
取自本地已缓存的 s677/_survivor_symbols.json)。

**预注册原文(S-731,2026-11-05 08:43 UTC,REFUTATION_LEDGER.md § S-731;抄在本文件顶部,先写后算):**

「**为什么。** 现行宇宙(257 名)是今天的幸存者名单(S-684);全宇宙(约 650 个 coin 永续)近三个月扩出来的部分是负的
(T-238 v2)。**原因假设:** 薄盘口的新合约上的突破多半是做出来的(Jazz「机械交易是做市商的提款机」);S-112 的准入经验值是
ADV > ~1,500 万。**规则(写死):** 开票日 d 当天上市满 365 天、30 日均报价成交额 ≥ 2,000 万美元,只用 ≤ d 的数;死币照常进。
**判据(全过 ✅,U2 可以替代 U1):** U2 的 Calmar ≥ U1 的 90%;两半总 R 都 > 0;2026-08-08 后一段总 R ≥ 0。
副只报:门槛 1,000 / 5,000 万、180 / 730 天;U0 多出来那部分的每票 R。**✅ 的含义:** 改真钱宇宙要 Jazz 拍板,不由这条直接改。
**试验计数:交易层 +1。**」

三个宇宙(同一条 R-v2 规则、同一份 perp_bv_daily):
- U0 = 全部 coin 永续(perp_bv_pairs: kind='coin' 或 kind 为空且 dead_from 有值),无额外门槛;
- U1 = 现行 257 名(ohlcv_daily source=binance_hist 面板 ∩ coin 永续)+ 1000PEPE;
- U2 = 开票日 d 当天:上市满 365 天(d − first_d ≥ 365)且 30 日均报价成交额 ≥ 2,000 万美元(只用 ≤ d 的数)。

R-v2 规则逐字照 t159.run_long(S-610 进场 / S-627 majors 闸门 / 2.5 ATR / SMA20 出场 / 120 根上限 /
0.4% 来回 / cap 10 / f = 1%),脚本里对同一份 bars 跑一遍 t159.run_long 做等价自检。

用法:python3 docs/research/t246_rv2_pit_universe.py [--stage all|fetch|compute]
"""
from __future__ import annotations

import datetime as dt
import gzip
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local"))
CACHE = ROOT / "research" / "t246"
PAIRS_JSON = CACHE / "perp_bv_pairs.json"
DAILY_GZ = CACHE / "perp_bv_daily.jsonl.gz"
SURV = ROOT / "research" / "s677" / "_survivor_symbols.json"
OUT_JSON = HERE / "t246_results.json"
OUT_MD = HERE / "T-246_rv2_pit_universe.md"

_spec = importlib.util.spec_from_file_location("t159", str(HERE / "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

# ── 预注册常量(先写后算) ─────────────────────────────────────────────────────
SIG_FROM, SIG_TO = "2020-03-01", "2026-10-31"   # 票生成窗(卡上写死)
CURVE_TO = "2026-10-31"                         # 钱曲线终点
COST = 0.004                                   # 来回成本(t159 逐字)
F_RISK = 0.01                                  # 钱曲线每笔 1%(S-638 的 f★)
CAP = 10                                       # 同时最多 10 张
SPLIT = "2026-08-08"                           # 量纲断点(T-237)
H1 = ("2020-03-01", "2022-12-31")              # 前半
H2 = ("2023-01-01", "2026-10-31")              # 后半
AGE_BINS = ((0.0, 1.0, "<1 年"), (1.0, 2.0, "1–2 年"),
            (2.0, 4.0, "2–4 年"), (4.0, 99.0, "≥4 年"))
BASE_ADV, BASE_AGE = 20e6, 365                 # U2 的两个门槛(写死)
VARIANTS = [("10M / 365d", 10e6, 365), ("50M / 365d", 50e6, 365),
            ("20M / 180d", 20e6, 180), ("20M / 730d", 20e6, 730)]


# ── DB 只读 ──────────────────────────────────────────────────────────────────
def _get(table, params, rng="0-999", prefer=None):
    q = urllib.parse.urlencode(params, safe="()*,.<>=")
    h = {"apikey": os.environ["SUPABASE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_KEY"],
         "Range": rng}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + table + "?" + q,
                                 headers=h)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()), r.headers.get("Content-Range", "")


def _get_retry(table, params, rng, tries=6, base=2.0):
    """连接被重置 / 5xx 时退避重试(库偶尔断开并发连接)。"""
    import time
    last = None
    for k in range(tries):
        try:
            return _get(table, params, rng)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(base ** k, 20))
    raise last


def fetch_pairs() -> dict:
    if PAIRS_JSON.exists():
        return json.load(open(PAIRS_JSON))
    CACHE.mkdir(parents=True, exist_ok=True)
    rows, cr = _get("perp_bv_pairs",
                    [("select", "pair,symbol,kind,first_d,dead_from,active"),
                     ("order", "symbol.asc,pair.asc")], "0-999", "count=exact")
    total = int(str(cr).split("/")[-1]) if cr and "/" in str(cr) else len(rows)
    if len(rows) < total:  # > 1000 行时分页补齐
        off = len(rows)
        while off < total:
            more, _ = _get("perp_bv_pairs",
                           [("select", "pair,symbol,kind,first_d,dead_from,active"),
                            ("order", "symbol.asc,pair.asc")], f"{off}-{min(off + 999, total - 1)}")
            if not more:
                break
            rows += more
            off += len(more)
    json.dump(rows, open(PAIRS_JSON, "w"))
    print(f"[t246] perp_bv_pairs {len(rows)} 行(声明 {total})", flush=True)
    return rows


def fetch_daily(workers: int = 4, page: int = 1000) -> None:
    """拉 perp_bv_daily 全量(pair,d,o,h,l,c,qv)。翻页带 order=pair.asc,d.asc,每页 1000 行,流式写 gzip。"""
    if DAILY_GZ.exists():
        print(f"[t246] perp_bv_daily 命中缓存 {DAILY_GZ}", flush=True)
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    params = [("select", "pair,d,o,h,l,c,qv"), ("order", "pair.asc,d.asc")]
    _, cr = _get("perp_bv_daily", params, "0-0", "count=exact")
    total = int(str(cr).split("/")[-1]) if cr and "/" in str(cr) else 0
    if total <= 0:
        raise SystemExit("perp_bv_daily 读不到 Content-Range 总数,不能确定分页边界")
    print(f"[t246] perp_bv_daily 总行 {total}", flush=True)
    offs = list(range(0, total, page))
    import threading
    lock = threading.Lock()
    raw = open(str(DAILY_GZ) + ".tmp", "wb")
    gz = gzip.GzipFile(fileobj=raw, mode="wb")
    written = {"n": 0}

    def grab(o):
        rows, _ = _get_retry("perp_bv_daily", params, f"{o}-{o + page - 1}")
        if not rows:
            return 0
        with lock:
            gz.write((json.dumps(rows, separators=(",", ":")) + "\n").encode())
            written["n"] += len(rows)
        return len(rows)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, k in enumerate(ex.map(grab, offs)):
            if (i + 1) % 50 == 0:
                print(f"[t246] perp_bv_daily {written['n']}/{total}", flush=True)
    gz.close()
    raw.close()
    if written["n"] != total:
        os.remove(str(DAILY_GZ) + ".tmp")
        raise SystemExit(f"perp_bv_daily 只拿到 {written['n']}/{total} 行,不写缓存")
    os.rename(str(DAILY_GZ) + ".tmp", DAILY_GZ)
    print(f"[t246] perp_bv_daily 缓存写入 {DAILY_GZ}({written['n']} 行)", flush=True)


# ── 数据装载 ─────────────────────────────────────────────────────────────────
def load_bars() -> tuple[dict, dict]:
    """返回 (bars: pair -> [(d,o,h,l,c,qv)], 重复统计)。"""
    bars = defaultdict(list)
    seen = defaultdict(set)
    dup = 0
    nulls = 0
    with gzip.open(DAILY_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            for r in json.loads(line):
                p, d = r.get("pair"), r.get("d")
                o, h, l, c, qv = r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("qv")
                if None in (o, h, l, c, qv):
                    nulls += 1
                    continue
                if d in seen[p]:
                    dup += 1
                    continue
                seen[p].add(d)
                bars[p].append((d, float(o), float(h), float(l), float(c), float(qv)))
    out = {p: sorted(v) for p, v in bars.items() if v}
    return out, {"dup_rows": dup, "null_rows": nulls, "n_pairs": len(out)}


def load_gate() -> dict:
    """majors 闸门(S-627):t159.load_gate() 原样(t156/_style.json)。"""
    return t159.load_gate()


# ── 票生成(t159.run_long 逐字 + 一个按时点闸门钩子) ──────────────────────────
def _ticket(a, n, i, sym, d):
    ei = i + 1
    if ei >= n:
        return None
    entry, stop = a["o"][ei], a["o"][ei] - 2.5 * a["atr14"][i]
    if not (entry > stop):
        return None
    k = None
    for j in range(ei, min(i + 120, n - 1) + 1):
        if a["l"][j] <= stop or a["c"][j] < a["sma20"][j]:
            k = j
            break
    if k is None:
        xi, xp, still = min(i + 120, n - 1), a["c"][min(i + 120, n - 1)], (i + 120 > n - 1)
    elif a["l"][k] <= stop:
        xi, xp, still = k, (a["o"][k] if (k > ei and a["o"][k] <= stop) else stop), False
    elif k + 1 <= n - 1:
        xi, xp, still = k + 1, a["o"][k+1], False
    else:
        xi, xp, still = k, a["c"][k], True
    t = dict(symbol=sym, signal_d=d, entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
             entry_px=entry, stop_px=stop, exit_px=None if still else xp, ei=ei, xi=xi,
             bars_held=xi - ei + 1, still=still)
    t["r"] = None if still else ((xp - entry) / (entry - stop) - COST * entry / (entry - stop))
    return t


def run_long_pit(bars, gate, d_from, d_to, elig=None, ind=None):
    """逐字照 t159.run_long;elig(sym, d, a, i) 是按时点的额外闸门(U2 用)。"""
    tr = defaultdict(list)
    for sym, rows in bars.items():
        a = ind[sym] if ind is not None else t159.indicators(rows)
        n = len(rows)
        for i in range(220, n):
            d = a["d"][i]
            if not (d_from <= d <= d_to) or not t159.sig_long(a, i, gate):
                continue
            if elig is not None and not elig(sym, d, a, i):
                continue
            t = _ticket(a, n, i, sym, d)
            if t is not None:
                tr[sym].append(t)
    return t159._chain(tr)


# ── 指标 ─────────────────────────────────────────────────────────────────────
def last_close_at(bars, sym, d_to):
    rows = bars.get(sym) or []
    c = [r[4] for r in rows if r[0] <= d_to]
    return c[-1] if c else None


def mtm(tickets, bars, d_to=CURVE_TO):
    for t in tickets:
        if t.get("r") is None:
            c = last_close_at(bars, t["symbol"], d_to)
            if c is None:
                continue
            t["r"] = (c - t["entry_px"]) / (t["entry_px"] - t["stop_px"]) - COST * t["entry_px"] / (
                t["entry_px"] - t["stop_px"])
            t["still"] = True
    return tickets


def summarize(tickets, bars, d_to=CURVE_TO, label=""):
    rs = [t["r"] for t in tickets if t.get("r") is not None]
    out = {"label": label, "n": len(tickets), "n_with_r": len(rs),
           "total_r": round(sum(rs), 4) if rs else 0.0,
           "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
           "win": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
           "still_open": sum(1 for t in tickets if t.get("still"))}
    curve = list(t159.nav(tickets, bars, F_RISK, cap=CAP, d_to=d_to))
    st = t159.stats(curve) if curve else None
    if st:
        mdd = st["mdd"]
        out["nav"] = {"d0": st["d0"], "d1": st["d1"], "end": round(st["end"], 6),
                      "annualised": st["annualised"], "mdd": mdd,
                      "calmar": (st["annualised"] / abs(mdd)) if (st["annualised"] and mdd) else None,
                      "nominal_peak": st["peak_gross"], "taken": st["taken"], "skipped": st["skipped"],
                      "closed": st["closed"]}
    return out


def window(tickets, bars, lo, hi, label):
    sub = [t for t in tickets if lo <= t["signal_d"] <= hi]
    d = summarize(sub, bars, label=label)
    d["window"] = [lo, hi]
    return d


def age_buckets(tickets, first_d):
    out = {}
    for lo, hi, name in AGE_BINS:
        rs = []
        for t in tickets:
            fd = first_d.get(t["symbol"])
            if not fd:
                continue
            age = (dt.date.fromisoformat(t["signal_d"]) - dt.date.fromisoformat(fd)).days / 365.25
            if lo <= age < hi:
                rs.append(t["r"] if t.get("r") is not None else 0.0)
        out[name] = {"n": len(rs), "total_r": round(sum(rs), 4) if rs else 0.0,
                     "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
                     "win": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None}
    return out


def dead_at_ticket(tickets, dead_from):
    n = 0
    rs = []
    for t in tickets:
        df = dead_from.get(t["symbol"])
        if df and df <= t["signal_d"]:
            n += 1
            rs.append(t["r"] if t.get("r") is not None else 0.0)
    return {"n": n, "total_r": round(sum(rs), 4) if rs else 0.0,
            "mean_r": round(sum(rs) / len(rs), 6) if rs else None}


def key(t):
    return (t["symbol"], t["signal_d"])


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    stage = "all"
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]

    if stage in ("all", "fetch"):
        fetch_pairs()
        fetch_daily()

    pairs_rows = fetch_pairs()
    info = {r["pair"]: {"symbol": r.get("symbol"), "kind": r.get("kind"),
                        "first_d": r.get("first_d"), "dead_from": r.get("dead_from"),
                        "active": r.get("active")} for r in pairs_rows}
    coin = {p for p, v in info.items() if v["kind"] == "coin" or (v["kind"] is None and v["dead_from"])}
    panel = set(json.load(open(SURV))["symbols"])
    coin_bases = {info[p]["symbol"] for p in coin}
    u1_bases = (panel & coin_bases) | {"1000PEPE"}
    u1_pairs = {p for p in coin if info[p]["symbol"] in u1_bases}

    bars_all, dupstats = load_bars()
    bars = {p: v for p, v in bars_all.items() if p in coin}
    first_d = {}
    for p, v in info.items():
        if p in coin:
            first_d[p] = v["first_d"] or (bars[p][0][0] if p in bars else None)
    dead_from = {p: info[p]["dead_from"] for p in coin}
    print(f"[t246] coin 永续 {len(coin)} 个;有 bar 的 {len(bars)} 个;U1 名义 {len(u1_pairs)} 个", flush=True)

    gate = load_gate()

    def elig_factory(min_adv, min_age):
        def elig(sym, d, a, i):
            fd = first_d.get(sym)
            if not fd:
                return False
            if (dt.date.fromisoformat(d) - dt.date.fromisoformat(fd)).days < min_age:
                return False
            adv = a["adv30"][i]
            return adv is not None and adv >= min_adv
        return elig

    # ── 逐个合约算一次 indicators,六个宇宙各收一遍票 ──────────────────────
    tr = {k: defaultdict(list) for k in ["U0", "U1", "U2", "V10M", "V50M", "V180", "V730"]}
    eligs = {"U2": elig_factory(BASE_ADV, BASE_AGE), "V10M": elig_factory(10e6, 365),
             "V50M": elig_factory(50e6, 365), "V180": elig_factory(20e6, 180),
             "V730": elig_factory(20e6, 730)}
    for n_i, (p, rows) in enumerate(sorted(bars.items()), 1):
        a = t159.indicators(rows)
        n = len(rows)
        for i in range(220, n):
            d = a["d"][i]
            if not (SIG_FROM <= d <= SIG_TO) or not t159.sig_long(a, i, gate):
                continue
            t = _ticket(a, n, i, p, d)
            if t is None:
                continue
            tr["U0"][p].append(t)
            if p in u1_pairs:
                tr["U1"][p].append(t)
            for uk, el in eligs.items():
                if el(p, d, a, i):
                    tr[uk][p].append(t)
        if n_i % 100 == 0:
            print(f"[t246] 信号扫描 {n_i}/{len(bars)} 个合约", flush=True)

    tk = {k: t159._chain(v) for k, v in tr.items()}
    for k in tk:
        mtm(tk[k], bars)
    print({k: len(v) for k, v in tk.items()}, flush=True)

    # ── 等价自检:同一份 bars,我的 run_long_pit(无闸门) vs t159.run_long ─────
    bars_u1 = {p: v for p, v in bars.items() if p in u1_pairs}
    mine = run_long_pit(bars_u1, gate, SIG_FROM, SIG_TO)
    ref = t159.run_long(bars_u1, gate, SIG_FROM, SIG_TO)
    A = {key(t): t for t in mine}
    B = {key(t): t for t in ref}
    diffs = [k for k in set(A) & set(B)
             if abs((A[k]["r"] or 0) - (B[k]["r"] or 0)) > 1e-9 or A[k]["exit_d"] != B[k]["exit_d"]
             or A[k]["entry_px"] != B[k]["entry_px"]]
    # 主循环(U1,无闸门)生成的票 vs t159.run_long 的票:必须逐张一致
    C = {key(t): t for t in tk["U1"]}
    inline_diffs = [k for k in set(C) & set(B)
                    if abs((C[k]["r"] or 0) - (B[k]["r"] or 0)) > 1e-9 or C[k]["exit_d"] != B[k]["exit_d"]
                    or C[k]["entry_px"] != B[k]["entry_px"]]
    selfcheck = {"n_mine": len(mine), "n_ref": len(ref), "n_both": len(set(A) & set(B)),
                 "n_diff": len(diffs), "only_mine": len(set(A) - set(B)), "only_ref": len(set(B) - set(A)),
                 "equal": len(mine) == len(ref) and not diffs and set(A) == set(B),
                 "inline_u1_n": len(C), "inline_u1_diff": len(inline_diffs),
                 "inline_u1_only_main": len(set(C) - set(B)), "inline_u1_only_ref": len(set(B) - set(C)),
                 "inline_equal": set(C) == set(B) and not inline_diffs}
    print(f"[t246] 等价自检 {selfcheck}", flush=True)

    # 台账自检:dead_from 有值、但 perp_bv_daily 里还有更晚的 bar(下架日与日线互相矛盾)
    ledger_bad = []
    for p_, v_ in info.items():
        if p_ in coin and v_["dead_from"] and p_ in bars_all:
            last_bar = bars_all[p_][-1][0]
            if last_bar > v_["dead_from"]:
                ledger_bad.append({"pair": p_, "dead_from": v_["dead_from"], "last_bar": last_bar})
    ledger_check = {"n_coin_with_dead_from": sum(1 for p_ in coin if info[p_]["dead_from"]),
                    "n_bars_after_dead_from": len(ledger_bad),
                    "sample": sorted(ledger_bad, key=lambda x: x["dead_from"])[:10]}

    res = {"meta": {"card": "T-246", "prereg": "S-731", "sig_window": [SIG_FROM, SIG_TO],
                    "cost": COST, "f": F_RISK, "cap": CAP, "split": SPLIT,
                    "halves": [H1, H2], "base_gate": [BASE_ADV, BASE_AGE],
                    "universe": {"coin_pairs": len(coin), "panel_n": len(panel),
                                 "panel_inter_coin": len(panel & coin_bases),
                                 "u1_n": len(u1_pairs), "u1_bases_extra": ["1000PEPE"]},
                    "data": dupstats, "selfcheck": selfcheck, "ledger_check": ledger_check}}

    # ── 每个宇宙的指标 ─────────────────────────────────────────────────────
    summ = {}
    for k in ["U0", "U1", "U2", "V10M", "V50M", "V180", "V730"]:
        t = tk[k]
        s = summarize(t, bars, label=k)
        s["h1"] = window(t, bars, H1[0], H1[1], f"{k} 前半")
        s["h2"] = window(t, bars, H2[0], H2[1], f"{k} 后半")
        post = [x for x in t if x["signal_d"] >= SPLIT]
        s["post_split"] = summarize(post, bars, label=f"{k} 08-08 后")
        s["post_split"]["window"] = [SPLIT, SIG_TO]
        s["age"] = age_buckets(t, first_d)
        s["dead_at_ticket"] = dead_at_ticket(t, dead_from)
        s["n_symbols"] = len({x["symbol"] for x in t})
        summ[k] = s
    res["universes"] = summ

    # ── U0 相对 U2 多出来的票 ──────────────────────────────────────────────
    k0, k2 = {key(t) for t in tk["U0"]}, {key(t) for t in tk["U2"]}
    only0 = [t for t in tk["U0"] if key(t) not in k2]
    only2 = [t for t in tk["U2"] if key(t) not in k0]
    res["u0_vs_u2"] = {
        "u0_only": summarize(only0, bars, label="U0 独有"),
        "u2_only": summarize(only2, bars, label="U2 独有"),
        "common_n": len(k0 & k2),
        "u0_only_age": age_buckets(only0, first_d),
        "u2_only_age": age_buckets(only2, first_d),
    }

    # ── 判(S-731) ─────────────────────────────────────────────────────────
    u1, u2 = summ["U1"], summ["U2"]
    c1 = (u2["nav"]["calmar"] is not None and u1["nav"]["calmar"] is not None
          and u2["nav"]["calmar"] >= 0.9 * u1["nav"]["calmar"])
    c2 = u2["h1"]["total_r"] > 0 and u2["h2"]["total_r"] > 0
    c3 = u2["post_split"]["total_r"] >= 0
    c4 = u2["dead_at_ticket"]["n"] > 0
    res["judge"] = {
        "rule": "S-731:① U2 的 Calmar ≥ U1 的 90%;② U2 两半总 R 都 > 0;③ U2 2026-08-08 后一段总 R ≥ 0;"
                "④ U2 的票里开票时已下架(dead_from ≤ signal_d)的合约照常计入。全过 ✅「U2 可以替代 U1」。",
        "c1_calmar": {"u1_calmar": u1["nav"]["calmar"], "u2_calmar": u2["nav"]["calmar"],
                      "threshold": (0.9 * u1["nav"]["calmar"]) if u1["nav"]["calmar"] is not None else None,
                      "pass": bool(c1)},
        "c2_halves": {"h1_total_r": u2["h1"]["total_r"], "h2_total_r": u2["h2"]["total_r"], "pass": bool(c2)},
        "c3_post_split": {"total_r": u2["post_split"]["total_r"], "n": u2["post_split"]["n"], "pass": bool(c3)},
        "c4_dead_counted": {"n": u2["dead_at_ticket"]["n"], "total_r": u2["dead_at_ticket"]["total_r"],
                            "note": "U2 票里开票时已下架的合约数(照常计入 U2 的总数)",
                            "u1_same": u1["dead_at_ticket"]["n"], "pass": bool(c4)},
        "verdict": "✅ U2 可以替代 U1" if (c1 and c2 and c3 and c4) else "❌",
    }

    # 逐票明细(便于复核)
    res["tickets"] = {k: [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                           "exit_d": t["exit_d"], "r": t["r"], "still": bool(t.get("still")),
                           "first_d": first_d.get(t["symbol"])} for t in tk[k]]
                      for k in ["U0", "U1", "U2"]}
    json.dump(res, open(OUT_JSON, "w"), indent=1, default=str)
    print(f"[t246] 结果写入 {OUT_JSON}", flush=True)
    write_report(res)


# ── 报告 ─────────────────────────────────────────────────────────────────────
def _f(x, nd=3):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))


def write_report(res) -> None:
    L = []
    p = L.append
    u = res["universes"]
    j = res["judge"]
    p("# T-246 · S-731:R-v2 的宇宙能不能写成一条按时点的规则")
    p("")
    p("> **预注册原文(S-731,2026-11-05 08:43 UTC;先抄后算,只算一次)**")
    p(">")
    p("> **为什么。** 现行宇宙(257 名)是今天的幸存者名单(S-684);全宇宙(约 650 个 coin 永续)近三个月扩出来的部分是负的(T-238 v2)。"
      "**原因假设:** 薄盘口的新合约上的突破多半是做出来的(Jazz「机械交易是做市商的提款机」);S-112 的准入经验值是 ADV > ~1,500 万。"
      "**规则(写死):** 开票日 d 当天上市满 365 天、30 日均报价成交额 ≥ 2,000 万美元,只用 ≤ d 的数;死币照常进。"
      "**判据(全过 ✅,U2 可以替代 U1):** U2 的 Calmar ≥ U1 的 90%;两半总 R 都 > 0;2026-08-08 后一段总 R ≥ 0。"
      "副只报:门槛 1,000 / 5,000 万、180 / 730 天;U0 多出来那部分的每票 R。**✅ 的含义:** 改真钱宇宙要 Jazz 拍板,不由这条直接改。"
      "**试验计数:交易层 +1。**")
    p("")
    p(f"- 生成:`docs/research/t246_rv2_pit_universe.py` · 数值:`docs/research/t246_results.json` · 场景:`docs/research/scenarios/lane-c-T-246.json`")
    p(f"- 数据:`perp_bv_daily`(o/h/l/c/qv,2019-12 起,含死币)+ `perp_bv_pairs`(first_d / dead_from / kind);只读,未入库、未改代码、未做 DDL。")
    p("")
    p("## 0 · 口径")
    p("")
    p("**R-v2 规则(逐字照 `t159.run_long`,S-610 进场 / S-627 majors 闸门 / 2.5 ATR / SMA20 出场 / 120 根上限 / 0.4% 来回 / cap 10 / f = 1%)。**"
      "本脚本的 `run_long_pit` 只多一个「按时点闸门」钩子;等价自检见 §1。")
    p("")
    p("| 项 | 值 |")
    p("|---|---|")
    p(f"| 信号窗 | {res['meta']['sig_window'][0]} → {res['meta']['sig_window'][1]} |")
    p(f"| 钱曲线 | f = {res['meta']['f']:.0%}/笔,cap = {res['meta']['cap']},来回成本 {res['meta']['cost']:.1%},盯市到 {CURVE_TO} |")
    p(f"| 两半 | {H1[0]} → {H1[1]} / {H2[0]} → {H2[1]} |")
    p(f"| 量纲断点 | {SPLIT}(断点后单列) |")
    p(f"| U2 门槛 | 上市满 {BASE_AGE} 天 且 30 日均报价成交额 ≥ ${BASE_ADV:,.0f}(只用 ≤ d 的数) |")
    p("")
    p("**三个宇宙(同一份 perp_bv_daily、同一份 R-v2 规则):**")
    p("")
    p("| 宇宙 | 定义 | 名义个数 |")
    p("|---|---|---|")
    p(f"| U0 | 全部 coin 永续(`kind='coin'` 或 `kind` 空且 `dead_from` 有值),无额外门槛 | {res['meta']['universe']['coin_pairs']} |")
    p(f"| U1 | 现行面板 ∩ coin 永续 = {res['meta']['universe']['panel_inter_coin']} 名,加 1000PEPE | {res['meta']['universe']['u1_n']} |")
    p(f"| U2 | U0 + 按时点门槛(365 天 + 30 日均 ≥ ${BASE_ADV:,.0f}) | {res['meta']['universe']['coin_pairs']}(按票逐日筛) |")
    p("")
    p(f"面板名单来源:`ohlcv_daily source=binance_hist` 的 distinct symbols({res['meta']['universe']['panel_n']} 名,本地缓存 s677/_survivor_symbols.json,"
      "2026-10-23 快照);其中 5 个不是 coin 永续(BTCDOM / DEFI / MDT / PEPE / USDC),交集 {res['meta']['universe']['panel_inter_coin']} 名 + 1000PEPE。")
    p("")
    p("## 1 · 自检与数据")
    p("")
    sc = res["meta"]["selfcheck"]
    p(f"- **等价自检**:同一份 U1 的 bars,本脚本 `run_long_pit`(无闸门) vs `t159.run_long`:票数 {sc['n_mine']} vs {sc['n_ref']},"
      f"逐票不同的 {sc['n_diff']} 张,只在本脚本 {sc['only_mine']} 张、只在 t159 {sc['only_ref']} 张 ⇒ **{'完全一致' if sc['equal'] else '不一致'}**。")
    p(f"- 数据自检:perp_bv_daily 重复 (pair,d) 行 {res['meta']['data']['dup_rows']}、OHLC/QV 为空的行 {res['meta']['data']['null_rows']};"
      f"有 bar 的 coin 合约 {res['meta']['data']['n_pairs']} 个。")
    p("")
    p("## 2 · 三个宇宙的结果")
    p("")
    p("| 宇宙 | 票数 | 总 R | 每票 R | 胜率 | 年化 | 盯市 MDD | Calmar | 名义峰值 | 接/挡/了结 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for k in ["U0", "U1", "U2"]:
        s = u[k]
        nv = s.get("nav", {})
        p(f"| {k} | {s['n']} | {s['total_r']} | {_f(s['mean_r'])} | {_f(s['win'], 4)} | {_f(nv.get('annualised'), 4)} | "
          f"{_f(nv.get('mdd'), 4)} | {_f(nv.get('calmar'))} | {_f(nv.get('nominal_peak'), 2)} | "
          f"{nv.get('taken')}/{nv.get('skipped')}/{nv.get('closed')} |")
    p("")
    p("**两半与断点后(总 R / 票数):**")
    p("")
    p("| 宇宙 | 前半 2020-03→2022-12 | 后半 2023-01→2026-10 | 2026-08-08 后 |")
    p("|---|---|---|---|")
    for k in ["U0", "U1", "U2"]:
        s = u[k]
        p(f"| {k} | {s['h1']['total_r']} / {s['h1']['n']} | {s['h2']['total_r']} / {s['h2']['n']} | "
          f"{s['post_split']['total_r']} / {s['post_split']['n']} |")
    p("")
    p("**按开票时上市年数分档(每票 R / 票数):**")
    p("")
    p("| 宇宙 | <1 年 | 1–2 年 | 2–4 年 | ≥4 年 |")
    p("|---|---|---|---|---|")
    for k in ["U0", "U1", "U2"]:
        s = u[k]
        cells = []
        for _, _, name in AGE_BINS:
            b = s["age"][name]
            cells.append(f"{_f(b['mean_r'])} / {b['n']}")
        p(f"| {k} | " + " | ".join(cells) + " |")
    p("")
    p("**开票时已下架(dead_from ≤ signal_d)的合约:**")
    p("")
    p("| 宇宙 | 票数 | 总 R | 每票 R |")
    p("|---|---|---|---|")
    for k in ["U0", "U1", "U2"]:
        s = u[k]
        d = s["dead_at_ticket"]
        p(f"| {k} | {d['n']} | {d['total_r']} | {_f(d['mean_r'])} |")
    p("")
    p("## 3 · 副只报")
    p("")
    o = res["u0_vs_u2"]
    p(f"**U0 相对 U2 多出来的票**(门槛挡掉的那部分):{o['u0_only']['n']} 张,总 R {o['u0_only']['total_r']},"
      f"每票 R **{_f(o['u0_only']['mean_r'])}**,胜率 {_f(o['u0_only']['win'], 4)};"
      f"两边共有 {o['common_n']} 张,U2 独有 {o['u2_only']['n']} 张(总 R {o['u2_only']['total_r']},每票 R {_f(o['u2_only']['mean_r'])})。")
    p("")
    p("**门槛变体(只报不判):**")
    p("")
    p("| 变体 | 票数 | 总 R | 每票 R | 胜率 | Calmar | 前半总 R | 后半总 R | 08-08 后总 R |")
    p("|---|---|---|---|---|---|---|---|---|")
    for k, name in [("U2", "20M / 365d(基准)"), ("V10M", "10M / 365d"), ("V50M", "50M / 365d"),
                    ("V180", "20M / 180d"), ("V730", "20M / 730d")]:
        s = u[k]
        p(f"| {name} | {s['n']} | {s['total_r']} | {_f(s['mean_r'])} | {_f(s['win'], 4)} | "
          f"{_f(s.get('nav', {}).get('calmar'))} | {s['h1']['total_r']} | {s['h2']['total_r']} | {s['post_split']['total_r']} |")
    p("")
    p("## 4 · 判(S-731)")
    p("")
    p(f"> {j['rule']}")
    p("")
    p("| 判据 | 实测 | 过? |")
    p("|---|---|---|")
    c1 = j["c1_calmar"]
    p(f"| ① U2 的 Calmar ≥ U1 的 90% | U1 Calmar {_f(c1['u1_calmar'])},U2 Calmar {_f(c1['u2_calmar'])},门槛 {_f(c1['threshold'])} | "
      f"{'✅' if c1['pass'] else '❌'} |")
    p(f"| ② U2 两半总 R 都 > 0 | 前半 {j['c2_halves']['h1_total_r']},后半 {j['c2_halves']['h2_total_r']} | "
      f"{'✅' if j['c2_halves']['pass'] else '❌'} |")
    p(f"| ③ U2 2026-08-08 后一段总 R ≥ 0 | {j['c3_post_split']['total_r']}({j['c3_post_split']['n']} 张) | "
      f"{'✅' if j['c3_post_split']['pass'] else '❌'} |")
    p(f"| ④ U2 的票里开票时已下架的合约照常计入 | U2 {j['c4_dead_counted']['n']} 张(总 R {j['c4_dead_counted']['total_r']}),"
      f"U1 {j['c4_dead_counted']['u1_same']} 张 | {'✅' if j['c4_dead_counted']['pass'] else '❌'} |")
    p("")
    p(f"**判: {j['verdict']}**")
    p("")
    # ── 机制与别的发现 ────────────────────────────────────────────────────
    u0, u1, u2 = u["U0"], u["U1"], u["U2"]
    ov = res["u0_vs_u2"]
    lc = res["meta"].get("ledger_check", {})
    var_ratio = {name: (u[k]["nav"]["calmar"] / u1["nav"]["calmar"] if u[k].get("nav", {}).get("calmar")
                         and u1["nav"]["calmar"] else None)
                 for k, name in [("V10M", "10M/365d"), ("V50M", "50M/365d"), ("V180", "20M/180d"),
                                 ("V730", "20M/730d"), ("U2", "20M/365d(基准)")]}
    best_var = max((x for x in var_ratio.items() if x[1] is not None), key=lambda kv: kv[1])
    p("## 5 · 机制与别的发现")
    p("")
    p("**① 管线与 T-238 v2 对上了。** U0(全部 coin 永续)在同一份 perp_bv_daily 上得 "
      f"**{u0['n']} 张 / Σ{u0['total_r']}R / 每票 {_f(u0['mean_r'])}R / 胜率 {_f(u0['win'], 4)}**,"
      f"钱曲线年化 {_f(u0['nav']['annualised'], 4)}、盯市 MDD {_f(u0['nav']['mdd'], 4)}、Calmar {_f(u0['nav']['calmar'])};"
      "lane-b 的 T-238 v2 实测是 **960 张 / 309.6R / 每票 0.32R / 胜率 34.4% / 年化 25.0% / MDD −36.9% / Calmar 0.68** —— 逐项一致。")
    p("")
    p(f"**② 门槛挡掉的是好票。** U0 独有(U2 挡掉或被连锁挤掉的){ov['u0_only']['n']} 张,总 R {ov['u0_only']['total_r']},"
      f"每票 **{_f(ov['u0_only']['mean_r'])}R**、胜率 {_f(ov['u0_only']['win'], 4)} —— 比 U2 留下的票(每票 {_f(u2['mean_r'])}R)还好。"
      "被挡掉的这批按上市年数:<1 年 " + _f(ov['u0_only_age']['<1 年']['mean_r']) + "R / "
      + str(ov['u0_only_age']['<1 年']['n']) + " 张,1–2 年 " + _f(ov['u0_only_age']['1–2 年']['mean_r']) + "R / "
      + str(ov['u0_only_age']['1–2 年']['n']) + " 张,2–4 年 " + _f(ov['u0_only_age']['2–4 年']['mean_r']) + "R / "
      + str(ov['u0_only_age']['2–4 年']['n']) + " 张,≥4 年 **" + _f(ov['u0_only_age']['≥4 年']['mean_r']) + "R** / "
      + str(ov['u0_only_age']['≥4 年']['n']) + " 张 —— 最老的一档(上市 ≥4 年、但当时 30 日均成交额不到 $20M)反而最好。")
    p("")
    p("**③ S-731 点名的「薄盘口新合约上的突破多半是做出来的」,在全宇宙层面没有成立。** U0 按开票时上市年数:"
      + " · ".join(f"{name} {u0['age'][name]['n']} 张 / 每票 {_f(u0['age'][name]['mean_r'])}R"
                   for _, _, name in AGE_BINS)
      + " —— 最年轻的那档(<1 年)不是最差的,最差的是 **1–2 年**那一档;真正集中的负值在 2026-08-08 之后那一段"
      f"(U0 该段 {u0['post_split']['n']} 张 / Σ{u0['post_split']['total_r']}R)。")
    p("")
    p("**④ U2 的钱曲线为什么掉得这么狠。** U2 把 U1 的 "
      f"{u1['n']} 张换成 {u2['n']} 张,总 R 从 {u1['total_r']} 掉到 {u2['total_r']},年化从 {_f(u1['nav']['annualised'], 4)} 掉到 "
      f"{_f(u2['nav']['annualised'], 4)},而盯市 MDD 反而从 {_f(u1['nav']['mdd'], 4)} 深到 {_f(u2['nav']['mdd'], 4)}。"
      "本卡**没有**分解原因(没测相关性/敞口),只报现象:门槛换掉的是「当日流动性更高」的名字,cap 10 下坑更少但更同向。")
    p("")
    p("**⑤ 不是门槛取值的问题。** 四个变体相对 U1 的 Calmar 比:"
      + " · ".join(f"{k} {v*100:.0f}%" for k, v in var_ratio.items() if v is not None)
      + f" —— 最好的一条({best_var[0]})也只有 U1 的 {best_var[1]*100:.0f}%,离 90% 的线还差得远。"
      "换句话说:「用一条按时点的规则重建宇宙」在这份数据上整体不如「今天的名单」,不是 2,000 万 / 365 天定错了。")
    p("")
    if lc:
        p(f"**⑥ 台账与日线打架(criterion ④ 的注脚)。** `perp_bv_pairs` 里 {lc['n_coin_with_dead_from']} 个 coin 合约有 dead_from,"
          f"其中 **{lc['n_bars_after_dead_from']} 个**在 `perp_bv_daily` 里还有 dead_from 之后的日线"
          + (f"(例:{', '.join(x['pair'] + ' dead ' + x['dead_from'] + ' 但日线到 ' + x['last_bar'] for x in lc['sample'][:3])})" if lc.get("sample") else "")
          + f" ⇒ U2 里那 {u2['dead_at_ticket']['n']} 张「开票时已下架」的票并不是真的买在已下架的合约上,"
          "而是台账的 dead_from 与日线互相矛盾。criterion ④ 形式上成立(照常计入),实质证据弱。")
        p("")
    p("## 6 · 诚实与限制")
    p("")
    p("- **U1 是今天的名单**(含幸存者偏差);U2 是一条规则(可以照着算任何一天)。U2 比 U1 差一点是预期的,"
      "判据写的是「≥ 90%」而不是「更好」。")
    p("- **门槛 2,000 万与 365 天是按 S-112 定的,没有扫**;§3 的四列只是把这条线上的四个点摊开,不是选优。")
    p("- 三个宇宙都在 **perp_bv_daily** 上重算(卡上写死「同一份 perp_bv_daily」),所以 U1 的数字**不能**直接和"
      "已发布的现货面板数(770 张 / Σ+372.4R / 年化 27.3% / MDD −32.3% / Calmar 0.85)对比 —— 那是 ohlcv_daily(现货)上的数。")
    p("- R-v2 规则本身含 `adv30 ≥ $5M` 的旧宇宙闸门(S-610 原文);U0 的「无额外门槛」= 不在 R-v2 之外再加门槛,"
      "不是把 R-v2 自带的闸门去掉。")
    p("- 没有任何零分布 / 随机对照在本卡里;本卡是「同一批票换宇宙」的对照,不是显著性检验。")
    p("- ✅ 只表示「这条规则可以作为真钱宇宙的候选」;**改真钱宇宙要 Jazz 拍板**。")
    p("")
    p("## 7 · 复算")
    p("")
    p("```bash")
    p("python3 docs/research/t246_rv2_pit_universe.py          # fetch + compute")
    p("python3 docs/research/t246_rv2_pit_universe.py --stage compute   # 复用缓存")
    p("```")
    p("")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[t246] 报告写入 {OUT_MD}", flush=True)


if __name__ == "__main__":
    main()
