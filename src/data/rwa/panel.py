"""代币化 RWA 面板 —— 高维对象在前,标量在后 (S-266).

## 为什么不是一张「持仓量」表

Jazz,2026-09-01:「多重判断来决定股票和 etf 全市场持仓量」,然后:「**往高维度走**」。

`docs/HIGH_DIM_ONTOLOGY.md` §5 的空间表里,`Entity/Decision` 一行写着
「待定义 · 🎯 frontier · **内核的缺失层;从 holder/flow/治理事件起步**」。
这个模块是那一行的起步 ——

    Entity    发行方(Ondo / Kraken xStocks / Binance bStocks / …)
    Decision  把某一只传统资产搬上链,这是一个决策
    flow      那只代币的链上市值 = 这个决策吸到的资金

CoinGecko 的 `/rwas/*` 族恰好按这个形状给数据,而它的文档写明:
`tokenized_market_data` 反映的是 **the aggregated onchain tokenized market,
not the underlying asset's spot market** —— 代币化 Tesla 的市值与 Tesla 本身的
市值是两个独立的量。**那正是 Jazz 论点里「相对不影响那边」的可观测形式。**

## 降维必须写明保什么、丢什么(§4)

「股票 + ETF 全市场持仓量」是一个标量,而市场状态是高维的。§4 要求每一层投影
都申报它的守恒律。这里的级联:

    RWA 微观态(每个代币 × 每条链 × 每个场所)
      → RwaRow 逐资产          保:市值/成交/换手/24h 市值变化 + asset_type + 发行方
      → 多轴聚合               保:asset_type × issuer 两个轴,以及各自的集中度
      → 一个标量「持仓量」      保:值 **+ 置信度** —— 置信度不保就是把分歧平均掉

**I1(未测=NaN 永不为 0)在这里是硬约束**:`market_cap: null` 的 RWA 不是
市值为零的 RWA。实测 2026-09-01,`/rwas/markets` 顶层没有 `market_cap` 字段
(它嵌在 `tokenized_market_data` 里),取错层会得到 250 个 null —— 而把 null
当 0 求和,会得到一个「$0 全市场持仓量」并且不报错。

## 为什么必须多重判断

不是稳妥,是因为**这个数本身就有分歧**。2026-09-01 网检,同一个量在几周内出现
四个说法:$2.3B / $2.4B / $2.6B / 「突破 $3B」。分歧有四个来源,每一个都是设计约束:

    ① 口径边界    rwa.xyz 把 stocks 与 ETFs 报成【一个】分段;别的来源拆开
    ② 重复暴露    同一只 NVDA 被 Ondo/xStocks/bStocks 各自代币化 ——
                  按发行方求和会重复计【暴露】,但不重复计【代币】
    ③ 背书模型    全额托管 vs 镜像/合成,不该直接相加
    ④ 时点        7 月中 $2.3B、8 月 $2.33B,中间有来源说 $3B

所以 `total()` 返回的是 `PanelEstimate`(值 + 裁决 + 离散度),
与 `RegimeQuorum`(S-263)、`SourceHealth`(S-251)同一形状:
**一个 dispersed 的估计仍然是估计,但下游必须知道它是 dispersed 的。**

## 参考量级(2026-09-01 网检,用作 sanity 上下界,不做实时依赖)

    股票+ETF 链上市值   $2.33B (rwa.xyz 2026-08-19)
    一年前              $329M          → ~7x
    占链上 RWA 总盘     >15% of $29.5B
    2026 迄今成交量     $9B(1 月 $1B → 7 月 $9B)
    发行方             Ondo $955M · xStocks $507M · bStocks $334M
    链                 ETH 34% · BNB 30% · SOL 23%

换手 ≈ $9B / $2.3B ≈ **4x**,且过半发生在美股闭市时段。

⚠️ **S-267 更正:换手是映射层内部的活跃度,不是流。** 代币化 NVDA 换手一百次,
NVDA 那边一股没动。跨两个世界的比值在 `penetration.py` —— 代币化发行量 /
标的总流通盘,那才是「这条流对标的重不重要」的唯一答案。
按量级估:$2.42B 全市场 vs 标的的万亿级市值 ⇒ 渗透率在**个位数基点**,
这正是 Jazz 说的「发行方相当于一个中小型券商和做市商」的定量形式。
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# ── asset_type 是 CG 的封闭枚举,不是我们的自由文本 ────────────────────────
STOCK, ETF, COMMODITY = "stock", "etf", "commodity"
ASSET_TYPES = frozenset({STOCK, ETF, COMMODITY})

#: 「股票和 ETF 全市场持仓量」的口径。**集中在这里** —— 分歧来源①是口径边界,
#: 把它散在调用点上,两个调用点迟早给出两个不同的「全市场」。
EQUITY_LIKE = frozenset({STOCK, ETF})

# ── 裁决(值 + 置信度,S-263/S-251 同一形状)──────────────────────────────
AGREE, DISPERSED, SINGLE, NO_DATA = "agree", "dispersed", "single_source", "no_data"

#: 两个独立估计相差超过这个比例即判 dispersed。
#: 取 10%:实测公开来源之间的分歧($2.3B vs $2.6B ≈ 13%)本来就大于它,
#: 所以这个门槛的作用不是「几乎不触发」,而是**如实反映这个量确实有分歧**。
DISPERSION_LIMIT = 0.10


@dataclass(frozen=True)
class RwaRow:
    """一个代币化资产的当日观测。**未测的字段是 None,不是 0**(I1)。"""
    rwa_id: str
    name: str
    symbol: str
    asset_type: str
    market_cap: Optional[float]
    total_volume: Optional[float]
    mcap_change_24h: Optional[float]
    mcap_change_pct_24h: Optional[float]
    price_change_pct_30d: Optional[float] = None
    issuer: Optional[str] = None
    last_updated: Optional[str] = None

    @property
    def turnover(self) -> Optional[float]:
        """24h 成交 / 代币化市值 —— **映射层内部的活跃度,不是流**(S-267 更正)。

        ⚠️ 我在 S-266 把它写成「流的强度」。**那是错的。**
        Jazz 2026-09-01:「链上的换手只是映射,多少比例和资产的发行占总流通盘
        才更重要。」代币化 NVDA 在链上换手一百次,NVDA 那边一股没动 ——
        这个数对标的完全沉默,而 S-266 的全部动机是「离因更近」。

        跨两个世界的那个比值在 `penetration.py`:代币化发行量 / 标的总流通盘。

        还有一个口径疑点,**核清楚之前不得与「链上换手」并列**:实测 stock 日
        换手 0.384(年化 ~90x),而公开的**链上**口径是 $9B/$2.3B ≈ 4x/年。
        单日 $841M 是那个口径日均值的 20 倍 —— 最可能是 CG 的 `total_volume`
        含 CEX 成交(xStocks/bStocks 本来就在 Kraken 和 Binance 上交易)。

        它仍然有用:同一口径下的**时间序列**与**横截面对比**是有效的,
        只是它的绝对水平不能拿去跟别人的链上数字比。
        """
        if self.market_cap in (None, 0) or self.total_volume is None:
            return None
        return self.total_volume / self.market_cap

    @property
    def measured(self) -> bool:
        return self.market_cap is not None


@dataclass(frozen=True)
class PanelEstimate:
    """一个标量 + 它值不值得信。

    `value` 与 `verdict` 分开,理由与 `RegimeQuorum.regime`/`verdict` 相同:
    一个 dispersed 的持仓量仍然是持仓量,调用方有权同时拿到数值和它的成色。
    把不可信的值换成 None,会让「没有」和「不可信」再一次共用一个表示。
    """
    value: Optional[float]
    verdict: str
    reason: str
    n_measured: int = 0
    n_unmeasured: int = 0
    estimates: dict = field(default_factory=dict)
    dispersion: Optional[float] = None

    @property
    def usable(self) -> bool:
        """`single_source` 算可用但须标注;`dispersed` 与 `no_data` 不算。"""
        return self.verdict in (AGREE, SINGLE)


def parse_rows(payload: Iterable[dict], *, issuer_of: Optional[dict] = None
               ) -> list[RwaRow]:
    """把 `/rwas/markets` 的响应解析成面板行。

    ⚠️ 市场数据嵌在 `tokenized_market_data` 里,**顶层没有 `market_cap`**。
    2026-09-01 实测:按顶层取会得到 250 个 null,而把 null 当 0 求和会给出
    一个「$0 全市场持仓量」并且不抛任何异常。这就是 I1 存在的理由 ——
    **未测必须是 None 并被计数,不能塌成 0。**
    """
    issuer_of = issuer_of or {}
    out: list[RwaRow] = []
    for r in payload or []:
        if not isinstance(r, dict):
            continue
        tmd = r.get("tokenized_market_data") or {}
        if not isinstance(tmd, dict):
            tmd = {}
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        out.append(RwaRow(
            rwa_id=rid,
            name=str(r.get("name") or rid),
            symbol=str(r.get("symbol") or ""),
            asset_type=str(r.get("asset_type") or "").strip().lower(),
            market_cap=_num(tmd.get("market_cap")),
            total_volume=_num(tmd.get("total_volume")),
            mcap_change_24h=_num(tmd.get("market_cap_change_24h")),
            mcap_change_pct_24h=_num(tmd.get("market_cap_change_percentage_24h")),
            price_change_pct_30d=_num(tmd.get("price_change_percentage_30d_in_currency")),
            issuer=issuer_of.get(rid),
            last_updated=tmd.get("last_updated"),
        ))
    return out


def _num(v: Any) -> Optional[float]:
    """数值或 None。**`0` 是数值,`None` 是「没测」—— 两者不合并**(I1)。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


