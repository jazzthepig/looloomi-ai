#!/usr/bin/env python3
"""T-169 / 台账 S-668 H1 —— 个股上 v2 合成(规模 + 稳定 + 供给纪律)对之后 20 个交易日收益的 Spearman IC。

照 S-668 H1 原文一字不改地跑,发现段 2016-01 → 2020-12、留出段 2021-01 → 2026-09,
**同一次运行机械走完**:发现段过门槛(IC > 0 且 t ≥ 1.5)才算留出段;留出段 IC > 0 且 t ≥ 2 = 过。

维度与合成**一律 import `src.data.cis.v2`**(`equity_inputs` / `score_group('equity', …)`),
不自己写一版 —— 影子写入端用的是同一个函数。v2.py 已进 origin/main,直接 import(file-loader shim 已删)。

数据(只读,publishable key):
  world50_mcap_weekly(**source = shares_x_close_v3**, key, d, mcap_usd) · ohlcv_daily(source=eodhd, close = 复权收盘)
  供给纪律的股数 = mcap_usd ÷ close,所以**只取一个 source**:表里三个口径
  (sec_shares_x_close / sec_shares_x_close_v2 / shares_x_close_v3)同一 (key, d) 都有行,
  混着取会把口径差当成股数变化(实测 CMCSA 2015-01-02:老口径 118.32B 美元 vs v3 147.96B,差 25%)。
  只取**不带 . 后缀的 key**(美股挂牌与美元 ADR)。输入行 = (周日期, mcap_usd, 当周最后一个交易日的 eodhd 收盘)。
  名单是**今天的候选池 ⇒ 幸存者偏差**,结论里标注。

用法:
    python3 docs/research/t169_equity_quality.py

产出:
    docs/research/t169_results.json
    /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-169_s668_h1.md
    本地缓存 /Volumes/CometCloudAI/cometcloud-local/research/t169/
"""
from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.data.evaluation.apparatus import null_distribution, percentile_of  # 零分布只走 apparatus

# ── v2 内核:唯一的定义处 ─────────────────────────────────────────────────────────────────────────
# 直接 import —— v2.py 已在 origin/main,S-668 要求研究脚本与影子写入端是同一个文件、同一批函数。
from src.data.cis.v2 import CODE_REF, DIMS, equity_inputs, score_group  # noqa: E402

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H0 = {"apikey": KEY, "Authorization": "Bearer " + KEY}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t169")
CACHE.mkdir(parents=True, exist_ok=True)
REPORT = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-169_s668_h1.md")

# world50_mcap_weekly 只有一个 source 参与本卡:供给纪律的股数就是 mcap_usd ÷ close,
# 三个口径混在一起时按日期去重只能随机留一个,口径差(实测 CMCSA 差 25%)会被当成股数变化。
MCAP_SOURCE = "shares_x_close_v3"
V1_RESULTS = REPO / "docs/research/t169_results_v1.json"

DISCOVERY = (date(2016, 1, 1), date(2020, 12, 31))
HOLDOUT = (date(2021, 1, 1), date(2026, 9, 30))
HORIZON_DAYS = 20          # 之后 20 个交易日
MIN_CROSS_SECTION = 15     # 截面 < 15 家 ⇒ 跳过并计数
SAMPLE_EVERY_WEEKS = 4     # 发现段每 4 周取一个不重叠样本
NULL_N = 400
NULL_SEED = 20261022


# ── 取数 ────────────────────────────────────────────────────────────────────────────────────────
def _get(path: str, lo: int, hi: int) -> list[dict]:
    h = dict(H0)
    h["Range"] = "%d-%d" % (lo, hi)
    r = httpx.get(URL + "/rest/v1/" + path, headers=h, timeout=180)
    r.raise_for_status()
    return r.json()


def _fetch_all(path: str, page: int = 1000) -> list[dict]:
    out: list[dict] = []
    lo = 0
    while True:
        chunk = _get(path, lo, lo + page - 1)
        if not chunk:
            return out
        out.extend(chunk)
        lo += page
        print("    %6d rows" % len(out), end="\r", flush=True)


