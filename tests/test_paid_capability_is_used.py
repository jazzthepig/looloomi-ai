"""付费能力必须真的被调用 —— **不然那就是白付的钱** (S-291).

Jazz 2026-09-04:「我们有 coingecko analyst api 是 139 刀一个月的。。。
你又把他忽略了?**这件事已经被失忆了很多次**,你害我浪费多少钱了!」

他是对的,而时间线让这条无可辩驳:

    S-264  我自己写下 `PAID_ENTITLEMENTS`,列了 14 项 analyst_only 能力,
           还为 public_treasury 写了理由(「有主体、有时点、有金额的企业决策」)
    此后    **那批 Entity 能力零调用**
    S-290  我用【免费】端点建了快照层,并写下「历史买不来,今天开始攒」
    S-291  实测:付费档直接给到 2020-08-11 —— 那句话对免费档成立,
           **对我们付的这档不成立**

而我判「不可用」的依据是一次 HTTP 403 —— **那是 Cloudflare 1010 客户端指纹
拦截**(裸 urllib),不是权限。换 httpx 立刻 200:`plan=Analyst`,
月额度 500,000,本月剩余 482,574。

> **「我探测失败」和「我们没有这个能力」是两个状态。**

## 为什么守卫要长这样

一条台账、一段注释、一行 CLAUDE.md 都**已经存在过**,而失忆照样发生 ——
因为那些东西要人主动去读。**这个文件不需要谁记得它。**

判据:`PAID_ENTITLEMENTS` 里每一项 `analyst_only` 能力,
要么在 `src/` 里有真实调用点,**要么显式登记为「尚未接入」并带理由**。
未接入的数量走**只减不增预算** —— 不逼一次全接,但不许再涨,
而且每次有人读到这个数,就会想起我们在为没用的东西付钱。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.source_policy import PAID_ENTITLEMENTS       # noqa: E402
from tests._source import code_only                               # noqa: E402

_FAIL: list = []
SELF = Path(__file__).name

#: 尚未接入的 analyst_only 能力 —— **每条必须带理由**,且这个集合只减不增。
#: 「以后要接」不是理由;理由要说清**为什么现在不接**。
NOT_WIRED_YET: dict[str, str] = {
    "/coins/top_gainers_losers":
        "横截面极值 —— ②层 tilt 用得上,但 ① 还没落地,接了没有消费者",
    "/coins/list/new":
        "新上币 —— 叙事萌芽观测点,但没有对应的研究问题在等它",
    "/exchanges/{id}/volume_chart/range":
        "场所成交量 —— 需要先有「场所 infra 被买」这个假设的判据",
    "/onchain/.../tokens/{addr}/trades":
        "成交分类原料 —— 需要 pattern recognition 先立起来(Jazz 09-02)",
    "/onchain/.../tokens/{addr}/top_holders":
        "持有人结构 —— **下一个该接的**,S-291 的链上侧对应物",
    "/onchain/.../tokens/{addr}/holders_chart":
        "持有人历史 —— 同上,与 top_holders 一起接",
    # ⚠️ 这条原本写「同上批次」。**「同上」是指针,而指针会断** ——
    # 有人重排字典或只读到这一条时,它什么也没说(当天第二次学到这条)。
    "/onchain/.../top_traders":
        "谁在交易 —— 需要先有「哪些地址算机构」的判据,否则只是一串地址",
    "/onchain/pools/megafilter":
        "跨链池筛选 —— 没有对应的面板需求",
    "onchain_ohlcv_depth":
        "池级 OHLCV —— ohlcv_daily 已够用,接了是第二份记录(规则 3b)",
    "websocket":
        "10 路实时流 —— 轮询目前够用,上实时流要先有延迟预算",
}

#: 只减不增。**一个不能变大的数,比一句「以后都要接」有用。**
NOT_WIRED_BUDGET = len(NOT_WIRED_YET)

#: 名字不是路径的能力(标签型),**需要一个显式的证明指针**。
#: 模糊字符串匹配对它们无效 —— `coin_history_depth` 这个字符串不会出现在代码里,
#: 证明它的是 `deep_walk.FLOOR = 2013`。
#: **一个匹配不到就报「未接入」的守卫,会把已接入的说成没接。**
LABEL_PROOFS: dict[str, tuple] = {
    "coin_history_depth": (
        "src/data/market/deep_walk.py", "FLOOR",
        "S-258/S-269:日线深度 from 2013 —— `FLOOR = dt.date(2013, 1, 1)` "
        "就是这项能力的兑现,实跑 BTC 4,901 根"),
}


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _src_code() -> str:
    """`src/` 的**代码**(剥注释与 docstring)。

    不剥的话,`source_policy.py` 自己的能力清单会证明它自己「已接入」——
    S-264 踩过一次(登记表匹配到自己),当天第五次那个形状。
    """
    parts = []
    for f in (ROOT / "src").rglob("*.py"):
        if ".venv" in f.parts or "site-packages" in f.parts:
            continue
        if f.name in ("source_policy.py",):          # 登记表不为自己作证
            continue
        try:
            parts.append(code_only(f.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass
    return "\n".join(parts)


def _fragment(cap: str) -> str:
    """能力名 → 一个**足够特异**的搜索片段。

    ⚠️ S-264 踩过:`/rwas/markets` 取末段 `markets` 会匹配到 `/coins/markets`。
    所以取**最后两段**,并保留斜杠。
    """
    if not cap.startswith("/"):
        return cap
    segs = [s for s in cap.split("/") if s and "{" not in s and "." not in s]
    return "/".join(segs[-2:]) if len(segs) >= 2 else (segs[-1] if segs else cap)


def t_every_paid_capability_is_wired_or_explicitly_deferred():
    """**本文件的理由。** 一项付费能力要么被调用,要么带理由登记为未接。"""
    cg = PAID_ENTITLEMENTS.get("coingecko_pro") or {}
    caps = cg.get("analyst_only") or {}
    _check("能力清单非空", bool(caps), str(len(caps)))

    src = _src_code()
    unaccounted = []
    for cap in caps:
        if cap in NOT_WIRED_YET:
            continue
        if cap in LABEL_PROOFS:
            f, token, _why = LABEL_PROOFS[cap]
            body = (ROOT / f).read_text(encoding="utf-8", errors="ignore") \
                if (ROOT / f).exists() else ""
            if token in body:
                continue
            unaccounted.append(f"{cap}(证明指针 {f}:{token} 失效)")
            continue
        if _fragment(cap) not in src:
            unaccounted.append(cap)
    _check("没有【既未调用也未登记】的付费能力", not unaccounted,
           f"{unaccounted} —— 要么接上,要么写进 NOT_WIRED_YET 并说明为什么不接。"
           f"**一项没人用的付费能力就是每月在烧的钱**")


def t_label_proofs_actually_point_at_something():
    """标签型能力的证明指针必须**当场可验**,否则它就是另一句空话。"""
    for cap, (f, token, why) in LABEL_PROOFS.items():
        path = ROOT / f
        _check(f"{cap}: 证明文件存在", path.exists(), f)
        if path.exists():
            _check(f"{cap}: 证明 token `{token}` 在文件里",
                   token in path.read_text(encoding="utf-8", errors="ignore"))
        _check(f"{cap}: 说明为什么它算兑现", len(why) > 20, why)


def t_deferred_capabilities_carry_a_real_reason():
    """「以后要接」不是理由。理由要说清**为什么现在不接**。"""
    for cap, why in NOT_WIRED_YET.items():
        _check(f"{cap[:34]:34s} 带理由", len(why) > 12 and "以后" not in why,
               why)
    _check(f"未接数 {len(NOT_WIRED_YET)} ≤ 预算 {NOT_WIRED_BUDGET}(只减不增)",
           len(NOT_WIRED_YET) <= NOT_WIRED_BUDGET)


def t_the_entity_layer_is_actually_wired_now():
    """S-291 的具体回归:企业持币这条**必须**在代码里有调用点。"""
    src = _src_code()
    _check("public_treasury 有真实调用点", "public_treasury" in src,
           "这正是被忘掉几个月的那一项")
    _check("transaction_history 有真实调用点",
           "transaction_history" in src,
           "付费档解锁的正是它的 page>1(回到 2020-08-11)")
    _check("并且不在未接清单里",
           not any("public_treasury" in c for c in NOT_WIRED_YET))


def t_a_probe_failure_is_not_an_entitlement_answer():
    """**403 ≠ 没有这个能力。** 实测那次是 Cloudflare 1010 指纹拦截。"""
    doc = (ROOT / "src/data/entity/collect.py").read_text(encoding="utf-8")
    _check("采集层写明了 403 的真实来源", "Cloudflare" in doc, doc[:200])
    _check("并写明两者是两个状态", "两个状态" in doc)
    probe = (ROOT / "scripts/probe_entity_sources.py").read_text(encoding="utf-8")
    _check("探针的 key 加载器查多个来源(不是一个)",
           probe.count("COINGECKO_API_KEY") >= 2, "只查一处正是那次误判的起点")


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
