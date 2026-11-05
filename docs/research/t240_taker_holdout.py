"""T-240 (S-723) —— T-235「主动买盘占比」那一格的**留出样本**检验。

纪律(卡上 acceptance.check 原文即下面的 PREREG):
  * 预注册(S-723 原文)先写进报告开头,再算;只算一次,只测「主动买盘占比」这一个量。
  * 票集 = T-235 的 767 张(不改);R 用票里的数(不重算)。
  * 新口径 = tbqv / qv(perp_bv_daily,开票日 d;d−1 口径另报)。
  * 零分布/分位只用 src/data/evaluation/apparatus.py。
  * 不改代码、不做 DDL、不入库;探针改同一个文件再跑;长脚本 nohup 后台。

用法:
  python3 docs/research/t240_taker_holdout.py            # 全流程(写报告 + json)
  python3 docs/research/t240_taker_holdout.py --probe    # 只打诊断(票集/参考集/数据可用性)
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import statistics as st
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    stationary_bootstrap_index,
)

# ───────────────────────────── 0. 预注册(先写进报告,再算) ─────────────────────────────

PREREG = """# T-240 (S-723) —— T-235「主动买盘占比」那一格的留出样本检验

**预注册(2026-11-05,先写下来再算;只测这一个量,只算一次,不扫阈值)**

> 只读。预注册(S-723 原文)抄进报告开头再算,**只算一次**:
> ① 主动买盘占比 = tbqv / qv(perp_bv_daily,开票日 d;d−1 口径另报),
>    与 T-235 用的 s695 口径在 2023 后重叠段对一遍(相关 / 分档一致率),写明是否同一个量;
> ② 票集 = T-235 的 767 张(不改),H1 = 开票日 2020-03-01 → 2022-12-31 的票,
>    扩张窗口五分位(只用 ≤ d 已出场的票)、顶档减底档 ΔR、随机打乱标签 1,000 次
>    (种子 240,只用 apparatus.py)单侧 / 双侧分位,缺失率;
>    H2 用新口径重算一遍并与 T-235 的 +1.08R 对照(同口径应接近);
> ③ 判(S-723):H1 ΔR ≥ +0.3R 且单侧分位 ≥ 0.95 且与 H2 同号 ⇒ ✅「留出样本确认」;否则 ❌。
> ④ 诚实:H1 的票几乎都是 2020–21 的(2022 长票 0 张);只测这一个量、不扫阈值;
>    多重比较只剩 1 次。纪律:不改代码、不做 DDL、不入库;探针脚本改同一个文件再跑;
>    长脚本 nohup 后台、下一轮收;交付附 docs/research/scenarios/lane-a-T-240.json(≥ 2 条)。

**沿用 T-235 的实现口径(不新造)**:
  * 开票日 d = 票的 `signal_d`(entry_px == signal_d 收盘,进场在 d+1 开盘 ⇒ d 收盘是进场时的全部信息集)。
  * 扩张窗口五分位:参考集 = `exit_d ≤ d` 且该量可得的**已出场**票;参考集 < 20 张 ⇒ 该票不定档。
  * 五分位边界 = 参考集该量的 20/40/60/80 分位;顶档(5)减底档(1) = ΔR。
  * 零分布 = 1000 次标签置换(打乱档位标签再算顶−底),种子 240(apparatus `null_distribution` + `percentile_of`)。
  * 自举区间 = iid 自举 2000 次(apparatus `stationary_bootstrap_index(mean_block=1)`)。
  * 缺失就是缺失:不补 0,单列缺失率。
