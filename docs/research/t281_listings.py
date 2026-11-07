#!/usr/bin/env python3
"""T-281 / S-760 —— Binance「白送的币」上市后 30 天,比一般上币跌得更多吗。

口径一字不改照台账 `REFUTATION_LEDGER.md` S-760(2026-11-07 10:21 UTC,Seth 预注册):
  事件 = events(source=binance, kind=listing);按标题分三组(白送 / 认购 / 一般);
  每个代币取第一次上币公告;d0 = 公告 UTC 日之后第一个有价的日收盘(最多等 10 天);
  价格 asset_mcap_daily(主) / ohlcv_daily(source=coingecko_pro_ohlc)(副);
  超额 = 代币 − BTC;30 天主、90 天副;判据 (a)–(d) 全过才 ✅。

只读:全部 SELECT。零分布 / 盈亏只用 `src/data/evaluation/apparatus.py`。
用法:python3 docs/research/t281_listings.py        (缓存优先,缺则抓)
"""
from __future__ import annotations

import collections
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from src.data.evaluation import apparatus as AP  # noqa: E402

CACHE = Path(os.environ.get("T281_CACHE", "/Volumes/CometCloudAI/cometcloud-local"))
OUT_JSON = HERE / "t281_results.json"
OUT_MANIFEST = HERE / "t281_manifest.json"
OUT_SCEN = HERE / "scenarios" / "lane-c-T-281.json"

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 退出(不猜、不硬编码 key)")

# ── 台账写死的分组关键词 ───────────────────────────────────────────────────
FREE_KW = ("launchpool", "hodler", "megadrop")
PAD_KW = ("launchpad",)
STABLE = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "USDS", "AEUR", "EURI",
          "USD1", "USDE", "USDP", "PYUSD", "FRAX", "LUSD", "GUSD", "RLUSD", "USTC", "SUSDE",
          "BUSD", "EUR", "XUSD", "USDF", "BFUSD"}

# ── HTTP ────────────────────────────────────────────────────────────────────


def _get(path: str, **params):
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}" + (f"?{q}" if q else ""),
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range")


def fetch_all(path: str, **params):
    """翻页读:一律带 order= 与 count=exact(每页 ≤ 1000)。"""
    rows, rng = _get(path, limit=1000, offset=0, **params)
    total = int(rng.split("/")[-1]) if rng and "/" in rng else None
    out = list(rows)
    off = 1000
    while total is None or off < total:
        more, _ = _get(path, limit=1000, offset=off, **params)
        if not more:
            break
        out.extend(more)
        off += 1000
    if total is not None and len(out) != total:
        sys.exit(f"抓取不完整:{path} 拿到 {len(out)} / 表内 {total}")
    return out


def cached(name: str, fn):
    p = CACHE / name
    if p.exists() and p.stat().st_size > 100:
        with p.open() as f:
            return json.load(f)
    data = fn()
    with p.open("w") as f:
        json.dump(data, f)
    return data


# ── 筛选 / 分组(先写死,再对全部事件跑一遍) ──────────────────────────────────


def classify(title: str):
    """→ (group, exclude_reason)。group ∈ {free, pad, general};exclude_reason 为 None 表示合格。"""
    t = title.lower()
    has_free = any(k in t for k in FREE_KW)
    has_pad = any(k in t for k in PAD_KW)
    if "stock" in t or "bstocks" in t or "tokenized securities" in t:
        return None, "F5_股票代币"
    if has_free:
        return "free", None
    if has_pad:
        return "pad", None
    if "trading pairs" in t:
        return None, "F3_交易对公告"
    return "general", None


def is_leveraged(title: str, syms) -> bool:
    """杠杆代币:Binance Leveraged Tokens 形如 <BASE>UP / <BASE>DOWN。

    注意:`PUMP`(S-708 提到的例子)恰好以 `UP` 结尾 —— 用「去后缀后 base 长度 ≥ 2」才不误伤它;
    标题里明写 `Leveraged` 的也直接判为杠杆。"""
    if "leveraged" in title.lower():
        return True
    for s in syms:
        su = str(s).upper()
        for suf in ("UP", "DOWN"):
            if su.endswith(suf) and len(su) - len(suf) >= 2:
                return True
    return False


