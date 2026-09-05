"""后台循环的心跳 —— **一个只进 stdout 的失败,等于没有发生** (S-282).

## 实测:39 个循环里 28 个的失败只进 stdout

⚠️ 我第一次报的是「67 个里 64 个」—— **那 67 里有一半是 `_start_*` 包装函数**
(只有一行 `create_task`),不是循环。**今天第二次夸大动机数字**
(上一次是 regime 争议率 27%→22%)。夸大一个动机数字,会让后面所有
基于它的判断都带着同样的倍数。

`_outcome_tracker_loop` 是最干净的样本,整个机制就在四行里:

    except Exception as _e:
        print(f"[OUTCOME] ⚠️  daily run failed: {_e}")   # ← 只进 stdout
    await _asyncio.sleep(_OUTCOME_INTERVAL_S)             # ← 然后继续睡

于是:循环**活着**、启动时打了 `✅ scheduled`、每天准时跑、**每天失败一次**,
而 `signal_outcomes` 从 2026-05-03 起 **123 天**没有新行,
没有任何监控知道 —— 因为失败从来没有离开过 stdout。

> **一个只进 stdout 的失败,对任何监控来说等于没有发生。**

这与 S-279 的覆盖缺口相乘,就是「静默死亡」的完整配方:
**写入者悄悄失败 × 表无人判活。** 补上任一边都不够。

## 三个状态,不是一个 bool

    never_ran     从来没跑过 —— 可能根本没被调度
    ok            上次成功
    failing       上次失败(**带上连续失败次数与错误**)

`market_state_vectors` 正是第一种:每一行的 `computed_at` 都是
`2026-08-06 09:15:28.873599`,精确到微秒相同 ⇒ **一次性回填,从未被调度**。
而 `signal_outcomes` 是第三种:跑着,天天失败。
**两者在 `max()` 上完全同形**,而修法完全不同(前者要加调度,后者要查错)。

## 为什么写 Redis 不写 Supabase

Supabase 是免费档(Jazz 2026-08-30:「能不增加用量就不增加」),而心跳是
**每个循环每轮一次写**。Redis 已经是缓存桥,TTL 让死掉的循环自己消失 ——
**而「键不见了」正是我们要的信号**,不需要额外的过期判断。

## 失败不改变循环的行为

`beat()` 只记录。它**不重试、不退避、不终止** —— 那些是各循环自己的事,
而一个记录器如果还顺手改行为,下一个人就不敢用它。
"""
from __future__ import annotations

import time
from typing import Optional

#: Redis 键。单键存整张表 —— 39 个循环各一个键会让读取变成 39 次往返。
BEAT_KEY = "loops:beat"

#: 心跳 TTL。取 3 天:比最长的循环间隔(24h)宽裕,
#: 又足够短到**一个死了的循环会自己从表里消失**。
#: 键消失本身就是信号,不需要再判一次过期。
BEAT_TTL_S = 3 * 24 * 3600

NEVER_RAN, OK, FAILING = "never_ran", "ok", "failing"

#: ⚠️ **第三个状态 (S-294)。** 心跳上线第一天就误报:`_deep_panel_loop` 被记成
#: failing,而它的错误原文是 `Write REFUSED so the gap stays visible` ——
#: **那是地板守卫在正确工作**(S-245),不是故障。
#:
#: `deep_panel_collector` 自己早就返回 `refused: True`;**是心跳这一层把它
#: 折叠进了 ok=False**。又是本周那个形状:两个不同的状态塌进一个表示,
#: 而这次塌的是我自己刚建的那层。
#:
#: 拒绝**不计入连续失败**(循环没坏),但**自己计数** ——
#: 连续拒绝 30 天意味着数据一直没恢复,那是它自己的信号,不是健康。
REFUSED = "refused"