"""

# ───────────────────────────── 1. 常量 / 数据源 ─────────────────────────────

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
ROOT = "/Volumes/CometCloudAI/cometcloud-local"
TICKETS = f"{ROOT}/research/t159/_tickets_2020-03-01_2026-06-20.json"
T235_RESULTS = HERE / "t235_results.json"

HALVES = [("H1 2020-03→2022-12", "2020-03-01", "2022-12-31"),
          ("H2 2023-01→2026-10", "2023-01-01", "2026-12-31")]
SEED = 240
N_NULL = 1000
MIN_REF = 20
OUT_MD = HERE / "T-240_taker_holdout.md"
OUT_JS = HERE / "t240_results.json"


def pull(table: str, query: str, step: int = 5000) -> list[dict]:
    """按主键排序翻页(必须带 order=,不然边界会漂)。"""
    rows: list[dict] = []
    off = 0
    total = -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off + step - 1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        with urllib.request.urlopen(req, timeout=300) as resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def pull_symbol_dates(table: str, sym: str, dates: list[str], cols: str, chunk: int = 50) -> list[dict]:
    """只取某 symbol 的若干日期(避免把整表拉下来)。日期按主键排、查询带 order=;
    日期多时分块(PostgREST 对 in.(...) 的 URL 长度有限)。"""
    ds = sorted(set(dates))
    rows: list[dict] = []
    for i in range(0, len(ds), chunk):
        part = ds[i:i + chunk]
        q = f"select={cols}&symbol=eq.{sym}&d=in.({','.join(part)})&order=d.asc"
        try:
            rows.extend(pull(table, q, step=2000))
        except urllib.error.HTTPError as e:
            body = getattr(e, "read", lambda: b"")().decode()[:200]
            raise RuntimeError(f"{table} {sym} query failed: {e} {body}") from e
    return rows


def load_tickets() -> tuple[list[dict], dict]:
    """T-235 的票集装载(逐字沿用):t159 本地长票 + r_tickets_paper 已出场票。"""
    tix = json.load(open(TICKETS))
    longs, shorts = tix["long"], tix["short"]
    paper_rows = pull("r_tickets_paper", "select=*&order=signal_d.asc&limit=5000")
    tickets = []
    n_r_none = 0
    for t in longs:
        if t.get("r") is None:
            n_r_none += 1
            continue
        tickets.append({"symbol": t["symbol"], "signal_d": t["signal_d"][:10],
                        "entry_d": (t.get("entry_d") or "")[:10],
                        "exit_d": (t.get("exit_d") or "")[:10] if t.get("exit_d") else None,
                        "r": float(t["r"]), "src": "t159_local"})
    n_paper = 0
    for t in paper_rows:
        if t.get("r") is None:
            continue
        tickets.append({"symbol": t.get("symbol"), "signal_d": (t.get("signal_d") or "")[:10],
                        "entry_d": (t.get("entry_d") or "")[:10],
                        "exit_d": (t.get("exit_d") or "")[:10] if t.get("exit_d") else None,
                        "r": float(t["r"]), "src": "r_tickets_paper"})
        n_paper += 1
    tickets.sort(key=lambda x: (x["signal_d"], x["symbol"]))
    meta = {"n_long_in_file": len(longs), "n_short_in_file_excluded": len(shorts),
            "n_paper_used": n_paper, "n_r_none_dropped": n_r_none,
            "r_tickets_paper_rows": len(paper_rows)}
    return tickets, meta


def half_of(d: str) -> int | None:
    for i, (_, lo, hi) in enumerate(HALVES):
        if lo <= d <= hi:
            return i
    return None


# ───────────────────────────── 2. 分档 + 统计(与 T-235 同构) ─────────────────────────────

def assign_buckets(tickets: list[dict], qvals: dict, min_ref: int = MIN_REF) -> list[int | None]:
    """扩张窗口:参考集 = exit_d ≤ d 且该量可得的已出场票。返回每张票的档位 1..5 / None。"""
    by_exit = sorted([t for t in tickets if t.get("exit_d")], key=lambda t: t["exit_d"])
    buckets: list[int | None] = []
    ref_vals: list[float] = []
    p = 0
    for t in tickets:
        d = t["signal_d"]
        while p < len(by_exit) and by_exit[p]["exit_d"] <= d:
            v = qvals.get(by_exit[p]["symbol"] + "|" + by_exit[p]["signal_d"])
            if v is not None:
                ref_vals.append(v)
            p += 1
        own = qvals.get(t["symbol"] + "|" + t["signal_d"])
        if own is None or len(ref_vals) < min_ref:
            buckets.append(None)
            continue
        edges = np.percentile(np.asarray(ref_vals, dtype=float), [20, 40, 60, 80])
        buckets.append(int(np.searchsorted(edges, own, side="right")) + 1)
    return buckets


def boot_ci(vals: list[float], seed: int = SEED, n_boot: int = 2000) -> list[float] | None:
    n = len(vals)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_index(n, mean_block=1.0, n_boot=n_boot, rng=rng)
    means = np.asarray(vals, dtype=float)[idx].mean(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def analyse(tickets: list[dict], qvals: dict, label: str, min_ref: int = MIN_REF) -> dict:
    """一个量在一个口径下的完整统计(与 T-235 的 analyse 同构)。"""
    buckets = assign_buckets(tickets, qvals, min_ref=min_ref)
    res = {"label": label, "min_ref": min_ref, "buckets": buckets, "halves": {}}
    for hi, (hname, _, _) in enumerate(HALVES):
        sel = [(t, b) for t, b in zip(tickets, buckets) if b is not None and half_of(t["signal_d"]) == hi]
        q_stats = []
        for k in range(1, 6):
            vals = [t["r"] for t, b in sel if b == k]
            q_stats.append({"q": k, "n": len(vals),
                            "mean_r": round(st.mean(vals), 4) if vals else None,
                            "median_r": round(st.median(vals), 4) if vals else None,
                            "hit": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else None,
                            "ci95": [round(x, 4) for x in boot_ci(vals)] if len(vals) >= 2 else None})
        top = [t["r"] for t, b in sel if b == 5]
        bot = [t["r"] for t, b in sel if b == 1]
        obs = (st.mean(top) - st.mean(bot)) if top and bot else None
        pctl = p2 = None
        null_note = ""
        if obs is not None:
            rs = [t["r"] for t, b in sel]
            labs = [b for t, b in sel]

            def fn(rng, rs=rs, labs=labs):
                # 打乱**标签**:把档位重新分配给票,再算顶档−底档。
                perm = rng.permutation(len(labs))
                lp = [labs[i] for i in perm]
                a = [r for r, l in zip(rs, lp) if l == 5]
                b = [r for r, l in zip(rs, lp) if l == 1]
                return st.mean(a) - st.mean(b) if a and b else float("nan")

            try:
                null = null_distribution(fn, n=N_NULL, seed=SEED, actual=obs)
                pctl = percentile_of(obs, null)
                p2 = 2.0 * min(pctl, 1.0 - pctl) if pctl is not None else None
            except NoOpNull as e:
                null_note = f"NoOpNull: {e}"
                p2 = None
        res["halves"][hname] = {"quintiles": q_stats,
                                "delta_r": round(obs, 4) if obs is not None else None,
                                "null_pct": round(pctl, 4) if pctl is not None else None,
                                "null_pct_two_sided": round(p2, 4) if p2 is not None else None,
                                "null_note": null_note, "n_labeled": len(sel)}
    return res


def pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return pearson(rx.tolist(), ry.tolist())


def desc(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {"n": len(s), "min": round(s[0], 6), "p25": round(s[len(s) // 4], 6),
            "median": round(st.median(s), 6), "p75": round(s[3 * len(s) // 4], 6),
            "max": round(s[-1], 6), "mean": round(st.mean(s), 6)}


# ───────────────────────────── 3. 主流程 ─────────────────────────────

def main() -> None:
    with open(OUT_MD, "w") as fh:  # ① 预注册先落盘,再算
        fh.write(PREREG)
        fh.write("\n## 0. 口径与实现决定(开算前写定)\n\n(计算中……)\n")
    print("prereg written ->", OUT_MD, flush=True)

    tickets, meta = load_tickets()
    symbols = sorted({t["symbol"] for t in tickets})
    print("tickets", len(tickets), "symbols", len(symbols), meta, flush=True)

    # 需要哪些 (symbol, date):票的 signal_d 与 signal_d−1(两个口径)
    need: dict[str, set[str]] = defaultdict(set)
    for t in tickets:
        d = t["signal_d"]
        prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        need[t["symbol"]].update({d, prev})
    n_pairs = sum(len(v) for v in need.values())
    print("needed (symbol,date) pairs", n_pairs, flush=True)

    # 新口径:perp_bv_daily 的 tbqv / qv
    perp: dict[tuple[str, str], tuple[float, float]] = {}
    perp_dup = 0
    perp_bad = 0
    for i, sym in enumerate(symbols):
        rows = pull_symbol_dates("perp_bv_daily", sym, sorted(need[sym]), "symbol,d,qv,tbqv")
        for r in rows:
            if r.get("tbqv") is None or r.get("qv") is None:
                continue
            qv = float(r["qv"])
            if qv <= 0:
                perp_bad += 1
                continue
            key = (r["symbol"], r["d"][:10])
            if key in perp:
                perp_dup += 1
            perp[key] = (float(r["tbqv"]), qv)
        if (i + 1) % 40 == 0:
            print("perp pull", i + 1, "/", len(symbols), "rows", len(perp), flush=True)
    print("perp rows", len(perp), "dup", perp_dup, "qv<=0 skipped", perp_bad, flush=True)

    # 旧口径(s695 / T-235 用的):deriv_metrics_daily.taker_ratio_mean /(1+ratio)
    # 多取 d±3 天,只为做 ① 的**滞后诊断**(是不是日期错位),不改任何量、不新增检验。
    need_old: dict[str, set[str]] = defaultdict(set)
    for t in tickets:
        d0 = dt.date.fromisoformat(t["signal_d"])
        for k in range(-3, 4):
            need_old[t["symbol"]].add((d0 + dt.timedelta(days=k)).isoformat())
    old: dict[tuple[str, str], float] = {}
    old_rows = 0
    for i, sym in enumerate(symbols):
        rows = pull_symbol_dates("deriv_metrics_daily", sym, sorted(need_old[sym]), "symbol,d,taker_ratio_mean")
        for r in rows:
            if r.get("taker_ratio_mean") is None:
                continue
            old_rows += 1
            old[(r["symbol"], r["d"][:10])] = float(r["taker_ratio_mean"])
        if (i + 1) % 60 == 0:
            print("deriv pull", i + 1, "/", len(symbols), "rows", len(old), flush=True)
    print("deriv taker rows", old_rows, flush=True)

    # ── 量:d 口径 与 d−1 口径 ──
    q_new_d: dict[str, float] = {}
    q_new_d1: dict[str, float] = {}
    q_old_d: dict[str, float] = {}
    for t in tickets:
        sym, d = t["symbol"], t["signal_d"]
        prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        k = sym + "|" + d
        p = perp.get((sym, d))
        q_new_d[k] = (p[0] / p[1]) if p else None
        p1 = perp.get((sym, prev))
        q_new_d1[k] = (p1[0] / p1[1]) if p1 else None
        tr = old.get((sym, d))
        q_old_d[k] = (tr / (1.0 + tr)) if tr is not None else None

    # ── ① 口径一致性(2023 后重叠段) ──
    overlap = []
    for t in tickets:
        if HALVES[1][1] <= t["signal_d"] <= HALVES[1][2]:
            k = t["symbol"] + "|" + t["signal_d"]
            if q_new_d.get(k) is not None and q_old_d.get(k) is not None:
                overlap.append((k, q_new_d[k], q_old_d[k]))
    xs = [o[1] for o in overlap]
    ys = [o[2] for o in overlap]
    diffs = [abs(a - b) for a, b in zip(xs, ys)]
    # 分档一致率:同一套扩张窗口规则下,新/旧口径各自定档后逐票比较
    b_new = assign_buckets(tickets, q_new_d)
    b_old = assign_buckets(tickets, q_old_d)
    both = [(t, bn, bo) for t, bn, bo in zip(tickets, b_new, b_old)
            if bn is not None and bo is not None and HALVES[1][1] <= t["signal_d"] <= HALVES[1][2]]
    exact = sum(1 for _, bn, bo in both if bn == bo)
    within1 = sum(1 for _, bn, bo in both if abs(bn - bo) <= 1)
    # 滞后诊断:是不是日期错位(new[t] 对 old[t+lag])?只诊断,不改量、不新增检验。
    lag_tab: dict[str, dict] = {}
    for lag in range(-3, 4):
        ax: list[float] = []
        ay: list[float] = []
        for t in tickets:
            if not (HALVES[1][1] <= t["signal_d"] <= HALVES[1][2]):
                continue
            k = t["symbol"] + "|" + t["signal_d"]
            nv = q_new_d.get(k)
            if nv is None:
                continue
            dd = (dt.date.fromisoformat(t["signal_d"]) + dt.timedelta(days=lag)).isoformat()
            tr = old.get((t["symbol"], dd))
            if tr is None:
                continue
            ax.append(nv)
            ay.append(tr / (1.0 + tr))
        lag_tab[str(lag)] = {"n": len(ax), "pearson": pearson(ax, ay)}
    caliber = {"n_overlap": len(overlap), "pearson": pearson(xs, ys), "spearman": spearman(xs, ys),
               "mean_abs_diff": round(st.mean(diffs), 6) if diffs else None,
               "median_abs_diff": round(st.median(diffs), 6) if diffs else None,
               "max_abs_diff": round(max(diffs), 6) if diffs else None,
               "new_desc": desc(xs), "old_desc": desc(ys),
               "n_bucket_both": len(both), "bucket_exact_rate": round(exact / len(both), 4) if both else None,
               "bucket_within1_rate": round(within1 / len(both), 4) if both else None,
               "lag_corr": lag_tab}
    print("caliber", caliber, flush=True)

    # ── ② 新口径的 H1 / H2 ──
    res_d = analyse(tickets, q_new_d, "主动买盘占比 tbqv/qv · d")
    res_d1 = analyse(tickets, q_new_d1, "主动买盘占比 tbqv/qv · d−1")
    h1n, h2n = HALVES[0][0], HALVES[1][0]
    h1, h2 = res_d["halves"][h1n], res_d["halves"][h2n]
    h1m, h2m = res_d1["halves"][h1n], res_d1["halves"][h2n]

    miss = {}
    for hi, (hname, _, _) in enumerate(HALVES):
        sel = [t for t in tickets if half_of(t["signal_d"]) == hi]
        k_new = sum(1 for t in sel if q_new_d.get(t["symbol"] + "|" + t["signal_d"]) is not None)
        k_old = sum(1 for t in sel if q_old_d.get(t["symbol"] + "|" + t["signal_d"]) is not None)
        miss[hname] = {"n_tickets": len(sel), "n_new_available": k_new,
                       "missing_rate_new": round(1 - k_new / len(sel), 4) if sel else None,
                       "n_old_available": k_old,
                       "missing_rate_old": round(1 - k_old / len(sel), 4) if sel else None}

    # T-235 对照(旧口径 H2 的读数)
    t235 = {}
    if T235_RESULTS.exists():
        p235 = json.load(open(T235_RESULTS))
        ts = p235["quantities"].get("taker_share", {})
        t235 = {"n_tickets": p235["universe"]["n_tickets"],
                "old_H2_delta_r": ts.get("d", {}).get("halves", {}).get(h2n, {}).get("delta_r"),
                "old_H2_null_pct": ts.get("d", {}).get("halves", {}).get(h2n, {}).get("null_pct"),
                "old_H2_null_pct_two_sided": ts.get("d", {}).get("halves", {}).get(h2n, {}).get("null_pct_two_sided"),
                "old_H1_delta_r": ts.get("d", {}).get("halves", {}).get(h1n, {}).get("delta_r"),
                "old_H1_n_labeled": ts.get("d", {}).get("halves", {}).get(h1n, {}).get("n_labeled"),
                "old_missing_rate": ts.get("missing_rate")}

    # ── ③ 判(S-723) ──
    c_mag = h1["delta_r"] is not None and h1["delta_r"] >= 0.3
    c_sig = h1["null_pct"] is not None and h1["null_pct"] >= 0.95
    c_sign = (h1["delta_r"] is not None and h2["delta_r"] is not None
              and (h1["delta_r"] > 0) == (h2["delta_r"] > 0))
    verdict = {"H1_delta_r_ge_0.3": c_mag, "H1_null_pct_ge_0.95": c_sig,
               "same_sign_as_H2": c_sign,
               "confirm": bool(c_mag and c_sig and c_sign),
               # 补充标记(不改卡上判据):全局纪律「信号日当天的派生量,挪一天判一次;
               # 只在当天成立的不算」。d−1 口径翻号 ⇒ d_only。
               "d_only_flag": (h1m["delta_r"] is not None and h1["delta_r"] is not None
                               and (h1m["delta_r"] > 0) != (h1["delta_r"] > 0))}

    payload = {
        "card": "T-240", "prereg": "S-723",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "universe": {**meta, "n_tickets": len(tickets), "n_symbols": len(symbols)},
        "tickets_by_year": {y: sum(1 for t in tickets if t["signal_d"][:4] == y)
                            for y in sorted({t["signal_d"][:4] for t in tickets})},
        "sources": {"perp_bv_daily_rows": len(perp), "perp_dup": perp_dup,
                    "perp_qv_le_0_skipped": perp_bad,
                    "deriv_taker_rows": old_rows, "n_symbols": len(symbols)},
        "caliber_check": caliber,
        "missing": miss,
        "measure": {"name": "主动买盘占比 = tbqv/qv (perp_bv_daily)", "d": res_d, "d_minus_1": res_d1},
        "t235_reference": t235,
        "verdict": verdict,
    }
    with open(OUT_JS, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    write_report(payload, OUT_MD)
    print("verdict", verdict, flush=True)
    print("report ->", OUT_MD, flush=True)


# ───────────────────────────── 4. 报告 ─────────────────────────────

def write_report(p: dict, out_md: Path) -> None:
    u, s = p["universe"], p["sources"]
    cal, mis, t235 = p["caliber_check"], p["missing"], p["t235_reference"]
    h1n, h2n = HALVES[0][0], HALVES[1][0]
    md, md1 = p["measure"]["d"], p["measure"]["d_minus_1"]
    h1, h2 = md["halves"][h1n], md["halves"][h2n]
    h1m, h2m = md1["halves"][h1n], md1["halves"][h2n]
    v = p["verdict"]
    L: list[str] = []
    L.append(PREREG)
    L.append("""