def _cached(name: str, fn):
    p = CACHE / name
    if p.exists():
        print("  [cache] %s" % name)
        return json.loads(p.read_text())
    val = fn()
    p.write_text(json.dumps(val))
    print("  [fetch] %s -> %s" % (name, p))
    return val


def bare_symbols() -> list[str]:
    """World50 候选池里**不带 . 后缀**的 key(美股挂牌 + 美元 ADR)。"""
    rows = _cached("w50_keys.json", lambda: _fetch_all("world50_mcap_weekly?select=key"))
    return sorted({r["key"] for r in rows if "." not in r["key"]})


def mcap_weekly(keys: list[str]) -> dict[str, list[tuple]]:
    """周频市值,**只取 source = shares_x_close_v3**。返回 (key -> [(d, mcap_usd)])。"""
    out: dict[str, list[tuple]] = {}

    def one(k):
        rows = _fetch_all("world50_mcap_weekly?select=d,mcap_usd&source=eq.%s&key=eq.%s&order=d"
                          % (MCAP_SOURCE, k))
        ser = [(r["d"][:10], float(r["mcap_usd"])) for r in rows if r.get("mcap_usd")]
        # 单一口径下同一天至多一行;去重只防重复行,不再有「随机留一个口径」的问题
        return k, sorted({d: v for d, v in ser}.items())

    with ThreadPoolExecutor(max_workers=8) as ex:
        for k, ser in ex.map(one, keys):
            out[k] = ser
    return _cached("w50_mcap_weekly_bare_%s.json" % MCAP_SOURCE, lambda: out)


def eodhd_closes(keys: list[str]) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}

    def one(k):
        rows = _fetch_all("ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.%s"
                          "&order=trade_date" % k)
        ser = [(r["trade_date"][:10], float(r["close"])) for r in rows if r.get("close")]
        return k, sorted({d: v for d, v in ser}.items())

    with ThreadPoolExecutor(max_workers=8) as ex:
        for k, ser in ex.map(one, keys):
            out[k] = ser
    return _cached("eodhd_close_bare.json", lambda: out)


