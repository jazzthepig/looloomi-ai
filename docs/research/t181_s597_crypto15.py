"""S-597 加密非 BTC 市值前 15 篮子:三条臂 R / L / LC(另 LC-cap 只报)—— T-181。

照台账 §S-597 预注册原文(REFUTATION_LEDGER.md,2026-10-16 11:28 UTC)实现:
  R  = 每期调回等权(现状,卖赢家买输家)
  L  = 每期只换成分:离开的卖掉,新进的每个拿 1/N 的当前净值、按比例从老成员里出,老成员不调权重
  LC = L + 周度检查:任何成员从**它进篮子那天的价格**跌 ≥ 25% ⇒ 下周收盘卖掉,钱按当前权重分给
       还在篮子里的,到下次调仓前不回来
成本 20 bp × 换手。统计只走 src/data/evaluation/apparatus.py。数据:Mac 数据根 research/
crypto_daily/panel.json(日频 price / mcap)。
"""
from __future__ import annotations
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Optional
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.data.evaluation.apparatus import ab_test  # noqa: E402

PANEL = "/Volumes/CometCloudAI/cometcloud-local/research/crypto_daily/panel.json"
N_SLOTS = 15
REB_WEEKS = 4
COST_BP = 20.0
CUT = 0.75          # 从进篮子那天的价格跌 ≥ 25%
FWD_WEEKS = 13      # 被砍之后 13 周
ARMS = ("R", "L", "LC", "LCcap")

# 稳定币 / 包装币 / 债券代币(T-109 与 s587 两份名单的并集;不含 BTC —— 篮子是非 BTC)
EXCLUDE = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "USDE", "USDS", "USDD",
    "USD1", "USDF", "USDTB", "USDG", "FRAX", "RLUSD", "BFUSD", "GUSD", "USDP", "LUSD",
    "SUSD", "EUR", "EURS", "EURT", "XAUT", "PAXG", "THBILL", "EUTBL", "USTBL", "BUIDL",
    "FIGR_HELOC", "JTRSY", "SAFO", "EURSAFO", "STABLE", "MSTRX", "STRCX", "JITOSOL", "MSOL",
    "WBTC", "TBTC", "CBBTC", "BTCB", "CBETH", "SBTC", "LBTC", "SOLVBTC", "CLBTC", "BTC", "BTCDOM",
    "WETH", "STETH", "WSTETH", "RETH", "WEETH", "EETH", "EZETH", "METH", "RSETH", "FRXETH",
}
SEGMENTS = [("2019-06", "2022-01"), ("2022-01", "2024-01"), ("2024-01", "2027-01")]


# ---------------------------------------------------------------- 纯机制(被红测直接打)

def drift_weights(w: np.ndarray, r: np.ndarray) -> np.ndarray:
    """一周后 w_i' = w_i(1+r_i) / Σ_j w_j(1+r_j) —— 价格漂移,不是等权。"""
    raw = np.asarray(w, float) * (1.0 + np.asarray(r, float))
    return raw / raw.sum() if raw.sum() > 0 else np.asarray(w, float)


def _turnover(before: dict, after: dict, nav: float) -> float:
    return sum(abs(after.get(k, 0.0) - before.get(k, 0.0)) for k in set(before) | set(after)) / nav


def rebalance_r(vals: dict, entry: dict, basket: set, n_slots: int,
                price: Any = 1.0, nav: float = 1.0, t: int = 0) -> tuple[dict, dict, float]:
    """R:每期调回等权 —— 每个 1/N,不管上期涨了多少。"""
    after = {k: 0.0 for k in vals}
    after.update({k: nav / n_slots for k in basket})
    ent = {k: entry.get(k, t) for k in basket}
    return after, ent, _turnover(vals, after, nav)


