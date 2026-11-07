#!/usr/bin/env python3
"""T-272 — S-751:Binance 下架公告之后 30 天,代币在别的场所还继续跑输吗(公告之后,不是公告当天那一跳)。

口径照 REFUTATION_LEDGER S-751 一字不改:事件 = events(source=binance, kind=delisting) 里
**整个代币下架**的公告;d0 = 公告时刻之后的第一个 UTC 日收盘;价格 = CoinGecko 日收盘;
超额 = 代币收益 − BTC 收益;H = 30 天(主) / 7 天(副);对照 = 同一代币在 [d0−365, d0−60]
里随机取 200 个日子,同样算 30 天超额,事件中位数在对照中位数分布里的分位。

阶段(先落文件,再往下走):
  screen  跑筛选规则 → docs/research/t272_screening.json(全部 368 条的纳入/排除清单)
  prices  拉价格     → docs/research/t272_price_cache.json
  stats   算 + 判据  → docs/research/t272_results.json
  all     三段连跑

用法:python3 docs/research/t272_delisting.py [screen|prices|stats|all]
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
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
SCREEN_PATH = os.path.join(HERE, "t272_screening.json")
PRICE_PATH = os.path.join(HERE, "t272_price_cache.json")
RESULT_PATH = os.path.join(HERE, "t272_results.json")

# ── 筛选规则(先写死,再对全表跑)──────────────────────────────────────────────
# 纳入:标题里出现 "Will Delist <代币>…" 且不含任何「仅杠杆 / 仅合约 / 仅交易对 / 仅板块」标记。
# 排除:标题形态本身不是整币现货下架(移除交易对、保证金、借贷、杠杆代币、期权、Alpha、质押、理财…)
BANNED = (
    "Margin", "Loan", "Leveraged Token", "Options", "Alpha", "Staking",
    "Earn", "Redemption", "Trading Pair", "Collateral", "Stocks",
)
NOT_WILL = ("Notice of Removal of", "Notice on Delisting of Binance Loans",
            "Notice Regarding the Removal", "Upcoming Changes to", "Suspension of")


def screen_title(title):
    """→ (include: bool, reason: str)"""
    if "Will Delist" not in title:
        if title.startswith("Notice of Removal of Spot Trading Pairs") or title.startswith("Notice of Removal of Trading Pairs"):
            return False, "pair_removal:spot_or_trading_pairs"
        if title.startswith("Notice of Removal of Margin") or title.startswith("Notice of Removal of Isolated Margin"):
            return False, "pair_removal:margin_pairs"
        if "Notice of Removal of Margin Token" in title:
            return False, "margin_token"
        for p in NOT_WILL:
            if title.startswith(p):
                return False, f"not_a_delisting:{p}"
        if "Binance Alpha" in title:
            return False, "alpha_board"
        return False, "no_will_delist"
    hit = [b for b in BANNED if b in title]
    if hit:
        return False, "banned:" + ",".join(hit)
    return True, "whole_token_delisting"


def extract_perp_symbols(title):
    """perp_delisting 公告的标的:Binance Futures 标题里带 USDT/USD 后缀的合约代码。
    "Multiple …" 那种枚举不出来的 ⇒ 空列表(排除)。"""
    if "Multiple" in title:
        return []
    out = []
    for m in re.finditer(r"\b([A-Z0-9]{1,12})(?:USDT|USDC|BUSD|USD)\b", title):
        s = m.group(1)
        if s in ("USD", "USDT", "USDC", "BUSD", "M", "COIN", "PERPETUAL"):
            continue
        out.append(s)
    # 去掉被 USD 后缀重复切出来的碎片(如 "PORT3" / "3")
    out = [s for s in out if len(s) >= 2]
    seen, keep = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            keep.append(s)
    return keep


def extract_symbols(title):
    """标题里 "Will Delist" 之后的代币列表。"""
    m = re.search(r"\bWill Delist\b(.*)$", title)
    if not m:
        return []
    seg = m.group(1)
    seg = re.sub(r"\s+on\s+\d{4}-\d{2}-\d{2}.*$", "", seg)
    seg = re.sub(r"\s*\(.*?\)\s*$", "", seg)
    out = []
    for part in re.split(r",|\band\b", seg):
        s = part.strip().strip(".").strip()
        if s and re.fullmatch(r"[A-Za-z0-9]{1,12}", s):
            out.append(s.upper())
    return out


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


# ── 阶段 1:screen ───────────────────────────────────────────────────────────
def phase_screen():
    rows, total = rest_rows("events?kind=eq.delisting&order=id.asc")
    print(f"[screen] events(kind=delisting) 抓到 {len(rows)} 行(表内共 {total})")
    assert len(rows) == total, "分页没抓全"
    rows.sort(key=lambda r: r["ts"])

    decisions = []
    included_ann = []
    for r in rows:
        inc, reason = screen_title(r["title"])
        syms = extract_symbols(r["title"]) if inc else []
        d = {
            "id": r["id"], "ts": r["ts"], "title": r["title"], "source": r["source"],
            "kind": r["kind"], "payload": r.get("payload"), "include": inc,
            "reason": reason, "symbols": syms,
        }
        decisions.append(d)
        if inc:
            included_ann.append(d)

    # 一个代币多次公告取第一次
    first = {}
    for d in included_ann:
        for s in d["symbols"]:
            if s not in first or d["ts"] < first[s]["ts"]:
                first[s] = d
    dup = len(included_ann) - sum(len(d["symbols"]) for d in included_ann)
    print(f"[screen] 纳入公告 {len(included_ann)} 条 / 覆盖代币 {len(first)} 个")
    print(f"[screen] 排除 {len(rows) - len(included_ann)} 条;理由分布:",
          dict(Counter(d["reason"] for d in decisions if not d["include"]).most_common()))

    # 副项:perp_delisting(同口径另报)
    perp_rows, perp_total = rest_rows("events?kind=eq.perp_delisting&order=id.asc")
    perp_dec = []
    for r in perp_rows:
        inc, reason = screen_title(r["title"])
        perp_dec.append({"id": r["id"], "ts": r["ts"], "title": r["title"], "include": inc,
                         "reason": reason,
                         "symbols": extract_perp_symbols(r["title"]) if "Futures" in r["title"] else []})
    print(f"[screen] perp_delisting 共 {perp_total} 条;纳入 {sum(1 for d in perp_dec if d['include'])} 条")
    for d in perp_dec:
        if d["include"]:
            print("   PERP+", d["ts"][:10], d["symbols"], "|", d["title"][:90])

    out = {
        "task": "T-272", "ledger": "S-751",
        "screen_rule": {
            "include": '标题含 "Will Delist" 且不含 BANNED 任一词',
            "banned": list(BANNED),
            "one_event_per_token": "同一代币多次公告取最早一次(ts)",
            "d0": "公告 ts 的 UTC 日期收盘",
        },
        "events_total": total,
        "decisions": decisions,
        "included_announcements": included_ann,
        "tokens": {s: first[s] for s in sorted(first)},
        "perp_decisions": perp_dec,
    }
    with open(SCREEN_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[screen] 落 {SCREEN_PATH}")
    return out


# ── 阶段 2:prices ───────────────────────────────────────────────────────────
def phase_prices():
    sc = json.load(open(SCREEN_PATH))
    syms = sorted(set(sc["tokens"]) | {"BTC"})
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
            for attempt in range(3):
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
def series_from(rows, sym, date_key, price_key):
    d = {}
    for r in rows:
        if r["symbol"] != sym:
            continue
        v = r.get(price_key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0 and math.isfinite(fv):
            d[str(r[date_key])[:10]] = fv
    return d


def before_price(dates, closes, d, max_gap_days=3):
    """d 当天或之前 max_gap_days 天内的最后一个有效收盘(apparatus 只有向后版本,这里补一个对称的取价,
    不涉及任何统计:零分布/盈亏/分位一律走 apparatus)。"""
    tgt = date.fromisoformat(str(d)[:10])
    best = None
    for dd, c in zip(dates, closes):
        dd_ = date.fromisoformat(str(dd)[:10])
        if dd_ > tgt:
            continue
        if (tgt - dd_).days > max_gap_days:
            continue  # 太旧;序列升序,最近的那天在后面
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
        "mcap": (build(mcap_rows, "d", "price"), "d"),
        "ohlc": (build(ohlc_rows, "trade_date", "close"), "trade_date"),
    }
    # 公告前市值(用于副项:按公告前市值三分位分组)
    MCAPV = build(mcap_rows, "d", "mcap")
    for nm, (tbl, _) in SRC.items():
        have = sum(1 for s in sc["tokens"] if s in tbl)
        print(f"[stats] 源 {nm}: 命中 {have}/{len(sc['tokens'])} 个代币")

    def anchors(tbl, s, d0):
        """d0 附近 6 个锚点。"""
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

    def run_source(name):
        tbl, _ = SRC[name]
        btc = tbl.get("BTC", {})
        bdates = sorted(btc)
        bcloses = [btc[x] for x in bdates]
        btc_g = lambda tgt: price_on_or_after(bdates, bcloses, tgt, 3)  # noqa: E731

        per_token = {}
        for sym, ev in sc["tokens"].items():
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
        # (d) 两段中位数
        seg = {}
        for lo, hi, nm in ((2022, 2023, "2022-2023"), (2024, 2026, "2024-2026")):
            vals = sorted(r["ret30"] for s, r in usable.items() if lo <= int(s and r["d0"][:4]) <= hi)
            seg[nm] = {"n": len(vals), "median": float(vals[len(vals) // 2]) if vals else None}
        # 对照:同一代币在 [d0−365, d0−60] 里随机取日子
        eligible = {}
        for s, r in usable.items():
            d0 = date.fromisoformat(r["d0"])
            lo, hi = d0 - timedelta(days=365), d0 - timedelta(days=60)
            cand = []
            for dd in sorted(SRC[name][0].get(s, {})):
                if lo <= date.fromisoformat(dd) <= hi:
                    cand.append(dd)
            eligible[s] = cand
        ev_pairs = [(s, usable[s]["d0"]) for s in sorted(usable)]
        n_samp = 200
        usable_pairs = [(s, d) for s, d in ev_pairs if eligible.get(s)]

        def one_draw(rng):
            picks = random_dates_like(usable_pairs, eligible, rng, stratum=lambda x: "all")
            vals = []
            for s, d in picks:
                if d is None:
                    continue
                dd = date.fromisoformat(d)
                tbl_ = SRC[name][0]
                ds = sorted(tbl_.get(s, {}))
                cs = [tbl_[s][x] for x in ds]
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

        null = null_distribution(one_draw, n_samp, seed=20261107, actual=med)
        null_f = [x for x in null if x is not None]
        pctl = percentile_of(med, null_f)
        return {
            "source": name, "n_tokens_total": len(per_token),
            "n_tokens_with_price": sum(1 for r in per_token.values() if r.get("status") == "ok"),
            "n_exc30_computable": len(usable),
            "median_exc30": med,
            "pct_negative_exc30": (neg / len(exc30)) if exc30 else None,
            "n_negative": neg,
            "segments": seg,
            "control": {"n_samples": n_samp, "null_median_q": {
                "q05": float(sorted(null_f)[int(0.05 * len(null_f))]) if null_f else None,
                "q50": float(sorted(null_f)[len(null_f) // 2]) if null_f else None,
                "q95": float(sorted(null_f)[int(0.95 * len(null_f))]) if null_f else None},
                "percentile_of_actual": pctl,
                "n_draws_used": len(null_f)},
            "per_token": per_token,
        }

    res = {name: run_source(name) for name in SRC}

    # 判据(照 S-751 (a)–(e),主源 = asset_mcap_daily;另一源作交叉核对)
    primary = res["mcap"]
    a_ok = primary["median_exc30"] is not None and primary["median_exc30"] <= -0.10
    b_ok = primary["pct_negative_exc30"] is not None and primary["pct_negative_exc30"] >= 0.65
    c_ok = primary["control"]["percentile_of_actual"] is not None and primary["control"]["percentile_of_actual"] <= 0.05
    s1, s2 = primary["segments"]["2022-2023"]["median"], primary["segments"]["2024-2026"]["median"]
    d_ok = s1 is not None and s2 is not None and (s1 < 0) == (s2 < 0)
    e_ok = primary["n_exc30_computable"] >= 40
    verdict = "PASS_announced_after" if all([a_ok, b_ok, c_ok, d_ok, e_ok]) else "FAIL"
    primary["criteria"] = {
        "(a) 30天超额中位数 ≤ −10%": {"value": primary["median_exc30"], "pass": a_ok},
        "(b) ≥65% 事件超额为负": {"value": primary["pct_negative_exc30"], "pass": b_ok},
        "(c) 对照分位 ≤ 0.05": {"value": primary["control"]["percentile_of_actual"], "pass": c_ok},
        "(d) 2022-23 与 2024-26 两段中位数同号": {"value": {"2022-2023": s1, "2024-2026": s2}, "pass": d_ok},
        "(e) 有价可算代币 ≥ 40": {"value": primary["n_exc30_computable"], "pass": e_ok},
    }
    primary["verdict"] = verdict

    # 敏感性:① 剔除 ticker 可能复用的样本(coin_id 与 ticker 对不上)② 剔除极端值
    COIN_ID = {s: (rows[0].get("coin_id") if rows else None)
               for s, rows in json.load(open(PRICE_PATH))["asset_mcap_daily"].items()}
    # ticker 是否出现在 coin_id 里只是**提示**(多数 coin_id 用全名而非 ticker,会误报);
    # 真正按 coin_id 逐条核对过、疑似复用到别的币的只有 DATA(→ story-2,ticker 应是 STORY)。
    SUSPECT = {"DATA"}
    auto_flag = sorted(s for s, v in primary["per_token"].items()
                       if v.get("status") == "ok" and v.get("ret30") is not None
                       and COIN_ID.get(s) and s.lower() not in str(COIN_ID.get(s)).lower())
    suspicious = sorted(SUSPECT)
    def med_of(items):
        v = sorted(items)
        return float(v[len(v) // 2]) if v else None
    def negpct(items):
        return (sum(1 for x in items if x < 0) / len(items)) if items else None
    _pt = primary["per_token"]
    allv = [v["ret30"] for v in _pt.values() if v.get("ret30") is not None]
    keep = [v["ret30"] for s, v in _pt.items() if s not in suspicious and v.get("ret30") is not None]
    trimmed = sorted(allv)[3:]
    primary["sensitivity"] = {
        "suspicious_ticker_symbols": suspicious,
        "suspicious_coin_ids": {s: COIN_ID.get(s) for s in suspicious},
        "auto_flag_not_used": auto_flag,
        "all_coin_ids": {s: COIN_ID.get(s) for s in primary["per_token"]
                         if primary["per_token"][s].get("ret30") is not None},
        "drop_suspicious": {"n": len(keep), "median_exc30": med_of(keep), "pct_negative": negpct(keep)},
        "drop_top3_extremes": {"n": len(trimmed), "median_exc30": med_of(trimmed), "pct_negative": negpct(trimmed)},
        "deciles": [round(x, 4) for x in [sorted(allv)[int(q * len(allv))] for q in (0, .1, .25, .5, .75, .9)]] if allv else None,
    }

    # 副项(只报不判)
    prim = primary["per_token"]
    pre30 = sorted(v["pre30"] for v in prim.values() if v.get("status") == "ok" and v.get("pre30") is not None)
    jump = sorted(v["jump"] for v in prim.values() if v.get("status") == "ok" and v.get("jump") is not None)
    exc7 = sorted(v["ret7"] for v in prim.values() if v.get("status") == "ok" and v.get("ret7") is not None)
    # 公告前市值三分位(副项)
    tert = {}
    mv = {}
    for s, r in prim.items():
        if r.get("status") != "ok":
            continue
        tbl_m = MCAPV.get(s, {})
        ds = sorted(tbl_m)
        cs = [tbl_m[x] for x in ds]
        v = before_price(ds, cs, (date.fromisoformat(r["d0"]) - timedelta(days=1)).isoformat(), 3)
        if v is not None:
            mv[s] = v
    if len(mv) >= 6:
        srt = sorted(mv, key=lambda s: mv[s])
        k = len(srt) // 3
        buckets = {"low": srt[:k], "mid": srt[k:2 * k], "high": srt[2 * k:]}
        for nm, members in buckets.items():
            vals = sorted(prim[s]["ret30"] for s in members if prim[s].get("ret30") is not None)
            tert[nm] = {"n": len(vals),
                        "median_exc30": float(vals[len(vals) // 2]) if vals else None,
                        "mcap_lo": min(mv[s] for s in members), "mcap_hi": max(mv[s] for s in members)}
    tertiary = tert
    # perp_delisting 同口径(用 mcap 源)
    perp = sc["perp_decisions"]
    perp_tokens = {}
    for d in perp:
        if not d["include"]:
            continue
        for s in d["symbols"]:
            if s not in perp_tokens or d["ts"] < perp_tokens[s]["ts"]:
                perp_tokens[s] = d
    perp_rows = []
    for s, ev in perp_tokens.items():
        tbl = SRC["mcap"][0]
        if s not in tbl:
            perp_rows.append({"token": s, "status": "no_price_source"})
            continue
        d0 = date.fromisoformat(ev["ts"][:10])
        a = anchors(tbl, s, d0)
        btc = SRC["mcap"][0].get("BTC", {})
        bd = sorted(btc)
        bc = [btc[x] for x in bd]
        b0 = price_on_or_after(bd, bc, d0.isoformat(), 3)
        b1 = price_on_or_after(bd, bc, (d0 + timedelta(days=30)).isoformat(), 3)
        tr, br = long_return(a["d0"], a["p30"]), long_return(b0, b1)
        perp_rows.append({"token": s, "ts": ev["ts"], "title": ev["title"],
                          "exc30": None if (tr is None or br is None) else tr - br})
    pexc = sorted(x["exc30"] for x in perp_rows if x.get("exc30") is not None)

    out = {
        "task": "T-272", "ledger": "S-751", "run_utc": "2026-11-07",
        "primary_source": "asset_mcap_daily",
        "sources": res,
        "verdict": verdict,
        "criteria": primary["criteria"],
        "secondary": {
            "note": "副项只报不判",
            "pre30_exc_median": float(pre30[len(pre30) // 2]) if pre30 else None, "pre30_n": len(pre30),
            "announce_day_jump_median": float(jump[len(jump) // 2]) if jump else None, "jump_n": len(jump),
            "exc7_median": float(exc7[len(exc7) // 2]) if exc7 else None, "exc7_n": len(exc7),
            "perp_delisting": {"n_tokens": len(perp_rows),
                               "n_computable": len(pexc),
                               "median_exc30": float(pexc[len(pexc) // 2]) if pexc else None,
                               "pct_negative": (sum(1 for v in pexc if v < 0) / len(pexc)) if pexc else None,
                               "rows": perp_rows},
            "mcap_tertile": tertiary,
        },
    }
    with open(RESULT_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[stats] 落 {RESULT_PATH}")
    print(json.dumps({"verdict": verdict, "criteria": primary["criteria"],
                      "n_exc30": primary["n_exc30_computable"]}, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    ph = sys.argv[1] if len(sys.argv) > 1 else "all"
    if ph in ("screen", "all"):
        phase_screen()
    if ph in ("prices", "all"):
        phase_prices()
    if ph in ("stats", "all"):
        phase_stats()