## 0. 口径与实现决定(开算前写定)

| 项 | 决定 | 依据 |
|---|---|---|
| 开票日 d | = 票的 `signal_d` | T-235 已核实:entry_px == signal_d 收盘,进场在 d+1 开盘 ⇒ d 收盘是进场时的全部信息 |
| 票集 | T-235 的 767 张,一字不改(R 用票里的数) | 卡 ② |
| 新口径 | `tbqv / qv`(perp_bv_daily,开票日 d);d−1 口径 = 前一**自然日**同一口径 | 卡 ① |
| 旧口径(对照) | `taker_ratio_mean /(1 + taker_ratio_mean)`(deriv_metrics_daily,s695 来源) | T-235 用的就是它 |
| 扩张窗口 | 参考集 = `exit_d ≤ d` 且该量可得的已出场票;< 20 张 ⇒ 该票不定档 | T-235 同款(min_ref=20) |
| 五分位边界 | 参考集该量的 20/40/60/80 分位 | 常规 |
| ΔR | 顶档(5)平均 R − 底档(1)平均 R | T-235 同款 |
| 零分布 | 1000 次**标签置换**(打乱档位标签再算顶−底),种子 240 | 卡 ② + apparatus |
| 分位 | 单侧 = `percentile_of(obs, null)`;双侧 = 2×min(单侧, 1−单侧) | T-235 同款 |
| 自举区间 | iid 自举 2000 次(apparatus `stationary_bootstrap_index(mean_block=1)`) | T-235 同款 |
| 缺失 | 不补 0,单列缺失率 | 卡 ② |

