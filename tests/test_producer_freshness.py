"""生产者表判活的守卫 (S-278)。

这个文件里只有一条真正重要的断言:

    **一个未来日期不是新鲜,是污染 —— 而 max() 分不出来。**

实测:`risk_meter_history` 有一行 `d = 2099-12-31`。任何 `max(d)` 判活从此
**永远报新鲜**,那张表死了也没人知道。一个判活器最坏的失败不是漏报,
是**被它监视的数据本身关掉**。

第二条:**「有多新」在说清是哪个时钟之前没有定义。**
写时钟停 = 写入者死了;写时钟新而事件时钟旧 = **写入者活着但在写陈旧内容** ——
后者最阴,因为进程在跑、日志在滚,而单一个新鲜度数字会把它报成健康。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.producer_freshness import (                # noqa: E402
    DEAD, EMPTY, EXPECTED, FRESH, FUTURE_DATED, NOT_APPLICABLE, PRODUCER_SQL,
    STALE, UNKNOWN, assess, overall,
)

_FAIL: list = []
TODAY = dt.date(2026, 9, 2)


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_a_future_date_is_corruption_not_freshness():
    """**本文件的理由。** 实测 risk_meter_history d=2099-12-31。"""
    h = assess("risk_meter_history", 12, "2026-09-02", "2099-12-31", today=TODAY)
    _check("判 future_dated 而不是 fresh", h.verdict == FUTURE_DATED, h.verdict)
    _check("理由点破「会让 max() 永远报新鲜」",
           "永远报新鲜" in h.reason, h.reason[:90])
    _check("不算 alive", not h.alive)

    # 判别性:一个正常日期的同一张表必须判 fresh
    ok = assess("risk_meter_history", 12, "2026-09-02", "2026-09-02", today=TODAY)
    _check("正常日期 → fresh(不是见谁都拒)", ok.verdict == FRESH, ok.verdict)

    # 容差内的「未来」(时区/结算)不该报污染
    tz = assess("risk_meter_history", 12, "2026-09-02", "2026-09-03", today=TODAY)
    _check("差 1 天在容差内 → 仍 fresh", tz.verdict == FRESH, tz.verdict)


def t_two_clocks_because_two_different_failures():
    """写入者死了 vs 写入者活着但内容陈旧 —— 单一个数字会漏掉后者。"""
    # 两个都停 = 写入者死了(实测 market_state_vectors)
    dead = assess("market_state_vectors", 582, "2026-08-06", "2026-08-05",
                  today=TODAY)
    _check("两个时钟都停 → dead", dead.verdict == DEAD, dead.verdict)

    # 写时钟新、事件时钟旧 = **最阴的那种**
    drift = assess("market_state_vectors", 582, "2026-09-02", "2026-08-05",
                   today=TODAY)
    _check("写新事件旧 → 仍判坏(不被写时钟掩护)",
           drift.verdict in (STALE, DEAD), drift.verdict)
    _check("并明确点出「写入者活着但内容是陈的」",
           "写入者活着但内容是陈的" in drift.reason, drift.reason[-70:])
    _check("两个场景的 reason 不同(不是一个模板)",
           dead.reason != drift.reason)


def t_no_clock_by_design_is_not_ignorance():
    """**我第一版犯的错。** cis_scores 是最健康的表,却被报成 unknown。"""
    h = assess("cis_scores", 144597, "2026-09-02", None, today=TODAY)
    _check("按设计只有写时钟 → 总裁决 fresh(不是 unknown)",
           h.verdict == FRESH, h.verdict)
    _check("那个时钟本身判 not_applicable", h.event.verdict == NOT_APPLICABLE,
           h.event.verdict)
    _check("理由写明是「规格已声明」", "规格已声明" in h.event.reason,
           h.event.reason)

    # 而真正的无知仍然是 unknown
    u = assess("some_table_nobody_declared", 5, "2026-09-02", None, today=TODAY)
    _check("不在 EXPECTED 里 → unknown", u.verdict == UNKNOWN, u.verdict)
    _check("两者可分(按设计没有 ≠ 不知道)", h.verdict != u.verdict)
    _check("unknown 的理由指向 S-180", "S-180" in u.reason, u.reason[-40:])


def t_cadence_is_per_table_not_global():
    """strategy_records 30 天没写是正常的;cis_scores 一天没写就是故障。"""
    sr = assess("strategy_records", 26, "2026-08-20", None, today=TODAY)
    _check("strategy_records 13 天前写 → 仍 fresh", sr.verdict == FRESH,
           sr.verdict)
    cs = assess("cis_scores", 1000, "2026-08-31", None, today=TODAY)
    _check("cis_scores 2 天前写 → dead", cs.verdict == DEAD, cs.verdict)
    _check("同样的天数在两张表上裁决不同(节奏是表的属性)",
           EXPECTED["strategy_records"].dead_after_days
           > EXPECTED["cis_scores"].dead_after_days)


def t_zero_rows_is_its_own_verdict():
    h = assess("risk_meter_history", 0, None, None, today=TODAY)
    _check("0 行 → empty(不是 dead,也不是 fresh)", h.verdict == EMPTY,
           h.verdict)
    _check("理由带上这张表的 why", "mac-write" in h.reason or "污染" in h.reason,
           h.reason[:80])


def t_overall_reports_the_worst_not_the_average():
    """面板层报最坏的 —— 一个平均新鲜度会把三张死表藏在七张活表后面。"""
    live = [
        ("cis_scores", 144597, "2026-09-02", None),
        ("signal_outcomes", 7743, None, "2026-05-03"),
        ("risk_meter_history", 12, "2026-09-02", "2099-12-31"),
        ("market_state_vectors", 582, "2026-08-06", "2026-08-05"),
        ("beta_core_nav", 25, "2026-09-02", "2026-09-02"),
    ]
    o = overall([assess(t, n, w, e, today=TODAY) for t, n, w, e in live])
    _check("总裁决 dead", o["verdict"] == DEAD, o["verdict"])
    _check("三张死/污染的表被点名", set(o["dead_or_corrupt"]) == {
        "signal_outcomes", "risk_meter_history", "market_state_vectors"},
           str(o["dead_or_corrupt"]))
    _check("理由把「未来日期」单独说明", "未来日期单列" in o["reason"],
           o["reason"][-70:])

    all_ok = overall([assess("cis_scores", 100, "2026-09-02", None, today=TODAY)])
    _check("全健康时 → fresh(不是永远报警)", all_ok["verdict"] == FRESH,
           all_ok["verdict"])


def t_sql_names_each_tables_own_time_column():
    """**不能写成猜时间列的通用循环** —— signal_journal 有四个。"""
    s = PRODUCER_SQL
    _check("signal_journal 显式用 recorded_at + signal_date",
           "max(recorded_at)" in s and "max(signal_date)" in s)
    _check("beta_core_nav 用 marked_at/mark_date(不是 computed_at/d)",
           "max(marked_at)" in s and "max(mark_date)" in s)
    _check("每张 EXPECTED 里的表都在 SQL 里",
           all(t in s for t in EXPECTED), 
           str([t for t in EXPECTED if t not in s]))


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