# ── S-299 (2026-09-05):从「函数没崩」改成「活干完了」 ────────────────────────
#
# 架构自上而下核对的头条:**14 个有心跳的循环里,11 个写死 `ok=True`。**
# 只要采集函数没抛异常,心跳就报健康 —— 它从不看返回值。
#
# `_outcome_tracker_loop` 是最干净的样本,整个机制在三行里:
#
#     summary = await run_outcome_tracker(dry_run=False)
#     print(f"[OUTCOME] ... written={summary.get('rows_written')}")
#     await _beat("_outcome_tracker_loop", ok=True)     # ← 无条件
#
# **`rows_written` 被打印出来,然后被丢掉。它就在那一行的上一行。**
#
# 实测的四条假绿灯(2026-09-05):
#
#     _outcome_tracker_loop   ok   signal_outcomes      停 125 天
#     _factor_tilt_loop       ok   factor_tilt_nav      0 行
#     _pod_aggregator_loop    ok   pod_aggregator_nav   0 行
#     _two_layer_paper_loop   ok   two_layer_paper_nav  停 14 天
#
# 9 本纸面账里 4 本的表是空的或陈旧的,而面板写着「12/14 健康」。
#
# > **「循环成功」和「工作完成」是两个状态,而心跳只测了第一个。**
#
# ## 为什么复用 REFUSED 而不是加第五个状态
#
# `skipped` / `no_data` / `warming_up` 的语义是「跑通了,按规矩没干活」——
# 与地板拒绝**同类**。REFUSED 已经带 `n_consecutive_refusals`,
# 而「连续 N 轮没进展」正是我们要的那个信号。加新状态等于重造它。
#
# ## 未知状态判 failing,不判 ok
#
# 一个没被枚举的 status,**我们不知道它有没有干活**。
# 判 ok 就是让未知伪装成健康 —— 这个 session 排了二十几条,全是这个形状。
# 词表由实测得来(AST 抽 11 个循环实际调用的函数里的 status 字面量),
# 不是猜的,所以「未知」是真的未知。

#: 真的产生了工作。`already_marked` 也算 —— 今天的行**存在**是目的本身。
PROGRESS_STATUS = frozenset({
    "ok", "marked", "already_marked", "inception", "accruing", "success",
    "closed", "filled", "live", "generated_uncached", "on_track",
})

#: 跑通了、按规矩没干活。**不是故障,但也不是进展** —— 单独计数。
NO_WORK_STATUS = frozenset({
    "skipped", "no_data", "warming_up", "not_yet_marked", "nothing_to_flush",
    "insufficient_episodes", "insufficient_data", "pending", "building",
    "empty", "stale", "accruing_only",
})

#: 真的坏了。
BROKEN_STATUS = frozenset({
    "error", "mark_failed", "inception_failed", "no_supabase", "undeclared",
    "failed", "unavailable", "rejected", "unconfigured", "unknown",
})


def classify(res: object) -> tuple[bool, bool, Optional[str]]:
    """采集器的返回值 → `(ok, refused, error)`。**纯函数,可离线测。**

    判据是 `status`,不是「有没有抛异常」。三条出口:

        progress  → (True,  False, None)   干了活
        no_work   → (False, True,  why)    跑通了但按规矩没干活 —— 计数,不报错
        broken    → (False, False, why)    真故障

    **未知 status 走 broken**,理由见上面那段注释:未知不是健康。
    返回值不是 dict(旧式调用点)时给 `(True, False, None)` ——
    那是「这个调用点还没迁移」,由 `HARDCODED_OK_BUDGET` 只减不增地收口,
    而不是在这里假装判过。
    """
    if not isinstance(res, dict):
        return True, False, None
    st = str(res.get("status") or "").strip().lower()
    if not st:
        return True, False, None
    if st in PROGRESS_STATUS:
        return True, False, None
    if st in NO_WORK_STATUS:
        return False, True, f"status={st} —— 跑通但没有产生工作"
    if st in BROKEN_STATUS:
        return False, False, f"status={st} :: {str(res.get('error') or res.get('reason') or '')[:120]}"
    return False, False, (
        f"未知 status '{st}' —— **未知不是健康**。它没有出现在实测词表里,"
        f"所以我们不知道这一轮有没有干活;判健康等于让未知伪装成健康")


def _now() -> int:
    return int(time.time())


