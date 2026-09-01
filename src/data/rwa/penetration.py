"""代币化渗透率 —— 唯一跨越两个世界的比例 (S-267).

## Jazz 的更正(2026-09-01),以及我错在哪

> 「**链上的换手只是映射**,多少比例和资产的发行占总流通盘才更重要。
> 现在链上资产发行方其实只是相当于一个中小型券商和做市商。」

我在 S-266 把 `turnover`(24h 成交 / 代币化市值)写成「**流的强度**」。那是错的:
代币化 NVDA 在链上换手一百次,NVDA 那边一股没动。换手度量的是**这个映射层
内部的活跃度**,它对标的完全沉默 —— 而 S-266 的全部动机是「离因更近」。

真正的量是:

    渗透率 = 代币化发行量 / 标的的总流通盘

它是**唯一一个分子在链上、分母在传统世界**的比值,所以也是唯一能回答
「这条流对标的重不重要」的数。其余指标(市值、成交、换手、集中度)全部只在
代币化世界内部说话。

## 这个数的量级决定怎么读整件事

网检 2026-09-01:代币化股票+ETF 全市场 **$2.42B**(我们自己测的)。
而单是 NVDA 一家的市值就是万亿级。所以渗透率的量级是**万分之几甚至更低** ——
这在算术上确认了 Jazz 论点的后半句(「相对不影响那边」),
同时也界定了前半句的规模:

> 「发行方其实只是相当于一个中小型券商和做市商。」

一个中小型券商的自营盘规模,不会重定价它经手的标的。**所以渗透率不是一个
「机会有多大」的指标,而是一个「这件事离重要还有多远」的指标** ——
它的**变化率**比它的**水平**有信息量得多。

## 为什么分母必须带出处,且必须能拒绝

`data_layer.py:2951` 在取不到真实市值时有一个兜底:

    market_cap = price_now * volume_24h * 30   # rough ADV→cap proxy

对 F 支柱来说那是合理的(宁可粗糙也别把 mcap 饿成 0 让资产掉到 F)。
**但拿它做渗透率的分母是灾难性的**:分子是一个精确到美元的链上市值,
分母是一个 30 倍 ADV 的猜测,得到的比例看起来完全正常而实际毫无意义。

所以 `Penetration` 强制带 `denom_source`,且 `ADV_PROXY` 这个来源**直接判不可用**。
这与规则 #9(生产路径不用假数据,宁可空且标记)是同一条。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── 分母的出处。**必须显式,不能默认。** ─────────────────────────────────
FUNDAMENTALS_EQUITY = "fundamentals_equity"   # EODHD Highlights::MarketCapitalizationMln
ETF_AUM = "etf_aum"                           # EODHD ETF_Data::TotalAssets
ADV_PROXY = "adv_proxy"                       # price×volume×30 —— **不可用于渗透率**
UNAVAILABLE = "unavailable"

#: 可以用来算渗透率的分母来源。**白名单,不是黑名单** ——
#: 新增一个来源必须显式加进来,而不是「只要不在黑名单里就放行」。
TRUSTED_DENOMS = frozenset({FUNDAMENTALS_EQUITY, ETF_AUM})

OK, NO_DENOM, UNTRUSTED_DENOM, NO_NUMER = (
    "ok", "no_denominator", "untrusted_denominator", "no_numerator")


@dataclass(frozen=True)
class Penetration:
    """代币化发行量占标的流通盘的比例 + 它算不算得数。

    `ratio` 与 `verdict` 分开,与 `PanelEstimate`(S-266)、`RegimeQuorum`(S-263)
    同一形状。这里 `verdict` 尤其不能省:一个用 ADV 代理算出来的渗透率,
    和一个用真实市值算出来的,在数值上长得**一模一样**。
    """
    symbol: str
    ratio: Optional[float]
    tokenized_mcap: Optional[float]
    underlying_mcap: Optional[float]
    denom_source: str
    verdict: str
    reason: str

    @property
    def usable(self) -> bool:
        return self.verdict == OK

    @property
    def bps(self) -> Optional[float]:
        """以基点表示 —— 这个量的自然刻度。$2.4B / 万亿级 ⇒ 个位数 bp。"""
        return None if self.ratio is None else self.ratio * 10_000


def compute(symbol: str, tokenized_mcap: Optional[float],
            underlying_mcap: Optional[float], denom_source: str) -> Penetration:
    """算一个标的的渗透率。**分母来源是必需参数,不给默认值。**

    不给默认值是故意的:一个 `denom_source="unknown"` 的默认会让调用点
    忘记传它而照样得到一个数,而那个数无法与真实的区分开。
    """
    def _p(ratio, verdict, reason):
        return Penetration(symbol, ratio, tokenized_mcap, underlying_mcap,
                           denom_source, verdict, reason)

    if tokenized_mcap is None:
        return _p(None, NO_NUMER, "代币化市值未测(I1:未测≠0)")
    if underlying_mcap is None or underlying_mcap <= 0:
        return _p(None, NO_DENOM,
                  f"拿不到 {symbol} 的标的流通盘 —— **不要用任何代理值补上**,"
                  f"没有分母就没有渗透率")
    if denom_source not in TRUSTED_DENOMS:
        return _p(None, UNTRUSTED_DENOM,
                  f"分母来源 '{denom_source}' 不在白名单 {sorted(TRUSTED_DENOMS)} 里。"
                  f"若它是 data_layer 的 ADV 代理(price×volume×30),那是给 F 支柱"
                  f"用的粗估,**做渗透率的分母会得到一个看起来正常而毫无意义的比例**")

    r = tokenized_mcap / underlying_mcap
    return _p(r, OK,
              f"{symbol}:代币化 {_usd(tokenized_mcap)} / 标的 {_usd(underlying_mcap)}"
              f" = {r * 10_000:.2f} bp(分母来源 {denom_source})")


def aggregate(pens: list[Penetration]) -> dict:
    """面板层的渗透率。**用可算的那部分做分子和分母,并报出覆盖率。**

    不能对 `ratio` 求平均:每个标的的分母差几个数量级,等权平均会让一只
    小盘股的高渗透率主导整个读数。正确做法是分子分母各自求和 ——
    那等于按标的规模加权,也就是「整个代币化层占它所映射的那部分传统盘多少」。
    """
    usable = [p for p in pens if p.usable]
    if not usable:
        return {"ratio": None, "bps": None, "n_usable": 0, "n_total": len(pens),
                "coverage": 0.0,
                "reason": "没有任何标的同时具备可信分母与已测分子 —— "
                          "先把 EODHD fundamentals 的分母接上"}
    num = sum(p.tokenized_mcap for p in usable)
    den = sum(p.underlying_mcap for p in usable)
    r = num / den if den else None
    # 覆盖率按【分子的金额】算,不按标的条数 —— 少一只万亿市值的标的,
    # 和少一只两千万的,对结论的影响差几个数量级,而条数对此完全沉默。
    all_num = sum(p.tokenized_mcap for p in pens if p.tokenized_mcap)
    return {
        "ratio": r,
        "bps": None if r is None else r * 10_000,
        "n_usable": len(usable),
        "n_total": len(pens),
        "coverage": round(num / all_num, 3) if all_num else 0.0,
        "reason": f"{len(usable)}/{len(pens)} 个标的可算,覆盖代币化市值的 "
                  f"{(num / all_num * 100) if all_num else 0:.1f}%;"
                  f"分子分母分别求和(**不是对比率求平均** —— 分母差几个数量级,"
                  f"等权会让小盘股主导)",
    }


def eodhd_ticker(symbol: str, *, exchange: str = "US") -> str:
    """RWA 的 symbol → EODHD ticker。**只做大小写与交易所后缀,不猜映射。**

    CG 的 RWA symbol 实测形如 `nvda` / `tsla` / `spy`,与美股 ticker 同形。
    但 `spacex` 这类**未上市标的没有 EODHD 对应物** —— 它们会拿不到分母,
    于是判 `no_denominator` 并被 `aggregate` 的覆盖率如实扣掉。
    **这是正确的结果,不是缺陷:一个未上市公司的「总流通盘」本来就不可比。**
    """
    return f"{symbol.strip().upper()}.{exchange}"


def _usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"