# ── 多轴聚合:标量之前先保住轴 ────────────────────────────────────────────

def by_axis(rows: Iterable[RwaRow], axis: str) -> dict[str, dict]:
    """沿一个轴聚合。`axis` ∈ {"asset_type", "issuer"}。

    先有轴,才有标量。一个 $2.33B 的总量,在「Ondo 占 41%」和「二十家均分」
    两种结构下是完全不同的对象,而标量把这个差别丢掉了 —— 集中度正是
    ⓪ 层(流动性周期判断)要读的东西。
    """
    if axis not in ("asset_type", "issuer"):
        raise ValueError(f"未知的轴:{axis}")
    buckets: dict[str, list[RwaRow]] = {}
    for r in rows:
        k = getattr(r, axis) or "unknown"
        buckets.setdefault(str(k), []).append(r)
    out = {}
    for k, rs in buckets.items():
        measured = [x for x in rs if x.measured]
        mcap = sum(x.market_cap for x in measured) or None
        vol = [x.total_volume for x in rs if x.total_volume is not None]
        flow = [x.mcap_change_24h for x in rs if x.mcap_change_24h is not None]
        out[k] = {
            "n": len(rs),
            "n_measured": len(measured),
            "n_unmeasured": len(rs) - len(measured),   # I1:数出来,不塞进 0
            "market_cap": mcap,
            "total_volume": sum(vol) if vol else None,
            "net_mcap_change_24h": sum(flow) if flow else None,
            "turnover": (sum(vol) / mcap) if (vol and mcap) else None,
            "hhi": herfindahl([x.market_cap for x in measured]),
        }
    return out


