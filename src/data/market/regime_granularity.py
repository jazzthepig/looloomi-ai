"""regime 的日内颗粒度:标签之外,还有它有多确定 (S-270).

## 实测(2026-09-02,近 60 天):22% 有分歧,7% 是实质争议

`cis_scores` **每天写入约 22.6 个小时槽**,而 `daily_macro_regime` 那个 view
把它压成每天一个众数。压掉了多少:

    59 天有小时数据,平均 22.6 个小时槽
    **13 天(22%)日内出现超过一种 regime**
    **4 天(6.8%)众数占比 < 80%** —— 实质性争议
    一致度中位数 1.000,**最低 0.625**

⚠️ 我第一次报的是「27% 有争议」—— **那是把原始行的多标签当成了小时众数的
多标签**(原始行一小时内有多条,大小写变体也在内)。准确的两个数是
22% 有任何分歧、7% 跨过 80% 门槛。**夸大一个动机数字,会让后面所有基于它的
判断都带着同样的倍数。**

这也说明 `CONTESTED_BELOW = 0.80` 放对了位置:13 天有分歧、只有 4 天跨过它 ——
**它在分离噪声与信号,不是见谁都响。** 而最差那天的 62.5% 是真的:
那一天有三分之一以上的小时不同意众数,下游看到的仍是一个确定的字符串。

那不是噪声要被平滑掉,那正是这个标签一直缺的东西 —— `cis_scores` 有
`pillar_f/m/o/s/a`、`confidence`、`score_zscore`,**没有任何一列是 regime 的
置信度或边界距离**。一个 51/49 的判断和一个 95/5 的判断,在下游是同一个字符串。

## 三个量,不是一个

    label       当日众数 —— 原来就有的那个
    agreement   众数占当日观测的比例。**24/24 与 13/24 是两个状态**
    churn       日内标签变化次数。A→B→A 是震荡,A→A→B 是转折

`HIGH_DIM_ONTOLOGY` §5b-bis 说 ⓪ 层的判据是「在崩塌里是否把回撤削掉」,
而拐点恰恰发生在 agreement 塌下去、churn 起来的时候 —— **那两个量在日频众数
里完全不可见**。等到标签真的翻,已经晚了一整段。

## 「一致」必须区分是几个人的一致

一天只有 1 个观测时 agreement = 1.0,但那不是共识,那是**只有一个投票人**。
与 S-263 的 `n_sources` 塌陷是同一个陷阱:分母消失时,比例会假装自己很健康。
所以 `agreement` 永远与 `n_obs` 一起给,且 `n_obs` 低于门槛时裁决为 `thin`。
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

#: 一天至少要这么多个小时槽,`agreement` 才有意义。
#: 实测正常日是 24 —— 取 6 是为了在部分停机的日子里仍能给读数而不是空白,
#: 但低于它就判 thin:**一个 2/2 的「100% 一致」不是共识。**
MIN_OBS_PER_DAY = 6

#: 众数占比低于此,判为「有争议」。取 0.80 的依据是实测:近 60 天里 13 天有
#: 多标签,而只有 4 天跨过 0.80 —— 其余是 23/24 这种轻微分歧。
#: **门槛在分离噪声与信号,不是见谁都响。** 最差那天是 0.625。
CONTESTED_BELOW = 0.80

UNANIMOUS, CONTESTED, THIN, NO_DATA = "unanimous", "contested", "thin", "no_data"


@dataclass(frozen=True)
class RegimeDay:
    """一天的 regime,**带上它有多确定**。"""
    d: str
    label: Optional[str]
    agreement: Optional[float]
    n_obs: int
    n_labels: int
    churn: int
    verdict: str
    reason: str
    #: 日内按小时的标签序列(去重相邻),让「震荡」与「转折」可分。
    path: tuple = ()

    @property
    def usable(self) -> bool:
        """`contested` **仍然可用** —— 它是信息,不是故障。`thin` 不可用。"""
        return self.verdict in (UNANIMOUS, CONTESTED)

    @property
    def is_turning(self) -> bool:
        """路径单调(A…A→B…B)而非往返 —— 转折的形状,不是震荡的形状。

        **只是形状判断,不是预测。** 一个单调路径可能第二天就翻回去;
        这个字段回答的是「今天这一天长什么样」,不是「接下来会怎样」。
        """
        return len(self.path) == 2 and self.churn == 1


def _canon(raw: Optional[str]) -> Optional[str]:
    """大小写与连字符归一。**不重新实现规范化** —— 只做形状统一。

    真正的规范集合校验在 `cis_provider.canonical_regime_strict`(S-249:
    我曾在这里写出第 4 个实现)。这里只把 `Risk-Off` 与 `RISK_OFF` 合并,
    因为不合并会让「日内两种标签」这个计数被大小写虚增。
    """
    if not raw:
        return None
    return str(raw).strip().upper().replace("-", "_").replace(" ", "_") or None


def day_from_hours(d: str, labels: Iterable[Optional[str]]) -> RegimeDay:
    """一天的小时标签序列 → 标签 + 一致度 + 震荡度。

    `labels` 按时间升序。`None` 被计为**缺测**(不参与分母),不是一个标签 ——
    把缺测当成一个类别会让 `n_labels` 虚增,把停机说成分歧。
    """
    seq = [_canon(x) for x in labels]
    obs = [x for x in seq if x]
    if not obs:
        return RegimeDay(d, None, None, 0, 0, 0, NO_DATA,
                         "当天没有任何非空 regime 观测(缺测不计为一个类别)")

    counts = Counter(obs)
    label, top = counts.most_common(1)[0]
    agreement = top / len(obs)

    # 相邻去重的路径:A A B B A → (A, B, A)。churn = 变化次数。
    path: list = []
    for x in obs:
        if not path or path[-1] != x:
            path.append(x)
    churn = len(path) - 1

    if len(obs) < MIN_OBS_PER_DAY:
        return RegimeDay(
            d, label, agreement, len(obs), len(counts), churn, THIN,
            f"当天只有 {len(obs)} 个观测(需 ≥{MIN_OBS_PER_DAY})—— "
            f"{agreement:.0%} 的「一致」是几个人的一致?**分母消失时比例会假装健康**"
            f"(S-263 同一个陷阱)",
            tuple(path))

    if agreement < CONTESTED_BELOW:
        return RegimeDay(
            d, label, agreement, len(obs), len(counts), churn, CONTESTED,
            f"众数 {label} 只占 {agreement:.0%}(< {CONTESTED_BELOW:.0%}),"
            f"日内 {len(counts)} 种标签、变化 {churn} 次。"
            f"**这一天的 regime 是有争议的,而日频众数会把它说成确定的**",
            tuple(path))

    return RegimeDay(
        d, label, agreement, len(obs), len(counts), churn, UNANIMOUS,
        f"{label} 占 {agreement:.0%}({top}/{len(obs)}),日内变化 {churn} 次",
        tuple(path))


def series(rows: Iterable[dict]) -> list:
    """`cis_scores` 的小时行 → 每日 `RegimeDay`。

    `rows` 需含 `d`(日期)、`hr`(小时)、`macro_regime`。
    """
    by_day: dict = {}
    for r in rows or []:
        d = str((r or {}).get("d") or "")[:10]
        if not d:
            continue
        by_day.setdefault(d, []).append(
            (str(r.get("hr") or ""), r.get("macro_regime")))
    out = []
    for d in sorted(by_day):
        hrs = [g for _h, g in sorted(by_day[d], key=lambda x: x[0])]
        out.append(day_from_hours(d, hrs))
    return out


def summarise(days: Iterable[RegimeDay]) -> dict:
    """面板层读数。**报有争议的比例,那是日频众数丢掉的全部信息。**"""
    days = list(days)
    usable = [x for x in days if x.usable]
    if not usable:
        return {"n_days": len(days), "n_usable": 0, "contested_share": None,
                "reason": "没有一天有足够观测 —— 先确认 cis_scores 的小时写入还在"}
    contested = [x for x in usable if x.verdict == CONTESTED]
    turning = [x for x in usable if x.is_turning]
    agr = sorted(x.agreement for x in usable)
    return {
        "n_days": len(days),
        "n_usable": len(usable),
        "n_contested": len(contested),
        "contested_share": round(len(contested) / len(usable), 3),
        "median_agreement": round(agr[len(agr) // 2], 3),
        "min_agreement": round(agr[0], 3),
        "n_turning_shape": len(turning),
        "total_churn": sum(x.churn for x in usable),
        "reason": f"{len(contested)}/{len(usable)} 天有争议(众数占比 < "
                  f"{CONTESTED_BELOW:.0%});一致度中位数 {agr[len(agr) // 2]:.0%}、"
                  f"最低 {agr[0]:.0%};日内变化合计 {sum(x.churn for x in usable)} 次。"
                  f"**这些在日频众数里全部不可见**",
    }


#: 取小时级 regime 的 SQL。集中在这里 —— 散到调用点上,下一个调用点会写成
#: 按天聚合,而那正是这个模块要修的东西。
HOURLY_SQL = """
select recorded_at::date::text as d,
       date_trunc('hour', recorded_at)::text as hr,
       macro_regime
from cis_scores
where recorded_at >= %(since)s and macro_regime is not null
order by 1, 2
"""
