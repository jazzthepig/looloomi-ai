"""上市公司持币 —— **Entity/Decision 层的第一个真实样本** (S-290).

## 为什么是这个,不是 VC 融资

Jazz 2026-09-04:「vc funding flow、investment events 这个位置可以解决了吧?
我现在付费的 coingecko analyst 没有吗?」

实测(2026-09-04,对照组 `/protocols` 200/8179 证明网络无碍):

    defillama:/raises      HTTP 402   要钱
    defillama:/emissions   HTTP 402   要钱
    CG Analyst 的 14 项能力里 **没有任何 raises/funding 端点**

而 `/companies/public_treasury/{coin}` **在 CoinGecko 免费档上就有**:

    BTC   180 家公司   1,293,205 枚   **占总供应 6.16%**
    ETH    34 家公司   7,914,466 枚   **占总供应 6.49%**

### 它比 VC 融资更适合我们要的东西

    VC 融资       别人对某项目的决策 —— 自我披露的新闻稿,无披露义务
    上市公司持币   **有主体、有金额、有披露义务的一手决策**(8-K / 年报背书)

ARCHITECTURE 说最深的对象不是 Asset 是 **Entity/Decision**,而 `entities` 现在
**1 行**、`decisions` **0 行**(§IN-FLIGHT:「本体论主张无数据支撑」)。
这份数据正是那两张空表要装的东西 —— **主体是公司,决策是持仓变动。**

而且它直接给出 `percentage_of_total_supply` —— Jazz 2026-09-02 纠正过我的
那个量:「**多少比例和资产的发行占总流通盘才更重要**」。

## ⚠️ 本模块唯一真正的守卫:`entry_value = 0` 是「未披露」,不是「零成本」

实测 180 家里有相当一部分 `total_entry_value_usd = 0`
(MARA、BitMine、Twenty One、SharpLink…)。**那是未披露。**
把它当成本为零,浮盈倍数会变成无穷大,而那个数会一路走到「抛压强度」的排序里。

    Strategy       成本 $64.27B  现值 $68.55B  ⇒ 浮盈 **+6.7%**(可算)
    BitMine        成本 $0       现值 $14.88B  ⇒ **不可算**,不是 +∞

I1:**未测 ≠ 0。** 所以 `unrealized_multiple` 是 `Optional[float]`,
且 `n_undisclosed` 与 `n_measured` 永远一起给 —— 一个基于 40% 样本的
「平均浮盈」和一个基于 95% 样本的,在下游不能长得一样。

## 历史买不来,但可以今天开始

免费档只给**当前快照**。CG Analyst 的 `public_treasury_history`(from 2020)
给历史,是否可用需 Mac 侧探针确认(`scripts/probe_entity_sources.py`)。

**但无论那个端点通不通,今天开始存快照就等于开始造历史** ——
与 `beta_core_nav` 的 60 天同一个道理:**时间买不来,只能现在起算。**
每天 ~214 行,一年 ~78k 行,Supabase 免费档吃得下。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional, Sequence

#: 免费端点。**不需要 key** —— 实测 2026-09-04 直接 200。
FREE_URL = "https://api.coingecko.com/api/v3/companies/public_treasury/{coin}"

#: Analyst 档的历史端点(S-264 登记为 `public_treasury_history`,**零调用**)。
#: 可用性未验证 —— 见 `scripts/probe_entity_sources.py`。
HISTORY_NOTE = ("CG Analyst 的 public_treasury_history(from 2020)可提供历史,"
                "**但尚未验证**。在验证之前,历史只能从今天起自己积累")

#: 支持的资产。CoinGecko 只对这两个发布企业持仓。
COINS = ("bitcoin", "ethereum")

OK, THIN, NO_DATA = "ok", "thin", "no_data"

#: 已披露成本的公司低于这个比例,面板层的浮盈统计判 `thin`。
#: 取 0.5:低于一半样本算出来的「平均浮盈」代表的是那一半,不是整体。
MIN_DISCLOSED_SHARE = 0.5


@dataclass(frozen=True)
class Holding:
    """一家公司在某个资产上的持仓 —— **一个有主体、有时点、有金额的决策。**"""
    d: str
    coin: str
    name: str
    country: Optional[str]
    symbol: Optional[str]
    total_holdings: Optional[float]
    pct_of_supply: Optional[float]
    entry_value_usd: Optional[float]      # **None = 未披露,不是 0**
    current_value_usd: Optional[float]

    @property
    def unrealized_multiple(self) -> Optional[float]:
        """现值 / 成本。**未披露成本时返回 None,不返回 +∞ 也不返回 0。**

        这是本模块最重要的一行:实测 180 家里相当一部分 `entry_value` 是 0,
        而那是「未披露」。把它当零成本,浮盈会变成无穷大,
        然后那个数会一路走进「抛压强度」的排序里。
        """
        e, c = self.entry_value_usd, self.current_value_usd
        if e is None or c is None or e <= 0:
            return None
        return c / e

    @property
    def cost_disclosed(self) -> bool:
        return self.entry_value_usd is not None and self.entry_value_usd > 0


def _num(v) -> Optional[float]:
    """数值或 None。**`0` 在成本字段上意味着未披露**,由调用方转成 None ——
    这里只做类型收敛,不做语义判断。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def parse(coin: str, payload: dict, *, d: Optional[str] = None) -> list:
    """CoinGecko 响应 → `Holding` 列表。

    **`total_entry_value_usd == 0` 被转成 `None`** —— 见模块 docstring。
    一家真的零成本拿到币的公司不存在;0 只可能是「没填」。
    """
    d = d or dt.date.today().isoformat()
    out = []
    for c in (payload or {}).get("companies") or []:
        ev = _num(c.get("total_entry_value_usd"))
        out.append(Holding(
            d=d, coin=coin,
            name=str(c.get("name") or "").strip() or "(unnamed)",
            country=c.get("country"), symbol=c.get("symbol"),
            total_holdings=_num(c.get("total_holdings")),
            pct_of_supply=_num(c.get("percentage_of_total_supply")),
            entry_value_usd=(None if ev is None or ev <= 0 else ev),
            current_value_usd=_num(c.get("total_current_value_usd")),
        ))
    return out


