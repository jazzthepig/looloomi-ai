"""T-097 A/B:每条回放臂对 ①(cap_uncapped)做同日期配对比较 —— 块自助置信区间、单侧 p、最小可检出效应。

用法:python3 docs/research/t097_ab_replay.py [序列目录]
序列来自公开接口 /api/v1/portfolio/series(回放行 = 按时点模拟,不是交易记录);目录里有 s_<arm>.json 就读文件,
没有就去接口取。只用 src/data/evaluation/apparatus.py 的 ab_test —— 不在这里另写零分布。
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test, windows  # noqa: E402

BASE = "https://looloomi.ai/api/v1/portfolio/series"
A = ("core_variants_daily", "cap_uncapped")
ARMS = [
    ("core_variants_daily", "btc", "① 换成 BTC"),
    ("core_variants_daily", "cap_c40", "① 单币 ≤ 40%(旧 ①)"),
    ("cis_tilt_daily", "cis_a1_u_replay", "② CIS 倾斜"),
    ("core_variants_daily", "mom90", "② 90 日动量加权"),
    ("multiplier_daily", "mult_v2_replay", "③ 推力 0.7–1.3"),
    ("portfolio_layer_daily", "pl_v3_replay", "组合层 0–1"),
    ("core_variants_daily", "broad_mom30_breadth", "宽宇宙动量 × 宽度"),
    ("meta_allocator_daily", "meta_knn", "类比元配置"),
]
CUTS = ["2023-01-01", "2025-01-01"]


def load(table: str, arm: str, folder: Path | None) -> dict[str, float]:
    f = folder / f"s_{arm}.json" if folder else None
    if f and f.exists():
        data = json.loads(f.read_text())
    else:
        with urllib.request.urlopen(f"{BASE}?table={table}&arm={arm}&start=2023-01-01", timeout=60) as r:
            data = json.loads(r.read())
    rows = data.get("rows") or []
    return {str(d)[:10]: (float(ret) if ret is not None else float("nan")) for d, ret, _nav in rows}


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    a = load(*A, folder)
    out = []
    for table, arm, label in ARMS:
        b = load(table, arm, folder)
        dates = sorted(set(a) & set(b))
        ra = [a[d] for d in dates]
        rb = [b[d] for d in dates]
        res = {"arm": arm, "label": label, "windows": {}}
        res["windows"]["all"] = ab_test(ra, rb, seed=97)
        for name, mask in windows(dates, CUTS):
            res["windows"][name] = ab_test([x for x, m in zip(ra, mask) if m], [x for x, m in zip(rb, mask) if m], seed=97)
        out.append(res)
        for w, r in res["windows"].items():
            if r.get("verdict") == "不可算":
                print(f"{label:22s} {w:26s} 不可算 ({r.get('why')})")
                continue
            lo, hi = r["ci95_log_diff"]
            print(f"{label:22s} {w:26s} ① {r['cum_a']:+8.1%}  B {r['cum_b']:+8.1%}  "
                  f"B/A {r['ratio_b_over_a']:.2f}  95%CI x[{2.718281828**lo:.2f}, {2.718281828**hi:.2f}]  "
                  f"p(B≤A) {r['p_b_le_a']:.2f}  MDE/年 {r['mde_log_diff_per_year']:+.0%}  {r['verdict']}"
                  f"{'  功效不足' if r['underpowered'] else ''}")
    (ROOT / "docs" / "research" / "t097_ab_replay_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
