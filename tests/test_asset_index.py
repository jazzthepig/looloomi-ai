"""大类资产要跟指数,不跟 ETF 的守卫 (S-275)。

这个文件里只有一条真正重要的断言:

    **一个 ETF 的收盘价不是它所代表的资产。**

Jazz 2026-09-02:「要找对资产的指数先,etf 是产品,所以你现在的逻辑不对的,
价格也不会对。」

第二条,是我写守卫时**自己又犯一次**才发现的:
`convention` 这个标签不足以判定两个序列可比 —— `GLD` 与 `TLT` 都是
`price_return`,而泄漏是 40 vs 400 bp/年,**差十倍**。
一个标签装着两个差异巨大的状态,正是本模块要修的那个形状。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.asset_index import (                     # noqa: E402
    CANONICAL, HELD_PROXIES, LEAK_ESTIMATE_UNCERTAINTY_BPS, LEVEL, RATE,
    RATIOABLE, TOLERANCE, TRADING_DAYS_YR, can_ratio, gap_report,
    horizon_verdict, ratio_leak_bps, ratio_max_horizon_days,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_a_yield_can_never_be_a_ratio_leg():
    """**本文件的第一条。** `US10Y / XAU` 没有意义 —— 收益率是水平,不是价格。"""
    ok, why = can_ratio(CANONICAL["gold"], CANONICAL["ust_10y"])
    _check("gold / ust_10y 被拒", not ok, why)
    _check("原因点破「收益率不是价格」", "不是价格" in why, why)
    _check("RATE 不在可比价集合里", RATE not in RATIOABLE, str(RATIOABLE))

    # 判别性:同为 LEVEL 且口径一致的一对必须能过,否则这个守卫是「见谁都拒」
    ok2, why2 = can_ratio(CANONICAL["gold"], CANONICAL["silver"])
    _check("gold / silver 通过(守卫不是见谁都拒)", ok2, why2)


def t_the_convention_label_is_not_enough_because_it_hides_a_tenfold_gap():
    """**我写守卫时自己犯的那次。**

    第一版只比 `convention`,于是 GLD/TLT 判 True —— 两者都是 price_return,
    而泄漏 40 vs 400。同一个标签装着差十倍的状态。
    """
    gld, tlt = HELD_PROXIES["GLD"], HELD_PROXIES["TLT"]
    _check("两者 convention 确实相同(所以只看它一定放行)",
           gld.convention == tlt.convention, gld.convention)
    _check("而泄漏差十倍", tlt.leak_bps_yr >= 10 * gld.leak_bps_yr,
           f"{gld.leak_bps_yr} vs {tlt.leak_bps_yr}")

    d = ratio_leak_bps(gld, tlt)
    _check("比价的失真取【差】而非任一边", d == abs(gld.leak_bps_yr - tlt.leak_bps_yr),
           str(d))
    h = ratio_max_horizon_days(gld, tlt)
    _check(f"该比价上限 {h} 交易日(约 {h / TRADING_DAYS_YR:.1f} 年)", h < 300, str(h))

    ok, why = can_ratio(gld, tlt, window_days=1926)   # S-274 用的 2019+ 窗口
    _check("在 S-274 用过的 1926 天窗口上被拒", not ok, why)
    _check("原因写出泄漏差", "泄漏之差" in why, why[:80])

    # 判别性:短窗口必须放行,否则这就不是「窗口约束」而是「一律禁止」
    ok_short, _ = can_ratio(gld, tlt, window_days=60)
    _check("60 天窗口上放行(约束是窗口,不是禁令)", ok_short)


def t_leaks_that_cancel_are_allowed_but_not_infinitely():
    """同向同量的泄漏在比值里相消 —— 但**估计值相等不是相等**。"""
    tlt, shy = HELD_PROXIES["TLT"], HELD_PROXIES["SHY"]
    _check("两者的泄漏估计恰好相同", tlt.leak_bps_yr == shy.leak_bps_yr,
           f"{tlt.leak_bps_yr} vs {shy.leak_bps_yr}")
    d = ratio_leak_bps(tlt, shy)
    _check(f"差值仍有下界 {LEAK_ESTIMATE_UNCERTAINTY_BPS}bp,不报 0",
           d == LEAK_ESTIMATE_UNCERTAINTY_BPS, str(d))
    h = ratio_max_horizon_days(tlt, shy)
    _check("于是上限是有限的,不是「不设限」", h < 10 ** 5, str(h))

    # 只有【结构上】无泄漏的两个(现货/总回报)才允许 0
    d0 = ratio_leak_bps(CANONICAL["gold"], CANONICAL["us_equity_tr"])
    _check("规范对象之间允许 0(结构上无泄漏,不是估计相等)", d0 == 0, str(d0))


def t_every_ratio_used_in_S274_is_blocked_at_the_window_it_was_used_at():
    """S-274 报的四个比价,在它实际使用的窗口上必须全部被拒 —— 那是勘误的依据。"""
    for a, b in [("GLD", "TLT"), ("GLD", "FXY"), ("GLD", "UUP"), ("TLT", "FXY")]:
        ok, why = can_ratio(HELD_PROXIES[a], HELD_PROXIES[b], window_days=1926)
        _check(f"{a}/{b} 在 2019+ 窗口(1926d)上被拒", not ok,
               f"通过了 —— 上限 {ratio_max_horizon_days(HELD_PROXIES[a], HELD_PROXIES[b])}d")


def t_uso_is_unusable_at_any_meaningful_window():
    """期货展期不是一个小偏差 —— USO 与油价长期脱钩。"""
    uso = HELD_PROXIES["USO"]
    _check("USO 泄漏是数量级最大的",
           uso.leak_bps_yr == max(s.leak_bps_yr for s in HELD_PROXIES.values()),
           str(uso.leak_bps_yr))
    _check(f"最多撑 {uso.max_horizon_days} 交易日(不到一个月)",
           uso.max_horizon_days < 25, str(uso.max_horizon_days))
    _check("一年窗口上不可用", not uso.usable_over(252))


def t_unquantified_leak_blocks_rather_than_passes():
    """**未量化 ≠ 没有。** I1:未测不能塌成 0。"""
    from dataclasses import replace
    unknown = replace(HELD_PROXIES["GLD"], leak_bps_yr=None)
    _check("泄漏 None → max_horizon 是 None", unknown.max_horizon_days is None)
    _check("None → 任何窗口都不可用", not unknown.usable_over(1))
    ok, why = can_ratio(unknown, HELD_PROXIES["SLV"], window_days=60)
    _check("含未量化的一边 → 比价被拒", not ok, why)
    _check("原因写明「未量化不等于没有」", "未量化不等于没有" in why, why)


def t_horizon_verdict_names_the_binding_constraint():
    """窗口由泄漏最大的那个决定 —— 报出来是哪一个,不只报「不行」。"""
    v = horizon_verdict([HELD_PROXIES[k] for k in ("GLD", "TLT", "FXY", "UUP")], 1926)
    _check("全部阻塞", v["n_blocking"] == 4, str(v["blocking"]))
    _check("点名约束者", v["binding_constraint"] in ("TLT", "FXY", "SHY", "VNQ"),
           str(v["binding_constraint"]))
    v2 = horizon_verdict([HELD_PROXIES["GLD"]], 60)
    _check("短窗口下 GLD 单独可用", v2["n_blocking"] == 0, str(v2["blocking"]))


def t_the_gap_is_a_suffix_not_a_vendor():
    """我们付了 EODHD 的钱,缺的是没用过 `.INDX/.FOREX/.GBOND/.COMM`。"""
    g = gap_report()
    _check("持有的规范对象为 0", g["n_held_canonical"] == 0, str(g["n_held_canonical"]))
    _check("持有的代理 = 面板全部", g["n_held_proxies"] == len(HELD_PROXIES))
    _check("原因指向后缀而非数据源", "缺口是后缀" in g["reason"], g["reason"][-60:])
    _check("最差代理榜首是 USO", g["worst_proxies"][0]["key"] == "USO",
           str(g["worst_proxies"][0]))


def t_tolerance_is_small_enough_to_matter():
    """容差若定得太松,这整层守卫就不会拦下任何东西。"""
    _check(f"容差 {TOLERANCE:.0%} ≤ 3%", TOLERANCE <= 0.03, str(TOLERANCE))
    blocked = [k for k, v in HELD_PROXIES.items() if not v.usable_over(1926)]
    _check(f"在 2019+ 窗口上 {len(blocked)}/{len(HELD_PROXIES)} 个代理被拦",
           len(blocked) == len(HELD_PROXIES), str(blocked))
    passed = [k for k, v in HELD_PROXIES.items() if v.usable_over(60)]
    _check(f"而 60 天窗口上 {len(passed)} 个通过(不是一律禁止)",
           len(passed) >= len(HELD_PROXIES) - 1, str(passed))


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