def build_sha() -> str:
    """当前进程跑的是哪个构建。**与 `/internal/build-state` 同源。**

    ⚠️ S-295:没有这个字段时,「修了还在失败」和「修完之后还没再跑过」
    **完全同形**。这些循环大多 24 小时一轮 —— 一个修复上线后,心跳条目
    仍带着旧构建记下的那次失败,而 TTL 是 3 天,足够让人反复误读三次。

    实际发生过:`_pod_aggregator_loop` 的 R62_Z 修复推上去之后,
    读到的仍是同一条 ImportError —— 分不清是没修好,还是没轮到它跑。
    """
    import os
    return (os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or os.environ.get("GIT_COMMIT_SHA")
            or os.environ.get("SOURCE_COMMIT") or "")[:8]


async def beat(name: str, *, ok: bool, error: Optional[str] = None,
               detail: Optional[dict] = None, refused: bool = False) -> None:
    """记一次循环的结果。**只记录,不改变行为。**

    三个状态,不是两个:

        ok       跑完并写了
        refused  跑完并**正确地拒绝写**(地板/覆盖率不达标)—— 不是故障
        failing  真的坏了

    `ok=False` 时累加 `n_consecutive_failures` —— 一次失败和连续 123 次失败
    是两个状态。而 `refused` **另外计数**:连续拒绝 30 天说明数据一直没恢复,
    那是它自己的信号,把它记成失败会让真故障淹没在里面。
    """
    try:
        from src.api.store import redis_get_key, redis_set_key
        cur = await redis_get_key(BEAT_KEY) or {}
        if not isinstance(cur, dict):
            cur = {}
        prev = cur.get(name) or {}
        n_fail = int(prev.get("n_consecutive_failures") or 0)
        n_ref = int(prev.get("n_consecutive_refusals") or 0)
        # 拒绝是「跑通了但按规矩没写」—— 它清零失败计数,自己另计。
        entry = {
            "last_run_at": _now(),
            "ok": bool(ok) or bool(refused),
            "refused": bool(refused),
            "n_consecutive_failures": 0 if (ok or refused) else n_fail + 1,
            "n_consecutive_refusals": n_ref + 1 if refused else 0,
            "last_ok_at": _now() if (ok and not refused) else prev.get("last_ok_at"),
            "last_error": None if (ok or refused) else (error or "")[:200],
            "last_refusal": (error or "")[:200] if refused else None,
            # **哪个构建记的这一条** —— 见 `build_sha()` 的 docstring。
            "build": build_sha(),
        }
        if detail:
            entry["detail"] = detail
        cur[name] = entry
        await redis_set_key(BEAT_KEY, cur, ttl=BEAT_TTL_S)
    except Exception:                                          # noqa: BLE001
        # **心跳失败绝不能影响业务循环。** 一个为了记录健康而弄死循环的
        # 记录器,比没有记录器更糟。
        pass


async def read_beats() -> dict:
    try:
        from src.api.store import redis_get_key
        d = await redis_get_key(BEAT_KEY)
        return d if isinstance(d, dict) else {}
    except Exception:                                          # noqa: BLE001
        return {}


def _stale(entry: dict) -> bool:
    """这条心跳是不是旧构建记的。**两者都有 sha 才判得了** ——
    否则返回 False 而不是 True(未知不该伪装成一个确定的答案)。"""
    cur, was = build_sha(), (entry or {}).get("build")
    return bool(cur and was and cur != was)


