"""一条收益序列只能来自一个源 —— 而且必须说出是哪个 (S-230).

WHY THIS EXISTS AS A SHARED HELPER AND NOT A DOCSTRING. 这条规则本来已经写在
`forward_return_backfill.py` 里(「NO CROSS-SOURCE RETURNS」),写得很清楚,
而且是对的。**但它写在我 lane 的一个模块里,C 的模拟器 import 不到一句 docstring。**
于是同一条规则,在一个地方被强制,在另一个地方被重新违反。

MEASURED 2026-08-25 (M-83「hold-the-panel」①基准):

    报告                     V0 buy-hold 11 资产   总回报 -30.26%  Sharpe +1.881
                             V1 weekly rebal 11    总回报 -86.17%  Sharpe +1.493

    而同一窗口(06-13 → 08-24)11 个资产的等权实测:

        binance_hist   +8.39%    覆盖 06-13 → 07-27  ← 07-27 之后全缺
        coingecko     +36.67%    覆盖 06-13 → 08-23  ← 只有 9 个 symbol
        hyperliquid   +22.04%    覆盖 08-09 → 08-23  ← 只有 15 天

**没有任何一个源给出负数。** 11 个名字里 8 个上涨,最差 -28.5%,最好 +97.4%。
一个上涨的市场,被测成 -86%。

### 两个指纹,任何一个单独出现都该停下来

**① Sharpe 与总回报符号矛盾。** `-86.17% 总回报` 配 `+1.493 Sharpe` 在数学上要求
日收益的**算术均值为正而连乘积坍塌** —— 那是巨幅交替跳动的签名:
价格跳到高价源时记一个大涨,跳回时记一个大跌。均值留正,乘积归零。
**这不是市场的形状,是拼接的形状。**

**② 各源覆盖窗口不重合。** `binance_hist` 死于 07-27,`hyperliquid` 起于 08-09。
任何"哪个源有这天的价就用哪个"的取数逻辑,**必然在窗口中间跨源**,
而三个源对同一个 BTC 同一个窗口的读数是 +1.6% / +21.3% / +19.1%。

这是 S-106 的原话:**两种 bar 约定之间的拼接会被读成市场结构。** 那次是价格轴,
这次是日期轴 × 源轴,而后果更大:它成了 ①基准,而 ①基准是**其他每一个 sleeve
用来对比的地面**。地面错了,上面每一条比较都错。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

#: 可用于收益序列的源。
#:
#: ⚠️ 禁的是【端点】,不是 vendor (S-234)。S-195 的证据是
#: `/coins/{id}/market_chart/range` 返回采样点(短窗口下是小时点),而
#: `/coins/{id}/ohlc/range` + `interval=daily`(Pro 专属)返回真 K 线 ——
#: 端点实测可达,我们付了四个月,调用 0 次。
#:
#: 我在 S-195 结尾写的「CoinGecko 不是定价源」比证据宽,Minimax-C 照着它把整个
#: vendor 划掉,于是只剩 binance_hist(44d)和 hyperliquid(15d)两段不重合的窗口,
#: 得出「60d 在单源下 structurally infeasible」。**推导是对的,前提是我写宽的。**
#:
#: 所以标签按【端点】分,不按 vendor 分:同一个 vendor 的两个端点是两种数据。
#: 存量行标 `coingecko`(来自 market_chart,不可用于收益);
#: 回填行必须标 `coingecko_pro_ohlc`。
TRUSTED_RETURN_SOURCES = ("binance_hist", "hyperliquid", "eodhd", "coingecko_pro_ohlc")

#: 明确不可用于收益序列,附原因 —— 让拒绝的信息量大于一个布尔值。
BARRED_RETURN_SOURCES = {
    "coingecko": "market_chart 采样点塌缩成日期,不是收盘 (S-195);"
                 "改用 /ohlc/range interval=daily 并标为 coingecko_pro_ohlc",
    "yfinance":  "63 天不更新,已死",
}


class CrossSourceError(RuntimeError):
    """一条收益序列跨了源。抛出,不警告 —— 警告会被记进日志然后被忽略。"""


@dataclass(frozen=True)
class SeriesSource:
    """一条序列的源与覆盖,作为结果的一部分被带走,而不是留在作者脑子里。"""

    source: str
    n_rows: int
    first_day: str
    last_day: str
    n_symbols: int

    def as_payload(self) -> dict[str, Any]:
        return {"price_source": self.source, "rows": self.n_rows,
                "coverage": f"{self.first_day}..{self.last_day}",
                "symbols": self.n_symbols}


def assert_single_source(rows: Sequence[Mapping[str, Any]], *,
                         job: str, source_key: str = "source") -> SeriesSource:
    """所有行必须同源;返回那个源与它的覆盖。

    不接受"默认源" —— **调用方必须能说出自己在用哪个源**,因为 M-83 的作者
    当时也说不出:报告里 4 个变体、11 个资产、73 天,没有一处写价源。
    """
    if not rows:
        raise CrossSourceError(f"{job}: 空序列 —— 没有行不等于没有波动")

    seen: dict[str, int] = {}
    days: list[str] = []
    syms: set[str] = set()
    for r in rows:
        s = str(r.get(source_key) or "")
        seen[s] = seen.get(s, 0) + 1
        d = str(r.get("trade_date") or "")[:10]
        if d:
            days.append(d)
        if r.get("symbol"):
            syms.add(str(r["symbol"]))

    if len(seen) > 1:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(seen.items(), key=lambda kv: -kv[1]))
        raise CrossSourceError(
            f"{job}: 收益序列跨了 {len(seen)} 个源 ({parts})。"
            f"三个源对同一 BTC 同一窗口给 +1.6% / +21.3% / +19.1%,"
            f"拼接会被读成市场结构 (S-106/S-230)。选一个源,声明它,接受它的覆盖缺口。")

    src = next(iter(seen))
    if src not in TRUSTED_RETURN_SOURCES:
        raise CrossSourceError(
            f"{job}: 源 '{src}' 不可用于收益序列 "
            f"(允许: {', '.join(TRUSTED_RETURN_SOURCES)})。"
            + (f" 原因:{BARRED_RETURN_SOURCES[src]}" if src in BARRED_RETURN_SOURCES
               else " 未知源 —— 先声明它的 bar 约定再用。"))

    return SeriesSource(src, len(rows), min(days) if days else "?",
                        max(days) if days else "?", len(syms))


def sanity_check_curve(total_pct: float, sharpe: float, *, job: str) -> str | None:
    """总回报与 Sharpe 的符号矛盾 —— 返回原因,None 表示无矛盾。

    **这不是风格检查,是拼接探测器。** 一条真实的曲线,累计亏损时算术均值几乎
    不可能为正;要同时成立,日收益必须包含巨幅交替跳动,而那正是跨源取价的签名。

    M-83 实测:V1 总回报 -86.17%,Sharpe +1.493 —— 两个数各自看都不像错的,
    **放在一起才暴露。** 所以这个检查必须看两个数,而不是分别校验每一个。
    """
    if total_pct < 0 and sharpe > 0:
        return (f"{job}: 总回报 {total_pct:.2f}% 为负而 Sharpe {sharpe:+.3f} 为正 —— "
                f"要求日收益算术均值为正而连乘积坍塌,那是巨幅交替跳动的签名,"
                f"通常来自跨源取价 (S-230)。先查价源单一性,再解读这条曲线。")
    if total_pct > 0 and sharpe < 0:
        return (f"{job}: 总回报 {total_pct:.2f}% 为正而 Sharpe {sharpe:+.3f} 为负 —— "
                f"同一个矛盾的另一半;同样先查价源。")
    return None


def coverage_gap_warning(sources: Iterable[SeriesSource]) -> str | None:
    """多条序列各自单源、但彼此覆盖窗口不重合时,它们不可比。

    binance_hist 死于 2026-07-27,hyperliquid 起于 2026-08-09 —— 用前者做的
    ①基准和用后者做的 sleeve **测的不是同一段市场**,而两个数字会被并排放进
    同一张表里比较。
    """
    ss = list(sources)
    if len(ss) < 2:
        return None
    lo = max(s.first_day for s in ss)
    hi = min(s.last_day for s in ss)
    if lo > hi:
        return ("这些序列的覆盖窗口完全不重合 —— 它们测的不是同一段市场,"
                "不可并排比较: " + "; ".join(f"{s.source} {s.first_day}..{s.last_day}"
                                             for s in ss))
    return None
