"""每个 symbol×source 我们**实际**持有多深 —— 跨 lane 的共享基线 (S-276).

## 为什么建这个:一次可查证的重复劳动

M-118(minimax-c,2026-09-02)用 CG Pro 回填 5 个标的,报「PENDLE +820 天,
大赢家」。查证:

    M-118 抓到       PENDLE 1954 行,2021-04-28 起
    Supabase 已有    PENDLE 1940 行,2021-04-28 起(source=coingecko)

**起始日一模一样。那 820 天我们早就有了。** 他报的 +933 天里,
PENDLE 那项(最大的一项)是重复,SUI/SEI/TIA 三项其实是
「binance_hist 从 07-27 停更之后的近期天数」,不是历史深度。

### 根因不是粗心,是**他看不到 Supabase**

minimax-c 只能读 Mac 侧的表,于是拿**单一个源**(`ohlcv_11yr` / binance_hist)
当基线。而正确的基线是**所有源的并集**:

    PENDLE binance_hist  2023-07-03 起   ← 他看到的
    PENDLE coingecko     2021-04-28 起   ← 实际最深的,他看不到

于是两个不同的状态在他那里同形:

    ① 这个标的我们真的只有 2023 年起的数据
    ② 这个标的有更深的源,只是**不是他在看的那个源**

**让他更小心解决不了这个 —— 给他一个可查的基线才能。**

## 所以本模块的产出是「并集深度」,不是「每个源的深度」

`deepest_start` 与 `best_source` 回答的是他真正的问题:
**「如果我去回填 X,实际能新增多少?」**

而 `per_source` 保留明细,因为「哪个源停更了」是另一个问题
(S-272 的 `by_source` 回答那个),两个问题不该共用一个答案。

## 三个状态,不是一个

    absent      我们完全没有这个标的        → 回填有全部增量
    stale       有,但最新的源也停更了      → 回填只补近期,**历史已在库**
    covered     有且新鲜                    → 回填是纯重复

M-118 把 ① 和 ③ 弄混了(PENDLE 是 covered,被当成了 absent)。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional, Sequence

#: 最新一根超过这么多天,判为 stale。取 7:容得下周末 + 一次调度抖动。
STALE_AFTER_DAYS = 7

ABSENT, STALE, COVERED = "absent", "stale", "covered"


@dataclass(frozen=True)
class SourceSpan:
    source: str
    n: int
    first: str
    last: str


@dataclass(frozen=True)
class SymbolCoverage:
    """一个标的的并集覆盖。**深度取跨源最深的,不取任一个源的。**"""
    symbol: str
    per_source: tuple = ()
    verdict: str = ABSENT
    reason: str = ""

    @property
    def deepest_start(self) -> Optional[str]:
        return min((s.first for s in self.per_source), default=None)

    @property
    def best_source(self) -> Optional[str]:
        """给出最深的那个源 —— **这是 M-118 缺的那一个字段。**"""
        if not self.per_source:
            return None
        return min(self.per_source, key=lambda s: s.first).source

    @property
    def latest(self) -> Optional[str]:
        return max((s.last for s in self.per_source), default=None)

    def backfill_gain_days(self, candidate_start: str,
                           today: Optional[str] = None) -> dict:
        """一个候选回填相对**并集**能新增多少 —— 分成历史与近期两块。

        M-118 把两者混报成一个「+933 天」。它们的价值完全不同:
        历史深度扩展横截面窗口,近期补齐只是修停更。
        """
        today = today or dt.date.today().isoformat()
        if not self.per_source:
            return {"historical_days": None, "recent_days": None,
                    "reason": "库里没有这个标的 —— 回填的全部都是增量"}
        hist = max(0, (dt.date.fromisoformat(self.deepest_start)
                       - dt.date.fromisoformat(candidate_start)).days)
        recent = max(0, (dt.date.fromisoformat(today)
                         - dt.date.fromisoformat(self.latest)).days)
        return {
            "historical_days": hist,
            "recent_days": recent,
            "reason": (
                f"相对并集最深的 {self.best_source}({self.deepest_start}):"
                f"历史 +{hist} 天、近期 +{recent} 天。"
                + ("**历史增量为 0 —— 这段我们已经有了**,"
                   "报成「大赢家」多半是拿单一个源当了基线(M-118 就是这样)"
                   if hist == 0 else "")),
        }


def build(rows: Sequence[dict], *, today: Optional[str] = None) -> dict:
    """`rows` 每行 `{symbol, source, n, first, last}` → 按标的的并集覆盖。"""
    today = today or dt.date.today().isoformat()
    by_sym: dict = {}
    for r in rows or []:
        sym = str((r or {}).get("symbol") or "")
        if not sym or not r.get("first") or not r.get("last"):
            continue
        by_sym.setdefault(sym, []).append(SourceSpan(
            str(r.get("source") or "?"), int(r.get("n") or 0),
            str(r["first"])[:10], str(r["last"])[:10]))

    out: dict = {}
    for sym, spans in sorted(by_sym.items()):
        spans_t = tuple(sorted(spans, key=lambda s: s.first))
        latest = max(s.last for s in spans_t)
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(latest)).days
        if age > STALE_AFTER_DAYS:
            v, why = STALE, (
                f"最新的源也停在 {latest}({age} 天前)—— **历史已在库,"
                f"回填只补近期**。最深 {min(s.first for s in spans_t)} "
                f"来自 {min(spans_t, key=lambda s: s.first).source}")
        else:
            v, why = COVERED, (
                f"新鲜到 {latest};最深 {min(s.first for s in spans_t)} 来自 "
                f"{min(spans_t, key=lambda s: s.first).source}"
                f"({len(spans_t)} 个源)")
        out[sym] = SymbolCoverage(sym, spans_t, v, why)
    return out


def lookup(cov: dict, symbol: str) -> SymbolCoverage:
    """**缺失是一个答案,不是一个空** —— 返回带 `absent` 裁决的对象。"""
    return cov.get(symbol) or SymbolCoverage(
        symbol, (), ABSENT,
        "库里没有这个标的(任何源)—— 回填的全部都是增量")


def as_json(cov: dict) -> dict:
    """给跨 lane 消费的扁平形状。**`deepest_start` 排在最前**,
    因为那是回填前唯一必须看的字段。"""
    return {
        sym: {
            "verdict": c.verdict,
            "deepest_start": c.deepest_start,
            "best_source": c.best_source,
            "latest": c.latest,
            "n_sources": len(c.per_source),
            "per_source": [
                {"source": s.source, "n": s.n, "first": s.first, "last": s.last}
                for s in c.per_source],
            "reason": c.reason,
        } for sym, c in cov.items()
    }


#: 取覆盖的 SQL。**一次全表聚合,不按标的 fan-out** ——
#: Supabase 是免费档(Jazz 2026-08-30:「能不增加用量就不增加」),
#: 而 262 个标的各查一次会把一个 O(1) 变成 O(n)。
COVERAGE_SQL = """
select symbol, source, count(*) as n,
       min(trade_date)::text as first, max(trade_date)::text as last
from ohlcv_daily
group by symbol, source
"""

#: 跨 lane 契约说明 —— 随响应一起返回,免得下一次又是从单一个源推断。
CONSUMER_NOTE = (
    "回填任何标的之前先查这里。**基线是 `deepest_start`(跨源并集),"
    "不是你手上那个源的起点** —— M-118 拿 binance_hist 当基线,"
    "把 Supabase 已有的 PENDLE(2021-04-28,coingecko)报成了「+820 天大赢家」。"
    "`verdict=stale` 意味着历史已在库、只缺近期;"
    "`absent` 才是真的全部缺失。"
)