def herfindahl(values: Iterable[Optional[float]]) -> Optional[float]:
    """份额平方和。1.0 = 一家独占,→0 = 均分。

    ⓪ 层要的是**结构**不是总量:网检 2026-09-01,Ondo 一家 $955M / 全市场
    $2.33B ≈ 41%。一个由单一发行方主导的 $2.3B,和二十家均分的 $2.3B,
    对「这条流有多稳」是相反的读数,而总量对此完全沉默。
    """
    vs = [v for v in values if v is not None and v > 0]
    if not vs:
        return None
    tot = sum(vs)
    return sum((v / tot) ** 2 for v in vs) if tot else None


# ── 降维到标量:多重判断 ──────────────────────────────────────────────────

def total_equity_like(
    rows: Iterable[RwaRow],
    *,
    issuer_total: Optional[float] = None,
    category_total: Optional[float] = None,
    external_anchor: Optional[float] = None,
) -> PanelEstimate:
    """「股票 + ETF 全市场持仓量」—— 多重判断,不是一个求和。

    三个独立估计:
      E1 面板直接求和(`asset_type ∈ {stock, etf}`)—— 主估计
      E2 按发行方求和 —— 应与 E1 对得上;对不上说明面板或发行方映射有洞
      E3 分类法交叉(`/coins/categories`)—— 同一 vendor 的独立分类

    `external_anchor`(rwa.xyz 的公开数)**只做周期性对照,不参与求值** ——
    把一个外部读数掺进计算,就等于让我们的数字依赖一个我们不控制、
    也无法在 CI 里复现的东西。它只影响 `reason` 里的一句话。
    """
    rows = list(rows)
    eq = [r for r in rows if r.asset_type in EQUITY_LIKE]
    measured = [r for r in eq if r.measured]
    n_un = len(eq) - len(measured)

    if not measured:
        return PanelEstimate(
            None, NO_DATA,
            f"股票/ETF 行 {len(eq)} 条,其中 0 条有市值 —— "
            f"若 payload 非空,先确认是不是取错了层(市场数据在 "
            f"tokenized_market_data 里,顶层没有 market_cap)",
            n_measured=0, n_unmeasured=n_un)

    e1 = sum(r.market_cap for r in measured)
    est = {"panel_sum": e1}
    if issuer_total is not None:
        est["issuer_sum"] = issuer_total
    if category_total is not None:
        est["category_sum"] = category_total

    vals = [v for v in est.values() if v is not None and v > 0]
    if len(vals) < 2:
        return PanelEstimate(
            e1, SINGLE,
            f"只有面板求和一个估计({_usd(e1)});{n_un} 条未测未计入(I1:未测≠0)。"
            f"接上 /rwas/issuers 或 /coins/categories 才有交叉验证"
            + _anchor_note(e1, external_anchor),
            len(measured), n_un, est)

    spread = (max(vals) - min(vals)) / statistics.median(vals)
    if spread > DISPERSION_LIMIT:
        return PanelEstimate(
            statistics.median(vals), DISPERSED,
            f"{len(vals)} 个估计离散 {spread:.1%} > {DISPERSION_LIMIT:.0%}:"
            f"{ {k: _usd(v) for k, v in est.items()} } —— "
            f"取中位数,但**不要当作一个确定的数字发布**。"
            f"常见成因:同一标的被多家发行方代币化(按发行方求和会重复计暴露)、"
            f"口径含不含 ETF、背书模型不同" + _anchor_note(statistics.median(vals),
                                                            external_anchor),
            len(measured), n_un, est, spread)

    return PanelEstimate(
        statistics.median(vals), AGREE,
        f"{len(vals)} 个独立估计一致(离散 {spread:.1%});"
        f"{n_un} 条未测未计入" + _anchor_note(statistics.median(vals), external_anchor),
        len(measured), n_un, est, spread)


