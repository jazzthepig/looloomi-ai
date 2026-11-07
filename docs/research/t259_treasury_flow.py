#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-259 / S-738 —— 国库 BTC 净买入(按时点可得日)对之后 30 天 BTC:是因还是影。

预注册原文见 REFUTATION_LEDGER.md S-738(可得日规则 / 信号 / 判据一字不改)。
本脚本只读、只算:不写库、不改其它代码。零分布只用 src/data/evaluation/apparatus.py。

用法:
    python3 docs/research/t259_treasury_flow.py --probe   # 表结构 / 规模 / 情景表键
    python3 docs/research/t259_treasury_flow.py           # 全量分析 → t259_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("需要环境变量 SUPABASE_URL 与 SUPABASE_KEY(publishable 只读)")

HDRS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_JSON = os.path.join(HERE, "t259_results.json")
PAGE = 1000  # PostgREST 每页硬上限 1000


def _load_apparatus():
    """只用 src/data/evaluation/apparatus.py(验证装置);import 失败则按路径加载同一个文件。"""
    try:
        from src.data.evaluation import apparatus  # type: ignore

        return apparatus
    except Exception:  # noqa: BLE001
        import importlib.util

        p = os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py")
        spec = importlib.util.spec_from_file_location("apparatus_t259", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


AP = _load_apparatus()


# ── 取数(只读,分页带 order) ────────────────────────────────────────────────

def _url(table: str, params: dict) -> str:
    safe = ",().*:<>=!+-/ _$"
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe=safe)}" for k, v in params.items())
    return f"{SUPABASE_URL}/rest/v1/{table}?{q}"


def fetch(table: str, params: dict) -> list[dict]:
    req = urllib.request.Request(_url(table, params), headers=HDRS)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def count(table: str, params: dict) -> int:
    req = urllib.request.Request(
        _url(table, dict(params, limit=1)), headers=dict(HDRS, Prefer="count=exact"), method="HEAD"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else -1


def fetch_paged(table: str, params: dict, order: str) -> list[dict]:
    """按主键排序分页取全(每页 <=1000)。"""
    out: list[dict] = []
    offset = 0
    while True:
        p = dict(params)
        p.update({"order": order, "limit": PAGE, "offset": offset})
        assert "order=" in _url(table, p)  # 每次分页请求都必须带 order=(PostgREST 翻页边界会漂)
        rows = fetch(table, p)
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out


# ── 统计(秩相关 / 回归 / 装置的零分布) ─────────────────────────────────────

def rankdata(a) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="mergesort")
    s = a[order]
    ranks = np.empty(len(a), dtype=float)
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x, y) -> float:
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def ols_resid(y, x) -> np.ndarray:
    """y = a + b·x + e,返回残差 e。"""
    yy = np.asarray(y, dtype=float)
    xx = np.asarray(x, dtype=float)
    X = np.column_stack([np.ones_like(xx), xx])
    beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
    return yy - X @ beta


def perm_test(x, y, *, block: int = 8, n: int = 1000, seed: int = 738) -> dict:
    """块置换零分布:打乱 x 的时间顺序(保留块内结构),y 固定。零分布只用 apparatus。"""
    actual = spearman(x, y)

    def fn(rng):
        return spearman(AP.block_permute(np.asarray(x, dtype=float), block, rng), y)

    try:
        null = AP.null_distribution(fn, n, seed, actual=actual)
    except AP.NoOpNull as e:
        return {"rho": actual, "p_two_sided": None, "p_one_sided_high": None,
                "percentile": None, "null_n": 0, "note": f"NoOpNull:{e}"}
    pct = AP.percentile_of(actual, null)
    p_hi = None if pct is None else float(1.0 - pct)
    p_two = None if pct is None else float(min(1.0, 2.0 * min(pct, 1.0 - pct)))
    return {"rho": actual, "p_two_sided": p_two, "p_one_sided_high": p_hi,
            "percentile": pct, "null_n": int(len(null)),
            "null_mean": float(np.mean(null)), "null_sd": float(np.std(null, ddof=1))}


