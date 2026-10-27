"""S-690 附记一(台账,预注册 2026-10-27 14:11 UTC):真钱进场时只看得到 d−1 的 OI 归档 —— 滞后版截面还灵不灵。

输入:s690_lag_bits.json —— 每个 (symbol, signal_d)(按 signal_d、symbol 的 C 序排)一位:
'1' = 该滞后下 p ≥ 2/3,'0' = p < 2/3,'-' = 不在截面。lag 0 与 s690_p.txt 的 H 逐张一致(核过,0 处不同)。
SQL = s690_rv2_oi_filter.sql 的 cs 段换成 `o.d + lag`(OI 与市值都取 d − lag 当天),同一口径。
判据:(a) 差 ≤ −0.40R;(b) 月块自助 P(差 ≥ 0) < 0.05;(c) 两个半段差都为负。
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from s690_rv2_oi_filter import run  # noqa: E402


def p_file(pairs, bits) -> Path:
    toks = [f"{s}|{d}|{'' if c == '-' else ('1' if c == '1' else '0')}||true" for (s, d), c in zip(pairs, bits)]
    f = Path(tempfile.mkstemp(suffix=".txt")[1])
    f.write_text(";".join(toks))
    return f


def main():
    src = json.load(open(HERE / "s690_lag_bits.json"))
    pairs = [tuple(p) for p in src["pairs"]]
    out = {}
    for lag, bits in sorted(src["bits"].items()):
        r = run(p_file(pairs, bits))
        a = r["diff_mean_r"] <= -0.40
        b = r["boot_p_diff_ge0"] < 0.05
        c = all(h["diff"] is not None and h["diff"] < 0 for h in r["halves"].values())
        out[lag] = {k: v for k, v in r.items() if k not in ("tickets", "verdict", "spearman_p_vs_r")}
        out[lag]["verdict_addendum"] = {"a_diff_le_-0.40": a, "b_boot_p_lt_005": b, "c_both_halves_neg": c, "pass": a and b and c}
    b0, b1 = src["bits"]["0"], src["bits"]["1"]
    both = [(x, y) for x, y in zip(b0, b1) if x != "-" and y != "-"]
    out["agreement_lag1_vs_lag0"] = {"n_both": len(both), "same": sum(x == y for x, y in both),
                                     "H0_to_L1": sum(x == "1" and y == "0" for x, y in both),
                                     "L0_to_H1": sum(x == "0" and y == "1" for x, y in both)}
    json.dump(out, open(HERE / "s690_lag_results.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
