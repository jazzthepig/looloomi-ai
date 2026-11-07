#!/usr/bin/env python3
"""T-287 — S-751 盲复算(只看台账文字;自己筛整币下架、自己取价、自己做对照)。

不使用 docs/research/t272_delisting.py 与 src/data/signals/delisting_watch.py。
统计只用 src/data/evaluation/apparatus.py。

用法:
  python3 t287_recompute.py probe     # 看表结构 / 事件样本
  python3 t287_recompute.py screen     # 只筛 368 条 → 落 t287_screening.json
  python3 t287_recompute.py run        # 全流程 → t287_results.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    long_return,
    null_distribution,
    percentile_of,
    price_on_or_after,
    random_dates_like,
)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("SUPABASE_URL / SUPABASE_KEY 未设置", file=sys.stderr)
    raise SystemExit(2)

BASE = URL.rstrip("/")
HDRS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/json",
}
# 每张表的默认排序(翻页必须带 order=)
DEFAULT_ORDER = {
    "events": "ts.asc,id.asc",
    "asset_mcap_daily": "symbol.asc,d.asc",
    "ohlcv_daily": "symbol.asc,trade_date.asc",
}


def rest(path: str, params: dict | None = None, prefer_count: bool = False, order: str | None = None):
    q = dict(params or {})
    order = q.pop("order", None) or order or DEFAULT_ORDER.get(path, "id.asc")   # Seth 合并时:字典里的 order 优先(静态检查只认字典)
    url = f"{BASE}/rest/v1/{path}"
    if q:
        url += "?" + urllib.parse.urlencode(q, safe=",()")
    # 翻页必须带 order=(PostgREST 不带 order 时翻页边界会漂,11-05 实测)
    url += ("&" if q else "?") + "order=" + urllib.parse.quote(order, safe=",.")
    h = dict(HDRS)
    if prefer_count:
        h["Prefer"] = "count=exact"
    req = urllib.request.Request(url, headers=h)
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:  # noqa: PERF203
        raise RuntimeError(f"REST {e.code} {url}\n{e.read().decode()[:800]}") from None
    with resp as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range", "")
        return (json.loads(body) if body else None), cr


def paged(path: str, params: dict, page_size: int = 1000, order: str = "id.asc"):
    """PostgREST 翻页:每页 ≤1000,带 order=,核总行数。"""
    rows: list[dict] = []
    offset = 0
    total = None
    while True:
        p = dict(params)
        p.update({"limit": page_size, "offset": offset})
        chunk, cr = rest(path, p, prefer_count=True, order=order)
        if total is None:
            total = int(cr.split("/")[-1]) if cr else None
        if not chunk:
            break
        rows.extend(chunk)
        offset += len(chunk)
        if len(chunk) < page_size:
            break
    if total is not None and total != len(rows):
        print(f"!! 分页行数不符: Content-Range total={total}, got={len(rows)}", file=sys.stderr)
    return rows


# ───────────────────────────── stage: probe ─────────────────────────────
# (Seth 合并时:几个 limit 1 / 2 的探针也补了 order —— 静态检查不分探针与翻页;已跑过的结果不受影响)
def stage_probe() -> None:
    one, _ = rest("events", {"select": "*", "order": "id.asc", "limit": 1})
    print("events columns:", list(one[0].keys()) if one else "?")
    print("events sample:", json.dumps(one[0], ensure_ascii=False)[:600] if one else "")
    cr = rest("events", {"source": "eq.binance", "kind": "eq.delisting", "select": "id", "order": "id.asc", "limit": 1},
              prefer_count=True)[1]
    print("events total (binance/delisting):", cr)
    m = rest("asset_mcap_daily", {"select": "*", "order": "symbol.asc", "limit": 1})
    print("asset_mcap_daily row:", json.dumps(m, ensure_ascii=False)[:400] if m else "EMPTY")
    o = rest("coingecko_pro_ohlc", {"select": "*", "order": "symbol.asc", "limit": 1})
    print("coingecko_pro_ohlc row:", json.dumps(o, ensure_ascii=False)[:400] if o else "EMPTY")


# ───────────────────────────── stage: pull ─────────────────────────────
def pull_events() -> list[dict]:
    evs = paged("events", {"source": "eq.binance", "kind": "eq.delisting"},
                page_size=1000, order="ts.asc,id.asc")
    out = []
    for e in evs:
        out.append({
            "id": e.get("id"),
            "ts": e.get("ts"),
            "title": e.get("title") or "",
            "symbols": e.get("symbols"),
            "url": e.get("url"),
        })
    return out


def stage_pull() -> None:
    evs = pull_events()
    print("pulled:", len(evs))
    p = HERE / "t287_events_raw.json"
    p.write_text(json.dumps(evs, ensure_ascii=False, indent=1))
    print("wrote", p, p.stat().st_size, "bytes")
    # 标题首 60 字的直方图(自己看模式,先不筛)
    from collections import Counter
    c = Counter(e["title"][:55] for e in evs)
    for k, v in c.most_common(25):
        print(f"{v:4d}  {k}")


# ───────────────────────────── stage: screen ─────────────────────────────
def stage_buckets() -> None:
    evs = json.loads((HERE / "t287_events_raw.json").read_text())
    fams = [
        ("will_delist", re.compile(r"Will Delist", re.I)),
        ("notice_removal", re.compile(r"^Notice of Removal", re.I)),
        ("margin_delist", re.compile(r"Margin to Delist|Delist .*Margin", re.I)),
        ("loans", re.compile(r"Binance Loans|Loans \(", re.I)),
        ("other_delist", re.compile(r"[Dd]elist", re.I)),
    ]
    from collections import Counter
    seen = Counter()
    for e in evs:
        t = e["title"]
        for name, rx in fams:
            if rx.search(t):
                seen[name] += 1
                break
        else:
            seen["no_delist_word"] += 1
    print("title family counts:", seen.most_common())
    # 每个家族看 4 条样例
    for name, rx in fams:
        ex = [e for e in evs if rx.search(e["title"])]
        print(f"\n### {name}  n={len(ex)}")
        for e in ex[:4]:
            print("   ", e["ts"][:10], "|", e["title"][:150])
    ex = [e for e in evs if not any(rx.search(e["title"]) for _, rx in fams)]
    print(f"\n### no_delist_word n={len(ex)}")
    for e in ex[:6]:
        print("   ", e["ts"][:10], "|", e["title"][:150])


def stage_titles() -> None:
    evs = json.loads((HERE / "t287_events_raw.json").read_text())
    generic = re.compile(r"^Notice of Removal of (Trading|Spot Trading) Pairs - \d{4}-\d{2}-\d{2}$", re.I)
    gd = [e for e in evs if generic.match(e["title"])]
    ng = [e for e in evs if e["title"].startswith("Notice of Removal") and not generic.match(e["title"])]
    print(f"generic Notice-of-Removal (no coin names): {len(gd)}   non-generic Notice-of-Removal: {len(ng)}")
    print("\n--- non-generic Notice of Removal, 前 25 条 ---")
    for e in ng[:25]:
        print("  ", e["ts"][:10], "|", e["title"][:110])
    print("\n--- 全部含 'Will Delist' 的标题 ---")
    wd = [e for e in evs if re.search(r"Will Delist", e["title"], re.I)]
    for i, e in enumerate(wd):
        print(f"{i:3d} {e['ts'][:10]} | {e['title'][:120]}")
    print(f"\n--- 其余含 delist 但非 Will Delist ---")
    for e in evs:
        if re.search(r"[Dd]elist", e["title"]) and not re.search(r"Will Delist", e["title"], re.I):
            print("  ", e["ts"][:10], "|", e["title"][:120])
    print(f"\n--- 无 delist 字样的 {len([e for e in evs if not re.search(r'[Dd]elist', e['title'])])} 条 ---")
    for e in evs:
        if not re.search(r"[Dd]elist", e["title"]):
            print("  ", e["ts"][:10], "|", e["title"][:120])


# ─────────────────── 筛选:自己写的「整币下架」规则 ───────────────────
# 规则(写在看价格之前;先对全部标题跑一遍,排除清单落文件):
#  纳入 = Binance **现货整币下架**公告:标题形如 "Binance Will Delist <币名列表> on <YYYY-MM-DD>"
#         (含 "Announced the First Batch of Vote to Delist Results and Will Delist <币名列表> on <date>" 变体)
#  排除 = ① 只针对保证金 / 借贷 / 抵押品 / 期权 / 杠杆代币 / 质押 / Alpha / Earn 的公告(币仍在现货)
#         ② 「移除交易对」类公告(标题不带币名 ⇒ 无从知道哪些币;带币名的也是移除交易对,不是整币下架)
RE_DELIST_RE = re.compile(
    r"^Binance (?:Announced the First Batch of Vote to Delist Results and )?Will Delist (.+?) on (\d{4}-\d{2}-\d{2})$"
)


def classify(title: str) -> tuple[str, list[str]]:
    """返回 (理由, 代币列表)。纳入时理由 = 'included'。"""
    t = title.strip()
    m = RE_DELIST_RE.match(t)
    if m:
        body = m.group(1)
        # 币名列表:逗号 / and / & 分隔
        body = body.replace(" and ", ", ").replace(" & ", ", ").replace("&", ", ")
        toks = [x.strip() for x in body.split(",")]
        toks = [x for x in toks if x and re.fullmatch(r"[A-Z0-9]{1,12}", x)]
        if toks:
            return "included", toks
        return "no_token_parsed", []
    # —— 排除理由(按顺序)——
    if re.search(r"Leveraged Tokens|UP & |UP&|UPDOWN|ADADOWN", t, re.I):
        return "excluded_leveraged_token", []
    if re.search(r"Options", t, re.I):
        return "excluded_options", []
    if re.search(r"Binance Alpha", t, re.I):
        return "excluded_alpha", []
    if re.search(r"Binance Earn|Dual Investment", t, re.I):
        return "excluded_earn", []
    if re.search(r"Staking to Delist", t, re.I):
        return "excluded_staking_only", []
    if re.search(r"Margin|Loan|Loans|Borrowable|Collateral", t, re.I):
        return "excluded_margin_or_loan", []
    if re.search(r"^Notice of Removal of .*Trading Pair", t, re.I):
        return "excluded_pair_removal", []
    if re.search(r"Removal of", t, re.I):
        return "excluded_pair_removal", []
    return "excluded_other", []


def stage_screen() -> None:
    evs = json.loads((HERE / "t287_events_raw.json").read_text())
    from collections import Counter
    reasons = Counter()
    rows = []
    inc_tokens: list[str] = []
    for e in evs:
        reason, toks = classify(e["title"])
        reasons[reason] += 1
        inc_tokens.extend(toks)
        rows.append({"id": e["id"], "ts": e["ts"], "title": e["title"],
                     "reason": reason, "tokens": toks})
    print("368 条 → 理由分布:", reasons.most_common())
    inc = [r for r in rows if r["reason"] == "included"]
    print(f"纳入公告 {len(inc)} 条;提取代币 {len(inc_tokens)} 次,去重 {len(set(inc_tokens))} 个")
    print("重复代币:", [t for t, c in Counter(inc_tokens).items() if c > 1])
    out = {"n_events": len(evs), "n_included_events": len(inc),
           "n_tokens_raw": len(inc_tokens), "n_tokens_unique": len(set(inc_tokens)),
           "reasons": dict(reasons), "rows": rows}
    (HERE / "t287_screening.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t287_screening.json")
    print("\n纳入公告明细:")
    for r in inc:
        print(f"  {r['ts'][:10]} | {len(r['tokens']):2d} | {r['title'][:110]}")


def stage_schema() -> None:
    for tbl in ("asset_mcap_daily", "coingecko_pro_ohlc"):
        rows, cr = rest(tbl, {"select": "*", "order": "symbol.asc", "limit": 2})
        print(f"\n== {tbl} ==")
        print("  cols:", list(rows[0].keys()) if rows else "EMPTY")
        print("  row0:", json.dumps(rows[0], ensure_ascii=False)[:300] if rows else "")
        print("  row1:", json.dumps(rows[1], ensure_ascii=False)[:300] if len(rows) > 1 else "")
        rows2, cr2 = rest(tbl, {"select": "symbol", "order": "symbol.asc", "limit": 1}, prefer_count=True)
        print("  rows(total):", cr2)
        # 抽几个 symbol
        sy, _ = rest(tbl, {"select": "symbol,d", "order": "symbol.asc", "limit": 5})
        print("  sample sym/d:", sy)


def stage_tsdiag() -> None:
    evs = json.loads((HERE / "t287_events_raw.json").read_text())
    inc = [e for e in evs if re.match(RE_DELIST_RE, e["title"].strip())]
    print("纳入公告 ts(前 8):")
    for e in inc[:8]:
        print("   ", e["ts"], "|", e["title"][:70])
    from collections import Counter
    print("ts 小时分布:", Counter(e["ts"][11:13] for e in inc).most_common())
    print("tz 偏移:", Counter(e["ts"][-6:] for e in inc).most_common())


def _fetch_symbol_window(sym: str, d_lo: str, d_hi: str) -> list[dict]:
    rows = paged("asset_mcap_daily",
                 {"symbol": f"eq.{sym}", "d": f"gte.{d_lo}", "d": f"lte.{d_hi}",
                  "select": "symbol,coin_id,d,price,mcap,source", "order": "d.asc"},
                 page_size=1000, order="d.asc")
    return rows or []


def stage_prices() -> None:
    from concurrent.futures import ThreadPoolExecutor
    scr = json.loads((HERE / "t287_screening.json").read_text())
    inc = [r for r in scr["rows"] if r["reason"] == "included"]
    # d0 = 公告时刻所在 UTC 日
    jobs = []
    for r in inc:
        d0 = r["ts"][:10]
        for tok in r["tokens"]:
            jobs.append((tok, d0, r["id"]))
    jobs.sort()
    print("要取的代币-事件对:", len(jobs))

    def one(job):
        tok, d0, eid = job
        from datetime import date, timedelta
        dt = date.fromisoformat(d0)
        lo = (dt - timedelta(days=372)).isoformat()
        hi = (dt + timedelta(days=38)).isoformat()
        try:
            rows = _fetch_symbol_window(tok, lo, hi)
        except Exception as e:  # noqa: BLE001
            return {"token": tok, "d0": d0, "err": str(e)[:120], "rows": []}
        return {"token": tok, "d0": d0, "rows": rows}

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(one, jobs))
    have = [o for o in out if o["rows"]]
    print(f"窗口内有价的代币-事件对: {len(have)} / {len(out)}")
    print("无价(窗口内 0 行):", sorted({o['token'] for o in out if not o['rows']})[:200])
    (HERE / "t287_prices.json").write_text(json.dumps(out, ensure_ascii=False))
    print("wrote t287_prices.json", (HERE / "t287_prices.json").stat().st_size)


# ───────────────────────────── stage: run ─────────────────────────────
def _btc_series() -> tuple[list[str], list]:
    rows = paged("asset_mcap_daily", {"symbol": "eq.BTC", "d": "gte.2020-01-01"},
                 page_size=1000, order="d.asc")
    return [r["d"] for r in rows], [r["price"] for r in rows]


def _try_cross_source_tables() -> list[str]:
    """找台账点名的交叉源表(找不到就报 N/A,不猜)。"""
    found = []
    for name in ("coingecko_pro_ohlc", "coingecko_ohlc_daily", "cg_ohlc_daily",
                 "coingecko_pro_market_chart", "ohlcv_daily"):
        try:
            rows, _ = rest(name, {"select": "*", "order": "id.asc", "limit": 1})
            found.append(f"{name}: {list(rows[0].keys()) if rows else 'EMPTY'}")
        except Exception as e:  # noqa: BLE001
            found.append(f"{name}: MISSING ({str(e)[:60]})")
    return found


def stage_run() -> None:
    from datetime import date, timedelta
    import statistics as st

    prices = json.loads((HERE / "t287_prices.json").read_text())
    scr = json.loads((HERE / "t287_screening.json").read_text())
    bd, bc = _btc_series()
    print("BTC 行数:", len(bd), bd[0], "→", bd[-1])

    def series(rows):
        return [r["d"] for r in rows], [r["price"] for r in rows]

    samples = []      # 每条:token, d0, excess30, excess7, pre30, jump, mcap0
    for o in prices:
        if not o["rows"]:
            continue
        td, tc = series(o["rows"])
        d0 = date.fromisoformat(o["d0"])

        def ex(entry: date, exit_: date, td=td, tc=tc):
            pi = price_on_or_after(td, tc, entry.isoformat())
            po = price_on_or_after(td, tc, exit_.isoformat())
            bi = price_on_or_after(bd, bc, entry.isoformat())
            bo = price_on_or_after(bd, bc, exit_.isoformat())
            if None in (pi, po, bi, bo):
                return None
            return long_return(pi, po) - long_return(bi, bo)

        e30 = ex(d0, d0 + timedelta(days=30))
        if e30 is None:
            continue
        mcap0 = next((r["mcap"] for r in o["rows"] if r["d"] == o["d0"]), None)
        samples.append({
            "token": o["token"], "d0": o["d0"], "excess30": e30,
            "excess7": ex(d0, d0 + timedelta(days=7)),
            "pre30": ex(d0 - timedelta(days=30), d0),
            "jump": ex(d0 - timedelta(days=1), d0),
            "mcap0": mcap0,
        })
    print("可算 30 天超额的代币:", len(samples))

    # 对照:同代币在 [d0-365, d0-60] 里随机取日子(S-751 预注册:200 个日子)
    elig = {}
    for o in prices:
        if not o["rows"]:
            continue
        td, tc = series(o["rows"])
        d0 = date.fromisoformat(o["d0"])
        lo, hi = d0 - timedelta(days=365), d0 - timedelta(days=60)
        ds = []
        for s in td:
            sd = date.fromisoformat(s)
            if sd < lo or sd > hi:
                continue
            if price_on_or_after(td, tc, s) is None:
                continue
            if price_on_or_after(td, tc, (sd + timedelta(days=30)).isoformat()) is None:
                continue
            ds.append(s)
        elig[o["token"]] = ds
    n_elig = sum(1 for v in elig.values() if v)
    print("有合格对照日的代币:", n_elig, "| 对照日天数分布:",
          sorted({len(v) for v in elig.values()})[:12])

    keyed = [s for s in samples]
    ev_med30 = st.median(s["excess30"] for s in keyed)
    ev_med7 = st.median(s["excess7"] for s in keyed if s["excess7"] is not None)
    neg_frac = sum(1 for s in keyed if s["excess30"] < 0) / len(keyed)
    print(f"(a) 30 天超额中位 = {ev_med30*100:.3f}%   (b) 为负比例 = {neg_frac*100:.1f}%")

    # 零分布(同代币随机日对照):每次抽一组对照日 → 算 30 天超额中位
    ev_list = [(s["token"], s["d0"]) for s in keyed]
    by_tok = {o["token"]: o for o in prices}

    def ctrl_median(rng):
        picks = random_dates_like(ev_list, elig, rng)
        vals = []
        for tok, dt in picks:
            if dt is None:
                continue
            o = by_tok[tok]
            td, tc = series(o["rows"])
            sd = date.fromisoformat(dt)
            pi = price_on_or_after(td, tc, dt)
            po = price_on_or_after(td, tc, (sd + timedelta(days=30)).isoformat())
            bi = price_on_or_after(bd, bc, dt)
            bo = price_on_or_after(bd, bc, (sd + timedelta(days=30)).isoformat())
            if None in (pi, po, bi, bo):
                continue
            vals.append(long_return(pi, po) - long_return(bi, bo))
        if not vals:
            return float("nan")
        return st.median(vals)

    null30 = null_distribution(ctrl_median, 200, seed=20261107, actual=ev_med30)
    pctl30 = percentile_of(ev_med30, null30)
    print(f"(c) 对照零分布 200 次:中位 {np.median(null30)*100:.3f}%  "
          f"p05 {np.percentile(null30,5)*100:.3f}%  实际分位 = {pctl30}")

    # (d) 两段
    seg = {"2022-2023": [], "2024-2026": []}
    for s in keyed:
        seg["2022-2023" if s["d0"] < "2024-01-01" else "2024-2026"].append(s["excess30"])
    for k, v in seg.items():
        print(f"(d) {k}: n={len(v)} 中位 {st.median(v)*100:.3f}%" if v else f"(d) {k}: n=0")
    med22 = st.median(seg["2022-2023"]) if seg["2022-2023"] else None
    med24 = st.median(seg["2024-2026"]) if seg["2024-2026"] else None

    # 副项
    pre30 = [s["pre30"] for s in keyed if s["pre30"] is not None]
    jump = [s["jump"] for s in keyed if s["jump"] is not None]
    print(f"副: 公告前 30 天中位 {st.median(pre30)*100:.3f}% (n={len(pre30)}); "
          f"公告当天中位 {st.median(jump)*100:.3f}% (n={len(jump)}); "
          f"7 天超额中位 {ev_med7*100:.3f}%")
    caps = [s for s in keyed if s["mcap0"]]
    caps.sort(key=lambda s: s["mcap0"])
    if caps:
        k = len(caps) // 3
        for name, grp in (("小", caps[:k]), ("中", caps[k:2 * k]), ("大", caps[2 * k:])):
            if grp:
                print(f"   公告前市值三分位 {name}: n={len(grp)} 中位 {st.median(g['excess30'] for g in grp)*100:.2f}%")

    verdict = {
        "a_median30_le_-10pct": bool(ev_med30 <= -0.10),
        "b_neg_frac_ge_65pct": bool(neg_frac >= 0.65),
        "c_pctl_le_0.05": bool(pctl30 is not None and pctl30 <= 0.05),
        "d_two_segments_same_sign": bool(med22 is not None and med24 is not None
                                         and (med22 < 0) == (med24 < 0)),
        "e_priced_ge_40": bool(len(keyed) >= 40),
    }
    print("判据:", verdict)
    res = {
        "ledger_targets": {"n_included_events": 39, "n_tokens": 164, "n_priced": 53,
                           "median30": -0.377, "neg_frac": 0.811, "pctl": 0.000,
                           "seg_2022_2023": -0.027, "seg_2024_2026": -0.377,
                           "cross_source_n": 32, "cross_source_median": -0.543},
        "recompute": {"n_included_events": scr["n_included_events"],
                      "n_tokens": scr["n_tokens_unique"],
                      "n_priced": len(keyed), "median30": ev_med30,
                      "neg_frac": neg_frac, "pctl": pctl30,
                      "seg_2022_2023": med22, "seg_2024_2026": med24,
                      "excess7_median": ev_med7,
                      "pre30_median": st.median(pre30) if pre30 else None,
                      "day_jump_median": st.median(jump) if jump else None,
                      "null_median": float(np.median(null30)),
                      "null_p05": float(np.percentile(null30, 5)),
                      "n_eligible_tokens": n_elig},
        "verdict": verdict,
        "samples": samples,
    }
    (HERE / "t287_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote t287_results.json")


def stage_diag_prices() -> None:
    prices = json.loads((HERE / "t287_prices.json").read_text())
    have = [o for o in prices if o["rows"]]
    print("窗口内有行的对:", len(have))
    for o in have[:14]:
        ds = [r["d"] for r in o["rows"]]
        near = [d for d in ds if o["d0"] <= d <= str(int(o["d0"][:4]) + 1) + o["d0"][4:7] + "01"][:6]
        srcs = {r.get("source") for r in o["rows"]}
        print(f"  {o['token']:8s} d0={o['d0']} n={len(ds):4d} {ds[0]}→{ds[-1]} "
              f"near_d0={near} src={srcs}")


def stage_cross() -> None:
    for line in _try_cross_source_tables():
        print(" ", line)
    rows, _ = rest("asset_mcap_daily", {"select": "source", "order": "symbol.asc,d.asc", "limit": 2000})
    from collections import Counter
    print("asset_mcap_daily source 分布:", Counter(r["source"] for r in rows).most_common())
    for src in ("coingecko_pro_ohlc", "coingecko", "coingecko_pro_market_chart",
                "binance_hist", "yfinance"):
        try:
            r, cr = rest("ohlcv_daily", {"source": f"eq.{src}", "select": "symbol,trade_date,close",
                                          "order": "trade_date.asc", "limit": 2}, prefer_count=True)
            print(f"  ohlcv_daily source={src}: n={cr} sample={r}")
        except Exception as e:  # noqa: BLE001
            print(f"  ohlcv_daily source={src}: ERR {str(e)[:80]}")
    for s in ("BTC", "A2Z", "DATA"):
        r, _ = rest("ohlcv_daily", {"symbol": f"eq.{s}", "select": "symbol,trade_date,close,source,asset_class",
                                    "order": "trade_date.asc", "limit": 3})
        print(f"  ohlcv_daily {s}:", r)


def stage_xsrc() -> None:
    """交叉源核对:ohlcv_daily source = coingecko_pro_ohlc(台账点名的那个源)。"""
    from datetime import date, timedelta
    import statistics as st
    from concurrent.futures import ThreadPoolExecutor

    prices = json.loads((HERE / "t287_prices.json").read_text())
    jobs = []
    for o in prices:
        d0 = date.fromisoformat(o["d0"])
        jobs.append((o["token"], o["d0"],
                     (d0 - timedelta(days=372)).isoformat(),
                     (d0 + timedelta(days=38)).isoformat()))

    def one(j):
        tok, d0, lo, hi = j
        rows = paged("ohlcv_daily",
                     {"symbol": f"eq.{tok}", "source": "eq.coingecko_pro_ohlc",
                      "trade_date": f"gte.{lo}", "trade_date": f"lte.{hi}",
                      "select": "symbol,trade_date,close,source", "order": "trade_date.asc"},
                     page_size=1000, order="trade_date.asc")
        return tok, d0, rows

    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(one, jobs))
    btc_rows = paged("ohlcv_daily", {"symbol": "eq.BTC", "source": "eq.coingecko_pro_ohlc",
                                     "select": "symbol,trade_date,close,source", "order": "trade_date.asc"},
                     page_size=1000, order="trade_date.asc")
    bd = [r["trade_date"] for r in btc_rows]
    bc = [r["close"] for r in btc_rows]
    print("交叉源 BTC 行数:", len(bd), bd[0] if bd else "", "→", bd[-1] if bd else "")

    vals = []
    for tok, d0, rows in got:
        if not rows:
            continue
        td = [r["trade_date"] for r in rows]
        tc = [r["close"] for r in rows]
        d0d = date.fromisoformat(d0)
        pi = price_on_or_after(td, tc, d0)
        po = price_on_or_after(td, tc, (d0d + timedelta(days=30)).isoformat())
        bi = price_on_or_after(bd, bc, d0)
        bo = price_on_or_after(bd, bc, (d0d + timedelta(days=30)).isoformat())
        if None in (pi, po, bi, bo):
            continue
        vals.append({"token": tok, "d0": d0,
                     "excess30": long_return(pi, po) - long_return(bi, bo)})
    if vals:
        med = st.median(v["excess30"] for v in vals)
        neg = sum(1 for v in vals if v["excess30"] < 0) / len(vals)
        print(f"交叉源 coingecko_pro_ohlc: n={len(vals)} 中位 {med*100:.3f}%  为负 {neg*100:.1f}%")
    else:
        med, neg = None, None
        print("交叉源: 0 个可算")
    res = json.loads((HERE / "t287_results.json").read_text())
    res["cross_source"] = {"source": "ohlcv_daily:coingecko_pro_ohlc", "n": len(vals),
                           "median30": med, "neg_frac": neg,
                           "ledger_n": 32, "ledger_median30": -0.543,
                           "samples": vals}
    (HERE / "t287_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote t287_results.json (cross_source)")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if stage == "probe":
        stage_probe()
    elif stage == "pull":
        stage_pull()
    elif stage == "buckets":
        stage_buckets()
    elif stage == "titles":
        stage_titles()
    elif stage == "screen":
        stage_screen()
    elif stage == "schema":
        stage_schema()
    elif stage == "tsdiag":
        stage_tsdiag()
    elif stage == "prices":
        stage_prices()
    elif stage == "diag_prices":
        stage_diag_prices()
    elif stage == "cross":
        stage_cross()
    elif stage == "run":
        stage_run()
    elif stage == "xsrc":
        stage_xsrc()