def _usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"


def _anchor_note(value: Optional[float], anchor: Optional[float]) -> str:
    """外部锚只入说明,不入计算。"""
    if value is None or anchor in (None, 0):
        return ""
    d = (value - anchor) / anchor
    verdict = "与外部锚一致" if abs(d) <= 0.20 else "**与外部锚差距显著**"
    return f"。{verdict}(锚 {_usd(anchor)},偏离 {d:+.0%})"


# ── 快照:落库的行形状 ────────────────────────────────────────────────────

def snapshot(rows: Iterable[RwaRow], *, d: Optional[dt.date] = None) -> dict:
    """一天的面板快照 —— 轴、标量、裁决一起落。

    标量单独落库会让下一个读它的人无从判断成色,而成色恰恰是这个量最缺的东西
    (公开来源在几周内给过四个不同的数)。
    """
    rows = list(rows)
    d = d or dt.date.today()
    est = total_equity_like(rows)
    return {
        "d": d.isoformat(),
        "n_rows": len(rows),
        "by_asset_type": by_axis(rows, "asset_type"),
        "by_issuer": by_axis(rows, "issuer"),
        "equity_like_total": est.value,
        "equity_like_verdict": est.verdict,
        "equity_like_reason": est.reason,
        # ⚠️ 这两个是**股票/ETF 口径**的计数,不是全面板的。
        # 初版叫 `n_measured`/`n_unmeasured`,与同一个 dict 里的 `n_rows`(全面板)
        # 并排,读的人会算 646−644=2 并以为有 2 条未测 —— 实际 644 是股票+ETF
        # 全部已测,那 2 条是商品(不进这个口径)。
        # **两个不同的分母并排报告而不标注,就是让人算出一个错的差。**
        "equity_like_n_measured": est.n_measured,
        "equity_like_n_unmeasured": est.n_unmeasured,
    }
