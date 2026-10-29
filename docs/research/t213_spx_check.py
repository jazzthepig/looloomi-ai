"""T-213 附加诊断:SPY(ETF, eodhd) vs SPX(指数, FRED) 的逐日偏离到底长什么样。

问题:基线报出全窗口逐日 TE 2.610%(corr 0.9913),比「同一只 ETF 两个数据源」的
0.851% 大一个量级。要确认这是真实的数据差异(股息除权/费用/口径)还是某几天的
坏数据 ⇒ 把最大的 15 个 |r_ETF − r_IDX| 日打印出来。

只读:不写库、不下单。输出留证在 t213_spx_check.json。
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.dirname(__file__))

from t210_tracking import supabase_ohlcv, fetch_spx_series  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "t213_spx_check.json")


def main():
    spy, srcs, _ = supabase_ohlcv("SPY")
    spx, attempts, spx_src = fetch_spx_series()
    dates = sorted(set(spy) & set(spx))
    rows = []
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        r_etf = spy[d1] / spy[d0] - 1.0
        r_idx = spx[d1] / spx[d0] - 1.0
        rows.append({"d0": d0, "d1": d1, "r_etf": r_etf, "r_idx": r_idx,
                     "diff": r_etf - r_idx})
    rows.sort(key=lambda x: -abs(x["diff"]))
    out = {
        "spy_sources": srcs,
        "spx_source": spx_src,
        "spx_fetch_attempts": attempts,
        "n_common_days": len(dates),
        "first_day": dates[0], "last_day": dates[-1],
        "top_abs_diffs": [
            {**r, "diff_bps": round(r["diff"] * 10000, 2),
             "r_etf_pct": round(r["r_etf"] * 100, 4),
             "r_idx_pct": round(r["r_idx"] * 100, 4)}
            for r in rows[:15]
        ],
        "median_abs_diff_bps": round(
            sorted(abs(r["diff"]) for r in rows)[len(rows) // 2] * 10000, 2),
        "n_days_abs_diff_gt_20bps": sum(1 for r in rows if abs(r["diff"]) > 0.002),
        "n_days_abs_diff_gt_50bps": sum(1 for r in rows if abs(r["diff"]) > 0.005),
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("common days", len(dates), "->", OUT)
    for r in out["top_abs_diffs"]:
        print(f"  {r['d1']} diff {r['diff_bps']:+.2f}bps  etf {r['r_etf_pct']:+.4f}%  "
              f"idx {r['r_idx_pct']:+.4f}%")
    print("  median |diff| bps:", out["median_abs_diff_bps"],
          "| days >20bps:", out["n_days_abs_diff_gt_20bps"],
          "| days >50bps:", out["n_days_abs_diff_gt_50bps"])


if __name__ == "__main__":
    main()
