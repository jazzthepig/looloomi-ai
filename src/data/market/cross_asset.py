"""跨资产:相对估值、相关性、历史分位 —— **窗口跟着数字走** (S-274).

## Jazz 的要求(2026-09-02)

> 「那个层面是在 fx 市场的,不是 etf 层面可以体现的。我提供这个逻辑可以寻找
> 各种大类资产和相对估值和相关性,还有相应历史估值分位。」

## 这三样共用一个陷阱:窗口的选择就是结论

**同一个值,一年窗口 95 分位、十年窗口可能 40 分位。** 而绝大多数「历史分位」
的报法只给一个数字,把窗口藏在实现里 —— 于是读的人以为自己在读市场,
实际在读我们选的那个窗口。

相关性同理:十年一个相关系数会把「2020 之前是 +0.6、之后翻成 −0.3」抹平成
一个看起来温和的 +0.1,**而那个 +0.1 在任何一段真实时期里都没有出现过。**

所以本模块的核心产出不是分位数,是 **`spread`** ——
同一个值在多个窗口下分位数的极差。

    spread 小  ⇒ 「这个位置」是稳健的陈述
    spread 大  ⇒ **那个分位数是窗口选出来的,不是市场给的**

一个 spread 0.55 的「90 分位」和一个 spread 0.03 的「90 分位」,
在下游不能长得一样。这与 S-263 的 `agreement`、S-266 的 `dispersion`、
S-267 的 `denom_source` 是同一条:**值 + 它值不值得信,永远两个字段。**

## 相关性要报离散,不报均值

滚动相关的**均值**是最没有信息量的那个统计量 —— 它恰好是被抹平的那个数。
`rolling_corr()` 因此返回 min / max / 最新 / 符号翻转次数,
而 `mean` 只作为参考项列出,并在 reason 里说明为什么不该单看它。

## 相对估值用比价,不用基本面

跨大类做相对估值,最少假设的方式是**比价及其自身的历史分位** ——
GLD/TLT 这个比值今天在它自己十年分布的什么位置。
它不需要盈利、不需要贴现率,因此也不会继承那些估计量的误差。

代价是它只回答「相对于自己的历史」,不回答「相对于内在价值」。
**这个边界写在这里,免得下游把它当成后者。**
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

#: 默认的多窗口。**必须多于一个** —— 单窗口的分位数没有 spread 可言,
#: 而 spread 正是本模块存在的理由。
DEFAULT_WINDOWS_D = (252, 756, 1260, 2520)      # ≈1y / 3y / 5y / 10y

#: **有经济含义的锚点。** Jazz 2026-09-02:「先看到 2019 年开始,那是新的
#: 历史周期起点。」
#:
#: 一个滚动天数是任意的;`2019-01-01` 不是 —— 它标记的是 2019-09 回购危机 +
#: 2020 QE 之后那个货币体制的起点。**用一个可辩护的日期,好过用一个整数。**
#:
#: 实测(2026-09-02)证明这个切点是对的:三个黄金比价对 2019 **之前**的分位是
#: **100.0%** —— 不是 99.9%,是高于 2019 年前的每一个交易日。那 875 天对
#: 「今天在哪」零信息量,只会说「比全部都高」,而它们正是全窗口 spread 0.52 的来源。
#: 切在 2019 之后,三个子窗口只差约 5 个百分点(spread 0.033)⇒ robust。
#:
#: **同一个价格,窗口切对了,结论从「不可信」变成「可信」。**
#: 所以 spread 大不一定是数据脏,也可能是**切点没找对** —— 这两个要分开读:
#:   · 子窗口之间散、且不存在一个让它们收敛的切点 ⇒ 真的窗口敏感
#:   · 存在一个切点让它们收敛 ⇒ **那个切点是体制边界,是信息不是噪声**
REGIME_ANCHORS = {
    "2019+": "2019-01-01",       # 回购危机 → QE 常态化,新货币体制起点
    "post_qe": "2020-04-01",     # COVID 后无限 QE 落地
    "2022+": "2022-01-01",       # 加息周期起点
}

#: ⚠️ 货币与商品 ETF 带**结构性 carry / 费率拖累**:FXY 持日元近零息而美元有息,
#: GLD 约 0.40%/年费率。单年可忽略,**十一年窗口上累积成实质偏差** ——
#: 这是「不要用长窗口」的第二个独立理由,与体制切点无关。
ETF_DRAG_NOTE = ("比价用的是 ETF,带 carry/费率拖累(FXY 无息 vs 美元有息、"
                 "GLD ~0.40%/年)。长窗口分位会被这个漂移污染,短窗口不会")

#: 一个窗口至少要这么多个观测才算数。低于它不给分位,而不是给一个脆的。
MIN_OBS = 60

#: `spread` 超过它,判为「窗口敏感」—— 分位数是窗口选出来的。
SPREAD_SENSITIVE = 0.25

ROBUST, WINDOW_SENSITIVE, THIN, NO_DATA = (
    "robust", "window_sensitive", "thin", "no_data")


@dataclass(frozen=True)
class PercentileRead:
    """一个值在自己历史里的位置 —— **以及这个位置有多依赖窗口**。"""
    value: Optional[float]
    by_window: dict = field(default_factory=dict)   # window_days -> pct | None
    verdict: str = NO_DATA
    reason: str = ""

    @property
    def measured(self) -> list:
        return [p for p in self.by_window.values() if p is not None]

    @property
    def spread(self) -> Optional[float]:
        """同一个值在不同窗口下分位数的极差。**本模块的主产出。**"""
        m = self.measured
        return None if len(m) < 2 else max(m) - min(m)

    @property
    def usable(self) -> bool:
        """`window_sensitive` **仍然可用** —— 它是信息。`thin` 不可用。"""
        return self.verdict in (ROBUST, WINDOW_SENSITIVE)


def _pct_rank(series: Sequence[float], value: float) -> Optional[float]:
    """`value` 在 `series` 里的分位(0–1)。**含并列的中点法**,
    因为纯 `<` 会让一个恰好等于历史最大值的观测报 1.0 —— 那读起来像"史无前例",
    而它只是"并列最高"。"""
    xs = [x for x in series if x is not None and x == x]
    if len(xs) < MIN_OBS:
        return None
    below = sum(1 for x in xs if x < value)
    equal = sum(1 for x in xs if x == value)
    return (below + 0.5 * equal) / len(xs)


def percentile(series: Sequence[float], *,
               windows: Sequence[int] = DEFAULT_WINDOWS_D) -> PercentileRead:
    """最新值在多个回看窗口下的分位。`series` 按时间升序,末尾是最新。

    **不给一个分位数,给一组** —— 因为「一个分位数」这件事本身就是误导:
    它把窗口这个假设藏进了实现里。
    """
    xs = [x for x in series if x is not None and x == x]
    if not xs:
        return PercentileRead(None, {}, NO_DATA, "序列为空")
    cur = xs[-1]
    by = {w: _pct_rank(xs[-w:], cur) for w in windows}

    read = PercentileRead(cur, by)
    m = read.measured
    if not m:
        return PercentileRead(
            cur, by, THIN,
            f"没有任何窗口达到 {MIN_OBS} 个观测(序列长 {len(xs)})—— "
            f"**不给一个脆的分位数**")
    if len(m) < 2:
        return PercentileRead(
            cur, by, THIN,
            f"只有 1 个窗口够长(序列长 {len(xs)})—— **单窗口没有 spread,"
            f"而 spread 才是判断这个分位数可不可信的东西**")

    sp = read.spread
    if sp > SPREAD_SENSITIVE:
        return PercentileRead(
            cur, by, WINDOW_SENSITIVE,
            f"分位随窗口从 {min(m):.0%} 变到 {max(m):.0%}(极差 {sp:.0%} > "
            f"{SPREAD_SENSITIVE:.0%})—— **这个分位数是窗口选出来的,不是市场给的**。"
            f"报它必须连窗口一起报")
    return PercentileRead(
        cur, by, ROBUST,
        f"{len(m)} 个窗口下分位 {min(m):.0%}–{max(m):.0%}(极差 {sp:.0%})—— "
        f"位置对窗口不敏感")


@dataclass(frozen=True)
class CorrRead:
    """滚动相关的读数。**均值是这里最没有信息量的统计量。**"""
    latest: Optional[float]
    lo: Optional[float]
    hi: Optional[float]
    mean: Optional[float]
    n_windows: int
    sign_flips: int
    reason: str

    @property
    def range(self) -> Optional[float]:
        return None if self.lo is None or self.hi is None else self.hi - self.lo


def rolling_corr(a: Sequence[float], b: Sequence[float], *,
                 window: int = 126) -> CorrRead:
    """滚动相关。**报 min/max/翻转次数,均值只作参考。**

    一个十年期的单一相关系数会把「2020 前 +0.6、之后 −0.3」抹成 +0.1,
    而那个 +0.1 **在任何一段真实时期里都没有出现过**。
    """
    n = min(len(a), len(b))
    a, b = list(a[-n:]), list(b[-n:])
    vals: list = []
    for i in range(window, n + 1):
        wa, wb = a[i - window:i], b[i - window:i]
        c = _corr(wa, wb)
        if c is not None:
            vals.append(c)
    if not vals:
        return CorrRead(None, None, None, None, 0, 0,
                        f"样本不足以形成任何 {window} 日窗口(共 {n} 个观测)")
    flips = sum(1 for x, y in zip(vals, vals[1:]) if x * y < 0)
    mean = sum(vals) / len(vals)
    return CorrRead(
        vals[-1], min(vals), max(vals), mean, len(vals), flips,
        f"{len(vals)} 个 {window} 日窗口:最新 {vals[-1]:+.2f}、"
        f"区间 [{min(vals):+.2f}, {max(vals):+.2f}]、符号翻转 {flips} 次。"
        f"**均值 {mean:+.2f} 只作参考** —— 它恰好是被抹平的那个数;"
        f"翻转 {flips} 次说明这对资产的关系不是一个常数")


def _corr(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    d = math.sqrt(sxx * syy)
    return None if d == 0 else sxy / d


def percentile_since(dated: Sequence, *, anchors: dict = None) -> dict:
    """按**有经济含义的锚点**给分位,而不是按滚动天数。

    `dated` 是 `[(date_str, value), ...]`,按时间升序。

    额外返回 `pre_earliest_anchor` —— 最早锚点**之前**那段的分位。
    它存在的理由是实测那次:三个黄金比价对 2019 前是 **100.0%**,
    而 100.0% 不是一个分位数,是一句「这段历史对当下零信息量」。
    **把它单列出来,读的人才会知道该丢掉它,而不是把它平均进去。**
    """
    anchors = anchors or REGIME_ANCHORS
    xs = [(d, v) for d, v in dated if v is not None and v == v]
    if not xs:
        return {"latest": None, "verdict": NO_DATA, "reason": "序列为空"}
    cur = xs[-1][1]
    out: dict = {}
    for name, since in sorted(anchors.items(), key=lambda kv: kv[1]):
        seg = [v for d, v in xs if d >= since]
        out[name] = _pct_rank(seg, cur)
    earliest = min(anchors.values())
    pre = [v for d, v in xs if d < earliest]
    pre_pct = _pct_rank(pre, cur)

    m = [p for p in out.values() if p is not None]
    if len(m) < 2:
        return {"latest": cur, "by_anchor": out, "pre_earliest_anchor": pre_pct,
                "verdict": THIN,
                "reason": f"只有 {len(m)} 个锚点窗口够长(需 ≥{MIN_OBS} 个观测)"}
    sp = max(m) - min(m)
    verdict = WINDOW_SENSITIVE if sp > SPREAD_SENSITIVE else ROBUST
    pre_note = ""
    if pre_pct is not None and pre_pct >= 0.999:
        pre_note = (f" ⚠️ 对最早锚点【之前】那段是 {pre_pct:.1%} —— "
                    f"**高于那段的每一个观测,所以那段对「今天在哪」零信息量**,"
                    f"把它平均进来只会稀释结论")
    return {
        "latest": cur,
        "by_anchor": {k: (None if v is None else round(v, 3)) for k, v in out.items()},
        "pre_earliest_anchor": None if pre_pct is None else round(pre_pct, 3),
        "spread": round(sp, 3),
        "verdict": verdict,
        "reason": (f"锚点窗口下分位 {min(m):.0%}–{max(m):.0%}(极差 {sp:.0%})"
                   f"{'—— 对切点不敏感' if verdict == ROBUST else '—— 仍然窗口敏感'}"
                   f"{pre_note}。{ETF_DRAG_NOTE}"),
    }


def relative_value(a: Sequence[float], b: Sequence[float], *,
                   windows: Sequence[int] = DEFAULT_WINDOWS_D) -> dict:
    """比价 A/B 及其自身的历史分位。

    **它只回答「相对于自己的历史」,不回答「相对于内在价值」。**
    比价法的代价就是这个边界 —— 写在这里,免得下游把它读成后者。
    """
    n = min(len(a), len(b))
    ratio = [(x / y) for x, y in zip(a[-n:], b[-n:])
             if y not in (None, 0) and x is not None]
    r = percentile(ratio, windows=windows)
    return {
        "ratio_latest": r.value,
        "percentile_by_window": {str(k): (None if v is None else round(v, 3))
                                 for k, v in r.by_window.items()},
        "spread": None if r.spread is None else round(r.spread, 3),
        "verdict": r.verdict,
        "reason": r.reason,
        "scope": "相对于该比价自身的历史分布 —— **不是相对于内在价值**",
    }