def rebalance_l(vals: dict, entry: dict, basket: set, n_slots: int,
                price: Any = 1.0, nav: float = 1.0, t: int = 0) -> tuple[dict, dict, float]:
    """L:只换成分 —— 新进各拿 1/N,老成员按自己的净值比例让出;老成员的**相对**权重不变。"""
    surv = [k for k in basket if vals.get(k, 0.0) > 0.0]
    new = [k for k in basket if vals.get(k, 0.0) <= 0.0]
    after = {k: 0.0 for k in vals}
    if surv:
        # 老成员一共拿 nav × (1 − m/N) —— 剩下的正好是新进 m 个的 m × 1/N,
        # 离场者的卖出款也在这 nav 里,所以幸存者按比例缩放(相对权重不变,可能 >1)
        tot = sum(vals[k] for k in surv)
        shrink = (nav * (1.0 - len(new) / n_slots) / tot) if tot > 0 else 0.0
        for k in surv:
            after[k] = vals[k] * shrink
    for k in new:
        after[k] = nav / n_slots
    ent = {k: entry.get(k, t) for k in basket}
    return after, ent, _turnover(vals, after, nav)


def apply_cut(vals: dict, cut: set) -> dict:
    """LC 砍:被砍的钱按当前权重分给还在篮子里的 —— 不是补成等权。"""
    keep = {k: v for k, v in vals.items() if k not in cut}
    tot = sum(keep.values())
    if tot <= 0:
        return {k: 0.0 for k in vals}
    return {k: (v / tot if k not in cut else 0.0) for k, v in vals.items()}


def cap_weights(vals: dict, cap: float) -> dict:
    """单名上限(LC-cap 臂,10-18 看过结果才加的 ⇒ 只报):超出的按比例分给未超额的。"""
    v = dict(vals)
    for _ in range(6):
        over = {k: x - cap for k, x in v.items() if x > cap}
        exc = sum(over.values())
        under = {k: x for k, x in v.items() if x < cap}
        usum = sum(under.values())
        if exc <= 1e-12 or usum <= 0:
            break
        for k, x in over.items():
            v[k] = cap
        for k, x in under.items():
            v[k] = x + exc * x / usum
    return v


def cuts_at(P: np.ndarray, names, entry: dict, t: int, thresh: float = CUT) -> set:
    """周度检查:从**进篮子那天的价格**跌 ≥ 25% 的成员。entry 跨调仓日存活。"""
    out = set()
    for i in names:
        e = entry.get(i)
        if e is None or not np.isfinite(P[e, i]) or P[e, i] <= 0:
            continue
        if np.isfinite(P[t, i]) and P[t, i] <= thresh * P[e, i]:
            out.add(i)
    return out


# ---------------------------------------------------------------- 模拟

def simulate(P: np.ndarray, basket: list[set], reb: list[int], arm: str,
             cost_bp: float = COST_BP, cap_n: float = 2.0) -> dict[str, Any]:
    """P:(n_weeks × n_names) 周收盘价(NaN = 无价)。basket[t]:第 t 周末调仓后的目标篮子。"""
    n = P.shape[0]
    shares: dict[int, float] = {}
    entry: dict[int, int] = {}
    nav = np.zeros(n)
    wret = np.zeros(n)
    held: list[set] = [set() for _ in range(n)]
    maxw = np.zeros(n)
    turns: dict[int, float] = {}
    cuts_exec: list[tuple[int, int]] = []      # (卖出的周, 名字)
    pending: set = set()
    haircut = 1.0        # 成本是乘性的:每次成交按换手比例把净值打折,后面周继续带着
    prev = 1.0
    reb_set = set(reb)

    for t in range(n):
        # ① 上周触发、本周收盘执行 LC 的砍
        if arm.startswith("LC") and pending:
            vals = {i: shares[i] * P[t, i] for i in list(shares) if np.isfinite(P[t, i])}
            doing = {i for i in pending if i in vals and P[t, i] > 0}
            if doing:
                after = apply_cut(vals, doing)
                for i in doing:
                    cuts_exec.append((t, i))
                turn = _turnover(vals, after, sum(vals.values()) or 1.0)
                for i in doing:
                    shares.pop(i, None)
                    entry.pop(i, None)
                for i, v in after.items():
                    if i in doing or v <= 0 or not np.isfinite(P[t, i]) or P[t, i] <= 0:
                        continue
                    shares[i] = v / P[t, i]
                turns[t] = turns.get(t, 0.0) + turn
                haircut *= (1.0 - turn * cost_bp / 1e4)
            pending -= doing
        # ② 调仓日
        if t in reb_set and basket[t]:
            names = [i for i in basket[t] if np.isfinite(P[t, i]) and P[t, i] > 0]
            vals = {i: shares[i] * P[t, i] for i in list(shares) if np.isfinite(P[t, i])}
            gross = sum(vals.values()) or prev          # 首期:空仓 ⇒ 用上一周的净值当本金
            if gross > 0 and names:
                fn = rebalance_r if arm == "R" else rebalance_l
                after, entry, turn = fn(vals, entry, set(names), len(names), P[t], gross, t)
                if arm == "LCcap":
                    after = cap_weights(after, gross * cap_n / len(names))
                shares = {i: v / P[t, i] for i, v in after.items()
                          if v > 0 and i in entry}
                turns[t] = turns.get(t, 0.0) + turn
                haircut *= (1.0 - turn * cost_bp / 1e4)
        nav[t] = max(haircut * sum(s * P[t, i] for i, s in shares.items()
                                   if np.isfinite(P[t, i])), 1e-9)
        wret[t] = 0.0 if t == 0 else nav[t] / prev - 1.0
        prev = nav[t]
        held[t] = set(shares)
        tot = sum(shares[i] * P[t, i] for i in shares if np.isfinite(P[t, i]))
        maxw[t] = max((shares[i] * P[t, i] / tot for i in shares
                       if np.isfinite(P[t, i])), default=0.0) if tot > 0 else 0.0
        # ③ 本周收盘检查,下周卖
        if arm.startswith("LC") and t < n - 1:
            pending |= cuts_at(P, list(shares), entry, t)
    return {"nav": nav, "weekly_ret": wret, "held_by_week": held, "max_weight": maxw,
            "turnover": turns, "n_cuts": len(cuts_exec), "cuts": cuts_exec,
            "held_counts": [len(h) for h in held]}


