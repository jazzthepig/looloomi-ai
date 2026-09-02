"""加密圈自己的宏观状态 —— 与美元宏观分层,不合并 (S-271).

## Jazz 的论点(2026-09-02)

> 「现在的 macro regime 主要是判断全球、以美元资金主导的宏观,所以我们需要
> 分层细化出加密圈的宏观,这是新的边际增长。**crypto 是 ai native 的 money,
> 是 tokenomics 的远祖。**」

这句话解释了今天那次 GOLDILOCKS/TIGHTENING 的混乱。`data_layer.py:2410` 的
分类器吃的是 **CPI / GDP / 利率** —— 纯美元宏观。而同期 BTC +24.6%。

**那两件事从来不矛盾。它们是两个货币体系上的两个 regime,
而我们只有一个标签在描述它们两个。**

## 两层,以及为什么分歧本身才是信号

    USD 宏观    CPI / GDP / 利率 —— 已有(`daily_macro_regime`)
    加密宏观    稳定币供给 / 资金费率 / TVL / OI / 主导率 —— 本模块

> 「宏观紧,但边际资金从 TradFi 转进来」在单层里是一个矛盾,
> **在两层里是一个可观测的组合**。⓪ 层要读的正是这个组合,不是任一层的标签。

## 加密原生变量,以及它们在传统世界的对应物

    stablecoin_supply    加密的 M2 —— 增发/赎回就是这个体系的货币基数变动
    funding_rate         杠杆成本 —— 加密的政策利率,而且是市场定的不是央行定的
    defi_tvl             信用条件 —— 抵押品总量
    perp_open_interest   系统杠杆 —— 顺周期的那部分
    btc_dominance        体系内的风险曲线 —— 钱在曲线的哪一端

## ⚠️ 本模块**不发标签**

发一个 `CRYPTO_TIGHTENING` 之类的枚举,需要:一个因、一个基础率、一次 OOS 存活。
三样一样都没有。而 `REFUTATION_LEDGER` 里 R76–R94 那 15 次连败,
**正是「先发明分类器、后找证据」这个形状**。

所以这一层产出的是**状态向量 + 完备度**,标签留空并写明为什么留空。
`HIGH_DIM_ONTOLOGY` §4 的话:每一层降维都要申报保什么 ——
从五个连续量塌成一个六值枚举,是这条链上最贵的一次降维,
在有 OOS 之前不该做。

R20 的教训同向:**相变不可 profitable 地择时,regime 信息只进 sizing。**

## 实测(2026-09-02):五个维度里有两个

    funding_rate      ✓  `funding_history` 表在
    btc_dominance     ✓  S-268 刚建
    stablecoin_supply ✗  CG `/coins/categories` 有,**未落库**
    defi_tvl          ✗  DeFiLlama 有,**未落库**
    perp_open_interest ✗ Hyperliquid `metaAndAssetCtxs` 一次调用就有,**未落库**

所以 `completeness = 0.4`,而这个数**必须跟着状态一起走** ——
一个 2/5 维的「加密宏观状态」和一个 5/5 维的,在下游不能长得一样(I1)。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

# ── 维度声明:名字 → (它代理什么, 数据源, 是否已落库) ──────────────────────
#
# **声明在前,取数在后。** 一个只按「现在能拿到什么」定义的状态向量,
# 会把「我们没接」伪装成「这个体系没有这个量」—— 而后者是关于世界的断言。
CRYPTO_MACRO_DIMS: dict[str, dict] = {
    "stablecoin_supply": {
        "proxies": "加密的 M2 —— 增发/赎回是这个体系的货币基数变动",
        "source": "coingecko_pro:/coins/categories(stablecoins 分类市值)",
        "persisted": False,
        "note": "S-264 记过:该端点是 ephemeral,10 分钟 TTL 从不落库",
    },
    "funding_rate": {
        "proxies": "杠杆成本 —— 加密的政策利率,**由市场定不由央行定**",
        "source": "hyperliquid:funding_history",
        "persisted": True,
    },
    "defi_tvl": {
        "proxies": "信用条件 —— 抵押品总量",
        "source": "defillama",
        "persisted": False,
        "note": "免费源,按 S-205 只能单点查询不可 fan-out",
    },
    "perp_open_interest": {
        "proxies": "系统杠杆 —— 顺周期的那部分",
        "source": "hyperliquid:/info metaAndAssetCtxs(一次调用覆盖全部永续)",
        "persisted": False,
    },
    "btc_dominance": {
        "proxies": "体系内的风险曲线 —— 钱在曲线的哪一端",
        "source": "coingecko_pro:/global(厂商自算,S-268)",
        "persisted": True,
    },
}

#: 完备度低于此,状态不可用于任何定仓决策。
#: 取 0.6:五维里至少三维 —— 两维("有杠杆成本和主导率")说不了货币状况,
#: 因为**货币基数那一维不在里面**,而那是这套框架的核心量。
MIN_COMPLETENESS = 0.6

OK, PARTIAL, INSUFFICIENT, NO_DATA = "ok", "partial", "insufficient", "no_data"


@dataclass(frozen=True)
class CryptoMacroState:
    """加密宏观的一天。**没有 label —— 见模块 docstring。**"""
    d: str
    values: dict = field(default_factory=dict)       # dim → float|None
    verdict: str = NO_DATA
    reason: str = ""

    @property
    def measured_dims(self) -> list:
        return sorted(k for k, v in self.values.items() if v is not None)

    @property
    def missing_dims(self) -> list:
        return sorted(k for k in CRYPTO_MACRO_DIMS if self.values.get(k) is None)

    @property
    def completeness(self) -> float:
        return len(self.measured_dims) / len(CRYPTO_MACRO_DIMS)

    @property
    def usable(self) -> bool:
        return self.verdict == OK

    #: 标签永远是 None,直到有 OOS 证据。**这是一个字段而不是一句注释**,
    #: 因为下游会去读它;读到 None 才会去看 `label_reason`。
    label: Optional[str] = None

    @property
    def label_reason(self) -> str:
        return ("本层不发 regime 标签:发一个枚举需要因 + 基础率 + OOS 存活,"
                "三样都没有。R76–R94 那 15 次连败正是「先发明分类器、后找证据」"
                "这个形状(见 REFUTATION_LEDGER)。"
                "从五个连续量塌成一个六值枚举,是这条链上最贵的一次降维。")


def build(d: str, raw: dict) -> CryptoMacroState:
    """`raw` 是 dim → 数值(缺的给 None 或不给)。**缺失被数出来,不补 0。**"""
    vals = {k: _num(raw.get(k)) for k in CRYPTO_MACRO_DIMS}
    st = CryptoMacroState(d, vals)
    n_ok, n_all = len(st.measured_dims), len(CRYPTO_MACRO_DIMS)

    if n_ok == 0:
        return CryptoMacroState(
            d, vals, NO_DATA,
            f"{n_all} 个维度一个都没测到 —— 先确认 funding_history 与 /global 还在写")

    if st.completeness < MIN_COMPLETENESS:
        return CryptoMacroState(
            d, vals, INSUFFICIENT,
            f"完备度 {st.completeness:.0%}({n_ok}/{n_all}),缺 {st.missing_dims}。"
            f"**不足以描述货币状况** —— 缺的里面若有 stablecoin_supply,"
            f"那是这套框架的货币基数,没有它「加密宏观」这个词不成立")

    if n_ok < n_all:
        return CryptoMacroState(
            d, vals, PARTIAL,
            f"完备度 {st.completeness:.0%}({n_ok}/{n_all}),缺 {st.missing_dims} —— "
            f"可用但**必须带着完备度一起往下游传**:一个 3/5 维的状态和一个 5/5 维的,"
            f"在下游不能长得一样(I1)")

    return CryptoMacroState(d, vals, OK, f"五个维度全测到({n_ok}/{n_all})")


def _num(v) -> Optional[float]:
    """数值或 None。**`0` 是数值,`None` 是没测** —— 资金费率恰好可以是 0,
    而把没测的资金费率记成 0,等于宣称杠杆成本为零。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else f


