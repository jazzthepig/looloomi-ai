#!/usr/bin/env python3
"""T-314 · lane-c · S-793 盲复算。

只读三个来源(没有一个是我自己写的口径):
  1) REFUTATION_LEDGER 的 S-793 原文(唯一口径来源);
  2) IC 序列:docs/research/t312_results.json 的 weekly_ic(lane-a/T-312;main 上还没有);
  3) 状态:market_state_vectors.vec_full(PostgREST 只读 SELECT,翻页带 order=d.asc)。

写:docs/research/t314_state.csv(逐周表)、docs/research/t314_results.json。
报告 docs/research/T-314_blind_replication.md 手写(口径歧义一节在最前)。

用法:
    python3 docs/research/t314_blind.py --stage fetch   # 只抓状态快照 + 打印形状
    python3 docs/research/t314_blind.py --stage run     # 抓(或用缓存)+ 算 (a)-(d)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.data.evaluation.apparatus import (  # noqa: E402
    block_permute,
    null_distribution,
    percentile_of,
)
from src.data.evaluation.joint_model import spearman  # noqa: E402

DOCS = ROOT / "docs" / "research"
CACHE = DOCS / "t314_states_cache.json"
STATE_CSV = DOCS / "t314_state.csv"
RESULTS = DOCS / "t314_results.json"

# ── S-793 写死的参数(原文逐条对应) ────────────────────────────────────────
K = 10                 # kNN 取最近 k = 10
K_DESC = (5, 20)       # 描述性敏感度(不进判定)
EMBARGO_DAYS = 35      # 候选周 s ≤ t − 35 天
COMMON_MIN = 8         # 共有实测维 < 8 的候选剔除
MIN_ELIGIBLE = 26      # 合格候选 < 26 周则该周不预测
INERTIA_N = 12         # 惯性臂:最近 12 周 P-IC 均值
LOOKBACK_DAYS = 3      # 周一当天没有状态 ⇒ 往前最近一天(≤ 3 天)
BLOCK = 8              # 块置换块长(周)
N_NULL = 1000          # 1,000 次
SEED = 793             # 种子 793
NW_LAGS = 5            # Newey–West 滞后 5


# ── 只读抓取 ──────────────────────────────────────────────────────────────
def fetch_states() -> tuple[list[dict], str]:
    """market_state_vectors 全表(d, vec_full, zscore_pass),order=d.asc 翻页,每页 ≤ 1000 行。"""
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/market_state_vectors"
    key = os.environ["SUPABASE_KEY"]
    hdr = {"apikey": key, "Authorization": "Bearer " + key, "Prefer": "count=exact"}
    rows: list[dict] = []
    total = None
    offset, page = 0, 1000
    while True:
        q = urllib.parse.urlencode({
            "select": "d,vec_full,zscore_pass", "order": "d.asc",
            "limit": str(page), "offset": str(offset),
        })
        req = urllib.request.Request(url + "?" + q, headers=hdr)
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
            cr = r.headers.get("Content-Range") or ""
        chunk = json.loads(body)
        if total is None and "/" in cr:
            total = int(cr.split("/")[-1])
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    if total is not None and len(rows) != total:
        raise RuntimeError(f"抓取行数 {len(rows)} != Content-Range 总数 {total}")
    return rows, (total if total is not None else len(rows))


def fetch_ic() -> tuple[bytes, str, dict]:
    """t312_results.json:本地有就用本地,否则从 lane-a/T-312 拿(git show 读,不落盘)。"""
    local = DOCS / "t312_results.json"
    if local.is_file():
        raw = local.read_bytes()
        src = "docs/research/t312_results.json(本地)"
    else:
        raw = subprocess.run(
            ["git", "show", "origin/lane-a/T-312:docs/research/t312_results.json"],
            cwd=ROOT, capture_output=True, check=True).stdout
        src = "git show origin/lane-a/T-312:docs/research/t312_results.json"
    return raw, src, json.loads(raw)


# ── 快照指纹 ──────────────────────────────────────────────────────────────
def state_fingerprint(rows: list[dict]) -> dict:
    """行数、zscore_pass、按 (d, vec_full) 排序后的 sha256。"""
    pairs = sorted(((r["d"], r["vec_full"]) for r in rows),
                   key=lambda p: (p[0], json.dumps(p[1], ensure_ascii=False)))
    canon = json.dumps([[d, v] for d, v in pairs], ensure_ascii=False, separators=(",", ":"))
    tags = sorted({r.get("zscore_pass") for r in rows}, key=lambda x: (x is None, str(x)))
    return {
        "rows": len(rows),
        "zscore_pass": tags,
        "zscore_pass_n_distinct": len(tags),
        "sha256_sorted_d_vecfull": hashlib.sha256(canon.encode("utf-8")).hexdigest(),
        "canonical_form": "json.dumps([[d, vec_full], ...] 按 (d, json(vec_full)) 升序, ensure_ascii=False, separators=(',',':')) 的 UTF-8 字节",
        "d_min": pairs[0][0] if pairs else None,
        "d_max": pairs[-1][0] if pairs else None,
    }


# ── 状态向量取用 ──────────────────────────────────────────────────────────
def pick_state_day(d_by_date: dict[str, list], week: str) -> tuple[str | None, int | None]:
    """周 t 当天(周一)没有 ⇒ 往前最近一天(≤ 3 天);再没有 ⇒ None(该周不预测)。"""
    base = date.fromisoformat(week)
    for k in range(0, LOOKBACK_DAYS + 1):
        d = (base - timedelta(days=k)).isoformat()
        if d in d_by_date:
            return d, k
    return None, None


def to_vec(v) -> np.ndarray:
    arr = np.full(24, np.nan)
    for i, x in enumerate(v or []):
        if x is not None:
            arr[i] = float(x)
    return arr


# ── kNN / 惯性两臂 ────────────────────────────────────────────────────────
def predict_week(t: int, weeks: list[str], P: list[float], vec: dict[str, np.ndarray],
                 eligible_mode: str = "ge8"):
    """返回 (knn_pred, inertia_pred, 诊断)。

    eligible_mode="ge8"  :「合格候选」= 过时间闸 + 有状态 + 共有维 ≥ 8(默认读法)
    eligible_mode="time" :「合格候选」= 只过时间闸(26 周门槛按时间候选数算)—— 敏感度用
    """
    dt = date.fromisoformat(weeks[t])
    vt = vec.get(weeks[t])
    cand_idx = [s for s in range(len(weeks))
                if date.fromisoformat(weeks[s]) + timedelta(days=EMBARGO_DAYS) <= dt]
    n_time = len(cand_idx)
    # 惯性臂:只要 IC,不需要状态;最近 12 周
    if cand_idx:
        recent = sorted(cand_idx, key=lambda s: weeks[s])[-INERTIA_N:]
        inertia = float(np.mean([P[s] for s in recent]))
    else:
        inertia = None
    diag = {"n_cand_time": n_time, "n_cand_with_state": 0, "n_eligible_ge8": 0}
    if vt is None:
        return None, inertia, diag
    scored = []
    for s in cand_idx:
        vs = vec.get(weeks[s])
        if vs is None:
            continue
        diag["n_cand_with_state"] += 1
        common = ~(np.isnan(vt) | np.isnan(vs))
        n_common = int(common.sum())
        if n_common < COMMON_MIN:
            continue
        dist = float(np.sqrt(np.sum((vt[common] - vs[common]) ** 2) / n_common))
        scored.append((dist, weeks[s], s, n_common))
    diag["n_eligible_ge8"] = len(scored)
    if scored:
        ncs = sorted(x[3] for x in scored)
        diag["n_common_min"] = ncs[0]
        diag["n_common_median"] = ncs[len(ncs) // 2]
        diag["n_common_max"] = ncs[-1]
        ds = sorted(x[0] for x in scored)
        diag["d10_d11_gap"] = float(ds[K] - ds[K - 1]) if len(ds) > K else None
        diag["n_exact_ties_in_topK"] = int(len(ds[:K]) - len(set(np.round(ds[:K], 12))))
    if eligible_mode == "time":
        if n_time < MIN_ELIGIBLE:
            return None, inertia, diag
    elif len(scored) < MIN_ELIGIBLE:
        return None, inertia, diag
    if len(scored) < K:
        return None, inertia, diag
    scored.sort(key=lambda x: (x[0], x[1]))          # 距离升序,平手按日期升序
    knn = float(np.mean([P[x[2]] for x in scored[:K]]))
    diag["nn_distances"] = [round(x[0], 6) for x in scored[:K]]
    return knn, inertia, diag


def predict_week_k(t: int, weeks: list[str], P: list[float], vec: dict[str, np.ndarray], k: int):
    """描述性敏感度用:k 可变版。"""
    dt = date.fromisoformat(weeks[t])
    vt = vec.get(weeks[t])
    if vt is None:
        return None
    scored = []
    for s in range(len(weeks)):
        if date.fromisoformat(weeks[s]) + timedelta(days=EMBARGO_DAYS) > dt:
            continue
        vs = vec.get(weeks[s])
        if vs is None:
            continue
        common = ~(np.isnan(vt) | np.isnan(vs))
        if int(common.sum()) < COMMON_MIN:
            continue
        d = float(np.sqrt(np.sum((vt[common] - vs[common]) ** 2) / common.sum()))
        scored.append((d, weeks[s], s))
    if len(scored) < MIN_ELIGIBLE:
        return None
    scored.sort(key=lambda x: (x[0], x[1]))
    return float(np.mean([P[x[2]] for x in scored[:k]]))


# ── 判据 ──────────────────────────────────────────────────────────────────
def spearman_or_none(a, b):
    return spearman(a, b)


def permutation_p_observed(knn: np.ndarray, ic: np.ndarray) -> dict:
    """(a) 的循环块置换零分布。三档读法都算,判定用 apparatus 档。"""
    obs = spearman(knn, ic)
    out = {"observed_spearman": obs}

    def fn_block(rng):
        return spearman(knn, block_permute(ic, BLOCK, rng))

    try:
        null = null_distribution(fn_block, N_NULL, SEED, actual=obs)
        out["P1_apparatus_block_permute"] = {
            "method": f"apparatus.block_permute(block={BLOCK}), null_distribution(n={N_NULL}, seed={SEED})",
            "p_one_sided_upper": float(np.mean(np.asarray(null) >= obs)),
            "p_one_sided_upper_midrank": float((np.sum(np.asarray(null) >= obs)
                                                + 0.5 * np.sum(np.asarray(null) == obs)) / len(null)),
            "percentile_of": percentile_of(obs, null),
            "null_mean": float(np.mean(null)), "null_sd": float(np.std(null)),
            "null_max": float(np.max(null)), "null_min": float(np.min(null)),
            "n_null": int(len(null)),
        }
    except Exception as e:  # NoOpNull 等
        out["P1_apparatus_block_permute"] = {"error": f"{type(e).__name__}: {e}"}

    # 读法二:块粒度的整体循环移位(把序列切成 BLOCK 周一块,整块循环转)
    def fn_circ_block(rng):
        blocks = [ic[i:i + BLOCK] for i in range(0, len(ic), BLOCK)]
        nb = len(blocks)
        rot = int(rng.integers(0, nb))
        rolled = blocks[rot:] + blocks[:rot]
        return spearman(knn, np.concatenate(rolled))

    rng2 = np.random.default_rng(SEED)
    null2 = np.array([fn_circ_block(rng2) for _ in range(N_NULL)], dtype=float)
    out["P2_circular_block_rotation"] = {
        "method": f"整段切成 {BLOCK} 周一块,块序循环移位,{N_NULL} 次,seed={SEED}",
        "p_one_sided_upper": float(np.mean(null2 >= obs)),
        "null_mean": float(np.mean(null2)), "null_sd": float(np.std(null2)),
        "null_max": float(np.max(null2)), "n_distinct_null": int(len(set(np.round(null2, 12)))),
    }

    # 读法三:整段序列任意偏移的循环移位(字面「整体循环平移」)
    rng3 = np.random.default_rng(SEED)
    null3 = np.array([spearman(knn, np.roll(ic, int(rng3.integers(0, len(ic)))))
                      for _ in range(N_NULL)], dtype=float)
    out["P3_whole_series_rotation"] = {
        "method": f"整段序列任意偏移循环移位,{N_NULL} 次,seed={SEED}",
        "p_one_sided_upper": float(np.mean(null3 >= obs)),
        "null_mean": float(np.mean(null3)), "null_sd": float(np.std(null3)),
        "null_max": float(np.max(null3)), "n_distinct_null": int(len(set(np.round(null3, 12)))),
    }
    return out


def nw_ols(y: np.ndarray, X: np.ndarray, lags: int = NW_LAGS) -> dict:
    """OLS + Newey–West(Bartlett,与 apparatus.newey_west_t 同约定:无小样本修正)。自算,与 statsmodels 对齐用。

    Ω̂ = Γ0 + Σ_l w_l (Γ_l + Γ_l'),Γ_l = Σ_{t>l} x_t u_t u_{t-l} x_{t-l}';V = (X'X)^-1 Ω̂ (X'X)^-1。
    标量情形退化到 apparatus.newey_west_t:var = (Ω0 + 2Σ w_l Ω_l)/n,se = sqrt(var/n)。
    """
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    beta = XtXi @ (X.T @ y)
    u = y - X @ beta
    Om = (X * (u ** 2)[:, None]).T @ X             # Γ0
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = (X[lag:] * u[lag:, None]).T @ (X[:-lag] * u[:-lag, None])   # Γ_l
        Om = Om + w * (G + G.T)
    V = XtXi @ Om @ XtXi
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    t = np.where(se > 0, beta / se, np.nan)
    return {"beta": beta.tolist(), "se": se.tolist(), "t": t.tolist(), "n": int(n), "k": int(k)}


def ols_hac(y: np.ndarray, X: np.ndarray, lags: int = NW_LAGS) -> dict:
    import statsmodels.api as sm
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": False})
    res_c = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True})
    return {
        "coef": res.params.tolist(), "se": res.bse.tolist(), "t": res.tvalues.tolist(),
        "p": res.pvalues.tolist(),
        "t_with_small_sample_correction": res_c.tvalues.tolist(),
        "rsquared": float(res.rsquared),
    }


def summarize_group(x) -> dict:
    a = np.asarray(x, dtype=float)
    return {"n": int(a.size), "mean": float(np.mean(a)), "median": float(np.median(a)),
            "p10": float(np.percentile(a, 10)), "p90": float(np.percentile(a, 90))}


def judge_rows(per_week: list[dict]) -> dict:
    """把逐周表判一遍:(a) Spearman + 块置换 p;(b) OLS+NW 的 kNN 系数 t;(c) 两半 Spearman;(d) 金额判据。"""
    window = [r for r in per_week if r["knn"] is not None and r["inertia"] is not None]
    W = len(window)
    knn_arr = np.array([r["knn"] for r in window])
    iner_arr = np.array([r["inertia"] for r in window])
    ic_arr = np.array([r["P"] for r in window])
    pb_arr = np.array([r["Pb"] for r in window])

    a_res = permutation_p_observed(knn_arr, ic_arr)
    p1 = a_res.get("P1_apparatus_block_permute", {}).get("p_one_sided_upper", 1.0)
    a_pass = (a_res["observed_spearman"] is not None and a_res["observed_spearman"] >= 0.20
              and p1 <= 0.05)

    X = np.column_stack([np.ones(W), knn_arr, iner_arr])
    b_hand = nw_ols(ic_arr, X)
    b_sm = ols_hac(ic_arr, X)
    b_pass = bool(b_sm["t"][1] >= 2.0)

    h = W // 2
    split = h + (W % 2)
    first, second = window[:split], window[split:]
    s1 = spearman([r["knn"] for r in first], [r["P"] for r in first])
    s2 = spearman([r["knn"] for r in second], [r["P"] for r in second])
    c_pass = bool(s1 is not None and s2 is not None and s1 * s2 > 0 and s1 >= 0.10 and s2 >= 0.10)

    med = float(np.median(knn_arr))
    above = [i for i in range(W) if knn_arr[i] > med]
    below = [i for i in range(W) if knn_arr[i] <= med]
    g_above = summarize_group(pb_arr[above])
    g_below = summarize_group(pb_arr[below])
    diff = g_above["mean"] - g_below["mean"]
    d_pass = bool(diff <= -0.010)

    def _pc(a, b):
        return float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else None

    return {
        "n_judgment_window": W,
        "window_first": window[0]["week"] if window else None,
        "window_last": window[-1]["week"] if window else None,
        "a": {**a_res, "pass": a_pass},
        "b": {"hand_rolled_nw": b_hand, "statsmodels_hac": b_sm,
              "knn_coef_t": b_sm["t"][1], "knn_coef": b_sm["coef"][1],
              "nw_t_max_abs_diff_hand_vs_statsmodels":
                  float(np.max(np.abs(np.array(b_hand["t"]) - np.array(b_sm["t"])))),
              "pass": b_pass},
        "c": {"spearman_first_half": s1, "spearman_second_half": s2,
              "n_first": len(first), "n_second": len(second),
              "first_window": [first[0]["week"], first[-1]["week"]] if first else None,
              "second_window": [second[0]["week"], second[-1]["week"]] if second else None,
              "pass": c_pass},
        "d": {"median_knn_pred": med, "above": g_above, "below": g_below,
              "mean_diff_frac": diff, "mean_diff_pp": diff * 100.0,
              "split_rule": "A = knn_pred > 中位;B = knn_pred ≤ 中位",
              "pass": d_pass},
        "diagnostics": {
            "pearson_knn_vs_realized_ic": _pc(knn_arr, ic_arr),
            "pearson_inertia_vs_realized_ic": _pc(iner_arr, ic_arr),
            "pearson_knn_vs_inertia": _pc(knn_arr, iner_arr),
            "spearman_inertia_vs_realized_ic": spearman(iner_arr, ic_arr),
            "knn_pred_mean": float(np.mean(knn_arr)),
            "knn_pred_sd": float(np.std(knn_arr)),
            "realized_ic_mean": float(np.mean(ic_arr)),
            "realized_ic_sd": float(np.std(ic_arr)),
            "realized_ic_first": float(ic_arr[0]), "realized_ic_last": float(ic_arr[-1]),
        },
    }


# ── 主流程 ────────────────────────────────────────────────────────────────
def build(weeks, P, Pb, vec, state_day, state_lag):
    rows = []
    for t in range(len(weeks)):
        knn, inertia, diag = predict_week(t, weeks, P, vec)
        rows.append({"t": t, "week": weeks[t], "knn": knn, "inertia": inertia,
                     "P": P[t], "Pb": Pb[t], **diag})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="run", choices=["fetch", "run"])
    a = ap.parse_args()

    raw, src, j = fetch_ic()
    w = j["weekly_ic"]
    weeks = list(w["weeks"])
    P = [float(x) for x in w["P"]]
    Pb = [float(x) for x in w["P_bottom_quintile_x30"]]
    ic_fingerprint = {
        "source": src,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "ledger_snapshot_sha256_prefix": "bf52601c",
        "ledger_snapshot_matches_file_cache_sha256":
            str(j.get("snapshot_fingerprint", {}).get("cache_sha256", "")).startswith("bf52601c"),
        "declared_cache_sha256": j.get("snapshot_fingerprint", {}).get("cache_sha256"),
        "n_weeks": len(weeks), "first": weeks[0], "last": weeks[-1],
    }
    if a.stage == "fetch":
        print(json.dumps({"ic": ic_fingerprint}, ensure_ascii=False, indent=2))
        return 0

    if CACHE.is_file():
        rows = json.loads(CACHE.read_text())["rows"]
        fp = json.loads(CACHE.read_text())["fingerprint"]
    else:
        rows, total = fetch_states()
        fp = state_fingerprint(rows)
        CACHE.write_text(json.dumps({"fingerprint": fp, "rows": rows}, ensure_ascii=False),
                         encoding="utf-8")
    print("状态快照:", json.dumps(fp, ensure_ascii=False))

    d_by_date: dict[str, list] = {}
    for r in rows:
        d_by_date.setdefault(r["d"], []).append(r)
    dupes = {d: len(v) for d, v in d_by_date.items() if len(v) > 1}
    if dupes:
        print("重复日期(取最后一行 computed_at?没有 computed_at → 取最后一条):", list(dupes.items())[:5])

    vec: dict[str, np.ndarray] = {}
    state_day: dict[str, str] = {}
    state_lag: dict[str, int] = {}
    no_state = []
    for wk in weeks:
        d, lag = pick_state_day(d_by_date, wk)
        if d is None:
            no_state.append(wk)
            continue
        r = d_by_date[d][-1]
        vec[wk] = to_vec(r["vec_full"])
        state_day[wk] = d
        state_lag[wk] = lag

    per_week = build(weeks, P, Pb, vec, state_day, state_lag)
    primary = judge_rows(per_week)
    window = [r for r in per_week if r["knn"] is not None and r["inertia"] is not None]
    W = len(window)

    # 敏感度 S1:「合格候选 < 26 周」按**时间闸**算(26 周门槛不含 8 维筛)—— 口径歧义 #2 的端到端影响
    per_week_time = []
    for t in range(len(weeks)):
        knn_t, iner_t, diag_t = predict_week(t, weeks, P, vec, eligible_mode="time")
        per_week_time.append({"t": t, "week": weeks[t], "knn": knn_t, "inertia": iner_t,
                              "P": P[t], "Pb": Pb[t], **diag_t})
    s1_judge = judge_rows(per_week_time)

    # 描述性: k = 5 / 20
    desc_k = {}
    for kk in K_DESC:
        preds = [predict_week_k(t, weeks, P, vec, kk) for t in range(len(weeks))]
        vals = [(preds[t], P[t]) for t in range(len(weeks)) if preds[t] is not None]
        desc_k[str(kk)] = {"n_weeks": len(vals),
                           "spearman": spearman([x[0] for x in vals], [x[1] for x in vals])}

    # ── 落 t314_state.csv(逐周表,判定区间标记)
    with STATE_CSV.open("w", newline="", encoding="utf-8") as fh:
        cw = csv.writer(fh)
        cw.writerow(["week", "state_d", "state_lag_days", "measured_dims", "n_cand_time",
                     "n_cand_with_state", "n_eligible_ge8", "knn_pred", "inertia_pred",
                     "realized_P_ic", "P_bottom_quintile_x30", "in_judgment_window"])
        in_win = {r["week"] for r in window}
        for r in per_week:
            md = ("" if r["week"] not in vec
                  else int(np.sum(~np.isnan(vec[r["week"]]))))
            cw.writerow([r["week"], state_day.get(r["week"], ""), state_lag.get(r["week"], ""),
                         md, r["n_cand_time"], r["n_cand_with_state"], r["n_eligible_ge8"],
                         "" if r["knn"] is None else f"{r['knn']:.10f}",
                         "" if r["inertia"] is None else f"{r['inertia']:.10f}",
                         f"{r['P']:.10f}", f"{r['Pb']:.10f}",
                         1 if r["week"] in in_win else 0])

    lag_hist = {}
    for r in window:
        lag_hist[str(state_lag.get(r["week"]))] = lag_hist.get(str(state_lag.get(r["week"])), 0) + 1
    out = {
        "task": "T-314", "lane": "lane-c", "ledger": "S-793",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {"ic": ic_fingerprint, "state": fp},
        "params": {"k": K, "embargo_days": EMBARGO_DAYS, "common_min": COMMON_MIN,
                   "min_eligible": MIN_ELIGIBLE, "inertia_n": INERTIA_N,
                   "lookback_days": LOOKBACK_DAYS, "block": BLOCK, "n_null": N_NULL,
                   "seed": SEED, "nw_lags": NW_LAGS},
        "coverage": {"n_weeks_total": len(weeks), "n_weeks_no_state": len(no_state),
                     "weeks_no_state": no_state,
                     "n_judgment_window": W,
                     "window_first": window[0]["week"] if window else None,
                     "window_last": window[-1]["week"] if window else None,
                     "n_eligible_min_over_window": min((r["n_eligible_ge8"] for r in window), default=None),
                     "n_eligible_max_over_window": max((r["n_eligible_ge8"] for r in window), default=None),
                     "n_cand_time_min_over_window": min((r["n_cand_time"] for r in window), default=None),
                     "state_lag_hist_over_window": lag_hist,
                     "all_ic_weeks_are_monday":
                         all(date.fromisoformat(x).weekday() == 0 for x in weeks),
                     "n_common_min_over_window": min((r.get("n_common_min", 0) for r in window), default=None),
                     "n_common_median_over_window": sorted(
                         (r.get("n_common_median", 0) for r in window))[len(window) // 2] if window else None,
                     "n_weeks_with_exact_tie_in_top10": sum(
                         1 for r in window if r.get("n_exact_ties_in_topK", 0) > 0),
                     "d10_d11_gap_min_over_window": min(
                         (r["d10_d11_gap"] for r in window if r.get("d10_d11_gap") is not None),
                         default=None),
                     },
        "a": primary["a"], "b": primary["b"], "c": primary["c"], "d": primary["d"],
        "diagnostics": primary["diagnostics"],
        "verdict": {"a": primary["a"]["pass"], "b": primary["b"]["pass"],
                    "c": primary["c"]["pass"], "d": primary["d"]["pass"],
                    "all_pass": all([primary["a"]["pass"], primary["b"]["pass"],
                                     primary["c"]["pass"], primary["d"]["pass"]]),
                    "ledger_consequence": "全过 ⇒ 开前向记录;(a) 或 (b) 不过 ⇒ ❌"},
        "descriptive_k_sensitivity": desc_k,
        "sensitivity_S1_eligible_by_time_only": {
            "note": "「合格候选 < 26 周」的 26 周门槛只按时间闸算(8 维筛只影响取哪 10 个最近)",
            "n_judgment_window": s1_judge["n_judgment_window"],
            "window_first": s1_judge["window_first"], "window_last": s1_judge["window_last"],
            "a_spearman": s1_judge["a"]["observed_spearman"],
            "a_p_P1": s1_judge["a"].get("P1_apparatus_block_permute", {}).get("p_one_sided_upper"),
            "a_p_P2": s1_judge["a"].get("P2_circular_block_rotation", {}).get("p_one_sided_upper"),
            "a_p_P3": s1_judge["a"].get("P3_whole_series_rotation", {}).get("p_one_sided_upper"),
            "b_knn_coef_t": s1_judge["b"]["knn_coef_t"],
            "c_first": s1_judge["c"]["spearman_first_half"],
            "c_second": s1_judge["c"]["spearman_second_half"],
            "d_mean_diff_pp": s1_judge["d"]["mean_diff_pp"],
            "verdict": {k: s1_judge[k]["pass"] for k in ("a", "b", "c", "d")},
        },
        "per_week": per_week,
    }
    RESULTS.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("coverage", "verdict", "diagnostics",
                                          "descriptive_k_sensitivity",
                                          "sensitivity_S1_eligible_by_time_only")},
                     ensure_ascii=False, indent=2)[:3000])
    for k in ("a", "b", "c", "d"):
        print(k, "pass =", out[k]["pass"])
    print("ALL =", out["verdict"]["all_pass"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
