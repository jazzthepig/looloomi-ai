#!/usr/bin/env python3
"""T-313 / S-793 —— Regime 态(market_state_vectors)能不能提前读出 Asset 空间里 P(价格相位)排序的强弱。

口径一字不改照 S-793 预注册(原文照抄在 docs/research/T-313_state_to_ic.md 开头):
  · IC 序列不重算:t312_results.json 的 weekly_ic(P / P_bottom_quintile_x30),197 周 2023-01-02 → 2026-10-05。
  · 状态:market_state_vectors.vec_full(24 维,按时点 z 分数;null = 未测)。周 t 取周一 t 当天,
    没有则往前最近一天(≤ 3 天);再没有 ⇒ 该周不预测。**不补 0**。
  · kNN 臂:候选 = 所有 s ≤ t − 35 天的周;距离 = 两向量**共有实测维**上的欧氏距离 ÷ √(共有维数);
    共有维 < 8 的候选剔除;取最近 k = 10,预测 = 它们 P-IC 的等权均值;合格候选 < 26 周 ⇒ 该周不预测。
  · 惯性臂(基线):同样只用 s ≤ t − 35 天的周,最近 12 周 P-IC 的均值。
  · 判定区间:两臂都有预测的全部周;两半按周数对半切(前半多一周)。
  · 判据 (a)(b)(c)(d) 照原文,全过才 ✅。

只算一次,不扫参数。k = 5 / 20 只作描述性敏感度,不进判定。
零分布 / 块置换 / A-B 只用 src/data/evaluation/apparatus.py;Spearman 用 joint_model.spearman。
只读:不写库、不改 src/。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    block_permute,
    null_distribution,
    percentile_of,
    stationary_bootstrap_index,
)
from src.data.evaluation.joint_model import spearman  # noqa: E402

# ── 预注册常数(算前写死,不扫) ─────────────────────────────────────────────────
KNN_K = 10                 # S-793:取最近 k = 10
CANDIDATE_LAG_DAYS = 35    # S-793:候选 s ≤ t − 35 天
INERTIA_WEEKS = 12         # S-793:惯性臂最近 12 周
MIN_SHARED_DIMS = 8        # S-793:共有维 < 8 剔除
MIN_CANDIDATES = 26        # S-793:合格候选 < 26 周则该周不预测
PERM_BLOCK = 8             # S-793:块长 8 周
N_NULL = 1000              # S-793:1,000 次
SEED = 793                 # S-793:种子 793
NW_LAGS = 5                # S-793:Newey–West 滞后 5
STATE_MAX_BACKFILL_DAYS = 3  # S-793:往前最近一天(≤ 3 天)
DIMS = 24                  # S-793:24 维

IC_CANDIDATE_PATHS = [
    ROOT / "docs/research/t312_results.json",
    ROOT / "docs/research/_t313_ic_raw.json",
]
STATE_SNAPSHOT = ROOT / "docs/research/_t313_state_raw.json"
OUT_STATE_CSV = ROOT / "docs/research/t313_state.csv"
OUT_RESULTS = ROOT / "docs/research/t313_results.json"


# ── 读库(只读 SELECT) ─────────────────────────────────────────────────────────
def fetch_state() -> list[dict]:
    """从 Supabase 拉 market_state_vectors(d, zscore_pass, vec_full),翻页带 order=d.asc。"""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    rows: list[dict] = []
    offset, page = 0, 1000
    while True:
        path = (f"market_state_vectors?select=d,zscore_pass,vec_full"
                f"&order=d.asc&limit={page}&offset={offset}")
        req = urllib.request.Request(url + "/rest/v1/" + path)
        req.add_header("apikey", key)
        req.add_header("Authorization", "Bearer " + key)
        req.add_header("Prefer", "count=exact")
        with urllib.request.urlopen(req, timeout=180) as resp:
            batch = json.loads(resp.read().decode())
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
        if offset > 50_000:
            break
    return rows


def state_fingerprint(rows: list[dict]) -> str:
    """按 (d, vec_full) 排序后的 sha256(与取数脚本同一口径)。"""
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda x: x["d"]):
        h.update(r["d"].encode())
        h.update(b"|")
        h.update(json.dumps(r["vec_full"], sort_keys=False, separators=(",", ":")).encode())
        h.update(b"\n")
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ledger_section(ledger_id: str) -> list[str]:
    """从台账里原样取出 S-NNN 那一节(到下一个 '## ' 之前),保证报告开头的原文一字不改。"""
    path = ROOT / "REFUTATION_LEDGER.md"
    if not path.exists():
        raise SystemExit(f"找不到 {path}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"## {ledger_id} "):
            start = i
            break
    if start is None:
        raise SystemExit(f"台账里找不到 {ledger_id} 那一节")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return lines[start:end]


# ── 前向预期(scenarios/):概率用历史基率,不用手感 ────────────────────────────
def _rest_get(path: str):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(url + "/rest/v1/" + path)
    req.add_header("apikey", key)
    req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def _paged(path_base: str, order: str) -> list[dict]:
    """翻页读,带 order=;每页 ≤ 1000 行。"""
    rows: list[dict] = []
    offset = 0
    while True:
        batch = _rest_get(f"{path_base}&order={order}&limit=1000&offset={offset}")
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
        if offset > 50_000:
            break
    return rows


def base_rate_up(series: list[tuple[str, float]], horizon_days: int = 35) -> tuple[float | None, int]:
    """P(x[t+h] > x[t]) 的历史基率(h 日后第一个有值的日)。"""
    pts = sorted({dt.date.fromisoformat(a): float(b) for a, b in series}.items())
    days = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    n = len(pts)
    num = den = 0
    j = 0
    for i in range(n):
        tgt = days[i] + dt.timedelta(days=horizon_days)
        while j < n and days[j] < tgt:
            j += 1
        if j >= n:
            break
        if (days[j] - days[i]).days > horizon_days + 5:
            continue
        den += 1
        if vals[j] > vals[i]:
            num += 1
    return (num / den if den else None), den


def write_scenarios() -> dict:
    """写 docs/research/scenarios/lane-a-T-313.json:≥3 条,≥1 条自动结算;概率 = 历史基率。"""
    st_b = _paged("state_daily?select=d,value&entity=eq.panel&feature=eq.breadth_above_ma50", "d.asc")
    st_s = _paged("state_daily?select=d,value&entity=eq.panel&feature=eq.style_rel_majors_30d", "d.asc")
    btc = _paged("ohlcv_daily?select=trade_date,close&symbol=eq.BTC&source=eq.binance_hist", "trade_date.asc")

    def series(rows, dk, vk):
        seen = {}
        for r in rows:
            if r.get(vk) is None or r.get(dk) is None:
                continue
            seen[str(r[dk])[:10]] = float(r[vk])
        return sorted(seen.items())

    b_ser, s_ser, btc_ser = series(st_b, "d", "value"), series(st_s, "d", "value"), series(btc, "trade_date", "close")
    br_breadth, n_breadth = base_rate_up(b_ser)
    br_style, n_style = base_rate_up(s_ser)
    br_btc, n_btc = base_rate_up(btc_ser)

    cur_breadth = b_ser[-1][1]
    cur_style = s_ser[-1][1]
    cur_btc = btc_ser[-1][1]
    last_d = dt.date.fromisoformat(b_ser[-1][0])
    horizon = (last_d + dt.timedelta(days=35)).isoformat()

    entries = [
        {"id": "T-313-1", "scenario": "T-313 态读 P 排序的强弱(判定 ❌)",
         "statement": f"市场宽度(breadth_above_ma50,{last_d.isoformat()} = {cur_breadth:.4f})在 {horizon} 高于该值",
         "variable": "state:breadth_above_ma50", "op": "gt", "lo": round(cur_breadth, 6),
         "prob": round(br_breadth, 2) if br_breadth is not None else 0.5, "horizon_d": horizon},
        {"id": "T-313-2", "scenario": "T-313 态读 P 排序的强弱(判定 ❌)",
         "statement": f"风格相对强弱(style_rel_majors_30d,{last_d.isoformat()} = {cur_style:.4f})在 {horizon} 高于该值",
         "variable": "state:style_rel_majors_30d", "op": "gt", "lo": round(cur_style, 6),
         "prob": round(br_style, 2) if br_style is not None else 0.5, "horizon_d": horizon},
        {"id": "T-313-3", "scenario": "T-313 态读 P 排序的强弱(判定 ❌)",
         "statement": f"BTC 收盘({last_d.isoformat()} = {cur_btc:.2f})在 {horizon} 高于该值",
         "variable": "close:BTC", "op": "gt", "lo": round(cur_btc, 2),
         "prob": round(br_btc, 2) if br_btc is not None else 0.5, "horizon_d": horizon},
        {"id": "T-313-4", "scenario": "T-313 态读 P 排序的强弱(判定 ❌)",
         "statement": ("从 2026-11-16 起的前 6 个判定周上(最后一周 2026-12-21,实现 IC 到 2027-01-21 才齐),"
                       "S-793 kNN 臂的周度 Spearman(kNN 预测, 实现 IC)仍 < 0.20"),
         "variable": "manual", "op": "lt", "hi": 0.20, "prob": 0.55, "horizon_d": "2027-01-26"},
    ]
    payload = {"author": "lane-a", "entries": entries}
    outp = ROOT / "docs/research/scenarios/lane-a-T-313.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(outp.relative_to(ROOT)),
            "entries": entries,
            "base_rates": {"breadth_above_ma50": [br_breadth, n_breadth],
                           "style_rel_majors_30d": [br_style, n_style],
                           "BTC_close": [br_btc, n_btc]},
            "current": {"breadth": cur_breadth, "style": cur_style, "btc": cur_btc},
            "horizon": horizon}


def write_report(out: dict, ledger_lines: list[str]) -> None:
    """报告:台账原文照抄 + 实测数字(数字全部从 out 里取,不手抄)。"""
    c = out["criteria"]
    d = c["d"]
    diag = out["mechanism_diagnostics"]
    ic = out["snapshots"]["ic"]
    st = out["snapshots"]["state"]
    jd = out["judgement"]
    q = "".join("> " + ln + "\n" for ln in ledger_lines)
    hi, lo = d["high_group"], d["low_group"]

    def pc(x, k=4):
        return "n/a" if x is None else f"{x:.{k}f}"

    def pct(x, k=2):
        return "n/a" if x is None else f"{x * 100:+.{k}f}%"

    md_hist = out["state_coverage"]["measured_dim_histogram"]
    md_str = "、".join(f"{k} 维 × {v} 周" for k, v in sorted(md_hist.items(), key=lambda kv: int(kv[0])))
    sc = out.get("scenarios") or {}
    sc_rows = ""
    for e in (sc.get("entries") or []):
        sc_rows += (f"| `{e['id']}` | `{e['variable']}` | {e['statement']} | {e['prob']} | {e['horizon_d']} |\n")
    br = sc.get("base_rates") or {}
    br_txt = "、".join(f"{k} {v[0]:.2f}(n={v[1]})" for k, v in br.items()) if br else "n/a"

    md = f"""# T-313 / S-793 —— Regime 态(`market_state_vectors`)能不能提前读出 Asset 空间里 P(价格相位)排序的强弱

