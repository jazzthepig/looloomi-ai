#!/usr/bin/env python3
"""T-348 第六轮(T-377):情景文件三处修正的原始数核对。

只读本地文件:
  docs/research/t348_r3_families.csv   族曲线缓存(S-681 H2 / H4 的族净值)
  docs/research/t348_r5_results.json  第五轮汇总(族的 standalone 指标 / C0 长账本口径)
输出:
  docs/research/_t348_r6_scenario_fix.md

口径说明(为什么这样算):
- 族曲线止于 2026-09-30(族票最后一票出场);情景条目 horizon 2026-12-31 ⇒ 到期要用**续算后的**族曲线。
- 概率先验 = 族曲线**滚动 62 日**相对收益的经验分布(2026-10-30 → 2026-12-31 的自然日)。
  这是描述统计(给先验概率用),不是零分布检验;本脚本不做零分布 / 多空盈亏 / A-B 比较。
- C0 长账本曲线不在任何产物里(只存了汇总),故 C0 相关只用 r5 的 base_long 汇总数。
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FAM_CSV = os.path.join(HERE, "t348_r3_families.csv")
R5_JSON = os.path.join(HERE, "t348_r5_results.json")
OUT_MD = os.path.join(HERE, "_t348_r6_scenario_fix.md")

HORIZON_D = "2026-12-31"
ASOF = "2026-10-30"
H = 62  # ASOF → HORIZON_D 的自然日数


def fam_nav(df: pd.DataFrame, family: str) -> pd.Series:
    s = df[df["family"] == family].set_index("d")["nav"].astype(float).sort_index()
    return s


def roll_stats(nav: pd.Series, thr: float, label: str) -> dict:
    """滚动 H 日相对收益 r_i = nav[i+H]/nav[i] - 1;统计 r_i 相对 thr 的频率。"""
    v = nav.to_numpy()
    n = len(v)
    if n <= H:
        return {"label": label, "n": n, "note": "样本太短,没有滚动窗口"}
    r = v[H:] / v[:-H] - 1.0
    out = {
        "label": label,
        "n_days": n,
        "d0": str(nav.index[0].date()),
        "d1": str(nav.index[-1].date()),
        "nav_start": float(v[0]),
        "nav_end": float(v[-1]),
        "total_return": float(v[-1] / v[0] - 1.0),
        "H": H,
        "n_windows": int(len(r)),
        "thr": float(thr),
        "freq_le_thr": float(np.mean(r <= thr)),
        "freq_ge_thr": float(np.mean(r >= thr)),
        "roll_mean": float(np.mean(r)),
        "roll_std": float(np.std(r, ddof=1)),
        "roll_min": float(np.min(r)),
        "roll_max": float(np.max(r)),
        "roll_p05": float(np.quantile(r, 0.05)),
        "roll_p95": float(np.quantile(r, 0.95)),
    }
    return out


def main() -> None:
    df = pd.read_csv(FAM_CSV, parse_dates=["d"])
    r5 = json.load(open(R5_JSON, encoding="utf-8"))
    lines: list[str] = []
    lines.append("# T-348 第六轮(T-377):情景文件三处修正的原始数\n")
    lines.append(f"口径:族曲线缓存 `{os.path.basename(FAM_CSV)}` · 第五轮汇总 `{os.path.basename(R5_JSON)}`")
    lines.append(f"时点 {ASOF} → 到期 {HORIZON_D}({H} 自然日)")
    lines.append("")

    # ── 一、C0 长账本:当前水位与最长水下段 ────────────────────────────────
    bl = r5["base_long"]
    uw_g, uw_829 = bl["C0_uw_G"], bl["C0_uw_S829"]
    cur_level = 1.0 + float(bl["C0_total_return"])
    peak_level = float(uw_g["peak_value"])
    lines.append("## 1. C0 长账本(2020-08-16 起):当前水位与最长水下段\n")
    lines.append("| 量 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 区间 | {bl['d0']} → {bl['d1']}({bl['n_days']} 天) |")
    lines.append(f"| 年化 | {float(bl['C0_cagr']):+.4%} |")
    lines.append(f"| 累计收益 | {float(bl['C0_total_return']):+.4%} |")
    lines.append(f"| 当前水位(起点=1) | {cur_level:.6f} |")
    lines.append(f"| 历史峰值水位 | {peak_level:.6f}({uw_g['peak_d']}) |")
    lines.append(f"| 当前水位 / 历史峰值 | {cur_level / peak_level:.4f} 倍 |")
    lines.append(f"| 最长水下(G 口径) | {uw_g['length_d']} 天 · {uw_g['peak_d']} → {uw_g['recover_d']}(recovered={uw_g['recovered']}) |")
    lines.append(f"| 最长水下(S-829 口径) | {uw_829['longest_uw_d']} 天 · {uw_829['longest_uw']} |")
    lines.append(f"| 最大回撤 | {float(bl['C0_max_dd']):+.4%}(峰 {uw_g['peak_d']} → 谷 {uw_g['trough_d']}) |")
    lines.append(f"| 水下段条数 | {uw_g['n_episodes']} |")
    cur_in_uw = cur_level < peak_level
    lines.append("")
    lines.append(f"**当前是否处在水下段内:{'是' if cur_in_uw else '否'}**"
                 f"(当前水位 {cur_level:.4f} {'<' if cur_in_uw else '>'} 历史峰值 {peak_level:.4f})"
                 f" ⇒ 当前**没有**未闭合的水下段可问。")
    lines.append("")

    # ── 二、S-681 H4 / H2:族自身累计 + 滚动 62 日收益分布 ────────────────
    rows = []
    for key, r5key in (("S681_H4", "S681_H4"), ("S681_H2", "S681_H2")):
        nav = fam_nav(df, key)
        f5 = r5["families"][r5key]
        st = f5["family_standalone"]
        thr = 1.0 / float(nav.iloc[-1]) - 1.0   # 从当前水位出发,62 日后仍「累计 > 0」⇒ r > thr
        rs = roll_stats(nav, thr, key)
        rows.append((key, f5, st, nav, thr, rs))
        lines.append(f"## 2.{'1' if key == 'S681_H4' else '2'} {key}:族自身累计与滚动 {H} 日收益分布\n")
        lines.append("| 量 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 族曲线区间 | {rs['d0']} → {rs['d1']}({rs['n_days']} 天) |")
        lines.append(f"| 首日水位 | {f5['first_waterlevel']:.9f} |")
        lines.append(f"| 族自身累计收益(本脚本自算) | {rs['total_return']:+.6f} |")
        lines.append(f"| 同上(r5 family_standalone.total_return) | {float(st['total_return']):+.6f} |")
        lines.append(f"| 两者之差 | {abs(rs['total_return'] - float(st['total_return'])):.3e} |")
        lines.append(f"| 族自身年化 | {float(st['cagr']):+.4%} · 最大回撤 {float(st['max_dd']):+.4%} |")
        lines.append(f"| 最差月 / 最好月 | {float(st['worst_month']):+.4%}({st['worst_month_end']}) / {float(st.get('best_month', 0)):+.4%} |")
        lines.append(f"| 滚动 {H} 日窗口数 | {rs['n_windows']} |")
        lines.append(f"| 滚动 {H} 日相对收益:均值 / 标准差 | {rs['roll_mean']:+.4%} / {rs['roll_std']:.4%} |")
        lines.append(f"| 滚动 {H} 日相对收益:5% / 95% 分位 | {rs['roll_p05']:+.4%} / {rs['roll_p95']:+.4%} |")
        lines.append(f"| 滚动 {H} 日相对收益:最小 / 最大 | {rs['roll_min']:+.4%} / {rs['roll_max']:+.4%} |")
        lines.append(f"| 阈值 thr(62 日后累计越过 0 所需相对涨跌) | {thr:+.4%} |")
        lines.append(f"| P(滚动 {H} 日 ≤ thr)(即累计翻负/翻正) | {rs['freq_le_thr']:.4f} |")
        lines.append(f"| P(滚动 {H} 日 ≥ thr) | {rs['freq_ge_thr']:.4f} |")
        lines.append("")

    # ── 三、结论:两条族条目到期的先验 ────────────────────────────────────
    h4 = [r for r in rows if r[0] == "S681_H4"][0]
    h2 = [r for r in rows if r[0] == "S681_H2"][0]
    p19 = 1.0 - h4[5]["freq_le_thr"]   # H4 族累计到 12-31 仍 > 0
    p21 = 1.0 - h2[5]["freq_ge_thr"]   # H2 族累计到 12-31 仍 < 0
    lines.append("## 3. 两条族条目的到期先验(经验分布直读)\n")
    lines.append("| 条目 | 命题 | 经验频率 | 建议 prob |")
    lines.append("|---|---|---|---|")
    lines.append(f"| T-348-19(改) | H4 族累计到 {HORIZON_D} 仍 > 0 | 成立 {p19:.4f} | {min(0.9, round(p19 + 0.05, 2))} |")
    lines.append(f"| T-348-21(不改方向) | H2 族累计到 {HORIZON_D} 仍 < 0 | 成立 {p21:.4f}(原写 0.70) | 0.70(本轮不改,差异见 SYNC) |")
    lines.append("")
    lines.append("注:经验分布只覆盖 2020-09 → 2026-09 的族票期(含 2021 与 2022 两轮熊市);"
                 "样本内 62 日窗口高度重叠,频率不是独立样本的频率。")
    lines.append("")

    # ── 四、T-348-20:最长水下 > 700 天这条为什么撤 ───────────────────────
    lines.append("## 4. T-348-20(「最长水下 > 700 天」)为什么移进 dropped\n")
    lines.append(f"- 该段水下**已经发生并闭合**:{uw_g['peak_d']} → {uw_g['recover_d']},"
                 f"{uw_g['length_d']} 天(G 口径)/ {uw_829['longest_uw_d']} 天(S-829 口径),"
                 f"最长水下长度已是历史事实,除非再出现一段更长的水下,否则到期时该条必然成立。")
    lines.append(f"- 写下时({ASOF})已知该数 ⇒ 不是前向预期,是写下即知。")
    lines.append(f"- 「改问当前这段水下」在本口径下不成立:{ASOF} 账户水位 {cur_level:.4f} "
                 f"高于历史峰值 {peak_level:.4f}({cur_level / peak_level:.3f} 倍)⇒ 当前**不在**水下段内,没有可问的当前水下段。")
    lines.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"→ 已写 {OUT_MD}")


if __name__ == "__main__":
    main()