**只测这一个量、多重比较只剩 1 次**:主动买盘占比(新口径)。H2 的对照读数来自 T-235 已落盘的
`t235_results.json`(旧口径),不重算、不扫阈值。
""")

    L.append(f"""
## 1. 票集与数据源(装载记录)

| 项 | 值 |
|---|---|
| 票数 | {u['n_tickets']}(t159 本地长票 {u['n_long_in_file']} 张,去掉 r 为空的 {u['n_r_none_dropped']} 张;空头票 {u['n_short_in_file_excluded']} 张不计) |
| r_tickets_paper 已出场票 | {u['n_paper_used']} 张(表里共 {u['r_tickets_paper_rows']} 行) |
| 票按开票年 | {json.dumps(p['tickets_by_year'], ensure_ascii=False)} |
| 涉及 symbol | {u['n_symbols']} 个 |
| perp_bv_daily 取回行 | {s['perp_bv_daily_rows']} 行(重复 {s['perp_dup']},qv ≤ 0 跳过 {s['perp_qv_le_0_skipped']}) |
| deriv_metrics_daily taker 取回行 | {s['deriv_taker_rows']} 行 |

**H1 票的构成**:H1 = 开票日 2020-03-01 → 2022-12-31,共 {mis[h1n]['n_tickets']} 张,
开票日从 2020-04-29 到 2021-11-30(2022 年长票 0 张,与卡上诚实段一致)。
""")

    L.append(f"""