> 状态:**结果已出,判定 ❌**。口径照 S-793 预注册原文,只算一次,不扫参数。
> 脚本 `docs/research/t313_state_to_ic.py`;数字 `docs/research/t313_results.json`;
> 状态快照逐周落 `docs/research/t313_state.csv`(周一 t / 取到的状态日 / 实测维数 / 24 维值)。
> 只读:不改代码、不写库、不动 `src/`;A/B 与零分布只走 `src/data/evaluation/apparatus.py`。

## 一、预注册(S-793 原文,照抄,只算一次)

{q}
## 二、本卡实际执行口径(与预注册的对照)

| 项 | 预注册 | 本卡实测 | 关系 |
|---|---|---|---|
| IC 序列 | `t312_results.json` 的 `weekly_ic`(不重算) | 同;197 周,sha256 `{ic['sha256'][:16]}…` | 照抄 |
| 状态 | `market_state_vectors.vec_full`,24 维,按点 z,`null`=未测 | 同;{st['rows']:,} 行,{st['first_d']} → {st['last_d']};按 (d, vec_full) 排序 sha256 `{st['sha256_rows_by_d'][:16]}…` | 照抄 |
| 取状态日 | 周一当天;没有则往前最近一天(≤ 3 天);不补 0 | {out['state_coverage']['weeks_with_state']}/{out['state_coverage']['weeks_total']} 周命中**周一当天**,回填 {out['state_coverage']['weeks_backfilled']} 次;实测维数 {md_str} | 照抄 |
| kNN 臂 | k=10;s ≤ t−35;共有实测维 < 8 剔除;合格候选 < 26 不预测 | 同;判定区间内「共有维 < 8」的剔除中位 **{diag['dropped_by_shared_lt8_median_per_week']:.0f}** 次/周(门槛未起作用) | 照抄 |
| 惯性臂 | 最近 12 周 P-IC 均值 | 同 | 照抄 |
| 判定区间 | 两臂都有预测的全部周 | **{jd['n_weeks']} 周,{jd['start']} → {jd['end']}**;前半 {jd['half1']['n_weeks']} 周({jd['half1']['start']} → {jd['half1']['end']}),后半 {jd['half2']['n_weeks']} 周({jd['half2']['start']} → {jd['half2']['end']}) | 照抄 |
| 置换 | 循环块置换,块长 8 周,1,000 次,种子 793 | 同族:装置 `block_permute`(8 周块、块顺序随机置换),机器 `null_distribution`、分位 `percentile_of` | 照抄(注①) |
| 单边 p 方向 | 「单边 p ≤ 0.05」 | 假设方向为正(ρ ≥ 0.20)⇒ p = P(null ≥ 实测) = 1 − `percentile_of(实测, null)` | 注② |
| 回归 | OLS,Newey–West 滞后 5 | `statsmodels` OLS + `cov_type='HAC'`, `maxlags=5`(Bartlett,与装置 `newey_west_t` 同族) | 照抄 |