# ── 可得日规则(S-738 写死) ────────────────────────────────────────────────

QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}


def is_month_end(d: date) -> bool:
    nxt = d + timedelta(days=1)
    return nxt.month != d.month


def avail_date(d: date, mode: str = "prereg") -> date:
    """预注册:季末 → +45 天(10-Q 时滞);月末(非季末)→ +5 天;其余 → +1 天。敏感度:统一 +7 天。"""
    if mode == "flat7":
        return d + timedelta(days=7)
    if (d.month, d.day) in QUARTER_ENDS:
        return d + timedelta(days=45)
    if is_month_end(d):
        return d + timedelta(days=5)
    return d + timedelta(days=1)


def delay_days(d: date, mode: str = "prereg") -> int:
    return (avail_date(d, mode) - d).days


def dd_class(d: date) -> str:
    if (d.month, d.day) in QUARTER_ENDS:
        return "quarter_end"
    if is_month_end(d):
        return "month_end"
    return "other"


# ── 载入 ───────────────────────────────────────────────────────────────────

def load_decisions(coin_id: str) -> list[dict]:
    return fetch_paged(
        "treasury_decisions",
        {"coin_id": f"eq.{coin_id}", "select": "*"},
        "decision_date.asc,entity_id.asc,decision_type.asc,recorded_at.asc",
    )


def load_market(symbol: str) -> dict[str, dict]:
    rows = fetch_paged(
        "asset_mcap_daily",
        {"symbol": f"eq.{symbol}", "select": "d,price,mcap,volume"},
        "d.asc",
    )
    out = {}
    for r in rows:
        d = str(r["d"])[:10]
        p, mc, v = r.get("price"), r.get("mcap"), r.get("volume")
        out[d] = {"price": float(p) if p is not None else None,
                  "mcap": float(mc) if mc is not None else None,
                  "volume": float(v) if v is not None else None}
    return out


# ── 信号 ───────────────────────────────────────────────────────────────────

def build_series(decisions: list[dict], mkt: dict[str, dict], *,
                 sample_start: str, sample_end: str | None,
                 mode: str = "prereg", denom: str = "volume", asof_shift: int = 0,
                 exclude_entity: str | None = None, flow: str = "net") -> dict:
    """周一信号:TB(d) = 可得日 ∈ (d−28, d] 的 BTC 买入金额 − 卖出金额(美元),除以 BTC 过去 30 天日均成交额。

    asof_shift:信息整体挪几天(0 = 预注册原样;1 = 判完再挪一天,验证不依赖信号日当天)。
    flow: net = 买入−卖出;sell = 只算卖出金额(绝对值)。
    """
    evs = []
    for r in decisions:
        if exclude_entity and r.get("entity_id") == exclude_entity:
            continue
        amt = r.get("transaction_value_usd")
        if amt is None:
            continue
        d = date.fromisoformat(str(r["decision_date"])[:10])
        av = avail_date(d, mode)
        signed = float(amt) if r.get("decision_type") == "buy" else -float(amt)
        evs.append({"av": av, "signed": signed, "amt": float(amt),
                    "type": r.get("decision_type"), "entity": r.get("entity_id"), "dd": d})
    evs.sort(key=lambda e: (e["av"], e["dd"]))

    md = sorted(mkt)
    closes = [mkt[x]["price"] for x in md]
    idx = {d: i for i, d in enumerate(md)}
    vols = {d: mkt[d]["volume"] for d in md}
    mcaps = {d: mkt[d]["mcap"] for d in md}

    def trailing_mean(series: dict, asof: date, n: int = 30):
        vals = []
        for k in range(n):
            kk = (asof - timedelta(days=k)).isoformat()
            v = series.get(kk)
            if v is None:
                return None, None
            vals.append(v)
        return float(np.mean(vals)), vals

    rows = []
    d0 = date.fromisoformat(sample_start)
    d_end = date.fromisoformat(sample_end) if sample_end else date.fromisoformat(md[-1])
    cur = d0
    while cur <= d_end:
        if cur.weekday() == 0:  # 周一
            asof = cur - timedelta(days=asof_shift)
            win_hi, win_lo = asof, asof - timedelta(days=28)
            inc = [e for e in evs if win_lo < e["av"] <= win_hi]
            if flow == "net":
                net = float(sum(e["signed"] for e in inc))
            else:
                net = float(sum(e["amt"] for e in inc if e["type"] == "sell"))
            dm, _ = trailing_mean(vols, asof, 30)
            mm, _ = trailing_mean(mcaps, asof, 30)
            base = dm if denom == "volume" else mm
            tb = (net / base) if (base and base > 0) else None
            # 过去 30 天收益(残差化用)
            p_entry = AP.price_on_or_after(md, closes, (asof - timedelta(days=30)).isoformat(), 3)
            p_now = AP.price_on_or_after(md, closes, asof.isoformat(), 3)
            past30 = (p_now / p_entry - 1.0) if (p_entry and p_now) else None
            # 之后 30 天收益(入场 d,出场 d+30)
            f_entry = AP.price_on_or_after(md, closes, cur.isoformat(), 3)
            f_exit = AP.price_on_or_after(md, closes, (cur + timedelta(days=30)).isoformat(), 3)
            fwd = AP.long_return(f_entry, f_exit)
            rows.append({"d": cur.isoformat(), "asof": asof.isoformat(), "n_inc": len(inc),
                         "net_usd": net, "tb": tb, "past30": past30, "fwd30": fwd,
                         "entities": sorted({e["entity"] for e in inc}),
                         "inc_avail": [e["av"].isoformat() for e in inc]})
        cur += timedelta(days=1)
    return {"rows": rows, "events": evs}


