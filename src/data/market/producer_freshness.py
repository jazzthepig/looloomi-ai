"""生产者表的判活 —— **两个时钟,不是一个** (S-278).

## 缺口

`/internal/data-freshness` 只看 `ohlcv_daily` 的**数据源**。而静默死亡这个失败类
(该端点自己的 docstring:「已经代价三次」)大多发生在**生产者表**上:
T2 pillars 全 NULL 数月 · signal_outcomes 死 80 天 · `_daily_snapshot_loop`
静默 42 天(S-任务#32)。**没有一张生产者表在被判活。**

## 实测(2026-09-02)三个活的故障

    risk_meter_history        事件时钟 = 2099-12-31   ← 未来日期
    signal_outcomes           事件时钟 = 2026-05-03   ← 停了 122 天
    market_state_vectors      写时钟   = 2026-08-06   ← 停了 27 天

## ① 未来日期不是新鲜,是污染 —— 而 `max()` 分不出来

`risk_meter_history` 有一行 `d = 2099-12-31`。任何 `max(d)` 判活从此
**永远报新鲜**,而那张表可能已经死了。一个哨兵值给整张表披上了永久的外衣。

**所以 `future_dated` 必须是一个独立裁决,不能折进 `fresh`。**
这是本模块最重要的一条:一个判活器最坏的失败不是漏报,是**被数据本身关掉**。

## ② 「这张表有多新」在说清是哪个时钟之前没有定义

`signal_journal` 有四个时间列:`signal_date`(信号何时发生)、
`recorded_at`(我们何时写的)、`exit_date`、`outcome_at`。选错一个,
会得到一个看起来完全正常的错答案。

    写时钟  computed_at / recorded_at / created_at  → **写入者还活着吗**
    事件时钟 d / mark_date / signal_date            → **内容是当期的吗**

两者必须分开,因为它们对应两种不同的故障:

    写时钟停       写入者死了
    写时钟新、事件时钟旧   **写入者活着,但在反复写陈旧内容** ← 单一数字会漏掉这个

`market_state_vectors` 恰好是第一种(两个都停在 8 月初);
而第二种是最阴的一种,因为进程在跑、日志在滚、指标在动。

## ③ 节奏是表的属性,不是全局常数

一张按需写的表(`strategy_records`)30 天没写不是故障;
`cis_scores` 一小时没写就是。所以 `EXPECTED` 逐表声明,
**而没有声明的表判 `unknown`,不判 `ok`**(S-180:读不到 ≠ 都健康)。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

FRESH, STALE, DEAD, FUTURE_DATED, EMPTY, UNKNOWN = (
    "fresh", "stale", "dead", "future_dated", "empty", "unknown")

#: ⚠️ **「按设计没有这个时钟」不是「不知道这张表健不健康」。**
#: 第一版把两者都判 `unknown`,于是 `cis_scores`(系统里最健康的表,
#: 只是按设计只有写时钟)被报成 unknown,而 `unknown` 在总裁决里压过 `fresh`。
#:
#: 规格里显式写着 `event_col=None` **本身就是知识** —— 它说「这张表一个时钟就够」。
#: 而 `UNKNOWN` 要留给真正的无知:这张表根本不在 `EXPECTED` 里。
#: 又是同一个形状:两个不同的状态塌进一个表示。
NOT_APPLICABLE = "not_applicable"

#: 未来多少天以内容忍(时区/结算日差)。超过它就是污染,不是提前。
FUTURE_TOLERANCE_DAYS = 1


@dataclass(frozen=True)
class ProducerSpec:
    """一张生产者表该有的节奏 —— **逐表声明,没有全局默认。**"""
    table: str
    write_col: Optional[str]      # 写时钟:写入者还活着吗
    event_col: Optional[str]      # 事件时钟:内容是当期的吗
    stale_after_days: float
    dead_after_days: float
    why: str = ""


#: 未在此表内的生产者判 `unknown` —— **不判 ok**。
EXPECTED: dict[str, ProducerSpec] = {
    "cis_scores": ProducerSpec(
        "cis_scores", "recorded_at", None, 0.5, 2,
        "Mac T1 每 ~30 分钟推一次;半天不写就是引擎或推送断了"),
    "signal_journal": ProducerSpec(
        "signal_journal", "recorded_at", "signal_date", 3, 10,
        "有信号才写 —— 但 10 天一条没有,多半是产出信号的那一步断了"),
    "signal_outcomes": ProducerSpec(
        "signal_outcomes", None, "d", 3, 14,
        "**曾死 80 天无人知**(data_freshness docstring)。只有事件时钟"),
    "risk_meter_history": ProducerSpec(
        "risk_meter_history", "computed_at", "d", 2, 7,
        "S-277 起走 mac-write 代理;实测有 d=2099-12-31 的污染行"),
    "beta_core_nav": ProducerSpec(
        "beta_core_nav", "marked_at", "mark_date", 2, 5,
        "①层前向记录 —— 断一天就是前向天数断一天,补不回来"),
    "asset_embeddings_history": ProducerSpec(
        "asset_embeddings_history", "computed_at", "d", 2, 7, ""),
    "asset_embeddings": ProducerSpec(
        "asset_embeddings", "computed_at", None, 2, 7,
        "pgvector 检索面 —— 停了 similar/cluster 会静默返回旧邻居"),
    "market_state_vectors": ProducerSpec(
        "market_state_vectors", "computed_at", "d", 3, 10,
        "S-任务#7/#8 建的 writer;实测 2026-08-06 起停"),
    "trade_results": ProducerSpec(
        "trade_results", "created_at", "entry_time", 7, 30,
        "回测导出,按需"),
    "treasury_decisions": ProducerSpec(
        "treasury_decisions", "recorded_at", "decision_date", 7, 21,
        "企业决策流 (S-292)。事件时钟是【披露日】——**没有新披露是正常的**"
        "(企业不是每天买),所以死亡线放到 21 天;而写时钟停 7 天就是循环坏了"),
    "strategy_records": ProducerSpec(
        "strategy_records", "created_at", None, 21, 60,
        "按需写(一轮研究一条)—— 长间隔是正常的,不是故障"),
}


@dataclass(frozen=True)
class ClockRead:
    """一个时钟的读数。**未来日期是它自己的裁决。**"""
    col: Optional[str]
    last: Optional[str]
    age_days: Optional[float]
    verdict: str
    reason: str


@dataclass(frozen=True)
class ProducerHealth:
    table: str
    n_rows: int
    write: ClockRead
    event: ClockRead
    verdict: str
    reason: str
    #: 未来日期的行数 (S-281)。**被看见,不被抹掉。**
    #: 实测那行的 interpretation 是 "[smoke test from D2 swap verification]" ——
    #: 一个「用很远的未来日期以免撞车」的合理直觉,把判活器静默关了 10 天。
    #: 修法是让 max() 只看已发生的行(RPC 侧),而这个计数让污染仍然可读。
    n_future: int = 0

    @property
    def alive(self) -> bool:
        return self.verdict in (FRESH,)


#: `NOT_APPLICABLE` 排在 FRESH **之前** —— 它不该把总裁决往坏里拉。
_RANK = {NOT_APPLICABLE: -1, FRESH: 0, UNKNOWN: 1, STALE: 2, EMPTY: 3,
         FUTURE_DATED: 4, DEAD: 5}


def _clock(col: Optional[str], last: Optional[str], spec: ProducerSpec,
           today: dt.date, label: str) -> ClockRead:
    if col is None:
        # 规格显式声明没有这个时钟 ⇒ **不适用**,不是未知,不参与总裁决。
        return ClockRead(None, None, None, NOT_APPLICABLE,
                         f"按设计没有{label}(规格已声明)—— 不参与裁决")
    if not last:
        return ClockRead(col, None, None, EMPTY, f"{col} 全为空")
    d = dt.date.fromisoformat(str(last)[:10])
    age = (today - d).days
    if age < -FUTURE_TOLERANCE_DAYS:
        return ClockRead(
            col, str(d), float(age), FUTURE_DATED,
            f"{col} = {d},在未来 {-age} 天。**这不是新鲜,是污染** —— "
            f"一个未来日期会让任何 max() 判活永远报新鲜,"
            f"于是这张表死了也没人知道")
    age = max(0.0, float(age))
    if age >= spec.dead_after_days:
        return ClockRead(col, str(d), age, DEAD,
                         f"{col} 停在 {d}({age:.0f} 天前 ≥ 死亡线 "
                         f"{spec.dead_after_days:g})")
    if age >= spec.stale_after_days:
        return ClockRead(col, str(d), age, STALE,
                         f"{col} 停在 {d}({age:.0f} 天前 ≥ 陈旧线 "
                         f"{spec.stale_after_days:g})")
    return ClockRead(col, str(d), age, FRESH, f"{col} = {d}({age:.0f} 天前)")


def assess(table: str, n_rows: int, write_last: Optional[str],
           event_last: Optional[str], *, today: Optional[dt.date] = None,
           n_future: int = 0) -> ProducerHealth:
    """一张生产者表 → **两个时钟各自的裁决 + 一个总裁决。**"""
    today = today or dt.date.today()
    spec = EXPECTED.get(table)
    if spec is None:
        nul = ClockRead(None, None, None, UNKNOWN, "未声明节奏")
        return ProducerHealth(
            table, n_rows, nul, nul, UNKNOWN,
            f"`{table}` 不在 EXPECTED 里 —— **判 unknown 而不是 ok**。"
            f"一张没人声明过节奏的表,我们无从判断它是死是活 (S-180)")

    if n_rows == 0:
        e = ClockRead(None, None, None, EMPTY, "0 行")
        return ProducerHealth(table, 0, e, e, EMPTY,
                              f"`{table}` 0 行 —— {spec.why or '尚未开始写入'}")

    w = _clock(spec.write_col, write_last, spec, today, "写时钟")
    ev = _clock(spec.event_col, event_last, spec, today, "事件时钟")

    worst = max((w.verdict, ev.verdict), key=lambda v: _RANK.get(v, 1))
    # 写时钟新、事件时钟旧 —— **最阴的一种**,进程在跑但内容是陈的
    drift = (w.verdict == FRESH and ev.verdict in (STALE, DEAD))
    reason = " · ".join(x.reason for x in (w, ev) if x.reason)
    if drift:
        reason += ("。⚠️ **写入者活着但内容是陈的** —— "
                   "进程在跑、日志在滚,而产出已经不当期了;"
                   "单一个新鲜度数字会把这种情况报成健康")
    if n_future:
        reason += (f"。⚠️ 另有 **{n_future} 行日期在未来** —— 已被排除在判活之外"
                   f"(S-281),但它们仍是脏数据:一个 `d=2099` 的冒烟测试行"
                   f"曾让 max() 永远报新鲜,把判活器静默关了 10 天")
    return ProducerHealth(table, n_rows, w, ev, worst, reason, n_future)


def overall(healths: list) -> dict:
    """面板层。**报最坏的,不报平均的。**"""
    if not healths:
        return {"verdict": UNKNOWN, "reason": "没有任何生产者被检查"}
    bad = [h for h in healths if h.verdict in (DEAD, FUTURE_DATED)]
    warn = [h for h in healths if h.verdict in (STALE, EMPTY)]
    unk = [h for h in healths if h.verdict == UNKNOWN]   # 只有不在 EXPECTED 里的
    v = (DEAD if bad else STALE if warn else UNKNOWN if unk else FRESH)
    return {
        "verdict": v,
        "n": len(healths), "n_dead_or_corrupt": len(bad),
        "n_stale_or_empty": len(warn), "n_unknown": len(unk),
        "dead_or_corrupt": [h.table for h in bad],
        "stale_or_empty": [h.table for h in warn],
        "tables": {h.table: {
            "verdict": h.verdict, "n_rows": h.n_rows,
            "write": {"col": h.write.col, "last": h.write.last,
                      "age_days": h.write.age_days, "verdict": h.write.verdict},
            "event": {"col": h.event.col, "last": h.event.last,
                      "age_days": h.event.age_days, "verdict": h.event.verdict},
            "reason": h.reason} for h in healths},
        "reason": (
            f"{len(bad)} 张死亡或被未来日期污染 {[h.table for h in bad]}、"
            f"{len(warn)} 张陈旧或空。**未来日期单列** —— 它会让 max() 判活"
            f"永远报新鲜,是判活器被数据本身关掉的那种失败"
            if bad or warn else f"{len(healths)} 张生产者表全部新鲜"),
    }


#: 一次查完所有生产者的 SQL。**每张表的时间列不同**,所以不能写成一个通用循环 ——
#: 一个「猜时间列」的通用实现会在 signal_journal 上选错(它有四个)。
PRODUCER_SQL = """
select 'cis_scores' t, count(*) n, max(recorded_at)::date::text w, null::text e from cis_scores
union all select 'signal_journal', count(*), max(recorded_at)::date::text, max(signal_date)::date::text from signal_journal
union all select 'signal_outcomes', count(*), null, max(d)::text from signal_outcomes
union all select 'risk_meter_history', count(*), max(computed_at)::date::text, max(d)::text from risk_meter_history
union all select 'beta_core_nav', count(*), max(marked_at)::date::text, max(mark_date)::text from beta_core_nav
union all select 'asset_embeddings_history', count(*), max(computed_at)::date::text, max(d)::text from asset_embeddings_history
union all select 'asset_embeddings', count(*), max(computed_at)::date::text, null from asset_embeddings
union all select 'market_state_vectors', count(*), max(computed_at)::date::text, max(d)::text from market_state_vectors
union all select 'trade_results', count(*), max(created_at)::date::text, max(entry_time)::date::text from trade_results
union all select 'strategy_records', count(*), max(created_at)::date::text, null from strategy_records
union all select 'treasury_decisions', count(*), max(recorded_at)::date::text, max(decision_date)::text from treasury_decisions
"""