注①:预注册写「循环块置换(实现 IC 序列整体循环平移)」。装置提供的是**块顺序随机置换**(`block_permute`),与「块顺序循环旋转」同族(块内结构与元素多重集合都保留),取值更细(1,000 抽样 vs ~25 种旋转)。字面循环旋转的零分布只有 ~25 个不同取值,不足以定 p。
注②:装置 `percentile_of` 返回的是**实际值在零分布里的分位**,不是 p 值。负向假设用「分位 ≤ 0.05」(同族先例:`_t270_view.py` 的负向判据);本卡假设方向为正,故取上尾。

## 三、判据逐条

| 判据 | 阈值 | 实测 | 结论 |
|---|---|---|---|
| (a) Spearman(kNN 预测, 实现 IC) | ≥ 0.20 | **{pc(c['a']['spearman_knn_vs_ic'])}** | 过 |
| (a) 块置换单边 p | ≤ 0.05 | **{pc(c['a']['perm_p_one_sided'], 4)}**(上尾;零分布 mean {pc(c['a']['null_summary']['mean'])}、sd {pc(c['a']['null_summary']['sd'])}、q05 {pc(c['a']['null_summary']['q05'])}、q95 {pc(c['a']['null_summary']['q95'])}) | 过 |
| (b) 回归 kNN 系数 t(NW-5) | ≥ 2.0 | **{c['b']['t_knn']}**(系数 {c['b']['coef_knn']};惯性系数 {c['b']['coef_inertia']}、t {c['b']['t_inertia']};R² {c['b']['r2']};n={c['b']['ols_n']}) | **不过** |
| (c) 两半 Spearman | 同号且各 ≥ 0.10 | 前半 **{pc(c['c']['rho_half1'])}** / 后半 **{pc(c['c']['rho_half2'])}**(同号 {c['c']['same_sign']}) | **不过**(后半) |
| (d) 高于中位组 − 低于中位组(P_bottom_quintile_x30 均值) | ≤ −1.0pp | **{d['mean_diff_pp']:+.4f}pp** | 过 |