def build_manifest(events):
    """逐条事件走完全部规则 → 落清单。"""
    manifest = []
    for ev in events:
        scope = (ev.get("payload") or {}).get("scope")
        syms = ev.get("symbols") or []
        title = ev.get("title") or ""
        ts = ev.get("ts")
        utc_day = datetime.fromisoformat(ts).astimezone(timezone.utc).date().isoformat()
        grp, why = None, None
        if scope != "spot":
            why = f"F1_scope={scope}"
        elif not syms:
            why = "F2_无symbols"
        elif is_leveraged(title, syms):
            why = "F4_杠杆代币"
        else:
            grp, why = classify(title)
        manifest.append({
            "id": ev.get("id"), "ts": ts, "utc_day": utc_day, "title": title,
            "scope": scope, "symbols": syms, "group": grp, "exclude": why,
            "url": ev.get("url"),
        })
    return manifest


def first_per_symbol(manifest):
    """每个代币取最早的合格公告。"""
    best = {}
    for m in manifest:
        if m["group"] is None:
            continue
        for s in m["symbols"]:
            s = str(s).upper()
            if s not in best or m["ts"] < best[s]["ts"]:
                best[s] = m
    return best


# ── 价格 ────────────────────────────────────────────────────────────────────


def build_series(rows, date_key, px_key):
    ser = collections.defaultdict(list)
    for r in rows:
        p = r.get(px_key)
        if p is None:
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        if not (p > 0):
            continue
        ser[str(r["symbol"]).upper()].append((str(r[date_key])[:10], p))
    for k in ser:
        ser[k].sort()
    return dict(ser)


def pick(series, target: str, max_gap: int):
    """第一个 ≥ target 且 ≤ target+max_gap 的有价日 → (日期, 价格)。价格语义照 apparatus。"""
    if not series:
        return None
    td = date.fromisoformat(target)
    dates = [d for d, _ in series]
    closes = [p for _, p in series]
    px = AP.price_on_or_after(dates, closes, target, max_gap)
    if px is None:
        return None
    for d, p in series:
        if d < target:
            continue
        if (date.fromisoformat(d) - td).days > max_gap:
            return None
        if p == px:
            return d, px
    return None


def median(xs):
    a = np.asarray([x for x in xs if x is not None], dtype=float)
    return float(np.median(a)) if a.size else None


# ── 主计算 ──────────────────────────────────────────────────────────────────


def compute_events(best, ser_mcap, ser_cg, horizon=30, max_gap_in=10, max_gap_out=10):
    out = []
    for sym, m in sorted(best.items()):
        rec = {"symbol": sym, "group": m["group"], "utc_day": m["utc_day"], "ts": m["ts"],
               "title": m["title"], "event_id": m["id"]}
        for tag, ser in (("mcap", ser_mcap), ("cg", ser_cg)):
            s = ser.get(sym)
            d0 = pick(s, _plus(m["utc_day"], 1), max_gap_in) if s else None
            if d0 is None:
                rec[tag] = {"d0": None, "exit": None, "ret": None, "excess": None}
                continue
            tgt = _plus(d0[0], horizon)
            ex = pick(s, tgt, max_gap_out)
            btc = ser.get("BTC")
            b_in = pick(btc, d0[0], max_gap_out) if btc else None
            b_ex = pick(btc, tgt, max_gap_out) if btc else None
            ret = AP.long_return(d0[1], ex[1]) if ex else None
            bret = AP.long_return(b_in[1], b_ex[1]) if (b_in and b_ex) else None
            rec[tag] = {
                "d0": d0[0], "d0_px": d0[1], "exit": ex[0] if ex else None,
                "hold_days": (date.fromisoformat(ex[0]) - date.fromisoformat(d0[0])).days if ex else None,
                "btc_d0": b_in[0] if b_in else None,
                "ret": ret, "btc_ret": bret,
                "excess": (ret - bret) if (ret is not None and bret is not None) else None,
            }
        out.append(rec)
    return out


def _plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


# ── 判据 ────────────────────────────────────────────────────────────────────


def stat_diff(vals_a, vals_b):
    """中位差(a − b)。"""
    ma, mb = median(vals_a), median(vals_b)
    if ma is None or mb is None:
        return None
    return ma - mb


def null_for_diff(all_vals, n_free, n_gen, n_boot, seed):
    """组标签随机重排的零分布(白送 vs 一般的中位差)。"""
    def one(rng):
        idx = rng.permutation(len(all_vals))
        a = [all_vals[i] for i in idx[:n_free]]
        b = [all_vals[i] for i in idx[n_free:n_free + n_gen]]
        return stat_diff(a, b) or 0.0
    return AP.null_distribution(one, n_boot, seed)