def summarise(holdings: Sequence[Holding]) -> dict:
    """面板层。**已披露与未披露的家数永远一起给。**

    一个基于 40% 样本的「平均浮盈」和一个基于 95% 样本的,
    在下游不能长得一样(与 S-263 `agreement`、S-274 `spread` 同一条)。
    """
    hs = list(holdings)
    if not hs:
        return {"verdict": NO_DATA, "n": 0,
                "reason": "没有任何持仓行 —— **读不到 ≠ 没有公司持币**(S-180)"}

    disclosed = [h for h in hs if h.cost_disclosed]
    mults = sorted(m for m in (h.unrealized_multiple for h in disclosed)
                   if m is not None)
    share = len(disclosed) / len(hs)
    total_pct = sum(h.pct_of_supply or 0.0 for h in hs)

    verdict = OK if share >= MIN_DISCLOSED_SHARE else THIN
    return {
        "verdict": verdict,
        "n": len(hs),
        "n_cost_disclosed": len(disclosed),
        "n_cost_undisclosed": len(hs) - len(disclosed),
        "disclosed_share": round(share, 3),
        "pct_of_supply_total": round(total_pct, 4),
        "median_unrealized_multiple": (round(mults[len(mults) // 2], 4)
                                       if mults else None),
        "min_unrealized_multiple": round(mults[0], 4) if mults else None,
        "max_unrealized_multiple": round(mults[-1], 4) if mults else None,
        "reason": (
            f"{len(hs)} 家共持有总供应的 {total_pct:.2f}%;"
            f"**{len(disclosed)}/{len(hs)} 家披露了成本**({share:.0%})"
            + (f",这批的浮盈中位数 {mults[len(mults)//2]:.2f}x" if mults else "")
            + ("。**披露率低于一半 —— 这个浮盈只代表披露的那批,不代表整体**"
               if verdict == THIN else "")
            + "。未披露成本记为 None,**不是 0**:零成本会让浮盈变成无穷大 (I1)"),
    }


def concentration(holdings: Sequence[Holding]) -> dict:
    """集中度 —— **谁是那个 interest taker。**

    Herfindahl 用「占总供应的比例」而不是「占企业持仓的比例」:
    后者会把「企业整体只持有 0.1% 供应」和「持有 30%」说成一样集中。
    """
    hs = [h for h in holdings if (h.pct_of_supply or 0) > 0]
    if not hs:
        return {"verdict": NO_DATA, "reason": "没有可用的供应占比"}
    tot = sum(h.pct_of_supply for h in hs)
    shares = sorted((h.pct_of_supply / tot for h in hs), reverse=True)
    hhi = sum(s * s for s in shares)
    top = max(hs, key=lambda h: h.pct_of_supply)
    return {
        "verdict": OK,
        "n": len(hs),
        "herfindahl": round(hhi, 4),
        "top1_share_of_corporate": round(shares[0], 4),
        "top1_name": top.name,
        "top1_pct_of_supply": round(top.pct_of_supply, 4),
        "top5_share_of_corporate": round(sum(shares[:5]), 4),
        "reason": (
            f"{len(hs)} 家企业持有者,HHI {hhi:.3f};"
            f"**{top.name} 一家占企业持仓的 {shares[0]:.1%}、占总供应 "
            f"{top.pct_of_supply:.2f}%**。集中度按【占总供应】算 —— "
            f"按【占企业持仓】算会把「企业总共只有 0.1% 供应」和「有 30%」"
            f"说成同样集中"),
    }
