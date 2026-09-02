"""regime 日内颗粒度守卫 (S-270)。

两条最重要的:

  · **一致度必须与观测数一起给。** 一天只有 2 个观测时 `agreement=1.0`,
    但那不是共识,那是只有一个投票人 —— 与 S-263 的 `n_sources` 塌陷是
    同一个陷阱:**分母消失时,比例会假装自己很健康。**

  · **缺测不是一个标签。** 把 `None` 计进类别数,会把停机说成分歧,
    于是「日内两种 regime」这个计数虚增,而虚增的方向恰好是「看起来更有信息」。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.regime_granularity import (       # noqa: E402
    CONTESTED, CONTESTED_BELOW, MIN_OBS_PER_DAY, NO_DATA, THIN, UNANIMOUS,
    day_from_hours, series, summarise,
)

_FAIL: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_agreement_is_never_reported_without_its_denominator():
    """**本文件的第一理由。** 2/2 的 100% 不是共识。"""
    thin = day_from_hours("2026-09-01", ["TIGHTENING", "TIGHTENING"])
    _check("2 个观测 → THIN,即使 100% 一致", thin.verdict == THIN,
           f"{thin.verdict} agreement={thin.agreement}")
    _check("agreement 仍然给出(不可用 ≠ 抹掉)", thin.agreement == 1.0)
    _check("n_obs 一起给", thin.n_obs == 2)
    _check("原因点破「分母消失时比例会假装健康」",
           "假装健康" in thin.reason, thin.reason)
    _check("THIN 不可用", thin.usable is False)

    # 判别性:同样 100% 一致,观测够多就必须可用 —— 门槛不是永远说不。
    full = day_from_hours("2026-09-01", ["TIGHTENING"] * 24)
    _check("24 个观测且一致 → UNANIMOUS", full.verdict == UNANIMOUS, full.verdict)
    _check("UNANIMOUS 可用", full.usable is True)
    _check(f"MIN_OBS_PER_DAY = {MIN_OBS_PER_DAY} 在 2 与 24 之间(门槛真的在分界)",
           2 < MIN_OBS_PER_DAY < 24)


def t_missing_is_not_a_label():
    """缺测计进类别数 = 把停机说成分歧,而且是往「更有信息」的方向虚增。"""
    d = day_from_hours("2026-09-01", ["TIGHTENING"] * 12 + [None] * 12)
    _check("None 不进分母", d.n_obs == 12, str(d.n_obs))
    _check("None 不算一个标签", d.n_labels == 1, str(d.n_labels))
    _check("一致度按非空算 = 100%", d.agreement == 1.0, str(d.agreement))
    _check("判 UNANIMOUS 而不是 CONTESTED", d.verdict == UNANIMOUS, d.verdict)

    empty = day_from_hours("2026-09-01", [None, None, None])
    _check("全缺测 → NO_DATA", empty.verdict == NO_DATA, empty.verdict)
    _check("全缺测时 label 是 None,不是编一个", empty.label is None)
    _check("原因写明缺测不计为类别", "缺测不计为一个类别" in empty.reason, empty.reason)


def t_a_contested_day_is_information_not_a_fault():
    """27% 的日子有分歧 —— 那是信号,所以 CONTESTED 仍然可用。"""
    d = day_from_hours("2026-09-01",
                       ["TIGHTENING"] * 14 + ["NEUTRAL"] * 10)
    _check("众数占 58% < 80% → CONTESTED", d.verdict == CONTESTED,
           f"{d.verdict} {d.agreement}")
    _check("**CONTESTED 仍然可用**(它是信息不是故障)", d.usable is True)
    _check("标签仍是众数", d.label == "TIGHTENING", str(d.label))
    _check("原因点破日频众数会把它说成确定的",
           "说成确定的" in d.reason, d.reason)

    # 判别性:轻微分歧(23/24)不该报警 —— 否则这个字段永远在响。
    mild = day_from_hours("2026-09-01", ["TIGHTENING"] * 23 + ["NEUTRAL"])
    _check("23/24 的轻微分歧仍判 UNANIMOUS(门槛不是 100%)",
           mild.verdict == UNANIMOUS, f"{mild.verdict} {mild.agreement:.2f}")
    _check(f"CONTESTED_BELOW = {CONTESTED_BELOW} 严格在 (0,1) 内",
           0 < CONTESTED_BELOW < 1)


def t_churn_and_turning_are_different_shapes():
    """A→B→A 是震荡,A→B 是转折的形状 —— 日频众数两者都看不见。"""
    osc = day_from_hours("2026-09-01",
                         ["TIGHTENING"] * 8 + ["NEUTRAL"] * 8 + ["TIGHTENING"] * 8)
    _check("往返 → churn = 2", osc.churn == 2, str(osc.churn))
    _check("往返不是转折形状", osc.is_turning is False)
    _check("路径记录顺序", osc.path == ("TIGHTENING", "NEUTRAL", "TIGHTENING"),
           str(osc.path))

    turn = day_from_hours("2026-09-01", ["TIGHTENING"] * 12 + ["EASING"] * 12)
    _check("单调 → churn = 1", turn.churn == 1, str(turn.churn))
    _check("单调是转折形状", turn.is_turning is True)

    flat = day_from_hours("2026-09-01", ["TIGHTENING"] * 24)
    _check("不变 → churn = 0 且不是转折", flat.churn == 0 and not flat.is_turning)

    # 判别性:两者的 label 和 agreement 可能相同,只有 path/churn 能分开。
    _check("震荡与转折的众数占比可以相同 —— 只有 path 能分开",
           abs(osc.agreement - 2 / 3) < 0.01 and osc.label == turn.label
           and osc.is_turning != turn.is_turning)


def t_case_variants_do_not_inflate_the_label_count():
    """`Risk-Off` 与 `RISK_OFF` 不是两种 regime。

    不归一会让「日内两种标签」虚增 —— 实测库里同时存在
    `Tightening` 与 `TIGHTENING`(120 天内 8 种取值,其中一半是大小写变体)。
    """
    d = day_from_hours("2026-09-01",
                       ["Risk-Off"] * 12 + ["RISK_OFF"] * 12)
    _check("大小写/连字符变体合并为一种", d.n_labels == 1, str(d.n_labels))
    _check("判 UNANIMOUS 而不是 CONTESTED", d.verdict == UNANIMOUS, d.verdict)
    _check("输出的是归一形式", d.label == "RISK_OFF", str(d.label))


def t_series_groups_by_day_and_orders_by_hour():
    rows = ([{"d": "2026-09-01", "hr": f"2026-09-01 {h:02d}", "macro_regime": "TIGHTENING"}
             for h in range(24)]
            + [{"d": "2026-09-02", "hr": f"2026-09-02 {h:02d}",
                "macro_regime": "TIGHTENING" if h < 10 else "NEUTRAL"}
               for h in range(24)])
    s = series(rows)
    _check("分成两天", len(s) == 2 and [x.d for x in s] == ["2026-09-01", "2026-09-02"],
           str([x.d for x in s]))
    _check("第二天按小时排序后路径是 T→N",
           s[1].path == ("TIGHTENING", "NEUTRAL"), str(s[1].path))
    _check("缺日期的行被跳过", len(series([{"hr": "x", "macro_regime": "T"}])) == 0)


def t_summary_reports_the_contested_share():
    """那正是日频众数丢掉的全部信息。"""
    days = ([day_from_hours(f"2026-08-{i:02d}", ["TIGHTENING"] * 24) for i in range(1, 21)]
            + [day_from_hours(f"2026-08-{i:02d}",
                              ["TIGHTENING"] * 13 + ["NEUTRAL"] * 11)
               for i in range(21, 29)])
    s = summarise(days)
    _check(f"有争议 {s['n_contested']}/{s['n_usable']} 天", s["n_contested"] == 8,
           str(s["n_contested"]))
    _check("比例算出来", abs(s["contested_share"] - 8 / 28) < 0.01,
           str(s["contested_share"]))
    _check("最低一致度报出来", s["min_agreement"] < 0.6, str(s["min_agreement"]))
    _check("说明点破这些在日频众数里不可见",
           "在日频众数里全部不可见" in s["reason"], s["reason"])

    thin_only = summarise([day_from_hours("2026-09-01", ["T", "T"])])
    _check("全是 thin → 比例是 None 而不是 0", thin_only["contested_share"] is None)
    _check("原因指向小时写入", "小时写入" in thin_only["reason"], thin_only["reason"])


def t_this_module_does_not_reimplement_canonicalisation():
    """S-249:我曾在这里写出第 4 个 `canonical_regime`。"""
    import inspect

    from src.data.market import regime_granularity as G
    src = inspect.getsource(G)
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))
    _check("没有已知集合的校验(那归 canonical_regime_strict)",
           "TIGHTENING" not in code.split('def _canon')[1].split('def ')[1]
           if 'def _canon' in code else True,
           "_canon 里出现了具体 regime 名 —— 那是在重新实现校验")
    _check("docstring 指明真正的校验在哪",
           "canonical_regime_strict" in src)


if __name__ == "__main__":
    print("── regime 日内颗粒度守卫 (S-270) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ regime 日内颗粒度守卫全绿")
