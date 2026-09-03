"""覆盖清册的守卫 (S-279)。

这个文件里只有一条真正重要的断言:

    **清册必须从库里数出来,不能是一份手写清单。**

因为手写清单本身就是抽样,而抽样正是本模块要修的毛病。实测:库里 67 张表,
S-278 的生产者判活只看 10 张;9 张 NAV 表里只有 1 张在被判活 ——
而 ARCHITECTURE 说产品就是**可验证的前向记录**,NAV 表就是那个记录。

第二条,是我自己差点犯的:**不能用一盏永久红灯去修一盏永久黄灯。**
第一版让覆盖不全把总裁决压成 `blocked`,而覆盖不全会持续数周 ——
一盏常亮的红灯和一盏坏掉的灯在行为上是同一个东西,那正是这个模块要修的病。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.watch_census import (                     # noqa: E402
    BLOCKING_TIERS, CENSUS_SQL, COVERAGE, COVERED, EXCLUDED,
    EXCLUDED_BY_DESIGN, NOT_COVERED, SIGNAL, TRACK_RECORD, census,
    qualify_verdict, tier_of,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_a_new_table_shows_up_as_not_covered_without_anyone_remembering():
    """**本文件的理由。** 清册现查,所以明天新建的表明天就在缺口里。"""
    c = census(["cis_scores", "brand_new_table_nobody_declared"])
    _check("没人声明过的新表 → not_covered", "brand_new_table_nobody_declared"
           in sum(c["not_covered_by_tier"].values(), []),
           str(c["not_covered_by_tier"]))
    _check("已覆盖的仍是已覆盖", c["n_covered"] == 1, str(c["n_covered"]))
    _check("SQL 是现查 information_schema",
           "information_schema.tables" in CENSUS_SQL and "table_schema" in CENSUS_SQL)


def t_exclusion_must_be_explicit_and_carry_a_reason():
    """一个 `endswith('_log')` 的规则会把明天某张重要的表静默吞掉。"""
    for name, why in EXCLUDED_BY_DESIGN.items():
        _check(f"{name} 的排除带理由", bool(why and len(why) > 4), why)
    # 一个没被显式排除的 _log 表必须仍然进缺口 —— 证明没有模式匹配在偷偷排除
    c = census(["some_important_log"])
    _check("未声明的 *_log 表仍进 not_covered(没有模式在偷偷排除)",
           c["n_not_covered"] == 1, str(c))


def t_nav_tables_are_track_record_and_their_gap_is_blocking():
    """产品是可验证的前向记录,NAV 表就是那个记录本身。"""
    _check("beta_core_nav_q 归 track_record",
           tier_of("beta_core_nav_q") == TRACK_RECORD, tier_of("beta_core_nav_q"))
    _check("fusion_paper_nav 归 track_record",
           tier_of("fusion_paper_nav") == TRACK_RECORD)
    _check("track_record 是阻塞层", TRACK_RECORD in BLOCKING_TIERS)

    c = census(["beta_core_nav", "beta_core_nav_q", "fusion_paper_nav"])
    _check("已覆盖的那张不算缺口", c["n_covered"] == 1, str(c["n_covered"]))
    _check("两张未覆盖的 NAV 表算阻塞级", c["n_blocking"] == 2, str(c["n_blocking"]))
    _check("裁决为 blocked", c["verdict"] == "blocked", c["verdict"])
    _check("原因点出「前向记录」", "前向记录" in c["reason"], c["reason"][:80])

    # 判别性:全部覆盖时必须判 complete,否则这个判据没在做事
    ok = census(["beta_core_nav"])
    _check("全覆盖 → complete(不是永远 blocked)", ok["verdict"] == "complete",
           ok["verdict"])


def t_incomplete_coverage_qualifies_the_verdict_it_does_not_redden_it():
    """**我差点犯的那个错。** 不能用永久红灯修永久黄灯。"""
    c = census(["beta_core_nav", "beta_core_nav_q"])
    q = qualify_verdict("fresh", c)
    _check("裁决本身没被改红", q["verdict"] == "fresh", q["verdict"])
    _check("但标记为非无条件", q["unqualified"] is False, str(q["unqualified"]))
    _check("给出覆盖比例", q["covers"] == "1/2", q["covers"])
    _check("范围说明点破「常亮的红灯等于坏灯」",
           "常亮" in q["scope_note"], q["scope_note"][-50:])

    full = qualify_verdict("fresh", census(["beta_core_nav"]))
    _check("覆盖完整 → unqualified True", full["unqualified"] is True)
    _check("两种情况可分", q["unqualified"] != full["unqualified"])


def t_covered_must_name_who_covers_it():
    """一个说不出「被谁看」的「已覆盖」等于没覆盖。"""
    for name, by in COVERAGE.items():
        _check(f"{name} 说得出被谁看", bool(by and "(" in by), by)
    c = census(["cis_scores"])
    _check("已覆盖数与 COVERAGE 一致", c["n_covered"] == 1)


def t_the_gap_is_reported_by_tier_not_as_one_number():
    """「67 张少看 38 张」是误导 —— 配置表没人看不要紧,NAV 表要命。"""
    c = census(["api_tiers", "beta_core_nav_q", "cis_regime_fitness"])
    _check("api_tiers 被显式排除,不进缺口",
           "api_tiers" not in sum(c["not_covered_by_tier"].values(), []))
    tiers = list(c["not_covered_by_tier"])
    _check("缺口按层分组", len(tiers) >= 2, str(tiers))
    _check("track_record 排在最前(严重度排序)", tiers[0] == TRACK_RECORD,
           str(tiers))
    _check("n_blocking 只数阻塞层", c["n_blocking"] == 1, str(c["n_blocking"]))


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
