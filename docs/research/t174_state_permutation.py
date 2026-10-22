"""T-174 / S-669 返工:把「块置换零化均值」换成「组内按日期打乱标签 ↔ 收益的配对」。

T-171 用 apparatus.block_permute 打乱「标签桶超额」序列后取均值 —— 块置换保留元素的多重集合,
均值不变,零分布只剩浮点噪声(apparatus.null_distribution 在 1e-12 相对跨度处抛 NoOpNull)。
台账 S-669 那句「0 存活」是空转出来的,已作废。

本脚本的零分布(卡 T-174 acceptance 原文):
    每个「标签 × 段」:把该段内**所有** (日期, 名字) 的 4 周组内超额摆成 date × name 一张大表,
    每次抽样在**每个日期内部**用 apparatus.shuffle_within 打乱「名字 ↔ 之后 4 周组内超额」的配对,
    再重算该标签的桶均值 = mean(打乱后的超额 | 标签命中)。
  · 组内打乱保留同日横截面的分布,也保留组等权基准(超额里已经减掉了 ew),只摧毁标签↔收益的关联;
  · 观测值与 T-171 逐格一致(面板由 t171_state_layer.build_panels() 建),两版可直接对读;
  · 同一 (组, 段) 的所有标签共用同一批打乱 —— 打乱只跟日期有关,跟标签无关,共用是正确且省 8 倍算力。

用法:
    python3 docs/research/t174_state_permutation.py [--root /Volumes/CometCloudAI/cometcloud-local] [--nboot 400]
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv \
    else "/Volumes/CometCloudAI/cometcloud-local"
NBOOT = int(sys.argv[sys.argv.index("--nboot") + 1]) if "--nboot" in sys.argv else 400
SEED = 20261023
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import t171_state_layer as t171                                  # noqa: E402
from src.data.evaluation.apparatus import (NoOpNull,            # noqa: E402
                                           null_distribution,
                                           percentile_of,
                                           shuffle_within)

LABELS = {"trend": [t171.T_UP, t171.T_DOWN, t171.T_FLAT],
          "mom": [t171.M_STRONG, t171.M_WEAK, t171.M_MID],
          "crowd": [t171.C_HOT, t171.C_COLD, t171.C_NORM]}


def seg_idx(cal: list[str], a: str, b: str) -> list[int]:
    return [i for i, d in enumerate(cal) if a <= d <= b]


def seg_table(P: dict, idx: list[int]) -> tuple[list, np.ndarray, dict]:
    """该段内所有「日期 + 名字 + 4 周组内超额」都有限的行。

    返回 (日期数组, 超额数组, 每种标签族逐行的标签数组)。超额 = fwd - 组等权 fwd,与 T-171 同源。"""
    cal, mem = P["cal"], P["members"]
    d_rows, e_rows = [], []
    lab_rows = {k: [] for k in LABELS}
    for i in idx:
        ew = P["ew_fwd"][i]
        if ew is None or not math.isfinite(ew):
            continue
        for s in mem:
            f = P["fwd"][s][i]
            if f is None or not math.isfinite(f):
                continue
            d_rows.append(cal[i])
            e_rows.append(float(f) - float(ew))
            for k in LABELS:
                lab_rows[k].append(P[k][s][i])
    return (np.asarray(d_rows, dtype=object),
            np.asarray(e_rows, dtype=float),
            {k: np.asarray(v, dtype=object) for k, v in lab_rows.items()})


def paired_null(exc: np.ndarray, dates: np.ndarray, mask: np.ndarray,
                obs: float, n_boot: int, seed: int):
    """零分布:组内(按日期)打乱标签 ↔ 超额的配对后,重算该标签的桶均值。

    返回 (百分位, n_null, 零分布均值, 零分布标准差)或 (None, …) —— 打乱不改变任何东西时为 None。"""
    rng = np.random.default_rng(seed)
    shuffles = [shuffle_within(exc, dates, rng) for _ in range(n_boot)]
    cur = {"i": -1}

    def one(_rng):
        cur["i"] = (cur["i"] + 1) % n_boot
        return float(shuffles[cur["i"]][mask].mean())

    try:
        null = null_distribution(one, n_boot, seed, actual=obs)
    except NoOpNull as e:                      # 标签在段内完全不带信息 / 命中集合退化
        return None, 0, None, None, str(e)
    return (percentile_of(obs, null), int(np.isfinite(null).sum()),
            float(np.nanmean(null)), float(np.nanstd(null)), None)


def stability_counts(panels: dict) -> dict:
    """每 30 天(按名字分块)的换标签次数 —— 只报数,**不下「稳 / 不稳」的结论**。

    T-171 只对 trend 定了门槛(≤2 次 / 30 天),动量与拥挤的门槛 S-669 没给,这里也不给。"""
    out = {}
    for gname, P in panels.items():
        cal, mem = P["cal"], P["members"]
        blocks = [(i, min(i + 30, len(cal))) for i in range(0, len(cal) - 29, 30)]
        for kind in LABELS:
            ch, cov, switches = [], [], []
            for s in mem:
                lab = P[kind][s]
                for i0, i1 in blocks:
                    seq = [(i, lab[i]) for i in range(i0, i1) if lab[i] is not None]
                    if len(seq) < 10:
                        continue
                    ch.append(sum(1 for k in range(1, len(seq)) if seq[k][1] != seq[k - 1][1]))
                    cov.append(len(seq))
                    for k in range(1, len(seq)):
                        if seq[k][1] == seq[k - 1][1]:
                            continue
                        prev = seq[k - 1][1]
                        switches.append(1.0 if any(seq[j][1] == prev
                                                    for j in range(k, min(k + 3, len(seq)))) else 0.0)
            if ch:
                out[f"{gname}/{kind}"] = {
                    "n_name_blocks": len(ch),
                    "mean_changes_per_30d": round(float(np.mean(ch)), 3),
                    "median_changes_per_30d": round(float(np.median(ch)), 3),
                    "p90_changes_per_30d": round(float(np.percentile(ch, 90)), 3),
                    "revert_within_3d": round(float(np.mean(switches)), 4) if switches else None,
                    "n_switches": len(switches),
                }
    return out


def tail_p(pct: float | None) -> float | None:
    """双尾显著性:percentile_of 给的是「零分布里有多少落在观测值下方」,
    所以正向信号要看 ≥0.975、反向信号要看 ≤0.025,不能一律卡 ≤0.05(那是只抓反向)。"""
    return None if pct is None else min(pct, 1.0 - pct)


def main() -> dict:
    built = t171.build_panels()
    res, panels, fng, vix = built["res"], built["panels"], built["fng"], built["vix"]
    res["t174"] = {"prereg": "T-174 (tasks/T-174.json, 2026-10-22),S-669 台账更正",
                   "nboot": NBOOT, "seed": SEED,
                   "null": "shuffle_within(excess, groups=date) —— 打乱「名字 ↔ 之后 4 周组内超额」"
                           "的配对后重算标签桶均值;块置换那版保留多重集合、均值不变,是空转"}

    # ---- 组等权基准的 4 周无条件收益(超额就是它减出来的,单列出来给读者看绝对量级)----
    bench = {}
    for gname, P in panels.items():
        cal = P["cal"]
        idx_all = seg_idx(cal, t171.WIN_START, t171.WIN_END)
        row = {}
        for sname, rng_ in (("A", t171.SEG_A), ("B", t171.SEG_B), ("ALL", (t171.WIN_START, t171.WIN_END))):
            xs = [P["ew_fwd"][i] for i in seg_idx(cal, *rng_)
                  if P["ew_fwd"][i] is not None and math.isfinite(P["ew_fwd"][i])]
            t, n, mu = t171.t_stat(xs)
            row[sname] = {"mean_ew_fwd_28d": round(mu, 6) if mu == mu else None,
                          "t": round(t, 3) if t == t else None, "n": n,
                          "ann_from_mean": (round((1.0 + mu) ** (365 / 28.0) - 1.0, 4)
                                            if mu == mu and mu > -1 else None)}
        bench[gname] = row
    res["benchmark_group_equal_weight_fwd28"] = bench

    # ---- 换标签次数(动量 / 拥挤只报数,不下结论)----
    stab = stability_counts(panels)
    res["label_switches_per_30d"] = stab
    res["label_switches_note"] = ("T-171 只对 trend 定了门槛(中位数 ≤2 次 / 30 天 = 能展示);"
                                  "动量与拥挤 S-669 没给门槛,这里只报次数,不给稳 / 不稳的结论。")

    # ---- 逐个标签 × 段:观测值 + 配对置换零分布 ----
    pred = {}
    for gname, P in panels.items():
        cal = P["cal"]
        for kind, labs in LABELS.items():
            if kind == "crowd" and not P["is_crypto"]:
                continue
            for sname, (a, b) in (("A", t171.SEG_A), ("B", t171.SEG_B)):
                idx = seg_idx(cal, a, b)
                dates, exc, lab_rows = seg_table(P, idx)
                if exc.size == 0:
                    continue
                for lab in labs:
                    key = f"{gname}/{kind}/{lab}"
                    per_seg = pred.setdefault(key, {})
                    mask = lab_rows[kind] == lab
                    xs = exc[mask]
                    t, n, mu = t171.t_stat(xs.tolist())
                    per_seg[sname] = {"mean_excess": round(mu, 6) if mu == mu else None,
                                      "t": round(t, 3) if t == t else None, "n": n,
                                      "n_shuffled_rows": int(exc.size)}
                    if n < 3 or mu != mu:
                        per_seg[sname]["perm_pct"] = None
                        continue
                    pct, nn, nm, nsd, why = paired_null(exc, dates, mask, mu, NBOOT, SEED)
                    per_seg[sname].update({"perm_pct": (round(pct, 4) if pct is not None else None),
                                           "null_n": nn,
                                           "null_mean": (round(nm, 6) if nm is not None else None),
                                           "null_sd": (round(nsd, 6) if nsd is not None else None)})
                    if why:
                        per_seg[sname]["null_note"] = why
                    print(f"  [{key} / 段{sname}] n={n} 超额均值={mu:+.5f} t={t:+.2f} "
                          f"置换分位={pct if pct is not None else 'NoOpNull'}", flush=True)

    # ---- 候选判法:照 S-669 原文(两段同号且两段 |t| ≥ 2)----
    for key, per_seg in pred.items():
        mA, mB = per_seg.get("A", {}).get("mean_excess"), per_seg.get("B", {}).get("mean_excess")
        tt = {s: per_seg[s]["t"] for s in ("A", "B") if per_seg.get(s, {}).get("t") is not None}
        same_sign = (mA is not None and mB is not None and mA * mB > 0)
        loose = bool(tt) and max(abs(x) for x in tt.values()) >= 2.0
        strict = len(tt) == 2 and all(abs(x) >= 2.0 for x in tt.values())
        per_seg["same_sign"] = same_sign
        per_seg["candidate"] = bool(same_sign and strict)          # 严格为主口径
        per_seg["candidate_loose"] = bool(same_sign and loose)
        per_seg["verdict"] = ("候选(另立预注册,不采用)" if (same_sign and strict)
                              else "描述,不是预测")

    res["prediction"] = pred
    res["candidates"] = [k for k, v in pred.items() if v["candidate"]]
    res["candidates_loose_reading"] = [k for k, v in pred.items() if v["candidate_loose"]]
    # 每个候选两段的双尾置换 p(= min(分位, 1−分位);400 次抽样 ⇒ 分辨率 1/400 = 0.0025)
    res["candidate_tail_p"] = {k: {s: (round(tail_p(v.get(s, {}).get("perm_pct")), 4)
                                     if tail_p(v.get(s, {}).get("perm_pct")) is not None else None)
                                     for s in ("A", "B")}
                               for k, v in pred.items() if v["candidate"]}
    res["candidates_surviving_paired_permutation"] = [
        k for k, v in res["candidate_tail_p"].items()
        if all(p is not None and p <= 0.05 for p in v.values())]

    # ---- 组级情绪:日期级序列,没有同日横截面可打乱 ⇒ 本卡不给它配对零分布 ----
    sent = {}
    for gname, series, fn, labs in (("加密", fng, t171.sentiment_label_crypto,
                                     [t171.S_GREED, t171.S_FEAR, t171.S_NEUT]),
                                    ("传统", vix, t171.sentiment_label_trad,
                                     [t171.S_TENSE, t171.S_CALM, "VIX 中性"])):
        P, cal = panels[gname], panels[gname]["cal"]
        cur, filled, vals = None, 0, []
        for d in cal:
            if d in series:
                cur = series[d]
            else:
                filled += 1
            vals.append(cur)
        uncond = [P["ew_fwd"][i] for i in range(len(cal))
                  if P["ew_fwd"][i] is not None and math.isfinite(P["ew_fwd"][i])]
        tu, nu, mu = t171.t_stat(uncond)
        per_lab = {}
        for lab in labs:
            xs = [P["ew_fwd"][i] for i in range(len(cal)) if vals[i] is not None
                  and fn(vals[i]) == lab and P["ew_fwd"][i] is not None
                  and math.isfinite(P["ew_fwd"][i])]
            t, n, m = t171.t_stat(xs)
            per_lab[lab] = {"mean_ew_fwd": round(m, 6) if m == m else None,
                            "t": round(t, 3) if t == t else None, "n": n,
                            "excess_vs_uncond": (round(m - mu, 6) if (m == m and mu == mu) else None),
                            "perm_pct": None}
        sent[gname] = {"uncond_mean_ew_fwd": round(mu, 6) if mu == mu else None,
                       "uncond_t": round(tu, 3) if tu == tu else None, "n": nu,
                       "macro_fill_forward_days": filled, "labels": per_lab}
    res["sentiment_group_level"] = sent
    res["sentiment_note"] = (
        "情绪是日期级标签、当日只有一条组等权收益,没有同日横截面 ⇒ shuffle_within(groups=date) "
        "退化成不打乱(每组 1 个元素),本卡不给它配对分位;T-171 的块置换同样空转(perm_p=None)。"
        "日期级序列要有意义的零分布,需要装置里另有一个设备(例如带符号翻转的平稳自助法),"
        "已写进最终回复 @seth,没有另起炉灶。")

    out = os.path.join(HERE, "t174_results.json")
    open(out, "w").write(json.dumps(res, ensure_ascii=False, indent=2))
    mroot = os.path.join(ROOT, "_reports", "absorb_input")
    os.makedirs(mroot, exist_ok=True)
    open(os.path.join(mroot, "T-174_s669_rework_results.json"), "w").write(
        json.dumps(res, ensure_ascii=False, indent=2))
    print("→", out)
    print("候选(S-669 判法):", res["candidates"] or "无")
    print("候选里过配对置换的:", res["candidates_surviving_paired_permutation"] or "无")
    return res


if __name__ == "__main__":
    main()