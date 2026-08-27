"""信号战绩:一次只用一种度量,并且说得出它测不了什么 (S-248).

## Jazz 2026-08-27:「signal performance 现在展示的问题很大,我们不是有几个赚钱的吗?」

有。而且这个问题指对了地方 —— 但答案只对一半,两半都要说。

### 四条缺陷叠在一起,每一条都是同一个形状

**① 面板标题说的是 α,复利的是绝对收益。**
`_compute_metrics` 取 `r["return_pct"]` 复利成曲线,而 UI 把它标成
「CUMULATIVE ALPHA VS BTC/SPY」。`return_pct = exit/entry - 1`,**不含基准**。
`alpha_30d = return_pct_30d - benchmark_return_30d` 才是超额。
一条绝对收益曲线被贴上了超额收益的标签。

**② 曲线的持仓期和判定窗口不是同一个东西。**

    outcome_30d=WIN   n=23   持仓 8.0 天   return_pct=−2.46   return_pct_30d=+6.01
                             其中 12/23 在【退出时是亏的,30 天时是赚的】

`exit_reason` 几乎全是 `DOWNGRADE` —— 评级一降就平仓,平均 8 天;
而 WIN/LOSS 标签来自固定 30 天窗口。**曲线用 8 天的数,胜率用 30 天的数,
它们在 12 个样本上符号相反。** 同一块面板,两套度量。

**③ 出口价源 83/95 是被禁的源。**

    coingecko:vs_BTC   n=38   ret30=−13.38%   ← S-195:market_chart 采样点塌缩,不是收盘
    yfinance:vs_SPY    n=45   ret30= −1.78%   ← S-230:63 天不更新,已死
    ohlcv_daily:*      n=12   ret30= +1.64%   ← 唯一可信

**可信子集的 30 天绝对收益是 +1.64%,coingecko 那 38 行是 −13.38%,差 15pp。**
这强烈提示那段负数里有相当部分是采样塌缩的产物,不是真实亏损。

**④ regime 分组不规范化,把一个 regime 拆成两个。**
`EASING`(1475, α−1.43)与 `Easing`(1185, α−5.43);
`RISK_ON`(856, α+5.83)与 `Risk-On`(330, α−6.17)——
**同一个 regime,符号相反,差 12pp。** 拼写在 2025-06-17 切换,
所以这两个「regime」其实是两段相邻时间窗:**归因表有一部分在测时代,不是在测 regime。**

### 「赚钱的那几个」在哪 —— 以及为什么现在还不能声称

    STRONG_OUTPERFORM   n=7    α30=+4.99%   ret30=+7.32%   α 胜率 71.4%
    OUTPERFORM          n=84   α30=−4.13%   ret30=−8.41%   α 胜率 26.0%

**最强那一档确实是显著正的。** 而且 legacy era 独立复现:
`STRONG OUTPERFORM` n=134,α_beta_adj=+7.99%,胜率 50%。

**但那 7 个信号【没有一个】用可信价源测出来** —— 全部来自 barred/none。
可信子集只有 12 行,而且它的 α 仍是 −2.97%(3/12 为正)。

所以诚实的结论是三句话,缺一不可:

1. **有一档是正的,而且在两个 era 独立出现** —— 不是噪声里的偶然。
2. **它是用被禁的价源测的** —— 按我们自己的规则(S-195/S-230),这个数不能声称。
3. **可信样本只有 12 个** —— 不足以支持任何方向的结论,包括"我们不行"。

**页面现在展示的 −26.19% 既不是坏消息也不是好消息 —— 它是一个不可测量的量,
被渲染成了一个可信的数。** 这和今天其余的缺陷是同一件事:
**「测不了」被投影成了「测出来是负的」。**

### 这个模块做什么

不修数,只让度量分开、并让每个数带着它的可信域走:

    · 一次只用一种 measure,并在 payload 里写明是哪一种
    · 按 outcome_source 分层:trusted / barred / unsourced,各报各的 n
    · 可信样本不足 → `verdict="insufficient"`,而不是给一个数
    · regime 一律 canonicalise 之后再分组
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

#: 可信的出口价源前缀。`ohlcv_daily` 走的是 binance_hist 血统。
#:
#: ⚠️ 判据是【前缀】不是子串:`outcome_source` 长这样 `ohlcv_daily:vs_BTC`,
#: 而 `cross_source:signal_entry_price->coingecko` 里也含 `coingecko` ——
#: 用子串判会把跨源行误分进 coingecko 桶,而跨源行属于第四类(S-241)。
TRUSTED_SOURCE_PREFIXES = ("ohlcv_daily:",)

#: 被禁的源,附原因 —— 拒绝的信息量要大于一个布尔值。
BARRED_SOURCE_PREFIXES = {
    "coingecko:": "market_chart 采样点塌缩成日期,不是收盘 (S-195)",
    "yfinance:":  "63 天不更新,已死 (S-230)",
}

#: 两种度量,永不混用。混用正是 S-248 ① 和 ② 的成因。
MEASURE_EXIT = "exit_return"      # return_pct:entry→exit,持仓期由 exit_reason 决定
MEASURE_ALPHA30 = "alpha_30d"     # 固定 30 天窗口,已减基准

#: 低于这个数,不给结论。12 个可信样本上的任何 Sharpe 都是噪声的名字。
MIN_MEASURABLE = 30


def canonical_regime(raw: Optional[str]) -> Optional[str]:
    """UPPER_SNAKE,唯一拼写;无法识别 → None。

    **任何按 regime 分组的地方都必须先过这一道。** `signals.py:380` 没有过,
    于是 `EASING` 与 `Easing` 被当成两个 regime(α 差 4pp),
    `RISK_ON` 与 `Risk-On` 差 12pp 且符号相反。拼写在 2025-06-17 切换,
    所以那不是两个 regime,是两段时间窗。

    ⚠️ **这里【不实现】,只转发。** 我的第一版自己写了一遍
    `s.upper().replace("-","_")` —— 而仓库里**已经有三个** regime 规范化实现
    (`cis_provider.canonical_regime` / `canonical_regime_strict` /
    `r70_rule.canonical_regime`),我把它变成了第四个。

    这正是今天早些时候我自己避开过的错:`test_no_route_is_shadowed._flatten()`
    已经解决过路由展平,我复用了它而没有重写 —— **两个展平器会各自漂移,
    而漂移的那一个会静默地少看几十条。** 半天之后我在 regime 上原样犯了一遍。

    而且我那版更差:只做大小写替换,**不校验是否属于已知 regime 集** ——
    一个拼错的标签会安静地变成一个合法的分组桶。`canonical_regime_strict`
    对无法识别的标签返回 None,那才是分组时想要的行为(归入 UNKNOWN 桶,
    而不是发明一个新 regime)。

    用 strict 而非宽松版还有第二个理由(S-207 / `test_regime_write_path`):
    宽松版会把"没读到"变成 `NEUTRAL`,而 ① 账本按这个标签定仓位 ——
    TIGHTENING 映射 0.5、NEUTRAL 映射 1.0,于是前向记录头两个 mark 都在双倍敞口上。
    **一个把 unknown 变成合法值的规范化器,只属于渲染侧。**
    """
    from src.data.cis.cis_provider import canonical_regime_strict
    return canonical_regime_strict(raw)


def classify_source(outcome_source: Optional[str]) -> tuple[str, str]:
    """(类别, 原因)。四类,不是两类。

    trusted / barred / cross_source / unsourced —— 后两类都不是"有源但不好",
    它们是**不同的失败**:跨源是拼接(S-241),无源是根本没记。
    """
    s = (outcome_source or "").strip()
    if not s:
        return "unsourced", "outcome_source 为空 —— 没有记录用哪个价源结算"
    if s.startswith("cross_source"):
        return "cross_source", f"入口与出口价源不同,收益不可用 (S-241):{s}"
    for p in TRUSTED_SOURCE_PREFIXES:
        if s.startswith(p):
            return "trusted", ""
    for p, why in BARRED_SOURCE_PREFIXES.items():
        if s.startswith(p):
            return "barred", why
    return "unknown", f"未声明的价源 '{s}' —— 先说明它的 bar 约定再用"


@dataclass(frozen=True)
class MeasureResult:
    """一个度量 + 它的可信域。别人给你一个 Sharpe;我们给你它测在什么上面。"""

    measure: str                     # MEASURE_EXIT | MEASURE_ALPHA30
    verdict: str                     # "measured" | "insufficient" | "unmeasurable"
    n_measurable: int
    n_total: int
    mean_pct: Optional[float]
    win_rate_pct: Optional[float]
    by_source: dict[str, int] = field(default_factory=dict)
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "measure": self.measure,
            "verdict": self.verdict,
            "n_measurable": self.n_measurable,
            "n_total": self.n_total,
            "source_mix": self.by_source,
        }
        if self.verdict == "measured":
            out["mean_pct"] = self.mean_pct
            out["win_rate_pct"] = self.win_rate_pct
        else:
            # 不给数,给原因。一个 12 样本上的 Sharpe 是噪声的名字。
            out["mean_pct"] = None
            out["win_rate_pct"] = None
            out["reason"] = self.reason
        return out


def measure(rows: Iterable[Mapping[str, Any]], *, which: str,
            trusted_only: bool = True,
            min_measurable: int = MIN_MEASURABLE) -> MeasureResult:
    """算一个度量。**一次只算一种**,并报出样本是怎么筛出来的。

    `trusted_only=True` 时只用可信价源 —— 那是能被声称的那部分。
    `False` 时把全部算进去,但 `by_source` 会把混入了什么写在脸上,
    调用方不能假装不知道。
    """
    field_name = {MEASURE_EXIT: "return_pct", MEASURE_ALPHA30: "alpha_30d"}.get(which)
    if field_name is None:
        raise ValueError(f"未知度量 '{which}' —— 只有 {MEASURE_EXIT} 与 {MEASURE_ALPHA30}")

    rows = list(rows)
    by_source: dict[str, int] = {}
    vals: list[float] = []

    for r in rows:
        cls, _why = classify_source(r.get("outcome_source"))
        by_source[cls] = by_source.get(cls, 0) + 1
        v = r.get(field_name)
        if v is None:
            continue
        if trusted_only and cls != "trusted":
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue

    n = len(vals)
    if n == 0:
        return MeasureResult(which, "unmeasurable", 0, len(rows), None, None, by_source,
                             "没有任何一行带着可用的价源与数值 —— 这不等于收益为零")
    if n < min_measurable:
        return MeasureResult(
            which, "insufficient", n, len(rows), None, None, by_source,
            f"只有 {n} 个可测样本 < {min_measurable} —— 不足以支持任何方向的结论,"
            f"包括'我们不行'。给出一个数会让读者以为它有信息。")

    mean = sum(vals) / n
    wins = sum(1 for v in vals if v > 0)
    return MeasureResult(which, "measured", n, len(rows),
                         round(mean, 3), round(100.0 * wins / n, 1), by_source)


def by_regime(rows: Iterable[Mapping[str, Any]], *, which: str = MEASURE_ALPHA30
              ) -> dict[str, dict[str, Any]]:
    """按 regime 归因 —— **先 canonicalise,再分组**。

    不加这一道,`EASING` 与 `Easing` 会各自成一行,而它们是同一个 regime 的
    前后两段时间。那张表就从"按 regime 归因"变成了"按时代归因",而标题不会变。
    """
    field_name = {MEASURE_EXIT: "return_pct", MEASURE_ALPHA30: "alpha_30d"}[which]
    buckets: dict[str, list[float]] = {}
    spellings: dict[str, set[str]] = {}

    for r in rows:
        raw = r.get("macro_regime")
        canon = canonical_regime(raw) or "UNKNOWN"
        v = r.get(field_name)
        if v is None:
            continue
        buckets.setdefault(canon, []).append(float(v))
        spellings.setdefault(canon, set()).add(str(raw))

    out: dict[str, dict[str, Any]] = {}
    for canon, vals in buckets.items():
        n = len(vals)
        merged = {
            "measure": which,
            "n": n,
            "mean_pct": round(sum(vals) / n, 3),
            "win_rate_pct": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
        }
        # 合并了几种拼写要说出来 —— 这是可审计性,不是装饰:
        # 读者应当能看出这一行是不是刚刚才被合并过。
        if len(spellings[canon]) > 1:
            merged["merged_spellings"] = sorted(spellings[canon])
        out[canon] = merged
    return out