def main():
    events = cached("t281_cache_events.json",
                    lambda: fetch_all("events", source="eq.binance", kind="eq.listing", order="id.asc"))
    print(f"events(binance/listing) = {len(events)}")
    mcap_rows = cached("t281_cache_mcap.json",
                       lambda: fetch_all("asset_mcap_daily", select="symbol,d,price,mcap,source",
                                         order="symbol.asc,d.asc"))
    cg_rows = cached("t281_cache_cg.json",
                     lambda: fetch_all("ohlcv_daily", source="eq.coingecko_pro_ohlc",
                                       select="symbol,trade_date,close,source",
                                       order="symbol.asc,trade_date.asc"))
    print(f"asset_mcap_daily = {len(mcap_rows)};cg ohlc = {len(cg_rows)}")

    manifest = build_manifest(events)
    with OUT_MANIFEST.open("w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    excl = collections.Counter(m["exclude"] for m in manifest if m["exclude"])
    grp_rows = collections.Counter(m["group"] for m in manifest if m["group"])
    print("排除计数:", dict(excl))
    print("分组条数(事件条):", dict(grp_rows))

    best = first_per_symbol(manifest)
    print("唯一代币(每币取第一次公告):", len(best),
          dict(collections.Counter(m["group"] for m in best.values())))

    ser_mcap = build_series(mcap_rows, "d", "price")
    ser_cg = build_series(cg_rows, "trade_date", "close")

    ev30 = compute_events(best, ser_mcap, ser_cg, horizon=30)
    ev90 = compute_events(best, ser_mcap, ser_cg, horizon=90)

    def by_group(evs, tag="mcap", key="excess"):
        g = collections.defaultdict(list)
        for e in evs:
            v = e[tag].get(key)
            if v is not None:
                g[e["group"]].append(v)
        return dict(g)

    G30 = by_group(ev30)
    G90 = by_group(ev90)
    GC = by_group(ev30, "cg")

    # 探索性第三源:ohlcv_daily(source=binance_hist)(Binance 自己的日线)—— 只报,不参与判据
    bh_path = CACHE / "t281_cache_bh.json"
    bh_info = None
    if bh_path.exists():
        ser_bh = build_series(json.load(bh_path.open()), "trade_date", "close")
        G_BH = by_group(compute_events(best, ser_bh, ser_bh, horizon=30))
        bh_info = {
            "source": "ohlcv_daily[binance_hist].close",
            "free": {"n": len(G_BH.get("free", [])), "median": median(G_BH.get("free", []))},
            "general": {"n": len(G_BH.get("general", [])), "median": median(G_BH.get("general", []))},
            "pad": {"n": len(G_BH.get("pad", [])), "median": median(G_BH.get("pad", []))},
            "diff_free_minus_general": stat_diff(G_BH.get("free", []), G_BH.get("general", [])),
        }
        print(f"\n[探索性] 第三源 binance_hist: 白送 n={bh_info['free']['n']} "
              f"中位 {bh_info['free']['median']} / 一般 n={bh_info['general']['n']} "
              f"中位 {bh_info['general']['median']} / 差 {bh_info['diff_free_minus_general']}")

    n_free = len(G30.get("free", []))
    n_gen = len(G30.get("general", []))
    n_pad = len(G30.get("pad", []))

    diff = stat_diff(G30.get("free", []), G30.get("general", []))
    print(f"\n主口径(主源 asset_mcap_daily,30 天):白送 n={n_free} 一般 n={n_gen} 认购 n={n_pad}")
    print(f"  白送中位 {median(G30.get('free', []))} / 一般中位 {median(G30.get('general', []))} "
          f"/ 认购中位 {median(G30.get('pad', []))}")
    print(f"  差(白送 − 一般) = {diff}")

    # (b) 组标签随机重排 5,000 次,种子 760
    pool = G30.get("free", []) + G30.get("general", [])
    null = null_for_diff(pool, n_free, n_gen, 5000, 760)
    p_b = AP.percentile_of(diff, null)
    print(f"  (b) 重排零分布分位 = {p_b}")

    # (c) 两段
    segs = {}
    for name, lo, hi in (("2020-2023", 2020, 2023), ("2024-2026", 2024, 2026)):
        a = [e["mcap"]["excess"] for e in ev30 if e["group"] == "free" and e["mcap"].get("excess") is not None
             and lo <= int(e["utc_day"][:4]) <= hi]
        b = [e["mcap"]["excess"] for e in ev30 if e["group"] == "general" and e["mcap"].get("excess") is not None
             and lo <= int(e["utc_day"][:4]) <= hi]
        segs[name] = {"free_n": len(a), "gen_n": len(b), "free_med": median(a), "gen_med": median(b),
                      "diff": stat_diff(a, b)}
    print("  (c) 分段:", json.dumps(segs, ensure_ascii=False))

    other = [e for e in ev30 if int(e["utc_day"][:4]) < 2020]
    n_other_free = sum(1 for e in other if e["group"] == "free" and e["mcap"].get("excess") is not None)

    crit = {
        "a": {"value_pp": diff, "need_pp": -10.0, "pass": bool(diff is not None and diff <= -10.0)},
        "b": {"percentile": p_b, "need": "<= 0.05", "n_boot": 5000, "seed": 760,
              "pass": bool(p_b is not None and p_b <= 0.05)},
        "c": {"segments": segs, "same_sign": bool(
            segs["2020-2023"]["diff"] is not None and segs["2024-2026"]["diff"] is not None
            and np.sign(segs["2020-2023"]["diff"]) == np.sign(segs["2024-2026"]["diff"])),
            "min_free_per_seg": 15,
            "pass": bool(
                segs["2020-2023"]["diff"] is not None and segs["2024-2026"]["diff"] is not None
                and np.sign(segs["2020-2023"]["diff"]) == np.sign(segs["2024-2026"]["diff"])
                and segs["2020-2023"]["free_n"] >= 15 and segs["2024-2026"]["free_n"] >= 15)},
        "d": {"free_priced": n_free, "need": ">= 40", "pass": bool(n_free >= 40)},
    }
    crit["all_pass"] = all(crit[k]["pass"] for k in "abcd")
    print("  判据:", json.dumps({k: crit[k]["pass"] for k in "abcd"}), "=>", "✅" if crit["all_pass"] else "❌")

    # 副项(只报不判)
    sec = {
        "pad_vs_general_30": {"pad_med": median(G30.get("pad", [])), "gen_med": median(G30.get("general", [])),
                              "diff": stat_diff(G30.get("pad", []), G30.get("general", [])),
                              "pad_n": n_pad},
        "n90": {"free_med": median(G90.get("free", [])), "gen_med": median(G90.get("general", [])),
                "pad_med": median(G90.get("pad", [])),
                "free_vs_gen_diff": stat_diff(G90.get("free", []), G90.get("general", [])),
                "pad_vs_gen_diff": stat_diff(G90.get("pad", []), G90.get("general", [])),
                "free_n": len(G90.get("free", [])), "gen_n": len(G90.get("general", [])),
                "pad_n": len(G90.get("pad", []))},
        "副源_cg": {"free_med": median(GC.get("free", [])), "gen_med": median(GC.get("general", [])),
                    "pad_med": median(GC.get("pad", [])),
                    "free_vs_gen_diff": stat_diff(GC.get("free", []), GC.get("general", [])),
                    "free_n": len(GC.get("free", [])), "gen_n": len(GC.get("general", []))},
        "其他年代(2017-2019)": {"free_n": n_other_free},
    }

    # 敏感性(副项):剔除稳定币后的 (a)
    def drop_stable(group):
        return [e["mcap"]["excess"] for e in ev30 if e["group"] == group
                and e["mcap"].get("excess") is not None and e["symbol"] not in STABLE]
    sec["敏感性_剔除稳定币"] = {
        "剔除的符号": sorted({e["symbol"] for e in ev30 if e["symbol"] in STABLE
                             and e["group"] in ("free", "pad", "general")}),
        "free_med": median(drop_stable("free")), "gen_med": median(drop_stable("general")),
        "diff": stat_diff(drop_stable("free"), drop_stable("general")),
        "free_n": len(drop_stable("free")), "gen_n": len(drop_stable("general"))}

    # 副项:按上市后首日涨幅三分位
    # 「上市后首日涨幅」= d0(第一个有价日收盘)→ 下一个有价日收盘的涨跌 = 上市后第一个完整交易日的涨跌。
    def first_day_move(e):
        s = ser_mcap.get(e["symbol"])
        d0 = e["mcap"].get("d0")
        px0 = e["mcap"].get("d0_px")
        if not s or not d0 or not px0:
            return None
        nxt = pick(s, _plus(d0, 1), 10)
        if not nxt:
            return None
        return nxt[1] / px0 - 1.0

    moves = [(e, first_day_move(e)) for e in ev30]
    have = [(e, m) for e, m in moves if m is not None]
    terc = {}
    if have:
        vals = np.array([m for _, m in have])
        qs = np.quantile(vals, [1 / 3, 2 / 3])
        for name, sel in (("低三分位", vals <= qs[0]), ("中三分位", (vals > qs[0]) & (vals <= qs[1])),
                          ("高三分位", vals > qs[1])):
            sub = [e for (e, m), s in zip(have, sel) if s and e["mcap"].get("excess") is not None]
            terc[name] = {
                "free": median([e["mcap"]["excess"] for e in sub if e["group"] == "free"]),
                "gen": median([e["mcap"]["excess"] for e in sub if e["group"] == "general"]),
                "pad": median([e["mcap"]["excess"] for e in sub if e["group"] == "pad"]),
                "n": len(sub),
                "cut_lo": float(qs[0]), "cut_hi": float(qs[1])}
    sec["首日涨幅三分位"] = {"可算条数": len(have), "分位": terc}

    # 敏感性(副项):若某代币曾有任何白送公告就归白送组(偏离台账「取第一次公告」,只报不判)
    all_by_sym = collections.defaultdict(list)
    for m in manifest:
        if m["group"] is None:
            continue
        for s in m["symbols"]:
            all_by_sym[str(s).upper()].append(m)
    prefer = {}
    for s, ms in all_by_sym.items():
        ms2 = sorted(ms, key=lambda m: (0 if m["group"] == "free" else 1, m["ts"]))
        prefer[s] = ms2[0]
    G_PREF = by_group(compute_events(prefer, ser_mcap, ser_cg, horizon=30))
    moved = sorted(s for s, m in prefer.items()
                   if m["group"] == "free" and s in {x for x, y in best.items() if y["group"] != "free"})
    sec["敏感性_归组优先白送"] = {
        "free": {"n": len(G_PREF.get("free", [])), "median": median(G_PREF.get("free", []))},
        "general": {"n": len(G_PREF.get("general", [])), "median": median(G_PREF.get("general", []))},
        "diff": stat_diff(G_PREF.get("free", []), G_PREF.get("general", [])),
        "从其他组移入白送组": moved,
        "跨组代币总数": sum(1 for ms in all_by_sym.values() if len({x["group"] for x in ms}) > 1),
    }

    # 覆盖损失分解(为什么有价代币这么少)
    mcap_symbols = set(ser_mcap)
    coverage = {}
    for g in ("free", "pad", "general"):
        sub = [e for e in ev30 if e["group"] == g]
        coverage[g] = {
            "symbols": len(sub),
            "priced_30d": sum(1 for e in sub if e["mcap"].get("excess") is not None),
            "symbol_absent_from_table": sum(1 for e in sub if e["symbol"] not in mcap_symbols),
            "first_row_after_announcement": sum(
                1 for e in sub if e["symbol"] in mcap_symbols
                and ser_mcap[e["symbol"]][0][0] > e["utc_day"]),
        }

    hold = [e["mcap"]["hold_days"] for e in ev30 if e["mcap"].get("hold_days") is not None]
    results = {
        "meta": {
            "card": "T-281", "ledger": "S-760", "run_utc": datetime.now(timezone.utc).isoformat(),
            "events_total": len(events), "events_manifest": len(manifest),
            "asset_mcap_daily_rows": len(mcap_rows), "cg_ohlc_rows": len(cg_rows),
            "price_main": "asset_mcap_daily.price", "price_secondary": "ohlcv_daily[coingecko_pro_ohlc].close",
            "d0_rule": "公告 UTC 日 +1 .. +10 内第一个有价日", "exit_rule": "第一个 ≥ d0+N 的有价日(最多 +10 天)",
            "excess": "代币收益 − BTC 同期收益(同源同日历日)",
            "universe": "每个代币取第一次合格上币公告", "stats": "src/data/evaluation/apparatus.py",
        },
        "manifest_counts": {"exclude": dict(excl), "group_events": dict(grp_rows),
                            "symbols_per_group": dict(collections.Counter(m["group"] for m in best.values()))},
        "main": {
            "free": {"n": n_free, "median": median(G30.get("free", [])),
                     "mean": float(np.mean(G30["free"])) if G30.get("free") else None},
            "general": {"n": n_gen, "median": median(G30.get("general", [])),
                        "mean": float(np.mean(G30["general"])) if G30.get("general") else None},
            "pad": {"n": n_pad, "median": median(G30.get("pad", [])),
                    "mean": float(np.mean(G30["pad"])) if G30.get("pad") else None},
            "diff_free_minus_general": diff,
            "hold_days": {"median": float(np.median(hold)) if hold else None, "n": len(hold)},
        },
        "criteria": crit, "secondary": sec,
        "coverage": coverage,
        "bh_exploratory": bh_info,
        "events": [{k: v for k, v in e.items() if k != "title"} for e in ev30],
    }
    with OUT_JSON.open("w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("\n写:", OUT_JSON, OUT_MANIFEST)
    return results


if __name__ == "__main__":
    main()
