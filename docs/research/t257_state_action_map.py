"""T-257 —— S-737 预注册:状态 × 动作地图(只算、不改代码、不入库)。

口径全部照 REFUTATION_LEDGER S-737(2026-11-06 05:59 UTC)与 S-736 出场规则:
  状态:14 个特征 → k-means k=6, seed=737, n_init=20,只用训练期 2021-03-01→2023-12-31 的均值/标准差标准化;
        留出期 2024-01-01→(最后 30 天结果已到期)只用训练期中心分配。
  动作(入场日 d,d+1 开盘进):A1 持有 BTC 30 天;A2 空仓(0);A3 战术空单(止损 1.5 ATR、止盈 2.5 ATR、
        +1R 后保本、15 根时间止损,1 倍名义 %);A4 买 30 天 90% 看跌到期(BS,σ=DVOL/100,r=0,估算);
        A5 30 天 90/80 看跌价差(同上);A6 持有 BTC + A4(保护性多头)。
  判据:训练均值>0 且 留出均值>0 且 留出期块自助(ab_test 对 A2,mean_block=20)p 经 BH(6×5=30,q=0.10)显著;
        A6 对 A1:留出期 p05 改善 ≥ 均值损失 × 2。

【已知偏离(唯一一处,数据所致,非调参)】S-737 的第 9 个特征 `oi_chg_30d` 在**整个样本期结构性缺失**
(源头表 open_interest_history 只有 2026-09-27 起的快照),训练期 1036 天里 1036 天没有该值 ⇒
14 特征全齐的天数 = 0。主口径用**可得 13 特征**(去掉 oi_chg_30d,其余 13 个一字不改,k/种子/动作/判据不动)。
副口径(含 14 特征)只覆盖 2026-10-27 之后 ⇒ 样本不足以拟合,报「不可算」。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from data.evaluation.apparatus import ab_test, percentile_of  # noqa: E402

# ── 预注册常量(不改) ────────────────────────────────────────────────────────
FEATURES_14 = ["mom_20", "mom_60", "mom_200", "dist_200", "vol_30", "vratio_30_180",
               "breadth_above_ma50", "funding_7d_ann_binance", "oi_chg_30d",
               "taker_buy_share_30d", "stable_supply_30d", "cycle:deterioration",
               "dvol:btc_pct_1y", "macro:vix"]
FEATURES = [f for f in FEATURES_14 if f != "oi_chg_30d"]          # 主口径 13 特征
TRAIN_LO, TRAIN_HI = "2021-03-01", "2023-12-31"
HOLD_LO = "2024-01-01"
K, SEED, N_INIT = 6, 737, 20
HOLD_DAYS = 30
STOP_ATR, TP_ATR, TIME_STOP = 1.5, 2.5, 15
COST_BPS = 7.5
ATR_N = 14
BH_Q = 0.10
N_BOOT = 2000

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t257_cache")
OUT = Path(__file__).resolve().parent

ACTIONS = ["A1", "A2", "A3", "A4", "A5", "A6"]
ACTION_CN = {"A1": "持有 BTC 30 天", "A2": "空仓(基准,恒 0)", "A3": "战术空单",
             "A4": "买 30 天 90% 看跌", "A5": "30 天 90/80 看跌价差", "A6": "持有 BTC + 90% 看跌"}
FEATURE_CN = {
    "mom_20": "20 日收益", "mom_60": "60 日收益", "mom_200": "200 日收益",
    "dist_200": "偏离 200 日均线", "vol_30": "30 日波动率", "vratio_30_180": "30/180 日量比",
    "breadth_above_ma50": "站上 50 日均线比例", "funding_7d_ann_binance": "7 日年化资金费",
    "oi_chg_30d": "30 日未平仓量变化", "taker_buy_share_30d": "主动买占比(30 日)",
    "stable_supply_30d": "稳定币供应 30 日变化", "cycle:deterioration": "周期恶化分",
    "dvol:btc_pct_1y": "DVOL 一年分位", "macro:vix": "VIX",
}


# ── 数据层(分页 + 缓存) ────────────────────────────────────────────────────
def pull(table: str, query: str, step: int = 1000) -> list[dict]:
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        r = requests.get(f"{URL}/rest/v1/{table}?{query}", headers={**H, "Prefer": "count=exact"},
                         timeout=300, params={"limit": step, "offset": off})
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{table}: HTTP {r.status_code} {r.text[:200]}")
        body = r.json()
        cr = r.headers.get("content-range", "")
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def load(name: str, table: str, query: str) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows")
        return rows
    rows = pull(table, query)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows")
    return rows


# ── Black-Scholes put(σ=DVOL/100, r=0, q=0,无偏斜无价差 —— 写死的估算口径) ──
def bs_put(s: float, k: float, sigma: float, t: float) -> float:
    if sigma <= 0 or t <= 0 or s <= 0 or k <= 0:
        return float("nan")
    sq = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / sq
    d2 = d1 - sq
    N = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    # put = K·N(−d2) − S·N(−d1)(r=q=0);写成 call 的形式会得到负价格
    return k * N(-d2) - s * N(-d1)


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    print("== 拉数据 ==")
    fm_rows = load("fm", "feature_matrix_daily", "select=d,f&order=d.asc")
    perp = load("perp_btc", "perp_bv_daily", "select=d,o,h,l,c&pair=eq.BTCUSDT&order=d.asc")
    dvol_rows = load("dvol_btc", "deriv_vol_daily", "select=d,dvol_close&currency=eq.BTC&order=d.asc")
    fund_rows = load("fund_btc", "v_funding_daily", "select=d,symbol,funding_rate,n&symbol=eq.BTC&order=d.asc,symbol.asc")

    FM = {r["d"]: (r.get("f") or {}) for r in fm_rows}
    DATES = [r["d"] for r in perp]
    O = [float(r["o"]) for r in perp]
    Hh = [float(r["h"]) for r in perp]
    L = [float(r["l"]) for r in perp]
    C = [float(r["c"]) for r in perp]
    IDX = {d: i for i, d in enumerate(DATES)}
    DVOL = {r["d"]: float(r["dvol_close"]) for r in dvol_rows if r.get("dvol_close") is not None}
    FUND: dict[str, float] = {}
    for r in fund_rows:
        FUND[r["d"]] = FUND.get(r["d"], 0.0) + float(r["funding_rate"]) * int(r.get("n") or 1)
    print(f"  fm {len(FM)} 天 | perp {len(DATES)} 天 ({DATES[0]}→{DATES[-1]}) | "
          f"dvol {len(DVOL)} 天 ({min(DVOL)}→{max(DVOL)}) | funding {len(FUND)} 天")
    assert len(perp) == len(set(DATES)), "perp 有重复日期"

    # ATR14(Wilder RMA,照 T-256 口径)
    n = len(DATES)
    tr = np.full(n, np.nan)
    for i in range(1, n):
        pc = C[i - 1]
        tr[i] = max(Hh[i] - L[i], abs(Hh[i] - pc), abs(L[i] - pc))
    atr = np.full(n, np.nan)
    if n > ATR_N:
        atr[ATR_N] = float(np.mean(tr[1:ATR_N + 1]))
        for i in range(ATR_N + 1, n):
            atr[i] = (atr[i - 1] * (ATR_N - 1) + tr[i]) / ATR_N

    # ── 训练期样本:13 特征齐备 ──
    def feat_vec(d: str):
        f = FM.get(d) or {}
        vals = [f.get(k) for k in FEATURES]
        if any(v is None for v in vals):
            return None
        return [float(v) for v in vals]

    train_days = [d for d in DATES if TRAIN_LO <= d <= TRAIN_HI and feat_vec(d) is not None]
    hold_days = [d for d in DATES if d >= HOLD_LO and feat_vec(d) is not None]
    print(f"  训练期可用日 {len(train_days)} ({train_days[0]}→{train_days[-1]}) | "
          f"留出期可用日 {len(hold_days)} ({hold_days[0]}→{hold_days[-1]})")
    assert train_days and hold_days, "样本为空"

    Xtr = np.array([feat_vec(d) for d in train_days])
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
    sd = np.where(sd <= 0, 1.0, sd)

    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=K, random_state=SEED, n_init=N_INIT).fit((Xtr - mu) / sd)
    centers_raw = km.cluster_centers_ * sd + mu
    print(f"  k-means inertia {km.inertia_:.2f};每类训练天数 {[int(x) for x in np.bincount(km.labels_, minlength=K)]}")

    def assign(d: str):
        v = feat_vec(d)
        if v is None:
            return None
        return int(km.predict((np.array([v]) - mu) / sd)[0])

    # ── 动作回放 ──
    def actions_for(d: str) -> dict:
        """入场日 d+1 开盘;返回各动作的 % 收益(None = 不可算)。"""
        i = IDX[d]
        j = i + 1
        k30 = j + HOLD_DAYS
        if k30 >= n:
            return {}
        entry = O[j]
        s_exit = C[k30]
        out = {"A1": 100.0 * (s_exit - entry) / entry, "A2": 0.0}
        # A3 战术空单(S-736 出场,1 倍名义)
        a = atr[i]
        if not math.isnan(a) and a > 0:
            r_unit = STOP_ATR * a
            stop0 = entry + r_unit
            target = entry - TP_ATR * a
            be_trig = entry - r_unit
            stop = stop0
            exit_i = exit_px = None
            reason = ""
            for k in range(TIME_STOP):
                b = j + k
                if b >= n:
                    break
                o, hh, ll = O[b], Hh[b], L[b]
                if o >= stop:
                    exit_i, exit_px, reason = b, o, ("保本" if stop == entry else "止损")
                    break
                if o <= target:
                    exit_i, exit_px, reason = b, o, "止盈"
                    break
                if hh >= stop:
                    exit_i, exit_px, reason = b, stop, ("保本" if stop == entry else "止损")
                    break
                if ll <= target:
                    exit_i, exit_px, reason = b, target, "止盈"
                    break
                if ll <= be_trig:
                    if hh >= entry:
                        exit_i, exit_px, reason = b, entry, "保本"
                        break
                    stop = entry
            if exit_i is None:
                b = min(j + TIME_STOP - 1, n - 1)
                exit_i, exit_px, reason = b, C[b], "时间"
            fund = float(sum(FUND.get(x, 0.0) for x in DATES[j:exit_i + 1]))
            out["A3"] = 100.0 * (entry - exit_px) / entry - 2.0 * COST_BPS / 1e4 * 100 + fund * 100
            out["A3_gross"] = 100.0 * (entry - exit_px) / entry
            out["A3_reason"] = reason
        # A4 / A5 / A6:Black-Scholes 看跌
        dv = DVOL.get(d)
        if dv is not None and dv > 0:
            sig = dv / 100.0
            t = HOLD_DAYS / 365.0
            k90 = 0.9 * entry
            k80 = 0.8 * entry
            p90 = bs_put(entry, k90, sig, t)
            p80 = bs_put(entry, k80, sig, t)
            if not (math.isnan(p90) or math.isnan(p80)):
                pay90 = max(0.0, k90 - s_exit)
                pay80 = max(0.0, k80 - s_exit)
                out["A4"] = 100.0 * (pay90 - p90) / entry
                # A5 主口径 = bear put spread(买 90% 看跌 + 卖 80% 看跌,保护性,与 A4/A6 同向);
                # 规格里「90/80 看跌价差」没写方向 ⇒ 副口径 A5b = bull put spread(卖 90 + 买 80,收权利金),只报不判。
                out["A5"] = 100.0 * ((pay90 - pay80) - (p90 - p80)) / entry
                out["A5b"] = 100.0 * ((p90 - p80) - (pay90 - pay80)) / entry
                out["A6"] = 100.0 * ((s_exit - entry) + pay90 - p90) / entry
                out["prem90_pct"] = 100.0 * p90 / entry
                out["A4_undisc"] = 100.0 * pay90 / entry
        return out

    print("== 回放动作 ==")
    recs = []
    for d in DATES:
        if not (TRAIN_LO <= d <= "2026-12-31"):
            continue
        av = actions_for(d)
        if not av:
            continue
        st = assign(d)
        if st is None:
            continue
        period = "train" if d <= TRAIN_HI else "hold"
        rec = {"d": d, "state": st, "period": period}
        rec.update(av)
        recs.append(rec)
    print(f"  回放 {len(recs)} 个入场日 (train {sum(1 for r in recs if r['period']=='train')}, "
          f"hold {sum(1 for r in recs if r['period']=='hold')})")
    # 留出期只保留 30 天结果已到期的日子(最后一个完整 30 天窗口)
    last_entry = DATES[-1 - HOLD_DAYS]
    recs = [r for r in recs if r["d"] <= last_entry]
    print(f"  留出期截到入场日 ≤ {last_entry} ⇒ {len(recs)} 条")

    # ── 格子统计 ──
    def stats(vals: list[float]) -> dict:
        a = np.array(vals, dtype=float)
        if a.size == 0:
            return {"n": 0}
        return {"n": int(a.size), "mean": float(a.mean()), "median": float(np.median(a)),
                "p05": float(np.percentile(a, 5)), "p25": float(np.percentile(a, 25)),
                "win": float((a > 0).mean()), "min": float(a.min()), "max": float(a.max())}

    def segments(days: list[str]) -> int:
        if not days:
            return 0
        dd = [datetime.strptime(x, "%Y-%m-%d") for x in days]
        segs = 1
        for a, b in zip(dd, dd[1:]):
            if (b - a).days >= HOLD_DAYS:
                segs += 1
        return segs

    grid: dict = {}
    for st in range(K):
        for per in ("train", "hold"):
            sub = [r for r in recs if r["state"] == st and r["period"] == per]
            for act in ACTIONS:
                vals = [r[act] for r in sub if r.get(act) is not None]
                days = [r["d"] for r in sub if r.get(act) is not None]
                grid[f"{st}|{per}|{act}"] = {**stats(vals), "segments": segments(days),
                                            "days": days}
    # ab_test(留出期,动作 vs A2=0,块均长 20 天)
    ps = []
    for st in range(K):
        for act in ACTIONS:
            if act == "A2":
                continue
            sub = [r for r in recs if r["state"] == st and r["period"] == "hold" and r.get(act) is not None]
            if len(sub) < 2 * 20:
                grid[f"{st}|hold|{act}"]["p_one_sided"] = None
                grid[f"{st}|hold|{act}"]["ab_why"] = f"只有 {len(sub)} 天,少于两个平均块长"
                ps.append((f"{st}|{act}", None))
                continue
            a = np.array([r[act] for r in sub]) / 100.0
            b = np.zeros_like(a)
            res = ab_test(a, b, mean_block=20.0, n_boot=N_BOOT, seed=SEED)
            p = float(res["p_b_ge_a"])          # B(=空仓) ≥ A(动作) ⇒ 动作不如空仓
            grid[f"{st}|hold|{act}"]["p_one_sided"] = p
            grid[f"{st}|hold|{act}"]["ab_verdict"] = res["verdict"]
            grid[f"{st}|hold|{act}"]["ab_n"] = res["n_days"]
            ps.append((f"{st}|{act}", p))
    # BH(写死:6 × 5 = 30 格,q = 0.10)。不可算的格子 p 记 1.0 参与排序(不拒绝),m 固定 30。
    m = K * 5
    valid = [(k, p if p is not None else 1.0) for k, p in ps]
    valid.sort(key=lambda x: x[1])
    thr = {}
    for i, (k, p) in enumerate(valid, start=1):
        thr[k] = i * BH_Q / m
    for k, p in valid:
        stk, actk = k.split("|")
        cell = grid[f"{stk}|hold|{actk}"]
        cell["bh_threshold"] = thr[k]
        cell["bh_sig"] = bool(p <= thr[k] and p < 1.0)
    for st in range(K):
        for act in ACTIONS:
            if act == "A2":
                continue
            cell = grid[f"{st}|hold|{act}"]
            tr = grid[f"{st}|train|{act}"]
            cell["cond_advantage"] = bool(
                cell.get("mean", 0) > 0 and tr.get("mean", 0) > 0 and cell.get("bh_sig"))
    # 副口径 A5b(bull put spread)与 A3gross(不含成本/资金费)只报不判
    for st in range(K):
        for per in ("train", "hold"):
            sub = [r for r in recs if r["state"] == st and r["period"] == per]
            for key in ("A5b", "A3_gross"):
                vals = [r[key] for r in sub if r.get(key) is not None]
                days = [r["d"] for r in sub if r.get(key) is not None]
                grid[f"{st}|{per}|{key}"] = {**stats(vals), "segments": segments(days)}

    # A6 对 A1(留出期 p05 改善 ≥ 均值损失 × 2)
    a6v = {}
    for st in range(K):
        c1, c6 = grid[f"{st}|hold|A1"], grid[f"{st}|hold|A6"]
        if c1.get("n") and c6.get("n"):
            imp = c6["p05"] - c1["p05"]
            loss = c1["mean"] - c6["mean"]
            a6v[st] = {"p05_a1": c1["p05"], "p05_a6": c6["p05"], "p05_improve": imp,
                       "mean_a1": c1["mean"], "mean_a6": c6["mean"], "mean_loss": loss,
                       "ratio": (imp / loss) if loss > 1e-12 else None,
                       "pass": bool(loss <= 0 or imp >= 2 * loss)}
        else:
            a6v[st] = {}

    # 状态中心(原始单位,训练期中位数)+ 今天的类别
    centers = {}
    for st in range(K):
        mem = [d for d, lb in zip(train_days, km.labels_) if lb == st]
        cen = {}
        for j, k in enumerate(FEATURES):
            vals = [float(FM[d][k]) for d in mem]
            cen[k] = {"median": float(np.median(vals)), "mean": float(np.mean(vals)),
                      "p10": float(np.percentile(vals, 10)), "p90": float(np.percentile(vals, 90)),
                      "cn": FEATURE_CN[k]}
        # 相对全体训练分布的偏离(标准化空间)
        z = (np.array([cen[k]["median"] for k in FEATURES]) - mu) / sd
        cen["_z_vs_train"] = {k: float(v) for k, v in zip(FEATURES, z)}
        centers[st] = cen
    latest = max(d for d in DATES if assign(d) is not None)
    today_state = assign(latest)

    result = {
        "card": "T-257", "prereg": "S-737 (2026-11-06 05:59 UTC)",
        "spec_deviation": {
            "what": "去掉 oi_chg_30d(第 9 个特征),用 13 特征",
            "why": "oi_chg_30d 源头 open_interest_history 只有 2026-09-27 起,训练期 1036/1036 天全缺,14 特征全齐=0 天",
            "unchanged": "k=6, seed=737, n_init=20, 训练/留出切分, 6 个动作, 出场规则, 判据与 BH(q=0.10) 全部未动",
        },
        "n_features": len(FEATURES), "features": FEATURES,
        "k": K, "seed": SEED, "n_init": N_INIT,
        "train_window": [TRAIN_LO, TRAIN_HI], "hold_from": HOLD_LO,
        "train_days": len(train_days), "hold_days": len(hold_days),
        "train_first": train_days[0], "train_last": train_days[-1],
        "hold_first": hold_days[0], "hold_last": hold_days[-1],
        "last_entry_day": last_entry,
        "latest_feature_day": latest, "today_state": today_state,
        "cluster_sizes_train": [int(x) for x in np.bincount(km.labels_, minlength=K)],
        "centers": centers, "grid": grid, "a6_vs_a1": a6v,
        "inertia": float(km.inertia_),
    }
    # ── sanity:抽样打印期权估算与击穿,防止符号/单位错误 ──
    print("== sanity(前 5 个训练日)==")
    for r in [x for x in recs if x["period"] == "train"][:5]:
        print(f"  {r['d']} S{r['state']} A1 {r['A1']:.2f}% A4 {r.get('A4', float('nan')):.2f}% "
              f"A5 {r.get('A5', float('nan')):.2f}% A5b {r.get('A5b', float('nan')):.2f}% "
              f"A6 {r.get('A6', float('nan')):.2f}% "
              f"prem90 {r.get('prem90_pct', float('nan')):.2f}% "
              f"击穿90% {r.get('A4_undisc', float('nan')):.2f}%")
    bad = [r for r in recs if r.get("prem90_pct") is not None and not (0 < r["prem90_pct"] < 25)]
    assert not bad, f"期权权利金比例异常: {bad[:2]}"
    a4_all = [r["A4"] for r in recs if r.get("A4") is not None]
    print(f"  A4 可算 {len(a4_all)} 天;权利金均值 {np.mean([r['prem90_pct'] for r in recs if r.get('prem90_pct') is not None]):.2f}%;"
          f"击穿90%比例 {np.mean([r['A4_undisc'] > 0 for r in recs if r.get('A4_undisc') is not None]):.1%}")

    (OUT / "t257_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("== 写 t257_results.json ==")

    # ── 控制台摘要 ──
    for st in range(K):
        for per in ("train", "hold"):
            line = [f"S{st} {per:5s}"]
            for act in ACTIONS:
                c = grid[f"{st}|{per}|{act}"]
                if not c.get("n"):
                    line.append(f"{act}:n=0")
                    continue
                p = c.get("p_one_sided")
                line.append(f"{act}: n{c['n']} m{c['mean']:.2f} med{c['median']:.2f} "
                            f"p05 {c['p05']:.2f} w{c['win']:.0%}"
                            + (f" p{p:.3f}{'*' if c.get('bh_sig') else ''}" if p is not None else ""))
            print(" | ".join(line))
    print("\n今天(最新特征日 %s)落在 S%s" % (latest, today_state))
    print("A6 vs A1:", json.dumps(a6v, ensure_ascii=False))


if __name__ == "__main__":
    main()