def fwd_tb(decisions: list[dict], d: date, *, mode: str = "prereg", exclude_entity: str | None = None) -> float:
    """之后 4 周(严格在 d 之后)的净买入美元 —— 反身性子分析用。"""
    lo, hi = d, d + timedelta(days=28)
    net = 0.0
    for r in decisions:
        if exclude_entity and r.get("entity_id") == exclude_entity:
            continue
        amt = r.get("transaction_value_usd")
        if amt is None:
            continue
        av = avail_date(date.fromisoformat(str(r["decision_date"])[:10]), mode)
        if lo < av <= hi:
            net += float(amt) if r.get("decision_type") == "buy" else -float(amt)
    return net


# ── 数据体检 ───────────────────────────────────────────────────────────────

def health(decisions: list[dict], mkt: dict[str, dict], mode: str = "prereg", symbol: str = "BTC") -> dict:
    by_year: dict[str, dict] = defaultdict(lambda: {"rows": 0, "buy_rows": 0, "sell_rows": 0,
                                                     "buy_usd": 0.0, "sell_usd": 0.0,
                                                     "null_amt_rows": 0, "entities": set()})
    cls = {"quarter_end": 0, "month_end": 0, "other": 0}
    strat_rows = strat_usd = 0
    null_amt = 0
    delays: dict[str, int] = defaultdict(int)
    by_entity: dict[str, dict] = defaultdict(lambda: {"rows": 0, "usd": 0.0})
    seen: dict[tuple, int] = defaultdict(int)
    for r in decisions:
        d = date.fromisoformat(str(r["decision_date"])[:10])
        y = str(d.year)
        b = by_year[y]
        b["rows"] += 1
        b["entities"].add(r.get("entity_id"))
        amt = r.get("transaction_value_usd")
        key = (r.get("entity_id"), r.get("coin_id"), str(r["decision_date"])[:10],
               r.get("decision_type"), amt, r.get("holding_net_change"), r.get("holding_balance"))
        seen[key] += 1
        if amt is None:
            null_amt += 1
            b["null_amt_rows"] += 1
            continue
        amt = float(amt)
        e = by_entity[str(r.get("entity_id"))]
        e["rows"] += 1
        e["usd"] += amt
        if r.get("decision_type") == "buy":
            b["buy_rows"] += 1
            b["buy_usd"] += amt
        else:
            b["sell_rows"] += 1
            b["sell_usd"] += amt
        cls[dd_class(d)] += 1
        delays[str(delay_days(d, mode))] += 1
        if r.get("entity_id") == "strategy":
            strat_rows += 1
            strat_usd += amt
    n = len(decisions)
    n_amt = sum(b["buy_rows"] + b["sell_rows"] for b in by_year.values())
    total_usd = sum(b["buy_usd"] + b["sell_usd"] for b in by_year.values())
    dups = sum(c - 1 for c in seen.values() if c > 1)
    return {
        "rows_total": n, "rows_with_amount": n_amt, "rows_null_amount": null_amt,
        "exact_duplicate_rows": dups,
        "buy_usd_total": sum(b["buy_usd"] for b in by_year.values()),
        "sell_usd_total": sum(b["sell_usd"] for b in by_year.values()),
        "usd_total": total_usd,
        "n_distinct_entities": len(by_entity),
        "top_entities_by_usd": sorted(
            ({"entity": k, "rows": v["rows"], "usd": v["usd"],
              "usd_pct": round(100.0 * v["usd"] / max(total_usd, 1e-9), 2)} for k, v in by_entity.items()),
            key=lambda x: -x["usd"])[:8],
        "by_year": {y: {**{k: v for k, v in b.items() if k != "entities"},
                        "n_entities": len(b["entities"]),
                        "entities": sorted(x for x in b["entities"] if x)} for y, b in sorted(by_year.items())},
        "decision_date_class": {k: {"n": v, "pct": round(100.0 * v / max(n_amt, 1), 2)} for k, v in cls.items()},
        "delay_days_hist": dict(sorted(delays.items(), key=lambda kv: int(kv[0]))),
        "strategy": {"rows": strat_rows, "row_pct": round(100.0 * strat_rows / max(n, 1), 2),
                     "usd": strat_usd,
                     "usd_pct": round(100.0 * strat_usd / max(total_usd, 1e-9), 2)},
        "market": {"symbol": symbol, "n_days": len(mkt), "first": min(mkt) if mkt else None,
                   "last": max(mkt) if mkt else None},
    }


