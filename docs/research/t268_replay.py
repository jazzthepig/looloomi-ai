"""T-268 / S-745 时点重放:融合状态近邻臂 vs 原近邻臂 vs 基率臂(BTC 之后 30 天三档)。

**判据照台账写死**(REFUTATION_LEDGER S-745,2026-11-06 14:10 UTC):

- 检验:2022-06-01 → 2026-10-05 每天,三臂各自只用 ≤ d 的信息给出 30 天 BTC 三档
  (跌超 10% / ±10% / 涨超 10%)概率 —— 直接调用生产函数
  (`fused_knn.rates` / `exposure_decision.knn_rates` + `market_state_vectors` /
  `exposure_decision.base_rates`)。
- 指标:三档 Brier 的日均;技能 = 1 − Brier / 无条件频率的 Brier。
- 判据(全部满足才 ✅):(a) 融合臂 Brier < 原近邻臂且 < 基率臂;
  (b) 日度 Brier 差(融合 − 原近邻)的配对块自助(块长 60、2,000 次、种子 745)95% 区间上沿 < 0;
  (c) 两段(2022-06 → 2024-06 / 2024-07 →)融合臂都 ≤ 原近邻臂;(d) 融合臂技能 > 0。
- 副(只报不判):块长 30 / 90;K = 100 / 250;按 S-737 六状态拆 Brier。

**时点纪律(acceptance ①)**:对每个重放日 d,三臂拿到的 `fwd` 一律只含**结果已经出完**的历史日
(x + 30 天 ≤ d)。这样近邻臂不会用到「d 之后才有结果」的历史日,基率臂的无条件频率也只含 ≤ d 的信息。
价源:perp_bv_daily(BTC 永续,主口径);ohlcv_daily(eq.BTC,副项稳健性)。
只算、不改代码、不入库。

用法:`python3 docs/research/t268_replay.py`(cwd = 仓库根;需 SUPABASE_URL / SUPABASE_KEY)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from src.data.execution import exposure_decision as ED  # noqa: E402
from src.data.evaluation import apparatus as AP  # noqa: E402
from src.data.state import fused_knn  # noqa: E402

# ── 预注册常量(S-745;不改) ─────────────────────────────────────────────────
START, END = "2022-06-01", "2026-10-05"
SPLIT = "2024-07-01"          # (c) 两段:2022-06 → 2024-06 / 2024-07 →
BLOCK, N_BOOT, SEED = 60, 2000, 745
CATS = ("down", "flat", "up")
HORIZON = 30

# S-737 六状态(T-257 冻结规格:13 特征、训练期 2021-03-01 → 2023-12-31、k=6、种子 737、n_init 20)
S737_FEATURES = ["mom_20", "mom_60", "mom_200", "dist_200", "vol_30", "vratio_30_180",
                 "breadth_above_ma50", "funding_7d_ann_binance",
                 "taker_buy_share_30d", "stable_supply_30d", "cycle:deterioration",
                 "dvol:btc_pct_1y", "macro:vix"]
S737_TRAIN = ("2021-03-01", "2023-12-31")
S737_K, S737_SEED, S737_NINIT = 6, 737, 20

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY(脚本只用进程环境变量,不读 .env)")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
BASE = URL.rstrip("/") + "/rest/v1/"
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t268_cache")
OUT = Path(__file__).resolve().parent


# ── 数据层:分页读 + 本地缓存(每页 1000,一律带 order) ──────────────────────
def pull(table: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    offset, total = 0, -1
    while True:
        q = dict(params)
        q["limit"] = "1000"
        q["offset"] = str(offset)
        url = f"{BASE}{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={**HDR, "Prefer": "count=exact"})
        with urllib.request.urlopen(req, timeout=300) as r:
            body = json.loads(r.read().decode() or "[]")
            cr = r.headers.get("Content-Range") or ""
        rows.extend(body)
        if "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except ValueError:
                total = -1
        offset += len(body)
        if not body or total < 0 or offset >= total:
            break
    return rows


def load(tag: str, table: str, params: dict) -> list[dict]:
    p = CACHE / f"{tag}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {tag}: {len(rows)} 行")
        return rows
    rows = pull(table, params)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {tag}: {len(rows)} 行")
    return rows


# ── 三档 Brier(只走 apparatus.brier) ─────────────────────────────────────────
def brier3_series(probs_list: list[dict], ys: list[str]) -> float:
    """三档 Brier = 三个 one-vs-rest 二元 Brier 的平均(= (1/3)Σ_k (p_k − y_k)²)。"""
    per_cat = []
    for c in CATS:
        p = [float(pr[c]) for pr in probs_list]
        y = [1.0 if lab == c else 0.0 for lab in ys]
        per_cat.append(AP.brier(p, y))
    return float(np.mean(per_cat))


def skill(b: float, base: float) -> float:
    return 1.0 - b / base if base else float("nan")


# ── 主重放 ──────────────────────────────────────────────────────────────────
def replay(closes: dict[str, float], msv: dict[str, list[float]], fused: dict[str, list],
           buckets: dict[str, str], days: list[str], ks: tuple[int, ...]) -> dict:
    """对每个重放日 d 跑三臂,返回逐日记录。

    时点纪律(acceptance ①):
    - `fwd_d` = {x : x + 30 ≤ d} —— 结果已经出完的历史日(三臂共用的无条件频率口径)。
    - 原近邻臂另用 `fwd_d31` = {x ≤ d − 31}:近邻里不出现「最近 31 天」(与融合臂的 EXCLUDE_DAYS 同一口径),
      向量取 d 之前 3 天内最近的一天(market_state_vectors 逐日齐全,实际滞后 0 天)。
    - 生产函数 `exposure_decision.knn_rates` 本身没有 31 天排除开关,所以排除是在传进去的 fwd 上做的;
      副作用是它的收缩目标(无条件频率)也少一天 —— 与融合臂差 1/1650,报告里写明。
    """
    fwd = ED.forward_returns(closes, HORIZON)
    fwd_keys = sorted(fwd)
    msv_days = sorted(msv)
    recs: list[dict] = []
    for d in days:
        if d not in fwd:
            continue
        cut = (dt.date.fromisoformat(d) - dt.timedelta(days=HORIZON)).isoformat()
        cut31 = (dt.date.fromisoformat(d) - dt.timedelta(days=31)).isoformat()
        fwd_d = {x: fwd[x] for x in fwd_keys if x <= cut}          # 时点:结果已出完的历史日
        fwd_d31 = {x: fwd[x] for x in fwd_keys if x <= cut31}        # 再排除最近 31 天
        if len(fwd_d) < 60:
            continue
        today_vec = msv.get(d)
        if not today_vec:
            continue
        vec_day = max((x for x in msv_days if x <= d
                       and (dt.date.fromisoformat(d) - dt.date.fromisoformat(x)).days <= 3), default=None)
        if vec_day is None:
            continue
        rec: dict = {"d": d, "y": ED.outcome_bin(fwd[d]), "vec_day": vec_day,
                     "vec_lag": (dt.date.fromisoformat(d) - dt.date.fromisoformat(vec_day)).days}
        # 融合臂(生产函数;内部自己排除最近 31 天)
        for k in ks:
            r = fused_knn.rates(fused, fwd_d, d, k=k)
            rec[f"fused{k}"] = r.get("probs")
            rec[f"fused{k}_why"] = r.get("why")
            rec[f"fused{k}_vecd"] = r.get("vector_d")
        # 原近邻臂(生产函数;近邻 ≤ d−31,向量取 3 天内最近)
        for k in ks:
            probs, n, segs = ED.knn_rates(msv, fwd_d31, msv[vec_day], k=k)
            rec[f"orig{k}"] = probs
            rec[f"orig{k}_n"] = n
            rec[f"orig{k}_segs"] = segs
        # 原近邻臂(生产口径对照:不额外排除 31 天,近邻 ≤ d−30)
        for k in ks:
            probs, n, segs = ED.knn_rates(msv, fwd_d, msv[vec_day], k=k)
            rec[f"origp{k}"] = probs
            rec[f"origp{k}_n"] = n
        # 基率臂(生产函数;forward_returns 只取 < d)
        bprobs, bn, used = ED.base_rates(buckets, fwd_d, buckets.get(d, "unknown"))
        rec["base"] = bprobs
        rec["base_n"] = bn
        rec["base_used"] = used
        # 时点无条件频率(技能分母)
        cnt = {c: 0 for c in CATS}
        for r_ in fwd_d.values():
            cnt[ED.outcome_bin(r_)] += 1
        tot = sum(cnt.values()) or 1
        rec["clim"] = {c: cnt[c] / tot for c in CATS}
        rec["clim_n"] = tot
        recs.append(rec)
    return {"recs": recs, "fwd": fwd}


def arm_briers(recs: list[dict], key: str) -> dict:
    """在「三臂都可算」的公共样本上算每臂 Brier / 技能。"""
    common = [r for r in recs if r.get(key) and r.get("orig150") and r.get("base")]
    ys = [r["y"] for r in common]
    out: dict = {"n_common": len(common)}
    if not common:
        return out
    b_fused = brier3_series([r[key] for r in common], ys)
    b_orig = brier3_series([r["orig150"] for r in common], ys)
    b_base = brier3_series([r["base"] for r in common], ys)
    b_clim = brier3_series([r["clim"] for r in common], ys)
    out.update({
        "brier_fused": b_fused, "brier_orig": b_orig, "brier_base": b_base, "brier_clim_pit": b_clim,
        "skill_fused": skill(b_fused, b_clim), "skill_orig": skill(b_orig, b_clim),
        "skill_base": skill(b_base, b_clim),
        "a_fused_lt_orig": b_fused < b_orig, "a_fused_lt_base": b_fused < b_base,
        "d_skill_fused_gt_0": skill(b_fused, b_clim) > 0,
    })
    return out


def paired_bootstrap(diff: np.ndarray, block: int, seed: int = SEED, n_boot: int = N_BOOT) -> dict:
    """配对块自助:重抽同一批下标(配对保持),给出日均差的 95% 区间。"""
    n = len(diff)
    if n < 2 * block:
        return {"n": n, "why": f"样本 {n} 天 < 2×块长 {block}"}
    rng = np.random.default_rng(seed)
    idx = AP.stationary_bootstrap_index(n, block, n_boot, rng)
    boot = diff[idx].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return {"n": n, "block": block, "n_boot": n_boot, "seed": seed,
            "mean_diff": float(diff.mean()), "ci95": (float(lo), float(hi)),
            "p_mean_le_0": float((boot <= 0).mean())}


def perm_null(fused_series: np.ndarray, orig_series: np.ndarray, block: int,
              actual: float, seed: int = SEED, n_boot: int = N_BOOT) -> dict:
    """块置换零分布:打乱融合臂的块顺序后与原近邻臂配对 —— 破坏配对、保持块内结构。"""
    def fn(rng):
        return float(np.mean(AP.block_permute(fused_series, block, rng) - orig_series))
    try:
        null = AP.null_distribution(fn, n_boot, seed, actual=actual)
    except AP.NoOpNull as e:
        return {"why": str(e)}
    return {"n_boot": n_boot, "seed": seed, "block": block,
            "p_one_sided": AP.percentile_of(actual, null),
            "null_mean": float(null.mean()), "null_p05": float(np.quantile(null, 0.05)),
            "null_p95": float(np.quantile(null, 0.95))}


def main() -> None:
    print("== 拉数据 ==")
    fm_rows = load("fm", "feature_matrix_daily", {"select": "d,f", "order": "d.asc"})
    msv_rows = load("msv", "market_state_vectors", {"select": "d,vec", "order": "d.asc"})
    perp_rows = load("perp_btc", "perp_bv_daily", {"select": "d,c", "symbol": "eq.BTC", "order": "d.asc"})
    spot_rows = load("spot_btc", "ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC",
                                                 "source": "eq.binance_hist", "order": "trade_date.asc"})
    feats = ",".join(ED.FEATURES)
    sd_rows = load("state_daily", "state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                                  "feature": f"in.({feats})", "order": "d.asc,feature.asc"})

    closes_perp = {str(r["d"])[:10]: float(r["c"]) for r in perp_rows if r.get("c") is not None}
    closes_spot = {str(r["trade_date"])[:10]: float(r["close"]) for r in spot_rows if r.get("close") is not None}
    msv = {str(r["d"])[:10]: ED.parse_vec(r.get("vec")) for r in msv_rows}
    msv = {d: v for d, v in msv.items() if v}
    states: dict[str, dict] = {}
    for r in sd_rows:
        states.setdefault(str(r["d"])[:10], {})[r["feature"]] = r.get("value")
    buckets = {d: ED.bucket_of(st) for d, st in states.items()}
    fused = fused_knn.pit_vectors(fm_rows)
    print(f"  fm {len(fm_rows)} 天 | msv {len(msv)} 天 | perp {len(closes_perp)} 天 "
          f"({min(closes_perp)}→{max(closes_perp)}) | spot {len(closes_spot)} 天 | buckets {len(buckets)} 天")
    print(f"  融合向量 {len(fused)} 天 | 24 维向量维度样本 {sorted({len(v) for v in msv.values()})}")

    days = [d for d in sorted(closes_perp) if START <= d <= END]
    print(f"== 主重放 {days[0]} → {days[-1]}({len(days)} 天)==")
    rep = replay(closes_perp, msv, fused, buckets, days, ks=(100, 150, 250))
    recs = rep["recs"]
    print(f"  可算日 {len(recs)}")
    res: dict = {"card": "T-268", "prereg": "S-745",
                 "spec": {"start": START, "end": END, "split": SPLIT, "block": BLOCK, "n_boot": N_BOOT,
                          "seed": SEED, "horizon_d": HORIZON, "bands": [-0.10, 0.10],
                          "brier_def": "三档 one-vs-rest 二元 Brier 的平均(每档用 apparatus.brier)",
                          "pit_rule": "每天 d 只用 x + 30 ≤ d 的历史日(含无条件频率)",
                          "close_source_primary": "perp_bv_daily symbol=eq.BTC",
                          "close_source_secondary": "ohlcv_daily symbol=eq.BTC source=eq.binance_hist",
                          "fused_ks": [100, 150, 250], "orig_ks": [100, 150, 250]},
                 "data": {"fm_rows": len(fm_rows), "msv_rows": len(msv_rows), "msv_days": len(msv),
                          "perp_days": len(closes_perp), "spot_days": len(closes_spot),
                          "state_daily_rows": len(sd_rows), "bucket_days": len(buckets),
                          "fused_vector_days": len(fused),
                          "perp_range": [min(closes_perp), max(closes_perp)],
                          "msv_zero_vec_rows": sum(1 for v in msv.values() if not any(v))},
                 "primary": {}, "secondary": {}, "diagnostics": {}}

    # ── 主口径(K = 150)──
    prim = arm_briers(recs, "fused150")
    common = [r for r in recs if r.get("fused150") and r.get("orig150") and r.get("base")]
    ys = [r["y"] for r in common]
    dates = [r["d"] for r in common]
    prim["brier_by_cat"] = {
        arm: {c: AP.brier([float(r[key if arm != "orig" else "orig150"][c]) for r in common],
                           [1.0 if lab == c else 0.0 for lab in ys]) for c in CATS}
        for arm, key in (("fused", "fused150"), ("orig", "orig150"), ("base", "base"), ("clim", "clim"))}
    # (b) 配对块自助:日度 Brier 差(融合 − 原近邻)
    diff = np.array([brier3_series([r["fused150"]], [r["y"]]) - brier3_series([r["orig150"]], [r["y"]])
                     for r in common])
    prim["b_paired_block_bootstrap"] = paired_bootstrap(diff, BLOCK)
    # 附:块置换零分布 —— 结构上必然退化(置换保均值 ⇒ mean(permuted − orig) ≡ mean(fused − orig)),
    # apparatus 的 NoOpNull 守卫生成器把它挡下来了。留着这条是为了记录「为什么 (b) 只能靠自助区间判」。
    prim["b_permutation_null"] = perm_null(
        np.array([brier3_series([r["fused150"]], [r["y"]]) for r in common]),
        np.array([brier3_series([r["orig150"]], [r["y"]]) for r in common]), BLOCK, float(diff.mean()))
    # (c) 两段
    segs = {}
    for label, mask in AP.windows(dates, [START, SPLIT]):
        idxs = np.flatnonzero(mask)
        if idxs.size == 0:
            continue
        f_b = float(np.mean([brier3_series([common[i]["fused150"]], [common[i]["y"]]) for i in idxs]))
        o_b = float(np.mean([brier3_series([common[i]["orig150"]], [common[i]["y"]]) for i in idxs]))
        b_b = float(np.mean([brier3_series([common[i]["base"]], [common[i]["y"]]) for i in idxs]))
        c_b = float(np.mean([brier3_series([common[i]["clim"]], [common[i]["y"]]) for i in idxs]))
        segs[label] = {"n": int(idxs.size), "brier_fused": f_b, "brier_orig": o_b, "brier_base": b_b,
                       "brier_clim": c_b, "fused_le_orig": f_b <= o_b,
                       "skill_fused": skill(f_b, c_b), "skill_orig": skill(o_b, c_b)}
    prim["c_segments"] = segs
    prim["c_all_segments_fused_le_orig"] = all(v["fused_le_orig"] for v in segs.values())
    res["primary"] = prim
    print(f"  Brier 融合 {prim['brier_fused']:.5f} | 原近邻 {prim['brier_orig']:.5f} | "
          f"基率 {prim['brier_base']:.5f} | 时点无条件 {prim['brier_clim_pit']:.5f}")
    print(f"  技能 融合 {prim['skill_fused']:+.4f} | 原近邻 {prim['skill_orig']:+.4f} | "
          f"基率 {prim['skill_base']:+.4f}")
    print(f"  (b) 日均差 {prim['b_paired_block_bootstrap'].get('mean_diff'):+.6f} "
          f"95%CI {prim['b_paired_block_bootstrap'].get('ci95')}")
    print(f"  (c) 两段: {json.dumps({k: round(v['brier_fused'], 5) <= round(v['brier_orig'], 5) for k, v in segs.items()}, ensure_ascii=False)}")

    # ── 副项 1:K = 100 / 250 ──
    sec_k = {}
    for k in (100, 250):
        cm = [r for r in recs if r.get(f"fused{k}") and r.get(f"orig{k}") and r.get("base")]
        if not cm:
            sec_k[f"K={k}"] = {"why": "没有三臂都可算的日子"}
            continue
        yk = [r["y"] for r in cm]
        b_f = brier3_series([r[f"fused{k}"] for r in cm], yk)
        b_o = brier3_series([r[f"orig{k}"] for r in cm], yk)
        b_b = brier3_series([r["base"] for r in cm], yk)
        b_c = brier3_series([r["clim"] for r in cm], yk)
        d = np.array([brier3_series([r[f"fused{k}"]], [r["y"]]) - brier3_series([r[f"orig{k}"]], [r["y"]])
                      for r in cm])
        sec_k[f"K={k}"] = {"n_common": len(cm), "brier_fused": b_f, "brier_orig": b_o, "brier_base": b_b,
                           "brier_clim": b_c,
                           "skill_fused": skill(b_f, b_c), "skill_orig": skill(b_o, b_c),
                           "skill_base": skill(b_b, b_c),
                           "fused_lt_orig": b_f < b_o,
                           "paired_block_bootstrap": paired_bootstrap(d, BLOCK),
                           "paired_block_bootstrap_b30": paired_bootstrap(d, 30),
                           "paired_block_bootstrap_b90": paired_bootstrap(d, 90)}
    res["secondary"]["K_variants"] = sec_k

    # ── 副项 2:块长 30 / 90(主口径 K=150)──
    res["secondary"]["block_lengths"] = {
        "30": paired_bootstrap(diff, 30), "60": paired_bootstrap(diff, 60), "90": paired_bootstrap(diff, 90)}

    # ── 副项 3:S-737 六状态拆 Brier ──
    try:
        from sklearn.cluster import KMeans
        FM = {str(r["d"])[:10]: (r.get("f") or {}) for r in fm_rows}

        def feat_vec(d: str):
            f = FM.get(d) or {}
            vs = [f.get(k) for k in S737_FEATURES]
            if any(v is None for v in vs):
                return None
            return [float(v) for v in vs]

        tr = [d for d in sorted(FM) if S737_TRAIN[0] <= d <= S737_TRAIN[1] and feat_vec(d) is not None]
        X = np.array([feat_vec(d) for d in tr])
        mu, sd = X.mean(axis=0), np.where(X.std(axis=0) <= 0, 1.0, X.std(axis=0))
        km = KMeans(n_clusters=S737_K, random_state=S737_SEED, n_init=S737_NINIT).fit((X - mu) / sd)

        def assign(d: str):
            v = feat_vec(d)
            return None if v is None else int(km.predict((np.array([v]) - mu) / sd)[0])

        by_state: dict[int, list] = {}
        for r in common:
            st = assign(r["d"])
            if st is None:
                continue
            by_state.setdefault(st, []).append(r)
        six = {}
        for st, rs in sorted(by_state.items()):
            yss = [r["y"] for r in rs]
            six[f"S{st+1}"] = {"n": len(rs),
                               "brier_fused": brier3_series([r["fused150"] for r in rs], yss),
                               "brier_orig": brier3_series([r["orig150"] for r in rs], yss),
                               "brier_base": brier3_series([r["base"] for r in rs], yss),
                               "brier_clim": brier3_series([r["clim"] for r in rs], yss)}
        res["secondary"]["s737_six_states"] = {"train_days": len(tr), "train_range": [tr[0], tr[-1]],
                                               "spec": {"features": S737_FEATURES, "k": S737_K,
                                                        "seed": S737_SEED, "n_init": S737_NINIT,
                                                        "train_window": list(S737_TRAIN)},
                                               "states": six}
    except Exception as e:  # noqa: BLE001
        res["secondary"]["s737_six_states"] = {"why": f"六状态拆分失败:{type(e).__name__}:{e}"}

    # ── 副项 4:现货源(ohlcv_daily eq.BTC)稳健性 ──
    days_spot = [d for d in sorted(closes_spot) if START <= d <= END]
    rep_s = replay(closes_spot, msv, fused, buckets, days_spot, ks=(150,))
    res["secondary"]["spot_source"] = arm_briers(rep_s["recs"], "fused150")

    # ── 副项 5:原近邻臂「生产口径」对照(不额外排除最近 31 天,近邻 ≤ d−30)──
    b_f_p = brier3_series([r["fused150"] for r in common], ys)
    b_o_p = brier3_series([r["origp150"] for r in common], ys)
    d_p = np.array([brier3_series([r["fused150"]], [r["y"]]) - brier3_series([r["origp150"]], [r["y"]])
                    for r in common])
    res["secondary"]["orig_production_variant"] = {
        "note": "acceptance ① 要求原近邻臂排除最近 31 天;生产 knn_rates 没有这个开关(它只靠 fwd 的可得性)。"
                "这里是另一口径的对照:近邻 ≤ d−30、不额外排除。",
        "brier_fused": b_f_p, "brier_orig_prod": b_o_p, "brier_clim": prim["brier_clim_pit"],
        "skill_fused": skill(b_f_p, prim["brier_clim_pit"]),
        "skill_orig_prod": skill(b_o_p, prim["brier_clim_pit"]),
        "fused_lt_orig": b_f_p < b_o_p,
        "paired_block_bootstrap": paired_bootstrap(d_p, BLOCK)}

    # ── 诊断 ──
    fused_missing = [r for r in recs if not r.get("fused150")]
    why: dict[str, int] = {}
    for r in fused_missing:
        k = r.get("fused150_why") or "?"
        why[k] = why.get(k, 0) + 1
    res["diagnostics"] = {
        "replay_days_requested": len(days),
        "days_with_label": len(recs),
        "days_common_all_three": len(common),
        "fused_missing_days": len(fused_missing),
        "fused_missing_reasons": why,
        "fused_vec_lag_days": {str(k): v for k, v in sorted(
            {lag: sum(1 for r in recs if r.get("fused150_vecd")
                      and (dt.date.fromisoformat(r["d"]) - dt.date.fromisoformat(r["fused150_vecd"])).days == lag)
             for lag in range(0, 4)}.items())},
        "orig_vec_lag_days": {str(k): v for k, v in sorted(
            {lag: sum(1 for r in recs if r.get("vec_lag") == lag) for lag in range(0, 4)}.items())},
        "orig_fallback_unconditional_days": sum(1 for r in common if not r.get("orig150_n")),
        "base_fallback_all_days": sum(1 for r in common if r.get("base_used") == "all"),
        "outcome_mix_common": {c: sum(1 for r in common if r["y"] == c) for c in CATS},
        "mean_fwd_days_in_clim": float(np.mean([r["clim_n"] for r in common])) if common else None,
        "fwd_pairs_available": len(rep["fwd"]),
        "msv_zero_vec_rows": res["data"]["msv_zero_vec_rows"],
    }
    # 三档分位(描述用):融合臂与原近邻臂的概率分布
    for arm, key in (("fused", "fused150"), ("orig", "orig150")):
        arr = {c: [float(r[key][c]) for r in common] for c in CATS}
        res["diagnostics"][f"{arm}_prob_mean"] = {c: float(np.mean(arr[c])) for c in CATS}
        # 臂离时点无条件频率有多远(收缩把三臂都拉回气候态 ⇒ Brier 差被压扁)
        res["diagnostics"][f"{arm}_mean_abs_dev_from_clim"] = float(np.mean(
            [abs(float(r[key][c]) - float(r["clim"][c])) for r in common for c in CATS]))
    res["diagnostics"]["base_mean_abs_dev_from_clim"] = float(np.mean(
        [abs(float(r["base"][c]) - float(r["clim"][c])) for r in common for c in CATS]))
    # 抽样 5 天:三臂概率 + 气候态 + 标签(人眼可核)
    step = max(1, len(common) // 5)
    res["diagnostics"]["sample_days"] = [
        {"d": common[i]["d"], "y": common[i]["y"], "clim": common[i]["clim"],
         "fused": common[i]["fused150"], "orig": common[i]["orig150"], "base": common[i]["base"],
         "orig_n": common[i].get("orig150_n"), "orig_segs": common[i].get("orig150_segs"),
         "base_n": common[i].get("base_n"), "base_used": common[i].get("base_used"),
         "fused_vecd": common[i].get("fused150_vecd")}
        for i in range(0, len(common), step)][:5]
    # 原近邻臂的近邻里有多少是全零热身向量(诊断:全零向量两两距离 0,会挤进 top-K)
    zero_probe = []
    for i in range(0, len(common), max(1, len(common) // 5))[:5]:
        r = common[i]
        cut = (dt.date.fromisoformat(r["d"]) - dt.timedelta(days=31)).isoformat()
        today = msv[r["vec_day"]]
        cand = []
        for x, v in msv.items():
            if x > cut or x not in rep["fwd"]:
                continue
            try:
                dist = sum((float(a) - float(b)) ** 2 for a, b in zip(v, today)) ** 0.5
            except (TypeError, ValueError):
                continue
            cand.append((dist, x))
        near = sorted(cand)[:150]
        zero_probe.append({"d": r["d"], "n_cand": len(cand),
                           "near_zero_vec": sum(1 for _, x in near if not any(msv[x])),
                           "near_mean_dist": float(np.mean([dist for dist, _ in near])) if near else None})
    res["diagnostics"]["orig_zero_vector_neighbors"] = zero_probe
    print(f"  诊断:缺 {res['diagnostics']['fused_missing_days']} 天(原因 {why}) | "
          f"原臂退无条件 {res['diagnostics']['orig_fallback_unconditional_days']} 天 | "
          f"基率退 all {res['diagnostics']['base_fallback_all_days']} 天")
    print(f"  标签分布 {res['diagnostics']['outcome_mix_common']}")

    (OUT / "t268_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float))
    print(f"  → {OUT / 't268_results.json'}")


if __name__ == "__main__":
    main()
