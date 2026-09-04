"""谁在被看,谁没有 —— **「没有颜色」比「是红色」更危险** (S-279).

## Jazz 的问题(2026-09-02)

> 「怎么都说健康,都说没问题,但就是没有做完?总发现有东西停了?」

查下来**不是端点在撒谎**。它们此刻正在报:

    /internal/health-summary   degraded   (macro_brief STALE 582m)
    /internal/loop-health      stale
    /internal/data-freshness   domain_without_usable_source

**真正的机制是覆盖缺口:它们回答的是一个比「系统健康吗」小得多的问题,
而名字承诺了全景。** `health-summary` 只查 4 件事;S-278 的生产者判活
只看 10 张表 —— 而库里有 **67 张**。

我今天查出的三张死表(signal_outcomes 122 天 / market_state_vectors 27 天 /
risk_meter_history 的 2099 行)在今天之前**不在任何检查的视野里**。
那不是警报失灵,是**没装传感器的地方着火了**。

> **一个东西是红色的,至少它有颜色。没有颜色的东西,永远不会让任何裁决变坏。**

## 所以本模块产出的不是健康,是**覆盖率**

`not_covered` —— 有多少东西没有任何检查在看。**这是一个能收敛到零的整数**,
而守卫的数量不会收敛。Jazz 要的「还差多少」,答案在这里。

## 分层,因为「67 张表少看了 57 张」是个误导性的数字

`api_tiers` 没人看不要紧,它是配置表。**而 NAV 表没人看是要命的** ——
ARCHITECTURE 说产品就是**可验证的前向记录**,NAV 表就是那个记录本身。

实测:库里有 **9 张 NAV 表,只有 `beta_core_nav` 一张在被判活**。

    TRACK_RECORD  NAV / 成交 / 结果 —— **产品本身**,未覆盖 = P0
    SIGNAL        评分 / 状态 / 叙事 —— 未覆盖 = 会静默给出陈旧信号
    INPUT         价格 / 资金费率 / 成分 —— 未覆盖 = 上游断了不知道
    OPS           密钥 / 用量 / 审计 —— 未覆盖可接受,但要显式说
    REFERENCE     配置 / 别名 / 分层 —— **不需要判活**(不变的东西不会停)

## 清册从库里数出来,不是我列出来的

`census()` 吃的是 `information_schema` 的实时表名。**明天新建一张表,
它明天就会出现在 `not_covered` 里,不需要有人记得来加。**

这一条是本模块能收敛的全部原因:一份手写的清单本身就是抽样,
而抽样正是我们要修的那个毛病。

## 排除必须逐条带理由,不许用模式匹配

一个 `endswith('_log')` 的规则会把明天某张重要的 `_log` 表一起吞掉 ——
**静默吞掉,而且没人会发现**。所以 `EXCLUDED` 是显式字典,每条带原因;
不在里面又没被覆盖的,一律进 `not_covered`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TRACK_RECORD, SIGNAL, INPUT, OPS, REFERENCE = (
    "track_record", "signal", "input", "ops", "reference")

#: 层级的严重度 —— `not_covered` 要按层报,不按总数报。
TIER_SEVERITY = {TRACK_RECORD: 0, SIGNAL: 1, INPUT: 2, OPS: 3, REFERENCE: 4}

#: 未覆盖即 P0 的层级。**产品是可验证的前向记录,NAV 表就是那个记录。**
BLOCKING_TIERS = (TRACK_RECORD,)

COVERED, NOT_COVERED, EXCLUDED = "covered", "not_covered", "excluded"


@dataclass(frozen=True)
class WatchItem:
    name: str
    tier: str
    status: str
    watched_by: Optional[str] = None
    reason: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == NOT_COVERED and self.tier in BLOCKING_TIERS


#: 谁在看什么。**值是检查的名字** —— 一个说不出「被谁看」的「已覆盖」
#: 等于没覆盖(S-180 同源:说不清来源的健康不是健康)。
COVERAGE: dict[str, str] = {
    "ohlcv_daily": "data-freshness:by_source (S-251/S-272)",
    # S-278 生产者判活
    "cis_scores": "data-freshness:producers (S-278)",
    "signal_journal": "data-freshness:producers (S-278)",
    "signal_outcomes": "data-freshness:producers (S-278)",
    "risk_meter_history": "data-freshness:producers (S-278)",
    "beta_core_nav": "data-freshness:producers (S-278)",
    "asset_embeddings_history": "data-freshness:producers (S-278)",
    "asset_embeddings": "data-freshness:producers (S-278)",
    "market_state_vectors": "data-freshness:producers (S-278)",
    "trade_results": "data-freshness:producers (S-278)",
    "strategy_records": "data-freshness:producers (S-278)",
    "treasury_decisions": "data-freshness:producers (S-292)",
    "treasury_entities": "data-freshness:producers (S-292,随 decisions 一起判)",
}

#: **不需要判活的东西,逐条带理由。** 不许模式匹配 ——
#: 一个 `endswith('_log')` 会把明天某张重要的表静默吞掉。
EXCLUDED_BY_DESIGN: dict[str, str] = {
    "api_tiers": "配置表 —— 不变的东西不会停",
    "asset_aliases": "别名映射,配置",
    "strategy_params": "参数表,配置",
    "assets": "资产主数据,变更由人触发",
    "crypto_universe": "面板定义,变更由人触发",
    "api_keys": "凭证表 —— 不写不代表故障",
    "organizations": "租户表,按需增长",
    "leads": "CRM,与系统健康无关",
    "webhook_subscriptions": "订阅表,按需",
    "vault_deposit_intents": "用户发起,零行是正常状态",
    "audit_log": "审计追加日志 —— 无写入不代表故障",
    # ⚠️ 下面四条曾写成「同上」。**「同上」不是理由,是指针,而指针会断** ——
    # 有人重排字典、或只读到其中一条时,它什么也没说。守卫因此要求自足。
    "analytics_events": "前端埋点追加表 —— 量随流量走,无写入不代表故障",
    "api_usage": "调用量追加表 —— 量随流量走,无写入不代表故障",
    "api_key_usage": "按 key 的调用量追加表 —— 同样量随流量,不判活",
    "agent_call_log": "agent 调用追加日志 —— 量随流量,不判活",
    "experiment_runs": "研究按需写(与 strategy_records 同类,但后者已被看)",
    "cis_backtest_results": "回测产物,按需",
    "wallet_profiles": "钱包画像按需富化 —— 没有新钱包就没有新行,不是故障",
}


def tier_of(table: str) -> str:
    """表名 → 层级。**只用于分级,不用于排除** ——
    排除必须走 `EXCLUDED_BY_DESIGN` 的显式条目。

    分级用模式是安全的:猜错层级只会让它排错顺序,
    而猜错「要不要看」会让它消失。**两者的失败代价不同,所以规则不同。**
    """
    t = table.lower()
    if "nav" in t or t in ("trade_results", "execution_outcomes",
                           "execution_intents", "signal_track_record",
                           "prediction_outcomes", "cause_outcomes"):
        return TRACK_RECORD
    if t.startswith(("cis_", "signal_", "conviction_", "cause_", "narrative_",
                     "macro_", "regime_", "factor_tilt", "pod_aggregator",
                     "crowd_", "depth_", "trending_", "strategy_response",
                     "market_state", "asset_embeddings", "risk_meter",
                     "decisions", "entities", "fusion_paper_lifecycle")):
        return SIGNAL
    if t.startswith(("ohlcv", "funding", "holder_", "universe_")):
        return INPUT
    if t in EXCLUDED_BY_DESIGN:
        return REFERENCE if "配置" in EXCLUDED_BY_DESIGN[t] else OPS
    return OPS


def census(tables: list) -> dict:
    """库里的真实表名 → 覆盖清册。

    `tables` 应来自 `information_schema`(实时),**不是一份手写清单** ——
    手写清单本身就是抽样,而抽样正是本模块要修的毛病。
    """
    items = []
    for t in sorted(set(tables)):
        tier = tier_of(t)
        if t in COVERAGE:
            items.append(WatchItem(t, tier, COVERED, COVERAGE[t]))
        elif t in EXCLUDED_BY_DESIGN:
            items.append(WatchItem(t, tier, EXCLUDED,
                                   reason=EXCLUDED_BY_DESIGN[t]))
        else:
            items.append(WatchItem(
                t, tier, NOT_COVERED,
                reason="没有任何检查在看它 —— **没有颜色的东西永远不会让裁决变坏**"))

    gaps = [i for i in items if i.status == NOT_COVERED]
    blocking = [i for i in gaps if i.blocking]
    by_tier: dict = {}
    for i in gaps:
        by_tier.setdefault(i.tier, []).append(i.name)

    return {
        # **这个整数就是「还差多少」。** 它能收敛到零;守卫的数量不会。
        "n_not_covered": len(gaps),
        "n_blocking": len(blocking),
        "blocking": [i.name for i in blocking],
        "n_total": len(items),
        "n_covered": sum(1 for i in items if i.status == COVERED),
        "n_excluded": sum(1 for i in items if i.status == EXCLUDED),
        "not_covered_by_tier": {
            k: sorted(v) for k, v in
            sorted(by_tier.items(), key=lambda kv: TIER_SEVERITY.get(kv[0], 9))},
        "verdict": ("blocked" if blocking else
                    "incomplete" if gaps else "complete"),
        "reason": (
            f"{len(gaps)}/{len(items)} 个对象没有任何检查在看,"
            f"其中 **{len(blocking)} 个属于 {BLOCKING_TIERS[0]}** "
            f"({[i.name for i in blocking][:6]}…)。"
            f"**产品是可验证的前向记录,而 NAV 表就是那个记录本身** —— "
            f"它们没被判活,意味着记录可能有洞而我们不知道"
            if blocking else
            f"{len(gaps)}/{len(items)} 个未覆盖,但没有 track_record 层的缺口"
            if gaps else "全部对象要么被覆盖,要么被显式排除并带理由"),
    }


def qualify_verdict(base_verdict: str, cen: dict) -> dict:
    """裁决 + **它的适用范围**,而不是把裁决压红。

    ⚠️ 第一版的做法是:覆盖不全 ⇒ 总裁决压成 `blocked`。**那是错的,
    而且错得讽刺** —— 覆盖不全会持续数周,于是那盏灯会永久是红的,
    而**一盏常亮的灯和一盏坏掉的灯,在行为上是同一个东西**。
    这正是 Jazz 问的那个病(「都说健康 / 一直在报警但没人读」)的另一面,
    我差点用它去修它自己。

    所以正确的做法是**不动裁决,给裁决加一个范围声明**:

        verdict        仍然只说「我查过的那些,现在怎么样」—— 它变红时是真事件
        covers         我查过多少 / 一共多少 —— **这个数在动,是进度**
        unqualified    覆盖完整之前,永远 False

    `unqualified=False` 的意思是:**这个「健康」只对我看得见的那部分成立。**
    它不制造警报,但它让任何人无法把局部读成整体 —— 而那正是
    `health-summary` 只查 4 件事却叫这个名字所造成的误读。
    """
    complete = not cen.get("n_not_covered")
    return {
        "verdict": base_verdict,
        "unqualified": bool(complete),
        "covers": f"{cen.get('n_covered', 0)}/{cen.get('n_total', 0)}",
        "n_not_covered": cen.get("n_not_covered", 0),
        "n_blocking": cen.get("n_blocking", 0),
        "scope_note": (
            "覆盖完整 —— 这个裁决可以代表整体"
            if complete else
            f"⚠️ **这个裁决只对 {cen.get('n_covered', 0)}/{cen.get('n_total', 0)} "
            f"个对象成立**,另有 {cen['n_not_covered']} 个无人监视"
            + (f"(其中 {cen['n_blocking']} 个是 track_record 层 —— "
               f"产品就是可验证的前向记录,而承载它的表没被判活)"
               if cen.get("n_blocking") else "")
            + "。**不是警报,是范围声明** —— 一盏常亮的红灯等于一盏坏灯"),
    }


#: 实时表清册的 SQL。**每次现查** —— 明天新建的表明天就会出现在
#: `not_covered` 里,不需要有人记得来加。这是本模块能收敛的全部原因。
CENSUS_SQL = """
select table_name from information_schema.tables
where table_schema = 'public' and table_type = 'BASE TABLE'
"""