# ── 断言(可得日规则:信号日之后才可得的决定不进信号) ─────────────────────

def run_assertions(series: dict, decisions: list[dict], mkt: dict[str, dict], mode: str) -> list[dict]:
    out = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    # 规则本身(预注册口径;flat7 敏感度另按「统一 +7 天」断言)
    q = date(2024, 3, 31)
    if mode == "prereg":
        chk("季末 +45 天", avail_date(q, mode) == q + timedelta(days=45), f"{avail_date(q, mode)}")
        m = date(2024, 1, 31)
        chk("月末(非季末)+5 天", avail_date(m, mode) == m + timedelta(days=5), f"{avail_date(m, mode)}")
        o = date(2024, 1, 15)
        chk("普通日 +1 天", avail_date(o, mode) == o + timedelta(days=1), f"{avail_date(o, mode)}")
        chk("季末优先于月末(06-30)", avail_date(date(2024, 6, 30), mode) == date(2024, 6, 30) + timedelta(days=45))
    else:
        chk("统一 +7 天(敏感度口径)", avail_date(q, mode) == q + timedelta(days=7)
            and avail_date(date(2024, 1, 15), mode) == date(2024, 1, 15) + timedelta(days=7),
            f"{avail_date(q, mode)}")

    rows = series["rows"]
    evs = series["events"]
    # 1) 进信号的每一条都在窗口内
    bad = []
    for r in rows:
        hi = date.fromisoformat(r["asof"])
        lo = hi - timedelta(days=28)
        for av_s in r["inc_avail"]:
            av = date.fromisoformat(av_s)
            if not (lo < av <= hi):
                bad.append((r["d"], av_s))
    chk("进入信号的每条决定都满足 (d−28, d]", not bad, str(bad[:5]))
    # 2) 每条可得日在窗口内的决定都进了信号
    miss = []
    for r in rows:
        hi = date.fromisoformat(r["asof"])
        lo = hi - timedelta(days=28)
        want = sorted(e["av"].isoformat() for e in evs if lo < e["av"] <= hi)
        if want != sorted(r["inc_avail"]):
            miss.append(r["d"])
    chk("窗口内每条可得决定都进了信号(不多不少)", not miss, str(miss[:5]))
    # 3) 信号日之后才可得的决定绝不在该信号里
    late = []
    for r in rows:
        hi = date.fromisoformat(r["asof"])
        for e in evs:
            if e["av"] > hi and e["av"].isoformat() in r["inc_avail"]:
                late.append((r["d"], e["av"].isoformat()))
    chk("可得日晚于信号日的决定不进该信号", not late, str(late[:5]))
    # 4) 一条决定只在其可得日之后的 4 周窗口内出现
    span_bad = []
    for r in rows:
        hi = date.fromisoformat(r["asof"])
        lo = hi - timedelta(days=28)
        for av_s in r["inc_avail"]:
            av = date.fromisoformat(av_s)
            if not (av <= hi and av > lo):
                span_bad.append((r["d"], av_s))
    chk("每条决定只在可得日后的 28 天窗口内出现", not span_bad, str(span_bad[:5]))
    # 5) 分母只用 <= asof 的成交额
    md = sorted(mkt)
    denom_bad = []
    for r in rows:
        asof = date.fromisoformat(r["asof"])
        for k in range(30):
            kk = (asof - timedelta(days=k)).isoformat()
            if kk not in mkt:
                denom_bad.append((r["d"], kk))
                break
    chk("分母的 30 天窗口全在 asof 之前(含 asof)", not denom_bad, str(denom_bad[:5]))
    # 6) 前视:有信号但算不出之后 30 天收益的行,必须都在样本尾部(结果窗还没走完)
    last_mkt = max(mkt) if mkt else None
    fwd_bad = []
    for r in rows:
        if r["fwd30"] is None and r["tb"] is not None and last_mkt:
            if (date.fromisoformat(last_mkt) - date.fromisoformat(r["d"])).days > 30:
                fwd_bad.append(r["d"])
    chk("算不出之后 30 天收益的行都在样本最后 30 天内", not fwd_bad, str(fwd_bad[:5]))
    # 7) TB=0 ⇔ 窗口内净额为 0;窗口内没有决定 ⇒ 净额必为 0
    zero_bad = [r["d"] for r in rows if r["tb"] == 0 and abs(r["net_usd"]) > 0]
    chk("TB=0 的行净额确实是 0", not zero_bad, str(zero_bad[:5]))
    empty_bad = [r["d"] for r in rows if r["n_inc"] == 0 and abs(r["net_usd"]) > 0]
    chk("窗口内没有决定的行净额为 0", not empty_bad, str(empty_bad[:5]))
    return out


