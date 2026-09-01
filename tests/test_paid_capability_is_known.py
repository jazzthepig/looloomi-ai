"""我们买了什么、用了多少、哪些买了没用 (S-264)。

## 为什么这条守卫存在

2026-09-01,我告诉 Jazz「我们测不了流,库里没有任何持久化的流量序列」。
他说「coingecko pro 应该是有的」,然后:「**这点已经说过好多次了**,
我买了 139 刀每月的 pro api」。

他是对的。而更难看的是:**这件事本来就写在 `source_policy.py` 里** ——
S-205 的正文明写着 CoinGecko Pro 给 "market caps, dominance, categories,
trending, breadth across ~17,000 assets. **We pay monthly for exactly this and
were using the free-shaped endpoints**"。我没读自己 lane 里那个模块就断言了缺失。

跟 2026-08-19 那次是同一个动作(CLAUDE.md 为那次专门加了一整段:
「**Before saying a result does not exist, grep `_reports/`**」)。
一年第二次,所以这次不写警告 —— 写成一个会红的检查。

## 实测数字,和它说明的事

    plan                Analyst($139/月)
    monthly_call_credit 500,000
    calls_used          2,074       ← **0.4%**

我整个 session 都在为 Supabase 免费版的 500MB 做取舍(S-261 把 CG Pro 回填
改成本地优先,就为了不动那 50.7% 的占用),而旁边这个付费额度**几乎全新**。

> 一个被珍惜的免费额度和一个被闲置的付费额度同时存在,
> 说明约束被找错了地方。

## 这条守卫真正在测什么

「不要声称缺少我们付过钱的数据」是一句话,测不了。能测的是它的两个可机械化的影子:

  ① 每个付费源都必须登记 entitlement + 一条 VERIFY 命令 —— 否则「我们买了什么」
     又回到某个人的记忆里。
  ② **买了但一次没调过的端点必须被列出来。** 这是「我们不知道自己有什么」
     唯一可机械发现的形式:注册表里有,代码里搜不到。
     列出不等于失败 —— 刚补进注册表的端点本来就还没接。但它必须**被看见**,
     而且数量只能减(ratchet),不能悄悄增长。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.source_policy import (          # noqa: E402
    BULK_ENDPOINTS, PAID_ENTITLEMENTS, PAID_SOURCES, utilisation,
)

_FAIL: list[str] = []

#: 每条已登记端点的**摄取状态**。二值不够 —— 实测逼出第三个:
#:
#:     unwired    仓库里没有调用点
#:     ephemeral  **调了,但缓存几分钟就扔,不落库**  ← 这个才是真实的缺口形状
#:     persisted  落进表,有历史可查
#:
#: 我原本只有 unwired/wired 两值,于是 `/coins/categories` 因为「有调用点」
#: 被判成没问题 —— 而它只取 ~16 家 VC 组合、10 分钟 TTL、从不持久化。
#: 「我们没有叙事层的历史」是真的,原因不是拿不到,是**拿了就扔**。
#: 一个 ephemeral 的端点和一个 persisted 的端点,在「有没有调用点」这个尺度上同形。
INGEST_STATE: dict[str, str] = {
    "/coins/markets": "persisted",
    "/global": "ephemeral",
    "/coins/categories": "ephemeral",
    "/rwas/markets": "unwired",
    "/rwas/issuers/list": "unwired",
    "/global/market_cap_chart": "ephemeral",
    "/exchanges/{id}/volume_chart": "unwired",
}

#: 尚未落库的端点 + 用途。**只能减。**
#: 一个没有用途说明的闲置端点,下一个人无法判断该接它还是该把它删掉。
UNWIRED_BUDGET: dict[str, str] = {
    "/rwas/markets":
        "代币化 RWA 的市值序列 = 该资产的 AUM。这是 Jazz 的 TradFi→tokenized "
        "边际流论点唯一的直接观测量,其余全是价格倒影。待接。",
    "/rwas/issuers/list":
        "按发行方拆流。「同样的传统资产在 tokenized world 买入」——"
        "发行方是那个『在哪买』的维度。待接。",
    "/global/market_cap_chart":
        "历史全局市值+成交量,做分母。Analyst 档已含。**已有调用点但只在 "
        "scripts/reconstruct_cis_history.py 里,不在日常路径 ⇒ ephemeral。**",
    "/global":
        "总市值 + BTC 主导率,一次调用。**ephemeral**:实时读了给页面,不落库,"
        "所以主导率没有历史 —— 而「TradFi 边际流进加密」这类论点恰恰要看主导率的"
        "轨迹,不是它此刻的值。",
    "/global":
        "总市值 + BTC 主导率,一次调用。ephemeral:读了给页面,不落库,"
        "所以主导率没有历史 —— 而「TradFi 边际流进加密」这类论点要看的是主导率的"
        "轨迹,不是它此刻的值。",
    "/exchanges/{id}/volume_chart":
        "场所成交量历史。2026-09-01 的篮子测算显示场所/流动性层在 beta 走平的"
        "五周里 +9.0pp —— 那是价格证据,这个端点是它的成交量对照。待接。",
    "/coins/categories":
        "分类市值+成交量 = 叙事层读数。S-205(2026-08-23)点名过它。"
        "⚠️ 我在本文件初版写「至今仍未接」—— **错的,没核**:"
        "`data_layer.py:1662` 一直在调。真实状态是 ephemeral:只取 ~16 家 VC 组合、"
        "10 分钟 TTL、从不落库。所以叙事层没有历史,不是因为拿不到。",
}


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _repo_mentions(needle: str) -> bool:
    """端点在 src/ 或 scripts/ 里有没有调用点。

    路径里的 `{id}` 在代码里是 f-string 的 `{token_id}` 之类,整串匹配会全部落空;
    所以把 `{...}` 换成通配,但**保留至少两段路径**。

    ⚠️ 初版只取最后一段:`/rwas/markets` → `markets`,而 `/coins/markets` 满仓库
    都是 → 判成「已接」。守卫报「7 条端点 0 条未接」,而真实答案是 5 条未接。
    **而我那条判别性测试通过了** —— 它的反例是 `/zzz_not_a_real_endpoint_xyz`,
    一个明显不存在的串。**只测欠匹配的对照,抓不到过匹配。**
    对照必须与真值**共享一个片段**才有判别力,见 `t_the_grep_actually_discriminates`。

    ⚠️ 第二个坑:**注册表自己在 `src/` 里**,所以 `source_policy.py` 会匹配到它
    自己声明的每一条端点 → 全部判「已接」。「声明了这个能力」和「用了这个能力」
    是两个状态,而扫描器把它们合并了。排除注册表文件本身。
    """
    parts = [x for x in needle.strip("/").split("/") if x]
    pat = "/".join("[^/\"']*" if x.startswith("{") else re.escape(x)
                   for x in parts[-2:] if x)
    frag = pat
    try:
        r = subprocess.run(
            ["grep", "-rqE", frag, "src/", "scripts/",
             "--include=*.py", "--include=*.sh",
             # 注册表不是调用点 —— 不排除它,它会证明自己已接
             "--exclude=source_policy.py"],
            cwd=ROOT, capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:                                          # noqa: BLE001
        return False


def t_every_paid_source_declares_what_we_bought():
    """「我们买了什么」不能只活在某个人的记忆里。"""
    for s in sorted(PAID_SOURCES):
        e = PAID_ENTITLEMENTS.get(s)
        if s == "eodhd" and not e:
            # 诚实地记下缺口,而不是假装它不存在:EODHD 的档位没人量过。
            print(f"  · {s}: 未登记 entitlement —— 已知缺口,不是通过")
            continue
        _check(f"{s} 登记了 entitlement", bool(e))
        if not e:
            continue
        _check(f"{s} 写明了 plan 与额度",
               bool(e.get("plan")) and bool(e.get("monthly_call_credit")), str(e))
        _check(f"{s} 带一条 VERIFY 命令(否则又回到记忆里)",
               "verify" in e and "/key" in str(e["verify"]), str(e.get("verify")))


def t_utilisation_is_measured_and_absence_is_not_zero():
    """用了多少必须是**量出来的**;没量过要与 0% 分开。"""
    u = utilisation("coingecko_pro")
    _check("coingecko_pro 的使用率已量出", u is not None)
    if u is not None:
        _check(f"使用率 = {u:.1%}(2026-09-01 实测 2,074/500,000)", u < 0.05,
               f"{u:.1%} —— 若已显著上升,请重新测量并更新 PAID_ENTITLEMENTS")
    _check("未登记的源返回 None,不是 0.0(没量 ≠ 没用)",
           utilisation("hyperliquid") is None, str(utilisation("hyperliquid")))


def t_unwired_paid_capability_is_visible_and_shrinking():
    """**买了没用的端点必须被列出来,且数量只能减。**

    这是「我们不知道自己有什么」唯一可机械发现的形式:
    注册表里有,代码里搜不到。
    """
    registered = set(BULK_ENDPOINTS.get("coingecko_pro", {}))
    unwired = {ep for ep in registered if not _repo_mentions(ep)}

    print(f"  · CG Pro 已登记端点 {len(registered)} 条,其中仓库里搜不到调用点的 "
          f"{len(unwired)} 条")
    for ep in sorted(unwired):
        print(f"      · {ep}  {UNWIRED_BUDGET.get(ep, '⚠️ 无用途说明')}")

    undocumented = sorted(unwired - set(UNWIRED_BUDGET))
    _check("每条未接端点都写明了用途(没说明的无法判断该接还是该删)",
           not undocumented, "缺说明:" + ", ".join(undocumented))

    _check(f"未接端点数不超过预算({len(UNWIRED_BUDGET)})",
           len(unwired) <= len(UNWIRED_BUDGET),
           f"{len(unwired)} 条未接 > 预算 {len(UNWIRED_BUDGET)} —— "
           f"要么接上,要么把新增的写进 UNWIRED_BUDGET 并说明理由")

    # 判据是**落库**,不是「有调用点」。ephemeral 的端点留在预算里是正确的 ——
    # 它们没有解决「没有历史」这个问题。
    stale = sorted(k for k in UNWIRED_BUDGET
                   if INGEST_STATE.get(k) == "persisted")
    _check(f"UNWIRED_BUDGET 里没有已落库的条目({len(stale)} 条待删)",
           not stale, "已落库,从预算里删掉:" + ", ".join(stale))


def t_every_endpoint_declares_its_ingest_state():
    """三值,不是二值。**「调了就扔」不能穿着「已接」的衣服过关。**"""
    registered = set(BULK_ENDPOINTS.get("coingecko_pro", {}))
    missing = sorted(registered - set(INGEST_STATE))
    _check("每条已登记端点都声明了摄取状态", not missing, "未声明:" + ", ".join(missing))

    bad = sorted(k for k, v in INGEST_STATE.items()
                 if v not in ("unwired", "ephemeral", "persisted"))
    _check("状态值只能是 unwired/ephemeral/persisted", not bad, str(bad))

    # 未落库的都要在预算里说明用途 —— 包括 ephemeral,因为「拿了就扔」
    # 跟「没拿」在下游是同一个结果:没有历史。
    not_persisted = {k for k, v in INGEST_STATE.items()
                     if v != "persisted" and k in registered}
    undoc = sorted(not_persisted - set(UNWIRED_BUDGET))
    _check(f"未落库的 {len(not_persisted)} 条都写明了用途", not undoc,
           "缺说明:" + ", ".join(undoc))

    n_eph = sum(1 for v in INGEST_STATE.values() if v == "ephemeral")
    print(f"  · 摄取状态:persisted {sum(1 for v in INGEST_STATE.values() if v=='persisted')} · "
          f"ephemeral {n_eph}(调了就扔)· "
          f"unwired {sum(1 for v in INGEST_STATE.values() if v=='unwired')}")


def t_declared_unwired_is_actually_unwired():
    """声明与事实必须对得上 —— 否则这张表就是另一份可以过期的记忆。"""
    for ep, st in sorted(INGEST_STATE.items()):
        found = _repo_mentions(ep)
        if st == "unwired":
            _check(f"{ep} 声明 unwired,仓库里确实搜不到调用点", not found,
                   "有调用点却声明 unwired —— 声明过期了")
        else:
            _check(f"{ep} 声明 {st},仓库里确实有调用点", found,
                   "搜不到调用点却声明已接")


def t_the_grep_actually_discriminates():
    """判别性:上面那个 grep 必须能分辨接了和没接。

    没有这条,`_repo_mentions` 永远返回 False 也能让整个文件看起来在工作 ——
    而那正是本季反复出现的失败形状(守卫匹配的是拼写,不是构造)。
    """
    _check("一个确实存在的端点被判为『已接』",
           _repo_mentions("/coins/markets"), "grep 找不到 coins/markets —— 匹配方式坏了")
    _check("一个杜撰的端点被判为『未接』",
           not _repo_mentions("/zzz_not_a_real_endpoint_xyz"))
    # ↓ 这条才是有判别力的对照:它与真端点**共享最后一段**。
    #   初版的匹配(只取最后一段)会把它判成「已接」,因为 `markets` 到处都是。
    _check("与真端点共享末段的杜撰路径,仍判『未接』(抓过匹配,不只是欠匹配)",
           not _repo_mentions("/zzz_fake_family/markets"),
           "末段相同就被判已接 —— 匹配片段不够判别性")


if __name__ == "__main__":
    print("── 付费能力登记 (S-264) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 付费能力登记守卫全绿")
