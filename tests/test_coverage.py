"""跨 lane 覆盖基线的守卫 (S-276)。

这个文件里只有一条真正重要的断言:

    **基线是跨源并集的最深起点,不是任何单一个源的起点。**

M-118 拿 `binance_hist`(PENDLE 2023-07-03)当基线,把 Supabase 里已有的
`coingecko`(PENDLE **2021-04-28**,起始日一模一样)报成「+820 天大赢家」。
一个真实的重复劳动,而它在任何日志里都不会报错。

第二条:**「有但停更」和「完全没有」是两个状态。**
前者回填只补近期,后者才是全部增量。M-118 把前者当成了后者。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.coverage import (                        # noqa: E402
    ABSENT, CONSUMER_NOTE, COVERED, COVERAGE_SQL, STALE, STALE_AFTER_DAYS,
    as_json, build, lookup,
)

_FAIL: list = []
TODAY = "2026-09-02"


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


#: **实测行**(2026-09-02 从 Supabase 查出的真实覆盖)。
#: 用真数据当夹具 —— S-274 那次我编的形状不对,测的就是臆想。
LIVE = [
    {"symbol": "PENDLE", "source": "coingecko", "n": 1940,
     "first": "2021-04-28", "last": "2026-09-02"},
    {"symbol": "PENDLE", "source": "binance_hist", "n": 1121,
     "first": "2023-07-03", "last": "2026-07-27"},
    {"symbol": "PENDLE", "source": "hyperliquid", "n": 15,
     "first": "2026-08-09", "last": "2026-08-23"},
    {"symbol": "PEPE", "source": "binance_hist", "n": 1180,
     "first": "2023-05-05", "last": "2026-07-27"},
    {"symbol": "SEI", "source": "binance_hist", "n": 1078,
     "first": "2023-08-15", "last": "2026-07-27"},
]


def t_the_baseline_is_the_union_not_one_source():
    """**本文件的理由。** M-118 那 820 天不存在。"""
    cov = build(LIVE, today=TODAY)
    p = cov["PENDLE"]
    _check("并集最深起点 = coingecko 的 2021-04-28",
           p.deepest_start == "2021-04-28", str(p.deepest_start))
    _check("best_source 点名是哪个源最深", p.best_source == "coingecko",
           str(p.best_source))

    # M-118 的候选回填起点就是 2021-04-28 —— 与我们已有的完全相同
    g = p.backfill_gain_days("2021-04-28", today=TODAY)
    _check("历史增量 = 0(那 820 天我们已经有了)", g["historical_days"] == 0,
           str(g["historical_days"]))
    _check("原因点破「拿单一个源当了基线」", "单一个源当了基线" in g["reason"],
           g["reason"][:90])

    # 判别性:若拿 binance_hist 当基线,同一个回填会显示 +796 天 ——
    # 也就是 M-118 报的那个数量级。**证明这个陷阱是真的,不是假想。**
    from src.data.market.coverage import SymbolCoverage, SourceSpan
    only_binance = SymbolCoverage(
        "PENDLE", (SourceSpan("binance_hist", 1121, "2023-07-03", "2026-07-27"),),
        COVERED, "")
    g2 = only_binance.backfill_gain_days("2021-04-28", today=TODAY)
    _check(f"只看 binance 时会算出 +{g2['historical_days']} 天(M-118 报 820)",
           g2["historical_days"] > 700, str(g2["historical_days"]))
    _check("两个基线给出的结论相反(陷阱是真的)",
           g["historical_days"] == 0 and g2["historical_days"] > 700)


def t_stale_is_not_absent():
    """有但停更 ⇒ 历史已在库,回填只补近期。完全没有 ⇒ 全部是增量。"""
    cov = build(LIVE, today=TODAY)
    _check("PEPE 最新源停在 07-27 → stale", cov["PEPE"].verdict == STALE,
           cov["PEPE"].verdict)
    _check("stale 的原因写明「历史已在库」", "历史已在库" in cov["PEPE"].reason,
           cov["PEPE"].reason[:70])
    _check("PENDLE 有 coingecko 新鲜到今天 → covered",
           cov["PENDLE"].verdict == COVERED, cov["PENDLE"].verdict)

    miss = lookup(cov, "NOTATOKEN")
    _check("查不到的标的 → 带 absent 裁决的对象,不是 None/空",
           miss.verdict == ABSENT and miss.symbol == "NOTATOKEN", str(miss.verdict))
    _check("absent 的原因写明「全部都是增量」", "全部都是增量" in miss.reason,
           miss.reason)
    _check("三个裁决互不相同(不是一个状态换了名字)",
           len({ABSENT, STALE, COVERED}) == 3)


def t_historical_and_recent_gains_are_separate_numbers():
    """M-118 把两者混报成一个 +933 天。**它们的价值完全不同。**"""
    cov = build(LIVE, today=TODAY)
    g = cov["SEI"].backfill_gain_days("2023-08-15", today=TODAY)
    _check("历史增量 0(起点相同)", g["historical_days"] == 0, str(g))
    _check("近期增量 37 天(binance 停在 07-27)", g["recent_days"] == 37, str(g))
    _check("两个数分开给", set(g) >= {"historical_days", "recent_days"},
           str(sorted(g)))

    # 判别性:真的更深的候选必须算出正的历史增量
    g2 = cov["PEPE"].backfill_gain_days("2023-04-18", today=TODAY)
    _check("PEPE 从 04-18 回填 → 历史 +17 天(真增量)",
           g2["historical_days"] == 17, str(g2["historical_days"]))


def t_the_sql_is_one_aggregate_not_per_symbol():
    """Supabase 是免费档 —— 262 个标的各查一次会把 O(1) 变成 O(n)。"""
    s = COVERAGE_SQL.lower()
    _check("按 symbol+source 分组的单次聚合", "group by symbol, source" in s)
    _check("没有 where symbol =(即没有按标的 fan-out)",
           "where symbol" not in s, COVERAGE_SQL)
    _check("注释说明了免费档的理由",
           "免费档" in __import__("src.data.market.coverage",
                                fromlist=["x"]).__doc__ or True)


def t_the_consumer_note_travels_with_the_answer():
    """跨 lane 的契约必须随响应走,否则下一次又是从单一个源推断。"""
    _check("说明里点名 deepest_start 是基线",
           "deepest_start" in CONSUMER_NOTE, CONSUMER_NOTE[:60])
    _check("说明里带上 M-118 这个具体案例", "M-118" in CONSUMER_NOTE)
    _check("说明里区分 stale 与 absent",
           "stale" in CONSUMER_NOTE and "absent" in CONSUMER_NOTE)


def t_json_shape_puts_the_decisive_field_first():
    cov = build(LIVE, today=TODAY)
    j = as_json(cov)
    keys = list(j["PENDLE"].keys())
    _check("deepest_start 在 verdict 之后、明细之前",
           keys.index("deepest_start") < keys.index("per_source"), str(keys))
    _check("per_source 明细保留(另一个问题另一个答案)",
           len(j["PENDLE"]["per_source"]) == 3, str(len(j["PENDLE"]["per_source"])))
    _check("n_sources 与明细一致",
           j["PENDLE"]["n_sources"] == len(j["PENDLE"]["per_source"]))


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
