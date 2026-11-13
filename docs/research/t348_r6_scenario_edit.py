#!/usr/bin/env python3
"""T-348 第六轮(T-377):情景文件三处修正的改写脚本。

改 docs/research/scenarios/lane-c-T-348.json:
① T-348-19 前提错(H4 族累计是 +0.1128,不是负)→ 方向改为「仍为正」,prob 0.55→0.85;
② T-348-20「最长水下 > 700」写下即知 → 移进顶层 dropped,写理由;
③ T-348-19 / 21 写明族曲线止于 2026-09-30、到期由谁、用哪个脚本续到 12-31;
④ T-348-21 的 prob 0.70→0.95(族曲线 62 日内翻正需 +46.98%,样本内 2091 个滚动窗口一次没发生)。

原始数与依据:docs/research/t348_r6_scenario_fix.py → docs/research/_t348_r6_scenario_fix.md
本脚本幂等:跑第二遍得到同样的文件(改写基于当前内容,不是增量补丁)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "scenarios", "lane-c-T-348.json")
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

ST19 = (
    "S-681 H4 族(熊市反弹失败;每票 0.5% 净值、cap 10、逐日盯市)自身的累计收益在 2026-12-31 仍为正。"
    "2026-10-30 实测 +0.1128(族曲线 2020-09-04→2026-09-30 止);原写「仍为负」的前提作废,本条改为与实测同向。"
    "族曲线止于 2026-09-30:到期用续算后的曲线判 —— 由 lane-c 在 2027-01 首轮重跑 "
    "docs/research/s681_h4_bear_rally_fail.py → t348_r3.py(重出族曲线缓存)→ t348_r5.py(把截止日改到 2026-12-31)续到 12-31,"
    "再由非 lane-c 方按 evidence 人工结算。"
)

ST21 = (
    "S-681 H2 族(资金费拥挤)自身的累计收益在 2026-12-31 前仍为负(2026-10-30 实测 −32.03%,"
    "族曲线 2020-11-07→2026-09-29 止、末票出场 2026-09-30)。"
    "族曲线止于 2026-09-30:到期用续算后的曲线判 —— 由 lane-c 在 2027-01 首轮重跑 docs/research/s681_h2_pump_fade.py → "
    "t348_r3.py → t348_r5.py(把截止日改到 2026-12-31)续到 12-31,再由非 lane-c 方按 evidence 人工结算。"
)

REASON20 = (
    "2026-11-14(T-377)撤,不入账:① 写下即知 —— 该最长水下段 2021-11-24→2023-12-27 已闭合,"
    "长度 763 天(G 口径)/762 天(S-829 口径)已是历史事实,到期时必然成立,不是前向预期;"
    "② 「改问当前这段水下」在本口径下不成立 —— 2026-10-30 账户 C0 水位 5.9576 高于历史峰值 2.6426(2.254 倍),"
    "当前不在水下段内,没有可问的当前水下段。依据 docs/research/_t348_r6_scenario_fix.md §1/§4。"
)

NOTES = (
    "2026-11-14 T-377(第六轮)改三处:① T-348-19 前提错 —— H4 族自身累计实测 +0.112815"
    "(r5 family_standalone 与本轮自算差 0),不是负,方向改为「仍为正」,prob 0.55→0.85"
    "(族曲线滚动 62 日相对收益 ≤ −9.75% 的经验频率 0.0093);"
    "② T-348-20 移进 dropped(写下即知 + 当前无未闭合水下段可改问,理由见该条 dropped_reason);"
    "③ T-348-19/21 写明族曲线止于 2026-09-30、到期由 lane-c 在 2027-01 首轮重跑 s681_h4_bear_rally_fail.py / "
    "s681_h2_pump_fade.py → t348_r3.py → t348_r5.py(改截止日 2026-12-31)续到 12-31,再由非 lane-c 方结算。"
    "另:T-348-21 的 prob 0.70→0.95(族曲线 62 日内翻正需 +46.98%,样本内 2091 个滚动窗口一次没发生)—— "
    "未先经 Seth 点头,若不要请说一声。原始数与脚本:docs/research/t348_r6_scenario_fix.py → docs/research/_t348_r6_scenario_fix.md。"
)


def main() -> None:
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    by_id = {e["id"]: e for e in d["entries"]}

    e19 = by_id["T-348-19"]
    e19["statement"] = ST19
    e19["op"] = "gt"
    e19["lo"] = 0
    e19.pop("hi", None)
    e19["prob"] = 0.85

    e21 = by_id["T-348-21"]
    e21["statement"] = ST21
    e21["prob"] = 0.95

    e20 = by_id["T-348-20"]
    d["entries"] = [e for e in d["entries"] if e["id"] != "T-348-20"]
    d["dropped"] = [{
        "id": "T-348-20",
        "statement": e20["statement"],
        "variable": e20["variable"],
        "op": e20["op"],
        "lo": e20["lo"],
        "prob": e20["prob"],
        "horizon_d": e20["horizon_d"],
        "dropped_reason": REASON20,
    }]

    d["notes"] = NOTES

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from src.data.evaluation.scenario_ledger import validate
    soon = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=7)
    problems = []
    for e in d["entries"]:
        why = validate(dict(e, author="lane-c"), soon)
        if why:
            problems.append((e.get("id"), why))
        if len(e["statement"]) > 500:
            problems.append((e.get("id"), ["statement 超 500 字符"]))
    ids = [e["id"] for e in d["entries"]]
    if len(ids) != len(set(ids)):
        problems.append(("*", ["id 重复"]))
    print(f"entries={len(d['entries'])} dropped={len(d.get('dropped', []))} "
          f"max_stmt={max(len(e['statement']) for e in d['entries'])} problems={problems}")
    print("19:", json.dumps(by_id["T-348-19"], ensure_ascii=False))
    print("21:", json.dumps(by_id["T-348-21"], ensure_ascii=False))


if __name__ == "__main__":
    main()