## 2. ① 口径一致性:新口径(tbqv/qv)vs 旧口径(s695 的 taker_ratio_mean/(1+ratio))

对照段 = 2023-01-01 → 2026-12-31(H2)里两口径都有值的票,共 **{cal['n_overlap']}** 张。

| 指标 | 值 |
|---|---|
| Pearson 相关 | {cal['pearson']} |
| Spearman 相关 | {cal['spearman']} |
| 平均绝对差 | {cal['mean_abs_diff']} |
| 中位绝对差 | {cal['median_abs_diff']} |
| 最大绝对差 | {cal['max_abs_diff']} |
| 新口径取值范围 | min {cal['new_desc'].get('min')} / median {cal['new_desc'].get('median')} / max {cal['new_desc'].get('max')} |
| 旧口径取值范围 | min {cal['old_desc'].get('min')} / median {cal['old_desc'].get('median')} / max {cal['old_desc'].get('max')} |
| 分档逐票一致率(两口径都有档) | {cal['bucket_exact_rate']}(n={cal['n_bucket_both']}) |
| 分档 ±1 档一致率 | {cal['bucket_within1_rate']}(n={cal['n_bucket_both']}) |

**滞后诊断**(是不是日期错位?new[d] 对 old[d+lag],lag 0 = 同日):