# ── 主流程 ─────────────────────────────────────────────────────────────────

def analyze(decisions: list[dict], mkt: dict[str, dict], *, label: str, sample_start: str,
            mode: str = "prereg", denom: str = "volume", asof_shift: int = 0,
            exclude_entity: str | None = None, flow: str = "net",
            do_perm: bool = True, seg_perm: bool = False) -> dict:
    s = build_series(decisions, mkt, sample_start=sample_start, sample_end=None, mode=mode,
                      denom=denom, asof_shift=asof_shift, exclude_entity=exclude_entity, flow=flow)
    rows = [r for r in s["rows"] if r["tb"] is not None and r["fwd30"] is not None]
    x = np.array([r["tb"] for r in rows], dtype=float)
    y = np.array([r["fwd30"] for r in rows], dtype=float)
    res = {
        "label": label, "mode": mode, "denom": denom, "asof_shift": asof_shift,
        "exclude_entity": exclude_entity, "flow": flow,
        "n_weeks": len(rows),
        "first_signal": rows[0]["d"] if rows else None,
        "last_signal": rows[-1]["d"] if rows else None,
        "weeks_with_zero_tb": int(sum(1 for r in rows if r["tb"] == 0)),
        "tb_mean": float(x.mean()) if len(x) else None,
        "tb_sd": float(x.std(ddof=1)) if len(x) > 1 else None,
        "fwd30_mean_pct": float(100 * y.mean()) if len(y) else None,
    }
    if len(rows) < 10:
        res["note"] = "样本太小"
        return res
    res["spearman"] = spearman(x, y)
    if do_perm:
        res["perm"] = perm_test(x, y, block=8, n=1000, seed=738)
    # 残差化:TB 对过去 30 天收益回归
    p30 = np.array([r["past30"] if r["past30"] is not None else np.nan for r in rows], dtype=float)
    ok = np.isfinite(p30)
    if ok.sum() >= 10:
        e = ols_resid(x[ok], p30[ok])
        res["resid"] = {"n": int(ok.sum()), "rho_vs_past30": spearman(x[ok], p30[ok]),
                        "spearman_resid_vs_fwd30": spearman(e, y[ok])}
        if do_perm:
            res["resid"]["perm"] = perm_test(e, y[ok], block=8, n=1000, seed=738)
    # 分段
    segs = {}
    for name, lo, hi in (("2020-08→2023-12", "2020-08-01", "2023-12-31"),
                         ("2024-01→", "2024-01-01", "9999-12-31")):
        m = np.array([(lo <= r["d"] <= hi) for r in rows])
        if m.sum() >= 8:
            segs[name] = {"n": int(m.sum()), "rho": spearman(x[m], y[m])}
            if do_perm and seg_perm:
                segs[name]["perm"] = perm_test(x[m], y[m], block=8, n=1000, seed=738)
        else:
            segs[name] = {"n": int(m.sum()), "rho": None, "note": "n<8"}
    res["segments"] = segs
    # 断言
    res["assertions"] = run_assertions(s, decisions, mkt, mode)
    return res


