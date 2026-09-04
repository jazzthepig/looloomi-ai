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
NO_BEAT_BUDGET = 28


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


def t_loops_that_can_refuse_actually_pass_the_flag():
    """采集器返回 `refused` 而调用点不传,等于没修。

    ⚠️ **这一条只看调用方。** 被调方由
    `t_the_wrapper_signature_matches_the_callee` 覆盖 ——
    两条缺一不可,而 S-294 的线上错误正是只有前者时漏掉的。
    """
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    for name in ("_deep_panel_loop", "_hyperliquid_loop"):
        i = main.find(f'_beat("{name}"')
        seg = main[i:i + 260] if i > 0 else ""
        _check(f"{name} 传了 refused", "refused=" in seg, seg[:120])
    import pathlib as _pl
    for mod in ("src/data/market/deep_panel_collector.py",
                "src/data/market/hyperliquid_collector.py"):
        body = (ROOT / mod).read_text(encoding="utf-8")
        _check(f"{_pl.Path(mod).name} 确实会返回 refused",
               '"refused": True' in body)


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