| lag | -3 | -2 | -1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|---|
| Pearson | {_lag_row(cal)} |

**结论(是否同一个量)**:{_same_quantity(cal, h2['delta_r'])}
""")

    L.append(f"""
## 3. ② 新口径下的 H1 / H2

### 3.1 H1 = {h1n}(**留出样本**)

- 票数 {mis[h1n]['n_tickets']},新口径可得 {mis[h1n]['n_new_available']} 张 ⇒ **缺失率 {mis[h1n]['missing_rate_new']}**;
  旧口径可得 {mis[h1n]['n_old_available']} 张 ⇒ 旧口径缺失率 {mis[h1n]['missing_rate_old']}(这就是 T-235 里 H1 测不了的直接原因)。
- 定档(扩张窗口,min_ref={md['min_ref']})后有标签的票:**{h1['n_labeled']}** 张。

| 档 | n | 平均 R | 中位 R | 命中率 | 均值 95% 自举区间 |
|---|---|---|---|---|---|
""")
    for q in h1["quintiles"]:
        ci = q["ci95"]
        L.append(f"| {q['q']} | {q['n']} | {q['mean_r']} | {q['median_r']} | {q['hit']} | {ci if ci else '—'} |")
    L.append(f"""
- **ΔR(顶档 − 底档)= {h1['delta_r']}**
- **随机打乱标签 1,000 次(种子 {SEED})单侧分位 = {h1['null_pct']}**,双侧分位 = {h1['null_pct_two_sided']}
- null_note: {h1['null_note'] or '—'}