def main() -> None:
    dec_btc = load_decisions("bitcoin")
    dec_eth = load_decisions("ethereum")
    mkt_btc = load_market("BTC")
    mkt_eth = load_market("ETH")
    out: dict = {"generated_at_utc": date.today().isoformat(), "prereg": "S-738"}

    out["health_btc"] = health(dec_btc, mkt_btc, symbol="BTC")
    out["health_eth"] = health(dec_eth, mkt_eth, symbol="ETH")

    # 主口径:预注册原样
    main_res = analyze(dec_btc, mkt_btc, label="主口径(预注册原样)", sample_start="2020-08-03",
                        seg_perm=True)
    out["main"] = main_res
    # (c) 分段已在 main 内;但主口径样本的起止要看实际
    # (d) 去掉 Strategy
    out["ex_strategy"] = analyze(dec_btc, mkt_btc, label="去掉 Strategy(MSTR)",
                                 sample_start="2020-08-03", exclude_entity="strategy", seg_perm=True)
    # 敏感度 1:统一 +7 天
    out["sens_flat7"] = analyze(dec_btc, mkt_btc, label="敏感度:统一 +7 天可得日",
                                sample_start="2020-08-03", mode="flat7")
    # 敏感度 2:除以市值
    out["sens_mcap"] = analyze(dec_btc, mkt_btc, label="敏感度:除以 BTC 市值",
                               sample_start="2020-08-03", denom="mcap")
    # 敏感度 3:样本起点提前到数据第一天(2020-08 是预注册的分段边界,不是数据边界)
    out["sens_full_range"] = analyze(dec_btc, mkt_btc, label="敏感度:样本从 2018-06 起(数据边界)",
                                     sample_start="2018-06-04")
    # 稳健性:判完再挪一天(信号信息整体晚一天)
    out["sens_shift1"] = analyze(dec_btc, mkt_btc, label="稳健性:信息整体挪一天",
                                 sample_start="2020-08-03", asof_shift=1)
    # 副:只算卖出
    out["sub_sell_only"] = analyze(dec_btc, mkt_btc, label="副:卖出单独", sample_start="2020-08-03",
                                   flow="sell")

    # 副:反身性(过去 30 天收益 → 之后 4 周 TB)
    s = build_series(dec_btc, mkt_btc, sample_start="2020-08-03", sample_end=None)
    rows = [r for r in s["rows"] if r["past30"] is not None]
    xs, ys, ds = [], [], []
    for r in rows:
        d = date.fromisoformat(r["d"])
        t = fwd_tb(dec_btc, d)
        xs.append(r["past30"])
        ys.append(t)
        ds.append(r["d"])
    refl = {"n": len(xs)}
    if len(xs) >= 10:
        refl["spearman_past30_vs_next4w_tb"] = spearman(xs, ys)
        refl["perm"] = perm_test(np.array(xs), np.array(ys), block=8, n=1000, seed=738)
    out["sub_reflexivity"] = refl

    # 副:ETH 国库(2024 起)
    out["sub_eth"] = analyze(dec_eth, mkt_eth, label="副:ETH 国库(2024 起)", sample_start="2024-01-01")

    # 情景表键的当前值(给情景文件用)
    try:
        st = fetch("state_daily", {"select": "d,value", "feature": "eq.breadth_above_ma50",
                                   "order": "d.desc", "limit": 2})
        out["scenario_keys"] = {"breadth": st}
    except Exception as e:  # noqa: BLE001
        out["scenario_keys"] = {"breadth_error": str(e)}
    try:
        mc = fetch("macro_daily", {"select": "d,value", "series": "eq.fed_balance_sheet",
                                   "order": "d.desc", "limit": 12})
        out["scenario_keys"]["fed"] = mc
    except Exception as e:  # noqa: BLE001
        out["scenario_keys"]["fed_error"] = str(e)
    try:
        oc = fetch("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC",
                                   "source": "eq.binance_hist", "order": "trade_date.desc", "limit": 2})
        out["scenario_keys"]["btc_close"] = oc
    except Exception as e:  # noqa: BLE001
        out["scenario_keys"]["btc_error"] = str(e)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: out[k] for k in ("main", "ex_strategy", "sens_flat7", "sens_mcap",
                                          "sens_shift1", "sub_sell_only", "sub_reflexivity",
                                          "sub_eth")}, ensure_ascii=False, indent=2, default=str)[:6000])
    print("\nhealth:", json.dumps(out["health_btc"], ensure_ascii=False, indent=2, default=str)[:3000])
    print("\nwrote", OUT_JSON)