def assess(name: str, beats: dict, *, expect_every_s: Optional[int] = None,
           now: Optional[int] = None) -> dict:
    """一个循环的裁决。**「没有心跳」不等于「健康」。**"""
    now = now or _now()
    e = (beats or {}).get(name)
    if not e:
        return {"loop": name, "verdict": NEVER_RAN,
                "reason": ("这一轮没有任何心跳 —— **可能根本没被调度**"
                           "(market_state_vectors 就是这种:一次性回填、"
                           "从未上日程),也可能死得比 TTL 还久。"
                           "**两者都不是健康**")}
    if e.get("refused"):
        n = int(e.get("n_consecutive_refusals") or 1)
        return {"loop": name, "verdict": REFUSED,
                "build": e.get("build"),
                "stale_build": _stale(e),
                "n_consecutive_refusals": n,
                "last_refusal": e.get("last_refusal"),
                "last_ok_at": e.get("last_ok_at"),
                "reason": (f"**正确地拒绝写入**,连续 {n} 轮:"
                           f"{(e.get('last_refusal') or '')[:110]}。"
                           f"循环没坏 —— 但**连续 {n} 轮拒绝说明上游一直没恢复**,"
                           f"那是它自己的信号,不是健康")}
    if not e.get("ok"):
        n = int(e.get("n_consecutive_failures") or 1)
        return {"loop": name, "verdict": FAILING,
                "build": e.get("build"),
                # **True = 这条是旧构建记的,该循环还没在当前构建下跑过。**
                # 不是「修了还在失败」,是「还没轮到它」。
                "stale_build": _stale(e),
                "n_consecutive_failures": n,
                "last_error": e.get("last_error"),
                "last_ok_at": e.get("last_ok_at"),
                "reason": (f"连续失败 **{n}** 次,最后一次:"
                           f"{(e.get('last_error') or '')[:120]}。"
                           f"**一次失败和连续 {n} 次是两个状态**"
                           + ("。⚠️ **这条是旧构建 "
                              f"{e.get('build')} 记的,当前构建 {build_sha()} "
                              f"下它还没跑过** —— 不是「修了还在失败」,"
                              f"是「还没轮到它」" if _stale(e) else ""))}
    age = now - int(e.get("last_run_at") or 0)
    late = expect_every_s and age > expect_every_s * 2
    return {"loop": name, "verdict": OK, "age_s": age,
            "build": e.get("build"),
            "late": bool(late),
            "reason": (f"上次成功 {age // 60} 分钟前"
                       + ("(**已超过预期间隔的两倍**)" if late else ""))}


def overall(beats: dict, expected: Optional[dict] = None) -> dict:
    """面板层。**报失败中的和从没跑过的,不报「多少个健康」。**"""
    expected = expected or {}
    names = sorted(set(beats) | set(expected))
    rows = [assess(n, beats, expect_every_s=expected.get(n)) for n in names]
    failing = [r for r in rows if r["verdict"] == FAILING]
    refused = [r for r in rows if r["verdict"] == REFUSED]
    never = [r for r in rows if r["verdict"] == NEVER_RAN]
    return {
        # **拒绝不进总裁决的坏值** —— 一个按规矩拒绝的循环不是故障,
        # 而把它算进去会让告警常亮,常亮等于坏灯。
        "verdict": ("failing" if failing else "never_ran" if never else OK),
        "n": len(rows), "n_failing": len(failing), "n_never_ran": len(never),
        "n_refusing": len(refused),
        # **旧构建记下的失败** —— 它们还没在当前构建下跑过,
        # 把它们和「修了还在失败」混在一起会让人重复误读三天(TTL)。
        "n_failing_on_stale_build": sum(1 for r in failing if r.get("stale_build")),
        "failing": [{"loop": r["loop"],
                     "n": r.get("n_consecutive_failures"),
                     "err": (r.get("last_error") or "")[:80]} for r in failing],
        # 单列 —— 它是信息,不是警报。**连续轮数才是它的严重度。**
        "refusing": [{"loop": r["loop"],
                      "n": r.get("n_consecutive_refusals"),
                      "why": (r.get("last_refusal") or "")[:80]} for r in refused],
        "never_ran": [r["loop"] for r in never],
        "rows": rows,
        "reason": (
            f"{len(failing)} 个循环正在连续失败、{len(never)} 个这一轮没有心跳"
            + (f"、{len(refused)} 个在**正确地拒绝写入**(不是故障)" if refused else "")
            + "。"
            f"**一个只进 stdout 的失败等于没有发生** —— 实测 39 个循环里 "
            f"28 个是那个形状,而 signal_outcomes 因此死了 123 天无人知"
            if failing or never else
            f"{len(rows)} 个循环都在按时成功"),
    }