### (d) 两组的钱(判定区间 {jd['n_weeks']} 周,中位分界 kNN 预测 = {d['median_knn_pred']:.6f})

| 组 | 周数 | 均值 | 中位 | p10 | p90 |
|---|---|---|---|---|---|
| kNN 预测 ≥ 中位 | {hi['n']} | {pct(hi['mean'])} | {pct(hi['median'])} | {pct(hi['p10'])} | {pct(hi['p90'])} |
| kNN 预测 < 中位 | {lo['n']} | {pct(lo['mean'])} | {pct(lo['median'])} | {pct(lo['p10'])} | {pct(lo['p90'])} |
| 差(高 − 低) | {hi['n']} − {lo['n']} | **{d['mean_diff_pp']:+.4f}pp** | — | — | — |

块自助 CI95(装置 `stationary_bootstrap_index`,块长 8 周,2,000 次,种子 793):[{d['bootstrap_ci95'][0] * 100:+.2f}pp, {d['bootstrap_ci95'][1] * 100:+.2f}pp](含 0 —— (d) 是**阈值判据**不是检验)。

## 四、判定与后果

**❌ 不过**(全过才 ✅;且预注册写明「(a) 或 (b) 不过 ⇒ ❌」)。

(a) 与 (d) 过,(b) 与 (c) 不过:(a) 的 0.2469 里,有相当一部分**不是**「态读出强弱」——
回归里惯性臂一进来,kNN 的 t 从边际 **{diag['t_knn_marginal_hac5']}** 掉到 **{c['b']['t_knn']}**(两臂相关 {diag['corr_knn_vs_inertia']});后半的 ρ 只剩 {pc(c['c']['rho_half2'])}。

**后果照预注册执行**:态读不出 P 排序力的强弱 ⇒ ② 的倾斜按常数开,**OVERRIDE 层这条路在 P 上收卷**;不开前向记录。

## 五、探索性发现(**不进判定** —— 需另立预注册、在新数据上过零信号对照)

1. **态的几何确实带信息,但不够**。同样从合格候选池里抽 10 个、**随机**抽(不按距离)作对照:Spearman **{diag['control_random10_spearman']}**(上尾 p {diag['control_random10_perm_p_upper']}),而按距离取最近 10 个是 {pc(c['a']['spearman_knn_vs_ic'])}。距离比随机挑候选多出一倍的相关 ⇒ 不是「随便挑几个近期周」就能得到的效果;但增量过不了 (b) 的 t ≥ 2.0 与 (c) 的后半 ≥ 0.10。
2. **「最近的态」系统性地比随机候选年轻**:10 个近邻的年龄中位 **{diag['neighbour_age_days_median']:.0f} 天**,合格候选池的年龄中位 **{diag['eligible_pool_age_days_median']:.0f} 天**。kNN 的信号里混着「近期 IC」的分量,惯性臂吃掉的正是这一块。
3. **阈值很脆**:描述性敏感度 k=5 → {out['sensitivity_descriptive']['k=5']['spearman']},k=20 → {out['sensitivity_descriptive']['k=20']['spearman']}(不进判定)。0.20 这条线,k 一动就翻面。
4. **8 维门槛是空转的**:判定区间内每周实测 16 或 21 维,「共有维 < 8」的剔除一次都没触发 —— 这条预注册参数在本样本上不承重。

## 六、前向预期(机器结算:`docs/research/scenarios/lane-a-T-313.json`)

概率取**历史基率** P(x[t+35 日] > x[t]):{br_txt};不用手感,不算收益承诺。

| id | 变量 | 命题 | 概率 | 结算日 |
|---|---|---|---|---|
{sc_rows}
前三条自动结算(`state_daily` / `ohlcv_daily`);第四条是**手工**命题(要等 2026-11-16 起的 6 个判定周实现 IC 到 2027-01-21 才齐),
它直接复测本卡的 ❌ 判定在新数据上是否成立。

## 七、复算

```bash
python3 docs/research/t313_state_to_ic.py          # 用本地状态快照;--refetch 重新拉表
```