def probe() -> None:
    """数据体检:表结构 / 规模 / 情景表键。"""
    for table in ("treasury_decisions", "treasury_entities", "asset_mcap_daily"):
        try:
            rows = fetch(table, {"limit": 2})
        except Exception as e:  # noqa: BLE001
            print(f"=== {table} === ERROR {e}")
            continue
        print(f"\n=== {table} ===")
        if not rows:
            print("  (空)")
            continue
        print("  columns:", ", ".join(sorted(rows[0].keys())))
        print("  total rows:", count(table, {"select": "*"}))
    print("\n-- subsets --")
    print("  treasury_decisions coin_id=bitcoin:", count("treasury_decisions", {"coin_id": "eq.bitcoin"}))
    print("  treasury_decisions coin_id=ethereum:", count("treasury_decisions", {"coin_id": "eq.ethereum"}))
    print("  asset_mcap_daily symbol=BTC:", count("asset_mcap_daily", {"symbol": "eq.BTC"}))
    print("  asset_mcap_daily symbol=ETH:", count("asset_mcap_daily", {"symbol": "eq.ETH"}))
    print("\n-- scenario keys --")
    for tbl, sel, flt in (("state_daily", "feature", "breadth_above_ma50"),
                          ("macro_daily", "series", "fed_balance_sheet")):
        try:
            rows = fetch(tbl, {"select": sel, flt: f"eq.{flt}", "order": "d.desc", "limit": 3})
            print(f"  {tbl}.{flt}:", json.dumps(rows, ensure_ascii=False)[:300])
        except Exception as e:  # noqa: BLE001
            print(f"  {tbl} ERROR {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    if a.probe:
        probe()
    else:
        main()