# ---------------------------------------------------------------- 数据与报告

def weekly_grid(dates: list[str]) -> list[int]:
    """每周最后一个有数据的日(按 ISO 周分组)。"""
    last: dict[tuple[int, int], int] = {}
    for i, d in enumerate(dates):
        last[datetime.date.fromisoformat(d).isocalendar()[:2]] = i
    return sorted(last.values())


def build_panel() -> dict[str, Any]:
    p = json.loads(Path(PANEL).read_text())
    dates = p["dates"]
    gi = weekly_grid(dates)
    wd = [dates[i] for i in gi]
    syms = [s for s in p["price"] if s.upper() not in EXCLUDE]
    P = np.full((len(gi), len(syms)), np.nan)
    C = np.full((len(gi), len(syms)), np.nan)
    for j, s in enumerate(syms):
        P[:, j] = [p["price"][s][i] for i in gi]
        C[:, j] = [p["mcap"][s][i] for i in gi]
    basket = []
    for t in range(len(gi)):
        mc = np.where(np.isfinite(C[t]), C[t], -1.0)
        order = np.argsort(-mc)[:N_SLOTS]
        basket.append(set(int(i) for i in order if mc[i] > 0 and np.isfinite(P[t, i])))
    return {"dates": wd, "syms": syms, "P": P, "basket": basket}


def max_drawdown(nav: np.ndarray) -> float:
    return float((nav / np.maximum.accumulate(nav) - 1.0).min())


