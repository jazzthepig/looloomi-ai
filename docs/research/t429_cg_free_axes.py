#!/usr/bin/env python3
"""T-429:两条状态轴在 CoinGecko 停订之后还能不能读 —— 只量,不改。

卡:`tasks/T-429.json`(台账 S-898)。CG 停订 2026-11-21(12-01 恢复),两条轴的第二输入断了:
  A. 稳定币轴 `state_daily.stable_supply_30d`
     官方读法:`cg_coin_mcap_daily` 的 tether + usd-coin 市值,30 日变化。
     并行读法(本卡要量的):`stablecoin_issuer_daily`(DeFiLlama,免费)的 USDT + USDC 流通量,30 日变化。
  B. 形态轴 `state_daily.style_rel_majors_30d`
     官方读法:`style_index_daily`(cap)的 majors 30 日收益 − second_l1_l2 30 日收益(成分/权重每日按 CG 市值重算)。
     影子读法(本卡要量的):在 m−1 冻结成员与市值权重,之后只用 `ohlcv_daily`(binance_hist)收盘把两条指数续 30 天。

只读;不 import `src/`;不写库。取数一律带 `order=`;每页 ≤ 1000 行;取完核 `Content-Range` 总数。
结果落 `docs/research/t429_results.json`。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
if not URL or not KEY:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里,退出")
HEAD = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".t429_cache")
OUT = os.path.join(HERE, "t429_results.json")
RAILWAY = "https://web-production-0cdf76.up.railway.app"

PAGE = 1000
# ── 官方口径的常数(抄自 src/data/style/header.py,不在本脚本 import src/) ──
MIN_MCAP_USD = 20e6
MAX_DAILY_RET, MIN_DAILY_RET = 5.0, -0.95
LEAD_MIN_PRIOR = 365
STYLES = ("majors", "second_l1_l2")
FREEZE_FIRST = "2024-01-01"      # 卡上的起点:2024-01-01 → 2026-11-19
FREEZE_LAST = "2026-11-19"      # 官方风格指数最后一天(CG 停订前的最后一条)
HORIZON_D = 30                  # 每次停供后看 30 天


# ── 取数 ────────────────────────────────────────────────────────────────────
def _qs(params: dict) -> str:
    parts = []
    for k, v in params.items():
        vals = v if isinstance(v, (list, tuple)) else [v]
        for x in vals:
            parts.append(f"{k}={urllib.parse.quote(str(x), safe='(),.*:<>= ')}")
    return "&".join(parts)


def _q(table: str, params: dict):
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{_qs(params)}", headers=HEAD)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
            return r.status, r.headers.get("Content-Range"), json.loads(body or "[]")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{table} HTTP {e.code}: {e.read().decode()[:200]}") from e


def _total(cr):
    if cr and "/" in cr:
        tail = cr.rsplit("/", 1)[1]
        if tail.isdigit():
            return int(tail)
    return None


def fetch(table: str, params: dict, tag: str) -> list[dict]:
    """按 offset 翻页读全表;核总行数。"""
    path = os.path.join(CACHE, tag + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows: list[dict] = []
    off = 0
    total = None
    while True:
        p = dict(params)
        p["limit"] = str(PAGE)
        p["offset"] = str(off)
        st, cr, batch = _q(table, p)
        if total is None:
            total = _total(cr)
        rows.extend(batch)
        off += len(batch)
        if len(batch) < PAGE:
            break
    if total is not None and len(rows) != total:
        raise RuntimeError(f"{tag}: 取回 {len(rows)} 行 ≠ content-range 总数 {total}(翻页漏了)")
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_shards(table: str, shards: list[dict], tag: str) -> list[dict]:
    """分片并发取(每片内部按 offset 翻页)。"""
    path = os.path.join(CACHE, tag + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    os.makedirs(CACHE, exist_ok=True)

    def one(params: dict) -> list[dict]:
        rows: list[dict] = []
        off = 0
        while True:
            p = dict(params)
            p["limit"] = str(PAGE)
            p["offset"] = str(off)
            st, cr, batch = _q(table, p)
            rows.extend(batch)
            off += len(batch)
            if len(batch) < PAGE:
                break
        return rows

    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = list(ex.map(one, shards))
    rows = [r for part in parts for r in part]
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_railway(path: str, params: str) -> list[dict]:
    """Railway 公开读端点(无 key):官方 style_index_daily 的水平(旧口径 backfilled)。"""
    cache = os.path.join(CACHE, path + ".json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    url = f"{RAILWAY}/api/v1/style/index?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode())
    rows = data.get("data") or []
    os.makedirs(CACHE, exist_ok=True)
    with open(cache, "w") as f:
        json.dump(rows, f)
    return rows


# ── 小工具 ──────────────────────────────────────────────────────────────────
def D(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summ(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "median": round(statistics.median(xs), 6),
            "p95": round(pct(xs, 0.95) or 0.0, 6), "max": round(max(xs), 6),
            "mean": round(statistics.fmean(xs), 6)}


def month_starts(a: str, b: str) -> list[dt.date]:
    d0, d1 = D(a), D(b)
    out, y, m = [], d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        out.append(dt.date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ══════════════════════════════════════════════════════════════════════════
# A. 稳定币轴:DeFiLlama 口径 vs 官方(CG 市值)口径
# ══════════════════════════════════════════════════════════════════════════
def part_a() -> dict:
    print("[A] 取数 …", flush=True)
    sd = fetch("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                               "feature": "in.(stable_supply_30d,style_rel_majors_30d)",
                               "order": "d.asc,feature.asc"}, "sd_axes")
    official = {r["d"]: r["value"] for r in sd if r["feature"] == "stable_supply_30d"}

    iss = fetch("stablecoin_issuer_daily", {"select": "d,coin,circulating_usd", "coin": "in.(USDT,USDC)",
                                             "order": "d.asc,coin.asc"}, "issuer_usdt_usdc")
    by_coin: dict[str, dict[str, float]] = {}
    for r in iss:
        by_coin.setdefault(r["coin"], {})[r["d"]] = float(r["circulating_usd"])
    both_days = sorted(set(by_coin.get("USDT", {})) & set(by_coin.get("USDC", {})))
    llama: dict[str, float] = {d: by_coin["USDT"][d] + by_coin["USDC"][d] for d in both_days}

    # 自检:按官方的定义(cg_coin_mcap_daily 的 tether+usd-coin 市值)复算一遍,看能不能逐日对上 state_daily
    cgm = fetch("cg_coin_mcap_daily", {"select": "d,coin_id,mcap", "coin_id": "in.(tether,usd-coin)",
                                        "order": "d.asc,coin_id.asc"}, "cg_stable")
    cg: dict[str, float] = {}
    for r in cgm:
        cg[r["d"]] = cg.get(r["d"], 0.0) + float(r["mcap"])

    def ret30(series: dict[str, float], d: str) -> float | None:
        a = series.get(d)
        b = series.get((D(d) - dt.timedelta(days=30)).isoformat())
        return (a / b - 1) if a is not None and b else None

    replica_ok = replica_bad = 0
    for d, v in official.items():
        if v is None:
            continue
        mine = ret30(cg, d)
        if mine is None:
            continue
        if abs(mine - float(v)) < 1e-9:
            replica_ok += 1
        else:
            replica_bad += 1

    # 对照:重叠日
    rows = []
    for d, ov in official.items():
        if ov is None:
            continue
        sh = ret30(llama, d)
        if sh is None:
            continue
        rows.append({"d": d, "official": float(ov), "shadow": sh, "diff_pp": (sh - float(ov)) * 100.0})
    rows.sort(key=lambda r: r["d"])

    def sign(x: float) -> int:
        return (x > 0) - (x < 0)

    absd = [abs(r["diff_pp"]) for r in rows]
    same = [r for r in rows if sign(r["shadow"]) == sign(r["official"])]
    disagree = [r for r in rows if sign(r["shadow"]) != sign(r["official"])]
    near = [r for r in disagree if abs(r["official"]) * 100 < 0.5 and abs(r["shadow"]) * 100 < 0.5]

    by_year: dict[str, dict] = {}
    for r in rows:
        y = r["d"][:4]
        b = by_year.setdefault(y, {"n": 0, "absdiff": [], "same_sign": 0, "disagree": []})
        b["n"] += 1
        b["absdiff"].append(abs(r["diff_pp"]))
        if sign(r["shadow"]) == sign(r["official"]):
            b["same_sign"] += 1
        else:
            b["disagree"].append({"d": r["d"], "official_pp": round(r["official"] * 100, 4),
                                  "shadow_pp": round(r["shadow"] * 100, 4)})

    print(f"[A] 重叠日 {len(rows)} 天;同号 {len(same)};异号 {len(disagree)}", flush=True)
    return {
        "official_series": {"source": "state_daily.stable_supply_30d", "n_rows": len(official),
                            "first_nonnull": min([d for d, v in official.items() if v is not None], default=None),
                            "last_nonnull": max([d for d, v in official.items() if v is not None], default=None),
                            "last_value": next((official[d] for d in sorted(official, reverse=True)
                                                if official[d] is not None), None)},
        "defillama_series": {"table": "stablecoin_issuer_daily", "source": "defillama_stablecoins",
                             "usdt_first": min(by_coin.get("USDT", {}), default=None),
                             "usdc_first": min(by_coin.get("USDC", {}), default=None),
                             "both_first": both_days[0] if both_days else None,
                             "last": max(llama) if llama else None,
                             "usdt_usdc_last_usd": [round(llama[max(llama)], 0)] if llama else None},
        "replication_check": {"desc": "按官方定义(cg_coin_mcap_daily 的 tether+usd-coin 市值)复算 30 日变化,与 state_daily 逐日比",
                              "ok": replica_ok, "bad": replica_bad},
        "overlap": {"n_days": len(rows), "first": rows[0]["d"] if rows else None,
                    "last": rows[-1]["d"] if rows else None},
        "abs_diff_pp": summ(absd),
        "signed_diff_pp": summ([r["diff_pp"] for r in rows]),
        "sign_agreement": {"n": len(rows), "same": len(same), "rate": round(len(same) / len(rows), 6) if rows else None,
                           "disagree_n": len(disagree), "disagree_near_zero": len(near),
                           "near_zero_rule": "官方与影子两个值都在 ±0.5pp 以内"},
        "disagree_days": [{"d": r["d"], "official_pp": round(r["official"] * 100, 4),
                           "shadow_pp": round(r["shadow"] * 100, 4)} for r in disagree],
        "by_year": {y: {"n": b["n"], "abs_diff_pp": summ(b["absdiff"]),
                        "sign_same": b["same_sign"], "sign_same_rate": round(b["same_sign"] / b["n"], 6),
                        "disagree_days": b["disagree"]} for y, b in sorted(by_year.items())},
        "rows_tail": rows[-5:],
    }


# ══════════════════════════════════════════════════════════════════════════
# B. 形态轴:冻结成员/权重 + 币安收盘续算 30 天
# ══════════════════════════════════════════════════════════════════════════
def part_b() -> dict:
    print("[B] 取数 …", flush=True)
    sd = fetch("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                               "feature": "in.(stable_supply_30d,style_rel_majors_30d)",
                               "order": "d.asc,feature.asc"}, "sd_axes")
    official = {r["d"]: r["value"] for r in sd if r["feature"] == "style_rel_majors_30d"}

    pit = fetch("style_index_pit_daily",
                {"select": "d,style,level,ret,n_members,n_dropped,members,top_weight,n_not_in_today_lists",
                 "style": "in.(majors,second_l1_l2)", "weighting": "eq.cap", "d": "gte.2023-11-01",
                 "order": "d.asc,style.asc"}, "pit_two_styles")
    pit_level: dict[tuple[str, str], float] = {}
    pit_members: dict[tuple[str, str], list[str]] = {}
    for r in pit:
        k = (r["style"], r["d"])
        if r.get("level") is not None:
            pit_level[k] = float(r["level"])
        if r.get("members"):
            pit_members[k] = list(r["members"])

    # 官方(旧口径 backfilled)水平 —— 只用于对照与 PIT 基准的自检
    off_level: dict[tuple[str, str], float] = {}
    for st in STYLES:
        for r in fetch_railway(f"sty_{st}_off_2023", f"style={st}&weighting=cap&basis=backfilled&start=2023-11-01"):
            if r.get("level") is not None:
                off_level[(st, r["d"])] = float(r["level"])

    # 每个月初 = 一次「假装 CG 在 m 那天停了」
    freezes = month_starts(FREEZE_FIRST, FREEZE_LAST)
    # 成员全集(用于取币安价与市值)
    all_syms: set[str] = set()
    for f in freezes:
        for st in STYLES:
            all_syms |= set(pit_members.get((st, (f - dt.timedelta(days=1)).isoformat()), []))
    all_syms = {s for s in all_syms if s}
    print(f"[B] 成员全集 {len(all_syms)} 个;冻结点 {len(freezes)} 个", flush=True)

    # CG 市值(冻结日的权重用)+ 币安收盘
    fdates = sorted({(f - dt.timedelta(days=1)).isoformat() for f in freezes})
    sym_list = sorted(all_syms)
    shards = []
    for i in range(0, len(sym_list), 25):
        chunk = sym_list[i:i + 25]
        shards.append({"select": "symbol,d,mcap", "source": "eq.coingecko_pro_market_chart",
                       "symbol": f"in.({','.join(chunk)})", "d": f"in.({','.join(fdates)})",
                       "order": "symbol.asc,d.asc"})
    mcap_rows = fetch_shards("asset_mcap_daily", shards, "mcap_freeze")
    mcap: dict[tuple[str, str], float] = {}
    for r in mcap_rows:
        if r.get("mcap") is not None:
            mcap[(r["symbol"], r["d"])] = float(r["mcap"])

    shards = []
    for i in range(0, len(sym_list), 25):
        chunk = sym_list[i:i + 25]
        shards.append({"select": "symbol,trade_date,close", "source": "eq.binance_hist",
                       "symbol": f"in.({','.join(chunk)})",
                       "trade_date": "gte.2023-11-01", "order": "symbol.asc,trade_date.asc"})
    px_rows = fetch_shards("ohlcv_daily", shards, "bin_px_members")
    px: dict[tuple[str, str], float] = {}
    for r in px_rows:
        if r.get("close") is not None:
            px[(r["symbol"], r["trade_date"])] = float(r["close"])
    print(f"[B] 币安收盘 {len(px)} 行,市值 {len(mcap)} 行", flush=True)

    # 官方闸门(谁在领):严格更早的官方值的均值,≥365 个更早值
    prior_sum, prior_n = 0.0, 0
    gate: dict[str, float] = {}
    for d in sorted(official):
        v = official[d]
        if v is None:
            continue
        if prior_n >= LEAD_MIN_PRIOR:
            gate[d] = prior_sum / prior_n
        prior_sum += float(v)
        prior_n += 1

    def pit_rel(d: str) -> float | None:
        vals = {}
        for st in STYLES:
            a = pit_level.get((st, d))
            b = pit_level.get((st, (D(d) - dt.timedelta(days=30)).isoformat()))
            if a is None or b is None:
                return None
            vals[st] = a / b - 1
        return vals["majors"] - vals["second_l1_l2"]

    def off_rel(d: str) -> float | None:
        vals = {}
        for st in STYLES:
            a = off_level.get((st, d))
            b = off_level.get((st, (D(d) - dt.timedelta(days=30)).isoformat()))
            if a is None or b is None:
                return None
            vals[st] = a / b - 1
        return vals["majors"] - vals["second_l1_l2"]

    cases = []
    for m in freezes:
        f = m - dt.timedelta(days=1)
        fd = f.isoformat()
        members = {st: list(pit_members.get((st, fd), [])) for st in STYLES}
        if not all(members[st] for st in STYLES):
            continue
        if any(pit_level.get((st, fd)) is None for st in STYLES):
            continue
        # 权重:m−1 的市值(≥ MIN_MCAP_USD),归一化
        w = {}
        for st in STYLES:
            caps = {s: mcap.get((s, fd)) for s in members[st]}
            caps = {s: c for s, c in caps.items() if c is not None and c >= MIN_MCAP_USD}
            tot = sum(caps.values())
            w[st] = {s: c / tot for s, c in caps.items()} if tot > 0 else {}
        # 覆盖统计
        cov = {}
        for st in STYLES:
            caps = {s: mcap.get((s, fd)) for s in members[st]}
            tot_all = sum(c for c in caps.values() if c is not None)
            have = [s for s in members[st] if (s, fd) in px]
            cov[st] = {"n_members": len(members[st]), "n_with_binance_px": len(have),
                       "mcap_coverage": round(sum(caps[s] for s in have if caps[s] is not None) / tot_all, 6)
                       if tot_all > 0 else None}
        # 影子:从 m 起每天用币安收盘续算
        lvl = {st: pit_level[(st, fd)] for st in STYLES}
        daily = []
        for k in range(1, HORIZON_D + 1):
            t = (m + dt.timedelta(days=k - 1)).isoformat()
            tprev = (m + dt.timedelta(days=k - 2)).isoformat()
            row = {"d": t, "k": k}
            for st in STYLES:
                avail, rr = [], []
                for s in w[st]:
                    a, b = px.get((s, t)), px.get((s, tprev))
                    if a is None or b is None or b <= 0:
                        continue
                    r = a / b - 1
                    if not (MIN_DAILY_RET <= r <= MAX_DAILY_RET):
                        continue
                    avail.append(s)
                    rr.append(r)
                if avail and w[st]:
                    tot = sum(w[st][s] for s in avail)
                    r_st = sum(w[st][s] * r for s, r in zip(avail, rr)) / tot if tot > 0 else None
                    if r_st is not None:
                        lvl[st] = lvl[st] * (1 + r_st)
                    row[st] = {"ret": r_st, "n_avail": len(avail)}
                else:
                    row[st] = {"ret": None, "n_avail": len(avail)}
            row["shadow_rel"] = None
            den = {st: pit_level.get((st, (D(t) - dt.timedelta(days=30)).isoformat())) for st in STYLES}
            if all(row[st]["ret"] is not None for st in STYLES) and all(den[st] for st in STYLES):
                r30 = {st: lvl[st] / den[st] - 1 for st in STYLES}
                row["shadow_rel"] = r30["majors"] - r30["second_l1_l2"]
            daily.append(row)
        cases.append({"m": m.isoformat(), "coverage": cov, "daily": daily})

    # 统计
    by_k: dict[int, dict] = {}
    for c in cases:
        for row in c["daily"]:
            k = row["k"]
            s = by_k.setdefault(k, {"vs_official": [], "vs_pit": [], "n": 0, "n_off": 0,
                                    "gate_agree": 0, "n_gate": 0, "sign_agree_off": 0, "n_sign": 0,
                                    "n_pit": 0, "sign_agree_pit": 0, "n_none": 0})
            s["n"] += 1
            if row["shadow_rel"] is None:
                s["n_none"] += 1
                continue
            ov = official.get(row["d"])
            if ov is not None:
                s["vs_official"].append((row["shadow_rel"] - float(ov)) * 100.0)
                s["n_off"] += 1
                s["n_sign"] += 1
                if (row["shadow_rel"] > 0) == (float(ov) > 0):
                    s["sign_agree_off"] += 1
                g = gate.get(row["d"])
                if g is not None:
                    s["n_gate"] += 1
                    if (row["shadow_rel"] > g) == (float(ov) > g):
                        s["gate_agree"] += 1
            pr = pit_rel(row["d"])
            if pr is not None:
                s["vs_pit"].append((row["shadow_rel"] - pr) * 100.0)
                s["n_pit"] += 1
                s["sign_agree_pit"] += 1 if (row["shadow_rel"] > 0) == (pr > 0) else 0

    def kblock(s: dict) -> dict:
        return {"n_rows": s["n"], "n_with_official": s["n_off"], "n_shadow_none": s["n_none"],
                "abs_diff_pp_vs_official": summ([abs(x) for x in s["vs_official"]]),
                "signed_diff_pp_vs_official": summ(s["vs_official"]),
                "abs_diff_pp_vs_pit": summ([abs(x) for x in s["vs_pit"]]),
                "sign_agreement_vs_official": round(s["sign_agree_off"] / s["n_sign"], 6) if s["n_sign"] else None,
                "sign_agreement_vs_pit": round(s["sign_agree_pit"] / s["n_pit"], 6) if s["n_pit"] else None,
                "gate_agreement": round(s["gate_agree"] / s["n_gate"], 6) if s["n_gate"] else None,
                "n_gate": s["n_gate"]}

    out_by_k = {str(k): kblock(by_k[k]) for k in sorted(by_k)}
    for k in (1, 7, 14, 30):
        out_by_k.setdefault(str(k), None)

    cov_majors = [c["coverage"]["majors"] for c in cases]
    cov_second = [c["coverage"]["second_l1_l2"] for c in cases]
    cov_stats = {}
    for name, arr in (("majors", cov_majors), ("second_l1_l2", cov_second)):
        npx = [a["n_with_binance_px"] for a in arr]
        nm = [a["n_members"] for a in arr]
        mc = [a["mcap_coverage"] for a in arr if a["mcap_coverage"] is not None]
        cov_stats[name] = {"n_members_min": min(nm), "n_members_max": max(nm),
                            "n_with_binance_px_min": min(npx), "n_with_binance_px_max": max(npx),
                            "n_with_binance_px_median": statistics.median(npx),
                            "mcap_coverage_min": round(min(mc), 6), "mcap_coverage_max": round(max(mc), 6),
                            "mcap_coverage_median": round(statistics.median(mc), 6)}

    # PIT 基准 vs 官方(口径差,不是 CG 可得性差)
    pit_vs_off = []
    for d in sorted(official):
        if official[d] is None:
            continue
        pr = pit_rel(d)
        if pr is None:
            continue
        pit_vs_off.append((pr - float(official[d])) * 100.0)

    # 自检:官方水平端点 vs PIT 表的 majors(两条线在 majors 上应当一致)
    same_lvl = 0
    checked = 0
    for (st, d), v in off_level.items():
        p = pit_level.get((st, d))
        if p is not None:
            checked += 1
            if abs(p - v) < 1e-9:
                same_lvl += 1

    print(f"[B] 冻结案例 {len(cases)} 个;k=1 与官方差中位 {out_by_k.get('1',{})}", flush=True)
    return {
        "official_series": {"source": "state_daily.style_rel_majors_30d",
                            "last_nonnull": max([d for d, v in official.items() if v is not None], default=None),
                            "n_nonnull": len([v for v in official.values() if v is not None])},
        "official_levels_source": "Railway /api/v1/style/index basis=backfilled(style_index_daily,code_ref t039-v5)",
        "pit_levels_source": "style_index_pit_daily(cap)",
        "level_selfcheck": {"checked_days": checked, "identical": same_lvl,
                            "note": "majors 上两条线是否逐日相同(PIT 表与官方表)"},
        "basis_gap_pit_vs_official_pp": summ([abs(x) for x in pit_vs_off]),
        "n_freezes": len(freezes),
        "n_cases": len(cases),
        "by_k": out_by_k,
        "coverage": cov_stats,
        "cases_head": [{"m": c["m"], "coverage": c["coverage"],
                        "day1": {"d": c["daily"][0]["d"],
                                 "majors": c["daily"][0]["majors"],
                                 "second_l1_l2": c["daily"][0]["second_l1_l2"],
                                 "shadow_rel": c["daily"][0]["shadow_rel"]}} for c in cases[:3]],
    }


def _compact(res: dict) -> None:
    """人看的摘要(报告正文照抄这份)。"""
    a, b = res["A_stablecoin_axis"], res["B_style_axis"]
    print("### A 稳定币轴")
    print("official:", json.dumps(a["official_series"], ensure_ascii=False))
    print("defillama:", json.dumps(a["defillama_series"], ensure_ascii=False))
    print("replica:", json.dumps(a["replication_check"], ensure_ascii=False))
    print("overlap:", json.dumps(a["overlap"], ensure_ascii=False))
    print("absdiff:", json.dumps(a["abs_diff_pp"], ensure_ascii=False))
    print("signed:", json.dumps(a["signed_diff_pp"], ensure_ascii=False))
    print("sign:", json.dumps(a["sign_agreement"], ensure_ascii=False))
    print("by_year:", json.dumps({y: {"n": v["n"], "med": v["abs_diff_pp"].get("median"),
                                     "p95": v["abs_diff_pp"].get("p95"), "max": v["abs_diff_pp"].get("max"),
                                     "rate": v["sign_same_rate"], "n_dis": len(v["disagree_days"])}
                                 for y, v in a["by_year"].items()}, ensure_ascii=False))
    print("disagree_days:", json.dumps(a["disagree_days"], ensure_ascii=False))
    print("### B 形态轴")
    print("official:", json.dumps(b["official_series"], ensure_ascii=False))
    print("level_selfcheck:", json.dumps(b["level_selfcheck"], ensure_ascii=False))
    print("basis_gap_pit_vs_official_pp:", json.dumps(b["basis_gap_pit_vs_official_pp"], ensure_ascii=False))
    for k in ("1", "7", "14", "30"):
        v = b["by_k"].get(k)
        if not v:
            continue
        print(f"k={k}: vs_off abs med/p95/max = "
              f"{v['abs_diff_pp_vs_official'].get('median')}/{v['abs_diff_pp_vs_official'].get('p95')}/"
              f"{v['abs_diff_pp_vs_official'].get('max')} signed med = {v['signed_diff_pp_vs_official'].get('median')} | "
              f"vs_pit abs med/p95/max = {v['abs_diff_pp_vs_pit'].get('median')}/"
              f"{v['abs_diff_pp_vs_pit'].get('p95')}/{v['abs_diff_pp_vs_pit'].get('max')} | "
              f"sign_off={v['sign_agreement_vs_official']} sign_pit={v['sign_agreement_vs_pit']} "
              f"gate={v['gate_agreement']} n={v['n_rows']} n_off={v['n_with_official']} n_none={v['n_shadow_none']}")
    print("coverage:", json.dumps(b["coverage"], ensure_ascii=False))
    print("cases:", b["n_cases"], "freezes:", b["n_freezes"])


def main() -> None:
    res = {"card": "T-429", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "note": "只读库;不 import src/;不写库"}
    res["A_stablecoin_axis"] = part_a()
    res["B_style_axis"] = part_b()
    with open(OUT, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    _compact(res)
    print("→ ", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
