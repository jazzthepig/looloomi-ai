"""哪一层在服务这个响应 —— 一个字段,封闭取值,不含硬件名 (S-265).

## 三件事同时出错,而它们是同一件

**① 兜底写回上游那把钥匙。** `macro.py` 的模板兜底在生成后执行
`redis_set_key("macro:brief", payload)` —— 而 `health.py` 判活读的就是这把钥匙。
于是:

    Mac 死 → health 报 missing → 兜底跑一次 → 把自己写进 macro:brief
           → **health 变绿,而 Mac 仍然是死的**

缓解措施抹掉了它自己存在的证据。2026-09-01 12:xx 之所以看得见 `missing`,
只是因为兜底那份 15 分钟 TTL 刚好过期 —— 它会自己「好」,而没有人修过任何东西。

> **一个会把自己的报警清掉的兜底,比没有兜底更危险:**
> 没有兜底时故障是可见的,有它时故障是可见的**一小会儿**。

**② 四条返回路径,四种写法。** `source` 取值分别是 `"mac_mini"`(上游推的)、
`"auto"`(兜底)、`data.get("source", "mac_mini")`(最后一搏)、`"none"`(全失败),
另有一条路径用的是 `model: "template"`。**两条路径用两个不同的字段名报告同一件事**,
所以没有任何一个字段可以被下游问「这是第几层」。前端因此也不可能标出来。

**③ `"mac_mini"` 是公开响应里的硬件名。** 规则 #8 的守卫只扫 `dashboard/src/*.jsx`,
API 响应从来不在它的范围内(S-262 已在 `/internal/` 上发现同一个盲区,
这里是它在**面向用户的** `/api/v1/` 上的第二例)。

## 契约

一个字段 `tier`,封闭取值,**上游与兜底必须落在不同的存储键上**:

    UPSTREAM   由上游引擎生成并推送。权威。
    FALLBACK   本服务自己算的替代品。**可用,但不是权威**。
    STALE      上游的旧值,已超出新鲜窗口,在没有更好选择时继续服务。
    NONE       没有任何可服务的内容。

`tier` 与内容分开,和 `RegimeQuorum` 里 `regime`/`verdict` 分开是同一条理由
(S-263):一个 FALLBACK 的 brief 仍然是一个 brief,调用方有权同时知道内容是什么、
以及它来自第几层。把不权威的内容换成 None 会让「没有」和「不权威」再次同形。
"""
from __future__ import annotations

from typing import Optional

UPSTREAM = "upstream"
FALLBACK = "fallback"
STALE = "stale"
NONE = "none"

TIERS = frozenset({UPSTREAM, FALLBACK, STALE, NONE})

#: 兜底**不得**写进上游的键。分开存,判活才分得开「上游活着」和「兜底顶着」。
UPSTREAM_KEY_SUFFIX = ""          # 例:macro:brief
FALLBACK_KEY_SUFFIX = ":fallback"  # 例:macro:brief:fallback


def fallback_key(upstream_key: str) -> str:
    """兜底该写哪把钥匙。**永远不是上游那把。**"""
    return f"{upstream_key}{FALLBACK_KEY_SUFFIX}"


#: 公开响应里不得出现的词。规则 #8 延伸到 `/api/v1/`,不只是前端 bundle。
#: 值是替换词 —— 不是删掉,因为下游可能在按 `source` 分支。
PUBLIC_SOURCE_ALIASES = {
    "mac_mini": UPSTREAM,
    "macmini": UPSTREAM,
    "mac-mini": UPSTREAM,
    "local_engine": UPSTREAM,
    "railway": FALLBACK,
    "railway_snapshot": FALLBACK,
    "auto": FALLBACK,
    "template": FALLBACK,
}


def public_source(raw: Optional[str]) -> str:
    """把内部来源名映射成对外可说的层级词。

    未知取值**原样返回**,不是静默改成 `upstream` —— 一个没见过的来源名
    应该在响应里显眼地出现,而不是被伪装成权威层。守卫会抓到它。
    """
    if not raw:
        return NONE
    return PUBLIC_SOURCE_ALIASES.get(str(raw).strip().lower(), str(raw))


def describe(tier: str, *, age_s: Optional[int] = None,
             reason: str = "") -> dict:
    """标准的层级说明块,拼进任何响应。

    `tier_reason` 是给**人**看的:一个只有 `tier: "fallback"` 的响应,
    读的人还得去翻代码才知道上游为什么没顶上。
    """
    if tier not in TIERS:
        tier = NONE
    out = {"tier": tier, "tier_reason": reason or _DEFAULT_REASON[tier]}
    if age_s is not None:
        out["upstream_age_s"] = int(age_s)
    return out


_DEFAULT_REASON = {
    UPSTREAM: "上游引擎的推送,新鲜且权威",
    FALLBACK: "上游缺失或过期,由本服务自行计算的替代品 —— 不是权威值",
    STALE: "上游的旧值已超出新鲜窗口,但仍好于空白",
    NONE: "没有任何可服务的内容",
}