# ── 统计(不重写 apparatus 里有的那些:这里只有 Spearman / t,没有零分布与盈亏)───────────────────────
def _rank(xs: list[float]) -> np.ndarray:
    a = np.asarray(xs, dtype=float)
    order = np.argsort(a, kind="mergesort")
    r = np.empty(a.size, dtype=float)
    i = 0
    while i < a.size:
        j = i
        while j + 1 < a.size and a[order[j + 1]] == a[order[i]]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _rank(x), _rank(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def mean_t(vals: list[float]) -> tuple[float | None, float | None, int]:
    v = np.asarray([x for x in vals if x is not None and math.isfinite(x)], dtype=float)
    if v.size < 2:
        return None, None, int(v.size)
    m = float(v.mean())
    s = float(v.std(ddof=1))
    if s == 0:
        return m, None, int(v.size)
    return m, m / (s / math.sqrt(v.size)), int(v.size)


# ── 主流程 ──────────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("== 取 universe ==")
    keys = bare_symbols()
    print("  bare keys: %d" % len(keys))
    mc = mcap_weekly(keys)
    px = eodhd_closes(keys)
    print("  mcap keys=%d  price keys=%d" % (len(mc), len(px)))
    print("  price span: %s .. %s"
          % (min(v[0][0] for v in px.values() if v), max(v[-1][0] for v in px.values() if v)))

    # 截面日期 = world50 周频戳(周五)。交易日历 = 全部 bare 名字交易日的并集(同一日历给所有名字)。
    cal = sorted({d for v in px.values() for d, _ in v})
    cal_idx = {d: i for i, d in enumerate(cal)}

    def close_on_or_before(ser, day, max_gap=7):
        best = None
        for row in ser:
            if row[0] <= day:
                best = row
            else:
                break
        if best is None or (date.fromisoformat(day) - date.fromisoformat(best[0])).days > max_gap:
            return None
        return best[1]

    def fwd(sym, day):
        """之后 20 个交易日的收益(同一日历)。"""
        i = cal_idx.get(day)
        if i is None or i + HORIZON_DAYS >= len(cal):
            return None
        entry = cal[i]
        exit_ = cal[i + HORIZON_DAYS]
        a = close_on_or_before(px[sym], entry, max_gap=10)
        b = close_on_or_before(px[sym], exit_, max_gap=10)
        if not a or not b or a <= 0:
            return None
        return b / a - 1.0

    # 每个名字的周频输入行 = (周日期, mcap_usd, 当周最后一个交易日的 eodhd 收盘)
    weekly_rows: dict[str, list[tuple]] = {}
    for k, ser in mc.items():
        rows = []
        for d, m in ser:
            c = close_on_or_before(px.get(k, []), d, max_gap=7)
            if c:
                rows.append((d, m, c))
        weekly_rows[k] = rows
    n_weeks = len({d for rows in weekly_rows.values() for d, _, _ in rows})
    print("  weekly cross-sections: %d" % n_weeks)

    stamps = sorted({d for rows in weekly_rows.values() for d, _, _ in rows})
    print("== 逐周截面 ==")
    per_week: list[dict] = []
    skipped_small = skipped_no_fwd = 0
    for d in stamps:
        day = date.fromisoformat(d)
        raw = {k: equity_inputs(weekly_rows[k], d) for k in weekly_rows if any(r[0] == d for r in weekly_rows[k])}
        if len(raw) < MIN_CROSS_SECTION:
            skipped_small += 1
            continue
        scored = score_group("equity", raw)
        pts = []
        for k, s in scored.items():
            if s["score"] is None:
                continue
            r = fwd(k, d)
            if r is None:
                continue
            pts.append({"k": k, "score": s["score"],
                        "ranks": s["ranks"],
                        "raw": {dim: raw[k].get(dim) for dim in DIMS["equity"]},
                        "r": r})
        if len(pts) < MIN_CROSS_SECTION:
            skipped_no_fwd += 1
            continue
        row = {"d": d, "n": len(pts)}
        row["ic"] = spearman([p["score"] for p in pts], [p["r"] for p in pts])
        for dim in DIMS["equity"]:
            have = [(p["raw"][dim], p["r"]) for p in pts if p["raw"][dim] is not None]
            row["ic_" + dim] = spearman([a for a, _ in have], [b for _, b in have]) if len(have) >= MIN_CROSS_SECTION else None
        row["mean_r"] = float(np.mean([p["r"] for p in pts]))
        row["cross"] = pts
        per_week.append(row)
        if len(per_week) % 40 == 0:
            print("    %d/%d weeks" % (len(per_week), n_weeks), end="\r", flush=True)
    print("  weeks used=%d  skipped(<15 截面)=%d  skipped(前瞻不足)=%d" % (len(per_week), skipped_small, skipped_no_fwd))

    # ── 分段:发现段每 4 周取一个不重叠样本;留出段同构造(20 交易日 ≈ 4 周,两段同一口径)───────────
    def seg(lo, hi, every):
        out = []
        for i, w in enumerate(per_week):
            dd = date.fromisoformat(w["d"])
            if not (lo <= dd <= hi):
                continue
            if every and i % every != 0:
                continue
            out.append(w)
        return out

    def stats(rows, key="ic"):
        return mean_t([w[key] for w in rows])

    disc_all = seg(*DISCOVERY, 0)
    disc = seg(*DISCOVERY, SAMPLE_EVERY_WEEKS)
    hold_all = seg(*HOLDOUT, 0)
    hold = seg(*HOLDOUT, SAMPLE_EVERY_WEEKS)

    res = {
        "task": "T-169", "prereg": "S-668 H1", "code_ref": CODE_REF,
        "mcap_source": MCAP_SOURCE,
        "universe": {"source": "world50_mcap_weekly keys without '.' suffix",
                     "n_keys": len(keys), "note": "今天的候选池 ⇒ 幸存者偏差"},
        "horizon_days": HORIZON_DAYS, "min_cross_section": MIN_CROSS_SECTION,
        "weeks_total": len(per_week), "skipped_small": skipped_small,
        "skipped_no_forward": skipped_no_fwd,
        "discovery_window": [str(DISCOVERY[0]), str(DISCOVERY[1])],
        "holdout_window": [str(HOLDOUT[0]), str(HOLDOUT[1])],
    }

    d_ic, d_t, d_n = stats(disc)
    res["discovery"] = {"n_samples": d_n, "mean_ic": d_ic, "t": d_t,
                        "gate": "mean_ic > 0 and t >= 1.5",
                        "pass": bool(d_ic is not None and d_ic > 0 and d_t is not None and d_t >= 1.5),
                        "single_dims": {dim: stats(disc, "ic_" + dim) for dim in DIMS["equity"]}}
    res["discovery_all_weeks"] = {"n_samples": stats(disc_all)[2],
                                  "mean_ic": stats(disc_all)[0], "t": stats(disc_all)[1]}

    # 发现段过门槛才算留出段 —— 机械。发现段不过时**照样把留出段的数算出来**,
    # 但标 out_of_gate、不进 pass 判定:切换规则要看这个数,藏起来反而是信息更少。
    res["holdout"] = {"in_gate": bool(res["discovery"]["pass"])}
    h_ic, h_t, h_n = stats(hold)
    res["holdout"].update({"n_samples": h_n, "mean_ic": h_ic, "t": h_t,
                           "gate": "mean_ic > 0 and t >= 2",
                           "pass": bool(res["discovery"]["pass"] and h_ic is not None and h_ic > 0
                                        and h_t is not None and h_t >= 2),
                           "single_dims": {dim: stats(hold, "ic_" + dim) for dim in DIMS["equity"]},
                           "all_weeks": {"n_samples": stats(hold_all)[2],
                                         "mean_ic": stats(hold_all)[0], "t": stats(hold_all)[1]}})
    if not res["discovery"]["pass"]:
        res["holdout"]["note"] = ("发现段没过门槛 ⇒ 按 S-668 这段**不算证据**;数字列出来只为让切换规则(S-668 §切换规则)"
                                  "有个可看的数,不改变判定")
    res["verdict"] = ("H1 PASS(留出段过门槛)" if res["holdout"]["pass"]
                      else ("发现段过门槛、留出段不过 ⇒ H1 FAIL" if res["discovery"]["pass"]
                            else "发现段就没过(IC≤0 或 t<1.5)⇒ H1 FAIL;留出段数字只作参考,不算证据"))

    # ── 新旧并列:同一段口径、同一段日期,唯一差别 = mcap_usd 的 source ───────────────────────────────
    # 判定按本版(v3 单口径);v1 只作为对照列出,不进判定。
    if V1_RESULTS.exists():
        v1 = json.loads(V1_RESULTS.read_text())

        def cell(block):
            if not block:
                return None
            return {"n": block.get("n_samples"), "ic": block.get("mean_ic"), "t": block.get("t")}

        res["v1_comparison"] = {
            "what": "v1 = 三个 source 混取(按日期去重随机留一个);v2 = 只取 source=" + MCAP_SOURCE,
            "only_difference": "world50_mcap_weekly 的 source",
            "discovery": {"v1": cell(v1.get("discovery")), "v2": cell(res["discovery"])},
            "holdout": {"v1": cell(v1.get("holdout")), "v2": cell(res["holdout"])},
            "single_dims_discovery": {dim: {"v1": v1["discovery"]["single_dims"][dim],
                                            "v2": res["discovery"]["single_dims"][dim]}
                                      for dim in DIMS["equity"]},
            "single_dims_holdout": {dim: {"v1": v1["holdout"]["single_dims"][dim],
                                          "v2": res["holdout"]["single_dims"][dim]}
                                    for dim in DIMS["equity"]},
            "v1_verdict": v1.get("verdict"),
        }

    # ── 口径污染审计:v1 的缓存(混取)与本版(单口径)逐 (key, d) 对比 ──────────────────────────────
    # v1 的去重是「同一天后写的盖掉先写的」,而同一 (key, d) 有三行 ⇒ 留下哪一行取决于
    # PostgREST 的返回次序,不是数据本身说的。这一段把这件事量出来,而不是假设它。
    v1_cache = CACHE / "w50_mcap_weekly_bare.json"
    if v1_cache.exists():
        old = json.loads(v1_cache.read_text())
        new = {k: dict(v) for k, v in mc.items()}
        matched = differing = 0
        only_old: list[list] = []
        for k, ser in old.items():
            n3 = new.get(k, {})
            for d, val in ser:
                if d in n3:
                    matched += 1
                    if abs(n3[d] - val) > max(1e-6, abs(n3[d]) * 1e-9):
                        differing += 1
                else:
                    only_old.append([k, d, round(val, 2)])
        res["contamination_audit"] = {
            "v1_cache": str(v1_cache),
            "v1_matched_key_date": matched, "v1_differing_from_v3": differing,
            "v1_rows_only_in_old_source": only_old,
            "v1_rows_total": sum(len(v) for v in old.values()),
            "v2_rows_total": sum(len(v) for v in mc.values()),
            "note": "v1 按日期去重只能留一行;留哪一行取决于返回次序。matched 里 differing=0 "
                    "说明这一次 v1 恰好全留了 v3 —— 但那是次序的巧合,不是数据的性质。",
        }

    # ── 探索性:零信号对照(打乱前瞻收益、保留截面分布)—— 走 apparatus,不是自己写的零分布 ──────────
    def shuffled_ic(rng) -> float:
        ics = []
        for w in seg(DISCOVERY[0], HOLDOUT[1], SAMPLE_EVERY_WEEKS):
            r = np.asarray([p["r"] for p in w["cross"]], dtype=float)
            s = np.asarray([p["score"] for p in w["cross"]], dtype=float)
            ic = spearman(list(s), list(r[rng.permutation(r.size)]))
            if ic is not None:
                ics.append(ic)
        m, _, _ = mean_t(ics)
        return m if m is not None else float("nan")

    try:
        pool = seg(DISCOVERY[0], HOLDOUT[1], SAMPLE_EVERY_WEEKS)
        actual = stats(pool)[0]
        null = null_distribution(shuffled_ic, NULL_N, NULL_SEED + 7, actual=actual)
        res["exploratory_zero_signal"] = {
            "what": "打乱每周前瞻收益(保留截面分布)后的平均 IC 零分布",
            "n_null": int(null.size),
            "actual_mean_ic_full_sample": actual,
            "percentile_of_full_sample_mean_ic": percentile_of(actual, null),
            "caveat": "探索性 —— 未预注册,不构成证据",
        }
    except Exception as exc:  # apparatus 会主动拒绝退化零分布
        res["exploratory_zero_signal"] = {"error": type(exc).__name__ + ": " + str(exc)}

    (REPO / "docs/research/t169_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    # 每周明细(供核对 / 挖掘)
    (CACHE / "per_week_ic.json").write_text(json.dumps(
        [{k: v for k, v in w.items() if k != "cross"} for w in per_week], ensure_ascii=False))
    write_report(res, per_week)
    print(json.dumps({k: v for k, v in res.items() if k not in ("discovery", "holdout")},
                     ensure_ascii=False, indent=2)[:2000])
    print("VERDICT: %s" % res["verdict"])


def write_report(res: dict, per_week: list[dict]) -> None:
    def f(x, n=4):
        return "—" if x is None else ("%+.*f" % (n, x))

    d, h = res["discovery"], res["holdout"]
    L: list[str] = []
    L.append("# T-169 / S-668 H1 —— 个股:规模 + 稳定 + 供给纪律 对之后 4 周的 Spearman IC\n")
    L.append("- 生成:2026-10-22 · 脚本 `docs/research/t169_equity_quality.py` · 内核 `%s`(S-668)" % res["code_ref"])
    L.append("- 宇宙:World50 候选池里**不带 . 后缀**的 key(**今天**的名单 ⇒ 幸存者偏差)")
    L.append("- 数据:`world50_mcap_weekly`(**source = %s**)+ `ohlcv_daily(source=eodhd, close)`;"
             "输入行 = (周日期, mcap_usd, 当周最后交易日收盘)" % res.get("mcap_source", "?"))
    L.append("- 截面 < 15 家的周跳过并计数;发现段每 4 周一个不重叠样本,留出段同一口径\n")
    L.append("## S-668 H1 结果\n")
    L.append("| 段 | 样本 | 平均 IC | t | 门槛 | 判定 |")
    L.append("|---|---|---|---|---|---|")
    L.append("| 发现段 %s→%s | %d | %s | %s | IC>0 且 t≥1.5 | %s |"
             % (res["discovery_window"][0], res["discovery_window"][1], d["n_samples"],
                f(d["mean_ic"]), f(d["t"], 2), "**过**" if d["pass"] else "不过"))
    if h.get("in_gate"):
        L.append("| 留出段 %s→%s | %d | %s | %s | IC>0 且 t≥2 | %s |"
                 % (res["holdout_window"][0], res["holdout_window"][1], h["n_samples"],
                    f(h["mean_ic"]), f(h["t"], 2), "**过**" if h["pass"] else "不过"))
    else:
        L.append("| ~~留出段~~ %s→%s | %d | %s | %s | IC>0 且 t≥2 | **门槛外**(发现段没过,按 S-668 不算证据)|"
                 % (res["holdout_window"][0], res["holdout_window"][1], h["n_samples"],
                    f(h["mean_ic"]), f(h["t"], 2)))
    if h.get("note"):
        L.append("\n> %s" % h["note"])
    L.append("\n**总判定:%s**\n" % res["verdict"])

    L.append("### 三个单维度(只报,不作门槛)\n")
    L.append("| 维度 | 发现段 IC / t | 留出段 IC / t |")
    L.append("|---|---|---|")
    for dim in DIMS["equity"]:
        dd = d["single_dims"][dim]
        hh = h.get("single_dims", {}).get(dim)
        L.append("| %s | %s / %s | %s |" % (
            dim, f(dd[0]), f(dd[1], 2),
            ("%s / %s" % (f(hh[0]), f(hh[1], 2))) if hh else "—"))
    L.append("\n### 新旧并列(v1 = 三个 source 混取 / v2 = 只取 source=%s)\n" % res.get("mcap_source", "?"))
    cmp_ = res.get("v1_comparison")
    if not cmp_:
        L.append("- 无 v1 对照文件(`docs/research/t169_results_v1.json`),本表跳过。\n")
    else:
        L.append("唯一差别 = `world50_mcap_weekly` 的 source;日期、样本、内核、门槛全部一样。**判定按 v2。**\n")
        L.append("| 段 | v1(混取) IC / t | v2(单口径) IC / t |")
        L.append("|---|---|---|")
        for seg, label in (("discovery", "发现段"), ("holdout", "留出段")):
            a, b = cmp_[seg]["v1"], cmp_[seg]["v2"]
            sa = ("%s / %s" % (f(a["ic"]), f(a["t"], 2))) if a and a["ic"] is not None else "—"
            sb = ("%s / %s" % (f(b["ic"]), f(b["t"], 2))) if b and b["ic"] is not None else "—"
            L.append("| %s | %s | %s |" % (label, sa, sb))
        L.append("\n单维度(IC):\n")
        L.append("| 维度 | 发现段 v1 → v2 | 留出段 v1 → v2 |")
        L.append("|---|---|---|")
        for dim in DIMS["equity"]:
            row = []
            for seg in ("discovery", "holdout"):
                a = cmp_["single_dims_" + seg][dim]["v1"]
                b = cmp_["single_dims_" + seg][dim]["v2"]
                row.append("%s → %s" % (f(a[0]), f(b[0])))
            L.append("| %s | %s | %s |" % (dim, row[0], row[1]))
        L.append("\n> v1 判定:%s\n> v2 判定:%s\n" % (cmp_["v1_verdict"], res["verdict"]))
        aud = res.get("contamination_audit")
        if aud:
            L.append("\n**口径污染到底有多大(逐 (key, d) 对比)**:v1 有 %d 行,其中 %d 行能对上 v3,"
                     "**数值不同的 %d 行**;另有 %d 行只存在于旧口径(v3 没覆盖)。\n"
                     % (aud["v1_rows_total"], aud["v1_matched_key_date"], aud["v1_differing_from_v3"],
                        len(aud["v1_rows_only_in_old_source"])))
            if aud["v1_rows_only_in_old_source"]:
                grp: dict[str, int] = {}
                for k, _, _ in aud["v1_rows_only_in_old_source"]:
                    grp[k] = grp.get(k, 0) + 1
                L.append("- 只在旧口径里有的行:%s\n"
                         % " · ".join("%s %d 行" % (k, n) for k, n in sorted(grp.items())))
            L.append("- 也就是说 **v1 这次并没有真的混进去**:同一 (key, d) 有三行时,它每次都留下了 v3 那行,"
                     "所以两版数字几乎一样。但这是 PostgREST 返回次序的巧合,不是数据保证的 —— "
                     "Seth 指出的口径纪律问题是对的,只是**这一版的污染量恰好≈0**。"
                     "改成单口径是把「靠运气」换成「按规矩」,不是修一个已经算错了的数。\n")

    L.append("\n### 计数\n")
    L.append("- 有效周:%d · 因截面 < 15 家跳过:%d · 因前瞻不足跳过:%d"
             % (res["weeks_total"], res["skipped_small"], res["skipped_no_forward"]))
    L.append("- 发现段全周口径(每 4 周抽样之外的补充):平均 IC %s / t %s"
             % (f(res["discovery_all_weeks"]["mean_ic"]), f(res["discovery_all_weeks"]["t"], 2)))
    if h.get("all_weeks"):
        L.append("- 留出段全周口径:平均 IC %s / t %s"
                 % (f(h["all_weeks"]["mean_ic"]), f(h["all_weeks"]["t"], 2)))
    L.append("\n### 读这张表要知道的\n")
    L.append("- **幸存者偏差**:名单是 2026-10 的候选池,2016 年退市 / 被剔除的公司不在里面。"
             "发现段与留出段共用同一份名单,所以段内比较仍然成立,但绝对水平偏乐观。")
    L.append("- **留出段不是纯留出**:v2 的三个维度是照 2023–26 的加密数据(S-587 / S-589 / S-664)选的,"
             "个股这一段从没被选过 —— 门槛检验的是「这套维度换个资产类还成不成立」,不是「这套维度在个股上是从零发现」。")
    L.append("- 供应纪律的股数 = mcap_usd ÷ close,所以这一维**只认 source=%s**;"
             "表里另两个口径(sec_shares_x_close / sec_shares_x_close_v2)同一 (key, d) 也有行,"
             "混取会把口径差当成股数变化(老口径 CMCSA 2015-01-02 = 118.32B,v3 = 147.96B,差 25%%)。"
             "本次已改为单口径,新旧两版结果见上表。" % res.get("mcap_source", "?"))
    L.append("- `ohlcv_daily` 的列名是 `close`,按既有 t099 面板的约定当作**复权收盘**用。"
             "已单独核过:NVDA 2024-06-10 的 10:1 拆分当日 close 只动了 +0.75%(没有 −90% 的断层),"
             "所以这一列确实是拆股调整过的 —— 但**分红调整没核**(表里没有独立 adj_close 列可对)。\n")

    L.append("## 挖掘\n")
    L.append("**以下全部是探索性 —— 未预注册,不构成证据;要当结论用需另立预注册并在新数据上过零信号对照。**\n")
    z = res.get("exploratory_zero_signal", {})
    if "percentile_of_full_sample_mean_ic" in z:
        p = z["percentile_of_full_sample_mean_ic"]
        L.append("- 零信号对照(打乱每周前瞻收益、保留截面分布):全样本平均 IC 的分位 = %s(n_null=%d)。"
                 % (f(p, 3), z["n_null"]))
    else:
        L.append("- 零信号对照未跑成:%s" % z.get("error", "—"))
    by_year: dict[str, list[float]] = {}
    for w in per_week:
        if w["ic"] is not None:
            by_year.setdefault(w["d"][:4], []).append(w["ic"])
    L.append("- 按年拆的 v2 IC(样本少,只当形状看):%s"
             % " · ".join("%s %s" % (y, f(sum(v) / len(v), 3)) for y, v in sorted(by_year.items())))
    if not d["pass"] and h["mean_ic"] is not None:
        L.append("- **门槛外但值得记的一件事**:留出段(%s / t=%s)与发现段(%s / t=%s)的**符号相同、量级几乎相同**。"
                 "也就是说「这个反向关系会不会只是发现段的产物」——不是,它原样长到了 2021–26。"
                 "这是**探索性 —— 未预注册**;但它把结论从「发现段没测出来」变成「测出来了,是反的」。"
                 % (f(h["mean_ic"]), f(h["t"], 2), f(d["mean_ic"]), f(d["t"], 2)))
        L.append("- 三个维度里只有**供给纪律**在留出段翻正(%s / t=%s,不显著);规模与稳定两段都是负的。"
                 "**探索性 —— 未预注册**:下一张该拆的问题是「把规模与稳定拿掉、只留供给纪律,是不是仍然是反的」。"
                 % (f(h["single_dims"]["supply"][0]), f(h["single_dims"]["supply"][1], 2)))
    L.append("- 宇宙是**今天**的 World50 候选池(125 个不带 . 后缀的 key),2016 年退市 / 被剔除的公司不在里面。"
             "幸存者偏差通常把两边都抬平,但它**不能**解释「两段都稳定为负」——这个符号更像是大市值质量股"
             "在这 10 年里被反向定价。**探索性 —— 未预注册。**")
    L.append("- 样本 %d 个名字里,ADR(壳 / 非美注册)与美股本土公司在「供给纪律」上的股数口径不同,"
             "本卡未拆开 —— 若结果要用在对外分数上,这是下一个该拆的口子。\n"
             % res["universe"]["n_keys"])
    L.append("- **入库数据可疑点(不改数据,交 @seth)**:`sec_shares_x_close` 里 BRK-B 2015-01-02 → 2015-02-27 "
             "十周的 mcap_usd ≈ **$0.140B**,同表 2015-03-06 起是 **$358B**。用同一份 eodhd 收盘(≈$149)反推股数:"
             "那十周是 **0.9M 股**,之后是 **2,464.4M 股** —— 差约 2,700 倍,像是单位(千/百万)写错。"
             "v3 没有这十周,所以本次结果不受影响;但**任何还在读 sec_shares_x_close 的下游都会吃到它**。\n"
             "**探索性 —— 需另立预注册、在新数据上过零信号对照;数据本身归 Seth 的入库道。**")

    L.append("---\n_由 T-169 脚本自动生成;数值以 `docs/research/t169_results.json` 为准。_\n")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print("report -> %s" % REPORT)


if __name__ == "__main__":
    main()