def summarise(dates: list[str], sim: dict[str, Any], P: np.ndarray,
              bench: Optional[np.ndarray] = None) -> dict[str, Any]:
    nav, wret = sim["nav"], sim["weekly_ret"]
    mw = sim["max_weight"]
    cuts = []
    for t, i in sim["cuts"]:
        fwd = cut_fwd = None
        if t + FWD_WEEKS < P.shape[0] and np.isfinite(P[t + FWD_WEEKS, i]) and P[t, i] > 0:
            fwd = float(P[t + FWD_WEEKS, i] / P[t, i] - 1.0)
            if bench is not None:
                cut_fwd = float(bench[t + FWD_WEEKS] / bench[t] - 1.0)
        cuts.append({"week": dates[t], "name": i, "fwd13": fwd, "bench_fwd13": cut_fwd})
    f = [c["fwd13"] for c in cuts if c["fwd13"] is not None]
    hc = np.array(sim["held_counts"], dtype=float)
    return {
        "cum": float(nav[-1] - 1.0), "ann": float(nav[-1] ** (52.0 / len(nav)) - 1.0),
        "max_dd": max_drawdown(nav), "weeks": len(nav), "n_cuts": sim["n_cuts"],
        "held_median": float(np.median(hc)), "held_min": int(hc.min()),
        "weeks_held_le_5": int((hc <= 5).sum()),
        "turnover_per_rebal": float(np.mean(list(sim["turnover"].values()))) if sim["turnover"] else 0.0,
        "max_weight_max": float(mw.max()), "max_weight_p90": float(np.quantile(mw, 0.9)),
        "max_weight_median": float(np.median(mw)),
        "weeks_above_2_over_15": int((mw > 2.0 / N_SLOTS).sum()),
        "cut_fwd13_mean": float(np.mean(f)) if f else None,
        "n_cuts_with_fwd13": len(f),
        "cut_fwd13_vs_bench_mean": float(np.mean([c["fwd13"] - c["bench_fwd13"] for c in cuts
                                                  if c["fwd13"] is not None and c["bench_fwd13"] is not None]))
        if bench is not None and f else None,
        "cuts": cuts,
    }


def main() -> dict[str, Any]:
    d = build_panel()
    dates, P, basket = d["dates"], d["P"], d["basket"]
    reb = list(range(0, len(dates), REB_WEEKS))
    sims = {a: simulate(P, basket, reb, a) for a in ARMS}
    base = {a: summarise(dates, sims[a], P, bench=sims["R"]["nav"]) for a in ARMS}
    verdicts: dict[str, Any] = {}
    for cand in ("L", "LC", "LCcap"):
        full = ab_test(sims["R"]["weekly_ret"], sims[cand]["weekly_ret"],
                       mean_block=4, days_per_year=52, seed=181)
        segs = {}
        for lo, hi in SEGMENTS:
            m = np.array([(lo <= x < hi) for x in dates])
            s = ab_test(sims["R"]["weekly_ret"][m], sims[cand]["weekly_ret"][m],
                        mean_block=4, days_per_year=52, seed=181)
            segs[f"{lo}..{hi}"] = {"ratio_b_over_a": s.get("ratio_b_over_a"),
                                   "p_b_ge_a": s.get("p_b_ge_a"), "n_days": s.get("n_days")}
        # 判据:全样本 ab_test 判后者胜出,且三段至少两段同号
        up = full["ratio_b_over_a"] > 1.0
        n_same = sum(1 for v in segs.values()
                     if ((v["ratio_b_over_a"] or 1.0) > 1.0) is up)
        verdicts[cand] = {"full": full, "segments": segs,
                          "seg_same_sign_as_full": n_same >= 2,
                          "passes": full["verdict"] == "B > A" and n_same >= 2}
    out = {"ledger": "S-597", "task": "T-181", "n_weeks": len(dates),
           "date_range": [dates[0], dates[-1]], "n_slots": N_SLOTS,
           "reb_weeks": REB_WEEKS, "cost_bp": COST_BP, "cut_threshold": CUT,
           "segments": [list(s) for s in SEGMENTS], "arms": base, "verdicts": verdicts}
    dst = Path(__file__).with_name("t181_results.json")
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    r = main()
    for a in ARMS:
        s = r["arms"][a]
        f13 = 'None' if s['cut_fwd13_mean'] is None else round(s['cut_fwd13_mean'], 3)
        print(f"{a:6s} cum {s['cum']:+.2f} ann {s['ann']:+.3f} dd {s['max_dd']:+.3f} "
              f"maxw {s['max_weight_max']:.3f} p90 {s['max_weight_p90']:.3f} "
              f"turn {s['turnover_per_rebal']:.3f} cuts {s['n_cuts']}/{s['n_cuts_with_fwd13']} fwd13 {f13}")
    for c, v in r["verdicts"].items():
        f = v["full"]
        print(c, f["verdict"], "ratio", round(f["ratio_b_over_a"], 3),
              "p_le", round(f["p_b_le_a"], 3), "p_ge", round(f["p_b_ge_a"], 3),
              "2seg", v["seg_same_sign_as_full"], "PASS", v["passes"])