def gap_report() -> dict:
    """哪些维度还没落库,以及各自的来源。**这张表是路线图,不是清单。**"""
    missing = {k: v for k, v in CRYPTO_MACRO_DIMS.items() if not v["persisted"]}
    return {
        "n_dims": len(CRYPTO_MACRO_DIMS),
        "n_persisted": len(CRYPTO_MACRO_DIMS) - len(missing),
        "max_completeness_today": round(
            (len(CRYPTO_MACRO_DIMS) - len(missing)) / len(CRYPTO_MACRO_DIMS), 2),
        "missing": {k: v["source"] for k, v in missing.items()},
        "reason": f"{len(missing)}/{len(CRYPTO_MACRO_DIMS)} 个维度未落库,"
                  f"所以今天可达的最高完备度是 "
                  f"{(len(CRYPTO_MACRO_DIMS) - len(missing)) / len(CRYPTO_MACRO_DIMS):.0%} "
                  f"< {MIN_COMPLETENESS:.0%} —— **这一层现在还不可用于定仓,"
                  f"而它不可用的原因是摄取缺口,不是方法问题**",
    }


def divergence(usd_regime: Optional[str], crypto_state: CryptoMacroState) -> dict:
    """两层的组合。**这是 ⓪ 层真正要读的对象。**

    现在只能报「两层各自处于什么状态」,不能报一个组合标签 ——
    因为加密那一层还没有标签(且短期内不该有)。

    但即使只有状态,组合本身已经是可记录的:
    「USD=TIGHTENING + 加密宏观 5 维完备」与
    「USD=TIGHTENING + 加密宏观只有 2 维」是两个完全不同的处境,
    而后者意味着**我们对那一层一无所知**,不是那一层平静。
    """
    return {
        "usd_regime": usd_regime,
        "crypto_completeness": round(crypto_state.completeness, 2),
        "crypto_verdict": crypto_state.verdict,
        "crypto_label": None,
        "crypto_label_reason": crypto_state.label_reason,
        "readable": crypto_state.usable and bool(usd_regime),
        "reason": (
            "两层都可读 —— 组合可以被记录并在攒够样本后检验"
            if (crypto_state.usable and usd_regime) else
            f"组合尚不可读:USD 层 {'有' if usd_regime else '缺'}、"
            f"加密层 {crypto_state.verdict}。**「加密层没读数」不等于「加密层平静」**"),
    }
