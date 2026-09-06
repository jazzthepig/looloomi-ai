"""后台循环心跳的守卫 (S-282)。

这个文件里只有一条真正重要的断言:

    **一个只进 stdout 的失败,对任何监控来说等于没有发生。**

实测 2026-09-03:`src/api/main.py` 有 **39 个真实循环,28 个的失败只 print**。
(我第一次报「67 个里 64 个」—— 把 `_start_*` 包装函数也数进去了。
**今天第二次夸大动机数字**,上一次是 regime 争议率 27%→22%。)
`_outcome_tracker_loop` 是最干净的样本 —— 循环活着、启动时打了 ✅、每天准时跑、
**每天失败一次**,而 `signal_outcomes` 从 2026-05-03 起 123 天没有新行,
没有任何监控知道。

第二条:**「没跑过」和「跑了但失败」是两个状态,修法完全不同。**
`market_state_vectors` 每行 `computed_at` 精确到微秒相同 ⇒ 一次性回填、
**从未被调度**(要加日程);`signal_outcomes` 是跑着天天失败(要查错)。
而两者在 `max()` 上完全同形。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.loop_beat import (                                # noqa: E402
    BEAT_TTL_S, FAILING, NEVER_RAN, OK, REFUSED, assess, build_sha, overall,
)

_FAIL: list = []

#: 还没接心跳的循环数。**只减不增。**
#: 一个不能变大的数,比一句「以后都要接」有用(S-264/S-280 同一模式)。
#:
#: ⚠️ 2026-09-06:实测 25,而这里写着 28 —— **预算比现实松 3 个,
#: 那 3 个可以悄悄退回去而不被任何东西发现。棘轮没上紧就不是棘轮。**
#: 降到实测值本身应当是一个例行动作,而它显然没有被例行地做。
NO_BEAT_BUDGET = 25


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_never_ran_is_not_healthy():
    """**本文件的理由之二。** 没有心跳 ≠ 健康。"""
    r = assess("_some_loop", {})
    _check("没有心跳 → never_ran(不是 ok)", r["verdict"] == NEVER_RAN, r["verdict"])
    _check("理由点出「可能根本没被调度」", "没被调度" in r["reason"], r["reason"][:60])
    _check("理由明说两者都不是健康", "都不是健康" in r["reason"])


def t_one_failure_and_a_hundred_are_two_states():
    beats = {"_x": {"last_run_at": 1, "ok": False,
                    "n_consecutive_failures": 123, "last_error": "boom"}}
    r = assess("_x", beats)
    _check("判 failing", r["verdict"] == FAILING, r["verdict"])
    _check("连续次数被带出来", r["n_consecutive_failures"] == 123,
           str(r.get("n_consecutive_failures")))
    _check("理由里有那个次数", "123" in r["reason"], r["reason"][:60])
    _check("错误原文被保留", "boom" in r["reason"], r["reason"])

    one = assess("_y", {"_y": {"last_run_at": 1, "ok": False,
                               "n_consecutive_failures": 1, "last_error": "e"}})
    _check("一次失败与 123 次可分", one["reason"] != r["reason"])


def t_success_clears_the_streak_and_is_not_late_by_default():
    import time
    now = int(time.time())
    beats = {"_z": {"last_run_at": now - 60, "ok": True,
                    "n_consecutive_failures": 0, "last_ok_at": now - 60}}
    r = assess("_z", beats, expect_every_s=24 * 3600, now=now)
    _check("判 ok", r["verdict"] == OK, r["verdict"])
    _check("不判 late", r["late"] is False, str(r))

    old = {"_z": {"last_run_at": now - 3 * 24 * 3600, "ok": True,
                  "n_consecutive_failures": 0}}
    r2 = assess("_z", old, expect_every_s=24 * 3600, now=now)
    _check("超过预期间隔两倍 → late", r2["late"] is True, str(r2))
    _check("late 仍是 ok 而不是 failing(两个维度)", r2["verdict"] == OK)


def t_overall_reports_failing_and_never_ran_not_a_healthy_count():
    import time
    now = int(time.time())
    beats = {
        "_good": {"last_run_at": now, "ok": True, "n_consecutive_failures": 0},
        "_bad": {"last_run_at": now, "ok": False, "n_consecutive_failures": 9,
                 "last_error": "x"},
    }
    o = overall(beats, expected={"_good": 3600, "_bad": 3600, "_missing": 3600})
    _check("总裁决 failing", o["verdict"] == "failing", o["verdict"])
    _check("失败的被点名", o["failing"][0]["loop"] == "_bad", str(o["failing"]))
    _check("从没跑过的也被点名", o["never_ran"] == ["_missing"], str(o["never_ran"]))
    _check("理由带上 123 天那个案例", "123" in o["reason"], o["reason"][-60:])

    clean = overall({"_a": {"last_run_at": now, "ok": True,
                            "n_consecutive_failures": 0}})
    _check("全健康 → ok(不是永远报警)", clean["verdict"] == OK, clean["verdict"])


def t_ttl_lets_a_dead_loop_disappear_which_is_the_signal():
    _check(f"TTL {BEAT_TTL_S}s ≥ 最长循环间隔(24h)的两倍",
           BEAT_TTL_S >= 2 * 24 * 3600, str(BEAT_TTL_S))
    _check("但不至于长到看不出死亡(≤7 天)", BEAT_TTL_S <= 7 * 24 * 3600)


def t_loops_without_a_beat_is_shrink_only():
    """**不逼一次改 28 个,但不许新增。**"""
    src = (ROOT / "src/api/main.py").read_text()
    real = {n for n in re.findall(r'async def (_\w*loop\w*)\(', src)
            if not n.startswith("_start_")}
    beat = set(re.findall(r'_beat\("(\w+)"', src))
    n = len(real - beat)
    _check(f"未接心跳 {n} ≤ 预算 {NO_BEAT_BUDGET}(只减不增)",
           n <= NO_BEAT_BUDGET,
           f"新增了 {n - NO_BEAT_BUDGET} 个无心跳循环")
    if n < NO_BEAT_BUDGET:
        print(f"      ↓ 已降到 {n},把 NO_BEAT_BUDGET 调到 {n} 锁住成果")
    _check("已接心跳的至少覆盖全部 NAV 写入者",
           {"_beta_core_loop", "_causal_paper_loop", "_combined_book_loop",
            "_scalable_book_loop", "_two_layer_paper_loop", "_fusion_paper_loop",
            "_pod_aggregator_loop", "_factor_tilt_loop",
            "_dingge_paper_loop"} <= beat,
           str(sorted(beat)))


def t_a_correct_refusal_is_not_a_failure():
    """**心跳上线第一天的误报 (S-294)。**

    `_deep_panel_loop` 被记成 failing,而它的错误原文是
    `Write REFUSED so the gap stays visible` —— **那是地板守卫在正确工作**
    (S-245)。`deep_panel_collector` 自己早就返回 `refused: True`,
    **是心跳这一层把它折叠进了 ok=False** —— 我刚建的那层犯了本周同一个错。
    """
    import time
    now = int(time.time())
    ref = {"_deep": {"last_run_at": now, "ok": True, "refused": True,
                     "n_consecutive_refusals": 7,
                     "last_refusal": "only 1/3 symbols (33%) — Write REFUSED"}}
    r = assess("_deep", ref)
    _check("判 refused 而不是 failing", r["verdict"] == REFUSED, r["verdict"])
    _check("连续拒绝轮数被带出", r["n_consecutive_refusals"] == 7,
           str(r.get("n_consecutive_refusals")))
    _check("理由说明循环没坏", "循环没坏" in r["reason"], r["reason"][:70])
    _check("但也说明连续拒绝不是健康", "不是健康" in r["reason"], r["reason"][-40:])

    fail = {"_x": {"last_run_at": now, "ok": False, "refused": False,
                   "n_consecutive_failures": 5, "last_error": "ImportError"}}
    _check("真故障仍判 failing", assess("_x", fail)["verdict"] == FAILING)
    _check("两者可分(这就是第三个状态的全部作用)",
           assess("_deep", ref)["verdict"] != assess("_x", fail)["verdict"])

    o = overall({**ref, **fail})
    _check("总裁决只被真故障拉红", o["verdict"] == "failing", o["verdict"])
    _check("拒绝单列,不混进 failing", o["n_refusing"] == 1 and o["n_failing"] == 1,
           f"refusing={o.get('n_refusing')} failing={o.get('n_failing')}")
    _check("只有拒绝时总裁决不是 failing",
           overall(ref)["verdict"] != "failing", overall(ref)["verdict"])


def t_a_stale_build_failure_is_not_a_persisting_failure():
    """**S-295。** 这些循环大多 24 小时一轮。

    一个修复上线后,心跳条目仍带着**旧构建**记下的那次失败,而 TTL 是 3 天 ——
    足够让人反复误读三次。实际发生过:`_pod_aggregator_loop` 的 R62_Z 修复
    推上去之后,读到的仍是同一条 ImportError,**分不清是没修好还是没轮到它跑**。

    > **「修了还在失败」和「修完之后还没再跑过」是两个状态。**
    """
    import os
    import time
    os.environ["GIT_COMMIT_SHA"] = "newbuild123"
    now = int(time.time())
    old = {"_x": {"last_run_at": now, "ok": False, "n_consecutive_failures": 5,
                  "last_error": "ImportError", "build": "oldbuild"}}
    cur = {"_y": {"last_run_at": now, "ok": False, "n_consecutive_failures": 2,
                  "last_error": "real", "build": build_sha()}}
    a, b = assess("_x", old), assess("_y", cur)
    _check("旧构建记的 → stale_build True", a["stale_build"] is True, str(a))
    _check("当前构建记的 → stale_build False", b["stale_build"] is False, str(b))
    _check("两者可分(这就是这个字段的全部作用)",
           a["stale_build"] != b["stale_build"])
    _check("理由点破「还没轮到它」", "还没轮到它" in a["reason"], a["reason"][-60:])
    _check("而当前构建那条不带这句", "还没轮到它" not in b["reason"])

    o = overall({**old, **cur})
    _check("面板层单独数出旧构建的失败",
           o["n_failing_on_stale_build"] == 1, str(o.get("n_failing_on_stale_build")))
    _check("但它们仍计入 n_failing(不是被藏起来)", o["n_failing"] == 2,
           str(o["n_failing"]))

    # 判别性:缺 sha 时不能假装知道
    no_sha = {"_z": {"last_run_at": now, "ok": False,
                     "n_consecutive_failures": 1, "last_error": "e"}}
    _check("没有 build 字段 → 不判 stale(未知不伪装成确定)",
           assess("_z", no_sha)["stale_build"] is False)
    os.environ.pop("GIT_COMMIT_SHA", None)


def t_the_wrapper_signature_matches_the_callee():
    """**S-294 的第二个错,也是这个文件之前漏掉的那一半。**

    我给 `loop_beat.beat()` 和调用点都加了 `refused`,**唯独漏了中间那层
    薄包装 `main._beat`** —— 线上立刻报
    `_beat() got an unexpected keyword argument 'refused'`。

    而当时的守卫只检查**调用点里有没有 `refused=` 这个字符串**,
    从没真的调用过 `_beat`。**一个只看调用方、不看被调方的守卫,
    作用域小于问题** —— 而它恰恰是我用来修那个形状的守卫。

    所以这条**真的调它**,并逐字比对两个签名。
    """
    import asyncio as _a
    import inspect

    from src.api import main as _m
    from src.api.loop_beat import beat as _beat_impl

    wrapper = set(inspect.signature(_m._beat).parameters)
    callee = set(inspect.signature(_beat_impl).parameters)
    # `detail` 是 beat 的可选扩展,包装不转发它是有意的
    missing = callee - wrapper - {"detail"}
    _check("包装转发了被调方的每个关键字", not missing,
           f"缺 {sorted(missing)} —— 线上会 TypeError,而字符串检查看不出来")

    # **真的调一次。** 上面那条比对若哪天被绕过,这条仍会炸。
    try:
        _a.run(_m._beat("_guard_smoke", ok=True, refused=True, error="x"))
        ok = True
    except TypeError as e:
        ok, err = False, str(e)
    _check("用三个关键字实调 _beat 不抛 TypeError", ok,
           err if not ok else "")


#: 循环名 → 它调用的采集器模块。**这张表说的是「谁供数」,不是「谁会拒绝」** ——
#: 后者由采集器源码回答,见下。
_LOOP_COLLECTOR = {
    "_deep_panel_loop": "src/data/market/deep_panel_collector.py",
    "_hyperliquid_loop": "src/data/market/hyperliquid_collector.py",
}


def _fn_source(path, name: str) -> str:
    """模块里某个函数的源码。**粒度必须是函数,不是模块。**

    ⚠️ 这条本身踩过一次(2026-09-05):第一版按**模块**判「会不会 refused」,
    于是 `hyperliquid_collector.py` 判为「会」—— 因为
    `collect_hyperliquid`(成交集蜡烛,带覆盖率地板)确实会。
    但循环调的是 `collect_venue_marks`,它一次请求、没有地板、永远不 refuse。

    **一个模块里两个函数,一个有地板一个没有,在模块粒度上完全同形。**
    又是本周那个形状 —— 而这次是我为了修那个形状而写的守卫自己犯的。
    """
    import ast as _ast
    src = path.read_text(encoding="utf-8")
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return ""
    for n in _ast.walk(tree):
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == name:
            return _ast.get_source_segment(src, n) or ""
    return ""


def _collector_called_by(main_src: str, loop: str) -> str:
    """循环体里被调用的那个采集器函数名。**从代码读,不从清单读。**"""
    import ast as _ast
    try:
        tree = _ast.parse(main_src)
    except SyntaxError:
        return ""
    fn = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.AsyncFunctionDef) and n.name == loop), None)
    if fn is None:
        return ""
    # 循环体里 `from ... import X` 的 X,就是它的采集器。
    for n in _ast.walk(fn):
        if isinstance(n, _ast.ImportFrom) and "collector" in (n.module or ""):
            return n.names[0].name
    return ""


def t_refused_is_forwarded_iff_the_collector_can_refuse():
    """`refused=` 该不该传,由**采集器会不会返回它**决定,不由一张手写清单决定 (S-298).

    ## 这条守卫自己错过一次

    原文把 `_hyperliquid_loop` 硬编码进「必须传 refused」的清单里 ——
    而那张清单是 S-294 我**把它接错的那一天**写下的。当天 HL 的失败是
    `SourcePolicyError`(源选错了,设计错误),不是覆盖率拒绝;
    我按「采集器返回 refused」接了上去,顺手把这个错误写进了守卫。

    于是 S-296 把接法改对之后,**守卫红了,而红的是对的那一边**。

    > **一张手写的「应该如此」清单,会把写它那天的错误固化成规范。**
    > 清单不会随代码漂移,它让代码不敢漂回正确。

    ## 两个方向都要判

    - 采集器**会**返回 `refused` 而调用点不传 → 拒绝被记成故障,告警常亮
    - 采集器**不会**返回 而调用点传了 → **设计错误被伪装成「正确的拒绝」**,
      告警常绿。S-294 就是这一种,而它比前一种危险:
      前者吵得没道理,后者安静得没道理。

    ⚠️ **这一条只看调用方。** 被调方由
    `t_the_wrapper_signature_matches_the_callee` 覆盖 ——
    两条缺一不可,而 S-294 的线上 TypeError 正是只有前者时漏掉的。
    """
    import pathlib as _pl

    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    for name, mod in _LOOP_COLLECTOR.items():
        called = _collector_called_by(main, name)
        _check(f"{name} 的采集器可从代码解析出来", bool(called),
               "循环体里找不到 `from ...collector import X` —— "
               "解析不出来就只能回到手写清单,而清单会固化写它那天的错误")
        if not called:
            continue
        # 采集器有没有一条**返回 refused 为真**的路径。**判这个函数,不判整个模块** ——
        # 同一个文件里 `collect_hyperliquid` 有地板、`collect_venue_marks` 没有。
        body = _fn_source(ROOT / mod, called)
        can_refuse = '"refused": True' in body
        i = main.find(f'_beat("{name}"')
        _check(f"{name} 的心跳调用点存在", i > 0)
        if i <= 0:
            continue
        seg = main[i:i + 300]
        forwards = "refused=" in seg
        _check(f"{name} → {called}() 的 refused 接法一致",
               forwards == can_refuse,
               (f"采集器会返回 refused 但调用点没传 —— 正确的拒绝会被记成故障"
                if can_refuse else
                f"采集器**不会**返回 refused,调用点却传了 —— "
                f"真故障会被记成「正确地拒绝写」,告警常绿(S-294 原样)")
               + f" :: {seg[:110]}")


#: 写死 `ok=True` 的心跳调用点。**只减不增,现在是 0。**
HARDCODED_OK_BUDGET = 0


def t_no_loop_reports_ok_without_looking_at_its_own_result():
    """**架构核对的头条 (S-299)。** 14 个循环里 11 个写死 `ok=True`。

    只要采集函数没抛异常,心跳就报健康 —— 它从不看返回值。
    实测的四条假绿灯(2026-09-05):

        _outcome_tracker_loop   ok   signal_outcomes      停 125 天
        _factor_tilt_loop       ok   factor_tilt_nav      0 行
        _pod_aggregator_loop    ok   pod_aggregator_nav   0 行
        _two_layer_paper_loop   ok   two_layer_paper_nav  停 14 天

    9 本纸面账里 4 本的表是空的或陈旧的,而面板写着「12/14 健康」。

    > **「循环成功」和「工作完成」是两个状态,而心跳只测了第一个。**

    这是 Jazz 反复问的那句话的机器可读版本 ——
    「怎么都说健康,都说没问题,但就是没有做完?」
    """
    import ast as _ast
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    hard = []
    for n in _ast.walk(_ast.parse(src)):
        if not isinstance(n, _ast.Call):
            continue
        f = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if f != "_beat" or not n.args:
            continue
        kw = {k.arg: k.value for k in n.keywords}
        ok = kw.get("ok")
        if isinstance(ok, _ast.Constant) and ok.value is True:
            hard.append(getattr(n.args[0], "value", "?"))
    _check(f"写死 ok=True 的调用点 {len(hard)} ≤ 预算 {HARDCODED_OK_BUDGET}(只减不增)",
           len(hard) <= HARDCODED_OK_BUDGET,
           f"新增了 {sorted(set(hard))} —— **一个不看返回值的心跳,"
           f"报的是「我没崩」不是「我干完了」**")


def t_no_loop_can_be_outrun_by_the_deploy_cadence():
    """启动延迟必须封顶 (S-305)。

    **部署重置每个循环的启动计时器**,而我们一小时部署好几次。
    2026-09-05 实测:41 个循环里 20 个启动延迟 ≥ 600 秒,
    `_age_sweep_loop` 睡整整一小时 —— **在这个部署节奏下它永远不跑**。

    整晚四次「还没在当前构建下跑过」都是它,而它读起来像「循环坏了」:
    **又是两个状态一个表象。**

    判据是构造:第一条 sleep 必须走 `_boot_delay()`,不能是裸常数。
    裸常数会随时间被人调大,而封顶函数不会。
    """
    import ast as _ast
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    bare = []
    for n in _ast.walk(tree):
        if not (isinstance(n, _ast.AsyncFunctionDef) and n.name.endswith("_loop")):
            continue
        for st in n.body[:3]:
            hit = False
            for c in _ast.walk(st):
                if (isinstance(c, _ast.Call)
                        and getattr(c.func, "attr", None) == "sleep" and c.args):
                    a = c.args[0]
                    if isinstance(a, _ast.Constant) and isinstance(a.value, (int, float)):
                        if a.value > 300:
                            bare.append(f"{n.name}({a.value}s)")
                    hit = True
                    break
            if hit:
                break
    _check("没有循环的启动延迟是裸常数且 > 300s", not bare,
           f"{bare} —— 走 _boot_delay() 封顶。**部署比它睡得勤,它就永远不跑**")
    from src.api.main import _BOOT_DELAY_CAP_S, _boot_delay
    _check(f"封顶 {_BOOT_DELAY_CAP_S}s 且保序",
           _boot_delay(3600) > _boot_delay(900) > _boot_delay(120)
           and _boot_delay(3600) <= _BOOT_DELAY_CAP_S + 60,
           f"3600→{_boot_delay(3600):.0f} 900→{_boot_delay(900):.0f} "
           f"120→{_boot_delay(120):.0f}")


def t_classify_separates_progress_from_no_work_from_broken():
    """`classify` 是三值的,而且**未知不判健康**。"""
    from src.api.loop_beat import classify
    for st in ("marked", "already_marked", "ok", "inception"):
        _check(f"'{st}' → 进展", classify({"status": st}) == (True, False, None))
    for st in ("skipped", "no_data", "warming_up"):
        ok, ref, why = classify({"status": st})
        _check(f"'{st}' → 拒绝(不是故障,但也不是进展)",
               (ok, ref) == (False, True) and st in (why or ""), str((ok, ref, why)))
    ok, ref, why = classify({"status": "error", "error": "boom"})
    _check("'error' → 故障", (ok, ref) == (False, False) and "boom" in why, why or "")
    ok, ref, why = classify({"status": "brand_new_thing"})
    _check("未知 status → 故障,不是健康", (ok, ref) == (False, False), str((ok, ref)))
    _check("并说明未知为什么不能判健康", "未知不是健康" in (why or ""), why or "")
    # `already_marked` 是进展 —— **今天的行存在是目的本身**,
    # 把它判成「没干活」会让一个已完成的账每天报拒绝。
    _check("already_marked 不被误判成没干活",
           classify({"status": "already_marked"})[1] is False)


def t_the_beat_never_breaks_the_business_loop():
    """一个为了记录健康而弄死循环的记录器,比没有记录器更糟。"""
    src = (ROOT / "src/api/loop_beat.py").read_text()
    _check("beat() 吞掉自己的异常", "except Exception:" in src)
    _check("并写明理由", "比没有记录器更糟" in src)
    # ⚠️ 原本这条切 400 个字符找 `pass` —— 而我给 `_beat` 补了一段 docstring
    # 之后,`pass` 被挤出窗口,守卫就红了。**固定字符窗口的断言会被文档增长
    # 弄坏**,它测的是「排版」不是「行为」。改成解析真实函数体。
    import ast as _ast

    tree = _ast.parse((ROOT / "src/api/main.py").read_text(encoding="utf-8"))
    fn = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_beat"), None)
    _check("main 里有 _beat", fn is not None)
    if fn:
        handlers = [h for n in _ast.walk(fn) if isinstance(n, _ast.Try)
                    for h in n.handlers]
        swallows = any(all(isinstance(st, _ast.Pass) for st in h.body)
                       for h in handlers)
        _check("main 的 _beat 包装也吞异常(AST 判定,不看排版)", swallows,
               f"{len(handlers)} 个 except,没有一个是纯 pass")


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