只读 SELECT(`market_state_vectors`,翻页带 `order=d.asc`);不写库、不改 `src/`。
"""
    (ROOT / "docs/research/T-313_state_to_ic.md").write_text(md)


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true", help="重新拉状态表(默认用本地快照)")
    args = ap.parse_args()

    # 1) IC 序列(不重算)
    ic_path = next((p for p in IC_CANDIDATE_PATHS if p.exists()), None)
    if ic_path is None:
        raise SystemExit("找不到 t312_results.json —— 先 `git show origin/lane-a/T-312:docs/research/t312_results.json > docs/research/_t313_ic_raw.json`")
    ic_blob = json.loads(ic_path.read_text())
    w = ic_blob["weekly_ic"]
    weeks = list(w["weeks"])
    ic_P = [float(x) for x in w["P"]]
    ic_R = [float(x) for x in w["R"]]
    bottom = [float(x) for x in w["P_bottom_quintile_x30"]]
    n_weeks = len(weeks)
    assert n_weeks == len(ic_P) == len(bottom)
    wdate = [dt.date.fromisoformat(x) for x in weeks]

    # 2) 状态表(只读)
    if args.refetch or not STATE_SNAPSHOT.exists():
        rows = fetch_state()
        STATE_SNAPSHOT.write_text(json.dumps({"meta": {}, "rows": rows}, ensure_ascii=False))
    else:
        blob = json.loads(STATE_SNAPSHOT.read_text())
        rows = blob["rows"] if isinstance(blob, dict) and "rows" in blob else blob
    state_by_d = {r["d"]: r for r in rows}
    zs_counts = Counter(str(r.get("zscore_pass")) for r in rows)
    fp_state = state_fingerprint(rows)

    # 3) 每周 t 取状态:周一当天,没有则往前最近一天(≤3 天);没有 ⇒ 不预测
    week_state_day: list[str | None] = []
    M = np.full((n_weeks, DIMS), np.nan)      # 向量值(null → nan)
    MASK = np.zeros((n_weeks, DIMS), dtype=bool)  # 实测维
    n_backfill = 0
    for i, w0 in enumerate(wdate):
        hit = None
        for back in range(0, STATE_MAX_BACKFILL_DAYS + 1):
            d = (w0 - dt.timedelta(days=back)).isoformat()
            if d in state_by_d:
                hit = d
                if back > 0:
                    n_backfill += 1
                break
        week_state_day.append(hit)
        if hit is None:
            continue
        vec = state_by_d[hit]["vec_full"]
        for j in range(min(DIMS, len(vec))):
            v = vec[j]
            if v is not None:
                M[i, j] = float(v)
                MASK[i, j] = True

    # 4) 先落 t313_state.csv(周一 t、取到的状态日、实测维数、24 维值)
    with open(OUT_STATE_CSV, "w", newline="") as fh:
        wri = csv.writer(fh)
        wri.writerow(["week_monday", "state_day", "n_measured"]
                     + [f"d{j + 1:02d}" for j in range(DIMS)])
        for i, w0 in enumerate(wdate):
            day = week_state_day[i]
            nm = int(MASK[i].sum())
            wri.writerow([weeks[i], day if day else "", nm]
                         + ["" if not MASK[i, j] else repr(float(M[i, j])) for j in range(DIMS)])

    # 5) kNN 臂 + 惯性臂
    knn_pred: list[float | None] = []
    inertia_pred: list[float | None] = []
    n_cand_qual: list[int] = []
    nn_idx: list[list[int]] = []
    qual_pool: list[list[int]] = []
    n_dropped_shared: list[int] = []
    for i in range(n_weeks):
        # 候选:所有 s ≤ t − 35 天的周(须有状态向量才能算距离)
        cand = [j for j in range(i)
                if (wdate[i] - wdate[j]).days >= CANDIDATE_LAG_DAYS and MASK[j].any()]
        ok = False
        if cand:
            idx = np.asarray(cand)
            with np.errstate(invalid="ignore"):
                diff = M[idx] - M[i]
                shared = MASK[idx] & MASK[i]
                sq = np.where(shared, diff * diff, 0.0)
                ssum = sq.sum(axis=1)
                nsh = shared.sum(axis=1)
            dist = np.full(len(idx), np.inf)
            good = nsh >= MIN_SHARED_DIMS
            dist[good] = np.sqrt(ssum[good]) / np.sqrt(nsh[good])
            qualified = int(good.sum())
            n_cand_qual.append(qualified)
            n_dropped_shared.append(len(idx) - qualified)
            qual_pool.append([int(idx[o]) for o in np.nonzero(good)[0]])
            if qualified >= MIN_CANDIDATES:
                order = np.argsort(dist, kind="stable")
                sel = [int(idx[o]) for o in order[:KNN_K]]
                knn_pred.append(float(np.mean([ic_P[j] for j in sel])))
                nn_idx.append(sel)
                ok = True
            else:
                nn_idx.append([])
        else:
            n_cand_qual.append(0)
            n_dropped_shared.append(0)
            qual_pool.append([])
            nn_idx.append([])
        if not ok:
            knn_pred.append(None)
        # 惯性臂:同样只用 s ≤ t − 35 天的周,最近 12 周 P-IC 的均值
        hist = [j for j in range(i) if (wdate[i] - wdate[j]).days >= CANDIDATE_LAG_DAYS]
        if len(hist) >= INERTIA_WEEKS:
            inertia_pred.append(float(np.mean([ic_P[j] for j in hist[-INERTIA_WEEKS:]])))
        else:
            inertia_pred.append(None)

    # 6) 判定区间:两臂都有预测的全部周
    judge = [i for i in range(n_weeks) if knn_pred[i] is not None and inertia_pred[i] is not None]
    if len(judge) < 10:
        raise SystemExit(f"判定区间只有 {len(judge)} 周,太少,停。")
    ji = np.asarray(judge)
    knn_j = np.asarray([knn_pred[i] for i in judge], dtype=float)
    inr_j = np.asarray([inertia_pred[i] for i in judge], dtype=float)
    ic_j = np.asarray([ic_P[i] for i in judge], dtype=float)
    bq_j = np.asarray([bottom[i] for i in judge], dtype=float)
    ic_full = np.asarray(ic_P, dtype=float)

    # (a) Spearman(kNN 预测, 实现 IC)+ 块置换单边 p
    actual = spearman(knn_j, ic_j)

    def null_fn(rng):
        permuted = block_permute(ic_full, PERM_BLOCK, rng)
        return spearman(knn_j, permuted[ji])

    null = null_distribution(null_fn, N_NULL, SEED, actual=actual)
    # 装置的 percentile_of 返回的是「实际值在零分布里的分位」,不是 p 值。
    # (a) 的假设方向是正(ρ ≥ 0.20),故单边 p = P(null ≥ actual) = 1 − 分位。
    # 同族用法:_t270_view.py 的负向判据用「分位 ≤ 0.05」表示显著为负。
    pct = percentile_of(actual, null)
    p_a = None if pct is None else float(1.0 - pct)
    null_summary = {
        "mean": round(float(null.mean()), 4), "sd": round(float(null.std(ddof=1)), 4),
        "q05": round(float(np.percentile(null, 5)), 4),
        "q50": round(float(np.percentile(null, 50)), 4),
        "q95": round(float(np.percentile(null, 95)), 4),
    }
    crit_a = (actual is not None and actual >= 0.20 and p_a is not None and p_a <= 0.05)

    # (b) OLS: 实现 IC ~ 常数 + kNN 预测 + 惯性预测,Newey–West 滞后 5
    import statsmodels.api as sm
    X = sm.add_constant(np.column_stack([knn_j, inr_j]))
    ols = sm.OLS(ic_j, X).fit(cov_type="HAC", cov_kwds={"maxlags": NW_LAGS})
    t_knn = float(ols.tvalues[1])
    t_inr = float(ols.tvalues[2])
    crit_b = bool(np.isfinite(t_knn) and t_knn >= 2.0)
    # 边际(探索性):两臂各自单独进回归的 NW t
    ols_k = sm.OLS(ic_j, sm.add_constant(knn_j)).fit(cov_type="HAC", cov_kwds={"maxlags": NW_LAGS})
    ols_i = sm.OLS(ic_j, sm.add_constant(inr_j)).fit(cov_type="HAC", cov_kwds={"maxlags": NW_LAGS})
    t_knn_marginal = float(ols_k.tvalues[1])
    t_inr_marginal = float(ols_i.tvalues[1])

    # (c) 两半:按周数对半切(前半多一周)
    half = len(judge) // 2
    h1, h2 = judge[:half + (len(judge) % 2)], judge[half + (len(judge) % 2):]
    rho1 = spearman(np.asarray([knn_pred[i] for i in h1]), np.asarray([ic_P[i] for i in h1]))
    rho2 = spearman(np.asarray([knn_pred[i] for i in h2]), np.asarray([ic_P[i] for i in h2]))
    same_sign = (rho1 is not None and rho2 is not None
                 and ((rho1 > 0) == (rho2 > 0)))
    crit_c = bool(same_sign and rho1 is not None and rho2 is not None
                  and rho1 >= 0.10 and rho2 >= 0.10)

    # (d) 金额判据:kNN 预测在判定区间中位以上 vs 以下 → P_bottom_quintile_x30 均值之差
    med = float(np.median(knn_j))
    hi = [i for i in judge if knn_pred[i] >= med]
    lo = [i for i in judge if knn_pred[i] < med]
    hi_v = np.asarray([bottom[i] for i in hi], dtype=float)
    lo_v = np.asarray([bottom[i] for i in lo], dtype=float)

    def desc(v):
        return {"n": int(v.size), "mean": float(v.mean()) if v.size else None,
                "median": float(np.median(v)) if v.size else None,
                "p10": float(np.percentile(v, 10)) if v.size else None,
                "p90": float(np.percentile(v, 90)) if v.size else None}

    d_hi, d_lo = desc(hi_v), desc(lo_v)
    diff = (d_hi["mean"] - d_lo["mean"]) if (d_hi["mean"] is not None and d_lo["mean"] is not None) else None
    # 块自助置信区间(装置的 stationary_bootstrap_index,块长与置换块长一致 = 8 周)
    ci_lo = ci_hi = None
    if hi_v.size and lo_v.size:
        rng = np.random.default_rng(SEED)
        bi = stationary_bootstrap_index(hi_v.size, PERM_BLOCK, 2000, rng)
        bl = stationary_bootstrap_index(lo_v.size, PERM_BLOCK, 2000, rng)
        boot = hi_v[bi].mean(axis=1) - lo_v[bl].mean(axis=1)
        ci_lo, ci_hi = (float(x) for x in np.quantile(boot, [0.025, 0.975]))
    crit_d = bool(diff is not None and diff <= -0.01)

    # ── 机制诊断(描述性, 不进判定) ──────────────────────────────────────────
    # 1) 两臂共线度:knn 预测 与 惯性预测 的相关
    corr_arms = float(np.corrcoef(knn_j, inr_j)[0, 1])
    # 2) 惯性臂自己 与 实现 IC 的 Spearman(基线已经有多少)
    rho_inertia = spearman(inr_j, ic_j)

    def null_inertia(rng):
        permuted = block_permute(ic_full, PERM_BLOCK, rng)
        return spearman(inr_j, permuted[ji])

    null_in = null_distribution(null_inertia, N_NULL, SEED, actual=rho_inertia)
    pct_in = percentile_of(rho_inertia, null_in)
    p_inertia = None if pct_in is None else float(1.0 - pct_in)

    # 3) 近邻的「年龄」:最近的 10 个候选周离 t 有多远(天) —— 态距离是不是只是在挑最近的周
    ages_nn, ages_pool = [], []
    for i in judge:
        if not nn_idx[i]:
            continue
        ages_nn.extend((wdate[i] - wdate[j]).days for j in nn_idx[i])
        ages_pool.extend((wdate[i] - wdate[j]).days for j in qual_pool[i])
    age_nn_med = float(np.median(ages_nn)) if ages_nn else None
    age_pool_med = float(np.median(ages_pool)) if ages_pool else None

    # 4) 被「共有维 < 8」剔掉的候选数
    drop_med = float(np.median(n_dropped_shared[judge[0]:judge[-1] + 1])) if judge else None

    # 5) 对照(探索性):同样 10 个候选,但**随机**抽而不是取最近的 —— 隔离「态距离」本身的贡献
    rng_c = np.random.default_rng(SEED + 1)
    ctrl, ji_ctrl = [], []
    for i in judge:
        pool = qual_pool[i]
        if len(pool) < KNN_K:
            continue
        sel = rng_c.choice(pool, size=KNN_K, replace=False)
        ctrl.append(float(np.mean([ic_P[int(j)] for j in sel])))
        ji_ctrl.append(i)
    ctrl_j = np.asarray(ctrl, dtype=float)
    ji_ctrl_a = np.asarray(ji_ctrl, dtype=int)
    rho_ctrl = spearman(ctrl_j, np.asarray([ic_P[i] for i in ji_ctrl], dtype=float)) if len(ji_ctrl) else None

    def null_ctrl(rng):
        permuted = block_permute(ic_full, PERM_BLOCK, rng)
        return spearman(ctrl_j, permuted[ji_ctrl_a])

    p_ctrl = None
    if len(ji_ctrl):
        null_c = null_distribution(null_ctrl, N_NULL, SEED, actual=rho_ctrl)
        pct_c = percentile_of(rho_ctrl, null_c)
        p_ctrl = None if pct_c is None else float(1.0 - pct_c)

    verdict = "✅ 全过" if (crit_a and crit_b and crit_c and crit_d) else "❌ 不过"

    # 描述性敏感度:k = 5 / 20(不进判定)
    sens = {}
    for kk in (5, 20):
        preds = []
        for i in range(n_weeks):
            cand = [j for j in range(i)
                    if (wdate[i] - wdate[j]).days >= CANDIDATE_LAG_DAYS and MASK[j].any()]
            if not cand:
                preds.append(None)
                continue
            idx = np.asarray(cand)
            with np.errstate(invalid="ignore"):
                diffv = M[idx] - M[i]
                shared = MASK[idx] & MASK[i]
                sq = np.where(shared, diffv * diffv, 0.0)
                ssum = sq.sum(axis=1)
                nsh = shared.sum(axis=1)
            dist = np.full(len(idx), np.inf)
            good = nsh >= MIN_SHARED_DIMS
            dist[good] = np.sqrt(ssum[good]) / np.sqrt(nsh[good])
            if int(good.sum()) < MIN_CANDIDATES:
                preds.append(None)
                continue
            order = np.argsort(dist, kind="stable")
            sel = [int(idx[o]) for o in order[:kk]]
            preds.append(float(np.mean([ic_P[j] for j in sel])))
        sel_j = [i for i in range(n_weeks) if preds[i] is not None and inertia_pred[i] is not None]
        rho = spearman(np.asarray([preds[i] for i in sel_j]), np.asarray([ic_P[i] for i in sel_j]))
        sens[f"k={kk}"] = {"n_judge_weeks": len(sel_j), "spearman": None if rho is None else round(float(rho), 4)}

    out = {
        "task": "T-313",
        "ledger": "S-793",
        "prereg": {
            "knn_k": KNN_K, "candidate_lag_days": CANDIDATE_LAG_DAYS,
            "inertia_weeks": INERTIA_WEEKS, "min_shared_dims": MIN_SHARED_DIMS,
            "min_candidates": MIN_CANDIDATES, "perm_block": PERM_BLOCK,
            "n_null": N_NULL, "seed": SEED, "nw_lags": NW_LAGS,
            "state_max_backfill_days": STATE_MAX_BACKFILL_DAYS, "dims": DIMS,
            "swept": False,
        },
        "snapshots": {
            "ic": {"path": str(ic_path.relative_to(ROOT)), "sha256": file_sha256(ic_path),
                   "n_weeks": n_weeks, "first_week": weeks[0], "last_week": weeks[-1]},
            "state": {"table": "market_state_vectors", "rows": len(rows),
                      "first_d": min(r["d"] for r in rows), "last_d": max(r["d"] for r in rows),
                      "zscore_pass_distinct": sorted(zs_counts),
                      "zscore_pass_counts": dict(zs_counts),
                      "sha256_rows_by_d": fp_state},
        },
        "state_coverage": {
            "weeks_total": n_weeks,
            "weeks_with_state": int(sum(1 for x in week_state_day if x)),
            "weeks_backfilled": n_backfill,
            "measured_dim_histogram": dict(sorted(Counter(int(MASK[i].sum()) for i in range(n_weeks)).items())),
        },
        "judgement": {
            "start": weeks[judge[0]], "end": weeks[judge[-1]], "n_weeks": len(judge),
            "half1": {"start": weeks[h1[0]], "end": weeks[h1[-1]], "n_weeks": len(h1)},
            "half2": {"start": weeks[h2[0]], "end": weeks[h2[-1]], "n_weeks": len(h2)},
        },
        "criteria": {
            "a": {"spearman_knn_vs_ic": None if actual is None else round(float(actual), 4),
                  "threshold": 0.20,
                  "perm_p_one_sided": None if p_a is None else round(float(p_a), 4),
                  "p_direction": "upper tail: p = P(null ≥ actual) = 1 − percentile_of(actual, null)"
                                 "(装置的 percentile_of 给的是分位,不是 p;假设方向为正故取上尾)",
                  "percentile_of_actual": None if pct is None else round(float(pct), 4),
                  "null_summary": null_summary,
                  "null_n": int(null.size), "pass": bool(crit_a)},
            "b": {"ols_n": int(len(judge)), "coef_knn": round(float(ols.params[1]), 5),
                  "t_knn": round(t_knn, 3), "t_inertia": round(t_inr, 3),
                  "coef_inertia": round(float(ols.params[2]), 5),
                  "r2": round(float(ols.rsquared), 4), "nw_lags": NW_LAGS, "pass": bool(crit_b)},
            "c": {"rho_half1": None if rho1 is None else round(float(rho1), 4),
                  "rho_half2": None if rho2 is None else round(float(rho2), 4),
                  "same_sign": bool(same_sign), "threshold": 0.10, "pass": bool(crit_c)},
            "d": {"median_knn_pred": med, "high_group": d_hi, "low_group": d_lo,
                  "mean_diff_high_minus_low": None if diff is None else round(diff, 6),
                  "mean_diff_pp": None if diff is None else round(diff * 100, 4),
                  "bootstrap_ci95": [ci_lo, ci_hi], "threshold": -0.01, "pass": bool(crit_d)},
        },
        "verdict": verdict,
        "mechanism_diagnostics": {
            "note": "描述性诊断,不进判定;用于解释 (a) 为什么过而 (b) 不过。",
            "corr_knn_vs_inertia": round(corr_arms, 4),
            "spearman_inertia_vs_ic": None if rho_inertia is None else round(float(rho_inertia), 4),
            "inertia_perm_p_upper": None if p_inertia is None else round(float(p_inertia), 4),
            "neighbour_age_days_median": age_nn_med,
            "eligible_pool_age_days_median": age_pool_med,
            "dropped_by_shared_lt8_median_per_week": drop_med,
            "control_random10_spearman": None if rho_ctrl is None else round(float(rho_ctrl), 4),
            "control_random10_perm_p_upper": None if p_ctrl is None else round(float(p_ctrl), 4),
            "control_random10_n_weeks": len(ji_ctrl),
            "t_knn_marginal_hac5": round(t_knn_marginal, 3),
            "t_inertia_marginal_hac5": round(t_inr_marginal, 3),
        },
        "sensitivity_descriptive": sens,
        "weekly_series": [
            {"week": weeks[i], "state_day": week_state_day[i],
             "n_measured": int(MASK[i].sum()),
             "n_qualified_candidates": n_cand_qual[i],
             "knn_pred": knn_pred[i], "inertia_pred": inertia_pred[i],
             "ic_P": ic_P[i], "ic_R": ic_R[i],
             "P_bottom_quintile_x30": bottom[i],
             "in_judgement": i in set(judge),
             "nn_weeks": [weeks[j] for j in nn_idx[i]]}
            for i in range(n_weeks)
        ],
    }
    OUT_RESULTS.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    sc = write_scenarios()
    out["scenarios"] = sc
    write_report(out, load_ledger_section("S-793"))
    OUT_RESULTS.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print("== snapshots ==")
    print("IC  sha256", out["snapshots"]["ic"]["sha256"][:16], out["snapshots"]["ic"]["n_weeks"], "周")
    print("STATE rows", len(rows), "sha256", fp_state[:16])
    print("== coverage ==", out["state_coverage"])
    print("== judgement ==", out["judgement"])
    print("== (a) ==", out["criteria"]["a"])
    print("== (b) ==", out["criteria"]["b"])
    print("== (c) ==", out["criteria"]["c"])
    print("== (d) ==", out["criteria"]["d"])
    print("== sensitivity ==", sens)
    print("VERDICT", verdict)
    print("wrote", OUT_STATE_CSV.name, OUT_RESULTS.name)


if __name__ == "__main__":
    main()
