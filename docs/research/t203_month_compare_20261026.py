#!/usr/bin/env python3
"""T-203:交回后逐月对数(A 道 docs/research/s688_results.json vs B 道 docs/research/t203_results.json)。

交付(commit+push)之后才读 A 道文件 —— 独立性在交付前保持。
逐月比到 1e-6(S-688 台账要求「每个月的月均 ρ 到 1e-6」)。
"""
import json, sys

A = json.load(open("docs/research/s688_results.json"))
B = json.load(open("docs/research/t203_results.json"))

PAIRS = [
    ("fr_adj", ("terms", "fr_adj"), ("funding_term",)),
    ("diag_fr_level", ("terms", "diag_fr_level"), ("diagnostics", "funding_level_ic")),
    ("diag_oi_ratio", ("terms", "diag_oi_ratio"), ("diagnostics", "oi_mcap_ratio_ic")),
]


def dig(d, path):
    for p in path:
        d = d.get(p) or {}
    return d


def monthly_of(block, field="rho"):
    """A 道:months[月] = {'rho':…, 'prho':…, 'n_days':…};B 道:monthly[月] = 标量。"""
    v = block.get("monthly")
    if isinstance(v, dict):
        return {k: (x.get(field) if isinstance(x, dict) else x) for k, x in v.items()}
    v = block.get("months")
    if isinstance(v, dict):
        return {k: (x.get(field) if isinstance(x, dict) else x) for k, x in v.items()}
    return {}


def flat(block):
    """A 道的月序列块(每月一个 dict)"""
    v = block.get("months")
    return v if isinstance(v, dict) else {}


out = {"task": "T-203", "compare": "A 道 docs/research/s688_results.json vs B 道 docs/research/t203_results.json",
       "a_computed_at": A.get("computed_at"), "b_generated_at": B.get("generated_at_utc"),
       "a_panel": A.get("panel"), "b_panel": B.get("data", {}).get("panel_range"),
       "items": {}}

for name, pa, pb in PAIRS:
    ba, bb = dig(A, pa), dig(B, pb)
    ma, mb = monthly_of(ba, "rho"), monthly_of(bb, "rho")
    keys = sorted(set(ma) | set(mb))
    diffs = []
    for k in keys:
        va, vb = ma.get(k), mb.get(k)
        if va is None or vb is None:
            diffs.append({"month": k, "a": va, "b": vb, "delta": None})
        else:
            d = abs(float(va) - float(vb))
            if d > 1e-9:
                diffs.append({"month": k, "a": round(float(va), 6), "b": round(float(vb), 6),
                              "delta": round(float(vb) - float(va), 12)})
    n_cmp = sum(1 for k in keys if ma.get(k) is not None and mb.get(k) is not None)
    worst = max((abs(float(ma[k]) - float(mb[k])) for k in keys
                 if ma.get(k) is not None and mb.get(k) is not None), default=None)
    print("%-16s 月数 A/B=%d/%d 可比 %d 最大逐月差 %s 超出 1e-6 的月 %d"
          % (name, len(ma), len(mb), n_cmp, ("%.3e" % worst) if worst is not None else "—", len(diffs)))
    for d in diffs[:6]:
        print("   ", d)
    out["items"][name] = {
        "a_months_n": len(ma), "b_months_n": len(mb), "comparable": n_cmp,
        "max_abs_monthly_diff": worst,
        "months_over_1e_6": len(diffs),
        "mismatch_sample": diffs[:20],
        "a_summary": {k: ba.get(k) for k in ("mean_rho", "t", "n_months", "monthly_sd")
                       if k in ba},
        "b_summary": {k: bb.get(k) for k in ("mean_rho", "t", "n_months", "monthly_sd")
                       if k in bb},
    }

# 偏相关(A 道 prho)对 B 道:诊断 r 的偏相关(控分数);fr_adj 的偏相关是循环统计量(A 道已标 N/A)
a_ratio = dig(A, ("terms", "diag_oi_ratio"))
m_a = monthly_of(a_ratio, "prho")
m_b = monthly_of(dig(B, ("diagnostics", "oi_mcap_ratio_partial_corr")), "rho")
keys = sorted(set(m_a) & set(m_b))
worst = max((abs(float(m_a[k]) - float(m_b[k])) for k in keys
             if m_a.get(k) is not None and m_b.get(k) is not None), default=None)
over = [k for k in keys if m_a.get(k) is not None and m_b.get(k) is not None
        and abs(float(m_a[k]) - float(m_b[k])) > 1e-9]
print("\n诊断 r 的偏相关(控分数):可逐月比 %d 个月,最大差 %s,超出 1e-6 的月 %d"
      % (len(keys), ("%.3e" % worst) if worst is not None else "—", len(over)))
for k in over[:8]:
    print("   ", k, m_a[k], m_b[k])
out["partial_diag_oi_ratio"] = {"comparable": len(keys),
                                "max_abs_monthly_diff": worst,
                                "months_over_1e_6": len(over),
                                "mismatch_sample": [{"month": k, "a": m_a[k], "b": m_b[k]} for k in over[:20]]}

# OI 项:A 道判定「不可检验」的同一口径
print("\nA oi_adj:", json.dumps(A.get("oi_adj"), ensure_ascii=False)[:300])
print("B oi_term:", json.dumps({k: B.get("oi_term", {}).get(k) for k in
                                 ("n_months", "mean_rho", "t", "verdict")}, ensure_ascii=False))
out["oi_adj"] = {"a": A.get("oi_adj"),
                 "b": {k: B.get("oi_term", {}).get(k) for k in ("n_months", "mean_rho", "t", "verdict")}}

with open("docs/research/t203_month_compare.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("\nwrote docs/research/t203_month_compare.json")