### 3.2 H2 = {h2n}(**发现样本**,新口径重算)

| 档 | n | 平均 R | 中位 R | 命中率 | 均值 95% 自举区间 |
|---|---|---|---|---|---|
""")
    for q in h2["quintiles"]:
        ci = q["ci95"]
        L.append(f"| {q['q']} | {q['n']} | {q['mean_r']} | {q['median_r']} | {q['hit']} | {ci if ci else '—'} |")
    L.append(f"""
- **ΔR = {h2['delta_r']}**,单侧分位 = {h2['null_pct']},双侧 = {h2['null_pct_two_sided']},有标签 {h2['n_labeled']} 张。
- 缺失率 {mis[h2n]['missing_rate_new']}(旧口径 {mis[h2n]['missing_rate_old']})。

### 3.3 与 T-235 的 H2 对照(旧口径)

| 读数 | T-235(旧口径) | T-240(新口径) |
|---|---|---|
| H2 ΔR | {t235.get('old_H2_delta_r')} | {h2['delta_r']} |
| H2 单侧分位 | {t235.get('old_H2_null_pct')} | {h2['null_pct']} |
| H2 双侧分位 | {t235.get('old_H2_null_pct_two_sided')} | {h2['null_pct_two_sided']} |
| H1 ΔR | {t235.get('old_H1_delta_r')}(n_labeled={t235.get('old_H1_n_labeled')}) | {h1['delta_r']}(n_labeled={h1['n_labeled']}) |

### 3.4 d−1 口径(另报)

| 半 | ΔR(d 口径) | ΔR(d−1 口径) | 单侧(d) | 单侧(d−1) |
|---|---|---|---|---|
| {h1n} | {h1['delta_r']} | {h1m['delta_r']} | {h1['null_pct']} | {h1m['null_pct']} |
| {h2n} | {h2['delta_r']} | {h2m['delta_r']} | {h2['null_pct']} | {h2m['null_pct']} |

**d−1 口径翻号 ⇒ 标记 `d_only`**({ '✅ 是' if v.get('d_only_flag') else '❌ 否' })。
按全局纪律(「信号日当天的派生量,判完再挪一天判一次 —— 只在当天成立的不算」),
即使分位过了,一个只在 d 当天成立、在 d−1 就翻号的量也不该当候选。这是**补充标记,不改卡上判据**。
""")

    L.append(f"""
## 4. ③ 判(S-723 原判据)

> H1 ΔR ≥ +0.3R 且单侧分位 ≥ 0.95 且与 H2 同号 ⇒ ✅「留出样本确认」;否则 ❌。

| 条件 | 读数 | 是否满足 |
|---|---|---|
| H1 ΔR ≥ +0.3R | {h1['delta_r']} | {'✅' if v['H1_delta_r_ge_0.3'] else '❌'} |
| H1 单侧分位 ≥ 0.95 | {h1['null_pct']} | {'✅' if v['H1_null_pct_ge_0.95'] else '❌'} |
| 与 H2 同号 | H1={h1['delta_r']}, H2={h2['delta_r']} | {'✅' if v['same_sign_as_H2'] else '❌'} |

### 判定:{('✅ 留出样本确认(H1 独立复现了 H2 的方向与量级)' if v['confirm'] else '❌ 未确认(留出样本没有复现)')}

理由:{'三条全过。' if v['confirm'] else '至少一条不过 —— 见上表。'}
""")

    L.append(f"""
## 5. ④ 诚实段

1. **多重比较只剩 1 次**:本卡只测「主动买盘占比」一个量,没有扫阈值、没有扫窗口、没有试别的量。
2. **H1 的票几乎都是 2020–21 的**:{mis[h1n]['n_tickets']} 张里 2022 年开票 0 张,开票日跨度
   2020-04-29 → 2021-11-30。留出样本本身是**牛市尾巴 + 熊市初段**的票,不代表 2022 全年。
3. **H1 不是「当年才知道」**:H1 的票在 T-235 跑的时候(2026-11-05)就已经存在并已有 R;
   留出指的是**发现样本/检验样本的划分**,不是时间上的样本外。这一点必须写清。
