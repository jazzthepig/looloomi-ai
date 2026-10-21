"""S-663 价值挖掘:链上稳定币流入 / TVL 是否能在 L1/L2 代币横截面上挑出之后更好的链。

结构照抄 `docs/research/s661_value_mining.py`(`month_ends` / `add_months` / `at` /
`spearman` / `summarize` 都从 s661 import,块自助同 s661 内联),只换数据(链级稳定币
+ TVL)和信号(C1–C4)。链 → gecko_id 见 `t168_fetch_chains.py`。

发现段与留出段在同一次运行里按机械规则走完:发现段过的信号(平均 IC>0、t≥2、
两半 IC 都>0)自动进留出段(每信号只留 t 最大的期限,多于 3 个取 t 最大的 3 个,k
取实际过的个数;块自助 2,000 次,单侧 p<0.05/k)。没有信号过发现段 ⇒ 不算留出段。
截面<8 的月份跳过并计数(见 `coverage`)。

数据缓存(由 `t168_fetch_chains.py` 产出,本研究只读):
    <root>/research/t168/_llama_chain_stables.jsonl
    <root>/research/t168/_llama_chain_tvl.jsonl
    <root>/research/t168/_chains_gecko.json
    <root>/research/t168/_mcap_chain.json
输出:
    docs/research/t168_results.json
    <root>/_reports/absorb_input/T-168_s663_chain_flows.md

用法:python3 docs/research/t168_chain_flows.py [--root …]
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import random
import sys

# import 复用 —— s661 必须先落到 origin/main 才能被 CI 通过 import 拉进来;落地之前
# 本脚本要在主仓 worktree(`/Users/sbb/Projects/looloomi-ai`)里跑(s661 在那里是
# 已签出的工作目录)。
sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai/docs/research")
import s661_value_mining as s661                                # noqa: E402

month_ends = s661.month_ends
add_months = s661.add_months
at = s661.at
spearman = s661.spearman
summarize = s661.summarize
MIN_XS = s661.MIN_XS

ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
DIR = os.path.join(ROOT, "research", "t168")

MIN_MCAP, MIN_HIST_DAYS = 1e8, 120
DISC = ("2021-01-31", "2023-12-31")
HOLD = ("2024-01-31", "2026-06-30")
HORIZONS = {"1m": 1, "3m": 3}
SIGNALS = ("C1", "C2", "C3", "C4")
SEED = 663


# ── 数据加载 ────────────────────────────────────────────────────────────────────
def load_stables() -> dict[str, dict[dt.date, float]]:
    """gecko_id → {date: stables_usd}(按日聚合:同一 gecko_id 多条链求和)。
    输入 `_llama_chain_stables.jsonl`(每行 chain + data[[ts,usd],...])。
    """
    from collections import defaultdict
    chain_map: dict[str, str] = json.load(open(os.path.join(DIR, "_chains_gecko.json")))
    agg: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for line in open(os.path.join(DIR, "_llama_chain_stables.jsonl")):
        r = json.loads(line)
        g = chain_map.get(r.get("chain"))
        if not g or "data" not in r:
            continue
        for ts, v in r["data"]:
            agg[g][int(ts)] += float(v)
    out: dict[str, dict[dt.date, float]] = {}
    for g, ts_dict in agg.items():
        ser: dict[dt.date, float] = {}
        for ts, v in ts_dict.items():
            d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
            ser[d] = v
        out[g] = ser
    return out


def load_tvl() -> dict[str, dict[dt.date, float]]:
    from collections import defaultdict
    chain_map: dict[str, str] = json.load(open(os.path.join(DIR, "_chains_gecko.json")))
    agg: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for line in open(os.path.join(DIR, "_llama_chain_tvl.jsonl")):
        r = json.loads(line)
        g = chain_map.get(r.get("chain"))
        if not g or "data" not in r:
            continue
        for ts, v in r["data"]:
            agg[g][int(ts)] += float(v)
    out: dict[str, dict[dt.date, float]] = {}
    for g, ts_dict in agg.items():
        ser: dict[dt.date, float] = {}
        for ts, v in ts_dict.items():
            d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
            ser[d] = v
        out[g] = ser
    return out


def load_mcap() -> tuple[dict[str, list[tuple[dt.date, float, float]]], dict[str, dt.date]]:
    """(gecko_id → [(d, price, mcap),...], gecko_id → first_date_with_stable)。
    把 stables 第一日作为该 chain 的 `start`(spec:稳定币序列 ≥ 120 天)。
    """
    px: dict[str, list[tuple[dt.date, float, float]]] = {}
    for x in json.load(open(os.path.join(DIR, "_mcap_chain.json"))):
        if x.get("price"):
            c = x["coin_id"]
            px.setdefault(c, []).append((dt.date.fromisoformat(x["d"][:10]),
                                         float(x["price"]), float(x.get("mcap") or 0.0)))
    for c in px:
        px[c].sort()
    return px, {}


def window_sum_log(s: dict[dt.date, float], end: dt.date, days_back: int) -> float:
    """取 `end − days_back` 当天的 stables(最近可得,容忍 < 5 天的旧值)。"""
    for k in range(days_back, days_back + 6):
        v = s.get(end - dt.timedelta(days=k))
        if v and v > 0:
            return float(v)
    return 0.0


# ── 信号 ────────────────────────────────────────────────────────────────────────
def cross_section(t: dt.date, stables, px) -> list[dict]:
    """链级横截面(月末 t)。信号 C1 = ln(S[t]/S[t-30]);C2 = S[t]/mcap[t];
    C3 = C1 − ln(S[t-30]/S[t-120])/3;C4 = C1、C2 截面秩相加(两者都有的)。"""
    rows = []
    for g, ser in stables.items():
        if g not in px:
            continue
        if t not in ser:
            continue
        # 120 天历史检查(spec 写「t 之前稳定币序列 ≥ 120 天」)
        n_pre = sum(1 for k in range(1, 121) if (t - dt.timedelta(days=k)) in ser)
        if n_pre < MIN_HIST_DAYS:
            continue
        # 价格 / 市值(t 与 t+horizon 都得有)
        p0 = at(px[g], t)
        if not p0 or p0[2] < MIN_MCAP:
            continue
        s_t = float(ser.get(t, 0.0) or 0.0)
        s_30 = window_sum_log(ser, t, 30)
        s_120 = window_sum_log(ser, t, 120)
        if s_t <= 0 or s_30 <= 0 or s_120 <= 0 or p0[2] <= 0:
            continue
        c1 = math.log(s_t / s_30)
        c2 = s_t / p0[2]
        c3 = c1 - math.log(s_30 / s_120) / 3.0
        row = {"g": g, "mcap": p0[2], "p0": p0[1], "C1": c1, "C2": c2, "C3": c3}
        for h, k in HORIZONS.items():
            p1 = at(px[g], add_months(t, k))
            row["y" + h] = math.log(p1[1] / p0[1]) if p1 and p1[1] > 0 else None
        rows.append(row)
    # C4 = C1、C2 截面秩相加(两者都有的)
    both = [r for r in rows if r["C3"] is not None]
    for key in ("C1", "C2"):
        for rank, r in enumerate(sorted(both, key=lambda r: r[key])):
            r["_rk" + key] = rank
    for r in rows:
        r["C4"] = (r["_rkC1"] + r["_rkC2"]) if r["C3"] is not None else None
    # 相对宇宙:减同截面等权均值
    for h in HORIZONS:
        ys = [r["y" + h] for r in rows if r["y" + h] is not None]
        mu = sum(ys) / len(ys) if ys else 0.0
        for r in rows:
            r["x" + h] = (r["y" + h] - mu) if r["y" + h] is not None else None
    return rows


def month_stats(rows: list[dict], sig: str, h: str):
    pts = [(r[sig], r["x" + h]) for r in rows if r.get(sig) is not None and r.get("x" + h) is not None]
    if len(pts) < MIN_XS:
        return None
    ic = spearman([p[0] for p in pts], [p[1] for p in pts])
    pts.sort()
    k = len(pts) // 3
    spread = sum(p[1] for p in pts[-k:]) / k - sum(p[1] for p in pts[:k]) / k
    return ic, spread, len(pts)


def run_window(window: tuple[str, str], stables, px):
    xs = {t: cross_section(t, stables, px) for t in month_ends(*window)}
    out: dict = {}
    for sig in SIGNALS:
        for h in HORIZONS:
            ser = []
            for t, rows in xs.items():
                st = month_stats(rows, sig, h)
                if st:
                    ser.append((t, st[0], st[1], st[2]))
            out[f"{sig}:{h}"] = {"all": summarize(ser), "series": [(t.isoformat(), round(i, 4)) for t, i, *_ in ser],
                                 "_raw": ser}
    return out, xs


def pick_passes(res_d: dict) -> list[str]:
    """发现段机械选:每信号只留 t 最大的期限、平均 IC>0、t≥2、两半 IC 都>0;
    多于 3 个取 t 最大的 3 个。"""
    per_sig: dict[str, tuple[float, str]] = {}
    for key, v in res_d.items():
        sig, h = key.split(":")
        a = v["all"]
        h1 = v["half_2021_22"]
        h2 = v["half_2023"]
        if (a.get("mean_ic") or 0) > 0 and (a.get("t") or 0) >= 2.0 \
                and (h1.get("mean_ic") or 0) > 0 and (h2.get("mean_ic") or 0) > 0:
            t_val = a.get("t") or 0.0
            cur = per_sig.get(sig)
            if cur is None or t_val > cur[0]:
                per_sig[sig] = (t_val, h)
    ranked = sorted(per_sig.items(), key=lambda kv: kv[1][0], reverse=True)
    kept = ranked[:3]
    return [f"{sig}:{h}" for sig, (_, h) in kept]


def block_bootstrap_p(ser: list[tuple], k_total: int, seed: int) -> float:
    """3 个月一块的块自助 2,000 次,单侧 p(均值 ≤ 0 的占比)。
    与 s661 同口径,见 `s661_value_mining.py::holdout`。
    """
    ics = [s[1] for s in ser]
    n = len(ics)
    if n < 3:
        return float("nan")
    blocks = [ics[i:i + 3] for i in range(0, n, 3)]
    rng = random.Random(seed)
    boots = []
    for _ in range(2000):
        draw = [x for _b in range(len(blocks)) for x in rng.choice(blocks)]
        boots.append(sum(draw) / len(draw))
    return sum(1 for b in boots if b <= 0) / len(boots)


def main():
    stables = load_stables()
    px, _ = load_mcap()
    print(f"# chains_with_stables: {len(stables)}, # chains_with_mcap: {len(px)}", file=sys.stderr)

    res_d, xs_d = run_window(DISC, stables, px)
    res_h, xs_h = run_window(HOLD, stables, px)
    coverage_d = {t.isoformat(): len(r) for t, r in xs_d.items()}
    coverage_h = {t.isoformat(): len(r) for t, r in xs_h.items()}
    skipped_d = sum(1 for n in coverage_d.values() if n < MIN_XS)
    skipped_h = sum(1 for n in coverage_h.values() if n < MIN_XS)

    # 发现段每信号分两半(同 s661)
    for key, v in res_d.items():
        ser = v["_raw"]
        h1 = summarize([s for s in ser if s[0] < dt.date(2023, 1, 1)])
        h2 = summarize([s for s in ser if s[0] >= dt.date(2023, 1, 1)])
        v["half_2021_22"] = h1
        v["half_2023"] = h2
    passed = pick_passes(res_d)
    print(f"# discovery_picked: {passed}", file=sys.stderr)

    # 留出段:只对过了发现段的信号算块自助
    k = len(passed)
    threshold = 0.05 / k if k > 0 else None
    holdout_verdicts: dict = {}
    for key in passed:
        ser = res_h.get(key, {}).get("_raw") or []
        p = block_bootstrap_p(ser, k, SEED) if k > 0 else float("nan")
        a = summarize(ser)
        spread = (a.get("spread") or 0.0)
        ok = k > 0 and (a.get("mean_ic") or 0) > 0 and not math.isnan(p) and p < (threshold or 0) and spread > 0
        holdout_verdicts[key] = {"all": a, "p_block_boot": None if math.isnan(p) else round(p, 4),
                                  "threshold": threshold, "verdict": "过" if ok else "不过",
                                  "series": res_h.get(key, {}).get("series", [])}

    # 只报不判:TVL 30 日对数增长
    tvl_verdicts: dict = {}
    tvl_rows = {g: ser for g, ser in load_tvl().items()}
    for h, k_month in HORIZONS.items():
        ser = []
        for t in month_ends(*DISC):
            rows = []
            for g, tser in tvl_rows.items():
                if g not in px or t not in tser:
                    continue
                v_t = float(tser.get(t, 0.0) or 0.0)
                v_30 = window_sum_log(tser, t, 30)
                if v_t <= 0 or v_30 <= 0:
                    continue
                p0 = at(px[g], t)
                if not p0 or p0[2] < MIN_MCAP:
                    continue
                p1 = at(px[g], add_months(t, k_month))
                if not p1 or p1[1] <= 0:
                    continue
                ys = []
                for gg, gser in tvl_rows.items():
                    if gg not in px:
                        continue
                    gp0 = at(px[gg], t)
                    gp1 = at(px[gg], add_months(t, k_month))
                    if gp0 and gp1 and gp0[2] >= MIN_MCAP:
                        ys.append(math.log(gp1[1] / gp0[1]))
                rel = math.log(p1[1] / p0[1]) - (sum(ys) / len(ys) if ys else 0.0)
                rows.append((math.log(v_t / v_30), rel))
            if len(rows) >= MIN_XS:
                ser.append((t, spearman([p[0] for p in rows], [p[1] for p in rows]),
                            max([p[1] for p in rows]) - min([p[1] for p in rows]),
                            len(rows)))
        tvl_verdicts[f"TVL:{h}"] = {
            "all": summarize(ser),
            "series": [(t.isoformat(), round(i, 4)) for t, i, *_ in ser],
            "note": "only_report_no_judge(TVL 与币价机械相关,见 S-663 预注册)",
        }

    # 落盘 results.json(strip _raw;只留展示口径)
    out_json = {
        "id": "T-168",
        "prereg": "S-663 in REFUTATION_LEDGER.md (2026-10-21 16:31 UTC)",
        "discovery_window": DISC,
        "holdout_window": HOLD,
        "universe": f"{len(stables)} chains_with_stables × {len(px)} chains_with_mcap",
        "min_xs": MIN_XS,
        "skipped_months": {"discovery_lt_min_xs": skipped_d, "holdout_lt_min_xs": skipped_h},
        "coverage_discovery": coverage_d,
        "coverage_holdout": coverage_h,
        "signals": SIGNALS,
        "horizons": list(HORIZONS),
        "discovery": {key: {k: v[k] for k in ("all", "half_2021_22", "half_2023", "series")}
                       for key, v in res_d.items()},
        "discovery_passed": passed,
        "k": k,
        "holdout_threshold_alpha_over_k": threshold,
        "holdout": holdout_verdicts,
        "holdout_summary": (
            "过了" if holdout_verdicts and all(v["verdict"] == "过" for v in holdout_verdicts.values()) and k > 0
            else "没有信号过发现段" if k == 0
            else "不过"
        ),
        "tvl_only_report": tvl_verdicts,
    }
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    json.dump(out_json, open(os.path.join(out_dir, "t168_results.json"), "w"), indent=1)

    # 报告(MD)
    def fmt_row(label, d, h):
        key = f"{label}:{h}"
        a = (out_json["discovery"][key]["all"] if key in out_json["discovery"] else {})
        row = f"| {label} {h} | {a.get('mean_ic', '-')!s} | {a.get('t', '-')!s} | {a.get('spread', '-')!s} |"
        return row
    md = []
    md.append("# T-168 — S-663 链级稳定币流入 / TVL 价值挖掘")
    md.append("")
    md.append("**预注册:** S-663 in `REFUTATION_LEDGER.md` (2026-10-21 16:31 UTC,见卡 T-168)。**脚本:** `docs/research/t168_fetch_chains.py` + `docs/research/t168_chain_flows.py`(本文件)。**数据:** DeFiLlama `/stablecoincharts/{chain}`(每日 `totalCirculatingUSD.peggedUSD`)、`/v2/chains`、`/v2/historicalChainTvl/{chain}`;市值 `asset_mcap_daily`(publishable key,只读)。")
    md.append("")
    md.append(f"**宇宙:** {len(stables)} 条带稳定币序列的 gecko_id × {len(px)} 个有 CoinGecko 市值的 gecko_id(同一个 gecko_id 多条链合并求和)。")
    md.append(f"**截面门槛:** 市值 ≥ {int(MIN_MCAP/1e6)}M、稳定币序列 ≥ {MIN_HIST_DAYS} 天;每个期限 `MIN_XS = {MIN_XS}`。跳过月份(截面<8):发现段 {skipped_d}、留出段 {skipped_h}。")
    md.append("")
    md.append("## 发现段(2021-01-31 → 2023-12-31)")
    md.append("")
    md.append("| 信号 × 期限 | 平均 IC | t | 三分位顶 − 底 |")
    md.append("|---|---|---|---|")
    for s in SIGNALS:
        for h in HORIZONS:
            md.append(fmt_row(s, out_json, h))
    md.append("")
    md.append(f"**过了发现段(机械,k ≤ 3,过 t 最大的):** {passed}。")
    md.append("")
    if k == 0:
        md.append("## 留出段 — 没跑(没有信号过发现段,按 S-663 原文「不算留出段」)")
    else:
        md.append("## 留出段(2024-01-31 → 2026-06-30,一次性,块自助 p < "
                  f"{round(0.05/k, 4) if k else '-'}=0.05/{k})")
        md.append("")
        md.append("| 信号 | 平均 IC | t | 块自助单侧 p | 三分位顶 − 底 | 判 |")
        md.append("|---|---|---|---|---|---|")
        for key in passed:
            v = out_json["holdout"][key]
            a = v["all"]
            md.append(f"| {key} | {a.get('mean_ic', '-')!s} | {a.get('t', '-')!s} | "
                      f"{v['p_block_boot']!s} | {a.get('spread', '-')!s} | {v['verdict']} |")
    md.append("")
    md.append("## TVL 30 日增长(只报不判,见 S-663 原文)")
    md.append("")
    md.append("| 期限 | 平均 IC | t | 三分位顶 − 底 | 月份数 |")
    md.append("|---|---|---|---|---|")
    for h in HORIZONS:
        v = out_json["tvl_only_report"][f"TVL:{h}"]["all"]
        md.append(f"| {h} | {v.get('mean_ic', '-')!s} | {v.get('t', '-')!s} | "
                  f"{v.get('spread', '-')!s} | {v.get('months', '-')!s} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## S-663 结果")
    md.append("")
    if k == 0:
        md.append("**链级稳定币流入(及加速)在 L1/L2 代币横截面上挑不出之后更好的链——没有信号过发现段;按 S-663 原文不碰留出段。** 链级资金面**不进战场简报**。记档。")
    else:
        any_pass = all(v["verdict"] == "过" for v in out_json["holdout"].values())
        if any_pass:
            md.append(f"**链级资金面过了:** {passed} 在留出段同时过 ① (mean IC > 0、3m 块自助 p < 0.05/{k}) 与 ② (顶 − 底三分位 > 0)。**进战场简报一列、作为 ② 在链代币里的倾斜候选另立前向**。")
        else:
            md.append(f"**链级资金面没全套过:** {passed} 进了留出段但全部或部分没过 ① 或 ②。**记档** —— 不进战场简报、不立前向。")
    md.append("")
    md.append("**试验计数:** 价值族第 3 次;发现段 4 信号 × 2 期限为探索,留出段 k ≤ 3。")
    rep_dir = os.path.join(ROOT, "_reports", "absorb_input")
    os.makedirs(rep_dir, exist_ok=True)
    rep = os.path.join(rep_dir, "T-168_s663_chain_flows.md")
    open(rep, "w").write("\n".join(md))
    print(f"# wrote {rep}", file=sys.stderr)


if __name__ == "__main__":
    main()
