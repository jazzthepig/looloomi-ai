"""regime 配额层的守卫 (S-263)。

每条断言都要能**单独失败**。这个文件里最重要的两条不是「五个裁决都能触发」,
而是:

  · **当天那行不参与裁决** —— 09-01 上午 `n_obs=86` vs 基线 1450 = 6%。
    不隔离它,每天早上都会误报一次 COLLAPSED,而误报的代价是下游拒绝定仓。
  · **基线窗口排除近端** —— 慢速塌陷会把自己的基线拖下去。用「已经塌了 20 天」
    的序列验:近端基线判 ok(错),排除近端的基线判 COLLAPSED(对)。

两条都是「两个状态长得一样」的实例,而两次的区分手段都不是数值本身 ——
一次是日期,一次是取基线的窗口。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.regime_quorum import (            # noqa: E402
    COLLAPSED, FROZEN, NO_BASELINE, NO_DATA, OK, THIN,
    SELECT_COLS, classify, longest_prior_run,
)

_FAIL: list[str] = []
TODAY = dt.date(2026, 9, 1)


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _series(spec):
    """spec = [(起始日偏移, 天数, regime, n_obs, n_sources), ...],偏移相对 TODAY。"""
    out = []
    for off, n, g, o, s in spec:
        for i in range(n):
            out.append({"d": (TODAY - dt.timedelta(days=off - i)).isoformat(),
                        "regime": g, "n_obs": o, "n_sources": s})
    return sorted(out, key=lambda r: r["d"])


# ── 真实序列(2026-06-19 → 09-01,取自 Supabase daily_macro_regime)────────
REAL = [
    ("2026-06-19", "TIGHTENING", 1661, 3), ("2026-06-20", "TIGHTENING", 2317, 3),
    ("2026-06-21", "RISK_OFF", 1450, 2), ("2026-06-22", "RISK_OFF", 1450, 2),
    ("2026-06-23", "RISK_OFF", 1334, 2), ("2026-06-24", "TIGHTENING", 928, 3),
    ("2026-06-25", "TIGHTENING", 1508, 3), ("2026-06-30", "TIGHTENING", 1624, 3),
    ("2026-07-05", "TIGHTENING", 1553, 3), ("2026-07-10", "TIGHTENING", 1450, 3),
    ("2026-07-15", "TIGHTENING", 1710, 3), ("2026-07-18", "TIGHTENING", 1306, 3),
    ("2026-07-19", "NEUTRAL", 1276, 2), ("2026-07-20", "NEUTRAL", 1856, 2),
    ("2026-07-21", "RISK_OFF", 1566, 2), ("2026-07-22", "NEUTRAL", 1914, 2),
    ("2026-07-25", "RISK_OFF", 1450, 2), ("2026-07-26", "RISK_OFF", 1392, 2),
    ("2026-07-27", "TIGHTENING", 913, 3), ("2026-07-31", "TIGHTENING", 1450, 3),
    ("2026-08-03", "TIGHTENING", 1075, 2), ("2026-08-06", "TIGHTENING", 1388, 3),
    ("2026-08-09", "TIGHTENING", 1553, 3), ("2026-08-12", "TIGHTENING", 1059, 3),
    ("2026-08-15", "TIGHTENING", 971, 3), ("2026-08-17", "TIGHTENING", 1032, 1),
    ("2026-08-19", "TIGHTENING", 1564, 3), ("2026-08-21", "TIGHTENING", 1032, 1),
    ("2026-08-23", "TIGHTENING", 1264, 2), ("2026-08-26", "TIGHTENING", 1133, 2),
    ("2026-08-29", "TIGHTENING", 733, 2), ("2026-08-31", "TIGHTENING", 1090, 2),
    ("2026-09-01", "TIGHTENING", 86, 1),
]
REAL_ROWS = [{"d": d, "regime": g, "n_obs": o, "n_sources": s} for d, g, o, s in REAL]


def t_partial_day_is_excluded_from_the_verdict():
    """**这条最重要。** 09-01 的 86 票是「今天还没写完」,不是「面板塌了」。"""
    q = classify(REAL_ROWS, today=TODAY)
    _check("裁决落在最新的【完整】一天上,不是今天",
           q.d == "2026-08-31", f"判到了 {q.d}")
    _check("今天那行的数字仍被带出来(不是丢掉)",
           q.partial_today == ("2026-09-01", "TIGHTENING", 86, 1), str(q.partial_today))
    _check("裁决不是 COLLAPSED(86/1450 = 6% 会误触发)",
           q.verdict != COLLAPSED, f"{q.verdict}: {q.reason}")

    # 判别性:把同一批数据的日期整体前移一天,今天那行就变成「完整的一天」,
    # 于是同样的 86 票必须判 COLLAPSED。**同一个数,不同的日期,不同的裁决。**
    q2 = classify(REAL_ROWS, today=TODAY + dt.timedelta(days=1))
    _check("同样的 86 票,一旦它成为完整的一天 → COLLAPSED",
           q2.verdict == COLLAPSED and q2.d == "2026-09-01",
           f"{q2.verdict} @ {q2.d}: {q2.reason}")


def t_real_series_reads_thin_not_ok():
    """真实数据今天的诚实读数。锁住它,免得下次「变好」是因为判据松了。"""
    q = classify(REAL_ROWS, today=TODAY)
    _check("真实序列判 thin(信源 2 < 基线 3)", q.verdict == THIN,
           f"{q.verdict}: {q.reason}")
    _check("基线信源数是 3(从 6 月的那段算出来,不是从正在变薄的近端)",
           q.baseline_sources == 3, str(q.baseline_sources))
    _check("thin 仍算可用(2 个信源不是独裁)", q.usable is True)
    _check("标签本身照常带出(不可信 ≠ 抹掉)", q.regime == "TIGHTENING", str(q.regime))


def t_single_source_majority_is_collapsed():
    """1 个信源的『全票通过』不是共识。"""
    rows = _series([(70, 40, "TIGHTENING", 1500, 3), (30, 30, "TIGHTENING", 1500, 1)])
    q = classify(rows, today=TODAY)
    _check("信源 1 而基线 3 → COLLAPSED", q.verdict == COLLAPSED,
           f"{q.verdict}: {q.reason}")
    _check("原因点明是减员不是共识", "减员" in q.reason, q.reason)
    _check("COLLAPSED 不可用", q.usable is False)


def t_vote_count_collapse_is_caught_even_with_sources_intact():
    """信源数没变,但投票的资产少了一半 —— 众数不再代表这个面板。"""
    rows = _series([(70, 40, "TIGHTENING", 1500, 3), (30, 30, "TIGHTENING", 400, 3)])
    q = classify(rows, today=TODAY)
    _check("票数 400 < 基线 1500 的 50% → COLLAPSED", q.verdict == COLLAPSED,
           f"{q.verdict}: {q.reason}")


def t_baseline_excludes_the_recent_window():
    """**慢速塌陷不能把自己的基线拖下去。**

    序列:早期 3 信源,最近 25 天只剩 1。如果基线取「最近 30 天中位数」,
    中位数本身就是 1,`src_now(1) >= b_src(1)` → 判 ok,永远不触发。
    """
    rows = _series([(70, 45, "TIGHTENING", 1500, 3), (25, 25, "TIGHTENING", 1500, 1)])
    q = classify(rows, today=TODAY)
    _check("已塌陷 25 天仍判 COLLAPSED(基线来自更早的窗口)",
           q.verdict == COLLAPSED, f"{q.verdict}: {q.reason}")
    _check("基线信源数是塌陷【之前】的 3", q.baseline_sources == 3,
           str(q.baseline_sources))

    # 判别性:直接对比两个窗口的中位数。这才是那句话的内容 ——
    # 「近端基线会判错」不是关于某个切片的裁决,是关于**中位数取自哪一段**。
    #
    # ⚠️ 初版把它写成「只喂最近 30 天 → 不该触发」,跑出来照样 COLLAPSED:
    # 那 30 天里还含 5 天塌陷前的数据,中位数是 2,门槛仍然过得去。
    # **我又写了一个听起来合理、没核过的断言**(S-262 同一课)。
    import statistics
    recent = [r["n_sources"] for r in rows
              if r["d"] >= (TODAY - dt.timedelta(days=20)).isoformat()]
    naive_baseline = statistics.median(recent)
    _check(f"近端 20 天的中位信源数 = {naive_baseline:g}(全是塌陷后的)",
           naive_baseline == 1, str(naive_baseline))
    _check("拿近端当基线 → 1 >= 2 不成立 → 永远不触发",
           not (naive_baseline >= 2), f"naive={naive_baseline:g}")
    _check(f"排除近端的基线 = {q.baseline_sources:g},两者差 {3 - naive_baseline:g} —— "
           f"差别来自窗口,不来自数值", q.baseline_sources > naive_baseline)


def t_frozen_uses_longest_prior_run_not_median_flip_interval():
    """停留时长要跟『这个面板见过多长的段』比,不是跟『平均多久翻一次』比。"""
    ser = [(d, g) for d, g, _o, _s in REAL]
    lpr = longest_prior_run(ser)
    _check(f"历史最长段 = {lpr} 天(排除进行中的那一段)",
           lpr is not None and 20 <= lpr <= 30, str(lpr))

    # 进行中的段不得计入自己的基线,否则判据永远不触发。
    all_one = [("2026-01-%02d" % i, "TIGHTENING") for i in range(1, 29)]
    _check("全程一个标签 → 没有已完成的段可比(None,不是 27)",
           longest_prior_run(all_one) is None, str(longest_prior_run(all_one)))

    # 明显长于任何先例 → frozen。
    rows = _series([(300, 10, "NEUTRAL", 1500, 3), (290, 8, "RISK_OFF", 1500, 3),
                    (282, 283, "TIGHTENING", 1500, 3)])   # 长段一直到今天
    q = classify(rows, today=TODAY)
    _check("282 天的段 vs 先例 ~9 天 → frozen", q.verdict == FROZEN,
           f"{q.verdict}: {q.reason}")
    _check("frozen 不可用", q.usable is False)
    _check("原因承认两种可能都存在(判断 / 输入死了)",
           "也可能" in q.reason, q.reason)


def t_absent_measurement_is_not_health():
    """`no_baseline` 与 `ok` 必须分开 (S-246)。"""
    q = classify(_series([(5, 5, "TIGHTENING", 1500, 3)]), today=TODAY)
    _check("历史不足 → no_baseline,不是 ok", q.verdict == NO_BASELINE,
           f"{q.verdict}: {q.reason}")
    _check("no_baseline 不可用(没量过 ≠ 健康)", q.usable is False)
    _check("空输入 → no_data,与 no_baseline 也不同",
           classify([], today=TODAY).verdict == NO_DATA)


def t_healthy_series_reads_ok():
    """判据必须能给出 ok,否则它只是一个永远说不的东西。"""
    rows = _series([(70, 35, "TIGHTENING", 1500, 3), (35, 20, "NEUTRAL", 1500, 3),
                    (15, 15, "TIGHTENING", 1500, 3)])
    q = classify(rows, today=TODAY)
    _check("信源票数都在基线上 + 段长正常 → ok", q.verdict == OK,
           f"{q.verdict}: {q.reason}")
    _check("ok 可用", q.usable is True)


def t_select_cols_carries_the_vote_columns():
    """列清单集中在一处 —— 「只取 d,regime」正是本模块要修的 bug。"""
    for col in ("d", "regime", "n_obs", "n_sources"):
        _check(f"SELECT_COLS 含 {col}", col in SELECT_COLS, SELECT_COLS)


if __name__ == "__main__":
    print("── regime 配额层守卫 (S-263) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ regime 配额层守卫全绿")