4. **分位是零分布分位,不是 p 值**;单侧 0.95 的门槛在 T-235 里是同一条。
5. **d−1 口径另报**(全局纪律:信号日当天的派生量判完再挪一天判一次)。见 §3.4。
6. **数据源的诚实**:tbqv 缺失就是缺失(不补 0、不前向填充);缺失率逐半列出(§3.1、§3.2)。
7. **本次只读**:没有改代码、没有 DDL、没有入库。
""")
    out_md.write_text("\n".join(L), encoding="utf-8")


def _lag_row(cal: dict) -> str:
    lc = cal.get("lag_corr") or {}
    cells = []
    for k in ("-3", "-2", "-1", "0", "1", "2", "3"):
        v = lc.get(k) or {}
        p = v.get("pearson")
        cells.append(f"{round(p, 4) if p is not None else '—'}(n={v.get('n', 0)})")
    return " | ".join(cells)


def _same_quantity(cal: dict, h2_delta) -> str:
    p = cal.get("pearson")
    if p is None:
        return "重叠段样本不足,无法判定。"
    med = cal.get("median_abs_diff")
    exact = cal.get("bucket_exact_rate")
    lc = cal.get("lag_corr") or {}
    best_lag = None
    best_p = None
    for k, v in lc.items():
        pv = v.get("pearson")
        if pv is not None and (best_p is None or pv > best_p):
            best_p, best_lag = pv, k
    lag_note = (f"滞后诊断里最高的相关出现在 lag={best_lag}(Pearson {round(best_p, 4)});"
                if best_p is not None else "滞后诊断无有效读数;")
    if p >= 0.9 and med is not None and med <= 0.02:
        return (f"**是同一个量**(近乎同一):Pearson {p:.4f}、中位绝对差 {med:.4f}、"
                f"分档逐票一致率 {exact}。tbqv/qv 与 taker_ratio_mean/(1+ratio) 是同一个「主动买占比」的两种写法"
                f"(前者是成交额口径,后者是买卖量比口径),可以互相替代。")
    if p >= 0.5:
        return (f"**强相关但不是同一个量**:Pearson {p:.4f}、中位绝对差 {med:.4f}、分档逐票一致率 {exact}。"
                f"两者都叫「主动买占比」但来源/聚合不同(成交额口径 vs 买卖量比口径),"
                f"所以 H2 的新旧读数只能当近似对照,不能当同一读数复算。{lag_note}")
    return (f"**不是同一个量**:Pearson {p:.4f}(同日)、中位绝对差 {med:.4f}、分档逐票一致率 {exact}。"
            f"{lag_note}⇒ 相关低**不是**日期错位造成的。"
            f"两者虽然都叫「主动买占比」,但聚合方式不同(perp_bv_daily 是 K 线成交额口径的当日汇总;"
            f"deriv_metrics_daily 的 `taker_ratio_mean` 是 binance_vision_metrics 的 5 分钟买卖量比均值),"
            f"取值水平也不同(新口径中位 {cal['new_desc'].get('median')} vs 旧口径中位 {cal['old_desc'].get('median')})。"
            f"⇒ **新口径必须当成一个「新量」看待,T-235 的 +1.08R 不能直接搬过来;"
            f"H2 的 {h2_delta} 是新量的读数,不是旧量的复算。**")


def probe() -> None:
    """诊断:H1 票的新口径数据可得性 + 扩张窗口参考集规模(不下结论,只看可得性)。"""
    tickets, meta = load_tickets()
    h1 = [t for t in tickets if HALVES[0][1] <= t["signal_d"] <= HALVES[0][2]]
    syms = sorted({t["symbol"] for t in h1})
    need: dict[str, set[str]] = defaultdict(set)
    for t in h1:
        d = t["signal_d"]
        need[t["symbol"]].update({d, (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()})
    avail_d = avail_d1 = 0
    vals: list[float] = []
    for sym in syms:
        rows = pull_symbol_dates("perp_bv_daily", sym, sorted(need[sym]), "symbol,d,qv,tbqv")
        mp = {}
        for r in rows:
            if r.get("tbqv") is None or not r.get("qv"):
                continue
            mp[r["d"][:10]] = float(r["tbqv"]) / float(r["qv"])
        for t in h1:
            if t["symbol"] != sym:
                continue
            d = t["signal_d"]
            prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            if d in mp:
                avail_d += 1
                vals.append(mp[d])
            if prev in mp:
                avail_d1 += 1
    print("H1 tickets", len(h1), "symbols", len(syms))
    print("H1 new measure available at d:", avail_d, " at d-1:", avail_d1)
    print("value range", min(vals) if vals else None, max(vals) if vals else None,
          "median", st.median(vals) if vals else None)
    old_rows = 0
    for sym in syms:
        rows = pull_symbol_dates("deriv_metrics_daily", sym, sorted(need[sym]), "symbol,d,taker_ratio_mean")
        old_rows += sum(1 for r in rows if r.get("taker_ratio_mean") is not None)
    print("H1 old (s695) rows available:", old_rows)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        main()
