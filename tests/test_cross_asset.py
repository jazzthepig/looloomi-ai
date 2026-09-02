"""跨资产分位/相关的守卫 (S-274)。

这个文件里只有一条真正重要的断言:

    **一个分位数不带窗口就不许发出去。**

因为「窗口的选择就是结论」不是修辞 —— 实测 2026-09-02:GLD/UUP 在一年窗口是
43 分位、在十一年窗口是 95 分位。**同一个价格,52 个百分点的差,纯粹来自窗口。**

第二条:**spread 大 ≠ 数据脏。** 它也可能是切点没找对。Jazz 指出 2019 是新周期
起点后,同一批数据的 spread 从 0.52 掉到 0.033 —— 那个 spread 是体制边界,
是信息不是噪声。所以 `percentile_since` 必须存在,且必须把「最早锚点之前」
那段单列出来而不是平均进去。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.cross_asset import (                     # noqa: E402
    MIN_OBS, NO_DATA, REGIME_ANCHORS, ROBUST, SPREAD_SENSITIVE, THIN,
    WINDOW_SENSITIVE, _pct_rank, percentile, percentile_since,
    relative_value, rolling_corr,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_one_window_is_refused_because_it_has_no_spread():
    """**本文件的理由。** 单窗口的分位数看起来最干净,而它恰恰最不可信 ——
    它把「窗口」这个假设藏进了实现里,读的人无从知道它有多脆。"""
    s = list(range(100)) + [50]          # 够 1 个 252 窗口以下的窗口
    r = percentile(s, windows=(252,))
    _check("只有一个窗口 → THIN 而不是给一个数", r.verdict == THIN, r.verdict)
    _check("原因点破「单窗口没有 spread」", "spread" in r.reason, r.reason)

    r2 = percentile(s, windows=(80, 100))
    _check("两个窗口 → 给得出裁决", r2.verdict in (ROBUST, WINDOW_SENSITIVE),
           r2.verdict)
    _check("spread 被算出来", r2.spread is not None, str(r2.spread))


def t_spread_separates_robust_from_window_selected():
    """判别性:必须有一个案例判 robust、另一个判 window_sensitive。
    两个都判同一边的话,这个门槛就没有在做事。"""
    # 稳健:值一直在同一个相对位置
    flat = [10.0 + (i % 7) * 0.01 for i in range(3000)]
    r_flat = percentile(flat, windows=(252, 1260, 2520))
    _check("平稳序列 → robust", r_flat.verdict == ROBUST,
           f"{r_flat.verdict} spread={r_flat.spread}")

    # 敏感:**照实测的形状造** —— 今天在新体制里是中位,但高于旧体制的全部。
    #
    # ⚠️ 我第一版把今天造在了新体制的**顶部**,于是每个窗口都读到 99%、
    # spread 0.004,测试失败。那不是模块不灵,是**我编的数据没有实测的形状**。
    # 实测(GLD/UUP)是:1 年 43%、11 年 95% —— 中位 vs 高位,不是高位 vs 高位。
    # 拿臆想的形状当夹具,测的就是臆想。
    old = [1.0 + i * 0.001 for i in range(2000)]        # 旧体制,全部低
    new = [50.0 + (i % 100) * 0.5 for i in range(999)]  # 新体制 50–99.5
    shifted = old + new + [75.0]                        # 今天 = 新体制的中位
    r_sh = percentile(shifted, windows=(252, 1260, 2520))
    _check("有体制跳变的序列 → window_sensitive",
           r_sh.verdict == WINDOW_SENSITIVE,
           f"{r_sh.verdict} spread={r_sh.spread}")
    _check(f"两个案例判到了不同边(门槛 {SPREAD_SENSITIVE} 在做事)",
           r_flat.verdict != r_sh.verdict)
    _check("敏感那个的 reason 要求「连窗口一起报」",
           "连窗口一起报" in r_sh.reason, r_sh.reason)


def t_the_pre_anchor_era_is_reported_separately_not_averaged_in():
    """**实测咬到的那条(2026-09-02)。**

    三个黄金比价对 2019 前的分位是 **100.0%** —— 不是 99.9%。
    100.0% 不是一个分位数,它是一句「这段历史对当下零信息量」。
    把它平均进总窗口,只会把结论稀释成一个谁也不信的中间数。
    """
    dated = [(f"201{y}-06-{d:02d}", 1.0) for y in range(5, 9) for d in range(1, 29)]
    dated += [(f"202{y}-06-{d:02d}", 5.0 + (d % 10) * 0.1)
              for y in range(0, 7) for d in range(1, 29)]
    r = percentile_since(dated)
    _check("最早锚点之前那段被单列", "pre_earliest_anchor" in r,
           str(sorted(r.keys())))
    _check("那段确实是 100%(今天高于它的全部)",
           r["pre_earliest_anchor"] is not None and r["pre_earliest_anchor"] >= 0.999,
           str(r["pre_earliest_anchor"]))
    _check("reason 明说它零信息量、不该平均进来",
           "零信息量" in r["reason"], r["reason"][:120])
    _check("锚点窗口自己给出了裁决", r["verdict"] in (ROBUST, WINDOW_SENSITIVE, THIN),
           r["verdict"])

    # 判别性:若今天不是高于 2019 前的全部,就不该挂那句警告
    dated_mid = [(d, v) for d, v in dated]
    dated_mid[-1] = (dated_mid[-1][0], 0.5)      # 今天很低
    r2 = percentile_since(dated_mid)
    _check("今天不再高于旧体制全部时,不挂那句警告",
           "零信息量" not in r2["reason"], r2["reason"][:120])


def t_anchors_are_dates_not_day_counts():
    """一个滚动天数是任意的;`2019-01-01` 是可辩护的。"""
    _check("锚点是日期字符串", all(isinstance(v, str) and len(v) == 10
                                for v in REGIME_ANCHORS.values()),
           str(REGIME_ANCHORS))
    _check("2019 起点在里面", "2019-01-01" in REGIME_ANCHORS.values(),
           str(REGIME_ANCHORS))
    _check("多于一个锚点(否则同样没有 spread)", len(REGIME_ANCHORS) >= 2,
           str(len(REGIME_ANCHORS)))


def t_correlation_reports_the_range_because_the_mean_is_the_erased_number():
    """十年一个相关系数会把 +0.6 与 −0.3 抹成 +0.1 ——
    **而那个 +0.1 在任何一段真实时期里都没有出现过。**"""
    import math
    n = 800
    a = [math.sin(i / 9.0) for i in range(n)]
    # 前半同向、后半反向
    b = [a[i] if i < n // 2 else -a[i] for i in range(n)]
    r = rolling_corr(a, b, window=60)
    _check("符号翻转被数出来", r.sign_flips >= 1, str(r.sign_flips))
    _check("区间跨过 0(正负都出现过)", r.lo < 0 < r.hi, f"[{r.lo}, {r.hi}]")
    _check("区间宽度 > 1.0(被均值抹掉的就是这个)", r.range > 1.0, str(r.range))
    _check("均值落在一个从未真正持续出现的中间带",
           abs(r.mean) < 0.5 and r.range > 1.0,
           f"mean={r.mean} range={r.range}")
    _check("reason 明说均值只作参考", "只作参考" in r.reason, r.reason[:100])

    short = rolling_corr([1.0, 2.0], [1.0, 2.0], window=60)
    _check("样本不足 → latest 是 None 而不是 0", short.latest is None)


def t_a_value_equal_to_the_max_is_not_unprecedented():
    """纯 `<` 会让「并列最高」报成 1.0,读起来像「史无前例」。"""
    s = [1.0] * 50 + [2.0] * 50            # 100 个观测,今天 = 最大值
    p = _pct_rank(s, 2.0)
    _check("并列最高 → 0.75 而不是 1.0", p is not None and 0.7 < p < 0.8, str(p))
    p_above = _pct_rank(s, 3.0)
    _check("真的高于全部 → 1.0", p_above == 1.0, str(p_above))
    _check("两者可分(中点法在做事)", p != p_above, f"{p} vs {p_above}")


def t_short_series_gives_none_not_a_fragile_number():
    _check(f"少于 {MIN_OBS} 个观测 → None", _pct_rank([1.0] * 10, 1.0) is None)
    r = percentile([], windows=(252, 756))
    _check("空序列 → NO_DATA", r.verdict == NO_DATA, r.verdict)
    _check("空序列的 spread 是 None 而不是 0", r.spread is None)


def t_relative_value_declares_it_is_not_intrinsic_value():
    """比价法的边界必须随结果一起走,否则下游会把它当成估值。"""
    a = [10.0 + i * 0.01 for i in range(3000)]
    b = [5.0] * 3000
    rv = relative_value(a, b)
    _check("scope 写明不是内在价值", "不是相对于内在价值" in rv["scope"], rv["scope"])
    _check("给的是按窗口的一组分位,不是一个数",
           len(rv["percentile_by_window"]) >= 2, str(rv["percentile_by_window"]))
    _check("spread 随结果一起给", "spread" in rv, str(sorted(rv.keys())))


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
