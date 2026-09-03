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
    BEAT_TTL_S, FAILING, NEVER_RAN, OK, assess, overall,
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


def t_the_beat_never_breaks_the_business_loop():
    """一个为了记录健康而弄死循环的记录器,比没有记录器更糟。"""
    src = (ROOT / "src/api/loop_beat.py").read_text()
    _check("beat() 吞掉自己的异常", "except Exception:" in src)
    _check("并写明理由", "比没有记录器更糟" in src)
    main = (ROOT / "src/api/main.py").read_text()
    _check("main 的 _beat 包装也吞异常",
           "async def _beat(" in main and "pass" in main.split("async def _beat(")[1][:400])


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
